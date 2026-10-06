"""Regression tests for HYPE-MEDIA-1: the CLI advertised `twitch` as a source
kind and add_source accepted it, but list_new_items has no twitch branch —
poll() caught WatcherError as "list failed" and enqueued zero jobs, every
cycle, silently. Chief decision: fail closed — reject unsupported kinds at
intake with a plain-language error.

Falsification: these tests FAIL on pre-fix code (twitch accepted at intake,
CLI Choice lists twitch) and PASS on the fixed code.
"""

import json
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hypelab import campaigns as campaigns_mod  # noqa: E402
from hypelab import cli as cli_mod  # noqa: E402
from hypelab import watcher as watcher_mod  # noqa: E402
from hypelab.db import connect  # noqa: E402


@pytest.fixture()
def conn(tmp_path):
    cx = connect(tmp_path / "kinds.db")
    yield cx
    cx.close()


@pytest.fixture()
def camp(conn):
    campaigns_mod.add(conn, {
        "id": "kind-camp",
        "marketplace": "test-mart",
        "creator": "Kind Creator",
        "rate_basis": "observed",
        "platforms": ["tiktok"],
        "rules": {"source_allowlist": ["fixture.example"]},
    })
    return campaigns_mod.load(conn, "kind-camp")


def _auth():
    return {"basis": "campaign_supplied", "granted_by": "campaign"}


# ---------------------------------------------------------------- intake

def test_add_source_rejects_twitch(conn, camp):
    """twitch is not a listable source kind: rejected at intake, loudly."""
    with pytest.raises(watcher_mod.WatcherError) as excinfo:
        watcher_mod.add_source(
            conn, campaign_id=camp["id"], kind="twitch",
            url="https://www.twitch.tv/somechannel",
            authorization=_auth())
    msg = str(excinfo.value)
    assert "twitch" in msg
    assert "yt_channel" in msg and "rss" in msg and "manual" in msg


def test_add_source_rejects_other_unknown_kinds(conn, camp):
    with pytest.raises(watcher_mod.WatcherError, match="unsupported source kind"):
        watcher_mod.add_source(
            conn, campaign_id=camp["id"], kind="dailymotion",
            url="https://www.fixture.example/v",
            authorization=_auth())


def test_add_source_rejects_twitch_before_url_check(conn, camp):
    """Kind rejection comes first: even a garbage URL must surface the kind error."""
    with pytest.raises(watcher_mod.WatcherError, match="unsupported source kind"):
        watcher_mod.add_source(
            conn, campaign_id=camp["id"], kind="twitch",
            url="not-a-url",
            authorization=_auth())


@pytest.mark.parametrize("kind,url", [
    ("yt_channel", "https://www.fixture.example/c"),
    ("rss", "https://www.fixture.example/feed.xml"),
])
def test_add_source_accepts_supported_feed_kinds(conn, camp, kind, url):
    sid = watcher_mod.add_source(
        conn, campaign_id=camp["id"], kind=kind, url=url,
        authorization=_auth())
    assert sid


def test_add_source_accepts_manual(conn, camp, tmp_path):
    listing = tmp_path / "listing.json"
    listing.write_text(json.dumps({"items": []}))
    sid = watcher_mod.add_source(
        conn, campaign_id=camp["id"], kind="manual",
        url=str(listing), authorization=_auth())
    assert sid


# ------------------------------------------------- poll-time fail-closed

def test_list_new_items_still_fails_closed_on_unknown_kind():
    """Any legacy row (or hand-written row) with an unlistable kind must raise,
    never silently yield zero items."""
    with pytest.raises(watcher_mod.WatcherError, match="unknown source kind"):
        watcher_mod.list_new_items(
            {"kind": "twitch", "url": "https://www.twitch.tv/x"})


# ---------------------------------------------------------------- CLI

def test_cli_source_add_rejects_twitch_kind():
    """The CLI no longer advertises twitch: click.Choice rejects it (exit 2)."""
    runner = CliRunner()
    r = runner.invoke(cli_mod.cli, [
        "source", "add",
        "--campaign", "nope",
        "--kind", "twitch",
        "--url", "https://www.twitch.tv/x",
        "--rights", "/tmp/definitely-missing-rights.json",
    ])
    assert r.exit_code == 2, r.output
    assert "twitch" in r.output  # click names the invalid value


def test_cli_source_add_help_lists_only_supported_kinds():
    r = CliRunner().invoke(cli_mod.cli, ["source", "add", "--help"])
    assert r.exit_code == 0, r.output
    assert "twitch" not in r.output
    assert "yt_channel" in r.output
