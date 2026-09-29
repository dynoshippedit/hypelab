# ENV findings — HypeLab environment / config / dependency audit (2026-09-29)

Branch `devteam/review-2026-09-29`. Lane prefix: ENV · ID range ENV-650–699 ·
all NEW, all **Status: Confirmed** with `path:line` evidence. Severities use the
B7 scale (S1 critical → S5 info), calibrated to the single-user local-CLI trust
model. Builds on BLD Phase 1 (BLD-001, 003–009, 012, 013) and the notes in
`devteam/notes/environment.md` — findings below are the cross-cutting items BLD
did not file. Rules: read-only on product source; no fixes made.

## ENV-650 — S2 — No version floors for any dependency, Python or native

**Evidence.** `grep -rn '>=' hypelab/ --include=*.py` → no version pins/floors
anywhere; no `pyproject.toml` / `setup.py` / `requirements*.txt` (BLD-001). The
docs state no minimum versions either: `README.md` names ffmpeg, "whisper",
edge-tts, fonts with no versions; native tools (`ffmpeg` 8.1.2 installed,
Google Chrome 153.0.8010.52, `tesseract` absent, `yt-dlp` absent) are detected
by presence only (`shutil.which` / bare argv exec — `carousel.py:59-68`,
`reframe.py:135`, `watcher.py:50`).

**Impact.** Silent drift: a fresh machine installs whatever is current —
faster-whisper 2.x API changes, torch 2.x → 3.x, transformers 4.x vs the
installed 5.12.1 line — and nothing declares the floor that makes the pipeline
work. `ctranslate2`/`onnxruntime` ABI is torch-version-sensitive; a bad combo
fails at first transcribe, far from the install step. This is the version half
of BLD-001 (which covers the missing manifest); this finding covers the
missing *policy* for native tools too.

**Suggested fix:** document minimums for ffmpeg/ffprobe, Chromium, tesseract,
yt-dlp (docs fix, PRE-APPROVED); add a `[project] dependencies` table with `>=`
floors when the manifest lands (BLD-001).

## ENV-651 — S2 — HYPELAB_ROOT / HYPELAB_DB / model cache do not move together

**Evidence.** `cli.py:87` reads `HYPELAB_ROOT` for `work/<job_id>/` dirs, but
`_conn()` (`cli.py:91`) → `db.connect(None)` → `DEFAULT_DB_PATH =
Path("/home/dino/hypelab/hypelab.db")` (`db.py:26`) — the DB ignores
`HYPELAB_ROOT`. Meanwhile `align.py:28` pins
`DEFAULT_CACHE_DIR = "/home/dino/hypelab/models/wav2vec2-base-960h"` — the model
cache ignores `HYPELAB_ROOT` too (overridable only as a function argument,
`fetch_model(cache_dir=...)`, `align.py:159`).

**Impact.** An operator who relocates with `HYPELAB_ROOT=/data/hl` gets a split
brain: job artifacts under `/data/hl/work/`, the job ledger still at
`/home/dino/hypelab/hypelab.db`, models under the old root. Worse, the default
DB path is *inside the old root*, so the two halves silently disagree about
which jobs exist. Cross-var incoherence is a config-model bug, not just docs.

**Suggested fix:** NEEDS-OWNER — either single-root semantics (DB + model cache
derived from `HYPELAB_ROOT` with `HYPELAB_DB` as explicit override) or document
the split as required behavior. Behavior change → Dino's call.

## ENV-652 — S2 — Missing Python packages and ffmpeg-at-render fail with raw tracebacks

**Evidence.** All heavy ML imports are lazy (`align.py:71,126,165,226-227,264-271`,
`reframe.py:59`, `captions.py:62`, `gates.py:292`) with **no `try/except
ModuleNotFoundError`** and no install hint. A clean machine running
`hypelab audio` without `librosa`/`faster_whisper`, or Book 2 reframe without
`cv2`, gets a bare `ModuleNotFoundError` traceback instead of the CLI's usual
`error:` + exit 1. Separately, `render.py:456`
(`subprocess.run(cmd, …)` — no `FileNotFoundError` catch) and `gates.py:44`
(`_run` — only `TimeoutExpired` is caught, `gates.py:84`) raise raw
`FileNotFoundError` tracebacks when the `ffmpeg` binary is absent.

