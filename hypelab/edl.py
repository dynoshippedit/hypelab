"""Validation for render.json (EDL v1), slides.json, vo.words.json, beats.json.

Strict: anything the renderer would have to guess about is a rejection.
Returns a list of human-readable errors; empty list == valid.
"""
from __future__ import annotations
import re

EDL_VERSION = 1
MODES = {"original", "clip"}
ASPECTS = {"9:16", "1:1", "16:9"}
REFRAME_MODES = {"static", "track", "split", "blurpad"}
HOOK_BUDGET = {"original": 3.0, "clip": 2.0}

def _err(errors: list, path: str, msg: str) -> None:
    errors.append(f"{path}: {msg}")

def validate_edl(data: dict, asset_slots: set[str] | None = None) -> list[str]:
    e: list[str] = []
    if not isinstance(data, dict):
        return ["<root>: must be an object"]

    if data.get("edl_version") != EDL_VERSION:
        _err(e, "edl_version", f"must be {EDL_VERSION}")
    mode = data.get("mode")
    if mode not in MODES:
        _err(e, "mode", f"must be one of {sorted(MODES)}")
    if not data.get("kit") or not re.fullmatch(r"[A-Za-z0-9_-]+@\d+", str(data.get("kit"))):
        _err(e, "kit", "must look like 'kitid@version'")

    # target
    t = data.get("target")
    if not isinstance(t, dict):
        _err(e, "target", "missing object")
    else:
        if t.get("aspect") not in ASPECTS:
            _err(e, "target.aspect", f"must be one of {sorted(ASPECTS)}")
        for k in ("w", "h"):
            if not isinstance(t.get(k), int) or t[k] <= 0:
                _err(e, f"target.{k}", "must be a positive int")
        if not isinstance(t.get("fps"), (int, float)) or t["fps"] <= 0 or t["fps"] > 120:
            _err(e, "target.fps", "must be in (0, 120]")
        if not isinstance(t.get("max_duration_s"), (int, float)) or t["max_duration_s"] <= 0:
            _err(e, "target.max_duration_s", "must be positive")
        if not isinstance(t.get("loudness_lufs"), (int, float)) or not -30 <= t["loudness_lufs"] <= -8:
            _err(e, "target.loudness_lufs", "must be in [-30, -8]")

    # audio
    a = data.get("audio")
    if not isinstance(a, dict):
        _err(e, "audio", "missing object")
    else:
        vo = a.get("vo", {})
        if not vo.get("slot"):
            _err(e, "audio.vo.slot", "missing")
        if not vo.get("align_slot"):
            _err(e, "audio.vo.align_slot", "missing")
        mu = a.get("music", {})
        if mu:
            if not mu.get("slot"):
                _err(e, "audio.music.slot", "missing")
            dd = mu.get("duck_db", -12)
            if not isinstance(dd, (int, float)) or not -40 <= dd <= 0:
                _err(e, "audio.music.duck_db", "must be in [-40, 0]")
            for k in ("fade_in_s", "fade_out_s"):
                if not isinstance(mu.get(k), (int, float)) or mu[k] < 0 or mu[k] > 10:
                    _err(e, f"audio.music.{k}", "must be in [0, 10]")

    # beats
    beats = data.get("beats")
    if not isinstance(beats, list) or not beats:
        _err(e, "beats", "must be a non-empty list")
        beats = []
    seen_ids = set()
    prev_out = 0.0
    for i, b in enumerate(beats):
        p = f"beats[{i}]"
        if not isinstance(b, dict):
            _err(e, p, "must be an object"); continue
        bid = b.get("id")
        if not bid or bid in seen_ids:
            _err(e, p + ".id", "missing or duplicated")
        seen_ids.add(bid)
        if b.get("role") not in {"hook", "body", "cta"}:
            _err(e, p + ".role", "must be hook|body|cta")
        tin, tout = b.get("t_in"), b.get("t_out")
        if not isinstance(tin, (int, float)) or not isinstance(tout, (int, float)):
            _err(e, p, "t_in/t_out must be numbers"); continue
        if not tout > tin:
            _err(e, p, "t_out must be > t_in")
        if i == 0 and abs(tin) > 1e-6:
            _err(e, p + ".t_in", "first beat must start at 0")
        if tin < prev_out - 1e-6:
            _err(e, p + ".t_in", f"overlaps previous beat (prev t_out={prev_out})")
        if tin > prev_out + 1e-6:
            _err(e, p + ".t_in", f"gap before this beat (prev t_out={prev_out})")
        prev_out = tout
        if not b.get("line"):
            _err(e, p + ".line", "missing script line")
        if not b.get("clip_slot"):
            _err(e, p + ".clip_slot", "missing")
        elif asset_slots is not None and b["clip_slot"] not in asset_slots:
            _err(e, p + ".clip_slot",
                 f"slot '{b['clip_slot']}' has no attached asset")
        if b.get("clip_fit") not in {"cover", "contain"}:
            _err(e, p + ".clip_fit", "must be cover|contain")

    # hook budget
    if beats and mode in HOOK_BUDGET:
        hook = beats[0]
        dur = hook.get("t_out", 0) - hook.get("t_in", 0)
        if dur > HOOK_BUDGET[mode] + 1e-6:
            _err(e, "beats[0]", f"hook {dur:.2f}s exceeds budget {HOOK_BUDGET[mode]}s")

    # reframe (detail-checked by validate_edl_reframe, merged in validate_all)
    if not isinstance(data.get("reframe"), dict):
        _err(e, "reframe", "missing object (detail-checked in validate_all)")

    # captions
    c = data.get("captions")
    if not isinstance(c, dict):
        _err(e, "captions", "missing object")
    else:
        if c.get("style") not in {"word_pop", "line", "none"}:
            _err(e, "captions.style", "must be word_pop|line|none")
        sz = c.get("size")
        if not isinstance(sz, (int, float)) or not 24 <= sz <= 160:
            _err(e, "captions.size", "must be in [24, 160]")
        for k in ("safe_top_pct", "safe_bottom_pct"):
            v = c.get(k)
            if not isinstance(v, (int, float)) or not 0 <= v <= 40:
                _err(e, f"captions.{k}", "must be in [0, 40]")
        if isinstance(c.get("safe_top_pct"), (int, float)) and isinstance(
                c.get("safe_bottom_pct"), (int, float)):
            if c["safe_top_pct"] + c["safe_bottom_pct"] >= 80:
                _err(e, "captions", "safe areas overlap")
        mc = c.get("max_chars_per_card")
        if not isinstance(mc, int) or not 8 <= mc <= 60:
            _err(e, "captions.max_chars_per_card", "must be int in [8, 60]")

    # creative block (attribution dimensions — required so what_worked has data)
    cr = data.get("creative")
    if not isinstance(cr, dict):
        _err(e, "creative", "missing attribution block")
    else:
        for k in ("hook_len_s", "beat_count", "caption_style"):
            if k not in cr:
                _err(e, f"creative.{k}", "missing")

    return e


