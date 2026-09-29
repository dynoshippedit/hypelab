# Flow 2 (BUG) — worker loop: claim → handle → transition / fail+retry+poison

Owner: BUG (Logic & Correctness) · Phase 2, Pass 3 · 2026-09-29
Scope: `hypelab/queue.py` (232), `hypelab/cli.py` work loop + handlers
(826-940), `hypelab/jobs.py` (ALLOWED graph, transition).
Method: full read of queue.py and the work loop; at each hop asked about
null/empty/huge/malicious/slow/concurrent/repeated/out-of-order inputs,
TOCTOU on lease claims, lease durations/expiry units, and failure
semantics. Verdict on TST-003 included below.

## How it works (hop by hop, with path:line)

### H0. Claim — queue.claim (queue.py:59-126)
1. Validates owner non-empty, states ⊆ CLAIMABLE (queue.py:32-39:
   `queued_align→aligning`, `queued_render→rendering`,
   `queued_gates→gating`, `queued_ingest→ingesting`,
   `queued_score→scoring`). Priority: align > gates > render >
   ingest > score (queue.py:42-49); FIFO within a state (`ORDER BY
   created_at`).
2. Per state, two atomic `UPDATE … RETURNING` steps:
   - (1) fresh queued work: `state=src AND (lease_expires IS NULL OR
     lease_expires <= now)` → sets `state=dst, lease_owner, lease_expires
     = now+LEASE_TTL_S (1800s), attempts+1` (queue.py:92-108).
   - (2) crashed-worker reclaim: `state=dst AND lease_expires IS NOT NULL
     AND lease_expires <= now` → new owner/lease, `attempts+1`
     (queue.py:110-126).
3. Time handling is sound: `util.now()` and `_lease_expires()` both emit
   UTC ISO-8601 seconds precision (util.py:29-31, queue.py:52-55), so the
   string comparisons (`<=`) order chronologically. Units consistent
   (seconds everywhere).
4. **RACE (→ BUG-005):** the outer UPDATE's WHERE is only
   `id=(SELECT …)` — it does not re-check `state=src`. Two concurrent
   `work` processes can both subselect the same queued job before either
   commits (autocommit per statement, deferred locking — db.py sets
   `isolation_level=None`, WAL, 30s busy timeout) and BOTH receive the row:
   double lease, `attempts+2`, double execution (double ffmpeg renders,
   duplicate `renders` rows, conflicting transitions). The reclaim step
   has the same shape. Fix shape: add `AND state=?` to the outer WHERE and
   treat empty RETURNING as lost race.
5. Fresh-queued jobs always have NULL lease (`jobs.transition` clears
   leases, jobs.py:114-121), so the `lease_expires <= now` disjunct in
   step (1) is dead but harmless.

### H1. Dispatch — cli.py:890-940
1. Owner defaults to `hostname:pid` (cli.py:895); `--owner` override can
   collide across workers (operator footgun — shared owner → lease
   fights; S3 note, not separately logged).
2. `queue_mod.claim(conn, owner, states=[…])`; `None` → "no claimable jobs"
   (+5s sleep unless `--once`). Poison list printed every iteration
   (`_print_poison`, cli.py:820-830) — print-only, no remediation offered.
3. Dispatch on the ACTIVE state set by claim: `aligning/_handle_align`,
   `rendering/_handle_render`, `gating/_handle_gates`,
   `ingesting/_handle_ingest`, `scoring/_handle_score`; unknown →
   RuntimeError → caught → `fail()`.
4. **CRITICAL (→ BUG-001):** `except Exception as e:` (cli.py:928) does not
   catch `SystemExit` raised by `_die` (cli.py:80-83). Every `_die` in
   handler-reachable code kills the worker WITHOUT `queue.fail()`:
   - `_render_job` missing-clip preflight (cli.py:666-669) and
     `RenderError`/`ManifestError` → `_die(f"render failed: …")`
     (cli.py:717-718);
   - `_run_gates` `_die` on missing renders/edls rows (cli.py:762-770);
   - `_get_job` / `_get_kit` / `_load_edl` `_die`s inside `_handle_*`.
   Consequence: job stuck in its active state with a dead owner's lease;
   any deterministic failure (bad clip deleted from disk, corrupt input)
   kills EVERY worker that reclaims it, every 30 min, forever — a
   worker-killing livelock. `fail()` is never called, so no error is
   recorded and attempts/poison never engage.
