# S1 — Baseline (checkup-t044-relax-2026-09-29, 2026-09-29)

## Starting source identity
- Repo: /home/dino/hypelab, branch devteam/review-2026-09-29, HEAD 8effd32
  ("controller: hl-cycle-13 VERIFIED (T-043 cost labels + T-044 quarantine)").

## What changed during this task
1. Worker reverted hypelab/render.py to HEAD (removed experimental pin) —
   then the CHIEF restored the pin (conflict resolution ~17:02 EDT). Final:
   pin present, flags absent.
2. Worker changed candidate tolerance 0.01 -> 0.005 — then the CHIEF
   restored 0.01 (conflict resolution ~17:02 EDT). Final: 0.01.
3. Worker DELETED the quarantined `test_worker_crash_recovery_sha256` from
   tests/test_cli.py (89 lines) — stands; not reverted.

## Baseline check
- check-pipeline-baseline: `tests/test_pipeline.py` (render-module tests).
  render.py's audio_chain and build_command are unchanged vs HEAD apart from
  the additive version-pin guard; this check documents the render module's
  health. Receipt in checks/baseline/.

## Prior evidence this change builds on
- ~/workspace/t044-mismatch/EVIDENCE_SUMMARY.md — sidechaincompress proven
  the nondeterminism source; recovery path exonerated.
- ~/workspace/t044-mismatch/T044_DET_RESULTS.md — 420 renders, 39 mismatches
  (9.3%) single-threaded; peak |Δ| = 0.003791; -41.2 dB below music tail.
- checkup-t044-duck-2026-09-29 (S0-S8 PASS, SELF_REVIEW) — accepted pin +
  0.01 tolerance; deferred the real 5x full-suite gate. This checkup performs
  that gate against the chief's final state.
- Dino 2026-09-29 ~17:05 EDT: waived the ~-50 dBFS audibility rule for the
  25 ms tail transient ("Ok"); proceed with relaxed assertion.
