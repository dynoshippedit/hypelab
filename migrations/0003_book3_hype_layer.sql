-- 0003_book3_hype_layer: Book 3 (Hype Layer) additive schema.
--
-- Migration policy (improved Book 1, section 2; improved Book 3, section 1):
-- additive only on a live queue. New tables, new nullable columns (or with
-- defaults). No ALTER COLUMN, no DROP, no renames.
--
-- Deliberate deviations from the book's section-1 SQL, documented:
-- 1. consents: the book declares artifact_hash TEXT NOT NULL and a fresh
--    table. consents already exists from 0001 with artifact TEXT NOT NULL
--    (a path). SQLite cannot add a NOT NULL column without a default, and
--    the migration policy forbids a table rebuild. So artifact_hash is
--    added nullable and NOT NULL is enforced in code: consent.grant()
--    always hashes the artifact and refuses a grant without one
--    (fail closed). Same pattern as 0002's posts.posted_at deviation.
-- 2. consents.expiry: the book's field list names it `expiry`; the task
--    brief calls it expires_at and mandates it. The 0001 column `expiry`
--    is canonical (adding a second expires_at column would be two sources
--    of truth). Mandatory-ness is enforced in code: grant() refuses a
--    consent with no expiry.
-- 3. authorizations gains platform + intent columns (the book's SQL shows
--    only id/job_id/action/actor/authorized_at/note; the task brief
--    requires pitch|publish|invite x actor x platform intent+approval
--    pairs). Additive, no conflict.
-- 4. feed_back/priors: the book's feed_back writes into Book 2's
--    what_worked and reads it back with a min_n=8 guard. New tables
--    feedback_runs (audit of each feed_back pass) and priors (versioned
--    production-prior snapshots with their min_n and applied flag).
-- 5. post_placements: the placement ledger for the publish adapter
--    (dry_run request recording lives here; zero live calls).
-- 6. pitch_attempts: every pitch attempt logged, including no_response.

-- targets: publicity observation timestamp + corpus consent timestamp
-- (book section 1/4: is_public is a cached observation, never a fact).
ALTER TABLE targets ADD COLUMN is_public_checked_at TEXT;
ALTER TABLE targets ADD COLUMN corpus_consent_at TEXT;
ALTER TABLE targets ADD COLUMN invite_stats_json TEXT NOT NULL DEFAULT '{}';

-- consents: hash-pinned artifacts, revocation, actor identity,
-- jurisdiction + terms version. All new columns; existing rows keep
-- working (legacy rows have no hash -> they fail the new gate, which is
-- the fail-closed-correct behavior: re-grant under the new schema).
ALTER TABLE consents ADD COLUMN actor TEXT;
ALTER TABLE consents ADD COLUMN account_id TEXT;
ALTER TABLE consents ADD COLUMN artifact_hash TEXT;
ALTER TABLE consents ADD COLUMN artifact_path TEXT;
ALTER TABLE consents ADD COLUMN revoked_at TEXT;
ALTER TABLE consents ADD COLUMN revoked_by TEXT;
ALTER TABLE consents ADD COLUMN revocation_note TEXT;
ALTER TABLE consents ADD COLUMN jurisdiction TEXT;
ALTER TABLE consents ADD COLUMN terms_version TEXT;
ALTER TABLE consents ADD COLUMN recorded_at TEXT;
CREATE INDEX IF NOT EXISTS ix_consents_job_handle
  ON consents(job_id, handle, platform);

-- invites: creation timestamp (drives the 72h accept_timeout rule).
ALTER TABLE invites ADD COLUMN created_at TEXT;

-- authorizations: Dino's explicit approval rows. Consent is the creator's
-- grant; authorization is Dino's approval to act. Separate tables,
-- separate concerns (book section 5).
CREATE TABLE IF NOT EXISTS authorizations(
  id            TEXT PRIMARY KEY,
  job_id        TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  action        TEXT NOT NULL,   -- pitch | publish | invite
  actor         TEXT NOT NULL,   -- who authorized: "dino" (or a named delegate)
  platform      TEXT,            -- platform the action targets, when known
  intent        TEXT,            -- operator-stated intent, verbatim
  authorized_at TEXT NOT NULL,
  note          TEXT
);
CREATE INDEX IF NOT EXISTS ix_auth_job_action
  ON authorizations(job_id, action);

