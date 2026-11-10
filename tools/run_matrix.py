#!/usr/bin/env python3
"""Execute a declared C-SRD validation matrix, then prioritize measured candidates.

Profiles are read from versioned JSON. Unsupported capabilities are explicit.
Only admitted pure functions are transformed; linked harnesses are trusted C11.
"""
import argparse
import json
import math
import os
from pathlib import Path
import platform
import re
import shutil
import sys
from types import SimpleNamespace

import audit_protection as audit
from experiment_support import (assembly_metrics, digest, driver_source, input_vectors,
                                ir_structure, outputs, paired_costs, reconstruct, select_candidates)

ROOT = Path(__file__).resolve().parents[1]


def validate_manifest(manifest):
    if manifest.get("schema_version") != 1:
        raise ValueError("unsupported matrix schema")
    for key in ("cases", "profiles"):
        entries = manifest.get(key, [])
        ids = [e.get("id", "") for e in entries]
        if not entries or len(set(ids)) != len(ids) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", i) for i in ids):
            raise ValueError(f"{key} require unique safe identifiers")
    if any(c.get("split") not in ("development", "heldout") for c in manifest["cases"]):
        raise ValueError("unknown corpus split")


def flags_for(profile, family):
    if profile["optimization"] not in ("O0", "O1", "O2", "O3", "Os", "Oz", "Og"):
        raise ValueError("unknown optimization profile")
    flags = []
    lto = profile.get("lto", "none")
    if lto not in ("none", "full", "thin"):
        raise ValueError("unknown LTO mode")
    if lto != "none":
        if family == "gcc" and lto == "thin":
            raise ValueError("ThinLTO is not a GCC profile")
        flags.append("-flto" if lto == "full" else "-flto=thin")
    if profile.get("sanitizers"):
        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all"]
    cpu = profile.get("cpu", "default")
    if cpu == "native":
        flags.append("-mcpu=native" if platform.machine().lower() in ("arm64", "aarch64") else "-march=native")
    elif cpu != "default":
        raise ValueError("unknown CPU profile")
    return flags


def find_tool(value):
    return audit.executable(value)


def tool_identity(command, value):
    path = find_tool(value)
    return {"path": path, "sha256": audit.file_hash(path),
            "version": command([path, "--version"]).splitlines()[0]}


def prepare_variants(args, case, directory, command):
    source = (ROOT / case["source"]).resolve(strict=True)
    analysis_path = directory / "analysis.json"
    command([args.csrd, "analyze", source, "--report", analysis_path])
    analysis = json.loads(analysis_path.read_text())
    function = audit.require_one_function(analysis)
    if not 1 <= function["parameter_count"] <= 4:
        raise ValueError("matrix requires one to four parameters")
    variants = [{"id": "original", "path": str(source), "sha256": audit.file_hash(source), "control": "original"}]
    algorithms = ["none", *case.get("algorithms", [])]
    for algorithm in algorithms:
        for strategy in args.strategies:
            for seed, flow in [(seed, flow) for seed in ([0] if strategy == "identity" else args.seeds)
                               for flow in args.control_flows]:
                stem = ("" if algorithm == "none" else algorithm + "-") + strategy
                if strategy != "identity":
                    stem += "-" + str(seed)
                flow_control = stem
                if flow != "none":
                    stem += "-" + flow
                out = directory / stem
                out.mkdir()
                candidate, report = out / "candidate.c", out / "transformation.json"
                argv = [args.csrd, "transform", source, "-o", candidate,
                        "--strategy", strategy, "--seed", seed, "--report", report, "--control-flow", flow,
                        "--timeout-ms", args.timeout_ms]
                if algorithm != "none":
                    argv += ["--algorithm", algorithm]
                command(argv)
                manifest = json.loads(report.read_text())
                if any(f.get("verification") != "proved-under-model" or f["status"] != "transformed"
                       for f in manifest["functions"]):
                    raise ValueError("candidate was not transformed and verified")
                control = "identity" if algorithm == "none" else algorithm + "-identity"
                if flow != "none":
                    control += "-" + flow
                variants.append({"id": stem, "path": str(candidate), "sha256": audit.file_hash(candidate),
                                 "control": control, "algorithm": algorithm, "strategy": strategy, "seed": seed,
                                 "control_flow": flow, "control_flow_control": flow_control,
                                 "split_scales": sum(f.get("split_scales", 0) for f in manifest["functions"]),
                                 "manifest": str(report), "manifest_sha256": audit.file_hash(report)})
    return function, variants, analysis["target"]


