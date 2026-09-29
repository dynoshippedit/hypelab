# Data model — HypeLab (Phase 2, DAT, 2026-09-29)

Owner: DAT. Sources: `migrations/0001_book1_foundation.sql` (241 lines),
`migrations/0002_book2_clip_mine.sql` (64), `migrations/0003_book3_hype_layer.sql`
(157), `hypelab/db.py` (147), `hypelab/state_migrations.py` (31), plus query-pattern
reads of `hypelab/queue.py`, `hypelab/jobs.py`, `hypelab/render.py`, `hypelab/gates.py`,
`hypelab/manifests.py`, `hypelab/metrics.py`, `hypelab/feedback.py`,
`hypelab/attribution.py`, `hypelab/invites.py`, `hypelab/consent.py`, `hypelab/watcher.py`,
`hypelab/cut.py`, `hypelab/publish/*`, `hypelab/cli.py`.

**Table count correction:** MAP §6 says "23 tables". Counting distinct `CREATE TABLE`
statements across the three migration files gives **28 business tables** (`slides` is
declared twice, identical shape) plus the runner-owned `schema_migrations` = **29 total**.
The "23" figure is wrong.

## 0. Conventions used by the schema (verified)

- **Timestamps are TEXT, UTC ISO-8601, seconds precision** (`2026-09-28T17:45:00+00:00`)
  via `util.now()` (`hypelab/util.py:26-28`). Consistent everywhere, so lexical
  comparison of `lease_expires <= now()` works (`hypelab/queue.py:70-92`).
  No timezone mixing observed. There is no DATE/TIME affinity anywhere — all dates
  are strings. Fine, but SQLite date functions need the `+00:00` form; `date('now')`
  comparisons used in `attribution.py:68` (`p.posted_at > date('now', '-30 days')`)
  rely on `posted_at` being `YYYY-MM-DDTHH:MM:SS+00:00`, which sorts/compares
  correctly against `date('now')` output. OK.
- **Money is REAL float dollars everywhere** — `cost_ledger.usd`,
  `metrics.payout_usd`, `posts.payout_usd`, `campaigns.rate_per_1k_usd`,
  `campaigns.budget_total_usd`, `campaigns.budget_seen_usd`. Not integer cents.
  Display rounds via `%.2f` in `costs` (`hypelab/cli.py:968-971`), but stored and
  summed as floats. → DAT-357 (S3).
- **Booleans are INTEGER 0/1** (`gate_results.passed`, `post_placements.dry_run`,
  `priors.applied`, `moments.picked`, `targets.is_public`, `post_placements.is_ai_generated`).
  `compliance_log.passed` is tri-state: 1/0/NULL (NULL = UNKNOWN, routed to human) —
  documented in the migration comment, good.
- **No CHECK constraints, no column defaults beyond a few NOT NULL DEFAULTs.**
  State values are enforced in code (`jobs.ALLOWED`), not in the schema.
- **Every migration is transactional** (`db._apply_migration`: explicit BEGIN…
  COMMIT, ROLLBACK on failure) and recorded in `schema_migrations(version, name)`.
  The runner refuses boot on set mismatch (downgrade/foreign DB). → safe core.

## 1. Tables (all 28 + runner table)

### 1.1 `jobs` — the state machine row (also the queue entry)
`id TEXT PK` · `mode TEXT NOT NULL` · `state TEXT NOT NULL` · `kit_id TEXT`
(no FK → DAT-360) · `kit_version INTEGER` · `campaign_id TEXT` (no FK → DAT-360) ·
`title TEXT` · `created_at TEXT NOT NULL` · `updated_at TEXT NOT NULL` ·
`error TEXT` · `lease_owner TEXT` · `lease_expires TEXT` · `attempts INTEGER NOT NULL
DEFAULT 0` · `max_attempts INTEGER NOT NULL DEFAULT 3`.
Index: `ix_jobs_state(state)` — matches `queue.claim`'s `SELECT … WHERE state=?`
patterns. The claim itself uses `UPDATE … WHERE id=(SELECT id … WHERE state=? …
ORDER BY created_at LIMIT 1)`; state index helps.
**Types verdict:** sound. `mode`/`state` free-text TEXT but gated by `jobs.ALLOWED`
in code; schema-level enforcement absent (deliberate, documented nowhere — S4).

