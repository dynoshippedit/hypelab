# SEC findings — HypeLab security review (2026-09-29)

Branch `devteam/review-2026-09-29`. Severities use the B7 scale (S1 critical
→ S5 info). Every finding below has quoted `path:line` evidence, a concrete
impact, and a confidence. The system has no authentication by design (see
`devteam/notes/security/threat-model.md`); findings are calibrated to the
single-user local-CLI trust model, not to a web-service threat model.

## SEC-100 — S3 — Consent expiry accepts non-timestamp strings that never expire

**Evidence.** `hypelab/consent.py:74-77`:
```python
if not expires_at:
    raise ConsentError(
        "consent refused: expiry is mandatory — a grant without an "
        "expiry is not recordable"
    )
```
The *presence* of an expiry is enforced; its *format* is not. The gate then
compares lexically — `hypelab/consent.py:169-175`:
```python
row = conn.execute(
    """SELECT * FROM consents
       WHERE job_id=? AND handle=? AND platform=?
         AND decision='granted' AND revoked_at IS NULL
         AND expiry IS NOT NULL AND expiry > ?
         AND artifact_hash IS NOT NULL
       ORDER BY responded_at DESC LIMIT 1""",
    (job_id, handle, platform, now()),
).fetchone()
```
`now()` is an ISO-8601 string, so `expiry > ?` is a *string* comparison.
`--expires "never"` (or `"tbd"`, or any string sorting above `"2"`) passes
the gate forever.

