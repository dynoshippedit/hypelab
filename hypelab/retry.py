"""Failure-type-based requeue (T-011 / owner decision D1, 2026-09-29).

Split failures by TYPE:
  - AUTO-REQUEUE: only TRANSIENT failures (timeouts, rate limits, provider
    5xx), with backoff, max 3 attempts (the existing attempts/MAX_ATTEMPTS
    machinery), and each attempt's cost logged to the cost ledger.
  - REVIEW PILE: everything else (bad input, auth errors, refusals, failed
    quality gates, max attempts hit) goes to a manual review pile the owner
    clears by hand.

Hard exclusions (never auto-retry, even on a transient failure):
  - publish jobs: a timeout can mean the job already posted;
  - jobs paused waiting on the owner.

Unknown/unrecognized failures default to TERMINAL (fail closed: they land
in the review pile, never auto-retried).

The requeue path respects the hl-cycle-06 atomicity contract: legality is
enforced by predicates ON the UPDATE, and the state change + audit log +
cost row commit in ONE explicit transaction.
"""
from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import queue as queue_mod
from .util import now

#: Base backoff between auto-requeue attempts (seconds); doubles per attempt.
BACKOFF_BASE_S = 60
#: Hard cap on a single backoff delay (seconds).
BACKOFF_CAP_S = 900

#: Job states that belong to the publish handshake. A timeout here can mean
#: the post already happened, so these NEVER auto-requeue (D1).
PUBLISH_STATES = frozenset({
    # Book 3 publish handshake.
    "pitch_sent", "dry_run", "awaiting_consent", "consent_granted",
    "scheduled", "published", "awaiting_accept",
    # Book 2 clip pipeline: tray -> posted performs the post.
    "tray", "posted",
})

#: Job states where the job is paused waiting on the owner. Never auto-retry.
#: (compliance_unknown is defense-in-depth: jobs paused for human
#: compliance review; currently unreachable via the work loop.)
OWNER_WAITING_STATES = frozenset({
    "awaiting_consent", "awaiting_accept", "awaiting_media",
    "compliance_unknown",
})

_TRANSIENT_CODES = {408, 425, 429, 500, 502, 503, 504}
_TERMINAL_CODES = {400, 401, 402, 403, 404, 405, 410, 413, 415, 422, 451}

_TRANSIENT_HINTS = (
    "timeout", "timed out", "timedout", "temporarily", "try again",
    "rate limit", "ratelimit", "too many requests", "throttl",
    "service unavailable", "bad gateway", "gateway timeout",
    "internal server error", "overloaded", "capacity",
    "connection reset", "connection aborted", "econnreset",
)
_TERMINAL_HINTS = (
    "unauthor", "forbidden", "auth", "invalid", "bad input", "bad request",
    "not found", "validation", "refus", "policy", "not allowed",
    "permission", "gate", "poison", "declined", "denied", "expired",
)


