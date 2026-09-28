# HypeLab v2 — Architecture

**Status:** implementation-ready. Written 2026-09-28 from `hypelab-v2-handoff_9_ukhx.pdf`
(handoff) and `hypelab-spec_10_kh8z.pdf` (spec, supersedes the handoff).
No prior HypeLab repository existed; this document and the code under `hypelab/`
are the first implementation. v1 design notes (SQLite job queue, human-in-the-loop
media, no browser automation, identity locking) are carried forward where the spec
reaffirms them.

**Product in one paragraph:** HypeLab is a video production engine with a
distribution layer bolted to its output and a measurement layer bolted to its
results. One renderer, three feed modes (A: Original, B: Clip Mine, C: Carousel).
AI writes `render.json` (a versioned edit decision list); deterministic code
validates it and renders it. THE LAB turns script + voiceover + clips + music into
finished, captioned, platform-correct video. THE HYPE puts that video in a
creator's feed with recorded consent, then measures performance and writes the
outcome back to the creative decisions that produced it — closing the loop.

---

## Part 1 — Orchestration and persistence

### 1.1 Foundation: Python + SQLite

Python 3 + SQLite is the foundation. Rationale, concrete:

- The workload is orchestration of subprocesses (ffmpeg, whisper), not
  high-concurrency serving. SQLite's WAL mode handles many readers + one writer
  comfortably at this scale (tens of jobs/day, not thousands/sec).
- Single-file database = trivial backup/restore (copy the file), trivial
  deployment (no server to run), crash-safe via SQLite's own ACID guarantees.
- Python's `sqlite3` is stdlib; ffmpeg/whisper are subprocesses; no ORM needed.

**Change criterion:** revisit only if sustained write contention appears
(multiple workers contending on the tasks table with lease updates > ~10/sec) or
if a remote multi-operator deployment needs concurrent writers across machines.
Neither applies now.

### 1.2 Job and task schemas

A **job** is the unit of user intent (one video, one carousel, one collab).
A **task** is the unit of worker execution (one step: align, render, poll…).
Jobs carry state; tasks carry leases.

```sql
jobs(
  id            TEXT PRIMARY KEY,          -- ulid, e.g. job_01J...
  mode          TEXT NOT NULL,             -- 'original' | 'clip' | 'carousel'
  state         TEXT NOT NULL,             -- see §1.4
  kit_id        TEXT NOT NULL,             -- brand kit id
  kit_version   INTEGER NOT NULL,          -- frozen kit version bound at creation
  campaign_id   TEXT,                      -- mode B only
  title         TEXT NOT NULL,
  created_at    TEXT NOT NULL,             -- ISO-8601 UTC
  updated_at    TEXT NOT NULL,
  cost_usd      REAL NOT NULL DEFAULT 0,   -- rolled up from cost_ledger
  error         TEXT                       -- last terminal failure reason
);

tasks(
  id            TEXT PRIMARY KEY,
  job_id        TEXT NOT NULL REFERENCES jobs(id),
  kind          TEXT NOT NULL,             -- 'align_vo' | 'build_edl' | 'render' |
                                           -- 'run_gates' | 'poll_invite' | ...
  state         TEXT NOT NULL,             -- 'queued' | 'leased' | 'done' | 'failed'
  payload_json  TEXT NOT NULL,             -- task inputs (paths, params)
  result_json   TEXT,                      -- task outputs on done
  attempts      INTEGER NOT NULL DEFAULT 0,
  max_attempts  INTEGER NOT NULL DEFAULT 3,
  lease_owner   TEXT,                      -- worker id holding the lease
  lease_expires TEXT,                      -- ISO-8601 UTC; NULL when not leased
  idempotency_key TEXT NOT NULL UNIQUE,    -- dedupe key: job_id + kind + inputs hash
  run_after     TEXT NOT NULL,             -- not before (backoff / scheduling)
  created_at    TEXT NOT NULL,
  updated_at    TEXT NOT NULL
);
```

Idempotency: `enqueue_task` is `INSERT … ON CONFLICT(idempotency_key) DO NOTHING`
and returns the existing task. Re-running `hypelab render <job>` twice never
creates two render tasks for the same inputs.

### 1.3 Worker leases, retries, cancellation, crash recovery

