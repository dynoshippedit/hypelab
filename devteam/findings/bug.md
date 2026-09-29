# BUG findings — Logic & Correctness Reviewer

Phase 2 (Pass 3: critical-flow tracing) + Pass-4-relevant correctness checks
on the traced paths. IDs BUG-001…099 reserved for this lane. Severity per
Playbook B7; confidence per B7. Source read-only — all "Confirmed" below
rest on unambiguous code with cited lines.

Flows traced: `devteam/notes/flows/flow1-bug.md` (Book 1 pipeline),
`devteam/notes/flows/flow2-bug.md` (worker loop), `devteam/notes/flows/flow5-bug.md`
(kit lock). TST-003 verdict: CONFIRMED (see BUG-006).

## Ledger

| ID | Title | Sev | Confidence | Status |
|---|---|---|---|---|
| BUG-001 | SystemExit from `_die` in worker handlers bypasses `fail()` and kills the worker | S1 | Confirmed | NEW |
| BUG-002 | Render hash-skip leaves worker/CLI job wedged in `rendering` | S1 | Confirmed | NEW |
| BUG-003 | CLI drive parks jobs in active states with NULL leases on failure — unrecoverable without SQL | S1 | Confirmed | NEW |
| BUG-004 | Align-time low-confidence → `gate_failed` routing is dead code (the `min_word_prob=0.0` trick can never flag) | S1 | Confirmed | NEW |
| BUG-005 | `gate_word_confidence` maps normalized words onto original-line beats — silent misattribution; min-vs-mean mismatch | S1 | Confirmed | NEW |
| BUG-006 | `queue.claim()` double-claim race under concurrent workers; `fail()` SELECT→UPDATE TOCTOU | S1 | Likely | NEW |
| BUG-007 | `fail()` docstring promises a re-queue the work loop never performs; no operator retry path (TST-003 confirmed) | S2 | Confirmed | NEW |
| BUG-008 | CLI `gates` accepts worker-claimed `gating` state — concurrent double-gating, no lease check | S2 | Confirmed | NEW |
| BUG-009 | `queue.charge()` has zero production callers — `hypelab costs` always empty | S2 | Confirmed | NEW |
| BUG-010 | `render --aspect` variant drives the book pipeline; `ready` can certify a non-book aspect | S2 | Confirmed | NEW |
| BUG-011 | Degenerate script triggers faster-whisper model download before the inevitable AlignError | S2 | Confirmed | NEW |
| BUG-012 | `kit new`: uncaught float() in kit adaptation; seed/bump exists-check races | S3 | Confirmed | NEW |
| BUG-013 | Failed `attach` leaves orphan file in `work/assets/` (intake before probe) | S3 | Confirmed | NEW |
| BUG-014 | `run_all` resolves `globals()["gate_"+name]` outside the try — bad EXTRA_GATES name escapes as KeyError | S3 | Confirmed | NEW |
| BUG-015 | `_load_edl` never schema-validates render.json — hand-edited EDLs fail deep with KeyError tracebacks | S3 | Confirmed | NEW |

---

### BUG-001 — SystemExit from `_die` in worker handlers bypasses `fail()` and kills the worker
- **Severity:** S1 (core flow reliability: deterministic failures kill the
  worker process; lease orphaned; failure never recorded; poison never
  engages). Confidence: Confirmed.
- **Evidence:** `hypelab/cli.py:80-83` — `_die` raises `SystemExit(code)`.
  The work loop's handler guard is `except Exception as e:` at
  `hypelab/cli.py:928` — `SystemExit` derives from `BaseException`, so it
  is NOT caught. Handler-reachable `_die` calls: `_render_job` missing-clip
  preflight (`cli.py:666-669`) and `except (RenderError, ManifestError) →
  _die(f"render failed: …")` (`cli.py:717-718`); `_run_gates` `_die` on
  missing renders/edls rows (`cli.py:762-770`); `_get_job`/`_get_kit`/
  `_load_edl` `_die`s inside `_handle_align/_render/_gates`
  (`cli.py:833-864`). The outer `try` around the loop catches only
  `KeyboardInterrupt` (`cli.py:899,939-940`), so the process exits with the
  SystemExit code and `queue.fail()` never runs.
