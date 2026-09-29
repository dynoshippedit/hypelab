# Owner decisions — HypeLab — 2026-09-29 (Dino, verbatim spec)

## D1 — T-011: failure-type-based requeue (DECIDED)
- Split by failure type. Auto-requeue ONLY transient failures: timeouts, rate
  limits, provider 5xx. With backoff, max 3 attempts, and log each attempt's
  cost to the ledger.
- Everything else — bad input, auth errors, refusals, failed quality gates,
  or hitting max attempts — goes to a review pile Dino clears by hand.
- NEVER auto-retry a publish job: a timeout can mean it already posted.
  Never auto-retry anything paused waiting on Dino.
- Gate: do not turn requeue on until the race-condition fix is verified.
  **Gate now OPEN — T-007 verified 2026-09-29 (controller commit 98d64c9).**

## D2 — T-013/C4: rip out the money pipeline (DECIDED)
- Pull the charge/payout routes and code OUT of the app; park the removed
  code on an archive branch (local only, no push).
- KEEP the cost ledger — that is spend tracking, not the money surface.
- Drop queued tasks that only touch the removed code (C4 cluster: T-013,
  T-017, DAT-357).
- Money comes back later through a hosted processor, not custom
  charge/payout code.

## D3 — T-019/C9: single-root config (DECIDED)
- One root var (e.g. HYPELAB_HOME) that everything derives from by default.
- Documented per-path vars kept as OPTIONAL overrides.
- Validate paths at startup and print what resolved.
- Secrets stay as their own vars (not under the root).

## D4 — T-040: outputs out of the repo (APPROVED with constraints)
- `git rm --cached` so the files stay on disk; move them to an outputs
  folder under the new root; gitignore it.
- Keep a few small samples ONLY if tests need them.
- DO NOT touch the character store (reference.png, voice.wav) — locked
  inputs, not outputs.
- Send Dino the list of what moved.
- NO history rewrite (needs a force push) — flagged; Dino decides separately.
