# Env inventory — HypeLab (BLD, 2026-09-29)
Source of truth: `grep -rnE 'os\.(environ|getenv)'` over `hypelab/` + `tests/`,
cross-checked against README.md, ARCHITECTURE.md, VERTICAL_SLICE_REPORT.md,
AGENTS.md, CLAUDE.md.

| Variable | Read at | Default | Documented where | Secret? | Required? | Verdict |
|---|---|---|---|---|---|---|
| `HYPELAB_ROOT` | cli.py:87, b2cli.py:47, book3cli.py:43 | `/home/dino/hypelab` (`DEFAULT_ROOT`) | cli.py:19-20 docstring; b2cli.py:6; book3cli.py:6 | no | no (has default) | OK — read + documented |
| `HYPELAB_DB` | cli.py:91, b2cli.py:51, book3cli.py:47 | repo `hypelab.db` (`db.connect(None)`) | cli.py:19 docstring | no | no | OK — read + documented |
| `HYPELAB_LEASE_SECONDS` | cli.py:103 | `1800` (`queue_mod.LEASE_TTL_S`) | cli.py:21 docstring ("tests use a short one") | no | no | OK — read + documented. Note: `int()` parse, `ValueError` → silently 0 (no error); negative → ignored by `> 0` guard |
| `HYPELAB_CHROMIUM` | carousel.py:53 | PATH search (`google-chrome`, `chromium`, …), then `/opt/pw-browsers/chromium` | **only in the error message** (carousel.py:68) — no doc, no README | no | no | ⚠️ **read but effectively undocumented**; selects the binary the app executes → BLD-008 |
| `HYPELAB_HOME` | **never read** | n/a | README.md:16 ("default; the DB + jobs/ live here"), VERTICAL_SLICE_REPORT.md:45 | no | n/a | ⚠️ **documented but unused** — the README's setup step exports a variable the code ignores → BLD-005 |
| `HYPELAB_CACHE` | **never read** | n/a | ARCHITECTURE.md:381 ("`~/.cache/hypelab/` (or `$HYPELAB_CACHE`)") | no | n/a | ⚠️ **documented but unused** → BLD-006 |
| `HYPELAB_WORK_DIR` | **never read** | n/a | not documented; set by tests at test_book2.py:513,545 via `monkeypatch.setenv` | no | n/a | ⚠️ **set by tests but ignored by code** — dead test fixture config; suggests the tests don't isolate what they claim → BLD-007 (flagged for TST lane too) |

## Flags
- **Read but undocumented:** `HYPELAB_CHROMIUM` (BLD-008, S1 — names the executed binary).
- **Documented but unused:** `HYPELAB_HOME`, `HYPELAB_CACHE` (BLD-005, BLD-006, S3).
- **Set but unused:** `HYPELAB_WORK_DIR` in tests (BLD-007, S3).
- **Insecure defaults:** none — no secrets, tokens, or credentials are read from the environment at all; all four live variables are paths/durations. README.md:10 confirms the design intent ("no paid APIs; no credentials").
- **Hardcoded environment (B6 pattern):** `DEFAULT_ROOT = "/home/dino/hypelab"` (cli.py:57, b2cli.py, book3cli.py); shim `/home/dino/.local/bin/hypelab` does `cd /home/dino/hypelab`; carousel.py:64 fallback `/opt/pw-browsers/chromium`. → BLD-009.
