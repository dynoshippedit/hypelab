"""Durable task queue: leases, retries, idempotency, crash recovery.

Claim is a single atomic UPDATE so exactly one worker wins a task.
Crash recovery: tasks whose lease expired return to 'queued' on worker start.
"""
from __future__ import annotations
import hashlib
import json
import sqlite3
import uuid
from datetime import datetime, timedelta, timezone

from . import config
from .db import connect, migrate

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"

class Queue:
    def __init__(self, path=None):
        self.cx = connect(path)
        migrate(self.cx)

    # -- enqueue ---------------------------------------------------------
    def enqueue(self, job_id: str, kind: str, payload: dict,
                max_attempts: int = 3, run_after: str | None = None) -> dict:
        """Idempotent: same (job, kind, payload) -> same task, no duplicates."""
        key = hashlib.sha256(
            json.dumps([job_id, kind, payload], sort_keys=True).encode()
        ).hexdigest()
        now = _now()
        tid = _uid("task")
        cur = self.cx.execute(
            """INSERT INTO tasks(id, job_id, kind, state, payload_json, attempts,
                                 max_attempts, idempotency_key, run_after,
                                 created_at, updated_at)
               VALUES(?,?,?,?,?,0,?,?,?, ?,?)
               ON CONFLICT(idempotency_key) DO NOTHING""",
            (tid, job_id, kind, "queued", json.dumps(payload),
             max_attempts, key, run_after or now, now, now),
        )
        if cur.rowcount == 0:
            row = self.cx.execute(
                "SELECT * FROM tasks WHERE idempotency_key=?", (key,)).fetchone()
            return dict(row)
        return dict(self.cx.execute("SELECT * FROM tasks WHERE id=?", (tid,)).fetchone())

    # -- claim -----------------------------------------------------------
    def claim(self, worker_id: str, lease_s: int = config.LEASE_SECONDS) -> dict | None:
        """Atomically lease one queued, due task. Returns None if none available."""
        now = _now()
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_s)).isoformat()
        cur = self.cx.execute(
            """UPDATE tasks SET state='leased', lease_owner=?, lease_expires=?,
                                  updated_at=?
               WHERE id = (SELECT id FROM tasks
                           WHERE state='queued' AND run_after <= ?
                           ORDER BY created_at LIMIT 1)
               RETURNING *""",
            (worker_id, expires, now, now),
        )
        row = cur.fetchone()
        return dict(row) if row else None

    def heartbeat(self, task_id: str, worker_id: str,
                  lease_s: int = config.LEASE_SECONDS) -> bool:
        expires = (datetime.now(timezone.utc) + timedelta(seconds=lease_s)).isoformat()
        cur = self.cx.execute(
            """UPDATE tasks SET lease_expires=?, updated_at=?
               WHERE id=? AND lease_owner=? AND state='leased'""",
            (expires, _now(), task_id, worker_id),
        )
        return cur.rowcount == 1

    # -- completion ------------------------------------------------------
    def complete(self, task_id: str, result: dict) -> None:
        self.cx.execute(
            """UPDATE tasks SET state='done', result_json=?, lease_owner=NULL,
                                  lease_expires=NULL, updated_at=?
               WHERE id=?""",
            (json.dumps(result), _now(), task_id),
        )

    def fail(self, task_id: str, error: str, retryable: bool = True) -> dict:
        """Returns the updated task row. Requeues with backoff or marks failed."""
        row = self.cx.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        attempts = row["attempts"] + 1
        now = _now()
        if retryable and attempts < row["max_attempts"]:
            backoff_min = 2 ** attempts
            run_after = (datetime.now(timezone.utc)
                         + timedelta(minutes=backoff_min)).isoformat()
            self.cx.execute(
                """UPDATE tasks SET state='queued', attempts=?, lease_owner=NULL,
                                      lease_expires=NULL, run_after=?, result_json=?,
                                      updated_at=? WHERE id=?""",
                (attempts, run_after, json.dumps({"error": error}), now, task_id),
            )
        else:
            self.cx.execute(
                """UPDATE tasks SET state='failed', attempts=?, lease_owner=NULL,
                                      lease_expires=NULL, result_json=?,
                                      updated_at=? WHERE id=?""",
                (attempts, json.dumps({"error": error, "terminal": True}), now, task_id),
            )
        return dict(self.cx.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone())

    def release(self, task_id: str) -> None:
        """Give up a lease without counting an attempt (e.g. job cancelled)."""
        self.cx.execute(
            """UPDATE tasks SET state='queued', lease_owner=NULL, lease_expires=NULL,
                                  updated_at=? WHERE id=?""",
            (_now(), task_id),
        )

    # -- recovery --------------------------------------------------------
    def recover_expired_leases(self) -> int:
        """Crash recovery: leased tasks whose lease expired go back to queued.
        Attempts are NOT incremented — the crash wasn't the task's fault."""
        cur = self.cx.execute(
            """UPDATE tasks SET state='queued', lease_owner=NULL, lease_expires=NULL,
                                  updated_at=?
               WHERE state='leased' AND lease_expires < ?""",
            (_now(), _now()),
        )
        return cur.rowcount

    # -- reads -----------------------------------------------------------
    def get_task(self, task_id: str) -> dict | None:
        row = self.cx.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        return dict(row) if row else None

    def job_tasks(self, job_id: str) -> list[dict]:
        return [dict(r) for r in self.cx.execute(
            "SELECT * FROM tasks WHERE job_id=? ORDER BY created_at", (job_id,))]

    def reset_attempts(self, task_id: str) -> None:
        # run_after is set slightly in the past: a manual reset means "run now",
        # and must not be defeated by clock jitter.
        past = (datetime.now(timezone.utc) - timedelta(seconds=60)).isoformat()
        cur = self.cx.execute(
            "UPDATE tasks SET attempts=0, state='queued', run_after=?, updated_at=? WHERE id=?",
            (past, _now(), task_id),
        )
        if cur.rowcount == 0:
            raise KeyError(f"task {task_id} not found")
