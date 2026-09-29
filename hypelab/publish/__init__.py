"""Publish orchestration (improved Book 3, sections 4-5).

The consent ledger and the authorization log sit UNDER the publish path,
not beside it: nothing reaches the publish adapter without passing
through both.

publish_job() order of operations (fail closed at every step):
  1. job exists and is in a publishable state
  2. require_authorization(conn, job_id, "publish") — Dino's approval
  3. instagram_preflight: capability-discovered collaborator cap
     (never silently truncated) + publicity checks against targets
  4. gate_consent re-check at the scheduled -> published boundary
     (consent is revocable; a revoked grant fails here)
  5. adapter.create_post(dry_run=...) — dry_run records against fixtures;
     live refuses (Dino-gated, no credentials)
  6. post_placements ledger row (+ a posts row so Book 2's measurement
     machinery can poll invite-linked posts)

Postiz/Zernio/Ayrshare/native adapters live in publish/meta.py and
publish/providers.py. Provider SDKs are never called from anywhere else.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .. import authorize as authorize_mod
from .. import consent as consent_mod
from .. import jobs as jobs_mod
from ..util import new_id, now, sha256_file
from .base import PublishError, Publisher, check_collaborator_cap
from .dryrun import DryRunPublisher
from .meta import NativeMetaPublisher
from .providers import AyrsharePublisher, PostizPublisher, ZernioPublisher

ADAPTERS: dict[str, type[Publisher]] = {
    "dryrun": DryRunPublisher,
    "meta": NativeMetaPublisher,
    "postiz": PostizPublisher,
    "zernio": ZernioPublisher,
    "ayrshare": AyrsharePublisher,
}

#: job states from which a publish may be attempted.
PUBLISHABLE_STATES = ("ready", "consent_granted", "scheduled", "dry_run")


def get_adapter(name: str, fixtures_path=None) -> Publisher:
    try:
        cls = ADAPTERS[name]
    except KeyError:
        raise PublishError(
            f"unknown publish adapter {name!r}; known: {sorted(ADAPTERS)}"
        )
    return cls(fixtures_path)


def asset_fingerprint(media: list[str | Path]) -> str:
    """Deterministic fingerprint of the published media set: sha256 over
    the sorted files' bytes. The consent gate binds to this hash."""
    import hashlib

    h = hashlib.sha256()
    for m in sorted(str(p) for p in media):
        p = Path(m)
        if not p.is_file():
            raise PublishError(f"publish media not found: {m}")
        h.update(p.name.encode())
        h.update(sha256_file(p).encode())
    return h.hexdigest()


def _targets_get(conn: sqlite3.Connection, handle: str,
                 platform: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM targets WHERE handle=? AND platform=?",
        (handle, platform),
    ).fetchone()
    return dict(row) if row else None


def record_collab_caps(conn: sqlite3.Connection,
                       publisher: "Publisher") -> None:
    """Persist the adapter's versioned collaborator capability record.

    Called at publish preflight so the cap that governed the decision is
    in the ledger, not just in code. max_collaborators=None means the
    adapter's cap is UNKNOWN (preflight routes to human review)."""
    caps = publisher.capabilities()
    conn.execute(
        """INSERT INTO collab_caps(adapter_name, adapter_version,
                                  max_collaborators, source, recorded_at)
           VALUES(?,?,?,?,?)
           ON CONFLICT(adapter_name, adapter_version) DO UPDATE SET
             max_collaborators=excluded.max_collaborators,
             source=excluded.source,
             recorded_at=excluded.recorded_at""",
        (caps.name, caps.version, caps.max_collaborators,
         "adapter", now()),
    )


def instagram_preflight(conn: sqlite3.Connection,
                        collaborators: list[str],
                        publisher: Publisher,
                        platform: str = "instagram") -> dict:
    """Corrected preflight (book §4): the cap comes from the adapter's
    capability, never a global constant; publicity is a cached
    observation with a timestamp, never a universal law."""
    check_collaborator_cap(publisher, collaborators)
    for h in collaborators:
        t = _targets_get(conn, h, platform)
        if not t:
            raise PublishError(
                f"{h}: no target record — refresh before publishing"
            )
        if t["is_public"] is False or t["is_public"] == 0:
            raise PublishError(
                f"{h}: recorded as private/restricted "
                f"(checked {t['is_public_checked_at']}) — route to human review"
            )
        if t["is_public"] is None:
            raise PublishError(
                f"{h}: publicity check never performed — run a target "
                "refresh and route to human review"
            )
    return {
        "collaborators": list(collaborators),
        "is_ai_generated": True,
        "adapter": publisher.capabilities().name,
        "adapter_version": publisher.capabilities().version,
    }


