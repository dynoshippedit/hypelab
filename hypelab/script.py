"""Script text -> timed beats (Book 1).

Pure function of (script_text, kit, target_s): sentences become beats with
speech-rate durations, roles hook/body/cta, and contiguous boundaries.
"""
from __future__ import annotations

import re

# Split after sentence-ending punctuation (keeps the punctuation on the line).
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")

# Default speech rate when the kit does not specify one.
_DEFAULT_WORDS_PER_S = 2.6
_DEFAULT_MIN_BEAT_S = 1.2


def _split_sentences(text: str) -> list[str]:
    return [s for s in (p.strip() for p in _SENT_SPLIT.split(text.strip())) if s]


def to_beats(script_text: str, kit: dict, target_s: float) -> list[dict]:
    """Split script_text into sentences and time them into beats.

    dur = min(max(words/words_per_sec, min_beat_s), kit generator.max_clip_s),
    where words_per_sec and min_beat_s come from kit["generator"]
    (defaults 2.6 / 1.2).
    Roles: first beat is "hook", last is "cta", the rest are "body"
    (a single-sentence script yields one hook beat, so the EDL's
    exactly-one-hook rule always holds).
    When the natural total exceeds target_s, all durations are scaled
    proportionally to fit; boundaries stay contiguous after rounding.
    """
    sentences = _split_sentences(script_text)
    if not sentences:
        raise ValueError("script_text produced no sentences")
    if not target_s or target_s <= 0:
        raise ValueError(f"target_s must be positive, got {target_s!r}")

    gen = kit.get("generator") or {}
    words_per_sec = float(gen.get("words_per_sec", _DEFAULT_WORDS_PER_S))
    min_beat_s = float(gen.get("min_beat_s", _DEFAULT_MIN_BEAT_S))
    if words_per_sec <= 0:
        raise ValueError(f"kit generator.words_per_sec must be positive, "
                         f"got {words_per_sec!r}")
    if min_beat_s <= 0:
        raise ValueError(f"kit generator.min_beat_s must be positive, "
                         f"got {min_beat_s!r}")
    max_clip_s = float(gen.get("max_clip_s", 10.0))
    ref_image = kit.get("reference_image")

    durs = []
    for sent in sentences:
        words = len(sent.split())
        durs.append(min(max(words / words_per_sec, min_beat_s), max_clip_s))

    total = sum(durs)
    if total > target_s:
        scale = target_s / total
        durs = [d * scale for d in durs]

    beats: list[dict] = []
    t = 0.0
    n = len(sentences)
    for i, (sent, dur) in enumerate(zip(sentences, durs)):
        # Boundaries are rounded once from the running total, so each
        # beat's t_in is exactly the previous beat's t_out.
        t_in, t_out = round(t, 3), round(t + dur, 3)
        role = "hook" if i == 0 else ("cta" if i == n - 1 else "body")
        beats.append(
            {
                "id": f"b{i + 1}",
                "role": role,
                "t_in": t_in,
                "t_out": t_out,
                "line": sent,
                "clip": None,
                "clip_in": 0.0,
                "clip_fit": "cover",
                "prompt_used": None,
                "ref_image": ref_image,
            }
        )
        t += dur
    return beats
