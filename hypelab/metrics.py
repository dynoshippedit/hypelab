"""Metrics polling with provenance (Book 2, section 11).

Every metrics row records provenance: official_api | provider_api |
user_entered | unavailable. 'unavailable' writes a row with NULL measures —
the absence is data, not a gap to paper over.

Cadence (operational, not enforced here): hourly for 24h, then daily to 14
days. Most clip performance resolves inside 72 hours.

Calibration (§6/§11) uses official_api + provider_api rows ONLY — never
user_entered. A user_entered row is the operator typing numbers from a
screenshot; it is evidence of performance but not calibration-grade.
"""
from __future__ import annotations

import sqlite3

from .util import now

#: Provenance ranks: higher = more trustworthy for calibration.
PROVENANCE_RANK = {
    "official_api": 3,
    "provider_api": 2,
    "user_entered": 1,
    "unavailable": 0,
    "unknown": 0,
}

#: Rows at or above this rank are calibration-grade.
CALIBRATION_PROVENANCES = ("official_api", "provider_api")


class MetricsError(Exception):
    """Metrics recording failed."""


def fetch_metrics(platform: str, post_url: str):
    """Fetch current metrics for a post.

    Returns (measures_dict_or_None, provenance). This build ships NO
    provider integrations, so the fetcher honestly reports 'unavailable':
    poll_metrics records a NULL row — absence as data. Provider adapters
    (official_api / provider_api) plug in here when they exist.
    """
    return None, "unavailable"


def open_posts(conn: sqlite3.Connection):
    """Posts whose clips are in posted state (still being measured)."""
    return conn.execute(
        "SELECT p.* FROM posts p JOIN clips c ON c.id = p.clip_id "
        "WHERE c.state='posted' ORDER BY p.posted_at"
    ).fetchall()


def poll_metrics(conn: sqlite3.Connection,
                 fetch=fetch_metrics) -> list[dict]:
    """Poll every open post; insert one metrics row per post.

    Uses INSERT OR REPLACE on (post_id, at): re-polling within the same
    second replaces rather than duplicates. Returns the rows written.
    """
    written = []
    for p in open_posts(conn):
        measures, prov = fetch(p["platform"], p["post_url"])
        measures = measures or {}
        at = now()
        conn.execute(
            "INSERT OR REPLACE INTO metrics(post_id, at, views, likes,"
            " comments, shares, saves, provenance)"
            " VALUES(?,?,?,?,?,?,?,?)",
            (p["id"], at, measures.get("views"), measures.get("likes"),
             measures.get("comments"), measures.get("shares"),
             measures.get("saves"), prov),
        )
        written.append({"post_id": p["id"], "at": at,
                        "provenance": prov, **measures})
    return written


def record_user_metrics(conn: sqlite3.Connection, post_id: str, *,
                        views=None, likes=None, comments=None, shares=None,
                        saves=None, note: str = "") -> dict:
    """Operator-entered metrics (typed from a screenshot, etc.).

    Provenance is user_entered, always. Include the screenshot path in the
    note when there is one. Never calibration-grade — see module docstring.
    """
    if conn.execute("SELECT 1 FROM posts WHERE id=?",
                    (post_id,)).fetchone() is None:
        raise MetricsError(f"unknown post {post_id!r}")
    at = now()
    conn.execute(
        "INSERT OR REPLACE INTO metrics(post_id, at, views, likes,"
        " comments, shares, saves, provenance)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (post_id, at, views, likes, comments, shares, saves,
         "user_entered"),
    )
    return {"post_id": post_id, "at": at, "provenance": "user_entered",
            "views": views, "likes": likes, "comments": comments,
            "shares": shares, "saves": saves, "note": note}


def best_views(conn: sqlite3.Connection, post_id: str,
               provenances=CALIBRATION_PROVENANCES):
    """Latest best-provenance views for a post (calibration-grade only)."""
    row = conn.execute(
        """SELECT views FROM metrics WHERE post_id=?
           AND provenance IN ('official_api','provider_api')
           AND views IS NOT NULL
           ORDER BY CASE provenance WHEN 'official_api' THEN 2
                                    WHEN 'provider_api' THEN 1 ELSE 0 END DESC,
                    at DESC LIMIT 1""",
        (post_id,)).fetchone()
    return row["views"] if row else None


def usd_per_clip_hour(conn: sqlite3.Connection) -> list[dict]:
    """Realized $/clip-hour by campaign (§11) — the number that decides
    whether clipping is worth doing. Operator-logged work_minutes, including
    manual upload, from the first clip."""
    rows = conn.execute(
        """SELECT c.id AS campaign_id, c.creator,
                  SUM(p.payout_usd) AS earned,
                  COUNT(DISTINCT cl.id) AS clips,
                  SUM(cl.work_minutes) / 60.0 AS hours,
                  CASE WHEN SUM(cl.work_minutes) > 0
                       THEN SUM(p.payout_usd) / (SUM(cl.work_minutes) / 60.0)
                       END AS usd_per_hour
           FROM campaigns c
           JOIN clips cl ON cl.campaign_id = c.id
           JOIN posts p ON p.clip_id = cl.id
           GROUP BY c.id ORDER BY usd_per_hour DESC"""
    ).fetchall()
    return [dict(r) for r in rows]
