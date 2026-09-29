"""Failure-type-based requeue tests (T-011 / owner decision D1, hl-cycle-08).

Owner spec:
  - AUTO-REQUEUE only transient failures (timeouts, rate limits, provider
    5xx): with backoff, max 3 attempts, each attempt's cost in the ledger.
  - REVIEW PILE for everything else: bad input, auth errors, refusals,
    failed quality gates, max attempts hit. Owner clears by hand.
  - NEVER auto-retry a publish job (a timeout can mean it already posted)
    or anything paused waiting on the owner.
"""
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import db as db_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402
from hypelab import kits as kits_mod  # noqa: E402
from hypelab import queue as queue_mod  # noqa: E402
from hypelab import retry as retry_mod  # noqa: E402
from hypelab.cli import cli  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    root = tmp_path / "root"
    (root / "work").mkdir(parents=True)
    monkeypatch.setenv("HYPELAB_DB", str(dbp))
    monkeypatch.setenv("HYPELAB_ROOT", str(root))
    conn = db_mod.connect(str(dbp))
    try:
        db_mod.migrate(conn)
        kits_mod.seed(conn, "k", {})
    finally:
        conn.close()
    return {"db": dbp, "root": root}


def _conn(dbp):
    return db_mod.connect(str(dbp))


def _claim_pipeline_job(dbp, queued_state="queued_render", owner="w1"):
    """Create a job in a queued state and claim it (active state, attempt 1)."""
    conn = _conn(dbp)
    try:
        jid = jobs_mod.new(conn, mode="book1", title="tq", state=queued_state,
                           kit_id="k", kit_version=1)
        row = queue_mod.claim(conn, owner, states=[queued_state])
        assert row is not None and row["id"] == jid
        return jid
    finally:
        conn.close()


def _get(dbp, jid):
    conn = _conn(dbp)
    try:
        return jobs_mod.get(conn, jid)
    finally:
        conn.close()


def _cost_rows(dbp, jid):
    conn = _conn(dbp)
    try:
        return conn.execute(
            "SELECT provider, unit, qty, usd, note FROM cost_ledger"
            " WHERE job_id=? ORDER BY id", (jid,)).fetchall()
    finally:
        conn.close()


def _force_backoff_past(dbp, jid):
    past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat(
        timespec="seconds")
    conn = _conn(dbp)
    try:
        conn.execute("UPDATE jobs SET requeue_not_before=? WHERE id=?",
                     (past, jid))
    finally:
        conn.close()


class _HttpErr(Exception):
    def __init__(self, code, msg="provider error"):
        super().__init__("%s: %s" % (code, msg))
        self.status_code = code


# ---------------------------------------------------------------------------
# Classifier unit tests
# ---------------------------------------------------------------------------

def test_classifier_transient_shapes():
    assert retry_mod.classify_failure(TimeoutError("timed out"))[0] == "transient"
    assert retry_mod.classify_failure(_HttpErr(429))[0] == "transient"
    assert retry_mod.classify_failure(_HttpErr(503))[0] == "transient"
    assert retry_mod.classify_failure(_HttpErr(500))[0] == "transient"
    assert retry_mod.classify_failure(_HttpErr(504))[0] == "transient"
    assert retry_mod.classify_failure(
        RuntimeError("rate limit exceeded"))[0] == "transient"


def test_classifier_terminal_shapes():
    assert retry_mod.classify_failure(ValueError("bad input"))[0] == "terminal"
    assert retry_mod.classify_failure(_HttpErr(401))[0] == "terminal"
    assert retry_mod.classify_failure(_HttpErr(403))[0] == "terminal"
    assert retry_mod.classify_failure(
        RuntimeError("refused: content policy"))[0] == "terminal"
    assert retry_mod.classify_failure(
        RuntimeError("quality gate failed"))[0] == "terminal"
    # Unknown failures fail closed -> terminal, never auto-retried.
    assert retry_mod.classify_failure(
        RuntimeError("something completely novel"))[0] == "terminal"


