# DECISIONS

### D-001 · No push for this program — 2026-09-29 · Tech Lead
- Context: A remote (origin=dynoshippedit/hypelab) exists from earlier work, and the kit's A5 says to push "if a remote and permission exist".
- Options considered: push the work branch for backup vs local-only.
- Decision & why: LOCAL COMMITS ONLY on devteam/review-2026-09-29. Parent task explicitly: "Push: NONE for this program. You are not authorized to push."
- Consequences: checkpoint commits frequently; nothing leaves the Threadripper.

### D-002 · REFACTOR_MODE=propose — 2026-09-29 · Tech Lead
- Context: Owner default per kit; structural changes are NEEDS APPROVAL.
- Decision & why: Architect designs the target structure and migration plan only. Any file move/rename/API/schema change goes to QUESTIONS.md as NEEDS-OWNER.
- Consequences: Phase 5 fixes behavior-preserving bug fixes within FIX_SCOPE S0-S3 only.

### D-003 · Test command — 2026-09-29 · Tech Lead
- Context: README says `python3 -m unittest discover -s tests -v`; prior verified state says pytest with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1, 191 passing.
- Decision & why: canonical command is `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/`. BLD reproduces the 191 baseline; DOC logs the README discrepancy as a DOC issue if real.
- Consequences: all lanes use the pytest form.
