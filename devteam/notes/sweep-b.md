# SWEEP-B notes — files N–Z (read-only sweep, 2026-09-28)

Branch: `devteam/review-2026-09-29` (confirmed). Existing findings lanes checked
first (arc/bld/bug/dat/doc/map/sec/str/tst — BUG-001…015 etc.); overlaps are
referenced, not re-filed.

Modules covered (all read fully): `pitch.py`, `queue.py`, `reframe.py`,
`render.py`, `score.py`, `script.py`, `tray.py`, `util.py`, `watcher.py`,
`publish/{__init__,base,dryrun,meta,providers}.py`, `__init__.py`.
NOT present (skipped, no phantom files): parallel.py, platform/, postiz.py,
priors.py, secrets.py, show.py, slots.py, store.py, tts.py, validate.py,
voice.py, work.py, worker.py. (`publish/providers.py` exists and was read;
`weights/` is data JSON, not code.)

---

## pitch.py (275 lines)

- What it does: pitch.md template rendering, target rows, pitch attempts
  ledger, outcome recording, kill-tripwire status, voice-match hypothesis
  machinery with plagiarism cap.
- Checked: placeholder substitution, consent_state transitions, OUTCOMES
  validation, voice_profile/plagiarism_check math, kill threshold logic.
- `record_pitch_outcome("accepted")` sets consent_state='pitched' (pitch.py:169).
  Checked against consent.py:102 (`'granted'` only via consent.grant) and
  invites.py:114 (declined → back to 'pitched'): an accepted pitch is not a
  recorded consent grant (no scope terms artifact), so leaving 'pitched' is
  arguably deliberate. NOT filed — informational only.
- `make_pitch` hard-codes the scope sentence "one Instagram collab post, your
  handle as co-author, 30-day window" (pitch.py:115) while accepting a
  `platform` param — and the module docstring says the scope "doubles as
  consents.scope". A non-Instagram pitch misstates scope → REV-754.
- `render_pitch` regex `\{([a-z_]+)\}` (pitch.py:64): missing lowercase keys
  raise PitchError, but uppercase/digit placeholders pass through silently.
  pitch.md itself is all-lowercase so this is latent → REV-764 (S4).
- `plagiarism_check` (pitch.py:~245): builds (max_run+1)-word n-grams and
  flags overlap — matches the "no verbatim run longer than 5 words" docstring.
  Correct as written.
- `kill_threshold_status`: `tripped = n >= 20 and accepts < 3` — honest
  tripwire, matches the documented non-statistical framing. Fine.
- `ensure_target` commits inside, then `make_pitch` commits again — mixed
  transaction granularity but harmless.

## queue.py (232 lines)

- What it does: lease claim/heartbeat/release/fail + cost ledger for the
  Book 1 job queue.
- Checked: claim atomicity (UPDATE…RETURNING), lease expiry string
  comparisons, ACTIVE_TO_QUEUED reverse map, POISON threshold logic,
  charge() convention docs.
- `claim()` step 2 (crashed-worker reclaim, queue.py:~150) requires
  `lease_expires IS NOT NULL`. Active-state jobs with NULL leases (exactly
  what BUG-003 describes the CLI drive creating on failure) are therefore
  never reclaimable by any worker — the mechanism behind BUG-003's
  "unrecoverable without SQL". Referenced BUG-003, not re-filed.
- `fail()` POISON at attempts >= MAX_ATTEMPTS is consistent with
  per-claim attempt counting. The docstring's "work loop may re-queue"
  promise is already BUG-007.
- `release()` on an already-queued state is a silent no-op returning True
  (ACTIVE_TO_QUEUED.get(frm, frm)). Benign.
- Lease timestamps are all seconds-precision ISO strings; lexicographic
  `<=` comparisons are consistent. No issue found.
- `queue.charge()` zero production callers — already BUG-009.

## reframe.py (411 lines)

- What it does: 16:9→9:16 reframe planning (static/track/split/blurpad),
  Haar face detection, OCR text fail-closed, ffmpeg filter generation.
- Checked: mode-selection order (text check first, then faces, then
  inconclusive-text fail-closed — matches the documented contract),
  step_expr nesting, split-box math, track span merging.
- `both_persistent` (reframe.py:191): `n_samples = int((t_out-t_in)/0.25)`
  but `detect_faces` samples `t_in..t_out` inclusive → one more sample than
  the denominator; persistence fractions are slightly inflated on borderline
  cases → REV-757 (S4).
- `has_onscreen_text` temp frame (reframe.py:138): `/tmp/hypelab_textcheck_
  <hash(src)>.png` — `hash()` is process-salted but pid-less; two concurrent
  `plan_reframe` calls on the same src within one process collide
  (extract-then-delete race) → REV-758 (S4).
