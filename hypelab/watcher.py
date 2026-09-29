"""Source watcher (Book 2, section 4).

Polls due sources for new items and enqueues one clip job per new item.
The watcher only lists public metadata (titles, durations, upload times) —
listing is not downloading. The rights manifest (§5a) is required at
ingest time, before any bytes are fetched.

list_new_items dispatches on source kind:
  yt_channel — yt-dlp --flat-playlist (network; NOT exercised in tests)
  rss        — plain RSS/Atom fetch + parse (network; NOT exercised in tests)
  manual     — a local JSON listing file (the fixture/offline path; this is
               what tests and the local acceptance run use)

Poll cadence: 15 minutes default; 5 minutes for high-rate campaigns with a
predictable upload schedule. Never below that — rate-limiting costs hours.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlparse

from . import jobs as jobs_mod
from .util import now

#: Never poll more often than this, however the source is configured.
MIN_POLL_EVERY_S = 300


class WatcherError(Exception):
    """A source could not be listed."""


# ------------------------------------------------------------------ listers

def _ytdlp_flat_playlist(url: str, limit: int = 5) -> list[dict]:
    """yt-dlp --flat-playlist listing. NETWORK. Not exercised in tests."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--playlist-end", str(limit),
        "--dump-json", url,
    ]
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, shell=False
        )
    except FileNotFoundError as e:
        raise WatcherError(f"yt-dlp binary not found: {e}")
    if proc.returncode != 0:
        raise WatcherError(
            f"yt-dlp flat-playlist failed: {proc.stderr.strip()[:300]}"
        )
    items = []
    for line in proc.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except ValueError:
            continue
    return items


def _rss_items(url: str, limit: int = 20) -> list[dict]:
    """Minimal RSS/Atom listing. NETWORK. Not exercised in tests."""
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            data = r.read()
    except Exception as e:
        raise WatcherError(f"RSS fetch failed for {url}: {e}")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise WatcherError(f"RSS parse failed for {url}: {e}")
    items = []
    for entry in list(root.iter("item"))[:limit] + list(
        root.iter("{http://www.w3.org/2005/Atom}entry")
    )[:limit]:
        def _text(tag):
            el = entry.find(tag)
            if el is not None and el.text:
                return el.text.strip()
            el = entry.find(f"{{http://www.w3.org/2005/Atom}}{tag}")
            return el.text.strip() if el is not None and el.text else None

        link = _text("link")
        if link is None:
            for l in entry.findall("link") + entry.findall(
                "{http://www.w3.org/2005/Atom}link"
            ):
                if l.get("href"):
                    link = l.get("href")
                    break
        items.append({
            "id": _text("guid") or link or "",
            "url": link or "",
            "title": _text("title") or "",
            "published_at": _text("pubDate") or _text("published"),
        })
    return items


def _manual_items(url: str) -> list[dict]:
    """Local JSON listing file: {"items": [{id, url, title, duration,
    published_at, info_path?, words_path?}, ...]}. The offline/fixture path —
    no network, and the only lister exercised in tests."""
    p = Path(url)
    if not p.is_file():
        raise WatcherError(f"manual listing is not a file: {url}")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except ValueError as e:
        raise WatcherError(f"manual listing is not valid JSON: {e}")
    items = data.get("items")
    if not isinstance(items, list):
        raise WatcherError("manual listing needs an 'items' list")
    return items


def list_new_items(source) -> list[dict]:
    """List candidate items for a source row (dict-like)."""
    kind = source["kind"]
    if kind == "yt_channel":
        return _ytdlp_flat_playlist(source["url"])
    if kind == "rss":
        return _rss_items(source["url"])
    if kind == "manual":
        return _manual_items(source["url"])
    raise WatcherError(f"unknown source kind {kind!r}")


# ------------------------------------------------------------------ allowlist

def source_allowed(url: str, campaign: dict) -> bool:
    """Allowlist check (Fact-2 logic): when the campaign names a
    source_allowlist, the item URL must contain one of its entries. An empty
    or absent allowlist allows everything (no restriction recorded)."""
    allow = (campaign.get("rules") or {}).get("source_allowlist") or []
    if not allow:
        return True
    u = (url or "").lower()
    return any(a.lower() in u for a in allow if a)


# ------------------------------------------------------------------ poll

def _due_sources(conn: sqlite3.Connection, campaign_id: str | None = None):
    q = (
        "SELECT * FROM sources WHERE last_polled IS NULL "
        "OR (julianday('now') - julianday(last_polled)) * 86400 > poll_every_s"
    )
    args: tuple = ()
    if campaign_id:
        q += " AND campaign_id=?"
        args = (campaign_id,)
    return conn.execute(q, args).fetchall()


