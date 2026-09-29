# TST findings — Test Engineer

Phase 1 inventory + Phase 3 coverage mapping. IDs TST-001…TST-049 reserved
for this lane. Severity per Playbook B7; confidence per B7.
Source read-only in this phase — all "Confirmed" below rest on unambiguous
code/test text with cited lines.

## Ledger

| ID | Title | Sev | Confidence | Status |
|---|---|---|---|---|
| TST-001 | signals.py has zero test coverage (heatmap/timestamp extractors feed scoring) | S2 | Confirmed | NEW |
| TST-002 | b2cli.py — all Book 2 CLI commands untested | S2 | Confirmed | NEW |
| TST-003 | Worker retry path absent and untested; queue.fail docstring claims a re-queue the work loop never performs | S2 | Confirmed | NEW |
| TST-004 | Kit appearance lock across a mid-flight bump is untested | S2 | Confirmed | NEW |
| TST-005 | test_transcribe_smoke_short_clip has no skip guard — downloads/loads faster-whisper "medium" on every run | S2 | Confirmed | NEW |
| TST-006 | test_fetch_model_cache_present has no skip guard — fails instead of skipping on a clean machine | S2 | Likely | NEW |
| TST-007 | Claim atomicity tested single-connection only; two-process race untested (queue integrity crown jewel) | S2 | Confirmed | NEW |
| TST-008 | ingest(conn, job_id, work) full entry + _handle_ingest worker path untested | S2 | Confirmed | NEW |
| TST-009 | book3cli publish/pitch/consent CLI ops untested (only a smoke test) | S2 | Confirmed | NEW |
| TST-010 | Gate tests assert on float-formatted detail strings ("5.0", "5.00", "-8") — brittle coupling | S3 | Confirmed | NEW |
| TST-011 | No conftest.py; 8 copies of the sys.path repo-root hack | S3 | Confirmed | NEW |
| TST-012 | Render bit-determinism only proven via the crash-recovery test; no explicit API-level double-render test | S3 | Confirmed | NEW |

---

### TST-001 — signals.py has zero test coverage
- **Severity:** S2 (scoring inputs — wrong behavior in edge cases).
  Confidence: Confirmed.
- **Evidence:** `hypelab/signals.py` defines `extract_heatmap` (:29),
  `comment_timestamps` (:63), `have_tier3` (:114). `grep -rn "signals" tests/`
  shows no import of `hypelab.signals` anywhere; test_book2.py feeds
  hand-made signal dicts straight into `score_mod.score_windows`, bypassing
  both extractors.
- **Why it matters:** the module docstring states real limitations the code
  must honor — "None is a NORMAL outcome", "Never synthesize a heatmap",
  English-pattern dependence of the timestamp regex `TS`. None of these
  contracts is pinned. A regression that synthesizes a heatmap from nothing
  would silently poison scoring and no test would fire.
- **Fix (Phase 5):** unit tests with hand-made `info` dicts: valid heatmap,
  missing → None, partial; timestamp extraction incl. non-English text
  (pin the silent-miss behavior); `have_tier3` true/false. Pure functions,
  no mocks. Effort: S.

### TST-002 — b2cli.py: all Book 2 CLI commands untested
- **Severity:** S2 (core feature — the entire Book 2 operator surface).
  Confidence: Confirmed.
- **Evidence:** `hypelab/b2cli.py` defines CLI commands `campaign add/list/
  show/bump-rules/refresh-budget` (:81-133), `source add/clearance/list`
  (:154-199), `watch` (:216), `moments` (:235), `cut` (:261), `tray` (:292),
  `posted` (:319). No test file imports `b2cli`; test_book2.py tests the
  underlying modules only.
- **Why it matters:** CLI is the operator interface; argument parsing,
  error messages, and exit codes are user-visible behavior with zero
  verification. E.g. `source add` with an unknown rights basis is rejected
  at the API level (tested) but the CLI wiring is not.
