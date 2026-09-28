# HypeLab v2 — vertical slice

**Architecture:** [ARCHITECTURE.md](ARCHITECTURE.md) (8 parts + 7 required outputs).

## What runs today (M1–M4 + M6 gate)

Mode A (Original), Starter tier: script → VO → word alignment → validated
`render.json` → deterministic ffmpeg render → captioned MP4 → quality gates.
Job queue with leases, retries, crash recovery. Consent hard gate + publish
dry-run. **Nothing is published for real; no paid APIs; no credentials.**

## Setup (Threadripper)

```bash
cd /home/dino/hypelab
export HYPELAB_HOME=/home/dino/hypelab   # default; the DB + jobs/ live here
python3 -m hypelab.cli doctor            # ffmpeg, whisper, edge-tts, fonts
```

## Vertical slice walkthrough

```bash
# 1. brand kit (fixture values)
python3 -m hypelab.cli kit new --name demo --appearance "LOCKED: ..."
# 2. job from script
python3 -m hypelab.cli new <kit_id> --script fixtures/script.txt --title "slice-01"
# 3. shot prompts (paste into your generator, or attach fixture clips)
python3 -m hypelab.cli shots <job>
# 4. attach media (VO, music, one clip per beat)
python3 -m hypelab.cli attach <job> vo fixtures/vo.mp3 --provenance generated:edge-tts-fixture
python3 -m hypelab.cli attach <job> music fixtures/bed.mp3 --provenance generated:ffmpeg-fixture
python3 -m hypelab.cli attach <job> beat:b1 fixtures/clip1.mp4 --provenance generated:ffmpeg-fixture
# 5-8. pipeline (each enqueues a task; worker executes)
python3 -m hypelab.cli align <job> && python3 -m hypelab.cli work --once
python3 -m hypelab.cli plan <job>  && python3 -m hypelab.cli work --once
python3 -m hypelab.cli render <job> --aspect 9:16,1:1 && python3 -m hypelab.cli work --once
python3 -m hypelab.cli gates <job> && python3 -m hypelab.cli work --once
python3 -m hypelab.cli show <job>   # state should be asset_ready
# outputs: jobs/<job>/master.mp4, render/render_record.json, quality_report.json
```

## Tests

```bash
python3 -m unittest discover -s tests -v
```

## Consent gate (expected: REFUSED without a consent record)

```bash
python3 -m hypelab.cli publish <job> --target somecreator        # REFUSED (exit 3)
python3 -m hypelab.cli publish <job> --target somecreator --real # still refused: no consent
```

## What is NOT built yet

M5 multi-aspect audio polish beyond 1:1 derivation, M7 carousel, M8 clip mine,
M9 measurement/what_worked, real publish adapters (Postiz/Zernio/native stubs
only). Stubs fail loudly with NotImplementedError — nothing is faked.
