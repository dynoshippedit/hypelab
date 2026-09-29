# Flow 3 (ARC trace): Book 2 Clip Mine — campaign → ingest → score → cut → compliance → tray → posted

Owner: Architect (ARC) · Phase 2 · 2026-09-29
Read in full: `hypelab/b2cli.py` (1–453), `hypelab/campaigns.py` (1–182),
`hypelab/watcher.py` (1–293), `hypelab/ingest.py` (1–310), `hypelab/signals.py` (1–116),
`hypelab/score.py` (1–420), `hypelab/boundary.py` (1–259), `hypelab/cut.py` (1–301),
`hypelab/compliance.py` (1–389), `hypelab/tray.py` (1–203), `hypelab/metrics.py` (1–136),
`hypelab/attribution.py` (1–240), plus `hypelab/cli.py` worker section (826–940),
`hypelab/jobs.py` (1–140), `hypelab/queue.py` claim map (31–36), `hypelab/db.py` (1–147),
`migrations/0002_book2_clip_mine.sql` (1–64).

Entry: `python3 -m hypelab.cli` → `cli.py` registers Book 2 commands from
`b2cli.COMMANDS` (`cli.py:970-974`). `b2cli.py` is the whole CLI surface for
this flow; business logic lives in the sibling modules.

## Hop 1 — campaign add / bump-rules / refresh-budget
`b2cli.py:77-147` (click groups) → `campaigns.add/load/bump_rules/refresh_budget`
(`campaigns.py:57-160`).

- Layering: thin. CLI parses args + JSON file (`_read_json`, `b2cli.py:58-63`),
  module validates (`validate`, `campaigns.py:37-54`) and writes SQLite.
  Clean separation — the good pattern in this flow.
- **Breakage (ARC-301):** `campaign bump-rules` (`b2cli.py:117-131`) passes the
  `--by` operator *string* to `campaigns.bump_rules(conn, campaign_id, rules, provenance)`,
  whose contract requires a *dict* `{who, source_url, captured_at}`
  (`campaigns.py:119-133`) — every invocation raises `CampaignError`.
  `campaign refresh-budget` (`b2cli.py:133-147`) passes the whole parsed budget
  JSON *dict* as `seen_usd` to `refresh_budget(conn, campaign_id, seen_usd: float, ...)`
  (`campaigns.py:147-160`); `float(dict)` raises `TypeError`, which the
  `except CampaignError` clause does not catch — uncaught traceback.
  The CLI↔service contract is an implicit dict shape with no validation or
  test (TST inventory covers `campaigns.add` only). `b2cli.py` is the sole
  caller of both functions.
- Campaigns are "versioned data, never code" (`campaigns.py:1-13`); rules
  bumps are deliberate operator actions with provenance — sound design, broken
  plumbing.

## Hop 2 — source add (rights manifest required) + clearance
`b2cli.py:150-208` → `watcher.add_source` / `watcher.record_clearance`
(`watcher.py:163-221`).

- Layering: CLI validates click-level types; `add_source` enforces the
  fail-closed rights manifest (basis required, `watcher.py:163-196`).
  `record_clearance` mutates the stored manifest JSON in place
  (`watcher.py:197-221`) — the manifest is a JSON blob in `sources.authorization`,
  read-modify-write on every clearance.
- **Registry split (ARC-307):** the valid source-kind set is defined in three
  places — the CLI `click.Choice` (`b2cli.py:168-170`), `add_source`'s
  validation tuple (`watcher.py:166-168`), and `list_new_items`' dispatch
  (`watcher.py:124-133`). `twitch` is accepted by the first two but has no
  lister branch → `WatcherError` at poll time. Adding a kind requires
  editing all three; nothing enforces they agree.

## Hop 3 — watch (poll → enqueue)
`b2cli.py:211-227` → `watcher.poll(conn, lister=list_new_items, ...)`
(`watcher.py:223-287`) → `jobs.new(conn, mode="clip", state="queued_ingest")`
(`jobs.py:62-82`).

- Layering: `poll` does listing (via injectable `lister` — a genuine
  testability seam), allowlist filtering (`source_allowed`, `watcher.py:138-149`),
  dedup, `source_items` INSERT, job creation, and item↔job linking, all on one
  connection. It also *prints* progress lines (`watcher.py:240, 280-283`) —
  the module's documented "notification" path (ARC-315).
- **Duplicated allowlist (ARC-310):** `watcher.source_allowed` re-implements
  substring matching also implemented by `compliance.chk_source_allowed`
  (`compliance.py:152-165`), which additionally treats `embed`/`youtu.be`/
  `/shorts/` URLs as ambiguous → UNKNOWN. Poll-time and gate-time can
  disagree; the gate is the stricter one, so the failure mode is wasted
  scoring/cutting, not a bad publish (fail-safe direction).
- State: `queued_ingest` is created directly by `jobs.new` with no transition
  validation (`jobs.py:62-82` inserts any `state` string). Job lifecycle
  ownership starts here but lives in `jobs.py`'s `ALLOWED` map.

