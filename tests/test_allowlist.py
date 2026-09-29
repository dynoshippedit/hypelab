"""A2/C5: one shared allowlist verdict; substring bypasses are dead.

Proves: ``evilyoutube.com`` (REV-714), ``youtube.com.evil.com`` and
``notyoutube.com`` are REJECTED by a ``youtube.com`` allowlist while
``youtube.com`` / ``www.youtube.com`` / ``m.youtube.com`` are ACCEPTED —
in the shared verdict, the watcher poll path, and the compliance (money)
gate alike. Falsification: these tests FAIL on pre-fix code (substring
matching) and PASS on the fixed code.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hypelab import allowlist as allowlist_mod  # noqa: E402
from hypelab import campaigns as campaigns_mod  # noqa: E402
from hypelab import compliance as compliance_mod  # noqa: E402
from hypelab import watcher as watcher_mod  # noqa: E402
from hypelab.db import connect  # noqa: E402

ALLOW = ["youtube.com"]


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.youtube.com/watch?v=x", True),
        ("https://youtube.com/watch?v=x", True),
        ("https://m.youtube.com/shorts/x", True),
        ("http://youtube.com/x", True),
        ("https://WWW.YOUTUBE.COM/x", True),  # case-insensitive
        ("https://www.youtube.com:8443/x", True),  # port stripped
        ("https://evilyoutube.com/watch?v=x", False),  # REV-714 bypass
        ("https://youtube.com.evil.com/x", False),  # suffix attack
        ("https://notyoutube.com/x", False),  # confusable
        ("https://evil.com/?next=youtube.com", False),  # entry in query only
        ("", False),  # no host -> fail closed
        ("not a url", False),
        ("/home/dino/hypelab/tests/fixtures_book2/source.mp4", False),  # path
        ("ftp://www.youtube.com/x", True),  # host still matches; scheme
        # validated separately at add_source
    ],
)
def test_verdict_host_matching(url, expected):
    ok, _reason = allowlist_mod.allowlist_verdict(url, ALLOW)
    assert ok is expected


def test_verdict_empty_allowlist_allows_everything():
    ok, reason = allowlist_mod.allowlist_verdict("https://anything.example/x", [])
    assert ok is True
    assert "no allowlist" in reason


def test_verdict_entry_as_full_url():
    ok, _ = allowlist_mod.allowlist_verdict(
        "https://www.youtube.com/x", ["https://youtube.com/some/path"])
    assert ok is True


def test_verdict_subdomain_entry_does_not_grant_parent():
    ok, _ = allowlist_mod.allowlist_verdict(
        "https://youtube.com/x", ["www.youtube.com"])
    assert ok is False
    ok, _ = allowlist_mod.allowlist_verdict(
        "https://deep.www.youtube.com/x", ["www.youtube.com"])
    assert ok is True


def test_verdict_ignores_blank_entries():
    ok, _ = allowlist_mod.allowlist_verdict(
        "https://www.youtube.com/x", ["", "  ", "youtube.com"])
    assert ok is True


def test_watcher_source_allowed_delegates_to_shared_verdict():
    camp = {"rules": {"source_allowlist": ["youtube.com"]}}
    assert watcher_mod.source_allowed("https://www.youtube.com/watch?v=x", camp) is True
    assert watcher_mod.source_allowed("https://evilyoutube.com/x", camp) is False
    assert watcher_mod.source_allowed("https://youtube.com.evil.com/x", camp) is False
    # no allowlist recorded -> everything allowed (unchanged behavior)
    assert watcher_mod.source_allowed("https://anything.example/", {}) is True
    assert watcher_mod.source_allowed(
        "https://anything.example/", {"rules": {}}) is True


def test_compliance_gate_money_path():
    # REV-714: evilyoutube.com must FAIL the money gate, not PASS.
    verdict, _ = compliance_mod.chk_source_allowed(
        {"source_url": "https://evilyoutube.com/watch?v=x"},
        {"source_allowlist": ["youtube.com"]})
    assert verdict == compliance_mod.FAIL
    verdict, _ = compliance_mod.chk_source_allowed(
        {"source_url": "https://www.youtube.com/watch?v=x"},
        {"source_allowlist": ["youtube.com"]})
    assert verdict == compliance_mod.PASS
    # short link: host genuinely off-allowlist but ambiguous -> human review
    verdict, _ = compliance_mod.chk_source_allowed(
        {"source_url": "https://youtu.be/xyz"},
        {"source_allowlist": ["youtube.com"]})
    assert verdict == compliance_mod.UNKNOWN
    # host matches -> PASS even though the path looks "embed"-ish
    verdict, _ = compliance_mod.chk_source_allowed(
        {"source_url": "https://www.youtube.com/embed/xyz"},
        {"source_allowlist": ["youtube.com"]})
    assert verdict == compliance_mod.PASS
    # no allowlist -> PASS (unchanged behavior)
    verdict, msg = compliance_mod.chk_source_allowed(
        {"source_url": "https://anything.example/x"}, {})
    assert verdict == compliance_mod.PASS
    assert "n/a" in msg


@pytest.fixture()
def conn(tmp_path):
    cx = connect(tmp_path / "al.db")
    yield cx
    cx.close()


@pytest.fixture()
def camp(conn):
    campaigns_mod.add(conn, {
        "id": "allow-camp",
        "marketplace": "test-mart",
        "creator": "Allow Creator",
        "rate_per_1k_usd": 4.0,
        "rate_basis": "observed",
        "platforms": ["tiktok"],
        "rules": {"source_allowlist": ["fixture.example"]},
    })
    return campaigns_mod.load(conn, "allow-camp")


def _auth():
    return {"basis": "campaign_supplied", "granted_by": "campaign"}


def test_add_source_rejects_off_allowlist_feed(conn, camp):
    with pytest.raises(watcher_mod.WatcherError, match="allowlist"):
        watcher_mod.add_source(
            conn, campaign_id=camp["id"], kind="rss",
            url="https://evilyoutube.com/feed.xml",
            authorization=_auth(), poll_every_s=900)


def test_add_source_rejects_non_http_feed(conn, camp):
    with pytest.raises(watcher_mod.WatcherError, match="http"):
        watcher_mod.add_source(
            conn, campaign_id=camp["id"], kind="rss",
            url="ftp://fixture.example/feed.xml",
            authorization=_auth(), poll_every_s=900)


def test_add_source_accepts_on_allowlist_feed(conn, camp):
    sid = watcher_mod.add_source(
        conn, campaign_id=camp["id"], kind="rss",
        url="https://www.fixture.example/feed.xml",
        authorization=_auth(), poll_every_s=900)
    assert sid


def test_add_source_manual_keeps_placeholder_url(conn, camp):
    # manual listings are local files; their item URLs are checked at poll.
    sid = watcher_mod.add_source(
        conn, campaign_id=camp["id"], kind="manual", url="x",
        authorization=_auth(), poll_every_s=900)
    assert sid