def validate_inputs(args, compiler, profile, extra_flags, original, variant, root):
    root.mkdir()
    result = audit.run(SimpleNamespace(
        csrd=args.csrd, objdump=args.objdump, compiler=[compiler], original=original, candidate=variant,
        optimization=[profile["optimization"]], compile_flags=extra_flags,
        validation_only=True, timeout_ms=args.timeout_ms), root)
    if result["status"] != "completed":
        raise audit.AuditError(f"build validation failed: {result.get('error')}; {root / 'audit.json'}")
    config = result["configurations"][0]
    if config["status"] != "validated-build-inputs" or len(config.get("build_validation", {})) != 2:
        raise audit.AuditError("incomplete build-input validation")
    path = root / config["build_validation"]["candidate"]["preprocessed_path"]
    return path, config["flags"], result


def compile_link(command, compiler, flags, frozen, driver, directory):
    obj, harness, binary = directory / "function.o", directory / "driver.o", directory / "program"
    # Profile-use checks source locations. Keep a stable path in both phases,
    # while retaining each independently validated frozen input as evidence.
    stable = directory / "function.i"
    shutil.copyfile(frozen, stable)
    snapshot = audit.file_hash(frozen)
    command([compiler, *flags, "-c", stable, "-o", obj])
    if audit.file_hash(stable) != snapshot or audit.file_hash(frozen) != snapshot:
        raise audit.AuditError("frozen input changed during compilation")
    command([compiler, *flags, "-c", driver, "-o", harness])
    command([compiler, *flags, obj, harness, "-o", binary])
    return binary


def build_record(args, command, compiler, family, profile, function, variant, original, directory):
    extra = flags_for(profile, family)
    driver = directory / "driver.c"
    driver.write_text(driver_source(function["function"], function["parameter_count"]))
    # GNU profiling uses stable object names in both phases; Clang uses a merged indexed profile.
    profile_data = directory / "profile"
    profile_data.mkdir()
    pgo = profile.get("pgo", False)
    training = None
    if pgo:
        generate = (["-fprofile-instr-generate=" + str(profile_data / "train.profraw")]
                    if family == "clang" else ["-fprofile-generate=" + str(profile_data)])
        frozen, flags, _ = validate_inputs(args, compiler, profile, extra + generate,
                                           original, variant["path"], directory / "training-validation")
        binary = compile_link(command, compiler, flags, frozen, driver, directory)
        training_inputs = input_vectors(function["parameter_count"], 701, args.inputs)
        training = {"seed": 701, "vectors_sha256": digest(training_inputs), "count": len(training_inputs)}
        outputs(command, binary, training_inputs)
        if family == "clang":
            profdata = find_tool(args.profdata)
            command([profdata, "merge", "-output=" + str(profile_data / "train.profdata"),
                     profile_data / "train.profraw"])
            extra += ["-fprofile-instr-use=" + str(profile_data / "train.profdata")]
        else:
            extra += ["-fprofile-use=" + str(profile_data), "-fprofile-correction"]
    frozen, flags, validation = validate_inputs(args, compiler, profile, extra, original,
                                                variant["path"], directory / "validation")
    frozen_hash = audit.file_hash(frozen)
    binary = compile_link(command, compiler, flags, frozen, driver, directory)
    if audit.file_hash(frozen) != frozen_hash or audit.file_hash(variant["path"]) != variant["sha256"]:
        raise audit.AuditError("validated input changed before linked measurement")
    assembly = command([args.objdump, "--disassemble", "--no-show-raw-insn", binary])
    (directory / "linked.asm").write_text(assembly)
    metrics = assembly_metrics(assembly, [function["function"], "main"])
    record = {"binary": str(binary), "binary_sha256": audit.file_hash(binary),
              "binary_bytes": binary.stat().st_size, "flags": flags, "linked": metrics,
              "preprocessed_sha256": frozen_hash, "driver_sha256": audit.file_hash(driver),
              "validation": str(directory / "validation/audit.json"),
              "source_verification": validation["claims"]["source_equivalence"],
              "pgo_training": training, "llvm_ir": {"status": "not-available-for-this-compiler"}}
    record["profile_artifacts"] = [{"path": str(p), "sha256": audit.file_hash(p)}
                                   for p in sorted(profile_data.rglob("*")) if p.is_file()]
    if family == "clang" and not pgo:
        ir = directory / "function.ll"
        command([compiler, *flags, "-S", "-emit-llvm", frozen, "-o", ir])
        record["llvm_ir"] = {"status": "measured", "path": str(ir),
                             "sha256": audit.file_hash(ir), **ir_structure(ir.read_text(), function["function"])}
    return record