## Hop 4 — worker: queued_ingest → ingest (rights-gated)
`cli.py:884-940` (`work` loop) → `queue.claim` (`queue.py:59`;
`queued_ingest`→`ingesting` map at `queue.py:31-36`) → `_handle_ingest`
(`cli.py:867-873`) → `ingest.ingest` (`ingest.py:223-310`).

- `require_rights` (`ingest.py:80-108`) fails closed on missing/unknown/clearance-less
  manifests — the crown-jewel gate for this flow, cleanly separated from the
  download logic. Good.
- **Mixed concerns (ARC-313):** `ingest()` (88 lines) does rights check (DB),
  download (yt-dlp/network or local intake), content hash (DB UPDATE),
  transcription (ASR model via `align.transcribe`), signals extraction, and
  three file writes (`source.mp4`, `source.words.json`, `signals.json`).
  Contrast `score.py`, which separates pure `score_windows` (`score.py:277-331`)
  from I/O `score_moments` (`score.py:358-420`) — ingest has no such split, so
  the orchestration is untestable without ffmpeg/yt-dlp/ASR.
- `ingest()` is called with the worker's autocommit connection
  (`db.connect` sets `isolation_level=None`, `db.py:138-147`); each
  `conn.execute` commits independently — a crash between the
  `source_items` UPDATE and the file writes leaves DB and filesystem
  disagreeing, with no reconciler.

## Hop 5 — worker: queued_score → score_moments
`_handle_score` (`cli.py:876-882`) → `score.score_moments`
(`score.py:358-420`).

- Layering: the pure core is exemplary — `transcript_score` (`score.py:82-93`),
  `score_windows` (`score.py:277-331`), `nms` (`score.py:333-346`) are pure
  dict-in/dict-out and fully unit-testable (TST confirms). `score_moments`
  is the I/O shell: reads `source.words.json`/`signals.json`, runs Tier 2
  audio via ffmpeg, INSERTs `moments` + `moment_dedup` rows.
- Weights: `load_weights` (`score.py:220-250`) defaults to `Path.cwd()`;
  the worker passes `cli._WEIGHTS_DIR` (package dir, `cli.py:49`), `b2cli`
  has its own `WEIGHTS_DIR` (`b2cli.py:35`) — three resolutions of "the"
  weights dir (ARC-311). Dedup hash (`content_hash`, `score.py:348-355`) is
  the guard against re-mining — good.
- `score_moments` prints the dedup note (`score.py:414-415`) — library
  printing again (ARC-315).

## Hop 6 — moments (list) → cut (operator picks numbers)
`b2cli.py:230-289` → `cut.cut` (`cut.py:211-248`) → `cut_moment`
(`cut.py:106-208`).

- **SQL in the CLI (ARC-303):** `moments` embeds its ranking query
  (`b2cli.py:237-240`); `cut` re-embeds the *same* `ORDER BY score DESC`
  query (`b2cli.py:264-265`) and maps display numbers → moment ids in the
  command (`b2cli.py:276-286`). The `moments`-shows-`cut`-picks contract is
  two copies of one query; change one ordering and the numbers silently
  point at different moments.
- `cut()` guards `job["state"] != "scored"` (`cut.py:224-227`) — business
  rule in the service layer, good — then transitions `scored→queued_cut→cutting`
  (`cut.py:241-244`).
- `cut_moment` is a ~100-line orchestrator: DB read → `boundary.select`
  (pure, `boundary.py:226-259`) → `reframe.plan_reframe` (ffmpeg probe) →
  segment audio extract (ffmpeg) → `_build_edl` → `render.render` (Book 1's
  deterministic chain, **called without conn/job_id**, `cut.py:136-137`) →
  ffprobe → caption assembly via `tray.assemble_caption` (cross-module:
  caption assembly lives in `tray.py:54-73` but runs at cut time) →
  `clips` INSERT as `cutting` → `compliance.check` → state UPDATE.
  The `check_clip` dict it builds (`cut.py:150-167`) is data-shaping logic
  inside the orchestrator.
- **Render provenance gap (ARC-304):** because `render()` gets no conn, no
  `renders`/`edls` DB rows are written and the hash-skip never engages;
  the EDL built in `_build_edl` is validated but **never persisted** —
  `cut.py`'s own docstring ("the cut re-renderable: same EDL + same source
  hash = same clip", `cut.py:1-13`) has no materialized EDL behind it.
  Only `compliance_json` (boundary + gate record) survives in the DB.

## Hop 7 — compliance gate (after render, before tray)
`compliance.check` (`compliance.py:188-234`): 10 `chk_*` functions
(`compliance.py:52-167`), PASS/FAIL/UNKNOWN tri-state, fail-closed,
`compliance_log` INSERT per run.

- Layering: the checks are pure `(clip, rules) → (outcome, detail)` — the
  flow's best layering. `check()` mixes evaluation with audit persistence
  (the INSERT) — deliberate and documented, acceptable for an audit trail.
