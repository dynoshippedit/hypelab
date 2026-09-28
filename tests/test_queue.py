"""Queue semantics: idempotency, atomic claim, retry/backoff, lease recovery."""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from hypelab.queue import Queue

class TestQueue(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.q = Queue(path=Path(self.tmp.name) / "q.db")
        self.q.cx.execute(
            """INSERT INTO jobs(id, mode, state, kit_id, kit_version, title,
                                created_at, updated_at)
               VALUES('job1','original','asset_building','k','1','t',
                      datetime('now'),datetime('now'))""")

    def tearDown(self):
        self.tmp.cleanup()

    def test_idempotent_enqueue(self):
        t1 = self.q.enqueue("job1", "render", {"job_id": "job1"})
        t2 = self.q.enqueue("job1", "render", {"job_id": "job1"})
        self.assertEqual(t1["id"], t2["id"])
        n = self.q.cx.execute("SELECT COUNT(*) c FROM tasks").fetchone()["c"]
        self.assertEqual(n, 1)

    def test_claim_is_atomic_single_winner(self):
        self.q.enqueue("job1", "render", {"job_id": "job1"})
        a = self.q.claim("w1")
        b = self.q.claim("w2")
        self.assertIsNotNone(a)
        self.assertIsNone(b)
        self.assertEqual(a["lease_owner"], "w1")

    def test_retry_backoff_then_poison(self):
        t = self.q.enqueue("job1", "render", {"job_id": "job1"}, max_attempts=2)
        self.q.claim("w1")
        r1 = self.q.fail(t["id"], "boom", retryable=True)
        self.assertEqual(r1["state"], "queued")
        self.assertEqual(r1["attempts"], 1)
        # backoff in the future
        ra = datetime.fromisoformat(r1["run_after"])
        self.assertGreater(ra, datetime.now(timezone.utc))
        self.q.claim("w1")
        r2 = self.q.fail(t["id"], "boom", retryable=True)
        self.assertEqual(r2["state"], "failed")
        self.assertEqual(r2["attempts"], 2)

    def test_non_retryable_fails_immediately(self):
        t = self.q.enqueue("job1", "render", {"job_id": "job1"}, max_attempts=3)
        self.q.claim("w1")
        r = self.q.fail(t["id"], "bad edl", retryable=False)
        self.assertEqual(r["state"], "failed")
        self.assertEqual(r["attempts"], 1)

    def test_expired_lease_recovers_without_attempt_penalty(self):
        t = self.q.enqueue("job1", "render", {"job_id": "job1"})
        self.q.claim("w1", lease_s=60)
        # simulate a dead worker: expire the lease manually
        past = (datetime.now(timezone.utc) - timedelta(seconds=5)).isoformat()
        self.q.cx.execute("UPDATE tasks SET lease_expires=? WHERE id=?",
                          (past, t["id"]))
        n = self.q.recover_expired_leases()
        self.assertEqual(n, 1)
        row = self.q.get_task(t["id"])
        self.assertEqual(row["state"], "queued")
        self.assertEqual(row["attempts"], 0)  # crash wasn't the task's fault
        # another worker can now claim it
        self.assertIsNotNone(self.q.claim("w2"))

    def test_complete(self):
        t = self.q.enqueue("job1", "render", {"job_id": "job1"})
        self.q.claim("w1")
        self.q.complete(t["id"], {"ok": True})
        self.assertEqual(self.q.get_task(t["id"])["state"], "done")

if __name__ == "__main__":
    unittest.main(verbosity=2)
