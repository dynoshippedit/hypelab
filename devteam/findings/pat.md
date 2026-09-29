# PAT findings — Pattern Pack sweeps (Phase 3, 2026-09-29)

Lane prefix: PAT · ID range PAT-600–649 · all NEW, Status Confirmed.
Branch `devteam/review-2026-09-29`. Severities per Playbook B7.
"Evidence" = path:line + quoted code. Sweep method and dismissed patterns are
recorded in `devteam/notes/pattern-pack.md`; this file contains only new findings.
Sibling instances already covered by MAP/TST/BLD/DOC/STR/DAT/ARC/BUG/SEC findings
are mapped there, not re-filed (see the duplicates table in the notes file).

## PAT-600 — Dead code: 13 never-called functions incl. a dead sanitizer and stale docstring claims [S3, Confirmed]

**Location:** `hypelab/authorize.py:72`, `hypelab/campaigns.py:158,175`,
`hypelab/compliance.py:318`, `hypelab/consent.py:181`, `hypelab/render.py:35`,
`hypelab/tray.py:183,194`, `hypelab/watcher.py:289`, `hypelab/kits.py:167`,
`hypelab/publish/dryrun.py:107`, `hypelab/align.py:159,569`.

**Evidence:** AST call-graph over `hypelab/` (Name + Attribute call sites) plus
full-text reference search over `hypelab/` + `tests/` + docs — each function
below has **zero** call sites and **zero** textual references outside its own
`def` line. Click-registered CLI commands, `gates.gate_*` (string dispatch,
`gates.py:452`), and `compliance.chk_*` (string dispatch, `compliance.py:183`)
were verified live and are excluded.

```python
hypelab/authorize.py:72:      def list_for(conn, job_id)            # no callers anywhere
hypelab/campaigns.py:158:     def compliance_is_stale(conn, clip_id) # no callers anywhere
hypelab/campaigns.py:175:     def get_rule_provenance(conn, campaign_id)  # no callers anywhere
hypelab/compliance.py:318:   def unknowns_for_job(conn, job_id)     # no callers anywhere
hypelab/consent.py:181:      def require_consent(conn, job_id, ...)  # fail-closed wrapper, no callers
hypelab/render.py:35:        def _esc_filter(s)                     # filtergraph sanitizer, no callers
hypelab/tray.py:183:         def tray_clips(...)                    # no callers anywhere
hypelab/tray.py:194:         def tray_slug_for(...)                 # no callers anywhere
hypelab/watcher.py:289:       def host_of(url)                       # no callers anywhere
hypelab/kits.py:167:         def seed_cerebratico(conn, kit_path)   # no callers anywhere
hypelab/publish/dryrun.py:107: def fixture_post_id(*a, **k)         # module wrapper, no callers
hypelab/align.py:569:         def _constrain_to_script(...)          # no callers anywhere
hypelab/align.py:159:         def fetch_model(cache_dir)             # no PRODUCTION callers (tests only)
```

**What's wrong:** dead weight with two sharp edges. (1) `render._esc_filter`
is a *sanitizer* nobody calls — every live sink uses `_esc_sq`/`_esc_drawtext`,
so it is either vestigial or a sign a sink was meant to use it (all current
sinks verified escaped — see notes/pattern-pack.md §18). (2) Two docstrings lie
about why the dead code exists: `seed_cerebratico` says "NOT run automatically
— the integrator seeds via CLI" (`kits.py:168-169`), but no CLI command calls
it (`kit_new` calls `kits.seed()`); `_constrain_to_script` is "kept for existing
regression tests" (`align.py:567`), but zero tests reference it. `fetch_model`
is production-dead with no `fetch` CLI command — the `align.py:182` error
"run fetch_model first" is unreachable in production (sibling of DAT-364).
`require_consent` is harmless-dead only because `gate_consent`/`valid_for`
carry the enforcement (`publish/__init__.py:179`, `book3cli.py:223`).

**Impact:** maintainability / confusion risk; operators reading the docstrings
are pointed at workflows that do not exist. No behavior impact today.

**Already filed elsewhere (not duplicated here):** `queue.charge()` → DAT-352,
`queue.release()` → BUG-007, `metrics.usd_per_clip_hour()` → DAT-353.

**Suggested fix (Phase 5):** delete the dead functions; where a docstring
documents a workflow, either wire the workflow (CLI command) or delete the
docstring with the function. Effort: S.

---

## PAT-601 — Quarantine unique-name loop races the rename (TOCTOU): concurrent quarantines can overwrite each other's evidence [S3, Confirmed]

**Location:** `hypelab/manifests.py:232-235` (`_quarantine`).

**Evidence:**
```python
qname = name
i = 0
while (qdir / qname).exists():
    i += 1
    qname = f"{name}.quarantined-{i}"
src.rename(qdir / qname)
```

