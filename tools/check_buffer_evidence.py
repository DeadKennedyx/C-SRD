#!/usr/bin/env python3
"""Validate buffer-observer evidence chains after measurement, before conclusions.

This checks artifact identity, schedule, reconstruction and grading membership.
It is not an independent proof of Ghidra, the C frontend or resource counters.
Run in the same environment as collection so tool/header paths remain valid.
"""
import argparse
import copy
import json
from pathlib import Path

from audit_protection import file_hash, write_json
from audit_buffer_reconstruction import summarize
from buffer_observation_cases import cases, expected, LAYOUTS
from fit_buffer_traces import run as replay_fit
from pcode_memory import reconstruct

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition: raise ValueError(message)


def checked(path, digest):
    path = Path(path)
    require(file_hash(path) == digest, f"artifact hash mismatch: {path}")
    return path


def load(path):
    return json.loads(Path(path).read_text())


def implementation(report, evidence_root):
    for path, digest in report["implementation"].items():
        current = ROOT / path
        checked(current if file_hash(current) == digest else evidence_root / "implementation" / path, digest)


def check_reconstruction(path):
    path = Path(path); report = load(path)
    require(report["status"] in ("completed", "completed-with-gaps"), "reconstruction report is not finished")
    implementation(report, path.parent)
    for tool in report["tools"].values(): checked(tool["path"], tool["sha256"])
    for name, digest in report["ghidra_components"].items(): checked(name, digest)
    checked(ROOT / "benchmarks/matrix.json", report["profile_catalog_sha256"])
    for source in report["sources"]:
        for item in [source, *source["dependencies"]]: checked(item["path"], item["sha256"])
    for group in report["groups"]:
        if "public_abi" in group:checked(group["public_abi"],group["public_abi_sha256"])
        checked(group["reference"], group["reference_sha256"])
        require([v["variant"] for v in group["variants"]] == ["original", "identity", "affine", "original-copy"], "variant set changed")
        for variant in group["variants"]:
            checked(variant["binary"], variant["binary_sha256"]); checked(variant["source"], variant["source_sha256"])
        require(group["variants"][0]["binary_sha256"] == group["variants"][3]["binary_sha256"], "copy control is not identical")
    schedule = report["schedule"]
    expected_schedule = {(r, g, v) for r in range(report["protocol"]["repetitions"])
                         for g in range(len(report["groups"])) for v in range(4)}
    require(len(schedule) == len(expected_schedule) == len(report["observations"]) and
            set(map(tuple, schedule)) == expected_schedule, "missing/duplicate attempts")
    answers = controls = 0
    for attempt, (scheduled, row) in enumerate(zip(schedule, report["observations"])):
        repetition, gi, vi = scheduled
        group = report["groups"][gi]; variant = group["variants"][vi]
        require((row["attempt"], row["repetition"], row["group"], row["function"], row["profile"], row["variant"]) ==
                (attempt, repetition, gi, group["function"], group["profile"], variant["variant"]), "attempt/schedule mismatch")
        require(row["binary_sha256"] == variant["binary_sha256"], "observed binary identity changed")
        directory = path.parent / f"attempt-{attempt}"
        resources = load(directory / "decompiler-resources/resources.json")
        require(resources == row["decompiler_resources"], "decompiler counters changed")
        require(resources["argv"][resources["argv"].index("-import")+1] == variant["binary"], "wrong imported binary")
        if "export_path" not in row: continue
        export = load(checked(row["export_path"], row["export_sha256"]))
        require(export["function"] == group["function"] and export["parameters"] == group["parameters"], "export public ABI mismatch")
        if "adapter" not in row: continue
        require(load(directory / "adapter/adapter.json") == row["adapter"], "adapter result changed")
        require(load(directory / "adapter-resources/resources.json") == row["adapter_resources"], "adapter counters changed")
        require(row["adapter"]["export_sha256"] == row["export_sha256"], "adapter consumed a different export")
        if "recovered_path" not in row: continue
        candidate = checked(row["recovered_path"], row["recovered_sha256"])
        require(reconstruct(export) == candidate.read_text(), "replayed answer differs")
        require(row["adapter"]["recovered_sha256"] == row["recovered_sha256"], "adapter answer identity changed")
        grade = load(directory / "verification.json")
        require(grade["source_sha256"] == group["reference_sha256"] and grade["candidate_sha256"] == row["recovered_sha256"], "proof is for different C")
        require(len(grade["functions"]) == 1 and grade["functions"][0]["function"] == row["function"] and
                grade["functions"][0]["verification"] == row["verification"], "proof selection/status mismatch")
        if row["status"] == "recovered-under-source-model":
            require(row["verification"] == "proved-under-model", "unproved answer marked recovered")
            require(row["decompiler_resources"]["status"] == row["adapter_resources"]["status"] == "completed",
                    "recovery exceeded a resource budget")
            answers += 1
        mutations = {"return-plus-one": {"result_offset": 1}}
        if row["adapter"]["metrics"]["stores"]:
            if report["schema_version"] >= 2: mutations["last-store-plus-one"] = {"final_store_offset": 1}
            else: mutations["store-plus-one"] = {"store_offset": 1}
        require(set(row["controls"]) == set(mutations), "missing corruption control")
        for label, mutation in mutations.items():
            wrong = directory / f"{label}.c"
            require(wrong.read_text() == reconstruct(export, **mutation), "wrong mutation input")
            control = load(directory / f"{label}.json")
            control_source=group["reference_sha256"] if report.get("control_reference")=="original-source" else row["recovered_sha256"]
            require(control["source_sha256"] == control_source and control["candidate_sha256"] == file_hash(wrong), "control proof identity mismatch")
            require(control["functions"][0]["verification"] == row["controls"][label] == "counterexample", "control not rejected")
            controls += 1
    recomputed = copy.deepcopy(report); summarize(recomputed)
    require(recomputed["outcomes"] == report["outcomes"] and recomputed["paired_cold_costs"] == report["paired_cold_costs"], "summaries do not match attempts")
    return {"report_sha256": file_hash(path), "attempts": len(schedule), "proved_answers": answers, "rejected_controls": controls,
            "replay_implementation_sha256": file_hash(ROOT / "tools/pcode_memory.py")}


