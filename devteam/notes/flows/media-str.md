# Media Path Trace — HypeLab (STR, Phase 2)

Author: STR (Media Streaming Engineer) · 2026-09-29
Scope: `hypelab/ingest.py`, `hypelab/render.py`, `hypelab/reframe.py`,
`hypelab/cut.py`, `hypelab/captions.py`, `hypelab/gates.py`,
`hypelab/manifests.py`, plus `util.py`, `watcher.py`, `score.py`,
`tray.py`, `carousel.py`, `cli.py` attach/audio/render paths.
Read every line cited. Static analysis only; no ffmpeg run on untrusted input.

Threat model (from devteam/MAP.md §4): single-binary local CLI, no server,
no auth — the operator IS the machine owner. Book 1 inputs are
operator-supplied files. Book 2 additionally ingests **third-party bytes**
(RSS/yt-dlp sources, rights-gated) and third-party-derived words (ASR).

## Hop-by-hop media path

### Hop 0 — operator attach (Book 1) / source registration (Book 2)

- Book 1: `hypelab attach <job> <beat_id> <file>` → `cli.py:505-554`.
  Beat ids are generated (`script.py:63` `f"b{i + 1}"`), so the asset name is
  fixed: `name = f"{beat_id}.mp4"` (`cli.py:525`). `audio --vo/--music` uses
  fixed names `vo.mp3` / `music.mp3` (`cli.py:563-588`). The *source* file is
  operator-chosen; the *destination* name cannot be attacker-influenced.
- Book 2: `hypelab source add` → `watcher.py:172-198` (`add_source`):
  requires a rights manifest with a `basis` at add time (fail closed);
  `poll_every_s` clamped to ≥300 s. Rights basis is re-checked at ingest
  (`ingest.py:81-113`, `require_rights`).

### Hop 1 — ingest: atomic copy + sha256 + ffprobe

- `util.py:140-205` `intake_asset(src, dst_dir, name)`:
  stat-signature the source → copy to `dst_dir/.tmp.<name>.<rand>` + fsync
  → sha256 the temp file (byte-counted) → re-stat source (IntegrityError on
  mid-copy mutation) → `os.replace` → re-stat destination size. Temp file
  always unlinked in `finally`. Path traversal blocked:
  `Path(name).name != str(name)` → ValueError (`util.py:145`).
- `manifests.py:226-285` `attach_asset`: intake → ffprobe via
  `util.ffprobe(dest)` → manifest.json entry `{name, sha256, bytes,
  duration_s, w, h, fps, sar, codec}`. Audio-only assets fall back to
  `_audio_probe` (`manifests.py:193-218`); un-probable files raise MediaError
  (never attached silently). Out-of-band `expected_sha256` mismatch →
  `work/quarantine/` + ManifestError (`manifests.py:220-224`,
  `_quarantine` at `manifests.py:222-250`).
- Book 2 network ingest: `ingest.py:247-332`:
  manual kind → local `intake_asset`; cleared kinds with http(s) URL →
  `ytdlp_json(url)` (`ingest.py:117-136`) then `ytdlp_download(url, dest)`
  (`ingest.py:138-149`). `ingest()` hashes the result and records
  `content_sha256` on the source item (`ingest.py:292-296`).

### Hop 2 — EDL build + validation

- Book 1: `cli.py:394-464` (`new`) → `script.to_beats` → `edl.build_edl`
  → `edl_mod.validate(edl)` (`cli.py:449`); EDL saved atomically to
  `work/<job>/render.json` (JSON tmp+fsync+rename; `_save_edl`, cli.py).
- Book 2: `cut.py:62-104` `_build_edl` → `edl_mod.validate(edl)`.
- Schema: `edl.py:11-72`; structural rules (contiguity, exactly-one-hook,
  duration budget): `edl.py:107-187`.
- **Gap (documented, not a defect):** `render` does NOT re-validate an EDL
  edited after creation; `cli.py:636` `_retarget_edl` builds a derived EDL
  without re-validation. `build_command` fails loudly (KeyError/RenderError)
  on malformed fields, but schema validation is not re-run. (BUG lane may
  want this; STR notes it because `loudness_lufs`/`enable`/`reframe` values
  flow into ffmpeg argv/filtergraphs — all operator-controlled here.)

### Hop 3 — render: ffmpeg command construction

