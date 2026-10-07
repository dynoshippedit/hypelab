## Review program in progress
Before any work in this repo, read `devteam/PLAYBOOK.md` in full, then `devteam/STATUS.md`, and follow them. The Playbook overrides conflicting defaults.

## Cloud Agent environment

Dependencies live in `.venv` (editable install; `migrations/` is read from the checkout). Use `.venv/bin/hypelab` and `.venv/bin/python`.

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 .venv/bin/python -m pytest tests/ -q
```

Run tests with `HYPELAB_HOME` unset. The CLI prefers `HYPELAB_HOME` over `HYPELAB_ROOT`, and the tests isolate themselves with `HYPELAB_ROOT`.

`ffmpeg` on `PATH` must report version `8.1.2` (the render pin in `hypelab/render.py`). The venv sets `HYPELAB_CHROMIUM` so carousel probes use a headless Chrome that exits. Alignment tests read the wav2vec2 cache at `/home/dino/hypelab/models/wav2vec2-base-960h`. For a CLI experiment, point `HYPELAB_HOME` at an empty directory.
