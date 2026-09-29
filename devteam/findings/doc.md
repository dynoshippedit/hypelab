# DOC findings — Product & Docs Auditor (Phase 1, read-only)

Ledger entries for docs/product issues. IDs DOC-001 onward (range DOC-001–049).
Status: NEW. Confidence: Confirmed (all verified against code on the Threadripper,
2026-09-29). Full claim-by-claim evidence: devteam/notes/claims-audit.md.

## Index

| ID | Sev | Conf | Status | Title | Location | Effort |
|---|---|---|---|---|---|---|
| DOC-001 | S2 | Confirmed | NEW | README setup invokes `hypelab.cli doctor`, which does not exist | README.md:19 | XS |
| DOC-002 | S2 | Confirmed | NEW | README walkthrough commands are all stale (kit new/new/attach/align/plan/show/publish) | README.md:27-43 | M |
| DOC-003 | S2 | Confirmed | NEW | README "What is NOT built yet" lists M5/M7/M8/M9 as unbuilt — all built | README.md:61-64 | S |
| DOC-004 | S2 | Confirmed | NEW | README test command is wrong (unittest vs pytest) | README.md:48-50 | XS |
| DOC-005 | S3 | Confirmed | NEW | README documents HYPELAB_HOME; code reads HYPELAB_ROOT/HYPELAB_DB | README.md:18 | XS |
| DOC-006 | S2 | Confirmed | NEW | ARCHITECTURE §§1.2–1.3 describe a tasks-table queue, 10-min leases, backoff retries, cancel/retry commands — none exist | ARCHITECTURE.md:44-106 | M |
| DOC-007 | S2 | Confirmed | NEW | ARCHITECTURE §1.6: services.py missing; "no business logic in CLI" false; remote-control/bearer-token design absent | ARCHITECTURE.md:163-167 | S |
| DOC-008 | S3 | Confirmed | NEW | ARCHITECTURE §1.5: jobs.cost_usd/jobs.budget_usd columns don't exist; no budget enforcement | ARCHITECTURE.md:155-157 | S |
| DOC-009 | S2 | Confirmed | NEW | ARCHITECTURE §3.3 render.json schema stale (edl_version, reframe, creative, compliance fields gone) | ARCHITECTURE.md:236-290 | M |
| DOC-010 | S3 | Confirmed | NEW | ARCHITECTURE §2.1/§2.2/§6.1 schema listings mismatch actual tables (kits, assets→manifest.json, targets, consents) | ARCHITECTURE.md:179-217,414-428 | S |
| DOC-011 | S2 | Confirmed | NEW | ARCHITECTURE Required outputs §2 module list stale (9 named modules missing, ~20 new modules unlisted) | ARCHITECTURE.md:553-583 | S |
| DOC-012 | S2 | Confirmed | NEW | ARCHITECTURE promises docs/WALKTHROUGH.md and docs/OPERATIONS.md — docs/ is empty | ARCHITECTURE.md:584-586 | M |
| DOC-013 | S2 | Confirmed | NEW | ARCHITECTURE Required outputs §5 CLI reference stale (cancel/retry/backup/doctor/--i-confirm/--target) | ARCHITECTURE.md:610-628 | S |
| DOC-014 | S2 | Confirmed | NEW | ARCHITECTURE §8 ops claims false: secrets.env, fetch --url, backup, ulimit/nproc caps, upload allowlists/size caps | ARCHITECTURE.md:492-509 | M |
| DOC-015 | S3 | Confirmed | NEW | ARCHITECTURE §5.1 gate table names/thresholds stale vs current 8 gates | ARCHITECTURE.md:378-397 | S |
| DOC-016 | S3 | Confirmed | NEW | ARCHITECTURE §4.6/§4.7: render_record.json and ~/.cache/hypelab caching not as described | ARCHITECTURE.md:362-372 | S |
| DOC-017 | S3 | Confirmed | NEW | ARCHITECTURE §6.3: adapters raise LiveRefused (not NotConfigured); collab cap is per-adapter (Meta allows 5, not ≤3) | ARCHITECTURE.md:456-464 | XS |
| DOC-018 | S3 | Confirmed | NEW | ARCHITECTURE §7: measure "6h schedule" and CLI "insufficient evidence" wording don't match code | ARCHITECTURE.md:480-486 | XS |
| DOC-019 | S3 | Confirmed | NEW | ARCHITECTURE §1.4 state-transition table stale vs current state machine | ARCHITECTURE.md:110-133 | S |
| DOC-020 | S3 | Confirmed | NEW | README: `render --aspect 9:16,1:1` comma list rejected; --aspect takes one value | README.md:40 | XS |
| DOC-021 | S3 | Confirmed | NEW | README "Starter tier" terminology has no code counterpart | README.md:7 | XS |
| DOC-022 | S4 | Confirmed | NEW | README title "vertical slice" undersells current Books 1–3 scope; no Book 2/3 docs | README.md:1 | M |
| DOC-023 | S4 | Confirmed | NEW | Binary slice artifacts + kits tracked in git (mp4/png); no .gitignore policy stated | jobs/, kits/ | XS |
| DOC-024 | S4 | Confirmed | NEW | Env vars HYPELAB_ROOT/HYPELAB_DB/HYPELAB_LEASE_SECONDS/HYPELAB_CHROMIUM undocumented | (repo-wide) | S |

