# HypeLab queue: dedupe + reprioritization proposal (2026-09-29)

Analysis task HL-DEDUPE per Dino's direct order. **Proposal only — `devteam/TASKS.md`
was not edited** (hl-cycle-05 is working T-005; avoid conflicts).

## Queue reality check

- The queue is **42 tasks (T-001–T-042)**, not 200. The ~200 lane findings were
  already triaged into 42 tasks in hl-cycle-01; every finding ID is accounted for
  exactly once in `devteam/TASKS.md` (with two exceptions found below).
- Status: T-001…T-004 VERIFIED · T-005 IN PROGRESS (hl-cycle-05, do not touch) ·
  T-011, T-013, T-019, T-040 BLOCKED on owner decisions · rest READY.
- This proposal adds **17 new root-cause dedupe clusters (C1–C17)** beyond what
  triage already merged, **parks 5 findings**, and reorders everything into Dino's
  tiers: (A) security/money → (B) crashes/data loss → (C) rest.

## Triage corrections found during this pass

1. **BLD-004 double-counted**: it appears in T-038's group AND in T-041's
   `BLD-004/006/007/009/011/012/013` list. It belongs to T-038 (README rewrite).
2. **UIX-560 already fixed**: `campaign refresh-budget` TypeError was repaired by
   T-001 (VERIFIED). UIX-560 is its UX face — absorb into T-001, no new work.
3. **UIX-561 / REV-713 are the same defect** (`hypelab watch` Ctrl-C traceback).
   Dedupe the pair, then treat as one.

---

## Dedupe clusters (root cause + absorbed IDs + primary)

### C1 — Align/gate beat↔word mapping computed three inconsistent ways
Root: `_do_align` and `gate_word_confidence` disagree on what a beat's words are
(dead `min_word_prob=0.0` filter; original-line beats mapped onto normalized words;
`_WORD_RE` vs `str.split()` tokenizers). Fixing structurally (persist normalized
lines / per-beat word index ranges at align time, one statistic) resolves all three.
- Primary: **T-008** (M) · Absorbs: T-006, T-024, UIX-566 (help text promises the
  dead BUG-004 routing — fix the text when the routing is fixed)

