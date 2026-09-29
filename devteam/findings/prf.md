# PRF — Performance findings (Phase 3, PERF lens)

Branch: `devteam/review-2026-09-29` · commit `d778635` · reviewer: PERF subagent · 2026-09-28
IDs: PRF-500–549 · severity per Playbook B7 · all Status: Confirmed (unambiguous code, cited lines)

Related prior findings (not re-filed): DAT-359 (missing indexes, S4) — DB query
angle is DAT's; DAT-364 (faster-whisper auto-download, S2) — network-policy
angle is DAT's; ARC-311 (weights resolved three ways, S3) — location angle is
ARC's. PRF-500 below is the *distinct perf* aspect (reload-per-call cost).

Non-findings established by this pass: `parallel.py` does not exist (only the
dev-process comments "built in parallel by another agent"); the worker is a
single-threaded sequential claim loop (`cli.py:897-935`) — no parallel slots,
no lock-contention surface beyond SQLite `timeout=30` + WAL (`db.py:142-145`).
No `tests/test_parallel.py`, no `tests/test_stress*` — perf is untested.

---

## PRF-500 — Model weights reloaded from disk on every alignment/transcription call [S1, Confirmed]
**Location:** `hypelab/align.py:273,280` (`force_align_words`), `hypelab/align.py:129-130` (`transcribe`); callers `hypelab/cli.py:295` (`_do_align`), `hypelab/ingest.py:211`, worker loop `hypelab/cli.py:897-935`.
**What's wrong:** every call constructs a fresh `Wav2Vec2ForCTC.from_pretrained(str(cache), local_files_only=True)` + processor (no module-level cache, no `lru_cache` — contrast `provenance()` which does cache at `manifests.py:84`), and every `transcribe()` builds a fresh `WhisperModel(cfg["model"], ...)` (default `medium`, CPU, int8). The worker handles jobs sequentially **in one process**, so N jobs = N full model loads: ~360 MB wav2vec2 + torch init per align job; ~1.5 GB faster-whisper medium + CTranslate2 init per Book-2 ingest.
**Complexity:** reasoned — O(model bytes) disk+init cost per job, amortizable to once per process.
**Symptom:** tens of seconds to minutes of pure model-load overhead added to *every* job in a queue, instead of once per worker process. The longest pole on a multi-job night.
**Suggested fix (Phase 5):** process-lifetime cached loader (`functools.lru_cache` keyed on cache_dir/model name), with explicit invalidation hook.

## PRF-501 — Every render hashes all input media 3×; even the skip path hashes 2× [S2, Confirmed]
**Location:** `hypelab/render.py:462` (`build_command` → `verify_manifest` at `manifests.py:364-370`), `hypelab/render.py:495` (`render_hash` re-hashes every input at `manifests.py:72`), `hypelab/render.py:529-536` (`input_hashes` loop hashes them again). Skip check at `render.py:498-501` runs *after* the first two passes.
**What's wrong:** three full SHA-256 passes over every byte of beat clips + VO + music per successful render; two full passes before a "skipped: True" return is even reachable. Hashes are recomputed, never reused between the three consumers, despite identical file set.
**Complexity:** reasoned — O(3 × total input bytes) per render; O(2 × bytes) per no-op skip.
**Symptom:** on GB-scale inputs, seconds-to-minutes of pure disk read on every render *attempt*, including idempotent re-runs that change nothing.
**Suggested fix (Phase 5):** hash once in `build_command`, pass the digest map through to `render_hash` and the manifest entry; short-circuit the skip check before any hashing.

