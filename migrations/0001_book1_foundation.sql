-- 0001_book1_foundation: Book 1 baseline schema (improved Book 1, section 4).
--
-- Migration policy (improved section 2): migrations are numbered, additive,
-- applied in order by hypelab.db, and recorded in schema_migrations.
-- Additive-only on a live queue: destructive migrations are forbidden
-- because the ledger is append-only and must remain readable.
--
-- Book 1 additions over the wave-1 schema: jobs gains lease_owner,
-- lease_expires, attempts, max_attempts (queue leases, improved section 5);
-- renders gains manifest_json (tool provenance per render, delta item 4).

CREATE TABLE jobs(
  id TEXT PRIMARY KEY,
  mode TEXT NOT NULL,
  state TEXT NOT NULL,
  kit_id TEXT,
  kit_version INTEGER,
  campaign_id TEXT,
  title TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  error TEXT,
  lease_owner TEXT,
  lease_expires TEXT,
  attempts INTEGER NOT NULL DEFAULT 0,
  max_attempts INTEGER NOT NULL DEFAULT 3
);
CREATE INDEX ix_jobs_state ON jobs(state);

CREATE TABLE job_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  from_state TEXT,
  to_state TEXT NOT NULL,
  note TEXT
);
CREATE INDEX ix_job_events_job_at ON job_events(job_id, at);

CREATE TABLE edls(
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  version INTEGER NOT NULL,
  render_json TEXT NOT NULL,
  render_hash TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY (job_id, version)
);

CREATE TABLE kits(
  id TEXT NOT NULL,
  version INTEGER NOT NULL,
  data_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY (id, version)
);

CREATE TABLE renders(
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  edl_version INTEGER NOT NULL,
  aspect TEXT NOT NULL,
  path TEXT NOT NULL,
  duration_s REAL,
  lufs REAL,
  manifest_json TEXT,
  created_at TEXT NOT NULL
);

CREATE TABLE gate_results(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  gate TEXT NOT NULL,
  passed INTEGER NOT NULL,
  detail TEXT,
  at TEXT NOT NULL
);

CREATE TABLE cost_ledger(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
  at TEXT NOT NULL,
  provider TEXT NOT NULL,
  unit TEXT NOT NULL,
  qty REAL NOT NULL,
  usd REAL NOT NULL,
  note TEXT
);

CREATE TABLE what_worked(
  dimension TEXT NOT NULL,
  value TEXT NOT NULL,
  n INTEGER NOT NULL DEFAULT 0,
  mean_perf REAL,
  updated_at TEXT,
  PRIMARY KEY (dimension, value)
);

CREATE TABLE campaigns(
  id TEXT PRIMARY KEY,
  marketplace TEXT,
  creator TEXT,
  rate_per_1k_usd REAL,
  budget_total_usd REAL,
  budget_seen_usd REAL,
  budget_checked TEXT,
  platforms TEXT NOT NULL,
  rules_json TEXT NOT NULL,
  rules_version INTEGER NOT NULL DEFAULT 1,
  submission_json TEXT,
  state TEXT NOT NULL DEFAULT 'active',
  created_at TEXT NOT NULL
);

CREATE TABLE sources(
  id TEXT PRIMARY KEY,
  campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  url TEXT NOT NULL,
  poll_every_s INTEGER NOT NULL DEFAULT 900,
  last_polled TEXT,
  last_item_id TEXT
);

CREATE TABLE source_items(
  id TEXT PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  url TEXT NOT NULL,
  title TEXT,
  duration_s REAL,
  published_at TEXT,
  seen_at TEXT NOT NULL,
  job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL
);

CREATE TABLE moments(
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  t_in REAL NOT NULL,
  t_out REAL NOT NULL,
  score REAL NOT NULL,
  confidence REAL NOT NULL,
  signals_json TEXT NOT NULL,
  transcript TEXT,
  picked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE clips(
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  moment_id TEXT REFERENCES moments(id),
  campaign_id TEXT REFERENCES campaigns(id),
  path TEXT NOT NULL,
  caption TEXT,
  tray_rank INTEGER,
  predicted REAL,
  compliance_json TEXT,
  state TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE posts(
  id TEXT PRIMARY KEY,
  clip_id TEXT REFERENCES clips(id) ON DELETE CASCADE,
  job_id TEXT REFERENCES jobs(id) ON DELETE CASCADE,
  platform TEXT NOT NULL,
  account TEXT,
  post_url TEXT NOT NULL,
  posted_at TEXT,
  post_id TEXT
);

CREATE TABLE metrics(
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  at TEXT NOT NULL,
  views INTEGER,
  likes INTEGER,
  shares INTEGER,
  saves INTEGER,
  comments INTEGER,
  payout_usd REAL,
  reject_note TEXT,
  PRIMARY KEY (post_id, at)
);

CREATE TABLE targets(
  handle TEXT NOT NULL,
  platform TEXT NOT NULL,
  followers INTEGER,
  engagement REAL,
  is_public INTEGER,
  pattern_json TEXT,
  corpus_path TEXT,
  contact_route TEXT,
  consent_state TEXT DEFAULT 'none',
  last_checked TEXT,
  PRIMARY KEY (handle, platform)
);

CREATE TABLE consents(
  id TEXT PRIMARY KEY,
  handle TEXT NOT NULL,
  platform TEXT NOT NULL,
  job_id TEXT REFERENCES jobs(id) ON DELETE SET NULL,
  pitched_at TEXT NOT NULL,
  responded_at TEXT,
  decision TEXT,
  scope TEXT,
  expiry TEXT,
  artifact TEXT NOT NULL,
  FOREIGN KEY (handle, platform) REFERENCES targets(handle, platform)
);

CREATE TABLE invites(
  id TEXT PRIMARY KEY,
  post_id TEXT NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  handle TEXT NOT NULL,
  invite_status TEXT NOT NULL,
  checked_at TEXT
);

CREATE TABLE slides(
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
  idx INTEGER NOT NULL,
  spec_json TEXT NOT NULL,
  path TEXT
);

-- NOTE: schema_migrations is owned by the runner (hypelab.db), not by
-- migration files. It is created with IF NOT EXISTS before any migration
-- runs and must never appear in a migration file.