def test_classifier_terminal_hints_take_precedence_over_transient():
    """T-041b: mixed-signal error text (terminal + transient hints) must
    classify terminal so bad config can never auto-retry."""
    assert retry_mod.classify_failure(
        ValueError("invalid timeout value: must be positive"))[0] == "terminal"
    assert retry_mod.classify_failure(
        RuntimeError("connection timeout: invalid API key"))[0] == "terminal"
    # Pure transient signals still retry.
    assert retry_mod.classify_failure(
        TimeoutError("connection timed out"))[0] == "transient"
    assert retry_mod.classify_failure(
        RuntimeError("rate limit exceeded"))[0] == "transient"


def test_backoff_schedule():
    assert retry_mod.backoff_delay_s(1) == 60
    assert retry_mod.backoff_delay_s(2) == 120
    assert retry_mod.backoff_delay_s(3) == 240
    assert retry_mod.backoff_delay_s(99) == 900  # capped


# ---------------------------------------------------------------------------
# Routing: transient -> requeue, terminal -> review pile
# ---------------------------------------------------------------------------

def test_transient_failure_requeues_with_backoff(env):
    dbp = env["db"]
    jid = _claim_pipeline_job(dbp)  # rendering, attempts=1
    conn = _conn(dbp)
    try:
        outcome = retry_mod.handle_failure(conn, jid, "w1",
                                           TimeoutError("read timed out"))
    finally:
        conn.close()
    assert outcome == "requeued"
    row = _get(dbp, jid)
    assert row["state"] == "queued_render"
    assert row["attempts"] == 1  # attempts count claims, not failures
    assert row["review_reason"] is None
    # Backoff: ~60s out.
    nb = datetime.fromisoformat(row["requeue_not_before"])
    delta = (nb - datetime.now(timezone.utc)).total_seconds()
    assert 30 < delta <= 65, delta
    # One cost row for the spent attempt.
    costs = _cost_rows(dbp, jid)
    assert len(costs) == 1
    assert costs[0]["note"].startswith("UNMETERED|requeue attempt 1/3")


def test_claim_skips_job_until_backoff_elapses(env):
    dbp = env["db"]
    jid = _claim_pipeline_job(dbp)
    conn = _conn(dbp)
    try:
        assert retry_mod.handle_failure(conn, jid, "w1",
                                        TimeoutError("x")) == "requeued"
        # Still in backoff: not claimable.
        assert queue_mod.claim(conn, "w2", states=["queued_render"]) is None
    finally:
        conn.close()
    _force_backoff_past(dbp, jid)
    conn = _conn(dbp)
    try:
        row = queue_mod.claim(conn, "w2", states=["queued_render"])
        assert row is not None and row["id"] == jid
        assert row["attempts"] == 2
        # Claiming consumes the backoff.
        assert row["requeue_not_before"] is None
    finally:
        conn.close()


def test_three_attempts_then_review_pile(env):
    dbp = env["db"]
    jid = _claim_pipeline_job(dbp)
    # Attempt 1: transient -> requeue.
    conn = _conn(dbp)
    try:
        assert retry_mod.handle_failure(conn, jid, "w1",
                                        TimeoutError("t1")) == "requeued"
    finally:
        conn.close()
    # Attempt 2: transient -> requeue.
    _force_backoff_past(dbp, jid)
    conn = _conn(dbp)
    try:
        row = queue_mod.claim(conn, "w1", states=["queued_render"])
        assert row["attempts"] == 2
        assert retry_mod.handle_failure(conn, jid, "w1",
                                        _HttpErr(503)) == "requeued"
    finally:
        conn.close()
    # Attempt 3: transient BUT attempts exhausted -> review pile.
    _force_backoff_past(dbp, jid)
    conn = _conn(dbp)
    try:
        row = queue_mod.claim(conn, "w1", states=["queued_render"])
        assert row["attempts"] == 3
        assert retry_mod.handle_failure(conn, jid, "w1",
                                        TimeoutError("t3")) == "review"
    finally:
        conn.close()
    row = _get(dbp, jid)
    assert row["state"] == "failed"
    assert row["review_reason"] is not None
    assert row["review_reason"].startswith("transient:")
    # POISON stamp: max attempts hit.
    conn = _conn(dbp)
    try:
        notes = [r[0] for r in conn.execute(
            "SELECT note FROM job_events WHERE job_id=? AND to_state='failed'"
            " ORDER BY id", (jid,)).fetchall()]
    finally:
        conn.close()
    assert any(n.startswith("POISON|") for n in notes)
    # Exactly one cost row per attempt.
    costs = _cost_rows(dbp, jid)
    assert len(costs) == 3, [c["note"] for c in costs]
    assert costs[2]["note"].startswith("UNMETERED|attempt routed to review")


