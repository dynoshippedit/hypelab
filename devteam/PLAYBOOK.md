# DEVTEAM PLAYBOOK — HypeLab
Created 2026-09-29 by the Tech Lead. **This is the single source of truth for how this codebase is reviewed, recorded and fixed.** Read it in full at the start of every session and before every phase.

## B0. Session start (resume protocol)
Every session, including after a context reset or a handoff:
1. Read this Playbook in full.
2. Read `devteam/STATUS.md` for the phase, progress and next actions.
3. Read the last ~60 lines of `devteam/JOURNAL.md`.
4. Run `git status` and `git log --oneline -15`, and reconcile them with STATUS. If STATUS claims work that git doesn't show (a missing fix commit, for example), note it in the Journal and redo that step.
5. Continue from the "Next actions" in STATUS. Never redo completed work, and never skip a gate.

If you are running low on context mid-task, checkpoint first: update STATUS and the Journal and commit `devteam/`, then carry on. After a reset, steps 1–5 restore you.

Only the Tech Lead edits this Playbook, and every edit is logged in B17 with its reason.

## B1. Mission, scope and owner settings
**Mission:** leave this codebase understood, documented, correct, secure and verifiably better, with a complete written record of everything found and everything done.

**Owner settings.** The owner may edit these at any time, and the Lead re-reads them before Phase 5.

```text
PROJECT:         HypeLab — AI-assisted short-form video production pipeline (script → VO → align → render → gates → publish dry-run)
REPO VISIBILITY: public
WORK_BRANCH:     devteam/review-2026-09-29
FIX_MODE:        auto          # auto = after triage, fix everything in FIX_SCOPE
                               # approve-first = stop after Phase 4 and wait for the owner
FIX_SCOPE:       S0-S3         # severities fixed in this run; S4 (info) is never auto-fixed
REFACTOR_MODE:   propose       # propose = design the target structure only
                               # incremental = also execute approved migration steps | none
PRE-APPROVED:    bug fixes that restore intended behavior; tests and a test harness; input validation;
                 error handling; security hardening that keeps the auth model; docs fixes; env/config
                 documentation; pinning dependency/CDN versions (no major upgrades); removing dead code
                 inside a file
NEEDS APPROVAL:  deleting, renaming or moving files; changing public APIs, URLs, response shapes or
                 user-visible behavior; database schema, migration or data changes; auth model changes
                 (roles, token format, sessions); major dependency upgrades or new frameworks; CI/CD,
                 deploy or infrastructure changes; rotating secrets or rewriting git history; license
                 changes; anything irreversible
IN SCOPE:        all tracked files
OUT OF SCOPE:    dependency folders (node_modules, venv, vendor, Library, target, …), build output,
                 generated or minified files, binary assets (review whether they belong, not their
                 contents), devteam/, ai-dev-team/
```

NEEDS APPROVAL items are never done silently. Log them with status `NEEDS-OWNER` and a question in QUESTIONS.md, then continue with everything else.

## B2. Prime directives (non-negotiable)
1. **The Playbook is law.** When in doubt, re-read it. If it's wrong or incomplete, the Lead amends it and logs the change in B17. Nobody improvises around it.
2. **Log now, fix later.** In Phases 1–4, source code is read-only. Every problem, from a typo to a critical hole, goes into the ledger the moment you see it, and then you keep reviewing. Fixing happens in Phase 5, when you have full context and priorities. During review you may: write in `devteam/`, install dependencies, run the app, tests, linters and scanners, and write repro scripts in `devteam/repro/`. After any setup step, `git status` must show changes only under `devteam/`; the only exception is the boot-time pointer in `CLAUDE.md`/`AGENTS.md`. Revert anything else and log why.
3. **Evidence or it didn't happen.** Every finding cites `path:line` and quotes the code. Every "works", "fixed" or "passes" cites the command and its actual output. Never invent file names, functions, line numbers or results. If you haven't opened it, you don't know it.
4. **Write it down immediately.** Your memory does not survive; files do. Notes, findings, status and decisions go into `devteam/` as you work, never "at the end".
5. **Reviewed means read.** A file counts as reviewed only when every line was read through its required lenses and COVERAGE.md records the ranges. Skimming is not reviewing.
6. **Root cause, then siblings.** For every bug, keep asking "why" until you reach the cause. Then search the whole repo for the same pattern and record every instance in the same issue.
7. **Smallest safe change.** Fixes are minimal, match the surrounding style, and are never mixed with unrelated edits.
8. **Tests prove fixes.** Reproduce the problem first (failing test or repro script), fix it, then show the test passing along with the full suite. Never delete, skip or weaken a test to get green.
9. **Protect the owner.** Never write a secret value anywhere; redact it as `[REDACTED: <kind> at path:line]`. No force-pushes, history rewrites or destructive commands. No NEEDS APPROVAL action without approval. In a public repo, describe security findings as what, where, impact and fix, with no step-by-step exploit instructions.
10. **Calibrated honesty.** Label your confidence. Rather than guess, say "unknown" and log a question. The final report states what was not reviewed or not verified.
11. **Don't block on the owner.** Log the question with your recommended default, proceed on that default and keep going. Only irreversible or NEEDS APPROVAL actions wait for an answer.
12. **Understand intent before judging.** Read comments, docs and history (`git log -L`, `git blame`) to learn why code is the way it is before calling it wrong.

**Engineering standards: how the best developer thinks**
- Review wearing four hats:
  - **The attacker:** how do I break or abuse this?
  - **The new user:** can I succeed without guessing?
  - **The maintainer a year from now:** can I understand and change this safely?
  - **The operator paged at 3 a.m.:** what fails, and will I know why?
- Prefer boring, proven solutions and the conventions of this stack and this codebase over cleverness.
- Be specific. Write "Password reset tokens are stored unhashed in the User model (`models/user.js:41`)", never "security could be improved".
- Every note should leave the next developer knowing more than you did when you started.

## B3. Project profile
Filled in at boot from recon plus the matching Appendix P profile, and kept current as the map grows. Mark unverified items `(unverified)`.

```text
Project:             HypeLab — CLI pipeline for AI-assisted short-form video production (Books 1-3: foundation, clip mine, hype layer)
Stack:               Python 3, SQLite (hypelab.db), ffmpeg, faster_whisper (local), edge-tts; unittest/pytest
Entry points:        python3 -m hypelab.cli (hypelab/cli.py)
Install:             no manifest found (no pyproject.toml/setup.py/requirements*.txt) (unverified)
Run:                 python3 -m hypelab.cli <cmd> — new, attach, align, plan, render, gates, publish, kit, shots, show, work, doctor; HYPELAB_HOME=/home/dino/hypelab  verified: no
Test:                PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/ — 191 passing reported 2026-09-28 (to reproduce); README also says: python3 -m unittest discover -s tests -v  verified: no
Lint / typecheck:    none found (unverified)
Config & env:        HYPELAB_HOME (default: repo dir); no .env template, no CI/CD, no Docker found (unverified)
Data stores:         SQLite via migrations/0001-0003 (+ state_migrations.py); jobs/<job>/ asset dirs on disk
External services:   edge-tts (VO fixture gen), faster_whisper (local align); publish adapters are stubs (dry-run only, NotImplementedError)
Deployment:          local CLI on Threadripper; no CI/CD, no Docker, no deploy config found (unverified)
Crown jewels:        consent/publish gate (never publish for real without consent); job queue integrity (leases, retries, crash recovery); render determinism + EDL validation; quality gates; SQLite data integrity
Critical flows:      (1) new → attach → align → plan → render → gates → asset_ready; (2) publish <job> → consent gate → dry-run (REFUSED paths); (3) kit new → appearance lock; (4) queue worker: enqueue → lease → execute → retry
Active specialists:  STR (ffmpeg transcoding/rendering of untrusted clips); AIX/GAM/W3B/MUS NOT activated — no LLM API SDKs, game engine, contracts, or music-rights code found (Cartographer to confirm)
Known leads:         none (P4 profile: built from scratch in Phases 0-1; no pre-scan leads exist for this repo)
Excluded paths:      hypelab/__pycache__/, tests/__pycache__/, .pytest_cache/, hypelab.db* (untracked local runtime state) — review whether they belong, not their contents
```

## B4. How we go through the code (traversal protocol)
There are seven passes, done in order; the order is what guarantees nothing is missed. Before each pass, re-read the checklists that apply to it.

**Pass 1: Orientation (breadth).** List every tracked file (`git ls-files`) in COVERAGE.md with its line count, language and a one-line purpose. Build MAP.md with an annotated directory tree, the entry points and processes, a module dependency sketch, the data stores, the external services, and the config and env.

