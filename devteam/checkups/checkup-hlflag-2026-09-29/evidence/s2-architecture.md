# S2 — as-is architecture / flow map (checkup-hlflag-2026-09-29)

## Entrypoint flow (worker failure path)
1. `hypelab/cli.py:982` — work loop `except Exception` around each claimed job's
   handler calls `retry_mod.handle_failure(conn, job_id, owner, e)` once per
   failure. This is the only production caller of `handle_failure`.
2. `hypelab/retry.py:227 handle_failure`:
   - reads job row (state, attempts, max_attempts);
   - `classify_failure(err)` → transient | terminal (fail closed);
   - `state in PUBLISH_STATES` → `_to_review(..., "publish-excluded:<detail>")` — line 246;
   - `state in OWNER_WAITING_STATES` → `_to_review(..., "owner-waiting:<detail>")` — line 249;
   - transient AND attempts < max_attempts → **kill-switch gate** (line 252–256):
     `auto_requeue_enabled()` true → `_requeue`; false →
     `_to_review(..., "auto-requeue-disabled:<detail>")`;
   - otherwise → `_to_review(..., "<kind>:<detail>")`.
3. `auto_requeue_enabled()` (retry.py:46) — `os.environ.get("HYPELAB_AUTO_REQUEUE", "1").strip().lower() not in ("0","false","no","off")`.
   Read live at every routing decision; no import-time caching.
4. `_requeue` — lease-predicated UPDATE (state AND lease_owner) setting the queued
   state + `requeue_not_before = now + backoff(attempt)`; audit log + one
   `UNMETERED|requeue attempt N/M` cost row; ONE explicit transaction.
5. `_to_review` — `queue.fail()` (atomic, lease-predicated) stamping
   `review_reason`; one `UNMETERED|attempt routed to review pile` cost row; ONE
   explicit transaction.

## Invariants (authoritative)
- Publish jobs and owner-waiting jobs NEVER auto-requeue, independent of the
  flag (exclusions precede the gate).
- Transient scope only: timeouts, rate limits, provider 5xx; terminal hints take
  precedence over transient hints; unrecognized → terminal (fail closed).
- Max attempts: `queue.MAX_ATTEMPTS = 3`; backoff `60 * 2^(attempt-1)` capped at
  900 s (60/120/240 verified; attempt 4 would be 480).
- Every routing decision (requeue or review) writes exactly one cost-ledger row
  for the spent attempt (`UNMETERED|...` per T-043 label scheme).
- Direct-drive failures (`hypelab/jobs.py` ~line 187) never auto-requeue by
  design (operator present) — they only use `classify_failure` for the review
  reason; the kill switch does not apply there because there is no auto-requeue
  to disable. No bypass.

## Discrepancies
None observed between intended (owner decision 2026-09-29) and implemented
architecture. See S4 for challenged leads and one docs-gap improvement.
