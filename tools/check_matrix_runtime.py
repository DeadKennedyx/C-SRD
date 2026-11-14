#!/usr/bin/env python3
"""Revalidate runtime observations, frozen models, grades and resource pairings."""
import argparse
from collections import Counter, defaultdict
import itertools
import json
import math
from pathlib import Path

from audit_protection import file_hash
from effort_resources import save
from fit_matrix_runtime import fit, read_trace
from matrix_runtime_tasks import ARITIES, VERSION, targets, vectors
from measure_matrix_runtime import grade, labels_for, paired_summary, METRICS
from session_evidence import Evidence, distribution, local

ROOT = Path(__file__).resolve().parents[1]


def check(path):
    evidence = Evidence(); report = evidence.read(path)
    if report["status"] not in ("completed", "completed-with-gaps"):
        raise ValueError("terminal runtime collection required")
    for artifact, checksum in report["artifact_bindings"].items():
        evidence.bind(artifact, checksum)
    protocol = report["protocol"]
    if protocol["task_version"] != VERSION:
        raise ValueError("runtime task version changed")
    matrix_path = Path(protocol["matrix_report"])
    matrix_path = local(matrix_path if matrix_path.is_absolute() else ROOT/matrix_path)
    if matrix_path not in {local(p) for p in report["artifact_bindings"]}:
        raise ValueError("unbound matrix")
    matrix = evidence.read(matrix_path)
    records = {(r["case"], r["profile"], r["variant"]): r for r in matrix["records"]}
    cases = {c["id"]: c for c in matrix["cases"]}
    expected = set(itertools.product(protocol["case"], protocol["profile"], protocol["variant"], range(protocol["repetitions"])))
    actual = [(g["case"], g["profile"], g["variant"], g["repetition"]) for g in report["groups"]]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("missing or duplicate runtime group")
    for group in report["groups"]:
        directory = local(group["directory"])
        if evidence.read(directory/"group.json") != group:
            raise ValueError("runtime group differs from collection")
        built = records[(group["case"], group["profile"], group["variant"])]
        if built["status"] != "completed" or built["binary_sha256"] != group["binary_sha256"]:
            raise ValueError("runtime binary differs from matrix")
        evidence.bind(built["binary"], group["binary_sha256"])
        training, heldout = vectors(group["case"], protocol["input_seed"]+group["repetition"], protocol["training"], protocol["heldout"])
        partitions = [*(('training', v) for v in training), *(('heldout', v) for v in heldout)]
        if len(group["traces"]) != len(partitions):
            raise ValueError("missing runtime trace")
        for index, (entry, (split, vector)) in enumerate(zip(group["traces"], partitions)):
            if entry["split"] != split or tuple(entry["input"]) != vector:
                raise ValueError("runtime partition/input differs from frozen protocol")
            input_path = evidence.bind(directory/f"{index}.input", entry["input_sha256"])
            if input_path.read_text() != " ".join(map(str, vector))+"\n":
                raise ValueError("runtime input file changed")
            config_path, script_path = directory/f"{index}.config.json", directory/f"{index}.gdb"
            config = evidence.read(config_path, entry["config_sha256"])
            evidence.bind(script_path, entry["script_sha256"])
            if (config["function"] != cases[group["case"]]["function"] or config["step_limit"] != protocol["step_limit"] or
                    local(config["input_file"]) != input_path or local(config["output"]) != directory/f"{index}.trace.json.gz" or
                    local(entry["path"]) != local(config["output"])):
                raise ValueError("runtime trace configuration differs from protocol")
            resources = evidence.read(directory/f"{index}-resources/resources.json")
            resources.pop("samples", None)
            if resources != entry["resources"] or resources["argv"] != [report["gdb"]["path"], "--nx", "--batch", "-iex", "set auto-load off", "-x", str(Path(group["directory"])/f"{index}.gdb"), "--args", built["binary"]]:
                raise ValueError("runtime resource counters or invoked binary differ")
            for metric in METRICS:
                value = resources.get(metric)
                if value is not None and (not math.isfinite(value) or value < 0):
                    raise ValueError("invalid runtime resource counter")
            if "sha256" not in entry:
                if local(entry["path"]).exists() or entry["status"] != "missing-trace":
                    raise ValueError("unrecorded trace artifact")
                continue
            evidence.bind(entry["path"], entry["sha256"])
            trace = read_trace({**entry, "path": local(entry["path"])})
            if any(entry.get(key) != trace.get(key) for key in ("status", "steps", "stack_read_failures", "vector_read_failures", "return_value", "max_observed_stack_depth_bytes")):
                raise ValueError("trace metadata differs from observations")
            if trace["status"] not in ("completed", "step-limit"):
                continue
            if trace["steps"] != len(trace["samples"]) or not 0 < trace["steps"] <= protocol["step_limit"]:
                raise ValueError("invalid instruction-step accounting")
            if entry["value_observations"] != sum(len(s["values"]) for s in trace["samples"]):
                raise ValueError("value-observation count changed")
            if trace["status"] == "completed" and (not entry.get("return_validated") or trace["return_value"] != targets(group["case"], vector)["public_return"]):
                raise ValueError("traced return fails independent oracle")
        observed = all(t["status"] == "completed" and t["resources"]["status"] == "completed" and not t["stack_read_failures"] and not t["vector_read_failures"] for t in group["traces"])
        if not observed:
            if group["status"] != "incomplete-observation" or "targets" in group or "fits" in group:
                raise ValueError("incomplete observation promoted to recovery")
            continue
        config = evidence.read(directory/"fit-config.json")
        wanted = {"traces": [t for t in group["traces"] if t["split"] == "training"], "labels": labels_for(group["case"], training)}
        if config != wanted:
            raise ValueError("fit used a different training partition or labels")
        if not group.get("fits") or len(group["fits"]) > protocol["fit_repetitions"]:
            raise ValueError("missing or excessive fit repetitions")
        first = None
        for index, entry in enumerate(group["fits"]):
            resources = evidence.read(directory/f"fit-{index}-resources/resources.json"); resources.pop("samples", None)
            if resources != entry["resources"] or resources["argv"][1:] != [str(ROOT/"tools/fit_matrix_runtime.py"), str(Path(group["directory"])/"fit-config.json"), str(Path(group["directory"])/f"fit-{index}.json")]:
                raise ValueError("fit resource counters or invocation changed")
            if "sha256" not in entry:
                if group["status"] != "fit-failed" or index != len(group["fits"])-1:
                    raise ValueError("unrecorded fitted answer")
                break
            answer = evidence.read(entry["path"], entry["sha256"])
            if first is None:
                local_config = {**config, "traces": [{**t, "path": local(t["path"])} for t in config["traces"]]}
                expected_answer = {**fit(local_config), "config_sha256": file_hash(directory/"fit-config.json")}
                if answer != expected_answer:
                    raise ValueError("saved answer differs from fixed training-only observer")
                first = answer
            elif answer != first:
                raise ValueError("repeated fitter changed its candidate")
        if group["status"] == "fit-failed":
            if "targets" in group:
                raise ValueError("failed fit promoted to recovery")
            continue
        if group["status"] != "completed" or len(group["fits"]) != protocol["fit_repetitions"]:
            raise ValueError("incomplete fit collection")
        test_entries = [{**t, "path": local(t["path"])} for t in group["traces"] if t["split"] == "heldout"]
        if group["targets"] != grade(first, test_entries, labels_for(group["case"], heldout)):
            raise ValueError("saved recovery differs from held-out grading")
    if report["pairs"] != paired_summary(report["groups"]):
        raise ValueError("matched resource/accuracy summary changed")
    complete = all(g["status"] == "completed" for g in report["groups"])
    if (report["status"] == "completed") != complete:
        raise ValueError("runtime completeness status changed")
    return report, evidence


