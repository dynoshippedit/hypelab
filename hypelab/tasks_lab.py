"""Worker task handlers for the Lab half: align_vo, build_edl, render, run_gates.

Handlers are thin: validate inputs, call the pure modules, record results.
Any exception -> queue.fail (retryable or not, decided per error type).
"""
from __future__ import annotations
import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import config
from .db import connect, migrate
from . import edl as edl_mod
from . import plan as plan_mod
from . import align as align_mod
from . import render as render_mod
from . import gates as gates_mod
from .kits import Kits
from .assets import Assets

def _requeue_gates(cx, job_id: str) -> None:
    """Chain render -> gates: ensure a fresh run_gates task is queued.

    Recovery scenario: a render re-run must invalidate the previous gates
    verdict, so any existing run_gates task is reset to queued (never
    duplicated).
    """
    # run_after is compared lexicographically as ISO-8601 in queue.claim();
    # epoch floats would silently break that contract.
    due = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    row = cx.execute("SELECT id FROM tasks WHERE job_id=? AND kind='run_gates'",
                     (job_id,)).fetchone()
    if row:
        cx.execute("""UPDATE tasks SET state='queued', attempts=0, run_after=?,
                      lease_owner=NULL, lease_expires=NULL, result_json=NULL,
                      updated_at=? WHERE id=?""",
                   (due, now, row["id"]))
    else:
        tid = f"task_{uuid.uuid4().hex[:12]}"
        payload = json.dumps({"job_id": job_id})
        key = ("run_gates:" + job_id + ":" +
               hashlib.sha256(payload.encode()).hexdigest()[:16])
        cx.execute("""INSERT INTO tasks(id, job_id, kind, state, payload_json,
                      attempts, max_attempts, idempotency_key, run_after,
                      created_at, updated_at)
                      VALUES(?,?,?,?,?,0,?,?,?,?,?)""",
                   (tid, job_id, "run_gates", "queued", payload,
                    5, key, due, now, now))
    cx.commit()

def _cx():
    cx = connect()
    migrate(cx)
    return cx

def _job(cx, job_id: str) -> dict:
    row = cx.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise ValueError(f"job {job_id} not found")
    return dict(row)

def _set_state(cx, job_id: str, state: str, error: str | None = None):
    cx.execute("UPDATE jobs SET state=?, error=?, updated_at=datetime('now') WHERE id=?",
               (state, error, job_id))

# ---------------------------------------------------------------- align_vo

def handle_align_vo(payload: dict) -> dict:
    job_id = payload["job_id"]
    cx, assets, kits = _cx(), Assets(), Kits()
    job = _job(cx, job_id)
    vo = assets.get_slot(job_id, "vo")
    if not vo:
        raise ValueError("no VO attached (slot 'vo') — job waits in awaiting_media")
    out = config.job_dir(job_id) / "vo.words.json"
    script = config.job_dir(job_id) / "script.txt"
    data = align_mod.align_words(Path(vo["path"]), out,
                                 model=payload.get("whisper_model", "tiny"),
                                 script_path=script if script.exists() else None)
    rec = assets.add(job_id, "vo.words", out, provenance="generated:whisper-cpu")
    return {"words": len(data["words"]), "asset_id": rec["id"],
            "duration_s": data["words"][-1]["t1"] if data["words"] else 0}

# ---------------------------------------------------------------- build_edl

def handle_build_edl(payload: dict) -> dict:
    job_id = payload["job_id"]
    cx, assets, kits = _cx(), Assets(), Kits()
    job = _job(cx, job_id)
    kit = kits.get(job["kit_id"], job["kit_version"])

    script_path = config.job_dir(job_id) / "script.txt"
    script = script_path.read_text()
    wrec = assets.get_slot(job_id, "vo.words")
    if not wrec:
        raise ValueError("no word alignment yet (slot 'vo.words')")
    words = json.loads(Path(wrec["path"]).read_text())["words"]

    sentences = plan_mod.split_sentences(script)
    beats = plan_mod.group_into_beats(sentences, words, kit["max_clip_len_s"])
    data = plan_mod.assemble_edl(job_id, job["mode"], kit, job["kit_version"],
                                 script, words, beats,
                                 aspect=payload.get("aspect", "9:16"))
    slots = {a["slot"] for a in assets.list_job(job_id)}
    errors = edl_mod.validate_all(data, slots)
    if errors:
        # Non-retryable: the plan itself is bad. Fail the job back to repair.
        _set_state(cx, job_id, "asset_building",
                   "EDL invalid: " + "; ".join(errors[:8]))
        raise _NonRetryable("EDL invalid: " + "; ".join(errors[:8]))

    h = plan_mod.render_hash(data)
    data["render_hash"] = h
    ver = _upsert_edl(cx, job_id, json.dumps(data), h)
    return {"render_hash": h, "edl_version": ver, "beats": len(beats),
            "duration_s": round(beats[-1]["t_out"], 2)}

