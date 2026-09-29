# QUESTIONS for the owner
(To answer: write under "Answer (owner)" and set Status to ANSWERED.)

(none yet — DOC will add the P4 "what this app is" confirmation question in Phase 1.)

---

## Q-001 — DOC (2026-09-29): confirm the P4 what this app is paragraph

**Status:** OPEN

**Context:** The B9.10 claims audit found the docs describe the 2026-09-28 slice-era
implementation, not the current Books 1–3 code. The paragraph below (also at the top of
devteam/notes/claims-audit.md) is my one-paragraph statement of what the app IS today,
verified against the code. It will anchor the Phase 5 docs rewrite.

**Proposed paragraph:**

> HypeLab is a Python CLI pipeline for AI-assisted short-form video production. An
> operator seeds an immutable brand kit, creates a job from a script, attaches
> voiceover/music/clips, and a deterministic ffmpeg renderer — driven by a validated
> edit decision list (EDL) built from faster-whisper word alignment — produces captioned,
> platform-formatted MP4s that must pass quality gates (duration, loudness, first frame,
> hook budget, caption safety, slots, geometry, word confidence) before the job is marked
> ready. A job-level queue with 30-minute leases, atomic claims, heartbeats and crash
> recovery executes pipeline stages (align/render/gates, plus Book 2 clip-mine
> ingest/score); a consent ledger plus an explicit operator authorization row hard-gate
> publishing, and every publish adapter's live path currently refuses — only
> fixture-backed dry-runs work, with zero live network calls. Book 2 adds a clip mine
> (campaign → source → moments → scored cuts → compliance tray) and Book 3 adds a hype
> layer (carousel renderer, pitch/outreach, consent-gated dry-run publish, metrics
> polling that honestly records unavailable, and n≥30-gated attribution). Nothing is
> published for real; no paid APIs and no credentials are used.

**Options:** (a) accept as written; (b) correct specific sentences (reply with edits);
(c) reject and supply your own paragraph.

**Recommendation:** accept as written.

**Default assumption meanwhile:** the paragraph stands and will be used as the basis for
the Phase 5 docs rewrite (README/ARCHITECTURE corrections per DOC-001..DOC-024).

**Answer (owner):**