def add_source(conn: sqlite3.Connection, *, campaign_id: str, kind: str,
               url: str, authorization: dict, poll_every_s: int = 900) -> str:
    """Register a source. The rights manifest is REQUIRED at add time —
    fail closed: no basis, no source row."""
    from . import campaigns as campaigns_mod

    campaigns_mod.load(conn, campaign_id)  # raises if unknown
    if kind not in ("yt_channel", "rss", "twitch", "manual"):
        raise WatcherError(f"unknown source kind {kind!r}")
    if not isinstance(authorization, dict) or not authorization.get("basis"):
        raise WatcherError(
            "source add requires a rights manifest with a 'basis' "
            "(campaign_supplied | platform_mechanism | "
            "explicit_permission | needs_clearance)"
        )
    if authorization["basis"] not in (
        "campaign_supplied", "platform_mechanism",
        "explicit_permission", "needs_clearance",
    ):
        raise WatcherError(
            f"unknown rights basis {authorization['basis']!r}"
        )
    poll_every_s = max(int(poll_every_s), MIN_POLL_EVERY_S)
    sid = campaigns_mod.new_source_id()
    conn.execute(
        "INSERT INTO sources(id, campaign_id, kind, url, authorization,"
        " poll_every_s, last_polled, last_item_id)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (sid, campaign_id, kind, url, json.dumps(authorization),
         poll_every_s, None, None),
    )
    return sid


def record_clearance(conn: sqlite3.Connection, source_id: str,
                     granted_by: str, evidence: str, scope: str = "") -> None:
    """Record explicit clearance on a needs_clearance source.

    require_rights passes once a clearance object exists; the basis stays
    'needs_clearance' in the manifest so the history shows the source was
    not clear at add time.
    """
    row = conn.execute(
        "SELECT authorization FROM sources WHERE id=?", (source_id,)
    ).fetchone()
    if row is None:
        raise WatcherError(f"unknown source {source_id!r}")
    auth = json.loads(row["authorization"] or "{}")
    auth["clearance"] = {
        "granted_by": granted_by,
        "granted_at": now(),
        "evidence": evidence,
        "scope": scope,
    }
    conn.execute(
        "UPDATE sources SET authorization=? WHERE id=?",
        (json.dumps(auth), source_id),
    )


def poll(conn: sqlite3.Connection,
         lister=list_new_items,
         campaign_id: str | None = None) -> list[tuple[dict, str]]:
    """Poll due sources; enqueue one queued_ingest job per new allowed item.

    Returns [(item, job_id), ...]. Skips items already seen and items failing
    the campaign's source allowlist. Updates last_polled per source.
    Notification is a printed line — the value of the watcher is latency,
    and the operator's phone path is configured outside this module.
    """
    from . import campaigns as campaigns_mod

    new: list[tuple[dict, str]] = []
    for s in _due_sources(conn, campaign_id):
        try:
            items = lister(s)
        except WatcherError as e:
            print(f"watch: source {s['id']} list failed: {e}")
            conn.execute(
                "UPDATE sources SET last_polled=? WHERE id=?",
                (now(), s["id"]),
            )
            continue
        camp = campaigns_mod.load(conn, s["campaign_id"])
        for item in items:
            iid = str(item.get("id") or item.get("url") or "")
            if not iid:
                continue
            if conn.execute(
                "SELECT 1 FROM source_items WHERE id=?", (iid,)
            ).fetchone():
                continue
            if not source_allowed(item.get("url", ""), camp):
                continue
            conn.execute(
                "INSERT INTO source_items(id, source_id, url, title,"
                " duration_s, published_at, seen_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    iid, s["id"], item.get("url", ""),
                    item.get("title"), item.get("duration"),
                    item.get("published_at"), now(),
                ),
            )
            job_id = jobs_mod.new(
                conn, mode="clip", campaign_id=camp["id"],
                state="queued_ingest", title=item.get("title") or iid,
            )
            # Link the item to its job: ingest looks the item up by job_id.
            conn.execute(
                "UPDATE source_items SET job_id=? WHERE id=?",
                (job_id, iid),
            )
            dur = item.get("duration")
            dur_s = f" ({dur / 60:.0f}m)" if isinstance(dur, (int, float)) else ""
            print(f"NEW · {camp.get('creator')} · "
                  f"{item.get('title')}{dur_s} → {job_id}")
            new.append((item, job_id))
        conn.execute(
            "UPDATE sources SET last_polled=?, last_item_id=? WHERE id=?",
            (now(), str(items[-1].get("id")) if items else s["last_item_id"],
             s["id"]),
        )
    return new


def host_of(url: str) -> str:
    try:
        return urlparse(url or "").netloc.lower()
    except Exception:
        return ""
