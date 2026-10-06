# S4 — Findings (checkup-t044-relax-2026-09-29, 2026-09-29)

## FIND-01 (info): worker brief superseded mid-task by chief resolution
The T-044-RELAX brief specified tolerance 0.005 and a full render.py revert.
During execution the chief resolved a sibling-coordinator conflict in favor
of the reviewed values (0.01 tolerance, pin kept) and Dino waived the
audibility question. The worker's interim edits to those two files were
overridden on disk; the worker's surviving change is the test_cli.py
deletion. The 5x gate was restarted clean against the chief's final state
after the worker stopped the mixed-tolerance run. No action required; this
is recorded so the chief can see exactly what the brief said vs what shipped.

## FIND-02 (info): quarantined-test deletion is the un-quarantine
"Remove the quarantine marker" was implemented by deleting the superseded
test rather than un-marking it, because un-marking would have put the known-
flaky harness (blind sleep, racy kill point) back into the default gate and
run two ~70s kill-9 tests per suite. The chief's TASKS.md record already
called the original "superseded". Reversible via git (uncommitted deletion).

## Rejected leads
- Keeping the original quarantined alongside the candidate: rejected —
  dead quarantined code for a superseded test adds confusion, not safety.
- Re-applying the 0.005 tolerance: rejected — chief explicitly restored
  0.01 as the reviewed value; not the worker's call to re-litigate.

## Outstanding findings
None. Both findings above are informational; neither blocks the verdict.
