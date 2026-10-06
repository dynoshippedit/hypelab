# S0 — Scope (checkup-t044-relax-2026-09-29, 2026-09-29)

## Review target
T-044-RELAX final state after chief conflict resolution (2026-09-29 ~17:05
EDT). The chief's T-044-RELAX brief initially specified tolerance 0.005 and a
full render.py revert; a sibling-coordinator conflict was resolved by the
chief in favor of the REVIEWED values from checkup-t044-duck-2026-09-29:
tolerance 0.01 with the ffmpeg version pin kept. Dino waived the audibility
question ("Ok" — 1.4 dB over his ~-50 dBFS rule accepted as inaudible).

## Files in scope and their final state
- hypelab/render.py — carries the experimental `FFMPEG_PINNED_VERSION="8.1.2"`
  + `_require_ffmpeg_version()` (fail-closed at render startup). The
  `-filter_threads 1` / `-filter_complex_threads 1` flags are NOT in the code
  (tried, proven ineffective, not shipped). This is the chief's decided state;
  the worker's interim full revert was overridden. Net product render behavior
  vs hl-cycle-13: unchanged outputs; only the version fail-closed guard added.
- tests/test_t044_deterministic.py — T-044 crash-recovery test with the
  relaxed assertion: decoded video (rawvideo/yuv420p) SHA-256 bit-identical;
  decoded audio (f32le/stereo/48k) max |Δ| <= 0.01 amplitude (~8.6 dB margin
  over the measured peak -48.6 dBFS). No quarantine marker; runs in the
  default gate. This is the chief's reviewed value (checkup-t044-duck).
- tests/test_cli.py — WORKER CHANGE: the quarantined
  `test_worker_crash_recovery_sha256` (byte-exact SHA-256 assertion + old
  flaky harness: blind sleep(12), racy kill point) DELETED (89 lines). It was
  superseded by the candidate above, which implements the chief's tracked
  un-quarantine criteria (deterministic kill point, poll-until-lease-expired).
  Shared helpers (`_cli_subprocess`, `_db_state`) and `util_mod` import
  retained. No quarantine marker remains on any test.

## Explicitly out of scope
- Replacing sidechaincompress itself (product audio behavior; needs Dino).
- The HYPELAB_AUTO_REQUEUE flag work (separate task, same branch).
- Contracts/audits, publishing, any other HypeLab subsystem.

## Reviewer mode
SELF_REVIEW (worker == reviewer). Flagged honestly in the verdict.