5. On `Exception` (non-SystemExit): `queue.fail(conn, job_id, owner, e)`
   (cli.py:928-935); `ValueError` from `fail()` (lease not held — e.g.
   lease expired and was reclaimed mid-handler) is caught and printed
   ("fail() skipped") — handled, though the job is then mid-flight under a
   new owner while the old worker stops touching it. Correct-ish.

### H2. Handlers
- `_handle_align` (cli.py:833-851): `_get_job/_get_kit/_load_edl`,
  shared `_do_align`, flagged → `gate_failed`, else
  `aligned → queued_render` (via `jobs_mod.transition` directly, no
  print). AlignError (an `Exception` subclass, align.py:42) → `fail()`.
- `_handle_render` (cli.py:854-856): `_render_job(heartbeat_owner=owner)`;
  heartbeat thread beats every 60s on a SEPARATE connection
  (cli.py:684-700) — good (never shares the render connection across
  threads); 60s interval vs 1800s lease is safe, though with short test
  leases (`HYPELAB_LEASE_SECONDS`) the first beat may never fire — the
  crash test uses kill -9 so it doesn't matter.
- `_handle_gates` (cli.py:858-864): `_run_gates` → `ready|gate_failed`.
- **Skip-path interaction (→ BUG-002):** when `_render_job`'s
  `render_mod.render` returns `skipped=True`, state is left untouched
  (cli.py:725-729). In the worker the job is in `rendering` (active, lease
  held): it sits invisible until lease expiry, then is reclaimed
  (attempts+1) and skips again — unbounded attempts, never `fail()`,
  never poison. Crash window that seeds it: kill -9 between render's DB
  commit (render.py:505-527) and the `rendered → queued_gates` transitions
  (cli.py:732-735).

### H3. fail() — queue.fail (queue.py:172-201)
1. Unknown job → ValueError; lease not held by owner → ValueError.
   `state='failed'`, error recorded, lease cleared — UNCONDITIONALLY.
   `attempts >= MAX_ATTEMPTS (3)` → `POISON|` stamp in the `job_events`
   note; otherwise the plain error.
2. **Docstring lie (→ BUG-006 / TST-003 CONFIRMED):** "below the limit the
   work loop may re-queue it while attempts remain" — false. The work loop
   (cli.py:890-940) never re-queues; `grep -rn requeue hypelab/` hits only
   this docstring; `release()` (the only re-queue primitive,
   queue.py:144-170) has ZERO production callers. `failed`'s only legal
   exit is `failed → draft` (jobs.py:44) and NO CLI command performs it
   (no `"draft"` string in cli.py/b2cli.py/book3cli.py). Failed AND poison
   jobs are recoverable only via raw SQL; `_print_poison` prints them with
   no remediation path.
3. **TOCTOU (→ BUG-005 sibling):** SELECT checks `lease_owner == owner`
   (queue.py:186-190) but the UPDATE (queue.py:196-201) is `WHERE id=?`
   only — a reclaim landing between the two statements lets a stale worker
   clobber the new owner's lease and fail a job it no longer owns. Window
   is microseconds (needs lease expiry mid-fail); rated S2/Likely.

### H4. heartbeat / release — queue.py:129-170
- `heartbeat` (129-141): owner-checked UPDATE, returns rowcount==1. Sound;
  docstring "another 30 minutes" matches `_lease_expires()`.
- `release` (144-170): owner-or-expired-lease may return an active job to
  its queued state, attempts unchanged ("expiry is not a failure").
  Correct semantics — but dead code in production (no callers). The only
  re-queue path that exists is never used.

