"""D2 (hl-cycle-09): the custom money pipeline is gone, the cost ledger stays.

Proves:
  * no charge/payout/budget CLI command remains reachable
  * the cost ledger still accepts rows via log_cost (spend tracking kept)
  * the money-model columns are gone from the schema
  * the payout metric is gone
"""

import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import b2cli as b2cli_mod  # noqa: E402
from hypelab import book3cli as book3cli_mod  # noqa: E402
from hypelab import cli as cli_mod  # noqa: E402
from hypelab import db as db_mod  # noqa: E402
from hypelab import jobs as jobs_mod  # noqa: E402
from hypelab import metrics as metrics_mod  # noqa: E402
from hypelab import queue as queue_mod  # noqa: E402

MONEY_WORDS = ("charge", "payout", "budget")


def _all_command_names(mod):
    names = set()

    def walk(cmd):
        names.add(cmd.name)
        if hasattr(cmd, "commands"):
            for sub in cmd.commands.values():
                walk(sub)

    for c in getattr(mod, "COMMANDS", []):
        walk(c)
    return names


@pytest.fixture()
def conn(tmp_path):
    dbp = tmp_path / "money.db"
    cx = sqlite3.connect(str(dbp))
    cx.row_factory = sqlite3.Row
    db_mod.migrate(cx)
    yield cx
    cx.close()


def test_no_money_cli_commands_reachable():
    found = {}
    for mod, label in ((b2cli_mod, "b2cli"), (book3cli_mod, "book3cli"),
                       (cli_mod, "cli")):
        for name in _all_command_names(mod):
            low = name.lower()
            if any(w in low for w in MONEY_WORDS):
                found.setdefault(label, []).append(name)
    assert not found, f"money commands still reachable: {found}"


def test_money_columns_gone_from_schema(conn):
    def cols(table):
        return {r[1] for r in conn.execute(f"PRAGMA table_info({table})")}
    camp_cols = cols("campaigns")
    for c in ("rate_per_1k_usd", "rate_basis", "budget_total_usd",
              "budget_seen_usd", "budget_checked", "budget_provenance"):
        assert c not in camp_cols, f"campaigns.{c} still present"
    assert "payout_usd" not in cols("posts")


def test_payout_metric_removed():
    assert not hasattr(metrics_mod, "usd_per_clip_hour")
    assert not any("payout" in n for n in dir(metrics_mod))


def test_cost_ledger_still_accepts_rows(conn):
    # The ledger is spend tracking, kept per D2. log_cost is its writer.
    jid = jobs_mod.new(conn, mode="A", title="ledger-check")
    queue_mod.log_cost(conn, jid, "whisper", "audio_min", 2.0, 0.012,
                       "ESTIMATE|stt draft")
    queue_mod.log_cost(conn, jid, "whisper", "audio_min", 2.0, 0.011,
                       "ACTUAL|stt billed")
    rows = conn.execute(
        "SELECT usd, note FROM cost_ledger WHERE job_id=? ORDER BY id",
        (jid,)).fetchall()
    assert [r[0] for r in rows] == [0.012, 0.011]
    assert rows[0][1].startswith("ESTIMATE|")
    assert rows[1][1].startswith("ACTUAL|")


def test_no_charge_function_left():
    assert not hasattr(queue_mod, "charge")
    assert hasattr(queue_mod, "log_cost")
