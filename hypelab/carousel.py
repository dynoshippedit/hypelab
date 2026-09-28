"""Mode C carousel renderer: slides.json -> HTML -> PNG. STUB (milestone M7).

Contract is fixed (see ARCHITECTURE.md §3.3 slides.json); the Chromium-based
renderer lands in M7. This module fails loudly rather than faking output.
"""
from __future__ import annotations

def render_carousel(slides: dict, kit: dict, out_dir) -> list[str]:
    raise NotImplementedError(
        "carousel renderer is milestone M7 — not yet implemented. "
        "Contract: slides.json (7 slides) -> headless Chromium screenshots.")
