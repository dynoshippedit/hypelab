"""Regression tests for T-004 (BUG-003): CLI drives must not strand jobs.

audio/render/gates/cut move the job to an active state via transition()
(which clears the lease). On drive failure the job used to sit in the
active state with a NULL lease — unclaimable (claim() only reclaims active
jobs whose lease is non-NULL and expired) and unrecoverable without SQL.
Drives now fail the job (fail-equivalent) when no lease is held, and
re-raise so the CLI error contract is unchanged.
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from click.testing import CliRunner  # noqa: E402

from hypelab import align as align_mod  # noqa: E402
from hypelab import cli as cli_mod  # noqa: E402
from hypelab import cut as cut_mod  # noqa: E402
from hypelab import db as db_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402
from hypelab import kits as kits_mod  # noqa: E402
from hypelab import manifests as manifests_mod  # noqa: E402
from hypelab import render as render_mod  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    root = tmp_path / "root"
    (root / "work").mkdir(parents=True)
    monkeypatch.setenv("HYPELAB_DB", str(dbp))
    monkeypatch.setenv("HYPELAB_ROOT", str(root))
    runner = CliRunner()
    r = runner.invoke(cli_mod.cli, ["migrate"])
    assert r.exit_code == 0, r.output
    conn = db_mod.connect(str(dbp))
    try:
        kits_mod.seed(conn, "k", {})
    finally:
        conn.close()
    return {"db": dbp, "root": root, "runner": runner}


def _mk_job(dbp, state):
    conn = db_mod.connect(str(dbp))
    try:
        return jobs_mod.new(conn, mode="book1", title="t004", state=state,
                            kit_id="k", kit_version=1)
    finally:
        conn.close()


def _job_row(dbp, job_id):
    cx = sqlite3.connect(str(dbp))
    try:
        return cx.execute(
            "SELECT state, lease_owner, lease_expires, error FROM jobs"
            " WHERE id=?",
            (job_id,),
        ).fetchone()
    finally:
        cx.close()


def _last_event(dbp, job_id):
    cx = sqlite3.connect(str(dbp))
    try:
        return cx.execute(
            "SELECT from_state, to_state FROM job_events WHERE job_id=?"
            " ORDER BY rowid DESC LIMIT 1",
            (job_id,),
        ).fetchone()
    finally:
        cx.close()


# ---------------------------------------------------------------- fail_drive


@pytest.mark.parametrize("state", ["aligning", "rendering", "gating", "cutting"])
def test_fail_drive_moves_unleased_active_job_to_failed(env, state):
    jid = _mk_job(env["db"], state)
    conn = db_mod.connect(str(env["db"]))
    try:
        assert jobs_mod.fail_drive(conn, jid, RuntimeError("boom")) is True
    finally:
        conn.close()
    state_got, lease_owner, lease_expires, err = _job_row(env["db"], jid)
    assert state_got == "failed"
    assert lease_owner is None and lease_expires is None
    assert "boom" in (err or "")
    assert _last_event(env["db"], jid) == (state, "failed")


def test_fail_drive_noop_when_lease_held(env):
    # The work loop owns leased failures via queue.fail(); fail_drive must
    # not touch them.
    jid = _mk_job(env["db"], "rendering")
    conn = db_mod.connect(str(env["db"]))
    try:
        conn.execute(
            "UPDATE jobs SET lease_owner='w1',"
            " lease_expires='2999-01-01T00:00:00+00:00' WHERE id=?", (jid,))
        assert jobs_mod.fail_drive(conn, jid, RuntimeError("boom")) is False
    finally:
        conn.close()
    state_got, lease_owner, _, _ = _job_row(env["db"], jid)
    assert state_got == "rendering"
    assert lease_owner == "w1"


@pytest.mark.parametrize("state", ["queued_render", "aligned", "failed", "ready"])
def test_fail_drive_noop_outside_drive_states(env, state):
    jid = _mk_job(env["db"], state)
    conn = db_mod.connect(str(env["db"]))
    try:
        assert jobs_mod.fail_drive(conn, jid, RuntimeError("boom")) is False
    finally:
        conn.close()
    assert _job_row(env["db"], jid)[0] == state


def test_fail_drive_unknown_job(env):
    conn = db_mod.connect(str(env["db"]))
    try:
        assert jobs_mod.fail_drive(conn, "j-nope", RuntimeError("boom")) is False
    finally:
        conn.close()


# ------------------------------------------------------------------- drives


def test_gates_drive_failure_fails_job(env):
    # No renders recorded: _run_gates dies AFTER the job moved to gating.
    jid = _mk_job(env["db"], "rendered")
    r = env["runner"].invoke(cli_mod.cli, ["gates", jid])
    assert r.exit_code != 0
    assert "error:" in r.output
    state_got, lease_owner, _, err = _job_row(env["db"], jid)
    assert state_got == "failed", (state_got, err)
    assert lease_owner is None
    assert "no renders" in (err or "")


def test_render_drive_failure_fails_job(env, monkeypatch):
    jid = _mk_job(env["db"], "queued_render")
    work = Path(cli_mod._work_dir(jid))
    work.mkdir(parents=True, exist_ok=True)
    (work / "render.json").write_text(json.dumps({
        "edl_version": 1,
        "target": {"aspect": "9:16", "w": 1080, "h": 1920},
        "beats": [{"id": "b0", "clip_path": "/tmp/clip.mp4"}],
    }))

    def _boom(*a, **k):
        raise render_mod.RenderError("ffmpeg exploded")

    monkeypatch.setattr(render_mod, "render", _boom)
    r = env["runner"].invoke(cli_mod.cli, ["render", jid])
    assert r.exit_code != 0
    assert "error:" in r.output
    state_got, lease_owner, _, err = _job_row(env["db"], jid)
    assert state_got == "failed", (state_got, err)
    assert lease_owner is None
    assert "ffmpeg exploded" in (err or "")


def test_audio_drive_failure_fails_job(env, monkeypatch, tmp_path):
    jid = _mk_job(env["db"], "scripted")
    work = Path(cli_mod._work_dir(jid))
    work.mkdir(parents=True, exist_ok=True)
    (work / "render.json").write_text(json.dumps({"edl_version": 1,
                                                  "beats": []}))
    vo = tmp_path / "vo.mp3"
    vo.write_bytes(b"fake-audio")
    monkeypatch.setattr(
        manifests_mod, "attach_asset",
        lambda src, work, name, expected_sha256=None: {
            "sha256": "abc", "name": name})
    def _boom(conn, job_id, kit, work, edl):  # noqa: ARG001
        raise align_mod.AlignError("no speech detected")

    monkeypatch.setattr(cli_mod, "_do_align", _boom)
    r = env["runner"].invoke(cli_mod.cli, ["audio", jid, "--vo", str(vo)])
    assert r.exit_code != 0
    assert "error:" in r.output
    state_got, lease_owner, _, err = _job_row(env["db"], jid)
    assert state_got == "failed", (state_got, err)
    assert lease_owner is None
    assert "no speech" in (err or "")


def test_cut_drive_failure_fails_job(env, monkeypatch):
    jid = _mk_job(env["db"], "scored")
    conn = db_mod.connect(str(env["db"]))
    try:
        conn.execute(
            "INSERT INTO moments(id, job_id, t_in, t_out, score, confidence,"
            " signals_json, transcript, picked, weight_version)"
            " VALUES (?,?,?,?,?,?,?,?,?,?)",
            ("m1", jid, 0.0, 1.0, 0.9, 0.8, "{}", "", 0, "test"))
    finally:
        conn.close()
    work = Path(cli_mod._work_dir(jid))
    work.mkdir(parents=True, exist_ok=True)
    (work / "source.words.json").write_text(json.dumps({"words": []}))

    def _boom(*a, **k):
        raise cut_mod.CutError("reframe exploded")

    monkeypatch.setattr(cut_mod, "cut_moment", _boom)
    r = env["runner"].invoke(cli_mod.cli, ["cut", jid, "1"])
    assert r.exit_code != 0
    assert "error:" in r.output
    state_got, lease_owner, _, err = _job_row(env["db"], jid)
    assert state_got == "failed", (state_got, err)
    assert lease_owner is None
    assert "reframe exploded" in (err or "")
