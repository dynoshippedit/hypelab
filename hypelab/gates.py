"""Quality gates (Book 1, section 11): fail the job, never ship it.

Uniform gate signature: ``gate_<name>(edl, render_path, work) -> (ok, detail)``.
``ok`` is a bool; ``detail`` is a human-readable string that ALWAYS
distinguishes "unreadable/corrupt input" from a creative failure (black open,
frozen open, over budget, ...), because the quality report routes on that
distinction.

``run_all`` executes every gate in ``GATES + EXTRA_GATES`` (later books append
to ``EXTRA_GATES``), records each verdict in the ``gate_results`` table, and
returns the ``[(name, ok, detail)]`` list.

Hard rules:
- ffmpeg/ffprobe run via validated argv arrays only (never shell=True, never
  shell-string interpolation).
- Deterministic: identical inputs always produce identical verdicts.
- Fail closed: anything we cannot read or measure fails its gate; unreadable
  media is never reported as passing.
- ``util`` (now()/ffprobe()/MediaError) is imported lazily inside functions.
  It is built in parallel by another agent and must NOT be vendored here.
"""
from __future__ import annotations

import json
import json
import re
import subprocess
import tempfile
from pathlib import Path

GATES = ["duration", "loudness", "first_frame", "hook_budget",
         "caption_safe", "slots_filled", "geometry", "word_confidence"]
EXTRA_GATES: list[str] = []

_FFMPEG_TIMEOUT = 180

_GATE_RESULTS_DDL = (
    "CREATE TABLE IF NOT EXISTS gate_results("
    "job_id TEXT NOT NULL, gate TEXT NOT NULL, passed INTEGER NOT NULL, "
    "detail TEXT, at TEXT NOT NULL)"
)


def _run(argv: list[str], timeout: int = _FFMPEG_TIMEOUT) -> subprocess.CompletedProcess:
    """Run a validated argv array. Never shell=True, never a shell string."""
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _stderr_tail(p: subprocess.CompletedProcess, n: int = 3) -> str:
    lines = (p.stderr or "").strip().splitlines()
    return " | ".join(lines[-n:]) if lines else "no stderr"


# ---------------------------------------------------------------- first_frame
# Book 1 section 11: first_frame = "frame 0 not black AND not identical to
# frame 1". No freezedetect heuristics: freezedetect (n=0.01:d=1.0)
# false-positived on valid synthetic movement, and the old gate ignored
# ffmpeg's nonzero return code so truncated/corrupt MP4s passed as "clean".

def _frame_pixels(png_path: Path) -> bytes | None:
    """Decode a PNG to raw rgb24 bytes; None if ffmpeg cannot decode it."""
    q = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(png_path),
         "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
        capture_output=True, timeout=60)
    if q.returncode != 0 or not q.stdout:
        return None
    return q.stdout


def gate_first_frame(edl: dict, render_path, work) -> tuple[bool, str]:
    render = str(render_path)

    # 1. Corruption check: nonzero ffmpeg exit => unreadable => FAIL CLOSED.
    #    NOTE on verbosity: the spec's step 2 needs blackdetect's
    #    "black_start:0" line in stderr, which blackdetect emits at info
    #    level. With "-v error" that line is suppressed for file inputs
    #    (verified: present with -v info, absent with -v error on the
    #    identical file), so this pass runs at info level. The fail-closed
    #    corruption check (returncode != 0) is verbosity-independent.
    try:
        p = _run(["ffmpeg", "-v", "info", "-i", render,
                  "-vf", "blackdetect=d=0.1:pix_th=0.10", "-f", "null", "-"])
    except subprocess.TimeoutExpired:
        return False, "unreadable input: ffmpeg timed out probing the file"
    if p.returncode != 0:
        return False, (f"unreadable input: ffmpeg exit {p.returncode}: "
                       f"{_stderr_tail(p)}")

    # 2. Opens on black?
    if "black_start:0" in (p.stderr or ""):
        return False, "opens on black: blackdetect flags black from t=0"

    # 3. Frozen open? Compare raw pixels of frame 0 vs frame 1.
    with tempfile.TemporaryDirectory(prefix="hypelab_gate_") as td:
        frames = []
        for n in (0, 1):
            out = Path(td) / f"f{n}.png"
            try:
                q = _run(["ffmpeg", "-v", "error", "-i", render,
                          "-vf", f"select=eq(n\\,{n})",
                          "-vframes", "1", str(out)], timeout=60)
            except subprocess.TimeoutExpired:
                return False, ("unreadable input: frame extraction timed out "
                               f"on frame {n}")
            if q.returncode != 0 or not out.exists():
                return False, (f"unreadable input: frame {n} extraction "
                               f"failed (ffmpeg exit {q.returncode}): "
                               f"{_stderr_tail(q)}")
            px = _frame_pixels(out)
            if px is None:
                return False, ("unreadable input: could not decode extracted "
                               f"frame {n}")
            frames.append(px)
    if frames[0] == frames[1]:
        return False, "frozen open: frame 0 identical to frame 1"
    return True, "ok: frame 0 is not black and differs from frame 1"


