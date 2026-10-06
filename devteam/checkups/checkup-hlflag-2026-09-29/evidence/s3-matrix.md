# S3 — engineering matrix (checkup-hlflag-2026-09-29)

## kill-switch-impl (hypelab/retry.py)
- **COR**: `auto_requeue_enabled()` (lines 46–48) normalizes with
  `.strip().lower()` and matches the owner's four false-like spellings;
  unset defaults to `"1"` (on), empty string → on (live-verified). The gate sits
  inside the transient branch (lines 252–256) AFTER the publish/owner-waiting
  exclusions, so the flag cannot enable a retry the D1 exclusions forbid.
  Disabled path produces reason `auto-requeue-disabled:<detail>` — matches the
  required format (live: `auto-requeue-disabled:timeout`). REVIEWED.
- **ARC**: Single decision point, no duplicated policy; `handle_failure` is the
  only router and `_requeue` has no other caller (grep-verified). The drive path
  (`jobs.py`) uses only `classify_failure` for labeling and never requeues —
  no second auto-retry mechanism exists to bypass the flag. REVIEWED.
- **TST**: Behavior is asserted by 7 new tests (routing outcome, state,
  reason prefix, spellings both directions, default-on) plus the live-behavior
  script; fault-relevant branches (publish exclusion under disabled flag) are
  exercised against a real DB. REVIEWED.
- **DOC**: Module docstring (lines 18–20) and comment (lines 42–45) state the
  flag, values, default, and no-restart flip. Names (`auto_requeue_enabled`,
  `auto-requeue-disabled:`) match behavior. REVIEWED.
- **REL**: Live env read per routing decision; flipping the var mid-process
  changes the next decision (verified). No stale-cache failure mode. Failed
  routing (`_to_review`) preserves the same atomicity as before the change.
  REVIEWED.
- **DAT**: Both `_requeue` and `_to_review` commit state+audit+cost in one
  explicit transaction; the disabled path uses the identical `_to_review`
  transaction, so no partial-row risk is introduced. REVIEWED.

## kill-switch-tests (tests/test_failure_requeue.py)
- **COR**: Tests assert outcomes (routing outcome, DB state, reason prefix,
  boolean predicate), not implementation internals; parametrized spellings
  include whitespace/case variants (`" Off "`, `"FALSE"`). REVIEWED.
- **ARC**: New tests sit in the existing fixture style (`env`, `_claim_pipeline_job`);
  no new harness layering. REVIEWED.
- **TST**: 7 new tests target exactly the new branch; the disabled case asserts
  the review reason prefix and failed state (would fail if the flag were ignored
  — the flag-off path is the only route to that reason string). Test would fail
  on the pre-change code for `test_auto_requeue_kill_switch_sends_transient_to_review`
  (no `auto-requeue-disabled:` reason exists pre-change). REVIEWED.
- **DOC**: Test names and docstrings state the owner-visible behavior plainly.
  REVIEWED.

## work-loop-caller (hypelab/cli.py)
- **COR**: Work loop calls `handle_failure` once per handler exception and logs
  the outcome; `ValueError` (unknown job / lost race) is caught and treated as
  skip — unchanged by this change. REVIEWED.
- **ARC**: The work loop is the single integration boundary; the flag needs no
  plumbing through the CLI because the read happens inside the router.
  REVIEWED.
- **TST**: CLI-level drive-fail tests (21/21 with atomicity) exercise the
  adjacent failure paths; no new CLI test needed since routing is fully covered
  at the `handle_failure` level. REVIEWED.
- **DOC**: The inline comment (lines 977–979) describes transient requeue with
  backoff/max-3/cost-logged — still accurate under the flag (default on).
  REVIEWED.

No NOT_APPLICABLE cells among the declared unit/lens pairs.
