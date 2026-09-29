# UIX operator-UX audit — HypeLab CLI (Phase 3, 2026-09-29)

Lane: UIX · Branch: `devteam/review-2026-09-29` · read-only audit, no fixes.
Command surface verified against live `--help` (29 top-level commands) plus source
(`hypelab/cli.py` 997 lines, `hypelab/b2cli.py` 453, `hypelab/book3cli.py` 354).

## 1. Command inventory (leaf paths)

Book 1 (`cli.py`): `migrate`, `kit new`, `new`, `shots`, `attach`, `audio`,
`render`, `gates`, `work`, `costs` — 10 top-level, 1 nested.

Book 2 (`b2cli.py`): `campaign add|list|show|bump-rules|refresh-budget` (5),
`source add|clearance|list` (3), `review` (bare list) + `review resolve` (2),
`watch`, `moments`, `cut`, `tray`, `posted`, `measure`, `worked`,
`propose-weights`, `promote-weights` — 19 leaf paths.

Book 3 (`book3cli.py`): `authorize`, `carousel`, `publish`, `feedback`,
`priors`, plus op-arg pseudo-subcommands `consent grant|revoke|check|export`,
`pitch new|list|outcome|tripwire`, `invite add|poll` — 8 top-level, 14 op paths.

## 2. Consistency notes

### 2a. Naming — subcommand style is inconsistent
- Book 1 uses flat commands (`new`, `attach`, `audio`, `render`, `gates`).
- Book 2 uses real click groups for `campaign`, `source`, `review`
  (each op is a discoverable subcommand with its own `--help`).
- Book 3 uses a single command with a positional `op` Choice arg for
  `pitch`, `consent`, `invite` (`book3cli.py:165,243,291`). Consequences:
  `hypelab consent --help` dumps all 14 options for all 4 ops in one list;
  requiredness is enforced only at runtime via `_die` loops
  (`book3cli.py:183-190`), so the operator discovers missing flags
  one error at a time. `pitch`/`invite`/`consent` should be groups like
  `campaign`/`source`/`review`.

### 2b. Option spelling
- Media input is `--vo` on `audio` (`cli.py:556`); there is no `--voice`
  anywhere, so the pair is consistent-by-absence — but `audio --help`
  never says what `--vo` stands for.
- Operator identity is spelled three ways: `--by` (`campaign bump-rules`,
  `campaign refresh-budget`, `review resolve`, `promote-weights`, `posted`),
  `--actor` (`authorize`, `consent grant`/`revoke`), `--granted-by`
  (`source clearance`). Same concept, three flags.
- `--expires` on `consent grant` is renamed to `expires_at` internally
  (`book3cli.py:186`) — the external name is fine, the help text
  ("expiry timestamp (MANDATORY for grant)") is the only thing that
  communicates the format; no format example is given.
- `--max-s` on `new` (`cli.py:398`) is terse and unexplained; no help text
  on `--script`, `--aspect`, `--title` either (`new --help` output verified).
- Job identity is positional in `shots`/`attach`/`audio`/`render`/`gates`/
  `moments`/`cut`, but `--job` option in `publish`/`carousel`/`pitch`/
  `consent`/`invite`. Mixed convention for the same concept.
- Internal renames leak: `pitch --target` → `handle`, `pitch --id` →
  `attempt_id`, `campaign bump-rules --by` → `operator` (`b2cli.py:117-119`).

### 2c. Help text quality and staleness
- `migrate`: "Apply pending migrations and print applied versions."
  (`cli.py:349`) — but it never applies anything; `db.connect()` applies
  migrations on every connect (`db.py:104-131`). The command only lists.
  The "apply" half of its own help is fiction.
- `audio`: "Low-confidence beats … route to gate_failed with the reason —
  never to failed." (`cli.py:562-567`) — BUG-004 proves the routing is
  dead code; the help promises behavior the code cannot deliver.
- `carousel`: "Render a 7-slide 1080x1350 carousel (gates run first)."
  — accurate (carousel.py:276-370 runs gates first).
- `new --help` shows `Kit id (must already be seeded).` on `--kit` but no
  help on `--script/--aspect/--max-s/--title`.
- `costs`: prints a real ledger table, but BUG-009 means it always prints
  "no cost rows recorded" in production — the help doesn't warn the
  ledger is unwired.
- README staleness (DOC-001–004 context): README walkthrough commands
  (`kit new --name`, `align`, `plan`, `show`, `publish <job> --target`)
  match none of the above; a new operator following the README cannot
  execute a single step. Not re-litigated here — see DOC findings.

### 2d. Error messages — recovery guidance vs tracebacks
Good (name the fix):
- `render` missing-clip preflight: `missing clips for beats: … (attach with
  'hypelab attach <job> <beat> <file>')` (`cli.py:674-676`).
