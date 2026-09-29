"""SQLite connections + migration runner (Book 1 improved, section 2).

Migration policy: ``migrations/`` holds numbered, additive ``*.sql`` files.
``migrate(conn)`` applies pending migrations in order — each in ONE
transaction — and records them in ``schema_migrations(version, name,
applied_at)``. Boot REFUSES when the database's migration set differs from
the code's expected set (a downgrade or a foreign DB is a hard error, not a
silent schema drift).

No business logic.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

#: version -> migration file stem. The code's expected migration set.
EXPECTED_MIGRATIONS = {
    1: "0001_book1_foundation",
    2: "0002_book2_clip_mine",
    3: "0003_book3_hype_layer",
}

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"

DEFAULT_DB_PATH = Path("/home/dino/hypelab/hypelab.db")

_SCHEMA_MIGRATIONS_DDL = """CREATE TABLE IF NOT EXISTS schema_migrations(
  version INTEGER PRIMARY KEY,
  name TEXT NOT NULL,
  applied_at TEXT NOT NULL DEFAULT (datetime('now'))
)"""


class MigrationError(Exception):
    """Raised when the migration set mismatches or a migration fails."""


def _migration_sql(version: int, name: str) -> str:
    path = MIGRATIONS_DIR / f"{name}.sql"
    if not path.is_file():
        raise MigrationError(
            f"migration file missing for version {version}: {path}"
        )
    return path.read_text(encoding="utf-8")


def _applied_versions(conn: sqlite3.Connection) -> dict[int, str]:
    conn.execute(_SCHEMA_MIGRATIONS_DDL)
    return {
        int(r[0]): str(r[1])
        for r in conn.execute("SELECT version, name FROM schema_migrations")
    }


def _split_statements(sql: str) -> list[str]:
    """Split a migration file into individual SQL statements.

    Uses sqlite3.complete_statement so semicolons inside string literals
    or comments do not split. Blank chunks are dropped.
    """
    stmts: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            if buf.strip():
                stmts.append(buf)
            buf = ""
    if buf.strip():
        stmts.append(buf)
    return stmts


def _apply_migration(conn: sqlite3.Connection, version: int, name: str) -> None:
    """Apply one migration file inside ONE transaction.

    NOTE: sqlite3's executescript() implicitly commits, so it cannot be
    used here — statements are executed one by one between an explicit
    BEGIN and COMMIT. Any failure rolls the whole migration back.
    """
    stmts = _split_statements(_migration_sql(version, name))
    if not stmts:
        raise MigrationError(f"migration {version} ({name}) is empty")
    conn.execute("BEGIN")
    try:
        for stmt in stmts:
            conn.execute(stmt)
        conn.execute(
            "INSERT INTO schema_migrations(version, name) VALUES(?,?)",
            (version, name),
        )
        conn.execute("COMMIT")
    except Exception as e:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        raise MigrationError(
            f"migration {version} ({name}) failed: {e}"
        ) from e


def migrate(conn: sqlite3.Connection) -> dict[int, str]:
    """Boot the database: apply pending migrations, then verify the set.

    Each pending migration runs inside ONE transaction (BEGIN ... COMMIT;
    any failure rolls back and raises MigrationError). After applying, the
    database's migration set must equal the code's expected set — otherwise
    boot is refused (e.g. a DB migrated by newer code, or a foreign DB).

    Returns the applied {version: name} map.
    """
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    applied = _applied_versions(conn)
    for version in sorted(EXPECTED_MIGRATIONS):
        if version in applied:
            continue
        _apply_migration(conn, version, EXPECTED_MIGRATIONS[version])
        applied[version] = EXPECTED_MIGRATIONS[version]
    db_set = set(_applied_versions(conn))
    expected_set = set(EXPECTED_MIGRATIONS)
    if db_set != expected_set:
        raise MigrationError(
            "migration set mismatch: database has "
            f"{sorted(db_set)}, code expects {sorted(expected_set)} — "
            "refusing to boot"
        )
    return applied


def connect(path=None) -> sqlite3.Connection:
    """Open the HypeLab SQLite DB and boot it through the migration runner.

    Defaults to /home/dino/hypelab/hypelab.db. Row factory is sqlite3.Row,
    30 s busy timeout, autocommit (isolation_level=None), WAL journal mode,
    foreign keys enforced.
    """
    p = Path(path) if path else DEFAULT_DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    cx = sqlite3.connect(str(p), timeout=30, isolation_level=None)
    cx.row_factory = sqlite3.Row
    cx.execute("PRAGMA journal_mode=WAL;")
    cx.execute("PRAGMA foreign_keys=ON;")
    migrate(cx)
    return cx