@pytest.mark.parametrize("err", [
    ValueError("bad input: missing beatmap"),
    _HttpErr(401, "unauthorized"),
    _HttpErr(403, "forbidden"),
    RuntimeError("refused: content policy"),
    RuntimeError("quality gate failed: sharpness 0.2 < 0.5"),
])
def test_terminal_failures_go_straight_to_review(env, err):
    dbp = env["db"]
    jid = _claim_pipeline_job(dbp)  # rendering, attempts=1
    conn = _conn(dbp)
    try:
        outcome = retry_mod.handle_failure(conn, jid, "w1", err)
    finally:
        conn.close()
    assert outcome == "review"
    row = _get(dbp, jid)
    assert row["state"] == "failed"
    assert row["requeue_not_before"] is None  # never requeued
    assert row["review_reason"] is not None
    assert row["review_reason"].startswith("terminal:")
    costs = _cost_rows(dbp, jid)
    assert len(costs) == 1
    assert "review pile" in costs[0]["note"]


def test_mixed_signal_failure_goes_to_review_not_requeue(env):
    """T-041b routing: an error whose text mentions a timeout but is
    really bad config ("invalid timeout value") must land in the review
    pile, not auto-requeue."""
    dbp = env["db"]
    jid = _claim_pipeline_job(dbp)  # rendering, attempts=1
    conn = _conn(dbp)
    try:
        outcome = retry_mod.handle_failure(
            conn, jid, "w1",
            ValueError("invalid timeout value: must be positive"))
    finally:
        conn.close()
    assert outcome == "review"
    row = _get(dbp, jid)
    assert row["state"] == "failed"
    assert row["requeue_not_before"] is None  # never requeued
    assert (row["review_reason"] or "").startswith("terminal:")


# ---------------------------------------------------------------------------
# Hard exclusions: publish jobs and owner-waiting jobs never auto-retry
# ---------------------------------------------------------------------------

def _leased_job_in_state(dbp, state, owner="w1"):
    """Job sitting in a non-claimable state with a lease held by owner."""
    conn = _conn(dbp)
    try:
        jid = jobs_mod.new(conn, mode="book1", title="tq", state=state,
                           kit_id="k", kit_version=1)
        conn.execute(
            "UPDATE jobs SET lease_owner=?, lease_expires=?, attempts=1"
            " WHERE id=?",
            (owner, (datetime.now(timezone.utc)
                     + timedelta(minutes=30)).isoformat(timespec="seconds"),
             jid))
        return jid
    finally:
        conn.close()


@pytest.mark.parametrize("state", [
    "scheduled", "published", "awaiting_consent", "pitch_sent", "dry_run",
])
def test_publish_jobs_never_autorequeue(env, state):
    dbp = env["db"]
    jid = _leased_job_in_state(dbp, state)
    conn = _conn(dbp)
    try:
        # Even a textbook transient failure must NOT requeue a publish job.
        outcome = retry_mod.handle_failure(conn, jid, "w1",
                                           TimeoutError("post timed out"))
    finally:
        conn.close()
    assert outcome == "review"
    row = _get(dbp, jid)
    assert row["state"] == "failed"
    assert "publish-excluded" in (row["review_reason"] or "")


@pytest.mark.parametrize("state", ["awaiting_media", "compliance_unknown"])
def test_owner_waiting_jobs_never_autorequeue(env, state):
    dbp = env["db"]
    jid = _leased_job_in_state(dbp, state)
    conn = _conn(dbp)
    try:
        outcome = retry_mod.handle_failure(conn, jid, "w1",
                                           _HttpErr(503, "timeout-ish"))
    finally:
        conn.close()
    assert outcome == "review"
    row = _get(dbp, jid)
    assert row["state"] == "failed"
    assert "owner-waiting" in (row["review_reason"] or "")


# ---------------------------------------------------------------------------
# Review-pile CLI: list / retry / dismiss
# ---------------------------------------------------------------------------