def probe_profile(args, command, compiler, family, profile, directory):
    """Compile AND link a separate capability probe before evaluating any candidate."""
    directory.mkdir()
    if profile.get("pgo") and family == "clang":
        tool_identity(command, args.profdata)
    extra = flags_for(profile, family)
    if profile.get("pgo"):
        extra += (["-fprofile-instr-generate=" + str(directory / "probe.profraw")]
                  if family == "clang" else ["-fprofile-generate=" + str(directory / "profile")])
    probe = directory / "probe.c"
    probe.write_text(audit.MODEL_GUARD + "\nint main(void){return 0;}\n")
    binary = directory / "probe"
    command([compiler, "-std=c11", "-" + profile["optimization"], *extra, "-Wl,-v", probe, "-o", binary])
    command([binary])


def run(args, root):
    manifest_path = Path(args.matrix).resolve()
    manifest = json.loads(manifest_path.read_text())
    validate_manifest(manifest)
    report = {"schema_version": 1, "status": "running", "commands": [], "records": [],
              "implementation": {str(p.relative_to(ROOT)): audit.file_hash(p) for p in
                                 [ROOT / "tools" / name for name in
                                  ("run_matrix.py", "audit_protection.py", "experiment_support.py", "evaluate.py")]},
              "profiles": [], "cases": [], "platform": platform.platform(),
              "machine": platform.machine(), "processor": platform.processor(), "cpu_count": os.cpu_count(),
              "timing_scope": "shared host, interleaved paired samples; no isolation or statistical significance claim",
              "manifest": {"path": str(manifest_path), "sha256": audit.file_hash(manifest_path), "content": manifest},
              "claims": {"machine_code_equivalence": "not-proved", "human_reconstruction_effort": "not-assessed",
                         "memory_exposure": "requires-separate-runtime-observer", "confidentiality": "not-established"}}
    command = audit.Runner(report)
    try:
        args.csrd, args.objdump = find_tool(args.csrd), find_tool(args.objdump)
        report["tools"] = {k: tool_identity(command, getattr(args, k)) for k in ["csrd", "objdump"]}
        report["settings"] = {"tier": args.tier, "seeds": args.seeds, "strategies": args.strategies,
                              "control_flows": args.control_flows,
                              "selection_policy": "report-only" if args.no_select else "screen",
                              "case_filter": args.case, "profile_filter": args.profile,
                              "inputs": args.inputs, "iterations": args.iterations, "repetitions": args.repetitions}
        frozen = None
        if args.tier == "holdout":
            if not args.selection:
                raise ValueError("holdout runs require a frozen development selection")
            frozen = json.loads(Path(args.selection).read_text())
            if frozen.get("status") not in ("completed", "completed-with-gaps") or frozen["settings"]["tier"] == "holdout":
                raise ValueError("holdout requires a completed development experiment")
            if (frozen["settings"]["seeds"] != args.seeds or frozen["settings"]["strategies"] != args.strategies
                    or frozen["settings"].get("control_flows", ["none"]) != args.control_flows):
                raise ValueError("holdout must use the frozen development seeds, strategies and control-flow candidates")
            if frozen["settings"].get("selection_policy", "screen") != report["settings"]["selection_policy"]:
                raise ValueError("holdout must preserve the development selection policy")
            report["development_sha256"] = audit.file_hash(args.selection)
        selected_profiles = [p for p in manifest["profiles"] if args.tier in p["tiers"]]
        if args.profile:
            selected_profiles = [p for p in selected_profiles if p["id"] in args.profile]
            if {p["id"] for p in selected_profiles} != set(args.profile):
                raise ValueError("requested profile is absent from the selected tier")
        if not selected_profiles:
            raise ValueError("no selected profiles")
        cases = [c for c in manifest["cases"] if c["split"] == ("heldout" if args.tier == "holdout" else "development")]
        if args.case:
            cases = [c for c in cases if c["id"] in args.case]
            if {c["id"] for c in cases} != set(args.case):
                raise ValueError("requested case absent from split")
        if not cases:
            raise ValueError("no cases")
        compiler_map = dict(s.split("=", 1) for s in args.compiler)
        available = []
        for profile in selected_profiles:
            p = {**profile, "status": "unassessed"}
            report["profiles"].append(p)
            directory = root / ("probe-" + profile["id"])
            try:
                if profile.get("target", "native") not in ("native", audit.target_architecture(platform.machine())):
                    p.update(status="unavailable", reason="target requires a matching execution/frontend environment")
                    continue
                if profile.get("system") and profile["system"] != sys.platform:
                    p.update(status="unavailable", reason="profile requires a different OS")
                    continue
                family = profile["compiler"]
                compiler = tool_identity(command, compiler_map.get(family, family))
                actual = "clang" if "clang" in compiler["version"].lower() else "gcc" if "gcc" in compiler["version"].lower() else "unknown"
                if actual != family:
                    raise ValueError(f"expected {family}, found {actual}")
                p["tool"] = compiler
                if profile.get("pgo") and family == "clang":
                    p["profdata"] = tool_identity(command, args.profdata)
                p["target_triple"] = command([compiler["path"], "-dumpmachine"]).strip()
                probe_profile(args, command, compiler["path"], family, profile, directory)
                p["status"] = "available"
                available.append(p)
            except (audit.AuditError, OSError, ValueError) as error:
                p.update(status="unavailable", reason=str(error))
        for case in cases:
            directory = root / case["id"]
            directory.mkdir()
            function, variants, target = prepare_variants(args, case, directory, command)
            report["cases"].append({**case, "function": function["function"],
                                    "arity": function["parameter_count"], "target": target, "variants": variants})
            for profile in available:
                print(f"{case['id']}: {profile['id']}", flush=True)
                cells = []
                vectors = input_vectors(function["parameter_count"], 702, args.inputs)
                heldout = input_vectors(function["parameter_count"], 703, args.inputs)
                # A declared rare-difference challenge prevents presenting a known blind spot as validation.
                if function["parameter_count"] == 2:
                    heldout.append((0x43535244, 0))
                expected = None
                for variant in variants:
                    cell = {"case": case["id"], "family": case["family"], "split": case["split"],
                            "variant": variant["id"], "control": variant["control"],
                            "strategy": variant.get("strategy", "original"),
                            "control_flow": variant.get("control_flow", "none"),
                            "control_flow_control": variant.get("control_flow_control", "original"),
                            "split_scales": variant.get("split_scales", 0),
                            "profile": profile["id"], "status": "failed"}
                    report["records"].append(cell)
                    build_dir = directory / ("build-" + profile["id"] + "-" + variant["id"])
                    build_dir.mkdir()
                    try:
                        if (audit.target_architecture(profile["target_triple"]) != audit.target_architecture(target)
                                or audit.target_system(profile["target_triple"]) != audit.target_system(target)):
                            raise ValueError("compiler/frontend target mismatch")
                        cell.update(build_record(args, command, profile["tool"]["path"], profile["compiler"],
                                                 profile, function, variant, variants[0]["path"], build_dir))
                        discovery_values = outputs(command, cell["binary"], vectors)
                        heldout_values = outputs(command, cell["binary"], heldout)
                        if expected is None:
                            if variant["id"] != "original":
                                raise ValueError("original execution is unavailable")
                            expected = (discovery_values, heldout_values)
                        elif expected != (discovery_values, heldout_values):
                            raise ValueError("linked executable differential mismatch")
                        cell["execution"] = {"status": "tested", "comparisons": len(vectors) + len(heldout),
                                             "inputs_sha256": digest([vectors, heldout]),
                                             "discovery_fingerprint": digest(discovery_values),
                                             "heldout_fingerprint": digest(heldout_values)}
                        cell["reconstruction"] = reconstruct(command, cell["binary"], function["parameter_count"],
                                                               heldout, heldout_values)
                        cell["status"] = "completed"
                        cells.append(cell)
                    except (audit.AuditError, OSError, ValueError, KeyError) as error:
                        cell["error"] = str(error)
                if cells and cells[0]["variant"] == "original":
                    try:
                        paired_costs(command, cells, args.iterations, args.repetitions, 704)
                        by_id = {c["variant"]: c for c in cells}
                        base = by_id["original"]
                        for cell in cells:
                            control = by_id.get(cell["control"])
                            flow_control = by_id.get(cell["control_flow_control"])
                            cell["comparison"] = {
                                "instruction_sequences_differ_from_control_flow_control": None if not flow_control else cell["linked"]["opcode_sha256"] != flow_control["linked"]["opcode_sha256"],
                                "instruction_sequences_differ_from_original": cell["linked"]["opcode_sha256"] != base["linked"]["opcode_sha256"],
                                "instruction_sequences_differ_from_algorithm_control": None if not control else cell["linked"]["opcode_sha256"] != control["linked"]["opcode_sha256"],
                                "prelink_ssa_differs_from_original": None if cell["llvm_ir"]["status"] != "measured" else cell["llvm_ir"]["ssa_sha256"] != base["llvm_ir"]["ssa_sha256"]}
                    except (audit.AuditError, OSError, ValueError) as error:
                        for cell in cells:
                            cell.update(status="failed", error=f"cost measurement failed: {error}")
                audit.write_json(root / "matrix.json", report)
        # Fingerprint false matches/missed equivalences use corpus labels only at scoring.
        from evaluate import score
        report["recognition_scores"] = {}
        for profile in available:
            records = [{"id": r["case"] + "/" + r["variant"], "family": r["family"],
                        "discovery": r["execution"]["discovery_fingerprint"],
                        "heldout": r["execution"]["heldout_fingerprint"]}
                       for r in report["records"] if r["profile"] == profile["id"] and r["status"] == "completed"]
            # Unary and binary interfaces are scored separately.
            for arity in sorted({c["arity"] for c in report["cases"]}):
                ids = {c["id"] for c in report["cases"] if c["arity"] == arity}
                group = [r for r in records if r["id"].split("/")[0] in ids]
                report["recognition_scores"][profile["id"] + f"/arity-{arity}"] = {
                    "discovery": score(group, "discovery"), "heldout": score(group, "heldout")}
        required = [p["id"] for p in selected_profiles if p.get("selection_required")]
        if args.tier == "holdout":
            if audit.file_hash(args.selection) != report["development_sha256"]:
                raise ValueError("development selection changed during held-out evaluation")
            report["selection"] = {"status": "not-reranked", "development_sha256": report["development_sha256"],
                                    "frozen_selection": frozen["selection"],
                                    "scope": "new-case evaluation of frozen candidate families; no claim that a per-case choice generalizes"}
        elif args.no_select:
            report["selection"] = {"status": "not-performed", "reason": "explicit report-only exploration; no runtime/size ceiling applied"}
        elif required:
            report["selection"] = select_candidates(report["records"], required,
                                                     args.max_runtime_ratio, args.max_size_ratio)
        else:
            report["selection"] = {"status": "not-performed", "reason": "no required development profiles selected"}
        report["selected_artifacts"] = []
        for decision in report["selection"].get("decisions", []):
            if decision.get("selected"):
                case = next(c for c in report["cases"] if c["id"] == decision["case"])
                variant = next(v for v in case["variants"] if v["id"] == decision["variant"])
                if audit.file_hash(variant["path"]) != variant["sha256"]:
                    raise ValueError("selected source changed since verification")
                out = root / "selected"
                out.mkdir(exist_ok=True)
                target = out / (case["id"] + ".c")
                shutil.copyfile(variant["path"], target)
                report["selected_artifacts"].append({"case": case["id"], "variant": variant["id"],
                                                     "path": str(target), "sha256": audit.file_hash(target)})
        failed = sum(r["status"] == "failed" for r in report["records"])
        missing = sum(p["status"] == "unavailable" for p in report["profiles"])
        report["summary"] = {"completed": len(report["records"]) - failed, "failed": failed,
                              "unavailable_profiles": missing}
        report["status"] = "failed" if failed or not report["records"] else "completed-with-gaps" if missing else "completed"
    except (audit.AuditError, OSError, ValueError, KeyError) as error:
        report.update(status="failed", error=str(error))
    finally:
        audit.write_json(root / "matrix.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--matrix", default=str(ROOT / "experiments/matrix.json"))
    p.add_argument("--csrd", default="build/csrd")
    p.add_argument("--compiler", action="append", default=[], help="family=executable; e.g. gcc=gcc-16")
    p.add_argument("--objdump", default="llvm-objdump")
    p.add_argument("--profdata", default="llvm-profdata")
    p.add_argument("--tier", choices=["core", "extended", "holdout"], default="core")
    p.add_argument("--case", action="append")
    p.add_argument("--profile", action="append")
    p.add_argument("--strategies", nargs="+", choices=["identity", "affine", "xor", "planned"], default=["identity", "affine", "planned"])
    p.add_argument("--seeds", nargs="+", type=int, default=[42])
    p.add_argument("--control-flows", nargs="+", choices=["none", "split-scale"], default=["none"])
    p.add_argument("--inputs", type=int, default=128)
    p.add_argument("--iterations", type=int, default=200000)
    p.add_argument("--repetitions", type=int, default=5)
    p.add_argument("--timeout-ms", type=int, default=30000)
    p.add_argument("--max-runtime-ratio", type=float, default=2.0)
    p.add_argument("--max-size-ratio", type=float, default=1.5)
    p.add_argument("--selection", help="previous matrix.json, mandatory for held-out evaluation")
    p.add_argument("--no-select", action="store_true", help="measure all candidates without screening by runtime/size ceilings")
    p.add_argument("--require-selected-profiles", action="store_true", help="nonzero exit if any selected profile is unavailable")
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    if not (0 <= args.inputs <= 100000 and 1 <= args.iterations <= 100000000
            and 3 <= args.repetitions <= 100 and 1 <= args.timeout_ms <= 600000):
        p.error("invalid input/timing/timeout budget")
    if any(not 0 <= seed <= 2**64 - 1 for seed in args.seeds) or len(set(args.seeds)) != len(args.seeds):
        p.error("seeds must be unique uint64 values")
    if "identity" not in args.strategies or len(set(args.strategies)) != len(args.strategies):
        p.error("unique strategies including identity are required for controls")
    if "none" not in args.control_flows or len(set(args.control_flows)) != len(args.control_flows):
        p.error("unique control-flow modes including none are required for paired controls")
    if not all(math.isfinite(v) and v >= 1 for v in (args.max_runtime_ratio, args.max_size_ratio)):
        p.error("cost ratios must be >= 1")
    root = Path(args.output_dir).resolve()
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        p.error(f"new output directory required: {error}")
    result = run(args, root)
    print(f"{result['status']}: {root / 'matrix.json'}")
    return int(result["status"] == "failed" or
               (args.require_selected_profiles and result["status"] == "completed-with-gaps"))


if __name__ == "__main__":
    sys.exit(main())
