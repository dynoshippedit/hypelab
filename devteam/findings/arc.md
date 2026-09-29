# ARC findings — Architecture (Phase 2, 2026-09-29)
Lane prefix: ARC · ID range ARC-300–349 · all NEW unless noted.
Severities per Playbook B7. Confidence: Confirmed = unambiguous code with cited lines.
Flow traces: `devteam/notes/flows/flow3-arc.md`, `devteam/notes/flows/flow6-arc.md`.
As-is assessment: `devteam/ARCHITECTURE.md` §2.

## ARC-300 — Two align execution paths with divergent failure semantics [S2, Confirmed]
**Location:** `hypelab/cli.py:562-636` (`audio` command) vs `hypelab/cli.py:833-852` (`_handle_align`, worker path).
**Evidence:** Both paths load job/kit/EDL and call the shared `_do_align` (`cli.py:264-341`), but each
re-implements the surrounding orchestration: the `audio` command transitions
`scripted→awaiting_media→queued_align→aligning` inline (`cli.py:602-609`), then on `AlignError`
calls `_die` (`cli.py:616-619`) — the process exits with the job committed in state `aligning`
(committed by `_transition`, autocommit connection). The worker path lets the exception propagate
to the `work` loop's generic handler → `queue.fail()` with retry counting and poison stamps
(`cli.py:926-933`). Same failure (bad VO), two lifecycle outcomes: stuck-in-`aligning`
(interactive) vs `failed` with attempts (worker). No single owner of "what happens when align fails".
**What's wrong:** the transition sequencing and failure routing around the shared `_do_align`
core are duplicated, and the two copies disagree on failure semantics.
**Impact:** an operator running `hypelab audio` on a bad VO leaves a job stranded in a
non-queued state no worker will ever reclaim; the same job via `hypelab work` is properly
failed/retried. Diagnosis depends on which path was used.
**Suggested fix:** extract one `run_align(conn, job_id) -> (doc, flagged)` orchestrator used by
both the command and the worker; make the command's failure path call `queue.fail()` (or an
equivalent) instead of bare `_die` after a state change.

## ARC-301 — Implicit CLI↔service contracts; `campaign bump-rules` and `campaign refresh-budget` broken on every invocation [S1, Confirmed]
**Location:** `hypelab/b2cli.py:117-147` (callers) vs `hypelab/campaigns.py:119-160` (contracts).
**Evidence:** `campaign_bump_rules` passes the `--by` operator **string** (`b2cli.py:122,127`) to
`campaigns.bump_rules(conn, campaign_id, rules, provenance)` (`campaigns.py:119`), which requires
`provenance` to be a dict with `who` (`campaigns.py:130-133`) — every invocation raises
`CampaignError`. `campaign_refresh_budget` passes the whole parsed budget JSON **dict**
(`b2cli.py:138,143`) as `seen_usd` to `refresh_budget(conn, campaign_id, seen_usd: float, ...)`
(`campaigns.py:147`); `float(seen_usd)` (`campaigns.py:157`) raises `TypeError`, which the
`except CampaignError` clause (`b2cli.py:144`) does not catch — uncaught traceback. `b2cli.py`
is the sole caller of both functions (verified by grep); the TST inventory covers
`campaigns.add` only, not these commands.
**What's wrong:** the layer boundary carries implicit dict shapes with no validation,
no types, and no tests at the seam — so the CLI assembles the wrong shapes and nothing
catches it.
**Impact:** two deliberate-operator commands (rules versioning, budget refresh — Book 2 §3)
are 100% broken via the CLI; there is no CLI workaround.
**Suggested fix:** make the CLI extract/validate the fields the service needs (build the
`{who, source_url, captured_at}` provenance dict in `b2cli`; extract `budget_seen_usd` from
the budget JSON), and add CliRunner tests for both commands. Long-term: typed
parameter objects or validated schemas at the CLI→service boundary.