### C2 — Queue state transitions not atomic under concurrency
Root: legality checks happen outside transactions; state UPDATE and audit `log()`
are separate autocommit statements.
- Primary: **T-007** (S, S1) · Absorbs: DAT-354, DAT-355 (TST-007's two-process
  race test already covers this cluster's verification)

### C3 — No enforced CLI error boundary: raw tracebacks instead of `error:` exits
Root: input validation / lookups scattered outside the `_die` convention at CLI
entry points. Same one-line fix shape everywhere (validate early, `_die` cleanly).
- Primary: **T-020** (S) · Absorbs: BUG-012, BUG-014, BUG-015, ENV-657, REV-708,
  REV-711, REV-713+UIX-561 (same watch Ctrl-C defect), REV-716, REV-753, UIX-562,
  REV-763

### C4 — Documented money flows have no code
Root: cost ledger and payout columns exist in schema/docs but nothing writes them.
T-013's owner decision (wire vs remove) gates the whole cluster.
- Primary: **T-013** (BLOCKED — owner decision) · Absorbs: T-017, DAT-357
  (float-vs-cents only matters if wiring proceeds)

### C5 — URL allowlist/validation is duplicated substring matching with divergent verdicts
Root: `watcher.source_allowed` vs `compliance.chk_source_allowed` re-implement
"is this URL allowed"; neither parses hosts; allowlist never applied to feed URLs.
One shared `allowlist_verdict()` + scheme/host validation at `add_source` fixes all.
- Primary: **ARC-310** (S, in T-041) · Absorbs: REV-714 (S3 — `evilyoutube.com`
  passes the money-check allowlist), SEC-103 (S4)

### C6 — No fetch policy for untrusted inputs
Root: RSS/yt-dlp/ffmpeg fetch without size caps or sandboxing.
- Primary: **T-032** (M — triage already noted PAT-602 here) · Absorbs: PAT-602

### C7 — Unescaped interpolation into generated artifacts
Root: kit CSS values, drawtext `enable`, reframe split boxes interpolated raw.
Same fix: validate/allowlist at the sink.
- Primary: **STR-454** (XS, S3) · Absorbs: SEC-105, SEC-106 (S4)

### C8 — Weights resolution/loading is ad hoc
Root: three weights-dir resolutions; lexicographic "latest" sort; no schema
validation on weights files.
- Primary: **ARC-311** (S3, in T-041) · Absorbs: REV-752, REV-771

### C9 — Env-var config model incoherent; paths hardcoded to one machine
Root: `HYPELAB_ROOT` doesn't move DB/model cache; documented vars never read;
absolute `/home/dino/hypelab` paths. T-019's owner decision gates the cluster.
- Primary: **T-019** (BLOCKED — owner decision) · Absorbs: BLD-005, BLD-006,
  UIX-568, BLD-009

### C10 — No declared model-fetch policy
Root: faster-whisper/HF downloads have no pin, checksum, size guard, or offline
story; bootstrap caches undocumented.
- Primary: **T-018** (S, S2) · Absorbs: T-021 (docs/honor-HF_HUB_OFFLINE half of
  the same policy). T-015 stays separate — it's a fail-fast ordering bug.

### C11 — No single owner of clip/job lifecycle
Root: transition logic split across three modules lets submission re-gate
synthesize placeholder clips and request illegal tray transitions.
- Primary: **T-025** (M) · Absorbs: T-023 (REV-703/704 are instances of the
  missing owner)

### C12 — T-001 absorbs UIX-560 (refresh-budget TypeError already fixed, VERIFIED)
### C13 — T-005 absorbs UIX-569 ("hash unchanged, skipping" message must change with the skip-path fix; T-005 in progress)
### C14 — T-036 absorbs BLD-007 (tests set `HYPELAB_WORK_DIR` the code never reads — test hygiene)
### C15 — T-038 absorbs MAP-005 (stale `__init__` docstring), BLD-008 (document `HYPELAB_CHROMIUM`; covers DOC-024's row). BLD-004 confirmed here (see correction 1).
### C16 — T-039 absorbs PRF-505 (duplicate ffprobe — same redundant-probe root as PRF-502)
### C17 — Dead-code cleanup sweep: PAT-600 absorbs REV-710 (`INVITE_STATUSES` dead) and MAP-004 (duplicate `import json` — trivially fixed in the same sweep)

---

## Parked findings (5)

Parked = in stubs, dead code, or environment — fixing them as engineering tasks
has no value. Count: **5**.

1. **REV-767** — `NativeMetaPublisher` duplicates `_FixtureDelegatingPublisher.create_post`
   instead of subclassing. Lives in `hypelab/publish/meta.py`. The entire publish
   layer is dry-run fixtures by design (live publishing structurally impossible —
   four independent refusals, SEC lane). Refactoring class hierarchy in code that
   can never go live: PARKED.
2. **PRF-511** — `_constrain_to_script` O(N·M) via difflib. PAT-600 proves the
   function has zero callers (dead). Optimizing dead code: PARKED (dies with the
   C17 cleanup sweep).
3. **BLD-012** — torch is a CUDA build on a CPU-only box. Environment/package note,
   not a code defect; "fix" is reinstalling torch. PARKED as ops note.
4. **BLD-013** — `openai-whisper` installed but unused. Package hygiene
   (`pip uninstall`), not engineering work. PARKED as ops note.
5. **DAT-361** — `edge-tts` referenced by docs, zero code hits. No code action;
   the doc claim is removed by T-038's claims audit. PARKED (no standalone work).

Considered and NOT parked: the 8 carousel findings (REV-707/709/715/719, ARC-309,
ARC-314, PRF-506, +REV-708→C3). The carousel is demo-flavored (hardcoded kicker)
but it is real, reachable code with no recorded replacement plan — parking it
would need Dino's explicit call.

---

## Reprioritized work order

### Tier A — Security / money (first)

| # | Work | Sev | Effort | State |
|---|------|-----|--------|-------|
| A1 | T-007 + C2 — claim()/fail() races; queue txn atomicity (DAT-354/355) | S1 | S | READY |
| A2 | C5 — URL allowlist verdicts (ARC-310 + REV-714 + SEC-103) | S3/S4 | S | READY |
| A3 | T-032 + C6 — untrusted-fetch bounds/sandboxing (+PAT-602) | S2 | M | READY |
| A4 | STR-453 — ASS caption escaping residual | S3 | XS | READY |
| A5 | T-029 — authorizations expire/revoke | S3 | M | READY |
| A6 | T-030 — consent expiry format validation | S3 | S | READY |
| A7 | T-031 — CSV formula injection | S3 | XS | READY |
| A8 | C7 — unescaped artifact sinks (STR-454 + SEC-105/106) | S3/S4 | XS | READY |
| A9 | SEC-101 — pitch↔grant scope correspondence | S4 | S | READY |
| A10 | C4 — money pipeline (T-013 + T-017 + DAT-357) | S2/S3 | M | **BLOCKED — owner decision** |

### Tier B — Crashes / data loss (second)

| # | Work | Sev | Effort | State |
|---|------|-----|--------|-------|
| B1 | C1 — align beat↔word mapping (T-008 + T-006 + T-024 + UIX-566) | S1 | M | READY |
| B2 | T-010 — dependency manifest (clean-clone install impossible) | S1 | S | READY |
| B3 | T-012 — CLI `gates` accepts worker-claimed `gating` | S2 | XS | READY |
| B4 | T-015 — fail fast before model download on degenerate scripts | S2 | XS | READY |
| B5 | C11 — clip/job lifecycle owner (T-025 + T-023) | S2 | M | READY |
| B6 | T-022 — clearance flow write-only | S2 | S | READY |
| B7 | T-014 — `render --aspect` mis-certifies `ready` | S2 | M | READY |
| B8 | C3 — CLI error-hygiene sweep (T-020 + 11 findings) | S2/S3 | S | READY |
| B9 | T-016 — fixture provenance stamped calibration-grade | S2 | XS | READY |
| B10 | DAT-356 — render() dual-writes file+DB without atomicity | S3 | S | READY |
| B11 | PAT-601 — quarantine unique-name TOCTOU (evidence overwrite) | S3 | S | READY |
| B12 | DAT-358 — concurrent migration race on fresh DB | S3 | S | READY |
| B13 | STR-455 — work dir unbounded; SIGKILL orphans, no reaper | S3 | S | READY |
| B14 | BUG-013 — failed `attach` leaves orphan file | S3 | XS | READY |
| B15 | PRF-508 — full-file audio load into RAM (OOM risk) | S3 | M | READY |
| B16 | C8 — weights resolution/loading (ARC-311 + REV-752 + REV-771) | S3/S4 | S | READY |
| B17 | REV-755 — tray re-run leaves zombie dirs | S3 | S | READY |
| B18 | REV-712 — `check_slots` vs render preflight disagree | S3 | S | READY |
| B19 | REV-717 — `signals["duration"]` invents 0.0 fallback | S3 | XS | READY |
| B20 | ARC-305 — library functions commit the caller's connection | S3 | S | READY |
| B21 | ARC-308 — `worked` (read-named) writes to the DB | S3 | S | READY |
| B22 | PAT-603 — `work_dir` atomic-write docstring lie | S3 | S | READY |
| B23 | C9 — env config (T-019 + BLD-005/006/009 + UIX-568) | S2/S3 | M | **BLOCKED — owner decision** |

### Tier C — Everything else

| # | Work | Sev | Effort | State |
|---|------|-----|--------|-------|
| C-a | T-009 — model caching (every job reloads wav2vec2/Whisper) | S1 | M | READY |
| C-b | T-026 — raw SQL / duplicated ranking in CLI | S2 | S | READY |
| C-c | T-027 — render provenance split; Book 2 persists no EDL | S2 | S | READY |
| C-d | T-028 — source-kind registry in three places | S2 | S | READY |
| C-e | T-033 — "deterministic render" overclaims byte-determinism | S2 | S | READY |
| C-f | T-034 / T-035 / T-036 (+C14 BLD-007) — test gaps | S2/S3 | S/M | READY |
| C-g | T-037 — retry command (after T-011 decision) | S2 | M | READY* |
| C-h | T-039 + C16 — perf fixes (+PRF-505) | S2/S3 | M | READY |
| C-i | T-042 — unify `best_views` aggregation semantics | S3 | XS | READY |
| C-j | Carousel group: REV-707, REV-709, REV-715, REV-719, ARC-309, ARC-314 | S3 | S | READY |
| C-k | ARC-306, ARC-312, ARC-313, ARC-315 — structural hygiene | S3 | M | READY |
| C-l | DAT-359, DAT-360, DAT-363 — indexes, FKs, provenance default | S3/S4 | S | READY |
| C-m | ENV-654, ENV-655, ENV-656 — /tmp hardcode, compute defaults, import-time global | S3/S4 | S | READY |
| C-n | PRF-506, PRF-507, PRF-509, PRF-510 — remaining perf | S3/S4 | S/M | READY |
| C-o | REV-751, REV-754, REV-756–766 (excl. absorbed), REV-768, REV-769 — correctness S3/S4 | S3/S4 | XS/S | READY |
| C-p | UIX-550/551/553/554/555/556/557/558/559/563/564/565/567/570 — UX S3/S4 | S3/S4 | XS/S | READY |
| C-q | C17 — dead-code cleanup sweep (PAT-600 + REV-710 + MAP-004) | S3 | S | READY |
| C-r | T-038 (+C15: MAP-005, BLD-008; BLD-004 confirmed here) — README/ARCHITECTURE rewrite | S2–S4 | L | READY — **do LAST per kit** |

### Owner decisions needed (block Tier A/B items above)

- **T-011** (BUG-007/TST-003): auto-requeue below MAX_ATTEMPTS vs operator review
  (T-037 retry command follows the decision).
- **T-013 / C4**: wire `charge()` + payout fill vs remove the money surface.
- **T-019 / C9**: single-root (`HYPELAB_ROOT` moves DB + model cache) vs documented split.
- **T-040**: approve `git rm -r jobs/` + `.gitignore` for the ~34–39 MB tracked outputs.

---

## Unclassifiable findings

None. Every finding ID maps to exactly one cluster, task, or parked entry above.
Note: **STR-456** is an observation (single-pass loudnorm by design), not a defect —
no work, per the original triage.

## Suggested dispatch order (first 5 workable)

1. A1 (T-007+C2) — S1 queue integrity, small.
2. A2 (C5) — security boundary, small.
3. B1 (C1) — S1 silent misattribution, medium.
4. B2 (T-010) — S1 build/install, small.
5. A3 (T-032+C6) — fetch sandboxing, medium.

Then drain Tier A, then Tier B, then Tier C; T-038 docs last. Blocked items proceed
only on Dino's decisions above.
