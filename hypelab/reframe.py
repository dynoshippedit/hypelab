"""Reframe 16:9 -> 9:16 (Book 2, section 8).

The core rule: HOLD AND CUT, NEVER PAN. A continuously-tracked crop reads as
a drunk camera operator. Compute a crop center per shot, hold it constant,
and hard-cut when the speaker changes. A cut reads as an edit; a pan reads
as amateur.

Modes (ship order: blurpad, static, split, track):
  static  — one speaker, locked-off shot. Cheapest, correct most often.
  track   — one speaker who moves, or cuts between speakers. Hold-and-cut,
            min 1.2s between switches.
  split   — two-person podcast, both on screen throughout. Top/bottom, no
            switching artifacts at all.
  blurpad — screen shares, slides, gameplay, anything with text. Honest
            fallback; never embarrassing.

Face detection: local OpenCV Haar cascade at 4 fps — no network, no heavy
deps. LIMITATION (documented, not averaged away): Haar cascades miss
profile/occluded faces and misfire on busy backgrounds; diarization is NOT
implemented, so track mode segments by face motion, not speaker identity.
Onscreen-text detection needs tesseract; without it the check is
inconclusive and choose_mode fails closed to blurpad (cropping text is
fatal — half a word on screen).

render.py's lazy hook calls reframe_filter(plan, target, src_w, src_h):
keyframe t is seconds from the CUT SEGMENT START (post -ss), because the
crop filter runs before trim/setpts in the render chain and -ss before -i
resets input timestamps to zero.
"""
from __future__ import annotations

import math
import shutil
import statistics
import subprocess
from pathlib import Path

#: Minimum hold between crop switches in track mode.
TRACK_MIN_SPAN_S = 1.2

#: Face sampling rate for detection.
FACE_STEP_S = 0.25

#: Static vs track threshold: std of face cx below this = locked-off.
STATIC_MOTION_MAX = 0.06

#: A face counts as persistent when present in this fraction of samples.
PERSISTENT_FRAC = 0.6


class ReframeError(Exception):
    """Reframe planning failed."""


# ------------------------------------------------------------------ detection

def _cascade_path() -> str | None:
    try:
        import cv2

        p = Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml"
        if p.is_file():
            return str(p)
    except Exception:
        pass
    for cand in ("/usr/share/opencv4/haarcascades"
                 "/haarcascade_frontalface_default.xml",
                 "/usr/share/opencv/haarcascades"
                 "/haarcascade_frontalface_default.xml"):
        if Path(cand).is_file():
            return cand
    return None


