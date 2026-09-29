"""Book 3 (Hype Layer) tests.

Local only: recorded fixtures, dry-run adapter, headless Chromium for the
carousel renderer. No network, no provider calls, no external side effects.

Every gate is tested broken once, then fixed. Every refusal path is a
fail-closed refusal (no override flag exists anywhere in the code).
"""
import copy
import csv
import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import authorize as authorize_mod  # noqa: E402
from hypelab import carousel as carousel_mod  # noqa: E402
from hypelab import consent as consent_mod  # noqa: E402
from hypelab import feedback as feedback_mod  # noqa: E402
from hypelab import invites as invites_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402
from hypelab import pitch as pitch_mod  # noqa: E402
from hypelab import publish as publish_mod  # noqa: E402
from hypelab.db import connect  # noqa: E402
from hypelab.publish.base import (  # noqa: E402
    LiveRefused,
    PublishError,
    check_collaborator_cap,
)
from hypelab.state_migrations import (  # noqa: E402
    STATE_MIGRATIONS,
    apply_state_migrations,
)

FIXTURES = REPO / "tests" / "fixtures_book3"
SLIDES_FIXTURE = json.loads((FIXTURES / "slides_fixture.json").read_text())

KIT = {"captions": {"fill": "#FFFFFF", "highlight": "#39FF88",
                    "font": "DejaVu Sans"}}


@pytest.fixture()
def conn(tmp_path):
    cx = connect(tmp_path / "b3.db")
    yield cx
    cx.close()


def _job(conn, state="ready", mode="carousel", title="b3 test"):
    jid = jobs_mod.new(conn, mode=mode, title=title, state=state)
    conn.commit()
    return jid


def _target(conn, handle="@somecreator", platform="instagram",
            is_public=1):
    conn.execute(
        """INSERT INTO targets(handle, platform, is_public,
                               is_public_checked_at, consent_state)
           VALUES(?,?,?,?, 'none')
           ON CONFLICT(handle, platform) DO UPDATE SET
             is_public=excluded.is_public,
             is_public_checked_at=excluded.is_public_checked_at""",
        (handle, platform, is_public, "2026-09-28T00:00:00+00:00"),
    )
    conn.commit()


def _media(tmp_path, name="a.bin", data=b"fake-media-bytes"):
    p = tmp_path / name
    p.write_bytes(data)
    return str(p)


def _grant(conn, job_id, handle, media_path, tmp_path,
           expires_at="2030-01-01T00:00:00+00:00"):
    return consent_mod.grant(
        conn, job_id=job_id, handle=handle, platform="instagram",
        actor="@creator via DM", account_id="ig:" + handle.lstrip("@"),
        scope="one Instagram collab post, your handle as co-author, 30-day window",
        artifact_path=media_path, expires_at=expires_at,
        jurisdiction="US-OH", terms_version="pitch.md v1")


def _grant_agreement(conn, job_id, handle, tmp_path, **kw):
    """Grant consent on a normal agreement artifact (e.g. a DM screenshot).

    The artifact is evidence of the creator's agreement — it is NOT a copy
    of the media set. The consent gate keys on (job, handle), not on media
    bytes; scoping to content lives in the verbatim scope text.
    """
    art = tmp_path / "agreement.txt"
    art.write_text(f"agreement from {handle}: one collab post, 30-day window")
    return _grant(conn, job_id, handle, str(art), tmp_path, **kw)


def _authorize(conn, job_id, action):
    return authorize_mod.record(conn, job_id, action, actor="dino",
                                intent=f"test: {action}")


# ------------------------------------------------------------------ migration

