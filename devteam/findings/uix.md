# UIX findings — Operator UX (Phase 3, read-only)

Lane prefix: UIX · ID range UIX-550–599 · all NEW unless noted.
Severity: S0–S4 per Playbook B7 (UX issues are S3/S4 unless UX actively causes
data loss or unrecoverable states — UIX-552 is the one S2).
Confidence: Confirmed = unambiguous code with cited lines, verified on the
Threadripper 2026-09-29 against branch devteam/review-2026-09-29.
Companion notes: `devteam/notes/ux.md` (per-command consistency + recovery-story assessment).

## Index

| ID | Sev | Conf | Status | Title | Location |
|---|---|---|---|---|---|
| UIX-550 | S3 | Confirmed | NEW | `migrate` help promises "apply pending migrations" but only lists | cli.py:348-361 |
| UIX-551 | S3 | Confirmed | NEW | No job status/list command — wedged-job diagnosis is SQL-only | (CLI surface) |
| UIX-552 | S2 | Confirmed | NEW | Failed-job recovery is SQL-only: poison listed, no retry command | cli.py:820-830 |
| UIX-553 | S3 | Confirmed | NEW | `pitch`/`consent`/`invite` use op-arg pseudo-subcommands, not groups | book3cli.py:165,243,291 |
| UIX-554 | S4 | Confirmed | NEW | `consent grant` required fields unenforced by click (runtime discovery) | book3cli.py:183-190 |
| UIX-555 | S4 | Confirmed | NEW | Operator identity spelled three ways: --by / --actor / --granted-by | b2cli.py, book3cli.py |
| UIX-556 | S4 | Confirmed | NEW | Inconsistent empty-set exit semantics (moments/tray exit 1, others 0) | b2cli.py:232-243,290-303 |
| UIX-557 | S4 | Confirmed | NEW | `consent check` negative answer exits 1 as "error:" | book3cli.py:234 |
| UIX-558 | S3 | Confirmed | NEW | No progress reporting on long ops (audio download, render, carousel) | align.py:159-176 |
| UIX-559 | S3 | Confirmed | NEW | "run fetch_model first" names a function with no CLI entry point | align.py:159,182 |
| UIX-560 | S3 | Confirmed | NEW | `campaign refresh-budget` throws raw TypeError traceback (ARC-301 UX) | b2cli.py:138-145 |
| UIX-561 | S4 | Confirmed | NEW | `watch` Ctrl-C → traceback; `work` catches KeyboardInterrupt | b2cli.py:212-229 |
| UIX-562 | S4 | Confirmed | NEW | Unguarded file/JSON reads in command bodies → tracebacks | book3cli.py:104 |
| UIX-563 | S3 | Confirmed | NEW | Destructive commands lack confirmations/backups (promote-weights et al) | attribution.py:216-244 |
| UIX-564 | S4 | Confirmed | NEW | `new --help` gaps: --max-s/--script/--aspect/--title lack help text | cli.py:394-401 |
| UIX-565 | S4 | Confirmed | NEW | Job id positional in some commands, --job option in others | cli.py, book3cli.py |
| UIX-566 | S3 | Confirmed | NEW | `audio` help promises low-confidence routing BUG-004 proves dead | cli.py:562-567,321 |
| UIX-567 | S4 | Confirmed | NEW | `consent export` default writes consent_ledger.csv to CWD silently | book3cli.py:206 |
| UIX-568 | S4 | Confirmed | NEW | HYPELAB_HOME documented but ignored; code reads HYPELAB_ROOT | README.md:16, cli.py:87 |
| UIX-569 | S3 | Confirmed | NEW | "hash unchanged, skipping" masks BUG-002 wedge as benign success | cli.py:725-729 |
| UIX-570 | S4 | Confirmed | NEW | Hardcoded operator defaults in help (--actor dino, --kit cerebratico) | book3cli.py:77,99 |

## Entries

### UIX-550 — `migrate` help promises "Apply pending migrations" but only lists
- **Severity:** S3. **Location:** `hypelab/cli.py:348-361`.
- **Evidence:** Docstring "Apply pending migrations and print applied versions."
  The body only SELECTs `schema_migrations` and prints rows (`cli.py:350-361`);
  it never calls `db.migrate()`. Migrations are actually applied by
  `db.connect()` on every connect (`hypelab/db.py:104-131`).
