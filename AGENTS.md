## Review program in progress
Before any work in this repo, read `devteam/PLAYBOOK.md` in full, then `devteam/STATUS.md`, and follow them. The Playbook overrides conflicting defaults.

## Cursor Cloud specific instructions

- The CLI is installed editable in `.venv`. Run `.venv/bin/hypelab` and `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/ -q`. There is no dev server and no lint or typecheck command.
- Set `HYPELAB_HOME` to a writable directory before any CLI command. Unset, the default is `/home/dino/hypelab`.
- Forced alignment reads `/home/dino/hypelab/models/wav2vec2-base-960h`. The faster-whisper `medium` model is cached under `~/.cache/huggingface`.
- `ffmpeg` on PATH is the pinned 8.1.2 build in `/usr/local` (libass, libx264, libmp3lame). Ubuntu's 6.1.1 package is not used for renders.
- `/usr/local/bin/google-chrome` is a computer-use wrapper that does not exit. The venv sets `HYPELAB_CHROMIUM=/usr/bin/google-chrome-stable` so carousel screenshots use the real binary. Leave that wrapper in place.
- `espeak-ng` and `deno` 2.9.7 are on PATH. `deno` is only needed for yt-dlp YouTube sources.