- **Claim** is one atomic transaction: `UPDATE tasks SET state='leased',
  lease_owner=?, lease_expires=? WHERE id = (SELECT id FROM tasks WHERE
  state='queued' AND run_after <= now ORDER BY created_at LIMIT 1)`. Exactly one
  worker wins.
- **Lease duration:** 10 minutes default, renewable by heartbeat for long renders
  (ffmpeg render of a 60 s cut is well under this; heartbeats cover the tail).
- **Retry:** on task exception, `attempts += 1`. If `attempts < max_attempts` and
  the error is retryable (subprocess crash, OOM, transient I/O): requeue with
  exponential backoff (`run_after = now + 2^attempts minutes`), state back to
  `queued`. Non-retryable errors (validation failure, missing asset, consent
  refused): `failed` immediately, job → terminal or repair state with the reason.
- **Cancellation:** `hypelab cancel <job>` sets job state to `cancelled`;
  workers check the job state before and after each task and abort. Leased tasks
  for a cancelled job are released, never executed.
- **Crash recovery:** on worker startup, `recover_expired_leases()` runs:
  any task with `state='leased'` and `lease_expires < now` returns to `queued`
  (attempts unchanged — the crash wasn't the task's fault). A `kill -9` mid-render
  is therefore recoverable by simply starting a new worker; the render task
  re-runs from its inputs (rendering is deterministic and idempotent).
- **Poison tasks:** `attempts >= max_attempts` → `failed`; job moves to
  `failed` with the error recorded. Never retried again without operator action
  (`hypelab retry <task>` resets attempts).

### 1.4 Job state-transition table (full Lab + Hype)

| From | To | Trigger |
|---|---|---|
| `draft` | `asset_building` | job created with kit + script |
| `asset_building` | `awaiting_media` | shot list emitted; waiting on VO/clips/music (Starter: human attaches) |
| `awaiting_media` | `asset_building` | all media slots filled (`attach`) |
| `asset_building` | `gates` | EDL built + validated, render task done |
| `gates` | `asset_building` | a gate failed → job carries `gate_failures[]` with actionable reasons |
| `gates` | `asset_ready` | all gates passed |
| `asset_ready` | `pitch_sent` | operator runs `pitch --target` (draft recorded) |
| `pitch_sent` | `awaiting_consent` | pitch delivered |
| `awaiting_consent` | `consent_granted` | consent artifact recorded (identity, scope, expiry) |
| `awaiting_consent` | `consent_denied` | **terminal** — decline recorded, asset never published |
| `consent_granted` | `scheduled` | `publish --schedule` (consent re-checked at this transition) |
| `scheduled` | `published` | publish adapter confirms (or dry-run recorded) |
| `published` | `awaiting_accept` | collab invite sent (IG collaborator flow) |
| `awaiting_accept` | `accepted` | invite accepted |
| `awaiting_accept` | `declined` | invite declined |
| `accepted`/`declined` | `measured` | metrics polled, outcomes written |
| `measured` | `archived` | terminal |
| any non-terminal | `cancelled` | operator cancel — **terminal** |
| any | `failed` | poison task / non-retryable error — terminal until `retry` |

**Approval gates (operator approval required):**
1. `pitch_sent` — sending a pitch to a creator (reputation exposure).
2. `scheduled` — any real (non-dry-run) publish.
3. `awaiting_consent → consent_granted` — recording consent requires the actual
   artifact (screenshot/export/message id); the CLI never auto-grants.
4. Mode B `tray` → posting is manual by design (no automated multi-account
   posting, ever).

**Pause-on-third-party states:** `awaiting_media` (human supplies media),
`awaiting_consent` (creator responds), `awaiting_accept` (creator taps accept).
The state machine exists because these are waits on *other people*, not compute.

### 1.5 Cost ledger

```sql
cost_ledger(
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL, task_id TEXT,
  provider TEXT NOT NULL,            -- 'local' | 'edge-tts' | 'postiz' | ...
  units REAL NOT NULL, usd REAL NOT NULL,
  note TEXT, created_at TEXT NOT NULL
);
```

Every task handler may append ledger rows. `jobs.cost_usd` is the sum.
Per-job budgets: `jobs.budget_usd` (nullable); a task that would exceed the
budget refuses to start paid work and fails with `budget_exceeded`.
Local CPU work (ffmpeg, whisper) is logged with `usd = 0` so the ledger is
complete even when spend is zero.

