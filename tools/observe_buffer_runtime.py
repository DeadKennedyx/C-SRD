#!/usr/bin/env python3
"""Bounded memory/register observation of the seven declared buffer benchmarks.

Uses unchanged shared objects from audit_buffer_reconstruction.py. Application
I/O is checked against independent finite oracles. Fits never receive encoding
parameters. This does not measure human understanding or exhaustive visibility.
"""
import argparse
from collections import Counter
import fcntl
import json
from pathlib import Path
import sys

from audit_protection import Runner, executable, file_hash, write_json, AuditError
from buffer_observation_cases import cases, driver, expected, LAYOUTS
from effort_resources import measure, environment, measurement_lock

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = ["tools/observe_buffer_runtime.py", "tools/gdb_buffer_trace.py", "tools/buffer_observation_cases.py",
                  "tools/fit_buffer_traces.py", "tools/observe_runtime.py", "tools/effort_resources.py"]


def run(args, root):
    from byte_observation_cases import cases as byte_cases, driver as byte_driver, expected as byte_expected, LAYOUTS as byte_layouts
    selected_cases = byte_cases if args.corpus == "byte" else cases
    selected_driver = byte_driver if args.corpus == "byte" else driver
    selected_layouts = byte_layouts if args.corpus == "byte" else LAYOUTS
    report = {"schema_version": 3, "status": "running", "protocol": vars(args), "commands": [],
              "environment": environment(), "cases": selected_cases(args.input_protocol), "layouts": selected_layouts, "observations": [],
              "claims": {"known_intermediate_targets": True, "seed_or_encoding_given_to_fit": False,
                         "binary_only_algorithm_discovery": False, "human_effort": "not-measured",
                         "exhaustive_visibility": False, "heldout_matches_are_proof": False}}
    command = Runner(report)
    try:
        matrix_path = Path(args.reconstruction_report).resolve(strict=True)
        matrix = json.loads(matrix_path.read_text())
        report["matrix"] = {"path": str(matrix_path), "sha256": file_hash(matrix_path)}
        if matrix["status"] not in ("completed", "completed-with-gaps"):
            raise ValueError("requires a finished buffer reconstruction report")
        gdb = executable(args.gdb)
        report["gdb"] = {"path": gdb, "sha256": file_hash(gdb), "version": command([gdb, "--version"]).splitlines()[0]}
        report["implementation"] = {p: file_hash(ROOT / p) for p in IMPLEMENTATION}
        if args.corpus=="byte": report["implementation"]["tools/byte_observation_cases.py"]=file_hash(ROOT/"tools/byte_observation_cases.py")
        groups = [g for g in matrix["groups"] if (not args.function or g["function"] in args.function)
                  and (not args.profile or g["profile"] in args.profile)]
        if not groups: raise ValueError("no selected groups")
        for key, requested in (("function", args.function), ("profile", args.profile)):
            if requested and set(requested) != {g[key] for g in groups}: raise ValueError(f"missing {key}")
        prepared = []
        # Complete builds before resource measurement.
        for gi, group in enumerate(groups):
            profile = next(p for p in matrix["profiles"] if p["id"] == group["profile"])
            if profile.get("lto") or profile.get("sanitizers") or profile.get("pgo"):
                raise ValueError("runtime observer currently requires ordinary non-LTO/non-instrumented profiles")
            tool = matrix["tools"][profile["compiler"]]
            if file_hash(tool["path"]) != tool["sha256"]: raise ValueError("compiler changed")
            directory = root / f"group-{gi}"; directory.mkdir()
            harness = directory / "harness.c"; harness.write_text(selected_driver(group["function"], group["parameters"]))
            for variant in group["variants"]:
                if file_hash(variant["binary"]) != variant["binary_sha256"]: raise ValueError("library changed")
                executable_path = directory / variant["variant"]
                command([tool["path"], "-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-O2",
                         harness, variant["binary"], "-o", executable_path])
                prepared.append({"group": group, "variant": variant, "executable": str(executable_path),
                                 "executable_sha256": file_hash(executable_path), "directory": directory,
                                 "harness": str(harness), "harness_sha256": file_hash(harness)})
        write_json(root / "runtime.json", report)

        def progress():
            # Raw trace/resource files already persist each attempt. Avoid
            # serializing the entire growing history after every trace.
            write_json(root / "progress.json", {
                "status": "running", "observations_started": len(report["observations"]),
                "observations_finished": sum(o["status"] != "running" for o in report["observations"]),
                "trace_attempts": sum(len(o["traces"]) for o in report["observations"])})

        for prepared_index, item in enumerate(prepared):
            group, variant = item["group"], item["variant"]
            for li, (p, q) in enumerate(selected_layouts):
                directory = item["directory"] / f"{variant['variant']}-layout-{li}"; directory.mkdir()
                observation = {"function": group["function"], "profile": group["profile"], "variant": variant["variant"],
                               "layout": [p, q], "library_sha256": variant["binary_sha256"], "status": "running", "traces": [],
                               **{k: item[k] for k in ("executable", "executable_sha256", "harness", "harness_sha256")}}
                report["observations"].append(observation)
                print(f"{prepared_index+1}/{len(prepared)} {group['function']} {group['profile']} {variant['variant']} layout {li}", flush=True)
                labels = {}
                for ci, case in enumerate(report["cases"]):
                    inputs = directory / f"{ci}.input"
                    inputs.write_text(" ".join(map(str, [p, q, case["x"], *case["memory"]])) + "\n")
                    wanted = byte_expected(group["function"], case["memory"], p, q, case["x"],
                        plain_char_signed=group["parameters"][0].get("element_signed",False)) if args.corpus=="byte" else expected(group["function"], case["memory"], p, q, case["x"])
                    for target, value in wanted["targets"].items(): labels.setdefault(target, []).append(value)
                    trace_path, config_path, script = directory / f"{ci}.trace.json", directory / f"{ci}.json", directory / f"{ci}.gdb"
                    write_json(config_path, {"function": group["function"], "step_limit": args.step_limit,
                                            "sample_bytes": args.corpus=="byte",
                                            "input_file": str(inputs), "output": str(trace_path)})
                    script.write_text("python\nimport sys\nsys.path.insert(0, " + repr(str(ROOT / "tools")) +
                                      ")\nimport gdb_buffer_trace\ngdb_buffer_trace.main(" + repr(str(config_path)) + ")\nend\n")
                    resources = measure([gdb, "--nx", "--batch", "-iex", "set auto-load off", "-x", script,
                                         "--args", item["executable"]], directory / f"{ci}-resources", wall_seconds=60)
                    trace = json.loads(trace_path.read_text()) if trace_path.is_file() else {"status": resources["status"]}
                    record = {"path": str(trace_path), "status": trace["status"], "split": case["split"],
                              "case_index": ci, "steps": trace.get("steps"), "resources": resources,
                              "input_sha256": file_hash(inputs), "configuration_sha256": file_hash(config_path),
                              "gdb_script_sha256": file_hash(script)}
                    if trace_path.is_file(): record["sha256"] = file_hash(trace_path)
                    if resources["status"] != "completed": record["status"] = resources["status"]
                    if record["status"] == "completed":
                        if trace["return_value"] != wanted["return_value"] or trace["final_memory"] != wanted["final_memory"]:
                            record["status"] = "oracle-mismatch"
                        if trace["stack_read_failures"]: record["status"] = "incomplete-memory-sampling"
                    observation["traces"].append(record)
                    progress()
                observation["instruction_steps"] = sum(t.get("steps") or 0 for t in observation["traces"])
                observation["target_executions"] = len(observation["traces"])
                if any(t["status"] != "completed" for t in observation["traces"]):
                    observation["status"] = "incomplete-traces"
                    write_json(directory / "observation.json", observation); progress(); continue
                fit_config = directory / "fit-config.json"
                write_json(fit_config, {"traces": observation["traces"], "targets": labels})
                fit_report = directory / "fit.json"
                observation["fit_resources"] = measure([sys.executable, ROOT / "tools/fit_buffer_traces.py", fit_config, fit_report],
                                                       directory / "fit-resources", wall_seconds=60)
                observation["fit"] = json.loads(fit_report.read_text())
                observation["status"] = observation["fit"]["status"] if observation["fit_resources"]["status"] == "completed" else "fit-budget"
                write_json(directory / "observation.json", observation); progress()
            if file_hash(item["executable"]) != item["executable_sha256"] or file_hash(variant["binary"]) != variant["binary_sha256"]:
                raise ValueError("binary changed during observation")
        for path, expected_hash in report["implementation"].items():
            if file_hash(ROOT / path) != expected_hash: raise ValueError("observer changed during experiment")
        if file_hash(matrix_path) != report["matrix"]["sha256"] or file_hash(gdb) != report["gdb"]["sha256"]:
            raise ValueError("input/tool changed during observation")
        report["outcomes"] = dict(Counter(o["status"] for o in report["observations"]))
        report["status"] = "completed" if set(report["outcomes"]) == {"completed"} else "completed-with-gaps"
        if any(t["status"] == "oracle-mismatch" for o in report["observations"] for t in o["traces"]):
            report["status"] = "failed"
    except KeyboardInterrupt:
        report.update(status="interrupted", error="measurement interrupted; retained traces are partial evidence")
    except (AuditError, OSError, ValueError, KeyError, RuntimeError, StopIteration) as error:
        report.update(status="failed", error=str(error))
    finally:
        write_json(root / "runtime.json", report)
        write_json(root / "progress.json", {"status": report["status"], "observations": len(report["observations"]),
                                            "trace_attempts": sum(len(o["traces"]) for o in report["observations"])})
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reconstruction-report", required=True)
    p.add_argument("--gdb", default="gdb")
    p.add_argument("--function", action="append")
    p.add_argument("--profile", action="append")
    p.add_argument("--step-limit", type=int, default=512)
    p.add_argument("--input-protocol", choices=("basis-parity-v2", "seeded-v1"), default="basis-parity-v2")
    p.add_argument("--corpus", choices=("word","byte"), default="word")
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    if not 1 <= args.step_limit <= 10000: p.error("step limit must be 1..10000")
    root = Path(args.output_dir).resolve(); root.mkdir(parents=True, exist_ok=False)
    with measurement_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = run(args, root)
    print(report["status"], report.get("outcomes", report.get("error")), flush=True)
    return 130 if report["status"] == "interrupted" else int(report["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