## ARC-302 — Clip/job lifecycle transition logic split across three modules; no single owner [S2, Confirmed]
**Location:** `hypelab/cut.py:150-184,251-301`, `hypelab/compliance.py:236-319,348-389`, `hypelab/tray.py:127-203`.
**Evidence:** `clips.state` transitions happen in `cut.cut_moment` (`cutting` → `tray`/`compliance_unknown`/`failed`,
`cut.py:176-184`), `compliance.regated_if_stale` (re-gate moves, `compliance.py:272-289`),
`compliance.resolve` (human `compliance_unknown` → `tray`/`failed`, `compliance.py:362-377`),
and `cut.record_posted` (`tray` → `posted`, `cut.py:287`). Job-level aggregation is
implemented three times: `compliance.route_job` (`compliance.py:291-319`), `cut.record_posted`'s
own remaining-tray-count check (`cut.py:291-299`), and `compliance.resolve`'s
all-unknowns-resolved check (`compliance.py:371-383`). `tray.build_tray` moves files and
UPDATEs `clips.path` (`tray.py:182-201`) without touching state — file location and row
are synced inside one function but nothing owns the pair.
**What's wrong:** the state *column* is single (`clips.state`), but the *transition logic*
is spread over three modules; no one module can answer "what are all the ways a clip
changes state."
**Impact:** every lifecycle change (new state, new gate) must be edited in N places;
`route_job`'s aggregation rules and `record_posted`'s can silently disagree about when a
job is done.
**Suggested fix:** a single `clip_lifecycle` owner (e.g. in `jobs.py` or a new
`clips.py`): `transition_clip(conn, clip_id, to, ...)` validating against a declared
clip-state graph, with `route_job` as the one job aggregator. (File move + approval;
propose in ARCHITECTURE §3/§4.)

## ARC-303 — Raw SQL and business mapping in the CLI layer; `moments`/`cut` share a duplicated ranking query [S2, Confirmed]
**Location:** `hypelab/b2cli.py:230-289` (also `292-317`, `337-365`).
**Evidence:** `moments` embeds `SELECT id, t_in, t_out, score, confidence, weight_version
FROM moments WHERE job_id=? ORDER BY score DESC LIMIT ?` (`b2cli.py:237-240`); `cut`
re-embeds `SELECT id FROM moments WHERE job_id=? ORDER BY score DESC` (`b2cli.py:264-265`)
and maps display numbers → moment ids in the command body (`b2cli.py:276-286`). The
`tray` command queries `jobs WHERE state='tray'` (`b2cli.py:304-307`); the `review` group
embeds the clips⨝compliance_log JOIN (`b2cli.py:327-335`).
**What's wrong:** presentation (numbered list) and data access (ranking query) live in
the CLI; the `moments`-shows→`cut`-picks contract is two copies of one `ORDER BY`.
**Impact:** change the ordering in one command and the numbers `moments` prints silently
point at different moments in `cut` — an operator picks #3 and cuts #5's moment.
**Suggested fix:** move ranking/listing queries into the service modules
(`score.list_moments(conn, job_id)`, `tray`/`compliance` listers); the CLI only formats.

## ARC-304 — Render provenance split across two stores; Book 2 persists no EDL and skips the DB mirror [S2, Confirmed]
**Location:** `hypelab/render.py:404-534`, `hypelab/cut.py:106-137`.
**Evidence:** `render()` writes (a) `work/manifest.json` via `manifests.record_render`
(always, `render.py:497`) and (b) `renders` + `edls` DB rows only when `conn`+`job_id`
are passed (`render.py:500-534`). The hash-skip decision reads the **DB**
(`_latest_render_hash`, `render.py:396-401, 448-453`) — the DB is the authority for
"already rendered", the file manifest is the audit trail. `cut.cut_moment` calls
`render(edl, work, out)` **without** conn (`cut.py:136-137`): no DB rows, no skip,
and the EDL built in `_build_edl` (`cut.py:67-104`) is validated but **never persisted**
anywhere — while `cut.py`'s own module docstring claims "the EDL's reframe block makes
the cut re-renderable: same EDL + same source hash = same clip" (`cut.py:1-13`).
**What's wrong:** the provenance contract differs by caller; the "re-renderable" claim
has no materialized EDL behind it for Book 2.
**Impact:** a Book 2 clip cannot be re-rendered from a stored EDL (it was never stored);
if `work/manifest.json` and the DB disagree, the DB wins the skip decision silently.
**Suggested fix:** persist the cut EDL to `work/<job>/edl_<clip_id>.json` (or the
`edls` table) from `cut_moment`; decide one authority for the skip check and document it.

