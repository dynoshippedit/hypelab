# REV findings — SWEEP-B (files N–Z)

Fresh-eyes full-file sweep of HypeLab modules N–Z, branch
`devteam/review-2026-09-29`. IDs REV-750…799 reserved for this lane.
Source read-only; all "Confirmed" below rest on unambiguous code with
cited lines. Existing lanes (BUG-001…015 etc.) checked first; overlaps
are referenced, not re-filed.

## Ledger

| ID | Title | Sev | Status |
|---|---|---|---|
| REV-750 | `watcher.add_source` accepts "twitch" kind that `list_new_items` cannot list | S3 | NEW |
| REV-751 | `score.nms` `min_gap_s` parameter is dead — any overlap is dropped | S3 | NEW |
| REV-752 | `load_weights` picks "latest" by lexicographic version sort ("v10" < "v2") | S3 | NEW |
| REV-753 | `script.to_beats` never validates `max_clip_s` (0/negative; min>max silent clamp) | S3 | NEW |
| REV-754 | `make_pitch` hard-codes an Instagram scope sentence for any platform | S3 | NEW |
| REV-755 | `tray.build_tray` re-run leaves zombie tray dirs for dropped/re-ranked clips | S3 | NEW |
| REV-756 | `render.audio_chain` music-only `duck_db=-12` is erased by the following loudnorm | S4 | NEW |
| REV-757 | `reframe.both_persistent` sample-count denominator off by one | S4 | NEW |
| REV-758 | `reframe.has_onscreen_text` /tmp frame name lacks pid — same-src concurrent collision | S4 | NEW |
| REV-759 | `render.overlays_chain` maps any non-"top" pos to bottom (typos silent) | S4 | NEW |
| REV-760 | `render.derive` has no 9:16 aspect and writes `preview_1:1.mp4` (colon in filename) | S4 | NEW |
| REV-761 | `publish.instagram_preflight` runs for every platform, not just Instagram | S4 | NEW |
| REV-762 | Job state literally named `"dry_run"` collides with the adapter `dry_run` flag | S4 | NEW |
| REV-763 | `util.intake_asset` accepts `name=""` → IsADirectoryError deep in the flow | S4 | NEW |
| REV-764 | `pitch.render_pitch` regex silently passes through uppercase/digit placeholders | S4 | NEW |
| REV-765 | `watcher._rss_items` applies `[:limit]` per feed type, returns up to 2×limit | S4 | NEW |
| REV-766 | `score._parse_silences` comment claims trailing-silence handling the code doesn't do | S4 | NEW |
| REV-767 | `NativeMetaPublisher` duplicates `_FixtureDelegatingPublisher.create_post` instead of subclassing | S4 | NEW |
| REV-768 | `render()` temp path is PID-unique but not thread-unique | S4 | NEW |
| REV-769 | `watcher.poll` stores literal `"None"` as `last_item_id` when the item has no id | S4 | NEW |
| REV-771 | `score.load_weights` does no schema validation — bad weights file fails as KeyError later | S4 | NEW |

---

### REV-750 — `watcher.add_source` accepts "twitch" kind that `list_new_items` cannot list
- **Severity:** S3 (dead source kind; operator-visible misbehavior).
- **Status:** Confirmed.
- **Evidence:** `hypelab/watcher.py:170` — `add_source` allows
  `("yt_channel", "rss", "twitch", "manual")`. `hypelab/watcher.py:124-136`
  (`list_new_items`) has branches only for `yt_channel`, `rss`, `manual` and
  raises `WatcherError(f"unknown source kind {kind!r}")` for twitch. The CLI
  also offers twitch (`hypelab/b2cli.py:157`). On every poll the WatcherError
  is caught (`watcher.py:253-260`), `last_polled` is updated, and the source
  is retried forever — it registers successfully and silently never lists.

### REV-751 — `score.nms` `min_gap_s` parameter is dead
- **Severity:** S3 (effective suppression radius is the window width, 45 s,
  not the documented 30 s gap).
