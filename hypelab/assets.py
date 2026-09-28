"""Asset intake: validation, hashing, provenance. Symlinks rejected, job-dir confined."""
from __future__ import annotations
import hashlib
import json
import shutil
import subprocess
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .db import connect, migrate

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".webm"}
AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".ogg"}
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
JSON_EXTS = {".json"}
ALLOWED = VIDEO_EXTS | AUDIO_EXTS | IMAGE_EXTS | JSON_EXTS

MAX_VIDEO_BYTES = 500 * 1024 * 1024
MAX_AUDIO_BYTES = 100 * 1024 * 1024

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def probe(path: Path) -> dict:
    """ffprobe -> {duration_s, width, height, fps}. Raises on failure."""
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-print_format", "json",
         "-show_format", "-show_streams", str(path)],
        capture_output=True, text=True, timeout=60, check=False)
    if out.returncode != 0:
        raise ValueError(f"ffprobe failed for {path.name}: {out.stderr[:200]}")
    info = json.loads(out.stdout)
    d: dict = {"duration_s": None, "width": None, "height": None, "fps": None}
    try:
        d["duration_s"] = float(info["format"]["duration"])
    except (KeyError, TypeError, ValueError):
        pass
    for s in info.get("streams", []):
        if s.get("codec_type") == "video" and d["width"] is None:
            d["width"] = s.get("width")
            d["height"] = s.get("height")
            fps = s.get("avg_frame_rate", "0/1")
            try:
                n, dd = fps.split("/")
                d["fps"] = float(n) / float(dd) if float(dd) else None
            except (ValueError, ZeroDivisionError):
                pass
    return d

class Assets:
    def __init__(self, path=None):
        self.cx = connect(path)
        migrate(self.cx)

    def add(self, job_id: str, slot: str, src: Path | str,
            provenance: str) -> dict:
        """Validate, copy into the job dir, hash, record. Returns the asset row."""
        src = Path(src)
        if src.is_symlink():
            raise ValueError("symlinks are not accepted")
        src = src.resolve()
        if not src.is_file():
            raise ValueError(f"not a file: {src}")
        ext = src.suffix.lower()
        if ext not in ALLOWED:
            raise ValueError(f"extension {ext} not allowed")
        size = src.stat().st_size
        if ext in VIDEO_EXTS and size > MAX_VIDEO_BYTES:
            raise ValueError("video exceeds 500 MB cap")
        if ext in AUDIO_EXTS and size > MAX_AUDIO_BYTES:
            raise ValueError("audio exceeds 100 MB cap")

        kind = ("video" if ext in VIDEO_EXTS else
                "audio" if ext in AUDIO_EXTS else
                "image" if ext in IMAGE_EXTS else "json")
        meta = probe(src) if kind in ("video", "audio") else \
            {"duration_s": None, "width": None, "height": None, "fps": None}

        dest_dir = config.job_dir(job_id) / "assets"
        dest_dir.mkdir(parents=True, exist_ok=True)
        # slot-safe filename: no path traversal
        safe_slot = "".join(c if c.isalnum() or c in "-_:" else "_" for c in slot)
        dest = dest_dir / f"{safe_slot}{ext}"
        shutil.copyfile(src, dest)
        digest = sha256_file(dest)

        aid = "asset_" + uuid.uuid4().hex[:12]
        now = _now()
        self.cx.execute(
            """INSERT INTO assets(id, job_id, slot, path, sha256, bytes, kind,
                                  provenance, duration_s, width, height, fps, created_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (aid, job_id, slot, str(dest), digest, size, kind, provenance,
             meta["duration_s"], meta["width"], meta["height"], meta["fps"], now))
        row = self.cx.execute("SELECT * FROM assets WHERE id=?", (aid,)).fetchone()
        return dict(row)

    def get_slot(self, job_id: str, slot: str) -> dict | None:
        row = self.cx.execute(
            """SELECT * FROM assets WHERE job_id=? AND slot=?
               ORDER BY created_at DESC LIMIT 1""", (job_id, slot)).fetchone()
        return dict(row) if row else None

    def verify(self, asset: dict) -> bool:
        """Re-hash the file; True iff bytes are unchanged since intake."""
        p = Path(asset["path"])
        return p.is_file() and sha256_file(p) == asset["sha256"]

    def list_job(self, job_id: str) -> list[dict]:
        return [dict(r) for r in self.cx.execute(
            "SELECT * FROM assets WHERE job_id=? ORDER BY created_at", (job_id,))]
