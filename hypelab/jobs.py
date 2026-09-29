"""Book 1 job lifecycle: state machine + job creation.

The transition graph is the single source of truth for legal state changes.
Illegal transitions raise ValueError; every legal transition is logged to
job_events via queue.log. ``transition`` clears the lease fields on every
move (a state change always ends the previous lease).

Book 1 owns ALLOWED. Book 2 declares its additions as an explicit
extension (BOOK2_STATES). Book 3's additions arrive as a VERSIONED,
assertion-guarded migration (migrations/state_3_0.py, via
hypelab.state_migrations): the merge may only ADD keys and ADD
out-transitions — removing a transition fails hard with AssertionError.
This is the runtime invariant behind "Book 3 must not override Book 1"
(improved Book 3, section 2).
"""
from __future__ import annotations

import sqlite3

from .queue import log
from .state_migrations import STATE_MIGRATIONS, apply_state_migrations
from .util import new_id, now

# ------------------------------------------------------------------ Book 1
# Exact Book 1 transition map (improved Book 1, section 5, as concretized by
# the mode-A pipeline: script -> align -> render -> gates -> ready).
ALLOWED = {
    "draft": ("scripted", "failed"),
    "scripted": ("awaiting_media", "queued_align", "failed"),
    "awaiting_media": ("queued_align", "failed"),
    "queued_align": ("aligning", "failed"),
    # Low-confidence alignment is a gate outcome (Book 1, section 10),
    # not a crash: the audio command routes it here, never to failed.
    "aligning": ("aligned", "gate_failed", "failed"),
    "aligned": ("queued_render", "awaiting_media", "failed"),
    "queued_render": ("rendering", "failed"),
    "rendering": ("rendered", "failed"),
    "rendered": ("queued_gates", "failed"),
    "queued_gates": ("gating", "failed"),
    "gating": ("ready", "gate_failed", "failed"),
    "gate_failed": ("awaiting_media", "queued_render", "archived", "failed"),
    "ready": ("archived",),
    "archived": (),
    "failed": ("draft",),
}

# ------------------------------------------------------------------ Book 2
# Book 2 (Clip Mine) extension: ingest -> score -> cut pipeline.
# Per the improved books these states do not exist in Book 1.
BOOK2_STATES = {
    "queued_ingest": ("ingesting", "failed"),
    "ingesting": ("ingested", "failed"),
    "ingested": ("queued_score", "failed"),
    "queued_score": ("scoring", "failed"),
    "scoring": ("scored", "failed"),
    "scored": ("queued_cut", "failed"),
    "queued_cut": ("cutting", "failed"),
    "cutting": ("tray", "compliance_unknown", "failed"),
    "tray": ("posted", "archived", "failed"),
    "compliance_unknown": ("tray", "failed"),
    # "posted" has no outgoing in the Book 2 brief; it is terminal here
    # (archive directly). Kept as a key so the transition graph is closed.
    "posted": ("archived",),
}

# ------------------------------------------------------------------ Book 3
# Book 3 (Hype Layer) extension, per improved Book 3 section 2:
# ready gains pitch_sent / dry_run / scheduled; the consent and
# publish/accept handshake states below. Canonical record:
# migrations/state_3_0.py. Backwards-compatible alias:
BOOK3_STATES = dict(STATE_MIGRATIONS[0][1])

ALLOWED.update(BOOK2_STATES)
ALLOWED = apply_state_migrations(ALLOWED, STATE_MIGRATIONS)

#: Backwards-compatible alias for the merged transition map.
TRANSITIONS = ALLOWED


def new(conn: sqlite3.Connection, *, mode: str, kit_id=None, kit_version=None,
        title: str, campaign_id=None, state: str = "draft") -> str:
    """Create a job row and return its id (new_id("j")). Logs a creation event.

    Lease columns default NULL, attempts defaults 0, max_attempts defaults
    to queue.MAX_ATTEMPTS (3) via the schema.
    """
    jid = new_id("j")
    ts = now()
    conn.execute(
        """INSERT INTO jobs(id, mode, state, kit_id, kit_version, campaign_id,
                            title, created_at, updated_at)
           VALUES(?,?,?,?,?,?,?,?,?)""",
        (jid, mode, state, kit_id, kit_version, campaign_id, title, ts, ts),
    )
    log(conn, jid, None, state, "job created")
    return jid


def transition(conn: sqlite3.Connection, job_id: str, to: str, note=None) -> str:
    """Move a job to a new state.

    Raises ValueError(f"illegal transition {frm} -> {to}") when the move is
    not in ALLOWED (or the job is unknown). On success the state change and
    its job_events entry are committed atomically. The lease fields are
    cleared on every move: a transition always ends the previous lease.
    Returns `to`.
    """
    row = conn.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown job {job_id}")
    frm = row["state"]
    if to not in ALLOWED.get(frm, ()):
        raise ValueError(f"illegal transition {frm} -> {to}")
    ts = now()
    # Re-entrant: if the caller already holds an open transaction (e.g.
    # compliance inserts made through the same connection), participate in
    # it instead of starting a nested one. Only COMMIT/ROLLBACK what we
    # started; an outer transaction stays the caller's responsibility.
    own = not conn.in_transaction
    if own:
        conn.execute("BEGIN IMMEDIATE")
    try:
        conn.execute(
            "UPDATE jobs SET state=?, updated_at=?,"
            " lease_owner=NULL, lease_expires=NULL WHERE id=?",
            (to, ts, job_id),
        )
        log(conn, job_id, frm, to, note)
        if own:
            conn.execute("COMMIT")
    except Exception:
        if own:
            conn.execute("ROLLBACK")
        raise
    return to


def get(conn: sqlite3.Connection, job_id: str):
    """Return the job row, or None."""
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
