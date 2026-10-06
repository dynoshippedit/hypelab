# S6 — Verify (real receipts)

- Pin: _require_ffmpeg_version() passes on real ffmpeg 8.1.2; fault-injected
  "ffmpeg version 7.0.0" -> RenderError naming the mismatch; unparsable
  first line -> RenderError (fail closed). All three observed, not assumed.
- Relaxed assertion on the REAL T-044 incident pair
  (ref ff287add… vs crash 64124f64… from the 2026-09-29 incident):
  _assert_renders_equivalent PASSES; measured max|Δ| = 0.003791 (-48.4 dBFS)
  < tolerance 0.01 (-40 dBFS); video rawvideo sha256 equal.
- Discrimination: same pair against a deliberately tight tolerance 0.001 is
  REJECTED, so the audio comparison engages and is not vacuous.
- tests/test_pipeline.py: 15/15 green (pin placement does not disturb the
  mocked-subprocess gates).
- tests/test_t044_deterministic.py: 1 passed in 65.44s in the DEFAULT gate
  (not skipped; -rs shows no skip) — the crash-recovery test is re-enabled.

## Addendum — final checks re-run 2026-09-29 ~17:10-17:20 EDT
After the sibling intervention was resolved (0.01 tolerance restored, pin
standing, Dino waived the audibility flag), all three final gate checks were
re-run against the resolved tree (source 0f0aed819720, stable before/after
every check):
- check-pipeline-tests: 15 passed in 2.26s, exit 0
- check-t044: 1 passed in 64.24s, exit 0
- check-full-suite: 312 passed, 3 warnings in 247.17s, exit 0
Gate validate: PASS through S8, 0 outstanding findings.
