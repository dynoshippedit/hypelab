"""Publish adapter interface (improved Book 3, section 4).

One interface. Providers behind it. **Never call a provider SDK from
anywhere else in the codebase.**

The collaborator limit is a per-adapter, versioned capability — never a
global constant — and the list is NEVER silently truncated. Over-cap
requests fail closed with a clear error telling the operator exactly
which knob to turn.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import NamedTuple


class ProviderCapabilities(NamedTuple):
    name: str
    version: str                  # adapter version, pinned to docs snapshot
    max_collaborators: int | None  # None = UNKNOWN -> preflight routes to human review
    supports_is_ai_generated: bool
    docs_source: str              # URL the capability was verified against
    account_requirements: str = ""  # e.g. "Professional (Business or Creator)"


class PublishError(Exception):
    """Publish refused (fail closed)."""


class LiveRefused(PublishError):
    """The live path is Dino-gated: no explicit authorization + provider
    credentials on file. This is a refusal, not a missing feature."""


class Publisher(ABC):
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities: ...

    @abstractmethod
    def create_post(self, *, platform: str, media: list[str], caption: str,
                    collaborators: list[str] | None = None,
                    is_ai_generated: bool = False,
                    scheduled_at: str | None = None,
                    dry_run: bool = False) -> str:
        """Create a post. Returns the provider post id (or a deterministic
        fixture id when dry_run=True). dry_run=False without Dino
        authorization + credentials raises LiveRefused."""

    @abstractmethod
    def get_post(self, post_id: str) -> dict: ...

    @abstractmethod
    def get_collaborator_status(self, post_id: str) -> list[dict]:
        """Invite statuses: [{"username": ..., "invite_status": ...}]."""

    @abstractmethod
    def get_metrics(self, post_id: str) -> dict: ...


def check_collaborator_cap(publisher: Publisher,
                           collaborators: list[str]) -> None:
    """Fail closed on unknown or exceeded collaborator caps. The list is
    never silently truncated."""
    if not collaborators:
        return  # no collaborators requested — the cap is irrelevant
    cap = publisher.capabilities().max_collaborators
    name = publisher.capabilities().name
    if cap is None:
        raise PublishError(
            f"collaborator cap UNKNOWN for {name} — route to human review, "
            "do not guess"
        )
    if len(collaborators) > cap:
        raise PublishError(
            f"{len(collaborators)} collaborators requested, adapter {name} "
            f"(v{publisher.capabilities().version}) supports {cap}. "
            "Reduce the list explicitly — it is never truncated silently."
        )