### H5. Crash recovery (lease expiry → reclaim)
Design: claim step (2) reclaims active jobs whose lease expired, as a NEW
attempt (`attempts+1`). Coherent with "claiming is the attempt". Verified
by test_cli.py's kill -9 test (byte-identical re-render). Gaps:
- Reclaim re-runs the FULL handler (`_handle_align` re-runs the whole
  wav2vec2 alignment — expensive but idempotent; `_do_align` overwrites
  `vo.words.json` atomically and retime is deterministic).
- A job stranded by the CLI drive in an active state with NULL lease
  (`aligning`/`rendering`/`gating` after `_die` — BUG-003) is NEVER
  reclaimed: step (2) requires `lease_expires IS NOT NULL`. The recovery
  design assumes every active state carries a live-or-expired lease; the
  CLI drive violates that assumption on every failure.
- Reclaim counts attempts but a job that deterministically fails inside a
  handler via `_die` never reaches `fail()`, so poison never engages for
  the worst failure class (BUG-001).

## TST-003 verdict: CONFIRMED
`queue.fail()` (queue.py:196-201) unconditionally sets `state='failed'`;
its docstring (queue.py:172-180) claims "below the limit the work loop may
re-queue it while attempts remain." The work loop (cli.py:890-940) contains
no re-queue: on handler exception it calls only `queue_mod.fail()`. No
`requeue` symbol exists outside the docstring; `queue.release()` — the only
mechanism that could return a job to queued — has no production callers;
`failed → draft` (jobs.py:44) has no CLI exposure. A transient failure
(ffmpeg OOM) therefore parks the job in `failed` permanently (operator SQL
only), contradicting the documented "enqueue → lease → execute → retry"
flow. Logged as BUG-006 (S2: documented critical flow broken; doc
materially misleads). The product decision (auto-requeue vs operator
review) is already with the Lead in QUESTIONS.md.

## Observations
- The happy-path design is careful: atomic single-statement claims,
  priority ordering, FIFO, owner-checked heartbeats, poison stamping,
  kill -9 recovery proven by test. Every finding below is about the
  failure paths and concurrency, not the steady state.
- `SystemExit` as a control-flow mechanism (`_die`) is the root of the
  worst bug: it was designed for "CLI command fails loudly" but the worker
  reuses the same helpers, and `except Exception` cannot see it.
- The queue module is honest about its contract ("expiry is not a
  failure", "claiming is the attempt"); the CLI drive is where the
  contract breaks (NULL leases on active states, no fail() on SystemExit).

## Open questions
- Q1 (with Lead already): retry policy — auto-requeue below MAX_ATTEMPTS
  vs operator review? Note the docstring already promises re-queue; either
  implement it or correct the docstring AND provide a CLI retry command.
- Q2: should worker handlers convert ALL failures (including SystemExit
  from shared `_die` helpers) into `fail()`? Recommended default: yes —
  wrap handler dispatch in `except BaseException` (minus
  KeyboardInterrupt/SystemExit-intent?) — simplest correct: make `_die`
  raise a dedicated `CliError(Exception)` instead of SystemExit so the
  existing `except Exception` catches it everywhere, worker and CLI alike.
- Q3: two concurrent `work` processes — supported or not? If yes, fix the
  claim race (BUG-005). If no, document single-worker and add a lock /
  refuse a second worker. Recommended default: fix the race (one-line
  `AND state=?` in the outer WHERE).

## Related issues
- BUG-001 (S1): SystemExit from `_die` bypasses fail(), kills worker.
- BUG-002 (S1): render hash-skip wedges `rendering` (+ reclaim livelock).
- BUG-003 (S1): CLI drive parks jobs in active states with NULL leases.
- BUG-006 (S1): claim double-claim race; fail() TOCTOU sibling.
- BUG-007 (S2): fail() docstring re-queue promise; no retry path.
- BUG-008 (S2): CLI `gates` races worker-claimed `gating`.
- TST-003, TST-007 — confirmed here with code evidence.