- **What's wrong:** The command's own help advertises an action it doesn't
  perform; an operator debugging a half-migrated DB runs `migrate` expecting
  it to fix things and it changes nothing.
- **Impact:** Misdirects schema troubleshooting; the "apply" half is fiction.
- **Suggested fix:** Change the docstring to "Print applied migrations
  (pending ones are applied automatically at connect)" — or make the command
  actually run `db.migrate()` and report what it applied.

### UIX-551 — No job status/list command; wedged-job diagnosis is SQL-only
- **Severity:** S3. **Location:** CLI surface (verified via live `--help`:
  29 commands, none lists jobs).
- **Evidence:** `campaign list/show`, `source list`, `review` (bare) and
  `costs` cover campaigns/sources/clips/ledger — but the job
  (`state/lease_owner/lease_expires/attempts/error`) has no read command.
  BUG-002/003 recovery is documented as raw SQL only
  (`devteam/findings/bug.md` BUG-002/003).
- **What's wrong:** The operator's primary object is invisible; the exact
  states the S1 bugs wedge jobs into (`aligning`/`rendering`/`gating` with
  NULL leases) can only be seen via sqlite3.
- **Impact:** Every BUG-001–003 incident requires dropping out of the CLI
  into SQL. Highest-leverage operability gap in the review.
- **Suggested fix:** Add a read-only `hypelab jobs` (state/lease/attempts
  table) and `hypelab show <job>` (state history + error). Phase 5.

### UIX-552 — Failed-job recovery is SQL-only: poison listed, no retry command
- **Severity:** S2 (UX leaves jobs in a state with no CLI exit — the
  unrecoverable-state clause). **Location:** `hypelab/cli.py:820-830`
  (`_print_poison`), `hypelab/queue.py:172-204`, `hypelab/jobs.py:44`.
- **Evidence:** `work` prints `poison review (state=failed):` rows with
  attempts and error snippet — then offers no remediation. `failed → draft`
  is a legal transition (`jobs.py:44`) but no CLI command performs it (no
  `"draft"` in any CLI module). `queue.fail()`'s docstring promises a
  re-queue the work loop never performs (BUG-007). `release()` — the only
  re-queue primitive — has zero production callers.
- **What's wrong:** Diagnosis without remediation. A transient failure
  (ffmpeg OOM) parks the job in `failed` permanently from the operator's
  perspective; only SQL moves it.
- **Impact:** Failed jobs accumulate with no operator path back to work.
- **Suggested fix:** Owner decision first (Q-002): either a `hypelab retry
  <job>` command (`failed → draft` / re-queue) or documented auto-requeue
  below MAX_ATTEMPTS plus docstring correction.

### UIX-553 — `pitch`/`consent`/`invite` use op-arg pseudo-subcommands, not groups
- **Severity:** S3. **Location:** `hypelab/book3cli.py:165` (`consent`),
  `:243` (`pitch`), `:291` (`invite`).
- **Evidence:** Each takes a positional `op` Choice arg (`grant|revoke|check|
  export`, `new|list|outcome|tripwire`, `add|poll`) with all ops' options
  declared on one function. `hypelab consent --help` dumps 14 options for 4
  ops in a single list with no per-op grouping. Book 2's `campaign`/`source`/
  `review` are real click groups with per-op `--help`.