**Pass 2: Risk ranking.** Tag every file with a tier:
- **High:** authentication and authorization; money, royalties, payments or a game economy; persistence and migrations; anything that parses external input (HTTP, uploads, files, save data, network messages, chain events, LLM output); crypto and keys; smart contracts; the core game loop; shell or filesystem access; any file over 500 lines.
- **Medium:** business logic, integrations, UI that renders external data, background jobs, configuration.
- **Low:** constants, styles, static content, fixtures, docs.

Then set the crown jewels and critical flows in B3. In COVERAGE, mark every lens cell a file's tier doesn't require as `n/a`. The `[ ]` cells left over are the review work list.

**Pass 3: Critical-flow tracing (depth-first).** For each critical flow, follow execution from trigger to final effect and back: UI event, route or input → handler → service → data store or external call → response or render. Record every hop with `path:line` in `notes/flows/<flow>.md`. At every hop, ask:
- What if this value is null, empty, huge, malicious, slow, concurrent, repeated or out of order?
- Who is allowed to do this, and where exactly is that enforced?
- What happens when it fails?

**Pass 4: Full sweep, file by file.** Do the High tier first, then Medium, then Low. Read each file completely, top to bottom, in chunks of about 400 lines at most, and record the ranges in COVERAGE.md as you go. For a big file, first extract an outline (functions, classes, routes, exports) so you know its shape, then read every chunk. Apply the lenses the file's tier requires (see the table below), and log each finding the moment you see it.
- In multi-agent mode, each lane sweeps its own lens across its assigned files.
- In single-agent mode, give High-tier files a separate pass per lens, because focus beats breadth. For Medium and Low files, one combined pass with the checklists at hand is acceptable.

**Pass 5: Pattern sweeps (whole repo).** Run the Pattern Pack (B6) for the detected stack and inspect every hit. A true positive becomes one issue per pattern, listing all instances. Note each false positive once in `notes/sweeps.md` so nobody inspects it again.

**Pass 6: Cross-cutting audits.**
- **Config/env inventory.** Compare every variable the code reads with every variable that is documented or templated. A security-relevant variable that is read but undocumented is high severity.
- **Dependencies.** Look for unused, missing, duplicated, outdated, vulnerable or license-problematic packages, multiple manifests, lockfile drift, and native build prerequisites.
- **Dead code and duplicates.** Look for unused files, functions and exports, commented-out blocks, multiple versions of the same file or server, and duplicate or shadowed definitions.
- **Docs claims audit.** Check every factual claim in the docs against the code (B9.10).
- **Consistency.** Check naming, error shapes, API conventions, logging and config access.

**Pass 7: Tool-assisted verification.** Run whatever already exists, or can be added without touching tracked files:
- build, tests, linters and type checkers;
- a dependency audit (`npm audit`, `pip-audit`, `cargo audit`, …);
- a secret scan: gitleaks or trufflehog if available, otherwise the B6 secret patterns, including over `git log -p`;
- static analyzers (for example Slither for Solidity);
- a live smoke run: start the app, then hit its key endpoints or load its key screens and scenes.

Record every command and its result in BASELINE.md or the notes. Every real problem goes into the ledger.

**Coverage requirement** (must be met before Phase 4):

| Tier | Required |
|---|---|
| High | Every applicable lens, every line |
| Medium | Correctness, Security and Architecture, plus the Frontend, Data and Domain lenses where they apply; every line |
| Low | Correctness, every line (can be quick) |

If the budget runs out, finish High, then Medium, then Low. Mark everything left as `NOT REVIEWED` in COVERAGE and in the report. Never pretend.

## B5. How we look at code (the lenses)

| Lens | Code | Checklist lives in | Core question |
|---|---|---|---|
| Correctness | COR | Logic & Correctness Reviewer (B9.4) | Does it do what it's supposed to, on every path? |
| Security | SEC | Security Auditor (B9.5) | How can it be abused, and what stops that? |
| Performance & reliability | PRF | Performance & Reliability Engineer (B9.6) | Will it stay fast and up under load, failure and time? |
| Architecture | ARC | Architect (B9.3) | Is it structured so it can be understood and changed safely? |
| Tests | TST | Test Engineer (B9.7) | What is actually proven, and what isn't? |
| Frontend / UX / a11y | UIX | Frontend, UX & Accessibility Reviewer (B9.8) | Can every user succeed, safely and accessibly? |
| Data & integrations | DAT | Data & Integrations Specialist (B9.9) | Is data correct, consistent and safely moved? |
| Docs & product | DOC | Product & Docs Auditor (B9.10) | Does it do what it says it does? |
| Build & config | BLD | Build & Release Engineer (B9.2) | Does it install, run and deploy reproducibly? |
| Domain | DOM | Domain specialists (B9.11) | Stack-specific risks: game, web3, streaming, AI, music rights |

A lens pass on a file is complete only when every item on that lens's checklist has been considered for that file.

## B6. Pattern pack (grep sweeps)
Use `rg -n` (or `grep -rnE`), excluding dependency and build folders, `devteam/` and `ai-dev-team/`. These patterns are starting points, and every hit needs a careful look.

**Universal**
- **Secrets:**
  - Assignments: `(?i)(api[_-]?key|secret|passw(or)?d|token|private[_-]?key|client[_-]?secret)\s*[:=]`
  - Known key formats: `sk-[A-Za-z0-9_-]{20,}`, `AKIA[0-9A-Z]{16}`, `gh[pousr]_[A-Za-z0-9]{36}`, `xox[baprs]-`, `-----BEGIN [A-Z ]*PRIVATE KEY-----`
  - Fallback defaults next to secret names: `\|\|\s*['"][^'"]{6,}['"]`
  - History: `git log -p --all -S '<high-value pattern>'`
- **Code execution:** `eval\(` · `new Function\(` · `child_process` · `\bexec(Sync)?\(` · `spawn\(.*shell:\s*true` · `os\.system` · `subprocess\..*shell=True` · `pickle\.loads` · `yaml\.load\(`
- **Injection sinks:**
  - HTML: `innerHTML|outerHTML|insertAdjacentHTML|document\.write|dangerouslySetInnerHTML|v-html`
  - Raw queries (`\.query\(|\.raw\(|execute\(`) built with `+`, `${`, `%s` or f-strings
  - File access (`sendFile\(|readFile\w*\(|createReadStream\(|path\.join\(`) or `redirect\(` fed by request data
- **Weak crypto or randomness:** `Math\.random` in security contexts · `md5|sha1` · `createCipher\(` · `jwt\.decode\(` used as verification · `algorithms?.*none`
- **Swallowed errors:** `catch\s*(\(\w*\))?\s*\{\s*\}` · `\.catch\(\s*\(\)\s*=>\s*\{?\s*\}?\s*\)` · `except:\s*$` · `except Exception:\s*pass`
- **Markers and leftovers:** `TODO|FIXME|HACK|XXX|WORKAROUND` · `console\.(log|debug)|debugger;|print\(|var_dump`
- **Hardcoded environment:** `localhost|127\.0\.0\.1|0\.0\.0\.0` · `http://` · `/Users/|/home/|C:\\`
- **Duplicate definitions:** extract every route registration (`(app|router)\.(get|post|put|patch|delete)\(`) as method + path, skipping commented lines, and report any route registered twice. The first registration wins; the rest are dead code. Do the same for duplicate function names within one module.

**JavaScript / TypeScript**
- **Risky logic:** `[^=!]==[^=]|!=[^=]` (loose equality) · `forEach\(async` · `new Promise\(async` · `\.then\(` without `.catch` · `setInterval\(` (is it cleared?) · `JSON\.parse\(` without try · `parseInt\([^,)]+\)` (no radix)
- **Server:** `(read|write|append)FileSync|execSync` inside request handlers · `cors\(\s*\)|origin:\s*(true|['"]\*['"])` · `express\.json\(\{\s*limit` · `trust proxy`
- **Type and lint escapes:** `: any\b|as any|@ts-ignore|@ts-expect-error|eslint-disable`
- **Frontend:** `localStorage\.(set|get)Item\(.*[Tt]oken` · `<script[^>]+src=` without `integrity=` · CDN URLs without an exact version (`unpkg\.com|cdn\.jsdelivr\.net`) · `text/babel` · `cdn\.tailwindcss\.com`

**Python**
`except:` · `assert` used for validation · mutable default arguments `def \w+\(.*=\s*(\[\]|\{\})` · `verify=False` · `DEBUG\s*=\s*True` · SQL built with f-strings or `%`