## ARC-305 — Library functions commit the caller's connection [S3, Confirmed]
**Location:** `hypelab/render.py:528` (`conn.commit()`), `hypelab/carousel.py:412`
(`conn.commit()`), plus `hypelab/book3cli.py:109`.
**Evidence:** `render()` and `render_carousel()` both call `conn.commit()` on a
connection they did not open, after writing `renders`/`edls`/`slides` rows.
**What's wrong:** the transaction boundary lives inside the library. A caller composing
`render_carousel` with other writes in one unit of work cannot roll the slides rows back.
Mostly benign today because `db.connect` uses autocommit (`db.py:138-147`), which is
exactly why it is a latent trap: it works until someone passes a transactional connection.
**Impact:** low today; blocks any future "one CLI invocation = one transaction" design.
**Suggested fix:** remove `commit()` from library functions; commit at the command/worker
layer (the existing `jobs.transition` already manages its own transaction explicitly,
`jobs.py:104-137` — follow that pattern).

## ARC-306 — Subprocess argv-validation helper duplicated in four modules [S3, Confirmed]
**Location:** `hypelab/ingest.py:150-165` (`_run`), `hypelab/score.py:103-116` (`_run`),
`hypelab/cut.py:55-58` (inline loop in `_extract_segment_audio`),
`hypelab/tray.py:59-62` (inline loop in `_thumb`).
**Evidence:** four copies of "validate argv elements are non-empty strings, then
`subprocess.run(..., shell=False)`". `util.py` — imported by all four — would be the
home; instead each module grew its own.
**What's wrong:** a security-relevant pattern (argv hygiene, never `shell=True`) with
four independent copies; if one copy is ever weakened (or one gains logging/retry),
the others silently diverge.
**Impact:** maintainability; the pattern is correct everywhere today, so this is
about preventing future drift, not fixing a live bug.
**Suggested fix:** one `util.run_checked(argv, what, timeout)` (name TBD); replace
the four copies. PRE-APPROVED class (dead-code/consistency cleanup inside files —
no moves).

## ARC-307 — Source-kind registry defined in three places; `twitch` accepted at add, fails at poll [S3, Confirmed]
**Location:** `hypelab/b2cli.py:168-170`, `hypelab/watcher.py:124-133`, `hypelab/watcher.py:163-176`.
**Evidence:** valid kinds appear in the CLI `click.Choice` (`b2cli.py:168-170`:
`yt_channel|rss|twitch|manual`), in `add_source`'s validation tuple
(`watcher.py:166-168`), and in `list_new_items`' dispatch (`watcher.py:124-133`).
`twitch` passes the first two but has no lister branch → `WatcherError("unknown
source kind 'twitch'")` at poll time. Nothing enforces the three agree.
**What's wrong:** adding/removing a source kind requires editing three disconnected
lists; the failure surfaces late (at poll, not at add).
**Impact:** operator adds a `twitch` source successfully, then `watch` fails every
poll with an error that points at the wrong layer.
**Suggested fix:** single `SOURCE_KINDS` registry mapping kind → lister function,
imported by the CLI choice, `add_source`, and `list_new_items`.

## ARC-308 — `worked` (a read-named command) writes to the database [S3, Confirmed]
**Location:** `hypelab/b2cli.py:399-420`, `hypelab/attribution.py:98-113`.
**Evidence:** `hypelab worked` calls `attribution_mod.attribute(conn)` (`b2cli.py:407`),
which upserts `what_worked` rows (`attribution.py:104-112`, `ON CONFLICT ... DO UPDATE`).
The command's help text ("Attribution: what correlated with views") and name suggest a
read; it recomputes and rewrites attribution state on every invocation.
**What's wrong:** command/query responsibility separation is violated; a "read the
dashboard" operation has write side effects (row churn, `updated_at` bumps) that
pollute the audit story of when attribution actually changed.
**Impact:** low operational risk today (idempotent upsert), but `updated_at` no longer
means "new information arrived" — it means "someone ran `worked`".
**Suggested fix:** split into `attribute` (compute+store, explicit) and `worked`
(read-only over `what_worked`); or document the write in the help text and keep it.