**Impact.** Mandatory expiry is the crown-jewel business rule of the consent
ledger, and the docstring claims fail-closed behavior ("Fail closed on
missing expiry"). A malformed expiry silently converts a time-boxed grant
into a permanent one — the exact failure the rule exists to prevent. The
ledger is designed as dispute evidence, where a "valid" row with a nonsense
expiry undermines the whole artifact.

**Confidence:** high (read the code; comparison semantics confirmed).

**Fix:** validate ISO-8601 at `grant()` time and reject anything that does
not parse.

## SEC-101 — S4 — Pitch↔grant scope "word for word" correspondence is documented but unenforced

**Evidence.** `hypelab/consent.py:70-71`:
```python
- the pitch and the grant must match word for word: `scope` doubles
  as the pitch's stated scope.
```
`hypelab/pitch.py:11`: "The scope, verbatim — it doubles as consents.scope,
so the pitch and the grant must match word for word." The pitch scope is a
hardcoded string — `hypelab/pitch.py:115`:
```python
scope = "one Instagram collab post, your handle as co-author, 30-day window"
```
`consent.grant()` requires `scope` to be non-empty
(`hypelab/consent.py:78-79`) but **no code anywhere compares the grant's
scope against the pitch's scope text**.

**Impact.** The "verbatim agreement" evidence property the docs promise does
not hold: a consent row can be granted against a scope that never appeared in
any pitch. In the single-user model the operator is the one typing both, so
this is a documentation-vs-enforcement gap rather than an exploitable hole —
but the ledger's value as dispute defense rests on the correspondence the
docs claim.

**Confidence:** high (searched all scope references; no comparison exists).

**Fix:** at `grant()` time, compare against the latest pitch attempt's scope
for the (job, handle), or downgrade the docstrings to describe scope as
operator-attested.

## SEC-102 — S4 — Authorizations never expire and cannot be revoked

**Evidence.** `hypelab/authorize.py:53-55`:
```python
conn.execute(
    """INSERT INTO authorizations(job_id, action, actor, ...)
       VALUES(?,?,?,...)
       ON CONFLICT(job_id, action, actor)
       DO UPDATE SET intent=..., platform=..., note=...""",
```
Latest-wins upsert, no expiry column, no revocation path.
`hypelab/authorize.py:65-73` (`require_authorization`): checks only that the
latest `(job_id, action, actor)` row exists — `platform`, `intent`, and `note`
are recorded but never compared against the later request, so a stale
authorization covers different media, caption, platform, or schedule for the
same job.

**Impact.** An approval recorded once authorizes the action indefinitely;
there is no way to withdraw it. Publish is partially mitigated because
consent is re-checked at publish time (flow 4, step 4), but `pitch` and
`invite` approvals are permanent, and a `publish` authorization outlives any
change to what is being published.

**Confidence:** high.

**Fix:** add `expires_at` to authorizations (default 30 days), a
`revoke` op, and bind `platform`/`intent` at check time for publish.

## SEC-103 — S4 — Source URL handling is SSRF-shaped (operator-bounded)

**Evidence.** `hypelab/watcher.py:163-188` (`add_source`): validates `kind`
and the rights manifest, but performs **no URL validation** — no scheme,
host, or private-address check. The stored URL flows to
`hypelab/watcher.py:71`:
```python
with urllib.request.urlopen(url, timeout=30) as r:
    data = r.read()
```
and to yt-dlp argv (`hypelab/watcher.py:43`). The campaign
`source_allowlist` is a lowercase *substring* test on **item** URLs only —
`hypelab/watcher.py:138-146`:
```python
u = (url or "").lower()
return any(a.lower() in u for a in allow if a)
```
— never parsed as a host, never applied to the source feed URL itself.

**Impact.** Calibrated to the trust model: only the operator can register a
source, so the reachable harm is the operator's own machine requesting
attacker-influenced URLs (internal/private targets, `file://` URLs read into
the pipeline). Not remotely triggerable in this build. Defense-in-depth fix:
validate `http(s)` scheme at `add_source`, parse-and-compare hosts against
the allowlist, and apply the allowlist to the feed URL too.

**Confidence:** high.

## SEC-104 — S3 — Consent ledger CSV export is formula-injection prone

**Evidence.** `hypelab/consent.py:257-280` (`export_ledger`): every consent
row is written through `csv.writer` with **no neutralization** of cells
beginning `=`, `+`, `-`, `@`. User-controlled fields in the export include
`handle`, `actor`, `scope`, `artifact_path`, and `revocation_note`.

**Impact.** The docstring describes the export as "the deliverable in a
vendor security review — or a dispute defense": it is *designed* to be opened
by third parties in spreadsheet software, where a crafted `scope` or `note`
cell executes as a formula on open. Classic CSV injection; the fix is a
leading-`'` or tab prefix on formula-shaped cells.

**Confidence:** high.

## SEC-105 — S4 — Kit-controlled values interpolated unescaped into carousel CSS

**Evidence.** `hypelab/carousel.py:79-88` (`kit_to_css`):
```python
fill = caps.get("fill", "#FFFFFF")
accent = caps.get("highlight", "#39FF88")
font = caps.get("font", "DejaVu Sans")
return f"""
:root {{ --fill: {fill}; --accent: {accent}; }}
...
font-family: "{font}", sans-serif; }}
```
Slide *text* is HTML-escaped (`hypelab/carousel.py:112-113`), but the CSS
values are not validated or escaped — a crafted kit (`font` containing `"`
breaks out of the quoted `font-family`; `fill`/`accent` break the `:root`
block). Kits can be imported from JSON, and the resulting HTML is rendered
by headless Chromium (`_measure_slide`, `_screenshot`).

**Impact.** Stored-CSS/script injection into a generated HTML artifact. The
artifact is local and opened by the operator, so this is a hardening note,
not an active hole — but any future path that shares carousels or renders
kits from untrusted sources inherits it.

**Confidence:** high.

**Fix:** validate colors against `^#[0-9a-fA-F]{6}$` and fonts against an
allowlist at kit import.

## SEC-106 — S4 — Raw filtergraph interpolation of `enable` and reframe `split` boxes

**Evidence.** `hypelab/render.py:266`:
```python
enable_s = f":enable='{enable}'" if enable else ""
```
`enable` comes straight from the EDL overlay dict with no escaping (overlay
*text* is properly escaped at `hypelab/render.py:235-237`; the expression is
not). `hypelab/reframe.py:387-395` interpolates `plan["boxes"]` values raw
into `crop=w:h:x:y`; box values are `int()`-coerced when produced by
`two_speaker_boxes()`, but a hand-edited EDL plan bypasses that.

**Impact.** In the current trust model only the operator authors EDLs, so the
practical effect is a broken render (fail-noisy via ffmpeg) rather than
exploitation. Filed as defense-in-depth: these are the only two unescaped
sinks in an otherwise carefully escaped filtergraph pipeline, and they should
be allowlisted/validated before any EDL ever arrives from a less-trusted
producer.

**Confidence:** high.

---

## Negative results (verified, no finding)

- **No shell injection surface:** zero `shell=True`, zero `os.system`, all
  subprocess calls use argv arrays (swept all 40 modules).
- **No deserialization risk:** no pickle/YAML loading anywhere.
- **SQL injection:** all queries parameterized; one dynamic clause appends a
  fixed string only.
- **Path traversal:** `intake_asset`/`attach_asset` reject traversal in
  destination names; intake is atomic + hashed + ffprobe-probed.
- **ASS caption injection:** caption words escape braces
  (`hypelab/captions.py:103`), neutralizing ASS override blocks.
- **Overlay text:** newline-normalized + single-quote-escaped
  (`hypelab/render.py:235-237`) — adequate for ffmpeg quoted values.
- **Live publishing:** structurally impossible in this build (four
  independent refusals; see `devteam/notes/flows/flow4-sec.md`).
- **Web threat classes** (CSRF, CORS, JWT, cookies, IDOR/BOLA): no web
  server, no tokens, no multi-tenancy — considered, not applicable.
