"""Regression tests for T-003 (BUG-001): _die must not kill the worker.

_die() used to raise SystemExit (a BaseException), which escaped the
work-loop's `except Exception` guard in hypelab/cli.py: the worker
process died, the job lease was orphaned, and the failure was never
recorded via queue.fail(). _die() now raises CliError (a plain
Exception); the Click entrypoint (CliGroup) still translates it into
the historical contract: `error:` on stderr + nonzero exit, no traceback.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from click.testing import CliRunner  # noqa: E402

from hypelab import cli as cli_mod  # noqa: E402
from hypelab import db as db_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402
from hypelab.cli_errors import CliError  # noqa: E402


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
    return {"db": dbp, "root": root, "runner": runner}


def _queued_align_job(dbp):
    conn = db_mod.connect(str(dbp))
    try:
        jid = jobs_mod.new(conn, mode="book1", title="t003",
                           state="queued_align")
        conn.commit()
        return jid
    finally:
        conn.close()


def _job_row(dbp, job_id):
    cx = sqlite3.connect(str(dbp))
    try:
        return cx.execute(
            "SELECT state, lease_owner, error FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    finally:
        cx.close()


def test_die_raises_cli_error_not_system_exit(capsys):
    with pytest.raises(CliError) as ei:
        cli_mod._die("boom", code=3)
    assert ei.value.msg == "boom"
    assert ei.value.code == 3
    assert isinstance(ei.value, Exception)
    assert not isinstance(ei.value, SystemExit)
    # The message is still printed to stderr at the raise site.
    assert "error: boom" in capsys.readouterr().err


def test_cli_error_is_caught_by_plain_except_exception():
    # The exact guard shape the work loop uses must catch it.
    try:
        cli_mod._die("boom")
        raise AssertionError("unreachable")
    except Exception as e:
        assert isinstance(e, CliError)


def test_worker_survives_deterministic_handler_failure(env, monkeypatch):
    # BUG-001: a handler failing via _die used to raise SystemExit, which
    # escaped the work loop's `except Exception` guard and killed the
    # worker. Now the job must land in `failed` and the worker exits 0.
    job_id = _queued_align_job(env["db"])

    def _boom(conn, job_id_):
        cli_mod._die("simulated deterministic failure")

    monkeypatch.setattr(cli_mod, "_handle_align", _boom)
    r = env["runner"].invoke(cli_mod.cli, ["work", "--once", "--owner", "t003"])
    assert r.exit_code == 0, r.output
    assert r.exception is None
    state, lease_owner, error = _job_row(env["db"], job_id)
    assert state == "failed", (state, error)
    assert lease_owner is None
    assert "simulated deterministic failure" in (error or "")
    assert "handler error" in r.output


def test_clean_error_contract_preserved_end_to_end(env):
    # Deterministic failure through the real CLI: `error:` on stderr,
    # nonzero exit, never a traceback.
    script = env["root"] / "script.txt"
    script.write_text("hello world")
    r = env["runner"].invoke(
        cli_mod.cli, ["new", "--kit", "nosuchkit", "--script", str(script)])
    assert r.exit_code == 1, r.output
    assert "error:" in r.output
    assert "not found" in r.output
    assert "Traceback" not in r.output
