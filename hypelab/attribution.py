"""Attribution: what_worked (Book 2, section 11).

Attribute post performance back to the signals that selected each moment.
Vocabulary is CORRELATIONS ONLY — "averaged", "correlated with". Nothing in
this data supports causal claims: no randomization, no control group, and
every confound (posting time, account size, campaign, platform algorithm
week) rides along. The module enforces this: summary strings are built from
fixed correlational templates.

Code-enforced guards:
  - no dimension is READ as signal below n=30 (displayed as below-threshold);
  - no weight-change PROPOSAL below n=50 posted clips with measured
    (calibration-grade) views;
  - proposals are written to weights_v2_candidate.json with status
    "proposed" and promoted to weights_v2.json ("calibrated") ONLY by
    explicit operator approval (promote_weights).

Calibration reads official_api + provider_api metrics only — never
user_entered.
"""
from __future__ import annotations

import json
import math
import shutil
import sqlite3
import statistics
from collections import defaultdict
from pathlib import Path

from .metrics import CALIBRATION_PROVENANCES
from .util import now

#: Minimum n to read a dimension as signal (a floor, not a target).
READ_MIN_N = 30

#: Minimum posted clips with measured views before any weight proposal.
PROPOSE_MIN_N = 50


class AttributionError(Exception):
    """Attribution refused (below sample-size guards, bad inputs)."""


def _bucket(v: float) -> str:
    return f"{math.floor(float(v) * 10) / 10:.1f}"


def attribute(conn: sqlite3.Connection, lookback_days: int = 30) -> int:
    """Attribute measured views back to signal buckets; upsert what_worked.

    Returns the number of (dimension, value) rows written. Reads only
    calibration-grade metrics (official_api + provider_api); prefers the
    best provenance per post. user_entered rows are evidence, not
    calibration input.
    """
    prov_list = ",".join(f"'{p}'" for p in CALIBRATION_PROVENANCES)
    rows = conn.execute(
        f"""WITH best AS (
              SELECT m0.post_id,
                     (SELECT mx.views FROM metrics mx
                      WHERE mx.post_id = m0.post_id
                        AND mx.provenance IN ({prov_list})
                        AND mx.views IS NOT NULL
                      ORDER BY CASE mx.provenance
                                 WHEN 'official_api' THEN 2 ELSE 1 END DESC,
                               mx.at DESC LIMIT 1) AS views
              FROM (SELECT DISTINCT post_id FROM metrics) m0)
             SELECT m.signals_json, m.confidence, m.weight_version,
                    best.views AS views
             FROM moments m
             JOIN clips c ON c.moment_id = m.id
             JOIN posts p ON p.clip_id = c.id
             JOIN best ON best.post_id = p.id
             WHERE best.views IS NOT NULL
               AND p.posted_at > date('now', ?)""",
        (f"-{int(lookback_days)} days",),
    ).fetchall()

    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in rows:
        try:
            sig = json.loads(r["signals_json"] or "{}")
        except ValueError:
            continue
        parts = sig.get("parts") or {}
        for part, val in parts.items():
            try:
                buckets[("signal_" + part, _bucket(val))].append(r["views"])
            except (TypeError, ValueError):
                continue
        for hit in sig.get("hits") or []:
            buckets[("pattern", str(hit))].append(r["views"])
        try:
            buckets[("confidence", _bucket(r["confidence"]))].append(r["views"])
        except (TypeError, ValueError):
            pass
        buckets[("weight_version", str(r["weight_version"] or "unrecorded"))
                ].append(r["views"])

    n = 0
    for (dim, val), views in buckets.items():
        conn.execute(
            "INSERT INTO what_worked(dimension, value, n, mean_perf,"
            " updated_at) VALUES(?,?,?,?,?)"
            " ON CONFLICT(dimension, value) DO UPDATE SET"
            " n=excluded.n, mean_perf=excluded.mean_perf,"
            " updated_at=excluded.updated_at",
            (dim, str(val), len(views), statistics.mean(views), now()),
        )
        n += 1
    return n


def read_dimensions(conn: sqlite3.Connection):
    """what_worked rows split into signal (n>=30) vs below-threshold.

    Returns {"signal": [...], "below_threshold": [...]}. A dimension below
    n=30 is never read as signal — it is listed, not interpreted.
    """
    rows = [dict(r) for r in conn.execute(
        "SELECT dimension, value, n, mean_perf, updated_at FROM what_worked"
        " ORDER BY dimension, value").fetchall()]
    return {
        "signal": [r for r in rows if (r["n"] or 0) >= READ_MIN_N],
        "below_threshold": [r for r in rows if (r["n"] or 0) < READ_MIN_N],
    }


