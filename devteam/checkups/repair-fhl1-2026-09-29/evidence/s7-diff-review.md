# S7 - diff challenge (SELF_REVIEW)

The repair diff is test-only: tests/test_fhl1_lease_loss.py added;
hypelab/render.py and hypelab/cli.py UNCHANGED (git diff confirms).

Challenge answers:

- Cause vs symptom: the corruption mechanism the finding feared (two
  ffmpegs interleaving on one path) cannot occur - verified by tracing
  every write to the final path (single os.replace) and every -y target.
  The repair pins this with tests rather than changing code that is
  already correct; changing correct code to look fixed would be the risk.
- Could the regression tests pass against the broken implementation? NO -
  demonstrated by the negative control (all 3 fail when render() writes
  directly to out). The tests assert on observable behavior (decodable
  final file, byte-identity, argv target), not on implementation details.
- Ordering/retries/auth/data semantics: untouched (no product change).
- Assertions weakened? No: video byte-identity uses the T-044-proven
  determinism; the kill-simulation asserts exact byte equality of the
  pre-existing output; no thresholds were relaxed and no tests were
  skipped or deleted.
- The heartbeat/lease policy is deliberately unchanged (chief direction);
  recorded as QUEUED finding F-HL-1a with the owner decision outstanding,
  not hidden.
- Temp-file hygiene: an early test iteration leaked two junk files into
  the repo root; both removed and git status verified clean of them.
