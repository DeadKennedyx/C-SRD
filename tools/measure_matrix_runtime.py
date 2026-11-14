#!/usr/bin/env python3
"""Serialized known-intermediate recovery from frozen matrix executables.

Training labels calibrate a fixed observer. A separate grader checks its frozen
first candidate on held-out traces; searching those labels for a better model
does not count as primary recovery. Debugger and fitting costs are separate.
"""
import argparse
from collections import Counter
import fcntl
import gzip
import itertools
import json
from pathlib import Path
import random
import subprocess
import sys

from audit_decompiler import scoring_reference
from audit_protection import executable, file_hash
from effort_resources import environment, measure, measurement_lock, save
from fit_matrix_runtime import read_trace
from fit_region_values import score_models
from matrix_runtime_tasks import ARITIES, VERSION, targets, vectors

ROOT = Path(__file__).resolve().parents[1]
METRICS = ("wall_seconds", "cpu_seconds", "peak_process_rss_bytes", "peak_sampled_tree_rss_bytes")


def grade(answer, entries, labels):
    if any(entry["split"] != "heldout" for entry in entries):
        raise ValueError("grading requires held-out traces")
    traces = [read_trace(entry) for entry in entries]
    if any(t["status"] != "completed" or t["stack_read_failures"] or t["vector_read_failures"] for t in traces):
        raise ValueError("primary grading requires complete observations")
    result = {}
    if set(answer["targets"]) != set(labels):
        raise ValueError("observer target set changed")
    if any(len(values) != len(entries) for values in labels.values()):
        raise ValueError("held-out label/trace count mismatch")
    for name, target in answer["targets"].items():
        models, selected = target["models"], target["selected"]
        negative, negative_selected = target["negative_models"], target["negative_selected"]
        if selected != (models[0] if models else None) or negative_selected != (negative[0] if negative else None):
            raise ValueError("observer did not freeze its first candidate")
        def evaluate(candidates):
            scoring = score_models(candidates, traces, labels[name])
            first = scoring["models"][0] if scoring["models"] else None
            status = ("no-candidate" if first is None else "recovered-on-heldout" if first["correct"] == first["total"] else
                      "wrong-candidate" if first["available"] == first["total"] else "inconclusive")
            return {"status": status, "selected": first,
                    "accuracy": first["correct"]/first["total"] if first else None,
                    "availability": first["available"]/first["total"] if first else None,
                    "diagnostic_all_candidates": {k: v for k, v in scoring.items() if k != "models"}}
        result[name] = {"fit": target["fit"], "candidate_count": len(models),
                        "primary": evaluate(models), "negative_control": evaluate(negative)}
    return result


def labels_for(case, inputs):
    observations = [targets(case, vector) for vector in inputs]
    return {name: [observation["intermediates"][name] for observation in observations]
            for name in observations[0]["intermediates"]} | {
                "public_return_control": [observation["public_return"] for observation in observations]}


def resource_totals(group):
    phases = {}
    for phase, split in (("training_trace", "training"), ("grading_trace", "heldout")):
        resources = [entry["resources"] for entry in group["traces"] if entry["split"] == split]
        phases[phase] = {key: (sum(r[key] for r in resources) if key in ("wall_seconds", "cpu_seconds") else max(r[key] for r in resources))
                        if resources and all(r.get(key) is not None for r in resources) else None for key in METRICS}
    fits = group.get("fits", [])
    phases["primary_fit"] = {key: fits[0]["resources"].get(key) if fits else None for key in METRICS}
    training, fit = phases["training_trace"], phases["primary_fit"]
    phases["primary_observer"] = {key: (training[key]+fit[key] if key in ("wall_seconds", "cpu_seconds") else max(training[key], fit[key]))
        if training[key] is not None and fit[key] is not None else None for key in METRICS}
    return phases


