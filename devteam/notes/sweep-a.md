# SWEEP-A per-file notes — HypeLab full read, modules A–M

Sweeper: SWEEP-A (Phase 3, fresh eyes). Branch: `devteam/review-2026-09-29`
(commit d778635). Read-only on product source; 24 modules read fully
(align, attribution, authorize, b2cli, book3cli, boundary, campaigns,
captions, carousel, cli, compliance, consent, cut, db, edl, feedback,
gates, ingest, __init__, invites, jobs, kits, manifests, metrics).
archive.py, audio.py, cost(s).py, doctor.py, dryrun.py, library.py,
meta.py do not exist — skipped.

New findings filed in `devteam/findings/rev-a.md` as REV-700–REV-720.
Existing findings from MAP/TST/BLD/DOC/STR/DAT/ARC/BUG/SEC lanes were
checked first; confirmations are noted below, not re-filed.

---

## align.py (607 lines) — forced alignment + ASR transcription

What it does: wav2vec2 CTC forced alignment of known script words
(`force_align_words`, chunked at 30 s with 2 s overlap), faster-whisper
ASR transcription for Book 2 ingest, `vo.words.json` contract builder,
`retime_beats` (greedy beat↔word mapping), `low_confidence_beats`.

- **REV-705 (S2, NEW):** tokenization drift. `_script_tokens` uses
  `_WORD_RE = [A-Za-z0-9']+` (align.py:41), but `retime_beats`
  (align.py:478) and `low_confidence_beats` (align.py:414) count words
  with `str.split()`. These disagree on hyphens, em/en-dashes,
  underscores, and curly apostrophes: "well-known".split() → 1 word,
  `_WORD_RE.findall` → 2 tokens. The greedy sequential mapping then
  drifts for every beat after the first such word — beat t_in/t_out
  silently misattributed; trailing words silently dropped (split-count
  < token-count) or `AlignError("ran out of words")` (split-count >
  token-count). `normalize_numbers` does not strip hyphens, so this is
  reachable with ordinary scripts.
- BUG-004 CONFIRMED (not re-filed): `cli._do_align` calls
  `low_confidence_beats(doc, retimed, min_word_prob=0.0)`; since every
  word p ∈ [0,1], `mp < 0.0` is never true, `by_beat` is always `[]`,
  and `zip(by_beat, retimed)` yields nothing — `flagged` is always
  empty, so the align-time `gate_failed` routing in `hypelab audio`
  and the worker can never fire. The comment's stated intent (enumerate
  all beats, compute the mean here) is defeated by the 0.0 threshold.
- `force_align_words` chunk assignment (align.py:316-321) is a
  uniform-rate midpoint estimate; with strongly non-uniform speech
  (long pauses/silence) words land in the wrong chunk's audio window
  and the trellis silently aligns them to the wrong audio. The
  monotonicity pass cannot detect this. Documented heuristic, but the
  failure is silent — noted, not filed (S4-grade).
- `_check_words_sane` (align.py:548) fail-closed word-list validation
  is solid; the monotonicity fix pass guarantees t1 > t0 by ≥ one
  frame shift before rounding, so the post-rounding `t1 > t0` check
  cannot false-trip.
- `transcribe` strips empty words and rounds timings — fine.
  `_asr_cfg` accepts a bare string for backwards compat — fine.
- Unused leftover: `prev_t1 = 0.0` at align.py:323 (before the chunk
  loop) is dead — re-initialized at align.py:341. Trivial.

## attribution.py (240 lines) — what_worked attribution + weight proposals

What it does: attributes calibration-grade post views back to signal
buckets (`attribute`), n≥30 read guard (`read_dimensions`), n≥50
proposal guard (`propose_weights` → weights_v2_candidate.json),
operator-gated promotion (`promote_weights` → weights_v2.json).

