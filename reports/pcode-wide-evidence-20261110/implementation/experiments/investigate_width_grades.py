#!/usr/bin/env python3
"""Bounded grading-only follow-up for ALL unresolved positional-width queries.

Deduplicate exact SMT bytes, retaining all original trial bindings. Try 30 seconds
for each unknown query, then 120 only for those still unknown. Run the two bound
wrong-output queries and three generic arithmetic controls at each used budget.
No original answer, grade, observer, binary, or observer resource cost is changed.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from effort_resources import save
from verify_circuit import check, digest
from grade_saved_answers import bound_query


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-circuit", type=Path, required=True)
    parser.add_argument("--circuit-tool", type=Path, required=True)
    parser.add_argument("--abc", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prior, output = args.prior_circuit.resolve(), args.output_dir.resolve()
    previous = json.loads((prior / "protocol.json").read_text())
    results = json.loads((prior / "summary.json").read_text())
    done = json.loads((prior / "completion.json").read_text())
    if done["status"] != "completed" or done["controls_passed"] is not True:
        raise ValueError("completed controlled circuit replay required")
    output.mkdir(parents=True, exist_ok=False)
    (output / "queries").mkdir()
    cases = {c["name"]: c for c in previous["cases"]}
    grouped, bindings = {}, {}
    for path in [prior / f for f in ("protocol.json", "summary.json", "completion.json")]:
        bindings[str(path)] = digest(path)
    for name in ("experiments/investigate_width_grades.py", "experiments/grade_saved_answers.py", "tools/verify_circuit.py", "tools/query_circuit.cpp", "tools/effort_resources.py"):
        bindings[str(ROOT / name)] = digest(ROOT / name)

    def add(case, selected=None):
        query = Path(case["query"])
        expected_hash = case.get("query_sha256", case.get("binding", {}).get("query_sha256"))
        if digest(query) != expected_hash:
            raise ValueError("saved query hash mismatch")
        bindings[str(query)] = expected_hash
        if case["kind"] != "rule-control":
            section = "grade" if case["kind"] == "saved-answer" else "negative-control"
            grade = ROOT / case["binding"]["grade_report"]
            directory = grade.parent.parent
            binding, text = bound_query(directory, section)
            if binding != case["binding"] or text != query.read_text() or digest(directory / "trial.json") != case["trial_sha256"]:
                raise ValueError("saved-answer binding changed")
            for path in (grade, directory / "trial.json", directory / section / "measurement/command.json"):
                bindings[str(path)] = digest(path)
            for item in binding["files"]:
                bindings[str(ROOT / item["path"])] = item["sha256"]
        if expected_hash not in grouped:
            copied = output / "queries" / (expected_hash + ".smt2")
            copied.write_bytes(query.read_bytes())
            grouped[expected_hash] = {"query_sha256": expected_hash, "query": str(copied), "kind": case["kind"],
                                      "expected": case["expected"], "original_cases": [], "prior_unknown_reports": []}
        group = grouped[expected_hash]
        if (group["kind"], group["expected"]) != (case["kind"], case["expected"]):
            raise ValueError("query reused with contradictory role")
        group["original_cases"].append(case)
        if selected:
            report_path = ROOT / selected["report"]
            report = json.loads(report_path.read_text())
            if report["status"] != "inconclusive" or report["query_sha256"] != expected_hash:
                raise ValueError("selected grade is not bound and inconclusive")
            bindings[str(report_path)] = digest(report_path)
            group["prior_unknown_reports"].append(selected["report"])

    for row in results:
        if row["kind"] == "saved-answer" and row["status"] == "inconclusive":
            add(cases[row["name"]], row)
            add(cases[row["name"].replace("-grade", "-negative-control")])
    for case in cases.values():
        if case["kind"] == "rule-control":
            add(case)
    controls = [g for g in grouped.values() if g["expected"] is not None]
    pending = [g for g in grouped.values() if g["expected"] is None]
    if not pending or len(controls) < 3:
        raise ValueError("unknown queries and independent controls required")
    for tool in (args.circuit_tool.resolve(), args.abc.resolve()):
        bindings[str(tool)] = digest(tool)
    save(output / "protocol.json", {"status": "declared-before-results", "selection": "every unresolved measured query, deduplicated by exact SHA256",
         "budgets_seconds": [30, 120], "stage_extra_seconds": 5,
         "policy": "30s for all unknowns; 120s for remaining unknowns; controls at each used budget",
         "scope": "post hoc grader investigation; no observer effort or protection measurement",
         "queries": list(grouped.values()), "bindings": bindings})
    rows = []
    for budget in (30, 120):
        if not pending: break
        unresolved = []
        for index, group in enumerate([*controls, *pending]):
            folder = output / f"budget-{budget}-query-{index}"
            report = check(group["query"], args.circuit_tool, args.abc, folder, budget, budget+5)
            row = {"query_sha256": group["query_sha256"], "kind": group["kind"], "expected": group["expected"],
                   "budget_seconds": budget, "status": report["status"], "report": str(folder / "report.json"),
                   "report_sha256": digest(folder / "report.json"), "total_wall_seconds": report["total_wall_seconds"],
                   "child_cpu_seconds": report["child_cpu_seconds"], "control_passed": None if group["expected"] is None else group["expected"] == report["status"]}
            rows.append(row); save(output / "summary.json", rows)
            print(group["kind"], group["query_sha256"][:10], budget, report["status"], round(report["total_wall_seconds"], 3), flush=True)
            if row["control_passed"] is False:
                raise ValueError("grading control failed; no promotion permitted")
            if group["expected"] is None and report["status"] == "inconclusive":
                unresolved.append(group)
        pending = unresolved
    if any(digest(path) != value for path, value in bindings.items()):
        raise ValueError("frozen grading input changed")
    save(output / "completion.json", {"status": "completed", "unresolved_query_sha256": [g["query_sha256"] for g in pending],
         "controls_passed": True, "historical_records_modified": False})


if __name__ == "__main__":
    main()