## PRF-502 — Gates re-decode the finished render ~4× and probe it 3× per job [S2, Confirmed]
**Location:** `hypelab/gates.py:82-108` (`gate_first_frame`: 1 full blackdetect decode + 2 `select`-filter frame extractions, each a fresh ffmpeg that decodes from t=0, + 2 PNG decodes via `_frame_pixels` at `gates.py:61-68`), `hypelab/gates.py:169` (`gate_loudness`: full loudnorm decode); ffprobe of the same output at `hypelab/render.py:521` (during render), `hypelab/gates.py:126` (`gate_duration`), `hypelab/gates.py:383` (geometry gate).
**What's wrong:** per `gates run` / worker gating pass: ~4 full decode passes over the final render and 3 separate ffprobe process spawns of the identical file. Nothing is shared between gates (each gate re-opens the file independently in `run_all`, `gates.py:446-467`).
**Complexity:** reasoned — O(4 × render bytes decoded) + 6+ process spawns per gating pass.
**Symptom:** several extra seconds-to-minutes of CPU per job on 1080p renders; dominates wall-clock on short clips where the render itself is fast.
**Suggested fix (Phase 5):** one shared probe record per `run_all` invocation; fuse loudness+first-frame into fewer decode passes (e.g. loudnorm + blackdetect in one `-af`/`-vf` graph).

## PRF-503 — `score_windows` is quadratic in source duration [S2, Confirmed]
**Location:** `hypelab/score.py:277-330` with `text_between` (`score.py:95-98`, linear word scan per window → O(M·W)), `mean_over_heatmap` (`score.py:252-261`, full heatmap scan per window → O(M·H)), `nms` (`score.py:333-344`, each window vs all kept → O(M²)). Window count M = duration/5 (`WIN_S=45, HOP_S=5`, `score.py:39-40`).
**What's wrong:** three nested scans over duration-derived lists, all in pure Python. A 1-hour source: ~720 windows × ~7200 words ≈ 5.2M dict ops (text_between) + 720 × 3600 heatmap points ≈ 2.6M ops + ~518K NMS comparisons. Doubling source length ≈ 4× scoring time.
**Complexity:** reasoned — Θ(duration²) Python-level ops.
**Symptom:** scoring long sources (podcasts, streams) degrades super-linearly; tens of seconds at 1h, minutes beyond.
**Suggested fix (Phase 5):** index words/heatmap once (sorted lists + bisect, or one linear sweep assigning words to windows); sweep-line NMS.

## PRF-504 — Audio feature extraction decodes the source twice [S2, Confirmed]
**Location:** `hypelab/score.py:136-148` (`_audio_signals`: silencedetect pass, then astats pass — two separate `ffmpeg` invocations over the full audio).
**What's wrong:** both passes fully decode the source audio; one pass with two filter outputs (`asplit` → silencedetect + astats) would do it in one decode.
**Complexity:** reasoned — 2× audio decode cost per score.
**Symptom:** ~2× the necessary CPU/IO on every `_handle_score` for Tier-2 features.

## PRF-505 — Duplicate ffprobe spawns on the same file [S3, Confirmed]
**Location:** `hypelab/compliance.py:133` (`chk_aspect`) + `hypelab/compliance.py:272` (`chk_platform_limits`) — two ffprobe spawns per clip per `check()` run (`compliance.py:188`); `hypelab/cut.py:154` ffprobes the clip right after `render()` already probed it (`render.py:521`); `hypelab/reframe.py:345` and `hypelab/render.py:105-114` (`_beat_geometry` per-beat probe when reframe plans exist) probe inputs the manifest already knows.
**What's wrong:** no probe result is ever cached or passed between callers; each is a fresh process spawn (~50-200 ms) on the same path.
**Complexity:** reasoned — O(redundant spawns) per clip; multiplies by clip count in Book-2 loops.
**Symptom:** hundreds of milliseconds to seconds of spawn overhead per job, worse in batch clip flows.

## PRF-506 — Carousel: 14 Chromium launches per 7-slide carousel, no batching [S3, Confirmed]
**Location:** `hypelab/carousel.py:175-208` (`_measure_slide`, 1 Chromium per slide = 7), `hypelab/carousel.py:228-238` (`_screenshot`, 1 Chromium per slide = 7), plus 7 ffprobe PNG-size checks (`carousel.py:241-251`) and `export_jpeg` spawning 1 ffmpeg per PNG (`carousel.py:294-321`).
**What's wrong:** each slide pays a cold Chromium startup (~1-3 s) twice; no persistent browser context, no single multi-page run, no `--screenshot` batching. ARC-314 context: the Python↔browser contract is already stringly-typed, so this is pure overhead, not correctness.
**Complexity:** reasoned — 21 subprocess spawns (14 Chromium) of fixed cost per carousel, independent of slide content.
**Symptom:** ~15-40 s+ of fixed overhead per carousel before any real rendering work.

