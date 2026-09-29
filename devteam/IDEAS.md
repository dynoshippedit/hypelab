# IDEAS — opportunities, not defects
(none yet — anyone may add IDEA-NNN entries during review.)

---

## IDEA-001 — Implement a real `doctor` command (from DOC-001)
README's setup step references a `doctor` that doesn't exist. A real doctor would check:
ffmpeg/ffprobe versions, faster-whisper import, Chromium binary (or HYPELAB_CHROMIUM),
DejaVu fonts for captions, DB migrations applied, write access to HYPELAB_ROOT. Cheap,
high onboarding value.

## IDEA-002 — `hypelab show <job>` (state, tasks, EDL summary, gate results)
The slice-era `show` command is gone; operators currently have no single read view of a
job. A read-only summary command would close the loop the README promises.

## IDEA-003 — Close the ARCHITECTURE §8 upload-validation gap (from DOC-014)
Add the documented-but-missing controls to intake: extension allowlist, magic-byte
sniffing, size caps, symlink rejection, duration caps. Matters most for Book 2, where
the watcher auto-polls third-party source URLs.

## IDEA-004 — Rights disclaimer on `attach`/`audio` for operator-supplied music
Book 2 sources require a rights manifest, but Mode A music attach has no rights check
and no warning. Print a one-line reminder that the operator is responsible for the
rights to attached media (not legal advice; just surfacing the obligation).

## IDEA-005 — Decide the binary-artifact policy (from DOC-023)
jobs/job_c656669a5147/*.mp4 + caption_proof.png are git-tracked (~20 MB). Either keep
deliberately as golden fixtures (document why) or move to .gitignore + a fixtures
download note. Undecided binaries bloat every clone.

## IDEA-006 — Trademark/conflict check on the "HypeLab" name
No conflict search was done. Before any public launch or the Meta app-review process,
run a basic trademark screen.

## IDEA-007 — `hypelab backup` (from DOC-014)
ARCHITECTURE promises a timestamped tarball backup (SQLite DB + work/ dirs). Implement
it — it's the missing half of the crash-recovery story (lease recovery handles process
crash; nothing handles disk loss).

## IDEA-008 — Per-job budget enforcement (from DOC-008)
jobs.budget_usd + pre-spend refusal is documented but absent. Once any paid provider
exists, this becomes a cost-safety control. Implement before wiring paid APIs.

## IDEA-009 — Walkthrough + Operations docs (from DOC-012)
Write docs/WALKTHROUGH.md (verified end-to-end against the real CLI) and
docs/OPERATIONS.md (env vars, DB backup/restore, lease recovery, worker supervision).
ARCHITECTURE.md promises both; docs/ is empty.

## IDEA-010 — Publish-readiness checklist for the live path
The dry-run → live transition needs: provider credentials (Postiz/Zernio/Meta),
Meta app review + business verification (noted in meta.py as real lead times),
per-platform ToS review of the pitch template, and the DOC-008 budget control.
Keep as a gated checklist, not a TODO to rush.

## IDEA-011 — `worked` calibration-grade sourcing note in output
attribution already gates on n≥30 and calibration-grade provenance; consider printing
the provenance mix (official_api vs provider_api vs user_entered) alongside results so
the operator sees evidence quality at a glance.