def paired_summary(groups):
    originals = {(g["case"], g["profile"], g["repetition"]): g for g in groups if g["variant"] == "original"}
    result = []
    for group in groups:
        original = originals[(group["case"], group["profile"], group["repetition"])]
        paired = {key: group[key] for key in ("case", "profile", "variant", "repetition", "status")}
        paired["original_status"] = original["status"]
        paired["resource_phases"] = resource_totals(group)
        baseline = resource_totals(original)
        paired["cost_ratios"] = {phase: {key: value/baseline[phase][key] if value is not None and baseline[phase][key] else None
                                        for key, value in resources.items()} for phase, resources in paired["resource_phases"].items()}
        paired["instruction_steps"] = sum(t.get("steps", 0) for t in group["traces"] if t["split"] == "training")
        base_steps = sum(t.get("steps", 0) for t in original["traces"] if t["split"] == "training")
        paired["instruction_step_ratio"] = paired["instruction_steps"]/base_steps if base_steps and group["status"] == original["status"] == "completed" else None
        paired["queries"] = dict(Counter(t["split"] for t in group["traces"]))
        paired["targets"] = {}
        names = list(targets(group["case"], [0]*ARITIES[group["case"]])["intermediates"])+["public_return_control"]
        for name in names:
            target = group.get("targets", {}).get(name)
            base = original.get("targets", {}).get(name)
            if target is None:
                paired["targets"][name] = {"status": "unassessed", "original_status": base["primary"]["status"] if base else "unassessed",
                    "accuracy": None, "availability": None, "negative_control_status": "unassessed",
                    "matched_recovery_cpu_ratio": None, "query_ratio_on_success": None}
                continue
            recovered = target["primary"]["status"] == "recovered-on-heldout"
            matched = recovered and base is not None and base["primary"]["status"] == "recovered-on-heldout"
            paired["targets"][name] = {"status": target["primary"]["status"],
                "original_status": base["primary"]["status"] if base else "unassessed",
                "accuracy": target["primary"]["accuracy"], "availability": target["primary"]["availability"],
                "negative_control_status": target["negative_control"]["status"],
                "matched_recovery_cpu_ratio": paired["cost_ratios"]["primary_observer"]["cpu_seconds"] if matched else None,
                "query_ratio_on_success": paired["queries"]["training"]/sum(t["split"] == "training" for t in original["traces"]) if matched else None}
        result.append(paired)
    return result


