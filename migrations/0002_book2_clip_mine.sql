-- 0002_book2_clip_mine: Book 2 (Clip Mine) additive schema.
--
-- Migration policy (improved Book 1, section 2; improved Book 2, section 2):
-- additive only on a live queue. New tables, new columns (nullable or with
-- defaults). No ALTER COLUMN, no DROP, no renames.
--
-- Deliberate deviation from the book's §2 SQL, documented:
-- posts.posted_at is declared NOT NULL in the book, but SQLite cannot add a
-- NOT NULL constraint to an existing column without a table rebuild, which
-- the migration policy forbids on a live queue. Enforcement lives in code:
-- `hypelab posted` always writes posted_at=now() and refuses a post without
-- one (fail closed). The schema column stays nullable.

-- campaigns: rate basis (observed|vendor_claim|unknown), budget provenance,
-- rules provenance (who wrote the rule, from which URL, when).
ALTER TABLE campaigns ADD COLUMN rate_basis TEXT NOT NULL DEFAULT 'observed';
ALTER TABLE campaigns ADD COLUMN budget_provenance TEXT;
ALTER TABLE campaigns ADD COLUMN rules_provenance TEXT;

-- sources: rights manifest JSON (§5a). NULL = no manifest recorded.
ALTER TABLE sources ADD COLUMN authorization TEXT;

-- source_items: hash of the downloaded source bytes (§5a).
ALTER TABLE source_items ADD COLUMN content_sha256 TEXT;

-- moments: which calibrated weight set scored this row (§6). Never NULL in
-- new rows; the default covers rows predating this migration.
ALTER TABLE moments ADD COLUMN weight_version TEXT NOT NULL DEFAULT 'unrecorded';
CREATE INDEX IF NOT EXISTS ix_moments_job ON moments(job_id);

-- clips: operator-logged work minutes (feeds $/work-hour, §11).
ALTER TABLE clips ADD COLUMN work_minutes REAL;

-- posts: payout when known. posted_at NOT NULL is enforced in code
-- (see note above), not in this migration.
ALTER TABLE posts ADD COLUMN payout_usd REAL;

-- metrics: provenance per row (§11): official_api | provider_api |
-- user_entered | unavailable. 'unavailable' rows carry NULL measures.
ALTER TABLE metrics ADD COLUMN provenance TEXT NOT NULL DEFAULT 'unknown';

-- duplicate detection: the same moment mined from two videos, or the same
-- video re-mined. content_hash = sha256 of (source content_sha256, t_in, t_out).
CREATE TABLE IF NOT EXISTS moment_dedup(
  content_hash TEXT PRIMARY KEY,
  moment_id TEXT NOT NULL REFERENCES moments(id) ON DELETE CASCADE,
  seen_at TEXT NOT NULL
);

-- compliance audit trail: every gate decision, who/what decided, why.
-- passed: 1 = pass, 0 = fail, NULL = UNKNOWN (routed to human).
CREATE TABLE IF NOT EXISTS compliance_log(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  clip_id TEXT NOT NULL REFERENCES clips(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  rules_version INTEGER NOT NULL,
  passed INTEGER,
  unknown_reasons TEXT,
  decided_by TEXT NOT NULL,
  note TEXT
);

-- what_worked (attribution target, §11) already exists from 0001.
-- Downgrade: none (additive migration; no downgrade path by policy).
