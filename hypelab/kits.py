"""Brand Kit store over the kits(id, version, data_json, created_at) table.

Versions are immutable: bump() INSERTs a new row carrying the merged data,
never mutating old rows. Jobs bind kit_id@version at creation; the stored
JSON is the contract.

The kits table is owned by the DB layer (hypelab.db), but _ensure() applies
a defensive CREATE TABLE IF NOT EXISTS with the exact Book 1 shape so this
module also works against a bare sqlite connection (tests).
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

# Default location of the shipped cerebratico kit source (read, never written).
CEREBRATICO_KIT_PATH = Path("/home/dino/hypelab/kits/cerebratico/kit.json")


def _ensure(conn) -> None:
    conn.execute(
        """CREATE TABLE IF NOT EXISTS kits(
             id TEXT NOT NULL,
             version INTEGER NOT NULL,
             data_json TEXT NOT NULL,
             created_at TEXT NOT NULL,
             PRIMARY KEY (id, version))"""
    )


def _deep_merge(base: dict, changes: dict) -> dict:
    """Recursive merge: nested dicts merge key-wise, everything else replaces."""
    out = copy.deepcopy(base)
    for k, v in changes.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def load(conn, kit_id: str, version: int | None = None) -> dict:
    """Return the kit data dict. Latest version when version is None.

    Raises KeyError when the kit (or that version) does not exist.
    """
    _ensure(conn)
    if version is None:
        row = conn.execute(
            "SELECT data_json FROM kits WHERE id=? ORDER BY version DESC LIMIT 1",
            (kit_id,),
        ).fetchone()
        label = "latest"
    else:
        row = conn.execute(
            "SELECT data_json FROM kits WHERE id=? AND version=?",
            (kit_id, version),
        ).fetchone()
        label = f"v{version}"
    if row is None:
        raise KeyError(f"kit {kit_id}@{label} not found")
    return json.loads(row[0])


def seed(conn, kit_id: str, data: dict) -> int:
    """Insert version 1 of a new kit. Raises ValueError if the kit exists."""
    _ensure(conn)
    exists = conn.execute(
        "SELECT 1 FROM kits WHERE id=? LIMIT 1", (kit_id,)
    ).fetchone()
    if exists is not None:
        raise ValueError(f"kit {kit_id} already exists")
    payload = copy.deepcopy(data)
    payload["id"] = kit_id
    payload["version"] = 1
    conn.execute(
        "INSERT INTO kits(id, version, data_json, created_at) VALUES(?,?,?,?)",
        (kit_id, 1, json.dumps(payload), _now()),
    )
    conn.commit()
    return 1


def bump(conn, kit_id: str, **changes) -> int:
    """New immutable version = max+1 with data deep-merged with changes.

    Old rows are never touched. Raises KeyError if the kit does not exist.
    """
    _ensure(conn)
    cur = load(conn, kit_id)  # KeyError when missing
    row = conn.execute(
        "SELECT MAX(version) FROM kits WHERE id=?", (kit_id,)
    ).fetchone()
    new_v = (row[0] or 0) + 1
    merged = _deep_merge(cur, changes)
    merged["id"] = kit_id
    merged["version"] = new_v
    conn.execute(
        "INSERT INTO kits(id, version, data_json, created_at) VALUES(?,?,?,?)",
        (kit_id, new_v, json.dumps(merged), _now()),
    )
    conn.commit()
    return new_v


def _now() -> str:
    # util.now() has the same contract; stdlib here keeps kits import-light
    # (util is imported lazily by callers that need it).
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---------------------------------------------------------------- cerebratico

def _adapt_cerebratico(raw: dict) -> dict:
    """Adapt a shipped kit.json to the Book 1 §5 shape, filling defaults."""
    raw = raw or {}
    guard = raw.get("guardrails") or {}
    gen = raw.get("generator") or {}
    caps = raw.get("captions") or {}
    aud = raw.get("audio") or {}
    return {
        "appearance": raw.get("appearance") or raw.get("appearance_text") or "",
        "reference_image": raw.get("reference_image") or raw.get("ref_image_path"),
        "voice_sample": raw.get("voice_sample") or raw.get("voice_ref_path"),
        "guardrails": {
            "always": list(guard.get("always") or guard.get("do") or []),
            "never": list(guard.get("never") or guard.get("dont") or []),
        },
        "generator": {
            "max_clip_s": float(
                gen.get("max_clip_s", raw.get("max_clip_len_s", 10.0))
            ),
            "words_per_sec": float(gen.get("words_per_sec", 2.6)),
            "min_beat_s": float(gen.get("min_beat_s", 1.2)),
            "prompt_prefix": gen.get("prompt_prefix", ""),
            "prompt_suffix": gen.get("prompt_suffix", ""),
        },
        "asr": dict(raw.get("asr") or {
            "model": "medium", "device": "cpu",
            "compute_type": "int8", "vad_filter": True,
        }),
        "min_word_prob": float(raw.get("min_word_prob", 0.5)),
        "voiceprint_dir": raw.get("voiceprint_dir"),
        "captions": {
            "style": caps.get("style", "word_pop"),
            "font": caps.get("font", "DejaVu Sans"),
            "size": caps.get("size", 72),
            "fill": caps.get("fill", "#FFFFFF"),
            "highlight": caps.get("highlight", "#39FF88"),
            "outline": caps.get("outline", "#000000"),
            "outline_w": caps.get("outline_w", 3),
            "safe_top_pct": caps.get("safe_top_pct", 12),
            "safe_bottom_pct": caps.get("safe_bottom_pct", 20),
            "max_chars_per_card": caps.get("max_chars_per_card", 24),
        },
        "audio": {
            "voiceprint_dir": aud.get("voiceprint_dir"),
            "loudness_lufs": float(aud.get("loudness_lufs", -16.0)),
            "music_duck_db": float(aud.get("music_duck_db", -12.0)),
        },
    }


def seed_cerebratico(conn, kit_path: str | Path | None = None) -> int:
    """Seed the real cerebratico kit from kits/cerebratico/kit.json.

    NOT run automatically — the integrator seeds via CLI. Raises
    FileNotFoundError when the shipped kit.json is absent.
    """
    path = Path(kit_path) if kit_path else CEREBRATICO_KIT_PATH
    if not path.is_file():
        raise FileNotFoundError(
            f"cerebratico kit source not found: {path} "
            "(place the shipped kit.json there, then seed via CLI)"
        )
    raw = json.loads(path.read_text(encoding="utf-8"))
    return seed(conn, "cerebratico", _adapt_cerebratico(raw))
