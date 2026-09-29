"""Native Meta (Instagram Graph API) adapter (improved Book 3, section 4).

Capability record (verified 2026-09-28 against Meta's developer docs):
- up to FIVE collaborator accounts on feed images, Reels, carousels
  (not Stories); invite_status queryable.
- is_ai_generated disclosure field on the media container (set at
  creation, on the container, not the children).
- Professional account (Business OR Creator); the Facebook-Login Graph
  API path requires the IG Professional account linked to a Facebook
  Page; an Instagram Login path (graph.instagram.com) also exists.

The live path is Dino-gated and refuses: no explicit authorization +
provider credentials exist in this build. dry_run=True delegates to the
recorded-fixture backend (same as the dryrun adapter).
"""
from __future__ import annotations

from .base import (
    LiveRefused,
    ProviderCapabilities,
    Publisher,
    check_collaborator_cap,
)
from .dryrun import DryRunPublisher


class NativeMetaPublisher(Publisher):
    def __init__(self, fixtures_path=None):
        self._dry = DryRunPublisher(fixtures_path)

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="meta",
            version="adapter-1.0",
            max_collaborators=5,
            supports_is_ai_generated=True,
            docs_source=(
                "https://developers.facebook.com/documentation/"
                "instagram-platform/instagram-graph-api/reference/"
                "ig-media/collaborators (verified 2026-09-28)"
            ),
            account_requirements=(
                "Professional account (Business or Creator); "
                "Facebook-Login path requires linked Facebook Page"
            ),
        )

    def create_post(self, *, platform: str, media: list[str], caption: str,
                    collaborators: list[str] | None = None,
                    is_ai_generated: bool = False,
                    scheduled_at: str | None = None,
                    dry_run: bool = False) -> str:
        check_collaborator_cap(self, list(collaborators or []))
        if not dry_run:
            raise LiveRefused(
                "native Meta live path is Dino-gated: it needs an explicit "
                "authorization row AND provider credentials (Meta app "
                "review + business verification are also real lead times). "
                "Neither exists in this build — refusing."
            )
        return self._dry.create_post(
            platform=platform, media=media, caption=caption,
            collaborators=collaborators, is_ai_generated=is_ai_generated,
            scheduled_at=scheduled_at, dry_run=True,
        )

    def get_post(self, post_id: str) -> dict:
        return self._dry.get_post(post_id)

    def get_collaborator_status(self, post_id: str) -> list[dict]:
        return self._dry.get_collaborator_status(post_id)

    def get_metrics(self, post_id: str) -> dict:
        return self._dry.get_metrics(post_id)
