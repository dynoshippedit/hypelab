# Pattern Pack — disposition sweep (HypeLab)

- **Branch:** `devteam/review-2026-09-29` (confirmed via `git rev-parse --abbrev-ref HEAD`)
- **Scope:** `hypelab/`, `tests/`, `migrations/` (excl. `devteam/`, `.git`, generated `jobs/` artifacts)
- **Pack source:** AI Dev Team Kit B6 (`/home/dino/Desktop/instructions/MASTER_PROMPT.md` §§238–312)
- **Method per pattern:** `rg -n` sweeps + targeted AST sweeps (Python `ast`) + manual review of every hit
- **Line numbers** are on the branch above, as observed 2026-09-28.
- **New findings filed:** PAT-600 – PAT-603 → `devteam/findings/pat.md`

## Per-pattern disposition table

| # | Pattern | Sweep method | Disposition |
|---|---------|--------------|-------------|
| 1 | Shell injection (`shell=True`, `os.system`, `os.popen`) | `rg` for `shell=True`/`os\.system`/`os\.popen`; inspected all 19 `subprocess.*` call sites | **DISMISSED — no instances.** Zero `shell=True`/`os.system`; every call passes an argv list with explicit `shell=False`, and argv elements are validated (ingest.py:151, score.py:103-108, tray.py:62-63, cut.py:59-60). Absorbed by SEC negative results. |
| 2 | Code execution (`eval(`, `exec(`, `pickle.loads`, `yaml.load`) | `rg` | **DISMISSED — no instances.** Sole `eval(` hit is `model.eval()` (torch, align.py:281). No pickle/YAML anywhere. Absorbed by SEC negative results. |
| 3 | SQL injection (f-string/`%`/concat SQL) | `rg` over all 178 `.execute(` sites; searched for `execute(f"`, `%`, `+`, `.format(` near SQL | **DISMISSED — no instances.** All queries parameterized. The only interpolation (attribution.py:57,139) builds an `IN (...)` list from the module constant `CALIBRATION_PROVENANCES` (fixed strings, no user input). Absorbed by SEC negative results. |
| 4 | Path traversal in intake | Read `intake_asset` (util.py:119-170) and `attach_asset` (manifests.py:249-310) in full | **DISMISSED — blocked.** Both reject traversal with `if Path(name).name != str(name): raise ValueError` (util.py:136, manifests.py:264). Absorbed by SEC negative results. |
| 5 | Secrets (assignments, key formats, history) | B6 secret regexes over tree; `git log -p --all -S` for `sk-` / `BEGIN PRIVATE KEY` / `password=` / `api_key` | **DISMISSED — clean.** Only false positive is `sp.token` (sentencepiece tokenizer var, align.py:322). The one `-S` hit was the BLD baseline doc *describing* the clean scan. BLD lane already recorded this as clean. |
| 6 | Silent exception swallowing (`except:` / `except Exception:` / `except X: pass`) | `rg` found 8 `except Exception:` sites + 9 `pass`-body handlers; inspected every one with context | **DISMISSED — no silent loss.** jobs.py:131 and db.py:97 re-raise after rollback; reframe.py:64/86/153 return explicit sentinels (`"unavailable:..."`, `"ocr:error"`); ingest.py:305 sets a documented `0.0` fallback that score.py:285-287 fails closed on (`<= 0` → `ScoreError`); carousel.py:304/437, util.py:169/225, manifests.py:176 are finally-block tmp-file cleanups; manifests.py:91 returns `"unknown"`; attribution.py:96-97 and gates.py:243-244 skip malformed records with narrow `(TypeError, ValueError)`. |
| 7 | Mutable default arguments | AST sweep over `hypelab/`, `tests/`, `migrations/` (`ast.List/Dict/Set` in defaults) | **DISMISSED — zero instances.** |
| 8 | `assert` used for validation | `rg ^\s*assert` | **DISMISSED.** Single hit providers.py:34 (`assert self._CAPS is not None`) is a subclass-contract invariant, not validation of external input. |
| 9 | `verify=False` / `DEBUG = True` | `rg` | **DISMISSED — zero instances.** |
| 10 | Weak crypto / randomness (`md5`, `sha1`, `random.`) | `rg -i` | **DISMISSED.** Hashing is `hashlib.sha256`; ids use `secrets.token_hex`; the `random` module is never imported. |
| 11 | Hardcoded paths (`/home/`, `/Users/`, `/opt/`) | `rg` | **CONFIRMED — 4 new instances, MAPPED to BLD-009** (same pattern, same fix class; recommend extending BLD-009's Location list): kits.py:18 (`CEREBRATICO_KIT_PATH`), db.py:26 (`DEFAULT_DB_PATH`), align.py:28 (`DEFAULT_CACHE_DIR`), util.py:173 (`work_dir(..., root="/home/dino/hypelab")` default). No new PAT finding (duplicate avoidance). |
| 12 | `print()` in library modules | `rg` for `print(` across `hypelab/` | **DISMISSED — no new instances.** Only ARC-315's three sites remain (score.py:419, watcher.py:240/278; line drift vs the finding's 414-415). CLI-module prints are the CLI's business per ARC-315. |
| 13 | TODO/FIXME/HACK/XXX/WORKAROUND markers | `rg -i` over `hypelab/` | **DISMISSED — zero instances.** |
| 14 | Duplicate definitions in one module | AST `Counter` of `FunctionDef` names per module | **DISMISSED — zero instances.** |
| 15 | Dead code paths (never-called functions) | AST call-graph (Name + Attribute calls) over `hypelab/`, then textual-ref check over `hypelab/`+`tests/`+docs for all zero-call candidates; click-decorator and `globals()["gate_"+name]`/`globals()[f"chk_{name}"]` string dispatch verified live by hand | **CONFIRMED — filed PAT-600** (one batched entry per kit B8). Genuinely dead: `authorize.list_for` (authorize.py:72), `campaigns.compliance_is_stale` (campaigns.py:158), `campaigns.get_rule_provenance` (campaigns.py:175), `compliance.unknowns_for_job` (compliance.py:318), `consent.require_consent` (consent.py:181), `render._esc_filter` (render.py:35 — dead *sanitizer*), `tray.tray_clips` (tray.py:183), `tray.tray_slug_for` (tray.py:194), `watcher.host_of` (watcher.py:289), `kits.seed_cerebratico` (kits.py:167), `publish/dryrun.fixture_post_id` (dryrun.py:107), `align._constrain_to_script` (align.py:569), `align.fetch_model` (align.py:159, production-dead). Mapped to existing: `queue.charge`→DAT-352, `queue.release`→BUG-007, `metrics.usd_per_clip_hour`→DAT-353. Dismissed as live: all click-registered CLI commands, `gates.gate_*` (string dispatch gates.py:452), `compliance.chk_*` (string dispatch compliance.py:183). Dismissed as intentional surface: test-exercised lib functions with no production caller (`metrics.best_views`, `metrics.record_user_metrics`, `pitch.voice_match`, `invites.poll_invite_metrics`, `util.db_to_lin`, `util.read_json`). |
| 16 | TOCTOU check-then-act | `rg` for `exists()`/`is_file()`/`is_dir()` (40 sites); manually reviewed every check-gating-state-change site | **CONFIRMED — filed PAT-601**: manifests.py:232-234 — quarantine unique-name loop (`while (qdir/qname).exists()`) then `src.rename(qdir/qname)`; a concurrent quarantine of the same asset name makes the second rename silently overwrite the first's quarantined file while the manifest records both. DISMISSED: render.py:457 (PID-unique tmp + atomic rename; a race only duplicates work), db.py:41 (fail-noisy, same-process), consent.py:39-45 (`_fingerprint` hash-pins at grant time by design), ingest.py:251 (`intake_asset` re-checks + stat-signature race detection). Mapped: BUG-006, DAT-355 already filed. |
| 17 | Unbounded resource consumption (no size caps) | Reviewed every network→memory and network→disk path | **CONFIRMED — filed PAT-602**: (a) watcher.py:71-72 — `_rss_items` does unbounded `r.read()` on a third-party feed URL (the `limit=20` caps parsed items, not bytes); (b) ingest.py:136-146 — `ytdlp_download` has no `--max-filesize` (2 h timeout, 1080p video can be multi-GB). Mapped: DOC-014 (intake size caps), STR-455 (work/ accumulation), DAT-364 (model download). |
| 18 | Unvalidated format strings / injection into filtergraphs, CSS, ASS | Reviewed every f-string interpolation into ffmpeg filters, `-vf`/`-filter_complex`, drawtext, crop, and carousel HTML/CSS | **CONFIRMED — no new instances; DISMISSED.** All live sinks are escaped (`_esc_sq`/`_esc_drawtext`: render.py:159,268-269,556; derive() render.py:553-559 all-literal) or numeric (`y={y:.1f}`, `volume={duck_gain:.4f}`, `scale/crop` ints). reframe.py:409's `'{expr}'` looks raw but `step_expr` input is `float()`/`int()`-coerced inside `reframe_filter` (reframe.py:403-406), so even a hand-edited plan fails noisily instead of injecting. `blurpad_geo` tag is `f"bp{i}"` (render.py:134). The "only two unescaped sinks" claim in SEC-106 still holds. Mapped: STR-453, STR-454, SEC-105, SEC-106. |
| 19 | Docstring lies (docstring/code mismatches) | Grepped docstrings for ONLY/NEVER/ALWAYS/atomic/fail-closed/exactly-one claims; verified each against code | **CONFIRMED — filed PAT-603**: `util.work_dir` docstring (util.py:180-181) claims work/`job_id`/ gets "atomic writes only (temp → fsync → rename; never a partial file at its final name)", but ingest.py:286,307 write `source.words.json` / `signals.json` and tray.py:165,167,170 write `caption.txt` / `meta.json` / `submit.url` via direct `write_text` — the atomic helper `util.write_json` (util.py:209) exists but is not used at these sites. (Companion lies folded into PAT-600's evidence: `kits.seed_cerebratico` docstring "the integrator seeds via CLI" — no CLI caller exists; `align._constrain_to_script` "kept for existing regression tests" — zero test references.) DISMISSED: consent.py:8 "no override flag" (verified — zero override/bypass matches), dryrun.py:3 "ONLY working mode" (live paths raise `LiveRefused`), queue.py "exactly one worker wins"→already BUG-006, align.py network-ONLY claim→already DAT-364, `ingest.py:300` "never invent a duration" (the `0.0` is a sentinel that score.py:285-287 fails closed on). Mapped: BUG-007, DAT-352, DAT-353. |

## Duplicates avoided (instances absorbed by existing findings)

| Existing ID | Pattern-pack instances absorbed (not re-filed) |
|---|---|
| BLD-009 | kits.py:18, db.py:26, align.py:28, util.py:173 (hardcoded-path siblings; recommend extending Location list) |
| DAT-352 | `queue.charge()` zero production callers |
| DAT-353 | `metrics.usd_per_clip_hour()` zero callers (same payout-never-written gap) |
| BUG-007 | `queue.release()` zero production callers |
| BUG-006 | queue.py "exactly one worker" docstring claim; claim-step TOCTOU |
| DAT-355 | `jobs.transition()` check-outside-transaction TOCTOU |
| DAT-361 | edge-tts docs-only reference (dead-code pattern precedent) |
| DAT-364 | align.py network-ONLY docstring lie; `fetch_model` production-dead (noted in PAT-600 as sibling) |
| STR-453 | ASS brace/backslash escaping |
| STR-454 | kit CSS tokens, drawtext `enable` |
| SEC-105 | kit CSS injection |
| SEC-106 | `enable` + reframe `split` boxes filtergraph sinks |
| SEC negatives | shell injection, SQL injection, path traversal, deserialization, secrets |
| ARC-315 | `print()` in watcher.py/score.py |
| DOC-014 | intake size caps; STR-455 work/ growth (resource pattern) |

## Open questions (with defaults)

1. **BLD-009 sibling instances** (kits.py:18, db.py:26, align.py:28, util.py:173): mapped, not re-filed. Default: BLD lane extends BLD-009's Location list in Phase 4. If the Lead prefers per-instance tracking, split out as PAT-604.
2. **Test-only library functions** (`metrics.best_views`, `metrics.record_user_metrics`, `pitch.voice_match`, `invites.poll_invite_metrics`, `util.db_to_lin`, `util.read_json`): treated as intentional public surface, not filed. Default: keep; add to PAT-600 if the Lead wants a full purge list.
3. **PAT-601 severity**: filed S3 (quarantine-evidence loss in a concurrent edge case). Default stands; Verifier calibrates (S4 defensible — single-operator design).

## Blockers

None. Read-only sweep; no commits, no pushes, no fixes applied.
