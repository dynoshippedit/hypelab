# S6 — Verification

## Gate checks (executed through checkup_gate.py; receipts in checks/)

- check-pin-unit (baseline + final): `_require_ffmpeg_version()` passes on installed 8.1.2; `FFMPEG_PINNED_VERSION == "8.1.2"`.
- check-t044 (baseline + final): `pytest tests/test_t044_deterministic.py -q` green (includes the un-quarantined crash-recovery test).
- check-full-suite (final): `pytest tests/ -q` green — full default gate with the crash test collected (not skipped).

## 5x gate (sibling-executed, independently verified)

devteam/checkups/t044-relax-2026-09-29/evidence/gate-5x.log inspected line by line:
5 runs, each "312 passed", exit=0, zero mismatches under the relaxed assertion.
Run durations: 223s / 248s / 237s / 225s / 206s. The crash-recovery test ran
(un-skipped) in every run — the suite count is 312 passed with no skips, and
collection was independently verified.

## Fault-injection (pin)

- Real ffmpeg 8.1.2 → pin passes.
- Fake ffmpeg reporting 7.9.9 → `RenderError` fail-closed with explicit message.
Proven in both directions (S4).

## Post-fix re-verification

FIX-01/FIX-02 are comment/doc-only. check-t044 and check-full-suite (final
phase) ran AFTER the fixes — green. No behavior to regress.

## Un-quarantine confirmation

- Zero `@pytest.mark.quarantine` markers on any test (grep).
- `test_worker_crash_recovery_sha256_deterministic` collected in default gate.
- Green in all 5 full-suite runs and in this checkup's final checks.
- The superseded quarantined original no longer exists (sibling deletion, accepted).
→ **Crash-recovery test is un-quarantined on the settled relaxed assertion.**