def check_runtime(path):
    path = Path(path); report = load(path)
    require(report["status"] in ("completed", "completed-with-gaps"), "runtime report is not finished")
    implementation(report, path.parent); checked(report["gdb"]["path"], report["gdb"]["sha256"])
    for name in ("tools/fit_buffer_traces.py", "tools/observe_runtime.py"):
        checked(ROOT / name, report["implementation"][name])
    matrix = load(checked(report["matrix"]["path"], report["matrix"]["sha256"]))
    selected_cases,selected_expected,layouts=cases,expected,LAYOUTS
    if report["protocol"].get("corpus")=="control":
        from control_observation_cases import cases as selected_cases,expected as selected_expected,LAYOUTS as layouts
    elif report["protocol"].get("corpus","word")!="word":raise ValueError("evidence checker supports word/control runtime corpora")
    require(report["cases"] == selected_cases(report["protocol"].get("input_protocol", "seeded-v1")) and
            report["layouts"] == list(map(list, layouts)), "runtime input protocol changed")
    groups = [g for g in matrix["groups"] if (not report["protocol"]["function"] or g["function"] in report["protocol"]["function"])
              and (not report["protocol"]["profile"] or g["profile"] in report["protocol"]["profile"])]
    keys = {(g["function"], g["profile"], v["variant"], tuple(layout))
            for g in groups for v in g["variants"] for layout in layouts}
    require(len(keys) == len(report["observations"]), "runtime schedule incomplete")
    seen, executions, fits = set(), 0, 0
    for row in report["observations"]:
        key = row["function"], row["profile"], row["variant"], tuple(row["layout"])
        require(key in keys and key not in seen, "unknown/duplicate runtime observation"); seen.add(key)
        group = next(g for g in groups if (g["function"], g["profile"]) == key[:2])
        variant = next(v for v in group["variants"] if v["variant"] == row["variant"])
        checked(variant["binary"], row["library_sha256"])
        require(row["library_sha256"] == variant["binary_sha256"], "runtime library differs from matrix")
        if report["schema_version"] >= 2:
            checked(row["executable"], row["executable_sha256"]); checked(row["harness"], row["harness_sha256"])
        require(len(row["traces"]) == len(report["cases"]), "missing trace attempt")
        labels = {}
        for ci, (record, case) in enumerate(zip(row["traces"], report["cases"])):
            require(record["case_index"] == ci and record["split"] == case["split"], "wrong trace partition")
            trace_path = Path(record["path"])
            if report["schema_version"] >= 2:
                checked(trace_path.parent / f"{ci}.input", record["input_sha256"])
                checked(trace_path.parent / f"{ci}.json", record["configuration_sha256"])
                checked(trace_path.parent / f"{ci}.gdb", record["gdb_script_sha256"])
                argv = record["resources"]["argv"]
                require(argv[argv.index("--args")+1] == row["executable"], "trace invoked a different executable")
            require(load(trace_path.parent / f"{ci}-resources/resources.json") == record["resources"], "trace counters changed")
            if "sha256" not in record: continue
            trace = load(checked(trace_path, record["sha256"]))
            if record["status"] != "completed": continue
            require(record["resources"]["status"] == "completed", "completed trace exceeded a resource budget")
            oracle = selected_expected(row["function"], case["memory"], *row["layout"], case["x"])
            require(trace["status"] == "completed" and trace["steps"] == len(trace["samples"]) and
                    trace["return_value"] == oracle["return_value"] and trace["final_memory"] == oracle["final_memory"], "trace outcome/oracle mismatch")
            for target, value in oracle["targets"].items(): labels.setdefault(target, []).append(value)
            executions += 1
        if row["status"] != "completed": continue
        require(row["fit_resources"]["status"] == "completed", "completed fit exceeded a resource budget")
        fitpath = Path(row["traces"][0]["path"]).parent / "fit-config.json"
        config = load(checked(fitpath, row["fit"]["config_sha256"]))
        expected_config={"traces":row["traces"],"targets":labels}
        if report["schema_version"]>=3:expected_config["fit_protocol"]=report["protocol"]["fit_protocol"]
        require(config == expected_config, "fit inputs differ from declared labels/traces")
        for k, v in replay_fit(config).items(): require(row["fit"][k] == v, "fit replay differs")
        require(load(fitpath.parent / "fit.json") == row["fit"], "fit result changed")
        require(load(fitpath.parent / "fit-resources/resources.json") == row["fit_resources"], "fit counters changed")
        fits += 1
    return {"report_sha256": file_hash(path), "observations": len(seen), "checked_executions": executions, "replayed_fits": fits,
            "harness_input_hashes_present": report["schema_version"] >= 2,
            "replay_input_model_sha256": file_hash(ROOT / ("tools/control_observation_cases.py" if report["protocol"].get("corpus")=="control" else "tools/buffer_observation_cases.py"))}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reconstruction-report", required=True)
    p.add_argument("--runtime-report", action="append", default=[])
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = {"status": "running"}
    try:
        result["reconstruction"] = check_reconstruction(args.reconstruction_report)
        result["runtime"] = [check_runtime(path) for path in args.runtime_report]
        result["status"] = "checked"
    except Exception as error:
        result.update(status="failed", reason=str(error))
    write_json(Path(args.output), result)
    print(json.dumps(result, indent=2))
    return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
