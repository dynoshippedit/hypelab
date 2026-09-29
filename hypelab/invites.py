"""Invite-status polling (improved Book 3, section 8).

poll_invites() reuses the publish adapter's get_collaborator_status and
Book 2's metrics machinery — one poller, both modes. Book 3 does not fork
the measurement layer; it points the same machinery at collab posts.

Cadence (book §8): every 30 minutes for the first 24 hours, then hourly
to 72 hours, then stop and mark accept_timeout. Most accepts happen
within a few hours or never.

targets.record_outcome: after 30 attempts you know what kind of creator
accepts — follower band, engagement rate, niche, pitch angle. A declined
invite sets the target's consent_state back to 'pitched' (they saw it and
said no to the invite — not the same as denying the relationship — but it
is never auto-re-pitched).

Adding an invite requires a recorded `invite` authorization: the system
does not contact people on its own initiative.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone

from . import authorize as authorize_mod
from . import jobs as jobs_mod
from .publish.base import Publisher
from .util import new_id, now

INVITE_STATUSES = ("pending", "accepted", "declined", "expired")
ACCEPT_TIMEOUT_HOURS = 72


class InviteError(Exception):
    """Invite refused."""


def add(conn: sqlite3.Connection, post_id: str, handle: str,
        job_id: str) -> dict:
    """Record an invite for a collaborator on a post. Requires a recorded
    `invite` authorization for the job."""
    auth = authorize_mod.require_authorization(conn, job_id, "invite")
    post = conn.execute(
        "SELECT * FROM posts WHERE id=?", (post_id,)
    ).fetchone()
    if post is None:
        raise InviteError(f"unknown post {post_id}")
    conn.execute(
        """INSERT INTO targets(handle, platform, consent_state)
           VALUES(?,'instagram','none')
           ON CONFLICT(handle, platform) DO NOTHING""",
        (handle,),
    )
    iid = new_id("invite")
    ts = now()
    conn.execute(
        """INSERT INTO invites(id, post_id, handle, invite_status, checked_at,
                               created_at)
           VALUES(?,?,?,?,?,?)""",
        (iid, post_id, handle, "pending", ts, ts),
    )
    conn.commit()
    return dict(
        conn.execute("SELECT * FROM invites WHERE id=?", (iid,)).fetchone()
    )


def _provider_post_id(conn: sqlite3.Connection, post_row_id: str) -> str:
    """Resolve the provider-side post id for a posts-table row."""
    row = conn.execute(
        "SELECT post_id FROM posts WHERE id=?", (post_row_id,)
    ).fetchone()
    if row and row["post_id"]:
        return row["post_id"]
    return post_row_id


def _age_hours(ts: str | None) -> float:
    if not ts:
        return 0.0
    try:
        dt = datetime.fromisoformat(ts)
    except ValueError:
        return 0.0
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / 3600.0


def record_outcome(conn: sqlite3.Connection, handle: str, platform: str,
                   status: str) -> None:
    """Feed the collab outcome back into the target record (book §8)."""
    row = conn.execute(
        "SELECT invite_stats_json FROM targets WHERE handle=? AND platform=?",
        (handle, platform),
    ).fetchone()
    stats = {}
    if row and row["invite_stats_json"]:
        try:
            stats = json.loads(row["invite_stats_json"])
        except (ValueError, TypeError):
            stats = {}
    stats[status] = stats.get(status, 0) + 1
    conn.execute(
        """UPDATE targets SET invite_stats_json=?, last_checked=?
           WHERE handle=? AND platform=?""",
        (json.dumps(stats), now(), handle, platform),
    )
    if status == "declined":
        # Saw it, said no to the invite — not a relationship denial.
        # Never auto-re-pitched: next pitch needs a new angle + authorization.
        conn.execute(
            "UPDATE targets SET consent_state='pitched' "
            "WHERE handle=? AND platform=?",
            (handle, platform),
        )


def poll(conn: sqlite3.Connection, publisher: Publisher,
         platform: str = "instagram") -> list[dict]:
    """Poll every pending invite through the adapter. Returns the invites
    whose status changed (or timed out)."""
    changed = []
    pending = conn.execute(
        "SELECT * FROM invites WHERE invite_status='pending'"
    ).fetchall()
    for inv in pending:
        inv = dict(inv)
        if _age_hours(inv.get("created_at")) >= ACCEPT_TIMEOUT_HOURS:
            conn.execute(
                "UPDATE invites SET invite_status='accept_timeout', checked_at=? "
                "WHERE id=?",
                (now(), inv["id"]),
            )
            record_outcome(conn, inv["handle"], platform, "accept_timeout")
            _transition_job(conn, inv, "accept_timeout")
            changed.append({**inv, "invite_status": "accept_timeout"})
            continue
        try:
            provider_pid = _provider_post_id(conn, inv["post_id"])
            rows = publisher.get_collaborator_status(provider_pid)
        except Exception as e:  # adapter failure is not an invite outcome
            conn.execute(
                "UPDATE invites SET checked_at=? WHERE id=?", (now(), inv["id"])
            )
            continue
        want = inv["handle"].lstrip("@").lower()
        for r in rows:
            if str(r.get("username", "")).lower() != want:
                continue
            st = str(r.get("invite_status", "")).lower()
            if st not in ("accepted", "declined", "pending"):
                continue
            conn.execute(
                "UPDATE invites SET invite_status=?, checked_at=? WHERE id=?",
                (st, now(), inv["id"]),
            )
            if st in ("accepted", "declined"):
                record_outcome(conn, inv["handle"], platform, st)
                _transition_job(conn, inv, st)
                changed.append({**inv, "invite_status": st})
            break
    conn.commit()
    return changed


def _transition_job(conn: sqlite3.Connection, inv: dict, status: str) -> None:
    post = conn.execute(
        "SELECT job_id FROM posts WHERE id=?", (inv["post_id"],)
    ).fetchone()
    if not post or not post["job_id"]:
        return
    job = jobs_mod.get(conn, post["job_id"])
    if job is None or job["state"] != "awaiting_accept":
        return
    try:
        jobs_mod.transition(
            conn, post["job_id"], status, f"{inv['handle']} {status}"
        )
    except ValueError:
        pass  # already moved; the invite row is the record of truth


def poll_invite_metrics(conn: sqlite3.Connection,
                        fixture_metrics: dict[str, dict]) -> list[dict]:
    """Write metrics rows for invite-linked posts from recorded fixtures.

    This reuses Book 2's metrics table and provenance vocabulary; the
    fixture values stand in for provider API rows (provenance
    'provider_api', reject_note marking the fixture source). Real measured
    data awaits Dino-authorized real posts.
    """
    written = []
    post_ids = [
        r["post_id"]
        for r in conn.execute("SELECT DISTINCT post_id FROM invites").fetchall()
    ]
    # Fixtures are keyed by provider post id; resolve through posts.post_id.
    provider_ids = {
        pid: _provider_post_id(conn, pid) for pid in post_ids
    }
    for pid, provider_pid in provider_ids.items():
        fx = fixture_metrics.get(provider_pid)
        if not fx:
            continue
        at = now()
        conn.execute(
            """INSERT OR REPLACE INTO metrics(post_id, at, views, likes,
                 comments, shares, saves, provenance, reject_note)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (pid, at, fx.get("views"), fx.get("likes"), fx.get("comments"),
             fx.get("shares"), fx.get("saves"), "provider_api",
             "recorded fixture (dry-run build; real posts are Dino-gated)"),
        )
        written.append({"post_id": pid, "at": at, **fx})
    conn.commit()
    return written
