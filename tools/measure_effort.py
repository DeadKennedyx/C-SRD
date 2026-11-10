#!/usr/bin/env python3
"""Serialized, randomized paired reconstruction-effort experiments on validated builds."""
import argparse
from collections import defaultdict
import csv
import fcntl
import itertools
import json
import math
import os
from pathlib import Path
import random
import subprocess
import sys
import time

from audit_decompiler import scoring_reference
from audit_protection import executable, file_hash
from effort_resources import environment, measure, save
from effort_statistics import summarize
from effort_worker import model_source
from experiment_support import input_vectors, MASK
from observe_runtime import HELDOUT, score_models
from pcode_reconstruct import reconstruct
from pcode_cfg import LIMITS as PCODE_LIMITS

ROOT = Path(__file__).resolve().parents[1]
WORKER = ROOT / "tools/effort_worker.py"


def worker(config, directory, budget):
    directory.mkdir()
    save(directory / "config.json", config)
    resources = measure([sys.executable, WORKER, directory / "config.json"], directory / "measurement", **budget)
    answer_path = directory / "answer.json"
    answer = json.loads(answer_path.read_text()) if answer_path.is_file() else None
    return resources, answer


def proof(csrd, reference, candidate, directory, timeout_ms):
    directory.mkdir()
    path = directory / "proof.json"
    resources = measure([csrd, "verify", reference, candidate, "--report", path,
                         "--timeout-ms", timeout_ms], directory / "measurement", wall_seconds=timeout_ms/1000 + 15)
    result = {"resources": resources, "status": "inconclusive"}
    if path.is_file():
        report = json.loads(path.read_text())
        if len(report.get("functions", [])) == 1:
            result["proof"] = report["functions"][0]
            result["status"] = result["proof"].get("verification", "inconclusive")
    return result


def grade(args, matrix, record, config, answer, directory):
    frozen, frozen_hash = scoring_reference(matrix, record)
    result = {"reference_preprocessed_sha256": frozen_hash, "accuracy": None}
    if config["observer"] == "runtime":
        rng = random.Random(79190 + config["input_seed"])
        vectors = HELDOUT + [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(12)]
        grading = {**config, "observer": "runtime-grade", "vectors": vectors}
        resources, data = worker(grading, directory / "grade", {"wall_seconds": args.grading_seconds})
        result["grading_resources"] = resources
        if resources["status"] != "completed" or not data or data["status"] != "completed":
            return {**result, "status": "inconclusive", "reason": "heldout trace collection did not finish"}
        targets = [(x + y) & MASK for x, y in vectors]
        scoring = score_models(answer["models"], data["traces"], targets)
        negative = score_models(answer["negative_models"], data["traces"], targets)
        result.update(all_models=scoring, negative_control=negative, grading_queries=len(vectors))
        if not scoring["models"]:
            return {**result, "status": "no-candidate"}
        selected = scoring["models"][0]  # fixed by training, not held-out success
        result["accuracy"] = selected["correct"] / selected["total"]
        result["availability"] = selected["available"] / selected["total"]
        result["status"] = ("recovered-on-heldout" if selected["correct"] == selected["total"] else
                            "wrong-candidate" if selected["available"] == selected["total"] else "inconclusive")
        return result
    candidate = directory / "observer/candidate.c"
    result["candidate_sha256"] = file_hash(candidate)
    result["verification"] = proof(args.csrd, frozen, candidate, directory / "grade", args.timeout_ms)
    result["status"] = {"proved-under-model": "recovered-under-source-model",
                        "counterexample": "wrong-candidate"}.get(result["verification"]["status"], "inconclusive")
    if config["observer"] in ("blackbox", "bitlinear"):
        original = next(r for r in matrix["records"] if r["case"] == record["case"] and
                        r["profile"] == record["profile"] and r["variant"] == "original")
        heldout = input_vectors(config["arity"], 771992 + config["input_seed"], 128)
        hidden = {"observer": "output-grade", "binary": original["binary"], "vectors": heldout, "model": answer["model"]}
        resources, scores = worker(hidden, directory / "heldout", {"wall_seconds": args.grading_seconds})
        result["heldout_resources"] = resources
        if resources["status"] == "completed" and scores and scores["status"] == "completed":
            result.update(accuracy=scores["accuracy"], heldout_correct=scores["correct"], grading_queries=scores["total"])
            if result["status"] == "recovered-under-source-model" and scores["accuracy"] != 1:
                raise ValueError("formal and executable grading disagree")
        mutant_source = model_source(config["function"], config["arity"], answer["model"], result_offset=1)
    else:
        export = json.loads((directory / "observer/export.json").read_text())
        mutant_source = reconstruct(export, result_offset=1)
    mutant = directory / "mutant.c"
    mutant.write_text(mutant_source)
    result["negative_control"] = proof(args.csrd, candidate, mutant, directory / "negative-control", args.timeout_ms)
    if result["negative_control"]["status"] != "counterexample":
        raise ValueError("corrupted-output control was not rejected")
    if file_hash(frozen) != frozen_hash or file_hash(candidate) != result["candidate_sha256"]:
        raise ValueError("scoring artifact changed")
    return result


