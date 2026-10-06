# S5 — writer implementation evidence (repair engineer)

## Reproduction / before-state

Traced the reported locations at master@5c185ba:

- `hypelab/cli.py:711-724`: heartbeat thread breaks on lease loss without
  aborting the render — CONFIRMED present (retained per chief direction).
- `hypelab/render.py:380-397` (`build_command`): the reviewer's "no temp
  file, no atomic rename" sub-claim is STALE. `render()` (render.py:483-522)
  substitutes a PID-unique temp path before calling `build_command`, so the
  `-y` clobber applies only to `{slug}.partial-<pid>.mp4`; the final path
  is committed solely by `os.replace(tmp, out)` after ffprobe validation.
  Present since commit 81aaf52. Verified: (1) full read of render();
  (2) grep shows `build_command` has exactly one production caller
  (render.py:487, passing tmp); (3) the T-044 crash test already references
  the `9x16.partial-<worker-pid>.mp4` temp file.
- The actual gap: NO test covered the two-worker/lease-loss path (T-044
  covers single-worker SIGKILL only). That is what this repair adds.

## Change (test-only; no product-code modification)

New file `tests/test_fhl1_lease_loss.py` (3 tests, ~200 lines):

1. `test_concurrent_workers_no_partial_final_output` — two forked worker
   processes (separate PIDs, like production workers) render the same job
   concurrently against the same work dir and final path. Asserts both
   succeed, the final file decodes, its video bytes are sha256-identical
   to a single reference render (T-044 determinism), and no `.partial-*`
   files remain.
2. `test_killed_worker_leaves_final_output_intact` — subprocess.run shim
   performs a torn write to the ffmpeg target (the temp file) then raises
   TimeoutExpired (kill simulation). Asserts the pre-existing final output
   is byte-identical afterwards and the temp file exists.
3. `test_ffmpeg_never_targets_final_path` — captures the real ffmpeg argv
   from render() (shim delegates ffprobe/version-pin to the real runner,
   stands in a tiny valid mp4 for the encode). Asserts the target is a
   `.partial-<pid>` sibling of `out`, never `out` itself, and `-y` is
   retained (temp-file reuse on PID recycle).

## Falsification (negative control)

Temporarily forced the broken implementation (`tmp = out` in render(),
i.e. ffmpeg `-y` straight onto the shared path — the pre-fix behavior the
finding described), ran the 3 tests: ALL 3 FAILED. Reverted immediately;
`git diff` confirms render.py untouched. This proves the tests pin the
invariant and would catch a regression to direct writes.

## Callers / related instances swept

- All `-y` ffmpeg invocations in hypelab/: carousel.py, cut.py, ingest.py,
  reframe.py, tray.py target asset-processing temps/outputs, not the shared
  job output; render.py:384 targets the PID-unique temp; render.py:604
  (derive preview) targets its own temp + os.replace. No other writer to
  `work/out/{slug}.mp4` exists besides render()'s os.replace.
