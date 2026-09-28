"""Deterministic renderer: validated EDL + content-addressed assets -> MP4.

The ONLY module that builds ffmpeg argv. Never uses shell=True; filtergraph
values are escaped for the filter parser. Pure function of (EDL, assets).
"""
from __future__ import annotations
import json
import math
import re
import subprocess
from pathlib import Path

from . import config
from . import captions as cap_mod

RENDERER_VERSION = "0.1.0"

def _esc_filter(s: str) -> str:
    """Escape a value embedded in a filtergraph (not a shell)."""
    return (s.replace("\\", "\\\\").replace("'", "\\'")
             .replace(":", "\\:").replace(",", "\\,")
             .replace("[", "\\[").replace("]", "\\]")
             .replace(";", "\\;"))

def _duck_gain(duck_db: float) -> float:
    return 10 ** (duck_db / 20.0)

def _loud_gaps(words: list[dict], total: float, min_gap: float = 0.25) -> list[tuple[float, float]]:
    """Speech gaps where music comes back up: [start,end) pairs."""
    gaps: list[tuple[float, float]] = []
    prev_end = 0.0
    for w in words:
        if w["t0"] - prev_end >= min_gap:
            gaps.append((prev_end, w["t0"]))
        prev_end = max(prev_end, w["t1"])
    if total - prev_end >= min_gap:
        gaps.append((prev_end, total))
    # merge gaps closer than 0.15s apart (avoid flutter)
    merged: list[tuple[float, float]] = []
    for a, b in gaps:
        if merged and a - merged[-1][1] < 0.15:
            merged[-1] = (merged[-1][0], b)
        else:
            merged.append((a, b))
    return merged

def volume_expr(words: list[dict], total: float, duck_db: float) -> str:
    duck = _duck_gain(duck_db)
    gaps = _loud_gaps(words, total)
    if not gaps:
        return f"{duck:.4f}"
    terms = "+".join(f"between(t\\,{a:.3f}\\,{b:.3f})" for a, b in gaps)
    return f"if({terms}\\,1\\,{duck:.4f})"

def build_filtergraph(edl: dict, assets: dict[str, dict], words: list[dict],
                      ass_path: Path, measured: dict | None) -> tuple[str, dict]:
    """Returns (filtergraph, meta). measured=None -> measurement pass graph
    (audio only); otherwise the full graph with linear loudnorm."""
    t = edl["target"]
    W, H, FPS = t["w"], t["h"], t["fps"]
    beats = edl["beats"]
    total = beats[-1]["t_out"]
    n = len(beats)
    vo_idx, mus_idx = n, n + 1
    mu = edl["audio"]["music"]

    vparts: list[str] = []
    for i, b in enumerate(beats):
        dur = b["t_out"] - b["t_in"]
        fit = b.get("clip_fit", "cover")
        if fit == "cover":
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                  f"crop={W}:{H}")
        else:  # contain -> blurpad
            vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
                  f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2")
        vparts.append(
            f"[{i}:v]{vf},setsar=1,fps={FPS},"
            f"trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]")
    vcat = "".join(f"[v{i}]" for i in range(n)) + f"concat=n={n}:v=1:a=0[vcat]"
    vass = f"[vcat]ass={_esc_filter(str(ass_path))}[vout]"

    vexpr = volume_expr(words, total, mu.get("duck_db", -12))
    fade_in = mu.get("fade_in_s", 0.5)
    fade_out = mu.get("fade_out_s", 1.5)
    mus_chain = (
        f"[{mus_idx}:a]aresample=44100,"
        f"volume={vexpr},"
        f"afade=t=in:st=0:d={fade_in:.2f},"
        f"afade=t=out:st={max(0.0, total - fade_out):.2f}:d={fade_out:.2f},"
        f"atrim=duration={total:.3f},asetpts=PTS-STARTPTS[musa]")
    vo_chain = (f"[{vo_idx}:a]aresample=44100,"
                f"atrim=duration={total:.3f},asetpts=PTS-STARTPTS[voa]")
    mix = "[voa][musa]amix=inputs=2:duration=longest:dropout_transition=0[aout]"

    if measured is None:
        graph = ";".join([vo_chain, mus_chain, mix,
                           "[aout]loudnorm=print_format=json[loud]"])
        return graph, {"total": total, "n_beats": n}

    ln = (f"loudnorm=linear=true:I={t['loudness_lufs']}:TP=-1.5:LRA=11:"
          f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
          f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
          f"offset={measured['target_offset']}[aloud]")
    graph = ";".join(vparts + [vcat, vass, vo_chain, mus_chain, mix,
                               f"[aout]{ln}"])
    return graph, {"total": total, "n_beats": n}