- **What's wrong:** Two subcommand idioms in one CLI; the Book 3 idiom is
  undiscoverable (you can't ask "what does `consent grant` need?").
- **Impact:** Higher learning curve; option/requirement discovery is trial
  and error.
- **Suggested fix:** Convert to click groups mirroring `campaign`/`source`.

### UIX-554 — `consent grant` required fields unenforced by click
- **Severity:** S4. **Location:** `hypelab/book3cli.py:183-190`.
- **Evidence:** The grant path loops over 7 (name, value) pairs and `_die`s
  on the first missing one (`consent grant needs --job`, then `--handle`,
  …). None is `required=True` in click, so the operator discovers them one
  error at a time. Same runtime-check pattern in `pitch` (`:256-258,
  :266-268`) and `invite` (`:296-297`).
- **What's wrong:** Click can validate this declaratively; hand-rolled
  loops give worse errors (one at a time, after DB connect).
- **Impact:** Minor friction on the most paperwork-heavy command.
- **Suggested fix:** Mark per-op required options with `required=True`
  (natural once UIX-553 converts these to groups).

### UIX-555 — Operator identity spelled three ways
- **Severity:** S4. **Location:** `hypelab/b2cli.py:117,132,367,435,314`
  (`--by`); `hypelab/book3cli.py:77,188` (`--actor`); `hypelab/b2cli.py:183`
  (`--granted-by`).
- **Evidence:** `--by` (campaign bump-rules/refresh-budget, review resolve,
  promote-weights, posted), `--actor` (authorize, consent grant/revoke),
  `--granted-by` (source clearance) — all record "which human did this".
- **What's wrong:** One concept, three flags; muscle memory doesn't transfer.
- **Impact:** Cosmetic, but it's the provenance field — the one the audit
  trail depends on.
- **Suggested fix:** Standardize on one spelling (recommend `--by`, the
  majority) with the others as deprecated aliases.

### UIX-556 — Inconsistent empty-set exit semantics
- **Severity:** S4. **Location:** `hypelab/b2cli.py:232-243` (`moments`),
  `:290-303` (`tray`).
- **Evidence:** `moments` with no moments → `_die` (exit 1);
  `tray` with no tray jobs → `_die` (exit 1). But `measure` prints "no open
  posts" (exit 0), `costs` prints "no cost rows recorded" (exit 0),
  `review` prints "no clips awaiting review" (exit 0), `campaign list`
  prints nothing (exit 0).
- **What's wrong:** "Nothing to show" is sometimes an error, sometimes not.
  Scripts can't rely on exit codes uniformly.
- **Impact:** Minor; pick one convention (recommend exit 0 + message, the
  majority).
- **Suggested fix:** Make `moments`/`tray` print the friendly line and exit 0.

### UIX-557 — `consent check` negative answer exits 1 as "error:"
- **Severity:** S4. **Location:** `hypelab/book3cli.py:234`.
- **Evidence:** No valid consent → `_die("NO valid consent (granted,
  unrevoked, unexpired) on file")` → `error: …` on stderr, exit 1 —
  identical presentation to a DB failure.
- **What's wrong:** A valid query answer ("no") is presented as a failure;
  a script can't distinguish "checked, answer is no" from "check broke".
- **Impact:** Minor; matters for `check && publish`-style scripting.
- **Suggested fix:** Keep exit 1 (grep-like convention) but print without
  the `error:` prefix, or exit 0 with `NO` on stdout (Q-003).

### UIX-558 — No progress reporting on long operations
- **Severity:** S3. **Location:** `hypelab/align.py:159-176`
  (`fetch_model`), `hypelab/cli.py:612-624` (`audio`), `_render_job`
  (`cli.py:657-740`), `hypelab/book3cli.py:95-124` (`carousel`).
- **Evidence:** `audio`'s wav2vec2 download relies on transformers' own
  stderr bars; hypelab prints nothing until `aligned N words (…)` at the
  end. `render` runs ffmpeg silent and prints only `rendered …` + sha256
  on completion. `carousel` runs headless Chromium silent until
  `rendered N slides …`.
- **What's wrong:** Multi-minute silent stretches; the operator can't tell
  progress from hang (notably the first-ever `audio` model download).
- **Impact:** Operators kill and restart "hung" commands, or sit blind.
- **Suggested fix:** Minimal progress lines (per-beat render ticks,
  download start/done notices, per-slide carousel ticks).

### UIX-559 — "run fetch_model first" names a function with no CLI entry point
- **Severity:** S3. **Location:** `hypelab/align.py:159` (def),
  `:182` (AlignError message).
- **Evidence:** `grep -rn fetch_model` in cli.py/b2cli.py/book3cli.py/docs →
  zero callers. The error message instructs the operator to run a Python
  function that no CLI command exposes.
- **What's wrong:** Recovery instruction is unactionable from the CLI —
  the operator must drop to a REPL and import hypelab.align.
- **Impact:** First-run `audio` failure sends the operator off-road.
- **Suggested fix:** Add `hypelab fetch-model` (or fold into `audio` with a
  clear "downloading model (one-time)…" notice), and point the error at it.

### UIX-560 — `campaign refresh-budget` throws a raw TypeError traceback
- **Severity:** S3. **Location:** `hypelab/b2cli.py:138-145`,
  `hypelab/campaigns.py:147-160` (functional root cause: ARC-301).
- **Evidence:** `refresh_budget` passes the parsed budget JSON dict as
  `seen_usd: float`; `float(dict)` raises `TypeError`, which the
  `except CampaignError` clause (`b2cli.py:144`) doesn't catch → uncaught
  traceback. Its sibling `campaign bump-rules` fails cleanly via `_die`
  (`b2cli.py:122-127`).
- **What's wrong:** Two adjacent commands present failure differently;
  one dumps an interpreter traceback on a routine operator action.
- **Impact:** Confusing and unactionable error presentation on top of the
  ARC-301 functional break (no CLI workaround exists for either command).
- **Suggested fix:** Fix the ARC-301 contract mismatch first; add a
  catch-all `except Exception → _die` at the command boundary as defense.

### UIX-561 — `watch` Ctrl-C produces a traceback; `work` handles it cleanly
- **Severity:** S4. **Location:** `hypelab/b2cli.py:212-229` vs
  `hypelab/cli.py:937-940`.
- **Evidence:** `work` wraps its loop in `except KeyboardInterrupt:
  print("worker stopping")`. `watch`'s `while True: … time.sleep(60)` has
  no such guard → KeyboardInterrupt traceback.
- **What's wrong:** Two long-running poll loops, two interrupt behaviors.
- **Impact:** Cosmetic; the traceback looks like a crash.
- **Suggested fix:** Mirror the `work` KeyboardInterrupt handling in `watch`.

### UIX-562 — Unguarded file/JSON reads in command bodies
- **Severity:** S4. **Location:** `hypelab/book3cli.py:104`
  (`carousel` spec load); `hypelab/cli.py:791` (`gates` via BUG-003).
- **Evidence:** `carousel` does
  `json.loads(Path(spec_path).read_text(encoding="utf-8"))` with no
  try/except — bad path or malformed JSON → raw `FileNotFoundError` /
  `JSONDecodeError` traceback instead of an `error:` line. (Contrast
  `kit new` at `cli.py:373-376`, which guards the same operation.)
- **What's wrong:** The codebase already has the `_die` pattern for this;
  `carousel` doesn't use it.
- **Impact:** Minor; first thing a new operator hits with a typo'd spec path.
- **Suggested fix:** Wrap in try/except → `_die`, matching `kit new`.

### UIX-563 — Destructive commands have no confirmations or backups
- **Severity:** S3. **Location:** `hypelab/attribution.py:216-244`
  (`promote_weights`); `hypelab/b2cli.py:363-379` (`review resolve`),
  `:112-125` (`campaign bump-rules`), `:435-445` (`promote-weights` CLI).
- **Evidence:** `promote_weights` overwrites `weights_v2.json` in place with
  no backup of the prior version and no confirmation; "explicit operator
  approval" is just the `--by` string. `review resolve --decision fail`
  kills a clip's compliance standing with no confirmation. No `--yes` /
  prompt exists anywhere in the CLI (grep verified). (The brief's examples
  — `kit bump`, `campaign delete` — don't exist; these are the actual
  destructive commands.)
- **What's wrong:** One typo'd candidate path instantly replaces production
  weights with no undo; the prior version isn't preserved anywhere.
- **Impact:** Operator error becomes unrecoverable data loss on the
  scoring weights (mitigated: proposals are separate files, but the live
  file has no history).
- **Suggested fix:** Version the weights file on promote (keep
  `weights_v1.json`/timestamped backup) and/or add a `--yes` confirmation
  for the destructive three.

### UIX-564 — `new --help` gaps and `--max-s` spelling
- **Severity:** S4. **Location:** `hypelab/cli.py:394-401`.
- **Evidence:** `--script`, `--aspect`, `--max-s`, `--title` have no help
  text (verified in live `new --help` output). `--max-s` is unexplained
  shorthand for max duration seconds.
- **What's wrong:** The job-creation command — the operator's first real
  command — under-documents 4 of 5 options.
- **Impact:** Minor friction at onboarding.
- **Suggested fix:** Add help strings; consider `--max-duration-s` alias.

### UIX-565 — Job id positional in some commands, `--job` option in others
- **Severity:** S4. **Location:** `hypelab/cli.py` (`shots`/`attach`/`audio`/
  `render`/`gates`/`moments` positional) vs `hypelab/book3cli.py:95,126,243`
  (`carousel`/`publish`/`pitch` `--job`).
- **Evidence:** Book 1/2 take `JOB_ID` positionally; Book 3 takes `--job`.
  `carousel` even makes it optional (creates a job if absent).
- **What's wrong:** The single most-passed value has two conventions by book.
- **Impact:** Muscle-memory friction across the pipeline walk.
- **Suggested fix:** Standardize (recommend positional everywhere, keep
  `--job` as alias where optional semantics are needed).

### UIX-566 — `audio` help promises low-confidence routing BUG-004 proves dead
- **Severity:** S3. **Location:** `hypelab/cli.py:562-567` (docstring),
  `:321` (`min_word_prob=0.0`).
- **Evidence:** "Low-confidence beats (mean word probability below the kit
  threshold) route to gate_failed with the reason — never to failed." BUG-004
  proves `flagged` is unconditionally empty: the routing cannot fire.