### 1.2 `job_events` — append-only audit of state moves
`id INTEGER PK AUTOINCREMENT` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE
CASCADE` · `at TEXT NOT NULL` · `from_state TEXT` (NULL = creation) ·
`to_state TEXT NOT NULL` · `note TEXT`.
Index: `ix_job_events_job_at(job_id, at)` — matches read patterns. FK declared ✓.

### 1.3 `edls` — versioned Edit Decision Lists
`job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE` · `version INTEGER
NOT NULL` · `render_json TEXT NOT NULL` · `render_hash TEXT` · `created_at TEXT NOT
NULL`; PK `(job_id, version)`. Read pattern `WHERE job_id=? ORDER BY version DESC
LIMIT 1` (`hypelab/render.py:398`, `hypelab/cli.py:767`, `hypelab/feedback.py:83`)
is covered by the PK's leftmost column. FK declared ✓.
**Dual-write note:** render() inserts edls + renders + appends `work/manifest.json`
in sequence, not in one transaction (DAT-356). `render_hash` is the idempotency key
for hash-skip renders.

### 1.4 `kits` — immutable versioned brand kits
`id TEXT NOT NULL` · `version INTEGER NOT NULL` · `data_json TEXT NOT NULL` ·
`created_at TEXT NOT NULL`; PK `(id, version)`. Immutability enforced in code
(`kits.seed` raises if exists; `bump` inserts max+1). FK declared ✓ (none needed).

### 1.5 `renders` — one row per render
`id TEXT PK` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE` ·
`edl_version INTEGER NOT NULL` · `aspect TEXT NOT NULL` · `path TEXT NOT NULL` ·
`duration_s REAL` · `lufs REAL` (always NULL — "kept simple per Book 1",
`hypelab/render.py:518`) · `manifest_json TEXT` (tool provenance per render) ·
`created_at TEXT NOT NULL`.
**Index gap:** `cli.py:761` reads `WHERE job_id=? ORDER BY rowid DESC LIMIT 1` —
no index on `renders(job_id)`; full rowid scan per gates run (DAT-359, S4).
**Dual-write:** `manifest_json` mirrors the entry appended to `work/manifest.json`;
nothing cross-checks them (DAT-356). `lufs` is dead weight: written NULL, never
read (S4).

### 1.6 `gate_results` — verdict per gate per run
`id INTEGER PK AUTOINCREMENT` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE
CASCADE` · `gate TEXT NOT NULL` · `passed INTEGER NOT NULL` · `detail TEXT` ·
`at TEXT NOT NULL`. **No UNIQUE(job_id, gate)** — `gates.run_all` appends a row per
gate per run (`hypelab/gates.py:460-464`); re-running gates leaves stale duplicate
rows. Current CLI consumes the return value, not a re-read, so no functional bug
today — latent read hazard (DAT-366, S3).

### 1.7 `cost_ledger` — money ledger (write-dead in production)
`id INTEGER PK AUTOINCREMENT` · `job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL` ·
`at TEXT NOT NULL` · `provider TEXT NOT NULL` · `unit TEXT NOT NULL` ·
`qty REAL NOT NULL` · `usd REAL NOT NULL` · `note TEXT`.
**`queue.charge()` has zero production callers** — nothing in the CLI pipeline
records costs; `hypelab costs` always prints "no cost rows recorded" (DAT-352, S2).
ESTIMATE|/ACTUAL| prefix convention is documentary only (per the docstring).
Money in float dollars (DAT-357).

### 1.8 `what_worked` — attribution buckets
`dimension TEXT NOT NULL` · `value TEXT NOT NULL` · `n INTEGER NOT NULL DEFAULT 0` ·
`mean_perf REAL` · `updated_at TEXT`; PK `(dimension, value)`.
Written by **two paths**: `attribution.attribute()` (filters calibration
provenances) and `feedback.feed_back()` (**no provenance filter at all** —
DAT-350, S1). Reads: `attribution.read_dimensions` splits n>=30 signal vs
below-threshold. `mean_perf` float. Fine.

### 1.9 `campaigns`
`id TEXT PK` · `marketplace TEXT` · `creator TEXT` · `rate_per_1k_usd REAL` ·
`budget_total_usd REAL` · `budget_seen_usd REAL` · `budget_checked TEXT` ·
`platforms TEXT NOT NULL` · `rules_json TEXT NOT NULL` ·
`rules_version INTEGER NOT NULL DEFAULT 1` · `submission_json TEXT` ·
`state TEXT NOT NULL DEFAULT 'active'` · `created_at TEXT NOT NULL` (+0002:
`rate_basis TEXT NOT NULL DEFAULT 'observed'`, `budget_provenance TEXT`,
`rules_provenance TEXT`).
**Budget columns are write-only-ish:** `refresh-budget` writes `budget_seen_usd`;
nothing ever compares spend against `budget_total_usd` — no enforcement code
exists (corroborates DOC-008; DAT-353-adjacent). `rate_per_1k_usd` + `rate_basis`
(observed|vendor_claim|unknown) documented.

### 1.10 `sources`
`id TEXT PK` · `campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE` ·
`kind TEXT NOT NULL` · `url TEXT NOT NULL` · `poll_every_s INTEGER NOT NULL DEFAULT 900` ·
`last_polled TEXT` · `last_item_id TEXT` (+0002: `authorization TEXT` rights manifest JSON).
FK declared ✓. **Index gap:** `watcher._due_sources` filters on `campaign_id` and a
`julianday()` expression — no index on `sources(campaign_id)` (DAT-359, S4).
**No URL validation at insert** — `rss` URLs go straight to `urllib.request.urlopen`
(incl. `file://` → local-file read into listings, low-severity operator-only).

