# S3 — Review matrix

Coverage: review units × lenses. Each cell records the check performed and result.

## ffmpeg-version-pin (hypelab/render.py) — COR, ARC, TST, DOC, REL

| Lens | Check | Result |
|---|---|---|
| COR | Read `_require_ffmpeg_version()`; version parse handles `ffmpeg version X` first line; OSError → RenderError | PASS |
| COR | Fault-injection: fake ffmpeg 7.9.9 → RenderError; real 8.1.2 → passes | PASS (proven both directions) |
| ARC | Pin placed after skip path (no subprocess on fast path); `derive()`/`gates.py` probe calls out of scope by design (audio-copy / measurement-only) | PASS with documented boundary |
| TST | check-pin-unit (gate): pin passes on 8.1.2 | PASS (receipt in checks/) |
| TST | Existing `test_render_missing_clip_gate` / `test_render_and_skip` green in 5x suite | PASS |
| DOC | Pin block comment cites experiment (450 renders, 6 hashes), tolerance rationale, fail-closed behavior | PASS |
| REL | Pin is startup-only (~10 ms `ffmpeg -version`); no per-render overhead; loud failure beats silent drift | PASS |

## t044-relaxed-assertion (tests/test_t044_deterministic.py) — COR, TST, DOC, ARC

| Lens | Check | Result |
|---|---|---|
| COR | `_assert_renders_equivalent`: video sha256 equality; audio length equality; max\|Δ\| ≤ 0.01 with dBFS in message | PASS |
| COR | Decode symmetry: both files through identical `f32le/stereo/48kHz` pipeline — no asymmetric resampling bias | PASS |
| TST | check-t044 (gate): single-file run green | PASS (receipt in checks/) |
| TST | 5x full-suite: crash test green in all 5 runs (312 passed each) | PASS |
| DOC | Tolerance comment cites measurement (-48.6 dBFS), margin math (8.6 dB), experiment outcome; waiver recorded (S5 fix) | PASS after S5 fix |
| ARC | Relaxed assertion matches Dino's decided fallback (video exact + audio tolerance); 0.01 = S0-S8-reviewed value | PASS |

## crash-recovery-unquarantine (test file + conftest.py) — COR, TST, DOC, ARC

| Lens | Check | Result |
|---|---|---|
| COR | Kill point deterministic (claim → rendering → ffmpeg temp writing); missed-kill and early-exit are explicit AssertionErrors | PASS |
| COR | Lease-expiry poll replaces blind sleep; re-reads live `lease_expires`; 120 s expiry deadline | PASS |
| COR | Atomic-output regression: no partial at final path after SIGKILL | PASS |
| TST | Test collected (not skipped) in default gate; green in 5x suite | PASS |
| DOC | Header comment documents criterion mapping vs quarantined version; TASKS.md un-quarantine entry | PASS after S5 correction |
| ARC | Recovery path exonerated (root cause = sidechaincompress, not recovery); quarantine machinery retained for future use | PASS |

## t044-documentation (ARCHITECTURE.md, devteam/TASKS.md) — DOC, COR, ARC, TST

| Lens | Check | Result |
|---|---|---|
| DOC | ARCHITECTURE.md T-044 section accurate (450 renders, flags-not-shipped, pin behavior) | PASS |
| DOC | TASKS.md: stale "1 skipped" and "5x did not fit time-box" corrected (S5) | PASS after S5 fix |
| COR | Doc claims verified against tree: 0.01 tolerance, pin present, zero quarantine markers, 5x log matches | PASS |
| ARC | S7 docs-vs-tree check: no other stale T-044 claims found | PASS |
| TST | n/a (docs) | — |

## Rejected leads

- R1 "pin should also cover derive()/gates.py": REJECTED — derive copies audio (immune by construction); gates are measurement-only. Pin scope matches the T-044 root cause.
- R2 "tighter 0.005 tolerance (sibling's)": REJECTED — 0.01 is the S0-S8-reviewed value with 8.6 dB margin vs 2.4 dB; Dino's settled decision; sibling's spec is stale (S9).
- R3 "re-litigate audibility waiver": REJECTED — Dino waived 2026-09-29; not ours to re-open.