- **Status:** Confirmed.
- **Evidence:** `hypelab/score.py:333-345` — `nms(windows, min_gap_s=...)`
  drops any window overlapping a higher-scoring kept window; `min_gap_s` is
  never referenced in the body. Called as `nms(..., min_gap_s=NMS_MIN_GAP_S)`
  at `hypelab/score.py:330` with `NMS_MIN_GAP_S = 30.0` (`score.py:26`).
  Either the gap semantics should be implemented or the parameter/name
  should be removed.

### REV-752 — `load_weights` picks "latest" by lexicographic version sort
- **Severity:** S3 (latent; fires when a tenth weight set exists).
- **Status:** Confirmed.
- **Evidence:** `hypelab/score.py:246-248` —
  `pool.sort(key=lambda fd: str(fd[1].get("version", "")))` then
  `pool[-1][1]`. With versions "v1"… "v10", lexicographic order puts "v10"
  before "v2", so "v9" would win over "v10". Current file is
  `hypelab/weights/weights_v1.json` (`"version": "v1"`), so this never fires
  today — a silent landmine for the versioned-weights contract.

### REV-753 — `script.to_beats` never validates `max_clip_s`
- **Severity:** S3 (missing validation in a real path).
- **Status:** Confirmed.
- **Evidence:** `hypelab/script.py:42-55` — `words_per_sec` and `min_beat_s`
  raise ValueError when non-positive; `max_clip_s = float(gen.get(
  "max_clip_s", 10.0))` at line 49 is used raw at line 55:
  `min(max(words/words_per_sec, min_beat_s), max_clip_s)`. A kit with
  `max_clip_s=0` yields zero-length beats, negative yields negative
  durations, and `min_beat_s > max_clip_s` silently clamps every beat to
  `max_clip_s` with no error.

### REV-754 — `make_pitch` hard-codes an Instagram scope sentence for any platform
- **Severity:** S3 (wrong content; the scope doubles as `consents.scope`).
- **Status:** Confirmed.
- **Evidence:** `hypelab/pitch.py:89-115` — `make_pitch(..., platform:
  str = "instagram", ...)` accepts any platform, but line 115 sets
  `scope = "one Instagram collab post, your handle as co-author, 30-day
  window"` unconditionally. The module docstring (`pitch.py` header) says
  the scope "doubles as consents.scope, so the pitch and the grant must
  match word for word" — a non-Instagram pitch ships a false scope.

### REV-755 — `tray.build_tray` re-run leaves zombie tray dirs
- **Severity:** S3 (stale on-disk artifacts; re-rank shuffles files).
- **Status:** Confirmed.
- **Evidence:** `hypelab/tray.py:155-185` — on re-run, clips whose re-gate
  failed are excluded, but their old `tray/clip_NNNN/` dirs
  (caption.txt/meta.json/submit.url/thumb.jpg) are never removed. When the
  ranking changes, `src_mp4.replace(dst_mp4)` moves clip.mp4 files between
  rank slugs while the stale companions (caption/meta/thumb from the
  previous occupant) linger in the old dirs.

### REV-756 — `render.audio_chain` music-only `duck_db=-12` is erased by loudnorm
- **Severity:** S4 (dead code contradicting the docstring).
- **Status:** Confirmed.
- **Evidence:** `hypelab/render.py:220-228` — the music-only branch applies
  `volume={duck_gain}` with default `duck_db=-12.0`, but the chain ends in
  single-pass `loudnorm=I={lufs}:TP=-1.5:LRA=11`, which normalizes the whole
  output to the target LUFS and erases any constant pre-gain. The
  `audio_chain` docstring (`render.py:180`) says "vo-only / music-only get a
  straight loudnorm" — the vo-only branch does; the music-only branch does
  not. (In the vo+music branch the duck is real because loudnorm sees the
  mix.)