- `render.py:340-421` `build_command(edl, work, out, provenance)`:
  1. `manifests_mod.verify_manifest(work)` **first** — re-hashes every
     attached asset; tampered asset → quarantine + ManifestError
     (`manifests.py:335-381`). No argv is built against suspect bytes.
  2. `video_chain` (`render.py:149-178`): per-beat `[i:v]` geometry
     (cover/contain/blurpad, or Book-2 reframe plan via
     `reframe.reframe_filter`) → concat → `ass='…'` captions filter (path
     escaped via `_esc_sq`, `render.py:174`).
  3. `audio_chain` (`render.py:181-248`): VO+music → asplit sidechain duck
     → amix → **single-pass** `loudnorm=I={lufs}:TP=-1.5:LRA=11`; vo-only /
     music-only straight loudnorm; no audio → `anullsrc`.
  4. `overlays_chain` (`render.py:253-285`): drawtext labels; text escaped
     via `_esc_drawtext` (CR/LF → space, single-quote escape); the optional
     `enable` expression is interpolated RAW (`render.py:277`) — no caller
     currently passes untrusted `enable` (Book 1: overlays always `[]`,
     `cli.py:445`; Book 2: hardcoded `"between(t,0,2.05)"`, `cut.py:74`),
     but the sink is unescaped. See STR-454.
  5. Final argv (`render.py:400-421`): `ffmpeg -y -v error` + `-i` inputs +
     `-filter_complex graph` + `-c:v libx264 -preset medium -crf 19
     -pix_fmt yuv420p` + `-c:a aac -b:a 192k -ar 48000` + `-movflags
     +faststart` + `-t <total>` + out. Every element validated
     (non-empty str) at `render.py:414-416`. **No `-fflags +bitexact`, no
     `-map_metadata -1`.** See determinism section.
- `render.py:434-534` `render()`: slots-filled gate → manifest verify →
  **render-hash skip** (same hash + out exists → skip without running ffmpeg)
  → ffmpeg to PID-unique temp (`out.partial-<pid>.mp4`) → ffprobe the temp
  → `os.replace` onto `out` → manifest render entry
  `{render_hash, provenance, ffmpeg_argv, started_at, finished_at,
  input_hashes}` + DB rows. Temp unlinked on ffmpeg/ffprobe failure.
  SIGKILL leaves the orphaned temp behind (acknowledged in the comment at
  `render.py:449-455`) — never at the final path. See STR-455.

### Hop 4 — captions: ASS generation

- `captions.py:56-111` `build_ass(words, kit_caps, target, out_path)` via
  pysubs2: word-pop karaoke, `{\k<cs>}` sweep per word.
- Escaping: `text = wd["w"].replace("{", "\\{").replace("}", "\\}")`
  (`captions.py:101`) — ASS override-block injection neutralized.
- **Residual:** backslash and raw newlines are NOT escaped. A word
  containing literal `\n`/`\N` is interpreted by libass as a line break;
  a raw newline would split the `Dialogue:` line and corrupt the file.
  Words come from in-process faster-whisper (practically clean) or
  fixture/operator JSON (Book 2), so likelihood is low. See STR-453.

### Hop 5 — gates: loudnorm, freezedetect→blackdetect/first-frame, probes

`gates.py`, uniform signature `(edl, render_path, work)`, all fail closed:

- duration (`gates.py:125-134`): ffprobe duration vs 3.00s–max_duration_s.
- loudness (`gates.py:171-199`): re-runs `loudnorm=print_format=json`,
  strict JSON extract of `input_i` (anchored regex, single json.loads —
  `gates.py:140-168`), fail closed on unparsable block; budget ±1.0 LUFS;
  records measurement in manifest.
- first_frame (`gates.py:76-123`): (1) corruption check — nonzero ffmpeg
  exit fails closed; (2) blackdetect at `-v info` (info level required for
  the `black_start:0` line — documented, `gates.py:82-90`); (3) frozen open
  — decode frame 0 vs frame 1 via ffmpeg → PNG → raw rgb24, byte-compare.
  Frame PNGs live in a `TemporaryDirectory` (auto-cleaned).
- hook_budget, caption_safe (ASS re-parsed with pysubs2; deterministic
  bounding-box math from PlayRes+fontsize), slots_filled, geometry
  (ffprobe w/h/fps/sar vs target), word_confidence.
- `run_all` (`gates.py:416-444`): a gate that raises = failed gate; every
  verdict recorded in `gate_results`.
