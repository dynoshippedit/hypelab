"""Quality gates: fail the job, never ship it. Each gate returns
(pass: bool, measured, threshold, fix: str). Pure functions of (EDL, output)."""
from __future__ import annotations
import json
import re
import subprocess
from pathlib import Path

from .assets import probe
from . import captions as cap_mod

def _ffprobe_streams(path: Path) -> dict:
    return probe(path)

def gate_duration(edl: dict, out: Path):
    dur = probe(out)["duration_s"] or 0
    maxd = edl["target"]["max_duration_s"]
    ok = 3.0 <= dur <= maxd + 0.5
    return ok, round(dur, 2), f"3.0–{maxd}s", "check beat timings / VO length"

def gate_aspect(edl: dict, out: Path):
    m = probe(out)
    ok = m["width"] == edl["target"]["w"] and m["height"] == edl["target"]["h"]
    return ok, f"{m['width']}x{m['height']}", \
        f"{edl['target']['w']}x{edl['target']['h']}", "check renderer target"

def gate_first_frame(edl: dict, out: Path):
    # freezedetect n=0.01: <1% of pixels changing for a full second = frozen.
    # (n=0.5 proved hypersensitive: flagged slow-moving test patterns.)
    p = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(out),
         "-vf", "blackdetect=d=0.3:pix_th=0.10,freezedetect=n=0.01:d=1.0",
         "-t", "2", "-f", "null", "-"],
        capture_output=True, text=True, timeout=120)
    black = "black_start" in p.stderr
    frozen = "freeze_start" in p.stderr
    ok = not (black or frozen)
    measured = "black" if black else ("frozen" if frozen else "clean")
    return ok, measured, "clean", "replace the first beat's clip"

def gate_hook(edl: dict, out: Path):
    b0 = edl["beats"][0]
    dur = b0["t_out"] - b0["t_in"]
    budget = {"original": 3.0, "clip": 2.0}[edl["mode"]]
    return dur <= budget + 1e-6, round(dur, 2), f"<={budget}s", \
        "shorten the hook beat (cut words or tighten VO)"

def gate_captions_safe(edl: dict, out: Path, kit: dict, ass_path: Path):
    """Geometric check: caption block sits inside the safe box.

    Limitation (documented): this checks ASS layout geometry, not OCR of the
    rendered pixels. A font that renders wider than nominal could still clip.
    """
    t, cap = edl["target"], edl["captions"]
    geo = cap_mod.ass_safe_geometry(kit, t["w"], t["h"])
    text = ass_path.read_text() if ass_path.exists() else ""
    n_dialogues = text.count("Dialogue:")
    # worst case: one card, estimate lines from longest card
    longest = 0
    for line in text.splitlines():
        if line.startswith("Dialogue:"):
            txt = line.split(",", 9)[-1]
            longest = max(longest, len(re.sub(r"\{[^}]*\}", "", txt)))
    chars_per_line = max(10, int(t["w"] / (cap["size"] * 0.62)))
    est_lines = max(1, -(-longest // chars_per_line))
    block_h = est_lines * cap["size"] * 1.25
    block_bottom = t["h"] - geo["margin_v"]
    block_top = block_bottom - block_h
    ok = (block_bottom <= geo["bottom"] + 1
          and block_top >= geo["top"] - 1
          and n_dialogues > 0)
    measured = f"{est_lines} lines, block {block_top:.0f}–{block_bottom:.0f}px"
    threshold = f"inside {geo['top']:.0f}–{geo['bottom']:.0f}px, dialogues>0"
    return ok, measured, threshold, "reduce caption size or max_chars_per_card"

def gate_loudness(edl: dict, out: Path):
    p = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(out),
         "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True, text=True, timeout=180)
    m = re.search(r"Integrated loudness:\s+I:\s*(-?\d+\.\d+)", p.stderr)
    if not m:
        return False, "unmeasurable", "target ±1.5 LU", \
            f"ebur128 parse failed: {p.stderr[-200:]}"
    integ = float(m.group(1))
    target = edl["target"]["loudness_lufs"]
    return abs(integ - target) <= 1.5, integ, f"{target} ±1.5 LUFS", \
        "check loudnorm pass / music bed level"

def gate_slots_filled(edl: dict, out: Path, asset_slots: set[str]):
    missing = [b["clip_slot"] for b in edl["beats"]
               if b["clip_slot"] not in asset_slots]
    ok = not missing
    return ok, f"{len(edl['beats']) - len(missing)}/{len(edl['beats'])}", \
        "all beats", f"attach clips for slots: {missing}"

def gate_audio_present(edl: dict, out: Path):
    p = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "stream=codec_type",
         "-of", "csv=p=0", str(out)], capture_output=True, text=True, timeout=60)
    types = p.stdout.split()
    ok = "video" in types and "audio" in types
    return ok, "+".join(types), "video+audio", "check render audio chain"

GATES = [
    ("duration", gate_duration),
    ("aspect", gate_aspect),
    ("first_frame", gate_first_frame),
    ("hook", gate_hook),
    ("captions_safe", gate_captions_safe),
    ("loudness", gate_loudness),
    ("slots_filled", gate_slots_filled),
    ("audio_present", gate_audio_present),
]

def run_all(edl: dict, out: Path, kit: dict, ass_path: Path,
            asset_slots: set[str]) -> dict:
    results = []
    for name, fn in GATES:
        try:
            if name in ("captions_safe",):
                passed, measured, threshold, fix = fn(edl, out, kit, ass_path)
            elif name in ("slots_filled",):
                passed, measured, threshold, fix = fn(edl, out, asset_slots)
            else:
                passed, measured, threshold, fix = fn(edl, out)
        except Exception as ex:  # a gate that errors is a failed gate
            passed, measured, threshold, fix = False, f"error: {ex}", "n/a", \
                "fix the gate or the input it reads"
        results.append({"gate": name, "passed": bool(passed),
                        "measured": measured, "threshold": threshold,
                        "fix": fix})
    return {"passed": all(r["passed"] for r in results), "gates": results}
