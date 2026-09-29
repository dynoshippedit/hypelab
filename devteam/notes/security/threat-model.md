# HypeLab Threat Model — SEC review (2026-09-29)

Scope: `/home/dino/hypelab`, branch `devteam/review-2026-09-29`. Reviewed the
full package (40 modules) plus migrations. No authentication exists in the
system — that is intentional and this model is built around it.

## System shape

- Single-user local CLI (Click, 36 leaf command paths). No network server, no
  web UI, no multi-tenancy, no background daemon.
- State: SQLite at `~/hypelab.db` (`$HYPELAB_DB` override); work dirs under
  `~/hypelab_work` (`$HYPELAB_ROOT` override).
- Subprocesses: `ffmpeg`/`ffprobe` (all invocations verified as argv arrays
  with `shell=False` — zero `shell=True`, zero `os.system` anywhere),
  `yt-dlp` (listing/download), headless Chromium (carousel render +
  measurement probe).
- Network (all operator-initiated): RSS fetch (`watcher.py`), yt-dlp,
  provider adapters (every live path refuses in this build), faster-whisper
  model fetch, metrics fetcher (stubbed to `unavailable`).

## The honest trust model

1. **There is no authentication, by design.** Anyone able to invoke the CLI as
   the local OS user *is* the operator. There is no login, no token, no
   session. The security boundary is the OS account, not the application.
2. **The authorization ledger is a ceremony/provenance control, not identity
   verification.** `authorize record` + `require_authorization()`
   (`hypelab/authorize.py:65-73`) prove the operator *explicitly approved*
   the pitch / publish / invite action for a job. It records an intent
   ceremony; it does not verify who typed the command.
3. **Filesystem access is total access.** Anyone with read/write to the SQLite
   DB, the work dirs, consent artifacts, or the Python environment can forge
   authorizations, rewrite consent rows, swap media, or change the code. That
   is an OS-level concern (account security, backups), not something
   application checks can defend against — and the model must say so
   explicitly rather than pretend otherwise.
4. **The operator is trusted; their inputs still get validated where
   third-party content flows.** Defense-in-depth applies at crossings that
   carry outside content: RSS/yt-dlp responses, imported kits, attached
   media, collaborator handles, captions, consent-ledger fields.

## Crown jewels

- **Consent ledger** (`consents` table + CSV exports): the legal evidence of
  collaborator permission. Expiry/revocation integrity is the #1 business
  rule — see SEC-100, SEC-101, SEC-104.
- **Authorization ledger** (`authorizations` table): proof of explicit
  operator approval for pitch / publish / invite. Permanent, unexpirable,
  unrevocable — see SEC-102.
- **Queue integrity** (jobs state machine + leases): `claim()` is an atomic
  `UPDATE ... RETURNING` (`hypelab/queue.py:93-107`); the two-process race is
  untested per TST-007 but the SQL itself is race-safe.
- **Media provenance**: intake does atomic copy + sha256 + ffprobe probing;
  destination-name traversal rejected (`hypelab/util.py`, `hypelab/manifests.py`).
- **Calibration data**: metrics provenance ranks enforced —
  `user_entered` rows are never calibration-grade (`hypelab/metrics.py:105-116`).

## Trust crossings (untrusted → trusted)

| # | Crossing | Sink | Control present |
|---|----------|------|-----------------|
| 1 | RSS source URL + feed XML (operator-registered) | `urllib.request.urlopen(url)` (`hypelab/watcher.py:71`), `ET.fromstring` | None on the URL (SEC-103); stdlib XML parse |
| 2 | yt-dlp listing/download URLs | argv to yt-dlp (`hypelab/watcher.py:43`, `hypelab/ingest.py:115-146`) | argv, no shell; ingest requires a rights basis + `http` prefix (`hypelab/ingest.py:255`) |
| 3 | Imported kit JSON | CSS interpolation (`hypelab/carousel.py:79-88`), caption styling | slide text HTML-escaped (`hypelab/carousel.py:112-113`); CSS values unvalidated (SEC-105) |
| 4 | Attached/supplied media files | ffmpeg/ffprobe argv | sha256 + ffprobe probe, traversal rejected; no shell |
| 5 | Collaborator handles, pitch values, consent fields | pitch template, DB, CSV export | template is `{}`-substitution (no code exec); CSV cells unneutralized (SEC-104); expiry format unvalidated (SEC-100) |
| 6 | EDL JSON (operator-edited render specs) | ffmpeg filtergraph | overlay text escaped (`hypelab/render.py:235-237`); `enable` expr + reframe `split` boxes interpolated raw (SEC-106) |
| 7 | ML models (HF hub via faster-whisper) | local inference | intended fetch; supply-chain note only |

## Considered and not applicable (do not invent controls)

No web server → no CSRF / CORS / cookie / session-fixation surface. No JWT or
API tokens → no token theft/replay. No multi-tenancy → no IDOR/BOLA (job IDs
are `secrets.token_hex`; DB tampering is a filesystem-level act). No
`shell=True`, no `os.system`, no string-built shell commands anywhere. No
pickle/YAML deserialization. SQL is parameterized throughout the package
(one dynamic clause appends a fixed string only).

## Doc-vs-code gaps with security consequence

`ARCHITECTURE.md` §8 claims controls that have no code behind them
(DOC-014's lane, noted here for residual risk): no `secrets.env` handling
exists at all (nothing to protect — no credentials anywhere in the package);
`attach` does intake + sha256 + ffprobe but **no** extension allowlist or
magic-byte check (ffprobe is the de-facto gate — non-media fails closed);
there is no `hypelab fetch --url` command and no host allowlist; there are
**no file-size caps** on attach/intake (local disk-exhaustion only) and **no**
ulimit/nproc caps. None is remotely exploitable in this build, but the docs
overclaim.

## Residual risks (accepted, by design)

- Operator self-harm (hand-edited EDL, malicious URLs, bad kit JSON) — the
  operator is trusted; the code still validates where cheap.
- Filesystem-level tampering with DB / work dirs / code — OS boundary.
- Chromium rendering kit-controlled CSS — local-only artifact pipeline.
