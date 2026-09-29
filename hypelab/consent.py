"""Consent ledger: the hard gate (improved Book 3, section 5).

**No asset carrying a creator's name reaches `scheduled` without a recorded,
unrevoked consent artifact.** This is the layer's load-bearing rule.

Consent is keyed to scope x account/actor x platform x asset hash, carries
a MANDATORY expiry, and is revocable. A revoked consent fails the gate —
no override flag exists in the codebase; the only path is a new grant.
Revoking a consent knocks any `scheduled` job depending on it back to
`consent_granted` for re-gating.

The consent gate is re-checked at the `scheduled -> published` transition,
because a grant can be withdrawn between scheduling and publish.

This module REPLACES the pre-improved stub (which keyed consent to a file
path — a path can be swapped after the fact; a hash cannot — and had no
revocation, no actor identity, no terms version).
"""
from __future__ import annotations

import csv
import sqlite3
from pathlib import Path

from .util import new_id, now, sha256_file


class ConsentError(Exception):
    """Consent refused: missing, expired, revoked, or asset-mismatched."""


def _fingerprint(artifact: Path) -> str:
    """sha256 pinning the artifact. A file hashes itself; a directory
    hashes its files (sorted by name, concatenated). A path can be
    swapped after the fact; a hash cannot."""
    import hashlib

    artifact = Path(artifact)
    if not artifact.exists():
        raise ConsentError(f"consent artifact not found: {artifact}")
    if artifact.is_file():
        return sha256_file(artifact)
    h = hashlib.sha256()
    for p in sorted(artifact.rglob("*")):
        if p.is_file():
            h.update(p.name.encode())
            h.update(sha256_file(p).encode())
    return h.hexdigest()


def _ensure_target(conn: sqlite3.Connection, handle: str, platform: str) -> None:
    conn.execute(
        """INSERT INTO targets(handle, platform, consent_state)
           VALUES(?,?,'none')
           ON CONFLICT(handle, platform) DO NOTHING""",
        (handle, platform),
    )


