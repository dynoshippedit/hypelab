"""Tier 3 — external audience evidence (Book 2, section 6).

Two sub-signals, not two tiers: (a) the YouTube most-replayed heatmap,
(b) comment timestamp density. This is the only tier that is measurement
rather than guesswork — and it is OPPORTUNISTIC: it exists only when the
platform exposes it for that video, which a fresh upload never has.

Both extractors return None as a NORMAL outcome. None is not an error:
fresh uploads, embeds, age-gated videos, disabled comments, and platform
format changes all produce it. Callers MUST handle None via the blind path
(Tiers 1-2 only). Never synthesize a heatmap.

LIMITATION (stated, not averaged away): comment mining and the Tier 1
patterns are English-pattern dependent. Timestamps in other languages or
scripts are missed silently, which biases this signal toward
English-language audiences. Non-English sources degrade Tier 1 silently too —
which is why confidence is recorded per moment.
"""
from __future__ import annotations

import math
import re

#: Timestamps like 1:23, 12:34, 1:02:03 in comment text. English-pattern
#: dependent — see module docstring.
TS = re.compile(r"(?<!\d)(?:(\d{1,2}):)?([0-5]?\d):([0-5]\d)(?!\d)")


def extract_heatmap(info):
    """Normalized most-replayed segments, or None when unavailable.

    ``info`` is the yt-dlp JSON dict (or a fixture with the same shape).
    yt-dlp exposes the heatmap where YouTube provides it; it is not a
    guaranteed or documented API input and its shape can change without
    notice — so a missing/empty heatmap is a normal outcome, not a bug.
    """
    if not info:
        return None
    hm = info.get("heatmap")
    if not hm:
        return None
    try:
        vals = [float(h["value"]) for h in hm]
    except (KeyError, TypeError, ValueError):
        return None
    if not vals:
        return None
    lo, hi = min(vals), max(vals)
    rng = (hi - lo) or 1.0
    out = []
    for h in hm:
        try:
            out.append({
                "t0": float(h["start_time"]),
                "t1": float(h["end_time"]),
                "v": (float(h["value"]) - lo) / rng,
            })
        except (KeyError, TypeError, ValueError):
            continue
    return out or None


def comment_timestamps(info, sigma=8.0, grid=1.0):
    """Gaussian-smoothed comment-cited timestamp density, or None.

    Returns None when there are too few hits (< 3) — including the normal
    cases of comments disabled, comments not yet fetched, or no timestamps
    cited. A comment with 400 likes counts more than one with 0, but via
    log1p so a single viral comment cannot dominate. sigma ~= 8s because
    people timestamp approximately — they remember the minute, not the
    second.
    """
    if not info:
        return None
    duration = info.get("duration")
    if not duration or duration <= 0:
        return None
    hits = []
    for c in (info.get("comments") or []):
        if not isinstance(c, dict):
            continue
        txt = c.get("text", "") or ""
        try:
            likes = int(c.get("like_count") or 0)
        except (TypeError, ValueError):
            likes = 0
        for m in TS.finditer(txt):
            h, mnt, s = m.groups()
            t = int(h or 0) * 3600 + int(mnt) * 60 + int(s)
            if 0 < t < duration:
                hits.append((t, 1.0 + math.log1p(max(likes, 0))))
    if len(hits) < 3:
        return None

    n = int(duration / grid) + 1
    dens = [0.0] * n
    span = int(4 * sigma)
    for t, w in hits:
        c = int(t / grid)
        lo = max(0, c - span)
        hi = min(n, c + span)
        for i in range(lo, hi):
            d = i * grid - t
            dens[i] += w * math.exp(-(d * d) / (2 * sigma * sigma))

    peak = max(dens) or 1.0
    return {
        "grid": grid,
        "density": [d / peak for d in dens],
        "n_hits": len(hits),
    }


def have_tier3(signals: dict) -> bool:
    """True when at least one Tier 3 sub-signal is present."""
    return bool(signals.get("heatmap")) or bool(signals.get("comments"))
