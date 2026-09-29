# Flow 1 (BUG) — Book 1 pipeline: kit new → new → attach → audio → render → work → gates → ready|gate_failed

Owner: BUG (Logic & Correctness) · Phase 2, Pass 3 · 2026-09-29
Scope: `hypelab/cli.py` (orchestrator), `kits.py`, `script.py`, `edl.py`,
`manifests.py`, `align.py`, `render.py`, `gates.py`, `queue.py`, `jobs.py`.
Method: hop-by-hop trace from CLI handler → service → queue → worker
handlers → DB transitions → artifacts, asking at each hop about
null/empty/huge/malicious/slow/concurrent/repeated/out-of-order inputs.

## How it works (hop by hop, with path:line)

### H0. `kit new <id> --from kit.json` — cli.py:373-390 → kits.seed (kits.py:66-83)
1. `kit_new` reads + JSON-parses the file (`_die` on OSError/ValueError,
   non-dict → `_die`). If any of `generator/asr/captions/audio` keys are
   missing, the raw JSON is adapted via `kits_mod._adapt_cerebratico`
   (kits.py:100-165) — note the adaptation runs OUTSIDE the try/except, so
   garbage numerics (`"max_clip_s": "ten"`) raise an uncaught
   ValueError/TypeError traceback (→ BUG-011).
2. `kits.seed` checks existence (`SELECT 1 …`, kits.py:68-71) then INSERTs
   v1 with `payload["id"]/payload["version"]` forced (kits.py:74-82).
   Duplicate id → ValueError → clean `_die`. The exists-check→INSERT is a
   TOCTOU: two concurrent seeds → one unhandled `sqlite3.IntegrityError`
   (→ BUG-011).
3. Immutability actually enforced: PRIMARY KEY (id, version); `seed`
   refuses existing ids; `bump` (kits.py:85-103) only INSERTs max+1 with a
   deep-merged copy — old rows never UPDATE/DELETE. There is NO CLI
   command for `bump` (kit group exposes only `new`), so mid-flight bumps
   are Python-API-only.

### H1. `new --kit --script` — cli.py:392-464
1. `kits_mod.load(conn, kit_id)` — LATEST version, then PINNED:
   `jobs_mod.new(…, kit_id, kit_version=kit["version"])` (cli.py:452-455)
   and `edl["kit"] = f"{kit_id}@{kit['version']}"` (cli.py:443-444, schema
   pattern `^[a-z0-9_-]+@\d+$` in edl.py:35).
2. Script must be non-empty (`_die`); `script.to_beats(text, kit, max_s)`
   (script.py:37-84): sentences → beats, `dur =
   min(max(words/wps, min_beat_s), max_clip_s)`, proportional shrink when
   total > max_s, roles hook/body/cta, contiguous rounded boundaries.
   Negative/zero `--max-s` → ValueError → `_die`. `words_per_sec <= 0` etc.
   → ValueError → `_die` (script.py:52-60).
3. `edl.build_edl` (edl.py:158-184) stamps `min_word_prob` from the kit,
   snapshots the kit's `captions` block into the EDL; `edl.validate`
   (edl.py:104-155) enforces contiguity/hook/total rules → `_die` on
   violation.
4. `jobs_mod.new` → state `draft` (jobs.py:61-78); work dir created;
   `render.json` + `script.txt` written atomically
   (util.write_json tmp→fsync→rename, util.py:208-226); transition
   `draft → scripted`. `jobs.transition` clears lease fields on every move
   (jobs.py:114-121) and commits atomically (BEGIN IMMEDIATE … COMMIT).

### H2. `attach <job> <beat_id> <file>` — cli.py:508-554
1. Allowed only in `scripted|awaiting_media|gate_failed`; beat must exist.
2. `manifests.attach_asset` (manifests.py:230-280): `util.intake_asset`
   (stat → copy → hash → re-stat → atomic rename, util.py:132-178),
   ffprobe video probe with audio-only fallback; non-media → MediaError →
   `_die` — BUT the intaken file is already in `work/assets/` with no
   manifest entry and no cleanup (orphan bytes → BUG-014).
