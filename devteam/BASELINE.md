# BASELINE — Build & Release (BLD)
Captured: 2026-09-29 ~01:55 UTC (2026-09-28 21:55 EDT) · commit `60f4a79` · by BLD
Branch: devteam/review-2026-09-29 (Phase 1, source read-only)

## Environment
| Tool | Version | Notes |
|---|---|---|
| python3 | 3.14.7 | system python, Nobara |
| pip | 26.0.1 | |
| pytest | 9.0.3 | run with `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` per task |
| ffmpeg | 8.1.2 | present, `ffmpeg -version` OK |
| faster-whisper | 1.2.1 | user site `~/.local/lib/python3.14/site-packages` |
| openai-whisper (`whisper`) | 1.1.10 | system site; **not imported by hypelab/** — dead weight (BLD-013) |
| torch | 2.12.1+cu130 | user site; `torch.cuda.is_available()` = **False** → CPU-only inference (BLD-012) |
| torchaudio | 2.11.0 | |
| transformers | 5.12.1 | user site; unusual major (public line is 4.x) but imports work, tests green |
| numpy | 2.4.6 | system `/usr/lib64` |
| opencv (`cv2`) | 4.13.0 | system |
| click | 8.5.0 | user site |
| jsonschema | 4.26.0 | user site |
| librosa | 0.11.0 | user site |
| pysubs2 | 1.9.0 | user site |
| ctranslate2 | 4.8.2 | user site (faster-whisper backend) |
| pip-audit | **not installed** | dependency audit done manually; see notes |

## Before any change
| Step | Command | Exit | Result summary | Duration |
|---|---|---|---|---|
| install | n/a — **no manifest** (no pyproject.toml/setup.py/requirements*.txt). Deps resolved from two site-packages trees; `hypelab` importable only from repo root (see install story below) | — | nothing to install; clean-clone install **impossible** (BLD-001) | — |
| build | n/a (Python, no build step) | — | — | — |
| test | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/ -q` (from `/home/dino/hypelab`) | 0 | **191 passed**, 3 warnings, 0 failed. Baseline reproduced exactly | 200.18 s (pytest) / 3m23 s wall |
| test (README variant) | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m unittest discover -s tests` | 0 | **NO TESTS RAN** (0 tests). Test files are pytest-style (plain functions/fixtures); README's documented command is broken (BLD-002) | ~2 s |
| lint | none configured | — | no ruff/flake8/pylint config in repo | — |
| typecheck | none configured | — | no mypy/pyright config in repo | — |
| run / smoke | `python3 -m hypelab.cli doctor` | 2 | **command does not exist**: `Error: No such command 'doctor'.` README's setup step is stale (BLD-003) | — |
| run / smoke (alt) | `python3 -m hypelab.cli --help` | 0 | 30 commands listed; CLI entry works | <2 s |
| run / smoke (alt 2) | `python3 -m hypelab.cli migrate` with `HYPELAB_DB=/tmp/bld_mig.db` | 0 | `v1 0001_book1_foundation / v2 0002_book2_clip_mine / v3 0003_book3_hype_layer` applied on fresh DB | <2 s |
| run / smoke (alt 3) | `publish --job j_4e38949c9648 --media tests/fixtures_book2/source.mp4 --caption 'BLD smoke'` on `/tmp` copy of repo DB (after `authorize`) | 0 | `DRY RUN placement … zero live calls made — recorded against fixtures only`. Consent gate refused first (expected), then passed after authorize. | <3 s |
| dependency audit | pip-audit | n/a | **not installed**; manual audit only (see notes/dependencies.md, BLD-011) | — |
| secret scan | B6 secret patterns over `git grep` (tracked) + `git log -p --all -S` for `sk-` / `BEGIN PRIVATE KEY` / `password=` / `api_key` | 0 | **clean** — 1 false positive (`align.py:322 sp.token`, tokenizer variable). No secrets in history | — |

## The install story (one paragraph)
There is no install: the repo ships no `pyproject.toml`, `setup.py`, or `requirements*.txt`, so `pip install` is impossible and the package is not on `sys.path` anywhere — `python3 -c 'import hypelab'` fails from any directory except the repo root. It runs only because (a) the reviewer invokes `python3 -m hypelab.cli` from `/home/dino/hypelab`, or (b) the `/home/dino/.local/bin/hypelab` shim `cd`s to the hardcoded `/home/dino/hypelab` first. Its ten third-party imports resolve from a split, unpinned environment: some in the system tree (`/usr/lib/python3.14/site-packages`, `/usr/lib64/python3.14/site-packages`: cv2, numpy) and most in Dino's user tree (`~/.local/lib/python3.14/site-packages`: click, torch, faster-whisper, transformers, librosa, …). Nothing pins versions, so a rebuild of this machine (or any other machine) cannot reproduce the dependency set — see BLD-001.

## Notes / deviations
- The task brief said 86 tracked files; `git ls-files` shows **104** (49 Python files confirmed, ~14.2k Python LOC not re-verified).
- The task brief said run with `HYPELAB_HOME=/home/dino/hypelab`; that variable is **not read by the code** (BLD-005). Smoke runs used `HYPELAB_DB`/`HYPELAB_ROOT` instead, which the code does read.
- `pip check` reports broken requirements, but all are unrelated packages (google-generativeai, fastapi, langchain-*, …) sharing the machine — none touch hypelab's imports.
- Test run emits 3 warnings only: `audioread` shims for removed stdlib `aifc`/`sunau` (Python 3.14) and a GLib deprecation — cosmetic.
- All smoke DB writes went to `/tmp/bld_smoke.db` and `/tmp/bld_mig.db` (copies); the repo's `hypelab.db` was read, never written. `git status` clean at end of work.
- `faster_whisper` `doctor()` referenced in VERTICAL_SLICE_REPORT.md:69 no longer exists anywhere in code.
- Chromium available at `/usr/bin/google-chrome` (carousel fallback `/opt/pw-browsers/chromium` absent — fine, PATH search finds it).

## After (Phase 6) — same commands, compared with "Before"
| Step | Before | After | Change |
|---|---|---|---|
| *(filled in Phase 6)* | | | |