## Entries

### DOC-001 — README setup invokes `hypelab.cli doctor`, which does not exist
- **Severity:** S2 (setup instructions that fail on step 1 = project won't run from docs).
- **Location:** README.md:19.
- **Evidence:** `python3 -m hypelab.cli doctor` → `Error: No such command 'doctor'.` No `doctor` in cli.py/b2cli.py/book3cli.py (`grep -rn 'def doctor'` → nothing; `--help` lists 29 commands, no doctor).
- **What's wrong:** The README's only environment check doesn't exist. A new user stalls at setup.
- **Impact:** Every new user hits a dead command; also misdirects about edge-tts/fonts checks (edge-tts is used nowhere in current code).
- **Suggested fix:** Either implement a real `doctor` (ffmpeg/ffprobe/faster-whisper/Chromium/fonts/DB checks) or replace the step with the working equivalents (`python3 -m hypelab.cli migrate`, `ffmpeg -version`). Phase 5.

### DOC-002 — README walkthrough commands are all stale
- **Severity:** S2 (the entire quickstart is non-executable).
- **Location:** README.md:27-43.
- **Evidence:** `kit new --name/--appearance` vs actual `kit new <kit_id> --from <file>` (cli.py:366); `new <kit_id> --script` vs `new --kit <id> --script` (cli.py:394); `attach … --provenance` — no such option, vo/music via `audio --vo/--music` (cli.py:554); `align`, `plan`, `show` — no such commands; `publish <job> --target` vs `publish --job/--collab/--media` (book3cli.py:126).
- **What's wrong:** Written against the slice-era argparse CLI; the click rewrite (Books 1–3) changed every signature.
- **Impact:** Zero walkthrough steps work as written. New-user onboarding is broken.
- **Suggested fix:** Rewrite the walkthrough against current `--help` output and run it end-to-end in Phase 5.

### DOC-003 — README "What is NOT built yet" lists M5/M7/M8/M9 as unbuilt — all built
- **Severity:** S2 (materially misleads about product state).
- **Location:** README.md:61-64.
- **Evidence:** M7 carousel command exists (book3cli.py:95; carousel.py headless Chromium). M8 clip mine exists (b2cli.py: campaign/source/moments/cut/tray; commit 81aaf52 "Books 1-3 complete"). M9 measure/worked/feedback exist (b2cli.py:385-420; attribution.py n≥30 gating). M5: 1:1 derivation proven (master_1x1.mp4), ducking (render.py:196-206), loudnorm, _retarget_edl (cli.py:639).
- **What's wrong:** Stale slice-era status presented as current.
- **Impact:** Undersells the product; contradicts the repo's own git history.
- **Suggested fix:** Replace with an accurate current-status section in Phase 5.

### DOC-004 — README test command is wrong (unittest vs pytest)
- **Severity:** S2 (contributors can't run tests from docs).
- **Location:** README.md:48-50.
- **Evidence:** tests/ use pytest fixtures (test_foundation.py imports pytest, `conn(tmp_path)` fixture). `python3 -m unittest discover -s tests -v` cannot run them. Correct: `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest tests/` → 191 passed, 198.64s (2026-09-29).
- **Suggested fix:** One-line replacement in Phase 5.

### DOC-005 — README documents HYPELAB_HOME; code reads HYPELAB_ROOT/HYPELAB_DB
- **Severity:** S3.
- **Location:** README.md:18.
- **Evidence:** grep HYPELAB_HOME in hypelab/ + tests/ → zero hits. cli.py:87-103 reads HYPELAB_ROOT, HYPELAB_DB, HYPELAB_LEASE_SECONDS. Artifacts now in work/<job_id>/ (util.py:173), not jobs/<job>/.
- **Suggested fix:** Document the real variables (also HYPELAB_CHROMIUM, carousel.py:68).

### DOC-006 — ARCHITECTURE §§1.2–1.3 describe a tasks-table queue that doesn't exist
- **Severity:** S2 (core architecture doc misdescribes the core subsystem).
- **Location:** ARCHITECTURE.md:44-106.
- **Evidence:** No tasks table in migrations; no enqueue_task/idempotency_key in hypelab/. Queue is job-level (queue.py:59-204). LEASE_TTL_S = 1800 (30 min, queue.py:28), not "10 minutes". No run_after/backoff — fail() is terminal (queue.py:172-204). No `cancel`/`retry` commands (`--help` verified).
- **Impact:** Anyone implementing against this doc (retries, cancellation, lease tuning) builds against a phantom design.
- **Suggested fix:** Rewrite §§1.2–1.3 for the job-level queue in Phase 5.

### DOC-007 — ARCHITECTURE §1.6: services.py missing; "no business logic in CLI" false; remote-control design absent
- **Severity:** S2.
- **Location:** ARCHITECTURE.md:163-167.
- **Evidence:** hypelab/services.py doesn't exist; cli.py header says it was superseded (cli.py:1-9). cli.py is 997 lines with _do_align, _render_job, _run_gates, normalize_numbers. No Telegram bot/dashboard; authorize.py is DB approval rows, no bearer tokens/constant-time compare.
- **Suggested fix:** Describe the actual layering (click CLI + modules + DB) in Phase 5.

### DOC-008 — ARCHITECTURE §1.5: jobs.cost_usd/jobs.budget_usd don't exist; no budget enforcement
- **Severity:** S3 (cost-safety feature documented but absent).
- **Location:** ARCHITECTURE.md:155-157.
- **Evidence:** grep cost_usd/budget_usd in migrations + hypelab/ → zero hits. cost_ledger has (job_id, at, provider, unit, qty, usd, note). `costs` command exists (cli.py:941) but nothing charges.
- **Impact:** An operator believing budgets are enforced could incur spend once paid providers exist.
- **Suggested fix:** Either implement or reword to "ledger exists; enforcement future".

### DOC-009 — ARCHITECTURE §3.3 render.json schema stale
- **Severity:** S2.
- **Location:** ARCHITECTURE.md:236-290.
- **Evidence:** edl.py has no edl_version; EDL_SCHEMA requires mode/kit/target/beats/audio/captions/overlays/gates_passed (edl.py:18-30), mode ∈ ["original","clip"]; no reframe/creative/compliance/render_hash fields. Hook rule is "exactly one hook at beats[0]" (edl.py:126-160).
- **Suggested fix:** Regenerate §3.3 from edl.py in Phase 5.

### DOC-010 — ARCHITECTURE schema listings mismatch actual tables (kits, assets, targets, consents)
- **Severity:** S3.
- **Location:** ARCHITECTURE.md:179-217 (§2.1/§2.2), :414-428 (§6.1).
- **Evidence:** kits = (id, version, data_json, created_at) — kit fields live in data_json, not typed columns. No assets table — manifest.json per work dir (manifests.py:249-305). targets lacks invite_history_json/outcome; consents lacks asset_version/revoked_at (migrations/0001:195-222).
- **Suggested fix:** Regenerate from migrations in Phase 5.

### DOC-011 — ARCHITECTURE Required outputs §2 module list stale
- **Severity:** S2 (map of the codebase is wrong).
- **Location:** ARCHITECTURE.md:553-583.
- **Evidence:** Named but missing: services.py, worker.py, tasks_lab.py, plan.py, assets.py, audio.py, config.py, modes_b.py, measure.py, publish.py (now a package). Present but unlisted: script.py, jobs.py, manifests.py, util.py, b2cli.py, book3cli.py, authorize.py, campaigns.py, cut.py, ingest.py, invites.py, metrics.py, pitch.py, reframe.py, score.py, signals.py, tray.py, watcher.py, feedback.py, attribution.py, compliance.py, publish/{base,dryrun,meta,providers}.py, weights/.
- **Suggested fix:** Regenerate from git ls-files in Phase 5.

### DOC-012 — ARCHITECTURE promises docs/WALKTHROUGH.md and docs/OPERATIONS.md — docs/ is empty
- **Severity:** S2.
- **Location:** ARCHITECTURE.md:584-586.
- **Evidence:** `ls docs/` → empty (2026-09-29). The M10 milestone ("Docs: whitepaper-equivalent… matches implementation") depends on these.
- **Suggested fix:** Write them in Phase 5 (walkthrough against the real CLI; operations: DB backup, lease recovery, env vars).

### DOC-013 — ARCHITECTURE Required outputs §5 CLI reference stale
- **Severity:** S2.
- **Location:** ARCHITECTURE.md:610-628.
- **Evidence:** Lists kit show/bump, plan, show, publish [--dry-run] [--i-confirm], carousel <article> --kit, pitch <job> --target, cancel, retry, backup, doctor — none exist. Actual 29 commands from `--help`.
- **Suggested fix:** Regenerate from `--help` in Phase 5.

### DOC-014 — ARCHITECTURE §8 ops claims false (secrets.env, fetch --url, backup, ulimit/nproc, upload validation)
- **Severity:** S2 (security/ops properties claimed but not implemented).
- **Location:** ARCHITECTURE.md:492-509.
- **Evidence:** No ~/.config/hypelab/secrets.env reference in code. No fetch/backup commands. watcher.py auto-polls source URLs via urllib (watcher.py:22,71) — contradicts "only explicit hypelab fetch --url". FFMPEG_TIMEOUT=600 (10 min, render.py:26), not 30; no ulimit/nproc cap found. intake_asset: atomic+sha256+race-checks+ffprobe (util.py:119-170; manifests.py:279-305) — no extension allowlist, magic bytes, size caps, duration caps, or symlink rejection.
- **Impact:** Security posture is weaker than documented; operators may rely on controls that don't exist.
- **Suggested fix:** Implement the missing controls or rewrite §8 to describe reality in Phase 5 (implement first — several are BLD/SEC-adjacent).

### DOC-015 — ARCHITECTURE §5.1 gate table names/thresholds stale
- **Severity:** S3.
- **Location:** ARCHITECTURE.md:378-397.
- **Evidence:** Current gates: duration, loudness, first_frame, hook_budget, caption_safe, slots_filled, geometry, word_confidence (gates.py:31-32). Table lists aspect/hook/captions_safe/audio_present instead.
- **Suggested fix:** Regenerate from gates.py in Phase 5.

### DOC-016 — ARCHITECTURE §4.6/§4.7: render_record.json and ~/.cache/hypelab not as described
- **Severity:** S3.
- **Location:** ARCHITECTURE.md:362-372.
- **Evidence:** Record now work/manifest.json with {render_hash, provenance, ffmpeg_argv, started_at, finished_at, input_hashes} (manifests.py:312-331). No HYPELAB_CACHE / clipseg cache in render.py.
- **Suggested fix:** Update in Phase 5.

### DOC-017 — ARCHITECTURE §6.3: adapters raise LiveRefused (not NotConfigured); collab cap is per-adapter
- **Severity:** S3.
- **Location:** ARCHITECTURE.md:456-464.
- **Evidence:** providers.py:29-34, meta.py:60-66 raise LiveRefused. Native Meta cap is 5 (meta.py:31), not ≤3; publicity is a cached observation (publish/__init__.py:104-111). isAIGenerated: true enforcement is correct.
- **Suggested fix:** Reword in Phase 5.

### DOC-018 — ARCHITECTURE §7: "6h schedule" and "insufficient evidence" wording don't match code
- **Severity:** S3.
- **Location:** ARCHITECTURE.md:480-486.
- **Evidence:** `measure` is manual (b2cli.py:385-395); metrics cadence "operational, not enforced" (metrics.py:8-9); sources poll per poll_every_s default 900s. worked prints "(N bucket(s) below n=30: listed, not interpreted)" (b2cli.py:414-419), not "insufficient evidence".
- **Suggested fix:** Reword in Phase 5.

### DOC-019 — ARCHITECTURE §1.4 state-transition table stale
- **Severity:** S3.
- **Location:** ARCHITECTURE.md:110-133.
- **Evidence:** Current states: scripted, awaiting_media, queued_align/aligning, queued_render/rendering, queued_gates/gating, ready, gate_failed, failed (+ Book 2/3 states; jobs.py:50-77). Table's draft/asset_building/pitch_sent/scheduled states and cancel/retry triggers don't match.
- **Suggested fix:** Regenerate from jobs.py + state_migrations.py in Phase 5.

### DOC-020 — README: `render --aspect 9:16,1:1` comma list is rejected
- **Severity:** S3.
- **Location:** README.md:40.
- **Evidence:** --aspect is click.Choice single value (cli.py:742-744). Multi-aspect = repeated invocations + _retarget_edl (cli.py:639-644).
- **Suggested fix:** Fix in the walkthrough rewrite (DOC-002).

### DOC-021 — README "Starter tier" terminology has no code counterpart
- **Severity:** S3.
- **Location:** README.md:7.
- **Evidence:** grep starter/pro-tier in hypelab/*.py → nothing. ARCHITECTURE §3.2 also leans on it.
- **Suggested fix:** Define or drop the term in Phase 5.

### DOC-022 — README title "vertical slice" undersells Books 1–3; no Book 2/3 docs
- **Severity:** S4 (info/positioning).
- **Location:** README.md:1.
- **Evidence:** Commit 81aaf52 "HypeLab Books 1-3 complete: foundation, clip mine, hype layer". README covers only the Mode A slice.
- **Suggested fix:** Expand README scope in Phase 5.

### DOC-023 — Binary slice artifacts + kits tracked in git; no .gitignore policy
- **Severity:** S4 (hygiene).
- **Location:** jobs/job_c656669a5147/ (mp4s, png), kits/cerebratico/kit.json.
- **Evidence:** git ls-files shows master.mp4 (10.6 MB), master_1x1.mp4, caption_proof.png, asset mp4s tracked. Fine as evidence; worth an explicit decision (keep as fixtures vs gitignore).
- **Suggested fix:** Owner decision; see IDEAS.

### DOC-024 — Env vars HYPELAB_ROOT/HYPELAB_DB/HYPELAB_LEASE_SECONDS/HYPELAB_CHROMIUM undocumented
- **Severity:** S4 (docs gap).
- **Location:** repo-wide.
- **Evidence:** Read in cli.py:87-103 and carousel.py:68; documented nowhere.
- **Suggested fix:** Env-var section in README or OPERATIONS.md (Phase 5).
