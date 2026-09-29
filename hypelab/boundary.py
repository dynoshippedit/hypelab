"""Boundary refinement + cold open (Book 2, section 7).

A score gives you a center. The in/out points are a separate problem:
never open mid-sentence, never cut mid-breath, respect the campaign's
min/max, and keep the payload inside the ~2s hook budget — or convert the
moment with a cold open (premise card ≤ 9 words over the payload start).
"""
from __future__ import annotations

import re

from .score import PATTERNS

#: Sentence-ending punctuation for sentence segmentation.
_SENT_END = re.compile(r"[.!?…]+$")

#: The payload must land inside this many seconds of the clip open.
HOOK_BUDGET_S = 2.0

#: Cold-open premise card hold.
CARD_HOLD_S = 1.6


# ------------------------------------------------------------------ sentences

def sentences(words: list[dict]) -> list[dict]:
    """Group word timings into sentences: {t0, t1, text}.

    A sentence ends at a word whose text ends in . ! ? …. Words are expected
    to carry their punctuation (as Book 1's transcriber emits them).
    """
    out, cur = [], []
    for w in words:
        cur.append(w)
        if _SENT_END.search(w["w"] or ""):
            out.append({
                "t0": cur[0]["t0"], "t1": cur[-1]["t1"],
                "text": " ".join(x["w"] for x in cur),
                "words": list(cur),
            })
            cur = []
    if cur:  # trailing fragment without terminal punctuation
        out.append({
            "t0": cur[0]["t0"], "t1": cur[-1]["t1"],
            "text": " ".join(x["w"] for x in cur),
            "words": list(cur),
        })
    return out


def snap_to_sentence_start(words: list[dict], t: float) -> float:
    """Never open mid-sentence: if t falls inside a sentence, return that
    sentence's start. In a gap between sentences, t is kept."""
    for s in sentences(words):
        if s["t0"] <= t <= s["t1"]:
            return s["t0"]
        if t < s["t0"]:
            return t
    ss = sentences(words)
    return ss[-1]["t0"] if ss else t


def snap_to_sentence_end(words: list[dict], t: float) -> float:
    """Snap t to the nearest sentence end at or before t (for trimming)."""
    best = None
    for s in sentences(words):
        if s["t1"] <= t + 1e-6:
            best = s["t1"]
        elif s["t0"] <= t <= s["t1"]:
            return s["t1"]
        else:
            break
    return best if best is not None else t


def backfill_premise(words: list[dict], t0: float) -> float:
    """Walk back one sentence to include the setup the payload needs."""
    prev = None
    for s in sentences(words):
        if s["t0"] < t0 - 1e-6:
            prev = s
        else:
            break
    return prev["t0"] if prev is not None else t0


def extend_to_silence(pauses: list, t: float, max_extra: float) -> float:
    """Extend t through a nearby silence (never cut mid-breath).

    ``pauses``: [(start, end), ...]. If a pause overlaps [t, t+max_extra],
    t moves to the pause end (capped at t+max_extra); otherwise t is kept.
    """
    for ps, pe in pauses or []:
        ps, pe = float(ps), float(pe)
        if ps <= t + max_extra and pe >= t:
            return min(pe, t + max_extra)
    return t


# ------------------------------------------------------------------ payload

def _first_hit_charpos(text: str):
    best = None
    for name, (rx, _w) in PATTERNS.items():
        m = rx.search(text or "")
        if m and (best is None or m.start() < best[1]):
            best = (name, m.start())
    return best


def payload_offset(words: list[dict], t_in: float, t_out: float) -> float:
    """Seconds from t_in to the first pattern hit in the window.

    0.0 when no pattern hits (no payload found — no cold open triggered).
    """
    win = [w for w in words if w["t1"] > t_in and w["t0"] < t_out]
    text = " ".join(w["w"] for w in win)
    hit = _first_hit_charpos(text)
    if hit is None:
        return 0.0
    pos = 0
    for w in win:
        nxt = pos + len(w["w"]) + 1
        if pos <= hit[1] < nxt:
            return max(0.0, w["t0"] - t_in)
        pos = nxt
    return 0.0


def find_payload_sentence(words: list[dict], t_in: float,
                          t_out: float) -> dict | None:
    """The sentence containing the first pattern hit in the window."""
    win = [w for w in words if w["t1"] > t_in and w["t0"] < t_out]
    text = " ".join(w["w"] for w in win)
    hit = _first_hit_charpos(text)
    if hit is None:
        return None
    pos = 0
    hit_word = None
    for w in win:
        nxt = pos + len(w["w"]) + 1
        if pos <= hit[1] < nxt:
            hit_word = w
            break
        pos = nxt
    if hit_word is None:
        return None
    for s in sentences(words):
        if s["t0"] <= hit_word["t0"] <= s["t1"]:
            return s
    return None