def detect_faces(src, t_in: float, t_out: float,
                 step: float = FACE_STEP_S) -> tuple[list[dict], str]:
    """Sample frames at 4 fps; return (faces, method).

    faces: [{t, cx, cy, w, h}] with normalized coords (largest face per
    frame). method is "haar-cascade-4fps", or "unavailable:..." when cv2 or
    the cascade is missing — in which case faces is [] and callers fail
    closed to blurpad.
    """
    try:
        import cv2
    except Exception:
        return [], "unavailable:no-opencv"
    cascade = _cascade_path()
    if cascade is None:
        return [], "unavailable:no-haar-cascade"
    clf = cv2.CascadeClassifier(cascade)
    if clf.empty():
        return [], "unavailable:cascade-load-failed"

    cap = cv2.VideoCapture(str(src))
    if not cap.isOpened():
        return [], "unavailable:cannot-open-source"
    faces = []
    try:
        t = float(t_in)
        while t <= float(t_out):
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok or frame is None:
                t += step
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            h, w = gray.shape[:2]
            found = clf.detectMultiScale(gray, scaleFactor=1.15,
                                         minNeighbors=4,
                                         minSize=(h // 8, h // 8))
            if len(found):
                x, y, fw, fh = max(found, key=lambda b: b[2] * b[3])
                faces.append({
                    "t": round(t, 3),
                    "cx": round((x + fw / 2) / w, 4),
                    "cy": round((y + fh / 2) / h, 4),
                    "w": round(fw / w, 4),
                    "h": round(fh / h, 4),
                })
            t += step
    finally:
        cap.release()
    return faces, "haar-cascade-4fps"


def has_onscreen_text(src, t0: float, t1: float) -> tuple[bool | None, str]:
    """Onscreen-text check (runs FIRST in mode selection).

    Returns (True/False/None, method). None = inconclusive: tesseract is not
    installed, so the check cannot run. Callers MUST treat None as fail-closed
    (blurpad) — cropping a chart or lower-third produces half a word on
    screen, and no tracking saves it.
    """
    if shutil.which("tesseract") is None:
        return None, "unavailable:no-ocr-binary"
    mid = (float(t0) + float(t1)) / 2.0
    frame = Path(f"/tmp/hypelab_textcheck_{abs(hash(str(src))) % 10**8}.png")
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-v", "error", "-ss", f"{mid:.2f}",
             "-i", str(src), "-frames:v", "1", str(frame)],
            capture_output=True, text=True, timeout=60, shell=False,
        )
        if proc.returncode != 0 or not frame.is_file():
            return None, "ocr:frame-extract-failed"
        proc = subprocess.run(
            ["tesseract", str(frame), "stdout", "--psm", "6"],
            capture_output=True, text=True, timeout=60, shell=False,
        )
        text = (proc.stdout or "").strip()
        return (len(text) > 12, "tesseract-psm6")
    except Exception:
        return None, "ocr:error"
    finally:
        try:
            frame.unlink()
        except OSError:
            pass


# ------------------------------------------------------------------ analysis

def distinct_faces(faces: list[dict]) -> int:
    """Cluster detections by horizontal position (crude identity)."""
    cxs = sorted(f["cx"] for f in faces)
    clusters = 0
    last = -1.0
    for cx in cxs:
        if cx - last > 0.12:
            clusters += 1
            last = cx
    return clusters


def face_motion(faces: list[dict]) -> float:
    """Std of face cx: locked-off vs moving speaker."""
    if len(faces) < 2:
        return 0.0
    return statistics.pstdev(f["cx"] for f in faces)


