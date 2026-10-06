# S0 — scope and source identity (checkup-hlflag-2026-09-29)

## Review type
**Change checkup** — the HYPELAB_AUTO_REQUEUE kill-switch change and its affected
callers, contracts, persistence, tests, and the work-loop workflow it gates.

## Requirement source
- Owner decision 2026-09-29 (Dino): env values 0/false/no/off disable auto-requeue
  without a code change; disabled → transient failures enter manual review.
- Queue task HL-FLAG (chief, 2026-09-29): "BLOCKED: being implemented by a separate
  worker (jobs/retry.py in flight). Do not claim." — this checkup is the QA
  verification pass on the landed implementation.

## Source identity
- Repo: /home/dino/hypelab, branch `devteam/review-2026-09-29`, HEAD `8effd32`
  ("controller: hl-cycle-13 VERIFIED (T-043 cost labels + T-044 quarantine)").
- Dirty (uncommitted, the change under review):
  - `hypelab/retry.py` (+18/−1)
  - `tests/test_failure_requeue.py` (+46)
- Frozen source digest (gate snapshot): `9ac0288959dafff5ab96a7279808c4afa558629fdec2f5841ae7e8b4c6857bbf`
  (per-file digests in initial.json).

## Review units
| Unit | Paths | Lenses |
|---|---|---|
| kill-switch-impl | hypelab/retry.py | COR, ARC, TST, DOC, REL, DAT |
| kill-switch-tests | tests/test_failure_requeue.py | COR, ARC, TST, DOC |
| work-loop-caller | hypelab/cli.py (work loop, the single production caller of handle_failure) | COR, ARC, TST, DOC |

## Exclusions
`.git` (inventory via git status separately), `__pycache__` (generated),
`devteam/checkups` (this checkup's own output). No generated/build inputs are
required for this change; the behavior is pure Python + sqlite.

## Commands (all through the gate)
1. `check-requeue-tests` — `env PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/test_failure_requeue.py -q` (36/36 expected)
2. `check-drive-atomicity` — same harness for tests/test_cli_drive_fail.py + tests/test_queue_atomicity.py (21/21 expected)
3. `check-live-behavior` — real-DB live verification script evidence/live_behavior_verify.py
   (live env flip mid-process, disabled routing reason, UNMETERED cost row,
   publish exclusion under disabled flag, empty=on, backoff curve)

## Applicability decisions
- SEC lens omitted: the change reads one process env var and routes DB rows; no
  identity/authorization/input-sink boundary is introduced or moved.
- PRF/UIX/BLD/API lenses omitted: no API surface, no UI, no build change, no
  measurable perf delta (one env dict lookup per failure routing).
