"""Cost-label honesty tests (T-043 / owner decision 2026-09-29, hl-cycle-13).

Owner spec:
  - Unmetered rows keep the fixed honest label "unmetered - subscription"
    (never the misleading "ACTUAL|" label on $0.00 rows).
  - Real cost is logged ONLY on paid API calls, from the usage numbers the
    provider's API returns. No estimated cost model, no invented prices.
"""
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import db as db_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402
from hypelab import kits as kits_mod  # noqa: E402
from hypelab import queue as queue_mod  # noqa: E402
from hypelab import retry as retry_mod  # noqa: E402

import pytest  # noqa: E402


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


def _conn(dbp):
    return db_mod.connect(str(dbp))


def _claim_pipeline_job(dbp, queued_state="queued_render", owner="w1"):
    conn = _conn(dbp)
    try:
        jid = jobs_mod.new(conn, mode="book1", title="tq", state=queued_state,
                           kit_id="k", kit_version=1)
        row = queue_mod.claim(conn, owner, states=[queued_state])
        assert row is not None and row["id"] == jid
        return jid
    finally:
        conn.close()


def _cost_rows(dbp, jid):
    conn = _conn(dbp)
    try:
        return conn.execute(
            "SELECT provider, unit, qty, usd, note FROM cost_ledger"
            " WHERE job_id=? ORDER BY id", (jid,)).fetchall()
    finally:
        conn.close()


def test_unmetered_label_is_the_owner_fixed_label():
    # Pins Dino's chosen label verbatim so it can't drift.
    assert queue_mod.COST_UNMETERED_LABEL == "unmetered - subscription"


def test_requeue_row_carries_honest_unmetered_label(env):
    dbp = env["db"]
    jid = _claim_pipeline_job(dbp)
    conn = _conn(dbp)
    try:
        assert retry_mod.handle_failure(conn, jid, "w1",
                                        TimeoutError("read timed out")) == "requeued"
    finally:
        conn.close()
    costs = _cost_rows(dbp, jid)
    assert len(costs) == 1
    row = costs[0]
    assert row["usd"] == 0.0
    assert row["note"].startswith("UNMETERED|requeue attempt 1/3")
    assert "unmetered - subscription" in row["note"]
    assert not row["note"].startswith("ACTUAL|"), \
        "unmetered rows must not wear the ACTUAL label"


def test_review_row_carries_honest_unmetered_label(env):
    dbp = env["db"]
    jid = _claim_pipeline_job(dbp)
    conn = _conn(dbp)
    try:
        assert retry_mod.handle_failure(conn, jid, "w1",
                                        ValueError("bad config")) == "review"
    finally:
        conn.close()
    costs = _cost_rows(dbp, jid)
    assert len(costs) == 1
    row = costs[0]
    assert row["usd"] == 0.0
    assert row["note"].startswith("UNMETERED|attempt routed to review")
    assert "unmetered - subscription" in row["note"]
    assert not row["note"].startswith("ACTUAL|"), \
        "unmetered rows must not wear the ACTUAL label"


def test_no_actual_or_estimate_rows_on_unmetered_paths(env):
    # Drive several failures through both paths; nothing may claim to be a
    # real or estimated cost.
    dbp = env["db"]
    for err, n in ((TimeoutError("t"), 1), (ValueError("bad"), 1)):
        jid = _claim_pipeline_job(dbp)
        conn = _conn(dbp)
        try:
            retry_mod.handle_failure(conn, jid, "w1", err)
        finally:
            conn.close()
        for c in _cost_rows(dbp, jid):
            assert not c["note"].startswith("ACTUAL|"), c["note"]
            assert not c["note"].startswith("ESTIMATE|"), c["note"]


def test_log_metered_cost_records_api_returned_numbers_verbatim(env):
    # The sanctioned path for real costs: whatever the provider's API
    # returned (unit/qty/usd) is recorded exactly, prefixed ACTUAL|.
    dbp = env["db"]
    jid = _claim_pipeline_job(dbp)
    conn = _conn(dbp)
    try:
        queue_mod.log_metered_cost(
            conn, jid, "acme-llm", "tokens", 1234, 0.002468,
            "completion billed per usage response")
    finally:
        conn.close()
    costs = _cost_rows(dbp, jid)
    assert len(costs) == 1
    row = costs[0]
    assert row["provider"] == "acme-llm"
    assert row["unit"] == "tokens"
    assert row["qty"] == 1234
    assert row["usd"] == 0.002468
    assert row["note"].startswith("ACTUAL|")


def test_no_estimate_rows_anywhere_in_codebase():
    # Static guard: no production code writes or aggregates ESTIMATE|
    # rows. (Owner decision 2026-09-29: no estimated cost model.) The only
    # sanctioned mentions are the RESERVED convention notes in docstrings.
    hits = []
    for src in sorted((REPO / "hypelab").rglob("*.py")):
        for i, line in enumerate(src.read_text().splitlines(), 1):
            if "ESTIMATE|" in line and "RESERVED" not in line:
                hits.append(f"{src.name}:{i}: {line.strip()}")
    assert hits == [], hits
