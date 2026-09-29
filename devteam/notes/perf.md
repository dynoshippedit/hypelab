# PERF lens — Phase 3 per-path analysis (HypeLab)

Branch `devteam/review-2026-09-29` @ `d778635`. Read-only pass; no source touched.
Method: static analysis with file:line grounding; complexity is **reasoned**
unless stated measured. No benchmarks were run (no solver/profiler installed
for this; operator-visible symptoms are reasoned from the code shape).

## 0. Things the task assumed that are not in the code
- **`parallel.py` does not exist.** The only "parallel" hits are dev-process
  comments ("built in parallel by another agent", e.g. `gates.py:123`).
  "Parallel slots" as a runtime concept do not exist: the worker
  (`cli.py:881-935`) is a single-threaded sequential claim loop over the
  SQLite lease queue (`queue.py`). Consequence: there is no thread pool, no
  lock contention, no slot starvation to analyze. SQLite is opened with
  `timeout=30`, `isolation_level=None` (autocommit), WAL (`db.py:133-145`);
  the heartbeat thread uses a *separate* connection (`cli.py:688-700`) so no
  cross-thread connection sharing. For a single-operator CLI this is adequate;
  it becomes the bottleneck only if multi-worker concurrency is ever added.
- **No `tests/test_parallel.py`, no `tests/test_stress*`.** Perf is untested;
  see Coverage in `devteam/findings/prf.md`.

## 1. Render pipeline (`render.py`, 576 lines)
- `build_command` → `verify_manifest` re-hashes **every** manifest asset
  (`manifests.py:364-370`), then `render_hash` hashes all inputs again
  (`manifests.py:59-76`), then `render()` hashes them a **third** time for the
  manifest entry (`render.py:529-536`). The idempotency skip (`render.py:498-501`)
  runs after two of those passes — a no-op re-render still re-reads gigabytes.
  Reasoned: O(3×input bytes)/render, O(2×)/skip. → PRF-501 (S2).
- `_ensure_render_tables` does DDL + 2× `PRAGMA table_info` twice per render
  (`render.py:383-397`, called at :499 and :544). µs-scale; hygiene only. → PRF-509 (S4).
- With reframe plans, `_beat_geometry` spawns one ffprobe **per beat per render**
  (`render.py:105-114`); probe results are never cached or shared. → PRF-505 (S3).
- `derive()` re-encodes previews at `-preset medium -crf 19` (`render.py:596-613`)
  although previews are never deliverables. → PRF-510 (S4).
- Positive: crash-safe output via PID-unique temp + `os.replace` (`render.py:455-459`);
  slots-filled gate before any ffmpeg (`render.py:438-447`); `provenance()` is
  `lru_cache`d (`manifests.py:84`) so `ffmpeg -version` is not re-spawned.

## 2. Alignment (`align.py`, 607 lines)
- **No model caching anywhere.** `force_align_words` loads processor + wav2vec2
  from disk on every call (`align.py:273,280`); `transcribe` constructs a new
  `WhisperModel("medium", cpu, int8)` on every call (`align.py:129-130`).
  Called per job from the single-process worker (`cli.py:295`, loop at
  `cli.py:897-935`) and from ingest (`ingest.py:211`). → PRF-500 (S1) — the
  top perf risk: N jobs = N full model loads.
- Chunking (`CHUNK_S=30`, `CHUNK_OVERLAP_S=2`) correctly bounds *compute*
  memory, but `_load_16k_mono` loads the whole VO as float32 first
  (`align.py:63-71`): O(duration) RAM ≈ 230 MB/hour of VO. → PRF-508 (S3).
- Word-assignment to chunks is a uniform-rate midpoint estimate
  (`align.py:309-314`) — linear, fine for perf; correctness is another lens.
- `retime_beats` / `low_confidence_beats` / `group_into_cards` / `build_ass` are
  all single linear passes — no quadratic on beat/caption counts.
- Legacy `_constrain_to_script` uses `difflib.SequenceMatcher(autojunk=False)`
  (`align.py:565`) — O(N·M) worst case, but dead code kept for old tests. → PRF-511 (S4).
- Network note (not re-filed): faster-whisper auto-download is DAT-364 (S2);
  weights-location triplication is ARC-311 (S3).