def test_migration_0003_applies(conn):
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    for t in ("authorizations", "slides", "post_placements",
              "pitch_attempts", "feedback_runs", "priors"):
        assert t in tables, f"missing table {t}"
    cols = {r[1] for r in conn.execute("PRAGMA table_info(consents)")}
    for c in ("actor", "account_id", "artifact_hash", "artifact_path",
              "revoked_at", "revoked_by", "revocation_note", "jurisdiction",
              "terms_version", "recorded_at"):
        assert c in cols, f"consents missing column {c}"
    tcols = {r[1] for r in conn.execute("PRAGMA table_info(targets)")}
    assert "is_public_checked_at" in tcols
    assert "corpus_consent_at" in tcols
    applied = dict(conn.execute(
        "SELECT version, name FROM schema_migrations").fetchall())
    assert applied[3] == "0003_book3_hype_layer"


# ------------------------------------------------------------------ state machine

def test_state_migration_is_additive():
    merged = apply_state_migrations(jobs_mod.ALLOWED, [])
    # Book 1 transitions survive the merge untouched.
    assert "archived" in merged["ready"]
    assert merged["draft"] == jobs_mod.ALLOWED["draft"]
    # Book 3 additions present.
    assert "pitch_sent" in merged["ready"]
    assert "dry_run" in merged["ready"]
    assert merged["consent_denied"] == ()
    assert "published" in merged["scheduled"]


def test_state_migration_refuses_removal():
    base = {"ready": ("archived", "scheduled")}
    bad = [("9.9", {"ready": ("scheduled",)})]  # drops "archived"
    with pytest.raises(AssertionError, match="removed transitions"):
        apply_state_migrations(base, bad)


def test_book3_job_lifecycle(conn):
    jid = _job(conn)
    jobs_mod.transition(conn, jid, "dry_run", "fixture check")
    jobs_mod.transition(conn, jid, "ready")
    assert jobs_mod.get(conn, jid)["state"] == "ready"
    with pytest.raises(ValueError, match="illegal transition"):
        jobs_mod.transition(conn, jid, "published")  # ready -> published illegal


# ------------------------------------------------------------------ carousel gates

def _broken_spec(kind):
    spec = copy.deepcopy(SLIDES_FIXTURE)
    if kind == "words":
        spec["slides"][1]["caption"] = " ".join(f"word{i}" for i in range(30))
    elif kind == "chars":
        spec["slides"][2]["title"] = "x" * 41
    elif kind == "hook":
        spec["slides"][0]["title"] = " ".join(f"word{i}" for i in range(15))
    elif kind == "nohook":
        spec["slides"][0]["title"] = ""
    return spec


def test_text_overflow_gate_broken_then_fixed():
    ok, detail = carousel_mod.gate_text_overflow(_broken_spec("words"), KIT)
    assert not ok and "words" in detail
    ok, detail = carousel_mod.gate_text_overflow(_broken_spec("chars"), KIT)
    assert not ok and "char" in detail
    # Passes the word/char/line rules but overflows its box in the browser:
    # 35 unbreakable chars at 92px cannot fit the content box.
    bad_slide = dict(SLIDES_FIXTURE["slides"][0])
    bad_slide["title"] = "Supercalifragilisticexpialidociousab"
    assert len(bad_slide["title"]) <= 40
    bad = {"slides": [bad_slide]}
    ok, detail = carousel_mod.gate_text_overflow(bad, KIT)
    assert not ok and ("overflow" in detail or "margin" in detail)
    ok, detail = carousel_mod.gate_text_overflow(SLIDES_FIXTURE, KIT)
    assert ok, detail


def test_slide_one_hook_gate_broken_then_fixed():
    ok, detail = carousel_mod.gate_slide_one_hook(_broken_spec("hook"))
    assert not ok and "12" in detail
    ok, detail = carousel_mod.gate_slide_one_hook(_broken_spec("nohook"))
    assert not ok and "no hook" in detail
    ok, detail = carousel_mod.gate_slide_one_hook(SLIDES_FIXTURE)
    assert ok, detail


