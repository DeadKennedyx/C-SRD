#!/usr/bin/env python3
"""Grade every inconclusive measured wide-observer answer in a separate run.

Freeze exact saved SMT bytes and source bindings. Deduplicate identical queries,
retain every trial membership, and use one declared 30-second circuit budget.
Observer resources and historical grades remain immutable.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from effort_resources import environment, save
from verify_circuit import check, digest
from verify_limbs import obligations
from grade_saved_answers import bound_query, digest_text


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer-run", type=Path, required=True)
    parser.add_argument("--circuit-tool", type=Path, required=True)
    parser.add_argument("--abc", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prior, output = args.observer_run.resolve(), args.output_dir.resolve()
    complete = json.loads((prior / "completion.json").read_text())
    effort = json.loads((prior / "effort/effort.json").read_text())
    if complete["status"] != "completed" or effort["status"] != "completed":
        raise ValueError("complete frozen observer run required")
    selected = [t for t in effort["trials"] if not t["warmup"] and t["status"] == "inconclusive"]
    output.mkdir(parents=True, exist_ok=False)
    (output / "queries").mkdir()
    paths = [prior / f for f in ("completion.json", "protocol.json", "effort/effort.json")]
    paths += [Path(__file__).resolve(), ROOT / "experiments/grade_saved_answers.py",
              ROOT / "tools/verify_circuit.py", ROOT / "tools/query_circuit.cpp",
              ROOT / "tools/effort_resources.py", ROOT / "tools/verify_limbs.py",
              args.circuit_tool.resolve(), args.abc.resolve()]
    bindings = {str(p): digest(p) for p in paths}
    grouped = {}

    def add(text, kind, expected, member):
        value = digest_text(text)
        if value not in grouped:
            query = output / "queries" / (value + ".smt2")
            query.write_text(text)
            grouped[value] = {"query_sha256": value, "query": str(query), "kind": kind,
                              "expected": expected, "members": []}
        group = grouped[value]
        if (group["kind"], group["expected"]) != (kind, expected):
            raise ValueError("query reused with contradictory roles")
        group["members"].append(member)

    for trial in selected:
        directory = ROOT / Path(trial["directory"]).relative_to("/work")
        record = directory / "trial.json"
        if json.loads(record.read_text()) != trial:
            raise ValueError("trial differs from completed effort report")
        bindings[str(record)] = digest(record)
        for section, kind, expected in (("grade", "saved-answer", None), ("negative-control", "negative-control", "sat")):
            binding, text = bound_query(directory, section)
            if binding["original_status"] != ("inconclusive" if section == "grade" else "counterexample"):
                raise ValueError("unexpected prior grade/control status")
            for path in (ROOT / binding["grade_report"], directory / section / "measurement/command.json"):
                bindings[str(path)] = digest(path)
            for item in binding["files"]:
                bindings[str(ROOT / item["path"])] = item["sha256"]
            add(text, kind, expected, {"trial": trial["id"], "case": trial["case"], "profile": trial["profile"],
                "variant": trial["variant"], "binary_sha256": trial["binary_sha256"],
                "candidate_sha256": trial["candidate_sha256"], "trial_sha256": digest(record), "binding": binding})
    for name, actual, expected, status in obligations():
        if name not in ("subtract", "scale-partial-products", "wrong-no-borrow"):
            continue
        text = "(set-logic QF_BV)\n" + "".join(f"(declare-const {v} (_ BitVec 32))\n" for v in ("x", "y", "k"))
        text += f"(assert (not (= {actual} {expected})))\n(check-sat)\n"
        add(text, "rule-control", status, {"name": name})
    protocol = {"schema_version": 1, "status": "declared-before-results", "environment": environment(),
                "selection": "all inconclusive measured trials; warmups excluded; exact query SHA256 deduplication",
                "selected_trials": [t["id"] for t in selected], "solver_seconds": 30, "stage_seconds": 35,
                "scope": "grading only; shared query results are not independent repeated measurements",
                "queries": list(grouped.values()), "bindings": bindings,
                "tools": {"circuit_sha256": digest(args.circuit_tool), "abc_sha256": digest(args.abc)}}
    save(output / "protocol.json", protocol)
    rows = []
    for i, group in enumerate(grouped.values()):
        folder = output / f"query-{i}"
        report = check(group["query"], args.circuit_tool, args.abc, folder, 30, 35)
        row = {"query_sha256": group["query_sha256"], "kind": group["kind"], "expected": group["expected"],
               "status": report["status"], "report": str(folder / "report.json"), "report_sha256": digest(folder / "report.json"),
               "total_wall_seconds": report["total_wall_seconds"], "child_cpu_seconds": report["child_cpu_seconds"],
               "control_passed": None if group["expected"] is None else report["status"] == group["expected"]}
        rows.append(row); save(output / "summary.json", rows)
        print(group["kind"], group["query_sha256"][:10], report["status"], round(report["total_wall_seconds"], 3), flush=True)
        if row["control_passed"] is False:
            raise ValueError("grading control failed; no grade promotion permitted")
    if any(digest(path) != expected for path, expected in bindings.items()):
        raise ValueError("frozen grading input changed")
    save(output / "completion.json", {"status": "completed", "controls_passed": True, "historical_records_modified": False,
         "unresolved_query_sha256": [r["query_sha256"] for r in rows if r["kind"] == "saved-answer" and r["status"] == "inconclusive"]})
    return 0


if __name__ == "__main__":
    sys.exit(main())
