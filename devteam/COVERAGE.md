# COVERAGE
Legend: [ ] not started · [~] partial (give ranges) · [x] done · n/a not required for this tier/file · NOT REVIEWED (reason)
Lenses: COR correctness · SEC security · PRF performance · ARC architecture · UIX frontend/CLI-UX · DAT data · DOM domain (STR=media) · DOC docs

Tier rules (B4 Pass 2): High = every applicable lens; Medium = COR+SEC+ARC plus UIX/DAT/DOM where they apply; Low = COR only.
DOM=STR applies to render/ingest/reframe/transcode/probe files.

| Path | Lines | Lang | Purpose | Tier | COR | SEC | PRF | ARC | UIX | DAT | DOM | DOC |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| AGENTS.md | 2 | Markdown | Boot-time pointer to devteam/PLAYBOOK.md | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| ARCHITECTURE.md | 670 | Markdown | Root design doc (8 parts + 7 required outputs) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| CLAUDE.md | 2 | Markdown | Boot-time pointer to devteam/PLAYBOOK.md | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| .gitignore | 27 | config | Ignores /work/, /hypelab.db*, models/, pycache | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| fixtures/script.txt | 9 | text | Canonical demo script (9 lines), used by tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| hypelab/__init__.py | 5 | Python | Package marker; HYPELAB_VERSION = 0.2.0 | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| hypelab/align.py | 607 | Python | Word alignment: forced align + faster_whisper backend | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/attribution.py | 240 | Python | Attribution: what_worked (Book 2, section 11) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/authorize.py | 80 | Python | Authorizations: explicit approval rows (Book 3, section 5) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/b2cli.py | 453 | Python | Book 2 (Clip Mine) CLI commands | High | [ ] | [ ] | [ ] | [ ] | [ ] | n/a | n/a | n/a |
| hypelab/book3cli.py | 354 | Python | Book 3 (Hype Layer) CLI commands | High | [ ] | [ ] | [ ] | [ ] | [ ] | n/a | n/a | n/a |
| hypelab/boundary.py | 259 | Python | Boundary refinement + cold open (Book 2, section 7) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/campaigns.py | 182 | Python | Campaigns as versioned data (Book 2, section 3) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/captions.py | 111 | Python | Word-level caption cards -> ASS subtitles via pysubs2 | Medium | [ ] | [ ] | n/a | [ ] | n/a | n/a | [ ] | n/a |
| hypelab/carousel.py | 441 | Python | Mode C carousel: spec -> HTML -> PNG via headless Chromium | High | [ ] | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a |
| hypelab/cli.py | 997 | Python | The only front door: Book 1 commands + claim-loop worker | High | [ ] | [ ] | [ ] | [ ] | [ ] | n/a | n/a | n/a |
| hypelab/compliance.py | 389 | Python | The compliance gate (Book 2, section 9) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/consent.py | 280 | Python | Consent ledger: the hard gate (Book 3, section 5) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/cut.py | 301 | Python | Cut compliant 9:16 clips from moments (Book 2, section 8) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | [ ] | n/a |
| hypelab/db.py | 147 | Python | SQLite connections + migration runner | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/edl.py | 210 | Python | EDL (Edit Decision List) build + validate | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/feedback.py | 201 | Python | Closing the loop: feedback runs (Book 3, section 9) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/gates.py | 478 | Python | Quality gates: fail the job, never ship it | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | [ ] | n/a |
| hypelab/ingest.py | 310 | Python | Ingest: rights-gated source download/hash (Book 2, 5+5a) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | [ ] | n/a |
| hypelab/invites.py | 218 | Python | Invite-status polling (Book 3, section 8) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/jobs.py | 140 | Python | Job lifecycle: state machine + creation | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/kits.py | 180 | Python | Brand Kit store over kits table (immutable v1 seed) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/manifests.py | 381 | Python | Content-addressed asset manifests (sha256) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | [ ] | n/a |
| hypelab/metrics.py | 136 | Python | Metrics polling with provenance (Book 2, section 11) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/pitch.md | 15 | Markdown | Pitch template rendered by pitch.py | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| hypelab/pitch.py | 275 | Python | Pitch generator (Book 3, section 6) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/publish/__init__.py | 260 | Python | Publish orchestration + consent re-check at publish | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/publish/base.py | 79 | Python | Publish adapter interface, LiveRefused, capability checks | High | [ ] | [ ] | [ ] | [ ] | n/a | n/a | n/a | n/a |
| hypelab/publish/dryrun.py | 108 | Python | Dry-run publisher: the only working publish backend | Medium | [ ] | [ ] | n/a | [ ] | n/a | n/a | n/a | n/a |
| hypelab/publish/meta.py | 74 | Python | Native Meta (Instagram Graph API) adapter; live refuses | Medium | [ ] | [ ] | n/a | [ ] | n/a | n/a | n/a | n/a |
| hypelab/publish/providers.py | 111 | Python | Postiz+Zernio+Ayrshare capability records; live refuses | High | [ ] | [ ] | [ ] | [ ] | n/a | n/a | n/a | n/a |
| hypelab/queue.py | 232 | Python | Queue: leases, atomic claim, heartbeat, release, fail, ledger | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/reframe.py | 411 | Python | Reframe 16:9 -> 9:16 (ffmpeg, Book 2, section 8) | High | [ ] | [ ] | [ ] | [ ] | n/a | n/a | [ ] | n/a |
| hypelab/render.py | 576 | Python | Deterministic ffmpeg render chains | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | [ ] | n/a |
| hypelab/score.py | 420 | Python | Moment scoring with versioned weights (Book 2, section 6) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | [ ] | n/a |
| hypelab/script.py | 85 | Python | Script text -> timed beats (parses user script text) | High | [ ] | [ ] | [ ] | [ ] | n/a | n/a | n/a | n/a |
| hypelab/signals.py | 116 | Python | Tier 3 external audience evidence (Book 2, section 6) | Medium | [ ] | [ ] | n/a | [ ] | n/a | n/a | n/a | n/a |
| hypelab/state_migrations.py | 31 | Python | Book 3 state-machine wiring (loads state_3_0.py by path) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/tray.py | 203 | Python | The clip tray: manual upload handoff (Book 2, section 10) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/util.py | 226 | Python | Shared helpers: time, ids, hashing, media probing, atomic IO | High | [ ] | [ ] | [ ] | [ ] | n/a | n/a | [ ] | n/a |
| hypelab/watcher.py | 293 | Python | Source watcher (Book 2, section 4) | Medium | [ ] | [ ] | n/a | [ ] | n/a | [ ] | n/a | n/a |
| hypelab/weights/cut_defaults.json | 0 | JSON | Versioned cut defaults (data) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| hypelab/weights/weights_v1.json | 0 | JSON | Versioned scoring weights v1, status uncalibrated (data) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| kits/cerebratico/kit.json | 49 | JSON | Seed brand-kit fixture (adapted at seed time) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| migrations/0001_book1_foundation.sql | 241 | SQL | Baseline schema; pre-creates Book 2/3 tables | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| migrations/0002_book2_clip_mine.sql | 64 | SQL | Additive ALTERs + moment_dedup, compliance_log | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| migrations/0003_book3_hype_layer.sql | 157 | SQL | Additive: authorizations, post_placements, priors, ... | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| migrations/state_3_0.py | 65 | Python | Versioned state-machine migration (additive-only assert) | High | [ ] | [ ] | [ ] | [ ] | n/a | [ ] | n/a | n/a |
| README.md | 59 | Markdown | Setup + walkthrough docs (STALE vs current CLI) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| VERTICAL_SLICE_REPORT.md | 173 | Markdown | Run report from an older CLI generation (STALE) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/fixtures_book2/campaign.json | 50 | JSON | Book 2 test fixture | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/fixtures_book2/info.json | 73 | JSON | Book 2 test fixture | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/fixtures_book2/listing.json | 12 | JSON | Book 2 test fixture | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/fixtures_book2/rights.json | 7 | JSON | Book 2 test fixture | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/fixtures_book2/source.mp4 | 23124 | binary | Book 2 test fixture (binary) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/fixtures_book2/words.json | 6045 | JSON | Book 2 test fixture | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/fixtures_book3/dryrun_fixtures.json | 0 | JSON | Book 3 dry-run fixture | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/fixtures_book3/slides_fixture.json | 55 | JSON | Book 3 carousel fixture | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/test_align.py | 240 | Python | Align tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/test_book2.py | 715 | Python | Book 2 (Clip Mine) tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/test_book3.py | 700 | Python | Book 3 (Hype Layer) tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/test_cli.py | 402 | Python | CLI tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/test_foundation.py | 506 | Python | Foundation (jobs/queue/db/state) tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/test_gates.py | 421 | Python | Gates tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/test_manifests.py | 237 | Python | Manifests tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| tests/test_pipeline.py | 306 | Python | End-to-end pipeline tests | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/beat:b1.mp4 | 8403 | binary | STALE generated beat clip (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/beat:b2.mp4 | 8477 | binary | STALE generated beat clip (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/beat:b3.mp4 | 8363 | binary | STALE generated beat clip (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/beat:b4.mp4 | 8393 | binary | STALE generated beat clip (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/beat:b5.mp4 | 8425 | binary | STALE generated beat clip (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/beat:b6.mp4 | 8431 | binary | STALE generated beat clip (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/music.mp3 | 3030 | binary | STALE generated music bed (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/vo.mp3 | 475 | binary | STALE generated VO (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/assets/vo_words.json | 311 | JSON | STALE alignment JSON (dup of vo.words.json) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/caption_proof.png | 1412 | binary | STALE render proof screenshot | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/master.mp4 | 41240 | binary | STALE 9:16 master render | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/master_1x1.mp4 | 30602 | binary | STALE 1:1 master render | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/quality_report.json | 60 | JSON | STALE gate results JSON | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/render/captions.ass | 27 | ASS | STALE ASS captions (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/render/render_record.json | 25 | JSON | STALE render record (legacy jobs/ layout) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/script.txt | 9 | text | STALE script copy (dup of fixtures/script.txt) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |
| jobs/job_c656669a5147/vo.words.json | 311 | JSON | STALE alignment JSON (dup of assets/vo_words.json) | Low | [ ] | n/a | n/a | n/a | n/a | n/a | n/a | n/a |

## Counts
Total in-scope files: 88 (88 = 104 tracked - 16 devteam/ files)
High: 29 · Medium: 14 · Low: 45

## Excluded (per B1 OUT OF SCOPE)
| Path | Reason |
|---|---|
| devteam/ (17 files) | review workspace, out of scope per B1 |
| hypelab/__pycache__/, tests/__pycache__/, .pytest_cache/ | generated bytecode/cache |
| hypelab.db, hypelab.db-shm, hypelab.db-wal | untracked local runtime state (BLD: review whether they belong) |
| work/ (untracked on disk) | job working dirs, gitignored |
| models/, ~/.cache | model caches, gitignored/read-mostly |

## Notes
- Required cells remaining: count via `grep -cE '\[ \]' devteam/COVERAGE.md`.
- Files >500 lines (High by size rule): hypelab/cli.py (997), hypelab/align.py (607), hypelab/render.py (576); tests excluded from sizing as fixtures.
- Binary job outputs in jobs/job_c656669a5147/ are Low/COR-only: review = whether they belong in git (MAP-001), not their contents.
