# S1 - executable baseline

Gate receipt: devteam/checkups/repair-fhl1-2026-09-29/checks/baseline/check-baseline-suite.json
(log: checks/baseline/check-baseline-suite.json.log)

Command: python3 -m pytest tests/ -q --ignore=tests/test_fhl1_lease_loss.py
Cwd: /home/dino/hypelab - exit_code 0, timed_out false, source unchanged
across the run (before/after digests equal the initial snapshot digest).

Result: 312 passed, 3 warnings in 213.79s - 0 failures, 0 skipped.
Matches the principal reviewer's 2026-09-29 baseline (312 passed, 0 skipped
on master@5c185ba).

This is the pre-repair behavioral baseline: the temp+rename mechanism in
render() was already present and the suite was green; the repair adds the
3 F-HL-1 regression tests on top (final check expects 315 passed).
T-044 settlement verified intact in this baseline: ffmpeg 8.1.2 pin
enforced, deterministic crash-recovery test running un-quarantined.