- SQL interpolates `prov_list` via f-string, but the values come from
  the module constant `CALIBRATION_PROVENANCES`, not user input —
  no injection (matches SEC's negative result).
- `propose_weights`: bucket keys from `_bucket` are numeric strings,
  so `float(v)` comparisons are safe for `signal_*` dimensions. The
  `total = sum(nudged.values()) or 1.0` guard silently produces an
  all-zero weight set if every weight is 0 — degenerate but unreachable
  with sane base weights. Not filed.
- `promote_weights` correctly refuses non-"proposed" candidates.
  Writes go to the passed `weights_dir`, not hardcoded paths.
- No commit in `attribute()` — relies on the caller's autocommit
  connection (db.connect uses isolation_level=None); consistent with
  metrics/campaigns modules. Noted under ARC-305, not re-filed.
- `describe_row` uses fixed correlational templates — the
  no-causal-language rule is genuinely code-enforced.

## authorize.py (80 lines) — Dino's approval rows

What it does: `record` / `require_authorization` / `list_for` over the
authorizations table; separate from creator consent.

- **REV-706 (S3, NEW):** `require_authorization` returns the latest row
  for (job_id, action) with no expiry, no revocation, no intent
  comparison. A single `hypelab authorize` row authorizes that action
  on that job forever — unlike `consent.revoke()`, there is no
  revocation path at all (no CLI command, no API). The module's own
  docstring frames authorization as the hard safety rule; an
  irrevocable, never-expiring grant weakens it.
- `record` validates action ∈ ACTIONS and job existence — good.
  Commits the caller's connection (ARC-305 instance, not re-filed).

## b2cli.py (453 lines) — Book 2 CLI commands

What it does: campaign/source/watch/moments/cut/tray/posted/review/
measure/worked/propose-weights/promote-weights commands.

- **REV-700 (S2, NEW):** `campaign list` (b2cli.py:107-111) prints
  `c['status']`, but the campaigns table has a `state` column and no
  `status` column (migrations/0001 + 0002 ALTERs verified; `_parse`
  never adds `status`). KeyError on every invocation that has ≥1
  campaign to list. (ARC-301 covers bump-rules/refresh-budget only —
  this command is a separate, unfiled breakage.)
- **REV-701 (S4, NEW):** `campaign show` (b2cli.py:114-121) catches
  `KeyError`, but `campaigns.load` raises `CampaignError` — an unknown
  id escapes as a traceback instead of the clean `_die` path.
- ARC-301 CONFIRMED (not re-filed): `campaign bump-rules` passes the
  `--by` operator STRING as `provenance`, but `bump_rules` requires a
  dict with `who` → CampaignError every time. `campaign refresh-budget`
  passes the parsed budget JSON dict as `seen_usd` → `float(dict)`
  TypeError (uncaught — not even CampaignError) AND stores a raw
  operator string as `budget_provenance`, which `_parse`'s
  `json.loads` then chokes on at load.
- **REV-713 (S4, NEW):** `watch` (b2cli.py:194-207) has no
  KeyboardInterrupt handler — Ctrl-C traceback — while cli.py's `work`
  handles it gracefully. Inconsistent.
- **REV-718 (S3, NEW):** `cut` → `cut_mod.cut` transitions
  scored→queued_cut→cutting, then loops `cut_moment`. A mid-loop
  failure (b2cli catches CutError → `_die`) leaves the job wedged in
  `cutting` with partial clips inserted and no retry/fail path — the
  CLI never calls `queue.fail`. Cf. BUG-003 (same shape, `work`
  command); this is the Book 2 cut-command instance.
- `source add --poll-every` help claims "floor: 300" — verified
  enforced in `watcher.add_source`
  (`max(int(poll_every_s), MIN_POLL_EVERY_S)`). Help is accurate.
- `moments` formats `m['score']:.3f` — TypeError (not caught) if a
  moment row ever has NULL score. Marginal; noted not filed.
- ARC-308 CONFIRMED: `worked` writes (attribute upserts +
  feedback_runs row) despite the read-sounding name. ARC-312
  CONFIRMED: `_die`/`_root`/`_conn` triplicated across cli/b2cli/book3cli.

## book3cli.py (354 lines) — Book 3 CLI commands

What it does: authorize/carousel/publish/consent/pitch/invite/
feedback/priors commands; registered by cli.py.

- **REV-716 (S4, NEW):** `carousel_cmd` (book3cli.py:96) does
  `json.loads(...)` on the spec file uncaught — a malformed spec
  escapes as a traceback, breaking the module's own `_die` convention
  used everywhere else in the file.
- `invite_cmd` poll path: `publish_mod.get_adapter(adapter_name)` is
  uncaught — an unknown adapter name traceback. Marginal; noted.
- `carousel_cmd` creates the job via `jobs_mod.new(...,
  state="ready")` then commits — ARC-309 CONFIRMED (born in `ready`,
  bypassing the state machine). The unvalidated initial `state` kwarg
  on `jobs.new` is the mechanism (see jobs.py notes).
- `publish --live` refuses loudly with a clear message — good.
- `consent grant` enforces `--expires` presence at the CLI layer too;
  DAT-362 (value not validated) CONFIRMED, not re-filed.
- `authorize_cmd` catches only AuthorizationError from `record` —
  correct, since record raises AuthorizationError for unknown job.

## boundary.py (259 lines) — boundary refinement + cold open

What it does: sentence snapping, backfill, silence extension,
payload/hook-budget logic, `refine`, `cold_open`, and `select`
(cut.py's entry point producing clip-relative caption words).

- Logic verified against docstrings: `extend_to_silence`'s condition
  (`ps <= t+max_extra and pe >= t`) exactly matches "overlaps
  [t, t+max_extra]"; min/max enforcement order (snap → backfill →
  close → silence → min/max → hook check) matches the docstring.
- `select` correctly re-bases caption words to clip-relative t=0 and
  keeps absolute timings in `seg["words"]` for audit.
- `payload_words = seg_words[:24]` fallback when no payload found —
  arbitrary 24-word prefix, undocumented. S4-grade; noted not filed.
- `cold_open` returns `{"t_in", "card": None}` when no payload —
  `select` handles it (`premise=None, cold_open=False`). Fine.
- `_first_hit_charpos` iterates PATTERNS (imported from score) —
  earliest hit wins. Fine.

## campaigns.py (182 lines) — versioned campaign data

What it does: validate/add/load/list/bump_rules/refresh_budget/
compliance_is_stale over the campaigns table.

- `refresh_budget(conn, campaign_id, seen_usd, provenance)` stores
  `provenance` raw, but `_parse` does `json.loads(v)` on
  `budget_provenance` — a plain operator string stored here makes
  every later `load()`/`list_all()` crash with JSONDecodeError.
  (Part of the ARC-301 mechanism; the CLI is the trigger.)
- `add`/`bump_rules`/`refresh_budget` never commit — safe only via
  the CLI's autocommit connection; `bump_rules` also never writes a
  history row (old rules survive only inside compliance_log rows that
  referenced the old version — the docstring's claim). Noted.
- `validate` does not check numeric types for rate_per_1k_usd /
  budgets, and `state` is unvalidated free text. S4-grade; noted.
- `compliance_is_stale`: `used is None` → stale=True — sensible.
  `new_source_id` is a trivial `new_id("src")` wrapper.

## captions.py (111 lines) — word-pop ASS builder

What it does: `group_into_cards` (char budget / 0.45 s pause split) and
`build_ass` via pysubs2.

- STR-453 CONFIRMED (not re-filed): only `{`/`}` are escaped
  (captions.py:103); backslash and newline are not — residual
  override-block risk per STR-453's analysis.
- `cs = max(1, ...)` floors karaoke `\k` at 1 cs — non-negative
  durations safe. `HOLD_S` extends the last card 0.25 s — fine.
- `margin_v = h*safe_bottom_pct/100 + 40` — the +40 px fudge is
  undocumented; `safe_top_pct` is accepted but unused. S4-grade; noted.
- Missing t0/t1 keys in a word dict → KeyError (no validation).
  Words come from align; BUG-015-adjacent. Noted not filed.

## carousel.py (441 lines) — Mode C carousel renderer

What it does: spec → HTML → headless-Chromium PNGs (1080x1350) +
  JPEG export + audio_map.json; two gates (text_overflow,
  slide_one_hook); optional slides-table persistence.

- **REV-707 (S3, NEW):** `_slide_html` (carousel.py:126) hardcodes the
  hook-slide kicker as "New Light Management" — not from the spec, not
  from the kit (no kit/spec field exists for it). The module docstring
  promises "a dumb spec, a deterministic renderer"; every carousel for
  any brand ships this kicker. (Also: the word-count gate in
  `gate_text_overflow` does not count the kicker's 3 words, while the
  in-browser probe does measure it — inconsistent accounting.)
- **REV-708 (S4, NEW):** `validate_spec`: `sorted(s.get("idx") for s
  in slides)` raises bare TypeError (not CarouselError) when a slide
  lacks `idx`; `gate_slide_one_hook` does `spec["slides"][0]` →
  IndexError on an empty slides list. Both escape book3cli's
  `except CarouselError`.
- **REV-709 (S4, NEW):** `_measure_slide` uses `--headless=new` but
  `_screenshot` uses legacy `--headless`. Harmless on Chrome ≥132
  (verified Chrome 153 on the Threadripper, where `--headless` aliases
  the new mode) but inconsistent and confusing.
- **REV-715 (S4, NEW):** `render_carousel` INSERTs slide rows with no
  dedup — re-rendering the same job_id accumulates duplicate rows.
- **REV-720 (S4, NEW):** `audio_map` hardcodes `range(1, 8)` instead of
  `SLIDES_REQUIRED` — drifts if the slide count ever changes.
- The `<title>MEASURE:...` regex extraction is actually correct: the
  trailing `</title>` anchor forces the non-greedy `\{.*?\}` to the
  final closing brace. Checked and cleared — not a bug.
- STR-454 CONFIRMED (not re-filed): `kit_to_css` interpolates
  fill/accent/font raw into CSS (carousel.py:107-130) — untrusted-kit
  sink, no untrusted caller today.

## cli.py (997 lines) — the front door (Book 1 commands + worker)

What it does: kit/new/shots/attach/audio/render/gates/work/costs;
  `_do_align` shared by CLI audio and the worker; number normalization
  for forced alignment.

- BUG-002 CONFIRMED: `_render_job` returns early on `rec["skipped"]`
  ("hash unchanged, skipping") with no transition — a worker-claimed
  job stays in `rendering` forever (wedged; BUG-003's NULL-lease trap
  does not even apply since the lease is held).
- BUG-004 CONFIRMED: see align.py notes — `_do_align`'s flagged
  computation is dead (`min_word_prob=0.0` → `by_beat` always empty).
- BUG-005 CONFIRMED: `_do_align` pins contiguity onto `beats` (EDL
  beats keep ORIGINAL lines) while `doc["words"]` are normalized
  tokens; `gate_word_confidence` later maps normalized words onto
  original-line beats via `low_confidence_beats` — silent
  misattribution (plus the REV-705 tokenizer drift).
- BUG-008 CONFIRMED: `gates_cmd` accepts `gating` state with no lease
  check. BUG-010 CONFIRMED: `_run_gates` gates the latest renders row
  against the latest book-aspect EDL — a `--aspect` variant render can
  be certified by gates run against different bytes. BUG-014
  CONFIRMED: `globals()["gate_"+name]` sits outside the try.
- BUG-015 CONFIRMED: `_load_edl` parses JSON but never calls
  `edl.validate`. Adjacent crash sites from unvalidated EDLs:
  `_do_align`'s `edl["beats"]` and `edl["captions"]["words"]` raise
  bare KeyError on hand-edited EDLs (CLI `audio` → traceback; worker
  → `fail()`).
- `_render_job`'s "fail open with a warning" branch for unexpected
  re-render states is deliberate and documented. The heartbeat thread
  uses a separate DB connection — correct; `join()` without timeout
  could stall on a wedged heartbeat, marginal.
- `normalize_numbers`: verified year/percent/decimal/thousands rules;
  negative numbers ("-5") are NOT spelled out (regex has no sign) —
  "-5" → "-five", which then fails wav2vec2 vocab → AlignError. Edge
  case; the failure is loud, not silent. Noted not filed.
- `costs` ESTIMATE|/ACTUAL| prefix split is fine; BUG-009/DAT-352
  (charge() has no callers) CONFIRMED — `costs` always prints empty.
- The module-level `HYPELAB_LEASE_SECONDS` override mutates
  `queue_mod.LEASE_TTL_S` at import — acknowledged in the comment as
  test-only; process-scoped. Fine.

## compliance.py (389 lines) — the compliance gate (Book 2 §9)

What it does: PASS/FAIL/UNKNOWN checks over clip+campaign;
  `check`, `regated_if_stale`, `route_job`, `unknowns_for_job`,
  human `resolve`.

- **REV-703 (S2, NEW):** `regated_if_stale` rebuilds the clip dict
  with placeholder content instead of the clip row's stored fields:
  `caption=""` (the row HAS caption), `burned_text=""`,
  `overlays_text=[]`, `source_url=""`, `audio_provenance=
  "campaign_supplied"`, `mixed_music=False`, `watermark_verified=
  False`. At submission re-gate this false-FAILS handle/hashtag/
  credit checks (empty caption) and source-allowlist checks (empty
  URL), false-PASSES banned-words (empty burned text), and forces
  UNKNOWN on watermark. The Book 2 §9 "gate runs again at submission"
  guarantee is systematically wrong in both directions.
- **REV-714 (S3, NEW):** substring matching in money checks:
  `chk_source_allowed` (`"youtube.com" in "evilyoutube.com"` →
  PASS), and `chk_handle_present` / `chk_hashtags_present` /
  `chk_credit_present` / `chk_banned_words` all use `in` — "@acme"
  matches "@acme2". (ARC-310 covers allowlist *duplication*, not this
  weakness.)
- `check()` itself is sound: rule-governed checks go UNKNOWN without
  provenance; `passed = not failed and not unknowns`; compliance_log
  write uses NULL for unknowns-only. `route_job` aggregates once.
  `resolve` correctly re-routes the job when no unknowns remain.
- `unknowns_for_job` uses `cl.id` — verified the compliance_log DDL
  has `id INTEGER PRIMARY KEY AUTOINCREMENT`. Fine.

## consent.py (280 lines) — consent ledger (Book 3 §5)

What it does: grant/revoke/valid_for/require_consent/gate_consent/
  export_ledger; hash-pinned artifacts; revocation knocks scheduled
  jobs back to consent_granted.

- DAT-362 CONFIRMED (not re-filed): `grant` enforces expiry *presence*
  only; `valid_for` compares `expiry > now()` as STRINGS — correct
  only for zero-padded ISO-8601 with matching timezone format.
  Non-padded or differently-formatted expiries miscompare silently.
- `revoke`'s knock-back relies on the state_3_0 deviation
  (scheduled→consent_granted) — verified present in
  migrations/state_3_0.py. Consistent.
- `export_ledger` uses a plain (non-atomic) file write — cosmetic.
- `grant` stores both `artifact` and `artifact_path` as the same
  string — redundant columns, harmless.

## cut.py (301 lines) — Book 2 clip cutting

What it does: `cut_moment` (boundary→reframe→audio extract→EDL→
  render→compliance→clip row) and `cut` (multi-moment driver + job
  routing); `record_posted` (manual upload + submission re-gate).

- **REV-704 (S3, NEW):** `record_posted`'s failed-re-gate path does
  `jobs_mod.transition(conn, clip["job_id"], res["state"], ...)` where
  `res["state"]` can be `"compliance_unknown"` — but
  `BOOK2_STATES["tray"]` is `("posted", "archived", "failed")` and
  Book 3's migration adds no tray edges (verified in
  migrations/state_3_0.py). From `tray` (or `compliance_unknown`) this
  raises ValueError: the clip row was already moved, the job is
  stranded, and the CLI dies via `_die`. The unknowns-at-submission
  path the book describes has no legal transition.
- **REV-711 (S4, NEW):** `cut_moment` computes
  `round(float(mrow["score"]) * float(mrow["confidence"]), 4)` —
  NULL score/confidence raises bare TypeError, not CutError, escaping
  b2cli's `except (CutError, ValueError)`.
- **REV-718 (S3, NEW):** see b2cli notes — `cut()` is not atomic
  across moments; mid-loop failure wedges the job in `cutting`.
- `_build_edl` stamps `min_word_prob=0.0` — moot (no vo.words.json
  exists for Book 2 clips, so `gate_word_confidence` passes via the
  missing-file branch anyway) but the stamped 0.0 misstates the EDL.
- `_extract_segment_audio` validates argv elements (ARC-306 instance).
  `record_posted` correctly requires post_url and writes posts.posted_at
  non-null. `work_minutes` column verified present via 0002 ALTER.

## db.py (147 lines) — SQLite connections + migration runner

What it does: `connect` (WAL, FK, 30 s timeout, autocommit),
  `migrate` (numbered additive migrations, strict set-equality boot
  refusal), `_split_statements` via `sqlite3.complete_statement`.

- DAT-358 CONFIRMED: `connect()` runs `migrate()` on every open,
  including read-only commands.
- `_apply_migration` uses explicit BEGIN/COMMIT (not executescript) —
  correct; empty migration files raise rather than silently passing.
- The downgrade/foreign-DB refusal (`db_set != expected_set`) is
  genuinely strict — good.
- `DEFAULT_DB_PATH` hardcodes `/home/dino/hypelab/hypelab.db`
  (BLD-009 instance, not re-filed).

## edl.py (210 lines) — EDL schema + validation + builder

What it does: `EDL_SCHEMA` (jsonschema), `validate()` (contiguity,
  hook, duration budget), `build_edl`, `EDLError`.

- `build_edl` deliberately does not validate (documented); every
  production caller (`cli.new`, `cut._build_edl`) calls `validate()`
  right after — except the `_load_edl` read path (BUG-015).
- `build_edl` stamps `min_word_prob` which is NOT in EDL_SCHEMA —
  harmless (schema allows additional properties) but the schema is
  not the full contract. Noted.
- Rule checks verified: contiguity within 1e-3, beats[0].t_in == 0,
  exactly-one-hook-first, total ≤ max_duration_s. The hook rule
  (`not hooks or hooks[0] != 0`) is correct.

## feedback.py (201 lines) — Book 3 feedback loop

What it does: `feed_back` (posts → what_worked buckets + feedback_runs
  audit), `priors`/`best_value` (min_n=8 guard, applied flag),
  `snapshot_priors` (versioned JSON + priors table).

- DAT-350 CONFIRMED (not re-filed): `_best_views` takes MAX(views)
  over ALL provenances — user_entered rows feed what_worked,
  violating the module's own calibration rule. The EDL-bucket branch
  is guarded by try/except (ValueError, KeyError, TypeError) — fine.
- `snapshot_priors` version counter parses `priors_v*.json` stems
  defensively (`.isdigit()` guard); tmp+replace is atomic. Two
  concurrent snapshots could collide on version — marginal.
- `priors`/`best_value` honor the `applied` flag correctly; the
  min_n=8 guard is code-enforced, not a comment.

## gates.py (478 lines) — Book 1 quality gates

What it does: 8 gates (duration, loudness, first_frame, hook_budget,
  caption_safe, slots_filled, geometry, word_confidence) + `run_all`
  recording to gate_results + Book 3 `gate_consent` wrapper.

- MAP-004 CONFIRMED: `import json` twice (gates.py:23-24).
- **REV-712 (S4, NEW):** `check_slots` requires `clip_slot`, but
  `_render_job`'s preflight (cli.py) checks `clip`/`clip_path` —
  divergent preconditions. A hand-edited EDL with `clip` but no
  `clip_slot` passes the render preflight, renders, then fails
  `slots_filled`. The triple-carry invariant (`clip`/`clip_slot`/
  `clip_path`) is documented only in a comment at cli.py attach.
- `gate_duration` hardcodes a 3.0 s minimum — printed in the detail
  string, but the 3.0 constant itself is uncited (no book section).
  Noted.
- `gate_geometry` uses float `==` on fps — fragile if `util.ffprobe`
  ever returns "30000/1001"-style strings (currently parsed by
  `util._fps`; out of sweep scope). Noted.
- `gate_caption_safe` passes vacuously when captions.ass is absent —
  deliberate and documented ("no captions … not present"). Not filed.
- `gate_word_confidence`: BUG-005 CONFIRMED (normalized-words vs
  original-line beats). Passes-with-note on missing vo.words.json is
  deliberate.
- `_LEGACY_TO_NUMPAD` mapping verified correct against SSA legacy
  semantics (\a1 bottom-left → \an1, etc.).
- `run_all` does not commit gate_results itself — safe under the
  CLI's autocommit connection; under a legacy deferred connection the
  subsequent `_transition` participates in the open transaction
  (`own = not conn.in_transaction`). No nested-BEGIN bug. Checked.

## ingest.py (310 lines) — Book 2 source ingest

What it does: `require_rights` (fail-closed rights manifest),
  yt-dlp/manual intake, transcription → source.words.json +
  signals.json, content_sha256 pinning.

- **REV-702 (S2, NEW):** the documented preference-3 path is
  unreachable. `require_rights` passes `basis="needs_clearance"` +
  recorded clearance, and `watcher.record_clearance` deliberately
  keeps `basis="needs_clearance"`. But `ingest`'s download dispatch
  requires `manifest.get("basis") in CLEAR_BASES`
  ("campaign_supplied" | "platform_mechanism" |
  "explicit_permission") — so a cleared third-party URL falls through
  to `IngestError("no ingest path …")`. The clearance object is
  write-only: recorded, never acted on.
- **REV-717 (S4, NEW):** `signals["duration"]` falls back to `0.0`
  when ffprobe fails — directly contradicting the comment two lines
  above ("never invent a duration").
- `ingest` takes only the FIRST source_item (`LIMIT 1`) — a job with
  several items silently ingests one. Undocumented; S4-grade, noted.
- `_fixture_item_info` is correctly gated to `kind="manual"`.
- `_transcribe_words` deletes the temp wav in a finally — good.
- STR-450 (unbounded yt-dlp/watcher fetch) noted as out of my lane;
  not re-filed.

## __init__.py (5 lines)

- MAP-005 CONFIRMED: docstring "M1-M4, M6 gate" is stale vs the
  Books 1–3 reality. `HYPELAB_VERSION = "0.2.0"` feeds
  manifests.provenance — fine.

## invites.py (140 lines) — invite tracking + polling

What it does: `add` (authorization-gated), `poll` (adapter status +
  72 h accept-timeout), `record_outcome`, `poll_invite_metrics`.

- **REV-710 (S4, NEW):** `INVITE_STATUSES` (pending/accepted/declined/
  expired) is never referenced anywhere — dead constant. Worse, the
  code WRITES `"accept_timeout"` (invites.py:111), which is not in the
  tuple ("expired" is, but is never written). Anyone trusting the
  tuple as the vocabulary is misled. (The `awaiting_accept →
  accept_timeout` job transition itself is legal per state_3_0.py —
  checked.)
- DAT-351 CONFIRMED: `poll_invite_metrics` writes recorded fixtures
  with `provenance='provider_api'` — calibration-grade provenance for
  fixture data.
- `poll`'s adapter-failure branch updates `checked_at` and continues —
  correct (adapter failure ≠ invite outcome). `_transition_job`
  swallows ValueError — the invite row stays the record of truth.
  Fine.
- `_age_hours` handles naive timestamps as UTC and garbage as 0.0 —
  garbage timestamps therefore never time out (fail-open on timeout,
  fail-closed on polling). Noted.
- `add` checks authorization BEFORE post existence — fine order.

## jobs.py (140 lines) — job lifecycle state machine

What it does: Book 1 ALLOWED map + Book 2/3 extensions, `new`,
  `transition` (lease-clearing, re-entrant transaction participation),
  `get`.

- `new()` does NOT validate the initial `state` — any string is
  accepted, including states not in ALLOWED (a job created in
  "banana" can never transition out; `ALLOWED.get("banana", ())`
  is empty → wedged at birth). `carousel_cmd`'s `state="ready"` is the
  live instance (ARC-309). The missing validation is the mechanism —
  noted under ARC-309, not separately filed.
- `new()` does not commit (unlike authorize.record/kits.seed) —
  every CLI caller happens to commit afterwards. Inconsistent with
  sibling modules (ARC-305); noted.
- `transition`'s re-entrancy (`own = not conn.in_transaction`) is
  correct and well-commented; lease fields cleared on every move.
- The Book 3 merge assertion (add-only) is a genuine invariant guard.

## kits.py (180 lines) — brand kit store

What it does: immutable versioned kits (`seed`/`bump`/`load`),
  `_adapt_cerebratico` for shipped kit.json.

- BUG-012 CONFIRMED: `_adapt_cerebratico`'s bare `float(...)` calls
  raise uncaught ValueError on non-numeric strings; `kit new`
  catches only ValueError from `seed`, not from adaptation. The
  seed/bump exists-check race is also as described.
- `bump`'s `MAX(version)+1` has a concurrent-bump race (two writers
  → PRIMARY KEY conflict → IntegrityError). TST-004-adjacent; noted.
