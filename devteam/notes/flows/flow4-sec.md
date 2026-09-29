# Flow 4 (SEC) — Book 3 publish path, consent + authorization chronology

Traced end-to-end on the review branch. All line references are to
`hypelab/` on `devteam/review-2026-09-29`.

## The publish sequence (`hypelab publish`)

Entry: `hypelab/book3cli.py:126-150`. `--live` is refused *before* any publish
logic runs:

> `book3cli.py:144-147` — `if live: _die("live publishing is Dino-gated: ...
> no live implementation exists in this build. Refusing — no live call was made.")`

`publish_job()` (`hypelab/publish/__init__.py`) then runs six ordered,
fail-closed steps:

1. **Job / media / state** (`:150-163`) — job must exist, media attached,
   state ∈ `("ready", "consent_granted", "scheduled", "dry_run")`. Note:
   nothing ever transitions a job *to* `"dry_run"` — that entry in
   `PUBLISHABLE_STATES` is unreachable (dead but harmless).
2. **Publish authorization** (`:165`) —
   `authorize_mod.require_authorization(conn, job_id, "publish")`: the latest
   `(job_id, action="publish", actor="dino")` row must exist
   (`hypelab/authorize.py:65-73`). Enforced in the module, not the CLI.
3. **Adapter capability / publicity preflight** (`:167-179`) —
   `instagram_preflight` checks the adapter can post and the content is
   public-safe.
4. **Consent re-check at publish time** (`:181-187`) —
   `gate_consent(conn, job_id, collaborators)` → `consent.gate_consent()` →
   per-collaborator `valid_for()` (`hypelab/consent.py:155-179`): the consent
   must be `granted`, `revoked_at IS NULL`, `expiry > now()`, and carry a
   non-null `artifact_hash`. Any failure raises `ConsentError` — fail closed.
5. **Adapter call** (`:206-210`) — `publisher.create_post(..., dry_run=True)`.
6. **Placement ledger** (`:213-250`) — always written: `post_placements` row
   with `dry_run=1`, `post_id=None`, `post_url="dryrun://{pid}"`, the consent
   IDs that authorized it (`consent_ids_json`), and the asset fingerprint.
   The job transitions to `published` **only** `if not dry_run` (`:241-245`) —
   unreachable in this build, kept for the Dino-gated future.

## Live-path verdict: live publishing cannot execute in this build

Defense in depth, four independent refusals:

- CLI: `--live` dies before orchestration (`book3cli.py:144-147`).
- DryRun adapter: `create_post` raises `LiveRefused` when `dry_run=False`
  (`hypelab/publish/dryrun.py:76-77`).
- Native Meta adapter: same refusal (`hypelab/publish/meta.py:54-55`).
- Postiz / Zernio / Ayrshare adapters: shared `_refuse_live()`
  (`hypelab/publish/providers.py:37-50`).

No environment variable, config flag, or alternate code path enables live
behavior; no provider-network implementation exists behind the adapters —
dry-run delegates to fixture data. **The live path is structurally absent,
not merely switched off.**

## Pitch → consent state machine (for the record)

`pitch new` requires a `pitch` authorization (`hypelab/pitch.py:101`), then
transitions `ready → pitch_sent → awaiting_consent` (`hypelab/pitch.py:141-144`).
`pitch outcome` moves the attempt and target through
`accepted → consent granted`, `declined`, `no_response`. `consent revoke`
sets `revoked_at` and knocks `scheduled` jobs back to `consent_granted`
(`hypelab/consent.py:218-244`).

Two dead transitions worth noting for future work:

- The graph allows `awaiting_consent → consent_expired`, but **nothing ever
  moves a job there** — expiry is evaluated lazily at gate time only. That is
  sound (the gate fails closed), just undocumented.
- `revoke` only knocks back jobs in `scheduled`; a job sitting in `ready` or
  `consent_granted` keeps its state, but the next publish still fails the
  re-check in step 4. Sound, same reason.

## TOCTOU note (future live path)

Step 4 (consent re-check) and step 5 (adapter call) are not in a single
transaction spanning a future external side effect. Harmless today — every
adapter refuses live — but when a real live adapter lands, the re-check must
move *inside* the commit that records the placement, or be re-verified after
the provider call returns, so a concurrent `consent revoke` between check and
post cannot slip through. Logged as a design requirement, not a finding:
there is no live side effect to race against in this build.
