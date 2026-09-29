# Flow 6 (ARC trace): carousel — gates-first → Chromium HTML→PNG

Owner: Architect (ARC) · Phase 2 · 2026-09-29
Read in full: `hypelab/carousel.py` (1–441), `hypelab/book3cli.py` carousel
command (95–122), `hypelab/jobs.py` (62–82), `hypelab/kits.py` (seed/load,
relevant parts).

Entry: `hypelab carousel --spec spec.json [--job J] [--kit ID]`
(`book3cli.py:95-122`) → `carousel_mod.render_carousel` + `export_jpeg`
(`carousel.py:353-441`).

## Hop 1 — CLI: spec load, kit load, job provisioning
`book3cli.py:101-120`:

- `spec = json.loads(Path(spec_path).read_text(...))` (`book3cli.py:103`) —
  no `try/except`: a malformed spec JSON raises an uncaught traceback
  (contrast `b2cli._read_json`, which `_die`s cleanly). Minor inconsistency
  in error handling across the three CLI modules.
- `kit = _kit_or_die(conn, kit_id)` (`book3cli.py:104`) — brand-kit reuse
  per Book 3 §3.
- **Job provisioning bypasses the state machine (ARC-309):** with no `--job`,
  the command creates `jobs.new(conn, mode="carousel", state="ready")`
  (`book3cli.py:106-108`) plus a manual `conn.commit()` (`book3cli.py:109`).
  `jobs.new` validates nothing about the initial state (`jobs.py:62-82`), so
  `ready` — a terminal-ish state reached in Book 1 only after 8 gates — is
  the *birth* state. Carousel jobs share the `jobs` table with pipeline
  jobs but not the lifecycle; `queue.claim` never sees them (no
  `queued_*` state), which is correct only by accident of the state names.
- `out_dir = work/<job>/carousel` (`book3cli.py:113`) — filesystem layout
  consistent with the `work/<job>/` write domain (`util.work_dir`,
  `util.py:174-206`).

## Hop 2 — spec validation (the "dumb spec" contract)
`validate_spec` (`carousel.py:353-374`): exactly 7 slides, `idx` 1..7,
`layout ∈ {hook, stat, body, cta}`. Structural, fail-fast, pure — good.
The spec is data (JSON file), the renderer is code; the boundary is clean.

## Hop 3 — gates run BEFORE any render
`run_carousel_gates` (`carousel.py:269-277`) → `gate_text_overflow`
(`carousel.py:224-254`) + `gate_slide_one_hook` (`carousel.py:257-267`),
invoked at `carousel.py:380-386` inside `render_carousel` before the
screenshot loop. "Gates-first" is honored structurally: a gate failure
raises `CarouselError` and no PNG is produced.

- `gate_text_overflow` does static checks (≤20 words/slide, ≤40-char lines)
  then **one Chromium launch per slide** (`_measure_slide`,
  `carousel.py:186-213`) for in-browser measurement. 7 slides → 7 probe
  launches + 7 screenshot launches = **14 Chromium invocations per
  carousel** (`carousel.py:380-403`). Correct but slow; no batching
  (one HTML page could carry all 7 slides).
- `gate_slide_one_hook`: slide 1 title non-empty, ≤12 words. Pure.

## Hop 4 — HTML generation (Python-side rendering)
`kit_to_css` (`carousel.py:76-110`) + `_slide_html` (`carousel.py:116-144`):

- Brand-kit reuse is real: caption `fill`/`highlight`/`font` flow into CSS
  variables (`carousel.py:79-84`).
- **Kit values are f-string-interpolated into CSS/HTML with no
  sanitization** (`carousel.py:85-110`); slide text is `html.escape`d
  (`_esc`, `carousel.py:113-114`) but CSS tokens are not. A hostile or
  malformed kit value breaks out of the stylesheet. (Noted for SEC;
  the ARC point is the seam: trusted-data → markup is string
  concatenation, not a template engine with auto-escaping.)
- **Hardcoded content (flag for BUG):** the `hook` layout's kicker is the
  literal string `New Light Management` (`carousel.py:125`), not from the
  spec or the kit — every carousel rendered with the `hook` layout carries
  it. The kit supplies colors/fonts but not this text.

## Hop 5 — the browser seam: probe + screenshot via Chromium
`_chromium()` (`carousel.py:53-70`) → `_measure_slide` (`carousel.py:186-213`)
→ `_screenshot` (`carousel.py:299-309`):

