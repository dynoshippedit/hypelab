"""Worker loop: recover leases, claim tasks, dispatch, heartbeat, done/fail.

Run:  python3 -m hypelab.worker [--once] [--worker ID]
A kill -9 mid-task is recovered by starting a new worker (lease expiry).
"""
from __future__ import annotations
import argparse
import json
import threading
import time
import traceback

from . import config
from .queue import Queue
from . import tasks_lab
from .db import connect, migrate

def _job_cancelled(job_id: str) -> bool:
    cx = connect(); migrate(cx)
    row = cx.execute("SELECT state FROM jobs WHERE id=?", (job_id,)).fetchone()
    return bool(row and row["state"] == "cancelled")

def run_once(worker_id: str, q: Queue) -> bool:
    task = q.claim(worker_id)
    if not task:
        return False
    kind, job_id = task["kind"], task["job_id"]
    print(f"[{worker_id}] claimed {task['id']} ({kind}) job={job_id} "
          f"attempt={task['attempts']+1}", flush=True)

    stop = threading.Event()
    def beat():
        while not stop.wait(60):
            q.heartbeat(task["id"], worker_id)
    th = threading.Thread(target=beat, daemon=True)
    th.start()
    try:
        if _job_cancelled(job_id):
            q.release(task["id"])
            print(f"[{worker_id}] job cancelled; released {task['id']}", flush=True)
            return True
        payload = json.loads(task["payload_json"])
        handler = tasks_lab.HANDLERS[kind]
        result = handler(payload)
        q.complete(task["id"], result if isinstance(result, dict) else {"ok": True})
        print(f"[{worker_id}] done {task['id']}", flush=True)
    except Exception as ex:
        retryable = tasks_lab.is_retryable(ex)
        updated = q.fail(task["id"], f"{type(ex).__name__}: {ex}", retryable=retryable)
        print(f"[{worker_id}] {'requeued' if updated['state']=='queued' else 'FAILED'} "
              f"{task['id']}: {ex}", flush=True)
        traceback.print_exc()
    finally:
        stop.set()
    return True

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--worker", default=config.WORKER_ID)
    args = ap.parse_args()

    q = Queue()
    recovered = q.recover_expired_leases()
    if recovered:
        print(f"[{args.worker}] recovered {recovered} expired lease(s)", flush=True)

    if args.once:
        if not run_once(args.worker, q):
            print(f"[{args.worker}] no tasks", flush=True)
        return
    print(f"[{args.worker}] running (Ctrl-C to stop)", flush=True)
    try:
        while True:
            if not run_once(args.worker, q):
                time.sleep(2)
    except KeyboardInterrupt:
        print(f"[{args.worker}] stopped", flush=True)

if __name__ == "__main__":
    main()