def test_carousel_render_7_slides_1080x1350(conn, tmp_path):
    jid = _job(conn)
    out = tmp_path / "carousel"
    pngs = carousel_mod.render_carousel(SLIDES_FIXTURE, KIT, out,
                                        conn=conn, job_id=jid)
    assert len(pngs) == 7
    for p in pngs:
        assert carousel_mod._png_size(p) == (1080, 1350)
    # no temp files leak (atomic rename discipline)
    assert not list(out.glob("*.tmp*"))
    audio_map = json.loads((out / "audio_map.json").read_text())
    assert all(v == 2.0 for v in audio_map.values())  # 2 s/slide rule
    assert len(audio_map) == 7
    n = conn.execute("SELECT COUNT(*) c FROM slides WHERE job_id=?",
                     (jid,)).fetchone()["c"]
    assert n == 7
    jpegs = carousel_mod.export_jpeg(pngs)
    assert len(jpegs) == 7 and all(p.suffix == ".jpg" for p in jpegs)


def test_carousel_render_refuses_bad_spec(tmp_path):
    with pytest.raises(carousel_mod.CarouselError, match="exactly 7"):
        carousel_mod.render_carousel({"slides": []}, KIT, tmp_path)


# ------------------------------------------------------------------ collaborator caps

def test_collab_cap_never_silently_truncates():
    dry = publish_mod.get_adapter("dryrun")
    with pytest.raises(PublishError, match="never truncated silently"):
        check_collaborator_cap(dry, [f"@c{i}" for i in range(6)])
    postiz = publish_mod.get_adapter("postiz")
    assert postiz.capabilities().max_collaborators == 3
    with pytest.raises(PublishError, match="supports 3"):
        check_collaborator_cap(postiz, ["@a", "@b", "@c", "@d"])
    meta = publish_mod.get_adapter("meta")
    assert meta.capabilities().max_collaborators == 5  # native IG cap


def test_unknown_capability_routes_to_human_review():
    ayr = publish_mod.get_adapter("ayrshare")
    assert ayr.capabilities().max_collaborators is None
    with pytest.raises(PublishError, match="UNKNOWN.*human review"):
        check_collaborator_cap(ayr, ["@a"])


def test_preflight_publicity_checks(conn):
    pub = publish_mod.get_adapter("dryrun")
    _target(conn, "@public1", is_public=1)
    _target(conn, "@private1", is_public=0)
    conn.execute(
        "INSERT INTO targets(handle, platform) VALUES('@unchecked1','instagram')")
    conn.commit()
    # public passes
    assert publish_mod.instagram_preflight(conn, ["@public1"], pub)["collaborators"]
    # private -> human review
    with pytest.raises(PublishError, match="human review"):
        publish_mod.instagram_preflight(conn, ["@private1"], pub)
    # never checked -> human review (NULL is not public)
    with pytest.raises(PublishError, match="never performed"):
        publish_mod.instagram_preflight(conn, ["@unchecked1"], pub)
    # unknown handle -> refresh
    with pytest.raises(PublishError, match="no target record"):
        publish_mod.instagram_preflight(conn, ["@ghost"], pub)


# ------------------------------------------------------------------ consent ledger

def test_consent_grant_requires_expiry_and_artifact(conn, tmp_path):
    jid = _job(conn)
    m = _media(tmp_path)
    with pytest.raises(consent_mod.ConsentError, match="expiry is mandatory"):
        consent_mod.grant(conn, job_id=jid, handle="@x", platform="instagram",
                          actor="a", account_id="ig:x", scope="s",
                          artifact_path=m, expires_at="")
    with pytest.raises(consent_mod.ConsentError, match="not found"):
        _grant(conn, jid, "@x", str(tmp_path / "missing.bin"), tmp_path)


def test_consent_grant_hashes_artifact(conn, tmp_path):
    jid = _job(conn)
    m = _media(tmp_path, data=b"artifact-bytes")
    row = _grant(conn, jid, "@somecreator", m, tmp_path)
    import hashlib
    assert row["artifact_hash"] == hashlib.sha256(b"artifact-bytes").hexdigest()
    assert row["decision"] == "granted"
    assert row["revoked_at"] is None


