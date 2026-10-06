# S1 — executable baseline (checkup-hlflag-2026-09-29)

All commands ran through the gate with source digests captured before/after
(source_before == source_after in every receipt; the tree was not modified
during the checkup).

## check-requeue-tests (baseline)
- argv: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_failure_requeue.py -q`
- exit 0, `36 passed in 0.55s`. Includes 7 new kill-switch tests:
  kill-switch disabled → review pile (reason `auto-requeue-disabled:`),
  default-on still requeues, 6 disabled spellings, 4 enabled spellings,
  default-on when unset.

## check-drive-atomicity (baseline)
- argv: `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_cli_drive_fail.py tests/test_queue_atomicity.py -q`
- exit 0, `21 passed in 2.21s`. Adjacent failure-path coverage (drive fail →
  review pile only, never requeue; lease-predicated atomic updates).

## check-live-behavior (baseline)
- argv: `python3 devteam/checkups/checkup-hlflag-2026-09-29/evidence/live_behavior_verify.py`
- exit 0, `ALL LIVE BEHAVIOR CHECKS PASSED`. Real sqlite DB, real implementation:
  - flag set to `0` **after import** takes effect at the next routing decision
    → env is read live per decision, not cached at import time;
  - disabled + transient → `review`, state `failed`,
    reason `auto-requeue-disabled:timeout`, one `UNMETERED|attempt routed to review pile` cost row;
  - flag flipped back to `on` mid-process → transient requeues again;
  - disabled flag + publish-state job → `publish-excluded:timeout` (kill switch
    does not bypass the D1 exclusion);
  - empty string → on; backoffs attempt 1–4/10 → 60/120/240/480/900.

## Environment faults (classified, not product defects)
- pydantic 2.13.5 is installed globally while hermes-agent 0.15.2 requires
  2.13.4; the langsmith pytest plugin fails to autoload and breaks collection.
  All pytest runs used `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` (as the task brief
  instructed). This is a VM environment fault, not a product or test defect.

## Limits
- Verification is single-process sqlite on the Threadripper; multi-worker env
  propagation across separate OS processes follows normal environment semantics
  (not exercised here).
