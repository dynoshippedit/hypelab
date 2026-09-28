"""Consent ledger + the hard gate. No consent artifact -> no publish, ever."""
from __future__ import annotations
import json
import uuid
from datetime import datetime, timezone

from .db import connect, migrate

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class ConsentRequired(Exception):
    pass

class Consents:
    def __init__(self, path=None):
        self.cx = connect(path)
        migrate(self.cx)

    def record(self, job_id: str, handle: str, platform: str, scope: str,
               asset_version: str, evidence: str, expiry: str) -> dict:
        """Recording consent requires the actual artifact (message id /
        screenshot path / export). The CLI never auto-grants."""
        cid = "consent_" + uuid.uuid4().hex[:12]
        now = _now()
        self.cx.execute(
            """INSERT INTO consents(id, target_handle, target_platform, job_id,
               pitched_at, responded_at, scope, asset_version, evidence, expiry,
               revoked_at) VALUES(?,?,?,?,?,?,?,?,?,?,NULL)""",
            (cid, handle, platform, job_id, now, now, scope, asset_version,
             evidence, expiry))
        self.cx.execute(
            "UPDATE targets SET consent_state='granted' WHERE handle=? AND platform=?",
            (handle, platform))
        return dict(self.cx.execute("SELECT * FROM consents WHERE id=?", (cid,)).fetchone())

    def revoke(self, consent_id: str) -> None:
        self.cx.execute("UPDATE consents SET revoked_at=? WHERE id=?", (_now(), consent_id))

    def valid_for(self, job_id: str, handle: str, platform: str,
                  asset_version: str) -> dict | None:
        """A consent is valid iff: matches job+target+asset version, not expired,
        not revoked. Asset version binding means re-rendering voids consent."""
        row = self.cx.execute(
            """SELECT * FROM consents
               WHERE job_id=? AND target_handle=? AND target_platform=?
                 AND asset_version=? AND revoked_at IS NULL AND expiry > ?
               ORDER BY responded_at DESC LIMIT 1""",
            (job_id, handle, platform, asset_version, _now())).fetchone()
        return dict(row) if row else None

def require_consent(job_id: str, handle: str, platform: str,
                    asset_version: str, path=None) -> dict:
    c = Consents(path).valid_for(job_id, handle, platform, asset_version)
    if not c:
        raise ConsentRequired(
            f"publishing refused: no valid consent for @{handle} on {platform} "
            f"covering asset {asset_version[:12]}… (job {job_id}). "
            f"Record consent with 'hypelab consent grant' first.")
    return c