3. Sets `beat["clip"]`, `beat["clip_slot"]`, `beat["clip_path"]` (all three;
   renderer reads `clip`, `check_slots` reads `clip_slot`/`clip_path`);
   `_save_edl` atomic. Warns (never pads) when clip < beat need.
   `scripted → awaiting_media` on first attach;
   `gate_failed → awaiting_media` on re-attach.

### H3. `audio --vo [--music]` — cli.py:562-636 → _do_align (cli.py:264-330)
1. Allowed in `scripted|awaiting_media|gate_failed`. VO/music intaken via
   `attach_asset` (same orphan caveat); `edl["audio"]` nodes written +
   `_save_edl` BEFORE any state change (crash-safe ordering).
2. Transitions: `gate_failed → awaiting_media` (re-drive),
   `scripted → awaiting_media`, then `queued_align → aligning`
   (cli.py:605-614). **Lease is NULL after these** (transition clears it).
3. `_do_align`:
   - raises `AlignError` on empty beats; normalizes numbers FIRST
     (`normalize_numbers`, cli.py:238-261) because wav2vec2 has no digits;
     normalized text written to `work/tmp/script_normalized.txt`.
   - `align_mod.align_words(vo_path, words_tmp, script_path=norm,
     asr_cfg=kit["asr"])` (align.py:500-533): tokens present → forced
     wav2vec2 path; **tokens ABSENT (degenerate script) → falls through to
     `transcribe()` → `WhisperModel("medium")` downloads the model, THEN
     `retime_beats` raises "empty line"** (→ BUG-010).
   - `os.replace(words_tmp, work/vo.words.json)` — atomic publish (the path
     `gate_word_confidence` reads).
   - `retime_beats(norm_beats, words)` (align.py:457-498) then forced
     contiguity (`t_in = prev_out`, min 0.04s beat); ORIGINAL beat lines are
     kept, only times copied back (cli.py:302-309); `edl["captions"]["words"]
     = doc["words"]`; `_save_edl`.
   - Low-confidence rule: **MEAN** word prob per beat vs kit
     `min_word_prob` (cli.py:314-316; comment: book §10 mandates the mean).
     **BUT the routing is dead code**: `_do_align` calls
     `low_confidence_beats(doc, retimed, min_word_prob=0.0)` (cli.py:321)
     "purely as a word-count consistency check", then computes the mean
     over the returned entries (cli.py:322-330). `low_confidence_beats`
     only returns FLAGGED beats (align.py:416-455), and with threshold 0.0
     `mp < 0.0` is never true (probs clamped 0–1) → `by_beat` is always
     empty → the mean loop never runs → `flagged` is always empty → the
     `gate_failed` early route (cli.py:331-338) NEVER fires, no matter how
     low the word probabilities are (→ BUG-004).
4. `AlignError` → `_die("alignment failed")` — **job left in `aligning`
   with NULL lease: never claimable again** (claim step 2 needs a non-null
   lease, queue.py:117-122) and no CLI command leaves `aligning`
   (→ BUG-003). The worker path for the SAME error records `failed`
   instead — divergent failure semantics.
5. Success path: `aligned → queued_render`.

### H4. `render [--aspect]` — cli.py:656-752 → render_mod.render (render.py:404-530)
1. Entry states: `queued_render|rendered|queued_gates|ready|gate_failed`
   (cli.py:651-653). Preflight names missing slots → `_die`.
2. `queued_render → rendering` transition happens BEFORE `render_mod.render`
   (cli.py:681-682). Heartbeat thread (60s interval, separate DB
   connection, cli.py:684-700) only when `heartbeat_owner` is passed (i.e.
   only from the worker).
3. `render()` gate order: slots-filled (clip on disk, render.py:427-436) →
   `build_command` → `verify_manifest` re-hashes every asset (quarantine +
   ManifestError on tamper, manifests.py:310-350) → render-hash skip check
   (render.py:454-458) → ffmpeg (600s timeout, PID-unique `.partial-`
   temp, atomic rename; SIGKILL-safe per comments) → ffprobe output →
   `record_render` (manifest.json) → DB `renders` + `edls` rows
   (version=max+1), commit.
