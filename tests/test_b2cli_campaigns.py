"""Campaign CLI command tests (T-001: ARC-301, REV-700, REV-701).

Exercises the campaign commands end to end through CliRunner against an
isolated SQLite database -- no service mocks. Covers:
  * add -> list -> show -> bump-rules all exit 0
  * bump-rules builds valid provenance ({who, source_url, captured_at})
  (the budget-refresh command was removed 2026-09-29 with the money
  pipeline, D2)
  * list prints the schema's `state` column (REV-700, was KeyError)
  * show on an unknown id exits 1 with a clean error (REV-701)
"""

import json
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from click.testing import CliRunner  # noqa: E402

from hypelab import b2cli as b2cli_mod  # noqa: E402

CAMPAIGN = {
    "id": "cmp_t001",
    "platforms": ["instagram"],
    "rules": {"banned_words": ["scam"]},
    "creator": "alice",
    "marketplace": "mkt",
}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    dbp = tmp_path / "t.db"
    monkeypatch.setenv("HYPELAB_DB", str(dbp))
    root = tmp_path / "root"
    (root / "work").mkdir(parents=True)
    monkeypatch.setenv("HYPELAB_ROOT", str(root))
    return {"runner": CliRunner(), "db": dbp}


def _w(tmp_path, name, obj):
    p = tmp_path / name
    p.write_text(json.dumps(obj), encoding="utf-8")
    return str(p)


def _add(env, tmp_path, campaign=CAMPAIGN):
    return env["runner"].invoke(
        b2cli_mod.campaign_grp, ["add", _w(tmp_path, "campaign.json", campaign)]
    )


def _row(env):
    conn = sqlite3.connect(str(env["db"]))
    try:
        return conn.execute(
            "SELECT * FROM campaigns WHERE id='cmp_t001'"
        ).fetchone(), conn
    finally:
        conn.close()


def test_add_list_show(env, tmp_path):
    r = _add(env, tmp_path)
    assert r.exit_code == 0, r.output
    assert r.output.strip() == "cmp_t001"

    # REV-700: list used c['status'] (KeyError); schema column is `state`.
    r = env["runner"].invoke(b2cli_mod.campaign_grp, ["list"])
    assert r.exit_code == 0, r.output
    assert "cmp_t001" in r.output
    assert "active" in r.output

    r = env["runner"].invoke(b2cli_mod.campaign_grp, ["show", "cmp_t001"])
    assert r.exit_code == 0, r.output
    assert '"rules_version": 1' in r.output


def test_show_unknown_id_is_clean_error(env):
    # REV-701: load() raises CampaignError, not KeyError -- must not traceback.
    r = env["runner"].invoke(b2cli_mod.campaign_grp, ["show", "no_such_campaign"])
    assert r.exit_code == 1
    assert "error:" in r.output
    assert "Traceback" not in r.output


def test_bump_rules_records_valid_provenance(env, tmp_path):
    r = _add(env, tmp_path)
    assert r.exit_code == 0, r.output

    # ARC-301a: passing the --by string straight through could never work.
    r = env["runner"].invoke(
        b2cli_mod.campaign_grp,
        ["bump-rules", "cmp_t001", _w(tmp_path, "rules.json", {"banned_words": ["x"]}), "--by", "dino"],
    )
    assert r.exit_code == 0, r.output
    assert "rules -> v2" in r.output

    conn = sqlite3.connect(str(env["db"]))
    try:
        row = conn.execute(
            "SELECT rules_version, rules_provenance FROM campaigns WHERE id='cmp_t001'"
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == 2
    prov = json.loads(row[1])  # must be valid JSON: _parse() json.loads it later
    assert prov["who"] == "dino"
    assert prov["source_url"]
    assert prov["captured_at"]


def test_bump_rules_unknown_id_is_clean_error(env, tmp_path):
    r = env["runner"].invoke(
        b2cli_mod.campaign_grp,
        ["bump-rules", "no_such_campaign", _w(tmp_path, "rules.json", {"a": 1}), "--by", "dino"],
    )
    assert r.exit_code == 1
    assert "error:" in r.output
