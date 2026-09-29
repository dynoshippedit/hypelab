"""Closing the loop (improved Book 3, section 9).

feed_back(): attribute collab-post outcomes to production decisions —
writes Book 2's what_worked table (the attribution prerequisite) plus a
feedback_runs audit row.

priors(): the read side — the part that makes it a loop rather than a
report. min_n=8 is a GUARD, not a formality, and it is code-enforced:
below the threshold the loop falls back to kit defaults. This guard is
distinct from Book 2's attribution guards (n>=30 to read a dimension,
n>=50 to propose weight changes) — Book 3's priors steer production
decisions, so they carry their own threshold.

The book's corrected sample table marks collab_accepted at n=7 as
"(n<8, not applied)". This module does exactly that: rows below min_n
are stored with applied=0 and are never returned as production priors.
"""
from __future__ import annotations

import json
import sqlite3
from collections import defaultdict
from pathlib import Path

from .util import now

#: Production-prior guard: below this n, the loop falls back to kit
#: defaults. With four data points you are fitting noise.
MIN_N = 8

PRIORS_DIRNAME = "priors"


class FeedbackError(Exception):
    """Feedback refused (bad inputs)."""


def _best_views(conn: sqlite3.Connection, post_id: str):
    row = conn.execute(
        """SELECT MAX(views) v FROM metrics
           WHERE post_id=? AND views IS NOT NULL""",
        (post_id,),
    ).fetchone()
    return row["v"] if row else None


def feed_back(conn: sqlite3.Connection) -> dict:
    """Attribute measured collab-post outcomes into what_worked.

    Buckets (dimension, value) -> views:
      - ("collab_" + invite_status, "n") for posts with an invite outcome
      - ("collaborator_count", str(k))
      - ("platform", platform)
      - ("has_collaborators", "yes"/"no")
    Plus the book's EDL-based buckets when the job has an EDL with beats
    (hook length, beat count, caption style, music, duration).
    """
    posts = conn.execute(
        """SELECT p.id AS post_id, p.platform, p.job_id,
                  (SELECT i.invite_status FROM invites i
                   WHERE i.post_id = p.id
                   ORDER BY i.checked_at DESC LIMIT 1) AS invite_status,
                  (SELECT COUNT(*) FROM invites i2
                   WHERE i2.post_id = p.id) AS n_invites
           FROM posts p"""
    ).fetchall()

    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    consumed = 0
    for p in posts:
        views = _best_views(conn, p["post_id"])
        if views is None:
            continue
        consumed += 1
        if p["invite_status"]:
            buckets[("collab_" + p["invite_status"], "n")].append(views)
        buckets[("collaborator_count", str(p["n_invites"] or 0))].append(views)
        buckets[("platform", p["platform"])].append(views)
        buckets[("has_collaborators",
                 "yes" if (p["n_invites"] or 0) > 0 else "no")].append(views)
        # Book 2 EDL buckets when available (book §9, guarded).
        edl = conn.execute(
            """SELECT render_json FROM edls WHERE job_id=?
               ORDER BY version DESC LIMIT 1""",
            (p["job_id"],),
        ).fetchone()
        if edl:
            try:
                e = json.loads(edl["render_json"])
                beats = e.get("beats") or []
                if beats:
                    hook_len = beats[0]["t_out"] - beats[0]["t_in"]
                    buckets[("hook_len_s",
                             f"{hook_len:.1f}")].append(views)
                    buckets[("beat_count", str(len(beats)))].append(views)
                    buckets[("duration_s",
                             f"{beats[-1]['t_out']:.0f}")].append(views)
                style = ((e.get("captions") or {}).get("style"))
                if style:
                    buckets[("caption_style", style)].append(views)
                if (e.get("audio") or {}).get("music"):
                    buckets[("music", "yes")].append(views)
            except (ValueError, KeyError, TypeError):
                pass

    import statistics

    for (dim, val), vs in buckets.items():
        mean = statistics.fmean(vs)
        conn.execute(
            """INSERT INTO what_worked(dimension, value, n, mean_perf, updated_at)
               VALUES(?,?,?,?,?)
               ON CONFLICT(dimension, value) DO UPDATE SET
                 n=excluded.n, mean_perf=excluded.mean_perf,
                 updated_at=excluded.updated_at""",
            (dim, val, len(vs), mean, now()),
        )
    conn.execute(
        "INSERT INTO feedback_runs(at, rows_consumed, note) VALUES(?,?,?)",
        (now(), consumed, f"{len(buckets)} buckets upserted"),
    )
    conn.commit()
    return {"rows_consumed": consumed, "buckets": len(buckets)}


def priors(conn: sqlite3.Connection, min_n: int = MIN_N) -> dict:
    """Read side of the loop. Returns per-dimension rows with an explicit
    `applied` flag: applied=True iff n >= min_n. Below the guard the loop
    falls back to kit defaults — the caller must honor `applied`."""
    out: dict[str, list[dict]] = {}
    for r in conn.execute(
        "SELECT dimension, value, n, mean_perf FROM what_worked ORDER BY dimension"
    ).fetchall():
        out.setdefault(r["dimension"], []).append({
            "value": r["value"],
            "n": r["n"],
            "mean_perf": r["mean_perf"],
            "applied": r["n"] >= min_n,
            "min_n": min_n,
        })
    return out


def best_value(conn: sqlite3.Connection, dimension: str,
               min_n: int = MIN_N) -> dict | None:
    """The production prior for one dimension: highest mean_perf among
    applied (n >= min_n) rows. None when nothing clears the guard."""
    rows = [
        r for r in priors(conn, min_n).get(dimension, []) if r["applied"]
    ]
    if not rows:
        return None
    return max(rows, key=lambda r: (r["mean_perf"] or 0.0))


def snapshot_priors(conn: sqlite3.Connection, root: str | Path,
                    min_n: int = MIN_N) -> Path:
    """Write a versioned priors.json: priors/priors_v<N>.json. The version
    counter is monotonic; old versions are never overwritten."""
    root = Path(root)
    pdir = root / PRIORS_DIRNAME
    pdir.mkdir(parents=True, exist_ok=True)
    existing = [
        int(p.stem.split("_v")[1])
        for p in pdir.glob("priors_v*.json")
        if p.stem.split("_v")[1].isdigit()
    ]
    version = (max(existing) + 1) if existing else 1
    data = priors(conn, min_n)
    for dim, rows in data.items():
        for r in rows:
            conn.execute(
                """INSERT INTO priors(dimension, value, n, mean_perf, min_n,
                                      applied, priors_version, updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(dimension, value, priors_version) DO UPDATE SET
                     n=excluded.n, mean_perf=excluded.mean_perf,
                     applied=excluded.applied, updated_at=excluded.updated_at""",
                (dim, r["value"], r["n"], r["mean_perf"], min_n,
                 1 if r["applied"] else 0, version, now()),
            )
    conn.commit()
    out = pdir / f"priors_v{version}.json"
    payload = {
        "version": version,
        "min_n": min_n,
        "at": now(),
        "dimensions": {
            dim: [
                {k: v for k, v in r.items()}
                for r in rows
            ]
            for dim, rows in data.items()
        },
        "note": ("Rows with applied=false sit below the min_n guard and are "
                 "NOT production priors — the loop falls back to kit defaults."),
    }
    tmp = out.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(out)
    return out
