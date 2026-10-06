#!/usr/bin/env python3
"""Build review_state.json for checkup-hypemedia1-2026-09-29.

Runs on the Threadripper AFTER final checks are complete. Computes evidence
sha256 hashes from the actual files, binds coverage unit digests to the
current (fixed) source snapshot, and writes review_state.json.
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path("/home/dino/hypelab")
CU = ROOT / "devteam/checkups/checkup-hypemedia1-2026-09-29"


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def ev(*names):
    out = []
    for n in names:
        p = CU / "evidence" / n
        assert p.is_file() and p.stat().st_size > 0, f"missing evidence {n}"
        out.append({"path": f"devteam/checkups/checkup-hypemedia1-2026-09-29/evidence/{n}",
                    "sha256": sha256(p)})
    return out


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


# --- spec digest + current unit digests (fixed source) -----------------------
spec = json.loads((CU / "review_spec.json").read_text())
spec_digest = digest(spec)


def file_hash(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


files = {}
for sp in spec["source_paths"]:
    files[sp] = file_hash(ROOT / sp)
unit_digests = {}
for u in spec["review_units"]:
    sel = {p: h for p, h in files.items() if p in u["paths"]}
    assert sel, f"unit matches nothing: {u['id']}"
    unit_digests[u["id"]] = digest(sel)

# --- stages ------------------------------------------------------------------
E = {
    "S0": ev("s0-scope.md"),
    "S1": ev("s1-baseline.md", "repro-before.log"),
    "S2": ev("s2-architecture.md"),
    "S3": ev("s3-matrix.md"),
    "S4": ev("s4-findings.md"),
    "S5": ev("s5-fix.md", "repro-after.log"),
    "S6": ev("s6-verify.md"),
    "S7": ev("s7-diff-review.md"),
    "S8": ev("s8-verdict.md"),
}
SUMMARIES = {
    "S0": "scope frozen: change checkup, 2 units, 2 gate checks; initial snapshot on pre-fix source",
    "S1": "baseline receipts on broken source: new regression 5 failed/4 passed (defect demonstrated), full suite 315 passed/9 failed (baseline intact); before-state repro logged",
    "S2": "flow map: CLI source add -> watcher.add_source (intake gate) -> poll/list_new_items; kind validity decided once at intake",
    "S3": "12/12 unit/lens cells REVIEWED with source-bound observations; no NOT_APPLICABLE cells",
    "S4": "1 CONFIRMED_DEFECT (FIND-HYPE-MEDIA-1, the twitch intake gap); counter-checked against a twitch lister existing or poll surfacing the error — neither holds",
    "S5": "repair engineer: twitch dropped from CLI Choice and add_source whitelist with plain-language rejection; 9 regression tests added; related instances grep-verified consistent",
    "S6": "final checks on fixed source, both exit 0: new regression 9/9, full suite 324/324 (315 baseline + 9 new; T-044 1/1 intact)",
    "S7": "SELF_REVIEW diff challenge: cause removed at both enforcement points; tests proven fail-on-broken; no weakened assertions; no semantic drift",
    "S8": "gate PASS through S8; verdict ACCEPT; 0 outstanding findings; change left uncommitted per constraints",
}
stages = [{"id": f"S{i}", "status": "PASS", "summary": SUMMARIES[f"S{i}"],
           "evidence": E[f"S{i}"]} for i in range(9)]

# --- coverage ----------------------------------------------------------------
REASONS = {
    ("source-intake-validation", "COR"): "add_source kind whitelist now exactly {yt_channel, rss, manual}; unsupported kinds raise WatcherError naming the supported kinds; CLI Choice mirrors the same three; twitch unreachable in the URL-validation branch (grep-verified no other twitch refs)",
    ("source-intake-validation", "ARC"): "two enforcement points (CLI parse, add_source) share one policy; no new modules, no signature or schema changes",
    ("source-intake-validation", "TST"): "9 tests cover intake rejection (twitch, unknown kind, kind-before-URL ordering), supported-kind acceptance, poll-time fail-closed for legacy rows, CLI Choice rejection and --help content",
    ("source-intake-validation", "DOC"): "source add --help lists only supported kinds (test-pinned); remaining twitch mentions are historical devteam review notes, intentionally untouched as records",
    ("source-intake-validation", "SEC"): "intake is a fail-closed trust boundary (rights manifest + kind + allowlist); unlistable kinds rejected at intake removes the silent-dead path; no secrets handled here, no new attack surface",
    ("source-intake-validation", "API"): "add_source signature unchanged, still raises WatcherError on bad input; message text changed for unsupported kinds — grep confirms no test or caller matched the old text",
    ("source-intake-validation", "DAT"): "no schema or migration change; supported-kind rows insert exactly as before; twitch rows were never productive (poll always raised)",
    ("source-intake-validation", "REL"): "poll/claim/release/retry/heartbeat untouched; legacy twitch rows still fail closed at poll with 'unknown source kind' — loud, zero silent jobs",
    ("regression-tests", "COR"): "assertions pin the exact rejection message, CLI exit code 2, and --help content; fixtures follow test_allowlist.py conventions",
    ("regression-tests", "ARC"): "single new test file; CliRunner pattern copied from test_cli_die.py; no conftest changes",
    ("regression-tests", "TST"): "falsification demonstrated: 5/9 fail on pre-fix code (the 5 encoding the behavior change), 9/9 pass post-fix; the 4 passing on both pin invariants",
    ("regression-tests", "DOC"): "module docstring states the falsification contract and the chief's fail-closed decision",
}
coverage = []
for u in spec["review_units"]:
    for lens in u["lenses"]:
        coverage.append({
            "unit_id": u["id"], "lens": lens, "status": "REVIEWED",
            "reason": REASONS[(u["id"], lens)],
            "unit_digest": unit_digests[u["id"]],
            "evidence": ev("s3-matrix.md"),
        })

# --- receipts ----------------------------------------------------------------
receipts = []
for phase, cid in [("baseline", "check-new-regression"),
                   ("baseline", "check-full-suite"),
                   ("final", "check-new-regression"),
                   ("final", "check-full-suite")]:
    p = CU / "checks" / phase / f"{cid}.json"
    assert p.is_file(), f"missing receipt {phase}/{cid}"
    receipts.append({"path": f"devteam/checkups/checkup-hypemedia1-2026-09-29/checks/{phase}/{cid}.json",
                     "sha256": sha256(p)})

# --- findings ----------------------------------------------------------------
findings = [{
    "id": "FIND-HYPE-MEDIA-1",
    "claim": "twitch was advertised and accepted as a source kind at intake but no twitch lister exists; every poll raised WatcherError, swallowed by poll() as 'list failed', producing zero jobs silently",
    "classification": "CONFIRMED_DEFECT",
    "location": "hypelab/b2cli.py:157 (CLI Choice); hypelab/watcher.py:170 (add_source whitelist); hypelab/watcher.py:143-155 (list_new_items, no twitch branch)",
    "challenge": "would be disproved by a twitch branch in list_new_items or by poll() surfacing the error to the operator; grep found no twitch lister and the pre-fix repro confirmed intake-accept + poll-raise",
    "evidence": ev("s4-findings.md", "repro-before.log", "repro-after.log"),
    "resolution": "FIXED",
    "verification_checks": ["check-new-regression", "check-full-suite"],
    "queue_task_id": None,
    "remaining_reason": None,
}]

init_p = CU / "initial.json"
state = {
    "schema_version": "1.0",
    "review_id": spec["review_id"],
    "spec_digest": spec_digest,
    "initial_snapshot": {
        "path": "devteam/checkups/checkup-hypemedia1-2026-09-29/initial.json",
        "sha256": sha256(init_p),
    },
    "stages": stages,
    "coverage": coverage,
    "receipts": receipts,
    "findings": findings,
    "reviewer_mode": "SELF_REVIEW",
    "reviewer_identity": "Repair Engineer (role muse-repair-engineer), subagent session 0be94284-aaee-4f9a-a8b5-b1a9442dc88c, task HYPE-MEDIA-1; no independent reviewer available this cycle — challenge pass performed explicitly and recorded as SELF_REVIEW",
    "independent_review_evidence": [],
    "next_action": "Hand back to the parent orchestrator/chief: HYPE-MEDIA-1 FIXED, gate PASS S8, suite 324/324, change left UNCOMMITTED per constraints. HYPE-MEDIA-1.json was absent from the review tree; results recorded in repair-HYPE-MEDIA-1-report.md and done/HYPE-MEDIA-1.json instead.",
}
(CU / "review_state.json").write_text(json.dumps(state, indent=2) + "\n")
print("review_state.json written")