- **Why it matters:** the comment at `cli.py:928` says "handler blew up:
  record, don't lose the job" — the intent is explicit, and `_die`
  defeats it. A deterministic failure (clip file deleted from disk →
  preflight `_die`; corrupt input → RenderError → `_die`) kills the worker;
  the job sits in its active state with a dead owner's lease; 30 min later
  another `work` reclaims it and dies the same way — a worker-killing
  livelock with no error recorded and no poison stamp. `AlignError`
  (an `Exception`, `align.py:42`) IS caught — so the same worker treats
  two failure classes inconsistently based on which helper raised.
- **Fix (Phase 5):** make `_die` raise a dedicated `CliError(Exception)`
  instead of `SystemExit`, so the existing `except Exception` catches it in
  both worker and CLI paths; or wrap handler dispatch in `except
  BaseException` (excluding KeyboardInterrupt). Test: monkeypatched
  `_handle_render` raising via `_die` → assert state `failed` + error
  recorded, worker alive. Effort: S.

### BUG-002 — Render hash-skip leaves worker/CLI job wedged in `rendering`
- **Severity:** S1 (job permanently wedged in a non-entry, non-claimable
  state via a realistic operator path). Confidence: Confirmed.
- **Evidence:** `_render_job` transitions `queued_render → rendering`
  BEFORE `render_mod.render` (`cli.py:681-682`); on
  `rec["skipped"]` it prints "hash unchanged, skipping" and returns with
  "the state is left untouched" (`cli.py:725-729`). `rendering` is NOT in
  `RENDER_ENTRY_STATES` (`cli.py:651-653`), and `transition` cleared the
  lease (`jobs.py:114-121`), so `queue.claim` step (2) — which requires
  `lease_expires IS NOT NULL` (`queue.py:117-122`) — can never reclaim it.
  Realistic trigger: `gate_failed` → `audio` (identical media + deterministic
  alignment → identical EDL → identical `render_hash`, output file exists)
  → `render` → skip → stuck in `rendering` forever (only SQL recovers).
  Worker variant: kill -9 between render's DB commit (`render.py:505-527`)
  and the `rendered → queued_gates` transitions (`cli.py:732-735`) →
  reclaim → skip → stuck with a LIVE lease → 30-min reclaim loop,
  `attempts+1` per cycle, unbounded, never `fail()`.
- **Why it matters:** the skip path was designed for CLI idempotence but
  ignores that the caller may have moved the job into an active state first.
  The worker variant additionally defeats the attempts/poison accounting.
