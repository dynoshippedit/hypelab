# HypeLab v2

HypeLab is a local-first Python CLI that turns a script + voiceover + clips +
music into finished, captioned, platform-sized MP4s. An AI authoring step writes
an edit decision list (`render.json`); a deterministic FFmpeg renderer plus
quality gates turn that EDL into verified assets. **Book 1** (foundation / Mode
A original video), **Book 2** (Clip Mine / Mode B), and **Book 3** (the Hype
layer: carousel renderer, consent ledger, dry-run publishing) are all
implemented here. **Nothing is published for real and no paid APIs or
credentials are used** — every publish adapter's live path refuses by default.

**Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md)

A fuller docs rewrite (devteam task T-038) is pending owner review of
`devteam/QUESTIONS.md` Q-001.

## Requirements

- Linux. Python >= 3.12 (verified on 3.14.7).
- System tools on PATH: `ffmpeg` with `libass` (verified 8.1.2), `espeak-ng`
  (used by the test fixtures), `google-chrome` or `chromium` (carousel /
  headless screenshot only), and `deno` (the JavaScript runtime that yt-dlp
  requires for YouTube sources — Mode B only).
- CPU-only is fine; no GPU is needed.

## Install

```bash
cd ~/hypelab
python3 -m venv .venv
.venv/bin/pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
.venv/bin/pip install -r requirements.txt
.venv/bin/pip install -e .      # editable install is REQUIRED (see note)
# exact known-good versions instead:
# .venv/bin/pip install -r requirements-lock.txt --extra-index-url https://download.pytorch.org/whl/cpu
```

Only the editable install (`pip install -e .`) is supported: the code reads
`migrations/` from the repository checkout, so a plain `pip install .` /
wheel install would be missing them (packaging migrations as package data is
a structural change left for owner review).

The wav2vec2 CTC alignment model (`facebook/wav2vec2-base-960h`) lives in
`HYPELAB_MODELS_DIR` (default `/home/dino/hypelab/models`, ~361 MB). The
faster-whisper `"medium"` ASR model downloads into `~/.cache/huggingface` on
first use (transcription, e.g. Mode B ingest). Once both are cached, set `HF_HUB_OFFLINE=1` to keep
the pipeline fully offline.

## Configuration

`HYPELAB_HOME` (default `/home/dino/hypelab`) is the single root. The DB,
`work/`, `outputs/`, `logs/`, `tmp/`, and `kits/` all derive from it, and every
command prints the resolved config at startup. Per-path overrides exist:
`HYPELAB_DB_PATH`, `HYPELAB_WORK_DIR`, `HYPELAB_MODELS_DIR`,
`HYPELAB_OUTPUTS_DIR`. The legacy `HYPELAB_ROOT` and `HYPELAB_DB` are still
honored. Use a separate `HYPELAB_HOME` for experiments so the main
`hypelab.db` is untouched.

## Tests

```bash
cd ~/hypelab
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/ -q
```

324 tests, about 4 minutes on the Threadripper. The
`PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` flag avoids a broken langsmith pytest plugin
in the user site.

## Mode A walkthrough (verified 2026-10-06)

```bash
export HYPELAB_HOME=~/hypelab-runs/my-run      # isolated run root
HL=~/hypelab/.venv/bin/hypelab
$HL migrate
$HL kit new cerebratico --from ~/hypelab/kits/cerebratico/kit.json
$HL new --kit cerebratico --script script.txt --title my-first-cut   # prints: job <JOB_ID>
$HL shots <JOB_ID>                       # one paste-ready prompt per beat (b1, b2, ...)
$HL attach <JOB_ID> b1 clips/b1.mp4      # repeat for every beat
$HL audio <JOB_ID> --vo vo.wav --music music.mp3
$HL render <JOB_ID>
$HL gates <JOB_ID>
```

`shots` prints one numbered prompt per beat (generate one clip per beat
elsewhere, then attach it). `audio` force-aligns the VO to the script with
wav2vec2 and retimes the beat boundaries to the word timestamps. `render` writes
`work/<job>/out/9x16.mp4` (the job's target aspect). `render --aspect 1:1|16:9`
exists but has a known state-routing bug (TASKS.md T-014), so treat other
aspects as experimental for now. `gates` runs
duration, loudness, first_frame, hook_budget, caption_safe, slots_filled,
geometry, and word_confidence, then moves the job to `ready` or `gate_failed`
with a reason in each case.

`script.txt` is split into beats on sentence-ending punctuation (`.` `!` `?`
`…` followed by whitespace), so one sentence = one beat; blank lines do not
split on their own. The first sentence is the hook and must fit the 3.0 s hook
budget (keep it short). A worked example with real
inputs is in `~/hypelab-runs/m1-modeA-2026-10-06` (`run-1-setup.sh`,
`run-2-render.sh`).

## Mode B and Book 3 (pointers only)

Book 2 (Clip Mine) surface: `campaign add`, `source add` (requires a rights
manifest; fails closed without one), `watch --once`, `work --once`, `moments`,
`cut`, `tray`, `posted`. Book 3 (Hype layer) surface: `authorize`, `carousel`,
`pitch`, `consent`, `publish` (dry-run by default; `--live` refuses). These have
only been exercised on fixtures so far — real campaigns, sources, and
publishing need Dino's explicit go-ahead.

## Status and open work

The engineering queue and open owner questions live in
`devteam/TASKS.md` and `devteam/QUESTIONS.md` respectively. Book 1 Mode A
(Starter) is the verified vertical slice; Books 2 and 3 are implemented but
operate on fixtures and dry-runs only. See the ARCHITECTURE.md state machine
for the full job lifecycle and the consent hard-gate that blocks real
publishing.