**What's wrong:** classic check-then-act. Two workers quarantining the same
asset name concurrently can both pass the `exists()` check with the same
`qname`; the second `rename` then silently overwrites the first's quarantined
file (POSIX `rename` semantics) while `data["quarantined"].append(record)`
(`manifests.py:242`) records **both** — the manifest claims two quarantined
files, one exists on disk.

**Impact:** quarantine is the fail-closed evidence path for sha256 mismatches;
losing a quarantined file breaks the audit trail it exists to preserve. Window
requires concurrent quarantine of the same asset name — rare in the
single-operator design, hence S3 not S2.

**Already filed elsewhere (not duplicated here):** BUG-006 (`queue.claim` /
`fail()` races), DAT-355 (`jobs.transition()` check outside transaction).

**Suggested fix (Phase 5):** make the name unique without a check — e.g.
`qname = f"{name}.quarantined-{secrets.token_hex(4)}"` (collision-resistant,
no TOCTOU), or catch the race with `os.link`/`O_EXCL` semantics. Effort: XS.

---

## PAT-602 — Unbounded reads: RSS fetch has no size cap; yt-dlp download has no --max-filesize [S3, Confirmed]

**Location:** `hypelab/watcher.py:71-72` (`_rss_items`); `hypelab/ingest.py:133-143`
(`ytdlp_download`).

**Evidence:**
```python
# watcher.py:71-72
with urllib.request.urlopen(url, timeout=30) as r:
    data = r.read()          # no size cap; limit=20 caps parsed ITEMS, not bytes
```
```python
# ingest.py:136-146
cmd = [
    "yt-dlp", "-f", "bv*[height<=1080]+ba/b",
    "--merge-output-format", "mp4",
    "-o", str(out_path), url,   # no --max-filesize
]
```

**What's wrong:** (a) `_rss_items` reads an entire third-party feed into memory
with no byte cap — a compromised or malicious feed URL (operator-configured
sources point at third-party content) can exhaust RAM before the `limit=20`
item cap ever applies. (b) `ytdlp_download` caps resolution (1080p) and time
(7200 s) but not bytes — a long 1080p video is multi-GB straight onto disk
under `work/<job>/`, with no pre-check against available space.

**Impact:** reliability / local DoS. Operator-triggered, so S3 not S2; the
watcher path runs on a poll schedule, which makes (a) the more exposed of the
two.

**Already filed elsewhere (not duplicated here):** DOC-014 (`intake_asset`
has no size caps), STR-455 (`work/<job>/` grows unbounded, no quota/reaper),
DAT-364 (model auto-download, no size guard).

**Suggested fix (Phase 5):** `r.read(MAX_FEED_BYTES)` (e.g. 5 MiB) in
`_rss_items`; add `--max-filesize` (e.g. 4 G) to `ytdlp_download` and fail
closed with `IngestError`. Effort: XS.

---

## PAT-603 — `work_dir` docstring promises atomic-only writes; ingest and tray write JSON/txt directly [S3, Confirmed]

**Location:** docstring `hypelab/util.py:180-181`; violations at
`hypelab/ingest.py:286,307`, `hypelab/tray.py:165,167,170`.

**Evidence:**
```python
# util.py:180-181 (work_dir docstring)
- Job artifacts: work/<job_id>/ — atomic writes only (temp → fsync →
  rename; never a partial file at its final name).
```
```python
# ingest.py:286,307 — direct writes to final names under work/<job>/
(work / "source.words.json").write_text(...)
(work / "signals.json").write_text(...)
# tray.py:165,167,170 — direct writes under work/<job>/tray/<clip>/
(d / "caption.txt").write_text(...)
(d / "meta.json").write_text(...)
(d / "submit.url").write_text(...)
```

**What's wrong:** the write-domain contract — the load-bearing crash-safety
claim for job artifacts — is false at five sites. A crash (or SIGKILL)
mid-`write_text` leaves a partial file at its final name, exactly what the
docstring says cannot happen. The atomic helper exists and is unused here:
`util.write_json` (`util.py:209`: "tmp file + flush + fsync + os.replace").
Downstream readers (`score.py:374` reads `signals.json`) fail noisily on
truncated JSON, so the failure mode is a crash, not silent corruption — the
finding is S3 as docs-materially-mislead plus minor robustness, not data loss.

**Impact:** operators (and future code) relying on "never a partial file at
its final name" for crash recovery are relying on a property that does not
hold for `signals.json`, `source.words.json`, and the tray artifacts.

**Already filed elsewhere (not duplicated here):** BUG-007 (`fail()` re-queue
docstring), DAT-352/DAT-353 (cost/payout docstring gaps), DAT-364 (align.py
network-ONLY claim).

**Suggested fix (Phase 5):** route the five sites through `util.write_json`
(or the tmp+fsync+replace pattern); keep the docstring as the contract.
Effort: S.