- `_now()` duplicates `util.now()` at seconds precision — same
  contract, harmless duplication.
- `CEREBRATICO_KIT_PATH` hardcoded (BLD-009 instance).
- `_deep_merge` semantics (nested dicts merge, everything else
  replaces) are correct and documented.

## manifests.py (381 lines) — content-addressed manifests

What it does: `render_hash` (canonical EDL + sorted input digests +
  provenance), `attach_asset` (atomic intake + probe + manifest),
  `verify_manifest` (re-hash, quarantine on mismatch),
  `record_render`/`record_measurement`.

- BUG-013 CONFIRMED: `attach_asset` intakes (copies into
  work/assets/) BEFORE probing — a probe failure leaves the orphan
  file (the manifest entry is never written, but the bytes stay).
- `render_hash` sorts input digests (order-independent) and truncates
  to 32 hex chars — sound. Re-reads every input file per call
  (expensive, correct).
- `_quarantine`'s name-collision loop is correct; `verify_manifest`
  re-reads the manifest after quarantining before dropping the entry
  — correct sequencing. First mismatch raises; remaining assets go
  unverified — fail-closed anyway.
- `attach_asset("")` — `Path("").name == ""` passes the traversal
  guard; intake would then fail downstream. Marginal; noted.
- Audio-fallback path swallows the audio probe error and re-raises
  the video error — the rejection reason can mislead, but the file is
  rejected either way. Noted not filed.

## metrics.py (136 lines) — metrics polling + $/clip-hour

What it does: `poll_metrics` (INSERT OR REPLACE per post),
  `record_user_metrics`, `best_views` (calibration-grade only),
  `usd_per_clip_hour`.

- `poll_metrics`'s INSERT OR REPLACE granularity is (post_id, at)
  with `now()` at seconds precision — two polls in the same second
  replace, not duplicate; documented as intended.
- DAT-352/DAT-353 CONFIRMED: `queue.charge()` has no production
  callers and `payout_usd` is never written — `usd_per_clip_hour`'s
  `earned` is always NULL. DAT-363 (`unknown` vs `unavailable`)
  CONFIRMED in PROVENANCE_RANK.
- `open_posts` joins posts→clips on `c.state='posted'` — correct per
  the polling-cadence docstring.
- `record_user_metrics` validates post existence — good. Neither it
  nor `poll_metrics` commits (autocommit reliance, ARC-305-adjacent).