**Impact.** First-run friction: the CLI is polite for the native binaries the
author anticipated (ffprobe → clean `MediaError`, `util.py:86`; Chromium →
`CarouselError`, `carousel.py:66`; yt-dlp → `WatcherError`, `watcher.py:51`)
but impolite for the entire lazy Python stack, which is the *most likely* thing
to be missing on a fresh machine. An operator cannot tell "install X" from a
real bug. Severity S2 because it hits the exact first-run path on any new
machine (and the 1 AM demo machine is a fresh-ish context).

**Suggested fix:** PRE-APPROVED-safe — wrap lazy imports at first use with a
helper that raises a domain error naming the package and the pip install line;
add `FileNotFoundError` → clean error in `render.py:456` and `gates.py:44`
(same treatment as `util.ffprobe`).

## ENV-653 — S2 — First-run model bootstrap: two hidden HF caches, no offline handling

**Evidence.** `transcribe()` (`align.py:126-131`) calls
`WhisperModel(cfg["model"], …)` with the default `"medium"` (`align.py:84`) —
faster-whisper downloads from the HF hub into **its own cache**
(`~/.cache/huggingface`), separate from the wav2vec2 cache in
`models/` (`align.py:28`). No `try/except` around the constructor; no
`HF_HUB_OFFLINE`/`TRANSFORMERS_OFFLINE` handling anywhere (`grep` → ∅); the
docs give no total download size and no `fetch` pre-step for the ASR model
(unlike `fetch_model()` for wav2vec2). An offline clean machine gets a raw
urllib/ctranslate2 traceback, not the clean `AlignError` the wav2vec2 path
provides (`align.py:182`).

**Impact.** The single heaviest first-run cost (GB-scale "medium" model, minutes
of CPU download+load) is undocumented, un-preflightable (no `doctor` — BLD-003),
and fails with the least actionable error in the pipeline. Two model caches
also double the disk/permission surface for backup and multi-user machines.

**Suggested fix:** NEEDS-OWNER on scope — at minimum document both caches +
sizes and the offline failure; consider a `fetch` CLI step for the ASR model
mirroring `fetch_model()`, or honor `HF_HUB_OFFLINE` with a clean error.

## ENV-654 — S3 — `reframe.py` hardcodes `/tmp/`, ignoring `$TMPDIR`

**Evidence.** `reframe.py:138`:
```python
frame = Path(f"/tmp/hypelab_textcheck_{abs(hash(str(src))) % 10**8}.png")
```
Every other temp file in the codebase goes through `tempfile` (which honors
`$TMPDIR`): `gates.py:95`, `carousel.py:192,292,378,421`. The module docstring
itself references `$TMPDIR` as the temp domain (`util.py:186`).

