"""The compliance gate (Book 2, section 9).

Runs after render, before the tray, and again at submission if rules changed.
Every check is money: clips are rejected at verification, after views have
accrued — every rule the gate catches is revenue that would otherwise have
been lost outright.

Every check returns one of three outcomes — PASS, FAIL, or UNKNOWN — and
UNKNOWN routes to a human. The gate fails closed: a clip enters the tray
only when every check is PASS. UNKNOWN never auto-passes.

``clip`` dict fields used:
  id, job_id, path, caption, burned_text, ocr_confidence (1.0 when the
  burned captions are generated from known words, not OCR'd), overlays_text
  (list of overlay strings we rendered), duration_s, source_url,
  audio_provenance, mixed_music (bool), watermark_verified (bool),
  target_aspect ("9:16").
``campaign`` is the parsed campaigns.load() dict.
"""
from __future__ import annotations

import json
import sqlite3

from . import jobs as jobs_mod
from .util import now

#: Machine checks, in book order.
CHECKS = [
    "duration", "handle_present", "hashtags_present", "credit_present",
    "banned_words", "watermark", "aspect", "platform_limits",
    "source_allowed", "music_policy",
]

PASS, FAIL, UNKNOWN = "pass", "fail", "unknown"

#: Checks whose governing rule lives in the campaign rules (vs format facts
#: like aspect). When the rules have no provenance (a rumor, not a rule),
#: these checks go UNKNOWN instead of pass.
RULE_GOVERNED = {
    "duration", "handle_present", "hashtags_present", "credit_present",
    "banned_words", "watermark", "source_allowed", "music_policy",
}


class ComplianceError(Exception):
    """Compliance plumbing failed (not a check outcome)."""


# ------------------------------------------------------------------ checks

def chk_duration(clip, rules):
    dur = float(clip.get("duration_s") or 0.0)
    lo, hi = float(rules.get("min_s", 0)), float(rules.get("max_s", 1e9))
    if lo <= dur <= hi:
        return PASS, f"{dur:.1f}s within [{lo:.0f},{hi:.0f}]"
    return FAIL, f"{dur:.1f}s outside [{lo:.0f},{hi:.0f}]"


def chk_handle_present(clip, rules):
    h = rules.get("required_handle")
    if not h:
        return PASS, "n/a: no required_handle"
    where = rules.get("handle_placement", "caption")
    caption = (clip.get("caption") or "").lower()
    if "caption" in where:
        if h.lower() in caption:
            return PASS, "in caption"
        return FAIL, f"missing {h} in caption"
    if "overlay" in where:
        # We know exactly which overlays we rendered; OCR of the frame is
        # the fallback and it is inconclusive without an OCR binary.
        texts = [t.lower() for t in (clip.get("overlays_text") or [])]
        if any(h.lower() in t for t in texts):
            return PASS, "in overlay (render record)"
        return UNKNOWN, f"ocr-inconclusive for {h} (no OCR binary; " \
                        "cannot prove overlay absence)"
    return FAIL, f"missing {h}"


def chk_hashtags_present(clip, rules):
    required = rules.get("required_hashtags") or []
    if not required:
        return PASS, "n/a: no required hashtags"
    caption = (clip.get("caption") or "").lower()
    missing = [t for t in required if t.lower() not in caption]
    if missing:
        return FAIL, f"missing hashtags: {', '.join(missing)}"
    return PASS, "all required hashtags present"


def chk_credit_present(clip, rules):
    credit = rules.get("required_credit")
    if not credit:
        return PASS, "n/a: no required credit"
    if credit.lower() in (clip.get("caption") or "").lower():
        return PASS, "credit in caption"
    return FAIL, f"missing credit {credit!r}"


