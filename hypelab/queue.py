"""Book 1 queue: leases, atomic claim, heartbeat, release, fail, ledger.

Claiming moves a job's state directly (queued_X -> X-ing) via a single
conditional UPDATE, so exactly one worker wins the job. No separate task
table: the job row IS the queue entry.

Leases (improved Book 1, section 5): every claim stamps ``lease_owner``
(the worker id) and ``lease_expires`` (now + 30 min). A worker extends its
lease with ``heartbeat``. ``release`` returns an active job to its queued
state and clears the lease (expiry is not a failure — attempts unchanged).
``fail`` moves the job to ``failed`` with the error recorded; when
``attempts`` reaches ``MAX_ATTEMPTS`` the failure is marked POISON and the
job needs operator review. ``transition`` (in jobs.py) clears the lease
fields on every move.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Optional

from .util import now

#: Attempts are counted per claim; MAX_ATTEMPTS exhausted -> POISON.
MAX_ATTEMPTS = 3

#: Lease TTL stamped on claim and extended by heartbeat (30 minutes).
LEASE_TTL_S = 30 * 60

CLAIMABLE = {
    "queued_align": "aligning",
    "queued_render": "rendering",
    "queued_gates": "gating",
    # Book 2 additions: ingest/score pipeline claimable states.
    "queued_ingest": "ingesting",
    "queued_score": "scoring",
}

#: Reverse map for release(): active state -> the queued state it came from.
ACTIVE_TO_QUEUED = {dst: src for src, dst in CLAIMABLE.items()}

#: Claim priority (Book 1 section 5): align > gates > render.
_CLAIM_PRIORITY = [
    "queued_align",
    "queued_gates",
    "queued_render",
    # Book 2 additions, after the Book 1 states.
    "queued_ingest",
    "queued_score",
]


def _lease_expires() -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=LEASE_TTL_S)).isoformat(
        timespec="seconds"
    )


def claim(conn: sqlite3.Connection, owner: str,
          states: Optional[list[str]] = None) -> Optional[sqlite3.Row]:
    """Atomically claim the oldest claimable job for ``owner``.

    Wanted queued states are tried in Book 1 priority order (align >
    gates > render); FIFO within a state. For each state two atomic
    UPDATE ... RETURNING steps run:

    1. fresh queued work in that state (never attempted);
    2. an active job in that state's active counterpart whose lease has
       EXPIRED — a crashed worker's job, reclaimed by ``owner`` as a new
       attempt (attempts+1). A lease that is still live is never taken
       from another owner.

    The winning job carries ``lease_owner=owner``,
    ``lease_expires=now+30min``, and ``attempts=attempts+1`` (claiming is
    the attempt; expiry/release never consume one).

    Returns the claimed job row (in its active state), or None when no
    claimable job exists. Raises ValueError for an empty owner or an
    unknown state name.
    """
    if not owner:
        raise ValueError("claim requires a non-empty owner")
    wanted = list(states) if states is not None else list(_CLAIM_PRIORITY)
    unknown = [s for s in wanted if s not in CLAIMABLE]
    if unknown:
        raise ValueError(f"unknown claimable state(s): {unknown}")
    ordered = [s for s in _CLAIM_PRIORITY if s in wanted]
    ts = now()
    expires = _lease_expires()
    for src in ordered:
        dst = CLAIMABLE[src]
        # (1) fresh queued work
        cur = conn.execute(
            """UPDATE jobs
               SET state=?, lease_owner=?, lease_expires=?,
                   attempts=attempts+1, updated_at=?
               WHERE id=(SELECT id FROM jobs WHERE state=?
                         AND (lease_expires IS NULL OR lease_expires <= ?)
                         ORDER BY created_at LIMIT 1)
               RETURNING *""",
            (dst, owner, expires, ts, src, ts),
        )
        row = cur.fetchone()
        if row is not None:
            log(conn, row["id"], src, dst,
                f"claimed by {owner} (attempt {row['attempts']})")
            return row
        # (2) crashed-worker reclaim: active, lease expired
        cur = conn.execute(
            """UPDATE jobs
               SET lease_owner=?, lease_expires=?,
                   attempts=attempts+1, updated_at=?
               WHERE id=(SELECT id FROM jobs WHERE state=?
                         AND lease_expires IS NOT NULL
                         AND lease_expires <= ?
                         ORDER BY lease_expires LIMIT 1)
               RETURNING *""",
            (owner, expires, ts, dst, ts),
        )
        row = cur.fetchone()
        if row is not None:
            log(conn, row["id"], dst, dst,
                f"lease reclaimed by {owner} after expiry"
                f" (attempt {row['attempts']})")
            return row
    return None


def heartbeat(conn: sqlite3.Connection, job_id: str, owner: str) -> bool:
    """Extend the lease on ``job_id`` by another 30 minutes.

    Only the lease owner can heartbeat. Returns True when the lease was
    extended, False when the job is unknown or the lease is held by
    someone else.
    """
    cur = conn.execute(
        "UPDATE jobs SET lease_expires=?, updated_at=?"
        " WHERE id=? AND lease_owner=?",
        (_lease_expires(), now(), job_id, owner),
    )
    return cur.rowcount == 1


def release(conn: sqlite3.Connection, job_id: str, owner: str) -> bool:
    """Return an active job to its queued state and clear its lease.

    Allowed for the lease owner, or for anyone when the lease has expired
    (the reaper path). Lease expiry is not a failure: ``attempts`` is left
    unchanged. Returns False when a live lease is held by another owner.
    Raises ValueError for an unknown job.
    """
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown job {job_id}")
    ts = now()
    lease_owner, lease_expires = row["lease_owner"], row["lease_expires"]
    lease_live = lease_expires is not None and lease_expires > ts
    if lease_live and lease_owner != owner:
        return False
    frm = row["state"]
    dst = ACTIVE_TO_QUEUED.get(frm, frm)
    conn.execute(
        "UPDATE jobs SET state=?, lease_owner=NULL, lease_expires=NULL,"
        " updated_at=? WHERE id=?",
        (dst, ts, job_id),
    )
    if dst != frm:
        log(conn, job_id, frm, dst, f"released by {owner}; lease cleared")
    return True


def fail(conn: sqlite3.Connection, job_id: str, owner: str, err) -> sqlite3.Row:
    """Fail a leased job: state -> ``failed``, error recorded, lease cleared.

    Only the lease owner may fail its job. When ``attempts`` has reached
    ``MAX_ATTEMPTS`` the job_events note is stamped ``POISON|`` — the job
    is terminal and needs operator review (the poison-review path); below
    the limit the work loop may re-queue it while attempts remain.
    Returns the updated job row.
    """
    row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown job {job_id}")
    if row["lease_owner"] != owner:
        raise ValueError(
            f"lease on {job_id} is not held by {owner!r}"
        )
    attempts = int(row["attempts"] or 0)
    ts = now()
    err_s = str(err)
    if attempts >= MAX_ATTEMPTS:
        note = (f"POISON|attempts {attempts}/{MAX_ATTEMPTS} exhausted — "
                f"operator review required: {err_s}")
    else:
        note = err_s
    conn.execute(
        "UPDATE jobs SET state='failed', error=?,"
        " lease_owner=NULL, lease_expires=NULL, updated_at=?"
        " WHERE id=?",
        (err_s, ts, job_id),
    )
    log(conn, job_id, row["state"], "failed", note)
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def log(conn: sqlite3.Connection, job_id: str, frm, to: str, note) -> None:
    """Append one state-transition event to job_events."""
    conn.execute(
        "INSERT INTO job_events(job_id, at, from_state, to_state, note)"
        " VALUES(?,?,?,?,?)",
        (job_id, now(), frm, to, note),
    )


def charge(conn: sqlite3.Connection, job_id: str, provider: str, unit: str,
           qty: float, usd: float, note: str) -> None:
    """Record one cost line in cost_ledger with at=now().

    CONVENTION (estimated-vs-actual accounting, within the mandated schema):
      - cost ESTIMATES use a note starting with "ESTIMATE|"
        e.g. "ESTIMATE|whisper stt, 2 audio_min @ $0.006/min"
      - realized/ACTUAL costs use a note starting with "ACTUAL|"
        e.g. "ACTUAL|whisper stt billed 2026-09-28"

    The convention is documentary, not enforced: aggregate SUM(usd) over
    notes LIKE 'ESTIMATE|%' vs 'ACTUAL|%' to compare forecast against spend.
    """
    conn.execute(
        "INSERT INTO cost_ledger(job_id, at, provider, unit, qty, usd, note)"
        " VALUES(?,?,?,?,?,?,?)",
        (job_id, now(), provider, unit, qty, usd, note),
    )
