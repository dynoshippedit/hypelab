# S4 — findings

## FIND-HYPE-MEDIA-1 · CONFIRMED_DEFECT (repaired)
- Claim: `twitch` was advertised and accepted as a source kind at intake,
  but no twitch lister exists; every poll of such a source raised
  WatcherError, which poll() swallowed as "list failed" and produced zero
  jobs — silently, every cycle.
- Location: hypelab/b2cli.py:157 (CLI Choice), hypelab/watcher.py:170
  (add_source whitelist), hypelab/watcher.py:143-155 (list_new_items, no
  twitch branch).
- Expected behavior source: chief decision — fail closed: reject twitch
  (and any unsupported source) with a clear error at intake.
- Observed: pre-fix repro — add_source accepted kind="twitch"
  (source id src_e45a36f79dc8); list_new_items raised
  `WatcherError: unknown source kind 'twitch'`.
- Counter-check (what would disprove it): a twitch branch in
  list_new_items, or poll() surfacing the error to the operator instead of
  "list failed". grep found no twitch lister; repro confirmed the silent
  path. Not stale, not a false assumption.
- Impact: S3 — user-facing dead option; no data loss, no money path
  involved, but jobs silently produce no work.
- Resolution: FIXED. Verification: check-new-regression (9/9 final),
  check-full-suite (324/324 final).
- Related, deliberately NOT expanded: implementing a real twitch lister
  (chief chose rejection); lifeboat/Decentralflix media findings (other
  roots).

No other candidate findings. No rejected leads beyond scope: the remaining
twitch mentions in devteam/*.md are historical review notes, not product
behavior — left untouched as records.
