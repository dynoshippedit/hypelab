# S6 — final verification (post-fix source)

Final checks executed on the FIXED source via the gate `run-check`
recorder; receipts in checks/final/.

## check-new-regression
- 9/9 passed, exit 0. Receipt: checks/final/check-new-regression.json.

## check-full-suite
- 324/324 passed (315 pre-existing incl. the T-044 deterministic test +
  9 new), exit 0. Receipt: checks/final/check-full-suite.json.
- T-044 settlement: test_t044_deterministic.py passed (1/1) — settlement
  intact, not re-litigated. The 315/315 baseline holds; the only delta is
  the +9 new regression tests.

Source identity: final receipts bind source_before == source_after ==
current source digest (fixed source). Baseline receipts bind to the
initial (pre-fix) digest. Both recorded in the receipts.
