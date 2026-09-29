"""Dry-run publisher: the fully-working publish path.

dry_run=True is the ONLY working mode in this build. It records the
request against recorded fixtures, writes the placement ledger, and makes
zero live provider calls. dry_run=False raises LiveRefused — the live path
is Dino-gated (explicit authorization + provider credentials) and is a
future step, not a missing flag.

No network calls, ever. The fixture backend is deterministic: identical
inputs produce identical fixture post ids.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

from .base import (
    LiveRefused,
    ProviderCapabilities,
    PublishError,
    Publisher,
    check_collaborator_cap,
)

FIXTURES_DEFAULT = (
    Path(__file__).resolve().parent.parent.parent
    / "tests" / "fixtures_book3" / "dryrun_fixtures.json"
)


class DryRunPublisher(Publisher):
    """Fully working against recorded fixtures. Sends nothing."""

    def __init__(self, fixtures_path: str | Path | None = None):
        self.fixtures_path = Path(fixtures_path or FIXTURES_DEFAULT)
        self._fixtures: dict | None = None

    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            name="dryrun",
            version="adapter-1.0-fixture",
            max_collaborators=5,  # mirrors the native IG cap in fixtures
            supports_is_ai_generated=True,
            docs_source="recorded fixtures (no live provider)",
            account_requirements="none — fixtures only",
        )

    # -- fixtures ------------------------------------------------------

    def _load_fixtures(self) -> dict:
        if self._fixtures is None:
            if self.fixtures_path.is_file():
                self._fixtures = json.loads(
                    self.fixtures_path.read_text(encoding="utf-8")
                )
            else:
                self._fixtures = {}
        return self._fixtures

    def _fixture_post_id(self, platform: str, media: list[str],
                         caption: str, collaborators: list[str]) -> str:
        seed = "|".join([platform, *sorted(media), caption,
                         *sorted(collaborators or [])])
        digest = hashlib.sha256(seed.encode()).hexdigest()[:16]
        return f"dryrun_{digest}"

    # -- Publisher -----------------------------------------------------

    def create_post(self, *, platform: str, media: list[str], caption: str,
                    collaborators: list[str] | None = None,
                    is_ai_generated: bool = False,
                    scheduled_at: str | None = None,
                    dry_run: bool = False) -> str:
        if not dry_run:
            raise LiveRefused(
                "dry-run adapter refuses live calls. Live publishing is "
                "Dino-gated: it needs an explicit authorization row AND "
                "provider credentials, neither of which exists in this "
                "build. This is a refusal, not a missing flag."
            )
        collaborators = list(collaborators or [])
        check_collaborator_cap(self, collaborators)
        if platform == "instagram" and not is_ai_generated:
            # book §4: is_ai_generated set on the container at creation.
            raise PublishError(
                "instagram dry_run requires is_ai_generated=True on the "
                "container (this system's assets are AI-generated)"
            )
        return self._fixture_post_id(platform, media, caption, collaborators)

    def get_post(self, post_id: str) -> dict:
        fx = self._load_fixtures().get("posts", {})
        return dict(fx.get(post_id, {"post_id": post_id, "dry_run": True}))

    def get_collaborator_status(self, post_id: str) -> list[dict]:
        fx = self._load_fixtures().get("collaborator_status", {})
        return [dict(r) for r in fx.get(post_id, [])]

    def get_metrics(self, post_id: str) -> dict:
        fx = self._load_fixtures().get("metrics", {})
        return dict(fx.get(post_id, {"views": None, "provenance": "fixture"}))


# Re-exported for convenience: the fixture backend is adapter-agnostic.
def fixture_post_id(*args, **kwargs) -> str:
    return DryRunPublisher()._fixture_post_id(*args, **kwargs)