def summarize_premise(words: list[dict], t0: float, payload_t0: float,
                      max_words: int = 9) -> str:
    """Setup text between the clip open and the payload, capped at 9 words."""
    setup = [w["w"] for w in words
             if w["t0"] >= t0 - 1e-6 and w["t1"] <= payload_t0 + 1e-6]
    toks = " ".join(setup).split()
    if len(toks) > max_words:
        toks = toks[:max_words]
    text = " ".join(toks).strip()
    return text + ("…" if len(" ".join(setup).split()) > max_words else "")


# ------------------------------------------------------------------ refine

def refine(moment: dict, words: list[dict], pauses: list,
           rules: dict) -> dict:
    """Refine a scored moment's in/out points. Mutates and returns moment.

    Order: snap open to sentence start -> backfill one sentence of premise ->
    snap close to sentence end -> extend through nearby silence -> enforce
    campaign min/max -> hook-budget check (flags needs_cold_open).
    """
    t0, t1 = float(moment["t_in"]), float(moment["t_out"])
    min_s = float(rules.get("min_s", 15))
    max_s = float(rules.get("max_s", 90))

    t0 = snap_to_sentence_start(words, t0)
    t0 = backfill_premise(words, t0)
    t1 = snap_to_sentence_end(words, t1)
    t1 = extend_to_silence(pauses, t1, max_extra=1.2)

    dur = t1 - t0
    if dur < min_s:
        t1 = extend_to_silence(pauses, t0 + min_s, max_extra=2.0)
        if t1 - t0 < min_s:  # no silence to extend through: hard floor
            t1 = t0 + min_s
    if t1 - t0 > max_s:
        t1 = snap_to_sentence_end(words, t0 + max_s)
        if t1 - t0 > max_s:  # degenerate: hard cap
            t1 = t0 + max_s

    moment["t_in"], moment["t_out"] = round(t0, 3), round(t1, 3)
    moment["needs_cold_open"] = (
        payload_offset(words, t0, t1) > HOOK_BUDGET_S
    )
    return moment


def cold_open(moment: dict, words: list[dict]) -> dict:
    """Convert a long-setup moment: start at the payload, backfill the
    premise as an opening caption card (≤ 9 words, 1.6s hold)."""
    t_in, t_out = float(moment["t_in"]), float(moment["t_out"])
    payload = find_payload_sentence(words, t_in, t_out)
    if payload is None:
        return {"t_in": t_in, "card": None}
    premise = summarize_premise(words, t_in, payload["t0"])
    return {
        "t_in": round(payload["t0"], 3),
        "card": {"text": premise, "hold_s": CARD_HOLD_S, "style": "premise"},
    }


# ------------------------------------------------------------------ select

def select(words: list[dict], t_in: float, t_out: float,
           rules: dict | None = None, cuts_cfg: dict | None = None,
           pauses=()) -> dict:
    """cut.py's entry point: refine boundaries, pick the cold-open card, and
    return clip-relative word timings for captions.

    refine() guarantees the segment never opens mid-sentence; caption_words
    are re-based so t=0 is the clip start (captions.build_ass needs that —
    absolute source timings would push every caption late or off the clip).
    """
    merged = dict(rules or {})
    for k in ("min_s", "max_s"):
        if isinstance(cuts_cfg, dict) and k in cuts_cfg:
            merged[k] = cuts_cfg[k]
    moment = {"t_in": float(t_in), "t_out": float(t_out)}
    refine(moment, words, list(pauses or []), merged)
    t_in_r, t_out_r = moment["t_in"], moment["t_out"]
    seg_words = [w for w in words
                 if w["t1"] > t_in_r and w["t0"] < t_out_r]
    co = cold_open(moment, words)
    card = co.get("card")
    payload = find_payload_sentence(words, t_in_r, t_out_r)
    if payload is not None:
        payload_words = [w for w in words
                         if w["t0"] >= payload["t0"]
                         and w["t1"] <= payload["t1"]]
    else:
        payload_words = seg_words[:24]
    rel = [dict(w, t0=round(w["t0"] - t_in_r, 3),
                t1=round(w["t1"] - t_in_r, 3)) for w in seg_words]
    return {
        "t_in": t_in_r,
        "t_out": t_out_r,
        "dur": round(t_out_r - t_in_r, 3),
        "words": seg_words,        # absolute timings (audit/debug)
        "caption_words": rel,      # clip-relative timings (captions)
        "payload_words": payload_words,
        "premise": card["text"] if card else None,
        "card": card,
        "cold_open": card is not None,
        "needs_cold_open": bool(moment.get("needs_cold_open")),
    }
