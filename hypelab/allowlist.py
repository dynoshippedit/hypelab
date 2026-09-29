"""Shared URL allowlist verdict (C5 / A2).

One function owns "is this URL allowed by this allowlist" for the whole
pipeline — the watcher poll path and the compliance gate. Matching is on
the parsed host with label-boundary suffix semantics, never substring
matching, so ``evilyoutube.com`` cannot ride on a ``youtube.com`` entry
(REV-714), and the two gates can no longer give divergent verdicts on the
same URL (ARC-310, SEC-103).

An entry matches a URL when the URL's host equals the entry's host or is a
subdomain of it: ``www.youtube.com`` matches ``youtube.com``;
``youtube.com.evil.com`` and ``evilyoutube.com`` do not. An empty or absent
allowlist allows everything, preserving the long-standing "no restriction
recorded" behavior. A URL with no parseable host is rejected when an
allowlist exists (fail closed): local file paths are not web sources.
"""

from __future__ import annotations

from urllib.parse import urlparse

#: Tokens that make a rejected URL "ambiguous" rather than a clean FAIL in
#: the compliance gate: redirects, embeds, re-uploads, short links. A human
#: verifies these against rules_provenance (the original chk_source_allowed
#: behavior, kept deliberately).
AMBIGUOUS_TOKENS = ("embed", "youtu.be", "list=", "/shorts/")


def host_of_url(url: str) -> str:
    """Lowercased host of a URL, port stripped; "" when unparseable."""
    try:
        host = urlparse(url or "").hostname or ""
    except Exception:
        return ""
    return host.lower().rstrip(".")


def scheme_of_url(url: str) -> str:
    """Lowercased URL scheme ("" when unparseable)."""
    try:
        return urlparse(url or "").scheme.lower()
    except Exception:
        return ""


def host_of_entry(entry: str) -> str:
    """Normalize an allowlist entry to a bare host.

    Accepts bare hosts (``youtube.com``), hosts with paths
    (``youtube.com/feed``), hosts with ports (``youtube.com:8080``), and
    full URLs (``https://www.youtube.com/channel/...``).
    """
    e = (entry or "").strip().lower().rstrip(".")
    if not e:
        return ""
    if "://" in e:
        return host_of_url(e)
    # bare host, possibly with path/query/fragment or :port
    e = e.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    if e.startswith("["):  # IPv6 literal
        return e.split("]", 1)[0] + "]"
    if e.count(":") == 1:
        e = e.split(":", 1)[0]
    return e


def entry_matches(host: str, entry_host: str) -> bool:
    """Label-boundary suffix match: exact host or any subdomain."""
    return bool(host) and bool(entry_host) and (
        host == entry_host or host.endswith("." + entry_host)
    )


def allowlist_verdict(url: str, allow) -> tuple[bool, str]:
    """Shared verdict: (allowed, reason).

    Empty/absent allowlist -> (True, ...) — no restriction recorded.
    A URL with no parseable host is rejected when an allowlist exists
    (fail closed).
    """
    entries = [a for a in (allow or []) if a and str(a).strip()]
    if not entries:
        return True, "no allowlist recorded"
    host = host_of_url(url)
    if not host:
        return False, f"no host in url {url!r}"
    for entry in entries:
        eh = host_of_entry(entry)
        if eh and entry_matches(host, eh):
            return True, f"host {host} on allowlist ({entry})"
    return False, f"host {host} not on allowlist"


def looks_ambiguous(url: str) -> bool:
    """True when a non-matching URL carries a token the old gate treated as
    human-review material (redirects, embeds, short links)."""
    u = (url or "").lower()
    return any(tok in u for tok in AMBIGUOUS_TOKENS)
