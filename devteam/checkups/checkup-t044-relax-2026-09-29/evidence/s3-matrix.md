# S3 — Test matrix (checkup-t044-relax-2026-09-29, 2026-09-29)

| Check | Phase | What it proves |
|---|---|---|
| check-pipeline-baseline | baseline | tests/test_pipeline.py green against render.py at HEAD (pre-experiment state) |
| check-t044 | final | T-044 candidate passes standalone with 0.005 tolerance |
| check-full-suite | final | default-gate full suite green (no quarantined skips remain) |
| check-render-revert | final | `git diff HEAD -- hypelab/render.py` empty — revert confirmed |
| 5x full-suite gate | final (task) | 5 consecutive green full-suite runs (the tracked T-044 un-quarantine criterion); log at evidence/gate-5x.log |

## Not run / not applicable
- `--run-quarantined` suite: no quarantined tests remain, so the flag selects
  nothing. The conftest mechanism itself is unchanged and untested here
  (out of scope; it was verified in hl-cycle-13).
- Mutation/fault-injection on the new tolerance: the 420-render DET dataset
  already bounds the tolerance empirically (max 0.003791 < 0.005 for all
  renders); a synthetic fault-injection run was not repeated.
