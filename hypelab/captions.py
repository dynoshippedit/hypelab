"""vo.words.json -> ASS subtitles (word-pop karaoke). Pure function of data."""
from __future__ import annotations

def _ass_color(hex_color: str, alpha_0_255: int = 0) -> str:
    """#RRGGBB + alpha -> ASS &HAABBGGRR."""
    h = hex_color.lstrip("#")
    r, g, b = h[0:2], h[2:4], h[4:6]
    return f"&H{alpha_0_255:02X}{b}{g}{r}".upper()

def group_cards(words: list[dict], max_chars: int) -> list[list[dict]]:
    """Group words into caption cards capped at max_chars."""
    cards: list[list[dict]] = []
    cur: list[dict] = []
    cur_len = 0
    for w in words:
        wl = len(w["w"]) + 1
        if cur and cur_len + wl > max_chars:
            cards.append(cur)
            cur, cur_len = [], 0
        cur.append(w)
        cur_len += wl
    if cur:
        cards.append(cur)
    return cards

def _ts(t: float) -> str:
    h = int(t // 3600); m = int((t % 3600) // 60); s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"

def words_to_ass(words: list[dict], kit: dict, w: int, h: int) -> str:
    """Build a full ASS file. Word-pop via \\k karaoke tags.

    Geometry: bottom-center (\\an2), inside the kit's safe box:
    margin_v = safe_bottom_pct of height; play area height = h*(1-safe_top-safe_bottom).
    """
    cap = kit["caption_style"]
    colors = kit["colors"]
    safe_top = h * cap["safe_top_pct"] / 100.0
    safe_bottom = h * cap["safe_bottom_pct"] / 100.0
    margin_v = int(safe_bottom + 40)  # 40px breathing room above the safe edge

    primary = _ass_color(colors.get("primary", "#FFFFFF"))
    highlight = _ass_color(colors.get("accent", "#FFD60A"))
    back = _ass_color(colors.get("caption_bg", "#000000"),
                      255 - colors.get("caption_bg_alpha", 160))
    outline = _ass_color("#000000")

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {w}\n"
        f"PlayResY: {h}\n"
        "WrapStyle: 2\n"
        "ScaledBorderAndShadow: yes\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour,"
        " OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut,"
        " ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow,"
        " Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: WordPop,{cap_font(kit)},{cap['size']},{primary},{highlight},"
        f"{outline},{back},-1,0,0,0,100,100,0,0,1,3,1,2,60,60,{margin_v},1\n"
    )
    events = ["[Events]",
              "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text"]
    for card in group_cards(words, cap["max_chars_per_card"]):
        start = card[0]["t0"]
        end = card[-1]["t1"] + 0.25  # small hold so the last word reads
        parts = []
        for wd in card:
            cs = max(1, int(round((wd["t1"] - wd["t0"]) * 100)))
            text = wd["w"].replace("{", "\\{").replace("}", "\\}")
            parts.append(f"{{\\k{cs}}}{text}")
        events.append(f"Dialogue: 0,{_ts(start)},{_ts(end)},WordPop,,0,0,0,,{' '.join(parts)}")
    return header + "\n".join(events) + "\n"

def cap_font(kit: dict) -> str:
    return kit["typography"].get("font", "DejaVu Sans")

def ass_safe_geometry(kit: dict, w: int, h: int) -> dict:
    """The box captions must stay inside; used by the captions_safe gate."""
    cap = kit["caption_style"]
    return {
        "top": h * cap["safe_top_pct"] / 100.0,
        "bottom": h * (1 - cap["safe_bottom_pct"] / 100.0),
        "font_size": cap["size"],
        "margin_v": int(h * cap["safe_bottom_pct"] / 100.0 + 40),
    }
