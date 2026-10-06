# S1 — Baseline

Tree state as found 2026-09-29 ~17:30 EDT (before this checkup's snapshot):

## Files under review

- `hypelab/render.py` — MODIFIED (uncommitted): ffmpeg 8.1.2 pin block (lines 28-39), `_require_ffmpeg_version()` (lines 326-347), call site at line 501 inside `render()` after the slots gate and render-hash skip path. Experimental `-filter_threads` flags NOT present (reverted).
- `tests/test_t044_deterministic.py` — UNTRACKED (new file, 247 lines): `T044_AUDIO_TOL_AMP = 0.01`, `T044_AUDIO_TOL_DBFS = -40.0`; `_assert_renders_equivalent` (video sha256-identical, audio max|Δ| ≤ 0.01); `test_worker_crash_recovery_sha256_deterministic` with NO quarantine marker.
- `tests/conftest.py` — quarantine machinery present (`@pytest.mark.quarantine` → skipped in default gate); zero tests currently carry the marker (verified by grep).
- `ARCHITECTURE.md` — MODIFIED (uncommitted): T-044 ffmpeg-pin section (lines ~393-401), accurate.
- `devteam/TASKS.md` — MODIFIED (uncommitted): T-044 quarantine/un-quarantine/chief-resolution entries; line 314 contained stale "1 skipped" and "5x did not fit time-box" (corrected in S5).

## Baseline behavior (pre-existing evidence, independently verified by this checkup)

- 5x full-suite gate: 5/5 GREEN, 312 passed each, 0 failed, 0 skipped — runs 223s / 248s / 237s / 225s / 206s. Evidence: devteam/checkups/t044-relax-2026-09-29/evidence/gate-5x.log (executed by sibling coordinator 2026-09-29 17:05-17:25 EDT; log inspected line-by-line by this reviewer, exit=0 on all 5 runs).
- Crash-recovery test collected (not skipped) in the default gate: `pytest --collect-only` → 1 test collected.
- Pin fault-injection (this checkup, S4): real ffmpeg 8.1.2 → `_require_ffmpeg_version()` passes; fake `ffmpeg` reporting 7.9.9 earlier in PATH → `RenderError` fail-closed with clear message.

## Environment

- Threadripper, ffmpeg 8.1.2 (matches pin), python3, pytest.
- pydantic 2.13.4 (PYDANTIC task done); `PYTEST_DISABLE_PLUGIN_AUTOLOAD` workaround no longer needed — this checkup runs WITHOUT it.
