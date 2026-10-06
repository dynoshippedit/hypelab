# S2 — Architecture

## ffmpeg version pin — placement and call path

`render()` (hypelab/render.py:440) is the single product entry point for full renders:
1. slots gate → 2. render-hash skip path → 3. **`_require_ffmpeg_version()`** (line 501) → 4. `subprocess.run(ffmpeg ...)` (line 509).

The pin is deliberately placed AFTER the skip path so the fast path (already-rendered jobs) never spawns a subprocess — the existing tests `test_render_missing_clip_gate` / `test_render_and_skip` assert exactly that, and they remain green.

`_require_ffmpeg_version()` runs `ffmpeg -version`, parses `first[2]` when the line starts with `ffmpeg version`, and raises `RenderError` on any mismatch OR on subprocess failure (OSError → RenderError). Fail-closed in both directions: missing ffmpeg and wrong ffmpeg both raise loudly.

## Scope boundary (documented observation, not a defect)

- `derive()` (line 580, aspect-ratio derivatives) invokes ffmpeg WITHOUT the pin. This is acceptable: derive uses `-c:a copy` (audio is copied, never re-encoded), so it is immune by construction to the sidechaincompress nondeterminism this pin guards against. Video re-encode determinism across ffmpeg versions was never in T-044's scope.
- `hypelab/gates.py` invokes ffmpeg for probing/measurement (astats, stream info), not rendering. Probe calls don't affect render output determinism; pinning them is out of scope.

## Crash-recovery test — structure

`test_worker_crash_recovery_sha256_deterministic` (tests/test_t044_deterministic.py:99):
1. Builds a reference job → renders to completion → gates to ready (so the crash-test worker can't claim it).
2. Builds a crash job → worker A claims (`work --once`) → test loop waits for claim (`state == "rendering"`) THEN for the deterministic kill point (PID-unique `9x16.partial-<pid>.mp4` exists with size > 0). Kill-point-missed and worker-early-exit are explicit `AssertionError`s with diagnosis (the old flake, now explicit, not silent).
3. SIGKILL worker A → poll-until-lease-expired loop (replaces the old blind `sleep(12)`; robust to heartbeat restamps by re-reading live `lease_expires`).
4. Asserts: job still `rendering` (reclaimable), NO partial file at final output path (atomic-output regression), worker B reclaims (`claimed`, `attempts >= 2`, state → `queued_gates`).
5. `_assert_renders_equivalent(ref, crash)`: video bytes sha256-identical; audio decoded identically (`f32le, stereo, 48kHz` both sides) → max |sample Δ| ≤ 0.01.

## Quarantine mechanism (conftest.py)

`@pytest.mark.quarantine` → skipped in the default gate, runnable via `--run-quarantined`. Zero tests carry the marker now; the machinery is retained for future timing-sensitive tests. The un-quarantined crash test runs in the default gate (verified by collection + 5x green runs).