## 3. ffmpeg invocation overhead (11 modules with subprocess use)
Observed call sites: carousel 5, compliance 4, cut 6, gates 12, ingest 6,
manifests 11, reframe 6, render 11, score 3, tray 2, util 11, watcher 1.
Per-call spawn cost is ~10-50 ms (ffmpeg/ffprobe) to 1-3 s (Chromium) — the
cost is in *redundant* invocations, not the spawn primitive:
- Gates re-decode the final render ~4× + probe it 3× per job (see §4). → PRF-502 (S2).
- `_audio_signals` decodes source audio twice (silencedetect, then astats;
  `score.py:136-148`) — fusible into one pass. → PRF-504 (S2).
- compliance runs 2 ffprobes per clip (`compliance.py:133,272`); cut re-probes
  right after render probed (`cut.py:154` vs `render.py:521`). → PRF-505 (S3).
- Carousel: 14 Chromium + 7 ffprobe + N ffmpeg per carousel. → PRF-506 (S3).
- No double-decode in the render chain itself: one ffmpeg with a single
  `-filter_complex` — good design; `loudnorm` is single-pass as configured.

## 4. Gates (`gates.py`, `run_all` at :446-467)
Per gating pass on one render: `gate_first_frame` = 1 full blackdetect decode
(:82) + 2 frame extractions that each decode from t=0 (:101-108) + 2 PNG
decodes (:61-68); `gate_loudness` = 1 full loudnorm decode (:169);
`gate_duration` (:126) and geometry (:383) each ffprobe; render itself probed at
`render.py:521`. Total ≈ 4 full decodes + 3 probes + ~10 spawns, none shared
between gates. → PRF-502 (S2).

## 5. DB query patterns
- No N+1 in CLI list/status loops: `_print_poison` (cli.py:820-828), `costs`
  (cli.py:948-971) are single `fetchall` + print loops. `build_tray` is the one
  N+1: 2 SELECTs + 1 UPDATE per clip (`tray.py:69-103,171-174`). → PRF-507 (S3).
- Missing indexes are DAT-359 (S4) — deferred to, not duplicated.
- `_print_poison` runs on every worker iteration including idle polls
  (`cli.py:900`) — trivial constant tax, noted in PRF-507.

## 6. File I/O
- Triple hashing per render (§1). → PRF-501.
- `intake_asset` (`util.py:105-177`) reads the file twice (copy + hash) — inherent
  to its integrity design; acceptable.
- Manifest rewrites are whole-file read+write per render/measurement
  (`manifests.py:158-177`); manifest.json grows with render history but stays
  KB-scale — fine at current scale.
- `vo.words.json` write is atomic tmp→rename (`cli.py:284-299`); carousel uses
  `TemporaryDirectory`; no tmpfile leaks found on hot paths. `reframe.py:140`
  uses a fixed `/tmp/hypelab_textcheck_<hash>.png` name with `finally: unlink` —
  safe single-worker, would collide under concurrency (no concurrency exists).

## 7. Carousel (ARC-314 context)
Confirmed 14 Chromium launches per carousel (7 probes + 7 screenshots) with no
browser reuse, plus 7 ffprobe size checks and per-PNG ffmpeg exports. Fixed
overhead ~15-40 s per 7-slide carousel regardless of content. → PRF-506 (S3).

## 8. Memory growth
- Whole-VO float32 load (§2). → PRF-508 (S3).
- `score_windows` builds one dict per window (fine); `nms` is O(M²)
  comparisons (`score.py:333-344`); `text_between`/`mean_over_heatmap` rescan
  per window → Θ(duration²) total (`score.py:95-98,252-261,277-330`). → PRF-503 (S2).
- Everything else (ASS build, EDL JSON, manifest) is linear and small.

## Verdicts per path
| Path | Verdict | Worst finding |
|---|---|---|
| render pipeline | S2 — redundant hashing dominates | PRF-501 |
| alignment | **S1 — model reload per job** | PRF-500 |
| ffmpeg overhead | S2 — redundant decodes/probes | PRF-502, PRF-504 |
| gates | S2 — 4× decode + 3× probe per job | PRF-502 |
| DB queries | S3 — one N+1 (tray); indexes are DAT-359 | PRF-507 |
| file I/O | S2 — triple hash; no tmpfile leaks | PRF-501 |
| carousel | S3 — 14 Chromium launches | PRF-506 |
| memory | S2/S3 — quadratic scoring; whole-VO load | PRF-503, PRF-508 |
