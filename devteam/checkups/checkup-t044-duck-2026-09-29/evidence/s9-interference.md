# S9 — Sibling intervention (recorded 2026-09-29 ~17:05 EDT, after S0-S8)

During the final gate check (check-full-suite, ~16:59-17:00 EDT) a sibling
coordinator concurrently working in /home/dino/hypelab modified the review
tree. mtimes: tests/test_cli.py 16:59:25, tests/test_t044_deterministic.py
16:59:36, hypelab/render.py 17:00:06 (all EDT).

## What the sibling changed
1. tests/test_cli.py: DELETED the quarantined original
   test_worker_crash_recovery_sha256 (89 lines, marker included). Convergent
   with un-quarantine; the deterministic candidate is now the sole
   crash-recovery test and the conftest quarantine mechanism has no marked
   crash-recovery test left.
2. tests/test_t044_deterministic.py: REPLACED the tolerance block with its own
   "T-044-DET" experiment: tolerance 0.005 amplitude (-46 dBFS), described as
   "2x measured peak 0.003791"; claims "420 full renders -> 39 mismatches
   (9.3%) even single-threaded". Test structure (helpers, video-exact
   assertion) is otherwise identical to this review's version.
3. hypelab/render.py: REVERTED to pre-experiment state, removing the ffmpeg
   version pin. The pin was re-applied per the task instruction afterward and
   is byte-identical to the snapshotted state (verified against initial.json).

## Resulting tree (hybrid)
- render.py: this task's pin (present, verified).
- test_t044_deterministic.py: sibling's version (tolerance 0.005).
- test_cli.py: sibling's deletion (quarantined original gone).

## Verification of both configurations
- WITH pin + this task's test (0.01): full default-gate suite 312 passed,
  1 skipped, 10:47 (standalone run, pre-intervention).
- WITHOUT pin + sibling's test (0.005): full default-gate suite 312 passed,
  1 skipped, 4:07 (gate check-full-suite receipt; note: the gate flagged
  source_before != source_after because the revert landed mid-run — the suite
  result itself is valid).
- The gate's baseline/final receipts for check-pipeline-tests and check-t044
  were recorded against this task's tree (digests stable, exit 0).

## Open conflicts for the chief (NOT adjudicated here)
- Tolerance: 0.01 (-40 dBFS, ~8.6 dB margin over measured max) vs 0.005
  (-46 dBFS, ~2.4 dB margin). A nondeterminism tolerance wants margin against
  unseen variants; 2.4 dB is thin.
- Pin vs no pin: this task's instruction requires the pin; the sibling
  reverted it as experiment residue.
- Audibility: this task measured peak -48.6 dBFS, which EXCEEDS Dino's ~-50
  dBFS "user-facing bug" rule of thumb (flagged in the report); the sibling's
  comment asserts "inaudible -- not a user-facing bug" (citing -41.2 dB below
  the concurrent music tail, a different metric).
- The sibling's "420 full renders / 9.3%" numbers vs this task's "450
  audio-chain renders / 6 variants both arms": different methodologies and
  metrics; both agree single-threading does not fix it.

## RESOLUTION (2026-09-29 ~17:05 EDT, per coordinator / Dino)
- The sibling-coordinator conflict was adjudicated: the reviewed 0.01
  amplitude (-40 dBFS) tolerance was RESTORED over the tighter 0.005.
  Current tests/test_t044_deterministic.py carries the reviewed version
  (tolerance 0.01, experiment comment citing 450 renders / 6 variants).
- DINO WAIVED the audibility flag ("Ok", ~17:05 EDT): the measured peak
  -48.6 dBFS exceeds his ~-50 dBFS rule of thumb by ~1.4 dB, but he accepts
  it as inaudible; proceed with the relaxed assertion. NOT a user-facing bug
  per his call.
- The ffmpeg 8.1.2 pin in hypelab/render.py stands (re-applied, verified
  byte-identical to the reviewed snapshot).
- The quarantined original test_worker_crash_recovery_sha256 remains DELETED
  from tests/test_cli.py by the sibling (convergent with un-quarantine); the
  deterministic candidate is the sole crash-recovery test.
- Final gate checks are being re-run against this resolved tree; receipts
  will be refreshed so validate() sees a stable source.
