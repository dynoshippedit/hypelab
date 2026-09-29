# STR findings — Media Streaming Engineer (Phase 2, read-only)

Ledger entries for media-path issues. IDs STR-450 onward (range STR-450–499).
Status: NEW. Confidence: Confirmed (all verified against code on the Threadripper,
2026-09-29). Media-path trace: devteam/notes/flows/media-str.md.

## Index

| ID | Sev | Conf | Status | Title | Location | Effort |
|---|---|---|---|---|---|---|
| STR-450 | S2 | Confirmed | NEW | ffmpeg/yt-dlp decode third-party media with no sandboxing | render.py:467, ingest.py:138-149, score.py:137-146 | M |
| STR-451 | S2 | Confirmed | NEW | RSS watcher fetch is unbounded and parses untrusted XML with entity expansion | watcher.py:66-76 | S |
| STR-452 | S2 | Confirmed | NEW | "Deterministic render" overclaims: only render_hash is deterministic, not output bytes | render.py:400-412, cut.py:6-10 | S |
| STR-453 | S3 | Confirmed | NEW | ASS caption escaping misses backslash/newline (override-block residual) | captions.py:101 | XS |
| STR-454 | S3 | Confirmed | NEW | Unescaped sinks with no untrusted caller today: kit CSS, drawtext enable | carousel.py:107-130, render.py:275-277 | XS |
| STR-455 | S3 | Confirmed | NEW | work/<job>/ grows unbounded; SIGKILL orphans partial renders, no reaper | render.py:449-455 | S |
| STR-456 | S4 | Confirmed | NEW | loudnorm is single-pass by design; gate fails closed at ±1.0 LUFS (no two-pass needed) | render.py:196-248, gates.py:171-199 | XS |

## Positive verdicts (not findings — recorded so they aren't re-raised)

- **No `shell=True` anywhere.** Every subprocess invocation (26 sites, 11
  modules) builds an argv array; `shell=False` explicit everywhere except
  `gates.py:44` `_run`, which relies on the subprocess default (`False`).
  Grep for `shell=True|os.system` returns only comments documenting the ban
  (render.py:3, gates.py:14, util.py:60, ingest.py:151, carousel.py:7).
- **No missing timeouts.** All 26 subprocess sites carry timeouts (60 s
  probes … 600 s render … 7200 s yt-dlp download). `subprocess.run` kills
  the child on timeout; the exception feeds the worker's fail path.
- **Filenames cannot reach a shell.** Filtergraph interpolation is escaped
  (`_esc_sq`, `_esc_drawtext`, numeric `:.3f` formatting); `-i <path>`
  consumes leading-dash paths literally; destination names are fixed or
  name-validated (`Path(name).name == name`).
- **Attach-time integrity is strong:** `intake_asset` (util.py:140-205)
  atomic rename + sha256 + mid-copy mutation detection; `verify_manifest`
  re-hashes every asset before each `build_command` (render.py:357).

## Entries

### STR-450 — ffmpeg/yt-dlp decode third-party media with no sandboxing
- **Severity:** S2 (security weakness that needs conditions: a decoder/parser
  bug in the untrusted-bytes path).
- **Location:** render.py:467 (render ffmpeg), score.py:137-146 (silencedetect/
  astats on source.mp4), ingest.py:138-149 (`ytdlp_download`), ingest.py:157
  (16k extract), gates.py:65-123 (probes on the render).
- **Evidence:** All ffmpeg/ffprobe/yt-dlp/tesseract/Chromium invocations run
  as the invoking user with full filesystem access — no seccomp, no
  namespaces/bwrap, no capability drop, no chroot. Book 2 makes
  "third-party bytes → decoder" routine: `ytdlp_download` fetches arbitrary
  cleared URLs (`ingest.py:142`, argv-safe but redirect-following), and
  `score._audio_signals` + `ingest._transcribe_words` feed the downloaded
  file to ffmpeg. ffmpeg 8.1.2 demuxer/codec memory-corruption bugs would
  execute with the user's privileges.
- **What's wrong:** The STR card's "sandboxed, since ffmpeg on untrusted input
  is an attack surface" is not implemented. Likelihood is tempered by the
  operator-owned threat model (MAP §4: no remote attacker, operator chose the
  sources, rights gate precedes download) — hence S2, not S1.
