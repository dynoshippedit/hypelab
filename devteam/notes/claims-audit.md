# Claims audit — HypeLab docs vs code (DOC, Phase 1)

Auditor: DOC (Product & Docs Auditor). Date: 2026-09-29. Branch: devteam/review-2026-09-29.
Method: every factual claim in README.md, ARCHITECTURE.md, VERTICAL_SLICE_REPORT.md and
hypelab/pitch.md checked against the code on the Threadripper (read-only). Commands run:
`python3 -m hypelab.cli --help`, `python3 -m hypelab.cli doctor` (fails: no such command),
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/` → **191 passed** in 198.64s.

## P4 card — what this app is

HypeLab is a Python CLI pipeline for AI-assisted short-form video production. An operator
seeds an immutable brand kit, creates a job from a script, attaches voiceover/music/clips,
and a deterministic ffmpeg renderer — driven by a validated edit decision list (EDL) built
from faster-whisper word alignment — produces captioned, platform-formatted MP4s that must
pass quality gates (duration, loudness, first frame, hook budget, caption safety, slots,
geometry, word confidence) before the job is marked ready. A job-level queue with
30-minute leases, atomic claims, heartbeats and crash recovery executes pipeline stages
(align/render/gates, plus Book 2 clip-mine ingest/score); a consent ledger plus an explicit
operator authorization row hard-gate publishing, and every publish adapter's live path
currently refuses — only fixture-backed dry-runs work, with zero live network calls.
Book 2 adds a clip mine (campaign → source → moments → scored cuts → compliance tray)
and Book 3 adds a hype layer (carousel renderer, pitch/outreach, consent-gated dry-run
publish, metrics polling that honestly records "unavailable", and n≥30-gated attribution).
Nothing is published for real; no paid APIs and no credentials are used.

## Summary counts

| Doc | TRUE | FALSE | PARTIAL | UNVERIFIABLE | N/A |
|---|---|---|---|---|---|
| README.md | 7 | 10 | 5 | 0 | 0 |
| ARCHITECTURE.md | 12 | 21 | 18 | 3 | 0 |
| VERTICAL_SLICE_REPORT.md | 11 | 0 | 2 | 2 | 0 |
| hypelab/pitch.md | 0 | 0 | 0 | 0 | 1 (template, no claims) |
| **Total** | **30** | **31** | **25** | **5** | **1** |

The FALSE/PARTIAL cluster is almost entirely **staleness**: the docs describe the
2026-09-28 vertical-slice implementation (task-level queue, `tasks` table, `services.py`,
argparse CLI, slice-era EDL schema), while the code has since been rewritten as the
"improved" Books 1–3 (job-level queue, click CLI, new EDL schema, publish/ package).
The VERTICAL_SLICE_REPORT is a dated historical record and is accurate as such;
README.md and ARCHITECTURE.md present slice-era facts as current and are the problem.

## Claims table

Legend: source `path:line` (repo-rooted). Verdicts: TRUE / FALSE / PARTIAL / UNVERIFIABLE.

### README.md

| # | Claim | Source | Verdict | Evidence |
|---|---|---|---|---|
| R-01 | Title: "HypeLab v2 — vertical slice" | README.md:1 | TRUE | Label matches; note: repo HEAD now covers Books 1–3, so the title undersells scope (DOC-022, S4). |
| R-02 | ARCHITECTURE.md is "8 parts + 7 required outputs" | README.md:3 | TRUE | ARCHITECTURE.md has 8 "Part" sections and 7 "Required outputs" sections. |
| R-03 | "What runs today (M1–M4 + M6 gate)": Mode A Original pipeline script → VO → word alignment → validated render.json → deterministic ffmpeg render → captioned MP4 → quality gates | README.md:5-9 | PARTIAL | Mode "original" exists (hypelab/edl.py:30); pipeline stages exist (align.py, render.py, gates.py); but "Starter tier" has no code counterpart (grep finds no starter/pro concept), and render.json no longer carries edl_version/reframe/creative fields. |
| R-04 | "Job queue with leases, retries, crash recovery" | README.md:9 | PARTIAL | Leases TRUE (hypelab/queue.py:27-28, LEASE_TTL_S=1800; heartbeat at :129). Crash recovery TRUE (release/expire + test, 191-pass suite). Retries FALSE as described: `fail()` (queue.py:172-204) moves the job to terminal `failed` immediately — no backoff requeue, no `run_after`; attempts/poison semantics exist (MAX_ATTEMPTS=3) but auto-retry does not. |
| R-05 | "Consent hard gate + publish dry-run" | README.md:9 | TRUE | publish_job re-checks consent fail-closed (hypelab/publish/__init__.py:136+); dry_run=True default; consent grant requires explicit artifact+expiry (hypelab/consent.py:60-75). |
| R-06 | "Nothing is published for real; no paid APIs; no credentials" | README.md:9 | TRUE | All live adapter paths raise LiveRefused (hypelab/publish/providers.py, meta.py); publish --live refuses at CLI (book3cli.py:141-145). No API keys/secrets found in hypelab/*.py (spot grep). metrics.fetch_metrics honestly returns (None, "unavailable") (hypelab/metrics.py:36-47). |
| R-07 | Setup: `cd /home/dino/hypelab` | README.md:17 | TRUE | Repo root on Threadripper. |
| R-08 | `export HYPELAB_HOME=/home/dino/hypelab  # default; the DB + jobs/ live here` | README.md:18 | FALSE | Code reads HYPELAB_ROOT / HYPELAB_DB / HYPELAB_LEASE_SECONDS (hypelab/cli.py:87-103); HYPELAB_HOME appears nowhere in hypelab/ or tests/. Job artifacts now live in work/<job_id>/ (hypelab/util.py:173), not jobs/<job>/. |
| R-09 | `python3 -m hypelab.cli doctor  # ffmpeg, whisper, edge-tts, fonts` | README.md:19 | FALSE | No `doctor` command exists. Ran it: `Error: No such command 'doctor'.` (also: edge-tts is used nowhere in current code). |
| R-10 | `kit new --name demo --appearance "LOCKED: ..."` | README.md:27 | FALSE | Actual: `kit new <kit_id> --from <file>` (hypelab/cli.py:366-391). |
| R-11 | `new <kit_id> --script fixtures/script.txt --title "slice-01"` | README.md:29 | FALSE | Actual: `new --kit <id> --script <file> [--aspect] [--max-s] [--title]` (hypelab/cli.py:394-464); kit is an option, not positional. |
| R-12 | `shots <job>` | README.md:31 | TRUE | hypelab/cli.py:466-502. |
| R-13 | `attach <job> vo|music|beat:b1 <file> --provenance generated:...` | README.md:33-35 | FALSE | No --provenance option; VO/music attach via `audio --vo/--music` (cli.py:554+); `attach` takes a beat id only (b1, b2… — script.py:72 emits b1), not `beat:b1`. |
| R-14 | `align <job>` | README.md:38 | FALSE | No align command (`--help` lists none). Alignment now runs via `audio` + worker (`_do_align`, cli.py:264; worker states queued_align/aligning, cli.py:885-939). |
| R-15 | `plan <job>` | README.md:39 | FALSE | No plan command. EDL is built at `new` time (cli.py:438-451) and retimed by `audio`. |
| R-16 | `render <job> --aspect 9:16,1:1` | README.md:40 | PARTIAL | `render` exists (cli.py:741), but --aspect is a single click.Choice (cli.py:742-744) — a comma list is rejected. Multi-aspect works via repeated invocations + _retarget_edl (cli.py:639). |
| R-17 | `gates <job>`, `work --once` | README.md:41 | TRUE | cli.py:794, cli.py:885. |
| R-18 | `show <job>  # state should be asset_ready` | README.md:42 | FALSE | No show command. State machine also changed (states: scripted, awaiting_media, queued_align…, ready, gate_failed, failed — jobs.py). |
| R-19 | "outputs: jobs/<job>/master.mp4, render/render_record.json, quality_report.json" | README.md:43 | PARTIAL | TRUE for the historical slice job (jobs/job_c656669a5147/ contains all three). Stale as current guidance: current code writes work/<job_id>/ and the render record is work/manifest.json (hypelab/manifests.py:312-331). |
| R-20 | Tests: `python3 -m unittest discover -s tests -v` | README.md:48-50 | FALSE | Tests are pytest-style with fixtures (tests/test_foundation.py:1-26 imports pytest). Actual command: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/` → 191 passed (run 2026-09-29). unittest discover cannot run fixture-based tests. |
| R-21 | Consent gate: `publish <job> --target somecreator` → REFUSED (exit 3); `--real` | README.md:52-56 | PARTIAL | Refusal behavior TRUE (no consent → PublishError/ConsentError; --live refuses). Command syntax FALSE: actual is `publish --job <id> --collab <handle> --media <file> [--live]` (book3cli.py:126-162); no --target, no --real flag. Exit code 3 unverified (book3cli uses _die → exit 1). |
| R-22 | "What is NOT built yet": M5 multi-aspect audio polish beyond 1:1, M7 carousel, M8 clip mine, M9 measurement/what_worked | README.md:61-63 | FALSE | Stale. M7: `carousel` command renders 7 slides via headless Chromium (book3cli.py:95; carousel.py). M8: Book 2 clip mine fully present (campaign/source/moments/cut/tray — b2cli.py; commit 81aaf52 "Books 1-3 complete"). M9: measure/worked/feedback + attribution with n≥30 gating (b2cli.py:385-420; attribution.py). M5: 1:1 derivation proven in slice (master_1x1.mp4); ducking (render.py:196-206), loudnorm, and _retarget_edl exist. |
| R-23 | "real publish adapters (Postiz/Zernio/native stubs only)" | README.md:63-64 | TRUE | Postiz/Zernio/Ayrshare/Meta publishers all raise LiveRefused on the live path (providers.py:29-34, meta.py:60-66). |
| R-24 | "Stubs fail loudly with NotImplementedError — nothing is faked" | README.md:64 | PARTIAL | Fail-loudly TRUE; exception type is LiveRefused/PublishError/AuthorizationError/ConsentError, not NotImplementedError. "Nothing is faked" TRUE: dry-run records against labeled fixtures (dryrun.py:1-14); metrics writes honest NULL/"unavailable" rows (metrics.py:36-47). |

### ARCHITECTURE.md

| # | Claim | Source | Verdict | Evidence |
|---|---|---|---|---|
| A-01 | "implementation-ready… Written 2026-09-28 from hypelab-v2-handoff_9_ukhx.pdf and hypelab-spec_10_kh8z.pdf (spec supersedes handoff)" | ARCHITECTURE.md:3-6 | TRUE | git: a8b5d8d "Add ARCHITECTURE.md" 2026-09-28. |
| A-02 | "No prior HypeLab repository existed; this document and the code under hypelab/ are the first implementation" | ARCHITECTURE.md:6-8 | TRUE | git log starts at a8b5d8d. |
| A-03 | "v1 design notes (SQLite job queue, human-in-the-loop media, no browser automation, identity locking) carried forward" | ARCHITECTURE.md:8-9 | UNVERIFIABLE | No v1 notes in the repo to compare against. |
| A-04 | "Python 3 + SQLite is the foundation" | ARCHITECTURE.md:26-27 | TRUE | Stack confirmed in code. |
| A-05 | "SQLite's WAL mode" | ARCHITECTURE.md:33 | TRUE | hypelab/db.py:114,144 `PRAGMA journal_mode=WAL`. |
| A-06 | jobs schema as printed: id "ulid, e.g. job_01J…", kit_id NOT NULL, cost_usd, plus a tasks table | ARCHITECTURE.md:44-78 | FALSE | Actual jobs(id prefix_hex via util.new_id — hypelab/util.py:31-34, e.g. job_9f2c…; kit_id NULLABLE; no cost_usd). No tasks table exists (migrations/*: jobs, job_events, edls, kits, renders, gate_results, cost_ledger, campaigns, sources, source_items, moments, clips, posts, metrics, targets, consents, invites, slides, …). Queue is job-level (queue.py). |
| A-07 | "`enqueue_task` is INSERT … ON CONFLICT(idempotency_key) DO NOTHING" | ARCHITECTURE.md:80-82 | FALSE | No enqueue_task, no idempotency_key anywhere in hypelab/. |
| A-08 | Claim = one atomic transaction `UPDATE tasks SET state='leased' …` — "Exactly one worker wins" | ARCHITECTURE.md:86-88 | PARTIAL | Atomic claim exists but on jobs (queue.py:59-127), not a tasks table. Single-winner semantics retained. |
| A-09 | "Lease duration: 10 minutes default" | ARCHITECTURE.md:89 | FALSE | LEASE_TTL_S = 30*60 = 1800 s = 30 min (queue.py:28; cli.py comment :100-105). |
| A-10 | "renewable by heartbeat for long renders" | ARCHITECTURE.md:89 | TRUE | queue.py:129 heartbeat(); used by render path (cli.py:686-687). |
| A-11 | Retry: "attempts += 1… requeue with exponential backoff (run_after = now + 2^attempts minutes)" | ARCHITECTURE.md:91-94 | FALSE | No run_after column; queue.fail() (queue.py:172-204) sets state='failed' terminal immediately. No backoff requeue exists. |
| A-12 | "Cancellation: hypelab cancel <job>" | ARCHITECTURE.md:96 | FALSE | No cancel command (`--help` verified). |
| A-13 | "hypelab retry <task> resets attempts" | ARCHITECTURE.md:106 | FALSE | No retry command; no reset_attempts in queue.py. |
| A-14 | "kill -9 mid-render is recoverable by starting a new worker" | ARCHITECTURE.md:100-104 | TRUE | Expired-lease release semantics (queue.py:144-170); proven live in slice (VERTICAL_SLICE_REPORT); crash-recovery covered by current test suite (191 passed). |
| A-15 | §1.4 job state-transition table (draft → asset_building → awaiting_media → … → cancelled/failed) | ARCHITECTURE.md:110-133 | PARTIAL | Current states differ (scripted, awaiting_media, queued_align/aligning, queued_render/rendering, queued_gates/gating, ready, gate_failed, failed + Book 2/3 states — jobs.py:50-77). pitch/consent/scheduled/published states exist in Book 3 flow but the table's exact transitions/commands don't match. |
| A-16 | cost_ledger schema as printed (id, job_id, task_id, provider, units, usd, note, created_at) | ARCHITECTURE.md:147-153 | PARTIAL | Actual: (job_id, at, provider, unit, qty, usd, note) (migrations/0001:88-98; queue.charge, queue.py:215-231). Different column names, no task_id/id. |
| A-17 | "jobs.cost_usd is the sum. Per-job budgets: jobs.budget_usd" | ARCHITECTURE.md:155-157 | FALSE | Neither column exists in migrations or code (grep: no hits). No budget enforcement anywhere. |
| A-18 | "Local CPU work (ffmpeg, whisper) is logged with usd = 0" | ARCHITECTURE.md:157-158 | UNVERIFIABLE | No charge() calls with usd=0 found in task handlers. |
| A-19 | "they call hypelab/services.py functions, which own all validation and queue writes" | ARCHITECTURE.md:163-164 | FALSE | hypelab/services.py does not exist. cli.py header: "This module supersedes the old argparse CLI…, worker.py, tasks_lab.py and services.py. None of those are imported here." (cli.py:1-9). |
| A-20 | "No business logic in the CLI layer" | ARCHITECTURE.md:165 | FALSE | cli.py is 997 lines including _do_align (264), _render_job (656), _run_gates (754), normalize_numbers (243). |
| A-21 | "Remote control adds authentication (token in config, compared in constant time)" / Telegram bot, dashboard | ARCHITECTURE.md:163-167 | FALSE | No remote control exists. authorize.py is DB approval rows (job_id/action/actor), not bearer tokens; no constant-time compare. |
| A-22 | kits/kit_versions schemas as printed (appearance_text, typography_json, colors_json, caption_style_json, …) | ARCHITECTURE.md:179-198 | PARTIAL | Actual: kits(id, version, data_json, created_at) (migrations/0001:59-65). Kit fields live inside data_json. Append-only versioning TRUE (kits.seed). |
| A-23 | assets table schema (id, job_id, slot, path, sha256, …) | ARCHITECTURE.md:206-217 | FALSE | No assets table. Assets recorded in work/<job>/manifest.json (manifests.attach_asset, manifests.py:249-305). |
| A-24 | "the renderer resolves slots through this table and verifies the sha256 before use" | ARCHITECTURE.md:219-221 | TRUE | build_command re-hashes every attached asset first; ManifestError on tampering (render.py:413-431, docstring). |
| A-25 | "Starter and Pro produce the same EDL" | ARCHITECTURE.md:228-230 | UNVERIFIABLE | No Starter/Pro tier concept in code. |
| A-26 | render.json schema + "Validation rules (hard rejects): edl_version == 1" | ARCHITECTURE.md:236-290 | FALSE | edl.py has no edl_version field. EDL_SCHEMA requires mode/kit/target/beats/audio/captions/overlays/gates_passed (edl.py:18-30); mode enum is ["original","clip"]. Hook rule is "exactly one hook, beats[0]" (edl.py:126-160), not the printed t_out−t_in ≤ 3.0 clause. |
| A-27 | slides.json: "Exactly 7 slides (cover, 5 body, CTA)" | ARCHITECTURE.md:296-301 | TRUE | carousel.py:341 enforces len(slides) == SLIDES_REQUIRED. |
| A-28 | "Renderer: HTML/CSS → PNG via headless Chromium" | ARCHITECTURE.md:298 | TRUE | carousel.py:49-68 (_chromium; --headless --screenshot). |
| A-29 | beats.json "Derived via librosa/aubio when available" | ARCHITECTURE.md:310-314 | PARTIAL | librosa is used in align.py:67-73 (resampling), not for beat-grid derivation. No beats.json producer found. |
| A-30 | §3.4 "CLI for the planning loop": new/shots/attach/align/plan/show signatures | ARCHITECTURE.md:318-328 | FALSE | Stale (see R-10..R-18). |
| A-31 | "All ffmpeg invocations are argv lists… subprocess.run([...], shell=False)" | ARCHITECTURE.md:338-341 | TRUE | render.py:467,570 use shell=False. |
| A-32 | "loudnorm dual-pass to target.loudness_lufs (−14 LUFS social target)" | ARCHITECTURE.md:351-354 | PARTIAL | loudnorm dual-pass exists (gates.py:136-172 measurement; render filtergraph). Target comes from kit audio config; new-job default is −16.0 (cli.py:428), slice EDL used −14. |
| A-33 | "Render the 9:16 master, then derive 1:1 and 16:9… hypelab render <job> --aspect 9:16,1:1,16:9" | ARCHITECTURE.md:356-360 | PARTIAL | Derivation mechanism exists (_retarget_edl, cli.py:639-644) but each render invocation takes ONE --aspect (cli.py:742-744); no comma-list. |
| A-34 | "Every render writes render_record.json next to the MP4" with listed fields | ARCHITECTURE.md:362-367 | PARTIAL | Reproducibility record now lives in work/manifest.json as {render_hash, provenance, ffmpeg_argv, started_at, finished_at, input_hashes} (manifests.py:312-331). Different location and fields. |
| A-35 | "Caching: ~/.cache/hypelab/ (or $HYPELAB_CACHE)… clipseg:{beat}:{sha}:{fit}" | ARCHITECTURE.md:369-372 | FALSE | No HYPELAB_CACHE reference, no clip-segment cache in render.py (only an overlay-font memo, render.py:63-75). |
| A-36 | §5.1 gates table (duration, aspect, first_frame, hook, captions_safe, loudness, slots_filled, audio_present) | ARCHITECTURE.md:378-397 | PARTIAL | Current gates: duration, loudness, first_frame, hook_budget, caption_safe, slots_filled, geometry, word_confidence (gates.py:31-32; BOOK7_GATES cli.py:54-62). Shape (8 gates, fail→repair) holds; names and thresholds differ. |
| A-37 | "Text overflow is a gate (measure via Chromium's layout, fail the slide with the overflowing field named)" | ARCHITECTURE.md:399-404 | TRUE | carousel.py:12-14, :118-163 overflow probe. |
| A-38 | targets/consents schemas as printed (invite_history_json, outcome, asset_version, revoked_at…) | ARCHITECTURE.md:414-428 | PARTIAL | Actual targets: handle/platform/followers/engagement/is_public/pattern_json/corpus_path/contact_route/consent_state/last_checked. Actual consents: id/handle/platform/job_id/pitched_at/responded_at/decision/scope/expiry/artifact. No invite_history_json, outcome, asset_version, or revoked_at columns. |
| A-39 | §6.2 hard-gate claims (consent re-checked before provider call; dry_run default; CLI never auto-grants) | ARCHITECTURE.md:432-449 | TRUE | publish_job: authorization required → preflight → consent gate_consent fail-closed → dry_run default True (publish/__init__.py:136-200); grant requires explicit artifact+expiry (consent.py:60-75). |
| A-40 | "v1 ships: dryrun adapter (always) and a postiz stub… every method raises NotConfigured until configured" | ARCHITECTURE.md:456-459 | PARTIAL | Adapters exist (dryrun + postiz/zernio/ayrshare/meta in publish/). They raise LiveRefused, not NotConfigured; dry_run delegates to labeled fixtures (dryrun.py). Fail-loudly holds. |
| A-41 | "Every Instagram publish sets collaborators (≤3, public accounts only) and isAIGenerated: true" | ARCHITECTURE.md:463-464 | PARTIAL | is_ai_generated=True enforced on instagram preflight (publish/__init__.py:113-131). Cap is per-adapter capability (postiz/zernio ≤3; native meta ≤5 — meta.py:31); publicity is a cached observation with timestamp, not a universal law (publish/__init__.py:104-111). |
| A-42 | "hypelab measure polls open posts on a schedule (default 6 h)" | ARCHITECTURE.md:480 | PARTIAL | `measure` is manual (b2cli.py:385-395); metrics cadence documented as "operational, not enforced" (metrics.py:8-9). watcher sources poll per poll_every_s (default 900 s, watcher.py:164). No 6h schedule. |
| A-43 | "the CLI prints 'insufficient evidence' otherwise" | ARCHITECTURE.md:485 | PARTIAL | worked prints "(N bucket(s) below n=30: listed, not interpreted)" (b2cli.py:414-419); attribution splits signal vs below_threshold at n≥30 (attribution.py:116-126). Spirit true, wording off. |
| A-44 | "Secrets: ~/.config/hypelab/secrets.env (mode 600)" | ARCHITECTURE.md:492 | FALSE | No such path referenced anywhere in code. |
| A-45 | "Remote auth: Bearer <redacted> in config, constant-time compare" | ARCHITECTURE.md:493-494 | FALSE | See A-21. |
| A-46 | "attach checks extension allowlist, magic bytes, size caps (video ≤ 500 MB, audio ≤ 100 MB), duration caps; quarantines on mismatch. Symlinks rejected; paths confined" | ARCHITECTURE.md:497-499 | FALSE | intake_asset does atomic copy + sha256 + mid-copy race checks (util.py:119-170); attach_asset adds ffprobe validation (manifests.py:279-305). No extension allowlist, magic-byte check, size caps, duration caps, or symlink rejection found. Quarantine exists only for expected_sha256 mismatch (manifests.py:271-276). |
| A-47 | "Only explicit hypelab fetch --url (operator-initiated, allowlisted hosts) downloads" | ARCHITECTURE.md:501-502 | FALSE | No fetch command. watcher.py auto-polls source URLs via urllib (watcher.py:22,71); ingest.py:257 handles http URLs. Renderer/workers do avoid fetching (render argv only), but the "only explicit fetch" claim is false. |
| A-48 | "worker subprocesses get timeouts (whisper 20 min, ffmpeg 30 min) and memory caps via ulimit… concurrent renders capped at nproc/2" | ARCHITECTURE.md:504-505 | FALSE | FFMPEG_TIMEOUT = 600 (10 min) (render.py:26); no whisper timeout / ulimit / nproc cap found. |
| A-49 | "hypelab backup → timestamped tarball; restore = unpack + hypelab worker recover" | ARCHITECTURE.md:507-509 | FALSE | No backup command. |
| A-50 | "Budgets: per-job budget_usd; paid tasks check before spending; hypelab costs shows spend" | ARCHITECTURE.md:511-513 | PARTIAL | `costs` command exists (cli.py:941). budget_usd column and any pre-spend check do not exist (see A-17). |
| A-51 | Required outputs §2 module list (cli.py thin, services.py, db.py, queue.py, worker.py, tasks_lab.py, kits.py, assets.py, plan.py, edl.py, align.py, captions.py, audio.py, render.py, gates.py, carousel.py, consent.py, publish.py, measure.py, modes_b.py, config.py) | ARCHITECTURE.md:553-583 | FALSE | Missing: services.py, worker.py, tasks_lab.py, plan.py, assets.py, audio.py, config.py, modes_b.py, measure.py, publish.py (now a package). Present but unlisted: script.py, jobs.py, manifests.py, util.py, b2cli.py, book3cli.py, authorize.py, boundary.py, campaigns.py, cut.py, ingest.py, invites.py, metrics.py, pitch.py, reframe.py, score.py, signals.py, tray.py, watcher.py, feedback.py, attribution.py, compliance.py, publish/{base,dryrun,meta,providers}.py, weights/. |
| A-52 | "docs/ WALKTHROUGH.md OPERATIONS.md" | ARCHITECTURE.md:584-586 | FALSE | docs/ is empty (verified 2026-09-29). |
| A-53 | Required outputs §5 CLI command list (kit new\|show\|bump, plan, show, publish [--dry-run] [--i-confirm], carousel <article> --kit, pitch <job> --target, cancel, retry, backup, doctor…) | ARCHITECTURE.md:610-628 | FALSE | Stale; see R-09..R-18 and actual `--help` output (attach, audio, authorize, campaign, carousel, consent, costs, cut, feedback, gates, invite, kit, measure, moments, new, pitch, posted, priors, promote-weights, propose-weights, publish, render, review, shots, source, tray, watch, work, worked). |
| A-54 | §7 milestones M1–M10 acceptance criteria | ARCHITECTURE.md:632-657 | PARTIAL | M1/M2/M4/M6 substantially met. M5/M7/M8/M9 acceptance now stale (features built beyond what the table describes; e.g. M8 acceptance assumed tray+compliance gate — exists, but table predates Book 2 build). M10 ("matches implementation, no fixture claims as real") is now FALSE — the doc itself no longer matches implementation. |
| A-55 | Product paragraph: "One renderer, three feed modes (A: Original, B: Clip Mine, C: Carousel)" | ARCHITECTURE.md:14-16 | TRUE | edl mode enum ["original","clip"]; carousel command; clip-mine modules. |
| A-56 | "THE HYPE puts that video in a creator's feed with recorded consent, then measures performance and writes the outcome back" | ARCHITECTURE.md:17-20 | PARTIAL | The loop is scaffolded, not live: publish is dry-run-only (all live paths refuse), metrics fetch returns "unavailable" (metrics.py:36-47). Consent recording + attribution plumbing are real. |

### VERTICAL_SLICE_REPORT.md (dated historical record, 2026-09-28)

| # | Claim | Source | Verdict | Evidence |
|---|---|---|---|---|
| V-01 | Date 2026-09-28 (EDT), machine Threadripper dino@100.85.119.8 Nobara, repo /home/dino/hypelab, local commits only | VERTICAL_SLICE_REPORT.md:3-4 | TRUE | Machine/repo verified live; commit SHAs below verify in git log. |
| V-02 | "Python 3.14.7, FFmpeg 8.1.2, faster-whisper (CPU, int8, tiny model)" | VERTICAL_SLICE_REPORT.md:5 | TRUE | python3 --version → 3.14.7; ffmpeg -version → 8.1.2 (checked 2026-09-29). |
| V-03 | PDF permanence table (sha256 of two Desktop PDFs) | VERTICAL_SLICE_REPORT.md:9-15 | UNVERIFIABLE | PDFs are not in the repo ("Desktop copies"); cannot re-hash from here. |
| V-04 | Commits a8b5d8d, cbbdc2a, f090c8e, 52d9f4e | VERTICAL_SLICE_REPORT.md:19-26 | TRUE | All present in `git log --oneline`. |
| V-05 | Kit kit_2d0b3169@1; job job_c656669a5147 "slice-01" mode original → asset_ready; 5 beats; render_hash 46aec30d5f57a933… | VERTICAL_SLICE_REPORT.md:30-36 | TRUE | jobs/job_c656669a5147/ tracked with all artifacts; render/render_record.json contains kit 'kit_2d0b3169@1', edl_version 1. render_hash prefix spot-check: record present (hash value itself not re-verified). |
| V-06 | Outputs: master.mp4 (1080×1920, 21.0 s, 10.6 MB), master_1x1.mp4 (7.9 MB), render_record.json, captions.ass, quality_report.json, vo.words.json | VERTICAL_SLICE_REPORT.md:37-40 | TRUE | Files exist; sizes: master.mp4 = 10,641,764 B ≈ 10.6 MB, master_1x1.mp4 = 7,855,222 B ≈ 7.9 MB (decimal MB). |
| V-07 | quality_report.json: 8/8 gates pass | VERTICAL_SLICE_REPORT.md:40 | TRUE | quality_report.json: passed=true, all 8 gates passed (duration, aspect, first_frame, hook, captions_safe, loudness, slots_filled, audio_present). |
| V-08 | vo.words.json: script_constrained=True, match_ratio 0.967 | VERTICAL_SLICE_REPORT.md:40 | TRUE | Verified: alignment.script_constrained=True, match_ratio=0.967, 60 words. |
| V-09 | 8 "failures found live and fixed" stories (planner contiguity, SQL placeholders, whisper pkg, loudnorm verbosity, freezedetect, run_after format, render→gates chaining, ASR spelling leak) | VERTICAL_SLICE_REPORT.md:48-75 | TRUE (as record) | Historical record of the slice session; corroborated where checkable (e.g. loudnorm info-verbosity handling in gates.py:136-172; faster-whisper alignment in align.py). Slice-era internals (run_after, _requeue_gates) were superseded by the job-level queue rewrite — expected, not a contradiction. |
| V-10 | Restart recovery (kill -9) — PROVEN | VERTICAL_SLICE_REPORT.md:77-87 | TRUE | Mechanism (expired-lease release) still present (queue.py:144-170) and covered by the passing suite (191 passed 2026-09-29). |
| V-11 | Consent blocking — PROVEN via CLI (REFUSED exit 3; dry-run exit 0; per-handle/per-asset-version strictness) | VERTICAL_SLICE_REPORT.md:89-97 | PARTIAL | Refusal behavior TRUE in current code (consent_mod.gate_consent fail-closed; --live refuses). CLI surface changed (publish --job/--collab/--media; book3cli uses _die → exit 1, not 3). Historical exit-3 detail is slice-era. |
| V-12 | Malformed EDL rejection — 13 validation unit tests | VERTICAL_SLICE_REPORT.md:99-103 | TRUE (as record) | Historical; current edl.py validation + test suite (191 passed) superset it. |
| V-13 | "python3 -m unittest discover -s tests — 34/34 pass, on both the agent VM and the Threadripper" | VERTICAL_SLICE_REPORT.md:107-111 | TRUE (as record) | Historical record of the slice-era suite. Current suite is larger: 191 passed (2026-09-29). The "agent VM" phrasing is stale context, not a code claim. |
| V-14 | "Honestly not done / blocked" (Mode B stub, Mode C stub, measure stub, no real publishing, no paid providers, no campaign/moment/clip persistence, cost ledger gaps, ASR timestamps, first-frame transient, pip warnings) | VERTICAL_SLICE_REPORT.md:113-131 | TRUE (as record, 2026-09-28) | Accurate as of the slice date. Several items are now built (Book 2/3, commit 81aaf52) — which is fine for a dated report but is exactly why README's undated "NOT built yet" list (R-22) is now wrong. |
| V-15 | Files of record | VERTICAL_SLICE_REPORT.md:135-140 | TRUE | Paths exist (ARCHITECTURE.md, VERTICAL_SLICE_REPORT.md, jobs/job_c656669a5147/). |

### hypelab/pitch.md

No factual claims about the app — it is a 15-line outreach DM template with {handle}/{observed}/{angle}/{ask}/{scope}/{sender}/{brand} placeholders, rendered by hypelab/pitch.py:55 (make_pitch; missing placeholders raise). Verdict: N/A. Product note: "If you're in, it's one tap: accept the collab invite and it goes live on both profiles" describes Instagram's collab-invite UX, not app behavior; the template carries no AI-generation disclosure, but the publish path sets is_ai_generated=True at the container level (publish/__init__.py:113-131), so the disclosure is enforced in product, not in copy.

## Setup truth test (README followed literally, 2026-09-29)

| README step | Result |
|---|---|
| `cd /home/dino/hypelab` | OK |
| `export HYPELAB_HOME=/home/dino/hypelab` | Accepted by shell but **ignored by the app** — code reads HYPELAB_ROOT/HYPELAB_DB/HYPELAB_LEASE_SECONDS (cli.py:87-103). Benign today only because the compiled-in default root is the same path. |
| `python3 -m hypelab.cli doctor` | **FAILS**: `Error: No such command 'doctor'.` No doctor/health command exists in any CLI module. |
| Walkthrough (`kit new --name/--appearance`, `new <kit> --script`, `attach … --provenance`, `align`, `plan`, `show`, `publish <job> --target`, `render --aspect 9:16,1:1`) | **All stale** — see R-09..R-18. None of these invocations work as written. |
| `python3 -m unittest discover -s tests -v` | **Wrong runner.** Tests are pytest with fixtures. Correct: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/` → 191 passed, 3 warnings, 198.64 s (run 2026-09-29, tree left clean). |
| Consent gate (`publish <job> --target somecreator`, exit 3) | Command shape wrong (actual: `publish --job … --collab … --media …`); refusal behavior itself verified in code. |

