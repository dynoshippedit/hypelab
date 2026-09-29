# BASELINE
Captured: (pending — Build & Release Engineer) · commit <sha> · by BLD

## Environment
| Tool | Version |
|---|---|
| (pending) | |

## Before any change
| Step | Command | Exit | Result summary | Duration |
|---|---|---|---|---|
| install | (no manifest — record what BLD does) | | | |
| build | n/a (Python, no build step) | | | |
| test | PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/ | | target: reproduce 191 passing | |
| lint | | | | |
| typecheck | | | | |
| run / smoke | python3 -m hypelab.cli doctor | | | |
| dependency audit | pip-audit or manual | | | |
| secret scan | gitleaks or B6 patterns over git log -p | | | |

## Notes / deviations

## After (Phase 6) — same commands, compared with "Before"
| Step | Before | After | Change |
|---|---|---|---|
