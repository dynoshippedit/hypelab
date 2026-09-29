"""Race/atomicity tests for T-007 + C2 (hl-cycle-06).

Root cause: queue state transitions were not atomic under concurrency.
Connections are autocommit, so legality checks ran in Python on a
separately-read row, the UPDATE carried no predicates, and the audit
``log()`` was a separate statement. The fix enforces legality ON the
UPDATE (``AND state=?``, ``AND lease_owner=?``) and commits UPDATE+log
in one explicit transaction; a lost race surfaces as "0 rows updated"
(ValueError / False) instead of a silent overwrite.

Each *_race test forces the interleaving deterministically with a
lock gate: the main thread holds ``BEGIN IMMEDIATE`` (the RESERVED write
lock), starts the victim thread (which blocks inside its transaction),
performs the concurrent steal/move, then COMMITs. On pre-fix code the
victim's unpredicated UPDATE fires after the concurrent change — the
test fails. On fixed code the predicate rejects it — the test passes.
Verified: every *_race test FAILS on pre-fix code (via git stash) and
PASSES on the fixed code.
"""

import sys
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import db as db_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402
from hypelab import kits as kits_mod  # noqa: E402
from hypelab import queue as queue_mod  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    root = tmp_path / "root"
    (root / "work").mkdir(parents=True)
    monkeypatch.setenv("HYPELAB_DB", str(dbp))
    monkeypatch.setenv("HYPELAB_ROOT", str(root))
    conn = db_mod.connect(str(dbp))
    try:
        db_mod.migrate(conn)
        kits_mod.seed(conn, "k", {})
    finally:
        conn.close()
    return {"db": dbp, "root": root}


def _mk_job(dbp, state):
    conn = db_mod.connect(str(dbp))
    try:
        return jobs_mod.new(conn, mode="book1", title="tq", state=state,
                            kit_id="k", kit_version=1)
    finally:
        conn.close()


def _job_row(dbp, job_id):
    conn = db_mod.connect(str(dbp))
    try:
        return conn.execute(
            "SELECT state, lease_owner, lease_expires, error, attempts"
            " FROM jobs WHERE id=?",
            (job_id,),
        ).fetchone()
    finally:
        conn.close()


def _event_count(dbp, job_id):
    conn = db_mod.connect(str(dbp))
    try:
        return conn.execute(
            "SELECT COUNT(*) FROM job_events WHERE job_id=?", (job_id,)
        ).fetchone()[0]
    finally:
        conn.close()


def _future_ts():
    return (datetime.now(timezone.utc)
            + timedelta(hours=1)).isoformat(timespec="seconds")


def _run_gated(dbp, victim_fn, concurrent_sql, concurrent_params=()):
    """Run victim_fn in a thread while the main thread holds the write lock.

    The victim blocks inside its transaction; the main thread then applies
    the concurrent change and releases the lock. Returns the victim's
    result dict.
    """
    result = {}
    gate = threading.Event()

    def victim():
        c = db_mod.connect(str(dbp))
        try:
            gate.set()
            result["value"] = victim_fn(c)
        except Exception as e:  # noqa: BLE001 - recorded for assertions
            result["error"] = e
        finally:
            c.close()

    m = db_mod.connect(str(dbp))
    try:
        m.execute("BEGIN IMMEDIATE")
        t = threading.Thread(target=victim, daemon=False)
        t.start()
        assert gate.wait(timeout=10), "victim thread did not start"
        time.sleep(0.3)  # let the victim block inside its transaction
        m.execute(concurrent_sql, concurrent_params)
        m.execute("COMMIT")
        t.join(timeout=30)
        assert not t.is_alive(), "victim thread hung"
    finally:
        m.close()
    return result


# ------------------------------------------------------------- fail() race


def test_fail_lease_steal_lost_race(env):
    """fail() must not fail a job whose lease was reclaimed mid-call.

    Worker A starts fail(); worker B reclaims the lease (expiry path)
    before A's write commits. Fixed code: A's UPDATE carries
    ``AND lease_owner='A'`` -> 0 rows -> ValueError, job untouched.
    Pre-fix code: the unpredicated UPDATE fires -> B's job is failed
    with A's error.
    """
    dbp = env["db"]
    jid = _mk_job(dbp, "queued_align")
    c0 = db_mod.connect(str(dbp))
    try:
        assert queue_mod.claim(c0, "A", states=["queued_align"]) is not None
    finally:
        c0.close()
    events_before = _event_count(dbp, jid)

    def victim(c):
        return queue_mod.fail(c, jid, "A", RuntimeError("boom-A"))

    result = _run_gated(
        dbp, victim,
        "UPDATE jobs SET lease_owner='B', lease_expires=? WHERE id=?",
        (_future_ts(), jid),
    )
    assert "error" in result, (
        "fail() should have raised ValueError on the lost race"
    )
    assert isinstance(result["error"], ValueError)
    assert "not held by" in str(result["error"])
    # Job untouched: still A's... no — B's now; still active, not failed.
    row = _job_row(dbp, jid)
    assert row[0] == "aligning", row
    assert row[1] == "B", row
    assert row[3] is None, row  # no error recorded
    assert _event_count(dbp, jid) == events_before


def test_fail_contract_single_threaded(env):
    dbp = env["db"]
    jid = _mk_job(dbp, "queued_align")
    c = db_mod.connect(str(dbp))
    try:
        queue_mod.claim(c, "A", states=["queued_align"])
        with pytest.raises(ValueError, match="unknown job"):
            queue_mod.fail(c, "j_nope", "A", "x")
        with pytest.raises(ValueError, match="not held by"):
            queue_mod.fail(c, jid, "B", "x")
        row = _job_row(dbp, jid)
        assert row[0] == "aligning" and row[1] == "A" and row[3] is None
        # The legitimate owner still succeeds, with its audit entry.
        before = _event_count(dbp, jid)
        out = queue_mod.fail(c, jid, "A", "boom")
        assert out["state"] == "failed" and out["error"] == "boom"
        assert _event_count(dbp, jid) == before + 1
    finally:
        c.close()