- Subprocess hygiene: `gates.py:44` `_run` (timeout 180 default, argv only,
  no shell — `shell=False` is the subprocess default; the module documents
  "never shell=True" at `gates.py:14`); `_frame_pixels` (`gates.py:53-61`)
  pipes raw video bytes (timeout 60).

### Hop 6 — Book 2 cut/reframe/score/tray

- `reframe.py` (`plan_reframe`, `reframe.py:400-436`): OpenCV Haar face
  sampling (in-process, no network); `has_onscreen_text` (`reframe.py:130-
  164`) extracts a frame via ffmpeg to `/tmp/hypelab_textcheck_<hash>.png`
  (deleted in `finally`) and runs tesseract; inconclusive → fail closed to
  blurpad. `reframe_filter` (`reframe.py:439-476`) emits crop expressions
  from numeric plan values only (`float()`/`int()` formatting — injection-
  safe). `split` mode crop boxes come from `_source_wh` ints.
- `cut.py:44-60` `_extract_segment_audio`: ffmpeg `-ss/-t` (formatted
  floats) → wav; argv validated.
- `score.py:119-153`: ffmpeg `silencedetect` + `astats=metadata=1:reset=16000`
  on `source.mp4`, stderr parsed with anchored regexes; fixed 1800 s
  timeout; fail-soft (empty features + note) on error.
- `tray.py:59-70` `_thumb`: ffmpeg `-ss 1` frame extract; clips moved
  atomically into `tray/clip_NNNN/` (`tray.py:139-159`).

### Hop 7 — Book 3 carousel: spec → HTML → PNG

- `carousel.py:377-441` `render_carousel`: gates BEFORE render
  (text_overflow with in-browser measurement via `--dump-dom`, slide_one_hook).
- Slide text escaped with `html.escape` (`carousel.py:135-136`,
  `_slide_html`). **Kit CSS is NOT escaped**: `kit_to_css`
  (`carousel.py:107-130`) interpolates `fill`, `accent`, `font` raw into a
  `<style>` block — a kit value containing `"` or `</style>` breaks into
  HTML. Kit is operator-seeded (immutable v1) → low impact. See STR-454.
- Chromium via argv only (`carousel.py:72-74`); screenshots to tempdir,
  PNG size verified 1080×1350 via ffprobe (`carousel.py:324-336`), then
  atomic write to out dir (`_atomic_write_bytes`).
- `export_jpeg` (`carousel.py:443-476`): ffmpeg PNG→JPEG, `-q:v` clamped
  int; atomic tmp + rename.

## Command-construction verdict

**Every subprocess call site is an argv array; `shell=True` appears nowhere
in the package** (the only `shell=True` hits are comments documenting the
ban: render.py:3, gates.py:14, util.py:60, ingest.py:151, carousel.py:7).
`shell=False` is passed explicitly at all ffmpeg/ffprobe/yt-dlp/tesseract/
chromium sites except `gates.py:44` `_run`, which relies on the
`subprocess.run` default (`False`). No `os.system`, no `os.popen`, no
interpolated shell strings.

Malicious filenames:
- Filenames never pass through a shell, so spaces/quotes/semicolons/newlines
  in names are inert at the exec boundary.
- ffmpeg/ffprobe option parsing: `-i <path>` consumes the next argv element
  literally even with a leading dash, so a `-`-prefixed path is a failed file
  open, not option injection. ffprobe's trailing-position path arg
  (`util.py:83`) is the only place a leading-dash string meets an option
  parser, and it just errors (MediaError). Destination names are fixed
  (`{beat_id}.mp4`, `vo.mp3`, `source.mp4`, `tmp_16k.wav`,
  `seg_<moment_id>.wav`, `clip_<clip_id>.mp4`) or name-validated
  (`Path(name).name == name`, util.py:145 / manifests.py name check).
- Filtergraph injection: the two sinks are `_esc_sq` (single-quote escape +
  backslash escape, render.py:41-44) used for `ass=`, `drawtext fontfile=`,
  `drawtext text=`, fontfile in `derive()`; `_esc_drawtext` additionally
  strips CR/LF (render.py:250-252); `_esc_filter` (render.py:35-39) is
  defined but **currently unused** — harmless dead code (S4). Numeric
  interpolations use `f"{x:.3f}"`-style formatting from floats/ints.
  The `enable` drawtext expression (render.py:277) and kit CSS values
  (carousel.py:107-130) are the unescaped residuals — no untrusted caller
  today (see findings).

