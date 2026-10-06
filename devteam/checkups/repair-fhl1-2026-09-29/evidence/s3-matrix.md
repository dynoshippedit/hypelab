# S3 — engineering matrix (14 unit/lens cells)

## Unit render-output-atomicity — hypelab/render.py

- COR: render() (440-565) writes ffmpeg output to PID-unique
  `out.stem.partial-<pid>.mp4` (486), validates via ffprobe (519), then
  `os.replace(tmp, out)` (522) — the only write to the final path. Failure
  paths unlink tmp (516, 521) and raise; the final path is never truncated
  by a failed render. build_command's `-y` (384) targets tmp only: the sole
  production caller passes tmp (487); verified by grep (no other callers).
- ARC: temp+rename is the single output-commit boundary; derive() reuses the
  same pattern (594/618). Manifest writes are atomic
  (manifests.py:_write_manifest tmp+fsync+replace, 158-173); concurrent
  record_render appends are read-modify-write without a lock — worst case a
  lost log entry, not a torn file (out of F-HL-1 scope, noted).
- TST: T-044 crash test covers SIGKILL-mid-render of one worker; the new
  tests/test_fhl1_lease_loss.py covers the two-worker lease-loss case
  (previously untested). Negative control: all 3 new tests fail when
  render() is forced to `-y` straight onto `out` (evidence in s5-fix.md).
- DOC: the mechanism is documented in-code (render.py:483-485 comment) and
  in the render() docstring gate-order list; no user-facing doc change
  needed (internal invariant).
- REL: concurrent same-job renders cannot interleave bytes (PID-unique
  temps); orphan temps after SIGKILL are never picked up (no glob-back);
  rename atomicity verified at the OS level (POSIX rename(2) semantics).

## Unit heartbeat-lease-policy — hypelab/cli.py

- COR: _render_job heartbeat thread (711-724) breaks on lease loss without
  aborting the render — behavior confirmed present, intentionally UNCHANGED
  per the chief's repair direction ("does not change scheduling semantics").
- ARC: heartbeat runs on a separate DB connection (c2) so render-thread
  connection state is never shared across threads (comment at ~705).
- TST: no test pins the heartbeat thread's post-loss behavior; out of this
  repair's scope (finding F-HL-1a QUEUED for owner/chief call).
- DOC: the "lease expired" print acknowledges the condition without acting —
  matches the principal reviewer's observation; no doc change in scope.
- REL: the 60s heartbeat / 30-min lease + reaper reclaim path is unchanged;
  with temp+rename in place, a lease-loss-while-alive worker cannot corrupt
  the shared output (the defect's corruption claim is addressed at the
  render layer regardless of lease policy).

## Unit regression-tests — tests/test_fhl1_lease_loss.py

- COR: 3 tests assert R1/R2/R3 (S0): (1) two forked worker processes render
  the same job concurrently → final file decodes and its video bytes are
  sha256-identical to a single reference render (T-044 determinism), no
  `.partial-*` remains; (2) kill-simulation (torn write to temp +
  TimeoutExpired) leaves pre-existing final output byte-identical;
  (3) captured ffmpeg argv targets a `.partial-<pid>` sibling, never `out`.
- ARC: tests sit at the render() level where the invariant lives; they use
  real ffmpeg/ffprobe (no mocks of the behavior under test) except a
  subprocess.run shim that still executes a real ffprobe and version-pin
  check via delegation.
- TST: the tests are deterministic by construction — (1) relies on the
  T-044-proven video determinism; (2)/(3) are fully hermetic. Negative
  control run proves each test fails against the broken implementation.
- DOC: module docstring maps each test to the finding, the chief direction,
  and the falsification property.

No NOT_APPLICABLE cells; all 14 cells REVIEWED.