### 1.6 Thin clients

`hypelab` CLI and any future remote control (Telegram bot, dashboard) are thin:
they call `hypelab/services.py` functions, which own all validation and queue
writes. No business logic in the CLI layer. Remote control adds authentication
(token in config, compared in constant time) and a supervision level
(`local` = approve every gate; `remote` = safe actions + notify).

---

## Part 2 — Brand Kits and asset management

### 2.1 Brand Kit: immutable, versioned

```sql
kits(id TEXT PRIMARY KEY, name TEXT NOT NULL, created_at TEXT NOT NULL);
kit_versions(
  kit_id TEXT NOT NULL, version INTEGER NOT NULL,
  appearance_text TEXT NOT NULL,        -- frozen, pasted verbatim into prompts
  ref_image_path TEXT,                 -- locked reference.png (sha256 in assets)
  voice_ref_path TEXT,                 -- locked voice.wav
  writing_samples_json TEXT NOT NULL,  -- 10–20 real published samples
  typography_json TEXT NOT NULL,       -- {font, fallback, weights}
  colors_json TEXT NOT NULL,           -- {primary, secondary, accent, caption_bg...}
  caption_style_json TEXT NOT NULL,    -- {style, size, safe_top_pct, safe_bottom_pct, max_chars}
  guardrails_json TEXT NOT NULL,       -- {do: [...], dont: [...]}
  max_clip_len_s REAL NOT NULL,        -- generator clip-length limit (kit field, not hardcoded)
  created_at TEXT NOT NULL,
  PRIMARY KEY (kit_id, version)
);
```

Rules: versions are append-only; a job binds `kit_id@version` at creation and
never floats. `hypelab kit bump <id>` copies the current version, applies
changes, increments. Rendering records `kit_id@version` + renderer version in
the reproducibility record (§4.6).

