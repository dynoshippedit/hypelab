# DAT findings — Data & Integrations (Phase 2, 2026-09-29)
Lane prefix: DAT · ID range DAT-350–399 · all NEW, confidence Confirmed unless noted.
Severities per Playbook B7. "Evidence" = path:line + quoted code.

## DAT-350 — feed_back() consumes metrics with NO provenance filter, violating the calibration rule [S1, Confirmed]
**Location:** `hypelab/feedback.py:40-46` (`_best_views`), called by `feed_back()` (`feedback.py:48-120`).
**Evidence:**
```python
"\"\"SELECT MAX(views) v FROM metrics
   WHERE post_id=? AND views IS NOT NULL\"\"\"   # no provenance predicate
```
`metrics.py:12` documents: "Calibration (§6/§11) uses official_api + provider_api
rows ONLY — never user_entered." `feed_back` ignores this: any `views` value —
`user_entered` (operator-typed screenshots), `unavailable` (NULL, filtered only by
the IS NOT NULL), `unknown`, and fixture rows — flows into `what_worked` and then
`snapshot_priors` → `priors` with `applied=1` at n>=8 (`feedback.py:156-180`), where
the read side is told to "honor applied, never n alone."
**What's wrong:** the write path that feeds production priors has no provenance
gate, while every read path (`metrics.best_views`, `attribution.attribute`) does.
**Impact:** uncalibrated numbers (screenshots, fixtures) can become applied
production priors that steer cuts/pitches. Data-integrity risk on the feedback loop.
**Suggested fix:** add `AND provenance IN ('official_api','provider_api')` to
`_best_views`, matching `attribution.py:57-68`. PRE-APPROVED (bug fix restoring
documented behavior).

## DAT-351 — recorded fixtures written with calibration-grade provenance 'provider_api' [S2, Confirmed]
**Location:** `hypelab/invites.py:185-220` (`poll_invite_metrics`).
**Evidence:**
```python
"\"\"INSERT OR REPLACE INTO metrics(post_id, at, views, likes,
 comments, shares, saves, provenance, reject_note)
 VALUES(?,?,?,?,?,?,?,?,?)\"\"\"",
(pid, at, fx.get("views"), ..., "provider_api",
 "recorded fixture (dry-run build; real posts are Dino-gated)"),
```
**What's wrong:** fixture values are stamped `provenance='provider_api'` — a
calibration-grade provenance. The only marker is `reject_note`, which **no
calibration reader checks**: `attribution.attribute()` filters on provenance IN
('official_api','provider_api') (`attribution.py:57-68`) and `metrics.best_views`
does the same (`metrics.py:54-66`). A fixture row passes both.
**Impact:** if this function is ever called, synthetic numbers pollute
attribution/what_worked as calibration-grade data. Currently **unwired** — no CLI
command calls it (grep-verified across `cli.py`, `b2cli.py`, `book3cli.py`) — so
latent, not live. S2 for that reason (would be S1 if wired).
**Suggested fix:** write fixtures with `provenance='unavailable'` (or a dedicated
`'fixture'` rank-0 value) and/or filter `reject_note IS NULL` in calibration
readers. PRE-APPROVED.

## DAT-352 — cost_ledger is write-dead: queue.charge() has no production callers [S2, Confirmed]
**Location:** `hypelab/queue.py:215-232` (definition); absence across `hypelab/cli.py`,
`hypelab/b2cli.py`, `hypelab/book3cli.py`, `hypelab/align.py`, `hypelab/render.py`,
`hypelab/cut.py`, `hypelab/ingest.py` (grep-verified zero call sites).
**Evidence:** the only references are the def, a docstring mention in
`hypelab/util.py:182`, and tests. `hypelab costs` (`cli.py:940-971`) always prints
"no cost rows recorded" on a real database.
**What's wrong:** the documented cost-accounting feature (ESTIMATE|/ACTUAL|
convention, estimate-vs-actual totals) can never produce a row; the CLI command is
a shell.
**Impact:** operators believe costs are tracked; they are not. No wrong numbers
are shown (empty ledger prints honestly), so not S0/S1.
**Suggested fix:** wire `charge()` into the align/render/publish cost points, or
remove the command and document the gap. NEEDS-OWNER (product decision) — log as
finding; recommend the question in QUESTIONS.md.