# ---------------------------------------------------------- release() race


def test_release_lease_renew_lost_race(env):
    """release() must not release a job whose lease changed mid-call.

    Worker A starts release() on its live lease; the lease is renewed /
    taken by B before A's write commits. Fixed code: the UPDATE's lease
    predicates miss -> False, job untouched. Pre-fix: unpredicated
    UPDATE clears B's lease and returns True.
    """
    dbp = env["db"]
    jid = _mk_job(dbp, "queued_align")
    c0 = db_mod.connect(str(dbp))
    try:
        assert queue_mod.claim(c0, "A", states=["queued_align"]) is not None
    finally:
        c0.close()
    events_before = _event_count(dbp, jid)

    def victim(c):
        return queue_mod.release(c, jid, "A")

    result = _run_gated(
        dbp, victim,
        "UPDATE jobs SET lease_owner='B' WHERE id=?",
        (jid,),
    )
    assert result.get("error") is None, result.get("error")
    assert result.get("value") is False, (
        "release() should return False on the lost race"
    )
    row = _job_row(dbp, jid)
    assert row[0] == "aligning", row
    assert row[1] == "B", row
    assert row[2] is not None, row  # lease still live
    assert _event_count(dbp, jid) == events_before


# ------------------------------------------------------- transition() race


def test_transition_lost_race(env):
    """transition() must not apply a move the job has already left.

    Thread T checks aligning->aligned as legal; the job moves to
    gate_failed before T's write commits. Fixed code: ``AND state=?``
    misses -> ValueError, job stays gate_failed. Pre-fix: the
    unpredicated UPDATE applies an illegal aligning->aligned move on top
    of gate_failed.
    """
    dbp = env["db"]
    jid = _mk_job(dbp, "aligning")
    events_before = _event_count(dbp, jid)

    def victim(c):
        return jobs_mod.transition(c, jid, "aligned", note="t")

    result = _run_gated(
        dbp, victim,
        "UPDATE jobs SET state='gate_failed' WHERE id=?",
        (jid,),
    )
    assert "error" in result, (
        "transition() should have raised ValueError on the lost race"
    )
    assert isinstance(result["error"], ValueError)
    assert "lost race" in str(result["error"])
    assert _job_row(dbp, jid)[0] == "gate_failed"
    assert _event_count(dbp, jid) == events_before


def test_transition_contract_single_threaded(env):
    dbp = env["db"]
    c = db_mod.connect(str(dbp))
    try:
        jid = _mk_job(dbp, "aligning")
        with pytest.raises(ValueError, match="illegal transition"):
            jobs_mod.transition(c, jid, "ready")
        with pytest.raises(ValueError, match="unknown job"):
            jobs_mod.transition(c, "j_nope", "aligned")
        assert jobs_mod.transition(c, jid, "aligned") == "aligned"
        assert _job_row(dbp, jid)[0] == "aligned"
    finally:
        c.close()


# ------------------------------------------------------- fail_drive() race


def test_fail_drive_lease_race(env):
    """fail_drive() must not fail a job that gained a lease mid-call.

    The work loop claims the job (live lease) after fail_drive()'s read
    but before its write. Fixed code: the ``lease_owner IS NULL``
    predicate misses -> False, job untouched. Pre-fix: the unpredicated
    UPDATE steals the lease holder's failure path.
    """
    dbp = env["db"]
    jid = _mk_job(dbp, "rendering")
    events_before = _event_count(dbp, jid)

    def victim(c):
        return jobs_mod.fail_drive(c, jid, RuntimeError("drive boom"))

    result = _run_gated(
        dbp, victim,
        "UPDATE jobs SET lease_owner='W', lease_expires=? WHERE id=?",
        (_future_ts(), jid),
    )
    assert result.get("error") is None, result.get("error")
    assert result.get("value") is False, (
        "fail_drive() should return False when a lease appeared mid-call"
    )
    row = _job_row(dbp, jid)
    assert row[0] == "rendering", row
    assert row[1] == "W", row
    assert row[3] is None, row
    assert _event_count(dbp, jid) == events_before


# ------------------------------------------------------------- claim() load


def test_concurrent_claim_no_double_claim(env):
    """N threads racing over M queued jobs: each job claimed exactly once."""
    dbp = env["db"]
    n_jobs, n_threads = 12, 6
    jids = [_mk_job(dbp, "queued_align") for _ in range(n_jobs)]
    claimed = []
    lock = threading.Lock()
    barrier = threading.Barrier(n_threads)

    def worker(i):
        c = db_mod.connect(str(dbp))
        try:
            barrier.wait(timeout=15)
            while True:
                row = queue_mod.claim(c, f"worker-{i}",
                                      states=["queued_align"])
                if row is None:
                    return
                with lock:
                    claimed.append(row["id"])
        finally:
            c.close()

    threads = [threading.Thread(target=worker, args=(i,))
               for i in range(n_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
        assert not t.is_alive(), "claim worker hung"

    assert sorted(claimed) == sorted(jids)
    for jid in jids:
        row = _job_row(dbp, jid)
        assert row[4] == 1, (jid, row)  # attempts == 1: claimed exactly once
        assert _event_count(dbp, jid) >= 1  # audit entry present
