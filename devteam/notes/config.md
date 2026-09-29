# HypeLab configuration — HYPELAB_HOME single root (D3 / T-019, 2026-09-29)

One variable owns every path: `HYPELAB_HOME`. Everything else derives from it
by default; each derived path has its own variable as an optional override.
At startup the CLI resolves, validates, and prints the configuration
(`hypelab/config.py`: `resolve_config` / `validate_config` / `print_config` /
`startup`). Secrets are never derived from the root and never printed.

## Variables

| Variable            | Default              | Purpose                              |
|---------------------|----------------------|--------------------------------------|
| HYPELAB_HOME        | /home/dino/hypelab   | Root of everything                   |
| HYPELAB_DB_PATH     | <home>/hypelab.db    | SQLite state & ledger                |
| HYPELAB_WORK_DIR    | <home>/work          | Job work dirs (work/<job_id>/)       |
| HYPELAB_MODELS_DIR  | /home/dino/hypelab/models | Read-mostly model caches (machine-global, not under home) |
| HYPELAB_OUTPUTS_DIR | <home>/outputs       | Build outputs (D4 target)            |
| HYPELAB_LOGS_DIR    | <home>/logs          | Log files                            |
| HYPELAB_TMP_DIR     | <home>/tmp           | Ephemeral temp files                 |
| HYPELAB_KITS_DIR    | <home>/kits          | Read-only content kits               |

## Legacy aliases (honored, deprecated)

- `HYPELAB_ROOT` → same as `HYPELAB_HOME` (`HYPELAB_HOME` wins if both set).
- `HYPELAB_DB` → same as `HYPELAB_DB_PATH` (`HYPELAB_DB_PATH` wins).

Tests use these aliases for isolation; they keep working unchanged.

## Not owned by the config module

`HYPELAB_LEASE_SECONDS` (lease override), `HYPELAB_CHROMIUM` (browser binary),
`HYPELAB_VERSION` — behavior unchanged.

## Secrets rule

A secret lives in its own environment variable (e.g. `HYPELAB_SOME_API_KEY`),
is never derived from the root, and is never printed. No secrets exist in the
app today; `tests/test_config.py::test_printed_config_has_no_secrets` guards
the invariant.