def summarize(report):
    grouped = defaultdict(list)
    for pair in report["pairs"]:
        grouped[pair["variant"]].append(pair)
    result = {}
    for variant, rows in sorted(grouped.items()):
        internal = [target for row in rows for name, target in row["targets"].items() if name != "public_return_control"]
        output = [row["targets"]["public_return_control"] for row in rows]
        result[variant] = {"groups": len(rows), "group_outcomes": dict(Counter(row["status"] for row in rows)),
            "internal_targets": len(internal), "internal_outcomes": dict(Counter(t["status"] for t in internal)),
            "original_internal_outcomes": dict(Counter(t["original_status"] for t in internal)),
            "negative_control_outcomes": dict(Counter(t["negative_control_status"] for t in internal)),
            "public_return_outcomes": dict(Counter(t["status"] for t in output)),
            "observer_cpu_ratios": distribution([row["cost_ratios"]["primary_observer"]["cpu_seconds"] for row in rows]),
            "observer_peak_rss_ratios": distribution([row["cost_ratios"]["primary_observer"]["peak_process_rss_bytes"] for row in rows]),
            "instruction_step_ratios": distribution([row["instruction_step_ratio"] for row in rows]),
            "matched_internal_recovery_cpu_ratios": distribution([t["matched_recovery_cpu_ratio"] for t in internal]),
            "queries": {split: sum(row["queries"].get(split, 0) for row in rows) for split in ("training", "heldout")}}
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime-report", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    report, evidence = check(args.runtime_report)
    output = Path(args.output_dir).resolve(); output.mkdir(parents=True, exist_ok=False)
    result = {"status": "checked", "collection_status": report["status"], "protocol": report["protocol"],
              "source_bindings": evidence.bindings, "variants": summarize(report), "pairs": report["pairs"]}
    save(output/"summary.json", result)
    print(json.dumps({"status": result["status"], "groups": len(report["groups"])}))