def _publishable(conn, tmp_path, handle="@somecreator", n_media=2):
    """A job ready for dry_run publish: target, media, job, auth."""
    jid = _job(conn)
    _target(conn, handle)
    media = [_media(tmp_path, f"m{i}.bin", data=f"bytes-{i}".encode())
             for i in range(n_media)]
    _authorize(conn, jid, "publish")
    return jid, media


def test_publish_refused_without_consent(conn, tmp_path):
    """The old suite's test, re-proved against the new API: no consent ->
    publishing refused, dry_run or not."""
    jid, media = _publishable(conn, tmp_path)
    with pytest.raises(consent_mod.ConsentError, match="no granted"):
        publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                media=media, caption="t")


def test_consent_grant_revoke_publish_refused(conn, tmp_path):
    jid, media = _publishable(conn, tmp_path)
    art = tmp_path / "artifact"
    art.mkdir()
    for i, m in enumerate(media):
        (art / f"m{i}.bin").write_bytes(f"bytes-{i}".encode())
    grant = _grant(conn, jid, "@somecreator", str(art), tmp_path)
    res = publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                  media=media, caption="hello")
    assert res["dry_run"] is True
    assert res["consent_ids"] == [grant["id"]]
    # revoke -> publish refused; no override flag exists
    consent_mod.revoke(conn, grant["id"], actor="dino", note="test revoke")
    with pytest.raises(consent_mod.ConsentError, match="no granted"):
        publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                media=media, caption="hello")
    c = consent_mod.valid_for(conn, jid, "@somecreator", "instagram")
    assert c is None


def test_consent_not_bound_to_media_bytes(conn, tmp_path):
    """Consent keys on (job, handle) — the relationship — not on media
    bytes. A grant on an agreement artifact covers the publish regardless
    of which exact media files go out; scoping lives in the verbatim
    scope text. (The old media-fingerprint binding made every real
    publish impossible: a creator's agreement never hashes to the media.)"""
    jid, media = _publishable(conn, tmp_path)
    _grant_agreement(conn, jid, "@somecreator", tmp_path)
    other = [_media(tmp_path, "other.bin", data=b"different")]
    res = publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                  media=other, caption="t")
    assert res["dry_run"] is True
    assert res["consent_ids"], "grant should cover the other media set too"


def test_consent_expiry_refused(conn, tmp_path):
    jid, media = _publishable(conn, tmp_path)
    _grant_agreement(conn, jid, "@somecreator", tmp_path,
                    expires_at="2020-01-01T00:00:00+00:00")
    with pytest.raises(consent_mod.ConsentError, match="no granted"):
        publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                media=[media[0]], caption="t")


def test_scheduled_revoke_knocks_back_for_regating(conn, tmp_path):
    jid, media = _publishable(conn, tmp_path)
    grant = _grant_agreement(conn, jid, "@somecreator", tmp_path)
    # walk the book's consent handshake to scheduled
    jobs_mod.transition(conn, jid, "pitch_sent", "test")
    jobs_mod.transition(conn, jid, "awaiting_consent", "test")
    jobs_mod.transition(conn, jid, "consent_granted", "test")
    jobs_mod.transition(conn, jid, "scheduled", "test")
    out = consent_mod.revoke(conn, grant["id"], actor="dino")
    assert out["knocked_back"] == [jid]
    assert jobs_mod.get(conn, jid)["state"] == "consent_granted"
    # gate verdict recorded as evidence
    ok, _ = consent_mod.gate_consent(conn, jid, ["@somecreator"])
    assert not ok
    row = conn.execute(
        "SELECT * FROM gate_results WHERE job_id=? AND gate='consent_recheck'"
        " ORDER BY id DESC LIMIT 1", (jid,)).fetchone()
    assert row is not None and row["passed"] == 0