## Reference check (every file/command/URL/env var named in docs)

- `ARCHITECTURE.md`, `hypelab/pitch.md`, `fixtures/script.txt` — exist. `fixtures/kit.json`, `fixtures/beats_sample.json` (implied by ARCHITECTURE §2 module list) — **missing**.
- `docs/WALKTHROUGH.md`, `docs/OPERATIONS.md` — **missing** (docs/ empty).
- `hypelab/services.py`, `worker.py`, `tasks_lab.py`, `plan.py`, `assets.py`, `audio.py`, `config.py`, `modes_b.py`, `measure.py`, `hypelab/publish.py` (module) — **missing** (publish/ is now a package).
- Commands named but absent: `doctor`, `align`, `plan`, `show`, `cancel`, `retry`, `backup`, `fetch`; flags `--target`, `--real`, `--i-confirm`, `--appearance`, `--provenance`.
- Env vars named but unread: `HYPELAB_HOME`; undocumented-but-read: `HYPELAB_ROOT`, `HYPELAB_DB`, `HYPELAB_LEASE_SECONDS`, `HYPELAB_CHROMIUM` (carousel.py:68).
- URLs in docs: none external except capability `docs_source` strings in code (not docs claims).
- `tests/test_edl.py test_queue.py test_gates.py test_consent.py test_render.py` (ARCHITECTURE §2) — **missing**; actual: test_align, test_book2, test_book3, test_cli, test_foundation, test_gates, test_manifests, test_pipeline.

