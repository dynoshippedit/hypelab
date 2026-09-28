# HypeLab Vertical Slice — Exact Run Report

Date: 2026-09-28 (EDT). Machine: Threadripper (`dino@100.85.119.8`, Nobara Linux).
Repo: `/home/dino/hypelab` (local commits only — **no push authorized, none performed**).
Python 3.14.7, FFmpeg 8.1.2, faster-whisper (CPU, int8, tiny model).

All media below is **synthetic fixture material**, labeled as such in provenance
fields (`generated:edge-tts-fixture`, `generated:ffmpeg-fixture`).

## Permanence check (PDFs)

Both Desktop copies are byte-identical to the uploaded originals:

| file | sha256 | bytes | match |
|---|---|---|---|
| `hypelab-v2-handoff_9_ukhx.pdf` | `a27fe92467bbe1945fb907858fbfb3439c5a338953a4e5162673f53e75ef35fe` | 216256 | yes |
| `hypelab-spec_10_kh8z.pdf` | `4f45de6ab6a91ad55ba9c261a28bc6678ea639bd8154ab984c5beef7a32fecbb` | 281661 | yes |

## Commits (local only)

- `a8b5d8d` — ARCHITECTURE.md (4,517 words; 8 areas, 7 outputs)
- `cbbdc2a` — vertical-slice implementation + 26 unit tests
- `f090c8e` — live fixes: planner contiguity, queue revive semantics, loudnorm
  verbosity, freezedetect thresholds; job reached `asset_ready`
- `52d9f4e` — script-constrained captions, render→gates chaining,
  faster_whisper doctor, 8 regression tests (34/34 green)

## Slice under test

- Kit: `kit_2d0b3169@1` (immutable brand kit version)
- Job: `job_c656669a5147` ("slice-01", mode `original`), final state **`asset_ready`**
- Fixtures: `fixtures/script.txt` (8 sentences), `/tmp/hl-fixtures/vo.mp3`
  (Edge TTS, 21.888 s), 6× 1080×1920 `testsrc2` clips labeled
  `FIXTURE CLIP bN`, 60 s synthetic 3-tone music bed
- EDL: 5 beats (b1 hook 0.00→2.66, b2–b4 body, b5 CTA 15.62→21.00),
  render_hash `46aec30d5f57a933…`
- Outputs: `jobs/job_c656669a5147/master.mp4` (1080×1920, 21.0 s, 10.6 MB),
  `master_1x1.mp4` (7.9 MB), `render/render_record.json`,
  `render/captions.ass`, `quality_report.json` (**8/8 gates pass**),
  `vo.words.json` (script_constrained=True, match_ratio 0.967)

## What ran (commands, condensed)

```bash
cd /home/dino/hypelab && export HYPELAB_HOME=/home/dino/hypelab
python3 -m hypelab.cli kit create --name fixture --palette ...      # kit_2d0b3169@1
python3 -m hypelab.cli new --title slice-01 --mode original         # job_c656669a5147
python3 -m hypelab.cli attach ... (vo, music, 6 clips)
python3 -m hypelab.cli align job_c656669a5147
python3 -m hypelab.cli plan job_c656669a5147
python3 -m hypelab.cli render job_c656669a5147 --aspect 9:16,1:1
python3 -m hypelab.cli gates job_c656669a5147
python3 -m hypelab.cli work --once --worker slice-wN   # per task
```

Worker-driven tasks observed `done`: `task_dd891fae7e10` (align_vo),
`task_b14804f14bfd` (build_edl), `task_b931a8bb3378` (render),
`task_a663789198f4` (run_gates).

## Failures found live and fixed

1. **Planner gaps**: first EDL correctly REJECTED by validator
   (`beats must tile contiguously`). Fixed planner: pauses belong to the
   following beat's visual hold. The rejection itself proved validation works.
2. **SQL placeholder bugs** (×2): `new_job` (9 vals/8 cols); EDL upsert
   (4 placeholders/3 bindings). Fixed; upsert extracted to `_upsert_edl`
   with regression test.
3. **Wrong `whisper` package**: installed `whisper` was Graphite's DB library.
   Alignment switched to `faster_whisper` (CPU int8); `doctor()` now checks
   `faster_whisper`.
4. **Loudnorm silence**: `measure_loudness()` used `-v error`, which suppresses
   the info-level loudnorm JSON → `RuntimeError: could not parse loudnorm
   JSON from:`. Fixed: measurement pass runs at info verbosity.
5. **Hypersensitive freeze gate**: `freezedetect=n=0.5:d=0.5` flagged
   slow-moving test patterns. Relaxed to `n=0.01:d=1.0` (<1% pixels changing
   for a full second = frozen).
6. **run_after format**: `_requeue_gates` wrote epoch floats; `queue.claim()`
   compares `run_after` lexicographically as ISO-8601. Fixed to ISO.
7. **Render→gates chaining gap**: a render re-run left the job in `gates`
   with the old (done) gates verdict. `handle_render` now resets/requeues
   the run_gates task via `_requeue_gates` (proven live: gates re-ran
   automatically after the recovery re-render).