# ------------------------------------------------------------------ authorizations

def test_no_side_effect_without_authorization(conn, tmp_path):
    jid = _job(conn)
    _target(conn)
    # pitch
    with pytest.raises(authorize_mod.AuthorizationError,
                       match="no recorded authorization"):
        pitch_mod.make_pitch(conn, jid, "@somecreator")
    # publish
    m = _media(tmp_path)
    with pytest.raises(authorize_mod.AuthorizationError,
                       match="no recorded authorization"):
        publish_mod.publish_job(conn, jid, collaborators=[], media=[m])
    # invite add
    conn.execute(
        "INSERT INTO posts(id, job_id, platform, post_url, posted_at)"
        " VALUES('post_x', ?, 'instagram', 'dryrun://x', '2026-09-28T00:00:00+00:00')",
        (jid,))
    conn.commit()
    with pytest.raises(authorize_mod.AuthorizationError,
                       match="no recorded authorization"):
        invites_mod.add(conn, "post_x", "@somecreator", jid)


def test_authorization_record_and_require(conn):
    jid = _job(conn)
    row = _authorize(conn, jid, "publish")
    assert row["actor"] == "dino" and row["action"] == "publish"
    back = authorize_mod.require_authorization(conn, jid, "publish")
    assert back["id"] == row["id"]
    with pytest.raises(authorize_mod.AuthorizationError):
        authorize_mod.require_authorization(conn, jid, "pitch")


# ------------------------------------------------------------------ dry_run publish

def test_dryrun_publish_writes_placement_ledger_zero_network(conn, tmp_path,
                                                             monkeypatch):
    import socket
    jid, media = _publishable(conn, tmp_path)
    _grant_agreement(conn, jid, "@somecreator", tmp_path)
    # Zero network: any socket creation fails the test.
    monkeypatch.setattr(socket, "socket", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("network call attempted during dry_run publish")))
    res = publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                  media=media, caption="dry run caption")
    assert res["dry_run"] is True
    row = conn.execute("SELECT * FROM post_placements WHERE id=?",
                       (res["placement_id"],)).fetchone()
    assert row is not None
    assert row["dry_run"] == 1
    assert json.loads(row["request_json"])["caption"] == "dry run caption"
    assert json.loads(row["collaborators_json"]) == ["@somecreator"]
    assert row["consent_ids_json"]
    # gate re-check evidence recorded
    g = conn.execute(
        "SELECT * FROM gate_results WHERE job_id=? AND gate='consent_recheck'",
        (jid,)).fetchone()
    assert g is not None and g["passed"] == 1
    # job state untouched by a dry_run (side-effect-free)
    assert jobs_mod.get(conn, jid)["state"] == "ready"


def test_live_path_refuses_everywhere(conn, tmp_path):
    for name in ("dryrun", "meta", "postiz", "zernio", "ayrshare"):
        adapter = publish_mod.get_adapter(name)
        with pytest.raises(LiveRefused):
            adapter.create_post(platform="instagram", media=["m"],
                                caption="c", dry_run=False)
    # publish_job with dry_run=False also refuses and writes no placement
    jid, media = _publishable(conn, tmp_path)
    _grant_agreement(conn, jid, "@somecreator", tmp_path)
    n0 = conn.execute("SELECT COUNT(*) c FROM post_placements").fetchone()["c"]
    with pytest.raises(LiveRefused):
        publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                media=[media[0]], dry_run=False)
    n1 = conn.execute("SELECT COUNT(*) c FROM post_placements").fetchone()["c"]
    assert n0 == n1


# ------------------------------------------------------------------ pitch

