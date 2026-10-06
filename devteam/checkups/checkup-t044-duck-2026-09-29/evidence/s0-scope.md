# S0 — Scope (checkup-t044-duck-2026-09-29, 2026-09-29)

## Review target
T-044 ducking determinism experiment outcome, per Dino's time-boxed decision
("try deterministic first; if mismatches remain, relax the assertion").

## Files in scope
- hypelab/render.py — ffmpeg version pin (FFMPEG_PINNED_VERSION=8.1.2,
  _require_ffmpeg_version() called in render() after the skip check, before
  the ffmpeg subprocess); single-thread flags tried and REMOVED (ineffective).
- tests/test_t044_deterministic.py — byte-exact sha256 assertion replaced by
  _assert_renders_equivalent: video decoded rawvideo must be bit-identical;
  audio decoded f32le must differ by <= 0.01 amplitude (-40 dBFS), with a code
  comment citing the measured max (-48.6 dBFS).
- ARCHITECTURE.md — one paragraph documenting the pin + experiment outcome.

## Explicitly out of scope
- The quarantined original test_cli.py::test_worker_crash_recovery_sha256
  (stays quarantined; superseded by the deterministic candidate, which runs
  in the default gate).
- Replacing sidechaincompress itself (product audio behavior; needs Dino).
- Contracts/audits, publishing, any other HypeLab subsystem.

## Reviewer mode
SELF_REVIEW (worker == reviewer). Flagged honestly in the verdict.