def both_persistent(faces: list[dict], t_in: float, t_out: float) -> bool:
    """Two face clusters each present in most samples."""
    if distinct_faces(faces) != 2:
        return False
    cxs = sorted(f["cx"] for f in faces)
    mid = (cxs[len(cxs) // 2 - 1] + cxs[len(cxs) // 2]) / 2.0
    left = [f for f in faces if f["cx"] < mid]
    right = [f for f in faces if f["cx"] >= mid]
    n_samples = max(1, int((t_out - t_in) / FACE_STEP_S))
    return (len(left) / n_samples > PERSISTENT_FRAC
            and len(right) / n_samples > PERSISTENT_FRAC)


def speaker_spans(faces: list[dict], t_in: float,
                  t_out: float) -> list[dict]:
    """Segment the range into speaker spans for track mode.

    LIMITATION: no diarization is implemented. Spans are derived from face
    clusters (one span per persistent face cluster, cut where the dominant
    cluster changes). Single-face footage yields one span — track then
    behaves like static with a documented reason.
    """
    if not faces:
        return [{"t0": t_in, "t1": t_out, "cx": 0.5, "note": "no-faces"}]
    if distinct_faces(faces) <= 1:
        cx = statistics.median(f["cx"] for f in faces)
        return [{"t0": t_in, "t1": t_out, "cx": cx,
                 "note": "single-face:no-diarization"}]
    cxs = sorted(f["cx"] for f in faces)
    mid = (cxs[len(cxs) // 2 - 1] + cxs[len(cxs) // 2]) / 2.0
    spans, cur = [], None
    for f in sorted(faces, key=lambda x: x["t"]):
        side = "L" if f["cx"] < mid else "R"
        if cur is None or cur["side"] != side:
            if cur is not None:
                spans.append(cur)
            cur = {"t0": f["t"], "t1": f["t"], "side": side, "cxs": []}
        cur["t1"] = f["t"]
        cur["cxs"].append(f["cx"])
    if cur is not None:
        spans.append(cur)
    out = []
    for sp in spans:
        dur = sp["t1"] - sp["t0"]
        if dur < TRACK_MIN_SPAN_S and out:
            out[-1]["t1"] = sp["t1"]  # merge short spans, hold the cut
            continue
        out.append({"t0": sp["t0"], "t1": sp["t1"],
                    "cx": statistics.median(sp["cxs"]),
                    "note": "face-cluster-span"})
    if out:
        out[0]["t0"] = t_in
        out[-1]["t1"] = t_out
    return out


def two_speaker_boxes(faces: list[dict], src_w: int, src_h: int) -> tuple[dict, dict]:
    """Top/bottom crop boxes, one per speaker cluster (source pixels)."""
    cxs = sorted(f["cx"] for f in faces)
    mid = (cxs[len(cxs) // 2 - 1] + cxs[len(cxs) // 2]) / 2.0
    left = [f["cx"] for f in faces if f["cx"] < mid]
    right = [f["cx"] for f in faces if f["cx"] >= mid]
    cw = int(src_h * 9 / 16) // 2 * 2
    ch = src_h // 2 // 2 * 2

    def _box(cx):
        x = int((src_w - cw) * min(max(cx, 0.0), 1.0)) // 2 * 2
        return {"w": cw, "h": ch, "x": x}

    a = _box(statistics.median(left))
    a["y"] = 0
    b = _box(statistics.median(right))
    b["y"] = src_h // 2 // 2 * 2
    return a, b


# ------------------------------------------------------------------ planning

def choose_mode(faces: list[dict], src, t0: float, t1: float,
                face_method: str = "") -> tuple[str, dict]:
    """Pick the reframe mode. The onscreen-text check runs FIRST; an
    inconclusive text check fails closed to blurpad."""
    text, text_method = has_onscreen_text(src, t0, t1)
    why = {"text_check": text_method, "face_method": face_method,
           "n_faces": len(faces)}
    if text:
        why["reason"] = "onscreen-text: cropping text is fatal"
        return "blurpad", why
    n = distinct_faces(faces)
    why["distinct_faces"] = n
    if n == 0:
        why["reason"] = "no faces detected"
        return "blurpad", why
    if text is None:
        # Fail closed: cannot prove the frame is text-free.
        why["reason"] = "text check inconclusive (no OCR) — fail closed"
        return "blurpad", why
    if n == 1:
        motion = face_motion(faces)
        why["face_motion"] = round(motion, 4)
        if motion < STATIC_MOTION_MAX:
            why["reason"] = "one locked-off speaker"
            return "static", why
        why["reason"] = "one moving speaker"
        return "track", why
    if n == 2 and both_persistent(faces, t0, t1):
        why["reason"] = "two persistent speakers"
        return "split", why
    why["reason"] = "multi-face: hold-and-cut track"
    return "track", why


def plan_reframe(src, t_in: float, t_out: float, target: dict,
                 mode: str = "auto") -> dict:
    """Build the reframe plan for a cut segment.

    ``target`` = {"w","h"}. ``mode`` = auto|static|track|split|blurpad.
    Keyframe t is seconds from the segment start (post -ss). The plan lands
    in the EDL's reframe block, so it re-renders deterministically
    (Book 1: same EDL + same source hash = same clip).
    """
    t_in, t_out = float(t_in), float(t_out)
    faces, face_method = detect_faces(src, t_in, t_out)
    why = {"face_method": face_method, "n_faces": len(faces)}
    if mode == "auto":
        mode, why = choose_mode(faces, src, t_in, t_out,
                                face_method=face_method)
    plan = {"mode": mode, "t_in": t_in, "t_out": t_out,
            "target": {"w": int(target["w"]), "h": int(target["h"])},
            "detection": why}

    if mode == "static":
        cx = statistics.median([f["cx"] for f in faces]) if faces else 0.5
        plan["keyframes"] = [{"t": 0.0, "cx": round(cx, 4),
                              "cy": 0.42, "scale": 1.0}]
    elif mode == "track":
        kf = []
        for sp in speaker_spans(faces, t_in, t_out):
            kf.append({"t": round(sp["t0"] - t_in, 3),
                       "cx": round(sp["cx"], 4), "cy": 0.42,
                       "scale": 1.0, "hold": True})
        plan["keyframes"] = kf
    elif mode == "split":
        if not faces:
            # No faces to split on: degrade honestly to blurpad.
            plan["mode"] = "blurpad"
            plan["detection"]["reason"] = \
                "split requested but no faces: degraded to blurpad"
        else:
            a, b = two_speaker_boxes(
                faces, *_source_wh(src))
            plan["boxes"] = [a, b]
    elif mode == "blurpad":
        pass
    else:
        raise ReframeError(f"unknown reframe mode {mode!r}")
    return plan


def _source_wh(src) -> tuple[int, int]:
    from .util import ffprobe

    info = ffprobe(str(src))
    return int(info["width"]), int(info["height"])


# ------------------------------------------------------------------ filtergen

def step_expr(keyframes: list[dict]) -> str:
    """Nested if(lt(t,…)) step function: the crop SNAPS between held
    positions instead of sliding. keyframes: [{t, x}] sorted by t, where x
    is the crop x-offset in pixels for t in [t_k, t_{k+1})."""
    stops = sorted(((float(k["t"]), int(k["x"])) for k in keyframes),
                   key=lambda s: s[0])
    if not stops:
        raise ReframeError("step_expr needs at least one keyframe")
    expr = str(stops[-1][1])
    for i in range(len(stops) - 1, 0, -1):
        tk, _ = stops[i]
        prev_x = stops[i - 1][1]
        expr = f"if(lt(t,{tk:.3f}),{prev_x},{expr})"
    return expr


def reframe_filter(plan: dict, target: dict, src_w: int, src_h: int) -> str:
    """Build the ffmpeg video filter for a reframe plan.

    Signature matches render.py's lazy hook exactly:
        reframe_filter(plan, target, src_w, src_h)
    where target = edl["target"] ({"w","h"}), src_w/src_h from ffprobe.
    """
    W, H = int(target["w"]), int(target["h"])
    mode = plan.get("mode")

    if mode == "blurpad":
        return (
            "split=2[bg][fg];"
            f"[bg]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},gblur=sigma=40[bgb];"
            f"[fg]scale={W}:-2[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2"
        )

    if mode == "split":
        (a, b) = plan["boxes"]
        return (
            "split=2[t][b];"
            f"[t]crop={a['w']}:{a['h']}:{a['x']}:{a['y']},"
            f"scale={W}:{H // 2}[tt];"
            f"[b]crop={b['w']}:{b['h']}:{b['x']}:{b['y']},"
            f"scale={W}:{H // 2}[bb];"
            "[tt][bb]vstack=inputs=2"
        )

    if mode in ("static", "track"):
        cw = int(src_h * W / H) // 2 * 2  # crop width for the 9:16 window
        if cw >= src_w:
            # Source narrower than the target window: no crop possible.
            return f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}"
        kf = []
        for k in plan.get("keyframes") or []:
            x = int((src_w - cw) * float(k["cx"])) // 2 * 2
            kf.append({"t": float(k["t"]), "x": x})
        if not kf:
            kf = [{"t": 0.0, "x": int((src_w - cw) * 0.5) // 2 * 2}]
        expr = step_expr(kf)
        return f"crop={cw}:{src_h}:'{expr}':0,scale={W}:{H}"

    raise ReframeError(f"unknown reframe mode {mode!r}")