## ARC-309 — Carousel job is born in `ready`, bypassing the job state machine [S3, Confirmed]
**Location:** `hypelab/book3cli.py:101-120`, `hypelab/jobs.py:62-82`.
**Evidence:** `carousel_cmd` creates the job via `jobs_mod.new(conn, mode="carousel",
kit_id=kit_id, title=title, state="ready")` (`book3cli.py:106-108`). `jobs.new`
inserts any `state` string with no validation (`jobs.py:62-82`); `ready` is reachable
as an *initial* state although the `ALLOWED` graph (`jobs.py:38-60`) only reaches it
via `gating→ready`. Carousel jobs share the `jobs` table with pipeline jobs but not
the lifecycle — `queue.claim` never sees them only because no `queued_*` name is used.
**What's wrong:** the state machine is advisory for job creation; two job families
with different lifecycles share one table and one `state` column with no `mode`-aware
rules.
**Impact:** today: a `ready` carousel job is indistinguishable from a fully-gated
Book 1 job to anything reading `jobs.state`. Future: any automation that trusts
`state='ready'` ⇒ "passed 8 gates" is wrong for carousel jobs.
**Suggested fix:** validate initial states in `jobs.new` (against a per-mode start
set), or give carousel its own honest lifecycle (`carousel_draft→carousel_ready`).

## ARC-310 — Source-allowlist logic duplicated with divergent verdicts [S3, Confirmed]
**Location:** `hypelab/watcher.py:138-149` vs `hypelab/compliance.py:152-165`.
**Evidence:** `watcher.source_allowed` does plain substring matching of
`source_allowlist` entries. `compliance.chk_source_allowed` re-implements substring
matching **plus** ambiguity handling: `embed`/`youtu.be`/`list=`/`/shorts/` URLs go
UNKNOWN for human review (`compliance.py:161-163`). A URL admitted at poll time can
be routed to human review at gate time.
**What's wrong:** two implementations of "is this URL allowed" that can disagree;
the stricter one runs last, after scoring and cutting already spent the work.
**Impact:** fail-safe direction (human review, not a bad publish), but wasted
ingest/score/cut cycles on items the gate was always going to flag.
**Suggested fix:** one `allowlist_verdict(url, allowlist) -> PASS|FAIL|UNKNOWN` in a
shared module, used by both `watcher.poll` and `compliance.chk_source_allowed`.

