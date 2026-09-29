"""Cut compliant 9:16 clips from moments (Book 2, section 8).

Pipeline per moment:
  moment -> boundary.select (never opens mid-sentence) -> reframe plan
  (hold-and-cut, never pan) -> segment audio pre-extract -> EDL ->
  render.render (Book 1's deterministic chain) -> compliance gate ->
  job routing (once, aggregated over all clips).

The EDL's reframe block makes the cut re-renderable: same EDL + same
source hash = same clip (Book 1's determinism guarantee, extended).
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from . import boundary as boundary_mod
from . import campaigns as campaigns_mod
from . import compliance as compliance_mod
from . import jobs as jobs_mod
from . import reframe as reframe_mod
from . import tray as tray_mod
from .util import ffprobe, new_id, now, sha256_file

#: The only output target in Book 2.
TARGET = {
    "aspect": "9:16", "w": 1080, "h": 1920, "fps": 30,
    "max_duration_s": 45.0, "loudness_lufs": -16.0,
}

#: Fallback caption style when the campaign kit_json has no captions block.
CAPTION_DEFAULTS = {
    "font": "DejaVu Sans", "size": 72, "fill": "#FFFFFF",
    "highlight": "#39FF88", "outline": "#000000", "outline_w": 3,
    "safe_top_pct": 10, "safe_bottom_pct": 20, "max_chars_per_card": 24,
}


class CutError(Exception):
    """Cut pipeline failed."""


def _extract_segment_audio(src: str, t_in: float, dur: float,
                           out: Path) -> Path:
    """Pre-extract the segment's audio to wav.

    Book 1's audio_chain atrims the VO from the START of its input, so a
    mid-source segment needs its own input file. Deterministic: same source
    bytes + same (t_in, dur) = same wav.
    """
    cmd = ["ffmpeg", "-y", "-v", "error",
           "-ss", f"{t_in:.3f}", "-t", f"{dur:.3f}",
           "-i", str(src), "-vn", "-ac", "2", "-ar", "48000", str(out)]
    for a in cmd:
        if not isinstance(a, str) or not a:
            raise CutError(f"invalid argv element: {a!r}")
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300,
                          shell=False)
    if proc.returncode != 0 or not out.is_file():
        raise CutError(
            f"segment audio extract failed: {proc.stderr.strip()[-300:]}")
    return out


def _build_edl(seg, plan: dict, wav: Path, caps_cfg: dict,
               premise_card: str | None, handle_overlay: str | None) -> dict:
    from . import edl as edl_mod

    overlays = []
    if premise_card:
        # Cold-open hook card: first ~2s only. render.py's overlays_chain
        # honors the optional "enable" drawtext expression (Book 2
        # additive extension; absent = whole-clip, Book 1 behavior).
        overlays.append({"text": premise_card, "pos": "top",
                         "enable": "between(t,0,2.05)"})
    if handle_overlay:
        overlays.append({"text": handle_overlay, "pos": "bottom"})
    # Captions must use clip-relative timings (t=0 is the clip start).
    # seg["words"] keeps absolute source timings for audit; caption_words
    # are re-based by boundary.select.
    words = [{"w": w["w"], "t0": w["t0"], "t1": w["t1"]}
             for w in seg["caption_words"]]
    captions = dict(caps_cfg)
    captions["words"] = words
    beat = {
        "id": "seg", "role": "hook", "line": "clip",
        "clip": seg["source"], "clip_in": seg["t_in"],
        "clip_fit": "cover", "t_in": 0.0, "t_out": seg["dur"],
        "reframe": plan,
    }
    edl = edl_mod.build_edl(
        mode="clip", kit_ref="book2@1",
        target=dict(TARGET),
        beats=[beat],
        audio={"vo": {"path": str(wav)}, "music": None},
        captions=captions,
        overlays=overlays,
        min_word_prob=0.0,
    )
    edl_mod.validate(edl)
    return edl


def cut_moment(conn: sqlite3.Connection, job_id: str, moment_id: str, *,
               root, campaign: dict, words: list[dict],
               reframe_mode: str = "auto",
               work_minutes: float | None = None) -> dict:
    """Cut one compliant clip from one moment. Returns the clip row dict."""
    from . import render as render_mod

    mrow = conn.execute("SELECT * FROM moments WHERE id=? AND job_id=?",
                        (moment_id, job_id)).fetchone()
    if mrow is None:
        raise CutError(f"moment {moment_id!r} not found for job {job_id!r}")

    work = Path(root) / "work" / job_id
    src = work / "source.mp4"
    if not src.is_file():
        raise CutError(f"source.mp4 missing for job {job_id}")

    cut_cfg = ((campaign.get("cut_json") or {}).get("cut")
               if isinstance(campaign.get("cut_json"), dict) else None)
    seg = boundary_mod.select(words, float(mrow["t_in"]),
                              float(mrow["t_out"]),
                              rules=campaign.get("rules"),
                              cuts_cfg=cut_cfg)
    seg["source"] = str(src)

    plan = reframe_mod.plan_reframe(
        str(src), seg["t_in"], seg["t_out"], {"w": 1080, "h": 1920},
        mode=reframe_mode)

    wav = _extract_segment_audio(str(src), seg["t_in"], seg["dur"],
                                 work / f"seg_{moment_id}.wav")

    rules = campaign.get("rules") or {}
    premise_card = seg.get("premise") if seg.get("cold_open") else None
    handle_overlay = None
    if rules.get("required_handle") \
            and rules.get("handle_placement") == "overlay":
        handle_overlay = rules["required_handle"]

    kit_json = campaign.get("kit_json") or {}
    caps_cfg = dict(CAPTION_DEFAULTS)
    caps_cfg.update(kit_json.get("captions") or {})

    edl = _build_edl(seg, plan, wav, caps_cfg, premise_card, handle_overlay)

    clip_id = new_id()
    out = work / f"clip_{clip_id}.mp4"
    res = render_mod.render(edl, work, out)
    info = ffprobe(str(out))

    payload = " ".join(w["w"] for w in seg.get("payload_words", [])
                       ) or " ".join(w["w"] for w in seg["words"][:24])
    caption = tray_mod.assemble_caption(campaign, payload)
    overlays_text = [ov["text"] for ov in edl["overlays"]]
    item = conn.execute(
        "SELECT url FROM source_items WHERE job_id=? LIMIT 1",
        (job_id,)).fetchone()
    clip = {
        "id": clip_id, "job_id": job_id,
        "campaign_id": campaign.get("id"), "moment_id": moment_id,
        "path": str(out), "caption": caption,
        "predicted": round(float(mrow["score"]) * float(mrow["confidence"]), 4),
        "state": "cutting",
        "compliance_json": None, "tray_rank": None,
        "work_minutes": work_minutes, "created_at": now(),
    }
    # NOTE: no posted_at here — 0001's clips table has no such column
    # (posted_at lives on posts, enforced non-null by record_posted).
    conn.execute(
        "INSERT INTO clips(id, job_id, campaign_id, moment_id, path,"
        " caption, predicted, state, compliance_json, tray_rank,"
        " work_minutes, created_at)"
        " VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        tuple(clip.values()),
    )
    check_clip = {
        "id": clip_id, "job_id": job_id,
        "path": str(out), "caption": caption,
        "burned_text": " ".join(w["w"] for w in seg["words"]),
        "ocr_confidence": 1.0,  # generated from known word timings, not OCR
        "overlays_text": overlays_text,
        "duration_s": info.get("duration_s") or seg["dur"],
        "source_url": item["url"] if item else "",
        "audio_provenance": "campaign_supplied",
        "mixed_music": False,
        "watermark_verified": False,
        "target_aspect": "9:16",
        "platforms": campaign.get("platforms") or [],
    }
    record = compliance_mod.check(conn, check_clip, campaign)
    new_state = ("tray" if record["passed"]
                 else "compliance_unknown" if record["unknowns"]
                 else "failed")
    conn.execute(
        "UPDATE clips SET state=?, compliance_json=? WHERE id=?",
        (new_state, json.dumps(record), clip_id),
    )
    clip["state"] = new_state
    clip["compliance_json"] = record
    clip["reframe_mode"] = plan["mode"]
    clip["boundary"] = {"t_in": seg["t_in"], "t_out": seg["t_out"],
                        "cold_open": seg["cold_open"]}
    return clip


def cut(conn: sqlite3.Connection, job_id: str, moment_ids: list[str], *,
        root, reframe_mode: str = "auto",
        work_minutes: float | None = None) -> dict:
    """Cut clips for a job's moments; route the job once at the end.

    moments <job> lists candidates; this cuts the selected ones. Job must
    be in scored state. Returns {"clips": [...], "job_state": ...}.
    """
    job = jobs_mod.get(conn, job_id)
    if job["state"] != "scored":
        raise CutError(f"job {job_id} is in state {job['state']!r}; "
                       "cut requires 'scored'")
    if not moment_ids:
        raise CutError("no moments selected")
    campaign = (campaigns_mod.load(conn, job["campaign_id"])
                if job["campaign_id"] else {"rules": {}})
    work = Path(root) / "work" / job_id
    try:
        words_doc = json.loads((work / "source.words.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise CutError(f"cannot read source.words.json: {e}")
    # The fixture/ingest word document is {"words": [...]}; boundary code
    # needs the bare list.
    words = words_doc.get("words", []) if isinstance(words_doc, dict) \
        else words_doc

    jobs_mod.transition(conn, job_id, "queued_cut",
                        f"{len(moment_ids)} moment(s) selected for cut")
    jobs_mod.transition(conn, job_id, "cutting",
                        f"cutting {len(moment_ids)} moment(s)")
    clips = []
    for mid in moment_ids:
        clips.append(cut_moment(
            conn, job_id, mid, root=root, campaign=campaign, words=words,
            reframe_mode=reframe_mode, work_minutes=work_minutes))
    dest = compliance_mod.route_job(conn, job_id)
    return {"clips": clips, "job_state": dest}


def record_posted(conn: sqlite3.Connection, clip_id: str, post_url: str,
                  platform: str, operator: str = "") -> dict:
    """Record a manual upload. Re-gates compliance first when the campaign
    rules changed since the clip was gated (section 9: the gate runs again
    at submission if rules changed).

    Sets posted_at (the additive-schema limitation means the DB cannot
    enforce NOT NULL; the CLI enforces it here: post_url is required and
    posted_at is always written). payout_usd is filled in later from the
    campaign's rate basis (see posted CLI).
    """
    clip = conn.execute("SELECT * FROM clips WHERE id=?",
                        (clip_id,)).fetchone()
    if clip is None:
        raise CutError(f"unknown clip {clip_id!r}")
    if clip["state"] != "tray":
        raise CutError(f"clip {clip_id} is in state {clip['state']!r}; "
                       "only tray clips can be posted")
    if not post_url:
        raise CutError("post_url is required (posted_at must be non-null)")
    campaign = campaigns_mod.load(conn, clip["campaign_id"])
    prev = json.loads(clip["compliance_json"] or "{}")
    if campaign.get("rules_version") != prev.get("rules_version"):
        # Rules changed since gating: re-run the gate on the rendered file.
        check_clip = {
            "id": clip_id, "job_id": clip["job_id"], "path": clip["path"],
            "caption": clip["caption"] or "",
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
        record = compliance_mod.check(conn, check_clip, campaign)
        if not record["passed"]:
            new_state = ("compliance_unknown" if record["unknowns"]
                         else "failed")
            conn.execute(
                "UPDATE clips SET state=?, compliance_json=? WHERE id=?",
                (new_state, json.dumps(record), clip_id))
            jobs_mod.transition(conn, clip["job_id"], new_state,
                                f"re-gate at submission failed ({operator})")
            return {"clip_id": clip_id, "state": new_state,
                    "regated": True, "passed": False}
    at = now()
    # NOTE: clips has no posted_at column (0001); posted_at lives on posts
    # where it is always written non-null by the INSERT below.
    conn.execute("UPDATE clips SET state='posted' WHERE id=?", (clip_id,))
    post_id = new_id()
    conn.execute(
        "INSERT INTO posts(id, clip_id, platform, post_url, posted_at,"
        " payout_usd) VALUES(?,?,?,?,?,?)",
        (post_id, clip_id, platform, post_url, at, None),
    )
    # The job stays in tray until every tray clip is posted or failed.
    remaining = conn.execute(
        "SELECT COUNT(*) FROM clips WHERE job_id=? AND state='tray'",
        (clip["job_id"],)).fetchone()[0]
    if remaining == 0:
        st = jobs_mod.get(conn, clip["job_id"])["state"]
        if st == "tray":
            jobs_mod.transition(conn, clip["job_id"], "posted",
                                f"{operator or 'operator'} posted last clip")
    return {"clip_id": clip_id, "post_id": post_id, "posted_at": at,
            "state": "posted"}