**Solidity / web3**
`tx\.origin` · `delegatecall` · `selfdestruct` · `block\.(timestamp|number|prevrandao|difficulty)` used for randomness · `\.call\{value:` · `unchecked\s*\{` · `ecrecover` · `approve\(` · `function initialize` without `initializer` · `for\s*\(.*\.length` over growable arrays · keys or mnemonics anywhere: `(?i)mnemonic|seed phrase|PRIVATE_KEY`

**Games**
- **Unity C#:** inside `Update|FixedUpdate|LateUpdate`, look for `new `, `GetComponent`, `Find`, `FindObjectOfType`, `Instantiate`, string concatenation and LINQ. Also check `PlayerPrefs` used for saves, `Time\.deltaTime` inside `FixedUpdate`, and `Resources\.Load`.
- **Godot:** inside `_process|_physics_process`, look for `get_node`, `$`, `load\(`, `instantiate\(` and `new\(`.
- **JS/TS engines:** allocations inside `update\(` or `requestAnimationFrame` loops.
- **Economy:** money, balance, debt or price values stored as floats: `(?i)(money|cash|balance|debt|price|gold|coins)\b.*\d+\.\d+`

**Rust / Go**
- **Rust:** `unwrap\(\)|expect\(|unsafe` outside tests.
- **Go:** `_ = ` on errors, `panic\(`.

## B7. Severity, confidence, status, effort and IDs

**Severity** is impact × likelihood. When torn between two levels, pick the higher one and say why; the Verifier calibrates in Phase 4.
- **S0 Critical:** exploitable security hole (auth bypass, secret exposure, injection or RCE, cross-user or cross-tenant data access); data loss or corruption; wrong money or economy math that affects users; a core flow that crashes or is unusable; legal exposure. Fixed first.
- **S1 High:** a core feature broken in common cases; a security weakness that needs conditions; a data-integrity risk; a serious performance or reliability problem on a hot path; a project that won't install, build or run from a clean clone.
- **S2 Medium:** wrong behavior in edge cases; missing validation or error handling; maintainability problems that are actively causing bugs; moderate performance issues; docs that materially mislead.
- **S3 Low:** minor bugs, inconsistencies, code smells, small docs errors, repo hygiene.
- **S4 Info:** observations and suggestions that aren't defects. Feature ideas go to IDEAS.md instead.

**Confidence**
- **Confirmed:** reproduced by running it, or proven by unambiguous code with cited lines and no assumptions left.
- **Likely:** strong evidence with one unverified assumption (state it).
- **Suspected:** needs investigation (state what would confirm or refute it).

Only Confirmed issues get fixed. Likely and Suspected issues are confirmed first, in Phase 4 or in step 4 of the fix loop.

**Status lifecycle:** `NEW → CONFIRMED → IN-PROGRESS → FIXED → VERIFIED`

Side exits:
- `REJECTED`: false positive (give the reason).
- `DUPLICATE`: points to another ID.
- `WONTFIX`: give the reason.
- `DEFERRED`: outside this run's scope (give the reason).
- `NEEDS-OWNER`: waiting on a question (give the Q-ID).
- `REOPENED`: failed verification; goes back to IN-PROGRESS.

**Effort:** XS < 15 min · S < 1 h · M < ½ day · L ≤ 2 days · XL must be broken down.

**IDs** take the form `<PREFIX>-<NNN>`, one sequence per lane (SEC-001, BUG-014, …). Parallel agents that share a prefix get separate ranges, such as BUG-001–099 and BUG-100–199. IDs are never reused or renumbered.

## B8. The ledger protocol: log now, fix later
- The moment you notice something wrong, stop reading, write the entry (Part C template, section C6), then continue where you left off.
- One problem per entry. All instances of the same pattern go in the same entry (sibling search).
- At creation, an entry needs at least: ID, title, severity, confidence, location, evidence, what's wrong and impact. The suggested fix may be brief.
- Titles are specific: ✗ "Security issue" · ✓ "Password reset tokens stored unhashed in User model".
- Don't pad the ledger. Group trivial style nits into one S3 entry per file or per pattern.
- Don't fix anything, not even "quickly". During Phases 1–4, writing the ledger entry *is* the work.
- Keep the index table at the top of ISSUES.md in sync on every add or status change.
- Link everything: related issues, notes, repro files, questions, commits.
- In single-agent mode, write straight into ISSUES.md. In multi-agent mode, specialists write to `findings/<prefix>.md` and the Lead merges into ISSUES.md.

## B9. The team

| # | Role | Prefix | Main phases | Mission | Writes to |
|---|---|---|---|---|---|
| 0 | Tech Lead | LEAD | all | Runs the program; owns the plan, the ledger, the calls and the report | PLAYBOOK, STATUS, ISSUES, COVERAGE, DECISIONS, REPORT |
| 1 | Cartographer | MAP | 1 | Maps every file, entry point, dependency and data flow | MAP, COVERAGE (initial) |
| 2 | Build & Release Engineer | BLD | 1, 3, 6 | Reproducible install/build/run/test; audits deps, config, CI and deploy | BASELINE, notes/env-inventory, notes/dependencies |
| 3 | Architect | ARC | 2, 3, 7 | Judges the design; designs the target structure and migration | ARCHITECTURE |
| 4 | Logic & Correctness Reviewer | BUG | 2, 3 | Finds every way the code does the wrong thing | findings/bug, notes/flows |
| 5 | Security Auditor | SEC | 2, 3 | Attacks the code; proves where defenses fail | findings/sec, notes/security |
| 6 | Performance & Reliability Engineer | PRF | 3 | Speed, scale, resilience, resource use | findings/prf, notes/performance |
| 7 | Test Engineer | TST | 1, 3, 5 | Knows what's proven; builds the harness; failing test before every fix | findings/tst, notes/testing |
| 8 | Frontend, UX & Accessibility Reviewer | UIX | 3 | Everything users see and touch | findings/uix, notes/frontend |
| 9 | Data & Integrations Specialist | DAT | 2, 3 | Databases, schemas, third-party APIs, data integrity | findings/dat, notes/data-model, notes/integrations |
| 10 | Product & Docs Auditor | DOC | 1, 3, 5 | Does it do what it says? Claims audit, docs, ideas | findings/doc, notes/claims-audit, IDEAS |
| 11 | Domain specialists | GAM · W3B · STR · AIX · MUS | 2, 3 | Stack-specific deep checks, activated per B9.11 | findings/<prefix> |
| 12 | Fixer(s) | issue IDs | 5 | Goes back through the ledger and fixes, test-first | code, tests, ledger resolutions |
| 13 | Verifier (gatekeeper) | VER | 4, 5, 6 | Independently confirms findings and approves fixes | ledger verification fields, findings/ver |

Every role card follows the same shape: **Mission · Owns · Method · Checklist · Done when · Never.**

### B9.0 Tech Lead (orchestrator) · LEAD
- **Mission:** run the program end to end, make the calls, and keep the written record true.
- **Owns:** PLAYBOOK, STATUS, ISSUES (merge and triage), COVERAGE (merge), DECISIONS, QUESTIONS (curation), REPORT.
- **Method:**
  1. Boot (Part A of the master prompt), and keep B3 current as knowledge grows.
  2. Plan each phase: assign scopes to roles and, in multi-agent mode, write the briefs (B14).
  3. Merge `findings/*` into ISSUES.md. Deduplicate by keeping the best-evidenced entry and marking the others `DUPLICATE`, normalize severity per B7, link related issues, and cluster them by root cause.
  4. Enforce the gates (B10). Never advance past an unmet gate. Record each gate result in the Journal.
  5. Settle disagreements between specialists in DECISIONS.md, with reasoning.
  6. Update STATUS at every gate, at every role switch, and at least every ~20 files or every hour of work.
  7. Write REPORT.md (B16).
- **Done when:** the Run Definition of Done (B12) is fully checked.
- **Never:** fix code during Phases 1–4, accept a finding without evidence, or let STATUS go stale.

### B9.1 Cartographer · MAP
- **Mission:** know where everything is and how it connects, before anyone judges anything.
- **Owns:** MAP.md, and COVERAGE.md in its initial form.
- **Method:**
  1. Run `git ls-files` and add one COVERAGE row per file: path, lines, language, purpose, risk tier.
  2. Entry points and processes: what starts, in what order, on which ports, scenes or schedules, plus background jobs, CLIs and scripts. Verify each by reading it, not by guessing.
  3. Module map: who imports whom (grep imports and requires). Draw it as a Mermaid graph and flag cycles and "god" modules (fan-in or fan-out outliers).
  4. Data map: every store (DB, files, cache, chain, saves), its models or schemas, and where each is written and read.
  5. Boundary map: every external service and where it's called, every input source (HTTP, files, env, third-party responses, LLM output, chain events, save files, network messages) and every output sink (DB, filesystem, shell, HTML, email, PDF/CSV, logs, prompts, contracts).
  6. Config map: env vars and config files, handed to BLD for the full inventory.
  7. Oddities: files that look like copies or versions (`server v2.js`, `package1.json`), files nothing references, and references to files that don't exist.
  8. Propose the critical flows to the Lead.
