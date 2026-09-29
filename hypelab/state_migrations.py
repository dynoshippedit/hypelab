"""Book 3 state-machine wiring.

The canonical versioned record lives in migrations/state_3_0.py (per
improved Book 3, section 2). This module loads it by file path — the
migrations/ directory is not a package — and re-exports it for jobs.py.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

_MIGRATION_FILE = (
    Path(__file__).resolve().parent.parent / "migrations" / "state_3_0.py"
)


def _load():
    spec = importlib.util.spec_from_file_location(
        "hypelab_state_3_0", _MIGRATION_FILE
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load state migration {_MIGRATION_FILE}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_mod = _load()

STATE_MIGRATIONS = _mod.STATE_MIGRATIONS
apply_state_migrations = _mod.apply_state_migrations