- `check()` deliberately does NOT transition the job (note at
  `compliance.py:198-207`); the caller aggregates via `route_job`
  (`compliance.py:291-319`). **But** job routing also lives in
  `cut.record_posted` (`cut.py:251-301`, its own remaining-tray-count
  aggregation) and `compliance.resolve` (`compliance.py:348-389`) —
  three aggregators (ARC-302).
- Re-gate paths: `record_posted` re-gates when `rules_version` changed
  (`cut.py:278-286` → `regated_if_stale`, `compliance.py:236-289`);
  `build_tray` re-gates stale clips too (`tray.py:148-160`). Two callers
  of the same re-gate, each with its own surrounding logic.

## Hop 8 — review (human) → tray → posted
`b2cli.py:337-385` (`review` group embeds the compliance JOIN in the CLI —
ARC-303 again) → `compliance.resolve` → `tray.build_tray`
(`tray.py:127-203`) → `b2cli.py:320-335` (`posted`) → `cut.record_posted`.

- `build_tray` ranks by `predicted`, **moves** each `clip_<id>.mp4` into
  `tray/clip_NNNN/clip.mp4` (`src_mp4.replace(dst_mp4)`, `tray.py:182-186`)
  and UPDATEs `clips.path`/`tray_rank` (`tray.py:198-201`). File location
  and DB row are kept in sync inside one function — but a `_thumb` failure
  mid-loop leaves earlier clips moved+updated and later clips not; the
  loop is re-runnable (the `resolve()` equality short-circuit,
  `tray.py:183`), not atomic.
- `record_posted` requires `state == 'tray'` (`cut.py:270-272`), refuses
  without `post_url` (`cut.py:273-274` — `posted_at` NOT NULL is enforced
  in code per `migrations/0002`, since the additive migration couldn't add
  the constraint), and only transitions the job to `posted` when no tray
  clips remain (`cut.py:291-299`).
- `posted` takes `post_url`/`--platform` as free text with no URL validation
  (`b2cli.py:320-335`) — operator-entered, fail-open on typos.

## Hop 9 — measure → worked → propose/promote-weights
`metrics.poll_metrics` (`metrics.py:89-112`, INSERT per open post),
`attribution.attribute` (`attribution.py:52-115`), `propose_weights` /
`promote_weights` (`attribution.py:139-240`).

- `worked` (`b2cli.py:399-420`) calls `attribute(conn)` which **upserts
  `what_worked` rows** — a read-named command with a write side effect
  (ARC-308). The n≥30 read guard (`attribution.py:39, 118-132`) and n≥50
  proposal guard (`attribution.py:42, 151-157`) are code-enforced — good.
- Best-provenance-views ranking is implemented twice: `metrics.best_views`
  (`metrics.py:114-130`) and the CTE inside `attribute`
  (`attribution.py:58-83`); `prov_list` is f-string-interpolated into SQL
  (`attribution.py:57`) — safe today (module constants), fragile pattern.
- `promote_weights` is operator-gated file promotion into the package's
  `weights/` dir (ARC-311).

## Layering verdict (flow 3)

The flow has a recognizable three-layer shape — `b2cli.py` (CLI parsing,
presentation) → service modules (`campaigns`, `watcher`, `ingest`, `score`,
`cut`, `compliance`, `tray`, `metrics`, `attribution`) → `db.py`/`util.py`
+ SQLite + `work/<job>/` files — and the *pure* cores are genuinely good
(`score.score_windows`, `boundary.*`, `compliance.chk_*`, `signals.*`).
But the seams leak in both directions:

1. **CLI layer does data access and business mapping**: raw SQL for
   `moments`/`cut`/`tray`/`review` (`b2cli.py:237-240, 264-265, 304-307,
   327-335`) and the display-number→moment-id mapping (`b2cli.py:276-286`).
2. **Service layer does orchestration + I/O + persistence in single
   functions**: `ingest()` (ARC-313), `cut_moment` (~100 lines, 8 stages),
   `watcher.poll` (listing + filtering + DB + printing).
3. **No single owner of the clip lifecycle**: clip state transitions are
   split across `cut.py` (cutting→tray/failed, posted), `compliance.py`
   (compliance_unknown routing, human resolve), and file moves + path
   updates in `tray.py`; job-level aggregation is split across
   `compliance.route_job`, `cut.record_posted`, `compliance.resolve`
   (ARC-302).
4. **Contracts between layers are implicit**: dict shapes assembled in the
   CLI and consumed by services — already broken twice in `campaign`
   commands (ARC-301).

**Who owns the clip lifecycle state?** Nominally the `clips.state` column
(SQLite), transitioned by `cut.py` + `compliance.py` + `tray.py`'s file moves.
In practice: nobody owns it end-to-end. The state *column* is single, but
the *transition logic* is spread over three modules with no one module
able to answer "what are all the ways a clip changes state."
