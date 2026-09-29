# Authorization Matrix — HypeLab CLI (SEC review, 2026-09-29)

Enumerated programmatically from Click registration on the review branch:
**36 leaf command paths** (Book 1: 10, Book 2: 18, Book 3: 8). Multi-operation
commands (`consent`, `pitch`, `invite`) are split into one row per operation
below — 43 operation rows total. The playbook's "30 commands" figure is stale;
the matrix covers the actual surface.

Conventions: **AuthN** = authentication (none exists, by design);
**AuthZ** = explicit authorization-ledger check; **Consent** = collaborator
consent gate; **Rate** = rate limiting (none exists, by design).

## Book 1 — local media pipeline (10 leaves)

| Command path | AuthN | AuthZ | Consent | Rate | Effect |
|---|---|---|---|---|---|
| `hypelab attach` | — | — | — | — | intake file → work dir (sha256 + ffprobe) |
| `hypelab audio` | — | — | — | — | extract/normalize audio |
| `hypelab costs` | — | — | — | — | read-only cost report |
| `hypelab gates` | — | — | — | — | run media gates, record verdicts |
| `hypelab kit new` | — | — | — | — | seed a brand kit |
| `hypelab migrate` | — | — | — | — | apply schema migrations |
| `hypelab new` | — | — | — | — | create job row |
| `hypelab render` | — | — | — | — | ffmpeg render → mp4 |
| `hypelab shots` | — | — | — | — | extract thumbnails |
| `hypelab work` | — | — | — | — | claim-loop worker (self-declared `--owner`) |

## Book 2 — campaign operations (18 leaves)

| Command path | AuthN | AuthZ | Consent | Rate | Effect |
|---|---|---|---|---|---|
| `hypelab campaign add` | — | — | — | — | insert campaign row (validated) |
| `hypelab campaign bump-rules` | — | — | — | — | version campaign rules |
| `hypelab campaign list` | — | — | — | — | read-only |
| `hypelab campaign refresh-budget` | — | — | — | — | recompute budget |
| `hypelab campaign show` | — | — | — | — | read-only |
| `hypelab cut` | — | — | — | — | score moments → tray clips |
| `hypelab measure` | — | — | — | — | poll metrics (stub → `unavailable` rows) |
| `hypelab moments` | — | — | — | — | detect score moments |
| `hypelab posted` | — | — | — | — | record a *manual* upload (post_url operator-supplied) |
| `hypelab promote-weights` | — | — | — | — | promote proposed weight version |
| `hypelab propose-weights` | — | — | — | — | stage a weight proposal |
| `hypelab review resolve` | — | — | — | — | human pass/fail on `compliance_unknown` clip (records `decided_by`) |
| `hypelab source add` | — | — | — | — | register poll source (rights manifest required) |
| `hypelab source clearance` | — | — | — | — | record clearance decision |
| `hypelab source list` | — | — | — | — | read-only |
| `hypelab tray` | — | — | — | — | rank compliant clips → tray dirs |
| `hypelab watch` | — | — | — | — | poll sources (RSS/yt-dlp network) |
| `hypelab worked` | — | — | — | — | record manual outcome data |

## Book 3 — external effects (8 leaves → 15 operations)

| Operation | AuthN | AuthZ | Consent | Rate | Evidence |
|---|---|---|---|---|---|
| `authorize` (record approval) | — | — | — | — | the ceremony itself; writes `authorizations` |
| `carousel` (render carousel) | — | — | — | — | local HTML/PNG artifact |
| `consent grant` | — | — | — | — | writes `consents` (expiry mandatory, artifact hashed) |
| `consent revoke` | — | — | — | — | sets `revoked_at`; knocks `scheduled` jobs back |
| `consent check` | — | — | — | — | read-only gate evaluation |
| `consent export` | — | — | — | — | CSV dump of the ledger (SEC-104) |
| `feedback` (record outcome) | — | — | — | — | writes `what_worked` table |
| `invite add` | — | **REQUIRED** | — | — | `invites.py:43` — `require_authorization(conn, job_id, "invite")` |
| `invite poll` | — | — | — | — | read-only status poll via adapter |
| `pitch new` | — | **REQUIRED** | — | — | `pitch.py:101` — `require_authorization(conn, job_id, "pitch")` |
| `pitch list` / `outcome` / `tripwire` | — | — | — | — | read-only / outcome logging |
| `priors` (show/snapshot) | — | — | — | — | read-only + writes `priors_v<N>.json` |
| `publish` | — | **REQUIRED** | **RE-CHECKED** | — | `publish/__init__.py:165` (authz) + `:181` (`gate_consent`); `--live` refuses at `book3cli.py:144-147` |

## Coverage verdict

- **Every externally-visible effect is gated.** The three actions that reach
  other people or the public — pitch a collaborator, invite a collaborator,
  publish — each require a recorded authorization row, enforced in the
  *module* (not just the CLI), so no alternate caller can bypass it.
  Publish additionally re-checks consent immediately before the adapter call.
- **No command is missing a check the business rules require.** Internal
  operations (render, cut, tray, resolve, …) move local data through a
  single-operator pipeline; gating them would add ceremony without threat
  reduction. `review resolve` records the deciding operator by name, which is
  the appropriate control for a human judgment call.
- **AuthN / rate limiting: absent everywhere, by design.** The threat model
  records why; repeating it per row would be noise.
- **Known weaknesses in the checks that do exist** (findings, not gaps):
  authorizations never expire and cannot be revoked (SEC-102); the pitch↔grant
  scope correspondence is documented but unenforced (SEC-101); consent expiry
  accepts non-timestamp strings that never expire (SEC-100).