4. **Skip path returns with state untouched** (cli.py:725-729): from the CLI
   this leaves the job in `rendering` — NOT in RENDER_ENTRY_STATES and not
   claimable → permanently wedged (→ BUG-002). Realistic trigger:
   `gate_failed → audio` (identical media/alignment → identical EDL →
   identical render_hash, output exists) → `render` → skip → wedge.
   Worker variant: crash between render's commit and the transitions →
   reclaim → skip → stuck in `rendering` with live lease → 30-min reclaim
   loop, `attempts+1` each cycle, unbounded, never `fail()`.
5. Post-render: `rendering → rendered → queued_gates`. From `ready` with a
   CHANGED hash: warning printed, state left `ready` — **latest render row
   is now ungated while the job claims `ready`** (→ BUG-009).
6. `--aspect` variant: derived (non-persisted) EDL retargeted, but
   `render()` inserts the RETARGETED EDL into `edls` and a `renders` row
   with `aspect='1:1'`; transitions still drive `rendering → rendered →
   queued_gates`; `gates` then evaluates the variant and `ready` certifies
   it — the book-aspect deliverable may never have existed (→ BUG-009).
   (`derive()` deliberately avoids the tables — inconsistent treatment.)

### H5. `work [--once]` — cli.py:890-940; handlers 833-888
(see flow2-bug.md for the full loop analysis)
1. `queue.claim` moves `queued_X → X-ing` (claim's CLAIMABLE map,
   queue.py:32-39); dispatch on the ACTIVE state:
   `aligning → _handle_align`, `rendering → _handle_render`,
   `gating → _handle_gates` (+ Book 2 ingest/score).
2. `_handle_align` (cli.py:833-851): assumes VO already attached
   (`edl["audio"]["vo"]`); calls the SHARED `_do_align`; flagged →
   `gate_failed`, else `aligned → queued_render`. This is the crash-resume
   path for jobs stranded in `queued_align` (CLI `audio` sets
   `queued_align` before `aligning`; a kill between them leaves it
   claimable). AlignError here → caught by `except Exception` → `fail()`.
3. `_handle_render` → `_render_job(heartbeat_owner=owner)`.
4. `_handle_gates` → `_run_gates` → `ready|gate_failed`.
5. **CRITICAL: `except Exception` (cli.py:928) does NOT catch `SystemExit`
   from `_die`.** Every `_die` inside a handler (render preflight,
   render errors, `_run_gates` missing rows, `_get_job/_get_kit/_load_edl`)
   kills the worker WITHOUT `fail()`; deterministic failures then kill
   each reclaiming worker every 30 min (→ BUG-001).

### H6. `gates` — cli.py:754-817 → gates.run_all (gates.py:442-467)
1. CLI accepts `rendered|queued_gates|gating` — **`gating` is the worker's
   claimed-active state and the CLI never checks `lease_owner`**: operator
   + worker can gate concurrently → duplicate `gate_results` rows, loser's
   transition raises illegal-transition (→ BUG-007).
2. `_run_gates` reads the LATEST `renders` row and LATEST `edls` row
   independently (cli.py:757-770) — paired in practice (same `render()`
   inserts both), but aspect-agnostic (→ BUG-009).
3. `run_all` runs 8 gates (`GATES`, gates.py:31-32), records each verdict
   in `gate_results` (append-only, no run id), returns list. A gate that
   raises → failed gate — EXCEPT `globals()["gate_"+name]` is resolved
   OUTSIDE the try (gates.py:451-453): a bad EXTRA_GATES name raises
   KeyError out of `run_all` (→ BUG-013).
