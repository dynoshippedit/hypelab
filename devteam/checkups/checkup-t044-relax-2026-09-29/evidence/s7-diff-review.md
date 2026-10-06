# S7 — Diff review (checkup-t044-relax-2026-09-29, 2026-09-29)

## Working tree diff vs HEAD 8effd32 (final state)
- `tests/test_cli.py` — 89 deletions: only the quarantined
  `test_worker_crash_recovery_sha256` (decorator + body). Verified: no other
  function touched; `_cli_subprocess`, `_db_state`, `test_work_once_claims_
  single_job`, and the `util_mod` import all retained and still referenced.
  `grep -rn "pytest.mark.quarantine" tests/` finds no test markers (only
  conftest.py documentation comments).
- `hypelab/render.py` — 43 insertions (chief's pin): `FFMPEG_PINNED_VERSION`,
  `_require_ffmpeg_version()`, call site in `render()`. No flag changes;
  `grep '"-filter_threads"' hypelab/render.py` finds nothing. Audio chain
  untouched.
- `tests/test_t044_deterministic.py` — untracked (chief's candidate):
  tolerance 0.01, comment cites the -48.6 dBFS measurement.
- Other modified files (ARCHITECTURE.md, devteam/TASKS.md,
  hypelab/retry.py, tests/test_failure_requeue.py) belong to other accepted
  tasks (HL-FLAG, TASKS bookkeeping) — not this review; noted for scope
  hygiene.

## Docs-vs-tree check (per 2026-09-29 steering)
- devteam/TASKS.md T-044 entry describes the candidate as the un-quarantined
  test and the original as "superseded" — matches the tree (original
  deleted, candidate active).
- The candidate's tolerance comment (0.01, -48.6 dBFS) matches the measured
  evidence cited.
- No stale references to the deleted test found in docs (`grep -rn
  "test_worker_crash_recovery_sha256" --include="*.md"` → only historical
  TASKS.md entries, which correctly describe it as quarantined/superseded).
