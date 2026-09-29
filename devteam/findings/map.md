# Findings — Cartographer (MAP-001–019)
Phase 1 (map). Source code is READ-ONLY; these are logged, not fixed.
Severity/confidence per B7. Status lifecycle per B7.

## Index
| ID | Sev | Conf | Status | Title | Location | Effort |
|---|---|---|---|---|---|---|
| MAP-001 | S3 | Confirmed | NEW | Stale generated job outputs (39 MB) tracked in jobs/job_c656669a5147/ | jobs/job_c656669a5147/ | S |
| MAP-002 | S2 | Confirmed | NEW | README.md describes a CLI surface that does not exist | README.md | S |
| MAP-003 | S3 | Confirmed | NEW | VERTICAL_SLICE_REPORT.md references a superseded CLI generation | VERTICAL_SLICE_REPORT.md | S |
| MAP-004 | S3 | Confirmed | NEW | Duplicate `import json` in hypelab/gates.py | hypelab/gates.py:24-25 | XS |
| MAP-005 | S4 | Confirmed | NEW | hypelab/__init__.py docstring stale ("M1-M4, M6 gate") | hypelab/__init__.py:1 | XS |

---

### MAP-001 — Stale generated job outputs (39 MB) tracked in jobs/job_c656669a5147/
- **Severity:** S3 (repo hygiene; 39 MB of binaries bloat every clone) · **Confidence:** Confirmed · **Status:** NEW · **Effort:** S
- **Location:** `jobs/job_c656669a5147/` (17 tracked files)
- **Evidence:**
  - `git ls-files jobs/` lists 17 files; `du -ch` total = **39M** (master.mp4 10.6M, master_1x1.mp4, 6 beat clips ~2.5M each, vo.mp3, music.mp3, caption_proof.png).
  - The current write-domain policy (`hypelab/cli.py:10-16`) says job artifacts live in `work/<job_id>/`; `util.work_dir` (`hypelab/util.py:173-174`) builds `<root>/work/<job_id>`. No current code references a `jobs/<job>` directory (grep for `"jobs/` in hypelab/*.py returns nothing).
  - `.gitignore` ignores `/work/` but has no `/jobs/` entry, so the old outputs stayed tracked while new work dirs are ignored.
  - Commits `52d9f4e`/`f090c8e` show the tree was captured under the older CLI generation whose layout was `jobs/<job>/master.mp4` (VERTICAL_SLICE_REPORT.md:37 still names that path).
  - Duplicates inside the tracked set: `md5sum` gives identical hashes for `jobs/job_c656669a5147/vo.words.json` and `jobs/job_c656669a5147/assets/vo_words.json` (`cc64a147624079a189b151119fc80ebc`); `jobs/job_c656669a5147/script.txt` == `fixtures/script.txt` (`34f22d523bb78389b78fc5dcce3ac75d`).
- **What's wrong:** generated outputs of a superseded pipeline generation are committed; they no longer reflect what the code produces, and they add ~39 MB to every clone. Deleting files needs owner approval (B1 NEEDS APPROVAL: deleting files).
- **Impact:** repo bloat; misleading "example outputs" that the current CLI cannot reproduce at those paths.
- **Suggested fix:** after owner approval, `git rm -r jobs/` and add `/jobs/` to `.gitignore` (or confirm the directory is intentionally kept as a historical artifact — then document it). Lead: log Q in QUESTIONS.md.

### MAP-002 — README.md describes a CLI surface that does not exist
- **Severity:** S2 (docs materially mislead; a new user cannot follow the setup) · **Confidence:** Confirmed · **Status:** NEW · **Effort:** S
- **Location:** `README.md`
- **Evidence:**
  - `README.md:17`: `python3 -m hypelab.cli doctor` — no `doctor` command exists (`grep -n 'def doctor\|"doctor"' hypelab/ tests/` → no hits; commands are migrate, kit/new, new, shots, attach, audio, render, gates, work, costs + Book 2/3 commands).
  - Walkthrough (`README.md:30-40`): `python3 -m hypelab.cli attach <job> vo fixtures/vo.mp3 --provenance ...` — current `attach` signature is `attach JOB_ID BEAT_ID SRC` with no `--provenance` (`hypelab/cli.py:504-507`); `align`, `plan`, `show` commands don't exist; `fixtures/vo.mp3`, `fixtures/bed.mp3`, `fixtures/clip1.mp4` don't exist (fixtures/ contains only script.txt).
  - `README.md:16`: `export HYPELAB_HOME=/home/dino/hypelab` — code reads `HYPELAB_ROOT`, `HYPELAB_DB`, `HYPELAB_LEASE_SECONDS`, `HYPELAB_CHROMIUM`; `HYPELAB_HOME` is read nowhere.
  - `README.md:56`: "Stubs fail loudly with NotImplementedError" — the code raises `LiveRefused` (`hypelab/publish/base.py:31`), not `NotImplementedError` (no hits in hypelab/).
  - Consent example (`README.md:53-55`): `publish <job> --target somecreator [--real]` — current signature is `publish --job JOB_ID --platform ... [--live]` (`hypelab/book3cli.py:126-140`), and `--live` `_die`s before any call.
- **What's wrong:** the README documents an older CLI generation; following it literally fails at the first command.
- **Impact:** new-user onboarding broken; DOC lane's claims audit should re-verify every README line after fixes (Phase 5 docs corrections come last per B11 step 9).
- **Suggested fix:** rewrite README setup + walkthrough against the real command surface (Phase 5, DOC).

### MAP-003 — VERTICAL_SLICE_REPORT.md references a superseded CLI generation
- **Severity:** S3 · **Confidence:** Confirmed · **Status:** NEW · **Effort:** S
- **Location:** `VERTICAL_SLICE_REPORT.md`
- **Evidence:**
  - `VERTICAL_SLICE_REPORT.md:45`: `export HYPELAB_HOME=/home/dino/hypelab` (not read by code — see MAP-002).
  - `VERTICAL_SLICE_REPORT.md:47-50`: `hypelab.cli new --title slice-01 --mode original`, `hypelab.cli align job_c656669a5147`, `hypelab.cli plan job_c656669a5147` — `--mode` is not a `new` option, `align`/`plan` are not commands (`hypelab/cli.py:393-401`).
  - `VERTICAL_SLICE_REPORT.md:31`: final state `asset_ready` — no such state in `hypelab/jobs.py` (terminal Book 1 state is `ready`).
  - `VERTICAL_SLICE_REPORT.md:37`: outputs at `jobs/job_c656669a5147/master.mp4` — legacy layout (see MAP-001); current code writes `work/<job>/out/9x16.mp4` (`hypelab/cli.py:675-677`).
- **What's wrong:** the report is a historical artifact of an older pipeline generation but reads as current documentation.
- **Impact:** low (report, not instructions), but it contradicts the README-less reality and the tracked jobs/ dir it points to.
- **Suggested fix:** mark it as superseded/archival at the top, or retire it. Owner decision (deleting/renaming needs approval).

### MAP-004 — Duplicate `import json` in hypelab/gates.py
- **Severity:** S3 (code smell; harmless — second import is a no-op) · **Confidence:** Confirmed · **Status:** NEW · **Effort:** XS
- **Location:** `hypelab/gates.py:24-25`
- **Evidence:**
  ```
  hypelab/gates.py:24: import json
  hypelab/gates.py:25: import json
  ```
  (from `sed -n '20,30p' hypelab/gates.py`; lines 24 and 25 are identical).
- **What's wrong:** duplicated import; indicates the file was assembled from two sources without a lint pass. Consistent with "no lint/typecheck found" in B3.
- **Impact:** none at runtime; signal that linting is absent (BLD).
- **Suggested fix:** delete one line; add a linter to CI (BLD lane).

### MAP-005 — hypelab/__init__.py docstring stale ("M1-M4, M6 gate")
- **Severity:** S4 (info) · **Confidence:** Confirmed · **Status:** NEW · **Effort:** XS
- **Location:** `hypelab/__init__.py:1`
- **Evidence:** `"HypeLab v2 — vertical slice (M1-M4, M6 gate). See ARCHITECTURE.md."` — the repo now ships Books 1–3 (commit `81aaf52 HypeLab Books 1-3 complete`).
- **What's wrong:** package docstring describes the old milestone scope.
- **Impact:** trivial; misleading only to a reader starting at the package root.
- **Suggested fix:** update the docstring in the Phase 5 docs batch.
