"""Regression tests for T-005 (BUG-002): render hash-skip must not wedge the job.

The render drive moves `queued_render -> rendering` (clearing the lease),
then render() can return {"skipped": True} when the output hash already
matches. The old code returned early with the state untouched, leaving the
job stranded in `rendering` with a NULL lease — unclaimable and unwedgeable
without SQL. The fix progresses a skip exactly like a fresh render:
rendering -> rendered -> queued_gates.

Setup note: the job is driven new -> attach -> audio -> render once (real
ffmpeg), then reset to `queued_render` via SQL to simulate the state an
audio re-drive leaves behind with an unchanged EDL. The render hash then
matches and the skip path is exercised deterministically.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from tests.test_cli import (  # noqa: E402
    _db_state,
    _full_pipeline_to_render,
    cli,
    env,
    media,
)


def _set_state(dbp, job_id, state):
    cx = sqlite3.connect(str(dbp))
    try:
        cx.execute("UPDATE jobs SET state=? WHERE id=?", (state, job_id))
        cx.commit()
    finally:
        cx.close()


def test_hash_skip_from_queued_render_reaches_queued_gates(env, media):
    """The T-005 wedge: skip after queued_render -> rendering must progress."""
    runner = env["runner"]
    job_id, out = _full_pipeline_to_render(runner, env, media)
    assert _db_state(env["db"], job_id)[0] == "queued_gates"

    # Simulate an audio re-drive with unchanged media: back at queued_render
    # with the same EDL, so the render drive moves to `rendering` and skips.
    _set_state(env["db"], job_id, "queued_render")

    r = runner.invoke(cli, ["render", job_id])
    assert r.exit_code == 0, r.output
    # Acceptance message preserved.
    assert "hash unchanged, skipping" in r.output
    state, _ = _db_state(env["db"], job_id)
    assert state == "queued_gates", f"wedged in {state!r}"


def test_hash_skip_from_rendered_still_progresses(env, media):
    """A skip is a current render: from `rendered` it advances to gates."""
    runner = env["runner"]
    job_id, out = _full_pipeline_to_render(runner, env, media)
    _set_state(env["db"], job_id, "rendered")

    r = runner.invoke(cli, ["render", job_id])
    assert r.exit_code == 0, r.output
    assert "hash unchanged, skipping" in r.output
    state, _ = _db_state(env["db"], job_id)
    assert state == "queued_gates", f"left in {state!r}"