## DAT-353 — payout_usd is never written: $/clip-hour is always NULL [S2, Confirmed]
**Location:** `hypelab/cut.py:286-289` (INSERTs NULL); absence of any
`UPDATE posts SET payout_usd` / metrics-column write (grep-verified).
**Evidence:** `record_posted` docstring: "payout_usd is filled in later from the
campaign's rate basis (see posted CLI)" — no code does this. `metrics.py:119-135`
`usd_per_clip_hour` ("the number that decides whether clipping is worth doing")
`SUM(p.payout_usd)` over all-NULL → `earned` NULL, `usd_per_hour` NULL for every
campaign. `metrics.payout_usd` column is likewise never written (both poll INSERTs
omit it).
**Impact:** the headline economic metric is uncomputable; any UI/CLI consumer sees
NULLs, not wrong values.
**Suggested fix:** implement the documented rate-basis payout fill (campaign
`rate_per_1k_usd` × views at measure time), or drop the column/metric.

## DAT-354 — claim/fail/release move state and log in separate autocommit statements [S3, Confirmed]
**Location:** `hypelab/queue.py:92-124` (claim: UPDATE…RETURNING then `log()`),
`hypelab/queue.py:128-165` (release: SELECT then UPDATE then `log()`),
`hypelab/queue.py:168-205` (fail: SELECT checks then UPDATE then `log()`).
**Evidence:** connections run `isolation_level=None` (autocommit, `db.py:139`);
each statement commits independently. Only `jobs.transition` wraps
UPDATE+log in BEGIN IMMEDIATE…COMMIT (`hypelab/jobs.py:104-120`).
**What's wrong:** the claim *itself* is atomic (single conditional UPDATE), but a
crash between the state UPDATE and the `job_events` INSERT loses the audit row —
silent divergence between the state machine and its audit trail.
**Impact:** rare (microsecond window), single-operator design; integrity of the
audit log, not of state. S3.

## DAT-355 — transition() checks legality outside the transaction (TOCTOU) [S3, Confirmed]
**Location:** `hypelab/jobs.py:96-120`.
**Evidence:** `SELECT state …` → Python legality check → `BEGIN IMMEDIATE` →
`UPDATE jobs SET state=? … WHERE id=?` (no `AND state=frm` predicate).
**What's wrong:** two concurrent transitions can both pass the check on the same
stale `frm`; the second overwrites the first's move without re-validation.
**Impact:** theoretical under the single-worker design; the UPDATE is serialized
by BEGIN IMMEDIATE but the *check* is not.
**Suggested fix:** add `AND state=?` to the UPDATE and raise on `rowcount==0`.

