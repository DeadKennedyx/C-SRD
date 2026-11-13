#!/usr/bin/env python3
"""Build and measure binary-only reconstruction of admitted buffer functions.

Cold Ghidra process totals include import/startup. Adapter execution and source
grading are separate stages. Unsupported is a coverage gap, never protection.
"""
import argparse
from collections import Counter
import fcntl
import json
from pathlib import Path
import random
import shutil
import statistics
import sys

from audit_protection import AuditError, Runner, executable, file_hash, write_json
from effort_resources import measure, environment, measurement_lock
from pcode_memory import reconstruct
from run_matrix import flags_for

ROOT = Path(__file__).resolve().parents[1]
IMPLEMENTATION = ["tools/audit_buffer_reconstruction.py", "tools/pcode_memory.py", "tools/pcode_values.py",
                  "tools/pcode_memory_cfg.py",
                  "tools/pcode_wide.py", "tools/pcode_cfg.py", "tools/effort_resources.py",
                  "tools/ghidra/ExportCSRDBuffers.java", "tools/run_matrix.py", "tools/audit_protection.py"]


def load_matrix(path, replay_path=None):
    """Use frozen binaries after a revised observer, retaining grading gaps."""
    path=Path(path).resolve();matrix=json.loads(path.read_text());evidence=None
    if replay_path:
        replay_path=Path(replay_path).resolve();replay=json.loads(replay_path.read_text())
        if replay['status'] not in ('completed','completed-with-gaps') or replay['input_sha256']!=file_hash(path) or Path(replay['input_report']).resolve()!=path:
            raise ValueError('requires a finished observer replay bound to this exact matrix')
        if any(r['status'] in ('false-reconstruction','control-failure') for r in replay['records']):
            raise ValueError('observer replay contains a correctness/control failure')
        expected={r['attempt'] for r in matrix['observations'] if r.get('export_path') and json.loads(Path(r['export_path']).read_text()).get('status')=='decompiled'}
        if {r['prior_attempt'] for r in replay['records']}!=expected:raise ValueError('replay omitted collected exports')
        for row in replay['records']:
            prior=matrix['observations'][row['prior_attempt']]
            if any(row[k]!=prior[k] for k in ('function','profile','variant','export_sha256','binary_sha256')):
                raise ValueError('replay changed observed artifact identity')
        evidence={'path':str(replay_path),'sha256':file_hash(replay_path),'status':replay['status'],'outcomes':replay['outcomes'],
                  'heap_observation':replay.get('heap_observation','events')}
    if matrix['status'] not in ('completed','completed-with-gaps'):
        if matrix['status']!='failed' or evidence is None or len(matrix.get('schedule',[]))!=len(matrix['observations']):
            raise ValueError('requires finished collection and grading, or a bound revised observer replay')
    return matrix,evidence


def grade(command, csrd, reference, candidate, function, output, timeout_ms, call_contracts=None, heap_observation="events"):
    try:
        command([csrd, "verify", reference, candidate, "--function", function, "--report", output,
                 "--timeout-ms", timeout_ms, *(["--call-contracts",call_contracts] if call_contracts else []),
                 *(["--heap-observation",heap_observation] if heap_observation!="events" else [])], timeout=timeout_ms / 1000 + 30)
    except AuditError as error:
        if not output.is_file():
            # A crashed/timed-out grader is missing evidence, not a failed
            # reconstruction or a proof. Preserve it without losing other rows.
            write_json(output,{"source_sha256":file_hash(reference),"candidate_sha256":file_hash(candidate),
                "grading_error":str(error),"functions":[{"function":function,"verification":"inconclusive",
                "reason":"verifier process did not produce a report"}]})
    functions = json.loads(output.read_text())["functions"]
    if len(functions) != 1 or functions[0]["function"] != function:
        raise ValueError("grader did not select exactly the requested function")
    return functions[0]