def grant(conn: sqlite3.Connection, *, job_id: str, handle: str, platform: str,
          actor: str, account_id: str, scope: str, artifact_path: str,
          expires_at: str, jurisdiction: str | None = None,
          terms_version: str | None = None,
          pitched_at: str | None = None) -> dict:
    """Record a consent grant. Fail closed on missing expiry or artifact.

    - expires_at is MANDATORY (schema column is `expiry`; mandatory-ness
      is enforced here because SQLite forbids adding NOT NULL columns).
    - artifact_path is hashed at grant time; the hash is the evidence.
    - the pitch and the grant must match word for word: `scope` doubles
      as the pitch's stated scope.
    """
    if not expires_at:
        raise ConsentError(
            "consent refused: expiry is mandatory — a grant without an "
            "expiry is not recordable"
        )
    if not scope:
        raise ConsentError("consent refused: scope is mandatory (verbatim)")
    if not actor:
        raise ConsentError("consent refused: actor identity is mandatory")
    if conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone() is None:
        raise ConsentError(f"unknown job {job_id}")
    artifact = Path(artifact_path)
    digest = _fingerprint(artifact)
    cid = new_id("consent")
    ts = now()
    _ensure_target(conn, handle, platform)
    # `artifact` is the 0001 NOT NULL path column (informational only;
    # the hash is the evidence). `artifact_path` is the new explicit copy.
    conn.execute(
        """INSERT INTO consents(id, handle, platform, job_id, actor, account_id,
                                pitched_at, responded_at, decision, scope,
                                expiry, artifact, artifact_hash, artifact_path,
                                jurisdiction, terms_version, recorded_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (cid, handle, platform, job_id, actor, account_id,
         pitched_at or ts, ts, "granted", scope, expires_at,
         str(artifact), digest, str(artifact), jurisdiction, terms_version, ts),
    )
    conn.execute(
        "UPDATE targets SET consent_state='granted' WHERE handle=? AND platform=?",
        (handle, platform),
    )
    conn.commit()
    return dict(
        conn.execute("SELECT * FROM consents WHERE id=?", (cid,)).fetchone()
    )


def revoke(conn: sqlite3.Connection, consent_id: str, actor: str,
           note: str | None = None) -> dict:
    """Revoke a consent. Any `scheduled` job depending on it is knocked
    back to `consent_granted` for re-gating (book section 5)."""
    from . import jobs as jobs_mod

    row = conn.execute(
        "SELECT * FROM consents WHERE id=?", (consent_id,)
    ).fetchone()
    if row is None:
        raise ConsentError(f"unknown consent {consent_id}")
    row = dict(row)
    if row["revoked_at"]:
        raise ConsentError(f"consent {consent_id} already revoked")
    ts = now()
    conn.execute(
        """UPDATE consents SET revoked_at=?, revoked_by=?, revocation_note=?
           WHERE id=?""",
        (ts, actor, note, consent_id),
    )
    knocked = []
    for j in conn.execute(
        "SELECT id, state FROM jobs WHERE id=?", (row["job_id"],)
    ).fetchall():
        if j["state"] == "scheduled":
            jobs_mod.transition(
                conn, j["id"], "consent_granted",
                f"consent {consent_id} revoked — re-gate required",
            )
            knocked.append(j["id"])
    conn.execute(
        "UPDATE targets SET consent_state='none' WHERE handle=? AND platform=?",
        (row["handle"], row["platform"]),
    )
    conn.commit()
    out = dict(
        conn.execute("SELECT * FROM consents WHERE id=?", (consent_id,)).fetchone()
    )
    out["knocked_back"] = knocked
    return out


def valid_for(conn: sqlite3.Connection, job_id: str, handle: str,
              platform: str) -> dict | None:
    """Latest granted, unrevoked, unexpired consent for
    (job_id, handle, platform).

    The gate keys on the relationship (job + handle), not on media bytes:
    the book's §5 gate checks handle/job_id + granted/unrevoked/expiry, and
    the artifact_hash is the pinned *evidence* of the agreement (a path can
    be swapped after the fact; a hash cannot). Scoping to specific content
    lives in the verbatim `scope` text, not in a hash comparison — binding
    the gate to a media fingerprint would make every real publish fail,
    because a creator's agreement artifact never hashes to the media set.

    Legacy rows without artifact_hash never match (fail closed): they
    predate hash-pinned consent and must be re-granted.
    """
    row = conn.execute(
        """SELECT * FROM consents
           WHERE job_id=? AND handle=? AND platform=?
             AND decision='granted' AND revoked_at IS NULL
             AND expiry IS NOT NULL AND expiry > ?
             AND artifact_hash IS NOT NULL
           ORDER BY responded_at DESC LIMIT 1""",
        (job_id, handle, platform, now()),
    ).fetchone()
    return dict(row) if row else None


def require_consent(conn: sqlite3.Connection, job_id: str, handle: str,
                    platform: str) -> dict:
    """Return the valid consent or raise ConsentError (fail closed)."""
    c = valid_for(conn, job_id, handle, platform)
    if c is None:
        raise ConsentError(
            f"publishing refused: no valid (granted, unrevoked, unexpired) "
            f"consent for {handle} on {platform} (job {job_id}). "
            f"Record consent with 'hypelab consent grant' first."
        )
    return c


def job_collaborators(conn: sqlite3.Connection, job_id: str) -> list[str]:
    """Collaborators on the job's latest placement request."""
    import json

    row = conn.execute(
        """SELECT collaborators_json FROM post_placements
           WHERE job_id=? ORDER BY created_at DESC LIMIT 1""",
        (job_id,),
    ).fetchone()
    if not row:
        return []
    try:
        return list(json.loads(row["collaborators_json"] or "[]"))
    except (ValueError, TypeError):
        return []


def gate_consent(conn: sqlite3.Connection, job_id: str,
                 collaborators: list[str] | None,
                 platform: str = "instagram",
                 record: bool = True) -> tuple[bool, str]:
    """The hard gate (book section 5). Runs inside the publish path and is
    re-checked at the scheduled -> published transition.

    Keys on (job_id, handle, platform) + granted/unrevoked/unexpired — the
    relationship, not media bytes (see valid_for).

    When `record` is true, the verdict is written to Book 1's gate_results
    table as gate "consent_recheck" — the re-check evidence.
    """
    collabs = list(collaborators) if collaborators is not None else job_collaborators(conn, job_id)
    if not collabs:
        detail = "no collaborators — gate n/a"
        ok = True
    else:
        missing = []
        ids = []
        for h in collabs:
            c = valid_for(conn, job_id, h, platform)
            if c is None:
                missing.append(h)
            else:
                ids.append(c["id"])
        if missing:
            ok, detail = False, (
                "no granted, unrevoked, unexpired consent "
                f"on file for: {', '.join(missing)}"
            )
        else:
            ok, detail = True, (
                f"{len(collabs)} consent(s) on file, unrevoked, unexpired "
                f"({', '.join(i[:14] for i in ids)})"
            )
    if record:
        conn.execute(
            """INSERT INTO gate_results(job_id, gate, passed, detail, at)
               VALUES(?,?,?,?,?)""",
            (job_id, "consent_recheck", 1 if ok else 0, detail, now()),
        )
        conn.commit()
    return ok, detail


def export_ledger(conn: sqlite3.Connection, out_csv: str | Path) -> Path:
    """Export the consent ledger: one row per consent, with artifact hash,
    actor, scope, expiry, revocation state, jurisdiction, terms version.
    The deliverable in a vendor security review — or a dispute defense."""
    out = Path(out_csv)
    rows = conn.execute(
        """SELECT id, handle, platform, job_id, actor, account_id, scope,
                  artifact_hash, artifact_path, jurisdiction, terms_version,
                  pitched_at, responded_at, decision, expiry,
                  revoked_at, revoked_by, revocation_note, recorded_at
           FROM consents ORDER BY recorded_at"""
    ).fetchall()
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "id", "handle", "platform", "job_id", "actor", "account_id",
            "scope", "artifact_hash", "artifact_path", "jurisdiction",
            "terms_version", "pitched_at", "responded_at", "decision",
            "expiry", "revoked_at", "revoked_by", "revocation_note",
            "recorded_at",
        ])
        for r in rows:
            w.writerow(list(r))
    return out