- **Fix (Phase 5):** on skip, if state is `rendering`, transition
  `rendering → rendered → queued_gates` (the output IS current, so gating
  is the correct next step); if the CLI entry state was `ready`/`gate_failed`
  with unchanged hash, leave state alone (today's correct case). Test:
  gate_failed → audio (same media) → render → assert state `queued_gates`,
  not `rendering`. Effort: S.

### BUG-003 — CLI drive parks jobs in active states with NULL leases on failure
- **Severity:** S1 (routine, expected failures wedge jobs beyond any CLI or
  worker recovery). Confidence: Confirmed.
- **Evidence:** Three sibling instances of one pattern — the CLI moves to an
  active state, then `_die`s without repair:
  1. `audio`: `queued_align → aligning` (`cli.py:612-614`), then
     `_do_align` raising `AlignError` → `_die("alignment failed")`
     (`cli.py:616-619`). Job in `aligning`, lease NULL.
  2. `render` via `_render_job`: `queued_render → rendering`
     (`cli.py:681-682`), then `RenderError`/`ManifestError` →
     `_die(f"render failed")` (`cli.py:717-718`). Job in `rendering`, lease
     NULL.
  3. `gates`: `queued_gates → gating` (`cli.py:803-806`), then any exception
     escaping `gates.run_all` → traceback, no state repair. Job in
     `gating`, lease NULL.
  `jobs.transition` clears `lease_owner/lease_expires` on every move
  (`jobs.py:114-121`); `queue.claim` step (1) only takes `queued_*`
  (`queue.py:92-108`) and step (2) requires a non-null lease
  (`queue.py:117-122`). No CLI command transitions OUT of
  `aligning`/`rendering`/`gating` except via the worker handlers, which
  can't claim these rows. Only raw SQL recovers.
- **Why it matters:** a bad VO file (the normal, expected AlignError case)
  permanently bricks the job when driven via CLI `audio`, while the SAME
  error via the worker records `failed` — divergent failure semantics for
  one operation (see flow1-bug.md §H3/H5 reconciliation). The queue's crash
  recovery was designed around "every active state carries a lease"; the
  CLI drive violates that invariant on every failure.
- **Fix (Phase 5):** on failure in the CLI drive, transition to `failed`
  (via `queue.fail`-equivalent semantics) instead of `_die`-and-park; or
  restore the previous queued state. Test each of the three commands with
  an injected failure → assert a recoverable state. Effort: M.

### BUG-004 — Align-time low-confidence → `gate_failed` routing is dead code
- **Severity:** S1 (the book §10 low-confidence rule's early route never
  fires; low-confidence jobs always proceed to render before any quality
  check). Confidence: Confirmed.
- **Evidence:** `_do_align` calls
  `align_mod.low_confidence_beats(doc, retimed, min_word_prob=0.0)`
  (`cli.py:321`), then iterates the returned entries computing the MEAN
  word prob per beat (`cli.py:322-330`) — the comment says the 0.0 call is
  just to get per-beat entries ("compute it here explicitly" because the
  landed function uses the minimum). But `low_confidence_beats` returns
  only FLAGGED beats (`align.py:416-455`): `mp = min(probs)` and
  `if mp < min_word_prob:` with `min_word_prob=0.0`. Word probabilities
  are clamped to 0–1, so `mp < 0.0` is never true → `by_beat` is ALWAYS
  empty → the `for entry, rb in zip(by_beat, retimed)` mean-computation
  loop never executes → `flagged` stays empty unconditionally. The
  `if flagged: … gate_failed` branch (`cli.py:331-338`) is unreachable.
- **Why it matters:** book §10's early `gate_failed` route for low word
  confidence does not exist in practice. Jobs with terrible alignment sail
  through `audio` to `queued_render` and consume a full render before the
  final gate (itself broken — BUG-005) may catch them. Both the CLI `audio`
  path and the worker `_handle_align` path share `_do_align`, so both are
  affected. The docstring of `_do_align` ("Returns (words_doc, flagged)
  … for beats whose mean word probability is below the kit threshold",
  `cli.py:271-273`) is false.
- **Fix (Phase 5):** iterate ALL beats (not the flagged subset) for the
  mean computation — e.g. call a helper that returns per-beat spans, or
  drop the `low_confidence_beats` call and compute the mean directly from
  the retimed spans. Test: feed words with known low p (stub align_words)
  → assert `flagged` non-empty and state `gate_failed`. Effort: S.

### BUG-005 — `gate_word_confidence` maps normalized words onto original-line beats
- **Severity:** S1 (quality gate judges the wrong words whenever number
  normalization expands a beat — a common case; false pass AND false fail
  both possible). Confidence: Confirmed.
- **Evidence:** `_do_align` aligns NORMALIZED lines (`norm_beats`,
  `cli.py:299-300`) but saves beats with ORIGINAL lines back to the EDL
  (`cli.py:304-309`). `gate_word_confidence` (`gates.py:402-440`) reads
  `beats = edl.get("beats")` — ORIGINAL lines (`gates.py:425`) — and calls
  `low_confidence_beats(doc, beats, min_word_prob=threshold)`, which maps
  `n = len(str(b.get("line","")).split())` (`align.py:435`) onto the
  NORMALIZED word stream. Expansion example (from the digits test,
  verified in `tests/test_cli.py` which only runs `audio`): "The year was
  1999." is 4 words but aligns as "the year was nineteen ninety nine" (7
  words); the gate consumes 4 words for that beat, shifting every later
  beat's span left and leaving the trailing words unevaluated — silently,
  because `len(span) < n` (the fail-closed AlignError) only triggers when
  the stream runs OUT, and original lines are SHORTER than normalized, so
  it never does. Second inconsistency: the gate flags on the MINIMUM word
  prob per beat (`align.py:449-452` docstring) while `_do_align`/book §10
  intend the MEAN (`cli.py:314-316` comment) — a beat passing align-time
  can fail gate-time with no regression, contradicting the `cli.py:64-65`
  comment ("a failure here means something regressed").
- **Why it matters:** the gate that certifies word confidence evaluates a
  misaligned word-to-beat mapping for any script with multi-word number
  expansions — missing truly low-confidence words in the ignored tail and
  flagging innocent beats on shifted spans.
