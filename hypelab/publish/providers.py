"""Postiz + Zernio + Ayrshare adapter capability records (Book 3, §4).

Snapshots verified 2026-09-28; re-verify before buying or wiring anything.
Every adapter's live path refuses (Dino-gated); dry_run delegates to the
recorded-fixture backend.

- Postiz: max_collaborators=3 per Postiz API docs.
- Zernio (ex-Late): max_collaborators=3 per Zernio's current API docs.
- Ayrshare: cap NOT verified at snapshot — declares UNKNOWN (None), so
  the preflight routes to human review rather than guessing.
"""
from __future__ import annotations

from .base import (
    LiveRefused,
    ProviderCapabilities,
    Publisher,
    check_collaborator_cap,
)
from .dryrun import DryRunPublisher


class _FixtureDelegatingPublisher(Publisher):
    """Shared skeleton: capability record + refusing live path."""

    #: override in subclasses
    _CAPS: ProviderCapabilities | None = None
    _LIVE_NOTE = ""

    def __init__(self, fixtures_path=None):
        self._dry = DryRunPublisher(fixtures_path)

    def capabilities(self) -> ProviderCapabilities:
        assert self._CAPS is not None
        return self._CAPS

    def _refuse_live(self) -> None:
        raise LiveRefused(
            f"{self.capabilities().name} live path is Dino-gated: "
            f"{self._LIVE_NOTE}Neither exists in this build — refusing."
        )

    def create_post(self, *, platform: str, media: list[str], caption: str,
                    collaborators: list[str] | None = None,
                    is_ai_generated: bool = False,
                    scheduled_at: str | None = None,
                    dry_run: bool = False) -> str:
        check_collaborator_cap(self, list(collaborators or []))
        if not dry_run:
            self._refuse_live()
        if platform == "instagram" and self.capabilities().supports_is_ai_generated \
                and not is_ai_generated:
            from .base import PublishError
            raise PublishError(
                "instagram dry_run requires is_ai_generated=True on the container"
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


class PostizPublisher(_FixtureDelegatingPublisher):
    _CAPS = ProviderCapabilities(
        name="postiz",
        version="adapter-1.0",
        max_collaborators=3,  # per Postiz API docs, verified 2026-09-28
        supports_is_ai_generated=True,
        docs_source="https://docs.postiz.com (pin the actual page at build time)",
        account_requirements="per Postiz plan; provider may narrow account types",
    )
    _LIVE_NOTE = ("it needs an explicit authorization row AND Postiz "
                  "credentials with the API add-on. ")


class ZernioPublisher(_FixtureDelegatingPublisher):
    _CAPS = ProviderCapabilities(
        name="zernio",
        version="adapter-1.0",
        max_collaborators=3,  # per Zernio's current API docs, verified 2026-09-28
        supports_is_ai_generated=False,  # not verified — assumed absent
        docs_source="https://zernio.com/blog/unified-social-media-api "
                    "(verified 2026-09-28)",
        account_requirements="per Zernio plan",
    )
    _LIVE_NOTE = ("it needs an explicit authorization row AND Zernio "
                  "credentials. ")


class AyrsharePublisher(_FixtureDelegatingPublisher):
    _CAPS = ProviderCapabilities(
        name="ayrshare",
        version="adapter-1.0",
        max_collaborators=None,  # UNKNOWN at snapshot — preflight routes to review
        supports_is_ai_generated=False,  # not verified — assumed absent
        docs_source="https://www.ayrshare.com/pricing/ "
                    "(cap not verified at snapshot — UNKNOWN)",
        account_requirements="per Ayrshare profile tier",
    )
    _LIVE_NOTE = ("it needs an explicit authorization row AND Ayrshare "
                  "credentials. ")