### 1.11 `source_items`
`id TEXT PK` · `source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE` ·
`url TEXT NOT NULL` · `title TEXT` · `duration_s REAL` · `published_at TEXT` ·
`seen_at TEXT NOT NULL` · `job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL`
(+0002: `content_sha256 TEXT`). FKs declared ✓.
`job_id` nullable by design (SET NULL on job delete). Index gap: `source_items(job_id)`
read at `hypelab/ingest.py:66`, `hypelab/cut.py:161`, `hypelab/score.py:388` (DAT-359, S4).

### 1.12 `moments`
`id TEXT PK` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE` ·
`t_in REAL NOT NULL` · `t_out REAL NOT NULL` · `score REAL NOT NULL` ·
`confidence REAL NOT NULL` · `signals_json TEXT NOT NULL` · `transcript TEXT` ·
`picked INTEGER NOT NULL DEFAULT 0` (+0002: `weight_version TEXT NOT NULL DEFAULT
'unrecorded'`). Index `ix_moments_job(job_id)` matches `b2cli` reads. FK ✓.
Scores are provenance-labeled (weight version + confidence + raw signals). Good.
No CHECK t_out > t_in (S4).

### 1.13 `clips`
`id TEXT PK` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE` ·
`moment_id TEXT REFERENCES moments(id)` (no ON DELETE → moments delete would be
blocked/NULL? No action specified = RESTRICT-ish NO ACTION; fine) ·
`campaign_id TEXT REFERENCES campaigns(id)` · `path TEXT NOT NULL` ·
`caption TEXT` · `tray_rank INTEGER` · `predicted REAL` · `compliance_json TEXT` ·
`state TEXT NOT NULL` · `created_at TEXT NOT NULL` (+0002: `work_minutes REAL`).
**Clip state changes (`tray`→`posted`) are raw UPDATEs with no audit table**
(`hypelab/cut.py:284`) — unlike jobs, no `clip_events` exists (S4).
Index gap: `clips(job_id)` heavily read, unindexed (DAT-359, S4).

### 1.14 `posts`
`id TEXT PK` · `clip_id TEXT REFERENCES clips(id) ON DELETE CASCADE` ·
`job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE` · `platform TEXT NOT NULL` ·
`account TEXT` · `post_url TEXT NOT NULL` · `posted_at TEXT` (nullable in schema;
**NOT NULL enforced in code** — documented 0002 deviation, enforced in
`hypelab/cut.py:250-289` "refuses a post without one") · `post_id TEXT`
(provider id, NULL in dry_run) (+0002: `payout_usd REAL`).
**`payout_usd` is never written by any code** — INSERTs NULL, no UPDATE anywhere
(grep-verified). The docstring "filled in later from the campaign's rate basis"
is unimplemented → `metrics.usd_per_clip_hour` always returns NULL (DAT-353, S2).
Index gap: `posts(clip_id)` unindexed; `metrics.open_posts` JOINs on it (DAT-359, S4).