### REV-757 — `reframe.both_persistent` sample-count denominator off by one
- **Severity:** S4 (borderline-case inflation).
- **Status:** Confirmed.
- **Evidence:** `hypelab/reframe.py:191-193` — `n_samples = max(1,
  int((t_out - t_in) / FACE_STEP_S))`, but `detect_faces` samples
  `t_in..t_out` inclusive (`reframe.py:86`, `while t <= float(t_out)`), so
  the actual maximum sample count is one more than the denominator.
  Persistence fractions are slightly inflated, which can flip borderline
  split/track decisions at the 0.6 threshold. (Failed frame reads push the
  other way; net effect is small.)

### REV-758 — `reframe.has_onscreen_text` /tmp frame name lacks pid
- **Severity:** S4 (same-process concurrent collision).
- **Status:** Confirmed.
- **Evidence:** `hypelab/reframe.py:138` —
  `frame = Path(f"/tmp/hypelab_textcheck_{abs(hash(str(src))) % 10**8}.png")`.
  `hash()` is process-salted, so two *processes* don't collide, but two
  concurrent `plan_reframe` calls on the same `src` within one process get
  the identical path: extract-frame → tesseract → delete races between
  them.

### REV-759 — `render.overlays_chain` maps any non-"top" pos to bottom
- **Severity:** S4 (silent misplacement).
- **Status:** Confirmed.
- **Evidence:** `hypelab/render.py:246-250` —
  `y = H * 0.10 if ov.get("pos") == "top" else H * 0.90`. Any other value
  ("middle", a typo like "Top") silently renders at the bottom with no
  validation or warning.

### REV-760 — `render.derive` has no 9:16 aspect and writes a colon filename
- **Severity:** S4.
- **Status:** Confirmed.
- **Evidence:** `hypelab/render.py:534` —
  `_DERIVE_WH = {"1:1": (1080, 1080), "16:9": (1920, 1080)}`; Book 2's
  primary aspect (9:16) cannot get a preview cutdown. And `render.py:554`
  builds `work / f"preview_{aspect}.mp4"` → `preview_1:1.mp4` — a colon in
  the filename, legal on Linux but hostile to Windows/shares.

### REV-761 — `publish.instagram_preflight` runs for every platform
- **Severity:** S4 (misleading name; wrong-record lookups for non-IG).
- **Status:** Confirmed.
- **Evidence:** `hypelab/publish/__init__.py:104-131` — the function is
  named `instagram_preflight` but `publish_job` calls it unconditionally
  (`publish/__init__.py` line ~165) with whatever `platform` was passed,
  and it looks up Instagram `targets` publicity records for collaborators
  even when publishing elsewhere.

### REV-762 — Job state literally named `"dry_run"` collides with the adapter flag
- **Severity:** S4 (naming).
- **Status:** Confirmed.
- **Evidence:** `hypelab/publish/__init__.py:46` —
  `PUBLISHABLE_STATES = ("ready", "consent_granted", "scheduled",
  "dry_run")`. "dry_run" is both a job *state* and the adapter's
  `dry_run=True/False` *mode* flag (base.py, dryrun.py); a job in state
  `dry_run` published with `dry_run=False` is a confusion trap in logs and
  gate messages.

### REV-763 — `util.intake_asset` accepts `name=""`
- **Severity:** S4 (deep confusing failure).
- **Status:** Confirmed.
- **Evidence:** `hypelab/util.py:137` —
  `if Path(name).name != str(name): raise ValueError(...)`. `Path("").name`
  is `""`, so `name=""` passes validation; later `os.replace(tmp,
  dst_dir / "")` attempts to replace the destination *directory* and raises
  `IsADirectoryError` far from the validation point.

### REV-764 — `pitch.render_pitch` regex silently passes through non-lowercase placeholders
- **Severity:** S4 (latent; inconsistent with the raise-on-missing behavior).
- **Status:** Confirmed.
- **Evidence:** `hypelab/pitch.py:64` —
  `re.sub(r"\{([a-z_]+)\}", _sub, text)`. A placeholder like `{CTA2}` or
  `{Handle}` is neither substituted nor flagged — it passes through
  silently, while a missing lowercase key raises PitchError. The shipped
  `pitch.md` is all-lowercase, so this is latent.

