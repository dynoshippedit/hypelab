# HypeLab Test Inventory & Test Plan (TST)

Owner: Test Engineer (TST) · Phase 1 inventory + Phase 3 lens prep.
Date: 2026-09-29. Source is read-only in this phase; this file records
what today's tests prove, what they don't, and what to test next.

Run command: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/`
Reported baseline: 191 passing (BLD owns the authoritative run).

## 1. Inventory — all 8 test files

Every file is an **automated** test (pytest runner + real assertions).
There are no manual/print-only scripts in tests/. Shared trait: no
conftest.py — each file repeats a `sys.path` repo-root hack (TST-011).

| File (lines) | Type | What it really covers (modules) | Headless / offline? | Flakiness / env risks | Assertion quality |
|---|---|---|---|---|---|
| test_align.py (240) | automated | `align`: words_doc contract, timing labels, asr cfg, low_confidence_beats, retime_beats (contiguous/clamp/exhaustion), force_align fail-closed without cache | **PARTIAL**: pure tests OK; `test_transcribe_smoke_short_clip:203` loads real faster-whisper "medium" with NO skip guard (network download + minutes of CPU); `test_fetch_model_cache_present:220` asserts the wav2vec2 cache exists with NO skip guard (fails instead of skipping on a clean box) | TST-005, TST-006. Both depend on `jobs/job_c656669a5147/assets/vo.mp3` (tracked, OK) | Strong. Contract set-equality on words_doc keys, inverted-condition checks (`low_confidence_beats` both polarities, raises on unknown method) |
| test_manifests.py (237) | automated | `manifests`: attach/verify round-trip, sha256-gated attach, out-of-band mismatch → quarantine fail-closed, tamper → quarantine fail-closed, missing asset, render_hash determinism + sensitivity (caption char, provenance, input bytes, order independence), provenance shape, record_render/record_measurement append-only | YES — real ffmpeg/ffprobe but synthetic lavfi sources only, no network | Fixture is module-scoped; media is byte-deterministic from lavfi. `fps == approx(30.0, rel=0.02)` has margin | Strong. Fail-closed quarantine tests assert the exact forensic outcome (bytes preserved, manifest row removed). `test_render_hash_changes_on_caption_char_change` catches hash dilution |
| test_pipeline.py (306) | automated | `edl` validate (gap/overlap/hook rules), `script.to_beats` roles/durations/contiguity, `captions` group_into_cards + build_ass smoke, `kits` seed/load/bump/version immutability, `render.build_command` sidechain filter, `render` missing-clip gate (ffmpeg monkeypatched to explode), `render` + hash-skip (spy asserts ffmpeg never invoked on skip path) | YES — real ffmpeg only in the render tests, synthetic lavfi media | render tests run real encodes (~seconds). `test_build_command_sidechain` is string-presence, not an exact argv assertion | Good. The monkeypatched `subprocess.run` that raises AssertionError is a genuine negative control (gate must fire before ffmpeg runs). The skip test asserts `calls == []` — would catch a cache-bypass regression |
| test_gates.py (421) | automated | `gates`: first_frame (4 regressions incl. corrupt-input fail-closed + frozen-open byte-identical-lossless fixture), duration, loudness (+manifest measurement), hook_budget, slots_filled, geometry, caption_safe (pass/overflow/no-ass), run_all recording (pass + fail), word_confidence (flag/pass/threshold/missing/malformed) | YES — real ffmpeg, synthetic media, no network | Module-scoped fixture encodes ~7 clips incl. 1080x1920 5s x264 (slow, ~1-2 min, not flaky). TST-010: `"5.0"`/`"5.00"`/`"-8"` in `detail` are float-format-coupled at lines 185, 199, 212 | Strong. The frozen-frame regression comments document the old failure mode; fail-closed-on-corrupt is a true inverted-condition test |
| test_foundation.py (506) | automated | `db` migrations (apply/idempotent/set-mismatch/rollback-atomic), pragmas (FK/WAL/indexes), `jobs` state machine (Mode A walk, Book 2 walk, terminal/recovery edges, closed graph), `queue` claim priority/FIFO/lease/heartbeat/release/fail/poison/expiry-reclaim, cost ledger estimate-vs-actual, `util.intake_asset` (roundtrip, mid-copy mutation, missing src), `util.ffprobe` (real/truncated/non-video/missing), FK cascade | YES — one synthetic mp4 for ffprobe only | `test_now_and_new_id` uses real randomness (uniqueness over 200 ids — fine). `test_heartbeat_extends_lease` uses `>=` on timestamps (not `>` — no sleep needed) | Strong. Poison-at-max-attempts asserts the `POISON\|` stamp; mutation-during-copy test is a real TOCTOU negative control |
| test_cli.py (402) | automated | Book 1 CLI end-to-end: migrate, kit new (+duplicate), new/attach/audio/render/gates → `ready`, shots, costs, normalize_numbers (digits), audio-aligns-digits (espeak VO), render skip, 7-gate PASS table, `work --once` claim, **kill -9 crash recovery** with sha256 equality of recovered vs reference render | YES — ffmpeg + espeak-ng (both installed), real subprocesses; no network | Slowest file. Crash test sleeps 12s after an 8s lease; 240×0.25s poll loop (60s cap) for the worker to reach `rendering` — tight if the box is loaded. espeak-ng binary required | Strong. Crash test asserts the partial output does NOT exist at the final path (atomic-output regression) AND byte equality after reclaim — the suite's only cross-process determinism proof |
| test_book2.py (715) | automated | `campaigns` add/validation/provenance round-trip, payout-rate-never-scores data guard, rights fail-closed (no manifest / needs clearance / unknown basis), scoring blind vs full path, NMS, moment dedup, boundary sentence-start, reframe math (blurpad/static/track), compliance (all-pass + each-check-breaks-once + watermark-unknown + provenance-less rules), tray rank/materialize + stale-compliance re-gate pass/exclude, metrics provenance, attribution guards, posted-requires-URL, watcher manual poll + re-dedup, overlays enable | YES — synthetic ffmpeg clips, local listing.json fixture, no yt-dlp | `conn` fixture relies on `db.connect()` auto-migrating (it does — db.py:145-147) | Good. `test_compliance_each_check_breaks_once` is the mutation pattern done right (break exactly one check). Weak spot: `test_payout_rate_never_scores` asserts `"rate" not in json.dumps(w["sets"])` — a substring guard on a data file, brittle if a legitimate weight key ever contains "rate" |
| test_book3.py (700) | automated | migration 0003, state-migration additivity + removal refusal, carousel text-overflow/hook gates (broken-then-fixed), carousel 7-slide render at 1080x1350 via headless Chrome, collab caps (never truncate / UNKNOWN → human review), preflight publicity checks, consent grant (expiry+artifact mandatory, artifact hashing), publish refused without consent / after revoke / after expiry, consent-not-bound-to-media, scheduled-revoke knock-back + re-gating, authorization required for pitch/publish/invite, dry-run zero-network (socket monkeypatched to explode), live-refuses-everywhere, pitch logging/outcomes, voice-match hypothesis labeling, invite poll cycle, priors min_n=8, feed_back, ledger export, CLI smoke (carousel/consent/priors), gate_consent, collab_caps recording | YES — headless google-chrome present, recorded JSON fixtures, no network | `test_cli_carousel_consent_priors_smoke` skips cleanly if kit.json missing | Strong. The zero-network dry-run test replaces `socket.socket` with a bomb — a real negative control. `test_live_path_refuses_everywhere` asserts placement count unchanged after refused live call |

Secrets/live APIs in tests: **none**. All media synthetic; no API keys; no paid
services; yt-dlp paths are explicitly marked NETWORK and never exercised.

Determinism: fixed timestamps (`2026-09-28T00:00:00+00:00`), synthetic media,
no sleeps except the crash-recovery test (12s lease expiry + poll loop).
Only randomness is `util.new_id()` uniqueness (200 draws) — fine.

## 2. Fixtures

- `fixtures/script.txt` (60 words, tracked): drives `_make_job` (5 beats) and
  `_full_pipeline_to_render`; the "aligned 60 words" output assertion is pinned
  to it.
- `tests/fixtures_book2/`: `campaign.json`, `info.json`, `listing.json`,
  `rights.json` (small, hand-written — realistic shapes, fixture URLs
  `fixture.example`), `words.json` (69 KB), `source.mp4` (5.8 MB real clip —
  used by the acceptance run per the docstring, NOT by unit tests).
- `tests/fixtures_book3/`: `dryrun_fixtures.json`, `slides_fixture.json`
  (7-slide carousel spec — realistic).
- `jobs/job_c656669a5147/` (tracked, 17 files): the recorded vertical-slice
  job whose `vo.mp3`/`music.mp3` anchor test_align.py and test_cli.py.
  In-repo binary fixtures — acceptable here (offline suite), but note: any
  future re-encode of these changes nothing in the tests except sha-agnostic
  content checks (VO tokens count is pinned to fixtures/script.txt via
  `_script_tokens`, not to this job's script).

## 3. Crown jewels × coverage

| Crown jewel | Coverage | Gaps |
|---|---|---|
| Consent / publish gate | STRONG — test_book3 (grant/revoke/expiry, no-consent refusal, revoke refusal, live-refuses-everywhere, zero-network dry-run, gate_consent) | Book3 CLI publish/pitch/consent grant+revoke paths untested (TST-009) |
| Job queue integrity | PARTIAL — claim/lease/heartbeat/release/fail/poison single-connection tested; `--once` + kill-9 recovery tested | Two-process claim race untested (TST-007); worker retry/requeue path absent AND untested (TST-003) |
| Render determinism + EDL validation | GOOD — EDL rules (gap/overlap/hook), render_hash sensitivity, bit-equality via crash test | No explicit double-render determinism test at API level (S3, crash test covers); render determinism across ffmpeg builds untested (S4) |
| Quality gates | STRONG — test_gates (all 7 + word_confidence, fail-closed regressions) | None material |
| SQLite data integrity | PARTIAL — migrations idempotent/rollback-atomic, FK cascade, WAL/FK pragmas | Multi-writer WAL behavior untested (S3); backup/restore untested (S4) |

## 4. Critical flows × coverage

1. `new → attach → align → render → gates → asset_ready` — COVERED end-to-end
   in test_cli.py (`_full_pipeline_to_render` + 7-gate PASS + `ready` state).
2. `publish → consent gate → dry-run` (+ REFUSED paths) — COVERED at API level
   in test_book3.py. Not covered via the operator CLI (TST-009).
3. `kit new → appearance lock` — PARTIAL. Pinning at creation is asserted only
   as the `kit_ref` string in render.json; no test bumps a kit mid-flight and
   re-renders the old job to confirm the old version's appearance/captions
   are used (TST-004).
4. `queue worker enqueue → lease → execute → retry` — BROKEN CHAIN.
   enqueue/lease/execute covered (`work --once`, crash recovery). Retry:
   `queue.fail()` always sets state='failed'; its docstring says "the work
   loop may re-queue it while attempts remain" but nothing in `cli.py work`
   implements re-queueing. Untested AND possibly unimplemented (TST-003).

## 5. Prioritized test plan (risk × ease)

Order by (crown-jewel risk) × (ease of writing). All are pure pytest, no new
infra; mocking strategy per item.

1. **Two-process claim race** (TST-007; queue integrity; EASY-MEDIUM).
   Two `sqlite3` connections (or `multiprocessing`) claim from one queued set;
   assert no job is handed to both owners and leases are distinct. Uses the
   real WAL DB — no mocks. Catches a real double-execution risk on the
   busiest path.
2. **Unguarded model tests → skip** (TST-005/006; suite reliability; EASY).
   Put `test_transcribe_smoke_short_clip` and `test_fetch_model_cache_present`
   behind the existing `needs_cache` skipif (or a `needs_whisper` marker).
   Zero risk to coverage; removes the only network-touching tests from CI.
3. **Kit appearance lock across bump** (TST-004; flow 3; EASY).
   `new` → bump kit captions → `render` the old job → assert the render's
   caption style/size came from v1 (kit_ref `cerebratico@1` in render.json +
   ASS content). Pure SQLite + ffmpeg; no mocks.
4. **signals.py unit tests** (TST-001; scoring inputs; EASY).
   `extract_heatmap` (valid/missing/partial info), `comment_timestamps`
   (timestamp regex, non-English text missed silently — pin that behavior),
   `have_tier3`. Pure functions, hand-made dicts — no mocks, fast.
5. **book3cli publish + consent CLI** (TST-009; crown jewel via operator path;
   MEDIUM). CliRunner against isolated DB: `publish` without consent →
   non-zero exit + refusal text; `consent grant` + `publish` → dry-run row;
   `consent revoke` + `publish` → refused. Reuses the `_publishable` pattern
   from test_book3.py.
6. **b2cli commands** (TST-002; MEDIUM). CliRunner: `campaign add` validation
   errors, `source add` unknown-basis rejection, `watch --once` on a file://
   listing, `tray` materialization. The yt-dlp paths stay untested by design;
   use the manual-kind fixtures.
7. **Worker failure path** (TST-003; MEDIUM). Invoke `work --once` on a job
   whose handler raises (monkeypatched `_handle_render`); assert state lands
   in `failed` with the error recorded and the poison stamp at max attempts —
   then decide the product question (auto-requeue vs operator) in QUESTIONS.md.

### How to mock external services

- **ffmpeg/ffprobe** (already the pattern): generate synthetic lavfi media in
  module-scoped fixtures; for negative control, `monkeypatch.setattr(
  render_mod.subprocess, "run", boom)` so ffmpeg must not run
  (test_pipeline.py: `test_render_missing_clip_gate`).
- **whisper/wav2vec2**: never load in unit tests. The suite's current split is
  right — pure-contract tests + explicitly-marked model tests — except the
  two unguarded ones (fix in #2). For new alignment-adjacent tests, feed
  hand-made `words` docs (test_align.py's `_mk_words` pattern).
- **edge-tts / VO synthesis**: there is no TTS module in hypelab/ — VO always
  arrives as a file. Nothing to mock; keep it that way (file-in, never a
  network call in the pipeline).
- **network (publish adapters, yt-dlp, RSS)**: the bomb pattern —
  `monkeypatch.setattr(socket, "socket", bomb)` (test_book3.py zero-network
  test). yt-dlp/RSS paths are declared NETWORK and untested by design; test
  only the rights-gate that guards them (`require_rights` fail-closed).
- **Chromium (carousel)**: headless `google-chrome` is installed; keep the
  render test but mark it slow. If CI lacks Chrome, gate behind a skipif
  like `needs_cache`.

### Test-data management

- One `conftest.py` (TST-011) replacing the 8 copies of the sys.path hack;
  shared fixtures: `db` (migrated tmp DB), `camp` (Book 2 campaign),
  `tiny_916`/`tiny_169` (move from test_book2), `media` (per-file for now —
  the ffmpeg recipes differ).
- Fixture policy: synthetic-first (lavfi), recorded-second (jobs/ vertical
  slice), hand-written JSON for shapes (fixtures_book2/3). Never live URLs,
  never live APIs.
- Keep model-dependent tests quarantined behind skip markers and runnable
  with the model caches present; the default CI path must be fully offline.

## 6. Open questions / judgment calls

- TST-003's retry question is a product decision, not just a test gap —
  logged to QUESTIONS.md by the Lead (auto-requeue vs operator review).
- The 191-test baseline count is BLD's number; TST did not rerun the suite.
- Slow-file budget: test_cli.py (crash test + full pipelines) and test_gates.py
  (1080x1920 encodes) dominate wall time; consider `-m "not slow"` markers
  in Phase 5 if the suite grows past ~10 min.