- `shots`: prints `attach with: hypelab attach …` per beat (`cli.py:483`).
- `_load_edl`: `no EDL at … (run 'hypelab new' first)` (`cli.py:122`).
- `new` with unknown kit: `kit 'x' not found (run 'hypelab kit new' first)`
  (`cli.py:403`).
- `publish --live` refusal: explains Dino-gating, authorization row +
  credentials, "no live call was made" (`book3cli.py:141-145`). Clean,
  honest, exits 1.
- All `_die` errors: `error: …` to stderr, exit 1 — consistent across the
  three CLI modules (`cli.py:80`, `b2cli.py:41`, `book3cli.py:37`).

Bad (traceback or misleading):
- `campaign refresh-budget`: uncaught `TypeError` traceback — the
  `except CampaignError` at `b2cli.py:144` doesn't catch it (ARC-301).
  Its sibling `campaign bump-rules` fails cleanly via `_die`; two
  adjacent commands present failure differently.
- `carousel`: `json.loads(Path(spec_path).read_text())` unguarded
  (`book3cli.py:104`) — bad path/JSON → raw traceback, no `error:` line.
- `gates`: exceptions escaping `gates.run_all` → traceback, job left in
  `gating` (BUG-003 instance 3).
- `watch`: Ctrl-C → traceback; `work` catches `KeyboardInterrupt`
  (`cli.py:937-940`) but `watch` doesn't (`b2cli.py:212-229`).
- `fetch_model` absence: `AlignError("wav2vec2 model not cached; run
  fetch_model first")` (`align.py:182`) names a function with no CLI
  entry point — the operator must drop to a Python REPL. Unactionable
  recovery instruction (UIX-559).

### 2e. Dry-run output readability
`publish` dry-run is the best output in the CLI:
`DRY RUN placement … (adapter=…, provider_post_id=…)`,
`consent re-check: …`, `zero live calls made — recorded against fixtures
only` (`book3cli.py:152-156`). Unambiguous about what did and didn't happen.
`propose-weights` similarly prints `(status: proposed, NOT applied)`
(`b2cli.py:428`). `render` hash-skip prints `hash unchanged, skipping`
(`cli.py:728`) — but see §4/BUG-002: in the worker path this message
masks a wedge.

### 2f. Progress reporting on long operations
None at the hypelab level:
- `audio`: faster-whisper/wav2vec2 first download goes through
  transformers' own stderr progress bars (`align.py:159-176`); hypelab
  prints nothing until `aligned N words (…)` at the end (`cli.py:621-624`).
- `render`: ffmpeg runs silent; `_render_job` prints only `rendered …` +
  sha256 on completion (`cli.py:731-732`). No per-beat progress.
- `carousel`: Chromium screenshots silent; only `rendered N slides …`
  at the end (`book3cli.py:122-123`).
- `watch`/`work` poll loops print per-iteration lines, which is adequate.

### 2g. Destructive commands and confirmations
There is no `--yes`/confirmation prompt anywhere in the CLI (grep verified),
and the two examples in the task brief don't exist: no `kit bump`, no
`campaign delete`. The actually-destructive commands:
- `promote-weights`: overwrites `weights_v2.json` in place, no backup of
  the prior version, no confirmation (`attribution.py:216-244`; CLI
  `b2cli.py:435-445`). "Explicit operator approval" is just the `--by`
  string. A wrong candidate instantly replaces production weights.
- `review resolve --decision fail`: kills a clip's compliance standing;
  no confirmation (`b2cli.py:363-379`).
- `campaign bump-rules`: version-bumps rules deliberately; no confirmation
  (`b2cli.py:112-125`) — though it is at least currently 100% broken
  (ARC-301), so nothing is at risk today.
- `migrate`: schema-mutating but idempotent and already-applied at connect;
  low risk.
Non-destructive-by-design: `kit new` fails cleanly on duplicates
("fails cleanly if it exists", `cli.py:368`); `campaign add` → `CampaignError
"already exists"` (`campaigns.py:70`); `pitch new` state-guards
("pitch starts from 'ready'", `pitch.py:104-107`).

### 2h. Idempotency messaging
- `render` hash-skip: `hash unchanged, skipping`, state untouched —
  correct for the CLI entry states (`cli.py:725-729`).
- `audio` on `gate_failed`: re-drives `gate_failed → awaiting_media`
  explicitly (`cli.py:604-606`); messaging is the state lines.
- `carousel` has no skip: re-running with `--job` re-renders silently.

### 2i. Exit codes
Uniform: 0 success, 1 any `_die` (all call sites use the default).
Click usage errors exit 2 (framework default). No command distinguishes
"query answered negatively" from "command failed": `consent check`
with no valid consent exits 1 via `_die` (`book3cli.py:234`) — the
negative answer is presented as an error, indistinguishable from a DB
failure to a script.
Empty-set semantics are inconsistent: `moments` (`b2cli.py:232-243`) and
`tray` (`b2cli.py:290-303`) exit 1 on empty; `measure` ("no open posts"),
`costs` ("no cost rows recorded"), `review` ("no clips awaiting review"),
`campaign list` (silent) all exit 0.

