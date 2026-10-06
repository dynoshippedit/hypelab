# S1 — baseline (pre-fix source)

Baseline checks executed on the BROKEN (pre-fix) source via the gate
`run-check` recorder; receipts in checks/baseline/.

## check-new-regression (tests/test_source_kinds.py)
- Result: 5 failed, 4 passed (exit 1). Receipt: check-new-regression.json.
- The 5 failures are exactly the behavioral changes this repair makes:
  twitch accepted at intake (test_add_source_rejects_twitch,
  test_add_source_rejects_twitch_before_url_check), CLI advertises twitch
  (test_cli_source_add_rejects_twitch_kind,
  test_cli_source_add_help_lists_only_supported_kinds), and the rejection
  message form (test_add_source_rejects_other_unknown_kinds matched
  "unsupported source kind"; pre-fix message was "unknown source kind").
- The 4 passes confirm invariants that must hold both before and after:
  yt_channel/rss/manual still accepted; list_new_items still fails closed
  on unlistable kinds at poll time.
- This is the falsification anchor: the regression suite cannot pass on
  the broken implementation.

## check-full-suite (tests/)
- Result: 319 passed, 5 failed (exit 1). Receipt: check-full-suite.json.
  (Full log: check-full-suite.json.log.)
- All 315 pre-existing tests pass on pre-fix source, plus the 4 new tests
  that pin invariants (supported kinds accepted; poll-time fail-closed
  preserved) — the change surface (source-kind intake validation) has no
  other behavioral dependents.
- The 5 failures are exactly the new tests that encode the behavior change
  (4 twitch-specific + 1 message-form). A failure is useful baseline
  evidence: the only failures prove the defect.

## Before-state demonstration (repro script, evidence/repro-before.log)
```
INTAKE accepted twitch -> source id: src_e45a36f79dc8
POLL FAILED: unknown source kind 'twitch'
```
add_source accepted kind="twitch"; list_new_items raised WatcherError —
the exact silent-dead-job path the Media Engineer traced.