- **What's wrong:** Help text describes phantom behavior; an operator
  trusting it believes a quality gate exists that doesn't.
- **Impact:** False assurance on the book §10 low-confidence rule.
- **Suggested fix:** Fix the BUG-004 routing first, then keep the docstring;
  until then, correct the docstring.

### UIX-567 — `consent export` default writes to CWD silently
- **Severity:** S4. **Location:** `hypelab/book3cli.py:206`
  (`--out` default `"consent_ledger.csv"`).
- **Evidence:** Default is a relative path; the command prints
  `exported N consent row(s) -> consent_ledger.csv` but never says where
  that resolved, and overwrites without warning.
- **Impact:** Minor; surprising file appears in whatever directory the
  operator happened to be in.
- **Suggested fix:** Print the resolved absolute path; warn before overwrite.

### UIX-568 — HYPELAB_HOME documented but ignored; code reads HYPELAB_ROOT
- **Severity:** S4 (complements DOC-005, which covers the doc side).
  **Location:** `README.md:16` vs `hypelab/cli.py:87`.
- **Evidence:** `grep HYPELAB_HOME hypelab/ tests/` → zero hits. An operator
  exporting the documented variable is silently ignored and lands on
  `DEFAULT_ROOT=/home/dino/hypelab`.
- **What's wrong:** Silent ignore of a documented env var — the worst kind
  of default drift (no error, wrong DB/work dirs possible).
