"""Moment scoring (Book 2, section 6).

Three tiers, defined once:
  Tier 1 — transcript / semantic evidence (heuristics over word timings).
           Always available. A guess about what humans find interesting.
  Tier 2 — audio / visual evidence (loudness envelope, pauses). Always
           available. A guess about what *sounds* interesting.
  Tier 3 — external audience evidence (heatmap, comment density). The only
           measurement — and opportunistic. Absent on fresh uploads.

The blind path (Tiers 1-2 only, confidence 0.45) is the path that runs when
it matters most. It is first-class, not a fallback error.

Weights are versioned data (weights_vN.json), never hard-coded constants.
Raw features stay in signals_json; re-weighting never rewrites history —
every scored moment records weight_version, and a re-score writes a new row.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import subprocess
from pathlib import Path

from . import signals as signals_mod
from .util import new_id, now

#: Confidence when Tier 3 audience evidence is present vs the blind path.
CONF_FULL = 0.9
CONF_BLIND = 0.45

#: Non-maximum suppression: drop windows overlapping a higher-scoring one.
NMS_MIN_GAP_S = 30.0

#: Scoring windows.
WIN_S = 45.0
HOP_S = 5.0


class ScoreError(Exception):
    """Scoring failed (bad inputs, unreadable signals)."""


# ------------------------------------------------------------------ Tier 1

PATTERNS = {
    "reversal": (re.compile(
        r"\b(everyone (thinks|says)|most people|actually|but here's|"
        r"turns out|the truth is)\b", re.I), 1.0),
    "number": (re.compile(
        r"\b\d[\d,.]*\s*(percent|%|million|billion|thousand|x|times)\b",
        re.I), 0.7),
    "question": (re.compile(r"\?"), 0.4),
    "superlative": (re.compile(
        r"\b(never|always|worst|best|only|first|nobody|everybody)\b",
        re.I), 0.5),
    "story_open": (re.compile(
        r"\b(so i|one time|back when|i remember|this guy)\b", re.I), 0.8),
    "stakes": (re.compile(
        r"\b(lost|died|quit|fired|broke|sued|arrested|bankrupt)\b", re.I), 0.9),
}

#: A clip that opens on an unresolved pronoun has no premise and does not
#: land, however good the line is.
_DANGLING_OPEN = {
    "it", "that", "this", "he", "she", "they", "them", "his", "her",
    "its", "their", "there", "and", "but",
}


def is_self_contained(window_text: str) -> bool:
    """True when the window does not open on a dangling pronoun."""
    toks = re.findall(r"[A-Za-z']+", (window_text or "").strip().lower())
    if not toks:
        return False
    return toks[0] not in _DANGLING_OPEN


def transcript_score(window_text: str) -> tuple[float, list[str]]:
    """Tier 1 score in [0,1] plus the pattern names that hit."""
    s, hits = 0.0, []
    for name, (rx, w) in PATTERNS.items():
        if rx.search(window_text or ""):
            s += w
            hits.append(name)
    if is_self_contained(window_text):
        s += 0.8
        hits.append("self_contained")
    return min(s / 3.0, 1.0), hits


def text_between(words: list[dict], t0: float, t1: float) -> str:
    return " ".join(
        w["w"] for w in words if w["t1"] > t0 and w["t0"] < t1
    )


# ------------------------------------------------------------------ Tier 2

def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    for a in cmd:
        if not isinstance(a, str) or not a:
            raise ScoreError(f"invalid argv element for {what}: {a!r}")
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=1800, shell=False
        )
    except FileNotFoundError as e:
        raise ScoreError(f"binary not found for {what}: {e}")
    if proc.returncode != 0:
        raise ScoreError(f"{what} failed: {proc.stderr.strip()[-500:]}")
    return proc


def audio_signals(source_mp4, grid: float = 1.0) -> dict:
    """Tier 2 audio features: RMS loudness envelope + silence spans.

    Laughter detection is NOT implemented — the returned dict says so
    honestly ("laughter": None, noted). Tier 2 here is rms + pauses only.
    A pause right before a line is a setup beat; it is cheap and real.

    Fail-soft: if ffmpeg probing fails, returns empty features with a note
    (scoring is not a money gate; a missing Tier 2 must not kill Tier 1).
    """
    try:
        return _audio_signals(source_mp4, grid=grid)
    except ScoreError as e:
        return {"rms": [], "pauses": [], "laughter": None,
                "note": f"tier2 unavailable: {e}"}


def _audio_signals(source_mp4, grid: float = 1.0) -> dict:
    proc = _run([
        "ffmpeg", "-v", "error", "-i", str(source_mp4),
        "-af", "silencedetect=noise=-35dB:d=0.35",
        "-f", "null", "-",
    ], "silencedetect")
    pauses = _parse_silences(proc.stderr)

    proc = _run([
        "ffmpeg", "-v", "info", "-i", str(source_mp4),
        "-af", "astats=metadata=1:reset=16000",
        "-f", "null", "-",
    ], "astats")
    rms_db = _parse_astats_rms(proc.stderr)
    rms = [10.0 ** (db / 20.0) if db > -90 else 0.0 for db in rms_db]
    lo, hi = (min(rms), max(rms)) if rms else (0.0, 1.0)
    rng = (hi - lo) or 1.0
    rms_n = [(v - lo) / rng for v in rms]

    return {
        "rms": rms_n,
        "pauses": pauses,
        "laughter": None,
        "note": "laughter detector not implemented (stub); Tier 2 = rms + pauses",
    }


def _parse_silences(stderr: str) -> list[tuple[float, float]]:
    starts = []
    spans = []
    for line in stderr.splitlines():
        m = re.search(r"silence_start:\s*([0-9.]+)", line)
        if m:
            starts.append(float(m.group(1)))
            continue
        m = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m and starts:
            spans.append((starts.pop(), float(m.group(1))))
    # A trailing silence_start with no end: close at the last known point.
    return [(s, e) for s, e in spans if e > s]


def _parse_astats_rms(stderr: str) -> list[float]:
    """One RMS dB value per astats reset window (16k samples = 1s)."""
    vals = []
    in_channel = False
    for line in stderr.splitlines():
        if "Channel:" in line:
            in_channel = True
            continue
        if in_channel:
            m = re.search(r"RMS level dB:\s*(-?inf|[-\d.]+)", line)
            if m:
                v = m.group(1)
                vals.append(float(v) if v != "-inf" else -120.0)
                in_channel = False
    return vals


def audio_score_over(audio_sig: dict, t0: float, t1: float,
                     grid: float = 1.0) -> float:
    """Tier 2 part score for a window: loudness energy (0.6) + pause beats
    (0.4). A documented heuristic, not a measurement."""
    rms = audio_sig.get("rms") or []
    if rms:
        lo = max(0, int(t0 / grid))
        hi = min(len(rms), int(t1 / grid) + 1)
        seg = rms[lo:hi]
        energy = sum(seg) / len(seg) if seg else 0.0
    else:
        energy = 0.0
    n_pauses = sum(
        1 for ps, pe in (audio_sig.get("pauses") or [])
        if pe > t0 and ps < t1
    )
    pause_part = min(1.0, n_pauses / 2.0)
    return 0.6 * energy + 0.4 * pause_part


# ------------------------------------------------------------------ weights

def _weights_files(weights_dir: Path) -> list[Path]:
    return sorted(weights_dir.glob("weights_v*.json"))


def load_weights(weights_dir=None, version: str | None = None) -> dict:
    """Load a versioned weight set.

    Default: the latest CALIBRATED set; when none is calibrated, the latest
    uncalibrated set. The version used is written to moments.weight_version.
    """
    d = Path(weights_dir) if weights_dir else Path.cwd()
    files = _weights_files(d)
    if not files:
        raise ScoreError(f"no weights_v*.json in {d}")
    docs = []
    for f in files:
        try:
            docs.append((f, json.loads(f.read_text(encoding="utf-8"))))
        except ValueError:
            continue
    if not docs:
        raise ScoreError(f"no readable weights_v*.json in {d}")
    if version:
        for f, doc in docs:
            if doc.get("version") == version:
                return doc
        raise ScoreError(f"weights version {version!r} not found in {d}")
    cals = [(f, doc) for f, doc in docs
            if doc.get("status") == "calibrated"]
    pool = cals or docs
    pool.sort(key=lambda fd: str(fd[1].get("version", "")))
    return pool[-1][1]


# ------------------------------------------------------------------ combine

def mean_over_heatmap(heatmap, t0: float, t1: float) -> float:
    if not heatmap:
        return 0.0
    num = den = 0.0
    for h in heatmap:
        ov = max(0.0, min(h["t1"], t1) - max(h["t0"], t0))
        if ov > 0:
            num += ov * h["v"]
            den += ov
    return num / den if den > 0 else 0.0


def mean_over_comments(comments, t0: float, t1: float) -> float:
    if not comments:
        return 0.0
    grid = comments.get("grid", 1.0) or 1.0
    dens = comments.get("density") or []
    if not dens:
        return 0.0
    lo = max(0, int(t0 / grid))
    hi = min(len(dens), int(t1 / grid) + 1)
    seg = dens[lo:hi]
    return sum(seg) / len(seg) if seg else 0.0


def score_windows(signals: dict, words: list[dict], weights: dict,
                  audio_sig: dict | None = None,
                  win_s: float = WIN_S, hop_s: float = HOP_S) -> list[dict]:
    """Score sliding windows; combine tiers with versioned weights.

    Returns moment dicts (NOT yet NMS'd or persisted). The blind path
    (no Tier 3) uses the blind weight set and confidence 0.45.
    """
    duration = float(signals.get("duration") or 0.0)
    if duration <= 0:
        raise ScoreError("cannot score: no duration in signals")
    have_t3 = signals_mod.have_tier3(signals)
    W = weights["sets"]["full" if have_t3 else "blind"]

    t = 0.0
    out = []
    while t < duration:
        t1 = min(t + win_s, duration)
        if t1 - t < 5.0 and out:
            break  # ignore a tiny tail window
        txt = text_between(words, t, t1)
        ts, hits = transcript_score(txt)
        parts = {
            "heatmap": mean_over_heatmap(signals.get("heatmap"), t, t1)
            if signals.get("heatmap") else 0.0,
            "comments": mean_over_comments(signals.get("comments"), t, t1)
            if signals.get("comments") else 0.0,
            "transcript": ts,
            "audio": audio_score_over(audio_sig or {}, t, t1)
            if audio_sig is not None else 0.0,
        }
        score = sum(W[k] * v for k, v in parts.items())
        out.append({
            "t_in": round(t, 3), "t_out": round(t1, 3),
            "score": round(score, 4),
            "confidence": CONF_FULL if have_t3 else CONF_BLIND,
            "weight_version": weights["version"],
            "signals": {
                "parts": {k: round(v, 4) for k, v in parts.items()},
                "weights": dict(W),
                "hits": hits,
                "raw": {
                    "heatmap_n": len(signals.get("heatmap") or []),
                    "comment_hits":
                        (signals.get("comments") or {}).get("n_hits", 0),
                    "pause_spans": (audio_sig or {}).get("pauses") or [],
                    "tier3": "full" if have_t3 else "blind",
                },
            },
            "transcript": txt,
        })
        t += hop_s
    return nms(sorted(out, key=lambda m: -m["score"]),
               min_gap_s=NMS_MIN_GAP_S)


def nms(windows: list[dict], min_gap_s: float = NMS_MIN_GAP_S) -> list[dict]:
    """Non-maximum suppression: after sorting by score desc, drop any window
    overlapping a higher-scoring one. Otherwise the top 10 are ten shifted
    copies of one moment."""
    kept = []
    for w in windows:
        if any(not (w["t_out"] <= k["t_in"] or w["t_in"] >= k["t_out"])
               for k in kept):
            continue
        kept.append(w)
    return kept


# ------------------------------------------------------------------ persist

def content_hash(source_sha: str, t_in: float, t_out: float) -> str:
    """Duplicate-detection hash: sha256 of (source content_sha256, t_in, t_out).

    The same moment mined from two videos, or the same video re-mined, hashes
    identically and is caught, not re-scored."""
    return hashlib.sha256(
        f"{source_sha}|{t_in:.3f}|{t_out:.3f}".encode("utf-8")
    ).hexdigest()


def score_moments(conn: sqlite3.Connection, job_id: str, work,
                  weights=None, weights_dir=None,
                  win_s: float = WIN_S, hop_s: float = HOP_S) -> list[dict]:
    """Score a job's ingested source and persist new moments.

    Reads work/source.words.json + work/signals.json, computes Tier 2 audio
    from work/source.mp4, combines with versioned weights, NMS, then inserts
    one moments row per surviving window — skipping windows whose
    content_hash is already in moment_dedup (caught, not re-scored).

    Returns the newly inserted moment dicts (with ids).
    """
    work = Path(work)
    try:
        words_doc = json.loads((work / "source.words.json").read_text(
            encoding="utf-8"))
        signals = json.loads((work / "signals.json").read_text(
            encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ScoreError(f"score needs ingest outputs: {e}")
    words = words_doc.get("words") or []
    if not words:
        raise ScoreError("no words to score")

    wdoc = weights or load_weights(weights_dir)
    audio_sig = audio_signals(work / "source.mp4")
    moments = score_windows(signals, words, wdoc, audio_sig,
                            win_s=win_s, hop_s=hop_s)

    item = conn.execute(
        "SELECT content_sha256 FROM source_items WHERE job_id=? LIMIT 1",
        (job_id,),
    ).fetchone()
    source_sha = (item["content_sha256"] if item else None) or "no-sha"

    new = []
    skipped = 0
    for m in moments:
        ch = content_hash(source_sha, m["t_in"], m["t_out"])
        if conn.execute(
            "SELECT 1 FROM moment_dedup WHERE content_hash=?", (ch,)
        ).fetchone():
            skipped += 1
            continue
        mid = new_id("m")
        conn.execute(
            "INSERT INTO moments(id, job_id, t_in, t_out, score, confidence,"
            " weight_version, signals_json, transcript, picked)"
            " VALUES(?,?,?,?,?,?,?,?,?,0)",
            (mid, job_id, m["t_in"], m["t_out"], m["score"],
             m["confidence"], m["weight_version"],
             json.dumps(m["signals"]), m["transcript"]),
        )
        conn.execute(
            "INSERT INTO moment_dedup(content_hash, moment_id, seen_at)"
            " VALUES(?,?,?)",
            (ch, mid, now()),
        )
        m["id"] = mid
        new.append(m)
    if skipped:
        print(f"  dedup: {skipped} window(s) already mined, skipped")
    return new