def run(args, output):
    matrix_path = Path(args.matrix_report).resolve(strict=True)
    matrix = json.loads(matrix_path.read_text())
    partial = matrix["status"] == "failed" and args.allow_partial_matrix and "summary" in matrix and "error" not in matrix
    if matrix["status"] not in ("completed", "completed-with-gaps") and not partial:
        raise ValueError("completed validated matrix required")
    args.csrd = executable(args.csrd)
    if file_hash(args.csrd) != matrix["tools"]["csrd"]["sha256"]:
        raise ValueError("verifier differs from frozen build model")
    records = [r for r in matrix["records"] if r["case"] in args.case and r["profile"] in args.profile
               and r["variant"] in args.variant]
    requested = set(itertools.product(args.case, args.profile, args.variant))
    if {(r["case"], r["profile"], r["variant"]) for r in records} != requested:
        raise ValueError("one or more requested matrix cells are missing")
    bindings = {str(matrix_path): file_hash(matrix_path), args.csrd: file_hash(args.csrd)}
    tools = {"csrd": {"path": args.csrd, "sha256": file_hash(args.csrd)}}
    for r in records:
        if r["status"] != "completed" or file_hash(r["binary"]) != r["binary_sha256"]:
            raise ValueError("unvalidated or changed binary")
        frozen, sha = scoring_reference(matrix, r)
        bindings.update({r["binary"]: r["binary_sha256"], str(frozen): sha})
    if args.observer == "runtime":
        args.gdb = executable(args.gdb)
        tools["gdb"] = {"path": args.gdb, "sha256": file_hash(args.gdb),
                        "version": subprocess.check_output([args.gdb, "--version"], text=True).splitlines()[0]}
        for profile in matrix["profiles"]:
            if profile["id"] in args.profile and (profile.get("lto", "none") != "none" or
                                                  profile.get("sanitizers") or profile.get("pgo")):
                raise ValueError("runtime observer requires non-LTO, non-instrumented profiles")
        if args.case != ["calculate"]:
            raise ValueError("runtime task currently specifies calculate's known intermediate sum only")
    if args.observer == "ghidra":
        args.headless = executable(args.headless)
        installation = Path(args.headless).resolve().parent.parent
        tools["ghidra"] = {"path": args.headless, "sha256": file_hash(args.headless),
                           "properties": (installation / "Ghidra/application.properties").read_text()}
        for p in sorted(set(installation.glob("Ghidra/Features/Decompiler/lib/*.jar")) |
                        set(installation.glob("Ghidra/Features/Decompiler/os/*/decompile"))):
            bindings[str(p)] = file_hash(p)
    for t in tools.values():
        bindings[t["path"]] = t["sha256"]
    implementation = [Path(__file__), WORKER, ROOT / "tools/effort_resources.py", ROOT / "tools/effort_statistics.py",
                      ROOT / "tools/observe_runtime.py", ROOT / "tools/gdb_trace.py", ROOT / "tools/pcode_reconstruct.py",
                      ROOT / "tools/pcode_cfg.py", ROOT / "tools/pcode_values.py",
                      ROOT / "tools/ghidra/ExportCSRD.java", ROOT / "tools/experiment_support.py"]
    bindings.update({str(p): file_hash(p) for p in implementation})
    query_budgets = args.query_budgets if args.observer != "ghidra" else [0]
    step_budgets = args.step_budgets if args.observer == "runtime" else [0]
    budgets = [{"wall_seconds": w, "query_budget": q, "step_budget": s, "cpu_seconds": c,
                "memory_bytes": m * 1024**2 if m else None} for w, q, s, c, m in
               itertools.product(args.wall_budgets, query_budgets, step_budgets,
                                 args.cpu_budgets or [None], args.memory_budgets_mib or [None])]
    report = {"schema_version": 1, "status": "running", "observer": args.observer,
              "environment_start": environment(), "tools": tools, "artifact_bindings": bindings,
              "matrix_status": matrix["status"], "matrix_summary": matrix.get("summary"),
              "protocol": {**vars(args), "budgets": budgets, "order": "serialized randomized complete blocks",
                           "cache": "fresh observer process and Ghidra project; filesystem caches not flushed",
                           "grading": "reference withheld from fixed observer; frozen answer; grader resources separate",
                           "pcode_adapter": {"version": "cfg-v2", "limits": PCODE_LIMITS} if args.observer == "ghidra" else None,
                           "human_effort": "unassessed", "binary_lifting_proved": False,
                           "lock_scope": "cooperating effort runs in this checkout only; shared-host noise remains"},
              "application_costs_from_matrix": [{k: r.get(k) for k in ("case", "profile", "variant", "timing", "binary_bytes", "binary_size_ratio")}
                                                for r in records], "trials": []}
    save(output / "protocol.json", {k: v for k, v in report.items() if k != "trials"})
    rng = random.Random(args.order_seed)
    groups = defaultdict(list)
    for r in records:
        groups[(r["case"], r["profile"])].append(r)
    blocks = list(itertools.product(range(-args.warmups, args.repetitions), range(len(budgets)), sorted(groups)))
    # Warmups first; randomize variants within each matched block.
    for repetition, budget_id, key in blocks:
        order = list(groups[key]); rng.shuffle(order)
        for r in order:
            index = len(report["trials"])
            directory = output / f"trial-{index:05d}"
            directory.mkdir()
            case = next(c for c in matrix["cases"] if c["id"] == r["case"])
            budget = budgets[budget_id]
            config = {"observer": args.observer, "binary": r["binary"], "function": case["function"],
                      "arity": case["arity"], "input_seed": args.input_seed + max(repetition, 0),
                      "gdb": args.gdb, "headless": args.headless, "analysis_seconds": args.analysis_seconds,
                      "decompile_seconds": args.decompile_seconds, **budget}
            trial = {"id": index, "directory": str(directory), "case": r["case"], "profile": r["profile"],
                     "variant": r["variant"], "budget_id": budget_id, "repetition": repetition,
                     "warmup": repetition < 0, "binary_sha256": r["binary_sha256"], "status": "running", "budget": budget}
            report["trials"].append(trial)
            print(f"{index + 1}: {key[0]}/{key[1]}/{r['variant']} budget={budget_id} repetition={repetition}", flush=True)
            try:
                resources, answer = worker(config, directory / "observer",
                    {"wall_seconds": budget["wall_seconds"], "cpu_seconds": budget["cpu_seconds"],
                     "memory_bytes": budget["memory_bytes"]})
                trial.update(resources=resources, answer=answer)
                progress = directory / "observer" / ("trace-progress.json" if args.observer == "runtime" else "queries.json")
                if progress.is_file():
                    counts = json.loads(progress.read_text())
                    trial["query_accounting"] = {k: counts[k] for k in ("attempted", "completed")}
                if resources["status"] != "completed":
                    trial["status"] = resources["status"] if resources["status"].endswith("budget") else "error"
                elif not answer:
                    trial.update(status="error", error="observer did not write an answer")
                elif answer["status"] == "candidate":
                    trial.update(grade(args, matrix, r, config, answer, directory))
                elif answer["status"] in ("analysis-timeout", "timeout"):
                    trial["status"] = "observer-timeout"
                elif answer["status"] in ("decompiler-error", "export-error", "error"):
                    trial["status"] = "error"
                else:
                    trial["status"] = answer["status"]
                if file_hash(r["binary"]) != r["binary_sha256"]:
                    raise ValueError("binary changed during measurement")
            except (OSError, ValueError, RuntimeError, KeyError) as error:
                trial.update(status="error", error=str(error))
            save(directory / "trial.json", trial)
            save(output / "effort.json", report)
    if any(file_hash(p) != h for p, h in bindings.items()):
        raise ValueError("bound input, tool or implementation changed during experiment")
    report.update(status="failed" if any(t["status"] == "error" for t in report["trials"]) else "completed",
                  environment_end=environment(), summary=summarize(report["trials"]))
    save(output / "effort.json", report)
    save(output / "summary.json", report["summary"])
    export_csv(report, output / "trials.csv")
    return report


