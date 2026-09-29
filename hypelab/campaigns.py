"""Campaigns as versioned data (Book 2, section 3).

A campaign is a JSON file, never a code change. Rules are versioned:
bumping rules_version is a deliberate operator action (never a background
mutation); the old version stays queryable via rules_provenance history.

rate_basis is observed | vendor_claim | unknown. A vendor's "average $/1k"
enters here only as vendor_claim — never as a number the system acts on as
fact, and NEVER hard-coded into scoring or tray prioritization.
"""
from __future__ import annotations

import json
import sqlite3

from .util import new_id, now

RATE_BASES = ("observed", "vendor_claim", "unknown")

REQUIRED_TOP_KEYS = ("id", "platforms", "rules")


class CampaignError(Exception):
    """Invalid campaign data or unknown campaign."""


def _parse(row: sqlite3.Row) -> dict:
    d = dict(row)
    for k in ("platforms", "rules_json", "rules_provenance",
              "budget_provenance", "submission_json"):
        v = d.get(k)
        d[k] = json.loads(v) if v else None
    d["rules"] = d.pop("rules_json") or {}
    d["platforms"] = d.pop("platforms") or []
    return d


def validate(data: dict) -> list[str]:
    """Return a list of problems (empty = valid)."""
    problems = []
    if not isinstance(data, dict):
        return ["campaign JSON must be an object"]
    for k in REQUIRED_TOP_KEYS:
        if k not in data:
            problems.append(f"missing required key: {k!r}")
    if not isinstance(data.get("id"), str) or not data["id"]:
        problems.append("id must be a non-empty string")
    if not isinstance(data.get("platforms"), list) or not data["platforms"]:
        problems.append("platforms must be a non-empty list")
    if not isinstance(data.get("rules"), dict):
        problems.append("rules must be an object")
    rb = data.get("rate_basis", "observed")
    if rb not in RATE_BASES:
        problems.append(f"rate_basis must be one of {RATE_BASES}, got {rb!r}")
    return problems


def add(conn: sqlite3.Connection, data: dict) -> str:
    """Insert a campaign row from a validated JSON dict. Returns the id.

    rules_version starts at 1. A missing rules_provenance is stored as NULL —
    the compliance gate treats unprovenanced rules as UNKNOWN (a rumor, not
    a rule), never as pass.
    """
    problems = validate(data)
    if problems:
        raise CampaignError("invalid campaign: " + "; ".join(problems))
    cid = data["id"]
    if conn.execute("SELECT 1 FROM campaigns WHERE id=?", (cid,)).fetchone():
        raise CampaignError(f"campaign {cid!r} already exists")
    prov = data.get("rules_provenance")
    conn.execute(
        """INSERT INTO campaigns(id, marketplace, creator, rate_per_1k_usd,
                                 rate_basis, budget_total_usd, budget_seen_usd,
                                 budget_checked, budget_provenance, platforms,
                                 rules_json, rules_version, rules_provenance,
                                 submission_json, state, created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            cid,
            data.get("marketplace"),
            data.get("creator"),
            data.get("rate_per_1k_usd"),
            data.get("rate_basis", "observed"),
            data.get("budget_total_usd"),
            data.get("budget_seen_usd"),
            data.get("budget_checked"),
            json.dumps(data["budget_provenance"])
            if data.get("budget_provenance") else None,
            json.dumps(data["platforms"]),
            json.dumps(data["rules"]),
            1,
            json.dumps(prov) if prov else None,
            json.dumps(data["submission"]) if data.get("submission") else None,
            data.get("state", "active"),
            now(),
        ),
    )
    return cid


def load(conn: sqlite3.Connection, campaign_id: str) -> dict:
    """Load a campaign row with JSON fields parsed. Raises CampaignError."""
    row = conn.execute(
        "SELECT * FROM campaigns WHERE id=?", (campaign_id,)
    ).fetchone()
    if row is None:
        raise CampaignError(f"unknown campaign {campaign_id!r}")
    return _parse(row)


def list_all(conn: sqlite3.Connection) -> list[dict]:
    return [
        _parse(r)
        for r in conn.execute("SELECT * FROM campaigns ORDER BY id").fetchall()
    ]


def bump_rules(conn: sqlite3.Connection, campaign_id: str, rules: dict,
               provenance: dict) -> int:
    """Deliberate operator action: replace rules, version+1, new provenance.

    ``provenance`` = {who, source_url, captured_at}. The previous version's
    rules stay in the audit trail via compliance_log rows that recorded the
    old rules_version — already-verified clips keep their history.
    """
    camp = load(conn, campaign_id)
    if not isinstance(rules, dict) or not rules:
        raise CampaignError("bump_rules needs a non-empty rules object")
    if not isinstance(provenance, dict) or not provenance.get("who"):
        raise CampaignError(
            "bump_rules needs provenance {who, source_url, captured_at}"
        )
    new_version = int(camp["rules_version"]) + 1
    conn.execute(
        "UPDATE campaigns SET rules_json=?, rules_version=?,"
        " rules_provenance=? WHERE id=?",
        (json.dumps(rules), new_version, json.dumps(provenance), campaign_id),
    )
    return new_version


def refresh_budget(conn: sqlite3.Connection, campaign_id: str,
                   seen_usd: float, provenance: str) -> None:
    """Record an OBSERVED remaining-budget snapshot with timestamp.

    A budget number without a timestamp is a rumor; budget_seen_usd is
    never assumed, only observed.
    """
    load(conn, campaign_id)  # raises if unknown
    conn.execute(
        "UPDATE campaigns SET budget_seen_usd=?, budget_checked=?,"
        " budget_provenance=? WHERE id=?",
        (float(seen_usd), now(), provenance, campaign_id),
    )


def compliance_is_stale(conn: sqlite3.Connection, clip_id: str) -> bool:
    """True when the campaign's live rules_version differs from the version
    the clip's compliance record was checked against (Book 2, section 3)."""
    row = conn.execute(
        "SELECT c.rules_version AS live, "
        "       json_extract(cl.compliance_json,'$.rules_version') AS used "
        "FROM clips cl JOIN campaigns c ON c.id = cl.campaign_id "
        "WHERE cl.id=?",
        (clip_id,),
    ).fetchone()
    if row is None:
        raise CampaignError(f"unknown clip {clip_id!r}")
    if row["used"] is None:
        return True  # no compliance record: treat as stale, re-check first
    return row["live"] != row["used"]


def get_rule_provenance(conn: sqlite3.Connection, campaign_id: str):
    """The rules_provenance dict, or None when the rules are a rumor."""
    camp = load(conn, campaign_id)
    return camp.get("rules_provenance")


def new_source_id() -> str:
    return new_id("src")
