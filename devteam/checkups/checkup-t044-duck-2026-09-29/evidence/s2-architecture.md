# S2 — Architecture

- render.py remains the ONLY module that builds ffmpeg argv (no change).
- The version pin is a startup gate inside render(), placed AFTER the
  render-hash skip check and BEFORE the ffmpeg subprocess, so:
  (a) the slots-filled gate still fires before any subprocess
      (test_render_missing_clip_gate mocks subprocess.run to explode);
  (b) the skip path still invokes zero subprocesses
      (test_render_and_skip asserts calls == [] on skip).
- _require_ffmpeg_version() parses "ffmpeg -version" first line; any parse
  failure or version mismatch raises RenderError (fail closed).
- T-044 assertion lives entirely in the test file; product audio chain
  (sidechaincompress params) is UNCHANGED — no product behavior change.
- ARCHITECTURE.md documents the pin in Part 4 (Deterministic rendering).