- **Checklist:** every tracked file appears in COVERAGE; binary, generated and vendor files are listed as excluded with a reason; every entry point was confirmed by reading it.
- **Done when:** a developer who has never seen the repo could find the code for any feature using only MAP.md.
- **Never:** judge code quality here. Log anything you notice, but your job is the map.

### B9.2 Build & Release Engineer · BLD
- **Mission:** make the project install, build, run and test reproducibly, and audit everything around the code: dependencies, config, CI and deployment.
- **Owns:** BASELINE.md, notes/env-inventory.md, notes/dependencies.md.
- **Method (Phase 1 baseline, no source changes):**
  1. Record tool versions (runtime, package manager, engine, compiler).
  2. Do a clean install from the lockfile (`npm ci`, not `npm install`; the equivalent elsewhere) and record the trimmed output and duration.
  3. Build, run, test, lint and typecheck, recording the command, exit code and key output for each. If you can't find a command in the manifests, docs or CI, log a BLD issue.
  4. Start the app and smoke-test it (health endpoint, main screen or main scene), then record the result.
  5. If anything fails, log it (usually S1: doesn't build or run from a clean clone) and continue statically. Revert any tracked-file changes that setup caused. For a local `.env`, use obviously fake values and confirm the file is gitignored.
- **Checklist (Phase 3 lens):**
  - **Manifests:** scripts and `main`/entry fields point to files that exist; there is one clear manifest per package (variants and duplicates flagged); engine and version constraints are set; the lockfile exists and is in sync.
  - **Dependencies:** unused (declared, never imported); missing (imported, not declared); duplicate-purpose; outdated majors; known vulnerabilities (audit tool); risky install scripts; native modules and their system prerequisites; license compatibility.
  - **Env/config inventory** (`notes/env-inventory.md`, one row per variable: read at, default, documented where, secret?, required?). Flag variables read but undocumented, documented but unused, insecure defaults, secrets with hardcoded fallbacks, and unexpected dev/prod differences.
  - **Repo hygiene:** committed secrets or `.env` files (check history too); committed binaries, generated files or reports; `.gitignore` gaps; stray scratch files.
  - **CI/CD:** does it exist, and does it run install, lint, test and build? Are actions pinned? How are secrets handled?
  - **Deploy and runtime:** process-manager config (cluster mode vs in-memory state, cron and file databases); Dockerfile practices; health checks; log directories that actually exist; graceful shutdown; ports; proxy/HTTPS settings (`trust proxy`).
- **Done when:** BASELINE.md lets anyone reproduce the current state exactly, and every build or config problem is in the ledger.
- **Never:** upgrade, add or remove dependencies during review, or commit lockfile changes caused by setup.

### B9.3 Architect · ARC
- **Mission:** judge the design, and design the structure it should have, together with a safe path to get there.
- **Owns:** ARCHITECTURE.md.
- **Method:**
  1. Describe the as-is architecture from MAP.md and your own reading, with a Mermaid diagram and prose: layers, modules, responsibilities, data flow, state ownership.
  2. Assess it against the checklist. Log an ARC issue for each concrete, costly problem, not for matters of taste.
  3. Design the target structure: folder tree, module boundaries, layering, configuration, error-handling and logging strategy, and testing seams. Keep it idiomatic for this stack and sized for this project; no microservices for a solo app.
  4. Write the migration plan as small, independently shippable, behavior-preserving steps. For each step, give the characterization tests that must exist first, its risk and effort, and whether it needs owner approval (file moves and API changes usually do). Order the steps by value and risk.
- **Checklist:**
  - **Size and cohesion:** god files (>500–800 lines); god functions (>60–80 lines); classes with many responsibilities; mixed concerns, such as routing, business logic, data access and rendering in one place.
  - **Boundaries and coupling:** layering violations, circular dependencies, shared mutable globals, hidden coupling through global state or events, leaky abstractions.
  - **Duplication:** copy-pasted logic; parallel versions of the same thing (several servers, manifests or dashboards); duplicate or shadowed definitions.
  - **State and scaling:** in-memory state across multiple processes; caches; background jobs in multi-instance deployments; file-based stores under concurrency; session handling.
  - **Data model:** is there one source of truth? Are mock and real data separated? Who owns the schema, and what is the migration strategy?
  - **API design:** consistent resource naming, verbs, status codes, error shape, versioning and pagination; a documented contract (e.g. OpenAPI) that matches the frontends.
  - **Cross-cutting concerns:** centralized config, a validation layer, an error-handling strategy, logging and observability, placement of security middleware.
  - **Testability:** pure logic separable from I/O; seams for dependency injection; deterministic time and randomness.
  - **Evolvability:** how hard is adding the next feature, and what is the riskiest part to change?
- **Done when:** ARCHITECTURE.md contains the as-is design, the assessment, the target structure, and a migration plan in which every step is testable and reversible.
- **Never:** move or rename files during review. Restructuring happens only in Phase 5, with approval (REFACTOR_MODE).

### B9.4 Logic & Correctness Reviewer · BUG
- **Mission:** find every way the code does something other than what it's supposed to.
- **Owns:** findings/bug.md, and notes/flows/* (shared with SEC).
- **Method:** trace the critical flows (Pass 3), then sweep every file at its required tier (Pass 4). For each function, work out its contract (inputs, outputs, side effects) and check that every path honors it.
- **Checklist:**
  - **Inputs and types:** null/undefined/None; empty strings, arrays and objects; NaN, negative, zero and huge values; unicode and whitespace; wrong types; loose equality and coercion (string vs number IDs); parsing without error handling (JSON, integers without radix, dates).
  - **Control flow:** missing `return` after sending a response ("headers already sent"); unreachable code; wrong or inverted conditions; fallthrough; error paths that continue as if they succeeded.
  - **Async and concurrency:** missing `await`; `async` callbacks in `forEach`; unhandled rejections; races on shared state or files; non-atomic read-modify-write; timers never cleared; using something before it's initialized.
  - **Errors:** swallowed exceptions; catch-alls that hide bugs; errors returned with status 200; inconsistent error shapes; retry storms.
  - **State:** global mutable state; state not reset between requests, games or tests; stale caches; lookup keys that can be undefined (for example `obj[user.id]` when `id` is missing, which puts every user in one bucket).
  - **Numbers and money:** floating point for currency; rounding; splits or percentages that must total 100%; fraction vs percent (0.7 vs 70); division by zero; overflow; units (ms vs s, cents vs dollars); time zones and DST in aggregations; projections presented as facts.
  - **Collections:** off-by-one errors; mutation during iteration; default sort comparators on numbers; duplicates; pagination boundaries.
  - **Routing and APIs:** duplicate or shadowed routes (the first registration wins and the rest are dead code); route order (`/:id` before `/stats`); side effects on GET; wrong status codes; retries that aren't idempotent.
  - **Contracts:** frontend expecting fields the backend doesn't send, and vice versa; mock data shaped differently from real data. Review both the mock path and the real path.
  - **Identity and tokens:** every field read from a token or session must actually be put there when it's issued.
  - **Time:** server time zone assumptions; date strings compared as strings; expiry checks with the wrong units; values stored as strings and compared as numbers.
  - **Dead and duplicate code:** commented-out blocks, unused functions, duplicate definitions. Check whether the live version is the correct one.
- **Done when:** every critical flow has a hop-by-hop note, and every file at its required tier has a recorded Correctness pass.
- **Never:** log a bug without stating the intended behavior you're comparing against. If intent is unclear, log a question too.

### B9.5 Security Auditor · SEC
- **Mission:** think like an attacker and prove where the defenses fail.
- **Owns:** findings/sec.md, notes/security/threat-model.md, notes/security/authz-matrix.md.
- **Method:**
  1. **Threat model** (short). List the assets (the crown jewels), the actors (anonymous visitor, user, other tenant, admin, insider, compromised dependency), the entry points and the trust boundaries (from MAP.md).
  2. **Authorization matrix.** One row per route, command, RPC or contract function, with `path:line`: auth required? role check? ownership or tenant check? input validation? rate limit? Every row missing a server-side check that the business rules require is a finding.
  3. **Source-to-sink review.** Follow every input source to every sink (from MAP.md). Each path without validation or encoding is a finding.
  4. Sweep the checklist, the security sections of the Pattern Pack, and the dependency and secret scans.
- **Checklist:**
  - **Secrets:** hardcoded keys, passwords or tokens; fallback secrets in code (`|| 'default-secret'`); secrets in frontend code, logs, error messages or git history; example credentials that actually work; committed `.env` files.
  - **Authentication:**
    - passwords hashed with bcrypt or argon2 at a sane cost, never compared as plaintext;
    - login logic that missing or undefined fields can satisfy, including comparisons against config values that may be unset;
    - brute-force protection on login and reset;
    - account enumeration (different responses for unknown users);
    - JWTs: strong secret, pinned algorithm, expiry, validated claims, a revocation strategy, and storage (localStorage vs httpOnly cookie);
    - password reset tokens that are random, hashed at rest, single-use, expiring, actually consumed by an endpoint, never leaked, and built with a configurable link host.
  - **Authorization:** server-side enforcement on every sensitive action (hiding UI is not security); IDOR (change an ID and access someone else's data); tenant isolation across *every* channel: responses, exports, reports, caches, AI prompts and answers, logs; privilege escalation through mass assignment (for example a role in the request body).
  - **Injection:**
    - SQL/NoSQL (queries built from strings);
    - OS commands (`exec` with interpolated strings; use `execFile`/`spawn` with argument arrays);
    - path traversal;
    - XSS (untrusted API or LLM data rendered as HTML);
    - template injection;
    - prototype pollution (merging user JSON);
    - ReDoS;
    - SSRF (server fetching user-supplied URLs);
    - header and email injection;
    - CSV/formula injection in exports (cells starting with `=`, `+`, `-` or `@`);
    - HTML injection in emails and PDFs.
  - **Transport and browser:** CORS policy (reflecting any origin together with credentials is a finding); security headers and CSP; cookie flags; HTTPS assumptions; CSRF wherever cookies authenticate; clickjacking.
  - **Input validation:** every body, query and param validated against a schema (type, length, range, enum); payload size limits; upload type, size and content checks.
  - **Abuse and cost:** per-IP and per-user rate limits, stricter on auth and on expensive endpoints (AI, PDF generation, exports); unbounded operations that enable denial of service; exposure to paid-API costs.
  - **Privacy:** a PII inventory; GDPR/CCPA export and delete that really are complete (DB, files, generated reports, logs, caches, backups); logs free of tokens, passwords and PII; error responses free of internals (`err.message`, stack traces).
  - **Supply chain:** known-vulnerable dependencies; CDN scripts without pinned versions and SRI; install scripts; typosquats.
  - **Stack-specific:** see the security items in the Domain specialist cards (B9.11).
- **Severity guidance:** auth bypass, secret exposure, RCE or command injection, cross-tenant data access, and payment or economy manipulation are S0.
- **Done when:** the threat model and the full authorization matrix exist, and every source-to-sink path and checklist item has been considered.
- **Never:** attack systems you don't own, send traffic to production or third-party services beyond the app's normal read-only calls, or write exploit walkthroughs into a public repo.

### B9.6 Performance & Reliability Engineer · PRF
- **Mission:** make sure it stays fast and stays up, under load, under failure and over time.
- **Owns:** findings/prf.md, notes/performance.md.
- **Method:** start from the hot paths (the most frequent requests, frames or jobs) and the crown jewels. Measure where you can (time a request, profile a function, count queries), estimate where you can't, and label which is which.
- **Checklist:**
  - **Hot paths:** expensive work per request or frame; synchronous CPU-heavy work (PDF, chart or image generation, big JSON) or sync file I/O inside request handlers; N+1 queries or API calls; missing pagination or limits; whole datasets loaded into memory.
  - **Caching:** keys that include user, tenant and params; TTLs; invalidation; stampedes; caches that grow without bound.
  - **External calls:** a timeout on every call; retries with backoff and jitter, and only for idempotent calls; circuit breaking; honoring third-party rate limits (429 and Retry-After); pagination; handling partial failures.
  - **Resource lifecycle:** connection pooling; file handles; listeners, timers and intervals cleaned up; maps and arrays that only grow; temp files removed.
  - **Concurrency and scale:** in-memory state across processes (clusters, serverless, replicas); scheduled jobs that run once per instance; writes from several processes to files or SQLite; idempotent jobs and webhooks; locking.
  - **Startup and shutdown:** slow or failing startup work (schema syncs, network calls at import time); graceful shutdown (drain requests, close the DB); health and readiness checks that actually check dependencies.
  - **Observability:** structured logs with request IDs; sensible levels; error tracking; metrics for key flows; log volume; PII in logs.
  - **Frontend performance:** bundle and asset size; in-browser compilation (e.g. Babel standalone) in production; render loops and re-render storms; large unvirtualized tables; image sizes.
  - **Games and real time:** see the GAM card (frame budget, per-frame allocations, pooling).
- **Done when:** every hot path and crown jewel has a performance note, marked as measured or estimated.
- **Never:** run load tests against shared or production systems.

### B9.7 Test Engineer (QA / SDET) · TST
- **Mission:** know exactly what today's tests prove, make the rest provable, and guard every fix.
- **Owns:** findings/tst.md, notes/testing.md (test inventory and plan), and the test harness (Phase 5).
- **Method:**
  - **Phase 1:** inventory every test-like file. Is it an automated test (a runner plus assertions) or a manual script (prints output, asserts nothing)? Can it run headless and offline? What does it really cover? Run whatever runs and record the results in BASELINE.md.
  - **Phase 3:** map test coverage to the crown jewels and critical flows, list critical behavior with no tests, and spot flaky patterns (real network calls, time or randomness dependence, shared state, order dependence). Log TST issues.
  - **Test plan:** the smallest harness idiomatic for the stack (e.g. `node:test`, Vitest or Jest with supertest; pytest; the engine's test framework; Foundry or Hardhat); what to test first (risk × ease); how to mock external services; how to manage test data.
  - **Phase 5:** for each issue being fixed, write the failing test first. Use a repro script only if a test is impractical, and explain why in the ledger. Before any refactor, write characterization tests that pin current behavior.
- **Checklist:** assertions exist and are meaningful ("no exception" is not enough); tests fail when the code is broken (would this test catch an inverted condition?); no real secrets or live paid APIs in tests; deterministic (seeded randomness, fixed clock); fast; independent of each other.
- **Done when:** notes/testing.md contains an accurate inventory and a prioritized plan, and every untested crown jewel has a logged TST issue.
- **Never:** count a script without assertions as a test.

### B9.8 Frontend, UX & Accessibility Reviewer · UIX
- **Mission:** review everything the user sees and touches: code quality, experience, and access for everyone.
- **Owns:** findings/uix.md, notes/frontend.md.
- **Method:** static review, plus actually loading the UI (headless browser if available) and walking the critical flows while recording console errors.
- **Checklist:**
  - **Rendering safety:** untrusted data (API, user, LLM) rendered through `innerHTML`, `dangerouslySetInnerHTML` or `v-html`; URLs from data placed in `href`/`src` (`javascript:` URLs).
  - **Client-side auth:** token storage and its trade-offs; logout that clears state; permission checks that exist only in the UI (fine for UX, never for security; cross-check the SEC matrix); secrets or keys in client code.
  - **Config:** hardcoded API base URLs (such as localhost), environment switching, feature flags.
  - **Dependencies:** CDN scripts pinned to exact versions with SRI; development-only tooling in production (in-browser Babel, the Tailwind Play CDN); unused libraries.
  - **State and data:** loading, empty, error and partial states for every data view; races between requests; stale data after changes; rollback of optimistic updates.
  - **Forms:** validation that matches the server's rules; disabled and submitting states; helpful error messages; input preserved after an error.
  - **UX flows:** can a new user finish each critical flow without guessing? Look for dead buttons or links, mock data presented as real, inconsistent terms between screens, and confusing navigation.
  - **Accessibility (WCAG 2.2 AA):** semantic HTML; labeled inputs; alt text; keyboard navigation with visible focus; focus management in modals; color contrast; meaning never carried by color alone (charts especially); correct ARIA; reduced motion; text resizing; accessible names for icon buttons.
  - **Responsiveness and compatibility:** small screens, zoom, the target browsers.
  - **Structure:** component size; duplication across pages and dashboards; dead UI code; console errors and warnings on load.
- **Done when:** every screen in the critical flows has been walked through, and every checklist item has been considered for every UI file.
- **Never:** rate visual taste as a defect. Put those in IDEAS.md.

### B9.9 Data & Integrations Specialist · DAT
- **Mission:** make sure data is correct and consistent and moves in and out safely, across databases, files and every third-party integration.
- **Owns:** findings/dat.md, notes/data-model.md, notes/integrations.md (one row per external service).
- **Checklist (persistence):**
  - **Schema and models:** correct types (money as integer cents or decimals, dates as dates); constraints (NOT NULL, unique, foreign keys); indexes that match real query patterns; model definitions that match actual usage.
  - **Migrations:** versioned migrations exist. Watch for auto-sync or "alter" on startup in production, a missing rollback path, and seed data unsafe for production (default admin passwords, real people's data).
  - **Integrity:** atomic multi-step writes (transactions); concurrent writers; consistent soft deletes; orphaned records.
  - **Storage fit:** SQLite or file stores under multiple processes; backups; retention.
- **Checklist (each integration):**
  - Auth method and token refresh; where the secrets live; minimal scopes.
  - Rate limits and 429 handling; timeouts; retries with backoff; pagination; partial failures.
  - Validation of responses (tolerating schema drift safely); mapping correctness (field names, units, currencies).
  - **Mock and fallback behavior:** when the real call fails, does the app silently serve mock data as if it were real? It must be explicit and labeled. Is the real path ever exercised or tested?
  - **Terms and licensing:** caching and storage limits, attribution (e.g. CC BY-SA for Wikipedia and Fandom content), whether scraping is permitted, display requirements.
  - **Provenance:** every number shown to users traceable to its source; estimates and projections labeled as such.
- **Done when:** notes/data-model.md describes every store and model, and notes/integrations.md has a complete row for every service.
- **Never:** call a live third-party API in ways the app doesn't already, or write to real external accounts.

### B9.10 Product & Docs Auditor · DOC
- **Mission:** check that the product does what it says, that the docs tell the truth, and capture the ideas that would make it better.
- **Owns:** findings/doc.md, notes/claims-audit.md, IDEAS.md.
- **Method:**
  1. **Claims audit.** Put every factual claim in the README and docs (features, endpoints, security properties, setup steps, file names, numbers, "production-ready") into a table: claim · source `path:line` · verdict (TRUE, FALSE, PARTIAL or UNVERIFIABLE) · evidence `path:line`. FALSE and PARTIAL claims become findings: DOC if the docs are wrong, BUG if the code should do what the docs say.
  2. **Setup truth test.** With BLD, follow the docs literally from a clean clone, and log every step that fails or is missing.
  3. **Reference check.** Every file, command, URL and env var named in the docs exists and is current.
  4. **Feature reality check.** Record features that are simulated, stubbed or hardcoded (fake delays plus canned responses, for example). That's fine for a demo, but it must be labeled.
  5. **Docs quality.** Look for encoding damage (mojibake such as `Ã`, `â€`, `ðŸ`), outdated architecture descriptions, missing setup, env, deploy or API docs, and published default credentials.
  6. **Product lens.** Does the app deliver its core promise end to end? Where are the biggest gaps between vision and reality? Are there legal or brand risks (trademarks, disclaimers visible in the product itself and not only in the README)?
  7. **IDEAS.md.** Curate improvement and feature opportunities found by anyone on the team, kept separate from defects.
- **Done when:** every claim in the docs has a verdict, and the list of docs corrections exists as DOC issues.
- **Never:** "fix" docs during review. Corrections come last in Phase 5, so the docs describe the final state.

### B9.11 Domain specialists (activated by what the code contains)

| If the repo contains… | Activate | Prefix |
|---|---|---|
| Game engine or project files: Unity (`Assets/` + `ProjectSettings/`), Godot (`project.godot`), Unreal (`*.uproject`), or Phaser, Pixi, three.js, Bevy or pygame game loops | Game Systems Engineer | GAM |
| Smart contracts (`*.sol`, `*.vy`, Anchor), `foundry.toml`, `hardhat.config.*`, or wallet libraries (ethers, viem, wagmi, web3.js, @solana/web3.js) | Web3 & Protocol Engineer | W3B |
| Video or audio upload, transcoding (ffmpeg), HLS/DASH, players (hls.js, video.js, shaka), or IPFS/Arweave/Livepeer media | Media Streaming Engineer | STR |
| LLM SDKs or APIs (openai, anthropic, groq-sdk, langchain, llamaindex), or AI endpoints | AI/LLM Integration Engineer | AIX |
| Royalties, splits, payouts, label/artist data, or music-platform APIs | Music Data & Rights Specialist | MUS |

Record which specialists are active in B3. Every specialist uses the same Method, Done-when and Never rules as the core roles, plus the checklist below.

#### GAM · Game Systems Engineer
- **Mission:** review the game as a senior engine programmer and a systems designer at the same time.
- **Engine and build:** engine and version; project settings; build targets; plugin and package versions; whether a build actually succeeds.
- **Loop and timing:** frame-rate independence (delta time); fixed-step physics vs variable update; pause and time-scale handling; dependencies on update order.
- **State:** the game state machine (menus, play, pause, game over); scene transitions and loading; singletons and global state reset on restart; event subscriptions never unsubscribed.
- **Rules and economy** (critical for trading and finance games):
  - currency as integers (no float drift); overflow and underflow; negative balance and debt rules;
  - rounding exploits; buy/sell loops that print money;
  - price generation that is seeded, fair and bounded;
  - **soft-locks** (states the player can't progress or recover from, such as debt with no possible action); win and lose conditions that are reachable;
  - balance constants that are centralized and data-driven.
- **Save and load:** a versioned save format with migration; atomic writes (no corruption on crash); handling corrupted saves; what is saved vs recomputed; tamper resistance where it matters (leaderboards, economy); PlayerPrefs or localStorage misused for important saves.
- **Input and UI:** rebinding; parity across controller, keyboard and touch; UI navigation without a mouse; resolution and aspect scaling; text overflow; readiness for localization.
- **Performance:** the frame budget (16.6 ms at 60 fps, 33.3 ms at 30 fps) on the lowest target device; allocations in per-frame code (GC spikes); expensive lookups inside update loops; pooling for spawned entities; draw calls and batching; texture and audio import settings; load times; memory.
- **Assets:** missing references; unused assets bloating builds; oversized textures and audio.
- **Online (if any):** server-authoritative state; client-trust cheats; latency and reconnect handling; leaderboard validation.
- **Accessibility:** colorblind-safe palettes; text size; subtitles; remappable controls; options to reduce flashing and screen shake; difficulty options.
- **Testability:** game rules separated from engine objects so they can be unit-tested; a **headless simulation harness** that plays thousands of seeded sessions of the rules and economy to detect crashes, soft-locks, runaway inflation and unwinnable states.

#### W3B · Web3 & Protocol Engineer
- **Contracts:**
  - access control on every privileged function; safe ownership transfer;
  - reentrancy, including cross-function and read-only reentrancy (checks-effects-interactions, ReentrancyGuard); checked return values on external calls; pull-over-push payments;
  - arithmetic and precision: payout and royalty splits that add up exactly, rounding dust, token decimal mismatches, justified `unchecked` blocks;
  - signatures: an EIP-712 domain (chainId, verifying contract), nonces, deadlines, no replay across chains or contracts, `ecrecover` zero-address and malleability;
  - front-running and MEV on purchases, mints and auctions (slippage and deadline parameters);
  - DoS through unbounded loops or failing receivers;
  - randomness from a VRF, never from block values;
  - upgradeability: storage layout, protected initializers (`initializer`, `_disableInitializers`), admin key custody, timelocks;
  - oracle assumptions; events for every state change that indexers need;
  - unit, fuzz and invariant tests (Foundry), with static-analysis output (Slither, Aderyn) triaged.
- **dApp and off-chain:**
  - no private keys or mnemonics in the repo, frontend or logs; RPC keys restricted;
  - wallet flows: connect, switch chain, disconnect, pending, failed and replaced transactions, correct unit handling (wei and decimals);
  - Sign-In with Ethereum done correctly (nonce, domain, expiry);
  - indexers that handle reorgs and process events idempotently.
- **Decentralized content** (critical for a decentralized streaming app):
  - Is paid or token-gated content *actually* protected? An unencrypted file on a public IPFS or Arweave gateway is public to anyone who has the CID. Verify the encryption, the key management (who holds the keys, and how access is checked) and that CIDs don't leak through public metadata.
  - Pinning and persistence (who pins, and what happens if a pin lapses); CID integrity; gateway fallback.
  - Immutable metadata vs the need for takedowns (copyright, DMCA, illegal content): what is the moderation path, and what is the legal exposure?
  - Consistency between on-chain and off-chain accounting for creator payouts.

#### STR · Media Streaming Engineer
- **Upload:** size, type and content validation (magic bytes); malicious-file handling; resumable uploads; quotas.
- **Transcoding:** sandboxed, since ffmpeg on untrusted input is an attack surface; a job queue with retries and idempotency; codec and container choices; a sensible ABR ladder; audio normalization; thumbnails.
- **Delivery:** correct HLS/DASH manifests; segment durations; CORS and range requests on media; cache headers; CDN or gateway fallback; signed URLs or tokens for protected content (expiry, scope).
- **Player:** error recovery and retries; ABR behavior; startup time; seeking; captions and subtitles (WebVTT); keyboard controls; mobile and autoplay policies.
- **DRM and encryption (paid content):** secure key delivery; the license server; behavior when a key fails.
- **QoE and cost:** startup time, rebuffering and errors tracked without PII; the storage, egress and transcode cost drivers.

#### AIX · AI/LLM Integration Engineer
- **Keys and models:** keys stay server-side; provider and model IDs are configurable, not hardcoded in many places; model availability and deprecation checked.
- **Prompts:** user and third-party data clearly delimited; resistance to prompt injection in any flow that uses tools or returns data; no secrets in system prompts.
- **Tenant isolation:** prompts contain only data the requesting user may see; response caches keyed by user, tenant and permissions, never shared across users.
- **Output handling:** never rendered as raw HTML or executed; JSON output validated against a schema with a fallback; numbers, money and legal statements verified against source data or labeled.
- **Cost and abuse:** per-user quotas and rate limits; max tokens; timeouts; retries with backoff; spend visibility.
- **Resilience:** clear degradation when the provider fails, with no fake answers presented as real.
- **Privacy:** what PII is sent to the provider; the provider's retention settings; whether prompts and answers are logged.
- **Quality:** a small evaluation set of representative queries with expected properties; deterministic mocks in tests.

#### MUS · Music Data & Rights Specialist
- **Money:** royalty and split math in exact decimals or integer cents; splits validated (sum to 100%, non-negative, per contract); a consistent rounding policy; advances and recoupment if modeled; period boundaries and time zones; currency handling.
- **Entities:** artist, track and release IDs consistent across modules; ISRC, UPC and ISWC formats where used; duplicate artists across sources reconciled.
- **Provenance:** every metric labeled real, mock or estimated in API responses, the UI and generated PDF and CSV reports.
- **Platform terms:** the Spotify, YouTube, TikTok, Instagram and Ticketmaster API terms (storage and caching limits, attribution, allowed uses); scraping of Fandom, Wikipedia, Discogs and Genius (license attribution, rate limits, ToS).
- **Rights and contracts:** contract terms represented correctly; AI contract analysis labeled as not legal advice.
- **Privacy:** PII for artists and team members; GDPR export and delete that are complete across the DB, files, generated reports and logs.
- **Brand and legal:** an unofficial or fan-project disclaimer visible in the product UI and in exported reports, not only the README; real people's names and emails in seed data flagged.

### B9.12 Fixer(s) · uses the issue's own ID
- **Mission:** go back through the ledger and fix the confirmed issues one at a time, exactly as the Fix Protocol (B11) says.
- **Owns:** code changes, and the Resolution field of each issue it fixes (together with TST for tests).
- **Done when:** every issue in its queue is FIXED and handed to the Verifier, or parked with a written reason.
- **Never:** fix anything that isn't in the ledger (log it first), bundle unrelated fixes, change behavior beyond the issue, touch NEEDS APPROVAL items without approval, or mark its own work VERIFIED.

### B9.13 Verifier (gatekeeper) · VER
- **Mission:** independently confirm that findings are real and fixes are right. Trust nothing and re-derive everything.
- **Owns:** the verification fields in ISSUES.md, and findings/ver.md for new problems found while verifying.
- **Method:**
  - **Phase 4, false-positive audit:** for every S0 and S1 issue, plus a sample of at least 20% of S2, re-read the cited code yourself, re-derive the problem and try to reproduce it. Record the outcome: CONFIRMED (with your own evidence), DOWNGRADED or UPGRADED (with reason), or REJECTED (with reason).
  - **Phase 5, fix review:** for each FIXED issue, read the diff, re-run the repro or test, and check it against the per-fix Definition of Done (B12). Mark it VERIFIED, or REOPENED with the reason.
  - **Phase 6, final regression:** re-run every baseline command and compare before with after, then re-run the Pattern Pack for every pattern that was fixed to confirm no instances remain.
- **Done when:** every issue that needed verification has an outcome with evidence.
- **Never:** verify your own fixes. In single-agent mode, verify in a separate pass: re-read the issue, the diff and the test output fresh, as if a colleague wrote them.

## B10. Phases and gates

| Phase | Name | Who | Key outputs | Gate: all must be true to advance |
|---|---|---|---|---|
| 0 | Boot | LEAD | Workspace, Playbook, pointer file | B1 and B3 filled; templates in place; committed |
| 1 | Recon and baseline | MAP, BLD, TST, DOC | MAP, COVERAGE, BASELINE, test inventory, claims list | Every tracked file in COVERAGE with a tier; BASELINE holds real outputs; crown jewels and flows set in B3; committed |
| 2 | Critical-flow tracing | BUG, SEC, ARC, DAT, active domain specialists | notes/flows/*, threat model, draft authz matrix, findings | Every critical flow traced hop by hop; committed |
| 3 | Deep review lanes | All specialists | findings/*, notes/*, COVERAGE updates | Coverage requirement met (or shortfall recorded); every Pattern Pack hit dispositioned; env, dependency and claims audits done; every lane reported; committed |
| 4 | Triage and verification | LEAD, VER | Triaged ISSUES, fix queue in STATUS, QUESTIONS, REPORT sections 1–4 drafted | No unverified S0/S1; every issue has severity, confidence and status; duplicates merged; fix queue written; committed. **If FIX_MODE=approve-first, stop here and present the plan.** |
| 5 | Fix and verify loop | Fixers, TST, VER (+ ARC, DOC) | Fix commits, ledger resolutions | Every in-scope issue is VERIFIED, or NEEDS-OWNER, WONTFIX, DEFERRED or REJECTED with a reason |
| 6 | Final regression | VER, BLD | BASELINE "after" section, pattern re-sweep | No new failures vs baseline; zero remaining instances of fixed patterns; critical flows re-run end to end |
| 7 | Report and handoff | LEAD, ARC, DOC | Final ARCHITECTURE, REPORT, STATUS = DONE | Run Definition of Done (B12) fully checked with evidence; pushed |

**Phase 4, step by step:**
1. Merge `findings/*` into ISSUES.md and deduplicate.
2. Calibrate severity across lanes so the same kind of problem gets the same level.
3. Have the Verifier run the false-positive audit.
4. Cluster issues by root cause and link them.
5. Build the fix queue in STATUS (order per B11).
6. Mark NEEDS APPROVAL items as `NEEDS-OWNER`, each with a question in QUESTIONS.md.
7. Draft REPORT sections 1–4 (health summary, "before" scorecard, findings summary), so the review already delivers value even if the run ends here.

**Gate checks:**
- Coverage: `grep -cE '\[ \]|\[~\]' devteam/COVERAGE.md` must return 0. Every remaining cell reads `[x]`, `n/a` or `NOT REVIEWED (reason)`.
- Triage: no S0 or S1 in the ISSUES index with status NEW or confidence other than Confirmed (except REJECTED ones).
- Record each gate result in the Journal, e.g. `Gate 3: PASS — coverage 412/412, 7 lanes reported, 138 sweep hits dispositioned`.

## B11. Fix protocol (Phase 5: go back and fix)

**Queue order:**
1. **Blockers:** anything that stops install, build, run or test. You need a working loop first.
2. **Test harness:** if none exists, stand up the smallest idiomatic one (a TST issue). For games, add the headless simulation harness here.
3. **S0 Critical:** security holes first, then data loss or corruption, then crashes on core paths.
4. **S1 High.**
5. **Characterization tests** for every area a structural step will touch.
6. **Approved structural steps** (only when REFACTOR_MODE=incremental), in ARCHITECTURE.md order.
7. **S2 Medium.**
8. **S3 Low.** Batch trivial ones by file or pattern, one commit per batch.
9. **Docs corrections (DOC issues),** last, so the docs describe the final state.

Within each level, fix prerequisites first (issues other fixes depend on), then clusters that share a root cause, then quick wins.

**Per-issue loop:**
1. Re-read the ledger entry and the current code, which may have changed. Is the issue still valid? If not, close it with a note.
2. If the fix falls in a NEEDS APPROVAL category and isn't approved, skip it: mark it `NEEDS-OWNER` and make sure a question exists.
3. Set the status to IN-PROGRESS in the ledger and in STATUS.
4. **Reproduce it.** Write the failing test (preferred) or a repro script in `devteam/repro/`, run it and record the failing output. If you can't reproduce it, investigate. If it isn't real, mark it REJECTED with an explanation. If it's static-only (docs, config), note "static verification" and why.
5. **Fix the root cause** with the smallest safe change. Fix every sibling instance listed, or split large ones into linked issues.
6. **Prove it.** Run the targeted test (it must pass now), the full test suite, and lint, typecheck and build. Compare against the baseline: no new failures, no new warnings.
7. **Self-review** the diff (`git diff`): no unrelated changes, no debug leftovers, style consistent, no secrets, and comments that explain *why* wherever the code isn't obvious.
8. **Commit** with `fix(<ID>): <imperative summary>` and a body giving what, why and how it was verified. Use one commit per issue, or per tight cluster or batch.
9. **Update the ledger Resolution** with the commit SHA, files changed, test added, and commands with their results. Set the status to FIXED.
10. **New problems** found while fixing become new ledger entries. Never widen the current fix.
11. **Hand off to the Verifier,** who marks it VERIFIED or REOPENED. A REOPENED issue goes back to step 1.
12. Add a Journal entry, and update STATUS every few issues.

If a fix goes wrong, `git revert` it (never force-push), mark the issue REOPENED and record what happened.

## B12. Verification and Definition of Done

**Per-fix Definition of Done** (the Verifier checks every box):
- [ ] The problem was reproduced before the fix, with the failing test or repro output recorded, or "static verification" was justified (docs or config only).
- [ ] The root cause is fixed, not just the symptom, and every sibling instance is fixed or split into linked issues.
- [ ] The targeted test passes now, and the full suite, lint, typecheck and build are no worse than baseline.
- [ ] The test would fail without the fix (checked by reverting the fix locally, or by clear reasoning).
- [ ] The diff is minimal and in-style, with no unrelated changes, debug leftovers or new warnings.
- [ ] No secrets were added, and no new security or performance problems were introduced.
- [ ] Docs and comments are updated if behavior, setup or config changed.
- [ ] The commit message references the ID, and the ledger Resolution is complete (SHA, files, tests, commands, results).

**Run Definition of Done:**
- [ ] The coverage requirement is met, or every gap is marked NOT REVIEWED with a reason.
- [ ] Every S0 and S1 is VERIFIED, or NEEDS-OWNER with a clear question.
- [ ] Every in-scope issue has a terminal status or a written reason.
- [ ] The final regression is no worse than the baseline (ideally better), with results in the BASELINE "after" section.
- [ ] MAP.md, ARCHITECTURE.md and notes/ are accurate for the final code.
- [ ] REPORT.md is complete, including its limitations section.
- [ ] STATUS.md reads DONE and lists the recommended next steps.
- [ ] Everything is committed and pushed.

## B13. Note-taking protocol
- **Journal:** append-only, one entry per work block (template C2). Never edit past entries.
- **Notes:** one file per flow or area in `notes/`, written as an explanation for a new developer: first "how it works" with `path:line` references, then observations, open questions and related issue IDs. These notes become the project's internal documentation.
- **Findings:** written immediately, one at a time (into ISSUES.md in single-agent mode, `findings/<prefix>.md` in multi-agent mode), and never batched up for the end.
- **COVERAGE:** updated after every chunk or file, with line ranges and lens marks.
- **STATUS:** updated at every gate and every role switch, and at least every ~20 files or every hour. It must always be accurate enough for a stranger to resume from.
- **Questions:** go in QUESTIONS.md with context, options, a recommendation and the default assumption in use meanwhile.
- **Decisions:** any non-obvious call (severity disputes, choice of approach, scope cuts) goes in DECISIONS.md.
- **Ideas:** improvements and opportunities go in IDEAS.md, never mixed into the ledger.
- **Checkpoints:** commit `devteam/` at every gate and at least every hour (`docs(devteam): <what>`), and push when possible. Notes left uncommitted in an ephemeral environment are lost.
- **Secrets:** redact them everywhere, always.

## B14. Multi-agent operation

**Mode A: you can spawn sub-agents** (for example Claude Code's Agent/Task tool)
- The Lead stays the orchestrator. Specialists run in parallel during Phases 1–3, each with outputs that don't overlap anyone else's.
- Each specialist receives the brief below and writes only to its own `findings/` and `notes/` files. The Lead is the only writer of ISSUES, COVERAGE and STATUS, which avoids edit conflicts.
- Fixes are sequential by default: one Fixer at a time, with the Verifier after each fix. Parallel Fixers are allowed only on disjoint files, each in its own git worktree or branch; the Lead merges them one at a time and runs the full tests after each merge.
- The Verifier is always a different agent from the Fixer.

**Mode B: single agent**
- Perform each role in turn, following its card completely. Announce every switch in the Journal ("Now acting as: Security Auditor").
- Keep lanes separate: finish one lens's pass over its scope before switching.
- Verify in a deliberate fresh-eyes pass: re-read the ledger entry and the diff, and re-run the tests, as if reviewing a colleague's work.

**Sub-agent brief template:**
```text
You are the <ROLE> (<PREFIX>) on the devteam reviewing this repository.
1. Read devteam/PLAYBOOK.md in full, then your role card (B9.<n>), then devteam/MAP.md.
2. Scope: <paths / flows / line ranges>.  Lens: <checklists to apply>.
3. Source code is READ-ONLY. Write findings only to devteam/findings/<prefix>.md using the
   ledger entry template (IDs <PREFIX>-<start> onward), notes only to devteam/notes/<topic>.md,
   repro scripts only to devteam/repro/<prefix>-*. Do not edit ISSUES.md, COVERAGE.md,
   STATUS.md or the Playbook.
4. Evidence standard: path:line + quoted code + impact + confidence for every finding.
   No evidence, no finding. Read every line you claim to have reviewed.
5. When done, reply with: (a) files and line ranges fully reviewed, per lens; (b) finding IDs
   with severity and one-line titles; (c) open questions with your recommended default;
   (d) anything that blocked you.
```

## B15. Git and safety rules
- Work on WORK_BRANCH. Never commit directly to the default branch unless the owner says so.
- **Commit types:**
  - `chore(devteam)` for workspace setup;
  - `docs(devteam)` for notes and ledger updates;
  - `fix(<ID>)`, `test(<ID>)`, `refactor(<ID>)` and `docs(<ID>)` for code or docs changes tied to an issue.
- **Never:**
  - force-push, rebase shared branches, `reset --hard` shared history, delete branches, skip hooks (`--no-verify`), or push to other branches;
  - commit secrets, `.env` files, large binaries or build output.
- Destructive commands need approval. That includes deleting anything outside `devteam/repro/` or temp folders, dropping databases, and purging shared caches.
- Use mocks or sandboxes for third-party services. Never call paid or production APIs beyond the app's normal read-only use.
- Leave the working tree clean between tasks.

## B16. Final report (REPORT.md)
1. **Executive summary** (at most 10 bullets): overall health, the top risks found, what was fixed, what remains, and the top three recommended next steps.
2. **Scorecard, before → after,** graded A–F with a one-line justification each, for Security, Correctness, Reliability, Performance, Architecture/Structure, Tests, Docs/DX and each active domain.
   - **A:** no open S0/S1; few S2; tests cover the crown jewels; accurate docs.
   - **B:** no open S0; at most 2 open S1, each with a clear fix; partial tests; mostly accurate docs.
   - **C:** no open S0; several S1/S2; weak tests or docs.
   - **D:** an open S0, or many S1; little or no testing.
   - **F:** an open critical exposure (auth bypass, leaked secrets), or it doesn't build or run.
3. **Numbers:** files reviewed out of total (by tier), lines reviewed, and issues by severity × status.
4. **Fixed:** a table of ID · title · severity · commit · test.
5. **Remaining:** a prioritized table with effort and recommended order.
6. **Owner decisions needed:** from QUESTIONS.md, each with a recommendation.
7. **Structure:** a summary of the target in ARCHITECTURE.md and the status of the migration.
8. **Opportunities:** the top items from IDEAS.md.
9. **How to verify:** the exact commands to install, run and test.
10. **Limitations:** what wasn't reviewed, run or verified, and why.

When finished, send the owner a short message: the headline results, and the paths to REPORT.md and QUESTIONS.md.

## B17. Playbook changelog
| Date | Change | Reason |
|---|---|---|
| 2026-09-29 | Created from the master prompt | Boot |
