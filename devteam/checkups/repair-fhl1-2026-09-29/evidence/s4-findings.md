# S4 — challenged findings

## F-HL-1 — lease-loss/concurrent render vs shared output · CONFIRMED_DEFECT → FIXED

- Claim: a worker that loses its lease keeps rendering; a reclaimed job can
  be rendered by two workers concurrently, and the shared output path was
  not protected by any regression test against interleaved/torn writes.
- Location: hypelab/render.py:440-565 (render), hypelab/cli.py:711-724
  (heartbeat); source identity master@5c185ba.
- Challenge / counter-check: the finding's sub-claim (b) — "ffmpeg invoked
  with -y writing directly to the shared work/out/{slug}.mp4 — no temp file,
  no atomic rename" — does NOT hold at HEAD. render() has written to a
  PID-unique temp file (out.stem.partial-<pid>.mp4, render.py:486) and
  committed via os.replace (render.py:522) since commit 81aaf52; the
  `-y` in build_command (render.py:384) targets that temp file only (sole
  production caller passes tmp; grep-verified). The real gap was the
  missing regression test for the concurrent/lease-loss path (T-044 covers
  only single-worker SIGKILL). Sub-claim (a) — render continues after lease
  loss — is true and is retained per the chief's explicit direction (no
  scheduling-semantics change); the temp+rename repair neutralizes its
  corruption consequence. Split off as F-HL-1a (QUEUED).
- Verification: check-final-suite (full suite incl. 3 new tests green);
  negative control (all 3 tests fail when render() is forced to -y onto
  `out`) proves the tests pin the invariant rather than the implementation.

## F-HL-1a — render continues after lease loss (no abort) · CONFIRMED_DEFECT → QUEUED

- Claim: cli.py:711-724 heartbeat thread breaks on lease loss but the render
  proceeds; the reclaimed job's second worker and the first worker both run
  to completion and both transition rendering→rendered→queued_gates.
- Location: hypelab/cli.py:711-724, master@5c185ba.
- Challenge: confirmed present by code read; not changed in this repair.
- queue_task_id: chief-decision-2026-09-29 (repair brief: "does not change
  scheduling semantics").
- remaining_reason: needs Dino's call — the principal reviewer's "Fix
  options (needs Dino's call)": abort-on-lease-loss vs temp-file+rename.
  The chief selected temp-file+rename for this repair; the abort policy is
  an open product/scheduling decision for the owner. With the rename in
  place, the lease-loss worker cannot corrupt the shared output (R1-R3 hold
  regardless of lease policy).

## Related observation (not a finding; reported, not expanded)

- manifests.record_render is read-modify-write without a lock; two
  concurrent workers can lose one manifest.json log entry (the file itself
  cannot tear — _write_manifest is tmp+fsync+replace). Benign bookkeeping
  loss; out of F-HL-1 scope.
- Stale `.partial-<pid>.mp4` orphans accumulate in work/out/ after SIGKILL;
  nothing reads them back. Cleanup would need live-PID discrimination;
  left as-is (deletion caution), noted for a future housekeeping pass.
