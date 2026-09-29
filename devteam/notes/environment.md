# Environment / config / dependency inventory — HypeLab (ENV, 2026-09-29)

Branch `devteam/review-2026-09-29`. Method: grep + AST scan of every `hypelab/*.py`
and `tests/*.py`; each claim below cites `path:line`. Builds on BLD Phase 1
(`devteam/notes/env-inventory.md`, `devteam/notes/dependencies.md`, BLD-001–013);
this note adds mis-set behavior, defaults/timing tables, the exact clean-install
import list, and the first-run failure map. Findings live in
`devteam/findings/env.md` (ENV-650–657).

## 1. Environment variables — complete inventory

### Read by the code (5)

| Variable | Read at | Default when unset | Documented? | Mis-set behavior |
|---|---|---|---|---|
| `HYPELAB_ROOT` | `cli.py:87`, `b2cli.py:47`, `book3cli.py:43` | `/home/dino/hypelab` (`DEFAULT_ROOT`, `cli.py:53`) | Yes — cli.py:19-20 docstring, b2cli/book3cli headers | Moves `work/<job_id>/` dirs only. **The DB does NOT follow** (`db.connect(None)` → hardcoded `/home/dino/hypelab/hypelab.db`, `db.py:26`) → ENV-651 |
| `HYPELAB_DB` | `cli.py:91`, `b2cli.py:51`, `book3cli.py:47` | `/home/dino/hypelab/hypelab.db` (`db.py:26`) | Yes — cli.py:19 docstring | Path that is a directory → `sqlite3.OperationalError` traceback; unwritable parent → `PermissionError` traceback in `p.parent.mkdir` (`db.py:141`). **Not** wrapped in `_die` → ENV-657 |
| `HYPELAB_LEASE_SECONDS` | `cli.py:98-107` | `1800` (`queue_mod.LEASE_TTL_S`, `queue.py:28`) | Yes — cli.py:21 docstring ("tests use a short one") | Garbage → `ValueError` → silently 0 (lease NOT overridden, no warning); negative → ignored by `> 0` guard. Read **at import time** → tests must set env *before* importing `hypelab.cli` (coupling) → ENV-656 |
| `HYPELAB_CHROMIUM` | `carousel.py:53` | PATH search (`google-chrome`, `google-chrome-stable`, `chromium`, `chromium-browser`), then `/opt/pw-browsers/chromium` | **No** — appears only in the error string (`carousel.py:68`) → BLD-008 | Non-file value → clean `CarouselError("HYPELAB_CHROMIUM=<v> is not a file")`, caught in `book3cli.py:118` → `error:` + exit 1. No test references it (`grep` tests/ → ∅) |
| `HYPELAB_WORK_DIR` | **set by tests, never read** | n/a | n/a | `tests/test_book2.py:513,545` set it via `monkeypatch.setenv`; code ignores it → BLD-007 (dead test isolation) |

### Documented but never read (do NOT rely on these)

| Variable | Documented where | Status |
|---|---|---|
| `HYPELAB_HOME` | `README.md:16`, `VERTICAL_SLICE_REPORT.md:45` ("default; the DB + jobs/ live here") | Read nowhere (`grep` → 0 hits) → BLD-005, DOC-005 |
| `HYPELAB_CACHE` | `ARCHITECTURE.md:381` ("`~/.cache/hypelab/` (or `$HYPELAB_CACHE`)") | Read nowhere → BLD-006 |
| `HYPELAB_WORK_DIR` | not documented | set by tests only → BLD-007 |

### NOT read (deliberate gaps worth knowing)

- `HF_HOME` / `HF_HUB_CACHE` / `HF_HUB_OFFLINE` / `TRANSFORMERS_OFFLINE`: never read.
  `fetch_model()` downloads `facebook/wav2vec2-base-960h` via transformers' default
  cache policy into `models/`; faster-whisper uses its own HF hub cache
  (`~/.cache/huggingface`). No env knob to relocate either cache, no offline flag
  is honored, and a no-network first transcribe raises a raw
  urllib/ctranslate2 traceback → ENV-653.
- `TMPDIR`: never read directly. `tempfile` calls (`gates.py:95`,
  `carousel.py:192,292,378,421`) honor it via stdlib; but `reframe.py:138`
  hardcodes `/tmp/hypelab_textcheck_<hash>.png` → ENV-654.