def _status_code(err: BaseException) -> Optional[int]:
    """Best-effort provider HTTP status from the exception shape."""
    for attr in ("status_code", "status"):
        v = getattr(err, attr, None)
        if isinstance(v, int) and 100 <= v < 600:
            return v
    resp = getattr(err, "response", None)
    if resp is not None:
        for attr in ("status_code", "status"):
            v = getattr(resp, attr, None)
            if isinstance(v, int) and 100 <= v < 600:
                return v
    m = re.search(r"\b(?:http|status)[ _]?(4\d\d|5\d\d)\b", str(err),
                  re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def _provider_hint(err: BaseException) -> str:
    p = getattr(err, "provider", None)
    if isinstance(p, str) and p:
        return p
    return "unknown"


def classify_failure(err: BaseException) -> tuple:
    """Classify a failure as ("transient"|"terminal", detail).

    Transient = timeouts, rate limits, provider 5xx. Everything else --
    including anything unrecognized -- is terminal (fail closed).
    """
    code = _status_code(err)
    if code is not None:
        if code in _TRANSIENT_CODES:
            return "transient", "provider HTTP %d" % code
        if code in _TERMINAL_CODES:
            return "terminal", "provider HTTP %d" % code
        if 500 <= code < 600:
            return "transient", "provider HTTP %d" % code
        # Any other recognized 4xx -> terminal.
        return "terminal", "provider HTTP %d" % code
    if isinstance(err, TimeoutError):
        # Covers builtin TimeoutError, asyncio.TimeoutError, socket.timeout.
        return "transient", "timeout"
    text = ("%s: %s" % (type(err).__name__, err)).lower()
    # T-041b: check TERMINAL hints BEFORE transient hints. Mixed-signal
    # text (e.g. "invalid timeout value", "connection timeout: invalid
    # API key") is bad config, not a flaky provider -- it must land in
    # the review pile, never auto-retry. The status-code path above is
    # untouched and still takes precedence.
    if any(h in text for h in _TERMINAL_HINTS):
        return "terminal", "terminal signal in error text"
    if any(h in text for h in _TRANSIENT_HINTS):
        return "transient", "transient signal in error text"
    return "terminal", "unrecognized failure (fail closed)"


def backoff_delay_s(attempt: int) -> int:
    """Backoff before requeue attempt N (1-based): 60s, 120s, 240s, cap 900s."""
    return min(BACKOFF_BASE_S * (2 ** max(attempt - 1, 0)), BACKOFF_CAP_S)


def _to_review(conn, job_id, owner, err, reason):
    """Route a failure to the manual review pile (state -> failed).

    Uses queue.fail() (atomic, lease-predicated) with the review reason
    stamped on the row, plus one cost-ledger row for the spent attempt --
    all in ONE transaction.
    """
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        queue_mod.fail(conn, job_id, owner, err, review_reason=reason)
        queue_mod.log_cost(
            conn, job_id, _provider_hint(err), "attempt", 1, 0.0,
            "ACTUAL|attempt routed to review pile: %s (cost unmetered)"
            % reason,
        )
        if own:
            conn.execute("COMMIT")
    except Exception:
        if own:
            conn.execute("ROLLBACK")
        raise
    return "review"


def _requeue(conn, job_id, owner, err, frm, attempt, detail):
    """Auto-requeue a transient failure: active state -> queued state.

    Sets requeue_not_before = now + backoff(attempt) so claim() skips the
    job until the backoff elapses. The UPDATE is predicated on the observed
    state AND the lease owner (hl-cycle-06 contract); state change + audit
    log + cost row commit in ONE transaction. A lost race raises ValueError.
    """
    queued = queue_mod.ACTIVE_TO_QUEUED.get(frm)
    if queued is None:
        # Not a requeueable pipeline state -- fail safe to the review pile.
        return _to_review(conn, job_id, owner, err,
                          "transient:%s (no queued state for %s)"
                          % (detail, frm))
    delay = backoff_delay_s(attempt)
    not_before = (datetime.now(timezone.utc)
                  + timedelta(seconds=delay)).isoformat(timespec="seconds")
    max_attempts = queue_mod.MAX_ATTEMPTS
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute(
            "UPDATE jobs SET state=?, requeue_not_before=?, error=?,"
            " lease_owner=NULL, lease_expires=NULL, updated_at=?"
            " WHERE id=? AND state=? AND lease_owner=?",
            (queued, not_before, str(err)[:2000], now(),
             job_id, frm, owner),
        )
        if cur.rowcount != 1:
            raise ValueError(
                "lease on %s is not held by %r (lost race)" % (job_id, owner)
            )
        queue_mod.log(
            conn, job_id, frm, queued,
            "transient failure, auto-requeue attempt %d/%d"
            % (attempt, max_attempts)
            + ": %s; backoff %ds" % (detail, delay),
        )
        queue_mod.log_cost(
            conn, job_id, _provider_hint(err), "attempt", 1, 0.0,
            "ACTUAL|requeue attempt %d/%d: %s (cost unmetered)"
            % (attempt, max_attempts, detail),
        )
        if own:
            conn.execute("COMMIT")
    except Exception:
        if own:
            conn.execute("ROLLBACK")
        raise
    return "requeued"


def handle_failure(conn, job_id, owner, err):
    """Classify a worker failure and route it. Returns "requeued"|"review".

    - Publish jobs and owner-waiting jobs NEVER auto-requeue.
    - Transient failures requeue (backoff) while attempts < max_attempts.
    - Everything else -- and transient failures at max attempts -- goes to
      the review pile.
    Raises ValueError for an unknown job or a lost race (same contract as
    queue.fail(); the work loop treats that as "skip").
    """
    row = conn.execute(
        "SELECT state, attempts, max_attempts FROM jobs WHERE id=?",
        (job_id,)).fetchone()
    if row is None:
        raise ValueError("unknown job %s" % job_id)
    state = row["state"]
    attempts = int(row["attempts"] or 0)
    max_attempts = int(row["max_attempts"] or queue_mod.MAX_ATTEMPTS)
    kind, detail = classify_failure(err)
    if state in PUBLISH_STATES:
        return _to_review(conn, job_id, owner, err,
                          "publish-excluded:%s" % detail)
    if state in OWNER_WAITING_STATES:
        return _to_review(conn, job_id, owner, err,
                          "owner-waiting:%s" % detail)
    if kind == "transient" and attempts < max_attempts:
        return _requeue(conn, job_id, owner, err, state, attempts, detail)
    return _to_review(conn, job_id, owner, err, "%s:%s" % (kind, detail))


def list_review(conn):
    """All failed jobs (the review pile), oldest failure first."""
    return conn.execute(
        "SELECT id, title, state, attempts, max_attempts, updated_at,"
        " review_reason, error FROM jobs WHERE state='failed'"
        " ORDER BY updated_at"
    ).fetchall()


def _clear_review_flag(conn, job_id):
    row = conn.execute(
        "SELECT id, state FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError("unknown job %s" % job_id)
    if row["state"] != "failed":
        raise ValueError(
            "job %s is in state %r, not 'failed'" % (job_id, row["state"])
        )
    conn.execute(
        "UPDATE jobs SET review_reason=NULL, updated_at=? WHERE id=?",
        (now(), job_id),
    )
    return row


def retry_review(conn, job_id):
    """Owner-cleared retry: failed -> draft (existing book edge)."""
    from . import jobs as jobs_mod  # deferred: jobs imports retry
    _clear_review_flag(conn, job_id)
    return jobs_mod.transition(conn, job_id, "draft",
                               "owner retry from review pile")


def dismiss_review(conn, job_id):
    """Owner-cleared dismiss: failed -> archived (terminal, no retry)."""
    from . import jobs as jobs_mod  # deferred: jobs imports retry
    _clear_review_flag(conn, job_id)
    return jobs_mod.transition(conn, job_id, "archived",
                               "owner dismissed from review pile")