## Feature reality check (simulated / stubbed / hardcoded)

All stubs fail loudly and are labeled — nothing is faked silently:

- **Publish adapters** (postiz, zernio, ayrshare, meta): live path raises `LiveRefused` ("Dino-gated: needs an explicit authorization row AND provider credentials"). dry_run records against labeled recorded fixtures (tests/fixtures_book3/dryrun_fixtures.json), prints "zero live calls made — recorded against fixtures only". No network calls.
- **Metrics polling**: `fetch_metrics` returns `(None, "unavailable")` — writes NULL rows; absence recorded as data, never zero-filled (metrics.py:36-47). Calibration uses official_api/provider_api rows only.
- **Attribution**: n≥30 gating; below-threshold buckets "listed, not interpreted" (b2cli.py:414-419).
- **VO generation**: not a current feature — no edge-tts code; VO is operator-attached, then force-aligned (faster-whisper). The slice's edge-tts VO was fixture tooling.
- **Clip mine scoring/cut/tray/compliance**: implemented (score.py, cut.py, tray.py, compliance.py), fixture-backed in tests.
- **Carousel**: real headless-Chromium renderer (needs a Chromium binary or HYPELAB_CHROMIUM).
- Determinism claims: ffmpeg argv built from validated data with shell=False (render.py:467,570); atomic tmp→fsync→rename writes; render-hash skip. No `~/.cache/hypelab` content cache exists (A-35).