def _put_in_review(dbp, reason="terminal:bad input"):
    conn = _conn(dbp)
    try:
        jid = jobs_mod.new(conn, mode="book1", title="review-me",
                           state="queued_render", kit_id="k", kit_version=1)
        queue_mod.claim(conn, "w1", states=["queued_render"])
        queue_mod.fail(conn, jid, "w1", ValueError("bad input"),
                       review_reason=reason)
        return jid
    finally:
        conn.close()


def test_review_pile_cli_list_retry_dismiss(env, monkeypatch):
    dbp = env["db"]
    runner = CliRunner()
    jid = _put_in_review(dbp)

    r = runner.invoke(cli, ["review-pile", "list"])
    assert r.exit_code == 0, r.output
    assert jid in r.output
    assert "terminal:bad input" in r.output

    r = runner.invoke(cli, ["review-pile", "retry", jid])
    assert r.exit_code == 0, r.output
    assert "draft" in r.output
    row = _get(dbp, jid)
    assert row["state"] == "draft"
    assert row["review_reason"] is None

    # Pile is empty again.
    r = runner.invoke(cli, ["review-pile", "list"])
    assert r.exit_code == 0, r.output
    assert "empty" in r.output

    # Dismiss path.
    jid2 = _put_in_review(dbp, reason="terminal:auth")
    r = runner.invoke(cli, ["review-pile", "dismiss", jid2])
    assert r.exit_code == 0, r.output
    assert "archived" in r.output
    row = _get(dbp, jid2)
    assert row["state"] == "archived"
    assert row["review_reason"] is None


def test_review_pile_cli_refuses_non_failed(env):
    dbp = env["db"]
    runner = CliRunner()
    conn = _conn(dbp)
    try:
        jid = jobs_mod.new(conn, mode="book1", title="notfailed",
                           state="queued_render", kit_id="k", kit_version=1)
    finally:
        conn.close()
    r = runner.invoke(cli, ["review-pile", "retry", jid])
    assert r.exit_code != 0
    r = runner.invoke(cli, ["review-pile", "retry", "j_nope"])
    assert r.exit_code != 0


def test_handle_failure_unknown_job_raises(env):
    conn = _conn(env["db"])
    try:
        with pytest.raises(ValueError):
            retry_mod.handle_failure(conn, "j_nope", "w1", TimeoutError("x"))
    finally:
        conn.close()


def test_auto_requeue_kill_switch_sends_transient_to_review(env, monkeypatch):
    """HYPELAB_AUTO_REQUEUE=0 routes transient failures to the review pile."""
    dbp = env["db"]
    monkeypatch.setenv("HYPELAB_AUTO_REQUEUE", "0")
    jid = _claim_pipeline_job(dbp)
    conn = _conn(dbp)
    try:
        outcome = retry_mod.handle_failure(conn, jid, "w1", TimeoutError("boom"))
    finally:
        conn.close()
    assert outcome == "review"
    row = _get(dbp, jid)
    assert row["state"] == "failed"
    assert row["review_reason"].startswith("auto-requeue-disabled:")


def test_auto_requeue_still_requeues_when_enabled(env, monkeypatch):
    """Default (env unset) keeps the auto-requeue behavior for transients."""
    dbp = env["db"]
    monkeypatch.delenv("HYPELAB_AUTO_REQUEUE", raising=False)
    jid = _claim_pipeline_job(dbp)
    conn = _conn(dbp)
    try:
        outcome = retry_mod.handle_failure(conn, jid, "w1", TimeoutError("boom"))
    finally:
        conn.close()
    assert outcome == "requeued"


@pytest.mark.parametrize("val", ["false", "no", "off", "0", "FALSE", " Off "])
def test_auto_requeue_kill_switch_spellings(val, monkeypatch):
    monkeypatch.setenv("HYPELAB_AUTO_REQUEUE", val)
    assert retry_mod.auto_requeue_enabled() is False


@pytest.mark.parametrize("val", ["1", "true", "yes", "on"])
def test_auto_requeue_enabled_spellings(val, monkeypatch):
    monkeypatch.setenv("HYPELAB_AUTO_REQUEUE", val)
    assert retry_mod.auto_requeue_enabled() is True


def test_auto_requeue_default_is_on(monkeypatch):
    monkeypatch.delenv("HYPELAB_AUTO_REQUEUE", raising=False)
    assert retry_mod.auto_requeue_enabled() is True
