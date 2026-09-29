"""Book 1 foundation tests: state machine, atomic claim, cost ledger,
atomic asset intake, ffprobe probing.

Repo-root path hack matches the existing tests (no conftest.py in this repo).
"""
import hashlib
import os
import shutil
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypelab import jobs, queue, util  # noqa: E402
from hypelab.db import MigrationError, connect, migrate  # noqa: E402
from hypelab.util import IntegrityError, MediaError  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    cx = connect(tmp_path / "t.db")
    migrate(cx)
    yield cx
    cx.close()


def _mk(conn, state, title="t", **kw):
    return jobs.new(conn, mode="A", title=title, state=state, **kw)


# -- schema -----------------------------------------------------------------

EXPECTED_TABLES = {
    "jobs", "job_events", "edls", "kits", "renders", "gate_results",
    "cost_ledger", "what_worked", "campaigns", "sources", "source_items",
    "moments", "clips", "posts", "metrics", "targets", "consents",
    "invites", "slides", "schema_migrations",
}


def test_schema_has_all_tables(conn):
    have = {r["name"] for r in
            conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert EXPECTED_TABLES <= have


def test_migration_runner_applies_0001(tmp_path):
    cx = connect(tmp_path / "fresh.db")
    rows = cx.execute(
        "SELECT version, name FROM schema_migrations").fetchall()
    assert [(r["version"], r["name"]) for r in rows] == [
        (1, "0001_book1_foundation"), (2, "0002_book2_clip_mine"),
            (3, "0003_book3_hype_layer")]
    job_cols = {r[1] for r in cx.execute("PRAGMA table_info(jobs)")}
    assert {"lease_owner", "lease_expires", "attempts",
            "max_attempts"} <= job_cols
    ren_cols = {r[1] for r in cx.execute("PRAGMA table_info(renders)")}
    assert "manifest_json" in ren_cols
    mig_cols = {r[1] for r in cx.execute("PRAGMA table_info(schema_migrations)")}
    assert mig_cols == {"version", "name", "applied_at"}
    cx.close()


def test_migration_runner_is_idempotent(conn):
    before = conn.execute(
        "SELECT version, name FROM schema_migrations").fetchall()
    migrate(conn)
    after = conn.execute(
        "SELECT version, name FROM schema_migrations").fetchall()
    assert [tuple(r) for r in before] == [tuple(r) for r in after]


def test_migration_runner_refuses_on_set_mismatch(tmp_path):
    cx = connect(tmp_path / "drift.db")
    # Simulate a DB migrated by newer/foreign code: an unknown version.
    cx.execute(
        "INSERT INTO schema_migrations(version, name) VALUES(99, 'bogus')")
    with pytest.raises(MigrationError, match="mismatch"):
        migrate(cx)
    cx.close()


def test_migration_failure_rolls_back_atomically(tmp_path, monkeypatch):
    import hypelab.db as db_mod

    migdir = tmp_path / "migs"
    migdir.mkdir()
    (migdir / "0001_book1_foundation.sql").write_text(
        "CREATE TABLE ok1(id TEXT PRIMARY KEY);")
    (migdir / "0002_bad.sql").write_text(
        "CREATE TABLE ok2(id TEXT PRIMARY KEY);\nTHIS IS NOT SQL;")
    monkeypatch.setattr(db_mod, "MIGRATIONS_DIR", migdir)
    monkeypatch.setattr(db_mod, "EXPECTED_MIGRATIONS",
                        {1: "0001_book1_foundation", 2: "0002_bad"})
    cx = sqlite3.connect(tmp_path / "atomic.db", isolation_level=None)
    cx.row_factory = sqlite3.Row
    with pytest.raises(MigrationError, match="0002_bad"):
        db_mod.migrate(cx)
    tables = {r[0] for r in cx.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ok1" in tables and "ok2" not in tables  # 0002 fully rolled back
    versions = {r[0] for r in cx.execute("SELECT version FROM schema_migrations")}
    assert versions == {1}  # the failed migration was not recorded
    cx.close()


def test_pragmas_on(conn):
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
    assert conn.execute("SELECT name FROM sqlite_master WHERE name='ix_jobs_state'"
                        ).fetchone() is not None


def test_transition_graph_is_closed():
    """Every transition target is itself a known state."""
    for frm, tos in jobs.TRANSITIONS.items():
        for to in tos:
            assert to in jobs.TRANSITIONS, f"{frm} -> {to}: unknown state"


# -- state machine ----------------------------------------------------------

MODE_A_PATH = [
    "draft", "scripted", "queued_align", "aligning", "aligned",
    "queued_render", "rendering", "rendered", "queued_gates", "gating",
    "ready", "archived",
]


def test_mode_a_full_legal_walk(conn):
    jid = jobs.new(conn, mode="A", title="mode-a walk")
    for to in MODE_A_PATH[1:]:
        jobs.transition(conn, jid, to, note="walk")
    row = conn.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()
    assert row["state"] == "archived"
    n_events = conn.execute(
        "SELECT COUNT(*) FROM job_events WHERE job_id=?", (jid,)).fetchone()[0]
    assert n_events == len(MODE_A_PATH)  # creation + one event per transition
    ev = conn.execute(
        "SELECT from_state, to_state FROM job_events WHERE job_id=? ORDER BY id",
        (jid,)).fetchall()
    assert ev[0]["from_state"] is None and ev[0]["to_state"] == "draft"
    assert ev[-1]["from_state"] == "ready" and ev[-1]["to_state"] == "archived"


def test_illegal_transition_raises(conn):
    jid = jobs.new(conn, mode="A", title="x")
    with pytest.raises(ValueError, match=r"illegal transition draft -> rendering"):
        jobs.transition(conn, jid, "rendering")
    # state unchanged, no event logged for the failed attempt
    row = conn.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()
    assert row["state"] == "draft"
    n = conn.execute(
        "SELECT COUNT(*) FROM job_events WHERE job_id=?", (jid,)).fetchone()[0]
    assert n == 1  # creation only


def test_book2_ingest_score_walk(conn):
    jid = _mk(conn, "queued_ingest")
    for to in ["ingesting", "ingested", "queued_score", "scoring", "scored",
               "queued_cut", "cutting", "tray", "archived"]:
        jobs.transition(conn, jid, to)
    assert conn.execute(
        "SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()["state"] == "archived"


def test_terminal_and_recovery_edges(conn):
    jid = _mk(conn, "draft")
    jobs.transition(conn, jid, "failed")
    jobs.transition(conn, jid, "draft")  # failed -> draft recovery
    with pytest.raises(ValueError, match="illegal transition"):
        jobs.transition(conn, _mk(conn, "consent_denied"), "pitch_sent")
    with pytest.raises(ValueError, match="unknown job"):
        jobs.transition(conn, "j_deadbeefcafe", "draft")


# -- claim / leases -----------------------------------------------------------

def test_claim_hands_out_distinct_jobs_atomically(conn):
    a = _mk(conn, "queued_render", title="a")
    b = _mk(conn, "queued_render", title="b")
    r1 = queue.claim(conn, "w1")
    r2 = queue.claim(conn, "w1")
    r3 = queue.claim(conn, "w1")
    assert r1 is not None and r2 is not None
    assert r1["id"] != r2["id"]
    assert {r1["id"], r2["id"]} == {a, b}
    assert r1["state"] == "rendering" and r2["state"] == "rendering"
    assert r3 is None  # nothing left claimable


def test_claim_respects_state_priority_and_fifo(conn):
    _mk(conn, "queued_render", title="render-first")  # created earlier...
    align = _mk(conn, "queued_align", title="align-second")
    got = queue.claim(conn, "w1")
    assert got["id"] == align  # ...but queued_align outranks queued_render
    assert got["state"] == "aligning"
    got2 = queue.claim(conn, "w1")
    assert got2["state"] == "rendering"


def test_claim_fifo_within_state(conn):
    first = _mk(conn, "queued_gates", title="first")
    _mk(conn, "queued_gates", title="second")
    assert queue.claim(conn, "w1")["id"] == first


def test_claim_stamps_lease(conn):
    jid = _mk(conn, "queued_render")
    row = queue.claim(conn, "w1")
    assert row["id"] == jid
    assert row["lease_owner"] == "w1"
    assert row["lease_expires"] is not None and row["lease_expires"] > util.now()
    assert row["attempts"] == 1
    assert row["state"] == "rendering"


def test_claim_requires_owner_and_known_states(conn):
    with pytest.raises(ValueError, match="owner"):
        queue.claim(conn, "")
    with pytest.raises(ValueError, match="unknown claimable"):
        queue.claim(conn, "w1", states=["nope"])


def test_claim_skips_live_lease_held_by_other(conn):
    jid = _mk(conn, "queued_render")
    queue.claim(conn, "w1")
    assert queue.claim(conn, "w2") is None  # w1's lease is live
    row = conn.execute("SELECT lease_owner FROM jobs WHERE id=?",
                       (jid,)).fetchone()
    assert row["lease_owner"] == "w1"


def test_claim_states_subset(conn):
    _mk(conn, "queued_render", title="r")
    assert queue.claim(conn, "w1", states=["queued_gates"]) is None
    row = queue.claim(conn, "w1", states=["queued_render"])
    assert row is not None and row["state"] == "rendering"


def test_heartbeat_extends_lease(conn):
    jid = _mk(conn, "queued_render")
    first = queue.claim(conn, "w1")
    old_exp = first["lease_expires"]
    assert queue.heartbeat(conn, jid, "w1") is True
    new_exp = conn.execute("SELECT lease_expires FROM jobs WHERE id=?",
                           (jid,)).fetchone()["lease_expires"]
    assert new_exp >= old_exp
    assert queue.heartbeat(conn, jid, "w2") is False  # not the owner
    assert queue.heartbeat(conn, "j_nope", "w1") is False


def test_release_returns_job_to_queued_and_clears_lease(conn):
    jid = _mk(conn, "queued_render")
    queue.claim(conn, "w1")
    assert queue.release(conn, jid, "w1") is True
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
    assert row["state"] == "queued_render"
    assert row["lease_owner"] is None and row["lease_expires"] is None
    assert row["attempts"] == 1  # expiry/release is not a failure
    # ...and the job is claimable again
    row2 = queue.claim(conn, "w2")
    assert row2["id"] == jid and row2["lease_owner"] == "w2"


def test_release_refuses_live_lease_of_other_owner(conn):
    jid = _mk(conn, "queued_render")
    queue.claim(conn, "w1")
    assert queue.release(conn, jid, "w2") is False
    row = conn.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()
    assert row["state"] == "rendering"
    with pytest.raises(ValueError, match="unknown job"):
        queue.release(conn, "j_nope", "w1")


def test_release_reaps_expired_lease_for_anyone(conn):
    jid = _mk(conn, "queued_render")
    queue.claim(conn, "w1")
    past = "2000-01-01T00:00:00+00:00"
    conn.execute("UPDATE jobs SET lease_expires=? WHERE id=?", (past, jid))
    assert queue.release(conn, jid, "reaper") is True
    row = conn.execute("SELECT state FROM jobs WHERE id=?", (jid,)).fetchone()
    assert row["state"] == "queued_render"


def test_fail_records_error_and_clears_lease(conn):
    jid = _mk(conn, "queued_render")
    queue.claim(conn, "w1")
    row = queue.fail(conn, jid, "w1", "boom")
    assert row["state"] == "failed"
    assert row["error"] == "boom"
    assert row["lease_owner"] is None
    assert "POISON" not in conn.execute(
        "SELECT note FROM job_events WHERE job_id=? ORDER BY id DESC LIMIT 1",
        (jid,)).fetchone()["note"]  # attempts 1/3: not poison


def test_fail_requires_lease_owner(conn):
    jid = _mk(conn, "queued_render")
    queue.claim(conn, "w1")
    with pytest.raises(ValueError, match="not held by"):
        queue.fail(conn, jid, "w2", "boom")
    with pytest.raises(ValueError, match="unknown job"):
        queue.fail(conn, "j_nope", "w1", "boom")


def test_fail_marks_poison_at_max_attempts(conn):
    jid = _mk(conn, "queued_render")
    for _ in range(2):
        queue.claim(conn, "w1")
        queue.fail(conn, jid, "w1", "boom")
        # the work loop re-queues while attempts remain
        conn.execute("UPDATE jobs SET state='queued_render' WHERE id=?", (jid,))
    queue.claim(conn, "w1")  # third and final attempt
    row = queue.fail(conn, jid, "w1", "boom")
    assert row["state"] == "failed"
    assert row["attempts"] == 3
    assert row["lease_owner"] is None
    note = conn.execute(
        "SELECT note FROM job_events WHERE job_id=? AND to_state='failed'"
        " ORDER BY id DESC LIMIT 1", (jid,)).fetchone()["note"]
    assert note.startswith("POISON|") and "3/3" in note
    assert "operator review required" in note


def test_lease_expiry_reclaim_by_another_owner(conn):
    jid = _mk(conn, "queued_render")
    queue.claim(conn, "w1")
    # w1 dies mid-render: expire its lease out-of-band
    conn.execute(
        "UPDATE jobs SET lease_expires='2000-01-01T00:00:00+00:00'"
        " WHERE id=?", (jid,))
    row = queue.claim(conn, "w2")
    assert row is not None and row["id"] == jid
    assert row["lease_owner"] == "w2"
    assert row["attempts"] == 2  # expiry is not a failure, claim counts on


def test_transition_clears_lease_fields(conn):
    jid = _mk(conn, "queued_render")
    queue.claim(conn, "w1")  # rendering, lease held by w1
    jobs.transition(conn, jid, "rendered")
    row = conn.execute(
        "SELECT lease_owner, lease_expires FROM jobs WHERE id=?",
        (jid,)).fetchone()
    assert row["lease_owner"] is None and row["lease_expires"] is None


# -- cost ledger --------------------------------------------------------------

def test_charge_estimate_vs_actual(conn):
    jid = jobs.new(conn, mode="A", title="cost")
    queue.charge(conn, jid, "whisper", "audio_min", 2.0, 0.012,
                 "ESTIMATE|stt draft, 2 audio_min @ $0.006/min")
    queue.charge(conn, jid, "whisper", "audio_min", 2.0, 0.011,
                 "ACTUAL|stt billed 2026-09-28")
    rows = conn.execute(
        "SELECT provider, unit, qty, usd, note, at FROM cost_ledger"
        " WHERE job_id=? ORDER BY id", (jid,)).fetchall()
    assert len(rows) == 2
    est, act = rows
    assert est["note"].startswith("ESTIMATE|")
    assert act["note"].startswith("ACTUAL|")
    assert est["provider"] == "whisper" and est["unit"] == "audio_min"
    assert est["qty"] == pytest.approx(2.0) and est["usd"] == pytest.approx(0.012)
    assert act["usd"] == pytest.approx(0.011)
    assert est["at"] and act["at"]  # timestamps present
    total = conn.execute(
        "SELECT SUM(usd) FROM cost_ledger WHERE job_id=? AND note LIKE 'ACTUAL|%'",
        (jid,)).fetchone()[0]
    assert total == pytest.approx(0.011)


# -- intake_asset --------------------------------------------------------------

def test_intake_asset_roundtrip(tmp_path):
    src = tmp_path / "src.bin"
    data = os.urandom(65536) + b"hello-hypelab"
    src.write_bytes(data)
    dst = tmp_path / "assets"
    got = util.intake_asset(src, dst, "asset.bin")
    assert got["path"] == str(dst / "asset.bin")
    assert got["sha256"] == hashlib.sha256(data).hexdigest()
    assert got["bytes"] == len(data)
    assert Path(got["path"]).read_bytes() == data
    assert src.read_bytes() == data  # source untouched
    assert list(dst.glob(".tmp.*")) == []  # no temp litter


def test_intake_asset_src_mutation_raises(tmp_path, monkeypatch):
    src = tmp_path / "src.bin"
    src.write_bytes(b"A" * 4096)
    real_copy = shutil.copyfileobj

    def evil(fin, fout, length=16384):
        # mutate the source mid-copy, then perform the real copy
        with open(src, "ab") as f:
            f.write(b"MUTATED-MID-COPY")
        return real_copy(fin, fout, length=length)

    monkeypatch.setattr("hypelab.util.shutil.copyfileobj", evil)
    with pytest.raises(IntegrityError):
        util.intake_asset(src, tmp_path / "assets", "asset.bin")
    assert list((tmp_path / "assets").glob(".tmp.*")) == []  # temp cleaned up


def test_intake_asset_missing_src_raises(tmp_path):
    with pytest.raises(MediaError):
        util.intake_asset(tmp_path / "nope.bin", tmp_path / "assets", "x.bin")


# -- ffprobe -------------------------------------------------------------------

@pytest.fixture(scope="module")
def sample_mp4(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    p = d / "sample.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error",
         "-f", "lavfi", "-i", "testsrc=duration=1:size=64x64:rate=30",
         "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", "-shortest", str(p)],
        check=True, timeout=120,
    )
    return p


def test_ffprobe_real_mp4(sample_mp4):
    info = util.ffprobe(sample_mp4)
    assert set(info) == {"duration_s", "width", "height", "fps", "pix_fmt",
                         "sar", "has_audio", "nb_frames"}
    assert info["width"] == 64 and info["height"] == 64
    assert info["fps"] == pytest.approx(30.0, rel=0.02)
    assert info["duration_s"] == pytest.approx(1.0, abs=0.2)
    assert info["has_audio"] is True
    assert info["pix_fmt"] == "yuv420p"
    assert info["sar"] == "1:1"
    assert info["nb_frames"] is None or info["nb_frames"] >= 25


def test_ffprobe_truncated_raises(sample_mp4, tmp_path):
    bad = tmp_path / "trunc.mp4"
    bad.write_bytes(sample_mp4.read_bytes()[:64])  # header stub, no moov
    with pytest.raises(MediaError):
        util.ffprobe(bad)


def test_ffprobe_no_video_stream_raises(tmp_path):
    p = tmp_path / "note.txt"
    p.write_text("not a video at all")
    with pytest.raises(MediaError):
        util.ffprobe(p)


def test_ffprobe_missing_file_raises(tmp_path):
    with pytest.raises(MediaError):
        util.ffprobe(tmp_path / "nope.mp4")


# -- misc helpers ---------------------------------------------------------------

def test_now_and_new_id():
    assert "T" in util.now()
    nid = util.new_id()
    assert nid.startswith("j_") and len(nid) == len("j_") + 12
    assert util.new_id("clip").startswith("clip_")
    assert len({util.new_id() for _ in range(200)}) == 200


def test_db_to_lin():
    assert util.db_to_lin(0.0) == pytest.approx(1.0)
    assert util.db_to_lin(-3.0) == pytest.approx(0.501187, rel=1e-4)
    assert util.db_to_lin(10.0) == pytest.approx(10.0)


def test_write_read_json_roundtrip_atomic(tmp_path):
    p = tmp_path / "sub" / "doc.json"
    util.write_json(p, {"b": [1, 2], "a": "x"})
    assert util.read_json(p) == {"b": [1, 2], "a": "x"}
    assert list((tmp_path / "sub").glob(".tmp.*")) == []


def test_work_dir(tmp_path):
    d = util.work_dir("j_abc123", root=str(tmp_path))
    assert d == tmp_path / "work" / "j_abc123"
    assert d.is_dir()
    assert util.work_dir("j_abc123", root=str(tmp_path)) == d  # idempotent


def test_fk_cascade_enforced(conn):
    jid = jobs.new(conn, mode="A", title="cascade")
    conn.execute(
        "INSERT INTO gate_results(job_id, gate, passed, at) VALUES(?,?,?,?)",
        (jid, "g1", 1, util.now()))
    conn.execute("DELETE FROM jobs WHERE id=?", (jid,))
    n = conn.execute("SELECT COUNT(*) FROM gate_results").fetchone()[0]
    assert n == 0
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO gate_results(job_id, gate, passed, at)"
            " VALUES('j_nope','g',1,?)", (util.now(),))