def _upsert_edl(cx, job_id: str, render_json_str: str, h: str) -> int:
    """Insert EDL version 1, or bump version on conflict. Returns version."""
    row = cx.execute("SELECT version FROM edls WHERE job_id=?", (job_id,)).fetchone()
    if row:
        cx.execute("""UPDATE edls SET version=version+1, render_json=?,
                      render_hash=?, created_at=datetime('now')
                      WHERE job_id=?""", (render_json_str, h, job_id))
        cx.commit()
        return row["version"] + 1
    cx.execute(
        """INSERT INTO edls(job_id, version, render_json, render_hash, created_at)
           VALUES(?, 1, ?, ?, datetime('now'))""",
        (job_id, render_json_str, h))
    cx.commit()
    return 1

# ---------------------------------------------------------------- render

def handle_render(payload: dict) -> dict:
    job_id = payload["job_id"]
    cx, assets, kits = _cx(), Assets(), Kits()
    job = _job(cx, job_id)
    kit = kits.get(job["kit_id"], job["kit_version"])

    row = cx.execute("SELECT render_json FROM edls WHERE job_id=?", (job_id,)).fetchone()
    if not row:
        raise ValueError("no EDL built yet")
    data = json.loads(row["render_json"])

    # resolve + re-validate against current assets (a replaced file changes the hash)
    asset_rows = {a["slot"]: a for a in assets.list_job(job_id)}
    needed = {data["audio"]["vo"]["slot"], data["audio"]["music"]["slot"],
              data["audio"]["vo"]["align_slot"]} | \
             {b["clip_slot"] for b in data["beats"]}
    missing = needed - set(asset_rows)
    if missing:
        _set_state(cx, job_id, "awaiting_media",
                   f"missing slots: {sorted(missing)}")
        raise _NonRetryable(f"missing asset slots: {sorted(missing)}")
    errors = edl_mod.validate_all(data, set(asset_rows))
    if errors:
        raise _NonRetryable("EDL invalid at render: " + "; ".join(errors[:8]))

    wrec = asset_rows[data["audio"]["vo"]["align_slot"]]
    words = json.loads(Path(wrec["path"]).read_text())["words"]

    work = config.job_dir(job_id) / "render"
    out = config.job_dir(job_id) / "master.mp4"
    record = render_mod.render_edl(data, asset_rows, words, kit, out, work)

    aspects = payload.get("aspects", ["9:16"])
    derived = {}
    for asp in aspects:
        if asp == data["target"]["aspect"]:
            continue
        w, h = {"1:1": (1080, 1080), "16:9": (1920, 1080)}[asp]
        dp = config.job_dir(job_id) / f"master_{asp.replace(':', 'x')}.mp4"
        render_mod.derive_aspect(out, w, h, dp)
        derived[asp] = str(dp)

    _set_state(cx, job_id, "gates")
    _requeue_gates(cx, job_id)
    return {"output": str(out), "derived": derived, "record": record}

# ---------------------------------------------------------------- run_gates

def handle_run_gates(payload: dict) -> dict:
    job_id = payload["job_id"]
    cx, assets, kits = _cx(), Assets(), Kits()
    job = _job(cx, job_id)
    kit = kits.get(job["kit_id"], job["kit_version"])
    row = cx.execute("SELECT render_json FROM edls WHERE job_id=?", (job_id,)).fetchone()
    data = json.loads(row["render_json"])
    out = config.job_dir(job_id) / "master.mp4"
    ass = config.job_dir(job_id) / "render" / "captions.ass"
    slots = {a["slot"] for a in assets.list_job(job_id)}

    report = gates_mod.run_all(data, out, kit, ass, slots)
    rpath = config.job_dir(job_id) / "quality_report.json"
    rpath.write_text(json.dumps(report, indent=1))

    if report["passed"]:
        _set_state(cx, job_id, "asset_ready")
        data["gates_passed"] = [g["gate"] for g in report["gates"]]
        cx.execute("UPDATE edls SET render_json=? WHERE job_id=?",
                   (json.dumps(data), job_id))
    else:
        fails = [g for g in report["gates"] if not g["passed"]]
        _set_state(cx, job_id, "asset_building",
                   "gates failed: " + "; ".join(
                       f"{g['gate']} (measured {g['measured']}, want {g['threshold']})"
                       for g in fails))
        cx.execute("UPDATE jobs SET gate_failures_json=? WHERE id=?",
                   (json.dumps(fails), job_id))
    return report

# ---------------------------------------------------------------- dispatch

class _NonRetryable(Exception):
    """Raised for errors that retrying cannot fix (bad EDL, missing media)."""

HANDLERS = {
    "align_vo": handle_align_vo,
    "build_edl": handle_build_edl,
    "render": handle_render,
    "run_gates": handle_run_gates,
}

def is_retryable(exc: Exception) -> bool:
    return not isinstance(exc, _NonRetryable)