**Impact.** In sandboxed or hardened environments (`TMPDIR` redirected,
read-only `/tmp`, disk-quota'd `/tmp`) the OCR frame lands in the wrong place
or fails while everything else works — an inconsistent temp policy. Minor
blast radius (one 1080p PNG, deleted after use — verify cleanup), single-user
machine today.

**Suggested fix:** `tempfile.NamedTemporaryFile(dir=os.environ.get("TMPDIR"))`
or `tempfile.gettempdir()` — small, PRE-APPROVED-safe.

## ENV-655 — S3 — Default compute config: "medium" model, forced CPU, no auto-detect

**Evidence.** `DEFAULT_ASR_CFG = {"model": "medium", "device": "cpu",
"compute_type": "int8", …}` (`align.py:84-89`), repeated in the kit seeding
fallback (`kits.py:142`). No CUDA/`torch.cuda.is_available()` probing anywhere
(`grep CUDA|TORCH_ hypelab/` → ∅). On this machine torch is `2.12.1+cu130` but
`cuda.is_available()=False` (BLD-012), so `medium`-on-CPU is the slowest legal
combo; on a GPU machine the default would still run CPU unless the operator
edits the kit JSON.

**Impact.** Silent perf default: first transcribe downloads the largest default
model and runs it on CPU with no warning and no doc estimate. Not a correctness
bug (results are the same, slower), but the config claims no agency the code
doesn't have — a GPU owner gets CPU silently. S3 in the single-user trust
model.

**Suggested fix:** PRE-APPROVED-safe — log the resolved `{model, device,
compute_type}` at transcribe time and document the estimate; NEEDS-OWNER for
auto-detecting CUDA.

## ENV-656 — S4 — `HYPELAB_LEASE_SECONDS` is read at import time and mutates a global

**Evidence.** `cli.py:98-107`:
```python
try:
    _lease_override = int(os.environ.get("HYPELAB_LEASE_SECONDS", "") or 0)
except ValueError:
    _lease_override = 0
if _lease_override > 0:
    queue_mod.LEASE_TTL_S = _lease_override
```
Garbage → silently 0 (no warning); negative → ignored. The read happens once
at import, and it **mutates `queue_mod.LEASE_TTL_S` process-wide** — any test or
long-lived process that sets the var after importing `hypelab.cli` gets no
effect, and a test that sets it poisons the module global for every later test
in the process.

**Impact.** Test-ordering hazard and a confusing operator knob (a typo'd value
is silently a no-op). Low blast radius — test-only variable — hence S4.

**Suggested fix:** read the var per-`work()` invocation (function of `_lease_seconds()`,
already exists at `cli.py:94`) instead of at import; warn on unparsable values.

## ENV-657 — S3 — Mis-set `HYPELAB_DB` / `HYPELAB_ROOT` crash with tracebacks, not `error:`

**Evidence.** `_conn()` (`cli.py:91`) passes `HYPELAB_DB` straight to
`db.connect()`: a path that is a directory → `sqlite3.OperationalError`
traceback; an unwritable parent → `PermissionError` from `p.parent.mkdir`
(`db.py:141`). `work_dir()` (`util.py:173`) similarly `mkdir`s without
handling. Neither is wrapped in the `_die` path the rest of the CLI uses for
config errors (`MediaError`, `ManifestError`, `AlignError` all → `_die`).

**Impact.** Operator typos in the two most important env vars surface as
tracebacks indistinguishable from bugs, while every other config error in the
CLI is a clean `error:` line. Consistent error discipline is part of the
single-user UX contract. S3: only triggers on operator misconfiguration.

**Suggested fix:** PRE-APPROVED-safe — validate `HYPELAB_DB`/`HYPELAB_ROOT` in
`_conn()`/`_repo_root()` and `_die` with a naming-what's-wrong message.

---

### Explicitly NOT findings (verified good — for the record)

- `tesseract` absent → `has_onscreen_text` returns `(None, "unavailable:no-ocr-binary")`
  and mode choice fails closed to `blurpad` (`reframe.py:131-138,264-278`) — the
  cleanest optional-dependency story in the codebase.
- `HYPELAB_CHROMIUM` mis-set → clean `CarouselError` → `error:` exit 1
  (`carousel.py:53-57`, caught `book3cli.py:118`).
- Missing `yt-dlp` → clean `WatcherError` (`watcher.py:50-51`).
- Missing `pysubs2` with captions present → gate FAILs closed with a clear message
  (`gates.py:292-296`), never passes silently.
- Migration-set mismatch → `connect()` refuses to boot with a clear message
  (`db.py:124-130`) — the one place startup config *is* fail-loud.
- No ports: no `socket.bind`/`listen`/`serve_forever` in `hypelab/` — the watcher
  is a poll loop, not a server; there is no HTTP port default to audit.
- No secrets in env: all live variables are paths/durations (agrees with BLD
  Phase 1 env-inventory flags).
