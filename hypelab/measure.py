"""Measurement + what_worked aggregation. STUB (milestone M9).

Records the contract: metrics are polled per post at 24h/7d/30d windows,
aggregated per creative dimension only when n >= 30 per cell, otherwise the
CLI reports 'insufficient evidence' and never auto-changes creative defaults.
"""
from __future__ import annotations

MIN_EVIDENCE_N = 30

def poll_all() -> dict:
    raise NotImplementedError("Measurement polling is milestone M9.")

def what_worked(dimension: str | None = None) -> dict:
    return {"insufficient_evidence": True,
            "note": f"need n>={MIN_EVIDENCE_N} measured posts per cell; none yet"}