def run(args, output):
    matrix_path = Path(args.matrix_report).resolve(strict=True)
    matrix = json.loads(matrix_path.read_text())
    if matrix["status"] not in ("completed", "completed-with-gaps"):
        raise ValueError("completed matrix required")
    requested = set(itertools.product(args.case, args.profile, args.variant))
    records = [r for r in matrix["records"] if (r["case"], r["profile"], r["variant"]) in requested]
    if len(records) != len(requested) or {(r["case"], r["profile"], r["variant"]) for r in records} != requested:
        raise ValueError("missing or duplicated matrix cell")
    bindings = {str(matrix_path): file_hash(matrix_path)}
    cases = {case["id"]: case for case in matrix["cases"]}
    for profile in matrix["profiles"]:
        if profile["id"] in args.profile and (profile.get("lto", "none") != "none" or profile.get("sanitizers") or profile.get("pgo")):
            raise ValueError("ordinary non-LTO, non-instrumented profiles required")
    for record in records:
        case = cases[record["case"]]
        if case["arity"] != ARITIES[case["id"]] or case.get("oracle") != case["id"]:
            raise ValueError("runtime task differs from the matrix contract")
        if record["status"] != "completed" or file_hash(record["binary"]) != record["binary_sha256"]:
            raise ValueError("unvalidated or changed binary")
        reference, checksum = scoring_reference(matrix, record)
        bindings.update({record["binary"]: record["binary_sha256"], str(reference): checksum})
    gdb = executable(args.gdb)
    bindings[gdb] = file_hash(gdb)
    for name in ("measure_matrix_runtime.py", "check_matrix_runtime.py", "gdb_matrix_trace.py", "fit_matrix_runtime.py", "matrix_runtime_tasks.py",
                 "benchmark_oracles.py", "fit_region_values.py", "observe_runtime.py", "effort_resources.py"):
        path = ROOT/"tools"/name
        bindings[str(path)] = file_hash(path)
    report = {"schema_version": 1, "status": "running", "artifact_bindings": bindings,
              "environment_start": environment(), "gdb": {"path": gdb, "sha256": file_hash(gdb),
                  "version": subprocess.check_output([gdb, "--version"], text=True).splitlines()[0]},
              "protocol": {**vars(args), "task_version": VERSION,
                  "selection": "first fitted location in fixed lexical order; held-out data withheld from fitting",
                  "order": "serialized randomized blocks of case/profile/repetition; fixed matched inputs",
                  "cost_scope": "fresh GDB per input, single-step sampling; fit includes Python startup, decompression and model search; grading traces excluded from primary observer cost",
                  "claim_scope": "finite supervised known-intermediate recovery, not whole-memory coverage, whole-function reconstruction, human effort or confidentiality",
                  "public_output": "visibility control; excluded from internal recovery counts"}, "groups": []}
    save(output/"protocol.json", report)
    rng = random.Random(args.order_seed)
    try:
        for repetition, case_id, profile in itertools.product(range(args.repetitions), args.case, args.profile):
            order = [r for r in records if (r["case"], r["profile"]) == (case_id, profile)]
            rng.shuffle(order)
            training, heldout = vectors(case_id, args.input_seed+repetition, args.training, args.heldout)
            for record in order:
                directory = output/f"group-{len(report['groups']):04d}"; directory.mkdir()
                group = {"case": case_id, "profile": profile, "variant": record["variant"], "repetition": repetition,
                         "binary_sha256": record["binary_sha256"], "directory": str(directory), "status": "tracing", "traces": []}
                report["groups"].append(group)
                for index, (split, vector) in enumerate([*(('training', v) for v in training), *(('heldout', v) for v in heldout)]):
                    input_path, config_path = directory/f"{index}.input", directory/f"{index}.config.json"
                    trace_path, script = directory/f"{index}.trace.json.gz", directory/f"{index}.gdb"
                    input_path.write_text(" ".join(map(str, vector))+"\n")
                    save(config_path, {"function": cases[case_id]["function"], "step_limit": args.step_limit,
                                       "input_file": str(input_path), "output": str(trace_path)})
                    script.write_text("python\nimport sys\nsys.path.insert(0,"+repr(str(ROOT/"tools"))+")\nimport gdb_matrix_trace\ngdb_matrix_trace.main("+repr(str(config_path))+")\nend\n")
                    resources = measure([gdb, "--nx", "--batch", "-iex", "set auto-load off", "-x", script,
                                         "--args", record["binary"]], directory/f"{index}-resources", wall_seconds=args.trace_seconds)
                    resources.pop("samples", None)
                    entry = {"path": str(trace_path), "split": split, "input": vector, "resources": resources,
                             "config_sha256": file_hash(config_path), "script_sha256": file_hash(script), "input_sha256": file_hash(input_path)}
                    group["traces"].append(entry)
                    if trace_path.exists():
                        entry["sha256"] = file_hash(trace_path); trace = read_trace(entry)
                        entry.update({key: trace.get(key) for key in ("status", "steps", "stack_read_failures", "vector_read_failures", "return_value", "max_observed_stack_depth_bytes")})
                        entry["value_observations"] = sum(len(s["values"]) for s in trace.get("samples", []))
                        if trace["status"] == "completed":
                            if trace["return_value"] != targets(case_id, vector)["public_return"]:
                                raise ValueError("traced return differs from independent oracle")
                            entry["return_validated"] = True
                    else:
                        entry["status"] = "missing-trace"
                    save(output/"runtime.json", report)
                complete = all(t["resources"]["status"] == "completed" and t["status"] == "completed" and
                               not t["stack_read_failures"] and not t["vector_read_failures"] for t in group["traces"])
                group["status"] = "observed" if complete else "incomplete-observation"
                save(directory/"group.json", group)
                print(f"{len(report['groups'])}: {case_id}/{profile}/{record['variant']}: {group['status']}", flush=True)
        # All debugger workloads finish before separate measured fitting runs.
        for group in report["groups"]:
            if group["status"] != "observed":
                continue
            directory = Path(group["directory"])
            training = [t for t in group["traces"] if t["split"] == "training"]
            heldout = [t for t in group["traces"] if t["split"] == "heldout"]
            config_path = directory/"fit-config.json"
            save(config_path, {"traces": training, "labels": labels_for(group["case"], [t["input"] for t in training])})
            group["fits"] = []
            first = None
            for repeat in range(args.fit_repetitions):
                answer_path = directory/f"fit-{repeat}.json"
                resources = measure([sys.executable, ROOT/"tools/fit_matrix_runtime.py", config_path, answer_path],
                                     directory/f"fit-{repeat}-resources", wall_seconds=args.fit_seconds)
                resources.pop("samples", None)
                answer = json.loads(answer_path.read_text()) if answer_path.exists() else None
                entry = {"path": str(answer_path), "resources": resources}
                group["fits"].append(entry)
                if answer is None or answer["status"] != "completed" or resources["status"] != "completed":
                    group["status"] = "fit-failed"; break
                entry["sha256"] = file_hash(answer_path)
                if answer["config_sha256"] != file_hash(config_path):
                    raise ValueError("fit configuration changed")
                if first is not None and answer != first:
                    raise ValueError("fixed observer changed its answer across repeated fits")
                first = answer
            if group["status"] != "fit-failed":
                group["targets"] = grade(first, heldout, labels_for(group["case"], [t["input"] for t in heldout]))
                group["status"] = "completed"
            save(directory/"group.json", group)
            save(output/"runtime.json", report)
        if any(file_hash(path) != checksum for path, checksum in bindings.items()):
            raise ValueError("bound artifact, tool or implementation changed")
        report["pairs"] = paired_summary(report["groups"])
        report.update(status="completed" if all(g["status"] == "completed" for g in report["groups"]) else "completed-with-gaps",
                      environment_end=environment())
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        save(output/"runtime.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-report", required=True)
    parser.add_argument("--case", action="append", choices=list(ARITIES), required=True)
    parser.add_argument("--profile", action="append", required=True)
    parser.add_argument("--variant", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--gdb", default="gdb")
    parser.add_argument("--step-limit", type=int, default=2048)
    parser.add_argument("--training", type=int, default=8)
    parser.add_argument("--heldout", type=int, default=12)
    parser.add_argument("--repetitions", type=int, default=1)
    parser.add_argument("--fit-repetitions", type=int, default=3)
    parser.add_argument("--input-seed", type=int, default=19011)
    parser.add_argument("--order-seed", type=int, default=20261113)
    parser.add_argument("--trace-seconds", type=int, default=60)
    parser.add_argument("--fit-seconds", type=int, default=120)
    args = parser.parse_args()
    if ("original" not in args.variant or any(len(v) != len(set(v)) for v in (args.case, args.profile, args.variant)) or
            not 1 <= args.step_limit <= 20000 or not 8 <= args.training <= 128 or not 8 <= args.heldout <= 128 or
            not 1 <= args.repetitions <= 20 or not 1 <= args.fit_repetitions <= 20 or
            not 1 <= args.trace_seconds <= 600 or not 1 <= args.fit_seconds <= 600):
        parser.error("invalid selection or observation budget; original baseline required")
    output = Path(args.output_dir).resolve(); output.mkdir(parents=True, exist_ok=False)
    with measurement_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        result = run(args, output)
    print(result["status"]+": "+str(output/"runtime.json"))
    return int(result["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