### 1.15 `metrics`
`post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE` · `at TEXT NOT NULL` ·
`views/likes/shares/saves/comments INTEGER` (nullable) · `payout_usd REAL`
(**never written** — both poll paths omit the column; always NULL) ·
`reject_note TEXT` (+0002: `provenance TEXT NOT NULL DEFAULT 'unknown'`); PK
`(post_id, at)`.
Provenance vocabulary: official_api | provider_api | user_entered | unavailable |
unknown. **Schema default 'unknown' vs documented 'unavailable' semantics**
(DAT-365, S4). `poll_metrics` uses INSERT OR REPLACE on (post_id, at): a second
poll within the same second silently replaces the row (documented as intended).
`best_views` filters calibration provenances only — good.

### 1.16 `targets`
`handle TEXT NOT NULL` · `platform TEXT NOT NULL` · `followers INTEGER` ·
`engagement REAL` · `is_public INTEGER` · `pattern_json TEXT` · `corpus_path TEXT` ·
`contact_route TEXT` · `consent_state TEXT DEFAULT 'none'` · `last_checked TEXT`
(+0003: `is_public_checked_at TEXT`, `corpus_consent_at TEXT`,
`invite_stats_json TEXT NOT NULL DEFAULT '{}'`); PK `(handle, platform)`.
`is_public` is a cached observation (documented). Compound PK referenced by
`consents` FK. No personal-data seed risk (rows are operator-created).

### 1.17 `consents`
`id TEXT PK` · `handle TEXT NOT NULL` · `platform TEXT NOT NULL` ·
`job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL` · `pitched_at TEXT NOT NULL` ·
`responded_at TEXT` · `decision TEXT` · `scope TEXT` · `expiry TEXT` ·
`artifact TEXT NOT NULL` (legacy path column) · (+0003: `actor TEXT`,
`account_id TEXT`, `artifact_hash TEXT`, `artifact_path TEXT`, `revoked_at TEXT`,
`revoked_by TEXT`, `revocation_note TEXT`, `jurisdiction TEXT`,
`terms_version TEXT`, `recorded_at TEXT`);
`FOREIGN KEY (handle, platform) REFERENCES targets(handle, platform)` — declared ✓.
Index `ix_consents_job_handle(job_id, handle, platform)` matches the gate query
(`hypelab/consent.py:168-173`: `WHERE job_id=? AND handle=? AND platform=? AND
decision='granted' AND revoked_at IS NULL AND expiry IS NOT NULL AND expiry > ?`).
**Enforcement is in code, fail-closed:** `grant()` refuses missing expiry/scope/actor
and hashes the artifact (`hypelab/consent.py:62-100`); the gate requires
granted+unrevoked+unexpired. Expiry is presence-checked only, not parsed/validated
as future-dated (DAT-362, S3).

### 1.18 `invites`
`id TEXT PK` · `post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE` ·
`handle TEXT NOT NULL` · `invite_status TEXT NOT NULL` · `checked_at TEXT`
(+0003: `created_at TEXT` — drives the 72h `ACCEPT_TIMEOUT_HOURS` rule).
No index on `post_id`/`handle`; small table (DAT-359, S4).