def test_pitch_attempts_all_logged(conn):
    handles = ["@alpha", "@beta", "@gamma"]
    attempts = []
    for h in handles:
        jid = _job(conn)
        _authorize(conn, jid, "pitch")
        attempts.append(pitch_mod.make_pitch(conn, jid, h, angle="data angle"))
    assert len(pitch_mod.list_attempts(conn)) == 3
    # every attempt logged, including the default no_response
    assert {a["outcome"] for a in attempts} == {"no_response"}
    assert all(a["authorization_id"] for a in attempts)
    # jobs moved ready -> pitch_sent -> awaiting_consent
    for a in attempts:
        assert jobs_mod.get(conn, a["job_id"])["state"] == "awaiting_consent"
    st = pitch_mod.kill_threshold_status(conn)
    assert st["pitches"] == 3 and st["accepts"] == 0
    assert "EXPERIMENTAL" in st["label"] and not st["tripped"]


def test_pitch_outcome_and_render(conn):
    jid = _job(conn)
    _authorize(conn, jid, "pitch")
    att = pitch_mod.make_pitch(conn, jid, "@delta", angle="reach angle")
    assert "@delta" in att["pitch_text"] and "reach angle" in att["pitch_text"]
    pitch_mod.record_pitch_outcome(conn, att["id"], "accepted")
    t = pitch_mod.get_target(conn, "@delta", "instagram")
    assert t["consent_state"] == "pitched"
    jid2 = _job(conn)
    _authorize(conn, jid2, "pitch")
    att2 = pitch_mod.make_pitch(conn, jid2, "@epsilon")
    pitch_mod.record_pitch_outcome(conn, att2["id"], "declined")
    t2 = pitch_mod.get_target(conn, "@epsilon", "instagram")
    assert t2["consent_state"] == "denied"
    with pytest.raises(pitch_mod.PitchError):
        pitch_mod.record_pitch_outcome(conn, att2["id"], "maybe")


def test_voice_match_is_labeled_hypothesis(conn):
    samples = ["we post every single tuesday morning", "tuesday morning posts win"]
    with pytest.raises(pitch_mod.PitchError, match="no corpus consent"):
        pitch_mod.voice_match("hello world", samples, corpus_consented=False)
    profile, _ = pitch_mod.voice_match("fresh draft text here",
                                       samples, corpus_consented=True)
    assert "HYPOTHESIS" in profile["label"]
    # A verbatim run LONGER than 5 words (6 here) is plagiarism and raises.
    with pytest.raises(pitch_mod.PitchError, match="verbatim run"):
        pitch_mod.voice_match(
            "we post every single tuesday morning sharp", samples,
            corpus_consented=True)


# ------------------------------------------------------------------ invites

def _fixture_adapter(tmp_path, statuses: dict, metrics: dict | None = None):
    fx = {"posts": {}, "collaborator_status": statuses,
          "metrics": metrics or {}}
    p = tmp_path / "fx.json"
    p.write_text(json.dumps(fx), encoding="utf-8")
    return publish_mod.get_adapter("dryrun", fixtures_path=p), p


def test_invite_poll_cycle_on_fixtures(conn, tmp_path):
    jid, media = _publishable(conn, tmp_path)
    _grant_agreement(conn, jid, "@somecreator", tmp_path)
    res = publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                  media=[media[0]])
    _authorize(conn, jid, "invite")
    inv = invites_mod.add(conn, res["post_row_id"], "@somecreator", jid)
    assert inv["invite_status"] == "pending"
    adapter, _ = _fixture_adapter(
        tmp_path,
        {res["provider_post_id"]: [
            {"username": "somecreator", "invite_status": "accepted"}]})
    # dry-run publish leaves the job in ready (a rehearsal moves no
    # state); walk the real publish path to the invite handshake.
    jobs_mod.transition(conn, jid, "scheduled", "test")
    jobs_mod.transition(conn, jid, "published", "test")
    jobs_mod.transition(conn, jid, "awaiting_accept", "test")
    changed = invites_mod.poll(conn, adapter)
    assert changed and changed[0]["invite_status"] == "accepted"
    assert jobs_mod.get(conn, jid)["state"] == "accepted"
    stats = json.loads(conn.execute(
        "SELECT invite_stats_json s FROM targets WHERE handle='@somecreator'"
        " AND platform='instagram'").fetchone()["s"])
    assert stats.get("accepted") == 1