- `CUDA_*` / `TORCH_*`: never read. `device` is fixed to `"cpu"` by default
  (`align.py:84-89`, `kits.py:142`); no auto-detect of a GPU → ENV-655.
- Watcher: no `HTTP_PROXY`/`HTTPS_PROXY` handling in code; `urllib.request.urlopen`
  honors proxy env vars implicitly via stdlib (timeout 30 s, `watcher.py:67-74`).
- No listening ports anywhere: no `socket.bind`/`listen`/`serve_forever` in
  `hypelab/` (verified by grep → ∅). "Watcher HTTP port" default = **none** —
  the watcher is a CLI poll loop (`b2cli.py:221`), not a server.

## 2. Defaults table

### Hardcoded paths (assume Dino's machine unless overridden)

| Default | Location | Overridable? |
|---|---|---|
| `/home/dino/hypelab` (DEFAULT_ROOT) | `cli.py:53`, `b2cli.py:35`, `book3cli.py:32`, `util.py:173` (`work_dir` default arg) | Yes, via `HYPELAB_ROOT` — except DB and model cache (ENV-651) |
| `/home/dino/hypelab/hypelab.db` (DEFAULT_DB_PATH) | `db.py:26` | Yes, via `HYPELAB_DB` only |
| `/home/dino/hypelab/models/wav2vec2-base-960h` (DEFAULT_CACHE_DIR) | `align.py:28` | Only as a function argument — **ignores `HYPELAB_ROOT`** (ENV-651) |
| `/home/dino/hypelab/kits/cerebratico/kit.json` (CEREBRATICO_KIT_PATH) | `kits.py:18` | Not via env |
| `/opt/pw-browsers/chromium` (carousel fallback) | `carousel.py:64` | Yes, via `HYPELAB_CHROMIUM` |
| `/tmp/hypelab_textcheck_<hash>.png` | `reframe.py:138` | No — ignores `TMPDIR` (ENV-654) |
| `tempfile` scratch (`hypelab_gate_*`, `hypelab_carousel_*`) | `gates.py:95`, `carousel.py:192,378` | Via `$TMPDIR` (stdlib default) |
| Job artifacts `work/<job_id>/` | `util.py:173` | Via `HYPELAB_ROOT` |

### Model / compute defaults

