"""Quarantine support for timing-sensitive tests (hl-cycle-13, T-044).

Tests marked @pytest.mark.quarantine are SKIPPED in the default gate and
run only with --run-quarantined. Rationale: wall-clock / process-kill
tests flake under load, and "passes on re-run" must not become normal for
the gate (owner decision 2026-09-29).
"""


def pytest_addoption(parser):
    parser.addoption(
        "--run-quarantined",
        action="store_true",
        default=False,
        help="run tests marked quarantine (skipped by default)",
    )


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "quarantine(reason): timing-sensitive test, skipped in the default "
        "gate; run explicitly with --run-quarantined. Tracked in "
        "devteam/TASKS.md.",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--run-quarantined"):
        return
    import pytest

    skip_q = pytest.mark.skip(
        reason="quarantined: timing-sensitive; run with --run-quarantined "
        "(see devteam/TASKS.md)"
    )
    for item in items:
        if item.get_closest_marker("quarantine"):
            item.add_marker(skip_q)
