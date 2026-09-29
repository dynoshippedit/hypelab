# BLD findings — Build & Release (Phase 1, 2026-09-29)
Lane prefix: BLD · ID range BLD-001–049 · all NEW unless noted.
Severities per Playbook B7. Confidence: Confirmed = reproduced or unambiguous code.

## BLD-001 — No dependency manifest: clean-clone install is impossible [S1, Confirmed]
**Location:** repo root (absence of `pyproject.toml` / `setup.py` / `requirements*.txt`).
**Evidence:** `git ls-files` shows no manifest; `python3 -c 'import hypelab'` from `/tmp` →
`ModuleNotFoundError: No module named 'hypelab'`. The package resolves only when the
cwd is `/home/dino/hypelab` (via `python3 -m hypelab.cli`) or via the
`/home/dino/.local/bin/hypelab` shim which does `cd /home/dino/hypelab`.
**What's wrong:** ten third-party imports (click, cv2, faster-whisper, jsonschema,
librosa, numpy, pysubs2, torch, torchaudio, transformers) resolve from a split,
unpinned environment (system `/usr/lib*` + user `~/.local/lib/python3.14/site-packages`)
that no file describes. No other machine can reproduce the dependency set.
**Impact:** the project does not install from a clean clone (B7 S1 criterion); a
rebuild of the Threadripper loses the working environment.
**Suggested fix:** add a `requirements.txt` (or `pyproject.toml`) pinning the ten
versions recorded in `notes/dependencies.md` — no upgrades, just pin what's there.
PRE-APPROVED per Playbook (pinning dependency versions).

## BLD-002 — README's test command runs zero tests [S2, Confirmed]
**Location:** README.md "Tests" section.
**Evidence:** README documents `python3 -m unittest discover -s tests -v`. Ran it:
`Ran 0 tests in 0.000s — NO TESTS RAN` (exit 0). The 8 test files are pytest-style
(plain test functions, fixtures); unittest discovery finds no `TestCase`s.
**What's wrong:** the documented way to verify the build silently does nothing.
**Impact:** anyone following the README believes they ran the suite; regressions go
undetected. The real command is `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/`
(191 passed, verified 2026-09-29).
**Suggested fix:** replace the README section with the pytest command (docs fix,
PRE-APPROVED).

## BLD-003 — `doctor` command documented in setup no longer exists [S2, Confirmed]
**Location:** README.md:17 (`python3 -m hypelab.cli doctor  # ffmpeg, whisper, edge-tts, fonts`).
**Evidence:** `python3 -m hypelab.cli doctor` → `Error: No such command 'doctor'.`
(exit 2); `grep -rn doctor hypelab/` returns nothing. VERTICAL_SLICE_REPORT.md:69
describes a `doctor()` that was removed.
**What's wrong:** the README's setup section ends with a smoke step that fails.
**Impact:** new operators follow setup into a dead end; there is no documented
environment self-check.
**Suggested fix:** docs fix — either restore a `doctor` command or replace the
README line with the verified smoke steps (`--help`, `migrate` on a scratch DB).
Note `edge-tts` in the comment was never a real dependency (see BLD-013).

## BLD-004 — README vertical-slice walkthrough references removed/renamed commands [S3, Confirmed]
**Location:** README.md "Vertical slice walkthrough" + "Consent gate" sections.
**Evidence:** walkthrough uses `align <job>`, `plan <job>`, `show <job>`,
`work --once`, `publish <job> --target …` and `--real`. Current CLI
(`--help`, 30 commands) has no `align`/`plan`/`show`; publish uses `--collab` and
`--live` (no `--target`, no `--real`).
**What's wrong:** the end-to-end usage doc does not match the CLI.
**Impact:** operators copy-paste commands that fail; onboarding friction.
Overlaps DOC lane's claims audit — BLD logs the run-reproducibility angle only.
**Suggested fix:** DOC lane to rewrite/verify the walkthrough against the real CLI.

## BLD-005 — `HYPELAB_HOME` documented but never read by code [S3, Confirmed]
**Location:** README.md:16, VERTICAL_SLICE_REPORT.md:45 (documented); no code reads it.
**Evidence:** `grep -rn 'HYPELAB_HOME' hypelab/` → zero hits. Code reads
`HYPELAB_ROOT` / `HYPELAB_DB` (cli.py:87,91; b2cli.py:47,51; book3cli.py:43,47).
**What's wrong:** the README's setup exports a variable that does nothing.
**Impact:** operators believe they configured the DB/root location when they
didn't; could mask a real misconfiguration.
**Suggested fix:** docs fix — replace `HYPELAB_HOME` with `HYPELAB_ROOT`/`HYPELAB_DB`
in README (or make the code honor `HYPELAB_HOME` as a fallback — NEEDS-OWNER: changes behavior).

## BLD-006 — `HYPELAB_CACHE` documented but never read by code [S3, Confirmed]
**Location:** ARCHITECTURE.md:381 ("`~/.cache/hypelab/` (or `$HYPELAB_CACHE`)").
**Evidence:** `grep -rn 'HYPELAB_CACHE' hypelab/` → zero hits.
**Impact:** minor doc drift; cache behavior is actually hardcoded elsewhere.
**Suggested fix:** docs fix — remove or implement. Full row in notes/env-inventory.md.

