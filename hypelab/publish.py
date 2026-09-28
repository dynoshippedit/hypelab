"""Provider-neutral publishing. Dry-run is the default and is explicit.

Real publishing requires ALL THREE: a valid consent artifact, dry_run=False,
and an explicit --i-confirm flag. Provider integrations (Postiz/Zernio/native)
are stubs until credentials exist AND their current API docs are re-verified.
"""
from __future__ import annotations
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Protocol

from .db import connect, migrate
from .consent import require_consent

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

@dataclass
class PublishPlan:
    job_id: str
    target_handle: str
    platform: str
    collaborators: list[str] = field(default_factory=list)
    is_ai_generated: bool = True
    caption: str = ""
    asset_path: str = ""
    dry_run: bool = True

    def validate(self) -> list[str]:
        e = []
        if len(self.collaborators) > 3:
            e.append("Instagram allows max 3 collaborators")
        if self.platform == "instagram" and not self.is_ai_generated:
            e.append("isAIGenerated must be set on Instagram publishes")
        if not self.asset_path:
            e.append("no asset to publish")
        return e

@dataclass
class PublishResult:
    ok: bool
    dry_run: bool
    detail: str
    media_id: str | None = None

class PublishAdapter(Protocol):
    name: str
    def capabilities(self) -> dict: ...
    def publish(self, plan: PublishPlan, dry_run: bool) -> PublishResult: ...
    def invite_status(self, media_id: str) -> str: ...

class DryRunAdapter:
    """Always available. Validates the plan, sends nothing, says so loudly."""
    name = "dryrun"
    def capabilities(self) -> dict:
        return {"publish": False, "collaborators": True, "is_ai_generated": True,
                "platforms": ["instagram", "tiktok", "youtube_shorts"]}
    def publish(self, plan: PublishPlan, dry_run: bool) -> PublishResult:
        errs = plan.validate()
        if errs:
            return PublishResult(ok=False, dry_run=True, detail="; ".join(errs))
        return PublishResult(
            ok=True, dry_run=True,
            detail=(f"DRY RUN — nothing was sent. Would publish {plan.asset_path} "
                    f"to {plan.platform} as @{plan.target_handle} "
                    f"collaborators={plan.collaborators} "
                    f"isAIGenerated={plan.is_ai_generated}"))
    def invite_status(self, media_id: str) -> str:
        return "unknown:dryrun"

class PostizAdapter:
    """Stub. Raises until configured AND re-verified against current Postiz docs."""
    name = "postiz"
    def capabilities(self) -> dict:
        return {"publish": False, "note": "not configured"}
    def publish(self, plan: PublishPlan, dry_run: bool) -> PublishResult:
        raise NotConfigured("Postiz adapter is not configured (no credentials, "
                            "API docs not re-verified).")
    def invite_status(self, media_id: str) -> str:
        raise NotConfigured("Postiz adapter is not configured.")

class NotConfigured(Exception):
    pass

ADAPTERS: dict[str, type] = {"dryrun": DryRunAdapter, "postiz": PostizAdapter}

def publish_job(job_id: str, handle: str, platform: str = "instagram",
                collaborators: list[str] | None = None,
                dry_run: bool = True, i_confirm: bool = False,
                adapter_name: str = "dryrun", path=None) -> PublishResult:
    cx = connect(path); migrate(cx)
    job = cx.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job:
        raise ValueError(f"job {job_id} not found")
    job = dict(job)
    if job["state"] not in ("asset_ready", "pitch_sent", "awaiting_consent",
                            "consent_granted", "scheduled"):
        raise ValueError(f"job is in '{job['state']}' — nothing publishable")

    edl_row = cx.execute("SELECT render_hash FROM edls WHERE job_id=?", (job_id,)).fetchone()
    asset_version = edl_row["render_hash"] if edl_row else "none"

    # HARD GATE: consent checked before anything else, dry-run or not.
    consent = require_consent(job_id, handle, platform, asset_version, path)

    if not dry_run and not i_confirm:
        raise ValueError("real publishing requires --i-confirm (and is still blocked: "
                         "no provider credentials configured)")

    from . import config as cfg
    asset_path = str(cfg.job_dir(job_id) / "master.mp4")
    plan = PublishPlan(job_id=job_id, target_handle=handle, platform=platform,
                       collaborators=collaborators or [], is_ai_generated=True,
                       asset_path=asset_path, dry_run=dry_run)
    adapter = ADAPTERS[adapter_name]()
    result = adapter.publish(plan, dry_run=dry_run)

    pid = "post_" + uuid.uuid4().hex[:12]
    cx.execute(
        """INSERT INTO posts(id, job_id, clip_id, platform, post_url, posted_at,
                             collaborator, dry_run)
           VALUES(?,?,?,?,?,?,?,?)""",
        (pid, job_id, None, platform,
         result.media_id if not dry_run else None, _now(), handle,
         1 if dry_run else 0))
    if not dry_run:
        cx.execute("UPDATE jobs SET state='published' WHERE id=?", (job_id,))
    return result
