# S7 — diff challenge (SELF_REVIEW)

Diff re-read (hypelab/b2cli.py, hypelab/watcher.py, tests/test_source_kinds.py):

1. Cause removed, not suppressed: twitch can no longer enter the system
   at either enforcement point (CLI parse rejects it; add_source raises).
   The poll-time symptom (silent zero-job cycles) is unreachable for new
   sources. Legacy rows still raise loudly at poll — the pre-existing
   fail-closed contract, unchanged.
2. Original user workflow: `source add --kind twitch` now fails fast with
   a plain-language message naming the supported kinds. `source add` for
   yt_channel/rss/manual is byte-identical to before (covered by tests).
3. Could the regression tests pass on the broken implementation? No —
   demonstrated: 5 of 9 fail on pre-fix code (baseline receipt). The 4
   that pass on both pin invariants that must survive the change.
4. Ordering/retries/auth/data semantics: untouched. add_source still
   raises WatcherError for bad input; the kind check still runs before
   the rights-manifest and URL checks? — VERIFIED: the kind check is first
   in add_source (line 170-174), before the basis check and URL check, so
   a twitch kind surfaces the kind error even with a garbage URL
   (test_add_source_rejects_twitch_before_url_check pins this).
5. No assertion/threshold/spec weakened to get a pass. The message-text
   change for unsupported kinds ("unknown" -> "unsupported ... supported
   kinds are ...") is the required "clear error at intake"; grep confirms
   nothing matched on the old text.
6. No performance claims; change is O(1) tuple membership.
7. Docs/UI: CLI --help now lists only supported kinds (test-pinned).
   Historical devteam notes mentioning twitch are records, not docs —
   intentionally untouched.

Reviewer mode: SELF_REVIEW — no independent reviewer was available in
this cycle; this challenge pass was performed explicitly against the
questions above. Recorded honestly per the flow.
