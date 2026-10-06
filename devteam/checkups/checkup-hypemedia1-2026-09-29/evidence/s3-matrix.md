# S3 — review matrix (change checkup, 2 units x lenses)

## Unit: source-intake-validation (hypelab/watcher.py, hypelab/b2cli.py)
- COR: kind whitelist in add_source now exactly {yt_channel, rss, manual};
  any other kind raises WatcherError with the supported kinds named in the
  message. CLI Choice lists the same three. The http(s)-URL branch narrowed
  to reachable kinds. No other branch references twitch (grep-verified).
- ARC: two enforcement points (CLI parse, add_source) share one policy;
  no new modules, no signature changes, no schema changes.
- TST: 9 tests in tests/test_source_kinds.py cover intake rejection (twitch,
  unknown kind, kind-before-URL ordering), supported-kind acceptance
  (yt_channel, rss, manual), poll-time fail-closed for legacy rows, and the
  CLI surface (Choice rejection, --help content).
- DOC: `source add --help` lists only supported kinds. No user docs mention
  twitch (remaining mentions are historical devteam notes, intentionally
  untouched as records).
- SEC: intake is a fail-closed trust boundary (rights manifest + kind +
  allowlist). Rejecting unlistable kinds at intake removes the silent-dead
  path; no secrets/credentials handled here. No new attack surface.
- API: add_source signature unchanged; still raises WatcherError on bad
  input. Message text changed for unsupported kinds — grep confirms no
  test or caller matched on the old text.
- DAT: no schema or migration change. Supported-kind rows insert exactly as
  before. twitch rows could never be productive (poll always raised).
- REL: poll()/claim/release/retry/heartbeat paths untouched. A legacy
  twitch row (hand-written or pre-existing dev row) still fails closed at
  poll with "unknown source kind" — loud in logs, zero silent jobs.

## Unit: regression-tests (tests/test_source_kinds.py)
- COR: assertions pin the exact rejection message, CLI exit code 2, and
  --help content; fixtures follow test_allowlist.py conventions.
- ARC: single new test file; CliRunner pattern copied from test_cli_die.py;
  no conftest changes.
- TST: falsification demonstrated — 5/9 fail on pre-fix code (the 5 that
  encode the behavior change), 9/9 pass post-fix. The 4 that pass pre-fix
  pin invariants (supported kinds accepted, poll fail-closed preserved).
- DOC: module docstring states the falsification contract and the chief's
  fail-closed decision.

No NOT_APPLICABLE cells: every lens above carries a concrete observation.
