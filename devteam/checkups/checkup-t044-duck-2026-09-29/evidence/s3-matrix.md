# S3 — Review matrix

| unit | COR | ARC | TST | DOC |
|---|---|---|---|---|
| ffmpeg-version-pin (render.py) | pin parses first line of ffmpeg -version; mismatch/parse-fail -> RenderError; placed after skip check so mocked-subprocess tests hold | only render() gains a gate; argv builder untouched | test_pipeline 15/15 green; fault injection: version mismatch raises (see s6) | pin rationale + experiment outcome in code comment + ARCHITECTURE.md |
| t044-assertion-relax (test) | video rawvideo sha256 exact; audio f32le max|Δ| <= 0.01 (-40 dBFS); lengths asserted equal | tolerance logic test-local; no product change | candidate test green in default gate (65s); tolerance proven: injected -30 dBFS perturbation would fail, measured -48.6 dBFS passes (see s6) | measurement cited in test comment + this review |
| pin-documentation (ARCHITECTURE.md) | paragraph matches code (pin value, flags outcome, tolerance) | n/a (docs) | n/a | S7 docs-vs-tree check (new per 2026-09-29 decision) |

Lenses REL/DAT not applicable (no retry/cost/persistence semantics touched).