## Docs quality

- **Encoding**: no mojibake in README.md / ARCHITECTURE.md / VERTICAL_SLICE_REPORT.md / hypelab/pitch.md (grep for Ã/â€/emoji-damage: 0 hits).
- **Outdated architecture descriptions**: ARCHITECTURE.md describes the slice-era implementation across §§1–8 (queue, schemas, EDL, CLI, gates, ops) — see A-06..A-53. It is the single largest docs defect in the repo.
- **Missing docs**: no setup/env/deploy/API docs beyond the (broken) README; docs/ empty; env vars HYPELAB_ROOT/HYPELAB_DB/HYPELAB_LEASE_SECONDS/HYPELAB_CHROMIUM undocumented anywhere; no walkthrough/operations docs as ARCHITECTURE promises.
- **Published default credentials**: none found (spot grep for api_key/client_secret/private_key/sk- in hypelab/: no hits). Full secret scan is SEC's lane.
- **Repo hygiene note**: binary slice artifacts are git-tracked (jobs/job_c656669a5147/master.mp4 10.6 MB, master_1x1.mp4, caption_proof.png, asset mp4s; kits/cerebratico/kit.json). Fine as evidence, worth a .gitignore decision later (DOC-023, S4).

## Product lens

- **Core promise**: "AI-assisted short-form video production: script → captioned MP4 with quality gates." **Delivered** end to end for Mode A (proven by the slice artifacts + 191 passing tests). Mode B (clip mine) and Mode C (carousel) are built at the CLI/module level; their end-to-end proof is thinner than Mode A's.
- **Biggest gaps between vision and reality**:
  1. **Docs describe a different app than the code.** A new user following README cannot run a single walkthrough step. This is the #1 product-facing gap (DOC findings below).
  2. **"Distribution + measurement loop" is scaffolded, not live.** ARCHITECTURE's product paragraph promises putting video "in a creator's feed… then measures performance and writes the outcome back." In reality: publishing is dry-run-only (correctly gated), metrics polling returns "unavailable", attribution waits on n≥30. The loop's *plumbing and honesty* are excellent; the *live* half needs provider credentials, Meta app review/business verification (months of lead time, per meta.py notes), and real posts.
  3. **Upload/input validation is weaker than documented.** ARCHITECTURE §8 promises extension allowlists, magic bytes, size caps, symlink rejection; the code does atomic intake + sha256 + ffprobe only (A-46). For a tool ingesting third-party clips (Book 2 sources auto-poll URLs), this is the honest gap to close.
- **Legal/brand risks**:
  - **Music/rights**: operator-attached music gets no rights check (attach validates parseability, not rights). Book 2 sources require a rights manifest (good), but Mode A music is operator's responsibility — undocumented. Suggest a warning/disclaimer in `audio`/`attach` output (IDEA).
  - **Trademark**: "HypeLab" not searched for conflicts (IDEA/question for owner).
  - **Pitch template**: outreach copy is fine, but sending it at scale without disclosure review could violate platform spam policies — operator's call; note in IDEAS.
  - **AI disclosure**: handled correctly in product (is_ai_generated=True enforced on Instagram containers); pitch.md copy lacks it, harmless since enforcement is in code.
  - **Privacy**: consent artifacts are hashed; targets store handles/followers — local SQLite, no exfiltration path found in publish dry-run. Fine.

## Open questions (for QUESTIONS.md Q-001)

Q-001 asks the owner to confirm/correct the P4 "what this app is" paragraph above. Recommendation:
accept as written; default assumption meanwhile = the paragraph stands.
