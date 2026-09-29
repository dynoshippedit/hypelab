"""Word-level caption cards -> ASS subtitles (word-pop karaoke) via pysubs2.

Port of the previous string-template implementation: the karaoke sweep,
card grouping, and kit-style mapping are preserved; the file is now built
with pysubs2 instead of hand-rolled ASS text.
"""
from __future__ import annotations

from pathlib import Path

# A new card starts when the char budget is exceeded OR the pause between
# consecutive words exceeds this many seconds.
PAUSE_SPLIT_S = 0.45
# Hold after the last word of a card so it stays readable.
HOLD_S = 0.25


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    h = hex_color.lstrip("#")
    if len(h) != 6:
        raise ValueError(f"bad hex color: {hex_color!r}")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def group_into_cards(words: list[dict], max_chars: int) -> list[list[dict]]:
    """Group words into caption cards.

    A new card starts when adding the next word would exceed max_chars,
    or when the gap w[i].t0 - w[i-1].t1 exceeds PAUSE_SPLIT_S (a real
    pause in speech). words are dicts with "w", "t0", "t1".
    """
    cards: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for i, w in enumerate(words):
        wl = len(w["w"]) + 1  # +1 for the joining space
        gap = (w["t0"] - words[i - 1]["t1"]) if i > 0 else 0.0
        if cur and (cur_len + wl > max_chars or gap > PAUSE_SPLIT_S):
            cards.append(cur)
            cur, cur_len = [], 0
        cur.append(w)
        cur_len += wl
    if cur:
        cards.append(cur)
    return cards


def build_ass(
    words: list[dict],
    kit_caps: dict,
    target: dict,
    out_path: str | Path,
) -> Path:
    """Build a word-pop karaoke ASS file from word timings.

    kit_caps carries the kit's captions block: style, font, size, fill,
    highlight, outline, outline_w, safe_top_pct, safe_bottom_pct,
    max_chars_per_card. target carries w/h. The ASS karaoke \\k sweep runs
    from SecondaryColour (fill, the unsung color) to PrimaryColour
    (highlight, the sung color).
    """
    import pysubs2

    w, h = int(target["w"]), int(target["h"])
    max_chars = int(kit_caps.get("max_chars_per_card", 24))
    margin_v = int(h * float(kit_caps.get("safe_bottom_pct", 20)) / 100.0 + 40)

    fill = _hex_to_rgb(kit_caps.get("fill", "#FFFFFF"))
    highlight = _hex_to_rgb(kit_caps.get("highlight", "#39FF88"))
    outline_c = _hex_to_rgb(kit_caps.get("outline", "#000000"))

    subs = pysubs2.SSAFile()
    subs.info["PlayResX"] = w
    subs.info["PlayResY"] = h
    subs.info["WrapStyle"] = "2"
    subs.info["ScaledBorderAndShadow"] = "yes"

    style = pysubs2.SSAStyle()
    style.fontname = kit_caps.get("font", "DejaVu Sans")
    style.fontsize = float(kit_caps.get("size", 72))
    style.primarycolor = pysubs2.Color(*highlight, 0)     # sung word
    style.secondarycolor = pysubs2.Color(*fill, 0)        # unsung words
    style.outlinecolor = pysubs2.Color(*outline_c, 0)
    style.backcolor = pysubs2.Color(0, 0, 0, 160)         # shadow, translucent
    style.bold = True
    style.borderstyle = 1
    style.outline = float(kit_caps.get("outline_w", 3))
    style.shadow = 1
    style.alignment = pysubs2.Alignment.BOTTOM_CENTER
    style.marginl = 60
    style.marginr = 60
    style.marginv = margin_v
    subs.styles["WordPop"] = style

    for card in group_into_cards(words, max_chars):
        ev = pysubs2.SSAEvent()
        ev.start = int(round(card[0]["t0"] * 1000))
        ev.end = int(round((card[-1]["t1"] + HOLD_S) * 1000))
        ev.style = "WordPop"
        parts = []
        for wd in card:
            cs = max(1, int(round((wd["t1"] - wd["t0"]) * 100)))
            text = wd["w"].replace("{", "\\{").replace("}", "\\}")
            parts.append(f"{{\\k{cs}}}{text}")
        ev.text = " ".join(parts)
        subs.events.append(ev)

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    subs.save(str(out))
    return out
