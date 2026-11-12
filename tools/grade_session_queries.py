#!/usr/bin/env python3
"""Replay every unknown session-answer grade, without remeasuring the observer."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tools"))
from effort_resources import environment, save
from session_evidence import checked, local
from verify_circuit import check, digest
from verify_limbs import obligations
from grade_saved_answers import bound_query, digest_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--grades", type=Path, required=True)
    parser.add_argument("--circuit-tool", type=Path, required=True)
    parser.add_argument("--abc", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prior, output = args.grades.resolve(), args.output_dir.resolve()
    completion = json.loads((prior/"completion.json").read_text())
    if completion["status"] != "completed" or not completion["controls_passed"]:
        raise ValueError("complete source grading and passing negative controls required")
    grades = json.loads((prior/"summary.json").read_text())
    selected = [row for row in grades if row["status"] == "inconclusive"]
    if sorted(r["id"] for r in selected) != sorted(completion["inconclusive"]):
        raise ValueError("selected unknown grades do not match completion record")
    output.mkdir(parents=True, exist_ok=False); (output/"queries").mkdir()
    paths = [prior/name for name in ("protocol.json", "summary.json", "completion.json")]
    paths += [Path(__file__).resolve(), ROOT/"tools/grade_saved_answers.py",
              ROOT/"tools/session_evidence.py", ROOT/"tools/verify_circuit.py", ROOT/"tools/verify_limbs.py",
              ROOT/"tools/query_circuit.cpp", ROOT/"tools/effort_resources.py",
              args.circuit_tool.resolve(), args.abc.resolve()]
    bindings = {str(p): digest(p) for p in paths}
    grouped = {}

    def add(text, kind, expected, member):
        sha = digest_text(text)
        if sha not in grouped:
            path = output/"queries"/(sha+".smt2"); path.write_text(text)
            grouped[sha] = {"query": str(path), "query_sha256": sha, "kind": kind,
                            "expected": expected, "members": []}
        group = grouped[sha]
        if (group["kind"], group["expected"]) != (kind, expected):
            raise ValueError("contradictory query roles")
        group["members"].append(member)

    for row in selected:
        directory = local(row["directory"])
        record = directory/"answer.json"
        if json.loads(record.read_text()) != row:
            raise ValueError("answer differs from completed source-grade report")
        bindings[str(record)] = digest(record)
        for section, kind, expected in (("grade", "saved-answer", None), ("negative-control", "negative-control", "sat")):
            checked(directory/section/"proof.json", row["grade_sha256" if section == "grade" else "negative_sha256"])
            binding, text = bound_query(directory, section)
            if binding["original_status"] != ("inconclusive" if section == "grade" else "counterexample"):
                raise ValueError("unexpected original proof status")
            for path in (ROOT/binding["grade_report"], directory/section/"measurement/command.json"):
                bindings[str(path)] = digest(path)
            for item in binding["files"]:
                bindings[str(ROOT/item["path"])] = item["sha256"]
            add(text, kind, expected, {"answer": row["id"], "candidate_sha256": row["candidate_sha256"],
                                       "reference_sha256": row["reference_sha256"], "binding": binding})
    for name, actual, expected, status in obligations():
        if name not in ("subtract", "scale-partial-products", "wrong-no-borrow"):
            continue
        text = "(set-logic QF_BV)\n"+"".join(f"(declare-const {v} (_ BitVec 32))\n" for v in ("x", "y", "k"))
        add(text+f"(assert (not (= {actual} {expected})))\n(check-sat)\n", "rule-control", status, {"name": name})
    protocol = {"status": "declared-before-results", "selection": "all unknown distinct session-answer grades, including initial requests",
                "selected_answers": [r["id"] for r in selected], "solver_seconds": 30, "stage_seconds": 35,
                "environment": environment(), "bindings": bindings, "queries": list(grouped.values()),
                "scope": "exact saved-query deduplication; grading cost only; shared results are not independent observations"}
    save(output/"protocol.json", protocol)
    rows = []
    for i, group in enumerate(grouped.values()):
        directory = output/f"query-{i:04d}"
        result = check(group["query"], args.circuit_tool, args.abc, directory, 30, 35)
        row = {"query_sha256": group["query_sha256"], "kind": group["kind"], "expected": group["expected"],
               "status": result["status"], "report": str(directory/"report.json"),
               "report_sha256": digest(directory/"report.json"), "total_wall_seconds": result["total_wall_seconds"],
               "child_cpu_seconds": result["child_cpu_seconds"],
               "control_passed": None if group["expected"] is None else result["status"] == group["expected"]}
        rows.append(row); save(output/"summary.json", rows)
        print(group["kind"], group["query_sha256"][:10], result["status"], flush=True)
        if row["control_passed"] is False:
            raise ValueError("query grading control failed; do not promote grades")
    for path, value in bindings.items(): checked(path, value)
    save(output/"completion.json", {"status": "completed", "controls_passed": True,
         "historical_records_modified": False,
         "unresolved_queries": [r["query_sha256"] for r in rows if r["kind"] == "saved-answer" and r["status"] == "inconclusive"]})


if __name__ == "__main__": main()