def prepare(args, root, report, command):
    contract_flags=[]
    if getattr(args,"call_contracts",None):
        path=root/"call-contracts.json";shutil.copyfile(args.call_contracts,path)
        report["call_contracts"]={"path":str(path),"sha256":file_hash(path)}
        contract_flags=["--call-contracts",path]
    contract_path=report.get("call_contracts",{}).get("path")
    csrd, headless = executable(args.csrd), executable(args.headless)
    compilers = {}
    for item in args.compiler:
        family, path = item.split("=", 1)
        if family not in ("clang", "gcc") or family in compilers:
            raise ValueError("unique clang=PATH / gcc=PATH compiler mappings required")
        compilers[family] = executable(path)
    report["tools"] = {name: {"path": path, "sha256": file_hash(path)}
                       for name, path in {"csrd": csrd, "headless": headless, **compilers}.items()}
    for name in ("csrd", *compilers):
        report["tools"][name]["version"] = command([report["tools"][name]["path"], "--version"]).splitlines()[0]
    installation = Path(headless).resolve().parent.parent
    report["ghidra_properties"] = (installation / "Ghidra/application.properties").read_text()
    components = sorted(set(installation.glob("Ghidra/Features/Decompiler/lib/*.jar")) |
                        set(installation.glob("Ghidra/Features/Decompiler/os/*/decompile")))
    report["ghidra_components"] = {str(p): file_hash(p) for p in components}
    language=installation/"Ghidra/Processors/AARCH64/data/languages"
    for name in ("AARCH64base.sinc","AARCH64.sla"):
        if (language/name).is_file(): report["ghidra_components"][str(language/name)]=file_hash(language/name)
    report["implementation"] = {name: file_hash(ROOT / name) for name in IMPLEMENTATION}
    catalog = ROOT / "benchmarks/matrix.json"
    report["profile_catalog_sha256"] = file_hash(catalog)
    profiles = {p["id"]: p for p in json.loads(catalog.read_text())["profiles"]}
    if not set(args.profile) <= profiles.keys(): raise ValueError("unknown build profile")
    selected_profiles = [profiles[name] for name in args.profile]
    report["profiles"] = selected_profiles
    for profile in selected_profiles:
        if profile.get("pgo") or profile.get("target") or profile.get("sanitizers"):
            raise ValueError("this binary observer excludes PGO, explicit cross-target and sanitizer profiles")
        if profile["compiler"] not in compilers: raise ValueError("missing selected compiler mapping")
    seen_functions = set()
    for source_index, source_name in enumerate(args.source):
        source = Path(source_name).resolve(strict=True)
        directory = root / f"source-{source_index}"; directory.mkdir()
        analysis_path = directory / "analysis.json"
        command([csrd, "analyze", source, "--report", analysis_path, *contract_flags])
        analysis = json.loads(analysis_path.read_text())
        functions = [f for f in analysis["functions"] if not args.function or f["function"] in args.function]
        if not functions: continue
        if any(f["status"] != "supported" or f.get("semantic_model") not in ("buffers-u32-c11-v1","buffers-byte-c11-v2","ordered-calls-byte-c11-v1","records-state-byte-c11-v1","guarded-memory-c11-v1","owned-heap-c11-v1") for f in functions):
            raise ValueError("selected source functions must use the admitted buffer contract")
        if seen_functions & {f["function"] for f in functions}: raise ValueError("duplicate selected function symbol")
        seen_functions.update(f["function"] for f in functions)
        report["sources"].append({"path": str(source), "sha256": file_hash(source),
                                  "dependencies": analysis["dependencies"], "functions": functions})
        sources = {"original": source}
        for strategy in ("identity", "affine"):
            candidate = directory / f"{strategy}.c"
            command([csrd, "transform", source, "-o", candidate, "--strategy", strategy, "--seed", 42,
                     "--timeout-ms", args.timeout_ms, "--report", directory / f"{strategy}.json", *contract_flags])
            transformed = json.loads((directory / f"{strategy}.json").read_text())
            for function in functions:
                decision = next(f for f in transformed["functions"] if f["function"] == function["function"])
                if decision["status"] != "transformed" or decision["verification"] != "proved-under-model":
                    raise ValueError("selected candidate was not transformed and verified")
            sources[strategy] = candidate
        for profile in selected_profiles:
            folder = directory / profile["id"]; folder.mkdir()
            compiler = compilers[profile["compiler"]]
            flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-" + profile["optimization"],
                     *flags_for(profile, profile["compiler"]), "-fPIC", "-I", str(source.parent)]
            variants = []
            for variant, source_path in sources.items():
                frozen, binary = folder / f"{variant}.i", folder / f"{variant}.so"
                command([compiler, *flags, "-E", "-P", source_path, "-o", frozen])
                for function in functions:
                    proof = grade(command, csrd, folder / "original.i", frozen, function["function"],
                                  folder / f"{variant}-{function['function']}-source-proof.json", args.timeout_ms, contract_path)
                    if proof["verification"] != "proved-under-model":
                        raise ValueError("compiler-specific input did not pass validation")
                command([compiler, *flags, "-shared", "-x", "c", frozen, "-o", binary])
                variants.append({"variant": variant, "binary": str(binary), "binary_sha256": file_hash(binary),
                                 "binary_bytes": binary.stat().st_size, "source": str(frozen), "source_sha256": file_hash(frozen),
                                 "compile_link_wall_seconds": report["commands"][-1]["elapsed_seconds"]})
            baseline = variants[0]
            copied = folder / "original-copy.so"; shutil.copyfile(baseline["binary"], copied)
            variants.append({**baseline, "variant": "original-copy", "binary": str(copied), "compile_link_wall_seconds": None})
            for function in functions:
                params = [{"kind": p["kind"], "read_only": p.get("read_only", False)} for p in function["parameters"]]
                for public, parameter in zip(params,function["parameters"]):
                    if parameter.get("element_bits")==8: public["element_signed"]=parameter["element_signed"]
                    if "record" in parameter: public["record"]=parameter["record"]
                group = {"function": function["function"], "profile": profile["id"], "parameters": params,
                         "reference": str(folder / "original.i"), "reference_sha256": file_hash(folder / "original.i"),
                         "variants": variants}
                if function["semantic_model"] in ("records-state-byte-c11-v1","guarded-memory-c11-v1"):
                    globals_=[{k:g[k] for k in ("name","kind","record") if k in g} for g in function.get("persistent_objects",[])]
                    interface=folder/f"{function['function']}-public-abi.json"
                    write_json(interface,{"parameters":params,"persistent_objects":globals_})
                    group.update(public_abi=str(interface),public_abi_sha256=file_hash(interface),persistent_objects=globals_)
                report["groups"].append(group)
    if not report["groups"] or (args.function and seen_functions != set(args.function)):
        raise ValueError("no groups or requested function missing")
    return csrd, headless


