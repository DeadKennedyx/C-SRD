#!/usr/bin/env python3
"""Compile every distinct recovered buffer answer and check declared finite oracles.

This supplements the saved all-input source-model grades. It does not turn the
finite sample into proof, and repeated identical answers are not independent.
"""
import argparse
import json
from pathlib import Path

from audit_protection import MODEL_GUARD, Runner, executable, file_hash, write_json
from buffer_observation_cases import cases, driver, expected, LAYOUTS

ROOT = Path(__file__).resolve().parents[1]


def local(path):
    path = Path(path)
    return ROOT / path.relative_to("/work") if path.is_relative_to("/work") else path


def run(args, root):
    report = {"status": "running", "commands": [], "answers": [], "compilers": [], "comparisons": 0,
              "claim": "finite compiled return/whole-memory checks; saved source-model proofs are separate evidence",
              "cases": cases(), "layouts": LAYOUTS}
    command = Runner(report)
    try:
        source_report = Path(args.reconstruction_report).resolve(strict=True)
        original = json.loads(source_report.read_text())
        if original["status"] not in ("completed", "completed-with-gaps"):
            raise ValueError("finished reconstruction comparison required")
        report["reconstruction"] = {"path": str(source_report), "sha256": file_hash(source_report)}
        report["implementation"] = {p: file_hash(ROOT / p) for p in
                                    ("tools/validate_buffer_answers.py", "tools/buffer_observation_cases.py", "tools/audit_protection.py")}
        distinct = {}
        for row in original["observations"]:
            if row["status"] != "recovered-under-source-model": continue
            path = local(row["recovered_path"])
            if file_hash(path) != row["recovered_sha256"]: raise ValueError("recovered answer changed")
            key = row["recovered_sha256"]
            item = distinct.setdefault(key, {"path": path, "function": row["function"],
                                              "parameters": original["groups"][row["group"]]["parameters"], "members": []})
            item["members"].append({k: row[k] for k in ("function", "profile", "variant", "repetition")})
        if not distinct: raise ValueError("no proved answers to compile")
        for compiler_name in args.compiler:
            compiler = executable(compiler_name)
            report["compilers"].append({"path": compiler, "sha256": file_hash(compiler),
                                        "version": command([compiler, "--version"]).splitlines()[0]})
        for ai, (digest, answer) in enumerate(distinct.items()):
            directory = root / f"answer-{ai}"; directory.mkdir()
            source = directory / "recovered.c"; source.write_bytes(answer["path"].read_bytes())
            harness = directory / "harness.c"; harness.write_text(MODEL_GUARD + driver(answer["function"], answer["parameters"]))
            record = {"function": answer["function"], "source_sha256": digest, "members": answer["members"], "builds": []}
            report["answers"].append(record)
            for ci, compiler in enumerate(report["compilers"]):
                for optimization in ("O0", "O2"):
                    binary = directory / f"compiler-{ci}-{optimization}"
                    command([compiler["path"], "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-"+optimization,
                             harness, source, "-o", binary])
                    build = {"compiler": ci, "optimization": optimization, "binary_sha256": file_hash(binary), "comparisons": 0}
                    record["builds"].append(build)
                    for p, q in LAYOUTS:
                        for case in report["cases"]:
                            wanted = expected(answer["function"], case["memory"], p, q, case["x"])
                            inputs = " ".join(map(str, [p, q, case["x"], *case["memory"]])) + "\n"
                            actual = list(map(int, command([binary], input=inputs).split()))
                            if actual != [wanted["return_value"], *wanted["final_memory"]]:
                                raise ValueError("compiled recovered answer disagrees with independent finite oracle")
                            build["comparisons"] += 1; report["comparisons"] += 1
                    if file_hash(binary) != build["binary_sha256"]: raise ValueError("compiled answer changed")
            if file_hash(source) != digest or file_hash(answer["path"]) != digest: raise ValueError("answer changed during validation")
        for compiler in report["compilers"]:
            if file_hash(compiler["path"]) != compiler["sha256"]: raise ValueError("compiler changed during validation")
        for path, digest in report["implementation"].items():
            if file_hash(ROOT / path) != digest: raise ValueError("validation implementation changed")
        if file_hash(source_report) != report["reconstruction"]["sha256"]: raise ValueError("input report changed")
        report["status"] = "tested"
    except Exception as error:
        report.update(status="failed", error=str(error))
    finally:
        write_json(root / "validation.json", report)
    print(report["status"], len(report["answers"]), report["comparisons"], report.get("error", ""), flush=True)
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reconstruction-report", required=True)
    p.add_argument("--compiler", action="append", required=True)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    root = Path(args.output_dir).resolve(); root.mkdir(parents=True, exist_ok=False)
    raise SystemExit(int(run(args, root)["status"] == "failed"))
