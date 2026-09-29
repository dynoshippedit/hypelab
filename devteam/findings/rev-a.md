# REV-A — SWEEP-A fresh-eyes findings

Sweep: SWEEP-A (Phase 3). Branch: `devteam/review-2026-09-29` (HEAD d778635).
Modules reviewed: align, attribution, authorize, b2cli, book3cli, boundary,
campaigns, captions, carousel, cli, compliance, consent, cut, db, edl,
feedback, gates, ingest, __init__, invites, jobs, kits, manifests, metrics.
All findings below are **new** — the 114 pre-existing findings (MAP/TST/BLD/
DOC/STR/DAT/ARC/BUG/SEC lanes) were checked first and are NOT re-filed;
confirmations live in `devteam/notes/sweep-a.md`.

## REV-700 — `campaign list` crashes with KeyError 'status' on every non-empty listing
- **Severity:** S2
- **Status:** Confirmed
- **Module(s):** b2cli.py, campaigns.py
- **Evidence:** b2cli.py:111 (`c['status']`); campaigns table DDL migrations/0001_book1_foundation.sql:108-121 (column is `state`, no `status`); campaigns.py:64-77 (`_parse` adds no `status` key).
- **Finding:** `campaign_list` prints `c['status']` for every campaign, but the
  schema has `state` and no later migration adds `status` (only `rate_basis`,
  `budget_provenance`, `rules_provenance`). Any invocation with ≥1 campaign
  raises `KeyError: 'status'`. ARC-301 covers `bump-rules`/`refresh-budget`
  only — this is a separate, equally-broken command on the same screen.

## REV-701 — `campaign show` catches the wrong exception type
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** b2cli.py, campaigns.py
- **Evidence:** b2cli.py:114-121 (catches `KeyError`); campaigns.py:126 (`load` raises `CampaignError`).
- **Finding:** `campaign show <unknown-id>` raises `CampaignError`, which the
  handler does not catch — the user gets a traceback instead of the clean
  `_die` error path every other command in the file uses.

## REV-702 — Documented preference-3 clearance path is unreachable: `ingest` rejects the basis `record_clearance` preserves
- **Severity:** S2
- **Status:** Confirmed
- **Module(s):** ingest.py, watcher.py
- **Evidence:** ingest.py:196-203 (dispatch requires `basis in CLEAR_BASES`); ingest.py:206-207 (manual path) and 233-236 (needs_clearance with URL → IngestError); watcher.py `record_clearance` (deliberately keeps `basis='needs_clearance'`); ingest.py:38 docstring (preference 3 = yt-dlp on third-party uploads *with clearance*).
- **Finding:** The clearance flow is a write-only ledger. After the operator
  records clearance, the source basis remains `needs_clearance`, and `ingest`
  has no download path for that basis with an http URL — the elif raises
  `IngestError("no ingest path for ...")`. The module's own documented
  preference-3 path (clearance obtained, then download) can never execute.

## REV-703 — Submission re-gate synthesizes placeholder clip content instead of using the clip row's stored fields
- **Severity:** S2
- **Status:** Confirmed
- **Module(s):** compliance.py, cut.py
- **Evidence:** compliance.py:281-296 (`regated_if_stale` builds clip with `caption=""`, `burned_text=""`, `overlays_text=[]`, `source_url=""`, `audio_provenance="campaign_supplied"`, `mixed_music=False`, `watermark_verified=False`); cut.py:273-279 (record_posted uses stored clip row for the FIRST check but calls regated_if_stale for the second).
- **Finding:** When campaign rules changed between gating and posting, the
  re-gate checks a fabricated clip instead of the stored row (which HAS
  caption, source_url, etc.). Empty caption false-FAILS handle/hashtag/credit
  and source-allowlist checks; empty burned_text false-PASSES banned-words;
  watermark is forced UNKNOWN. The Book 2 §9 "gate runs again at submission"
  guarantee is systematically wrong in both directions — it will block
  compliant clips (dominant mode) and can wave through non-compliant ones.

## REV-704 — Failed submission re-gate requests an illegal `tray → compliance_unknown` job transition
- **Severity:** S3
- **Status:** Confirmed
- **Module(s):** cut.py, jobs.py
- **Evidence:** cut.py:277-280 (`jobs_mod.transition(conn, clip['job_id'], res['state'])` where `res['state']` can be `'compliance_unknown'`); jobs.py BOOK2_STATES (`tray` → only `posted|archived|failed`); migrations/state_3_0.py (adds no tray edges).
- **Finding:** When `regated_if_stale` returns unknowns, the job sits in `tray`
  (the legal states from `compliance_unknown` do not include `tray` either —
  `route_job` can only produce `compliance_unknown` from `queued_compliance`
  or `compliance_failed`). `transition` raises ValueError: the clip row was
  already moved to `compliance_unknown`, the job is stranded in `tray`, and
  the CLI dies via `_die`. The unknowns-at-submission path the book describes
  has no legal job transition — the operator must resolve this by hand.