Subprocess call-site inventory (all argv, all with timeouts):

| Module | Calls (line) | Timeout |
|---|---|---|
| util.py:83 | ffprobe probe | 60 |
| manifests.py:86 | `ffmpeg -version` (provenance) | 30 |
| manifests.py:106 | pkg-config libass version | 15 |
| manifests.py:188 | ffprobe video codec | 60 |
| manifests.py:204 | ffprobe audio probe | 60 |
| ingest.py:119 | yt-dlp --dump-json | 300 |
| ingest.py:142 | yt-dlp download (7200 s = 2 h) | 7200 |
| ingest.py:157 | ffmpeg 16k mono extract (transcribe) | 3600 |
| watcher.py:48 | yt-dlp --flat-playlist | 120 |
| score.py:108 `_run` | silencedetect (score.py:137), astats (score.py:144) | 1800 |
| render.py:467 | main render ffmpeg | 600 (`FFMPEG_TIMEOUT`) |
| render.py:570 | derive (preview cutdown) | 600 |
| reframe.py:143 | ffmpeg frame extract (OCR check) | 60 |
| reframe.py:149 | tesseract | 60 |
| gates.py:44 `_run` | blackdetect probe (gates.py:65), loudnorm (gates.py:175), frame extracts (gates.py:102) | 180 (60 overrides) |
| gates.py:53 | ffmpeg raw-frame decode (pipes) | 60 |
| tray.py:63 | ffmpeg thumb extract | 120 |
| cut.py:59 | ffmpeg segment audio extract | 300 |
| carousel.py:72 `_run` | chromium probe/screenshot (via _measure_slide/_screenshot), ffprobe PNG size (carousel.py:324), ffmpeg JPEG export (carousel.py:462) | 120 |

**No call site is missing a timeout.** Timeouts are fixed constants, not
scaled to media length (600 s for a ≤45 s render is generous but bounded;
7200 s for yt-dlp, 1800 s for scoring, 3600 s for transcribe extract).
`subprocess.run` kills the child on timeout, so a hung ffmpeg cannot
linger; the exception propagates (worker → `queue.fail`, retry path).

## Determinism verdict

**What is deterministic:** `render_hash` (manifests.py:70-94) =
sha256(canonical EDL + canonical provenance + sorted sha256 of each input
file), first 32 hex chars. Pure function of its inputs; tests assert
identity and sensitivity (caption char change, provenance change, input
byte change flip the hash — test_pipeline.py:133-145,
test_manifests.py:153-174). The hash-skip in `render()` makes re-runs
idempotent: same EDL + same input bytes + same provenance → skip, no new
ffmpeg run. This is the property the codebase actually implements and
tests — **content-addressed idempotency, not bit-reproducible output.**

**What is NOT deterministic (output bytes):**
- No `-fflags +bitexact` and no `-map_metadata -1` in the render argv
  (render.py:400-412). ffmpeg writes `creation_time` and encoder-version
  tags into the MP4 → two runs of the identical EDL produce byte-different
  files.
- libx264 `preset medium` with default threading is not bit-exact across
  runs/machines (sliced threading), independent of inputs.
- `_overlay_font()` (render.py:55-66) picks the first existing TTF from a
  per-machine candidate list — different machines can render different
  overlay fonts; fontconfig rendering differs across OS builds anyway.
- The docstrings overclaim: "deterministic ffmpeg render chains"
  (render.py:1), "same EDL + same source hash = same clip (Book 1's
  determinism guarantee, extended)" (cut.py:6-10), "rendering is
  deterministic and idempotent" (ARCHITECTURE.md:103). The hash and the
  skip are; the MP4 bytes are not. See STR-452 (S2 — docs materially
  mislead; a consumer treating output files as content-addressed would be
  wrong).

## Transcoding choices

- **Codec/container (single MP4, no ABR ladder — n/a by design):**
  `-c:v libx264 -preset medium -crf 19 -pix_fmt yuv420p`,
  `-c:a aac -b:a 192k -ar 48000`, `-movflags +faststart`, `-t <total>`
  (render.py:400-412). Targets: 9:16 1080×1920 (book), 1:1 1080×1080,
  16:9 1920×1080 (`render.py:540` `_DERIVE_WH`; `ASPECT_DIMS` in cli.py).
  Previews are scale+crop re-encodes with a burned-in PREVIEW label, never
  inserted into the renders table (`derive`, render.py:543-577).
