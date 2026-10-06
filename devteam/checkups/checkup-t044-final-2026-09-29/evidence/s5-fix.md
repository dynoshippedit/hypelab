# S5 — Fixes applied

Two documentation fixes (no product behavior changes):

## FIX-01: test comment — audibility waiver recorded

File: tests/test_t044_deterministic.py (comment block above T044_AUDIO_TOL_AMP)

Before: "...flagged for his call; the transient is ~14 dB below local program
RMS (very likely inaudible) but the rule is his, not ours to waive."

After: "...Dino WAIVED this 2026-09-29 (accepted as inaudible); the transient
is ~14 dB below local program RMS."

Rationale: the flag is resolved; leaving "flagged for his call" would confuse
the next reader. Comment-only; zero behavior change.

## FIX-02: TASKS.md — stale claims corrected (append-only)

Appended "T-044 FINALIZATION 2026-09-29 ~17:30 EDT" entry:
- Records 5x gate results (5/5 green, 312 passed each, evidence path).
- Corrects "1 skipped" → 0 skipped (quarantined original deleted, deletion accepted).
- Corrects "5x did not fit time-box" → superseded (5x has been run).
- Records Dino's audibility waiver.
- Notes tree state (pin + 0.01 + un-quarantined test, uncommitted per constraints).

History preserved — earlier entries left intact, correction appended with timestamp.

## No product code changes

Both fixes are docs/comments. The pin, the tolerance, and the test logic are
unchanged from the S0-S8-reviewed state (checkup-t044-duck-2026-09-29).