def chk_banned_words(clip, rules):
    banned = rules.get("banned_words") or []
    if not banned:
        return PASS, "n/a: no banned words"
    text = ((clip.get("caption") or "") + " "
            + (clip.get("burned_text") or "")).lower()
    hits = [w for w in banned if w.lower() in text]
    if hits:
        return FAIL, f"banned: {', '.join(hits)}"
    # The burned captions are generated from known word timings
    # (ocr_confidence 1.0), not OCR'd — absence is provable. Below the
    # threshold we cannot prove absence: UNKNOWN, never auto-pass.
    if float(clip.get("ocr_confidence", 1.0)) < 0.8:
        return UNKNOWN, "burned-text OCR below confidence threshold"
    return PASS, "clean"


def chk_watermark(clip, rules):
    if not rules.get("watermark_required"):
        return PASS, "n/a: watermark not required"
    if clip.get("watermark_verified"):
        return PASS, "watermark verified"
    return UNKNOWN, "required watermark's presence cannot be confirmed " \
                    "(no template match available)"


def chk_aspect(clip, rules):
    from .util import ffprobe, MediaError

    target = clip.get("target_aspect", "9:16")
    want = {"9:16": 9 / 16, "1:1": 1.0, "16:9": 16 / 9}.get(target, 9 / 16)
    try:
        info = ffprobe(clip["path"])
    except (MediaError, KeyError) as e:
        return UNKNOWN, f"cannot probe clip: {e}"
    w, h = info.get("width"), info.get("height")
    if not w or not h:
        return UNKNOWN, "probe returned no dimensions"
    ratio = w / h
    if abs(ratio - want) / want < 0.01:
        return PASS, f"{w}x{h} = {target}"
    return FAIL, f"{w}x{h} is not {target}"


def chk_platform_limits(clip, rules):
    platforms = clip.get("platforms") or []
    if not platforms:
        return FAIL, "no target platforms recorded"
    return PASS, f"platforms: {', '.join(platforms)}"


def chk_source_allowed(clip, rules):
    allow = rules.get("source_allowlist") or []
    url = (clip.get("source_url") or "")
    if not allow:
        return PASS, "n/a: no allowlist recorded"
    u = url.lower()
    if any(a.lower() in u for a in allow if a):
        return PASS, "source on allowlist"
    # Not on the allowlist and not clearly off it (redirects, embeds,
    # re-uploads, short links): a human verifies against rules_provenance.
    if any(tok in u for tok in ("embed", "youtu.be", "list=", "/shorts/")):
        return UNKNOWN, f"source {url!r}: ambiguous vs allowlist"
    return FAIL, f"source {url!r} not on allowlist"


def chk_music_policy(clip, rules):
    policy = rules.get("music_policy")
    if not policy:
        return PASS, "n/a: no music policy"
    if policy != "original_audio_only":
        return UNKNOWN, f"unhandled music_policy {policy!r}"
    if clip.get("mixed_music"):
        return FAIL, "mixed music bed under original_audio_only"
    prov = clip.get("audio_provenance") or "unknown"
    if prov in ("campaign_supplied", "platform_mechanism",
                "explicit_permission", "original_verified"):
        return PASS, f"audio provenance: {prov}"
    return UNKNOWN, "music_rights_unproven: source audio provenance cannot " \
                    "be established (remix? library track? creator's own bed?)"


_CHECK_FNS = {name: globals()[f"chk_{name}"] for name in CHECKS}


# ------------------------------------------------------------------ gate

