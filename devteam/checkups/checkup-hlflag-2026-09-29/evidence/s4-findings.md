# S4 — challenged findings (checkup-hlflag-2026-09-29)

## FIND-01 — SUPPORTED_IMPROVEMENT (QUEUED)
**Claim:** ARCHITECTURE.md's retry section does not mention the
HYPELAB_AUTO_REQUEUE kill switch, so an operator reading the architecture doc
would not learn the flag exists.
**Location:** ARCHITECTURE.md lines 91–94 (Retry section); contrast
hypelab/retry.py lines 18–20, 42–45 (documented in module).
**Expected:** Docs describing failure routing mention the owner-facing control.
**Observed:** ARCHITECTURE.md describes generic retry/backoff without the flag.
No false claim is made — this is a docs gap, not a behavior defect.
**Counter-check:** grepped all *.md for AUTO_REQUEUE — only the module
docstring/comments and checkup notes mention it.
**Action:** add one line to ARCHITECTURE.md Retry section naming the flag,
values, default-on. Acceptance: `grep -n HYPELAB_AUTO_REQUEUE ARCHITECTURE.md`
non-empty.
**Resolution:** QUEUED — docs-only edit; task assignment is the chief's call.
No queue task ID exists yet; do not invent one.

## REJECTED_LEAD-01 — "drive path bypasses the flag"
**Lead:** `hypelab/jobs.py` drive-failure handling uses `classify_failure` and
never consults `auto_requeue_enabled()`.
**Counter-evidence:** jobs.py:187 comment and code — direct drives NEVER
auto-requeue ("the operator is present"); the path always lands in the review
pile with a `drive:<kind>:<detail>` reason. There is no auto-retry to disable,
so the flag's semantics are preserved. Not a bypass. REJECTED.

## REJECTED_LEAD-02 — "unrecognized values (e.g. 'banana') enable requeue"
**Lead:** Only the four false-like spellings disable; anything else → on.
**Counter-evidence:** This is exactly the specified behavior: default ON,
opt-out via 0/false/no/off. Fail-safe direction matches the owner's decision
(auto-retry is the verified, previously-accepted behavior). REJECTED.

## REJECTED_LEAD-03 — "flag read per call could race mid-batch"
**Lead:** Env flip between two failures in the same worker run changes routing.
**Counter-evidence:** That is the documented requirement ("flip it with no code
change and no restart"); each failure is routed independently, no shared state
carries across decisions. REJECTED.

**Result: 0 CONFIRMED_DEFECT, 1 SUPPORTED_IMPROVEMENT (docs, queued),
3 REJECTED_LEADs with traced counter-evidence.**
