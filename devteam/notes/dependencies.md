# Dependencies — HypeLab (BLD, 2026-09-29)
No manifest exists (no `pyproject.toml` / `setup.py` / `requirements*.txt`), so this
table is derived by AST-scanning every `import`/`from…import` in `hypelab/` and
mapping each third-party top-level module to the installed distribution.
Heavy ML imports (`faster_whisper`, `transformers`, `torchaudio`) are **lazy**
(inside functions in align.py:126,165,227,266,271) — good; CLI startup stays light.

## Third-party imports → installed versions
| Imported as | Distribution | Version | Location | Status |
|---|---|---|---|---|
| `click` | click | 8.5.0 | user site | used (CLI framework) |
| `cv2` | opencv | 4.13.0 | system `/usr/lib` | used |
| `faster_whisper` | faster-whisper | 1.2.1 | user site | used (word alignment) |
| `jsonschema` | jsonschema | 4.26.0 | user site | used |
| `librosa` | librosa | 0.11.0 | user site | used |
| `numpy` | numpy | 2.4.6 | system `/usr/lib64` | used |
| `pysubs2` | pysubs2 | 1.9.0 | user site | used (captions) |
| `torch` | torch | 2.12.1+cu130 | user site | used; **CUDA unavailable** → CPU-only (BLD-012) |
| `torchaudio` | torchaudio | 2.11.0 | user site | used (align.py, lazy) |
| `transformers` | transformers | 5.12.1 | user site | used (align.py, lazy); major version is unusual (public line is 4.x) — works, tests green |
| (transitive) | ctranslate2 | 4.8.2 | user site | faster-whisper backend |
| (transitive) | onnxruntime | 1.30.0 | user site | |
| (transitive) | audioread | 3.1.0 | user site | emits aifc/sunau DeprecationWarnings on py3.14 (cosmetic) |
| (transitive) | soundfile | 0.14.0 | user site | |
| (transitive) | av | 18.1.0 | user site | |

## Findings
- **Missing (imported, not declared):** n/a — nothing is declared, so trivially "all declared", but **no dependency is pinned or declared anywhere** → BLD-001 (S1). A fresh machine cannot reproduce this set.
- **Unused (declared, never imported):** n/a for the same reason; but **installed-but-unused**: `whisper` (openai-whisper) 1.1.10 sits in system site-packages while the code uses `faster-whisper` → BLD-013 (S4). `edge-tts` is named in README.md:17 but is neither imported nor installed — stale doc (folded into BLD-003/004).
- **Duplicate-purpose:** `whisper` vs `faster-whisper` (both Whisper engines installed; only faster-whisper used) — dead weight, see BLD-013.
- **Outdated majors:** `transformers` 5.12.1 is *ahead* of the public 4.x line (likely a Nobara/vendor build); not flagged as outdated, but its provenance is unverified — S4 note.
- **Vulnerable:** **not assessed** — `pip-audit` is not installed and was not installed during review (would change the shared user site). Manual reasoning: no obviously ancient/abandoned versions among the ten direct deps (click 8.5, numpy 2.4, torch 2.12 are current-era). Recommend `pip install pip-audit` (or a CI step) for a real CVE pass → BLD-011 (S3).
- **Risky install scripts / native modules:** none observed in hypelab's direct set; `ctranslate2`/`onnxruntime` ship prebuilt wheels.
- **License compatibility:** not audited (no manifest to audit against); all ten are mainstream OSI licenses by reputation — flag for a real pass if the repo is ever packaged.

## Native prerequisites
| Prerequisite | Present? | Notes |
|---|---|---|
| `ffmpeg` | ✅ 8.1.2 | render pipeline; verified via `ffmpeg -version` |
| Chromium (carousel render) | ✅ `/usr/bin/google-chrome` | carousel.py tries PATH names first, then `/opt/pw-browsers/chromium` (absent — fine) |
| fonts (caption render) | not verified | README mentions fonts for `doctor` (which doesn't exist) — unverified, S4 |
| GPU / CUDA | ❌ absent | torch reports `cuda.is_available()=False`; faster_whisper runs CPU int8 per VERTICAL_SLICE_REPORT.md:69 |
