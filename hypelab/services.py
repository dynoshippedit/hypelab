"""Application services: the API every client (CLI, remote) calls.

All validation and queue writes live here. The CLI is a thin wrapper.
"""
from __future__ import annotations
import json
import shutil
import tarfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .db import connect, migrate
from .queue import Queue
from .kits import Kits
from .assets import Assets
from . import plan as plan_mod

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

class Services:
    def __init__(self, path=None):
        self.cx = connect(path); migrate(self.cx)
        self.q = Queue(path)
        self.kits = Kits(path)
        self.assets = Assets(path)

    # -- jobs ----------------------------------------------------------
    def new_job(self, kit_id: str, script_file: str, title: str,
                mode: str = "original", kit_version: int | None = None) -> dict:
        kit = self.kits.get(kit_id, kit_version)
        script = Path(script_file).read_text()
        if not script.strip():
            raise ValueError("script is empty")
        jid = _uid("job")
        now = _now()
        self.cx.execute(
            """INSERT INTO jobs(id, mode, state, kit_id, kit_version, title,
                                created_at, updated_at)
               VALUES(?, ?, 'asset_building', ?, ?, ?, ?, ?)""",
            (jid, mode, kit["kit_id"], kit["version"], title, now, now))
        d = config.job_dir(jid)
        (d / "script.txt").write_text(script)
        return self.get_job(jid)

    def get_job(self, job_id: str) -> dict:
        row = self.cx.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise ValueError(f"job {job_id} not found")
        d = dict(row)
        d["tasks"] = self.q.job_tasks(job_id)
        d["assets"] = self.assets.list_job(job_id)
        return d

    def list_jobs(self) -> list[dict]:
        return [dict(r) for r in self.cx.execute(
            "SELECT id, mode, state, title, updated_at FROM jobs ORDER BY created_at DESC")]

    def set_state(self, job_id: str, state: str):
        self.cx.execute("UPDATE jobs SET state=?, updated_at=? WHERE id=?",
                        (state, _now(), job_id))

    # -- media ---------------------------------------------------------
    def attach(self, job_id: str, slot: str, file: str, provenance: str) -> dict:
        job = self.get_job(job_id)
        rec = self.assets.add(job_id, slot, file, provenance)
        # any new media while planning -> back to asset_building is handled by tasks
        return rec

    def shots(self, job_id: str) -> list[str]:
        """Numbered paste-ready prompts. Needs words if available, else script-only."""
        job = self.get_job(job_id)
        kit = self.kits.get(job["kit_id"], job["kit_version"])
        script = (config.job_dir(job_id) / "script.txt").read_text()
        sentences = plan_mod.split_sentences(script)
        wrec = self.assets.get_slot(job_id, "vo.words")
        if wrec:
            words = json.loads(Path(wrec["path"]).read_text())["words"]
            beats = plan_mod.group_into_beats(sentences, words, kit["max_clip_len_s"])
        else:
            beats = [{"id": f"b{i+1}", "role": "hook" if i == 0 else "body",
                      "t_in": 0.0, "t_out": kit["max_clip_len_s"],
                      "line": s} for i, s in enumerate(sentences)]
        return plan_mod.shot_prompts(beats, kit)

    # -- pipeline ------------------------------------------------------
    def _enqueue(self, job_id: str, kind: str, payload: dict,
                 max_attempts: int = 3) -> dict:
        """Enqueue. An explicit operator re-request means 'run it now': a task
        of the same kind that is failed or waiting in backoff is revived.
        (A leased task — a worker is on it — is left alone.)"""
        t = self.q.enqueue(job_id, kind, payload, max_attempts=max_attempts)
        if t["state"] in ("failed", "queued"):
            self.q.reset_attempts(t["id"])
            t = self.q.get_task(t["id"])
        return t

    def align(self, job_id: str, whisper_model: str = "tiny") -> dict:
        return self._enqueue(job_id, "align_vo",
                             {"job_id": job_id, "whisper_model": whisper_model})

    def plan(self, job_id: str, aspect: str = "9:16") -> dict:
        return self._enqueue(job_id, "build_edl",
                             {"job_id": job_id, "aspect": aspect})

    def render(self, job_id: str, aspects: list[str] | None = None) -> dict:
        return self._enqueue(job_id, "render",
                             {"job_id": job_id,
                              "aspects": aspects or ["9:16"]})

    def gates(self, job_id: str) -> dict:
        return self._enqueue(job_id, "run_gates", {"job_id": job_id})

    # -- hype ----------------------------------------------------------
    def pitch(self, job_id: str, handle: str, platform: str = "instagram") -> dict:
        from .consent import Consents
        cx = self.cx
        cx.execute(
            """INSERT INTO targets(handle, platform, consent_state)
               VALUES(?,?, 'pitched')
               ON CONFLICT(handle, platform) DO UPDATE SET consent_state='pitched'""",
            (handle, platform))
        self.set_state(job_id, "pitch_sent")
        return {"job_id": job_id, "target": handle, "state": "pitch_sent",
                "note": "pitch draft recorded. Consent must be recorded before publish."}

    def consent_grant(self, job_id: str, handle: str, platform: str, scope: str,
                      evidence: str, expiry: str) -> dict:
        from .consent import Consents
        job = self.get_job(job_id)
        edl_row = self.cx.execute("SELECT render_hash FROM edls WHERE job_id=?",
                                  (job_id,)).fetchone()
        rec = Consents().record(job_id, handle, platform, scope,
                                edl_row["render_hash"] if edl_row else "none",
                                evidence, expiry)
        self.set_state(job_id, "consent_granted")
        return rec

    def publish(self, job_id: str, handle: str, platform: str = "instagram",
                collaborators: list[str] | None = None,
                dry_run: bool = True, i_confirm: bool = False) -> dict:
        from . import publish as pub
        result = pub.publish_job(job_id, handle, platform, collaborators,
                                 dry_run=dry_run, i_confirm=i_confirm)
        return {"ok": result.ok, "dry_run": result.dry_run,
                "detail": result.detail, "media_id": result.media_id}

    # -- ops -----------------------------------------------------------
    def cancel(self, job_id: str):
        self.set_state(job_id, "cancelled")

    def retry_task(self, task_id: str):
        self.q.reset_attempts(task_id)

    def costs(self, job_id: str | None = None) -> dict:
        q = "SELECT provider, SUM(units) AS units, SUM(usd) AS usd FROM cost_ledger"
        args: tuple = ()
        if job_id:
            q += " WHERE job_id=?"; args = (job_id,)
        q += " GROUP BY provider"
        rows = [dict(r) for r in self.cx.execute(q, args)]
        total = sum(r["usd"] or 0 for r in rows)
        return {"by_provider": rows, "total_usd": round(total, 4)}

    def log_cost(self, job_id: str, task_id: str | None, provider: str,
                 units: float, usd: float, note: str = ""):
        self.cx.execute(
            """INSERT INTO cost_ledger(id, job_id, task_id, provider, units, usd,
                                      note, created_at)
               VALUES(?,?,?,?,?,?,?,?)""",
            (_uid("cost"), job_id, task_id, provider, units, usd, note, _now()))
        self.cx.execute("UPDATE jobs SET cost_usd = cost_usd + ? WHERE id=?",
                        (usd, job_id))

    def backup(self) -> Path:
        ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = config.repo_root() / f"hypelab-backup-{ts}.tar.gz"
        with tarfile.open(dest, "w:gz") as tf:
            tf.add(config.db_path(), arcname="hypelab.db")
            tf.add(config.jobs_dir(), arcname="jobs")
        return dest

    def doctor(self) -> dict:
        import shutil as sh
        return {
            "db": str(config.db_path()),
            "db_exists": config.db_path().exists(),
            "ffmpeg": sh.which("ffmpeg"),
            "ffprobe": sh.which("ffprobe"),
            "whisper": _has("whisper"),
            "edge_tts": sh.which("edge-tts"),
            "chromium": sh.which("chromium") or sh.which("google-chrome"),
            "supervision": config.SUPERVISION,
            "secrets_file": (Path.home() / ".config" / "hypelab" / "secrets.env").exists(),
        }

def _has(mod: str) -> bool:
    try:
        __import__(mod)
        return True
    except ImportError:
        return False
