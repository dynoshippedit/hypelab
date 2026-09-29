"""Authorizations: Dino's explicit approval rows (improved Book 3, section 5).

Consent is the CREATOR's grant (consent.py). Authorization is DINO's
approval to act. They are separate tables and separate concerns.

Hard rule: no external side effect — pitch send, publish, invite — without
a recorded authorization row (who, when, what). The system has no right to
act on Dino's behalf by default. This includes the "own account, no
collaborator" path: legitimate, but never invisible.

An authorization row is an (intent, approval) pair: `intent` records what
the operator said they wanted, in their own words; the row itself is the
approval artifact.
"""
from __future__ import annotations

import sqlite3

from .util import new_id, now

ACTIONS = ("pitch", "publish", "invite")


class AuthorizationError(Exception):
    """Raised when an action is attempted without a recorded authorization."""


def record(conn: sqlite3.Connection, job_id: str, action: str,
           actor: str = "dino", platform: str | None = None,
           intent: str | None = None, note: str | None = None) -> dict:
    """Record an authorization row. Returns the row as a dict."""
    if action not in ACTIONS:
        raise AuthorizationError(
            f"unknown authorization action {action!r}; expected one of {ACTIONS}"
        )
    if conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
        raise AuthorizationError(f"unknown job {job_id}")
    aid = new_id("auth")
    ts = now()
    conn.execute(
        """INSERT INTO authorizations(id, job_id, action, actor, platform,
                                      intent, authorized_at, note)
           VALUES(?,?,?,?,?,?,?,?)""",
        (aid, job_id, action, actor, platform, intent, ts, note),
    )
    conn.commit()
    return dict(
        conn.execute("SELECT * FROM authorizations WHERE id=?", (aid,)).fetchone()
    )


def require_authorization(conn: sqlite3.Connection, job_id: str, action: str,
                          actor: str = "dino") -> dict:
    """Return the latest authorization row for (job_id, action), or raise.

    Fail closed: no row -> AuthorizationError, no override flag exists.
    """
    row = conn.execute(
        """SELECT * FROM authorizations
           WHERE job_id=? AND action=? AND actor=?
           ORDER BY authorized_at DESC LIMIT 1""",
        (job_id, action, actor),
    ).fetchone()
    if row is None:
        raise AuthorizationError(
            f"{action} on {job_id}: no recorded authorization from {actor}. "
            f"Record one with 'hypelab authorize {job_id} {action}' first."
        )
    return dict(row)


def list_for(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    """All authorization rows for a job, newest first."""
    return [
        dict(r)
        for r in conn.execute(
            "SELECT * FROM authorizations WHERE job_id=? ORDER BY authorized_at DESC",
            (job_id,),
        ).fetchall()
    ]