- **Fix (Phase 5):** CliRunner tests with isolated DB: validation errors,
  unknown-basis rejection, `watch --once` against a file:// listing,
  `tray` materialization. yt-dlp paths stay untested by design. Effort: M.

### TST-003 — Worker retry path absent and untested
- **Severity:** S2 (documented critical flow (4) "enqueue → lease →
  execute → retry" is broken at "retry"; doc materially misleads).
  Confidence: Confirmed.
- **Evidence:** `hypelab/queue.py:172-180` — `fail()` docstring: "below the
  limit the work loop may re-queue it while attempts remain." But
  `hypelab/cli.py:885-940` (`work` loop) on handler exception calls only
  `queue_mod.fail(conn, job_id, owner, e)` and never re-queues; `fail()`
  unconditionally sets `state='failed'` (queue.py:196-201). No re-queue
  exists anywhere (`grep -rn requeue hypelab/` hits only the docstring).
  test_foundation.py's poison test manually re-queues via SQL
  ("the work loop re-queues while attempts remain" comment at
  test_foundation.py:~test_fail_marks_poison_at_max_attempts) — the test
  itself documents behavior the loop doesn't have.
- **Why it matters:** a transient failure (e.g. ffmpeg OOM) permanently
  parks the job in `failed` with no automatic retry, contradicting the
  documented flow. This is also a product decision (auto-requeue vs
  operator review) — recommend a QUESTIONS.md entry.
- **Fix:** decide the policy first; then test the `work --once` failure
  path (monkeypatched handler raising → assert `failed` + error recorded,
  poison stamp at max attempts). Effort: M (test) + owner decision.

### TST-004 — Kit appearance lock across a mid-flight bump is untested
- **Severity:** S2 (critical flow (3) "kit new → appearance lock"
  partially untested). Confidence: Confirmed.
- **Evidence:** Pinning happens at creation — `hypelab/cli.py:new`
  writes `kit_ref=f"{kit_id}@{kit['version']}"` and
  `kit_version=kit["version"]`. test_cli.py: `test_new_creates_job_and_beats`
  asserts the `kit_ref` string in render.json only. No test bumps a kit
  (`kits_mod.bump`, tested in test_pipeline.py in isolation) between `new`
  and `render` and checks the old job renders with the OLD captions/
  appearance.
- **Fix (Phase 5):** `new` → `bump` (change caption size) → `render` old job
  → assert ASS content reflects v1. Effort: S.

### TST-005 — test_transcribe_smoke_short_clip has no skip guard
- **Severity:** S2 (only network-touching test in the suite; slow; fails
  offline). Confidence: Confirmed.
- **Evidence:** tests/test_align.py:203 — calls
  `transcribe(clip, {"model": "medium"})` with no skipif; sibling model
  tests use `@needs_cache` (defined :39) but this one doesn't. Loading
  faster-whisper "medium" downloads weights if absent and takes minutes
  on CPU. The file's own docstring admits "Real models, real audio".
- **Fix (Phase 5):** guard with a whisper-cache check like `needs_cache`.
  Effort: XS.

### TST-006 — test_fetch_model_cache_present has no skip guard
- **Severity:** S2 (suite fails instead of skipping on a clean machine).
  Confidence: Likely (one unverified assumption: BLD's baseline ran with the
  cache present — the comment "fetch_model ran before the suite" at
  tests/test_align.py:220 says the cache is an environment precondition,
  not something the suite establishes).
- **Evidence:** tests/test_align.py:220-225 asserts the wav2vec2 cache
  files exist, unguarded.
- **Fix (Phase 5):** same skipif as TST-005, or call `fetch_model` in a
  session fixture. Effort: XS.

### TST-007 — Claim atomicity: two-process race untested
- **Severity:** S2 (crown jewel: job queue integrity; data-integrity risk —
  double execution of a render). Confidence: Confirmed.
- **Evidence:** test_foundation.py: `test_claim_hands_out_distinct_jobs_
  atomically` uses ONE connection sequentially. The real deployment is
  multiple workers = multiple processes/connections against one WAL DB.
  No test opens two connections and races `queue.claim`.
- **Fix (Phase 5):** two `sqlite3` connections (or multiprocessing workers)
  claim from the same queued set; assert disjoint ownership. Effort: S.

### TST-008 — ingest() full entry + _handle_ingest worker path untested
- **Severity:** S2 (ingest is a claimed pipeline stage with zero
  end-to-end coverage). Confidence: Confirmed.
- **Evidence:** `hypelab/ingest.py:223 ingest(conn, job_id, work)` (fixture
  kinds: metadata → transcribe → signals) and `hypelab/cli.py:867
  _handle_ingest` have no tests; test_book2.py covers only
  `require_rights` fail-closed. Network kinds (`ytdlp_*`) are correctly
  out of scope; the fixture/manual path is not.
- **Fix (Phase 5):** `ingest()` on a manual source with the
  tests/fixtures_book2 `listing.json`-style fixture, monkeypatched
  `_transcribe_words`; assert words doc + signals written. Effort: M.

### TST-009 — book3cli publish/pitch/consent CLI ops untested
- **Severity:** S2 (crown jewel consent/publish gate via the actual
  operator interface). Confidence: Confirmed.
- **Evidence:** `hypelab/book3cli.py` defines `authorize` (:81),
  `carousel` (:101), `publish` (:138), `consent` (:186), `pitch` (:253),
  `invite` (:297), `feedback` (:321), `priors` (:336). Only
  `test_cli_carousel_consent_priors_smoke` (test_book3.py) touches them —
  carousel render, consent export, priors. `publish` refusal/consent
  flows via CLI: zero.
- **Fix (Phase 5):** CliRunner on isolated DB: publish w/o consent →
  non-zero + refusal; grant → publish → dry-run row; revoke → publish →
  refused. Reuse test_book3's `_publishable` pattern. Effort: M.

### TST-010 — Float-format-coupled assertions in gate tests
- **Severity:** S3 (brittle tests, not wrong behavior). Confidence: Confirmed.
- **Evidence:** tests/test_gates.py:185 (`"5.0" in detail`), :199
  (`"-8" in detail and "-14" in detail`), :212 (`"5.00" in detail and
  "2.0" in detail`). A formatting change in the gate detail string
  (e.g. rounding 5.0 → 5) breaks the test without any behavior change.
- **Fix (Phase 5):** assert on parsed numbers or looser substrings
  ("duration" + "exceeds") where the point is the verdict, keep one
  exact-format test per gate if the format is a contract. Effort: S.

### TST-011 — No conftest.py; sys.path hack repeated 8×
- **Severity:** S3 (maintainability; hygiene). Confidence: Confirmed.
- **Evidence:** every tests/test_*.py contains its own
  `sys.path.insert(0, <repo root>)` (test_align.py:14, test_book2.py:18,
  test_book3.py:19, test_cli.py:26, test_foundation.py:16,
  test_gates.py:21, test_manifests.py:17, test_pipeline.py:17).
- **Fix (Phase 5):** one `conftest.py` with the path fix + shared fixtures
  (`db`, `camp`, `tiny_916`/`tiny_169`). Effort: S.

### TST-012 — Render bit-determinism only proven via crash test
- **Severity:** S3 (crown jewel render determinism; covered indirectly).
  Confidence: Confirmed.
- **Evidence:** the only byte-equality assertion is
  test_cli.py:`test_worker_crash_recovery_sha256` (recovered render ==
  reference render). test_pipeline.py:`test_render_and_skip` asserts the
  skip path never invokes ffmpeg, so no second render happens there.
- **Fix (Phase 5):** render the same EDL twice via the API (fresh work
  dirs) and assert byte-identical outputs. Cheap, fast with tiny media.
  Effort: S.
