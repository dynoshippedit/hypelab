# Integrations — HypeLab (Phase 2, DAT, 2026-09-29)

Owner: DAT. Method: read every call site; no live third-party calls made during
review (per playbook). Verdicts: REAL = actually invoked by code; STUB = present but
refuses/fixture; HONEST = stub is explicit and labeled (the codebase's own bar).

| # | Service | Kind | Verdict | Auth / secrets | Rate limits | Timeouts | Retries | Response validation | Mock/fallback honesty |
|---|---|---|---|---|---|---|---|---|---|
| 1 | **faster-whisper** (ASR, `hypelab/align.py:114-153` `transcribe()`) | Local in-process model | REAL (Book 2 ingest path) | None (local) | N/A | None on transcribe; model load unbounded | None | Word fields rounded to 3dp; `w.probability` used; no model-output schema validation beyond attribute access | Model auto-downloads from HF Hub on first use — **unguarded**: no checksum, no `revision` pin, no size limit. Module docstring claims `fetch_model` is "the ONLY function in this module allowed to touch the network" (`align.py:14-16`) — false for `transcribe()` → DAT-364 (S2). Default model `medium`, cpu, int8 (`DEFAULT_ASR_CFG`, `align.py:78-83`); overridable per kit `asr` block. |
| 2 | **wav2vec2 forced align** (`facebook/wav2vec2-base-960h`, `hypelab/align.py:158-174` `fetch_model()`) | One-time HF download | REAL | None | N/A | None passed to `from_pretrained` (transformers default) | None (transformers/hf-transfer default) | `_check_cache` requires `config.json` + weights file before use (`align.py:176-183`) | Explicit one-time fetch; no checksum verification of downloaded weights; no `revision` pin (tracks latest). S2 note inside DAT-364. |
| 3 | **edge-tts** | — | NOT REAL | — | — | — | — | — | **Never called by any code** — zero hits in `hypelab/` and `tests/` (grep-verified); appears only in README.md, ARCHITECTURE.md, VERTICAL_SLICE_REPORT.md. README's `doctor` comment and setup steps name it. HONEST-by-absence in code, but docs imply a dependency (DOC lane; MAP §2 already records it). |
| 4 | **ffmpeg / ffprobe** (41 subprocess call sites, 11 modules; `hypelab/util.py:59-94`, `hypelab/render.py:26,467`) | Local binaries, argv arrays, never `shell=True` | REAL | None | N/A | `FFMPEG_TIMEOUT=600` on renders (`render.py:26`); ffprobe timeouts handled → `MediaError`; carousel `_run` timeout 120s; yt-dlp 120s | None — single attempt; failure raises | ffprobe JSON parsed with `MediaError` on non-JSON (`util.py:94`); argv elements validated as non-empty strings (`render.py:361-363`); render output re-probed before rename; PID-unique temp + atomic `os.replace` | Version recorded into provenance (`manifests._ffmpeg_version`, `manifests.py:82`) but **no minimum-version check** — behavior with an old ffmpeg is untested (S4). Missing binary → `MediaError`/`WatcherError`, fail-closed. |
| 5 | **Headless Chromium** (Book 3 carousel HTML→PNG, `hypelab/carousel.py:50-70`) | Local binary | REAL | None | N/A | 120s per run | None | PNG existence checked downstream (carousel gates) | Binary discovery: `HYPELAB_CHROMIUM` env → `shutil.which` names → `/opt/pw-browsers/chromium`; hard fail with message when absent. **Env var undocumented** (BLD-008). Slide text is `html.escape`d (`carousel.py:113`); kit CSS values interpolated raw (operator-supplied; S4). |
| 6 | **Publish adapters — meta** (`hypelab/publish/meta.py`) | Instagram Graph API | STUB (live refuses) | None stored; live path requires "explicit authorization row AND provider credentials — neither exists" (`meta.py:63-70`) | N/A (no live calls) | N/A | N/A | Capability record pinned: max 5 collaborators, `is_ai_generated` on container, docs URL verified 2026-09-28 (`meta.py:40-55`) | HONEST: `create_post(dry_run=False)` raises `LiveRefused` with a message naming the gating requirements. |
| 7 | **Publish adapters — postiz/zernio/ayrshare** (`hypelab/publish/providers.py`) | Third-party schedulers | STUB (live refuses) | None stored | N/A | N/A | N/A | Versioned capability records in `collab_caps` table; NULL cap → human review (`base.py:53-73`) | HONEST: live raises `LiveRefused`; dry_run delegates to fixture backend. |
| 8 | **Publish adapters — dryrun** (`hypelab/publish/dryrun.py`) | Recorded fixtures | REAL (the only working backend) | None | N/A | N/A | N/A | Fixtures are static JSON; missing entries return `{"post_id":…, "dry_run": True}` / `{"views": None, "provenance": "fixture"}` | HONEST: fixture post ids prefixed `dryrun_` (deterministic sha256 of inputs); `post_placements` ledger records `dry_run=1`, fixture request/response JSON, `post_id=NULL`; dry_run posts get `dryrun://` URLs (`publish/__init__.py:217-236`). |
| 9 | **Metrics polling** (`hypelab/metrics.py:34-43` `fetch_metrics`) | Provider APIs | STUB | None | N/A | N/A | N/A | — | HONEST: ships with no provider integrations; `fetch_metrics` returns `(None, "unavailable")` and `poll_metrics` writes NULL-measure rows with `provenance='unavailable'` — absence recorded as data, not papered over. **BUT** two integrity holes: (a) `feed_back` consumes metrics with no provenance filter (DAT-350); (b) `invites.poll_invite_metrics` writes recorded fixtures with `provenance='provider_api'` (DAT-351). |
| 10 | **Invite-status polling** (`hypelab/invites.py:118-165` `poll()`) | Via publish adapter's `get_collaborator_status` | STUB (fixture-backed in practice) | None | Adapter-limited; cadence documented (30min/24h → hourly/72h → accept_timeout) but not scheduled — poll is manual/CLI-driven | None on adapter call | None; adapter exception → `checked_at` bumped, continue (`invites.py:147-150`) | Status allowlisted to accepted/declined/pending; unknown strings ignored (`invites.py:156-157`); handle matched case-insensitively with `@` stripped | HONEST about fixture backing in docstring; `poll_invite_metrics` (fixture→metrics writer) is currently **unwired** — no CLI calls it (dead code, S2 note in DAT-351). |
| 11 | **Source watcher — yt-dlp** (`hypelab/watcher.py:39-63`) | Subprocess, NETWORK | REAL (not exercised in tests — docstring says so) | None | Source-configured `poll_every_s`, floored at `MIN_POLL_EVERY_S=300` (`watcher.py:31,178`); no per-host rate limiting | 120s subprocess timeout | None — failure raises `WatcherError` | Each stdout line JSON-parsed; unparsable lines skipped (`watcher.py:56-61`) — tolerant but silent | Explicitly labeled "NETWORK. Not exercised in tests." Missing binary → `WatcherError`. |
| 12 | **Source watcher — RSS/Atom** (`hypelab/watcher.py:66-106`, `urllib.request.urlopen`) | HTTP, NETWORK | REAL | None | Same poll floor as above | 30s (`watcher.py:71`) | None | `ET.fromstring` parse; missing fields → None/""; tolerant to shape drift | Default `urllib` User-Agent (`Python-urllib/3.x`) — no custom UA (S4). **No URL allowlisting at add time** — any `rss` URL accepted, including `file://` (local file read into listings) and internal hosts (SSRF-ish, operator-only; S3 note). XML entity-expansion (billion-laughs) not mitigated in `ET.fromstring` (S3 note). |
| 13 | **Source watcher — manual listing** (`hypelab/watcher.py:109-121`) | Local JSON file | REAL (the only lister exercised in tests) | None | N/A | N/A | N/A | Requires `{"items": [...]}` shape; raises `WatcherError` otherwise | The honest offline path. |

## Cross-cutting notes

- **No HTTP client library** (no `requests`/`httpx`); network surface is
  `urllib.request` (RSS), `yt-dlp` subprocess, and HF-hub downloads
  (transformers/faster-whisper). No connection pooling, no shared retry/backoff
  policy anywhere.
- **Terms/licensing:** faster-whisper model weights are third-party artifacts
  downloaded at runtime (OpenAI Whisper weights via HF); no license notice
  recorded in-repo. yt-dlp usage for listing public playlists/RSS is the
  operator's own fetching; the rights-manifest gate (`watcher.add_source`
  requires a `basis`) is the legal control — verified enforced in code.
  Wikipedia/CC attribution: not applicable — no Wikipedia/Fandom content used
  (carousel text is operator/kit-supplied).
- **Secrets:** no auth layer, no tokens, no credentials in code or seeds
  (grep-verified: no `token`/`secret`/`password`/`api_key` in `hypelab/` outside
  tests naming fixture fields — and none found there either). Nothing to rotate.
- **Mock/fallback honesty verdict:** the codebase's own bar ("explicit and
  labeled") holds for publish (LiveRefused), metrics ("unavailable" rows), and
  dry-run (dryrun_ ids, dry_run=1 ledger) — with the two recorded exceptions
  DAT-350 (feed_back ignores provenance) and DAT-351 (fixtures labeled
  provider_api).
- **Environment variables read by code:** `HYPELAB_DB` (db path override,
  `cli.py:91`), `HYPELAB_ROOT` (work-dir root), `HYPELAB_CHROMIUM` (carousel
  binary; undocumented, BLD-008), `FIXTURE_WIKIPEDIA` n/a (other repo — ignore).
