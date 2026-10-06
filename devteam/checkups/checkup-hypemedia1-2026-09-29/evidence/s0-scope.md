# S0 — scope (checkup-hypemedia1-2026-09-29)

Scope: **change checkup** on the HYPE-MEDIA-1 repair.

Root: /home/dino/hypelab, branch master, HEAD 5c185ba
(repair left uncommitted per task constraints).

Confirmed defect (Media Engineer F-5, chief decision — fail closed):
the HypeLab CLI advertises and accepts `twitch` as a source kind, but
`watcher.list_new_items` has no twitch branch. `add_source` accepts it,
`poll()` catches the resulting WatcherError as "list failed", updates
`last_polled`, and enqueues zero jobs — every cycle, silently.

Repair (this change):
- `hypelab/b2cli.py`: `source add --kind` Choice drops `"twitch"`.
- `hypelab/watcher.py::add_source`: kind whitelist drops `"twitch"`;
  unsupported kinds (twitch or anything else) are rejected at intake with
  `WatcherError("unsupported source kind {kind!r}: supported kinds are
  'yt_channel', 'rss', 'manual' (twitch polling is not implemented)")`.
- `hypelab/watcher.py::add_source`: the http(s)-URL validation branch
  narrows from `("yt_channel","rss","twitch")` to `("yt_channel","rss")`
  (twitch is now unreachable there — same root cause, no behavior change).
- `tests/test_source_kinds.py`: 9 new regression tests.

Out of scope: T-044 settlement (verified intact, not re-litigated);
Decentralflix F-1..F-4 (different root); lifeboat; any twitch lister
implementation (chief chose rejection, not implementation).

Initial source identity: snapshot taken on PRE-FIX source (broken),
`initial.json` in this checkup dir. Source digest pinned before any
modification by this repair cycle.
