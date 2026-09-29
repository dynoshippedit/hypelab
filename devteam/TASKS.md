# TASKS — authoritative engineering queue (HypeLab)

Triage completed 2026-09-29 (hl-cycle-01) per Engineering Kit v3.0 Phase 5.
Source: `devteam/findings/*.md` (200 findings, 15 lanes, Phases 1–3).
Phase 4 triage lanes were spawned but their reports never arrived (Tech Lead
closed on kit switchover); this ledger re-derives triage directly from the
durable lane findings. Every finding ID is accounted for exactly once —
deduplicated entries name all merged IDs.

Severity scale (kit): S0 critical · S1 core workflows fail / important
boundaries violated under realistic conditions · S2 material defect, limited
scope/workable mitigation · S3 minor / maintainability with concrete
consequences / docs · S4 info/hygiene · Idea. Confidence: Confirmed / Likely /
Suspected. Statuses: READY · IN PROGRESS · IMPLEMENTED · VERIFIED · BLOCKED ·
DEFERRED · REJECTED.

## Triage challenges (independent, this cycle)

- **BLD-008 S1 → S3.** Undocumented `HYPELAB_CHROMIUM` selecting the executed
  binary was filed S1 per a "pick the higher severity when torn" rule.
  Challenged: mitigations in place (`Path.is_file()` check, argv array, no
  `shell=True`, clean `CarouselError` on mis-set — ENV lane verified);
  single-user local-CLI trust model (only the operator controls the env);
  realistic impact is operator confusion / doc gap, not compromise. S3.
  Fix = document it (also covers DOC-024's HYPELAB_CHROMIUM row).
- **BUG-006 stays S1, confidence Likely.** Race proven by code shape
  (deferred-locking autocommit, no state re-check in outer UPDATE), not
  executed live. Verification must include a two-process claim race test.
- **MAP-001 / BLD-010 deduped** — same root (tracked job outputs ~34–39 MB);
  single task, needs owner approval to `git rm`.
- **BUG-009 / DAT-352 deduped** — `queue.charge()` zero production callers.
- **BUG-007 / TST-003 deduped** — `fail()` docstring promises a re-queue the
  loop never performs; needs owner policy decision (already in QUESTIONS.md).
- **ARC-307 / REV-750 deduped** — source-kind registry in three places.
- **REV-706 / SEC-102 deduped** — authorizations never expire / no revoke.
- **SEC-100 / DAT-362 merged** — consent expiry format never validated.
- **BLD-002/DOC-004, BLD-003/DOC-001, BLD-005/DOC-005** merged into the
  README-rewrite group (also absorbs MAP-002's README rows).
- **ENV-650 / BLD-001 merged** — dependency manifest + version floors.
- **REV-718 merged into BUG-003** — 4th instance of "CLI drive parks jobs in
  active states with NULL leases" (Book 2 `cut`).
- **ARC-300 kept as architectural follow-up** to BUG-003 (single align
  orchestrator), not merged — different change shape (refactor vs repair).

## Queue

### T-001 — Campaign CLI commands repaired (ARC-301 S1, REV-700 S2, REV-701 S4)
- Status: **VERIFIED** (hl-cycle-01; controller re-ran: 6/6 focused + 197/197 full suite green, exit 0)
- Root: `/home/dino/hypelab`
- Problem: `campaign bump-rules` can never succeed (passes operator *string*
  as the `provenance` dict `bump_rules` requires — every invocation raises
  CampaignError); `campaign refresh-budget` passes the budget *dict* as
  `seen_usd: float` → uncaught `TypeError` traceback; `campaign list` crashes
  with `KeyError: 'status'` (schema column is `state`); `campaign show`
  catches `KeyError` but `campaigns.load` raises `CampaignError`.
- Evidence: independently verified 2026-09-29 against `hypelab/b2cli.py:93-147`
  vs `hypelab/campaigns.py:119-170` and schema
  `migrations/0001_book1_foundation.sql:108-121`.
- Acceptance: `add → list → show → bump-rules → refresh-budget` all exit 0
  on a scratch DB; rules_version increments; provenance recorded;
  `budget_seen_usd`/`budget_checked` updated; unknown id → clean `error:` exit 1.
- Implementation: build `{who, source_url, captured_at}` provenance in
  `bump-rules` (source_url = rules file path); accept raw-number or
  `{"budget_seen_usd": …}` JSON in `refresh-budget`, extract float, `_die`
  cleanly otherwise; `list` prints `state`; `show` catches `CampaignError`.
- Verification: new `tests/test_b2cli_campaigns.py` (CliRunner, isolated
  HYPELAB_DB); full suite `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1
  /home/dino/.local/bin/pytest tests/ -q` before/after.

### T-002 — feed_back() provenance filter (DAT-350 · S1/Confirmed)
- Status: **VERIFIED** (hl-cycle-02; controller: new tests FAIL pre-fix + PASS post-fix, full suite 199/199 green)
- Evidence: 2 new regression tests FAILED on unfixed code (reproduced DAT-350:
  user_entered MAX 99999 consumed instead of official 100; uncalibrated-only
  post consumed), PASS after fix; full suite 199 passed / 0 failed / 3 warnings
  (exit 0, 174s). Fix: `AND provenance IN ('official_api','provider_api')`
  in `_best_views`, reusing `CALIBRATION_PROVENANCES` exactly as
  attribution.py:57. Only caller is feed_back(); priors()/best_value() read
  what_worked only. Note for controller: metrics.best_views() (latest,
  provenance-ranked) vs feedback._best_views (MAX) differ in aggregation
  semantics — minimal predicate fix applied per task; no behavior change
  beyond excluding uncalibrated rows. Problem: `_best_views` consumes metrics with no provenance
  predicate, violating the calibration rule (`metrics.py:12`); uncalibrated
  rows (user_entered, fixtures) can become applied production priors.
- Fix: `AND provenance IN ('official_api','provider_api')` in
  `hypelab/feedback.py:40-46`, mirroring `attribution.py:57-68`.
- Verify: unit test seeding user_entered + official_api rows → only official
  feeds priors; full suite green.

### T-003 — SystemExit from _die kills the worker (BUG-001 · S1/Confirmed)
- Status: **VERIFIED** (hl-cycle-03; controller: tests falsifiable vs old code, full suite 203/203 green). Problem: `_die` raises SystemExit (BaseException); work-loop guard is
  `except Exception` (`cli.py:928`) → deterministic failures kill the worker,
  lease orphaned, failure never recorded. Fix: dedicated `CliError(Exception)`
  from `_die`, or `except BaseException` minus KeyboardInterrupt. Test:
  monkeypatched handler raising via `_die` → state `failed`, worker alive.

### T-004 — CLI drive parks jobs in active states with NULL leases (BUG-001? no: BUG-003 · S1/Confirmed; + REV-718 S3)
- Status: READY. `audio`/`render`/`gates`/`cut` move to active states then
  `_die`/traceback on failure; jobs unrecoverable without SQL (claim requires
  non-null lease; no CLI path out of aligning/rendering/gating/cutting).
- Fix: on CLI-drive failure, transition to `failed` (fail-equivalent) or
  restore prior queued state. Effort M. ARC-300 (single align orchestrator)
  follows as the structural fix.

### T-005 — Render hash-skip wedges job in `rendering` (BUG-002 · S1/Confirmed)
- Status: READY. Skip path returns with state untouched after the caller moved
  `queued_render → rendering`; `rendering` not claimable (lease cleared).
- Fix: on skip from `rendering`, transition `rendering → rendered →
  queued_gates`. Test: gate_failed → audio (same media) → render → assert
  `queued_gates`.

### T-006 — Low-confidence → gate_failed routing is dead code (BUG-004 · S1/Confirmed)
- Status: READY. `_do_align` calls `low_confidence_beats(min_word_prob=0.0)` —
  always returns empty → `flagged` unreachable. Fix: iterate all beats for
  the mean computation. Test with stubbed low-p words → `gate_failed`.

### T-007 — claim() double-claim race; fail() TOCTOU (BUG-006 · S1/Likely; + TST-007 S2)
- Status: READY. Outer UPDATEs don't re-check state; `fail()` UPDATE lacks
  `AND lease_owner=?`. Fix: add predicates, check rowcount, treat empty
  RETURNING as lost race. Verify: two-process claim race test (TST-007).

### T-008 — gate_word_confidence misattributes words to beats (BUG-005 · S1/Confirmed)
- Status: READY. Gate maps original-line beats onto normalized word stream
  (number expansions shift every later beat); min-vs-mean statistic mismatch.
  Fix: persist normalized lines / per-beat word index ranges at align time;
  align gate statistic with book (mean). Test with "1999"/"20%" script.

### T-009 — No model caching: every job reloads wav2vec2/Whisper (PRF-500 · S1/Confirmed)
- Status: READY. Process-lifetime cached loader (`lru_cache` keyed on
  cache_dir/model), explicit invalidation hook. Effort M. Note:
  `test_align.py:43` skips model tests when cache absent — add a
  cache-hit unit test that doesn't need the model.

### T-010 — No dependency manifest (BLD-001 S1 + ENV-650 S2 · Confirmed)
- Status: READY. Pin the ten recorded third-party deps from
  `devteam/notes/dependencies.md` into `requirements.txt` (no upgrades);
  document native minimums (ffmpeg, Chromium, tesseract, yt-dlp).
- Verify: `pip install -r requirements.txt --dry-run` resolves; import smoke.

### T-011 — Worker retry path absent; fail() docstring lies (BUG-007+TST-003 · S2/Confirmed)
- Status: **BLOCKED** — owner policy decision in QUESTIONS.md (auto-requeue
  vs operator review). After decision: implement re-queue below MAX_ATTEMPTS
  or correct docstring + add CLI retry command.

### T-012 — CLI `gates` accepts worker-claimed `gating` (BUG-008 · S2/Confirmed)
- Status: READY. Refuse `gating` when a live lease is held by another owner.
  Test: claim a job, CLI `gates` → clean refusal. Effort XS.

### T-013 — charge() has zero production callers; costs always empty (BUG-009+DAT-352 · S2/Confirmed)
- Status: **BLOCKED** — owner product decision (wire charge() into
  align/render/publish vs remove `costs` command). In QUESTIONS.md.

### T-014 — `render --aspect` variant drives book pipeline; `ready` mis-certifies (BUG-010 · S2/Confirmed)
- Status: READY (owner decision on intended --aspect semantics recorded in
  QUESTIONS.md; safe default: variants don't advance book states). Effort M.

### T-015 — Degenerate script downloads faster-whisper model before failing (BUG-011 · S2/Confirmed)
- Status: READY. Fail fast with AlignError on empty normalized tokens in
  `_do_align` before `align_words`. Test with socket bombed → no network. XS.

### T-016 — Recorded fixtures stamped calibration-grade provenance (DAT-351 · S2/Confirmed)
- Status: READY. Write `provenance='unavailable'` (or `'fixture'`) in
  `invites.poll_invite_metrics`. Latent today (unwired). XS.

### T-017 — payout_usd never written; $/clip-hour always NULL (DAT-353 · S2/Confirmed)
- Status: READY. Implement documented rate-basis payout fill
  (`rate_per_1k_usd` × views at measure time), or drop column/metric. M.

### T-018 — faster-whisper auto-download contradicts network policy (DAT-364 · S2/Confirmed)
- Status: READY. Revision pin + checksum/size guard + offline fail-closed, or
  document the egress; align with module docstring. S.

### T-019 — HYPELAB_ROOT/DB/model-cache split-brain (ENV-651 · S2/Confirmed)
- Status: **BLOCKED** — owner decision (single-root semantics vs documented
  split). In QUESTIONS.md.

### T-020 — Lazy imports / missing ffmpeg fail with raw tracebacks (ENV-652 · S2/Confirmed)
- Status: READY. Wrap lazy imports with helper raising domain error naming
  package + pip line; FileNotFoundError → clean error in `render.py:456`,
  `gates.py:44`. S.

### T-021 — First-run model bootstrap: hidden caches, no offline handling (ENV-653 · S2/Confirmed)
- Status: READY. Document both caches + sizes; add `fetch` step for ASR
  model or honor `HF_HUB_OFFLINE` with clean error. S + docs.

### T-022 — Clearance flow is write-only: ingest rejects the basis record_clearance preserves (REV-702 · S2/Confirmed)
- Status: READY. Add download path for `needs_clearance`+http URL after
  clearance (module's documented preference-3), or change record_clearance
  basis. S.

### T-023 — Submission re-gate synthesizes placeholder clip; illegal tray transition (REV-703 S2 + REV-704 S3 · Confirmed)
- Status: READY. `regated_if_stale` must use the stored clip row's fields;
  add legal `tray → compliance_unknown` path or handle unknowns without
  job transition. M.

### T-024 — Tokenizer mismatch corrupts beat boundaries on hyphens (REV-705 · S2/Confirmed)
- Status: READY. Unify tokenization (`_WORD_RE` vs `str.split()`) in
  `retime_beats` and `low_confidence_beats`. S.

### T-025 — Clip/job lifecycle transition logic split across three modules (ARC-302 · S2/Confirmed)
- Status: READY. Single `clip_lifecycle` owner (`transition_clip` + declared
  clip-state graph); `route_job` as the one job aggregator. M.

### T-026 — Raw SQL + duplicated ranking query in CLI (ARC-303 · S2/Confirmed)
- Status: READY. Move ranking/listing queries into service modules
  (`score.list_moments`, tray/compliance listers). S.

### T-027 — Render provenance split; Book 2 persists no EDL (ARC-304 · S2/Confirmed)
- Status: READY. Persist cut EDL to `work/<job>/edl_<clip_id>.json` (or
  `edls` table); decide one authority for the skip check; document. S.

### T-028 — Source-kind registry in three places; twitch accepted, never lists (ARC-307 S3 + REV-750 S3 · Confirmed)
- Status: READY. Single `SOURCE_KINDS` registry mapping kind → lister,
  imported by CLI choice, `add_source`, `list_new_items`. S.

### T-029 — Authorizations never expire, cannot be revoked (REV-706 S3 + SEC-102 S4 · Confirmed)
- Status: READY. Add `expires_at` (default 30d), `revoke` op, bind
  platform/intent at check time for publish. M.

### T-030 — Consent expiry format never validated; "never" never expires (SEC-100 S3 + DAT-362 S3 · Confirmed)
- Status: READY. Validate ISO-8601 at `grant()` time; reject unparseable.
  Test: `--expires never` → clean refusal. S.

### T-031 — Consent ledger CSV export is formula-injection prone (SEC-104 · S3/Confirmed)
- Status: READY. Prefix leading-`'` on formula-shaped cells in
  `export_ledger`. XS.

### T-032 — ffmpeg/yt-dlp decode untrusted media unsandboxed; RSS fetch unbounded (STR-450 S2, STR-451 S2 · Confirmed)
- Status: READY. Document threat model limits; add fetch size cap + entity
  expansion guard for RSS; `--max-filesize` for yt-dlp (also PAT-602). M.

### T-033 — "Deterministic render" overclaims byte-determinism (STR-452 · S2/Confirmed)
- Status: READY. Add `-fflags +bitexact -map_metadata -1` or correct the
  docstring/ARCHITECTURE claims to hash-determinism. S.

### T-034 — signals.py has zero test coverage (TST-001 · S2/Confirmed)
- Status: READY. Unit tests for extract_heatmap / comment_timestamps /
  have_tier3 with hand-made dicts. S.

### T-035 — b2cli.py Book 2 CLI commands untested (TST-002 · S2/Confirmed)
- Status: READY (campaign subset covered by T-001's tests; remainder:
  source/watch/moments/cut/tray/posted CliRunner tests). M.

### T-036 — Remaining test gaps (TST-004 S2, TST-005 S2, TST-006 S2, TST-008 S2, TST-009 S2, TST-010 S3, TST-011 S3, TST-012 S3)
- Status: READY. Skip guards for model tests; conftest.py replacing 8
  sys.path hacks; ingest entry test; book3cli CLI tests; de-brittle gate
  string assertions; explicit double-render determinism test.

### T-037 — Failed-job recovery is SQL-only; no retry command (UIX-552 · S2/Confirmed)
- Status: READY after T-011 decision. CLI `retry` (`failed → draft` or
  re-queue). M.

### T-038 — README + ARCHITECTURE rewrite group (MAP-002 S2, DOC-001–011 S2/S3 ex. merged, DOC-012/013/014 S2, DOC-015–021 S3, DOC-022/023/024 S4, BLD-004 S3, MAP-003 S3 · all Confirmed)
- Status: READY. Rewrite README setup/walkthrough/test/env sections
  against the real CLI; correct ARCHITECTURE §§1.x, 2, 3.3, 4.6/4.7, 5, 6.3,
  7, 8; write promised docs/WALKTHROUGH.md + docs/OPERATIONS.md or remove
  the promise. Do LAST per kit (docs corrections after behavior fixes).

### T-039 — Perf fixes (PRF-501 S2, PRF-502 S2, PRF-503 S2, PRF-504 S2 · Confirmed)
- Status: READY. Hash-once render; shared probe record + fused decodes in
  gates; sub-quadratic score_windows; single-decode audio features. M.

### T-040 — Tracked job outputs (~34–39 MB) in jobs/ (BLD-010 S3 + MAP-001 S3 · Confirmed)
- Status: **BLOCKED** — owner approval to `git rm -r jobs/` + `.gitignore`
  (deleting files needs approval). In QUESTIONS.md.

### T-041 — S3/S4 backlog (grouped; evidence in findings/*.md)
- Status: READY (pick by value when higher tiers drain).
- BUG-012/013/014/015 (kit float, attach orphan, run_all KeyError, EDL
  schema validation); ARC-305/306/308/309/310/311/312/313/314/315;
  DAT-354/355/356/357/358/359/360/363; ENV-654/655/656/657; PAT-600/601/602/603;
  PRF-505/506/507/508/509/510/511; REV-708/709/710/711/712/713/714/715/716/717/
  718(→T-004)/719; REV-751/752/753/754/755/756/757/758/759/760/761/762/763/764/
  765/766/767/768/769/771; SEC-101/103/105/106; STR-453/454/455/456;
  UIX-550/551/553/554/555/556/557/558/559/560/561/562/563/564/565/566/567/568/
  569/570; BLD-004/006/007/009/011/012/013; DOC-015–024 (in T-038);
  MAP-004/005; BLD-008 (downgraded S3: document HYPELAB_CHROMIUM).
- Note: STR-456 is an observation (not a defect) — no task.

## Rejected / not findings (verified good, kept for the record)

- DAT lane: FK enforcement on; consent gate fail-closed; publish honesty
  (LiveRefused); no credentials/synthetic-only fixtures; invite→job mapping
  defensive except genuinely unreachable.
- SEC lane: no shell injection (40 modules swept); no pickle/YAML; all SQL
  parameterized; traversal rejected in intake; ASS caption injection
  neutralized; overlay text escaped; live publishing structurally impossible
  (4 independent refusals); no web threat classes (no server/tokens).
- PRF lane: `parallel.py` doesn't exist — worker is single-threaded; no
  lock-contention surface beyond SQLite WAL.
- ENV lane: tesseract-absent fail-closed; HYPELAB_CHROMIUM mis-set → clean
  error; yt-dlp missing → clean error; pysubs2 missing → gate FAILs closed;
  migration-set mismatch refuses boot; no listening ports; no secrets in env.
- PAT lane: no shell injection (19 argv sites); no SQL injection (178 sites);
  no traversal; no secrets in tree/history; no mutable defaults; no silent
  exception swallowing.
- BLD lane: `whisper` installed but unused (info); torch CUDA build on
  CPU-only box (info); no committed secrets.

### T-042 -- Unify best_views aggregation semantics (controller-observed, S3)
- Status: READY.
- Problem: metrics.best_views() returns latest-by-provenance-rank (official_api
  preferred, then latest at), while feedback._best_views() returns MAX(views)
  over calibration-grade rows. Both are provenance-filtered since T-002, but
  two "best views" definitions can disagree on the same post.
- Fix: decide one semantic (recommend adopting the metrics.py ranking in
  feedback, or delegating outright), add a test pinning agreement, run the
  full suite. Effort: XS.
