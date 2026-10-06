# S2 — as-is architecture (source intake path)

Entry points:
- `hypelab/b2cli.py::source_add` (CLI `source add --campaign --kind --url
  --rights --poll-every`): parses args, click.Choice validates `--kind`,
  reads rights manifest JSON, calls `watcher.add_source`, `_die()`s on
  WatcherError.
- `hypelab/watcher.py::add_source` (the intake gate): loads campaign,
  validates kind, requires rights-manifest `basis`, validates feed URL
  scheme/host + campaign allowlist for yt_channel/rss, inserts source row.

Poll path (unchanged by this repair):
- `watcher.poll()` -> `_due_sources` -> `list_new_items(source)` ->
  per-kind lister; WatcherError caught as "list failed", `last_polled`
  updated, zero jobs enqueued. `list_new_items` branches yt_channel / rss
  / manual only; anything else raises.

Invariants (authoritative):
- Kind validity is decided ONCE at intake by add_source; poll trusts the
  stored kind (fail-closed raise for anything unlistable).
- CLI Choice and add_source's tuple were two copies of the same policy;
  both listed twitch while no lister existed. The repair keeps them as the
  two enforcement points but now with the identical supported set
  {yt_channel, rss, manual}.
- Rights-manifest requirement, allowlist checks, poll cadence floor,
  lease/retry/crash-recovery machinery: untouched.