def observe(args, root, report, command, csrd, headless):
    rng = random.Random(args.order_seed)
    schedule = []
    for repetition in range(args.repetitions):
        groups = list(range(len(report["groups"]))); rng.shuffle(groups)
        for group in groups:
            variants = list(range(4)); rng.shuffle(variants)
            schedule.extend((repetition, group, variant) for variant in variants)
    report["schedule"] = schedule
    # All builds precede resource collection; source grading follows all observers.
    for attempt, (repetition, gi, vi) in enumerate(schedule):
        group = report["groups"][gi]; variant = group["variants"][vi]
        item = {"attempt": attempt, "repetition": repetition, "group": gi,
                "function": group["function"], "profile": group["profile"], "variant": variant["variant"],
                "binary_sha256": variant["binary_sha256"], "status": "running", "target_queries": 0}
        report["observations"].append(item)
        directory = root / f"attempt-{attempt}"; directory.mkdir()
        export_dir = directory / "export"; export_dir.mkdir()
        project = directory / "project"; project.mkdir()
        def public_type(p):
            if p["kind"]=="uint32": return "u"
            if p["kind"]=="uint32-buffer": return "c" if p["read_only"] else "p"
            code={"unsigned-char-buffer":"b","signed-char-buffer":"s","char-buffer":"h" if p["element_signed"] else "j"}[p["kind"]]
            return code.upper() if p["read_only"] else code
        abi = "@"+group["public_abi"] if "public_abi" in group else ",".join(public_type(p) for p in group["parameters"])
        print(f"{attempt+1}/{len(schedule)} {group['function']} {group['profile']} {variant['variant']}", flush=True)
        try:
            if file_hash(variant["binary"]) != variant["binary_sha256"]: raise ValueError("binary changed")
            if "public_abi" in group and file_hash(group["public_abi"])!=group["public_abi_sha256"]:
                raise ValueError("public interface changed")
            item["decompiler_resources"] = measure(
                [headless, project, "buffer", "-import", variant["binary"], "-deleteProject", "-max-cpu", "2",
                 "-analysisTimeoutPerFile", "30", "-scriptPath", ROOT / "tools/ghidra", "-postScript",
                 "ExportCSRDBuffers.java", group["function"], abi, "15", export_dir,
                 *([report["call_contracts"]["path"]] if "call_contracts" in report else [])],
                directory / "decompiler-resources", wall_seconds=args.process_seconds)
            if item["decompiler_resources"]["status"] != "completed":
                item["status"] = item["decompiler_resources"]["status"]; continue
            exported = export_dir / "export.json"
            export = json.loads(exported.read_text())
            item.update(export_path=str(exported), export_sha256=file_hash(exported),
                        decompile_wall_seconds=export.get("decompile_seconds"))
            if export["status"] != "decompiled": item["status"] = export["status"]; continue
            if export["parameters"] != group["parameters"] or export["function"] != group["function"]:
                raise ValueError("export does not match supplied ABI")
            if "public_abi" in group and [{k:v for k,v in g.items() if k!="address"} for g in export.get("persistent_objects",[])]!=group["persistent_objects"]:
                raise ValueError("export does not match supplied persistent object interface")
            item["adapter_resources"] = measure(
                [sys.executable, ROOT / "tools/pcode_memory.py", "--export", exported, "--output-dir", directory / "adapter"],
                directory / "adapter-resources", wall_seconds=30)
            adapted = directory / "adapter/adapter.json"
            if not adapted.is_file(): item["status"] = item["adapter_resources"]["status"]; continue
            item["adapter"] = json.loads(adapted.read_text())
            item["status"] = item["adapter"]["status"]
            if item["status"] == "candidate":
                if item["adapter_resources"]["status"] != "completed":
                    item["status"] = item["adapter_resources"]["status"]; continue
                recovered = directory / "adapter/recovered.c"
                item.update(recovered_path=str(recovered), recovered_sha256=file_hash(recovered))
        except (OSError, ValueError, KeyError, RuntimeError) as error:
            item.update(status="error", reason=str(error))
        finally:
            write_json(root / "reconstruction.json", report)
    # Verification is deliberately outside every observer's CPU/time/RSS scope.
    for item in report["observations"]:
        if item["status"] != "candidate": continue
        group = report["groups"][item["group"]]
        directory = root / f"attempt-{item['attempt']}"
        proof = grade(command, csrd, group["reference"], item["recovered_path"], group["function"],
                      directory / "verification.json", args.timeout_ms, report.get("call_contracts",{}).get("path"))
        item["verification"] = proof["verification"]
        item["verification_wall_seconds"] = report["commands"][-1]["elapsed_seconds"]
        item["status"] = {"proved-under-model": "recovered-under-source-model", "counterexample": "false-reconstruction"}.get(
            proof["verification"], "inconclusive-grading")
        export = json.loads(Path(item["export_path"]).read_text())
        item["controls"] = {}
        controls = {"return-plus-one": {"result_offset": 1}}
        if item["adapter"]["metrics"].get("public_stores",item["adapter"]["metrics"]["stores"]): controls["last-store-plus-one"] = {"final_store_offset": 1}
        if item["adapter"]["metrics"].get("calls"):
            scalar_site=any(p["kind"]=="uint32" for op in export["operations"] if op["opcode"]=="CALL"
                            for p in export.get("call_signatures",{}).get(op.get("callee"),{}).get("parameters",[]))
            if scalar_site: controls["call-argument-plus-one"] = {"call_argument_offset": 1}
            else: item["control_skips"]={"call-argument-plus-one":"no scalar call argument to mutate"}
        for label, mutation in controls.items():
            wrong = directory / f"{label}.c"; wrong.write_text(reconstruct(export, **mutation))
            control = grade(command, csrd, group["reference"], wrong, group["function"],
                            directory / f"{label}.json", args.timeout_ms, report.get("call_contracts",{}).get("path"))
            item["controls"][label] = control["verification"]
            if control["verification"] == "proved-under-model":
                item.update(status="control-failure", reason=f"{label} was accepted as equivalent")
            elif control["verification"] != "counterexample" and item["status"] not in ("control-failure","false-reconstruction"):
                item.update(status="control-inconclusive", reason=f"{label} grading was inconclusive")
        write_json(root / "reconstruction.json", report)