| Default | Location | Notes |
|---|---|---|
| ASR model `"medium"`, device `"cpu"`, `compute_type "int8"`, `vad_filter true` | `align.py:84-89` (DEFAULT_ASR_CFG), `kits.py:142` (kit seeding fallback) | `medium` is a **GB-scale download on first transcribe** (no doc estimate, no progress UI beyond faster-whisper's own). `beam_size=5` (`align.py:131`). No CUDA auto-detect — GPU machines stay on CPU unless the kit overrides (ENV-655) |
| Forced-align model `facebook/wav2vec2-base-960h` → `models/` | `align.py:31`, `align.py:28` | Fetched once by `fetch_model()`; `_check_cache` (`align.py:176-182`) raises clean `AlignError` if `config.json`/weights missing — good |
| Faster-whisper cache | HF hub default (`~/.cache/huggingface`) | **Second, separate model cache** the docs never mention (ENV-653) |

### Timeouts (all hardcoded, none env-configurable)

| Timeout | Location |
|---|---|
| SQLite busy timeout 30 s | `db.py:142` |
| `gates._run` default 180 s; frame extract 60 s | `gates.py:35`, `gates.py:65,102` |
| render `FFMPEG_TIMEOUT` 600 s | `render.py:26` |
| `carousel._run` 120 s | `carousel.py:72` |
| ingest ffmpeg 300 s / 3600 s / 7200 s (three stages) | `ingest.py:119,142,157` |
| `cut.py` 300 s | `cut.py:59` |
| `manifests.py` sha 30 s | `manifests.py:86` |
| watcher: yt-dlp 120 s; RSS fetch 30 s | `watcher.py:49`, `watcher.py:67-74` |
| ffprobe 60 s | `util.py` (`subprocess.run(..., timeout=60)`) |
| reframe ffmpeg/tesseract 60 s each | `reframe.py:144-157` |

### Leases / polling

| Default | Location |
|---|---|
| `LEASE_TTL_S = 1800` (30 min claim lease) | `queue.py:28` |
| `HYPELAB_LEASE_SECONDS` override (tests only, import-time) | `cli.py:98-107` |
| Watcher `MIN_POLL_EVERY_S = 300` (floor on poll interval) | `watcher.py:31,185` |
| Claim-loop idle sleep 5 s | `cli.py:900` |
| Queue `MAX_ATTEMPTS = 3` → POISON | `queue.py:25,191` |

### CLI option defaults of note

- `hypelab render`: `--aspect` default `9:16` (`cli.py:397`); `--max-s` default 45.0 (`cli.py:399`)
- `book3 authorize`: `--actor` default `"dino"` (`book3cli.py`, ~line 74) — hardcoded operator name, cosmetic but machine-assumptive
- `hypelab work --owner`: default `hostname:pid` (`cli.py:888`)
- Carousel: `SLIDE_DURATION_S = 2.0`, exactly 7 slides, 1080×1350 (`carousel.py:38-40,348`)
- Captions: font `DejaVu Sans`, size 72, style `word_pop` (`kits.py`, captions block)
- `music_duck_db` default −12.0 (`cli.py:571`); `min_word_prob` 0.5; `max_clip_s` 10.0; `words_per_sec` 2.6; `min_beat_s` 1.2 (`kits.py:131-145`)

## 3. Dependency inventory — what a clean install actually needs

Derived by AST scan of all imports in `hypelab/` (collected 2026-09-29).
**No `pyproject.toml` / `setup.py` / `requirements*.txt` exists** → BLD-001
(clean-clone install is impossible; this table is the de-facto manifest).

### Python packages

| Package (import name) | Lazy / top-level | Needed for | Installed version (Threadripper, 2026-09-29) |
|---|---|---|---|
| `click` | TOP (`cli.py:35`, `b2cli.py:18`, `book3cli.py:18`) | CLI boot itself | 8.5.0 |
| `jsonschema` | TOP (`edl.py:12`, via `cli.py:39`) | CLI boot (EDL validation) | 4.26.0 |
| `librosa` | LAZY (`align.py:71`) | `audio`/`align` (16 kHz mono load) | 0.11.0 |
| `numpy` | LAZY (`align.py:69,264`) | align | 2.4.6 |
| `faster_whisper` | LAZY (`align.py:126`) | `transcribe()` | 1.2.1 (ctranslate2 4.8.2, onnxruntime 1.30.0, audioread 3.1.0, soundfile 0.14.0, av 18.1.0 transitive) |
| `torch` | LAZY (`align.py:226,265`) | forced align | 2.12.1+cu130 (**CUDA unavailable** → CPU-only, BLD-012) |
| `torchaudio` | LAZY (`align.py:227,266`) | forced align | 2.11.0+cu130 |
| `transformers` | LAZY (`align.py:165,271`) | fetch_model / forced align | 5.12.1 (ahead of public 4.x line; works, provenance unverified) |
| `pysubs2` | LAZY (`captions.py:62`, `gates.py:292`) | captions / caption_safe gate | 1.9.0 |
| `cv2` | LAZY (`reframe.py:59,85`) | reframe (Book 2) | 4.13.0 |

**Boot minimum: `click` + `jsonschema` only** — every heavy/ML import is lazy inside
functions, so `--help`, `new`, `migrate`, `jobs` work on a bare Python. Everything
else degrades at first use.

Test-only third-party: `pytest`, `soundfile` (AST scan of `tests/`), plus `click`
and `librosa` (re-exported from product set).

Installed-but-unused: `whisper` (openai-whisper 1.1.10 in system site) — BLD-013.

### Native prerequisites

| Tool | Required? | Behavior when absent | Present on Threadripper? |
|---|---|---|---|
| `ffmpeg` + `ffprobe` | yes (media path) | `ffprobe` absent → clean `MediaError("ffprobe binary not found")` → `error:` exit 1 (`util.py:86`); **`ffmpeg` absent at render/gates → raw `FileNotFoundError` traceback** (`render.py:456`, `gates.py:44` uncaught) → ENV-652 | ✅ ffmpeg 8.1.2 |
| Chromium / google-chrome | yes (Book 3 carousel only) | Clean: `CarouselError` → `error: no Chromium binary found … Set HYPELAB_CHROMIUM.` → exit 1 (`carousel.py:66-68`, caught `book3cli.py:118`) | ✅ Google Chrome 153.0.8010.52 |
| `tesseract` | no (optional OCR) | Graceful: `has_onscreen_text` → `(None, "unavailable:no-ocr-binary")` → mode chooser **fails closed to blurpad** (`reframe.py:131-138,264-278`) | ❌ absent |
| `yt-dlp` | no (watcher source kind) | Clean: `WatcherError("yt-dlp binary not found")` → `error:` exit 1 (`watcher.py:50-51`, caught `b2cli.py:174,222`) | ❌ absent |
| `edge-tts` | **never was** | Named only in `README.md:17` (`doctor` comment) and ARCHITECTURE provenance strings — stale doc → BLD-003 | ❌ absent (never imported) |
| GPU / CUDA | no | Torch reports `cuda.is_available()=False`; everything runs CPU | ❌ absent (BLD-012) |
| fonts (DejaVu Sans default) | yes for captions | Unverified failure mode | unverified |

**No version floors exist for anything** — Python or native (no `>=` anywhere in
the repo). The docs don't state minimum ffmpeg/Chromium/tesseract versions either
→ ENV-650.

## 4. First-run failure map (clean machine, Python 3.11+ only)

Ordered by how far a fresh operator gets:

| # | Missing piece | What happens | Failure mode |
|---|---|---|---|
| 1 | `click`, `jsonschema` | `python3 -m hypelab.cli` dies at import | **Traceback** (`ModuleNotFoundError`) — nothing runs |
| 2 | README setup step | `python3 -m hypelab.cli doctor` | **Clean-ish dead end**: `Error: No such command 'doctor'.` (exit 2) → BLD-003. There is **no environment self-check** anywhere |
| 3 | `ffmpeg`/`ffprobe` | `hypelab attach` → ffprobe | Clean: `error: ffprobe binary not found: …` (exit 1) via `MediaError` → `_die` |
| 3b | `ffmpeg` present-missing skew | `hypelab render` / gates with ffprobe OK but no ffmpeg | **Raw traceback** (`FileNotFoundError` from `subprocess.run`, uncaught at `render.py:456` and `gates.py:44`) → ENV-652 |
| 4 | `librosa`/`numpy` | `hypelab audio` | **Raw traceback** (`ModuleNotFoundError`, no install hint) → ENV-652 |
| 5 | `faster_whisper` | `hypelab audio` (transcribe path) | **Raw traceback** (`ModuleNotFoundError`) → ENV-652 |
| 5b | faster-whisper installed, **no network / no cached model** | `transcribe()` → `WhisperModel("medium", …)` | **Raw traceback** (urllib/ctranslate2 download error); no clean "run fetch first" message, no offline flag honored → ENV-653 |
| 6 | `torch`/`torchaudio`/`transformers` | forced-align path | **Raw traceback** (`ModuleNotFoundError`) → ENV-652 |
| 7 | wav2vec2 cache missing | `force_align_words` | Clean: `AlignError("wav2vec2 model not cached; run fetch_model first")` (`align.py:182`) — the one graceful model error |
| 8 | `tesseract` | reframe mode choice | **Graceful**: fails closed to `blurpad` (`reframe.py:270-278`) — honest degradation, no error |
| 9 | Chromium | `hypelab carousel` | Clean: `error: no Chromium binary found … Set HYPELAB_CHROMIUM.` (exit 1) |
| 10 | `yt-dlp` | watcher source add/poll | Clean: `error: yt-dlp binary not found: …` (exit 1) |
| 11 | `pysubs2` | caption_safe gate with `captions.ass` present | Clean fail-closed: gate FAILs, "unreadable input: captions.ass present but pysubs2 is not installed" (`gates.py:292-296`) |
| 12 | `cv2` | Book 2 reframe | **Raw traceback** (`ModuleNotFoundError`) → ENV-652 |
| 13 | Worker loop (`hypelab work`) with any of the above missing | handler raises | Caught per-job (`cli.py:928`): job fails, retried to `MAX_ATTEMPTS=3` → POISON. Machine-level misconfig becomes 3 poisoned jobs, no operator alert beyond stdout |

**Pattern:** the CLI is clean (`error:` + exit 1) for missing *native binaries the
author anticipated* (ffprobe, Chromium, yt-dlp, tesseract, wav2vec2 cache) but
produces raw tracebacks for missing *Python packages* (the lazy ML stack) and for
ffmpeg-missing at render time. The cleanest story is `tesseract` (fail-closed
blurpad); the worst is `doctor` (the documented first-run check doesn't exist).