def test_invite_poll_metrics_reuses_book2_machinery(conn, tmp_path):
    jid, media = _publishable(conn, tmp_path)
    _grant_agreement(conn, jid, "@somecreator", tmp_path)
    res = publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                                  media=[media[0]])
    _authorize(conn, jid, "invite")
    invites_mod.add(conn, res["post_row_id"], "@somecreator", jid)
    written = invites_mod.poll_invite_metrics(conn, {
        res["provider_post_id"]: {"views": 1234, "likes": 56}})
    assert len(written) == 1
    row = conn.execute(
        "SELECT * FROM metrics WHERE post_id=?", (res["post_row_id"],)).fetchone()
    assert row["views"] == 1234 and row["provenance"] == "provider_api"


# ------------------------------------------------------------------ feedback + priors

def _seed_what_worked(conn, dim, value, n, mean):
    conn.execute(
        """INSERT INTO what_worked(dimension, value, n, mean_perf, updated_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(dimension, value) DO UPDATE SET
             n=excluded.n, mean_perf=excluded.mean_perf""",
        (dim, value, n, mean, "2026-09-28T00:00:00+00:00"))
    conn.commit()


def test_priors_min_n_8_guard(conn, tmp_path):
    # The book's corrected table: collab_accepted at n=7 is NOT applied.
    _seed_what_worked(conn, "collab_accepted", "n", 7, 31500.0)
    _seed_what_worked(conn, "hook_len_s", "2.0", 14, 18400.0)
    _seed_what_worked(conn, "caption_style", "word_pop", 8, 16200.0)
    data = feedback_mod.priors(conn)
    collab = [r for r in data["collab_accepted"]][0]
    assert collab["n"] == 7 and collab["applied"] is False
    assert feedback_mod.best_value(conn, "collab_accepted") is None
    hook = [r for r in data["hook_len_s"]][0]
    assert hook["applied"] is True
    assert feedback_mod.best_value(conn, "hook_len_s")["value"] == "2.0"
    # boundary: exactly 8 applies
    assert [r for r in data["caption_style"]][0]["applied"] is True
    out = feedback_mod.snapshot_priors(conn, tmp_path)
    assert out.name == "priors_v1.json"
    snap = json.loads(out.read_text())
    assert snap["min_n"] == 8
    db_rows = conn.execute(
        "SELECT dimension, applied FROM priors WHERE priors_version=1"
    ).fetchall()
    applied = {r["dimension"]: r["applied"] for r in db_rows}
    assert applied["collab_accepted"] == 0
    assert applied["hook_len_s"] == 1
    out2 = feedback_mod.snapshot_priors(conn, tmp_path)
    assert out2.name == "priors_v2.json"  # versioned, never overwritten


def test_feed_back_consumes_measured_posts(conn, tmp_path):
    jid, media = _publishable(conn, tmp_path, handle="@fb1")
    _grant_agreement(conn, jid, "@fb1", tmp_path)
    res = publish_mod.publish_job(conn, jid, collaborators=["@fb1"],
                                  media=[media[0]])
    _authorize(conn, jid, "invite")
    invites_mod.add(conn, res["post_row_id"], "@fb1", jid)
    invites_mod.poll_invite_metrics(conn, {
        res["provider_post_id"]: {"views": 5000}})
    out = feedback_mod.feed_back(conn)
    assert out["rows_consumed"] == 1
    row = conn.execute(
        "SELECT n FROM what_worked WHERE dimension='has_collaborators'"
        " AND value='yes'").fetchone()
    assert row and row["n"] == 1
    assert conn.execute(
        "SELECT COUNT(*) c FROM feedback_runs").fetchone()["c"] == 1