### 1.19 `slides`
`id TEXT PK` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE` ·
`idx INTEGER NOT NULL` · `spec_json TEXT NOT NULL` · `path TEXT`;
index `ix_slides_job(job_id)` (declared in 0003; the 0001 copy lacks it — the 0003
`CREATE INDEX IF NOT EXISTS` applies since 0001's table exists). No UNIQUE(job_id, idx)
— duplicate slide idx possible (S4).

### 1.20 `moment_dedup` (0002)
`content_hash TEXT PK` (sha256 of source content_sha256 + t_in + t_out) ·
`moment_id TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE` ·
`seen_at TEXT NOT NULL`. FK ✓. Dedup correctness depends on `content_sha256` being
populated — the watcher INSERT at `hypelab/watcher.py:257-263` **omits
`content_sha256`** (column added in 0002 but the insert list predates it) → hash
falls back to NULL component; dedup still functions (deterministic) but weaker than
documented. (S3 note, folded into DAT-359-adjacent? Kept here as S4 observation —
actually log as S3: deviation from the migration's documented design.)

### 1.21 `compliance_log` (0002)
`id INTEGER PK AUTOINCREMENT` · `clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE
CASCADE` · `at TEXT NOT NULL` · `rules_version INTEGER NOT NULL` ·
`passed INTEGER` (tri-state: 1/0/NULL=UNKNOWN→human) · `unknown_reasons TEXT` ·
`decided_by TEXT NOT NULL` · `note TEXT`. FK ✓. Audit trail for gate decisions. Good.

### 1.22 `authorizations` (0003)
`id TEXT PK` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE` ·
`action TEXT NOT NULL` (pitch|publish|invite) · `actor TEXT NOT NULL` ·
`platform TEXT` · `intent TEXT` · `authorized_at TEXT NOT NULL` · `note TEXT`;
index `ix_auth_job_action(job_id, action)` matches `require_authorization`
(`hypelab/authorize.py:60`). FK ✓.

