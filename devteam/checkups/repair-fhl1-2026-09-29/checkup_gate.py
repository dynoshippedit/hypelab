#!/usr/bin/env python3
"""Evidence/coverage gate for the companion checkup. Python 3.10+, stdlib only.

This checks records, hashes, and real command receipts. It cannot establish
semantic truth or prevent a writer from forging records; the controller must
own the spec, runner, receipts, and stage transitions. See CONTROLLER.md.
"""
from __future__ import annotations
import argparse
import fnmatch
import hashlib
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from datetime import datetime, timezone

STAGES = [f"S{i}" for i in range(9)]
CORE_LENSES = {"COR", "ARC", "TST", "DOC"}
LENSES = CORE_LENSES | {"SEC", "DAT", "API", "REL", "PRF", "UIX", "BLD", "DOM"}

def require(condition, message):
    if not condition:
        raise ValueError(message)

def nonblank(value):
    return isinstance(value, str) and bool(value.strip())

def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()

def file_hash(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)

def within(root, value):
    path = Path(value)
    path = (root / path).resolve() if not path.is_absolute() else path.resolve()
    require(path.is_relative_to(root), f"Path is outside project root: {value}")
    return path

def matches(path, pattern):
    pattern = pattern.rstrip("/")
    return pattern == "." or path == pattern or path.startswith(pattern + "/") or fnmatch.fnmatchcase(path, pattern)

def load_spec(path):
    spec = read(path)
    require(spec.get("schema_version") == "1.0", "Unsupported specification version")
    require(isinstance(spec.get("review_id"), str) and spec["review_id"].strip(), "Missing review_id")
    raw_root = spec.get("project_root")
    require(isinstance(raw_root, str) and Path(raw_root).is_absolute(), "Resolve the absolute project_root first")
    root = Path(raw_root).resolve()
    require(root.is_dir(), "Project root does not exist")
    require(spec.get("source_paths"), "source_paths cannot be empty")
    for exclusion in spec.get("exclusions", []):
        require(exclusion.get("pattern") and exclusion.get("reason"), "Every exclusion needs a pattern and reason")
    units = spec.get("review_units", [])
    require(units and len({u["id"] for u in units}) == len(units), "Missing or duplicate review units")
    for unit in units:
        require(isinstance(unit.get("id"), str) and unit["id"].strip(), "Review unit needs a nonempty ID")
        require(unit.get("paths") and unit.get("lenses"), f"Unit {unit['id']} needs paths and lenses")
        require(len(set(unit["lenses"])) == len(unit["lenses"]), "Duplicate unit lens")
        require(CORE_LENSES.issubset(unit["lenses"]) and set(unit["lenses"]).issubset(LENSES), "Each unit needs COR, ARC, TST, DOC and only recognized lens IDs")
    checks = spec.get("checks", [])
    require(checks and len({c["id"] for c in checks}) == len(checks), "Missing or duplicate checks")
    for check in checks:
        require(isinstance(check.get("id"), str) and check["id"].strip(), "Check needs a nonempty ID")
        require(isinstance(check.get("argv"), list) and check["argv"] and all(isinstance(a, str) for a in check["argv"]), "Check argv must be a nonempty string array")
        require(check["argv"][0], "Empty executable")
        require(isinstance(check.get("timeout_seconds"), (int, float)) and check["timeout_seconds"] > 0, "Each check needs a positive timeout")
        require(check.get("purpose"), "Every check needs a behavioral purpose")
        require(type(check.get("baseline_required")) is bool and type(check.get("final_required")) is bool, "Check requirements must be booleans")
        require(within(root, check.get("cwd", ".")).is_dir(), "Check working directory does not exist")
    require(any(c["baseline_required"] for c in checks), "At least one baseline check is required")
    require(any(c["final_required"] for c in checks), "At least one final acceptance check is required")
    return spec, root

def snapshot(spec, root):
    files = {}
    exclusions = [e["pattern"] for e in spec.get("exclusions", [])]
    def collect(path):
        rel = path.relative_to(root).as_posix()
        if any(matches(rel, pattern) for pattern in exclusions):
            return
        require(path.resolve().is_relative_to(root), f"Source resolves outside project root: {rel}")
        require(not path.is_symlink(), f"Resolve or explicitly exclude symbolic link: {rel}")
        if path.is_dir():
            for child in sorted(path.iterdir()):
                collect(child)
        elif path.is_file():
            files[rel] = file_hash(path)
    for selected in spec["source_paths"]:
        path = root / selected
        require(not Path(selected).is_absolute() and ".." not in Path(selected).parts, "source_paths must stay relative to root")
        require(path.exists(), f"Selected source path missing: {selected}")
        collect(path)
    require(files, "Selected source set is empty")
    unit_digests = {}
    covered = set()
    for unit in spec["review_units"]:
        selected = {p: h for p, h in files.items() if any(matches(p, pattern) for pattern in unit["paths"])}
        require(selected, f"Review unit matches no source files: {unit['id']}")
        covered.update(selected)
        unit_digests[unit["id"]] = digest(selected)
    require(covered == set(files), "Source files missing from review units: " + ", ".join(sorted(set(files) - covered)))
    return {"review_id": spec["review_id"], "spec_digest": digest(spec), "source_digest": digest(files), "files": files, "unit_digests": unit_digests}

