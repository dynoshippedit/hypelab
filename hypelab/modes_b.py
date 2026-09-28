"""Mode B (Clip Mine): ingest, moment scoring, reframe, compliance, tray.
STUB (milestone M8). The vertical slice is Mode A; this module reserves the
names and the data contracts (campaigns, moments, tray package layout)."""
from __future__ import annotations

def ingest_source(url: str, campaign_id: str) -> dict:
    raise NotImplementedError("Mode B ingest is milestone M8.")

def score_moments(job_id: str) -> list[dict]:
    raise NotImplementedError("Moment scoring is milestone M8.")

def build_tray(job_id: str) -> dict:
    raise NotImplementedError("Clip tray is milestone M8.")