8. **ASR spelling leak**: faster-whisper transcribed "HypeLab" as "Hyplab".
   Alignment now snaps word *text* to script tokens (difflib, ratio ≥ 0.6,
   honest fallback recorded in `vo.words.json → alignment`).
   Timestamps remain ASR-derived — a full forced aligner can replace this
   step without changing the `words.json` contract.

## Restart recovery (kill -9) — PROVEN

- Worker `killtest-w3`, PID **316914**, claimed render task
  `task_b931a8bb3378`; `kill -9 316914` sent 1 s after claim (mid loudness
  pass); `ps -p 316914` confirmed dead.
- Task state immediately after: `leased`, owner `killtest-w3`, attempts 0
  (crash did not penalize the task).
- After 35 s (lease was 20 s), worker `recover-w1`:
  `recovered 1 expired lease(s)` → claimed → `done task_b931a8bb3378`.
- Post-recovery: task `done`, attempts 0, fresh `master.mp4` rendered.
- Cautionary note: two earlier kill attempts hit the wrong PID — `$!` had
  captured a parent subshell because `&&` binds tighter than `&` in
  `export … && python3 … &`. Those workers survived and completed the task;
  both were later killed by exact verified PID. Lesson recorded: verify
  `ps -p <pid> -o args` shows the actual worker before killing.

## Consent blocking — PROVEN (CLI)

- `publish job_c656669a5147 --target instagram` (no consent):
  `REFUSED: publishing refused: no valid consent …` exit 3.
- Same with `--real --i-confirm` (no consent): REFUSED, exit 3.
- Consent granted for the wrong handle (`@testcollab`): still REFUSED —
  consent is strictly per-handle/per-asset-version.
- Consent granted for `@instagram` (fixture artifact, expires 2026-12-31):
  dry-run → `DRY RUN — nothing was sent. Would publish …` exit 0.
- `--real --i-confirm` with consent: still `dry_run=True`, nothing sent —
  the CLI only wires the dry-run adapter; PostizAdapter raises
  NotConfigured. **No code path from the CLI can transmit anything.**

## Malformed EDL rejection — PROVEN

- 13 validation unit tests (12 malformed + 1 valid) pass.
- Live: the first planned EDL (timeline gaps) was rejected by
  `validate_all` before any render; the job was failed back to
  `asset_building` with the reason recorded.

## Retries — PROVEN

- Unit: backoff scheduling, poison-task failure after max attempts, single-
  winner atomic claim, simulated lease expiry/recovery.
- Live: the first align attempt failed (`whisper` AttributeError) and the
  task was requeued with backoff, then completed after the faster-whisper
  fix; `reset_attempts()` revives failed/queued tasks with `run_after` in
  the past (fixed live: a manual reset had left `run_after` in the future).

## Tests

`python3 -m unittest discover -s tests` — **34/34 pass** (0 failures),
on both the agent VM and the Threadripper. Covers EDL validation (13),
queue semantics (idempotency, atomic claim, backoff, poison, lease
recovery, revive), consent ledger (absent/wrong-version/expired/revoked),
publish dry-run honesty, collaborator-count restriction, plus 8 new
regression tests for the live-found defects.

## Honestly not done / blocked

- **Mode B (Clip Mine)** and **Mode C (carousel `slides.json` renderer)**:
  milestone stubs only (`modes_b.py`, `carousel.py`).
- **Metrics polling / `what_worked`**: stub (`measure.py`).
- **Real publishing** (Postiz/Zernio/native): no credentials, no
  authorization; adapters are honest stubs.
- **Paid media providers**: no spend, no keys.
- **Full campaign/source/moment/clip persistence**: architecturally
  described, not built in this slice.
- **Cost ledger**: exists, but task handlers don't yet record zero-dollar
  execution entries.
- **Alignment**: timestamps are ASR-derived (faster-whisper tiny); word
  *text* is now script-constrained. A true script-constrained forced
  aligner remains future work; the `words.json` contract is stable for it.
- **First-frame gate transient**: two worker runs immediately following an
  `scp` of `gates.py` reported `frozen`; the same code run directly and in
  5 subsequent worker/direct runs reports `clean` deterministically.
  Root cause not fully isolated (suspected stale import); current code is
  verified good multiple ways. Not hidden — flagged here.
- The pip environment warnings (Hermes/Gradio pydantic, Gemini CLI rich)
  were not touched; global-package churn was avoided per instructions.
  Hermes/Gemini CLI were not re-verified after the faster-whisper install.

## Files of record

- `/home/dino/hypelab/ARCHITECTURE.md`
- `/home/dino/hypelab/VERTICAL_SLICE_REPORT.md` (this file)
- `/home/dino/hypelab/jobs/job_c656669a5147/` — master.mp4, master_1x1.mp4,
  quality_report.json, render/render_record.json, render/captions.ass,
  vo.words.json, caption_proof.png
