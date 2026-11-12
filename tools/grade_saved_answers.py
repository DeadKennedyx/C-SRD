#!/usr/bin/env python3
"""Replay previously inconclusive measured answers, without rerunning observers.

The prior experiment must have saved complete single-function verify reports,
input source snapshots and resource commands rooted at /work in this checkout.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from effort_resources import environment, save
from verify_circuit import check, digest
from verify_limbs import obligations


def bound_query(trial, section):
    path = trial / section / "proof.json"
    report = json.loads(path.read_text())
    if report.get("action") != "verify" or len(report["functions"]) != 1:
        raise ValueError("one function in a standalone verify report required")
    function = report["functions"][0]
    proof = function["proof"]
    text = proof["smtlib"]
    if digest_text(text) != proof["obligation_sha256"]:
        raise ValueError("saved SMT hash mismatch")
    commands = trial / section / "measurement" / "command.json"
    argv = json.loads(commands.read_text())["argv"]
    if argv[1] != "verify":
        raise ValueError("unexpected prior verification command")
    files = []
    for location, expected in zip(argv[2:4], (report["source_sha256"], report["candidate_sha256"])):
        old = Path(location)
        local = (ROOT / old.relative_to("/work")).resolve()
        if not local.is_relative_to(ROOT) or digest(local) != expected:
            raise ValueError("frozen C input mismatch")
        files.append({"path": str(local.relative_to(ROOT)), "sha256": expected})
    return {"grade_report": str(path.relative_to(ROOT)), "grade_report_sha256": digest(path),
            "command_sha256": digest(commands), "function": function["function"],
            "original_status": function["verification"], "model": report["model"],
            "target": report["target"], "source_solver": report["solver"],
            "files": files, "query_sha256": digest_text(text)}, text


def digest_text(text):
    return hashlib.sha256(text.encode()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-run", type=Path, required=True)
    parser.add_argument("--circuit-tool", type=Path, required=True)
    parser.add_argument("--abc", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prior, output = args.prior_run.resolve(), args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    (output / "queries").mkdir()
    cases = []
    for record in sorted(prior.glob("trial-*/trial.json")):
        trial = json.loads(record.read_text())
        if trial["warmup"] or trial["status"] != "inconclusive":
            continue
        for section in ("grade", "negative-control"):
            binding, text = bound_query(record.parent, section)
            if section == "grade" and binding["original_status"] != "inconclusive":
                raise ValueError("selected grade was not inconclusive")
            if section == "negative-control" and binding["original_status"] != "counterexample":
                raise ValueError("selected negative control was not refuted")
            name = record.parent.name + "-" + section
            query = output / "queries" / (name + ".smt2"); query.write_text(text)
            cases.append({"name": name, "profile": trial["profile"], "variant": trial["variant"],
                          "kind": "saved-answer" if section == "grade" else "negative-control",
                          "expected": None if section == "grade" else "sat",
                          "trial_sha256": digest(record), "binary_sha256": trial["binary_sha256"],
                          "binding": binding, "query": str(query)})
    if not cases:
        raise ValueError("no measured inconclusive answers found")
    for name, actual, expected, status in obligations():
        if name not in ("subtract", "scale-partial-products", "wrong-no-borrow"):
            continue
        text = "(set-logic QF_BV)\n" + "".join(f"(declare-const {v} (_ BitVec 32))\n" for v in ("x", "y", "k"))
        text += f"(assert (not (= {actual} {expected})))\n(check-sat)\n"
        query = output / "queries" / (name + ".smt2"); query.write_text(text)
        cases.append({"name": name, "kind": "rule-control", "expected": status,
                      "query_sha256": digest(query), "query": str(query)})
    protocol = {"schema_version": 1, "scope": "fixed saved answers; grader resources only; development corpus",
                "question": "Can checked Boolean lowering and ABC discharge the frozen whole-function mismatches?",
                "selection": "all measured grading-inconclusive trials; prior warmups excluded",
                "solver_seconds": 5, "stage_seconds": 8, "environment": environment(), "cases": cases,
                "sources": {str(p.relative_to(ROOT)): digest(p) for p in [
                    Path(__file__).resolve(), ROOT / "tools/query_circuit.cpp", ROOT / "tools/verify_circuit.py",
                    ROOT / "tools/effort_resources.py", ROOT / "tools/verify_limbs.py"]},
                "tools": {"circuit_sha256": digest(args.circuit_tool), "abc_sha256": digest(args.abc)}}
    save(output / "protocol.json", protocol)
    rows = []
    for case in cases:
        report = check(case["query"], args.circuit_tool, args.abc, output / case["name"], 5, 8)
        row = {"name": case["name"], "kind": case["kind"], "profile": case.get("profile"),
               "status": report["status"], "expected": case["expected"],
               "control_passed": None if case["expected"] is None else report["status"] == case["expected"],
               "query_sha256": report["query_sha256"], "total_wall_seconds": report["total_wall_seconds"],
               "child_cpu_seconds": report["child_cpu_seconds"],
               "stages": {k: {f: v.get(f) for f in ("status", "wall_seconds", "cpu_seconds", "peak_process_rss_bytes", "peak_sampled_tree_rss_bytes")}
                          for k, v in report["stages"].items()},
               "circuit_validation": report.get("circuit_validation"),
               "report": str((output / case["name"] / "report.json").relative_to(ROOT))}
        rows.append(row); save(output / "summary.json", rows)
        print(case["name"], report["status"], round(report["total_wall_seconds"], 3), flush=True)
    controls_passed = all(row["control_passed"] is not False for row in rows)
    save(output / "completion.json", {"status": "completed", "controls_passed": controls_passed,
                                      "results": len(rows), "historical_records_modified": False})
    return 0 if controls_passed else 3


if __name__ == "__main__":
    sys.exit(main())