# ---------------------------------------------------------------- duration

def gate_duration(edl: dict, render_path, work) -> tuple[bool, str]:
    from . import util  # lazy: built in parallel, never vendored
    target = edl["target"]
    try:
        dur = float(util.ffprobe(str(render_path))["duration_s"])
    except Exception as ex:
        return False, f"unreadable input: ffprobe failed: {ex}"
    maxd = float(target["max_duration_s"])
    ok = 3.0 <= dur <= maxd
    return ok, f"duration {dur:.2f}s vs allowed 3.00s-{maxd:.2f}s"


# ---------------------------------------------------------------- loudness

#: Anchored pattern for loudnorm's print_format=json summary block: a JSON
#: object that actually contains the "input_i" key. loudnorm emits exactly
#: one such block at info level; anything else brace-shaped in stderr is
#: not the measurement.
_LOUDNORM_JSON_RE = re.compile(r"\{[^{}]*\"input_i\"[^{}]*\}", re.S)


def _loudnorm_integrated(stderr: str) -> float | None:
    """Strictly extract input_i from loudnorm's JSON summary block.

    The pattern is anchored to the block carrying "input_i" (the loudnorm
    summary), and the block is parsed with a single strict json.loads —
    no brace-hunting fallback. Returns None when the block is absent or
    unparsable; the caller turns that into a gate FAIL, never a crash.
    """
    m = _LOUDNORM_JSON_RE.search(stderr or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "input_i" not in data:
        return None
    try:
        return float(data["input_i"])
    except (TypeError, ValueError):
        return None


def gate_loudness(edl: dict, render_path, work) -> tuple[bool, str]:
    target = float(edl["target"]["loudness_lufs"])
    # No "-v error" here: the JSON summary is emitted at info level.
    p = _run(["ffmpeg", "-i", str(render_path),
              "-af", "loudnorm=print_format=json", "-f", "null", "-"])
    if p.returncode != 0:
        return False, (f"unreadable input: loudnorm failed "
                       f"(ffmpeg exit {p.returncode}): {_stderr_tail(p)}")
    integ = _loudnorm_integrated(p.stderr or "")
    if integ is None:
        return False, "unreadable input: could not parse loudnorm JSON"
    delta = abs(integ - target)
    ok = delta <= 1.0
    # Improved §11: record the measured value AND the renderer's loudnorm
    # parameters in the manifest (the render applies
    # loudnorm=I={target}:TP=-1.5:LRA=11; this gate verifies it).
    from . import manifests as manifests_mod  # lazy: built in parallel
    manifests_mod.record_measurement(work, "loudness", {
        "integrated_lufs": round(integ, 2),
        "target_lufs": target,
        "renderer_params": {"I": target, "TP": -1.5, "LRA": 11.0},
        "delta_lufs": round(delta, 2),
        "passed": ok,
    })
    return ok, (f"integrated {integ:.1f} LUFS vs target {target:.1f} LUFS "
                f"(delta {delta:.1f}, budget +/-1.0)")


# ---------------------------------------------------------------- hook_budget

def gate_hook_budget(edl: dict, render_path, work) -> tuple[bool, str]:
    b0 = edl["beats"][0]
    dur = float(b0["t_out"]) - float(b0["t_in"])
    budget = 2.0 if edl.get("mode") == "clip" else 3.0
    ok = dur <= budget
    return ok, (f"hook beat {dur:.2f}s vs budget {budget:.1f}s "
                f"(mode {edl.get('mode')!r})")


# ---------------------------------------------------------------- caption_safe

_LEGACY_TO_NUMPAD = {1: 1, 2: 2, 3: 3, 9: 4, 10: 5, 11: 6, 5: 7, 6: 8, 7: 9}
_CHAR_WIDTH_FACTOR = 0.6   # avg glyph advance as a fraction of fontsize
_LINE_HEIGHT_FACTOR = 1.2  # line box height as a fraction of fontsize


def _numpad_alignment(overrides: str, style_alignment) -> int:
    """Normalize ASS alignment (\\an1-9, legacy \\a1-11, or style value)
    to numpad 1-9."""
    m = re.search(r"\\an([1-9])", overrides or "")
    if m:
        return int(m.group(1))
    m = re.search(r"\\a(1[01]|[1-9])(?!\d)", overrides or "")
    if m:
        return _LEGACY_TO_NUMPAD.get(int(m.group(1)), 2)
    try:
        return _LEGACY_TO_NUMPAD.get(int(style_alignment), 2)
    except (TypeError, ValueError):
        return 2


def _event_box(ev, styles: dict, prx: float, pry: float,
               default_fs: float) -> tuple[float, float, float, float]:
    """Deterministic caption bounding box (x0, y0, x1, y1) in PlayRes px,
    derived from PlayRes + font size only."""
    raw = ev.text or ""
    overrides = "".join(re.findall(r"\{[^}]*\}", raw))
    text = re.sub(r"\{[^}]*\}", "", raw)
    style = styles.get(getattr(ev, "style", "") or "")
    fs = float(default_fs)
    margin_v = 20.0
    margin_l = 10.0
    margin_r = 10.0
    sal = 2
    if style is not None:
        try:
            fs = float(getattr(style, "fontsize", fs)) or fs
        except (TypeError, ValueError):
            pass
        for attr, default in (("marginv", margin_v), ("marginl", margin_l),
                              ("marginr", margin_r)):
            try:
                v = float(getattr(style, attr, default))
            except (TypeError, ValueError):
                v = default
            if attr == "marginv":
                margin_v = v
            elif attr == "marginl":
                margin_l = v
            else:
                margin_r = v
        sal = getattr(style, "alignment", sal)
    an = _numpad_alignment(overrides, sal)

    lines = text.replace("\\N", "\n").split("\n")
    nlines = max(1, len(lines))
    maxchars = max([len(line) for line in lines] + [0])
    width = maxchars * fs * _CHAR_WIDTH_FACTOR
    height = nlines * fs * _LINE_HEIGHT_FACTOR

    row = "bottom" if an in (1, 2, 3) else ("top" if an in (7, 8, 9)
                                           else "middle")
    if row == "bottom":
        y1 = pry - margin_v
        y0 = y1 - height
    elif row == "top":
        y0 = margin_v
        y1 = y0 + height
    else:
        y0 = pry / 2 - height / 2
        y1 = y0 + height

    if an in (1, 4, 7):
        x0, x1 = margin_l, margin_l + width
    elif an in (3, 6, 9):
        x1, x0 = prx - margin_r, prx - margin_r - width
    else:
        x0, x1 = prx / 2 - width / 2, prx / 2 + width / 2
    return (x0, y0, x1, y1)


def gate_caption_safe(edl: dict, render_path, work) -> tuple[bool, str]:
    ass_path = Path(work) / "captions.ass"
    if not ass_path.exists():
        return True, "no captions: captions.ass not present"
    try:
        import pysubs2
    except ImportError:
        return False, ("unreadable input: captions.ass present but pysubs2 "
                       "is not installed; cannot verify caption geometry")
    cap = edl.get("captions", {}) or {}
    tgt = edl.get("target", {}) or {}
    try:
        subs = pysubs2.load(str(ass_path))
    except Exception as ex:
        return False, f"unreadable input: cannot parse captions.ass: {ex}"
    try:
        prx = float(subs.info.get("PlayResX") or 0) or float(tgt.get("w") or 0)
        pry = float(subs.info.get("PlayResY") or 0) or float(tgt.get("h") or 0)
    except (TypeError, ValueError):
        prx = pry = 0.0
    if not prx or not pry:
        return False, "unreadable input: no PlayRes and no target dimensions"
    default_fs = cap.get("size", 48)
    top_lim = float(cap.get("safe_top_pct", 0)) / 100.0 * pry
    bot_lim = pry - float(cap.get("safe_bottom_pct", 0)) / 100.0 * pry
    bad = []
    for i, ev in enumerate(subs.events):
        _x0, y0, _x1, y1 = _event_box(ev, subs.styles, prx, pry, default_fs)
        if y0 < top_lim - 1e-9 or y1 > bot_lim + 1e-9:
            bad.append((i, y0, y1))
    n = len(subs.events)
    if bad:
        shown = ", ".join(f"#{i} y {y0:.0f}-{y1:.0f}" for i, y0, y1 in bad[:5])
        return False, (f"{len(bad)}/{n} caption event(s) intersect the safe "
                       f"margins (top {cap.get('safe_top_pct')}%, bottom "
                       f"{cap.get('safe_bottom_pct')}% of {pry:.0f}px): {shown}")
    return True, (f"ok: {n} caption event(s) inside safe area "
                  f"(top {cap.get('safe_top_pct')}%, bottom "
                  f"{cap.get('safe_bottom_pct')}%)")


# ---------------------------------------------------------------- slots_filled

def check_slots(edl: dict) -> list[str]:
    """Standalone pre-render check (also used by gate_slots_filled).

    Every beat must have a clip set, and any beat carrying a resolved
    ``clip_path`` must point at a file that exists on disk. Returns the list
    of problems; empty == all slots filled.
    """
    problems: list[str] = []
    for i, b in enumerate(edl.get("beats", [])):
        bid = b.get("id", f"[{i}]")
        if not b.get("clip_slot"):
            problems.append(f"missing clip for beat {bid}: no clip_slot set")
            continue
        cp = b.get("clip_path")
        if cp is not None and not Path(cp).is_file():
            problems.append(
                f"missing clip for beat {bid}: file not found: {cp}")
    return problems


def gate_slots_filled(edl: dict, render_path, work) -> tuple[bool, str]:
    problems = check_slots(edl)
    if problems:
        return False, "; ".join(problems)
    n = len(edl.get("beats", []))
    return True, f"ok: all {n} beat clip(s) set and present on disk"


# ---------------------------------------------------------------- geometry

def _parse_sar(v) -> float | None:
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    for sep in (":", "/"):
        if sep in s:
            a, b = s.split(sep, 1)
            try:
                return float(a) / float(b)
            except (ValueError, ZeroDivisionError):
                return None
    try:
        return float(s)
    except ValueError:
        return None


def gate_geometry(edl: dict, render_path, work) -> tuple[bool, str]:
    from . import util  # lazy: built in parallel, never vendored
    t = edl["target"]
    try:
        m = util.ffprobe(str(render_path))
    except Exception as ex:
        return False, f"unreadable input: ffprobe failed: {ex}"
    w, h = m.get("width"), m.get("height")
    fps = m.get("fps")
    sar = _parse_sar(m.get("sar"))
    detail = (f"actual {w}x{h}@{fps}fps sar={m.get('sar')} vs target "
              f"{t['w']}x{t['h']}@{t['fps']}fps sar=1:1")
    try:
        fps_ok = float(fps) == float(t["fps"])
    except (TypeError, ValueError):
        fps_ok = False
    sar_ok = sar is not None and abs(sar - 1.0) < 1e-9
    ok = (w == t["w"] and h == t["h"] and fps_ok and sar_ok)
    return ok, detail


# ---------------------------------------------------------------- run_all

def gate_word_confidence(edl: dict, render_path, work) -> tuple[bool, str]:
    """Fail beats containing words below the kit's ``min_word_prob``.

    Reads ``work/vo.words.json`` and ``edl["beats"]``; the threshold comes
    from the EDL's ``min_word_prob`` (stamped from the kit, default 0.5).
    A flagged job fails THIS gate with the reason — the work layer routes
    it to ``gate_failed``, never to ``failed``.

    Passes with a note when there is no words doc: nothing to judge.
    A malformed words doc, or words that cannot be mapped onto the beats,
    fails the gate (fail closed).
    """
    from . import align as align_mod  # lazy: built in parallel, never vendored
    wp = Path(work) / "vo.words.json"
    if not wp.is_file():
        return True, "no vo.words.json — word confidence not judged"
    try:
        doc = json.loads(wp.read_text())
    except json.JSONDecodeError as ex:
        return False, f"vo.words.json is malformed: {ex}"
    beats = edl.get("beats") or []
    try:
        threshold = float(edl.get("min_word_prob", 0.5))
    except (TypeError, ValueError):
        return False, "edl min_word_prob is not a number"
    try:
        flagged = align_mod.low_confidence_beats(
            doc, beats, min_word_prob=threshold)
    except align_mod.AlignError as ex:
        return False, f"word confidence unevaluable: {ex}"
    if not flagged:
        return True, (
            f"all {len(beats)} beats above min_word_prob={threshold}")
    desc = "; ".join(
        f"{f['beat_id']} ({f['line']!r} min_p={f['min_word_p']})"
        for f in flagged)
    return False, (
        f"low-confidence words below min_word_prob={threshold}: {desc}")


def run_all(conn, job_id: str, edl: dict, render_path, work
            ) -> list[tuple[str, bool, str]]:
    """Run every gate in GATES + EXTRA_GATES, record each verdict in the
    ``gate_results`` table (job_id, gate, passed, detail, at), and return the
    ``[(name, ok, detail)]`` list. A gate that raises is a failed gate."""
    from . import util  # lazy: built in parallel, never vendored
    conn.execute(_GATE_RESULTS_DDL)
    now = util.now()
    results: list[tuple[str, bool, str]] = []
    for name in GATES + EXTRA_GATES:
        fn = globals()["gate_" + name]
        try:
            ok, detail = fn(edl, render_path, work)
            ok = bool(ok)
            detail = str(detail)
        except Exception as ex:  # a gate that errors is a failed gate
            ok, detail = False, f"gate error: {type(ex).__name__}: {ex}"
        conn.execute(
            "INSERT INTO gate_results(job_id, gate, passed, detail, at) "
            "VALUES (?,?,?,?,?)",
            (job_id, name, int(ok), detail, now))
        results.append((name, ok, detail))
    return results


# ------------------------------------------------------------------ Book 3
# Consent gate, exposed here per improved Book 3 (gate_consent lives in
# gates.py). Thin wrapper over hypelab.consent.gate_consent — the consent
# module owns the logic; this is the discoverable entry point alongside
# the media gates above. Signature differs from the media gates on
# purpose: consent is about collaborators, not EDLs.
def gate_consent(conn, job_id, collaborators, platform="instagram", record=True):
    """Book 3 consent gate: every collaborator needs granted, unrevoked,
    unexpired consent. Delegates to hypelab.consent."""
    from . import consent as _consent
    return _consent.gate_consent(conn, job_id, collaborators,
                                 platform=platform, record=record)