- **Impact:** A malicious media file (or a compromised source feed item that
  passes the rights gate) reaching ffmpeg/yt-dlp could exploit a decoder bug
  as the local user.
- **Suggested fix (Phase 5):** Run third-party-media ffmpeg/yt-dlp under
  `bwrap` (Nobara ships bubblewrap) with `--ro-bind` on inputs, a private
  tmpfs work dir, `--unshare-net` for pure-decode passes; keep yt-dlp
  networked but confined to a scratch dir. Defense in depth; not urgent given
  the threat model.

### STR-451 — RSS watcher fetch is unbounded and parses untrusted XML with entity expansion
- **Severity:** S2 (remote-memory-exhaustion DoS from a hostile/compromised feed).
- **Location:** watcher.py:66-76 (`_rss_items`).
- **Evidence:**
  ```python
  with urllib.request.urlopen(url, timeout=30) as r:
      data = r.read()
  ...
  root = ET.fromstring(data)
  ```
  `r.read()` has no size cap — the whole body loads into memory. `ET.fromstring`
  parses attacker-controlled XML; Python's ElementTree does not resolve
  external entities but DOES expand internal entities (billion-laughs class).
  No Content-Length check, no content-type check. Feed URLs are
  operator-registered but feed *content* is third-party.
- **What's wrong:** A hostile or compromised RSS endpoint can OOM the watcher
  process (which runs inside `hypelab work`'s claim loop).
- **Impact:** Watcher crash / memory exhaustion; the poll loop dies mid-iteration
  (other due sources unpolled that round).
- **Suggested fix (Phase 5):** Cap the read (e.g. `r.read(2 << 20)` and reject
  oversize), enforce a Content-Length/Content-Type pre-check, and defuse
  entities (`xml.etree` → parse with `defusedxml` or a manual entity-count
  guard). Effort S.

### STR-452 — "Deterministic render" overclaims: only render_hash is deterministic, not output bytes
- **Severity:** S2 (docs that materially mislead; B7).
- **Location:** render.py:400-412 (argv), render.py:1 (docstring), cut.py:6-10,
  ARCHITECTURE.md:103.
- **Evidence:** The render argv has no `-fflags +bitexact` and no
  `-map_metadata -1` — ffmpeg writes `creation_time` and encoder-version
  tags, so identical EDLs produce byte-different MP4s. libx264 `preset
  medium` with default threading is not bit-exact run-to-run. `_overlay_font()`
  (render.py:55-66) picks the first existing TTF per machine; fontconfig
  rendering differs across OS builds. What IS deterministic and tested is
  `render_hash` = sha256(canonical EDL + canonical provenance + sorted input
  sha256s) (manifests.py:70-94; tests at test_pipeline.py:133-145,
  test_manifests.py:153-174 assert hash identity/sensitivity, never byte
  equality of outputs).
- **What's wrong:** "deterministic ffmpeg render chains", "same EDL + same
  source hash = same clip", "rendering is deterministic and idempotent"
  conflate content-addressed idempotency (true: the hash-skip works) with
  bit-reproducible output (false). Provenance deliberately includes the
  `ffmpeg -version` string, so the hash is not even stable across machines
  with different ffmpeg builds — by design, but undocumented.
- **Impact:** Anyone treating rendered MP4s as content-addressed (dedup,
  cache keys, reproducibility proofs) would be wrong; identical bytes are
  not reproducible.
- **Suggested fix (Phase 5):** Reword to "content-addressed idempotency
  (hash-skip); output bytes are not bit-reproducible"; optionally add
  `-fflags +bitexact -map_metadata -1` and single-threaded x264 for a true
  reproducible mode (slower; measure first). Effort S.

### STR-453 — ASS caption escaping misses backslash/newline (override-block residual)
- **Severity:** S3 (wrong behavior in an edge case; injection-class sink, low
  likelihood).
- **Location:** captions.py:96-103 (`build_ass`).
- **Evidence:** `text = wd["w"].replace("{", "\\{").replace("}", "\\}")` —
  override blocks `{...}` are neutralized, but backslash and raw newlines
  are not escaped. In ASS, literal `\n`/`\N` in dialogue text is a hard line
  break (interpreted by libass even outside override blocks); a raw newline
  in the word would split the `Dialogue:` line and corrupt the file.
  Words come from in-process faster-whisper (practically clean) or
  operator/fixture JSON (Book 2) — no attacker-controlled words today.
- **Impact:** Cosmetic caption corruption at worst; a malformed ASS could
  also trip the caption_safe gate (fail closed, not silent).
- **Suggested fix (Phase 5):** Strip or escape `\` and `\r\n` in `build_ass`
  alongside the brace escaping. Effort XS.

### STR-454 — Unescaped sinks with no untrusted caller today: kit CSS, drawtext enable
- **Severity:** S3 (latent injection sinks; no untrusted caller currently).
- **Location:** carousel.py:107-130 (`kit_to_css`); render.py:275-277
  (`overlays_chain` `enable`).
- **Evidence:** `kit_to_css` interpolates `fill`, `accent`, `font` raw into a
  `<style>` block — a value containing `"` or `</style>` breaks into HTML
  (slide *text* is properly `html.escape`d at carousel.py:135-136, but the
  *CSS tokens* are not). `overlays_chain` interpolates `enable` raw into
  `drawtext=...:enable='{enable}'` while `text=` goes through `_esc_drawtext`
  (render.py:250-252). Current callers are safe: kit is operator-seeded
  immutable v1; Book 1 passes `overlays=[]` (cli.py:445); Book 2 hardcodes
  `"between(t,0,2.05)"` (cut.py:74).
- **What's wrong:** Two sinks where a future caller passing third-party data
  (e.g. a campaign-supplied kit, a per-overlay schedule from feed metadata)
  gets filtergraph/CSS injection for free.
- **Impact:** None today; latent.
- **Suggested fix (Phase 5):** Validate kit CSS tokens against a strict
  pattern (`^#[0-9a-fA-F]{6}$`, font allowlist) at `kit seed` time; pass
  `enable` through `_esc_sq`. Effort XS.

### STR-455 — work/<job>/ grows unbounded; SIGKILL orphans partial renders, no reaper
- **Severity:** S3 (reliability/ops; disk is the failure mode).
- **Location:** render.py:449-455 (partial temp + orphan comment);
  util.py:207-234 (`work_dir` write domains); reframe.py:138-141
  (`/tmp/hypelab_textcheck_*.png`).
- **Evidence:** Every render leaves `out/<aspect>.mp4`, `assets/`,
  `manifest.json` (append-only renders/measurements), Book 2 `clips/`,
  `tray/`, `quarantine/` under `work/<job>/` with no retention, pruning, or
  quota — `.gitignore` ignores `/work/` but nothing else manages it. The
  render comment acknowledges a SIGKILLed worker orphans
  `out/<slug>.partial-<pid>.mp4` ("keeps writing to the temp file only") —
  those orphans are never reclaimed, and nothing reaps stale
  `hypelab_gate_*`/`hypelab_carousel_*` tempdirs after a kill (the normal
  path cleans them).
- **Impact:** Long-running `hypelab work` on the Threadripper slowly fills
  the disk; a full disk then fails every atomic write (fail-loud, but
  everything stops).
- **Suggested fix (Phase 5):** Startup reaper in `work` that deletes
  `*.partial-*` temps older than the oldest live lease; document a
  retention policy (e.g. keep last N renders per job); optionally warn at
  80% disk in `costs`/doctor. Effort S.

### STR-456 — loudnorm is single-pass by design; gate fails closed at ±1.0 LUFS (no two-pass needed)
- **Severity:** S4 (observation, not a defect).
- **Location:** render.py:196-248 (`audio_chain`); gates.py:171-199
  (`gate_loudness`).
- **Evidence:** Normalization is a single in-filter `loudnorm=I={lufs}:
  TP=-1.5:LRA=11` pass — there is no two-pass and therefore no loudnorm temp
  files to manage (single-pass needs none). The loudness gate re-measures
  integrated LUFS with a strict JSON parse (gates.py:140-168) and fails the
  job at |delta| > 1.0 LUFS, recording the measurement in the manifest.
  Single-pass loudnorm lands within ~±1 LUFS on full mixes, and any miss is
  a loud gate failure, never a silent bad master.
- **Note:** A two-pass would only tighten an already-gated value; not
  recommended unless gate failures on loudnorm become frequent.