- **Impact:** Operator thinks they've redirected state; they haven't.
- **Suggested fix:** Canonicalize on `HYPELAB_ROOT` (code wins), fix README
  in Phase 5, and consider warning on unknown `HYPELAB_*` vars.

### UIX-569 — "hash unchanged, skipping" masks the BUG-002 wedge as success
- **Severity:** S3. **Location:** `hypelab/cli.py:725-729`.
- **Evidence:** On skip the command prints `hash unchanged, skipping` and
  returns with "the state is left untouched". When the entry state was
  `rendering` (worker/CLI drove there first), the job is now wedged:
  `rendering` ∉ `RENDER_ENTRY_STATES`, lease NULL, unclaimable (BUG-002).
- **What's wrong:** The message reads as benign idempotent success while
  the job is permanently stuck; nothing hints at the wedge.
- **Impact:** Operator sees success, moves on; the stuck job is discovered
  much later (or never) via SQL.
- **Suggested fix:** On skip from `rendering`, complete the transition to
  `rendered → queued_gates` (the output IS current — BUG-002's fix); at
  minimum, print the resulting state.

### UIX-570 — Hardcoded operator defaults presented as neutral
- **Severity:** S4. **Location:** `hypelab/book3cli.py:77`
  (`--actor` default `"dino"`), `:99` (`--kit` default `"cerebratico"`).
- **Evidence:** `--help` shows `[default: dino]` / `[default: cerebratico]`;
  `pitch.py:114-115` hardcodes brand `New Light Management` / sender `Dino`.
- **What's wrong:** Single-operator assumptions baked into the interface
  with no comment that they're personal defaults.
- **Impact:** None today (Dino is the operator); confusing for any second
  operator or future handoff.
- **Suggested fix:** Note in help text, or move to env/config defaults.
