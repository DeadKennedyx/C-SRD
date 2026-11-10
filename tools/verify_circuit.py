#!/usr/bin/env python3
"""Check one saved SMT mismatch via validated Boolean export and optional ABC.

This replays a query; it does not parse C or certify a binary lifting. ABC is
optional, must be supplied explicitly, and is not used by the csrd transform gate.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import shutil
import sys
import time

from effort_resources import environment, measure, save


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def abc_status(resources, stdout, stderr):
    if resources["status"] != "completed" or resources.get("returncode") != 0 or stderr.strip():
        return "inconclusive"
    positive = re.findall(r"^Networks are equivalent\.\s+Time =\s+[0-9.]+ sec\s*$", stdout, re.M)
    negative = re.findall(r"^Networks are NOT EQUIVALENT\.\s+Time =\s+[0-9.]+ sec\s*$", stdout, re.M)
    if len(positive) == 1 and not negative:
        return "unsat"
    if len(negative) == 1 and not positive:
        return "sat"
    return "inconclusive"


def check(query, circuit_tool, abc, output, solver_seconds=5, stage_seconds=8):
    query, circuit_tool, abc, output = map(lambda p: Path(p).resolve(), (query, circuit_tool, abc, output))
    if not isinstance(solver_seconds, int) or solver_seconds <= 0 or not math.isfinite(stage_seconds) or stage_seconds <= solver_seconds:
        raise ValueError("positive solver budget and a larger stage wall budget required")
    for path in (query, circuit_tool, abc):
        if not path.is_file():
            raise ValueError(f"required file unavailable: {path}")
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(query, output / "query.smt2")
    started = time.perf_counter()
    report = {"schema_version": 1, "status": "inconclusive",
              "scope": "saved SMT assertion; no additional C, machine-code or protection guarantee",
              "query_sha256": digest(query), "environment": environment(),
              "solver_seconds": solver_seconds, "stage_wall_seconds": stage_seconds,
              "tools": {"circuit": {"path": str(circuit_tool), "sha256": digest(circuit_tool)},
                        "abc": {"path": str(abc), "sha256": digest(abc)}},
              "stages": {}}
    save(output / "report.json", report)

    def stage(name, argv, cwd=None):
        result = measure(argv, output / name, wall_seconds=stage_seconds, cwd=cwd)
        report["stages"][name] = result
        stdout = (output / name / "stdout.txt").read_text()
        stderr = (output / name / "stderr.txt").read_text()
        return result, stdout, stderr

    try:
        version, version_text, errors = stage("abc-version", [abc, "-s", "-c", "version"], cwd=output)
        if version["status"] != "completed" or errors.strip():
            raise ValueError("ABC version command did not complete cleanly")
        report["tools"]["abc"]["version_output"] = version_text.strip()
        exported, stdout, stderr = stage("export", [circuit_tool, "export", output / "query.smt2", output / "circuit"])
        if exported["status"] != "completed" or stderr.strip() or json.loads(stdout)["status"] != "exported-not-validated":
            raise ValueError("circuit export did not complete cleanly")
        circuit = output / "circuit" / "circuit.blif"
        report["circuit_sha256"] = digest(circuit)
        validated, stdout, stderr = stage("validate", [circuit_tool, "check", output / "query.smt2", circuit, output / "validation"])
        if validated["status"] != "completed" or stderr.strip():
            raise ValueError("actual circuit did not pass local gate validation")
        report["circuit_validation"] = json.loads(stdout)
        if report["circuit_validation"]["status"] != "circuit-validated":
            raise ValueError("unexpected gate validation response")
        # Fixed relative filename: no path or user text is interpolated into ABC's
        # command language. -s disables user/startup scripts for reproducibility.
        command = f"read_blif circuit.blif; strash; &get; &cec -m -T {int(solver_seconds)}"
        solved, stdout, stderr = stage("solve", [abc, "-s", "-c", command], cwd=output / "circuit")
        if digest(circuit) != report["circuit_sha256"] or digest(output / "query.smt2") != report["query_sha256"]:
            raise ValueError("query or validated circuit changed during solving")
        report["status"] = abc_status(solved, stdout, stderr)
        if report["status"] == "sat":
            report["counterexample_scope"] = "Boolean circuit; no public C input model has been reconstructed"
        if report["status"] == "inconclusive":
            report["reason"] = "missing unambiguous ABC result or process did not finish within its budget"
    except (ValueError, KeyError, OSError, RuntimeError) as error:
        report["status"] = "inconclusive"
        report["reason"] = str(error)
    report["total_wall_seconds"] = time.perf_counter() - started
    report["child_cpu_seconds"] = sum(v.get("cpu_seconds", 0) for v in report["stages"].values())
    report["artifacts"] = {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob("*"))
                           if p.is_file() and p.name != "report.json"}
    save(output / "report.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query", required=True, type=Path)
    parser.add_argument("--circuit-tool", required=True, type=Path)
    parser.add_argument("--abc", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--solver-seconds", default=5, type=int)
    parser.add_argument("--stage-seconds", default=8, type=float)
    args = parser.parse_args()
    try:
        report = check(args.query, args.circuit_tool, args.abc, args.output_dir,
                       args.solver_seconds, args.stage_seconds)
    except (OSError, ValueError) as error:
        parser.error(str(error))
    print(f"{report['status']}: {args.output_dir / 'report.json'}")
    return 0 if report["status"] in ("sat", "unsat") else 3


if __name__ == "__main__":
    sys.exit(main())