## ARC-311 — Weights location resolved three ways; proposals written into the package tree [S3, Confirmed]
**Location:** `hypelab/b2cli.py:35`, `hypelab/cli.py:49`, `hypelab/score.py:220-250`,
`hypelab/attribution.py:197-213`.
**Evidence:** `b2cli.WEIGHTS_DIR` and `cli._WEIGHTS_DIR` both point at the installed
package's `weights/` dir; `score.load_weights()` defaults to `Path.cwd()`
(`score.py:224`). `propose_weights` writes `weights_v2_candidate.json` and
`promote_weights` writes `weights_v2.json` **into the package directory**
(`attribution.py:208-213, 234-239`) — versioned *data* mutated inside the *code*
tree. "Which weights are live" is answered by a filesystem glob + string sort
(`score.py:241-248`), not by a recorded pointer.
**What's wrong:** data/code conflation; three resolutions of "the" weights dir;
promotion mutates the installed package (breaks read-only installs, confuses
packaging, and the file is tracked in git — a data write becomes a dirty tree).
**Impact:** works on this single machine; fragile for any reinstall, packaging,
or second checkout. `git status` goes dirty on every promotion.
**Suggested fix:** weights live under `HYPELAB_ROOT` (data domain, cf. `util.work_dir`
docstring's write domains, `util.py:174-206`); one resolver; record the active
version (DB row or `active.json` pointer) instead of glob+sort.

## ARC-312 — CLI support helpers triplicated across the three CLI modules [S3, Confirmed]
**Location:** `hypelab/cli.py:80-91`, `hypelab/b2cli.py:41-58`, `hypelab/book3cli.py:37-50`.
**Evidence:** `_die`, `_root`/`_repo_root`, `_conn` (all three read `HYPELAB_ROOT` /
`HYPELAB_DB` identically today), plus `_read_json` in `b2cli`/`book3cli`.
Behaviorally consistent now — which is exactly when to unify it, before it isn't.
**What's wrong:** exit codes, env-var fallbacks, and error shapes are user-visible
behavior defined in three copies; the next behavior change needs three edits.
(Evidence it already drifted: `book3cli.carousel_cmd` reads the spec JSON with a
bare `json.loads` + no error handling, `book3cli.py:103`, while `b2cli` has
`_read_json` with `_die` — the same concern solved two ways.)
**Impact:** maintainability; user-visible inconsistency already present in one spot.
**Suggested fix:** one `hypelab/cli_common.py` (name TBD) with `_die/_root/_conn/_read_json`;
the three modules import it. No moves of commands (REFACTOR_MODE=propose; new file
only — actually creating a new file is also a change; propose in §4).

## ARC-313 — `ingest()` mixes five concerns in 88 lines; no pure/IO split [S3, Confirmed]
**Location:** `hypelab/ingest.py:223-310` vs `hypelab/score.py:277-331` + `358-420`.
**Evidence:** `ingest()` does rights gating (DB), downloading (network/yt-dlp or
local intake), content hashing (DB UPDATE), transcription (ASR model), signals
extraction, and three file writes in one function. The codebase's own good pattern
— `score.py` separating pure `score_windows` from I/O `score_moments` — is not
followed here, so the ingest orchestration (order of operations, failure atomicity)
is untestable without ffmpeg, yt-dlp, and the ASR model.
**What's wrong:** testability and readability; the most failure-prone orchestration
in Book 2 (network + model + disk + DB) has the least separable structure.
**Impact:** the TST inventory notes ingest is covered only via fixtures; the
orchestration logic itself (e.g. "hash recorded before words written") cannot be
unit-tested.
**Suggested fix:** split into `plan_ingest` (pure: rights manifest → download plan),
`fetch_bytes` (I/O), `finalize_ingest` (hash + words + signals + DB) — mirroring
the `score_windows`/`score_moments` split.

## ARC-314 — Carousel's Python↔browser contract is an implicit string protocol; Chromium unpinned [S3, Confirmed]
**Location:** `hypelab/carousel.py:53-70`, `carousel.py:158-184`, `carousel.py:186-213`.
**Evidence:** `_PROBE_JS` serializes in-browser measurements into `document.title =
'MEASURE:' + JSON.stringify(...)` (`carousel.py:158-184`); `_measure_slide` scrapes
it with `re.search(r"<title>MEASURE:(\{.*?\})</title>", ...)` (`carousel.py:208`) and
indexes `measured["blocks"]` with no schema validation (`carousel.py:238-248`). The
two halves of the contract live in one file — the only thing keeping them in sync.
`_chromium()` takes whatever binary is on PATH (`carousel.py:53-70`); no version is
pinned or recorded, so slide output is not reproducible across environments — unlike
the ffmpeg determinism story the rest of the codebase tells (`render.py` render hash).
**What's wrong:** a cross-process contract with no schema, versioning, or renderer
identity; one Chromium behavior change in `--dump-dom` title handling breaks the
text-overflow gate.
**Impact:** mitigated by fail-loud behavior (`CarouselError` when no measurements,
`carousel.py:210-212`) and by the per-PNG 1080×1350 verification (`carousel.py:395-400`);
the risk is a subtly-wrong gate (measurements parse but mean something different),
not a silent bad render. Plus 14 Chromium launches per carousel (7 probe + 7
screenshot, `carousel.py:380-403`) — no batching.
**Suggested fix:** emit measurements as JSON to stdout via `--dump-dom` on a page
whose *body* carries the payload (or a `--headless --print-to-pdf`… simplest: keep
title protocol but `jsonschema`-validate the parsed payload and record
`chromium --version` in the slides' provenance). Batch: one page, 7 slides, one
probe pass.

## ARC-315 — Progress reporting via `print()` in library modules; no logging seam [S3, Confirmed]
**Location:** `hypelab/watcher.py:240,280-283`, `hypelab/score.py:414-415`
(plus prints in `hypelab/cli.py` handlers, which is the CLI's own business).
**Evidence:** `watcher.poll` prints `watch: source ... list failed` and
`NEW · creator · title → job_id` (`watcher.py:240, 280-283`); `score.score_moments`
prints the dedup note (`score.py:414-415`). The watcher docstring even documents
printing as its notification path (`watcher.py:283-287`).
**What's wrong:** library modules write unstructured text to stdout; there is no
logging module, no levels, no way for a future consumer (API, daemon, tests
asserting on behavior) to capture structured progress. `logging` vs `print` is a
one-line-per-site decision that gets harder the longer it waits.
**Impact:** evolvability/observability; today the CLI is the only consumer so the
cost is latent.
**Suggested fix:** `logging.getLogger("hypelab.<module>")` in library modules;
CLI configures the handler/formatter. PRE-APPROVED class (no behavior change).