### 2j. Env-var defaults (HYPELAB_HOME vs HYPELAB_ROOT)
README.md:16 documents `HYPELAB_HOME`; code reads `HYPELAB_ROOT`
(`cli.py:87`), `HYPELAB_DB`, `HYPELAB_LEASE_SECONDS` — zero hits for
`HYPELAB_HOME` in `hypelab/` or `tests/`. An operator exporting the
documented variable gets silently ignored and lands on
`DEFAULT_ROOT=/home/dino/hypelab`. Code-side default wins; README is
wrong (complements DOC-005). HYPELAB_ROOT/HYPELAB_DB/HYPELAB_LEASE_SECONDS/
HYPELAB_CHROMIUM are undocumented anywhere (DOC-024).

### 2k. Dino-specific hardcoded defaults
`--actor` defaults to `dino` (`book3cli.py:77`), `--kit` defaults to
`cerebratico` (`book3cli.py:99`), `--title` defaults to `carousel`
(`book3cli.py:99`), pitch hardcodes brand `New Light Management` /
sender `Dino` (`pitch.py:114-115`). Fine for a single-operator tool,
but the help text presents them as neutral defaults.

## 3. Recovery-story assessment (BUG-001–006 + siblings)

| Bug | What the CLI prints | Documented recovery? | Verdict |
|---|---|---|---|
| BUG-001 (`_die`→SystemExit kills worker) | `handler error on <job>: <e>` then the process dies; nothing recorded (`cli.py:928-935` vs `83`) | None — `fail()` never runs, poison never engages | Operator must notice the dead worker; job sits in active state with dead lease. No CLI recovery. |
| BUG-002 (hash-skip wedges `rendering`) | `hash unchanged, skipping` — reads as benign idempotent success | None — SQL-only (`UPDATE jobs SET state=…`) | The message actively masks the wedge; `rendering` ∉ `RENDER_ENTRY_STATES`, lease is NULL so `claim` can't reclaim. |
| BUG-003 (CLI parks NULL-lease active states) | `error: alignment failed: …` / `error: render failed: …` — names the failure, not the stranded state; `gates` escape → raw traceback | None — SQL-only | Accurate about *what* failed, silent about *where the job is now* and that no command can move it. |
| BUG-004 (low-conf gate_failed dead code) | Nothing — `flagged` always empty, no signal at all | N/A (nothing to recover; the route never fires) | The `audio` help text promises routing that cannot happen. |
| BUG-005 (gate misattributes words) | Gate table prints PASS/FAIL per gate — verdict may be wrong with no signal | None — silent misjudgment | Operator cannot distinguish a correct verdict from a shifted-span one. |
| BUG-006 (claim race) | Two workers print `claimed <job>`; no conflict signal | None | Silent duplication; loser's transitions raise `illegal transition`. |
| BUG-007 (no retry) | `work` prints `poison review (state=failed):` rows with attempts + error snippet (`cli.py:820-830`) — and stops there | None — `failed → draft` exists in `jobs.py:44` but no CLI command performs it | The poison listing is diagnosis without remediation; failed jobs are SQL-only. |
| BUG-008 (`gates` vs worker race) | Loser gets `error: illegal transition …` | None | Operator can't tell which verdict won; duplicate `gate_results` rows accumulate silently. |
| BUG-009 (`costs` unwired) | `no cost rows recorded` | N/A | Honest output, dead feature behind it. |

## 4. `status` / `show` / `list` usefulness for diagnosing wedged jobs

There is no top-level `hypelab status` or job-listing command. What exists:
- `campaign list` / `campaign show` — campaigns only, no job states.
- `source list` — sources only.
- `review` (bare) — clips in `compliance_unknown` only.
- `costs [job_id]` — cost ledger only.
- `_print_poison` inside `work` — failed jobs only, no remediation.

The most operationally important object — the job and its `state /
lease_owner / lease_expires / attempts / error` — is invisible to the CLI.
Diagnosing BUG-002/003 wedges requires raw SQL, e.g.
`SELECT id, state, lease_owner, lease_expires, attempts FROM jobs WHERE
state IN ('aligning','rendering','gating');`
A `hypelab jobs` / `hypelab show <job>` read command is the single highest-
leverage UX addition for operability.

## 5. Defaults assumed for open questions (see QUESTIONS.md Q-002–Q-004)
- Failed-job recovery: default = add a CLI `retry` command (`failed → draft`
  or re-queue), don't auto-requeue silently (Q-002).
- `consent check` negative answer: default = keep exit 1 but drop the
  `error:` prefix so scripts can distinguish answer-vs-failure (Q-003).
- Env canonical name: default = `HYPELAB_ROOT` (code wins), README corrected
  in Phase 5 (Q-004).
