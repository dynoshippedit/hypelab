"""The clip tray: the manual upload handoff (Book 2, section 10).

You upload by hand. That is the correct design, not a limitation — and
multi-account posting automation is deliberately EXCLUDED from this layer
(not deferred, excluded). So the effort goes into making the manual step
near-frictionless.

Tray layout (per job):
    work/<job_id>/tray/
        clip_0001/
            clip.mp4       final, compliant, correct aspect
            caption.txt    handle + hashtags + credit already assembled
            meta.json      campaign, source url + hash, predicted score, signals
            submit.url     the campaign's submission link
            thumb.jpg
        clip_0002/
        ...

build_tray ranks compliant clips by predicted performance (the tray's entire
reason to exist: if you only have time for three uploads, you upload the
right three) and assigns tray_rank.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from .util import now

TRAY_CLIP_QUERY = (
    "SELECT * FROM clips WHERE job_id=? AND state='tray' "
    "AND json_extract(compliance_json,'$.passed')=1"
)


class TrayError(Exception):
    """Tray build failed."""


def assemble_caption(campaign: dict, body: str) -> str:
    """Handle + body + hashtags + credit, ready to paste."""
    rules = campaign.get("rules") or {}
    lines = []
    if rules.get("required_handle"):
        lines.append(rules["required_handle"])
    lines.append(body.strip())
    tags = rules.get("required_hashtags") or []
    if tags:
        lines.append(" ".join(tags))
    if rules.get("required_credit"):
        lines.append(rules["required_credit"])
    return "\n".join(lines)


def _thumb(clip_mp4: Path, out: Path) -> None:
    cmd = ["ffmpeg", "-y", "-v", "error", "-ss", "1",
           "-i", str(clip_mp4), "-frames:v", "1", str(out)]
    for a in cmd:
        if not isinstance(a, str) or not a:
            raise TrayError(f"invalid argv element: {a!r}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                          shell=False)
    if proc.returncode != 0:
        raise TrayError(f"thumb extract failed: {proc.stderr.strip()[-200:]}")


def _clip_meta(conn: sqlite3.Connection, clip: dict, campaign: dict) -> dict:
    moment = None
    if clip.get("moment_id"):
        mrow = conn.execute(
            "SELECT id, t_in, t_out, score, confidence, weight_version,"
            " signals_json FROM moments WHERE id=?",
            (clip["moment_id"],)).fetchone()
        if mrow:
            sig = json.loads(mrow["signals_json"] or "{}")
            moment = {
                "id": mrow["id"], "t_in": mrow["t_in"], "t_out": mrow["t_out"],
                "score": mrow["score"], "confidence": mrow["confidence"],
                "weight_version": mrow["weight_version"],
                "parts": sig.get("parts"), "hits": sig.get("hits"),
            }
    item = conn.execute(
        "SELECT url, title, content_sha256 FROM source_items "
        "WHERE job_id=? LIMIT 1", (clip["job_id"],)).fetchone()
    return {
        "clip_id": clip["id"],
        "job_id": clip["job_id"],
        "moment": moment,
        "campaign": {
            "id": campaign.get("id"), "creator": campaign.get("creator"),
            "marketplace": campaign.get("marketplace"),
            "rules_version": campaign.get("rules_version"),
        },
        "source": {
            "url": item["url"] if item else None,
            "title": item["title"] if item else None,
            "content_sha256": item["content_sha256"] if item else None,
        },
        "predicted": clip.get("predicted"),
        "compliance_passed": True,
        "created_at": clip.get("created_at"),
    }


def build_tray(conn: sqlite3.Connection, job_id: str, root) -> list[dict]:
    """Rank compliant clips, assign tray_rank, materialize tray dirs.

    Moves each clip's rendered mp4 into work/<job_id>/tray/clip_NNNN/ and
    writes caption.txt, meta.json, submit.url, thumb.jpg. Updates clips.path
    and tray_rank. Returns the ranked clip dicts.
    """
    from . import campaigns as campaigns_mod

    job = conn.execute("SELECT * FROM jobs WHERE id=?",
                       (job_id,)).fetchone()
    if job is None:
        raise TrayError(f"unknown job {job_id!r}")
    campaign = (campaigns_mod.load(conn, job["campaign_id"])
                if job["campaign_id"] else {"rules": {}})
    clips = [dict(r) for r in conn.execute(TRAY_CLIP_QUERY, (job_id,))]
    ranked = sorted(clips, key=lambda c: -(c.get("predicted") or 0.0))

    tray_root = Path(root) / "work" / job_id / "tray"
    tray_root.mkdir(parents=True, exist_ok=True)
    submit_url = ((campaign.get("submission_json") or {}).get("url")
                  if isinstance(campaign.get("submission_json"), dict)
                  else None)
    if not submit_url:
        submit_url = ((campaign.get("submission") or {}).get("url")
                      if isinstance(campaign.get("submission"), dict)
                      else "")

    for i, clip in enumerate(ranked, 1):
        slug = f"clip_{i:04d}"
        d = tray_root / slug
        d.mkdir(parents=True, exist_ok=True)
        src_mp4 = Path(clip["path"])
        dst_mp4 = d / "clip.mp4"
        if src_mp4.resolve() != dst_mp4.resolve():
            if not src_mp4.is_file():
                raise TrayError(f"clip file missing: {src_mp4}")
            src_mp4.replace(dst_mp4)  # atomic move into the tray
        (d / "caption.txt").write_text(clip.get("caption") or "",
                                       encoding="utf-8")
        (d / "meta.json").write_text(
            json.dumps(_clip_meta(conn, clip, campaign), indent=2),
            encoding="utf-8")
        (d / "submit.url").write_text(
            f"[InternetShortcut]\nURL={submit_url or ''}\n",
            encoding="utf-8")
        _thumb(dst_mp4, d / "thumb.jpg")
        conn.execute(
            "UPDATE clips SET tray_rank=?, path=? WHERE id=?",
            (i, str(dst_mp4), clip["id"]),
        )
        clip["tray_rank"] = i
        clip["path"] = str(dst_mp4)
    return ranked


def tray_clips(conn: sqlite3.Connection, job_id: str | None = None):
    """Tray-state clips, ranked, optionally for one job."""
    q = (TRAY_CLIP_QUERY + " ORDER BY tray_rank") \
        if job_id else (
            "SELECT * FROM clips WHERE state='tray' "
            "AND json_extract(compliance_json,'$.passed')=1 "
            "ORDER BY job_id, tray_rank")
    args = (job_id,) if job_id else ()
    return [dict(r) for r in conn.execute(q, args)]


def tray_slug_for(conn: sqlite3.Connection, clip_id: str,
                  root) -> str | None:
    """The tray dir slug (clip_0001) for a clip, or None."""
    clip = conn.execute("SELECT job_id, tray_rank FROM clips WHERE id=?",
                        (clip_id,)).fetchone()
    if clip is None or not clip["tray_rank"]:
        return None
    d = (Path(root) / "work" / clip["job_id"] / "tray"
         / f"clip_{clip['tray_rank']:04d}")
    return str(d) if d.is_dir() else None
