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

---

## ENV (2026-09-29) — config-model questions for Dino

Findings: `devteam/findings/env.md` (ENV-650–657). Notes: `devteam/notes/environment.md`.

**Q-ENV-1 (ENV-651): Should `HYPELAB_ROOT` become the single root?**
Today `HYPELAB_ROOT` moves only `work/<job_id>/`; the DB stays at the hardcoded
`/home/dino/hypelab/hypelab.db` (`db.py:26`) and the wav2vec2 model cache stays
at the hardcoded `/home/dino/hypelab/models/` (`align.py:28`). **Options:** (a)
derive DB path and model cache from `HYPELAB_ROOT` (with `HYPELAB_DB` as explicit
override) — true single-root relocation; (b) keep the split and document it as
required behavior. **Recommendation:** (a) — a root variable that doesn't move
the state is a trap. **Default assumption meanwhile:** (b) — no behavior change
made; split documented in `devteam/notes/environment.md`.

**Q-ENV-2 (ENV-653): How should the ASR model be bootstrapped?**
`transcribe()` downloads the faster-whisper `"medium"` model on first use from a
second, undocumented HF cache (`~/.cache/huggingface`); no `fetch` step, no
offline flag honored, raw traceback when offline. **Options:** (a) add a `fetch`
CLI step for the ASR model mirroring `fetch_model()` for wav2vec2; (b) honor
`HF_HUB_OFFLINE` with a clean "model not cached" error; (c) leave as-is and
document both caches + sizes. **Recommendation:** (a)+(b) — pre-flight beats
tracebacks. **Default assumption meanwhile:** (c) — document only; nothing changed.

**Q-ENV-3 (ENV-650): Minimum-version policy for native tools?**
No version floors exist for ffmpeg/ffprobe, Chromium, tesseract, yt-dlp (or any
Python package — BLD-001). **Options:** (a) declare minimums (ffmpeg ≥ 6?,
Chromium ≥ 120?, tesseract ≥ 5?) in docs + a startup check; (b) document only
what's installed/known-good (ffmpeg 8.1.2, Chrome 153, tesseract absent). **Recommendation:**
(b) now, (a) when the manifest lands. **Default assumption meanwhile:** (b).

**Q-ENV-4 (ENV-655): Should the pipeline auto-detect CUDA?**
Default compute is `"medium"` model on forced `"cpu"` (`align.py:84-89`) — a GPU
machine silently runs CPU. **Options:** (a) probe `torch.cuda.is_available()` at
transcribe time and use GPU when present; (b) keep forced CPU, log the resolved
config and document the estimate. **Recommendation:** (b) now — (a) changes
render determinism/cost profile; your call. **Default assumption meanwhile:** (b).

**Answers (owner):**

## Q-002 — UIX (2026-09-29): failed-job recovery policy — CLI retry command vs auto-requeue

**Status:** OPEN

**Context:** BUG-007 / UIX-552. queue.fail()'s docstring promises a re-queue
the work loop never performs; failed jobs are SQL-only today. work prints
a poison list (cli.py:820-830) with no remediation, and failed -> draft
(jobs.py:44) has no CLI path. The operator's only recovery is raw SQL.

**Options:** (a) add hypelab retry <job> (operator-driven failed -> draft
or re-queue, attempts preserved); (b) auto-requeue below MAX_ATTEMPTS in the
work loop and correct the docstring; (c) both (auto-requeue for transient,
manual retry as backstop).

**Recommendation:** (a) — operator-driven retry keeps the human in the loop
for a pipeline where failures can be expensive (renders) and matches the
deliberate-operator pattern used elsewhere (bump-rules, resolve).

**Default assumption meanwhile:** (a); Phase 5 adds the retry command and a
poison-list remediation hint.

**Answer (owner):**

## Q-003 — UIX (2026-09-29): consent check negative answer — exit code and message

**Status:** OPEN

**Context:** UIX-557. hypelab consent check with no valid consent exits 1
via _die ("error: NO valid consent..."), indistinguishable from a DB failure.
A negative answer is a valid query result, not a command failure.

**Options:** (a) keep exit 1 but drop the error: prefix (grep-like
convention: 1 = "not found"); (b) exit 0 with NO on stdout and reserve
exit 1 for real failures.

**Recommendation:** (a) — minimal change, scripts can already branch on it,
and the message stops crying wolf.

**Default assumption meanwhile:** (a).

**Answer (owner):**

## Q-004 — UIX (2026-09-29): canonical env var — HYPELAB_ROOT (code) vs HYPELAB_HOME (README)

**Status:** OPEN

**Context:** UIX-568 / DOC-005. README.md:16 documents HYPELAB_HOME; code
reads HYPELAB_ROOT/HYPELAB_DB (cli.py:87) and ignores HYPELAB_HOME
silently. This matches the ARC lane's open drift question.

**Options:** (a) canonicalize on HYPELAB_ROOT (code wins), fix README in
Phase 5; (b) support both, HYPELAB_HOME as deprecated alias.

**Recommendation:** (a) — one name, no alias debt; the README is already
slated for rewrite (DOC-001–004).

**Default assumption meanwhile:** (a); operators should export
HYPELAB_ROOT/HYPELAB_DB today.

**Answer (owner):**