def check(conn: sqlite3.Connection, clip: dict, campaign: dict) -> dict:
    """Run every check and write the compliance_log row.

    Returns the compliance record (stored as clips.compliance_json).
    ``record["passed"]`` is True only when every check passed.

    NOTE (deliberate deviation from the book's snippet): check() does NOT
    transition the job. A job can carry several clips; per-clip transitions
    would strand the job on the first outcome (e.g. failed -> ... has no
    path to compliance_unknown). The caller (``hypelab cut``) aggregates
    all clip outcomes and routes the job once via route_job().
    """
    rules = campaign.get("rules") or {}
    provenanced = bool(campaign.get("rules_provenance"))
    results = []
    for name in CHECKS:
        if name in RULE_GOVERNED and not provenanced:
            outcome, detail = UNKNOWN, \
                f"rule_unprovenanced:{name} (rumor, not a rule)"
        else:
            try:
                outcome, detail = _CHECK_FNS[name](clip, rules)
            except Exception as e:  # a check that crashes is inconclusive
                outcome, detail = UNKNOWN, f"check error: {e}"
        results.append({"check": name, "outcome": outcome, "detail": detail})

    unknowns = [c["check"] for c in results if c["outcome"] == UNKNOWN]
    failed = [c["check"] for c in results if c["outcome"] == FAIL]
    passed = not failed and not unknowns
    record = {
        "rules_version": campaign.get("rules_version"),
        "checked_at": now(),
        "passed": passed,
        "results": results,
        "unknowns": unknowns,
        "failed": failed,
    }
    conn.execute(
        "INSERT INTO compliance_log(clip_id, at, rules_version, passed,"
        " unknown_reasons, decided_by, note) VALUES(?,?,?,?,?,?,?)",
        (clip["id"], now(), campaign.get("rules_version"),
         1 if passed else (0 if failed else None),
         json.dumps(unknowns), "machine",
         "auto-gate; unknowns routed to human" if unknowns else None),
    )
    return record


def regated_if_stale(conn: sqlite3.Connection, clip_row,
                     campaign: dict) -> dict:
    """Re-run the compliance gate on a rendered clip when the campaign
    rules changed since the clip was gated (Book 2 section 9: the gate
    runs again at submission if rules changed; section 3: the tray
    refuses to hand over a clip with stale compliance — it re-runs the
    gate first).

    ``clip_row`` is a clips row (sqlite3.Row or dict); ``campaign`` is the
    parsed campaigns.load() dict. Returns
    {"clip_id", "regated", "passed", "state"}.

    The clip row is updated in place: a failed re-gate moves it to
    failed/compliance_unknown with the fresh record; a passing re-gate
    refreshes compliance_json (new rules_version). The JOB is not touched
    — callers aggregate via route_job() (cut) or their own transition
    (record_posted).
    """
    from .util import ffprobe

    clip = dict(clip_row)
    prev = json.loads(clip.get("compliance_json") or "{}")
    if campaign.get("rules_version") == prev.get("rules_version"):
        return {"clip_id": clip["id"], "regated": False,
                "passed": bool(prev.get("passed")), "state": clip["state"]}
    check_clip = {
        "id": clip["id"], "job_id": clip["job_id"], "path": clip["path"],
        "caption": clip.get("caption") or "",
        "burned_text": "", "ocr_confidence": 1.0,
        "overlays_text": [], "duration_s": None,
        "source_url": "", "audio_provenance": "campaign_supplied",
        "mixed_music": False, "watermark_verified": False,
        "target_aspect": "9:16",
        "platforms": campaign.get("platforms") or [],
    }
    try:
        info = ffprobe(clip["path"])
        check_clip["duration_s"] = info.get("duration_s")
    except Exception:
        pass
    record = check(conn, check_clip, campaign)
    if not record["passed"]:
        new_state = ("compliance_unknown" if record["unknowns"]
                     else "failed")
        conn.execute(
            "UPDATE clips SET state=?, compliance_json=? WHERE id=?",
            (new_state, json.dumps(record), clip["id"]))
        return {"clip_id": clip["id"], "regated": True, "passed": False,
                "state": new_state}
    conn.execute("UPDATE clips SET compliance_json=? WHERE id=?",
                 (json.dumps(record), clip["id"]))
    return {"clip_id": clip["id"], "regated": True, "passed": True,
            "state": clip["state"]}