def publish_job(conn: sqlite3.Connection, job_id: str, *,
                platform: str = "instagram",
                collaborators: list[str] | None = None,
                caption: str = "",
                media: list[str | Path] | None = None,
                adapter_name: str = "dryrun",
                dry_run: bool = True,
                scheduled_at: str | None = None,
                fixtures_path=None) -> dict:
    """Publish a job's asset through the adapter (dry_run by default).

    Returns a dict describing the placement. Raises PublishError /
    AuthorizationError / ConsentError / LiveRefused on any failure.
    """
    collaborators = list(collaborators or [])
    media = [str(m) for m in (media or [])]

    job = jobs_mod.get(conn, job_id)
    if job is None:
        raise PublishError(f"unknown job {job_id}")
    state = job["state"]
    if state not in PUBLISHABLE_STATES:
        raise PublishError(
            f"job is in '{state}' — publishable states: {PUBLISHABLE_STATES}"
        )
    if not media:
        raise PublishError("no media to publish")

    # 2. Dino's authorization (the system never acts on its own initiative).
    auth = authorize_mod.require_authorization(conn, job_id, "publish")

    # 3. Preflight: adapter capability + publicity.
    publisher = get_adapter(adapter_name, fixtures_path)
    record_collab_caps(conn, publisher)
    preflight = instagram_preflight(conn, collaborators, publisher, platform)

    # 4. Consent re-check at the publish boundary (fail closed). The
    #    verdict is recorded in gate_results as "consent_recheck".
    #    The gate keys on (job, handle, platform) — the relationship — not
    #    on media bytes (see consent.valid_for). The media fingerprint is
    #    recorded on the placement row below as provenance of WHAT was
    #    published, but it is not a gate condition.
    fingerprint = asset_fingerprint(media)
    ok, detail = consent_mod.gate_consent(
        conn, job_id, collaborators, platform=platform, record=True
    )
    if not ok:
        raise consent_mod.ConsentError(f"consent gate refused publish: {detail}")
    consent_ids = [
        c["id"]
        for c in (
            consent_mod.valid_for(conn, job_id, h, platform)
            for h in collaborators
        )
        if c
    ]

    # 5. Adapter call. dry_run records against fixtures; live refuses.
    request = {
        "platform": platform,
        "media": media,
        "caption": caption,
        "collaborators": collaborators,
        "is_ai_generated": True,
        "scheduled_at": scheduled_at,
        "dry_run": dry_run,
        "adapter": publisher.capabilities().name,
        "preflight": preflight,
        "authorization_id": auth["id"],
    }
    post_id = publisher.create_post(
        platform=platform, media=media, caption=caption,
        collaborators=collaborators, is_ai_generated=True,
        scheduled_at=scheduled_at, dry_run=dry_run,
    )
    response = publisher.get_post(post_id)

    # 6. Placement ledger (always) + posts row (feeds Book 2 measurement).
    pid = new_id("place")
    ts = now()
    conn.execute(
        """INSERT INTO post_placements(id, job_id, post_id, platform, adapter,
              dry_run, collaborators_json, caption, media_json, asset_sha256,
              is_ai_generated, consent_ids_json, request_json, response_json,
              created_at)
           VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (pid, job_id, post_id if not dry_run else None, platform,
         publisher.capabilities().name, 1 if dry_run else 0,
         json.dumps(collaborators), caption, json.dumps(media), fingerprint,
         1, json.dumps(consent_ids), json.dumps(request),
         json.dumps(response), ts),
    )
    # posts row so poll_metrics-style machinery can measure invite-linked
    # posts; dry_run posts get a dryrun:// URL (never a real one).
    post_row_id = new_id("post")
    conn.execute(
        """INSERT INTO posts(id, clip_id, job_id, platform, account, post_url,
                             posted_at, post_id)
           VALUES(?,?,?,?,?,?,?,?)""",
        (post_row_id, None, job_id, platform, None,
         f"dryrun://{pid}" if dry_run else (response.get("url") or ""),
         ts, post_id),
    )
    if not dry_run:
        # Unreachable in this build (live refuses above), kept for the
        # Dino-gated future: the state move happens only on a real publish.
        jobs_mod.transition(conn, job_id, "published",
                            f"published via {publisher.capabilities().name}")
    conn.commit()
    return {
        "placement_id": pid,
        "post_row_id": post_row_id,
        "provider_post_id": post_id,
        "dry_run": dry_run,
        "adapter": publisher.capabilities().name,
        "collaborators": collaborators,
        "consent_ids": consent_ids,
        "consent_detail": detail,
        "asset_sha256": fingerprint,
    }


__all__ = [
    "ADAPTERS", "PUBLISHABLE_STATES", "get_adapter", "asset_fingerprint",
    "instagram_preflight", "publish_job",
]