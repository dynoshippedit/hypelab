# S5 — Fix

1. hypelab/render.py: FFMPEG_PINNED_VERSION="8.1.2" + _require_ffmpeg_version()
   called in render() after the render-hash skip check, before the ffmpeg
   subprocess. Mismatch or unparsable version -> RenderError (fail closed).
   (Single-thread flags were added, measured, and REMOVED — see FIND-01.)
2. tests/test_t044_deterministic.py: replaced sha256(mp4) equality with
   _assert_renders_equivalent — video decoded to rawvideo must be
   bit-identical (sha256), audio decoded to f32le/stereo/48k must satisfy
   max|Δ| <= 0.01 amplitude (-40 dBFS); comment cites the -48.6 dBFS
   measurement. Test docstring updated to describe the new assertion.
3. ARCHITECTURE.md (Part 4): one paragraph documenting the pin, the failed
   flags experiment, and the relaxed assertion.

No product render behavior changed: audio_chain filter params untouched.
