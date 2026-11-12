#!/usr/bin/env python3
"""Build, reconstruct and grade the stable private-region call/loop fixtures.

Linux pilot with GCC/Clang shared libraries and separate, withheld effect oracles.
Stages save durable checkpoints; resource measurements run sequentially.
"""
import argparse
import fcntl
import json
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

from audit_protection import file_hash, write_json
from effort_resources import measure, environment
from region_observation_cases import FIXTURES, FUNCTIONS, driver, vectors, oracle, input_text, effects, parse_output

ROOT = Path(__file__).resolve().parents[1]
VARIANTS = ("original", "identity", "affine-42", "original-copy")


def command(argv, directory, timeout=120, stdin=None):
    start = time.perf_counter()
    result = subprocess.run(list(map(str, argv)), input=stdin, capture_output=True, text=True, timeout=timeout)
    directory.mkdir(parents=True, exist_ok=False)
    (directory/"stdout.txt").write_text(result.stdout)
    (directory/"stderr.txt").write_text(result.stderr)
    if stdin is not None: (directory/"input.txt").write_text(stdin)
    write_json(directory/"command.json", {"argv": list(map(str, argv)), "returncode": result.returncode,
                                          "wall_seconds": time.perf_counter()-start})
    if result.returncode: raise RuntimeError(f"command failed ({result.returncode}): {directory}")
    return result.stdout


def prepare(args):
    root = Path(args.output).resolve(); root.mkdir(parents=True, exist_ok=False)
    tool = Path(args.csrd).resolve()
    report = {"schema_version": 1, "status": "building", "protocol": "private-region-observation-v1",
              "environment": environment(), "csrd": {"path": str(tool), "sha256": file_hash(tool)}, "artifacts": [],
              "script_hashes": {p.name: file_hash(p) for p in [Path(__file__), ROOT/"tools/region_observation_cases.py"]}}
    try:
        for fixture in args.fixture or list(FIXTURES):
            source_name=FIXTURES[fixture]
            source = ROOT/"tests/fixtures"/source_name
            for compiler_name in args.compiler:
                compiler = shutil.which(compiler_name)
                if not compiler: raise ValueError("missing compiler: " + compiler_name)
                family = "clang" if "clang" in compiler_name else "gcc"
                for profile in args.profile:
                    flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-" + profile.split("-")[0]]
                    if profile.endswith("-lto"): flags += ["-flto"] + (["-fuse-ld=lld"] if family == "clang" else [])
                    group = root/fixture/(family+"-"+profile); group.mkdir(parents=True)
                    version = command([compiler, "--version"], group/"compiler-version").splitlines()[0]
                    original = group/"original.c"
                    # Linker choice is irrelevant to preprocessing and Clang warns about it.
                    preflags = [f for f in flags if not f.startswith("-fuse-ld")]
                    command([compiler, *preflags, "-E", "-P", source, "-o", original], group/"preprocess")
                    by_variant = {}
                    for variant in VARIANTS:
                        directory = group/variant; directory.mkdir()
                        current = directory/"source.c"
                        proof = None
                        if variant in ("original", "original-copy"): shutil.copyfile(original, current)
                        else:
                            proof_path = directory/"transform.json"
                            command([tool, "transform", original, "-o", current, "--scope", "private-regions",
                                     "--strategy", "identity" if variant == "identity" else "affine", "--seed", "42", "--report", proof_path], directory/"transform")
                            proof = json.loads(proof_path.read_text())
                            if proof["candidate_sha256"] != file_hash(current): raise ValueError("candidate hash mismatch")
                            if any(f["status"] != "regions-transformed" or f["verification"] != "proved-under-model" or not f["context_bindings_verified"] for f in proof["functions"]):
                                raise ValueError("source frame/binding validation failed")
                        library = directory/"libregions.so"
                        if variant == "original-copy": shutil.copyfile(by_variant["original"]["library"], library)
                        else: command([compiler, *flags, "-fPIC", "-shared", current, "-o", library], directory/"compile-library")
                        record = {"id": f"{fixture}/{family}-{profile}/{variant}", "fixture": fixture, "compiler": compiler,
                                  "compiler_version": version, "compiler_sha256": file_hash(compiler), "profile": profile, "flags": flags,
                                  "variant": variant, "library": str(library), "library_sha256": file_hash(library), "library_bytes": library.stat().st_size,
                                  "source": str(current), "source_sha256": file_hash(current), "original_source_sha256": file_hash(original), "drivers": {},
                                  "frame_validation": None if proof is None else {"path": str(proof_path), "sha256": file_hash(proof_path)}}
                        for function in FUNCTIONS:
                            harness = directory/(function+"-driver.c"); harness.write_text(driver(function))
                            binary = directory/function
                            command([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", "-g", "-rdynamic", "-Wl,-z,now",
                                     harness, library, "-o", binary], directory/(function+"-link"))
                            cases = vectors(function, args.grade_cases)
                            out = command([binary], directory/(function+"-check"), stdin="".join(input_text(v) for v in cases))
                            observed = [parse_output(line) for line in out.splitlines()]
                            if observed != [effects(oracle(fixture, function, v)) for v in cases]: raise ValueError("baseline/candidate differs from effect oracle")
                            record["drivers"][function] = {"path": str(binary), "sha256": file_hash(binary), "harness_sha256": file_hash(harness), "effect_checks": len(cases)}
                        report["artifacts"].append(record); by_variant[variant] = record
                        write_json(root/"build.json", report)
                        print("validated " + record["id"], flush=True)
        report["status"] = "validated"
    except Exception as error:
        report.update(status="failed", error=str(error))
        raise
    finally: write_json(root/"build.json", report)


