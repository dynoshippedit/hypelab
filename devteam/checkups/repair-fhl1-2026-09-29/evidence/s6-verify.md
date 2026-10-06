# S6 - verification against resulting source

Gate receipt: devteam/checkups/repair-fhl1-2026-09-29/checks/final/check-final-suite.json
(log: checks/final/check-final-suite.json.log)

Command: python3 -m pytest tests/ -q
Cwd: /home/dino/hypelab - exit_code 0, timed_out false, source unchanged
across the run.

Result: 315 passed, 3 warnings in 218.51s - 0 failures, 0 skipped.
Delta vs baseline (312 passed): exactly the 3 new F-HL-1 regression tests,
all green:

- test_concurrent_workers_no_partial_final_output
- test_killed_worker_leaves_final_output_intact
- test_ffmpeg_never_targets_final_path

No pre-existing test changed outcome; no regressions introduced. T-044
settlement intact: ffmpeg 8.1.2 pin enforced, relaxed -40 dBFS audio
assertion green, deterministic crash-recovery test un-quarantined and
passing. Source identity at final: master@5c185ba + tests/test_fhl1_lease_loss.py
(new, untracked); hypelab/render.py and hypelab/cli.py byte-identical to HEAD.
