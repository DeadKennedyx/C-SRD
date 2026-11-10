#!/usr/bin/env python3
"""Finite compiled checks of ALL remaining inconclusive positional-width answers.

Identical repeated answers are grouped only after checking every saved binding.
Checks compare the frozen original, the answer, and a result-plus-one control
with an independent oracle. Passing never upgrades an equivalence proof grade.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import Runner, AuditError, executable, file_hash, write_json
from benchmark_oracles import ORACLES, vectors
from experiment_support import driver_source, outputs


def local(value):
    path = Path(value)
    return ROOT / path.relative_to("/work") if path.is_relative_to("/work") else path


def run(args, root):
    report = {"schema_version": 1, "status": "running", "commands": [], "records": [],
              "groups": [], "bindings": {}, "seed": 718003, "random_inputs": 2048,
              "selection": "all measured answers still inconclusive after checked-circuit replay",
              "scope": "finite compiled checks only; no historical grade or observer change"}
    command = Runner(report)

    def bind(path, expected=None):
        path = local(path).resolve()
        actual = file_hash(path)
        if expected is not None and actual != expected:
            raise ValueError("frozen input changed: " + str(path))
        report["bindings"][str(path)] = actual
        return path

    try:
        matrix_path, effort_path, circuit = args.matrix_report.resolve(), args.effort_report.resolve(), args.circuit_dir.resolve()
        matrix = json.loads(bind(matrix_path).read_text())
        effort = json.loads(bind(effort_path).read_text())
        protocol = json.loads(bind(circuit / "protocol.json").read_text())
        rows = json.loads(bind(circuit / "summary.json").read_text())
        done = json.loads(bind(circuit / "completion.json").read_text())
        if matrix["status"] not in ("completed", "completed-with-gaps") or effort["status"] != "completed" or done["status"] != "completed" or done["controls_passed"] is not True:
            raise ValueError("completed controlled experiments required")
        if effort["artifact_bindings"][str(matrix_path)] != file_hash(matrix_path):
            raise ValueError("effort does not bind this matrix")
        for path in (Path(__file__), ROOT / "tools/benchmark_oracles.py", ROOT / "tools/experiment_support.py", ROOT / "tools/audit_protection.py"):
            bind(path)
        trials = {t["id"]: t for t in effort["trials"] if not t["warmup"] and t["status"] == "inconclusive"}
        saved = {r["name"]: r for r in rows if r["kind"] == "saved-answer"}
        if set(saved) != {f"trial-{i:05d}-grade" for i in trials}:
            raise ValueError("circuit selection differs from all initial unknown grades")
        cases = {c["name"]: c for c in protocol["cases"]}
        groups = defaultdict(list)
        for name, row in saved.items():
            if row["status"] != "inconclusive":
                continue
            trial = trials[int(name.split("-")[1])]
            directory = local(trial["directory"])
            case = cases[name]
            if json.loads(bind(directory / "trial.json", case["trial_sha256"]).read_text()) != trial:
                raise ValueError("individual trial differs from aggregate")
            circuit_report = json.loads(bind(ROOT / row["report"]).read_text())
            if circuit_report["status"] != "inconclusive" or circuit_report["query_sha256"] != case["binding"]["query_sha256"]:
                raise ValueError("circuit report and grade binding disagree")
            candidate = bind(directory / "observer/candidate.c", trial["candidate_sha256"])
            bind(ROOT / case["binding"]["grade_report"], case["binding"]["grade_report_sha256"])
            negative = json.loads(bind(directory / "negative-control/proof.json").read_text())
            mutant = bind(directory / "mutant.c", negative["candidate_sha256"])
            if negative["source_sha256"] != trial["candidate_sha256"] or negative["functions"][0]["verification"] != "counterexample":
                raise ValueError("wrong-output control is not bound to the answer")
            groups[(trial["case"], trial["profile"], trial["variant"], file_hash(candidate), file_hash(mutant))].append(trial)
        if not groups:
            raise ValueError("no remaining inconclusive answers")
        compilers = {"clang": executable(args.clang), "gcc": executable(args.gcc)}
        report["compilers"] = {}
        for name, compiler in compilers.items():
            version = command([compiler, "--version"])
            if (name == "clang") != ("clang" in version.lower()):
                raise ValueError("compiler family mismatch")
            bind(compiler)
            report["compilers"][name] = {"path": compiler, "sha256": file_hash(compiler), "version": version}
        for key, members in sorted(groups.items()):
            case_id, profile, variant, candidate_hash, mutant_hash = key
            if case_id not in ("jenkins_word", "rgb_luma8"):
                raise ValueError("follow-up is limited to the two declared development contracts")
            case = next(c for c in matrix["cases"] if c["id"] == case_id)
            original = next(r for r in matrix["records"] if (r["case"], r["profile"], r["variant"]) == (case_id, profile, "original"))
            binary = bind(original["binary"], original["binary_sha256"])
            group_id = f"{case_id}-{profile}-{variant}"
            folder = root / group_id; folder.mkdir()
            probes = vectors(case["arity"], report["seed"], report["random_inputs"])
            expected = [ORACLES[case_id](*v) for v in probes]
            observed = outputs(command, binary, probes)
            write_json(folder / "oracle.json", {"inputs": probes, "expected": expected, "original_outputs": observed})
            if observed != expected:
                raise ValueError("frozen original differs from independent oracle")
            driver = folder / "driver.c"; driver.write_text(driver_source(case["function"], case["arity"]))
            source = local(members[0]["directory"])
            report["groups"].append({"id": group_id, "trials": [t["id"] for t in members],
                                     "candidate_sha256": candidate_hash, "mutant_sha256": mutant_hash,
                                     "vectors": len(probes), "original_binary_sha256": file_hash(binary)})
            configs = [(name, [opt]) for name in compilers for opt in ("-O0", "-O2")]
            configs.append(("clang", ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]))
            for name, flags in configs:
                for kind, path in (("answer", source / "observer/candidate.c"), ("wrong-output", source / "mutant.c")):
                    index = len(report["records"])
                    program = folder / ("program-" + str(index))
                    command([compilers[name], "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", *flags,
                             path, driver, "-o", program])
                    actual = outputs(command, program, probes)
                    matches = sum(a == b for a, b in zip(actual, expected))
                    passed = matches == (len(probes) if kind == "answer" else 0)
                    write_json(folder / ("outputs-" + str(index) + ".json"), actual)
                    report["records"].append({"group": group_id, "kind": kind, "compiler": name, "flags": flags,
                                              "binary_sha256": file_hash(program), "source_sha256": file_hash(path),
                                              "matches": matches, "total": len(probes), "passed": passed})
                    if not passed:
                        raise ValueError("compiled answer or wrong-output control failed")
            print(group_id, len(probes), "finite probes passed in five compiler configurations", flush=True)
            write_json(root / "checks.json", report)
        if any(file_hash(path) != value for path, value in report["bindings"].items()):
            raise ValueError("input or compiler changed during finite checks")
        report["status"] = "completed"
    except (ValueError, OSError, AuditError, KeyError) as error:
        report.update(status="failed", error=str(error))
    write_json(root / "checks.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-report", type=Path, required=True)
    parser.add_argument("--effort-report", type=Path, required=True)
    parser.add_argument("--circuit-dir", type=Path, required=True)
    parser.add_argument("--clang", default="clang-18")
    parser.add_argument("--gcc", default="gcc")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir.resolve(); root.mkdir(parents=True, exist_ok=False)
    report = run(args, root)
    print(report["status"], report.get("error", ""))
    return int(report["status"] != "completed")


if __name__ == "__main__":
    sys.exit(main())
