# S0 — Scope

**Review ID:** checkup-t044-final-2026-09-29
**Project:** /home/dino/hypelab (branch devteam/review-2026-09-29, uncommitted)
**Date:** 2026-09-29
**Reviewer mode:** SELF_REVIEW (chief-engineer finalization run; no independent reviewer dispatched — noted as a limitation)

## What this checkup reviews

The FINAL T-044 state after Dino's 2026-09-29 decisions:
1. Deterministic-ducking experiment FAILED (450 renders → 6 distinct PCM hashes with and without single-threading; flags not shipped) — reviewed under checkup-t044-duck-2026-09-29, not re-litigated here.
2. **ffmpeg 8.1.2 version pin** with fail-closed `_require_ffmpeg_version()` in hypelab/render.py (uncommitted).
3. **Relaxed T-044 assertion**: video bytes bit-identical + audio within 0.01 amplitude (-40 dBFS), ~8.6 dB margin over measured peak -48.6 dBFS, in tests/test_t044_deterministic.py (uncommitted).
4. **Un-quarantined crash-recovery test** `test_worker_crash_recovery_sha256_deterministic` — carries NO quarantine marker, runs in the default gate; the superseded quarantined original was deleted from tests/test_cli.py (accepted as convergent).
5. **Documentation**: ARCHITECTURE.md T-044 section, devteam/TASKS.md entries.
6. Dino WAIVED the audio-tail audibility flag (-48.6 dBFS vs ~-50 dBFS rule) — accepted as inaudible, not re-litigated.

## Out of scope

- The deterministic-ducking experiment itself (already checkup'd).
- The sibling coordinator's stale checkup-t044-relax-2026-09-29 (spec describes 0.005 tolerance / reverted pin — NOT the tree; documented in S9).
- Product behavior changes: none. All changes are test-harness + a fail-closed startup guard + docs.
- In The Red (read-only, playtest live).

## Review units

| Unit | Paths | Lenses |
|---|---|---|
| ffmpeg-version-pin | hypelab/render.py | COR, ARC, TST, DOC, REL |
| t044-relaxed-assertion | tests/test_t044_deterministic.py | COR, TST, DOC, ARC |
| crash-recovery-unquarantine | tests/test_t044_deterministic.py, tests/conftest.py | COR, TST, DOC, ARC |
| t044-documentation | ARCHITECTURE.md, devteam/TASKS.md | DOC, COR, ARC, TST |
