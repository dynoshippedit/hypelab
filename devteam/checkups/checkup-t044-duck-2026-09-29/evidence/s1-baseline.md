# S1 — Baseline

Pre-change state (hl-cycle-13 controller acceptance, commit 8effd32):
- Full default-gate suite green (the T-044 candidate was added in T-044 work
  and passed solo 5/5 after harness repair).
- tests/test_pipeline.py: 15/15 (includes test_build_command_sidechain,
  test_render_missing_clip_gate, test_render_and_skip).
- T-044 incident evidence (~/workspace/t044-mismatch/EVIDENCE_SUMMARY.md):
  byte-exact sha256 assertion failed ~2.5%/render; root cause proven to be
  ffmpeg 8.1.2 sidechaincompress nondeterminism (audio tail only, ~25 ms),
  NOT the crash-recovery path.

No pre-change checkup checks were re-run (change already applied when this
review started); baseline_required checks below re-verify the two fast
suites against the final tree, and the pre-change suite state is attested
by the hl-cycle-13 controller acceptance above.
