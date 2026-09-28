"""SQLite schema, migrations, and connections. WAL mode. No business logic."""
from __future__ import annotations
import sqlite3
from pathlib import Path
from . import config

SCHEMA = """
PRAGMA journal_mode=WAL;

CREATE TABLE IF NOT EXISTS jobs(
  id TEXT PRIMARY KEY, mode TEXT NOT NULL, state TEXT NOT NULL,
  kit_id TEXT NOT NULL, kit_version INTEGER NOT NULL, campaign_id TEXT,
  title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  cost_usd REAL NOT NULL DEFAULT 0, budget_usd REAL,
  error TEXT, gate_failures_json TEXT
);
CREATE TABLE IF NOT EXISTS tasks(
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES jobs(id),
  kind TEXT NOT NULL, state TEXT NOT NULL,
  payload_json TEXT NOT NULL, result_json TEXT,
  attempts INTEGER NOT NULL DEFAULT 0, max_attempts INTEGER NOT NULL DEFAULT 3,
  lease_owner TEXT, lease_expires TEXT,
  idempotency_key TEXT NOT NULL UNIQUE, run_after TEXT NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tasks_claim ON tasks(state, run_after, created_at);
CREATE TABLE IF NOT EXISTS kits(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, owner TEXT NOT NULL DEFAULT 'brand',
  created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS kit_versions(
  kit_id TEXT NOT NULL, version INTEGER NOT NULL,
  appearance_text TEXT NOT NULL, ref_image_path TEXT, voice_ref_path TEXT,
  writing_samples_json TEXT NOT NULL, typography_json TEXT NOT NULL,
  colors_json TEXT NOT NULL, caption_style_json TEXT NOT NULL,
  guardrails_json TEXT NOT NULL, max_clip_len_s REAL NOT NULL,
  created_at TEXT NOT NULL, PRIMARY KEY (kit_id, version));
CREATE TABLE IF NOT EXISTS assets(
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, slot TEXT NOT NULL,
  path TEXT NOT NULL, sha256 TEXT NOT NULL, bytes INTEGER NOT NULL,
  kind TEXT NOT NULL, provenance TEXT NOT NULL,
  duration_s REAL, width INTEGER, height INTEGER, fps REAL,
  created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_assets_job_slot ON assets(job_id, slot);
CREATE TABLE IF NOT EXISTS edls(
  job_id TEXT PRIMARY KEY, version INTEGER NOT NULL,
  render_json TEXT NOT NULL, render_hash TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS targets(
  handle TEXT NOT NULL, platform TEXT NOT NULL, followers INTEGER, er REAL,
  public INTEGER, pattern_json TEXT, contact_route TEXT,
  consent_state TEXT, invite_history_json TEXT, outcome TEXT,
  PRIMARY KEY (handle, platform));
CREATE TABLE IF NOT EXISTS consents(
  id TEXT PRIMARY KEY, target_handle TEXT NOT NULL, target_platform TEXT NOT NULL,
  job_id TEXT NOT NULL, pitched_at TEXT, responded_at TEXT,
  scope TEXT NOT NULL, asset_version TEXT NOT NULL,
  evidence TEXT NOT NULL, expiry TEXT NOT NULL, revoked_at TEXT);
CREATE TABLE IF NOT EXISTS posts(
  id TEXT PRIMARY KEY, job_id TEXT, clip_id TEXT, platform TEXT,
  post_url TEXT, posted_at TEXT, collaborator TEXT, dry_run INTEGER NOT NULL DEFAULT 1);
CREATE TABLE IF NOT EXISTS metrics(
  post_id TEXT NOT NULL, t TEXT NOT NULL, views INTEGER, likes INTEGER,
  comments INTEGER, shares INTEGER, saves INTEGER,
  PRIMARY KEY (post_id, t));
CREATE TABLE IF NOT EXISTS what_worked(
  dimension TEXT NOT NULL, value TEXT NOT NULL, n INTEGER NOT NULL,
  mean_perf REAL NOT NULL, updated_at TEXT NOT NULL,
  PRIMARY KEY (dimension, value));
CREATE TABLE IF NOT EXISTS cost_ledger(
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, task_id TEXT,
  provider TEXT NOT NULL, units REAL NOT NULL, usd REAL NOT NULL,
  note TEXT, created_at TEXT NOT NULL);
"""

def connect(path: Path | None = None) -> sqlite3.Connection:
    p = Path(path) if path else config.db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(str(p), timeout=30.0, isolation_level=None)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL;")
    cx.execute("PRAGMA foreign_keys=ON;")
    return cx

def migrate(cx: sqlite3.Connection) -> None:
    cx.executescript(SCHEMA)
