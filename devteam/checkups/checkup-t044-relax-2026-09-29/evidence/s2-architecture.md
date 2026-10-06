# S2 — Architecture (checkup-t044-relax-2026-09-29, 2026-09-29)

## Final state composition
The T-044-RELAX outcome is a composite of chief decisions and one worker edit:

1. **render.py: version pin kept (chief decision).** `FFMPEG_PINNED_VERSION`
   + `_require_ffmpeg_version()` fail-closed at render startup. The worker's
   interim `git checkout HEAD -- hypelab/render.py` was overridden by the
   chief's conflict resolution, which restored the pin. Rationale (chief):
   the pin was reviewed and accepted in checkup-t044-duck-2026-09-29; it
   guards against silent ffmpeg-version drift. The single-thread flags were
   never shipped (proven ineffective by the 420-render experiment).

2. **Candidate tolerance 0.01 (chief decision).** The worker's interim change
   to 0.005 was overridden; the chief restored the reviewed 0.01 value
   (~8.6 dB margin over the measured -48.6 dBFS peak). Dino waived his
   ~-50 dBFS "user-facing bug" rule for this 25 ms tail transient ("Ok").

3. **Quarantined original deleted (WORKER CHANGE).** `test_cli.py` lines
   318-406 removed: the `@pytest.mark.quarantine` decorator and the entire
   `test_worker_crash_recovery_sha256` function. The test was superseded —
   its byte-exact assertion is incompatible with the product's own audio
   chain (proven), and its harness is the known-flaky one. The candidate in
   tests/test_t044_deterministic.py is now the sole T-044 crash-recovery test.

## Interfaces / contracts
- No CLI, DB schema, or render-output contract changes.
- The quarantine mechanism (tests/conftest.py `--run-quarantined`) is
  untouched; no tests carry the marker anymore.