- **The Python↔browser contract is a hand-rolled string protocol (ARC-314):**
  `_PROBE_JS` (`carousel.py:158-184`) serializes measurements into
  `document.title = 'MEASURE:' + JSON.stringify(...)`; `_measure_slide`
  extracts it with `re.search(r"<title>MEASURE:(\{.*?\})</title>", ...)`
  (`carousel.py:208`) and indexes `measured["blocks"]` with no schema
  validation (`carousel.py:238-248`). The two sides of the contract live in
  the same file, which is the only thing keeping it honest — there is no
  shared schema, no versioning, and a Chromium change in `--dump-dom`
  title handling breaks measurement. Failure is loud (`CarouselError`,
  `carousel.py:210-212`), which is the saving grace.
- `_chromium()` resolves the binary per-call from `HYPELAB_CHROMIUM`, PATH
  (`google-chrome`, `chromium`, …), or a legacy path — **no version pin,
  no version record**. The PNG output depends on the Chromium build's text
  shaping; unlike Book 1's ffmpeg determinism story (render hash,
  `render.py`), carousel output is not reproducible across machines and
  nothing records which Chromium rendered a given slide set.
- Probe HTML is written with plain `write_text` into a `TemporaryDirectory`
  (`carousel.py:198-202`) — fine for temp scope; final PNGs use the atomic
  discipline (`_atomic_write_bytes`, `carousel.py:280-297`), consistent
  with Book 1's `util.write_json`/`intake_asset` conventions (though it is
  a second, parallel implementation of "atomic write" — `util.write_json`
  handles text/JSON only).
- Each PNG is verified at exactly 1080×1350 via ffprobe (`_png_size`,
  `carousel.py:312-322`; enforced at `carousel.py:395-400`) — the one
  hard output invariant, and it is checked. Good.

## Hop 6 — persistence (optional, inside the renderer)
`render_carousel(..., conn=conn, job_id=job_id)` INSERTs `slides` rows
(`carousel.py:405-412`) and calls **`conn.commit()`** (`carousel.py:412`).

- **Transaction boundary in the wrong place (ARC-305):** a renderer that
  optionally persists decides the commit. In autocommit mode
  (`db.connect`, `db.py:138-147`) this is a no-op, but it hard-codes the
  unit of work inside the library — a caller composing the carousel
  render with other writes cannot roll the slides rows back.
- The `slides` sort (`sorted(spec["slides"], ...)`) is computed twice
  (`carousel.py:380, 405`) — trivial, but symptomatic of the render loop
  and the persistence loop being two separate passes over the same data
  instead of one.

## Hop 7 — JPEG export
`export_jpeg` (`carousel.py:416-441`): ffmpeg PNG→JPG, same atomic
tmp+rename discipline. Clean.

## Layering verdict (flow 6)

The flow's *intended* layering is good: dumb JSON spec → pure validation →
pure gates → HTML string building → browser as a rendering appliance →
verified PNGs. Gates-before-render is structurally enforced, and the
1080×1350 output invariant is actually checked.

The seam between the Python pipeline and the browser renderer is the
weakest architectural point in this flow:

1. **Implicit cross-process contract (ARC-314):** measurement results cross
   the process boundary as a regex-scraped `document.title` payload with no
   schema. It works and fails loudly, but it is one Chromium behavior
   change away from a broken gate, and the "protocol" is invisible to
   anyone reading only one side.
2. **Unpinned, unrecorded renderer:** which Chromium binary (and version)
   produced a slide set is not recorded anywhere; output is not
   reproducible across environments, in contrast to the ffmpeg determinism
   story the rest of the codebase tells.
3. **Job-model bypass (ARC-309):** the carousel job is born `ready`,
   skipping the state machine the `jobs` table exists to enforce; the
   renderer optionally persists + commits (ARC-305), mixing the render
   layer with the persistence layer.
4. **14 browser launches per carousel** — no batching; a performance cost
   baked into the architecture (measure + screenshot are separate
   Chromium invocations per slide).

What the seam does right: validated argv arrays only (`_run`,
`carousel.py:73-76`), no `shell=True` anywhere; fail-loud on missing
Chromium (`carousel.py:67-70`); atomic final writes; per-PNG dimension
verification. The discipline around the seam is good — it is the
*contract across* the seam that is informal.
