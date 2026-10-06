# S7 — Diff review (docs-vs-tree)

Per the 2026-09-29 S7 rule addition: explicit docs-vs-tree check.

## Claims checked

| Doc claim | Tree truth | Status |
|---|---|---|
| ARCHITECTURE.md: "450 renders → 6 hashes with/without flags, flags not shipped" | No filter_threads in hypelab/ (grep) | MATCH |
| ARCHITECTURE.md: "render() fails loudly if ffmpeg ≠ 8.1.2" | `_require_ffmpeg_version()` at render():501; fault-injection proven | MATCH |
| ARCHITECTURE.md: "video bytes bit-identical; audio within -40 dBFS" | Test asserts sha256 video equality + 0.01 audio tolerance | MATCH |
| Test comment: "measured peak -48.6 dBFS" | Matches T044_DET_RESULTS evidence | MATCH |
| Test comment (after S5): "Dino WAIVED 2026-09-29" | Memory + task brief confirm waiver | MATCH |
| TASKS.md (after S5): "312 passed / 0 skipped" | 5x log: 312 passed, no skips; zero quarantine markers | MATCH |
| TASKS.md: "quarantined original deleted, deletion accepted" | test_cli.py has no crash-recovery test (grep) | MATCH |
| TASKS.md chief-resolution: "0.01 restored over 0.005" | Test file: T044_AUDIO_TOL_AMP = 0.01 | MATCH |

## Stale items found and fixed

- FIND-01, FIND-02 (see S4/S5). No other stale T-044 claims found in ARCHITECTURE.md, TASKS.md, or the test file.

## Uncommitted state

All T-044 changes remain uncommitted per constraints (git status: M render.py, M ARCHITECTURE.md, M TASKS.md, ?? test_t044_deterministic.py, ?? devteam/checkups/). No commit, no merge, no push performed by this checkup.