def export_csv(report, path):
    fields = ["id", "case", "profile", "variant", "budget_id", "repetition", "warmup", "status", "accuracy",
              "wall_seconds", "cpu_seconds", "peak_process_rss_bytes", "peak_sampled_tree_rss_bytes",
              "training_queries", "instruction_steps", "value_observations"]
    with Path(path).open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        for trial in report["trials"]:
            flat = {**trial, **trial.get("resources", {}), **(trial.get("answer") or {})}
            flat["status"] = trial["status"]
            writer.writerow({k: flat.get(k) for k in fields})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-report", required=True)
    parser.add_argument("--csrd", required=True)
    parser.add_argument("--observer", choices=["blackbox", "bitlinear", "ghidra", "runtime"], required=True)
    parser.add_argument("--allow-partial-matrix", action="store_true", help="explicitly measure only validated cells of a completed matrix that retained other failed cells")
    parser.add_argument("--case", action="append", required=True)
    parser.add_argument("--profile", action="append", required=True)
    parser.add_argument("--variant", action="append", required=True)
    parser.add_argument("--wall-budgets", nargs="+", type=float, default=[60])
    parser.add_argument("--query-budgets", nargs="+", type=int, default=[3, 8, 32])
    parser.add_argument("--step-budgets", nargs="+", type=int, default=[4, 16, 64])
    parser.add_argument("--cpu-budgets", nargs="+", type=float)
    parser.add_argument("--memory-budgets-mib", nargs="+", type=int)
    parser.add_argument("--repetitions", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--order-seed", type=int, default=20261109)
    parser.add_argument("--input-seed", type=int, default=19011)
    parser.add_argument("--headless", default=os.environ.get("CSRD_GHIDRA_HEADLESS", "analyzeHeadless"))
    parser.add_argument("--gdb", default="gdb")
    parser.add_argument("--analysis-seconds", type=int, default=30)
    parser.add_argument("--decompile-seconds", type=int, default=15)
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--grading-seconds", type=float, default=120)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if "original" not in args.variant or args.repetitions < 1 or args.warmups < 0:
        parser.error("original baseline, positive repetitions and nonnegative warmups required")
    if any(len(values) != len(set(values)) for values in (args.case, args.profile, args.variant, args.wall_budgets,
                                                         args.query_budgets, args.step_budgets)):
        parser.error("duplicate filters or budgets are not allowed")
    if any(v <= 0 for v in args.wall_budgets) or any(not 1 <= v <= 4096 for v in args.query_budgets):
        parser.error("positive wall budgets and query budgets 1..4096 required")
    if args.observer == "runtime" and (any(not 3 <= v <= 128 for v in args.query_budgets) or
                                       any(not 1 <= v <= 10000 for v in args.step_budgets)):
        parser.error("runtime requires 3..128 traces and 1..10000 steps")
    if any(not math.isfinite(v) or v <= 0 for v in [*args.wall_budgets, *(args.cpu_budgets or []),
                           *(args.memory_budgets_mib or []), args.analysis_seconds,
                           args.decompile_seconds, args.timeout_ms, args.grading_seconds]):
        parser.error("resource and grading budgets must be positive")
    output = Path(args.output_dir).resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
        # No overlap with another participating effort driver in this checkout.
        lock_path = ROOT / "experiments/runs/effort.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with lock_path.open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = run(args, output)
        print(f"{result['status']}: {output / 'effort.json'}")
        return int(result["status"] == "failed")
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        if output.exists():
            save(output / "failure.json", {"status": "failed", "error": str(error)})
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
