# S5 — Fix (checkup-t044-relax-2026-09-29, 2026-09-29)

## Worker change
**tests/test_cli.py**: deleted the quarantined `test_worker_crash_recovery_sha256`
(89 lines: the `@pytest.mark.quarantine` decorator + full function body). The
test was superseded on two independent grounds:
1. Its byte-exact SHA-256 assertion is incompatible with the product's own
   audio chain (ffmpeg 8.1.2 `sidechaincompress` nondeterminism — proven by
   EVIDENCE_SUMMARY.md and T044_DET_RESULTS.md, not a recovery-path defect).
2. Its harness is the known-flaky one (blind `sleep(12)`, kill point fires
   on observing `rendering` before ffmpeg spawns).

The replacement `tests/test_t044_deterministic.py::
test_worker_crash_recovery_sha256_deterministic` (chief's candidate, not
worker-written) carries the relaxed assertion (video bytes bit-identical,
audio max |Δ| <= 0.01) and the fixed harness (deterministic kill point:
SIGKILL only after the PID-unique ffmpeg temp exists with size > 0 while DB
reads `rendering`; poll-until-lease-expired replaces the blind sleep).

## Chief decisions (not worker changes; recorded for completeness)
- hypelab/render.py keeps the `FFMPEG_PINNED_VERSION="8.1.2"` fail-closed
  guard (chief conflict resolution ~17:02 EDT, overriding the worker's
  interim full revert). Single-thread flags never shipped.
- Candidate audio tolerance stays 0.01 (chief conflict resolution ~17:02
  EDT, overriding the worker's interim 0.005). Dino waived the ~-50 dBFS
  audibility rule for the 25 ms tail transient (~17:05 EDT, "Ok").

## What was NOT changed
- No product render logic (audio_chain, build_command, queue, CLI).
- The conftest quarantine mechanism itself.
