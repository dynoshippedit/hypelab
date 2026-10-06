# S7 — Diff review

Branch devteam/review-2026-09-29, uncommitted. git diff --stat on tracked files:
- hypelab/render.py: +43/-0 — pin constant + comment, _require_ffmpeg_version(),
  one call site in render() after the skip check. No argv change (the
  single-thread flags were added, measured, and removed — net zero).
- ARCHITECTURE.md: +19 total, of which +11 are this change (pin paragraph in
  Part 4); the other +8 are the pre-existing HL-FLAG cost-ledger paragraph.
- tests/test_t044_deterministic.py: UNTRACKED new file (created by T-044 work,
  this change edits it): tolerance constants + measurement comment, three
  helpers (_decode_video_bytes/_decode_audio_f32/_assert_renders_equivalent),
  replaced final byte-exact assertion, dropped unused util_mod import and
  ref_hash variable. No quarantine marker added or removed in test_cli.py;
  the quarantined original stays quarantined and superseded.

Docs-vs-tree check: the ARCHITECTURE.md paragraph's claims (pin value 8.1.2,
flags tried and removed, -40 dBFS tolerance citing -48.6 dBFS measured) were
verified against the actual code diff above.

Unrelated uncommitted changes present (pre-existing, NOT mine, NOT reviewed
here): hypelab/retry.py + tests/test_failure_requeue.py (HL-FLAG kill switch).
Untouched by this review.