## DAT-356 — render() dual-writes file + DB without atomicity [S3, Confirmed]
**Location:** `hypelab/render.py:497-528`.
**Evidence:** `manifests_mod.record_render(work, manifest_entry)` (file, atomic
tmp+replace) → `INSERT INTO renders …` → `INSERT INTO edls …`, all in autocommit;
`conn.commit()` at the end is a no-op under autocommit.
**What's wrong:** crash between steps leaves a manifest.json render entry with no
DB rows, or a renders row with no edls row. Nothing cross-checks file vs DB
afterward (see data-model.md §5: DB silently wins decisions; the file claims
otherwise).
**Impact:** rare, operator-visible only via manual inspection.
**Suggested fix:** wrap the two INSERTs in BEGIN IMMEDIATE…COMMIT (file write
can't join the tx, but ordering file-last after DB commit narrows the window).

## DAT-357 — money stored as REAL float dollars, not integer cents [S3, Confirmed]
**Location:** schema (`cost_ledger.usd`, `posts.payout_usd`, `metrics.payout_usd`,
`campaigns.rate_per_1k_usd/budget_*_usd` all REAL) + `hypelab/cli.py:970-971`
(`sum(r["usd"] …)` in float, formatted `%.2f`).
**What's wrong:** float accumulation (e.g. 0.1+0.2) before the display rounding;
`usd_per_clip_hour` returns raw floats to callers.
**Impact:** cosmetic at current magnitudes; no production rows exist yet
(DAT-352). S3 — worth fixing when cost recording is wired (migrate to integer
cents or NUMERIC).

## DAT-358 — db.connect() auto-migrates on every invocation, incl. read-only commands [S3, Confirmed]
**Location:** `hypelab/db.py:130-145` (`connect()` → `migrate(cx)`); called by
every CLI command via `_conn()` (`cli.py:90-91`, `b2cli.py:50-51`,
`book3cli.py:46-47`).
**What's wrong:** a read-only command (`costs`, `worked`, `measure`) mutates the
production DB file as a side effect. Content is safe (additive, transactional,
set-verified), but: (a) two processes booting a fresh DB concurrently can race —
both apply the same pending migration, the loser's `INSERT INTO schema_migrations`
fails the PK → spurious `MigrationError`; (b) no `--no-migrate` escape hatch.
**Impact:** low (single-operator CLI). S3.

## DAT-359 — missing indexes on real query patterns [S4, Confirmed]
Reads with no supporting index (verified against the SQL files): `renders(job_id)`
(`cli.py:761` ORDER BY rowid DESC), `clips(job_id)` (`compliance.py:300`,
`cut.py:293`, `tray.py:33`), `posts(clip_id)` (`metrics.open_posts` JOIN),
`source_items(job_id)` (`ingest.py:66`, `cut.py:161`, `score.py:388`),
`sources(campaign_id)` (`watcher._due_sources`), `invites(post_id)`.
Also `slides` lacks UNIQUE(job_id, idx) and `moment_dedup` relies on
`content_sha256` that the watcher INSERT omits (`watcher.py:257-263` predates the
0002 column). None on a hot path at current scale — S4, revisit with growth.

## DAT-360 — no FK on jobs.kit_id / jobs.campaign_id [S3, Confirmed]
**Location:** `migrations/0001_book1_foundation.sql` (`jobs` table: `kit_id TEXT`,
`campaign_id TEXT`, no REFERENCES).
**What's wrong:** orphan references possible via direct `jobs.new()` callers.
Mitigated in the CLI: `hypelab new` loads the kit first (`cli.py:405-408`);
`watcher.py:267` uses the loaded campaign row. The API itself doesn't enforce it.
**Impact:** low; S3.

## DAT-361 — edge-tts referenced by docs, never by code [S4, Confirmed]
**Location:** absence in `hypelab/` + `tests/` (case-insensitive grep: zero hits);
mentions only in README.md, ARCHITECTURE.md, VERTICAL_SLICE_REPORT.md.
Recorded for DOC lane (claims audit); no code action. S4.

## DAT-362 — consent.grant() validates expiry presence, not value [S3, Confirmed]
**Location:** `hypelab/consent.py:73` (`if not expires_at: raise` — presence only).
**What's wrong:** a grant with a past or malformed expiry string records
successfully, then immediately fails `gate_consent` (`consent.py:172-173`
`expiry > ?`). Fail-closed downstream, but the recorded row is dead on arrival.
**Impact:** operator confusion; S3.

## DAT-363 — metrics.provenance default 'unknown' vs documented 'unavailable' semantics [S4, Confirmed]
**Location:** `migrations/0002_book2_clip_mine.sql` (`DEFAULT 'unknown'`);
`metrics.py` docstring describes 'unavailable' rows as the NULL-measure
convention. Both rank 0 in `PROVENANCE_RANK`. Harmless inconsistency; S4.

## DAT-364 — faster-whisper model auto-download contradicts the module's network policy [S2, Confirmed]
**Location:** `hypelab/align.py:114-153` (`transcribe()` → `WhisperModel(cfg["model"])`);
module docstring `align.py:14-16` claims `fetch_model` is "the ONLY function in
this module allowed to touch the network."
**Evidence:** faster-whisper downloads the `medium` weights from the HF Hub on
first use — no checksum, no `revision` pin, no size guard, no timeout. Same for
`fetch_model`'s `from_pretrained` (no revision pin, no checksum). Corroborates
TST-005/006.
**Impact:** supply-chain surface + undeclared network egress on the ASR path;
operator-initiated, so S2 not S1.

## Rejected / not findings

- **FK enforcement:** `PRAGMA foreign_keys=ON` + `journal_mode=WAL` set on every
  connect (`db.py:121-122,137-138`). All 28 tables' FKs verified declared (see
  data-model.md §2). No issue.
- **Consent gate:** expiry/revocation/actor/scope all enforced fail-closed
  (`consent.py:62-100`, `168-187`); the 0003 deviations (nullable `artifact_hash`,
  `expiry` mandatory-in-code) verified enforced. No issue.
- **Publish honesty:** all four adapters raise `LiveRefused` on live; dry_run is
  labeled (`dryrun_` ids, `dry_run=1` ledger, `dryrun://` URLs). Metrics
  "unavailable" rows are honest. No issue beyond DAT-350/351.
- **Seeds/fixtures:** no credentials, no real personal data (synthetic "Fixture
  Creator"/"fixture-mart"); kit seeding is operator-invoked. No issue.
- **`_transition_job` invite→job mapping:** only receives
  accepted/declined/accept_timeout — all legal from `awaiting_accept`. No issue
  (the `except ValueError: pass` is genuinely unreachable-today defensive).
- **MAP "23 tables":** actually 28 (+schema_migrations) — MAP inaccuracy, noted
  in data-model.md; MAP lane's count to correct.
