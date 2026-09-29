"""Shared helpers: time, ids, hashing, media probing, atomic file IO.

Book 1 foundation. Other modules code against these exact signatures —
do not change them without updating every caller.
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path


class MediaError(Exception):
    """Raised when a media file is missing, unprobable, or has no video stream."""


class IntegrityError(Exception):
    """Raised when an asset changed mid-intake (source or destination corrupt)."""


def now() -> str:
    """UTC ISO-8601 timestamp, seconds precision, e.g. 2026-09-28T17:45:00+00:00."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def new_id(prefix: str = "j") -> str:
    """`<prefix>_` + 12 hex chars, e.g. j_9f2c... (cryptographic randomness)."""
    return f"{prefix}_{secrets.token_hex(6)}"


def sha256_file(path) -> str:
    """Hex SHA-256 of a file, streamed in 1 MiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _fps(value) -> float | None:
    """Parse an ffprobe avg_frame_rate string like '30000/1001'."""
    if value in (None, "", "0/0"):
        return None
    try:
        num, _, den = str(value).partition("/")
        den_f = float(den) if den else 1.0
        if den_f == 0:
            return None
        return float(num) / den_f
    except (ValueError, ZeroDivisionError):
        return None


def ffprobe(path) -> dict:
    """Probe a media file via ffprobe (validated arg array, never shell=True).

    Returns a dict with keys: duration_s, width, height, fps, pix_fmt, sar,
    has_audio, nb_frames. Fields are None when ffprobe does not report them
    (best effort) — but a result is never fabricated.

    Raises MediaError on: missing file, ffprobe nonzero exit / timeout /
    unparsable output, or no video stream.
    """
    p = Path(path)
    if not p.is_file():
        raise MediaError(f"not a file: {p}")
    cmd = [
        "ffprobe", "-v", "error",
        "-show_entries",
        "stream=index,codec_type,width,height,avg_frame_rate,"
        "pix_fmt,sample_aspect_ratio,nb_frames,duration",
        "-show_entries", "format=duration",
        "-of", "json",
        str(p),
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=60, shell=False
        )
    except FileNotFoundError as e:
        raise MediaError(f"ffprobe binary not found: {e}")
    except subprocess.TimeoutExpired as e:
        raise MediaError(f"ffprobe timed out on {p}: {e}")
    if proc.returncode != 0:
        raise MediaError(f"ffprobe failed on {p}: {proc.stderr.strip()[:300]}")
    try:
        info = json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        raise MediaError(f"ffprobe returned non-JSON for {p}: {e}")
    streams = info.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError(f"no video stream in {p}")
    dur = video.get("duration") or (info.get("format") or {}).get("duration")
    nb = video.get("nb_frames")
    return {
        "duration_s": float(dur) if dur is not None else None,
        "width": int(video["width"]) if video.get("width") is not None else None,
        "height": int(video["height"]) if video.get("height") is not None else None,
        "fps": _fps(video.get("avg_frame_rate")),
        "pix_fmt": video.get("pix_fmt"),
        "sar": video.get("sample_aspect_ratio"),
        "has_audio": any(s.get("codec_type") == "audio" for s in streams),
        "nb_frames": int(nb) if nb is not None else None,
    }


def _stat_sig(p: Path) -> tuple:
    """Identity signature used to detect mid-copy mutation of the source."""
    st = p.stat()
    return (st.st_ino, st.st_size, st.st_mtime_ns)


def intake_asset(src, dst_dir, name) -> dict:
    """Atomically ingest a file into dst_dir under `name`.

    Procedure (closes the asset race):
      1. stat the source (inode/size/mtime signature);
      2. copy to dst_dir/.tmp.<name>.<rand>, flush + fsync;
      3. SHA-256 the temp file (counting bytes as we hash);
      4. re-stat the source — raise IntegrityError if it changed mid-copy;
      5. os.replace() temp -> dst_dir/name (atomic rename);
      6. re-stat the destination — raise IntegrityError if its size does not
         match the byte count from the hash read.

    Returns {"path", "sha256", "bytes"}. The source file is never modified.
    Raises MediaError if src is not a file, IntegrityError on any mid-copy
    change or size mismatch. Temp files are always cleaned up.
    """
    src = Path(src)
    dst_dir = Path(dst_dir)
    if Path(name).name != str(name):
        raise ValueError(f"unsafe asset name: {name!r}")
    if not src.is_file():
        raise MediaError(f"intake source is not a file: {src}")
    dst_dir.mkdir(parents=True, exist_ok=True)
    before = _stat_sig(src)
    tmp = dst_dir / f".tmp.{name}.{secrets.token_hex(8)}"
    try:
        with open(src, "rb") as fin, open(tmp, "wb") as fout:
            shutil.copyfileobj(fin, fout, length=1 << 20)
            fout.flush()
            os.fsync(fout.fileno())
        h = hashlib.sha256()
        n = 0
        with open(tmp, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
                n += len(chunk)
        digest = h.hexdigest()
        if _stat_sig(src) != before:
            raise IntegrityError(f"source changed during intake: {src}")
        dest = dst_dir / name
        os.replace(tmp, dest)
        if dest.stat().st_size != n:
            raise IntegrityError(
                f"destination size mismatch after replace: {dest}"
            )
        return {"path": str(dest), "sha256": digest, "bytes": n}
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


def work_dir(job_id, root="/home/dino/hypelab") -> Path:
    """Per-job working directory: <root>/work/<job_id>. Created on demand.

    Write domains (improved Book 1, section 1) — the old "nothing outside
    work/<job_id>/" rule was false (global DB, model caches, temp files)
    and is replaced by six explicit domains:

    - Job artifacts: work/<job_id>/ — atomic writes only (temp → fsync →
      rename; never a partial file at its final name).
    - State & ledger: hypelab.db — only via queue transitions / charge() /
      gate-result inserts, inside explicit transactions.
    - Model caches: ~/.cache/, HF hub dir — read-mostly, content-
      addressed; never mutated by a job.
    - Temp files: $TMPDIR / work/<job_id>/tmp/ — deleted on job
      completion or crash recovery; never referenced after.
    - Inputs: kits/, user-supplied media — READ ONLY. Jobs never mutate
      inputs; re-rendering an old job must reproduce the old output.
    - Everything else: forbidden. A job that writes outside these domains
      is a bug.
    """
    d = Path(root) / "work" / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def db_to_lin(db: float) -> float:
    """dB (power ratio) -> linear, e.g. -3.0 -> ~0.501."""
    return 10.0 ** (db / 10.0)


def read_json(path):
    """Read and JSON-decode a file."""
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def write_json(path, obj) -> None:
    """Write JSON atomically: tmp file + flush + fsync + os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".tmp.{p.name}.{secrets.token_hex(8)}")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, indent=2))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, p)
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass
