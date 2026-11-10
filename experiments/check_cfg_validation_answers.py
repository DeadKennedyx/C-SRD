#!/usr/bin/env python3
"""Finite compiled checks of saved CFG-validation answers; never a proof grade.

Observer answers are frozen before this separate scorer sees the two known
validation contracts. Every answer and result-plus-one control is compiled with
both compilers at O0/O2 and Clang ASan/UBSan, then compared with the frozen
original executable and an independent integer oracle.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import Runner, executable, file_hash, write_json
from experiment_support import MASK, driver_source, input_vectors, outputs


def oracle(case, x, y):
    if case == "unsigned_distance":
        return abs(x - y)
    if case == "recurrence5":
        for _ in range(5):
            x = (1664525 * x + 1013904223) & MASK
            if x % 2:
                x = (x + y) & MASK
        return x
    raise ValueError("not a reserved CFG validation contract")


def run(args, root):
    report = {"schema_version": 1, "status": "running", "commands": [], "records": [],
              "scope": "finite compiled checks only; original grades and observer answers unchanged",
              "seed": 718002, "random_inputs": 2048, "bindings": {}}
    command = Runner(report)
    try:
        matrix_path, effort_path = args.matrix_report.resolve(), args.effort_report.resolve()
        matrix, effort = json.loads(matrix_path.read_text()), json.loads(effort_path.read_text())
        bindings = report["bindings"]
        bindings.update({str(p): file_hash(p) for p in (matrix_path, effort_path, Path(__file__))})
        if effort["artifact_bindings"][str(matrix_path)] != bindings[str(matrix_path)]:
            raise ValueError("saved effort does not bind this matrix")
        if effort["status"] != "completed" or matrix["status"] != "completed":
            raise ValueError("completed matrix and effort required")
        compilers = {"clang": executable(args.clang), "gcc": executable(args.gcc)}
        report["compilers"] = {}
        for name, compiler in compilers.items():
            version = command([compiler, "--version"])
            if (name == "clang") != ("clang" in version.lower()):
                raise ValueError("compiler family mismatch")
            report["compilers"][name] = {"path": compiler, "sha256": file_hash(compiler), "version": version}
            bindings[compiler] = file_hash(compiler)
        vectors = input_vectors(2, report["seed"], report["random_inputs"])
        write_json(root / "inputs.json", vectors)
        report["vectors"] = len(vectors)
        for trial in effort["trials"]:
            if trial["warmup"] or (trial.get("answer") or {}).get("status") != "candidate":
                continue
            case = next(c for c in matrix["cases"] if c["id"] == trial["case"])
            if case["arity"] != 2:
                raise ValueError("validation contracts have two u32 parameters")
            original = next(r for r in matrix["records"] if r["case"] == trial["case"] and
                            r["profile"] == trial["profile"] and r["variant"] == "original")
            binary = Path(original["binary"])
            directory = effort_path.parent / f"trial-{trial['id']:05d}"
            candidate, mutant = directory / "observer/candidate.c", directory / "mutant.c"
            negative = json.loads((directory / "negative-control/proof.json").read_text())
            for path, expected in ((binary, original["binary_sha256"]),
                                   (candidate, trial["candidate_sha256"]),
                                   (mutant, negative["candidate_sha256"])):
                if file_hash(path) != expected:
                    raise ValueError("frozen artifact hash mismatch")
                bindings[str(path)] = expected
            if negative["source_sha256"] != trial["candidate_sha256"]:
                raise ValueError("wrong-output control does not bind this answer")
            expected = [oracle(trial["case"], x, y) for x, y in vectors]
            actual_original = outputs(command, binary, vectors)
            if actual_original != expected:
                raise ValueError("frozen original and independent oracle disagree")
            folder = root / f"trial-{trial['id']:05d}"; folder.mkdir()
            driver = folder / "driver.c"; driver.write_text(driver_source(case["function"], 2))
            write_json(folder / "expected.json", expected)
            configs = [(name, [opt]) for name in compilers for opt in ("-O0", "-O2")]
            configs.append(("clang", ["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"]))
            for name, flags in configs:
                for kind, source in (("answer", candidate), ("wrong-output", mutant)):
                    index = len(report["records"])
                    program = folder / ("program-" + str(index))
                    command([compilers[name], "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", *flags,
                             source, driver, "-o", program])
                    observed = outputs(command, program, vectors)
                    matches = sum(a == b for a, b in zip(observed, expected))
                    passed = matches == (len(vectors) if kind == "answer" else 0)
                    write_json(folder / ("outputs-" + str(index) + ".json"), observed)
                    report["records"].append({"trial": trial["id"], "case": trial["case"],
                        "profile": trial["profile"], "variant": trial["variant"], "kind": kind,
                        "source_sha256": file_hash(source), "binary_sha256": file_hash(program),
                        "compiler": name, "flags": flags, "matches": matches, "total": len(vectors),
                        "passed": passed, "original_grade": trial["status"]})
                    if not passed:
                        raise ValueError("compiled answer or wrong-output control failed")
            print(trial["id"], trial["case"], trial["profile"], trial["variant"], "finite checks passed", flush=True)
            write_json(root / "checks.json", report)
        if any(file_hash(p) != h for p, h in bindings.items()):
            raise ValueError("artifact or compiler changed during checking")
        report["status"] = "completed"
    except (ValueError, OSError, RuntimeError, KeyError) as error:
        report.update(status="failed", error=str(error))
    write_json(root / "checks.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-report", type=Path, required=True)
    parser.add_argument("--effort-report", type=Path, required=True)
    parser.add_argument("--clang", default="clang")
    parser.add_argument("--gcc", default="gcc")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir.resolve(); root.mkdir(parents=True, exist_ok=False)
    report = run(args, root)
    print(report["status"], report.get("error", ""))
    return int(report["status"] != "completed")


if __name__ == "__main__":
    sys.exit(main())