## REV-705 — Tokenizer mismatch between forced alignment and beat retiming corrupts beat boundaries on hyphens/dashes
- **Severity:** S2
- **Status:** Confirmed
- **Module(s):** align.py
- **Evidence:** align.py:41 (`_WORD_RE = [A-Za-z0-9']+` used by `_script_tokens`); align.py:478 (`retime_beats` counts with `str.split()`); align.py:414 (`low_confidence_beats`, same split).
- **Finding:** Forced alignment produces one word per `_WORD_RE` token, but the
  greedy beat↔word mapping counts `line.split()`. On hyphens, em/en-dashes,
  underscores, and curly apostrophes they disagree ("well-known" = 1 split-word
  vs 2 tokens; `normalize_numbers` does not strip hyphens, so this is reachable
  with ordinary scripts). Every beat after the first such word silently gets
  the wrong t_in/t_out; trailing words are silently dropped (split-count <
  token-count) or the run dies with AlignError (split-count > token-count).
  Both `retime_beats` (render segmentation) and `low_confidence_beats`
  (gate mapping) are affected. Silent corruption of shipped video segments.

## REV-706 — Authorization rows never expire and cannot be revoked
- **Severity:** S3
- **Status:** Confirmed
- **Module(s):** authorize.py
- **Evidence:** authorize.py:55-70 (`require_authorization` = latest row for (job_id, action); no expiry check, no revoked state); book3cli.py:28-56 (no revoke command); contrast consent.py:156-208 (`revoke` exists for creator consent).
- **Finding:** A single `hypelab authorize` row authorizes that action on that
  job forever. There is no expiry, no revocation path (no CLI command, no API),
  and `require_authorization` does not compare the stored intent text. Dino's
  own approval grant is irrevocable while the creator's consent grant is
  revocable — the module's "hard rule: no external side effect without
  authorization" is weaker than the consent ledger it parallels.

## REV-707 — Carousel hook slide hardcodes the kicker "New Light Management"
- **Severity:** S3
- **Status:** Confirmed
- **Module(s):** carousel.py
- **Evidence:** carousel.py:126 (`kicker` hardcoded "New Light Management" in `_slide_html`); carousel.py:62-76 (`validate_spec` has no kicker field; no kit field exists for it).
- **Finding:** The module docstring promises "a dumb spec, a deterministic
  renderer", but the hook slide — the first thing a viewer sees — carries a
  hardcoded kicker unrelated to any spec or kit. Every carousel for any brand
  ships this text. Additionally, `gate_text_overflow` does not count the
  kicker's 3 words while the in-browser probe measures them, so the gate and
  the renderer disagree about what is on the slide.

## REV-708 — Carousel spec validation and hook gate raise unhandled exception types
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** carousel.py
- **Evidence:** carousel.py:74 (`sorted(s.get('idx') for s in slides)` → bare TypeError on missing idx); carousel.py:340 (`spec['slides'][0]` → IndexError on empty slides); book3cli.py:77-93 (`carousel_cmd` catches only CarouselError).
- **Finding:** Both defects escape `carousel_cmd`'s `except CarouselError` as
  raw tracebacks, breaking the module's own `_die` convention. `validate_spec`
  is also never called by `gate_slide_one_hook`, so `hypelab carousel gate
  --gates slide_one_hook` on an empty-slides spec crashes instead of failing
  the gate.

## REV-709 — Carousel uses inconsistent headless flags (`--headless` vs `--headless=new`)
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** carousel.py
- **Evidence:** carousel.py:183 (`_measure_slide` passes `--headless=new`); carousel.py:222 (`_screenshot` passes legacy `--headless`).
- **Finding:** The probe and the screenshot run Chromium in different headless
  modes. Harmless on Chrome ≥132 (verified Chrome 153 on the Threadripper,
  where `--headless` aliases the new mode), but the overflow gate measures in
  one engine and renders in another by accident, not by decision.

## REV-710 — `INVITE_STATUSES` is dead and contradicts the statuses the code writes
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** invites.py
- **Evidence:** invites.py:13 (tuple never referenced anywhere); invites.py:111 (writes `"accept_timeout"`, not in the tuple; `"expired"` in the tuple is never written).
- **Finding:** The documented status vocabulary is unreferenced and stale: the
  72-hour timeout writes `accept_timeout`, which is absent from
  `INVITE_STATUSES`, while `expired` is listed but never written. Anyone
  trusting the constant as the vocabulary (a future UI, a report) is misled.