- **Fix (Phase 5):** persist the normalized lines (or per-beat word index
  ranges) at align time and have the gate use them; align the gate's
  statistic with the book (mean). Test: script with "1999"/"20%" → full
  pipeline → assert gate verdict matches the align-time verdict. Effort: M.

### BUG-006 — `queue.claim()` double-claim race; `fail()` SELECT→UPDATE TOCTOU
- **Severity:** S1 (queue integrity is a crown jewel; two concurrent `work`
  processes double-execute: double ffmpeg renders, duplicate `renders`
  rows, conflicting transitions, `attempts+2`). Confidence: Likely (race
  proven by code shape; not executed live — TST-007).
- **Evidence:** claim step (1) (`queue.py:92-108`): the outer UPDATE's WHERE
  is only `id=(SELECT id FROM jobs WHERE state=? …)` — it does not re-check
  the state. Under autocommit (`isolation_level=None`, `db.py:143`) with
  deferred locking, two workers can both evaluate the subselect against the
  same queued job before either commits; both UPDATEs then apply (second
  overwrites `lease_owner`) and both callers receive the row. Same shape in
  the reclaim step (`queue.py:110-126`). Sibling: `fail()` SELECTs the row
  and checks `lease_owner == owner` (`queue.py:183-190`) but UPDATEs with
  `WHERE id=?` only (`queue.py:196-201`) — a reclaim landing in between
  lets a stale worker clobber the new owner's lease (microsecond window;
  S2 within this entry).
- **Why it matters:** the module docstring promises "exactly one worker
  wins the job" (`queue.py:1-11`); the SQL doesn't enforce it. Consequence
  isn't just wasted CPU: two `_handle_render`s interleave DB transitions
  and both insert `renders`/`edls` rows for one job.
