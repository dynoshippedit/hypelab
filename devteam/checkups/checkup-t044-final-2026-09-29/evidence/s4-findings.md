# S4 — Findings

## FIND-01 (fixed in S5): stale audibility comment in test file

tests/test_t044_deterministic.py said the -48.6 dBFS vs ~-50 dBFS exceedance was
"flagged for his call ... not ours to waive." Dino waived it 2026-09-29
("Ok now run it again" — accepted as inaudible). Comment updated to record the
waiver. Comment-only change; zero behavior impact.

## FIND-02 (fixed in S5): stale TASKS.md claims

devteam/TASKS.md line 314 (UN-QUARANTINED entry) said "312 passed / 1 skipped
(the skip is the quarantined original)" and "5x full-suite gate did not fit the
experiment time-box." Both stale: the sibling deleted the quarantined original
(deletion accepted as convergent) so the gate runs 312 passed / 0 skipped, and
the 5x gate has now been run (5/5 green). Correction appended to TASKS.md
(append-only; history preserved).

## FIND-03 (observation, not a defect): pin scope

`_require_ffmpeg_version()` guards `render()` only. `derive()` (audio-copy) and
`gates.py` probes are unpinned by design — neither can be affected by the
sidechaincompress nondeterminism this pin exists for. Documented in S2; no
action.

## FIND-04 (verified clean): no quarantine markers remain

Zero `@pytest.mark.quarantine` markers on any test (grep verified). The
conftest machinery is retained. The crash-recovery test is collected and runs
in the default gate.

## FIND-05 (verified clean): experimental flags fully reverted

No `-filter_threads` / `-filter_complex_threads` anywhere in hypelab/ (grep
verified). The failed experiment left no residue in product code.

## Rejected leads

- R1 "pin should cover derive()/gates.py": rejected — out of scope by design (see FIND-03).
- R2 "adopt sibling's 0.005 tolerance": rejected — stale spec, contradicts Dino's settled 0.01 decision and the S0-S8-reviewed state.
- R3 "re-litigate the audibility waiver": rejected — Dino decided; recorded.