## REV-711 — `cut_moment` raises bare TypeError (not CutError) on NULL score/confidence
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** cut.py
- **Evidence:** cut.py:133 (`float(mrow['score']) * float(mrow['confidence'])`); b2cli.py:293 (`except (CutError, ValueError)`).
- **Finding:** NULL score or confidence in a moment row raises TypeError, which
  escapes b2cli's `(CutError, ValueError)` handler as a traceback instead of
  the clean `cut failed: ...` path. Minor (score_moments always sets both),
  but the error-handling contract is narrower than the failure modes.

## REV-712 — `check_slots` and the render preflight disagree on required clip fields
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** gates.py, cli.py
- **Evidence:** gates.py:415-428 (`check_slots` requires `clip_slot`); cli.py:770-775 (`_render_job` preflight requires `clip` and `clip_path`).
- **Finding:** A hand-edited EDL carrying `clip`/`clip_path` but no `clip_slot`
  passes the render preflight, renders, then fails `slots_filled`. The
  triple-carry invariant (`clip`/`clip_slot`/`clip_path`) exists only as a
  comment at attach time — neither the EDL schema nor any single checkpoint
  enforces all three.

## REV-713 — `hypelab watch` has no Ctrl-C handling (traceback vs graceful exit)
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** b2cli.py, cli.py
- **Evidence:** b2cli.py:194-207 (`watch` loop, no KeyboardInterrupt handler); cli.py `work` (catches KeyboardInterrupt → "interrupted, exiting").
- **Finding:** The Book 2 long-running loop dies with a traceback on Ctrl-C
  while its Book 1 sibling exits gracefully. Inconsistent UX on the two
  commands an operator watches most.

## REV-714 — Compliance money-checks use substring matching (allowlist/handle/hashtag/credit)
- **Severity:** S3
- **Status:** Confirmed
- **Module(s):** compliance.py
- **Evidence:** compliance.py:141-146 (`chk_source_allowed`: `"youtube.com" in "evilyoutube.com"` → PASS); compliance.py:166-206 (handle/hashtag/credit/banned-words all use `in`).
- **Finding:** `chk_source_allowed` passes when the allowlist entry is a
  substring of the URL's domain — `https://evilyoutube.com/watch` passes a
  `["youtube.com"]` allowlist. The same substring logic lets `@acme` match
  `@acme2` and `#ad` match `#adapter`. ARC-310 covers allowlist logic
  *duplication*; this is the *matching weakness* itself — a real bypass shape
  in the money checks.

## REV-715 — Carousel re-render accumulates duplicate slide rows
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** carousel.py
- **Evidence:** carousel.py:301-312 (INSERTs slide rows per render, no DELETE/dedup).
- **Finding:** Re-running `hypelab carousel render` on the same job_id inserts a
  second copy of all 7 slide rows. The `slides` table has no uniqueness guard,
  so renders are not idempotent at the DB layer.

## REV-716 — `carousel` CLI parses the spec file outside the `_die` convention
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** book3cli.py
- **Evidence:** book3cli.py:96 (`json.loads(spec_path.read_text())` uncaught); book3cli.py:17-26 (`_die` convention used by every other command in the file).
- **Finding:** A malformed carousel spec escapes as a raw traceback instead of
  the `error: ...` message every other book3cli command produces. Cosmetic but
  inconsistent.

## REV-717 — `signals["duration"]` falls back to 0.0, contradicting the module's own "never invent a duration" rule
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** ingest.py
- **Evidence:** ingest.py:269-271 (comment: "never invent a duration"; then `signals["duration"] = 0.0` on ffprobe failure).
- **Finding:** When ffprobe fails, the module writes an invented 0.0 duration —
  exactly what the comment two lines above forbids. A 0.0 duration is
  indistinguishable from a real zero-length asset downstream.

## REV-718 — `cut()` is not atomic across moments: mid-loop failure wedges the job in `cutting` with partial clips
- **Severity:** S3
- **Status:** Confirmed
- **Module(s):** cut.py, b2cli.py
- **Evidence:** cut.py:199-232 (transitions scored→queued_cut→cutting, then loops `cut_moment` with no per-moment rollback or job-fail); b2cli.py:293-296 (catches CutError → `_die`, never calls `queue.fail`).
- **Finding:** If the second of three moments fails, the job sits in `cutting`
  with the first clip inserted and no retry/fail path — the CLI never calls
  `queue.fail`. The worker path is protected (its exception handler fails the
  job), but the CLI `cut` command is not. Same shape as BUG-003; this is the
  Book 2 cut-command instance.

## REV-719 — Carousel `audio_map` hardcodes the slide count instead of `SLIDES_REQUIRED`
- **Severity:** S4
- **Status:** Confirmed
- **Module(s):** carousel.py
- **Evidence:** carousel.py:316 (`range(1, 8)`); carousel.py:16 (`SLIDES_REQUIRED = 7`).
- **Finding:** The per-slide audio map is generated with a literal `range(1, 8)`
  while the required count lives in `SLIDES_REQUIRED`. A future slide-count
  change updates the validator but silently leaves the audio map at 7.
