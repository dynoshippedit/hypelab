"""Regression tests for bugs found during the live vertical-slice run.

Each test pins a defect that was fixed live on 2026-09-28:
- EDL upsert placeholder mismatch (4 placeholders, 3 bindings)
- render->gates chaining gap (re-render left job in 'gates' with no gates task)
- reset_attempts leaving run_after in the future (task never revived)
- doctor() checking the wrong whisper package
- ASR transcription leaking into captions instead of script tokens
"""
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypelab.db import connect, migrate
from hypelab.queue import Queue
from hypelab import tasks_lab
from hypelab.align import _constrain_to_script


_KEEPALIVE = []

def _cx(with_jobs=("job1", "job9")):
    tmp = tempfile.TemporaryDirectory()
    _KEEPALIVE.append(tmp)  # keep the tempdir alive for the test session
    cx = connect(Path(tmp.name) / "t.db")
    migrate(cx)
    for j in with_jobs:
        cx.execute(
            """INSERT INTO jobs(id, mode, state, kit_id, kit_version, title,
                                created_at, updated_at)
               VALUES(?, 'original', 'asset_building', 'k', '1', 't',
                      datetime('now'), datetime('now'))""", (j,))
    cx.commit()
    return cx


class TestEdlUpsert(unittest.TestCase):
    def test_insert_then_bump(self):
        cx = _cx()
        v1 = tasks_lab._upsert_edl(cx, "job1", '{"a":1}', "hash1")
        self.assertEqual(v1, 1)
        row = cx.execute("SELECT version, render_hash FROM edls WHERE job_id='job1'").fetchone()
        self.assertEqual(row["version"], 1)
        self.assertEqual(row["render_hash"], "hash1")
        v2 = tasks_lab._upsert_edl(cx, "job1", '{"a":2}', "hash2")
        self.assertEqual(v2, 2)
        row = cx.execute("SELECT version, render_hash, render_json FROM edls WHERE job_id='job1'").fetchone()
        self.assertEqual(row["version"], 2)
        self.assertEqual(row["render_hash"], "hash2")
        self.assertIn('"a":2', row["render_json"].replace(" ", ""))
        n = cx.execute("SELECT COUNT(*) c FROM edls").fetchone()["c"]
        self.assertEqual(n, 1)  # upsert, never a second row


class TestRequeueGates(unittest.TestCase):
    def _task(self, cx, state="done"):
        tid = "task_requeue1"
        cx.execute(
            """INSERT INTO tasks(id, job_id, kind, state, payload_json, attempts,
                                 max_attempts, idempotency_key, run_after,
                                 created_at, updated_at)
               VALUES(?,?,?,?,?,0,?,?,?,?,?)""",
            (tid, "job1", "run_gates", state, '{"job_id":"job1"}',
             5, "k1", datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat(),
             datetime.now(timezone.utc).isoformat()))
        cx.commit()
        return tid

    def test_resets_done_task_without_duplicating(self):
        cx = _cx()
        tid = self._task(cx, state="done")
        tasks_lab._requeue_gates(cx, "job1")
        rows = cx.execute("SELECT * FROM tasks WHERE kind='run_gates'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], tid)
        self.assertEqual(rows[0]["state"], "queued")
        self.assertEqual(rows[0]["attempts"], 0)
        ra = datetime.fromisoformat(rows[0]["run_after"])
        self.assertLess(ra, datetime.now(timezone.utc))  # runnable now

    def test_creates_when_missing(self):
        cx = _cx()
        tasks_lab._requeue_gates(cx, "job9")
        rows = cx.execute("SELECT * FROM tasks WHERE job_id='job9' AND kind='run_gates'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["state"], "queued")


class TestResetRevives(unittest.TestCase):
    def test_failed_task_with_future_backoff_is_runnable(self):
        tmp = tempfile.TemporaryDirectory()
        q = Queue(path=Path(tmp.name) / "q.db")
        q.cx.execute(
            """INSERT INTO jobs(id, mode, state, kit_id, kit_version, title,
                                created_at, updated_at)
               VALUES('job1','original','asset_building','k','1','t',
                      datetime('now'),datetime('now'))""")
        t = q.enqueue("job1", "render", {"job_id": "job1"}, max_attempts=5)
        q.claim("w1")
        q.fail(t["id"], "boom", retryable=True)
        row = q.get_task(t["id"])
        self.assertEqual(row["state"], "queued")
        ra = datetime.fromisoformat(row["run_after"])
        self.assertGreater(ra, datetime.now(timezone.utc))  # backed off
        q.reset_attempts(t["id"])
        row = q.get_task(t["id"])
        self.assertEqual(row["state"], "queued")
        self.assertEqual(row["attempts"], 0)
        ra = datetime.fromisoformat(row["run_after"])
        self.assertLess(ra, datetime.now(timezone.utc))  # revived: runnable now


class TestScriptConstrain(unittest.TestCase):
    def test_script_spelling_wins_timing_kept(self):
        asr = [{"w": "Hyplab", "t0": 0.0, "t1": 0.5},
               {"w": "is", "t0": 0.5, "t1": 0.7},
               {"w": "a", "t0": 0.7, "t1": 0.8},
               {"w": "test", "t0": 0.8, "t1": 1.1},
               {"w": "of", "t0": 1.1, "t1": 1.2},
               {"w": "the", "t0": 1.2, "t1": 1.4},
               {"w": "render", "t0": 1.4, "t1": 1.8},
               {"w": "pipeline", "t0": 1.8, "t1": 2.3}]
        script = ["HypeLab", "is", "a", "test", "of", "the", "render", "pipeline"]
        out, info = _constrain_to_script(asr, script)
        self.assertTrue(info["script_constrained"])
        self.assertEqual([w["w"] for w in out], script)
        self.assertEqual([(w["t0"], w["t1"]) for w in out],
                         [(w["t0"], w["t1"]) for w in asr])

    def test_low_match_falls_back_honestly(self):
        asr = [{"w": "hello", "t0": 0.0, "t1": 0.5}]
        out, info = _constrain_to_script(asr, ["completely", "different"])
        self.assertFalse(info["script_constrained"])
        self.assertIsNotNone(info["fallback"])
        self.assertEqual(out, asr)

    def test_no_script_falls_back(self):
        asr = [{"w": "hello", "t0": 0.0, "t1": 0.5}]
        out, info = _constrain_to_script(asr, [])
        self.assertFalse(info["script_constrained"])
        self.assertEqual(out, asr)


class TestDoctor(unittest.TestCase):
    def test_doctor_reports_faster_whisper(self):
        from hypelab.services import Services
        tmp = tempfile.TemporaryDirectory()
        os.environ["HYPELAB_HOME"] = tmp.name
        try:
            d = Services().doctor()
        finally:
            del os.environ["HYPELAB_HOME"]
        # regression: doctor() used to check the wrong 'whisper' package
        # (Graphite's round-robin DB, not a speech model)
        self.assertIn("faster_whisper", d)
        self.assertIsInstance(d["faster_whisper"], bool)


if __name__ == "__main__":
    unittest.main()
