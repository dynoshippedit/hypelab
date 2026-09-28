"""Brand Kit store: immutable versions. Jobs bind kit_id@version at creation."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone

from .db import connect, migrate

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

DEFAULT_KIT = {
    "appearance_text": "",
    "ref_image_path": None,
    "voice_ref_path": None,
    "writing_samples": [],
    "typography": {"font": "DejaVu Sans", "fallback": "sans-serif"},
    "colors": {"primary": "#FFFFFF", "accent": "#FFD60A",
               "caption_bg": "#000000", "caption_bg_alpha": 160},
    "caption_style": {"style": "word_pop", "size": 74,
                      "safe_top_pct": 14, "safe_bottom_pct": 22,
                      "max_chars_per_card": 22},
    "guardrails": {"do": [], "dont": []},
    "max_clip_len_s": 10.0,
}

class Kits:
    def __init__(self, path=None):
        self.cx = connect(path)
        migrate(self.cx)

    def new(self, name: str, owner: str = "brand", **overrides) -> tuple[str, int]:
        kit_id = "kit_" + uuid.uuid4().hex[:8]
        now = _now()
        self.cx.execute(
            "INSERT INTO kits(id, name, owner, created_at) VALUES(?,?,?,?)",
            (kit_id, name, owner, now))
        v = self._insert_version(kit_id, 1, overrides, now)
        return kit_id, v

    def _insert_version(self, kit_id: str, version: int, overrides: dict, now: str) -> int:
        base = json.loads(json.dumps(DEFAULT_KIT))  # deep copy
        for k, val in overrides.items():
            if k in base:
                base[k] = val
        self.cx.execute(
            """INSERT INTO kit_versions(kit_id, version, appearance_text, ref_image_path,
               voice_ref_path, writing_samples_json, typography_json, colors_json,
               caption_style_json, guardrails_json, max_clip_len_s, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (kit_id, version, base["appearance_text"], base["ref_image_path"],
             base["voice_ref_path"], json.dumps(base["writing_samples"]),
             json.dumps(base["typography"]), json.dumps(base["colors"]),
             json.dumps(base["caption_style"]), json.dumps(base["guardrails"]),
             float(base["max_clip_len_s"]), now))
        return version

    def bump(self, kit_id: str, **changes) -> int:
        """New immutable version carrying forward current fields + changes."""
        cur = self.get(kit_id)
        merged = {
            "appearance_text": cur["appearance_text"],
            "ref_image_path": cur["ref_image_path"],
            "voice_ref_path": cur["voice_ref_path"],
            "writing_samples": cur["writing_samples"],
            "typography": cur["typography"],
            "colors": cur["colors"],
            "caption_style": cur["caption_style"],
            "guardrails": cur["guardrails"],
            "max_clip_len_s": cur["max_clip_len_s"],
        }
        merged.update(changes)
        row = self.cx.execute(
            "SELECT MAX(version) AS v FROM kit_versions WHERE kit_id=?", (kit_id,)).fetchone()
        return self._insert_version(kit_id, (row["v"] or 0) + 1, merged, _now())

    def get(self, kit_id: str, version: int | None = None) -> dict:
        if version is None:
            row = self.cx.execute(
                """SELECT * FROM kit_versions WHERE kit_id=?
                   ORDER BY version DESC LIMIT 1""", (kit_id,)).fetchone()
        else:
            row = self.cx.execute(
                "SELECT * FROM kit_versions WHERE kit_id=? AND version=?",
                (kit_id, version)).fetchone()
        if not row:
            raise KeyError(f"kit {kit_id}@v{version} not found")
        d = dict(row)
        return {
            "kit_id": d["kit_id"], "version": d["version"],
            "appearance_text": d["appearance_text"],
            "ref_image_path": d["ref_image_path"],
            "voice_ref_path": d["voice_ref_path"],
            "writing_samples": json.loads(d["writing_samples_json"]),
            "typography": json.loads(d["typography_json"]),
            "colors": json.loads(d["colors_json"]),
            "caption_style": json.loads(d["caption_style_json"]),
            "guardrails": json.loads(d["guardrails_json"]),
            "max_clip_len_s": d["max_clip_len_s"],
        }

    def list(self) -> list[dict]:
        return [dict(r) for r in self.cx.execute(
            """SELECT k.id, k.name, k.owner, MAX(v.version) AS version
               FROM kits k JOIN kit_versions v ON v.kit_id = k.id
               GROUP BY k.id ORDER BY k.created_at""")]