def validate_edl_reframe(data: dict) -> list[str]:
    """Separate so the main validator stays readable; merged by validate_all."""
    e: list[str] = []
    rf = data.get("reframe")
    if not isinstance(rf, dict):
        return ["reframe: missing object"]
    if rf.get("mode") not in REFRAME_MODES:
        e.append(f"reframe.mode: must be one of {sorted(REFRAME_MODES)}")
    kfs = rf.get("keyframes")
    if not isinstance(kfs, list) or not kfs:
        e.append("reframe.keyframes: must be a non-empty list")
    else:
        for i, k in enumerate(kfs):
            for f in ("t", "cx", "cy", "scale"):
                if not isinstance(k.get(f), (int, float)):
                    e.append(f"reframe.keyframes[{i}].{f}: must be a number")
            if isinstance(k.get("cx"), (int, float)) and not 0 <= k["cx"] <= 1:
                e.append(f"reframe.keyframes[{i}].cx: must be in [0,1]")
            if isinstance(k.get("cy"), (int, float)) and not 0 <= k["cy"] <= 1:
                e.append(f"reframe.keyframes[{i}].cy: must be in [0,1]")
    return e


def validate_all(data: dict, asset_slots: set[str] | None = None) -> list[str]:
    return validate_edl(data, asset_slots) + validate_edl_reframe(data)


# ---------------------------------------------------------------- words/beat grids

def validate_words(data: dict) -> list[str]:
    e: list[str] = []
    if data.get("words_version") != 1:
        e.append("words_version: must be 1")
    words = data.get("words")
    if not isinstance(words, list) or not words:
        return e + ["words: must be a non-empty list"]
    prev_t1 = -1.0
    for i, w in enumerate(words):
        p = f"words[{i}]"
        if not w.get("w"):
            e.append(f"{p}.w: missing")
        t0, t1 = w.get("t0"), w.get("t1")
        if not isinstance(t0, (int, float)) or not isinstance(t1, (int, float)):
            e.append(f"{p}: t0/t1 must be numbers"); continue
        if not t1 > t0:
            e.append(f"{p}: t1 must be > t0")
        if t0 < prev_t1 - 1e-6:
            e.append(f"{p}.t0: overlaps previous word")
        prev_t1 = t1
    return e


def validate_slides(data: dict) -> list[str]:
    e: list[str] = []
    if data.get("slides_version") != 1:
        e.append("slides_version: must be 1")
    slides = data.get("slides")
    if not isinstance(slides, list) or len(slides) != 7:
        return e + ["slides: must be a list of exactly 7"]
    roles = [s.get("role") for s in slides]
    if roles[0] != "cover" or roles[-1] != "cta":
        e.append("slides: first must be 'cover', last must be 'cta'")
    for i, s in enumerate(slides):
        if not s.get("heading"):
            e.append(f"slides[{i}].heading: missing")
    return e