- **Audio normalization:** single-pass `loudnorm=I={lufs}:TP=-1.5:LRA=11`
  inside the render filtergraph (render.py:196-248, target -16 LUFS, Book 2
  `cut.py:40-43`). NO two-pass: single-pass loudnorm needs no temp files,
  and the loudness gate (`gates.py:171-199`) re-measures integrated LUFS
  and fails closed at ±1.0 LUFS. Fidelity is adequate given the gate;
  two-pass would only tighten an already-gated value. See STR-456 (S4).
- **Thumbnails/first-frame:** tray thumbnail `ffmpeg -ss 1 -frames:v 1`
  (tray.py:59-70); gate extracts frames 0/1 and byte-compares decoded RGB
  (gates.py:76-123) instead of the old freezedetect heuristic (documented
  rationale at gates.py:70-75). No separate thumbnail pipeline.

## Resource / lifecycle

- Temp files: intake (util.py:196-201), manifest writes (manifests.py),
  `tmp_16k.wav` (ingest.py:233-238), render partials (render.py:478,
  unlinked on ffmpeg/ffprobe failure), gate frame PNGs (TemporaryDirectory,
  gates.py:103), OCR frame PNG (reframe.py:159-162), carousel tempdirs and
  atomic writes (carousel.py:343-364, 443-476), JSON atomic writes
  (util.py:223-240). All cleaned on the normal and error paths.
- **Residual:** `work/<job>/` grows without bound — renders in `out/`,
  `assets/`, `clips/`, `tray/`, `quarantine/`, `manifest.json` history;
  nothing prunes old jobs or old render versions. SIGKILL orphans
  `out/<slug>.partial-<pid>.mp4` (acknowledged, render.py:449-455) and
  `/tmp/hypelab_textcheck_<hash>.png` (reframe.py:138-141 only cleans in
  `finally` on exception — wait, the `finally` does run on success too;
  only a kill orphans it). No startup reaper. See STR-455 (S3).
- **Sandboxing:** none. ffmpeg/ffprobe/yt-dlp/tesseract/Chromium run as
  the invoking user with full filesystem access — no seccomp, no
  namespaces/bwrap, no capability dropping. Third-party bytes (Book 2
  sources, yt-dlp downloads) are decoded by ffmpeg 8.1.2 in-process-space
  of the user. yt-dlp follows redirects from third-party URLs after the
  rights gate. Impact is bounded by the operator-owned threat model but
  Book 2 makes "untrusted bytes → decoder" a routine path. See STR-450.
- **RSS fetch:** `watcher.py:66-76` — `r.read()` with NO size cap, then
  `ET.fromstring(data)` on untrusted feed XML. Python ElementTree expands
  internal entities (billion-laughs class) and `r.read()` loads the whole
  body into memory. A hostile/compromised feed can OOM the watcher. See
  STR-451.
- Timeouts: present everywhere (inventory above); nothing hangs forever.
  The render timeout (600 s) is fixed regardless of target length — a stall
  raises TimeoutExpired into the worker's fail path, which is the correct
  behavior.

## Residual injection sinks (no untrusted caller today)

1. `overlays_chain` `enable` expression — raw interpolation into
   `drawtext=...:enable='...'` (render.py:275-277). Callers: none in Book 1
   (overlays=[]), hardcoded `"between(t,0,2.05)"` in Book 2 (cut.py:74).
2. `kit_to_css` — kit `fill`/`accent`/`font` raw into `<style>`
   (carousel.py:107-130). Kit seeded by operator, immutable v1.
3. `captions.py:101` — braces escaped, backslash/newline not (see above).
4. `_esc_filter` defined but unused (render.py:35-39) — dead code, S4.

## Positive controls verified (for the ledger's context)

- DOC-014's gap is real but narrower than stated for the media path:
  ingest does atomic copy + sha256 + ffprobe only (no allowlists/size caps/
  magic bytes). BUT: `intake_asset` blocks path traversal (util.py:145),
  quarantines on hash mismatch, and ffprobe decode-probes every attached
  file (manifests.py:236-262) — stronger than magic bytes for type
  validation, though it happens after the bytes are on disk.
- `verify_manifest` before every `build_command` (render.py:357) closes
  the TOCTOU between attach and render.
- test_pipeline.py's subprocess bomb (`monkeypatch` replacing
  `subprocess.run` with a raising stub, test_pipeline.py:260-269) is a
  genuine negative control for the render-failure path.