def checked_artifacts(build):
    if build["status"] != "validated": raise ValueError("requires validated build manifest")
    for record in build["artifacts"]:
        if file_hash(record["library"]) != record["library_sha256"]: raise ValueError("library changed")
        for binary in record["drivers"].values():
            if file_hash(binary["path"]) != binary["sha256"]: raise ValueError("driver changed")
    return build["artifacts"]


def grade(record, function, source, directory, cases_count, reference=None,seed=0x43535244):
    harness = directory/"driver.c"; harness.write_text(driver(function))
    binary = directory/"graded"
    # Grade reconstructed C independently under both compilers. Sanitizers are
    # useful here but run separately from measured analysis commands.
    cases = vectors(function, cases_count, seed=seed)
    expected = [effects(oracle(record["fixture"], function, v)) for v in cases]
    result = {"status": "running", "comparisons": 0, "compilers": []}
    if reference is not None:
        out = command([reference], directory/"reference-execute", stdin="".join(input_text(v) for v in cases))
        if [parse_output(line) for line in out.splitlines()] != expected:
            raise ValueError("independent oracle disagrees with original compiled function on grading inputs")
        result["original_effects_validated"] = len(cases)
    for compiler in ("clang-18", "gcc"):
        try:
            command([compiler, "-std=c11", "-Wall", "-Wextra", "-Werror", "-O2", source, harness, "-o", binary], directory/(compiler+"-compile"))
            out = command([binary], directory/(compiler+"-execute"), stdin="".join(input_text(v) for v in cases))
            actual = [parse_output(line) for line in out.splitlines()]
        except (RuntimeError, subprocess.TimeoutExpired) as error:
            result.update(status="execution-or-compilation-failed", error=str(error)); return result
        if len(actual) != len(expected): result.update(status="incomplete-results"); return result
        mismatches = [i for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
        result["comparisons"] += len(actual)
        result["compilers"].append({"compiler": compiler, "mismatches": len(mismatches)})
        if mismatches:
            i = mismatches[0]
            result["counterexample"] = {"input": cases[i], "expected": expected[i], "actual": actual[i]}
    result["status"] = "mismatch" if any(c["mismatches"] for c in result["compilers"]) else "tested-equivalent"
    return result


def reconstruct_all(args):
    manifest = Path(args.build).resolve(); build = json.loads(manifest.read_text())
    records = checked_artifacts(build)
    root = Path(args.output).resolve(); root.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "status": "observing", "build_sha256": file_hash(manifest), "build": str(manifest),
              "environment": environment(), "records": [], "claims": {"whole_function_proof": False, "human_effort": "unmeasured"},
              "observer_hashes": {p.name: file_hash(p) for p in [ROOT/"tools/ghidra/ExportCSRDRegions.java", ROOT/"tools/pcode_regions.py", ROOT/"tools/pcode_cfg.py", ROOT/"tools/pcode_values.py"]},
              "grader_hashes":{p.name:file_hash(p) for p in [Path(__file__), ROOT/"tools/region_observation_cases.py"]}}
    report["grading_protocol"]={"cases":args.grade_cases,"seed":args.grade_seed}
    headless=Path(args.ghidra).resolve()
    if not headless.is_file(): raise ValueError("Ghidra headless executable unavailable: "+str(headless))
    distribution=headless.parent.parent
    report["decompiler_files"]={str(path.relative_to(distribution)):file_hash(path) for path in [
        headless,distribution/"Ghidra/Features/Decompiler/os/linux_arm_64/decompile",
        distribution/"Ghidra/Processors/AARCH64/data/languages/AARCH64base.sinc",
        distribution/"Ghidra/Processors/AARCH64/data/languages/AARCH64.sla"] if path.is_file()}
    jobs = [(r, f, n) for r in records for f in FUNCTIONS for n in range(args.repetitions)]
    random.Random(20261110).shuffle(jobs)
    try:
        for serial, (record, function, repetition) in enumerate(jobs):
            directory = root/f"{serial:04d}"; directory.mkdir()
            export_dir = directory/"export"; export_dir.mkdir()
            project = directory/"project"; project.mkdir()
            item = {"artifact": record["id"], "function": function, "repetition": repetition, "directory": str(directory),
                    "library_sha256": record["library_sha256"], "status": "observing"}
            report["records"].append(item)
            item["decompilation"] = measure([args.ghidra, project, "regions", "-import", record["library"], "-deleteProject", "-max-cpu", "2",
                                             "-analysisTimeoutPerFile", "30", "-scriptPath", ROOT/"tools/ghidra", "-postScript", "ExportCSRDRegions.java",
                                             function, FUNCTIONS[function], "15", export_dir], directory/"decompile-resources", wall_seconds=120)
            # Large resource series stay in their own file; avoid quadratic reports.
            item["decompilation"].pop("samples", None)
            export = export_dir/"export.json"
            if item["decompilation"]["status"] != "completed": item["status"] = item["decompilation"]["status"]
            elif not export.exists(): item["status"] = "export-failed"
            else:
                item["export_sha256"] = file_hash(export)
                item["adapter"] = measure([sys.executable, ROOT/"tools/pcode_regions.py", export, directory/"recovered.c"], directory/"adapter-resources", wall_seconds=30)
                item["adapter"].pop("samples", None)
                item["reconstruction"] = json.loads((directory/"recovered.c.json").read_text())
                item["status"] = item["reconstruction"]["status"]
                if item["adapter"]["status"] != "completed" and item["status"] != "unsupported": item["status"] = item["adapter"]["status"]
                if (directory/"recovered.c").exists(): item["recovered_sha256"] = file_hash(directory/"recovered.c")
            write_json(root/"reconstruction.json", report)
            print(f"observed {serial+1}/{len(jobs)} {record['id']} {function}: {item['status']}", flush=True)
        # No grader source/oracle/feedback is supplied during observer execution.
        lookup = {r["id"]:r for r in records}
        for item in report["records"]:
            if item["status"] != "reconstructed": continue
            directory = Path(item["directory"]); grading = directory/"grade"; grading.mkdir()
            if file_hash(directory/"recovered.c") != item["recovered_sha256"]: raise ValueError("recovered file changed")
            original = lookup[item["artifact"].rsplit("/",1)[0]+"/original"]
            reference = original["drivers"][item["function"]]["path"]
            item["grading"] = grade(lookup[item["artifact"]], item["function"], directory/"recovered.c", grading, args.grade_cases, reference,args.grade_seed)
            item["status"] = item["grading"]["status"]
            write_json(root/"reconstruction.json", report)
        report["controls"] = []
        # Deliberate errors on each of the four contracts, separate from timed
        # reconstruction. These test the effect grader, not protection strength.
        for item in report["records"]:
            if not item["artifact"].endswith("/clang-O2/original") or item["repetition"] != 0 or item["status"] != "tested-equivalent": continue
            from pcode_regions import reconstruct
            directory = Path(item["directory"])
            export = json.loads((directory/"export/export.json").read_text())
            for mutation in ("return", "store", "call-argument", "drop-call", "branch"):
                if mutation == "branch" and item["function"] != "region_pipeline": continue
                control_dir = directory/("control-"+mutation); control_dir.mkdir()
                source = control_dir/"mutant.c"; source.write_text(reconstruct(export, mutation=mutation))
                result = grade(lookup[item["artifact"]], item["function"], source, control_dir, args.grade_cases,seed=args.grade_seed)
                report["controls"].append({"artifact":item["artifact"], "function":item["function"], "mutation":mutation,
                                           "directory":str(control_dir), "result":result})
        checked_artifacts(build)
        if file_hash(manifest) != report["build_sha256"]: raise ValueError("build manifest changed")
        report["status"] = "completed"
    except Exception as error: report.update(status="failed", error=str(error)); raise
    finally: write_json(root/"reconstruction.json", report)


def main():
    p = argparse.ArgumentParser(description=__doc__); sub = p.add_subparsers(dest="stage", required=True)
    a = sub.add_parser("prepare"); a.add_argument("--csrd", required=True); a.add_argument("--compiler", action="append", required=True)
    a.add_argument("--profile", choices=("O0", "O2", "O3", "Os", "O2-lto"), action="append", required=True)
    a.add_argument("--fixture",choices=tuple(FIXTURES),action="append")
    b = sub.add_parser("reconstruct"); b.add_argument("--build", required=True); b.add_argument("--ghidra", required=True)
    b.add_argument("--repetitions", type=int, default=1)
    b.add_argument("--grade-seed",type=int,default=0x43535244)
    for parser in (a,b):
        parser.add_argument("--output", required=True); parser.add_argument("--grade-cases", type=int, default=256)
    args = p.parse_args()
    if args.grade_cases < 32 or getattr(args, "repetitions", 1) < 1: p.error("at least 32 grading inputs and one repetition required")
    if not 0<=getattr(args,"grade_seed",0)<2**64:p.error("grading seed must be a uint64")
    with (ROOT/"experiments/runs/effort.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        prepare(args) if args.stage == "prepare" else reconstruct_all(args)


if __name__ == "__main__": main()