### 1.23 `post_placements` (0003)
`id TEXT PK` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE` ·
`post_id TEXT` (provider id; NULL in dry_run) · `platform TEXT NOT NULL` ·
`adapter TEXT NOT NULL` (dryrun|meta|postiz|zernio|ayrshare) ·
`dry_run INTEGER NOT NULL DEFAULT 1` · `collaborators_json TEXT NOT NULL DEFAULT '[]'` ·
`caption TEXT` · `media_json TEXT` · `asset_sha256 TEXT` · `is_ai_generated INTEGER
NOT NULL DEFAULT 1` · `consent_ids_json TEXT` · `request_json TEXT` ·
`response_json TEXT` · `created_at TEXT NOT NULL`;
index `ix_placements_job(job_id)`. Every publish-adapter call records here;
dry_run rows carry recorded fixture responses. Verified honest (see integrations.md).

### 1.24 `pitch_attempts` (0003)
`id TEXT PK` · `job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE` ·
`handle/platform TEXT NOT NULL` · `angle TEXT NOT NULL` · `pitch_text TEXT NOT NULL` ·
`authorization_id TEXT REFERENCES authorizations(id) ON DELETE SET NULL` ·
`outcome TEXT NOT NULL DEFAULT 'no_response'` (no_response|accepted|declined|expired) ·
`sent_at TEXT NOT NULL` · `decided_at TEXT` · `note TEXT`;
index `ix_pitch_job(job_id)`. FK ✓.

### 1.25 `feedback_runs` (0003)
`id INTEGER PK AUTOINCREMENT` · `at TEXT NOT NULL` · `rows_consumed INTEGER NOT NULL` ·
`note TEXT`. Audit of each `feed_back` pass. Good.

### 1.26 `priors` (0003)
`dimension/value TEXT NOT NULL` · `n INTEGER NOT NULL DEFAULT 0` · `mean_perf REAL` ·
`min_n INTEGER NOT NULL DEFAULT 8` · `applied INTEGER NOT NULL DEFAULT 0` ·
`priors_version INTEGER NOT NULL` · `updated_at TEXT NOT NULL`;
PK `(dimension, value, priors_version)`. `applied=1 iff n>=min_n` written by
`feedback.snapshot_priors` (`hypelab/feedback.py:173-180`). **Provenance caveat:**
rows inherit whatever `feed_back` consumed — including unfiltered provenances
(DAT-350). Also note two guard values coexist: priors min_n=8, attribution read
n>=30 (`hypelab/attribution.py:35`) — documented separately, not a bug, but an
operator can be confused by priors "applied" at 8 while `worked` lists it
below-threshold until 30.

### 1.27 `collab_caps` (0003)
`adapter_name TEXT NOT NULL` · `adapter_version TEXT NOT NULL` ·
`max_collaborators INTEGER` (NULL = UNKNOWN → human review) ·
`source TEXT NOT NULL DEFAULT adapter` · `recorded_at TEXT NOT NULL`;
PK `(adapter_name, adapter_version)`. Versioned capability records; fail-closed
on unknown (`hypelab/publish/base.py:53-73`). Good design.

### 1.28 `schema_migrations` (runner-owned)
`version INTEGER PK` · `name TEXT NOT NULL` · `applied_at TEXT NOT NULL DEFAULT
(datetime('now'))`. Never appears in migration files (documented). OK.

## 2. FK/constraint audit summary

- **Declared FKs (all verified in the SQL):** job_events→jobs(CASCADE),
  edls→jobs(CASCADE), renders→jobs(CASCADE), gate_results→jobs(CASCADE),
  cost_ledger→jobs(SET NULL), sources→campaigns(CASCADE), source_items→sources(CASCADE),
  source_items→jobs(SET NULL), moments→jobs(CASCADE), clips→jobs(CASCADE),
  clips→moments, clips→campaigns, posts→clips(CASCADE), posts→jobs(CASCADE),
  metrics→posts(CASCADE), consents→jobs(SET NULL), consents→targets(composite),
  invites→posts(CASCADE), slides→jobs(CASCADE), moment_dedup→moments(CASCADE),
  compliance_log→clips(CASCADE), authorizations→jobs(CASCADE),
  post_placements→jobs(CASCADE), pitch_attempts→jobs(CASCADE),
  pitch_attempts→authorizations(SET NULL).
- **Missing FKs:** `jobs.kit_id` → `kits(id)`, `jobs.campaign_id` → `campaigns(id)`
  (DAT-360, S3). CLI paths validate in code (`cli.py:405-408` loads the kit;
  `watcher.py` uses the loaded campaign row), but direct `jobs.new()` callers can
  create orphan references.
- **Enforced in code, not schema (documented deviations):** `posts.posted_at` NOT NULL
  (0002 comment; enforced `hypelab/cut.py:250-289`), `consents.artifact_hash` NOT NULL
  (0003 comment; enforced `hypelab/consent.py:62-100`), `consents.expiry` mandatory
  (same). All three verified enforced. The policy rationale (SQLite can't ADD NOT
  NULL columns; additive-only migrations) is sound; the enforcement sites are the
  single writers, verified.
- **PRAGMA foreign_keys=ON** set on every connect (`hypelab/db.py:122,138`) and
  `journal_mode=WAL` (`db.py:121,137`). Multi-writer: WAL + 30s busy timeout; two
  workers on one file is supported at the SQLite level. `jobs.transition` uses
  `BEGIN IMMEDIATE` when it owns the transaction; `queue.claim`'s claim step is a
  single conditional `UPDATE…RETURNING` (atomic). → atomicity verdict in §4.

## 3. Index vs real query patterns

Covered: ix_jobs_state, ix_job_events_job_at, PK(edls), ix_moments_job,
ix_consents_job_handle, ix_auth_job_action, ix_pitch_job, ix_placements_job,
ix_slides_job, PK(metrics)(post_id,at) for best_views + INSERT OR REPLACE,
PK(priors), PK(what_worked), PK(targets).
Gaps (all S4, small-scale): `renders(job_id)`, `clips(job_id)`, `posts(clip_id)`,
`source_items(job_id)`, `sources(campaign_id)`, `invites(post_id)`, `slides(job_id,idx)`
uniqueness. None on a hot path at current scale; flag for growth.

## 4. Atomicity verdict

- **`jobs.transition`: atomic** when called standalone — `BEGIN IMMEDIATE` …
  UPDATE + `queue.log` INSERT … COMMIT, with ROLLBACK on failure
  (`hypelab/jobs.py:104-120`). Participates in an outer transaction when one is
  open (documented re-entrancy).
- **`queue.claim`: claim step atomic, claim+log not.** The two `UPDATE…RETURNING`
  statements are each atomic (exactly one worker wins), but the subsequent
  `queue.log()` INSERT is a separate autocommit statement (`hypelab/queue.py:92-124`).
  A crash in between leaves a moved state with no audit row. Same pattern in
  `release()` (SELECT-then-UPDATE, `queue.py:128-165`) and `fail()` (`queue.py:168-205`).
  → DAT-354 (S3): audit-loss window, not state corruption.
- **`jobs.transition` TOCTOU:** legality is checked with a SELECT *before* the
  BEGIN; two concurrent transitions can both pass on stale state (DAT-355, S3).
  The UPDATE itself doesn't re-verify `WHERE state=frm`.
- **`render()`: dual-write not atomic** — `manifest.json` append, then INSERT
  renders, INSERT edls, all in autocommit (`hypelab/render.py:497-528`). Crash
  → orphan file entry without DB rows, or renders row without edls row (DAT-356, S3).
- **`consent.grant`, `invites.add`, `record_posted`, `poll_invite_metrics`:** several
  multi-statement writers; `invites.add`/`poll_invite_metrics` call `conn.commit()`
  explicitly, which would also commit a caller's outer transaction
  (`hypelab/invites.py:78,218`) — inconsistent commit semantics (S3 note).
- **Multi-writer conclusion:** single conditional-UPDATE claims + WAL + BEGIN
  IMMEDIATE transitions make concurrent workers safe for the queue; the residual
  risks are audit-row loss and TOCTOU on transitions, both low-likelihood in the
  single-operator design.

## 5. Source-of-truth verdict

On disagreement, **the SQLite DB wins for every decision the code actually makes**;
the files are append-only evidence, and nothing cross-checks the two:

| Record | File write | DB write | Who reads it for decisions |
|---|---|---|---|
| render entry | `work/<id>/manifest.json` (atomic tmp+replace, `manifests.record_render`) | `renders` + `edls` rows | DB: hash-skip (`render._latest_render_hash`), gates read latest render/EDL from DB (`cli.py:761-767`) |
| gate verdicts | `manifest.json` measurements (loudness gate) | `gate_results` rows | CLI uses the in-memory return value; DB rows are history |
| quality outcome | — (no quality_report.json exists) | `gate_results` + job state | job state machine |
| costs | — | `cost_ledger` (write-dead) | `hypelab costs` reads DB |

`render_record.json` / `quality_report.json` do not exist in this codebase — the
dual is DB `renders`/`gate_results` vs `work/<id>/manifest.json` (+ per-dir files).
**On disagreement there is no arbiter:** nothing verifies the file entry against
the DB row (no cross-check in `render()` or `gates`). File is the tamper-evidence
log (sha256 re-hashing on `verify_manifest`); DB is the operational record. If they
diverge (crash mid-dual-write, DAT-356), the DB silently governs behavior while the
file claims otherwise. `jobs/` legacy dir (`jobs/job_c656669a5147/`, ~39MB tracked)
is superseded by `work/<id>/` and read by nothing.

## 6. Money/number provenance (for §7 of findings)

- `cost_ledger`: write-dead (DAT-352). `hypelab costs` totals are correct sums of
  an always-empty table — honest output of no data, but the feature is a shell.
- `payout_usd` (posts + metrics): never written anywhere → `usd_per_clip_hour`
  (the "$/clip-hour decides whether clipping is worth doing") always returns NULL
  (DAT-353). Estimates vs actuals: the ESTIMATE|/ACTUAL| convention exists only as
  docstring + test; no production rows ever carry either prefix.
- Scores: labeled (weight_version, confidence, signals_json) — traceable.
- Metrics/attribution: poisoned at the write path (DAT-350) and by fixture labeling
  (DAT-351). `worked`'s claim "reads calibration-grade metrics only" is true for
  `attribute()` but false for the `feed_back`→`what_worked` path that feeds priors.
- Campaign budgets: written, never enforced.

## 7. Migration/versioning verdict

- Versioned, ordered, additive-only; `EXPECTED_MIGRATIONS` in code vs
  `schema_migrations` in DB; foreign/downgrade DBs refused at boot. Each migration
  runs in ONE transaction with rollback. **No rollback path by policy** ("Downgrade:
  none") — deliberate, documented in 0002/0003 headers. State-machine migrations are
  versioned separately (`migrations/state_3_0.py`) with an additivity assertion.
- **`db.connect()` auto-migrates on every CLI invocation**, including read-only
  commands (`costs`, `worked`). Safe in content (additive, transactional) but a
  side-effecting read path; concurrent first-boot can fail one process with
  MigrationError (PK race on `schema_migrations`) → DAT-358 (S3).
- Seeds: no default credentials (no auth layer at all), no real people's data;
  `kits.seed_cerebratico` is operator-invoked from a shipped fictional kit.json;
  fixtures are synthetic ("Fixture Creator", "fixture-mart"). Safe.