-- slides: rendered carousel slides, one row per slide.
CREATE TABLE IF NOT EXISTS slides(
  id        TEXT PRIMARY KEY,
  job_id    TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  idx       INTEGER NOT NULL,
  spec_json TEXT NOT NULL,
  path      TEXT
);
CREATE INDEX IF NOT EXISTS ix_slides_job ON slides(job_id);

-- post_placements: the placement ledger. Every publish-adapter call,
-- dry_run or live, records its request here. dry_run rows carry the
-- recorded fixture response; live rows are Dino-gated (none exist yet).
CREATE TABLE IF NOT EXISTS post_placements(
  id               TEXT PRIMARY KEY,
  job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  post_id          TEXT,          -- provider post id (NULL in dry_run)
  platform         TEXT NOT NULL,
  adapter          TEXT NOT NULL, -- dryrun | meta | postiz | zernio | ayrshare
  dry_run          INTEGER NOT NULL DEFAULT 1,
  collaborators_json TEXT NOT NULL DEFAULT '[]',
  caption          TEXT,
  media_json       TEXT,          -- list of published media paths
  asset_sha256     TEXT,          -- fingerprint of the published media set
  is_ai_generated  INTEGER NOT NULL DEFAULT 1,
  consent_ids_json TEXT,          -- consent ids re-checked at publish time
  request_json     TEXT,          -- recorded request payload
  response_json    TEXT,          -- recorded fixture / provider response
  created_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_placements_job ON post_placements(job_id);

-- pitch_attempts: every pitch attempt, including no_response after 14d.
CREATE TABLE IF NOT EXISTS pitch_attempts(
  id               TEXT PRIMARY KEY,
  job_id           TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  handle           TEXT NOT NULL,
  platform         TEXT NOT NULL,
  angle            TEXT NOT NULL,
  pitch_text       TEXT NOT NULL,
  authorization_id TEXT REFERENCES authorizations(id) ON DELETE SET NULL,
  outcome          TEXT NOT NULL DEFAULT 'no_response',
                                 -- no_response | accepted | declined | expired
  sent_at          TEXT NOT NULL,
  decided_at       TEXT,
  note             TEXT
);
CREATE INDEX IF NOT EXISTS ix_pitch_job ON pitch_attempts(job_id);

-- feedback_runs: audit trail of each feed_back pass.
CREATE TABLE IF NOT EXISTS feedback_runs(
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  at            TEXT NOT NULL,
  rows_consumed INTEGER NOT NULL,
  note          TEXT
);

-- priors: versioned production-prior snapshots. min_n is stored per row;
-- applied=1 iff n >= min_n. Reading code must honor applied, never n alone.
CREATE TABLE IF NOT EXISTS priors(
  dimension      TEXT NOT NULL,
  value          TEXT NOT NULL,
  n              INTEGER NOT NULL DEFAULT 0,
  mean_perf      REAL,
  min_n          INTEGER NOT NULL DEFAULT 8,
  applied        INTEGER NOT NULL DEFAULT 0,
  priors_version INTEGER NOT NULL,
  updated_at     TEXT NOT NULL,
  PRIMARY KEY (dimension, value, priors_version)
);

-- collab_caps: versioned per-adapter collaborator capability records.
-- max_collaborators NULL = UNKNOWN (preflight routes to human review).
-- Written by publish.record_collab_caps() at publish preflight time.
CREATE TABLE IF NOT EXISTS collab_caps(
  adapter_name      TEXT NOT NULL,
  adapter_version   TEXT NOT NULL,
  max_collaborators INTEGER,
  source            TEXT NOT NULL DEFAULT adapter,
  recorded_at       TEXT NOT NULL,
  PRIMARY KEY (adapter_name, adapter_version)
);

-- Downgrade: none (additive migration; no downgrade path by policy).