- **Fix (Phase 5):** add `AND state=?` (expected src/active state) to the
  outer UPDATE WHERE in both claim steps; treat empty RETURNING as a lost
  race and continue scanning. Add `AND lease_owner=?` to `fail()`'s UPDATE
  and check `rowcount`. Test: two-process claim race asserting single
  ownership (TST-007's planned test). Effort: S.

### BUG-007 — `fail()` docstring promises a re-queue the work loop never performs; no operator retry
- **Severity:** S2 (documented critical flow "enqueue → lease → execute →
  retry" is broken at "retry"; doc materially misleads; failed jobs are
  SQL-only). Confidence: Confirmed.
- **Evidence:** `queue.fail` docstring: "below the limit the work loop may
  re-queue it while attempts remain" (`queue.py:172-180`); but `fail()`
  unconditionally `UPDATE jobs SET state='failed'` (`queue.py:196-201`),
  and the work loop on handler exception calls only `queue_mod.fail()`
  (`cli.py:928-935`) — no re-queue anywhere (`grep -rn requeue hypelab/`
  hits only the docstring). `release()` (`queue.py:144-170`) — the only
  re-queue primitive — has ZERO production callers. `failed`'s sole legal
  exit is `failed → draft` (`jobs.py:44`); no CLI command performs it (no
  `"draft"` in cli.py/b2cli.py/book3cli.py); `_print_poison`
  (`cli.py:820-830`) prints poisoned jobs with no remediation offered.
- **Why it matters:** a transient failure (ffmpeg OOM) permanently parks
  the job in `failed` with no automatic retry, contradicting the docstring
  and the MAP's flow (4). This is TST-003, confirmed with code evidence;
  the product decision (auto-requeue vs operator review) is already with
  the Lead in QUESTIONS.md.
- **Fix (Phase 5):** decide policy first (QUESTIONS.md), then either
  implement re-queue below MAX_ATTEMPTS or correct the docstring AND add a
  CLI retry command (`failed → draft` or `failed → queued_*`). Effort: M
  + owner decision.

### BUG-008 — CLI `gates` accepts worker-claimed `gating` state
- **Severity:** S2 (concurrent double-gating; duplicate `gate_results`
  rows; loser's transition raises illegal-transition). Confidence:
  Confirmed.
- **Evidence:** `gates_cmd` accepts `rendered|queued_gates|gating`
  (`cli.py:796-817`); `gating` is exactly the state `queue.claim` moves a
  worker's job into (`queue.py:32-39`), and the CLI never checks
  `lease_owner`. Operator running `hypelab gates` while a worker handles
  the same job → both run the 8 ffmpeg gates concurrently → both INSERT
  into `gate_results` (append-only, no run id, no unique constraint) →
  both attempt `gating → ready|gate_failed`; the second gets
  `ValueError: illegal transition` (`_die` in CLI; `fail()` attempt in
  worker, whose lease was cleared by the winner's transition →
  "fail() skipped"). `render`/`attach`/`audio` don't have this overlap
  (`rendering`/`aligning` aren't CLI entry states) — `gates` is the only
  command that collides with a worker-claimed active state.
- **Why it matters:** silent duplicate gate history and a loud,
  confusing illegal-transition error for the loser; the operator can't
  tell which verdict won.
- **Fix (Phase 5):** refuse `gating` when a live lease is held by another
  owner (or unconditionally — the worker owns it). Test: claim a job,
  then CLI `gates` → clean refusal. Effort: XS.

### BUG-009 — `queue.charge()` has zero production callers
- **Severity:** S2 (dead feature presented as live; MAP §6 and the `costs`
  command imply a working ledger). Confidence: Confirmed.
- **Evidence:** `grep -rn 'charge(' hypelab/` shows only the definition
  (`queue.py:215`) and the docstring mention (`util.py:182`); the only
  calls are in `tests/test_foundation.py:355-359`. `hypelab costs`
  (`cli.py:943-984`) therefore always prints "no cost rows recorded" in
  real use. No pipeline step (align/model load, render) records
  ESTIMATE|/ACTUAL| rows despite the documented convention
  (`queue.py:215-241`).
- **Why it matters:** cost accounting is part of the book's operating
  picture; today it is test-only. Either wire it (charge on align/render)
  or remove/document as not-implemented.
- **Fix (Phase 5):** owner call — wire `charge()` into `_do_align` and
  `render()` (estimates), or drop the `costs` command. Effort: S-M.

### BUG-010 — `render --aspect` variant drives the book pipeline; `ready` can certify a non-book aspect
- **Severity:** S2 (wrong artifact certified; `ready` doesn't mean what it
  says). Confidence: Confirmed.
- **Evidence:** `_render_job` with `aspect != target.aspect` renders a
  derived EDL (`cli.py:664-669`) but `render()` still inserts the
  RETARGETED EDL into `edls` and a `renders` row with `aspect='1:1'`
  (`render.py:505-527`); transitions still run
  `rendering → rendered → queued_gates` (`cli.py:730-735`); `_run_gates`
  evaluates the LATEST rows regardless of aspect (`cli.py:754-791`), and
  `gate_geometry` checks against the variant's own target — so a 1:1-only
  render can carry a job to `ready` while the 9:16 book deliverable was
  never produced. `derive()` explicitly NEVER touches the tables
  (`render.py:533-585`, "a preview is not a deliverable") — the codebase
  knows the distinction; `--aspect` ignores it. Sibling: re-render from
  `ready` with a changed hash leaves state `ready` with only a printed
  warning (`cli.py:736-741`) while the latest render row is ungated.
- **Why it matters:** downstream consumers (Book 3 publish, the operator)
  read `ready` as "the deliverable passed gates"; after a variant render,
  `ready` certifies the variant.
- **Fix (Phase 5):** variants should not advance book states (record rows
  without transitions, like `derive()` does not), or gates must refuse
  non-target aspects; re-render from `ready` with a changed hash should
  force re-gating (e.g. transition to `queued_gates`). Owner decision on
  intended `--aspect` semantics. Effort: M.

### BUG-011 — Degenerate script triggers faster-whisper model download before failing
- **Severity:** S2 (unexpected multi-hundred-MB network download + minutes
  of compute before a deterministic, fail-fast-able error). Confidence:
  Confirmed.
- **Evidence:** `align_words` (`align.py:500-533`): `tokens =
  _script_tokens(script_path)` (`align.py:519`); empty tokens → falls to
  `transcribe()` → `WhisperModel(cfg["model"])` with default `"medium"`
  (`align.py:126-160`), which downloads when uncached — and only afterwards
  does `retime_beats` raise `AlignError("beat … has an empty line")`
  (`align.py:457-498`). Reachable: `new` accepts a punctuation-only script
  (`to_beats` splits "... !!!" into beats; `script.py:37-84`), `audio`
  normalizes to `""`, tokens empty. `_do_align` (`cli.py:264-330`) performs
  no token-emptiness check before calling `align_words`. Also contradicts
  the module docstring: "fetch_model is the ONLY function in this module
  allowed to touch the network" (`align.py:18-22`).
- **Why it matters:** fail-closed is right, but the failure should precede
  the download. On a metered/offline box this is a hang, not just slowness.
- **Fix (Phase 5):** in `_do_align`, fail fast with `AlignError` when the
  normalized script yields no tokens, before `align_words`. Test: feed a
  punctuation-only script with `socket.socket` bombed (the
  test_book3.py pattern) → assert AlignError, no network. Effort: XS.

### BUG-012 — `kit new`: uncaught float() in kit adaptation; seed/bump races
- **Severity:** S3 (tracebacks instead of clean errors; races need
  concurrency to trigger). Confidence: Confirmed.
- **Evidence:** `kit_new` (`cli.py:373-390`) calls
  `kits_mod._adapt_cerebratico(raw)` OUTSIDE the try/except that guards
  `seed()`; `_adapt_cerebratico` does unguarded `float(…)` on six fields
  (`kits.py:100-165`, e.g. `float(gen.get("max_clip_s", …))`) — a
  non-numeric string (or explicit null) raises ValueError/TypeError as a
  raw traceback instead of `error: …`. `seed`'s exists-check→INSERT
  (`kits.py:68-82`) and `bump`'s max+1 (`kits.py:85-103`) are check-then-act
  without a transaction: concurrent duplicate seeds/bumps → unhandled
  `sqlite3.IntegrityError`.
- **Fix (Phase 5):** validate numerics in `_adapt_cerebratico` (raise
  ValueError with field name; move the call inside the try); or rely on the
  PK and translate IntegrityError → "kit already exists". Effort: XS.

### BUG-013 — Failed `attach` leaves orphan file in `work/assets/`
- **Severity:** S3 (disk litter; no manifest entry, so later steps can't
  see it — but repeated failed attaches accumulate bytes). Confidence:
  Confirmed.
- **Evidence:** `attach_asset` (`manifests.py:230-280`) intakes the file
  into `work/assets/<name>` FIRST (`_util.intake_asset`, ~line 250), THEN
  probes: ffprobe video probe, audio fallback, else `raise video_err`
  (MediaError). On probe failure the intaken file stays on disk with no
  manifest entry and no cleanup (the quarantine path only handles hash
  mismatch, not probe failure).
- **Fix (Phase 5):** remove the intaken file when probing fails (or probe
  before intake — but intake-then-probe preserves the TOCTOU design;
  simplest: unlink dest in the `except` path). Effort: XS.

### BUG-014 — `run_all` resolves gate function outside the try
- **Severity:** S3 (a misnamed EXTRA_GATES entry escapes as KeyError
  traceback instead of a failed gate). Confidence: Confirmed.
- **Evidence:** `run_all` (`gates.py:442-467`) docstring: "A gate that
  raises is a failed gate." But `fn = globals()["gate_" + name]` sits at
  `gates.py:452`, OUTSIDE the `try:` — a name in EXTRA_GATES without a
  matching `gate_<name>` function raises KeyError out of `run_all`
  entirely (CLI: traceback; worker: `fail()`). The lookup belongs inside
  the try.
- **Fix (Phase 5):** move the `globals()[…]` line inside the try. Test:
  append a bogus EXTRA_GATES name → assert a failed gate row, no raise.
  Effort: XS.

### BUG-015 — `_load_edl` never schema-validates render.json
- **Severity:** S3 (hand-edited/corrupt-but-JSON-valid EDLs fail deep with
  KeyError tracebacks instead of a clean EDLError at load). Confidence:
  Confirmed.
- **Evidence:** `_load_edl` (`cli.py:116-123`) does `json.loads` only;
  `new` validates at build (`cli.py:451`), but `attach`/`audio`/`render`/
  `gates`/worker handlers all load without validation. A JSON-valid but
  schema-invalid file (e.g. beats missing `t_in`, missing `captions`)
  then fails deep: `_do_align` `edl["captions"]` KeyError (`cli.py:311`),
  `video_chain` `b["t_out"]` KeyError (`render.py:149`), etc. — raw
  tracebacks in the CLI, `fail()` in the worker (inconsistent loudness).
- **Fix (Phase 5):** call `edl_mod.validate()` in `_load_edl` and `_die`
  cleanly on EDLError. Test: corrupt render.json → clean `error:` exit.
  Effort: XS.