4. `gate_word_confidence` (gates.py:402-440) reads `work/vo.words.json` and
   calls `low_confidence_beats(doc, beats)` with beats carrying ORIGINAL
   lines while `doc["words"]` are number-NORMALIZED: the
   `n = len(line.split())` mapping (align.py:435) consumes original word
   counts against the expanded stream, so every beat after the first
   expansion maps onto the WRONG words and trailing words escape judgment
   entirely (→ BUG-005). It also enforces MIN prob while `_do_align` (dead
   anyway — BUG-004) and book §10 intend MEAN — a job can pass align-time
   and fail gate-time with no regression (the cli.py:64-65 comment claiming
   "a failure here means something regressed" is false on both counts).
5. `ready|gate_failed` routing considers all 8 gates; the CLI prints only
   the 7 book gates.

### H7. `costs` — cli.py:943-984
Reads `cost_ledger`; splits ESTIMATE|/ACTUAL| by note prefix (documentary
convention, queue.py:215-241). **`queue.charge()` has zero production
callers** (only tests/test_foundation.py:355-359) → always "no cost rows
recorded" (→ BUG-008).

## Align two-path reconciliation (MAP open item)
Both paths funnel through the single `_do_align` (cli.py:264-330):
- **Path A (inline, CLI `audio`)**: attach VO/music → save `edl["audio"]`
  → drive `queued_align → aligning` → `_do_align` → route.
- **Path B (worker `_handle_align`)**: claim does `queued_align →
  aligning` → assumes `edl["audio"]["vo"]` present → `_do_align` → route.
Path B is reachable only via crash between CLI audio's transitions, crash
during `_do_align`, or manual SQL — i.e. it is the crash-resume path, and
sharing `_do_align` is the right design. `_do_align` is re-runnable
(atomic `vo.words.json` replace, deterministic retime). DIVERGENCES:
(a) failure semantics differ — AlignError in A wedges the job in
`aligning` (BUG-003), in B records `failed`; (b) A re-drives
`gate_failed → awaiting_media` first, B never sees that state; (c) A prints
progress via `_transition`, B transitions silently.

## Observations
- State-machine discipline is good on the happy path (every transition via
  `jobs.transition`, leases cleared, atomic artifact writes, manifest
  verification before ffmpeg). The failure paths are where it breaks:
  active states + cleared leases + `_die` = wedged jobs (BUG-001/002/003).
- The number-normalization design is sound (normalize first, align
  normalized tokens), but the two places that judge confidence both break
  the invariant: the align-time mean check is dead code (BUG-004) and the
  gate re-maps with un-normalized lines (BUG-005).
- `render --aspect` is the only command that knowingly records a
  non-book artifact into the deliverable tables (BUG-009); `derive()`
  shows the authors knew the distinction.
- The queue's crash-recovery design (lease reclaim as a new attempt) is
  coherent, but the work loop trusts handler code not to `SystemExit`,
  and shared `_die`-based helpers violate that trust (BUG-001).

## Open questions
- Q1 (retry policy — already with Lead in QUESTIONS.md per TST-003): on
  handler failure below MAX_ATTEMPTS, auto-requeue or operator review?
  The `fail()` docstring promises re-queue; nothing implements it.
- Q2: should `render --aspect` variants advance the book pipeline, or be
  recorded without state transitions (like `derive()`)? Recommended
  default: variants must not drive `rendered → queued_gates → ready`;
  gates should refuse (or prominently label) non-target aspects.
- Q3: word-confidence gate — mean or min? Book §10 (per the `_do_align`
  comment) mandates MEAN; the gate enforces MIN on mis-mapped words.
  Recommended default: gate on mean over the normalized mapping, matching
  the align-time check.
- Q4: should CLI `gates` refuse `gating` when a live lease is held (or
  unconditionally)? Recommended default: refuse — the worker owns it.

## Related issues
- TST-003 (worker retry path absent; docstring claims re-queue) —
  confirmed here as BUG-007.
- TST-004 (kit appearance lock across bump untested) — the pinning
  mechanism itself is sound (see flow5-bug.md); only test coverage is
  missing.
- TST-007 (two-process claim race untested) — confirmed here as BUG-006.