# ------------------------------------------------------------------ export ledger

def test_export_ledger_has_hashes_and_revocation(conn, tmp_path):
    jid = _job(conn)
    m = _media(tmp_path)
    g = _grant(conn, jid, "@ledg", m, tmp_path)
    consent_mod.revoke(conn, g["id"], actor="dino", note="test")
    out = tmp_path / "ledger.csv"
    consent_mod.export_ledger(conn, out)
    with open(out, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 1
    r = rows[0]
    assert r["artifact_hash"] and len(r["artifact_hash"]) == 64
    assert r["revoked_at"] and r["revoked_by"] == "dino"
    assert r["scope"] and r["actor"] and r["expiry"]
    assert "jurisdiction" in r and "terms_version" in r


# ------------------------------------------------------------------ CLI smoke

def test_cli_carousel_consent_priors_smoke(tmp_path, monkeypatch):
    from click.testing import CliRunner
    from hypelab.cli import cli

    root = tmp_path / "root"
    (root / "work").mkdir(parents=True)
    dbp = tmp_path / "cli.db"
    monkeypatch.setenv("HYPELAB_DB", str(dbp))
    monkeypatch.setenv("HYPELAB_ROOT", str(root))
    runner = CliRunner()
    r = runner.invoke(cli, ["migrate"])
    assert r.exit_code == 0, r.output
    kit_src = REPO / "kits" / "cerebratico" / "kit.json"
    if kit_src.is_file():
        r = runner.invoke(cli, ["kit", "new", "cerebratico",
                                "--from", str(kit_src)])
        assert r.exit_code == 0, r.output
        kit_id = "cerebratico"
    else:
        kit_id = None
    spec_path = tmp_path / "spec.json"
    spec_path.write_text(json.dumps(SLIDES_FIXTURE))
    args = ["carousel", "--spec", str(spec_path)]
    if kit_id:
        args += ["--kit", kit_id]
    else:
        pytest.skip("cerebratico kit.json not found; skipping CLI render")
    r = runner.invoke(cli, args)
    assert r.exit_code == 0, r.output
    assert "7 slides" in r.output
    r = runner.invoke(cli, ["consent", "export", "--out",
                            str(tmp_path / "ledger.csv")])
    assert r.exit_code == 0, r.output
    r = runner.invoke(cli, ["priors"])
    assert r.exit_code == 0, r.output


def test_gates_module_exposes_consent_gate(conn, tmp_path):
    # gate_consent lives in gates.py per the book; it delegates to consent.
    from hypelab import gates as gates_mod
    jid, media = _publishable(conn, tmp_path)
    _grant_agreement(conn, jid, "@somecreator", tmp_path)
    ok, detail = gates_mod.gate_consent(conn, jid, ["@somecreator"])
    assert ok, detail
    ok, detail = gates_mod.gate_consent(conn, jid, ["@stranger"])
    assert not ok and "no granted" in detail


def test_collab_caps_recorded_at_preflight(conn, tmp_path):
    # The collaborator cap that governed the publish decision is persisted
    # in collab_caps, versioned per adapter. Ayrshare's cap is UNKNOWN.
    jid, media = _publishable(conn, tmp_path)
    _authorize(conn, jid, "publish")
    _grant_agreement(conn, jid, "@somecreator", tmp_path)
    publish_mod.publish_job(conn, jid, collaborators=["@somecreator"],
                            media=media)
    rows = {r["adapter_name"]: r for r in conn.execute(
        "SELECT * FROM collab_caps").fetchall()}
    assert "dryrun" in rows
    publish_mod.record_collab_caps(conn, publish_mod.get_adapter("ayrshare"))
    conn.commit()
    ay = conn.execute(
        "SELECT max_collaborators FROM collab_caps WHERE adapter_name='ayrshare'"
    ).fetchone()
    assert ay["max_collaborators"] is None  # UNKNOWN -> human review
