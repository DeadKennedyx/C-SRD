#!/usr/bin/env python3
"""Summarize completed buffer development evidence without significance claims."""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path
from statistics import median


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def spread(values):
    return {"count": len(values), "min": min(values), "median": median(values), "max": max(values)}


def runtime(report):
    if report["status"] != "completed": raise ValueError("incomplete runtime study")
    totals = defaultdict(lambda: defaultdict(float))
    pairs = defaultdict(dict)
    for row in report["observations"]:
        if row["status"] != "completed": raise ValueError("incomplete runtime group")
        t = totals[row["variant"]]
        t["groups"] += 1
        t["executions"] += row["target_executions"]
        t["instruction_steps"] += row["instruction_steps"]
        costs = {"trace_cpu_seconds": sum(x["resources"]["cpu_seconds"] for x in row["traces"]),
                 "trace_wall_seconds": sum(x["resources"]["wall_seconds"] for x in row["traces"]),
                 "fit_cpu_seconds": row["fit"]["cpu_seconds"]}
        for k, v in costs.items(): t[k] += v
        pairs[(row["function"], row["profile"], tuple(row["layout"]))][row["variant"]] = costs
        for target in row["fit"]["targets"].values():
            t["targets"] += 1
            t["targets_recovered"] += bool(target["recovery"]["validated_models"])
            for key in ("false_models", "inconclusive_models"):
                t[key] += target["recovery"][key]
            t["negative_control_validated_models"] += target["negative_control"]["validated_models"]
            for scope, counts in target["by_scope"].items():
                t[scope+"_targets_recovered"] += bool(counts["validated_locations"])
    ratios = {variant: {metric: spread([p[variant][metric]/p["original"][metric] for p in pairs.values()])
                       for metric in ("trace_cpu_seconds", "trace_wall_seconds", "fit_cpu_seconds")}
              for variant in ("identity", "affine", "original-copy")}
    return {"input_protocol": report["protocol"].get("input_protocol", "seeded-v1"),
            "by_variant": dict(totals), "paired_cost_ratios": ratios,
            "cost_scope": "debugger trace acquisition and Python known-label fitting; fixed-order development observations, no native application cost or human-effort inference"}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--runs", type=Path, default=Path("experiments/runs"))
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    bindings = {}

    def read(directory, name):
        path = args.runs / directory / name
        bindings[str(path)] = sha(path)
        return json.loads(path.read_text())

    r = read("buffer-reconstruction-development-20261110", "reconstruction.json")
    if r["status"] != "completed": raise ValueError("incomplete reconstruction study")
    reconstruction = {"outcomes": r["outcomes"], "observations": len(r["observations"]),
        "corruption_controls": sum(len(o["controls"]) for o in r["observations"]),
        "cold_ratios": {variant: {metric: spread([pair[metric] for row in r["paired_cold_costs"]
                if row["variant"] == variant for pair in row["pairs"]])
                for metric in ("cpu_seconds_ratio", "wall_seconds_ratio", "peak_sampled_tree_rss_bytes_ratio")}
                for variant in ("identity", "affine", "original-copy")}}
    answers = {}
    for host in ("native", "linux"):
        data = read(f"buffer-answers-{host}-20261110", "validation.json")
        if data["status"] != "tested": raise ValueError("answer compilation incomplete")
        answers[host] = {"comparisons": data["comparisons"], "distinct_answers": len(data["answers"]),
                         "compilers": data["compilers"]}
    evidence = read("buffer-observer-tests-20261110", "evidence-check-v3.json")
    controls = read("buffer-observer-tests-20261110", "evidence-tampering-controls.json")
    if evidence["status"] != "checked" or controls["status"] != "passed": raise ValueError("evidence checks failed")
    result = {"status": "completed", "reconstruction": reconstruction, "compiled_answers": answers,
              "runtime": runtime(read("buffer-runtime-development-20261110-v3", "runtime.json")),
              "earlier_runtime": runtime(read("buffer-runtime-development-20261110-v2", "runtime.json")),
              "evidence_checks": evidence, "evidence_tampering_controls": controls,
              "source_bindings": bindings,
              "claims": {"protection_advantage_established": False, "human_effort_measured": False,
                         "significance_tested": False, "source_model_proof_is_binary_proof": False}}
    args.output.write_text(json.dumps(result, indent=2)+"\n")


if __name__ == "__main__": main()