def describe_row(row: dict) -> str:
    """Correlational summary — fixed template, no causal language."""
    return (f"{row['dimension']}={row['value']}: clips averaged "
            f"{row['mean_perf']:.0f} views (n={row['n']})")


def _measured_post_count(conn: sqlite3.Connection) -> int:
    prov_list = ",".join(f"'{p}'" for p in CALIBRATION_PROVENANCES)
    row = conn.execute(
        f"SELECT COUNT(DISTINCT post_id) AS n FROM metrics"
        f" WHERE provenance IN ({prov_list}) AND views IS NOT NULL"
    ).fetchone()
    return row["n"] or 0


def _bucket_means(conn: sqlite3.Connection, dimension: str):
    """{value: (n, mean)} for one dimension, n>=READ_MIN_N buckets only."""
    rows = conn.execute(
        "SELECT value, n, mean_perf FROM what_worked"
        " WHERE dimension=? AND n>=?", (dimension, READ_MIN_N)).fetchall()
    return {r["value"]: (r["n"], r["mean_perf"]) for r in rows}


def propose_weights(conn: sqlite3.Connection, weights_dir,
                    base_version: str = "v1") -> dict:
    """Propose a re-weighting from attribution data.

    Guard: refuses below PROPOSE_MIN_N posted clips with measured
    calibration-grade views. The proposal is a heuristic nudge, documented
    in the file: for each signal part, compare the mean views of high
    (>=0.7) vs low (<=0.3) buckets; a >=20% gap nudges the part's weight by
    10% (up when high buckets averaged better), then renormalize. Written
    to weights_v2_candidate.json with status "proposed" — never applied.

    Returns {"path", "basis", "sets"}.
    """
    n_posts = _measured_post_count(conn)
    if n_posts < PROPOSE_MIN_N:
        raise AttributionError(
            f"refusing weight proposal: {n_posts} measured posts < "
            f"minimum {PROPOSE_MIN_N} (small-n 'insights' are how you "
            "confidently tune toward noise)")
    from .score import load_weights

    base = load_weights(weights_dir, version=base_version)
    basis, new_sets = {}, {}
    for set_name, wset in base["sets"].items():
        nudged = dict(wset)
        for part, w in wset.items():
            means = _bucket_means(conn, "signal_" + part)
            highs = [m for v, (_n, m) in means.items() if float(v) >= 0.7]
            lows = [m for v, (_n, m) in means.items() if float(v) <= 0.3]
            if not highs or not lows:
                continue
            hi, lo = statistics.mean(highs), statistics.mean(lows)
            if hi > lo * 1.2:
                nudged[part] = round(w * 1.1, 4)
                basis[f"{set_name}.{part}"] = (
                    f"high buckets averaged {hi:.0f} vs low {lo:.0f} views: "
                    f"weight {w} -> {nudged[part]} (proposal, not applied)")
            elif lo > hi * 1.2:
                nudged[part] = round(w * 0.9, 4)
                basis[f"{set_name}.{part}"] = (
                    f"low buckets averaged {lo:.0f} vs high {hi:.0f} views: "
                    f"weight {w} -> {nudged[part]} (proposal, not applied)")
        total = sum(nudged.values()) or 1.0
        new_sets[set_name] = {k: round(v / total, 4)
                              for k, v in nudged.items()}
    doc = {
        "version": "v2",
        "status": "proposed",
        "calibrated_on": None,
        "proposed_at": now(),
        "proposed_from": base.get("version"),
        "measured_posts": n_posts,
        "method": "high-vs-low bucket gradient nudge (heuristic); "
                  "operator review required before promotion",
        "basis": basis,
        "sets": new_sets,
    }
    d = Path(weights_dir)
    path = d / "weights_v2_candidate.json"
    path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {"path": str(path), "basis": basis, "sets": new_sets}


def promote_weights(weights_dir, candidate: str | Path,
                    operator: str) -> dict:
    """Explicit operator approval: promote a proposal to weights_v2.json.

    The old version keeps scoring until this runs. Promotion is the only
    way a new weight set becomes live — never automatic.
    """
    cand = Path(candidate)
    try:
        doc = json.loads(cand.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise AttributionError(f"cannot read candidate: {e}")
    if doc.get("status") != "proposed":
        raise AttributionError(
            f"candidate status is {doc.get('status')!r}, not 'proposed' — "
            "only proposed weight sets can be promoted")
    doc["status"] = "calibrated"
    doc["calibrated_on"] = now()
    doc["approved_by"] = operator
    doc["approved_at"] = now()
    d = Path(weights_dir)
    dest = d / "weights_v2.json"
    dest.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
    return {"path": str(dest), "version": doc.get("version"),
            "approved_by": operator}
