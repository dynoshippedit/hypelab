"""Paths, secrets, and runtime configuration. No business logic."""
from __future__ import annotations
import os
from pathlib import Path

def repo_root() -> Path:
    return Path(os.environ.get("HYPELAB_HOME", Path.home() / "hypelab")).resolve()

def db_path() -> Path:
    return repo_root() / "hypelab.db"

def jobs_dir() -> Path:
    d = repo_root() / "jobs"
    d.mkdir(parents=True, exist_ok=True)
    return d

def cache_dir() -> Path:
    d = Path(os.environ.get("HYPELAB_CACHE", Path.home() / ".cache" / "hypelab"))
    d.mkdir(parents=True, exist_ok=True)
    return d

def job_dir(job_id: str) -> Path:
    d = jobs_dir() / job_id
    (d / "assets").mkdir(parents=True, exist_ok=True)
    return d

def load_secret(name: str) -> str | None:
    """Secrets live in ~/.config/hypelab/secrets.env (mode 600), never in the repo."""
    p = Path.home() / ".config" / "hypelab" / "secrets.env"
    if not p.exists():
        return None
    for line in p.read_text().splitlines():
        line = line.strip()
        if line.startswith(name + "="):
            return line.split("=", 1)[1].strip().strip('"').strip("'")
    return None

WORKER_ID = os.environ.get("HYPELAB_WORKER", "worker-1")
LEASE_SECONDS = int(os.environ.get("HYPELAB_LEASE_S", "600"))
FFMPEG_TIMEOUT = int(os.environ.get("HYPELAB_FFMPEG_TIMEOUT", "1800"))
WHISPER_TIMEOUT = int(os.environ.get("HYPELAB_WHISPER_TIMEOUT", "1200"))
SUPERVISION = os.environ.get("HYPELAB_SUPERVISION", "local")  # local | remote
