"""Deterministic ffmpeg render chains (Book 1).

The ONLY module that builds ffmpeg argv. Never uses shell=True; filtergraph
values are escaped for the filter parser. Pure function of (EDL, work dir).

Chain layout (filter_complex = video ; audio ; overlays):
  video    per-beat geometry (cover/contain/blurpad, or a Book-2 reframe plan)
           -> concat -> [vcat] -> ass captions -> [vass]
  audio    vo+music ducked via asplit sidechain -> amix -> loudnorm -> [aout]
  overlays drawtext labels on [vass] -> [vout]

util (ffprobe/MediaError/work_dir/now/sha256_file) and hypelab.reframe are
imported LAZILY inside functions so import order never breaks.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from . import captions as cap_mod
from . import manifests as manifests_mod

RENDERER_VERSION = "1.0.0"
FFMPEG_TIMEOUT = 600


class RenderError(Exception):
    """Anything that stops a render: missing slots, ffmpeg failure, bad DB."""


# ------------------------------------------------------------------ escaping

def _esc_filter(s: str) -> str:
    """Escape a bare value embedded in a filtergraph (not a shell)."""
    return (
        s.replace("\\", "\\\\")
        .replace("'", "\\'")
        .replace(":", "\\:")
        .replace(",", "\\,")
        .replace("[", "\\[")
        .replace("]", "\\]")
        .replace(";", "\\;")
    )


def _esc_sq(s: str) -> str:
    """Escape for a single-quoted filtergraph value: '...'."""
    return s.replace("\\", "\\\\").replace("'", "\\'")


# ------------------------------------------------------------------ fonts

# DejaVuSans-Bold is the canonical overlay font; it is not installed on the
# Threadripper, so fall back through known-good bold TTFs (verified via
# fc-list on 2026-09-28).
_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/google-droid-sans-fonts/DroidSans-Bold.ttf",
    "/usr/share/fonts/gnu-free/FreeSansBold.ttf",
]
_overlay_font_cache: str | None = None


def _overlay_font() -> str:
    global _overlay_font_cache
    if _overlay_font_cache is None:
        for p in _FONT_CANDIDATES:
            if Path(p).is_file():
                _overlay_font_cache = p
                break
        else:
            raise RenderError("no bold TTF found for drawtext overlays")
    return _overlay_font_cache


# ------------------------------------------------------------------ geometry

def blurpad_geo(t: dict, tag: str) -> str:
    """Blur-pad subchain between [tag-in] and the returned tail.

    Splits the source: one copy is scaled up, cropped and blurred into a
    full-frame background; the other is scaled to fit and overlaid centered.
    `tag` keeps the intermediate labels unique per beat. Returned string
    starts with the split and ends at the overlay output (caller appends
    setsar/fps/trim/setpts and the [v{i}] label).
    """
    W, H = t["w"], t["h"]
    return (
        f"split=outputs=2[{tag}a][{tag}b];"
        f"[{tag}a]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},gblur=sigma=25[{tag}bg];"
        f"[{tag}b]scale={W}:{H}:force_original_aspect_ratio=decrease[{tag}fg];"
        f"[{tag}bg][{tag}fg]overlay=(W-w)/2:(H-h)/2"
    )


def _beat_geometry(edl: dict, b: dict, i: int) -> str:
    """The per-beat video subchain, WITHOUT the [i:v] head / [v{i}] tail."""
    t = edl["target"]
    W, H = t["w"], t["h"]

    rf = b.get("reframe")
    if isinstance(rf, dict):
        # Book-2 hook: a reframe plan overrides cover/contain/blurpad.
        try:
            from hypelab.reframe import reframe_filter
        except ImportError as e:
            raise RenderError(
                "reframe plan requires hypelab.reframe (Book 2)"
            ) from e
        try:
            from . import util as _util
        except ImportError as e:
            raise RenderError(f"hypelab.util is required for reframe: {e}") from e
        try:
            info = _util.ffprobe(b["clip"])
        except _util.MediaError as e:
            raise RenderError(
                f"ffprobe failed for beat {b.get('id')}: {e}"
            ) from e
        return reframe_filter(rf, t, info["width"], info["height"])

    fit = b.get("clip_fit", "cover")
    if fit == "cover":
        return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
    if fit == "contain":
        return (
            f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
            f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black"
        )
    if fit == "blurpad":
        return blurpad_geo(t, f"bp{i}")
    raise RenderError(f"beat {b.get('id')}: unknown clip_fit {fit!r}")


def video_chain(edl: dict, ass_path: str | Path | None = None) -> list[str]:
    """Per-beat geometry -> concat -> [vcat] -> ass captions -> [vass].

    ass_path None skips the captions filter ([vcat]null[vass]).
    """
    t = edl["target"]
    fps = t["fps"]
    beats = edl["beats"]
    parts: list[str] = []
    for i, b in enumerate(beats):
        dur = b["t_out"] - b["t_in"]
        geo = _beat_geometry(edl, b, i)
        parts.append(
            f"[{i}:v]{geo},setsar=1,fps={fps},"
            f"trim=duration={dur:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
    parts.append(
        "".join(f"[v{i}]" for i in range(len(beats)))
        + f"concat=n={len(beats)}:v=1:a=0[vcat]"
    )
    if ass_path is not None:
        parts.append(f"[vcat]ass='{_esc_sq(str(ass_path))}'[vass]")
    else:
        parts.append("[vcat]null[vass]")
    return parts


# ------------------------------------------------------------------ audio

def _audio_path(node) -> str | None:
    if node is None:
        return None
    if isinstance(node, dict):
        return node.get("path")
    return str(node)


def audio_chain(edl: dict, n_video: int) -> list[str]:
    """VO/music mix -> [aout].

    vo+music: the VO is asplit — one copy goes to the mix, the other keys a
    sidechaincompress ducking the music — then amix(normalize=0) and a
    single-pass loudnorm to the target LUFS. vo-only / music-only get a
    straight loudnorm; no audio at all yields generated silence.
    Input indices: beats are 0..n_video-1, vo is n_video, music n_video+1.
    """
    t = edl["target"]
    total = edl["beats"][-1]["t_out"]
    lufs = t["loudness_lufs"]
    audio = edl.get("audio") or {}
    vo_path = _audio_path(audio.get("vo"))
    music_node = audio.get("music")
    music_path = _audio_path(music_node)

    pre = f"aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"

    if vo_path and music_path:
        vi, mi = n_video, n_video + 1
        duck_db = (
            float(music_node.get("duck_db", -12.0))
            if isinstance(music_node, dict)
            else -12.0
        )
        duck_gain = 10 ** (duck_db / 20.0)
        return [
            f"[{vi}:a]{pre},atrim=duration={total:.3f},"
            f"asetpts=PTS-STARTPTS,asplit=outputs=2[vo_out][vo_key]",
            f"[{mi}:a]{pre},atrim=duration={total:.3f},"
            f"asetpts=PTS-STARTPTS,volume={duck_gain:.4f}[mu_pre]",
            "[mu_pre][vo_key]sidechaincompress=threshold=0.02:ratio=6:"
            "attack=200:release=800[mu_duck]",
            f"[vo_out][mu_duck]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0,"
            f"loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]",
        ]
    if vo_path:
        return [
            f"[{n_video}:a]{pre},atrim=duration={total:.3f},"
            f"asetpts=PTS-STARTPTS,"
            f"loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]"
        ]
    if music_path:
        duck_db = (
            float(music_node.get("duck_db", -12.0))
            if isinstance(music_node, dict)
            else -12.0
        )
        duck_gain = 10 ** (duck_db / 20.0)
        return [
            f"[{n_video}:a]{pre},atrim=duration={total:.3f},"
            f"asetpts=PTS-STARTPTS,volume={duck_gain:.4f},"
            f"loudnorm=I={lufs}:TP=-1.5:LRA=11[aout]"
        ]
    return [f"anullsrc=r=48000:cl=stereo:d={total:.3f}[aout]"]


# ------------------------------------------------------------------ overlays

def _esc_drawtext(s: str) -> str:
    s = s.replace("\r", " ").replace("\n", " ")
    return _esc_sq(s)


def overlays_chain(edl: dict) -> list[str]:
    """Text overlays on [vass] -> [vout], applied AFTER the ass captions.

    edl["overlays"] items: {text, pos "top"|"bottom"} (+ optional "type").
    y uses the target safe margins: h*0.10 for top, h*0.90 for bottom.
    """
    t = edl["target"]
    H = t["h"]
    items = [
        ov
        for ov in (edl.get("overlays") or [])
        if isinstance(ov, dict) and ov.get("text")
    ]
    if not items:
        return ["[vass]null[vout]"]
    fontfile = _overlay_font()
    parts: list[str] = []
    prev = "vass"
    for j, ov in enumerate(items):
        y = H * 0.10 if ov.get("pos") == "top" else H * 0.90
        nxt = "vout" if j == len(items) - 1 else f"vov{j}"
        # Book 2 additive extension: an overlay item may carry an "enable"
        # drawtext expression (e.g. a cold-open card shown for the first 2s).
        # Absent, behavior is exactly Book 1's (overlay for the whole clip).
        enable = ov.get("enable")
        enable_s = f":enable='{enable}'" if enable else ""
        parts.append(
            f"[{prev}]drawtext=fontfile='{_esc_sq(fontfile)}':"
            f"text='{_esc_drawtext(str(ov['text']))}':"
            f"fontsize=54:fontcolor=white:borderw=2:bordercolor=black:"
            f"x=(w-text_w)/2:y={y:.1f}{enable_s}[{nxt}]"
        )
        prev = nxt
    return parts


# ------------------------------------------------------------------ command

def _input_args(edl: dict) -> tuple[list[str], list[Path]]:
    """ffmpeg -i args (beat clips, then vo, then music) + input Paths."""
    args: list[str] = []
    paths: list[Path] = []
    for b in edl["beats"]:
        clip = b.get("clip")
        if not clip:
            raise RenderError(f"beat {b.get('id')}: no clip assigned")
        clip_in = float(b.get("clip_in") or 0.0)
        if clip_in > 0:
            args += ["-ss", f"{clip_in:.3f}"]
        args += ["-i", str(clip)]
        paths.append(Path(clip))
    audio = edl.get("audio") or {}
    for node in (audio.get("vo"), audio.get("music")):
        p = _audio_path(node)
        if p:
            args += ["-i", p]
            paths.append(Path(p))
    return args, paths


def _resolve_provenance(provenance: dict | None) -> dict:
    """The render provenance record actually used.

    ``provenance`` may carry a kit-derived dict (notably the kit's ``asr``
    block); when absent, :func:`manifests.provenance` builds the tool
    record with the asr entry marked "not-recorded" rather than invented.
    """
    if provenance is not None:
        return dict(provenance)
    return manifests_mod.provenance()


def build_command(
    edl: dict, work: str | Path, out: str | Path, provenance: dict | None = None
) -> tuple[list[str], str]:
    """Build the validated ffmpeg argv and the render hash.

    The manifest is verified FIRST: ``verify_manifest(work)`` re-hashes
    every attached asset and raises ``ManifestError`` on any mismatch, so
    no ffmpeg argv is ever built against tampered inputs.

    Returns (cmd, rhash). No shell involved; cmd is a plain arg list.
    Writes work/captions.ass when the EDL carries caption words.
    """
    work, out = Path(work), Path(out)
    manifests_mod.verify_manifest(work)
    work.mkdir(parents=True, exist_ok=True)
    prov = _resolve_provenance(provenance)
    beats = edl["beats"]
    total = beats[-1]["t_out"]

    input_args, input_paths = _input_args(edl)
    n_video = len(beats)

    caps = edl.get("captions") or {}
    words = caps.get("words") or []
    ass_path = None
    if words:
        ass_path = work / "captions.ass"
        cap_mod.build_ass(words, caps, edl["target"], ass_path)

    vparts = video_chain(edl, ass_path)
    aparts = audio_chain(edl, n_video)
    oparts = overlays_chain(edl)
    graph = ";".join(vparts + aparts + oparts)

    cmd = (
        ["ffmpeg", "-y", "-v", "error"]
        + input_args
        + [
            "-filter_complex", graph,
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "libx264", "-preset", "medium", "-crf", "19",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-movflags", "+faststart",
            "-t", f"{total:.3f}",
            str(out),
        ]
    )
    for a in cmd:  # validated arg array: plain strings only, nothing empty
        if not isinstance(a, str) or not a:
            raise RenderError(f"invalid ffmpeg argv element: {a!r}")

    rhash = manifests_mod.render_hash(edl, input_paths, prov)
    return cmd, rhash


# ------------------------------------------------------------------ render

_EDLS_DDL = """CREATE TABLE IF NOT EXISTS edls(
  job_id TEXT NOT NULL, version INTEGER NOT NULL,
  render_json TEXT NOT NULL, render_hash TEXT, created_at TEXT NOT NULL,
  PRIMARY KEY (job_id, version))"""
_RENDERS_DDL = """CREATE TABLE IF NOT EXISTS renders(
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, edl_version INTEGER NOT NULL,
  aspect TEXT NOT NULL, path TEXT NOT NULL, duration_s REAL, lufs REAL,
  manifest_json TEXT, created_at TEXT NOT NULL)"""


def _ensure_render_tables(conn) -> None:
    """Defensive DDL (the DB layer owns these tables; IF NOT EXISTS is a
    no-op when they already exist) plus a shape check that fails closed."""
    conn.execute(_EDLS_DDL)
    conn.execute(_RENDERS_DDL)
    edl_cols = {r[1] for r in conn.execute("PRAGMA table_info(edls)")}
    ren_cols = {r[1] for r in conn.execute("PRAGMA table_info(renders)")}
    if "render_hash" not in edl_cols or "version" not in edl_cols:
        raise RenderError("edls table lacks the Book-1 columns (version, render_hash)")
    if "edl_version" not in ren_cols or "duration_s" not in ren_cols:
        raise RenderError("renders table lacks the Book-1 columns")
    if "manifest_json" not in ren_cols:
        raise RenderError("renders table lacks manifest_json (Book 1, delta item 4)")


def _latest_render_hash(conn, job_id: str) -> str | None:
    row = conn.execute(
        "SELECT render_hash FROM edls WHERE job_id=? ORDER BY version DESC LIMIT 1",
        (job_id,),
    ).fetchone()
    return row[0] if row else None


def render(
    edl: dict,
    work: str | Path,
    out: str | Path,
    conn=None,
    job_id: str | None = None,
    force: bool = False,
    provenance: dict | None = None,
) -> dict:
    """Render an EDL to out. Returns {"path", "render_hash", "skipped"}.

    Gate order:
      1. slots-filled check: every beat clip must exist on disk — raises
         RenderError naming the missing slot BEFORE ffmpeg is ever invoked;
      2. manifest verification: build_command re-hashes every attached
         asset first (ManifestError on tampering);
      3. render-hash skip: when not force and the edls table already holds
         this render_hash as the latest version for job_id and out exists,
         return {"skipped": True} without running ffmpeg;
      4. run ffmpeg (stderr tail on failure), append the render entry
         {render_hash, provenance, ffmpeg argv, started_at, finished_at,
         input_hashes} to work/manifest.json, then insert the renders row
         (duration from ffprobe, manifest_json = the entry) and the edls
         row (version = max+1).
    DB writes only happen when both conn and job_id are given.
    """
    work, out = Path(work), Path(out)

    # 1. slots-filled gate — before build_command, before ffmpeg.
    missing = [
        f"{b.get('id', '?')}->{b.get('clip')!r}"
        for b in (edl.get("beats") or [])
        if not b.get("clip") or not Path(b["clip"]).is_file()
    ]
    if missing:
        raise RenderError(
            "slots-filled gate: missing beat clip(s): " + "; ".join(missing)
        )

    prov = _resolve_provenance(provenance)
    # Crash-safe output: ffmpeg writes to a PID-unique temp file; only a
    # fully-written, probed render is atomically renamed onto the final
    # path. A SIGKILLed worker can never leave a corrupt partial file at
    # `out`, and its orphaned ffmpeg child (which SIGKILL cannot reap)
    # keeps writing to the temp file only — a reclaiming worker renders to
    # its own temp file, so the two never interleave on one path.
    tmp = out.with_name(f"{out.stem}.partial-{os.getpid()}{out.suffix}")
    cmd, rhash = build_command(edl, work, tmp, provenance=prov)
    use_db = conn is not None and job_id is not None

    # 3. skip when this exact render already exists.
    if use_db and not force:
        _ensure_render_tables(conn)
        if _latest_render_hash(conn, job_id) == rhash and out.is_file():
            return {"path": str(out), "render_hash": rhash, "skipped": True}

    # 4. run ffmpeg.
    try:
        from . import util as _util
    except ImportError as e:
        raise RenderError(f"hypelab.util is required to probe output: {e}") from e
    started_at = _util.now()
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT, shell=False
    )
    finished_at = _util.now()
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RenderError(f"ffmpeg render failed: {proc.stderr[-2000:]}")

    try:
        duration = _util.ffprobe(str(tmp))["duration_s"]
    except _util.MediaError as e:
        tmp.unlink(missing_ok=True)
        raise RenderError(f"ffprobe of render output failed: {e}") from e
    os.replace(tmp, out)

    input_hashes = {}
    for _p in (b.get("clip") for b in edl.get("beats") or []):
        if _p:
            input_hashes[str(_p)] = manifests_mod.sha256_file(_p)
    audio = edl.get("audio") or {}
    for _node in (audio.get("vo"), audio.get("music")):
        _p = _node.get("path") if isinstance(_node, dict) else _node
        if _p:
            input_hashes[str(_p)] = manifests_mod.sha256_file(_p)
    manifest_entry = {
        "render_hash": rhash,
        "provenance": prov,
        "ffmpeg_argv": cmd,
        "started_at": started_at,
        "finished_at": finished_at,
        "input_hashes": input_hashes,
    }
    manifests_mod.record_render(work, manifest_entry)

    rec = {"path": str(out), "render_hash": rhash, "skipped": False}
    if use_db:
        _ensure_render_tables(conn)
        vrow = conn.execute(
            "SELECT MAX(version) FROM edls WHERE job_id=?", (job_id,)
        ).fetchone()
        edl_version = (vrow[0] or 0) + 1
        conn.execute(
            "INSERT INTO renders(id, job_id, edl_version, aspect, path,"
            " duration_s, lufs, manifest_json, created_at)"
            " VALUES(?,?,?,?,?,?,?,?,?)",
            (
                _util.new_id("r"),
                job_id,
                edl_version,
                edl["target"]["aspect"],
                str(out),
                duration,
                None,  # lufs: kept simple per Book 1 (duration from ffprobe)
                json.dumps(manifest_entry),
                _util.now(),
            ),
        )
        conn.execute(
            "INSERT INTO edls(job_id, version, render_json, render_hash,"
            " created_at) VALUES(?,?,?,?,?)",
            (job_id, edl_version, json.dumps(edl), rhash, _util.now()),
        )
        conn.commit()
    return rec


# ------------------------------------------------------------------ derive

_DERIVE_WH = {"1:1": (1080, 1080), "16:9": (1920, 1080)}


def derive(master: str | Path, aspect: str, work: str | Path) -> Path:
    """Derive a PREVIEW cutdown from the master (scale+crop, audio copy).

    Preview-only (improved Book 1, section 9): the output is always
    ``work/preview_<aspect>.mp4`` with a burned-in PREVIEW label, and it is
    NEVER inserted into the ``renders`` table — shipped aspects are
    re-rendered from the EDL. A preview is not a deliverable.
    """
    if aspect not in _DERIVE_WH:
        raise RenderError(f"unknown derive aspect: {aspect!r}")
    w, h = _DERIVE_WH[aspect]
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    out = work / f"preview_{aspect}.mp4"
    tmp = out.with_name(f"{out.stem}.partial-{os.getpid()}{out.suffix}")
    fontfile = _overlay_font()
    vf = (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1,"
        f"drawtext=fontfile='{_esc_sq(fontfile)}':"
        f"text='PREVIEW':fontsize=48:fontcolor=white@0.85:"
        f"borderw=2:bordercolor=black:x=24:y=24"
    )
    cmd = [
        "ffmpeg", "-y", "-v", "error", "-i", str(master),
        "-vf", vf,
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p",
        "-c:a", "copy",
        "-movflags", "+faststart",
        str(tmp),
    ]
    proc = subprocess.run(
        cmd, capture_output=True, text=True, timeout=FFMPEG_TIMEOUT, shell=False
    )
    if proc.returncode != 0:
        tmp.unlink(missing_ok=True)
        raise RenderError(f"aspect derivation failed: {proc.stderr[-500:]}")
    os.replace(tmp, out)
    return out
