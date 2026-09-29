# Flow 5 (BUG) — kit lock: `kit new` → immutable v1 seed → appearance lock

Owner: BUG (Logic & Correctness) · Phase 2, Pass 3 · 2026-09-29
Scope: `hypelab/kits.py` (180), `hypelab/cli.py` kit_new/new/_get_kit,
`hypelab/book3cli.py` carousel (latest-kit usage).
Method: trace what "immutable" enforces at the DB layer, how jobs pin the
kit version, whether any path reads the latest instead of the pin, and
what breaks on a mid-flight bump.

## How it works (hop by hop, with path:line)

### H0. `kit new` → immutable v1 seed (cli.py:373-390 → kits.py:66-83)
1. `kit_new` parses the JSON file (`_die` on bad JSON / non-object),
   adapts via `_adapt_cerebratico` when the four Book-1 keys are absent
   (kits.py:100-165; float() conversions uncaught → BUG-011), then
   `kits.seed(conn, kit_id, data)`.
2. `seed` (kits.py:66-83): existence check → ValueError("kit … already
   exists") → clean `_die` (duplicate seed tested in test_cli.py). INSERTs
   `(id, 1, data_json, created_at)` with `payload["id"]`/`payload["version"]`
   FORCED to `kit_id`/`1` — user-supplied id/version keys in the JSON are
   overwritten, never trusted.
3. What "immutable" actually enforces (all in kits.py):
   - `PRIMARY KEY (id, version)` — the DB rejects any second write to the
     same version;
   - `seed` refuses an existing id (no re-seed, no overwrite);
   - `bump(conn, kit_id, **changes)` (kits.py:85-103) INSERTs
     `max(version)+1` with a deep-merged COPY — old rows are never
     UPDATE/DELETE'd;
   - `load(conn, kit_id, version)` (kits.py:43-64) reads one pinned row;
     `version=None` reads latest (used only at creation + Book 3).
   - No UPDATE or DELETE statement on `kits` exists anywhere in the
     codebase (verified by grep).
4. Gaps in the enforcement:
   - exists-check→INSERT TOCTOU: two concurrent `kit new <same-id>` →
     one `sqlite3.IntegrityError` traceback instead of a clean error
     (→ BUG-011). Same race in `bump` (max+1 computed twice).
   - No CLI exposes `bump` (the `kit` group has only `new`) — mid-flight
     bumps are Python-API-only, which limits the blast radius in practice.

### H1. Pinning at `new` (cli.py:392-464)
1. `kit = kits_mod.load(conn, kit_id)` — LATEST at creation time
   (cli.py:405); immediately pinned two ways:
   - DB: `jobs_mod.new(…, kit_version=kit["version"])` (cli.py:452-455);
   - EDL: `kit_ref=f"{kit_id}@{kit['version']}"`, schema-enforced pattern
     `^[a-z0-9_-]+@\d+$` (edl.py:35), stamped into `render.json` and every
     `edls` row.
2. The EDL also snapshots the kit's `captions` block at creation
   (`captions=dict(kit.get("captions"))`, cli.py:447) and `min_word_prob`
   (cli.py:449) — caption style/size used by `render` →
   `cap_mod.build_ass` (render.py:340-343) comes from the SNAPSHOT, not
   from a later kit read. `target.loudness_lufs` likewise snapshotted
   (cli.py:425).

### H2. Every Book-1 read uses the pin
- `_get_kit(conn, job)` → `kits_mod.load(conn, job["kit_id"],
  job["kit_version"])` (cli.py:153-157); KeyError → `_die`. Used by
  `shots`, `audio`, `_render_job`, `_handle_align`.
- `audio` (cli.py:562-636): `asr` cfg, `min_word_prob`, `music_duck_db` —
  all from the PINNED kit.
- `render` (cli.py:656-752): `provenance=manifests_mod.provenance(kit)` —
  pinned kit's `asr` block feeds the render hash (manifests.py:158-172),
  so provenance (and therefore `render_hash`) is version-stable.
- `gates`: threshold from the EDL's stamped `min_word_prob`
  (gates.py:402-440), not from any kit read.
- No Book-1 path calls `kits.load` without a version. Verified by grep:
  the only version-less loads are cli.py:405 (creation pinning) and
  book3cli.py:67 (below).

### H3. What breaks if a kit is bumped mid-flight
Short answer: **nothing in Book 1** — that is the point of the design, and
it holds:
- In-flight job keeps `kit_version=v1` in its row; `_get_kit` loads v1;
  captions/ASR/thresholds are v1's; the render hash binds v1's provenance.
- A bump only affects jobs created AFTER it (`new` loads latest at
  creation). Old rows are never mutated, so re-rendering an old job
  reproduces the old appearance/captions (this is exactly what TST-004
  wants a test for — mechanism sound, coverage missing).
- `_adapt_cerebratico` defaults (font DejaVu Sans, size 72, …) are baked
  at seed; a bump that changes caption size cannot leak into an old job's
  ASS because `build_ass` reads the EDL snapshot.
- Edge: if the v1 ROW were deleted from the DB (no API does this; only
  raw SQL), `_get_kit` → KeyError → `_die` — loud, not silent. There is no
  fallback to latest (good).

### H4. The Book-3 exception
`book3cli.py:67` (`_kit_or_die`) loads the LATEST kit by id, and
`carousel --kit <id>` (book3cli.py:88-119) renders with it even when
`--job` points at a job pinned to an older kit version. So the appearance
lock does NOT extend to Book-3 carousels: bumping a kit mid-flight
changes subsequently rendered carousels for old jobs. Carousel takes
`--kit` explicitly from the operator, so this is arguably operator choice
— but `--job` implies "this job's kit" and the pin is silently ignored.
Noted as an observation (Book 3 is outside this flow's scope; SEC/DAT may
want it).

## Observations
- The immutability design is genuinely append-only (no UPDATE/DELETE on
  `kits` anywhere) and the pinning is complete for Book 1: row pin + EDL
  `kit_ref` + snapshot of captions/thresholds/loudness at creation. This
  is the strongest "lock" of the three flows reviewed.
- The weak points are all at the edges: concurrent seed/bump races
  (tracebacks, not corruption), uncaught float() in kit adaptation, and
  Book 3's latest-kit reads.
- `seed` commits inside the function (kits.py:81) while `load`/`bump`'s
  `_ensure` DDL runs uncommitted — harmless under autocommit, but a
  caller holding an explicit transaction would see `_ensure`'s CREATE
  participate in it. No caller does today.

## Open questions
- Q1: should `bump` get a CLI command (currently API-only), and if so,
  with what guardrails (e.g. refuse while jobs referencing the kit are
  in-flight)? Recommended default: keep API-only until an operator asks;
  the current surface can't bump by accident.
- Q2: should `carousel --job` resolve the job's pinned kit instead of
  `--kit`/latest? Recommended default: yes — `--kit` should default to
  the job's pinned version when `--job` is given.
- Q3 (already TST-004): add the mid-flight bump regression test
  (`new` → `bump` caption size → `render` old job → assert v1 captions in
  ASS + `kit_ref`).

## Related issues
- BUG-011 (S3): kit seed/bump races + uncaught adapt float() errors.
- TST-004: pinning mechanism sound; test coverage missing (no behavioral
  bug found).