- `step_expr` (reframe.py:~355): nested `if(lt(t,tk))` builds the correct
  hold-and-cut step function (verified index algebra). Duplicate keyframe
  times would be ambiguous, but keyframes come from span starts which are
  strictly increasing.
- `choose_mode`: when text is inconclusive AND no faces, returns "no faces
  detected" before reaching the fail-closed branch — same outcome
  (blurpad), different `why` reason. Cosmetic.
- `two_speaker_boxes` median-of-empty-cluster: unreachable (distinct_faces
  > 1 guarantees both clusters non-empty given mid is strictly between
  min and max cx). Verified, no finding.

## render.py (576 lines)

- What it does: the ONLY ffmpeg argv builder; beat geometry, audio duck/mix,
  overlays, build_command (+manifest verification + render-hash skip),
  render() with crash-safe temp output, derive() previews.
- Checked: filter escaping helpers, input index alignment (beats 0..n-1,
  vo n, music n+1 — matches audio_chain's `[vi:a]`/`[mi:a]`), skip logic,
  crash-safe rename, renders/edls inserts.
- Music-only branch (render.py:220-228) applies `volume={duck_gain}` with
  default duck_db=-12, but the chain ends in single-pass
  `loudnorm=I=…` which erases any constant pre-gain — the -12 dB is a
  no-op that contradicts the audio_chain docstring ("music-only get a
  straight loudnorm", render.py:180) → REV-756 (S4). (In the vo+music
  branch the duck is real because loudnorm sees the mix.)
- `overlays_chain` (render.py:246-250): `y = H*0.10 if pos=="top" else
  H*0.90` — any typo'd/unknown pos silently lands at bottom → REV-759 (S4).
- `derive` (render.py:534-547): `_DERIVE_WH` has only 1:1 and 16:9 — no
  9:16, Book 2's primary aspect; and the output filename is
  `preview_1:1.mp4` (colon in filename) → REV-760 (S4).
- Render temp path (render.py:450) is PID-unique but not thread-unique →
  REV-768 (S4). The SIGKILL-reclaim reasoning in the comment is sound for
  the process model.
- `build_command`/`video_chain` on empty beats → `beats[-1]` IndexError;
  no EDL schema validation anywhere — already BUG-015, referenced.
- `_beat_geometry` reframe hook imports `from hypelab.reframe` (absolute)
  while the file otherwise uses relative imports — works, but fragile to
  repackaging. Note only.
- `_overlay_font` raises RenderError naming the missing font — good
  fail-closed. FFMPEG_TIMEOUT=600 is a hard cap on long renders — noted,
  not filed (operational choice).

## score.py (420 lines)

- What it does: 3-tier moment scoring (transcript heuristics, audio
  envelope, optional audience evidence), versioned weights, NMS, dedup,
  persistence.
- Checked: pattern weights, self-containment bonus, silence/astats parsers,
  weight selection, window loop, dedup hashing.
- `nms` (score.py:333): the `min_gap_s` parameter is DEAD — the body drops
  any window overlapping a kept one, ignoring the gap entirely. The name
  `NMS_MIN_GAP_S = 30.0` implies gap-based suppression that isn't
  implemented → REV-751 (S3).
- `load_weights` (score.py:246): "latest" chosen by lexicographic string
  sort of `version` — `"v10" < "v2"`, so the tenth weight set would lose to
  the ninth. Latent landmine → REV-752 (S3).
- `load_weights` also performs no schema validation: a weights file without
  `sets`/`version` keys surfaces later as KeyError in `score_windows`
  (score.py:265) → REV-771 (S4).
- `_parse_silences` comment (score.py:173) says a trailing silence_start is
  "closed at the last known point"; the code drops it. Stale comment →
  REV-766 (S4).
- `score_windows` tail rule (score.py:~296): `if t1 - t < 5.0 and out: break`
  — correct; a sub-5s source still yields one window.
- `audio_score_over` grid indexing and the fail-soft `audio_signals`
  wrapper are sound. `_audio_signals` rms normalization is min-max, so the
  dB→linear convention choice is moot. `content_hash` uses rounded t's —
  consistent with the rounded values persisted.

## script.py (85 lines)

- What it does: script text → timed beats (sentence split, speech-rate
  durations, hook/body/cta roles, proportional scaling to target_s).
- Checked: role assignment, duration formula, contiguity after rounding,
  validation of words_per_sec / min_beat_s / target_s.
- `max_clip_s` (script.py:49,55) is NOT validated, unlike its siblings:
  0/negative → zero/negative beat durations; `min_beat_s > max_clip_s`
  silently clamps every beat to max_clip_s → REV-753 (S3).
- Scaling below min_beat_s after the proportional fit is by design (target
  must be hit); extreme sentence counts could round to zero-length beats —
  degenerate-script path already has BUG-011 context. Noted, not filed.
- Single-sentence script → hook only, no cta. Matches the documented
  "exactly-one-hook" rule. Noted, not filed.

## tray.py (203 lines)

- What it does: manual-upload tray assembly — ranks compliant clips,
  materializes clip_NNNN dirs (mp4, caption, meta, submit.url, thumb).
- Checked: compliance re-gate flow, ranking, file moves, DB path updates.
- Re-running `build_tray` (tray.py:155-185) leaves zombie dirs: clips that
  fail re-gating keep their old `clip_NNNN/` dirs (caption.txt/meta.json/
  thumb.jpg) on disk, and re-ranking moves clip.mp4 between rank slugs
  while stale companions linger → REV-755 (S3).
- `_thumb` seeks to `-ss 1`; a sub-1s clip edge case is unhandled (not
  filed — cosmetic).
- Ranking `-(c.get("predicted") or 0.0)` handles NULL predicted. Fine.
- `tray_slug_for` returns None for missing rank or missing dir — sound.

## util.py (226 lines)

- What it does: now/new_id/sha256, ffprobe wrapper, atomic intake_asset,
  atomic write_json, work_dir.
- Checked: intake race procedure (stat→copy→hash→re-stat→replace→size
  check — sound), name validation, ffprobe error paths, atomic writes.
- `intake_asset` name check (util.py:137): `Path(name).name != str(name)`
  rejects separators but ACCEPTS `""` (`Path("").name == ""`) → later
  `os.replace(tmp, dst_dir)` raises IsADirectoryError deep in the flow →
  REV-763 (S4).
- `ffprobe` (util.py:~80): validated arg array, no shell, MediaError on all
  failure modes — sound. `width`/`height` are None-tolerant by design.
- `work_dir` default root hard-codes `/home/dino/hypelab` — deployment
  assumption, noted.

## watcher.py (293 lines)

- What it does: source polling (yt-dlp flat playlist, RSS/Atom, manual
  JSON), allowlist, rights-manifest-gated source registration, ingest-job
  enqueue.
- Checked: poll cadence floor, dedup, allowlist logic, lister dispatch.
- `add_source` (watcher.py:170) accepts kind `"twitch"`, but
  `list_new_items` (watcher.py:124) has no twitch branch — twitch sources
  are registered successfully and then fail closed on EVERY poll
  (WatcherError caught at watcher.py:253, last_polled updated, retried
  forever, never lists) → REV-750 (S3).
- `_rss_items` (watcher.py:92-94): `[:limit]` applied to RSS items and Atom
  entries separately, then concatenated → up to 2×limit items →
  REV-765 (S4).
- `poll` (watcher.py:293-297): `str(items[-1].get("id"))` stores the literal
  string "None" as last_item_id when the id is missing → REV-769 (S4).
- `source_allowed` substring matching is documented ("must contain") —
  checked, intentional. `MIN_POLL_EVERY_S=300` floor enforced via max().
  `record_clearance` keeps basis='needs_clearance' — documented.

## publish/ (5 files)

- base.py: Publisher ABC + ProviderCapabilities + LiveRefused. The
  "stubs fail loudly with NotImplementedError" README claim vs LiveRefused
  is already a DOC-lane item (referenced, not re-filed).
- `check_collaborator_cap` (base.py:~58): fail-closed on None cap and
  over-cap, never truncates — matches the documented contract.
- __init__.py `instagram_preflight` (publish/__init__.py:104) runs for ALL
  platforms and consults Instagram target publicity records — misleading
  name → REV-761 (S4).
- `PUBLISHABLE_STATES` (publish/__init__.py:46) includes a job state literally
  named `"dry_run"`, colliding conceptually with the adapter's `dry_run`
  flag → REV-762 (S4).
- `publish_job` order (auth → preflight → consent re-check → adapter →
  ledger) matches the module docstring. Consent keys on the relationship
  (job, handle, platform), fingerprint is provenance-only — documented
  choice, checked.
- NativeMetaPublisher (meta.py:54-74) duplicates
  `_FixtureDelegatingPublisher.create_post` line-for-line instead of
  subclassing; the instagram `is_ai_generated` dry-run check is now in
  three places (meta.py, providers.py, dryrun.py) → REV-767 (S4).
- dryrun.py fixture backend is deterministic and sends nothing — as
  documented. `fixture_post_id` module function constructs a throwaway
  publisher — cheap, fine.

## __init__.py

- 5 lines; package marker only. Nothing to note.
