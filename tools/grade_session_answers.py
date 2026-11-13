#!/usr/bin/env python3
"""Grade every distinct persistent-session answer after resource collection."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tools"))
from audit_protection import file_hash
from effort_resources import environment, save
from measure_effort import proof
from pcode_reconstruct import reconstruct
from session_evidence import checked, read_sessions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("run the frozen Linux source verifier in its original environment")
    report, matrix, _, groups = read_sessions(args.sessions)
    csrd = matrix["tools"]["csrd"]
    checked(csrd["path"], csrd["sha256"])
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=False)
    paths = [args.sessions.resolve(), Path(__file__).resolve(), ROOT/"tools/session_evidence.py",
             ROOT/"tools/measure_effort.py", ROOT/"tools/effort_resources.py", Path(csrd["path"])]
    bindings = {str(p): file_hash(p) for p in paths}
    protocol = {"status": "declared-before-results", "source_solver_ms": 10000,
                "selection": "all distinct (original C hash, answer C hash) pairs, including excluded initial requests",
                "scope": "grading only; source-model proof does not prove binary lifting; shared grades are not independent trials",
                "sessions": str(args.sessions.resolve()), "sessions_sha256": file_hash(args.sessions),
                "environment": environment(), "bindings": bindings, "groups": groups}
    save(output/"protocol.json", protocol)
    rows = []
    save(output/"summary.json",rows)
    for i, group in enumerate(groups):
        directory = output/f"answer-{i:04d}"; directory.mkdir()
        reference = checked(group["reference"], group["reference_sha256"])
        candidate = checked(group["candidate"], group["candidate_sha256"])
        export = json.loads(checked(group["export"], group["export_sha256"]).read_text())
        if reconstruct(export).encode() != candidate.read_bytes():
            raise ValueError("answer differs from frozen semantic adapter")
        mutant = directory/"mutant.c"; mutant.write_text(reconstruct(export, result_offset=1))
        grade = proof(csrd["path"], reference, candidate, directory/"grade", 10000)
        negative = proof(csrd["path"], candidate, mutant, directory/"negative-control", 10000)
        row = {"id": i, "directory": str(directory), **group, "status": grade["status"],
               "negative_control": negative["status"], "mutant_sha256": file_hash(mutant),
               "grade_sha256": file_hash(directory/"grade/proof.json"),
               "negative_sha256": file_hash(directory/"negative-control/proof.json")}
        for section in ("grade", "negative-control"):
            value = json.loads((directory/section/"proof.json").read_text())
            expected = ((group["reference_sha256"], group["candidate_sha256"]) if section == "grade"
                        else (group["candidate_sha256"], row["mutant_sha256"]))
            if (value["source_sha256"], value["candidate_sha256"]) != expected:
                raise ValueError("proof input hash mismatch")
        rows.append(row); save(directory/"answer.json", row); save(output/"summary.json", rows)
        print(i, len(groups), grade["status"], negative["status"], flush=True)
        if negative["status"] != "counterexample":
            raise ValueError("wrong-output control was not rejected")
    for path, value in bindings.items(): checked(path, value)
    for path, value in report["bindings"].items(): checked(path, value)
    save(output/"completion.json", {"status": "completed", "controls_passed": True, "answers": len(rows),
         "inconclusive": [r["id"] for r in rows if r["status"] == "inconclusive"],
         "wrong_answers": [r["id"] for r in rows if r["status"] == "counterexample"],
         "historical_records_modified": False})


if __name__ == "__main__": main()
