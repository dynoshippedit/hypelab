# S5 — writer evidence (repair engineer)

Change (uncommitted, on master @ 5c185ba):
```
 hypelab/b2cli.py  | 1 line:  Choice(["yt_channel","rss","twitch","manual"])
                              -> Choice(["yt_channel","rss","manual"])
 hypelab/watcher.py | kind whitelist drops "twitch"; rejection message is now
                      "unsupported source kind {kind!r}: supported kinds are
                      'yt_channel', 'rss', 'manual' (twitch polling is not
                      implemented)"; http(s)-URL branch narrows to
                      ("yt_channel","rss").
 tests/test_source_kinds.py | new, 9 regression tests
```

Before/after identity:
- Before: `git stash` restored pre-fix source for the initial snapshot;
  before-state demonstrated by repro (evidence/repro-before.log) and by
  the baseline receipts (5 new tests failing on broken code).
- After: fix restored via `git stash pop`; post-fix repro rejects at
  intake (evidence/repro-after.log); final receipts green.

Focused test run: tests/test_source_kinds.py 9/9 passed (final receipt).
Introduced regressions: none — full suite 324/324 (final receipt).

Searched for directly related instances: grep for "twitch" across the
repo (excl. devteam/checkups) shows only the three repaired sites; the
CLI Choice, add_source whitelist, and URL-validation branch are now
consistent. No other intake path accepts source kinds (ingest.py has no
kind handling; poll trusts stored rows).

Limitations: legacy twitch rows (if any exist in a dev DB) still fail
closed at poll time with "unknown source kind" — unchanged, loud, no
silent behavior change; no migration required since such rows were never
productive.