def evidence(entry, root):
    require(isinstance(entry, dict) and entry.get("path") and entry.get("sha256"), "Evidence needs path and sha256")
    path = within(root, entry["path"])
    require(path.is_file() and path.stat().st_size > 0, f"Evidence artifact missing or empty: {entry['path']}")
    require(file_hash(path) == entry["sha256"], f"Evidence changed: {entry['path']}")

def evidence_list(entries, root):
    require(isinstance(entries, list) and entries, "An evidence list cannot be empty")
    for entry in entries:
        evidence(entry, root)

def run_check(spec_path, check_id, phase, output):
    spec, root = load_spec(spec_path)
    checks = {c["id"]: c for c in spec["checks"]}
    require(check_id in checks, f"Unknown check: {check_id}")
    check = checks[check_id]
    output = within(root, output)
    require(not output.exists(), "Use a new receipt path for every attempt")
    output.parent.mkdir(parents=True, exist_ok=True)
    log = output.with_suffix(output.suffix + ".log")
    require(not log.exists(), "Use a new log path for every attempt")
    before = snapshot(spec, root)
    started = datetime.now(timezone.utc).isoformat()
    timed_out, exit_code = False, None
    with log.open("wb") as stream:
        stream.write(("CHECK " + check_id + "\n").encode())
        stream.flush()
        try:
            proc = subprocess.Popen(check["argv"], cwd=within(root, check.get("cwd", ".")), stdout=stream, stderr=subprocess.STDOUT, start_new_session=(os.name == "posix"))
            try:
                exit_code = proc.wait(timeout=check["timeout_seconds"])
            except subprocess.TimeoutExpired:
                timed_out = True
                if os.name == "posix":
                    os.killpg(proc.pid, signal.SIGKILL)
                else:
                    proc.kill()
                exit_code = proc.wait()
        except OSError as error:
            stream.write(("LAUNCH ERROR: " + str(error) + "\n").encode())
    after = snapshot(spec, root)
    result = {"review_id": spec["review_id"], "spec_digest": digest(spec), "check_id": check_id, "phase": phase, "argv": check["argv"], "cwd": str(within(root, check.get("cwd", "."))), "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(), "source_before": before["source_digest"], "source_after": after["source_digest"], "exit_code": exit_code, "timed_out": timed_out, "log": {"path": log.relative_to(root).as_posix(), "sha256": file_hash(log)}}
    write(output, result)
    return 0 if exit_code == 0 and not timed_out and result["source_before"] == result["source_after"] else 1

def validate(spec_path, state_path, through="S8"):
    spec, root = load_spec(spec_path)
    current = snapshot(spec, root)
    state = read(state_path)
    require(state.get("review_id") == spec["review_id"], "Review ID mismatch")
    require(state.get("spec_digest") == digest(spec), "Specification changed or was not frozen")
    upto = STAGES.index(through)
    stages = state.get("stages", [])
    require([s.get("id") for s in stages] == STAGES, "Stages must include S0–S8 in order, exactly once")
    for stage in stages[:upto+1]:
        require(stage.get("status") == "PASS", f"Stage incomplete: {stage['id']}")
        require(nonblank(stage.get("summary")), f"Stage summary missing: {stage['id']}")
        evidence_list(stage.get("evidence"), root)
    initial_ref = state.get("initial_snapshot")
    evidence(initial_ref, root)
    initial = read(within(root, initial_ref["path"]))
    require(initial.get("review_id") == spec["review_id"] and initial.get("spec_digest") == digest(spec), "Initial snapshot mismatch")
    require(initial.get("files") and digest(initial["files"]) == initial.get("source_digest"), "Invalid initial source digest")
    if upto >= 3:
        cells = state.get("coverage", [])
        expected = {(u["id"], lens) for u in spec["review_units"] for lens in u["lenses"]}
        actual = [(c.get("unit_id"), c.get("lens")) for c in cells]
        require(len(set(actual)) == len(actual) and set(actual) == expected, "Coverage cells are missing, extra, or duplicated")
        for cell in cells:
            require(cell.get("status") in ("REVIEWED", "NOT_APPLICABLE"), "Unfinished coverage cell")
            require(nonblank(cell.get("reason")), "Coverage requires a substantive observation or applicability reason")
            require(cell.get("unit_digest") == current["unit_digests"][cell["unit_id"]], "Coverage is stale for changed source")
            evidence_list(cell.get("evidence"), root)
    checked = {"baseline": {}, "final": {}}
    if upto >= 1:
        definitions = {c["id"]: c for c in spec["checks"]}
        for ref in state.get("receipts", []):
            evidence(ref, root)
            receipt = read(within(root, ref["path"]))
            phase, check_id = receipt.get("phase"), receipt.get("check_id")
            require(phase in checked and check_id in definitions, "Unknown receipt check or phase")
            require(check_id not in checked[phase], "List only the selected current receipt for each check/phase")
            definition = definitions[check_id]
            require(receipt.get("review_id") == spec["review_id"] and receipt.get("spec_digest") == digest(spec), "Receipt belongs to another review/specification")
            require(receipt.get("argv") == definition["argv"] and receipt.get("cwd") == str(within(root, definition.get("cwd", "."))), "Receipt command differs from frozen check")
            evidence(receipt.get("log"), root)
            require(receipt.get("started_at") and receipt.get("finished_at"), "Missing execution timestamps")
            target = initial["source_digest"] if phase == "baseline" else current["source_digest"]
            require(receipt.get("source_before") == target and receipt.get("source_after") == target, "Receipt is stale or check changed source")
            checked[phase][check_id] = receipt
        for check in spec["checks"]:
            if check["baseline_required"]:
                require(check["id"] in checked["baseline"], f"Missing baseline command receipt: {check['id']}")
            if upto >= 6 and check["final_required"]:
                receipt = checked["final"].get(check["id"])
                require(receipt is not None, f"Missing final command receipt: {check['id']}")
                require(type(receipt.get("exit_code")) is int and receipt["exit_code"] == 0 and receipt.get("timed_out") is False, f"Final check did not pass: {check['id']}")
    findings = state.get("findings", [])
    if upto >= 4:
        require(isinstance(findings, list) and len({f['id'] for f in findings}) == len(findings), "Duplicate or invalid findings")
        for finding in findings:
            require(finding.get("classification") in ("CONFIRMED_DEFECT", "SUPPORTED_IMPROVEMENT", "HYPOTHESIS", "REJECTED_LEAD"), "Invalid finding classification")
            require(finding.get("claim") and finding.get("challenge") and finding.get("location"), "Finding needs claim, source location, and counter-check")
            evidence_list(finding.get("evidence"), root)
            if upto >= 7:
                resolution = finding.get("resolution")
                require(resolution in ("FIXED", "QUEUED", "REJECTED"), "Finding has no disposition")
                if resolution == "FIXED":
                    require(finding["classification"] in ("CONFIRMED_DEFECT", "SUPPORTED_IMPROVEMENT"), "A hypothesis cannot be marked fixed")
                    require(finding.get("verification_checks"), "Fixed finding lacks verification checks")
                    for check_id in finding["verification_checks"]:
                        receipt = checked["final"].get(check_id)
                        require(receipt is not None and type(receipt.get("exit_code")) is int and receipt["exit_code"] == 0 and receipt.get("timed_out") is False, "Fixed finding lacks a passing final check")
                if resolution == "QUEUED":
                    require(finding.get("queue_task_id") and finding.get("remaining_reason"), "Queued finding requires task ID and reason")
                if resolution == "REJECTED":
                    require(finding["classification"] == "REJECTED_LEAD", "Rejected disposition needs an explicitly rejected classification")
    if upto >= 8:
        require(state.get("reviewer_mode") in ("SELF_REVIEW", "INDEPENDENT_REVIEW"), "Declare actual reviewer mode")
        require(nonblank(state.get("reviewer_identity")), "Record the actual reviewer identity or session")
        if state["reviewer_mode"] == "INDEPENDENT_REVIEW":
            evidence_list(state.get("independent_review_evidence"), root)
        require(nonblank(state.get("next_action")), "Missing handback/next action")
    outstanding = sum(f.get("resolution") == "QUEUED" for f in findings)
    return {"gate": "PASS" if upto == 8 else f"PASS_THROUGH_{through}", "review_id": spec["review_id"], "through": through, "outstanding_findings": outstanding, "source_digest": current["source_digest"], "meaning": "Record and evidence checks passed; semantic review and controller ownership remain required."}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    snap = sub.add_parser("snapshot")
    snap.add_argument("--spec", required=True)
    snap.add_argument("--out", required=True)
    run = sub.add_parser("run-check")
    run.add_argument("--spec", required=True)
    run.add_argument("--check", required=True)
    run.add_argument("--phase", choices=("baseline", "final"), required=True)
    run.add_argument("--out", required=True)
    gate = sub.add_parser("validate")
    gate.add_argument("--spec", required=True)
    gate.add_argument("--state", required=True)
    gate.add_argument("--through", choices=STAGES, default="S8")
    args = parser.parse_args()
    try:
        if args.operation == "snapshot":
            spec, root = load_spec(args.spec)
            output = within(root, args.out)
            require(not output.exists(), "Use a new snapshot path")
            write(output, snapshot(spec, root))
            return 0
        if args.operation == "run-check":
            return run_check(args.spec, args.check, args.phase, args.out)
        print(json.dumps(validate(args.spec, args.state, args.through)))
        return 0
    except (ValueError, KeyError, TypeError, OSError) as error:
        print(json.dumps({"gate": "FAIL", "error": str(error)}))
        return 1

if __name__ == "__main__":
    sys.exit(main())