def route_job(conn: sqlite3.Connection, job_id: str) -> str:
    """Aggregate routing after all of a job's clips are gated.

    unknowns present -> compliance_unknown (human review); else any failed ->
    failed when nothing passed, else tray with a note; else tray. Returns
    the state routed to.
    """
    cur = jobs_mod.get(conn, job_id)["state"]
    counts = conn.execute(
        "SELECT state, COUNT(*) AS n FROM clips WHERE job_id=? GROUP BY state",
        (job_id,)).fetchall()
    by_state = {r["state"]: r["n"] for r in counts}
    dest, note = "tray", "all clips compliant"
    if by_state.get("compliance_unknown"):
        dest = "compliance_unknown"
        note = (f"{by_state['compliance_unknown']} clip(s) need human review")
    elif by_state.get("failed"):
        if not by_state.get("tray"):
            dest, note = "failed", "every clip failed compliance"
        else:
            note = (f"{by_state['failed']} clip(s) failed compliance; "
                    f"{by_state['tray']} in tray")
    if cur != dest:
        jobs_mod.transition(conn, job_id, dest, note)
    return dest


def unknowns_for_job(conn: sqlite3.Connection, job_id: str) -> list[dict]:
    """Clips awaiting human review, with their unknown reasons."""
    rows = conn.execute(
        "SELECT c.*, cl.unknown_reasons, cl.at AS checked_at "
        "FROM clips c JOIN compliance_log cl ON cl.clip_id = c.id "
        "WHERE c.job_id=? AND c.state='compliance_unknown' "
        "AND cl.decided_by='machine' "
        "ORDER BY cl.id DESC",
        (job_id,),
    ).fetchall()
    seen, out = set(), []
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        out.append(dict(r))
    return out


def resolve(conn: sqlite3.Connection, clip_id: str, operator: str,
            decision: str, note: str = "") -> dict:
    """Human resolution of a compliance_unknown clip.

    decision: "pass" | "fail". Recorded in compliance_log as
    decided_by="human:<operator>". Pass moves the clip to the tray;
    fail moves it to failed. When no unknown clips remain for the job, the
    job leaves compliance_unknown for tray (or failed).
    """
    if decision not in ("pass", "fail"):
        raise ComplianceError("decision must be 'pass' or 'fail'")
    clip = conn.execute(
        "SELECT * FROM clips WHERE id=?", (clip_id,)).fetchone()
    if clip is None:
        raise ComplianceError(f"unknown clip {clip_id!r}")
    if clip["state"] != "compliance_unknown":
        raise ComplianceError(
            f"clip {clip_id} is in state {clip['state']!r}, not "
            "compliance_unknown")
    campaign = conn.execute(
        "SELECT rules_version FROM campaigns WHERE id=?",
        (clip["campaign_id"],)).fetchone()
    rv = campaign["rules_version"] if campaign else 0
    prev = json.loads(clip["compliance_json"] or "{}")
    prev["human_decision"] = {
        "decision": decision, "by": operator, "at": now(), "note": note,
    }
    prev["passed"] = (decision == "pass")
    new_state = "tray" if decision == "pass" else "failed"
    conn.execute(
        "UPDATE clips SET state=?, compliance_json=? WHERE id=?",
        (new_state, json.dumps(prev), clip_id),
    )
    conn.execute(
        "INSERT INTO compliance_log(clip_id, at, rules_version, passed,"
        " unknown_reasons, decided_by, note) VALUES(?,?,?,?,?,?,?)",
        (clip_id, now(), rv, 1 if decision == "pass" else 0,
         json.dumps(prev.get("unknowns", [])),
         f"human:{operator}", note or None),
    )
    remaining = conn.execute(
        "SELECT COUNT(*) FROM clips WHERE job_id=? AND state=?",
        (clip["job_id"], "compliance_unknown")).fetchone()[0]
    job_state = jobs_mod.get(conn, clip["job_id"])["state"]
    if remaining == 0 and job_state == "compliance_unknown":
        tray_n = conn.execute(
            "SELECT COUNT(*) FROM clips WHERE job_id=? AND state='tray'",
            (clip["job_id"],)).fetchone()[0]
        jobs_mod.transition(
            conn, clip["job_id"], "tray" if tray_n else "failed",
            f"human review complete ({operator}): {tray_n} clip(s) to tray")
    return {"clip_id": clip_id, "state": new_state,
            "remaining_unknown": remaining}