### REV-765 — `watcher._rss_items` returns up to 2×limit items
- **Severity:** S4.
- **Status:** Confirmed.
- **Evidence:** `hypelab/watcher.py:92-94` —
  `for entry in list(root.iter("item"))[:limit] + list(root.iter(
  "{http://www.w3.org/2005/Atom}entry"))[:limit]:` — the limit is applied
  to each feed dialect separately, then concatenated. A feed containing
  both RSS items and Atom entries yields up to 2×limit.

### REV-766 — `score._parse_silences` stale comment
- **Severity:** S4 (comment/code mismatch).
- **Status:** Confirmed.
- **Evidence:** `hypelab/score.py:173` — "A trailing silence_start with no
  end: close at the last known point." The code at lines 174-183 only
  appends spans for matched start/end pairs; an unmatched trailing start
  is dropped, not closed.

### REV-767 — `NativeMetaPublisher` duplicates the fixture-delegating skeleton
- **Severity:** S4 (duplication; triple-copy of the IG ai-label check).
- **Status:** Confirmed.
- **Evidence:** `hypelab/publish/meta.py:54-74` re-implements
  `_FixtureDelegatingPublisher.create_post` (`hypelab/publish/providers.py:
  52-72`) method-for-method instead of subclassing it. The Instagram
  `is_ai_generated=True` dry-run requirement now lives in three places:
  `meta.py:60-65`, `providers.py:58-63`, `dryrun.py:96-110` — a future
  policy change will need all three.

### REV-768 — `render()` temp path is PID-unique but not thread-unique
- **Severity:** S4.
- **Status:** Confirmed.
- **Evidence:** `hypelab/render.py:450` (and `derive` at line 551) —
  `tmp = out.with_name(f"{out.stem}.partial-{os.getpid()}{out.suffix}")`.
  Two renders of the same `out` in threads of one process share a pid and
  would interleave on the same temp path. The crash-safety comment's
  reasoning assumes the process model.

### REV-769 — `watcher.poll` stores literal `"None"` as `last_item_id`
- **Severity:** S4.
- **Status:** Confirmed.
- **Evidence:** `hypelab/watcher.py:293-297` —
  `str(items[-1].get("id")) if items else s["last_item_id"]`. When the last
  listed item has no `id`, the string `"None"` is persisted to
  `sources.last_item_id`.

### REV-771 — `score.load_weights` does no schema validation
- **Severity:** S4 (missing validation).
- **Status:** Confirmed.
- **Evidence:** `hypelab/score.py:220-248` — `load_weights` returns any
  JSON doc with a matching `version` (or the "latest" by string sort) with
  no check for the `sets`/`version` keys that `score_windows`
  (`score.py:265`: `weights["sets"]["full" if have_t3 else "blind"]` and
  `weights["version"]`) requires — a malformed weights file surfaces as a
  bare KeyError far from the load site.

---

## Overlaps checked but NOT re-filed

- BUG-003 (CLI drive parks jobs in active states with NULL leases):
  `queue.claim`'s crashed-worker reclaim (`queue.py` step 2) requires
  `lease_expires IS NOT NULL`, so those NULL-lease active jobs are also
  unreachable by any worker — the reclaim-side mechanism of BUG-003.
- BUG-007 (fail() docstring re-queue promise): confirmed present in
  `queue.py:168-180`; left to BUG-007.
- BUG-009 (`queue.charge()` zero callers): confirmed; left to BUG-009.
- BUG-015 (no EDL schema validation): `render.build_command`/`video_chain`
  assume `edl["beats"]` non-empty and `edl["target"]` complete
  (`beats[-1]` IndexError, `edl["target"]["aspect"]` KeyError) — left to
  BUG-015.
- DOC-lane item on README "stubs fail loudly with NotImplementedError" vs
  `LiveRefused` (`publish/base.py:31`): noted in claims-audit; not re-filed.