## BLD-007 — Tests set `HYPELAB_WORK_DIR` which the code never reads [S3, Confirmed]
**Location:** tests/test_book2.py:513,545 (`monkeypatch.setenv("HYPELAB_WORK_DIR", …)`).
**Evidence:** `grep -rn 'HYPELAB_WORK_DIR' hypelab/` → zero hits.
**What's wrong:** test isolation fixture configures an env var with no effect —
the tests may not be isolating the work dir they think they are.
**Impact:** false confidence in test isolation; possible cross-test interference.
Flagged for TST lane to confirm; BLD logs the config-hygiene angle.
**Suggested fix:** TST to verify what those tests actually isolate; then remove or wire the var.

## BLD-008 — `HYPELAB_CHROMIUM` selects the executed binary but is undocumented [S1, Confirmed]
**Location:** hypelab/carousel.py:53-68.
**Evidence:** `_chromium()` returns `os.environ.get("HYPELAB_CHROMIUM")` directly and
`subprocess.run([chromium, …])` executes it (carousel.py, `_run`). The variable
appears nowhere in README/ARCHITECTURE/AGENTS/CLAUDE — only inside the
"is not a file" error string.
**What's wrong:** per B4 Pass 6, a security-relevant variable that is read but
undocumented is high severity: whoever controls the environment controls which
binary the pipeline executes. Mitigations in place: `Path(override).is_file()`
check, no `shell=True`. In the local-first threat model the env is the operator's
own, so exploitability is low — but the documentation gap is real and the rule
says pick the higher severity when torn.
**Impact:** an operator (or a compromised dotfile) can silently redirect browser
execution; no doc warns of this.
**Suggested fix:** document the variable (docs fix, PRE-APPROVED); consider
logging the resolved binary at startup.

## BLD-009 — Hardcoded absolute paths tie the project to one machine [S3, Confirmed]
**Location:** hypelab/cli.py:57 (`DEFAULT_ROOT = "/home/dino/hypelab"`; same in
b2cli.py, book3cli.py); `/home/dino/.local/bin/hypelab` shim (`cd /home/dino/hypelab`);
hypelab/carousel.py:64 (`/opt/pw-browsers/chromium` fallback).
**What's wrong:** B6 "hardcoded environment" pattern; the project cannot run from
any other home directory or path without editing source.
**Impact:** portability; the shim breaks on any other machine/user.
**Suggested fix:** derive the repo root from `Path(__file__)` instead of a
hardcoded constant (bug fix restoring intended behavior — but changes path
resolution, so treat as NEEDS-OWNER if Lead prefers proposal-only).

## BLD-010 — Generated job artifacts (~34 MB) committed under `jobs/` [S3, Confirmed]
**Location:** jobs/job_c656669a5147/ (11 binaries: 6× `beat:bN.mp4` ~3.3 MB each,
`music.mp3`, `vo.mp3`, `caption_proof.png`, `master.mp4` 10.6 MB,
`master_1x1.mp4` 7.9 MB).
**Evidence:** `git ls-files` lists them; `.gitignore` ignores `/work/` but not
`/jobs/`; they are render outputs of a job run, not test fixtures (the only
legit fixture binary is tests/fixtures_book2/source.mp4, 5.8 MB).
**What's wrong:** build output committed to the repo; every clone pays ~34 MB.
Filenames contain colons (`beat:b1.mp4`) — illegal on Windows checkouts.
**Impact:** repo bloat; cross-platform breakage.
**Suggested fix:** NEEDS-OWNER — add `/jobs/` (or the job-output subset) to
`.gitignore` and remove from tracking (history rewrite NOT required; `git rm
--cached` suffices going forward). Overlaps hygiene review.

## BLD-011 — No dependency vulnerability audit possible (pip-audit absent) [S3, Confirmed]
**Location:** environment (tooling gap).
**Evidence:** `pip show pip-audit` → not installed; not installed during review
(would alter the shared user site). Manual reasoning only: no obviously
ancient/abandoned versions among the ten direct deps (see notes/dependencies.md).
**Impact:** CVEs in torch/transformers/librosa/etc. are unchecked.
**Suggested fix:** install `pip-audit` in CI or a venv and run it; add the step to
CI when CI exists (BLD-015). Effort: S.

## BLD-012 — torch is a CUDA build but no GPU exists (CPU-only inference) [S4, Confirmed]
**Location:** environment.
**Evidence:** `torch.__version__` = `2.12.1+cu130`, `torch.cuda.is_available()` =
False. VERTICAL_SLICE_REPORT.md:69 says alignment runs "CPU int8".
**Impact:** info only — perf expectations for faster_whisper/transformers should
assume CPU. No defect.

## BLD-013 — `openai-whisper` installed but unused; `edge-tts` referenced but absent [S4, Confirmed]
**Location:** system site-packages (`whisper` 1.1.10); README.md:17.
**Evidence:** AST import scan of `hypelab/` shows `faster_whisper` used, `whisper`
never imported; `edge_tts` never imported and not installed.
**Impact:** info — dead weight on the machine; README's `doctor` comment names a
non-dependency. No code defect.

## Not findings (checked, clean)
- **Secret scan:** B6 secret patterns over all tracked files (excl. devteam/) →
  1 false positive (`hypelab/align.py:322` `sp.token`, a tokenizer variable).
  `git log -p --all -S` for `sk-`, `BEGIN PRIVATE KEY`, `password=`, `api_key` →
  no hits. No committed secrets.
- **`.gitignore` gaps:** `hypelab.db`, `hypelab.db.bak.*`, `__pycache__`, `.pytest_cache`
  (self-ignores via its own `.gitignore`), `/work/`, `/models/` all ignored;
  `git status` clean; nothing stray untracked. (The `/jobs/` gap is BLD-010.)
- **Binaries:** only the 12 listed above are tracked (11 job outputs + 1 fixture).