Mode B uses a **Campaign Profile** with the same shape but different authority:
look/voice come from the source creator (never impose the operator's brand),
text carries required credits/hashtags, rules are the campaign's. Same tables,
`owner` column distinguishes (`'brand'` vs `'campaign:<id>'`).

### 2.2 Assets: hashed, provenanced, versioned

```sql
assets(
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL,
  slot TEXT NOT NULL,                  -- 'vo' | 'music' | 'beat:b1' | 'ref_image' ...
  path TEXT NOT NULL,                  -- absolute path in the job's asset dir
  sha256 TEXT NOT NULL,
  bytes INTEGER NOT NULL,
  kind TEXT NOT NULL,                  -- 'audio' | 'video' | 'image' | 'json'
  provenance TEXT NOT NULL,            -- 'supplied' | 'generated:edge-tts' |
                                       -- 'generated:ffmpeg-fixture' | 'api:<provider>'
  duration_s REAL, width INTEGER, height INTEGER, fps REAL,
  created_at TEXT NOT NULL
);
```

Every EDL references assets by `slot`; the renderer resolves slots through this
table and verifies the sha256 before use. A replaced file is a new asset row
(old rows retained) — the EDL's `render_hash` then differs, which is correct:
different bytes, different render.

---

## Part 3 — Planning and the EDL

### 3.1 Pipeline

```
script → beats + shot prompts → voiceover → word alignment → final timeline
       → attached/generated media → validated EDL (render.json)
```

1. **Script → beats.** Split on sentences; group into beats sized to
   `kit.max_clip_len_s`. Beat 1 is the hook (budget: ≤3 s Mode A, ≤2 s Mode B).
   `hypelab shots <job>` prints numbered paste-ready prompts, each embedding the
   kit's appearance text + reference image path.
2. **Voiceover is the spine.** VO audio → word alignment (`vo.words.json`).
   Beat boundaries snap to word timestamps. Caption timings derive from the same
   artifact. Never cut on fixed intervals.
3. **Final timeline.** Beats get `t_in/t_out` from the alignment; each beat's
   clip must cover its duration (loop/pad/trim per `clip_fit`).
4. **Media attach.** `hypelab attach <job> <beat> <file>` fills slots (Starter).
   Pro fills the same slots via provider adapters — identical EDL either way.
5. **Validate.** `edl.validate()` enforces the schema (§3.3); invalid EDLs are
   rejected with field-level errors and never reach the renderer.

### 3.2 Tier/mode equivalence

Starter and Pro produce the **same EDL**; they differ only in who fills clip
slots (human attach vs API). Mode A and Mode B produce the **same EDL**; they
differ only in how beats are sourced (script vs extracted moment). One renderer.

### 3.3 render.json schema (v1) + artifact contracts

```jsonc
{
  "edl_version": 1,
  "mode": "original",            // "original" | "clip"
  "kit": "demo@1",               // kit_id@version, frozen
  "source": { "url": null, "t_in": null, "t_out": null },  // mode B provenance
  "target": { "aspect": "9:16", "w": 1080, "h": 1920, "fps": 30,
              "max_duration_s": 60, "loudness_lufs": -14 },
  "audio": {
    "vo":     { "slot": "vo", "align_slot": "vo.words" },
    "music":  { "slot": "music", "duck_db": -12, "fade_in_s": 0.5,
                "fade_out_s": 1.5, "beat_grid_slot": "beats" }
  },
  "beats": [ { "id": "b1", "role": "hook", "t_in": 0.0, "t_out": 3.1,
               "line": "…", "clip_slot": "beat:b1", "clip_fit": "cover",
               "prompt_used": "…", "ref_image_slot": "ref_image" } ],
  "reframe": { "mode": "static", "keyframes": [ {"t": 0.0, "cx": 0.5, "cy": 0.5, "scale": 1.0} ] },
  "captions": { "style": "word_pop", "font": "DejaVu Sans", "size": 74,
                "safe_top_pct": 14, "safe_bottom_pct": 22, "max_chars_per_card": 22 },
  "overlays": [ {"type": "handle", "text": "@demo", "corner": "tl", "persist": true} ],
  "compliance": { "campaign": null, "checks_passed": [] },
  "creative": { "hook_len_s": 3.1, "beat_count": 4, "caption_style": "word_pop",
                "music": true },   // attribution dimensions for what_worked
  "gates_passed": [], "render_hash": null
}
```

**Validation rules (hard rejects):** `edl_version == 1`; `mode`/`aspect`
enumerated; `w,h,fps > 0`; beats sorted, non-overlapping, `t_out > t_in`,
contiguous from 0; every `clip_slot`/`slot` present in assets; `duck_db`
in [-40, 0]; caption size within [24, 160]; safe areas within [0, 40] and
non-overlapping; `reframe.mode` enumerated; hook beat `t_out - t_in ≤ 3.0`
(2.0 for clip mode) — enforced again at gate time.

**slides.json (Mode C):**
```jsonc
{ "slides_version": 1, "kit": "demo@1", "size": [1080, 1350],
  "slides": [ { "n": 1, "role": "cover", "heading": "…", "body": "…",
                "bullets": ["…"], "image_slot": null, "theme": "dark" } ] }
```
Exactly 7 slides (cover, 5 body, CTA). Renderer: HTML/CSS → PNG via headless
Chromium (`--headless --screenshot`), Brand Kit tokens injected as CSS variables.

**vo.words.json (word alignment):**
```jsonc
{ "words_version": 1, "src_slot": "vo", "language": "en",
  "words": [ {"w": "hello", "t0": 0.12, "t1": 0.34}, … ] }
```
Strictly increasing `t0`, `t1 > t0`, gap between consecutive words < 2 s
(flags long silences for the planner, doesn't reject).

**beats.json (beat grid, optional):**
```jsonc
{ "beats_version": 1, "src_slot": "music", "bpm": 96.0, "beats": [0.0, 0.625, …] }
```
Derived via librosa/aubio when available; absent → cut-on-beat disabled, render
proceeds (graceful degradation, recorded in `gates_passed` notes).

### 3.4 CLI for the planning loop

```
hypelab new <kit> --script <file> [--title T]     # create job (draft → asset_building)
hypelab shots <job>                               # numbered paste-ready prompts
hypelab attach <job> <beat|vo|music> <file>       # fill a media slot
hypelab align <job>                               # VO → vo.words.json
hypelab plan <job>                                # beats + alignment + media → render.json (validated)
hypelab show <job>                                # job state, tasks, EDL summary
```

---

## Part 4 — Deterministic rendering
## Part 4 — Deterministic rendering

### 4.1 The contract

The renderer is a pure function: `validated EDL + content-addressed assets → MP4`.
It never improvises, never calls the network, never executes strings as shell.
All ffmpeg invocations are `argv` lists built from validated data
(`subprocess.run([...], shell=False)`).

### 4.2 Pipeline per beat

For each beat: take `clip_slot` video → `scale` + `crop` to target aspect per
`clip_fit` (`cover`: scale to fill, center-crop; `contain`: pad with blurpad) →
`trim`/`loop` to exactly `t_out - t_in` → `setpts` to start at `t_in` →
concatenate. Reframe keyframes (`reframe.mode: track|split|static|blurpad`)
become crop expressions evaluated per frame — still data, not code.

### 4.3 Captions: ASS word-pop

`vo.words.json` → ASS with karaoke `\k` tags: each word highlights as spoken.
Style from the kit (font, size, colors). Placement: inside the safe box
(`safe_top_pct`/`safe_bottom_pct`); line-breaking at `max_chars_per_card`.
Burned with `-vf ass=...`. ASS is generated, written to a temp file, passed as
a path — never interpolated into a shell string.

### 4.4 Audio

- VO track: as-is (already the timing spine).
- Music: `volume` automation keyed off VO word segments (duck to `duck_db`
  under speech, restore in gaps) — deterministic, no sidechain estimation
  variance; `sidechaincompress` reserved for Pro/live paths.
- `afade` in/out (`fade_in_s`/`fade_out_s`), `atrim` to the exact cut length.
- `loudnorm` dual-pass to `target.loudness_lufs` (−14 LUFS social target).
  Measured value is asserted by the loudness gate.

### 4.5 Multi-aspect from one timeline

Render the 9:16 master, then derive 1:1 and 16:9 with a second ffmpeg pass
(center-crop / blurpad per kit policy) — one edit, three formats, no re-cutting.
`hypelab render <job> --aspect 9:16,1:1,16:9`.

### 4.6 Reproducibility record

Every render writes `render_record.json` next to the MP4:
`{edl_version, render_hash (sha256 of canonical render.json), kit_id@version,
renderer_version, ffmpeg_version, whisper_model, asset_shas, caption_ass_sha,
filtergraph_sha, started_at, duration_s}`. Caption/layout changes reuse cached
clip segments (keyed by beat id + clip sha + fit params) so re-renders are fast.

### 4.7 Caching

`~/.cache/hypelab/` (or `$HYPELAB_CACHE`): keyed artifacts —
`clipseg:{beat}:{sha}:{fit}`, `ass:{words_sha}:{style_sha}`, `loudnorm:{mix_sha}`.
Cache is content-addressed; stale entries are impossible by construction.

## Part 5 — Quality gates and carousels

### 5.1 Gates (fail the job, never ship it)

| Gate | Check | Threshold |
|---|---|---|
| `duration` | output duration | ≤ `target.max_duration_s`, ≥ 3 s |
| `aspect` | output WxH | exactly `target.w` × `target.h` |
| `first_frame` | blackdetect + freezedetect on first 1 s | no black > 0.3 s, no freeze |
| `hook` | beat[0] duration | ≤ 3.0 s (Mode A) / ≤ 2.0 s (Mode B) |
| `captions_safe` | ASS layout vs safe box | 0 words outside safe area |
| `loudness` | ebur128 integrated | `target.loudness_lufs` ± 1.5 LU |
| `slots_filled` | every beat has a clip asset | 100% |
| `audio_present` | streams | ≥1 video + ≥1 audio stream |

A failed gate records `{gate, reason, measured, threshold, actionable_fix}` on
the job and returns it to `asset_building`. `hypelab gates <job>` re-runs gates
on demand. Limitations documented: blackdetect thresholds are heuristic;
loudness measurement depends on ffmpeg's ebur128; caption-safe is computed from
ASS geometry, not OCR of the pixels.

### 5.2 Carousel renderer (Mode C)

`slides.json` → Jinja-free Python HTML template with kit CSS variables →
headless Chromium `--headless --screenshot --window-size=1080,1350` →
7 PNGs. No Satori dependency, no demo-repo fork. Brand Kit controls type, color,
layout tokens. Text overflow is a gate (measure via Chromium's layout, fail the
slide with the overflowing field named).

## Part 6 — Consent and publishing

### 6.1 Records

```sql
targets(handle TEXT, platform TEXT, followers INTEGER, er REAL,
        public INTEGER, pattern_json TEXT, contact_route TEXT,
        consent_state TEXT, invite_history_json TEXT, outcome TEXT,
        PRIMARY KEY (handle, platform));
consents(id TEXT PRIMARY KEY, target_handle TEXT, target_platform TEXT,
         job_id TEXT NOT NULL, pitched_at TEXT, responded_at TEXT,
         scope TEXT NOT NULL,               -- e.g. 'collab_post:instagram'
         asset_version TEXT NOT NULL,       -- render_hash consented to
         evidence TEXT NOT NULL,            -- message id / screenshot path / export
         expiry TEXT NOT NULL, revoked_at TEXT);
```

### 6.2 The hard gate

`publish(job, dry_run=False)`:
1. If the job names a collaborator/target: query consents for a non-expired,
   non-revoked record whose `asset_version` equals the current `render_hash`.
2. None found → raise `ConsentRequired`, job stays in `awaiting_consent`.
   This is tested, not documented-wished.
3. `dry_run=True` (default): validate everything, write the publish plan,
   mark nothing published. Explicit in output: `DRY RUN — nothing was sent`.
4. Real publish requires `dry_run=False` **and** a `--i-confirm` flag **and**
   a valid consent. All three, always.

Consent is re-checked at `consent_granted → scheduled` and again immediately
before the provider call (a revocation between scheduling and posting must not
publish).

### 6.3 Provider-neutral publish interface

```python
class PublishAdapter(Protocol):
    name: str
    def capabilities(self) -> dict: ...        # what this provider can do
    def publish(self, plan: PublishPlan, dry_run: bool) -> PublishResult: ...
    def invite_status(self, media_id: str) -> str: ...
```

v1 ships: `dryrun` adapter (always) and a `postiz` stub (interface + config,
no credentials, every method raises `NotConfigured` until configured).
Provider choice (Postiz vs Zernio vs native) is re-verified against current
official API docs before any real integration — the brief's Aug-2026 table is
stale by the time you read this.

Every Instagram publish sets `collaborators` (≤3, public accounts only) and
`isAIGenerated: true`.

## Part 7 — Measurement and feedback

```sql
posts(id TEXT PRIMARY KEY, job_id TEXT, clip_id TEXT, platform TEXT,
      post_url TEXT, posted_at TEXT, collaborator TEXT);
metrics(post_id TEXT, t TEXT, views INTEGER, likes INTEGER, comments INTEGER,
        shares INTEGER, saves INTEGER, PRIMARY KEY (post_id, t));
what_worked(dimension TEXT, value TEXT, n INTEGER, mean_perf REAL,
            updated_at TEXT, PRIMARY KEY (dimension, value));
```

- **Metric windows:** views at 24 h / 7 d / 30 d per post; denominators recorded
  (follower count at post time) so rates, not raw counts, are compared.
- **Missing data:** a poll that fails is recorded as a gap, never as zero.
- **Polling:** `hypelab measure` polls open posts on a schedule (default 6 h);
  duplicate polls are idempotent on `(post_id, t)`.
- **Attribution:** `posts` links to the exact `render_hash` + EDL `creative{}`
  block (hook length, beat count, caption style, music on/off). `what_worked`
  aggregates per dimension. **Descriptive only** until n ≥ 30 per cell and an
  operator reviews — the CLI prints "insufficient evidence" otherwise and never
  auto-changes creative defaults.
- **Mode B:** `moments.signals_json` stores which signals selected the moment;
  outcomes train the scorer weights per source creator.

## Part 8 — Security, costs, and operations

- **Secrets:** `~/.config/hypelab/secrets.env` (mode 600), never in the repo,
  never in logs. Provider keys loaded at runtime; `hypelab doctor` reports
  which are present without printing values.
- **Remote auth:** bearer token in config, constant-time compare; supervision
  levels (`local`/`remote`) gate which commands are exposed remotely.
- **Upload validation:** `attach` checks extension allowlist, magic bytes,
  size caps (video ≤ 500 MB, audio ≤ 100 MB), duration caps; quarantines on
  mismatch. Symlinks rejected; paths confined to the job dir.
- **Network-fetch restrictions:** the renderer and workers never fetch URLs.
  Only explicit `hypelab fetch --url` (operator-initiated, allowlisted hosts)
  downloads, into quarantine, then hashed.
- **Resource limits:** worker subprocesses get timeouts (whisper 20 min,
  ffmpeg 30 min) and memory caps via `ulimit` where supported; concurrent
  renders capped at `nproc/2`.
- **Backups/recovery:** the SQLite DB + `jobs/` dir are the state. `hypelab
  backup` → timestamped tarball; restore = unpack + `hypelab worker recover`.
  Crash recovery is via lease expiry (§1.3) — no separate journal.
- **Budgets:** per-job `budget_usd`; paid tasks check before spending;
  `hypelab costs` shows per-job and total spend. Cancellation stops queued paid
  work immediately.
- **Manual fallback:** every Pro/provider path has a Starter equivalent —
  `attach` by hand. A provider outage degrades to `awaiting_media`, never to
  silent failure.

---

# Required outputs

## 1. Compact architecture diagram

```
                        ┌──────────────┐
                        │  Brand Kit   │  immutable versions
                        │  kit_id@v    │
                        └──────┬───────┘
                               │ bound at job creation
┌────────┐  script/   ┌────────▼────────┐   render.json  ┌─────────────┐
│  CLI   │──article/──▶│  PLANNER        │───(validated)─▶│  RENDERER   │
│ (thin) │  long-form  │  beats→VO→align │                │ ffmpeg+ASS  │
└───┬────┘  source     │  →EDL           │                │ (pure fn)   │
    │                 └────────┬────────┘                └──────┬──────┘
    │ services.py              │ media slots                    │ MP4
    │                          ▼                                ▼
┌───▼──────────────────────────────────────────────┐   ┌──────────────┐
│  SQLite: jobs │ tasks(leases) │ kits │ assets │    │──▶│ QUALITY      │
│  edls │ consents │ targets │ posts │ metrics │    │   │ GATES        │
│  what_worked │ cost_ledger                      │   │ pass → tray  │
└───┬──────────────────────────────────────────────┘   │ fail → repair│
    │                                                  └──────┬───────┘
    │            ┌──────────────────┐                          │
    └───────────▶│  WORKER (leases, │◀─────────────────────────┘
                 │  retry, recover) │
                 └────────┬─────────┘
                          │ consent hard gate
                 ┌────────▼─────────┐      ┌──────────────┐
                 │  PUBLISH adapter │─────▶│  MEASURE     │
                 │  (dry-run first) │      │  →what_worked│
                 └──────────────────┘      └──────────────┘
```

## 2. Module boundaries and directory structure

```
hypelab/                        # repo root
  ARCHITECTURE.md               # this document
  README.md                     # setup + quickstart
  hypelab/
    __init__.py
    cli.py          # thin CLI: argparse → services.py (no business logic)
    services.py     # application services: the API every client uses
    db.py           # schema, migrations, connection (WAL)
    queue.py        # enqueue/claim/complete/fail, leases, idempotency, recovery
    worker.py       # worker loop: claim → dispatch → heartbeat → done/fail
    tasks_lab.py    # task handlers: align_vo, build_edl, render, run_gates
    kits.py         # brand kit store (immutable versions)
    assets.py       # asset intake: validation, hashing, provenance
    plan.py         # script → beats → shot prompts → render.json assembly
    edl.py          # render.json / slides.json / words.json validation
    align.py        # whisper word alignment → vo.words.json
    captions.py     # words → ASS (word-pop)
    audio.py        # ducking, fades, loudnorm filtergraph fragments
    render.py       # EDL → ffmpeg argv (safe), multi-aspect derivation
    gates.py        # quality gate implementations
    carousel.py     # slides.json → HTML → PNG (mode C)
    consent.py      # consent ledger + hard gate
    publish.py      # provider-neutral interface; dryrun + postiz stub
    measure.py      # metrics polling, what_worked aggregation
    modes_b.py      # clip mine: ingest/score/reframe/tray (stub → build order #3)
    config.py       # paths, secrets loading, supervision levels
  tests/
    test_edl.py test_queue.py test_gates.py test_consent.py test_render.py
  fixtures/
    script.txt  kit.json  beats_sample.json
  docs/
    WALKTHROUGH.md  OPERATIONS.md
```

Boundary rule: `render.py`, `captions.py`, `audio.py`, `gates.py` are pure
functions of (validated EDL, assets). `queue.py`/`worker.py` never import them
directly — dispatch goes through `tasks_lab.py` handlers. Nothing outside
`render.py` builds ffmpeg argv.

## 3. Database schemas and artifact contracts

Schemas: §1.2 (jobs, tasks), §1.5 (cost_ledger), §2.1 (kits, kit_versions),
§2.2 (assets), §6.1 (targets, consents), §7 (posts, metrics, what_worked),
plus:

```sql
edls(job_id TEXT PRIMARY KEY, version INTEGER, render_json TEXT NOT NULL,
     render_hash TEXT NOT NULL, created_at TEXT NOT NULL);
```

Artifact contracts: §3.3 (render.json, slides.json, vo.words.json, beats.json).

## 4. Job state-transition table

§1.4 (Lab + Hype full machine, approval gates, pause-on-third-party states).

## 5. CLI commands and adapter interfaces

CLI: §3.4 plus
```
hypelab kit new|show|bump <id>
hypelab work [--once] [--worker ID]     # run the worker loop
hypelab render <job> [--aspect ...]
hypelab gates <job>
hypelab carousel <article> --kit <id>   # mode C
hypelab pitch <job> --target <handle>   # hype (records draft)
hypelab publish <job> [--dry-run] [--i-confirm]
hypelab measure [--all]
hypelab worked [dimension]
hypelab costs [--job <id>]
hypelab cancel <job> | hypelab retry <task>
hypelab backup | hypelab doctor
```
Adapter interfaces: `PublishAdapter` protocol (§6.3). Provider adapters for
media generation (Pro tier) follow the same shape: `fill_slot(slot, prompt) ->
asset`, always with a Starter manual fallback.

## 6. Failure-handling and recovery rules

| Failure | Detection | Response |
|---|---|---|
| Worker crash (kill -9) | lease expiry on next worker start | task → queued, re-runs from inputs |
| Transient subprocess error | exception in handler | retry with exponential backoff, ≤ max_attempts |
| Poison task | attempts exhausted | task failed, job failed with reason |
| Invalid EDL | `edl.validate()` | rejected before render; job → asset_building with field errors |
| Gate failure | `gates.run()` | job → asset_building with actionable reasons |
| Missing media | slot empty at plan/render | job → awaiting_media, prompts re-emitted |
| Budget exceeded | pre-task budget check | task refused, job paused with reason |
| Consent missing/expired/revoked | `consent.require()` | publish refused; job stays awaiting_consent |
| Publish partial failure | adapter result | recorded per-target; never blindly reposted |
| Duplicate enqueue | idempotency_key conflict | existing task returned, no double work |
| Upload invalid | magic-byte/size check | rejected at attach, never enters assets |

## 7. Ordered implementation milestones with acceptance criteria

| # | Milestone | Acceptance |
|---|---|---|
| M1 | Queue + worker + leases + recovery | kill -9 mid-task → new worker completes it; duplicate enqueue → one task |
| M2 | Kit store + asset intake | kit versions immutable; tampered asset detected by sha mismatch |
| M3 | EDL schema + validator | 10 invalid EDL fixtures → 10 rejections with field errors; valid → 0 errors |
| M4 | **Vertical slice (Mode A Starter): script → VO → align → EDL → MP4 → gates** | real ffmpeg render; gates pass; quality report written |
| M5 | Multi-aspect + audio (ducking, loudnorm) + beat grid | 3 aspects from one EDL; loudness within ±1.5 LU of target |
| M6 | Consent ledger + publish dry-run + hard gate | publish without consent → refused; dry-run → explicit "nothing sent" |
| M7 | Mode C carousel | 7 PNGs from slides.json, kit-styled, overflow gated |
| M8 | Mode B: ingest + scoring + reframe + tray | tray package complete per clip; compliance gate rejects a violating clip |
| M9 | Measure + what_worked | 30+ synthetic outcomes → aggregation correct; <30 → "insufficient evidence" |
| M10 | Docs: whitepaper-equivalent (this doc + README + walkthrough + operations) | matches implementation, no fixture claims as real |

**Blocked / explicitly out of scope:** real publishing credentials (no keys —
dry-run only); paid provider APIs (no spend); TikTok/X/LinkedIn/Substack
publishing (per platform reality §6/§7.5 of the spec); browser automation
(never); AI-detector evasion (never); local model hosting beyond CPU whisper.

---

*End of ARCHITECTURE.md — HypeLab v2, 2026-09-28.*