def _input_args_for_beats(beats: list[dict], assets: dict[str, dict]) -> tuple[list[str], dict]:
    """Per-beat -stream_loop when the clip is shorter than the beat."""
    args: list[str] = []
    for b in beats:
        a = assets[b["clip_slot"]]
        clip_dur = a.get("duration_s") or 0
        beat_dur = b["t_out"] - b["t_in"]
        loops = 0
        if clip_dur and clip_dur < beat_dur - 0.05:
            loops = math.ceil(beat_dur / clip_dur) - 1
        if loops > 0:
            args += ["-stream_loop", str(loops)]
        args += ["-i", a["path"]]
    return args, {}

def measure_loudness(edl: dict, assets: dict[str, dict], words: list[dict],
                     ass_path: Path) -> dict:
    """Audio-only pass: run the exact audio chain, parse loudnorm JSON."""
    graph, meta = build_filtergraph(edl, assets, words, ass_path, measured=None)
    argv = (["ffmpeg", "-y", "-v", "error"]
            + _input_args_for_beats(edl["beats"], assets)[0]
            + ["-i", assets[edl["audio"]["vo"]["slot"]]["path"],
               "-i", assets[edl["audio"]["music"]["slot"]]["path"],
               "-filter_complex", graph,
               "-map", "[loud]", "-f", "null", "-"])
    p = subprocess.run(argv, capture_output=True, text=True,
                       timeout=config.FFMPEG_TIMEOUT)
    if p.returncode != 0:
        raise RuntimeError(f"loudness measure pass failed: {p.stderr[-500:]}")
    m = re.search(r"\{[^}]*\"input_i\"[^}]*\}", p.stderr, re.S)
    if not m:
        raise RuntimeError("could not parse loudnorm JSON from: " + p.stderr[-500:])
    return json.loads(m.group(0))

def render_edl(edl: dict, assets: dict[str, dict], words: list[dict],
               kit: dict, out_path: Path, work_dir: Path) -> dict:
    """Full deterministic render. Returns the reproducibility record."""
    # 1. verify asset bytes match intake hashes
    from .assets import sha256_file
    for slot, a in assets.items():
        p = Path(a["path"])
        if not p.is_file() or sha256_file(p) != a["sha256"]:
            raise ValueError(f"asset '{slot}' changed or missing since intake")

    work_dir.mkdir(parents=True, exist_ok=True)
    ass_path = work_dir / "captions.ass"
    ass_text = cap_mod.words_to_ass(words, kit, edl["target"]["w"], edl["target"]["h"])
    ass_path.write_text(ass_text)

    # 2. loudness measurement pass (audio only)
    measured = measure_loudness(edl, assets, words, ass_path)

    # 3. full render with linear loudnorm
    graph, meta = build_filtergraph(edl, assets, words, ass_path, measured)
    t = edl["target"]
    argv = (["ffmpeg", "-y", "-v", "error"]
            + _input_args_for_beats(edl["beats"], assets)[0]
            + ["-i", assets[edl["audio"]["vo"]["slot"]]["path"],
               "-i", assets[edl["audio"]["music"]["slot"]]["path"],
               "-filter_complex", graph,
               "-map", "[vout]", "-map", "[aloud]",
               "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
               "-pix_fmt", "yuv420p", "-r", str(t["fps"]),
               "-c:a", "aac", "-b:a", "192k", "-ar", "44100",
               "-movflags", "+faststart",
               str(out_path)])
    p = subprocess.run(argv, capture_output=True, text=True,
                       timeout=config.FFMPEG_TIMEOUT)
    if p.returncode != 0:
        raise RuntimeError(f"ffmpeg render failed: {p.stderr[-2000:]}")

    import hashlib
    record = {
        "edl_version": edl["edl_version"], "renderer_version": RENDERER_VERSION,
        "kit": edl["kit"], "ffmpeg": _ffmpeg_version(),
        "asset_shas": {s: a["sha256"] for s, a in assets.items()},
        "ass_sha256": hashlib.sha256(ass_text.encode()).hexdigest(),
        "filtergraph_sha256": hashlib.sha256(graph.encode()).hexdigest(),
        "loudnorm_measured": {k: measured[k] for k in
                              ("input_i", "input_tp", "input_lra") if k in measured},
        "output": str(out_path), "duration_s": meta["total"],
    }
    (work_dir / "render_record.json").write_text(json.dumps(record, indent=1))
    return record

def _ffmpeg_version() -> str:
    p = subprocess.run(["ffmpeg", "-version"], capture_output=True, text=True)
    return p.stdout.splitlines()[0] if p.returncode == 0 else "unknown"

def derive_aspect(master: Path, w: int, h: int, out: Path) -> None:
    """Derive 1:1 / 16:9 from the master (cover crop). One edit, no re-cutting."""
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    argv = ["ffmpeg", "-y", "-v", "error", "-i", str(master),
            "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy", "-movflags", "+faststart",
            str(out)]
    p = subprocess.run(argv, capture_output=True, text=True,
                       timeout=config.FFMPEG_TIMEOUT)
    if p.returncode != 0:
        raise RuntimeError(f"aspect derivation failed: {p.stderr[-500:]}")
