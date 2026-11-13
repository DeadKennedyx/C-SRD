#!/usr/bin/env python3
"""Matched project build/runtime measurements with an independent behavior oracle.

This small corpus tests project integration, not general obfuscation strength.
The pass combination is affine followed by identity, a composition control.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import random
import shutil
import statistics
import subprocess
import sys

from effort_resources import environment, measure, measurement_lock, save
from evaluate import object_metrics
import project_fixture
from transform_project import build_project, digest

PROFILES = {"O0": ["-O0"], "O2": ["-O2"], "O3": ["-O3"], "Os": ["-Os"],
            "lto": ["-O2", "-flto"], "sanitize": ["-O1", "-g", "-fsanitize=address,undefined", "-fno-omit-frame-pointer"]}


def run(args):
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    tool = root / "csrd"
    shutil.copy2(args.csrd.resolve(), tool)
    report = {"schema_version": 1, "status": "running", "environment": environment(), "cells": [],
              "csrd_sha256": digest(tool), "seed": 4298189, "repetitions": args.repetitions,
              "iterations": args.iterations, "random_cases": args.cases,
              "bindings": {str(Path(__file__).resolve()): digest(__file__),
                           str(Path(project_fixture.__file__).resolve()): digest(project_fixture.__file__),
                           str(Path(__file__).with_name("transform_project.py").resolve()): digest(Path(__file__).with_name("transform_project.py")),
                           str(Path(__file__).with_name("effort_resources.py").resolve()): digest(Path(__file__).with_name("effort_resources.py")),
                           str(Path(__file__).with_name("evaluate.py").resolve()): digest(Path(__file__).with_name("evaluate.py"))},
              "scope": "one multi-file buffer pipeline; observed stdout, exit status, stderr and complete output file including buffer guard",
              "timing_scope": "whole process including startup, allocation and file I/O; repeat work inside process; no timing claim from sanitizer cells",
              "reconstruction_effort": "not measured; project-build integration introduces no new obfuscation technique",
              "runtime_value_recovery": "not measured on this project", "whole_program_proof": "not established"}
    target = root / "matrix.json"
    if args.objdump:
        report["objdump"] = {"path": str(args.objdump), "sha256": digest(args.objdump)}
    save(target, report)
    for compiler_spec in args.compiler:
        name, path = compiler_spec.split("=", 1)
        if not name.replace("-", "").replace("_", "").isalnum():
            raise ValueError("simple compiler label required")
        compiler = shutil.which(path)
        if compiler is None:
            raise ValueError("compiler unavailable: " + path)
        version = subprocess.check_output([compiler, "--version"], text=True)
        offset = 11 if "clang" in version.lower() else 13
        for profile in args.profile:
            directory = root / f"{name}-{profile}"
            directory.mkdir()
            cell = {"compiler": compiler, "compiler_sha256": digest(compiler), "version": version,
                    "profile": profile, "flags": PROFILES[profile], "status": "running", "correctness": [], "costs": []}
            report["cells"].append(cell)
            save(target, report)
            try:
                spec = project_fixture.create(directory / "source", compiler, PROFILES[profile])
                if args.transform_command is not None:
                    configured = json.loads(spec.read_text())
                    configured["transform_commands"] = args.transform_command
                    save(spec, configured)
                cell["transform_commands"] = args.transform_command if args.transform_command is not None else [0, 1, 2]
                build = build_project(tool, spec, directory / "artifacts")
                cell["manifest"] = str(directory / "artifacts/manifest.json")
                cell["manifest_sha256"] = digest(cell["manifest"])
                cell["build_costs"] = {}
                for variant in build["builds"]:
                    jobs = [m for m in build["measurements"] if m["label"].startswith((f"compile-{variant}-", f"link-{variant}-"))]
                    cell["build_costs"][variant] = {"cpu_seconds": sum(m["cpu_seconds"] for m in jobs),
                                                     "command_wall_seconds": sum(m["wall_seconds"] for m in jobs),
                                                     "max_process_rss_bytes": max(m["peak_process_rss_bytes"] for m in jobs)}
                programs = {variant: Path(data["links"][0]["path"]) for variant, data in build["builds"].items()}
                copy = directory / "original-copy"
                shutil.copy2(programs["original"], copy)
                if digest(copy) != digest(programs["original"]):
                    raise AssertionError("identical-binary control differs")
                programs["original_copy"] = copy
                cell["copy_control_sha256"] = digest(copy)
                rng = random.Random(report["seed"])
                vectors = [(0, 0, 0), (0xffffffff, 0, 1), (0xffffffff, 1, 1), (0xffffffff, 64, 3),
                           (0x80000000, 64, 0), (0x7fffffff, 31, 9), (1, 1, 5), (0, 64, 5)]
                vectors += [(rng.getrandbits(32), rng.randrange(65), rng.randrange(10)) for _ in range(args.cases)]
                cell["vectors"] = vectors
                for variant, binary in programs.items():
                    passed = 0
                    observations = []
                    for seed, count, repeats in vectors:
                        stdout, file_data = project_fixture.check(binary, directory, seed, count, repeats, offset)
                        observations.append({"input": [seed, count, repeats], "stdout_sha256": hashlib.sha256(stdout).hexdigest(),
                                             "output_file_sha256": hashlib.sha256(file_data).hexdigest()})
                        passed += 1
                    # Observable failure path: inability to open the requested output.
                    failure = subprocess.run([str(binary), "17", "7", "3", str(directory / "missing" / "result")],
                                             capture_output=True, timeout=30)
                    if (failure.returncode, failure.stdout, failure.stderr) != (5, b"", b""):
                        raise AssertionError("file-open failure behavior differs")
                    cell["correctness"].append({"variant": variant, "passed": passed, "file_open_failure_checked": True,
                                                 "observations": observations})
                # Independent negative control: the specified result for a different input
                # must not pass the same oracle. It checks grader discrimination, not an
                # estimate of false-positive probability across unrelated applications.
                wrong_stdout, wrong_file = project_fixture.oracle(18, 7, 3, offset)
                right_stdout, right_file = project_fixture.check(programs["original"], directory, 17, 7, 3, offset)
                if (wrong_stdout, wrong_file) == (right_stdout, right_file):
                    raise AssertionError("negative oracle control is uninformative")
                cell["negative_oracle_control"] = "different-input result rejected"
                cell["structure"] = {}
                if args.objdump:
                    def command(argv):
                        done = subprocess.run(list(map(str, argv)), capture_output=True, text=True, timeout=120, check=True)
                        return done.stdout, 0
                    for variant, binary in programs.items():
                        metrics = object_metrics(str(args.objdump), str(binary), command)
                        metrics["scope"] = "whole linked executable text section including startup, padding and instrumentation; structural evidence only"
                        metrics["binary_bytes"] = binary.stat().st_size
                        metrics["binary_sha256"] = digest(binary)
                        baseline = cell["structure"].get("original", metrics)
                        metrics["text_identical_to_original"] = metrics["text_sha256"] == baseline["text_sha256"]
                        metrics["text_ratio_to_original"] = metrics["text_bytes"] / baseline["text_bytes"]
                        cell["structure"][variant] = metrics
                else:
                    cell["structure_status"] = "not measured; --objdump not provided"
                # Application costs are collected after correctness, serially with
                # randomized matched order. Build cost collectors are already finished.
                runtime_input = [0xffffffff, 64, args.iterations]
                expected_stdout, expected_file = project_fixture.oracle(*runtime_input, offset)
                for repetition in range(args.repetitions):
                    order = list(programs)
                    rng.shuffle(order)
                    for variant in order:
                        result_file = directory / f"runtime-{repetition}-{variant}.txt"
                        output = directory / "runtime" / f"{repetition}-{variant}"
                        resource = measure([str(programs[variant]), *map(str, runtime_input), str(result_file)], output, wall_seconds=120)
                        if resource["status"] != "completed" or (output / "stdout.txt").read_bytes() != expected_stdout or (output / "stderr.txt").stat().st_size or result_file.read_bytes() != expected_file:
                            raise AssertionError("timed application behavior differs: " + variant)
                        cell["costs"].append({"variant": variant, "repetition": repetition,
                                              **{k: v for k, v in resource.items() if k != "samples"}})
                cell["ratios"] = {}
                originals = {r["repetition"]: r for r in cell["costs"] if r["variant"] == "original"}
                for variant in programs:
                    cell["ratios"][variant] = {}
                    for key in ("wall_seconds", "cpu_seconds", "peak_process_rss_bytes"):
                        paired = [r[key] / originals[r["repetition"]][key] for r in cell["costs"] if r["variant"] == variant and originals[r["repetition"]][key]]
                        cell["ratios"][variant][key] = {"median": statistics.median(paired), "min": min(paired), "max": max(paired), "samples": len(paired)}
                cell["status"] = "completed"
            except Exception as error:
                cell["status"], cell["error"] = "failed", str(error)
            save(target, report)
            print(f"{name}-{profile}: {cell['status']}", flush=True)
    report["status"] = "completed" if all(c["status"] == "completed" for c in report["cells"]) else "completed-with-failures"
    save(target, report)
    return 0 if report["status"] == "completed" else 1


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csrd", required=True, type=Path)
    p.add_argument("--compiler", action="append", required=True, help="label=compiler-path")
    p.add_argument("--profile", action="append", choices=PROFILES)
    p.add_argument("--objdump", type=Path)
    p.add_argument("--transform-command", action="append", type=int, help="select a fixture translation unit (0=map, 1=reduce, 2=main); repeatable")
    p.add_argument("--repetitions", type=int, default=5)
    p.add_argument("--iterations", type=int, default=100000)
    p.add_argument("--cases", type=int, default=24)
    p.add_argument("--output-dir", required=True, type=Path)
    args = p.parse_args()
    args.profile = args.profile or ["O0", "O2"]
    if args.repetitions < 1 or not 1 <= args.iterations <= 10000000 or args.cases < 0:
        p.error("positive repetitions/iterations and nonnegative random cases required")
    with measurement_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return run(args)


if __name__ == "__main__":
    sys.exit(main())