def summarize(report):
    report["outcomes"] = dict(Counter(o["status"] for o in report["observations"]))
    summaries = []
    for gi, group in enumerate(report["groups"]):
        rows = [o for o in report["observations"] if o["group"] == gi]
        for variant in ("identity", "affine", "original-copy"):
            pairs = []
            for row in rows:
                if row["variant"] != variant: continue
                base = next(o for o in rows if o["variant"] == "original" and o["repetition"] == row["repetition"])
                if any(o.get("decompiler_resources", {}).get("status") != "completed" for o in (row, base)): continue
                pair = {"repetition": row["repetition"], "outcomes": [base["status"], row["status"]]}
                for key in ("wall_seconds", "cpu_seconds", "peak_sampled_tree_rss_bytes"):
                    a, b = row["decompiler_resources"].get(key), base["decompiler_resources"].get(key)
                    pair[key + "_ratio"] = a / b if a is not None and b else None
                pairs.append(pair)
            summaries.append({"function": group["function"], "profile": group["profile"], "variant": variant,
                              "pairs": pairs, "cold_process_cpu_median_ratio": statistics.median(
                                  p["cpu_seconds_ratio"] for p in pairs) if pairs else None})
    report["paired_cold_costs"] = summaries


def run(args, root):
    report = {"schema_version": 2, "status": "running", "commands": [], "sources": [], "groups": [], "observations": [],
              "control_reference":"original-source",
              "environment": environment(), "protocol": vars(args),
              "scope": "Known-symbol, known-ABI buffer recovery including admitted bounded control flow; cold Ghidra process totals include startup/import; mutations graded against original source",
              "claims": {"binary_lifter_proved": False, "steady_state_costs": "not-measured",
                         "human_effort": "not-measured", "runtime_exposure": "separate-experiment",
                         "unsupported_means_protection": False, "source_given_to_observer": False}}
    command = Runner(report)
    try:
        csrd, headless = prepare(args, root, report, command)
        observe(args, root, report, command, csrd, headless)
        for group in report["groups"]:
            if "public_abi" in group and file_hash(group["public_abi"])!=group["public_abi_sha256"]:
                raise ValueError("public object interface changed")
            if file_hash(group["reference"]) != group["reference_sha256"]: raise ValueError("reference changed")
            for v in group["variants"]:
                if file_hash(v["binary"]) != v["binary_sha256"] or file_hash(v["source"]) != v["source_sha256"]:
                    raise ValueError("compiled artifact changed")
        for source in report["sources"]:
            for item in [source, *source["dependencies"]]:
                if file_hash(item["path"]) != item["sha256"]: raise ValueError("input/header changed")
        for path, expected in report["implementation"].items():
            if file_hash(ROOT / path) != expected: raise ValueError("observer changed during experiment")
        for tool in report["tools"].values():
            if file_hash(tool["path"]) != tool["sha256"]: raise ValueError("tool changed during experiment")
        for path, expected in report["ghidra_components"].items():
            if file_hash(path) != expected: raise ValueError("Ghidra component changed")
        if "call_contracts" in report and file_hash(report["call_contracts"]["path"])!=report["call_contracts"]["sha256"]:
            raise ValueError("call contracts changed")
        summarize(report)
        outcomes = report["outcomes"]
        report["status"] = "failed" if any(outcomes.get(k) for k in ("error", "control-failure", "false-reconstruction")) else (
            "completed" if set(outcomes) == {"recovered-under-source-model"} else "completed-with-gaps")
    except (AuditError, OSError, ValueError, KeyError, RuntimeError) as error:
        report.update(status="failed", error=str(error))
    finally:
        write_json(root / "reconstruction.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csrd", required=True)
    p.add_argument("--headless", required=True)
    p.add_argument("--compiler", action="append", required=True)
    p.add_argument("--source", action="append", required=True)
    p.add_argument("--call-contracts")
    p.add_argument("--function", action="append")
    p.add_argument("--profile", action="append")
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--order-seed", type=int, default=20261110)
    p.add_argument("--timeout-ms", type=int, default=10000)
    p.add_argument("--process-seconds", type=int, default=120)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    args.profile = args.profile or ["clang-O0", "gcc-O0", "clang-O2", "gcc-O2"]
    if not 1 <= args.repetitions <= 20 or not 1 <= args.process_seconds <= 600 or not 1 <= args.timeout_ms <= 600000:
        p.error("invalid repetition/timeout budget")
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    with measurement_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        report = run(args, root)
    print(report["status"], report.get("outcomes", report.get("error")), flush=True)
    return int(report["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