## PRF-507 — N+1 queries in tray build; poison query on every worker poll [S3, Confirmed]
**Location:** `hypelab/tray.py:151-174` (`build_tray` loop → `_clip_meta` at `tray.py:69-103` does 2 SELECTs per clip + 1 UPDATE per clip = 3N queries for N clips); `hypelab/cli.py:900` (`_print_poison` full failed-jobs SELECT on every loop iteration, including idle 5 s polls).
**What's wrong:** per-clip metadata could be one batched JOIN; the poison listing is a constant poll tax.
**Complexity:** reasoned — O(N) round-trips, N = clips per job (small, bounded).
**Symptom:** negligible today; becomes visible if clip counts grow 10-100×. Low priority.

## PRF-508 — Full-file audio load into RAM; unbounded by chunking [S3, Confirmed]
**Location:** `hypelab/align.py:63-71` (`_load_16k_mono` loads the entire VO as float32 via librosa). Chunking (`CHUNK_S=30`, `align.py:22`) bounds *compute* per chunk but the initial load is whole-file: ~4 bytes/sample → ~460 MB for a 2 h VO.
**What's wrong:** memory scales linearly with VO length with no streaming alternative; a long-VO job on a small box risks OOM before alignment even starts.
**Complexity:** reasoned — O(duration) RAM, ~230 MB/hour of VO.
**Symptom:** worker OOM on long sources; no failure mode is graceful here.

## PRF-509 — Redundant DDL + PRAGMA schema checks on every render [S4, Confirmed]
**Location:** `hypelab/render.py:383-397` (`_ensure_render_tables`: 2 DDL + 2 `PRAGMA table_info`), called twice per render — before the skip check (`render.py:499`) and before insert (`render.py:544`).
**What's wrong:** schema verification on a hot path; cheap (µs-ms) but pure waste.
**Symptom:** none measurable; hygiene note.

## PRF-510 — `derive()` re-encodes previews at production preset [S4, Confirmed]
**Location:** `hypelab/render.py:565-620` (`derive`: `-preset medium -crf 19` for a PREVIEW cutdown that is never a deliverable).
**What's wrong:** preview encodes pay full-quality encode cost; `veryfast`/`ultrafast` would be a fraction of the CPU for a label-burned preview.
**Symptom:** preview generation costs roughly what a real encode costs.

## PRF-511 — Legacy `_constrain_to_script` is O(N·M) via `difflib` with `autojunk=False` [S4, Confirmed]
**Location:** `hypelab/align.py:541-594` (`SequenceMatcher(None, asr_tok, script_low, autojunk=False)`).
**What's wrong:** `autojunk=False` disables the heuristic that keeps SequenceMatcher near-linear; worst case is quadratic in token counts. Kept only for old regression tests ("Legacy helper ... Kept for test_regressions.py").
**Symptom:** none on current paths; note for anyone reusing it.

---

## Coverage notes (tests)
- No `tests/test_parallel.py`, no `tests/test_stress*` — nothing exercises throughput, large inputs, or repeated calls. Perf behaviors above are **entirely untested**.
- `tests/test_align.py:43` skips model-dependent tests when the wav2vec2 cache is absent — so PRF-500's reload cost is invisible to the suite by construction.
- `tests/test_gates.py` (25 tests) exercises gate *correctness* on small synthetic media; nothing asserts on spawn counts or shared probes (PRF-502 untested).
- No test asserts hashing is done once (PRF-501), scoring is sub-quadratic (PRF-503), or Chromium is launched a bounded number of times (PRF-506).
- Pattern Pack: none found — searched `devteam/` and the kit instructions dir (`/home/dino/Desktop/instructions/` listing failed from this host); no perf-pattern checklist exists to dispose. If the Pack arrives later, map: model-cache→PRF-500, redundant-hash→PRF-501, decode-fusion→PRF-502/504, quadratic-scan→PRF-503, spawn-batching→PRF-505/506.
