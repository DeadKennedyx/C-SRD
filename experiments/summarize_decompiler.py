#!/usr/bin/env python3
"""Reproduce descriptive counts from the frozen 2026-11-09 experiment artifacts."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def matrix_summary(path):
    report = json.loads(path.read_text())
    rows = report["records"]
    assert report["status"] in ("completed", "completed-with-gaps")
    assert all(r["status"] == "completed" for r in rows)
    summary = {"sha256": digest(path), "status": report["status"], **report["summary"],
               "paired_input_output_comparisons": sum(r["execution"]["comparisons"] for r in rows if r["variant"] != "original"),
               "settings": report["settings"], "selection": report["selection"],
               "recognition_scores": report["recognition_scores"], "cases": []}
    for case in report["cases"]:
        subset = [r for r in rows if r["case"] == case["id"]]
        splits = [r for r in subset if r["control_flow"] == "split-scale"]
        eligible = [r for r in splits if r["split_scales"] > 0]
        original_plan = json.loads((path.parent / case["id"] / "planned-42/transformation.json").read_text())
        split_plan = json.loads((path.parent / case["id"] / "planned-42-split-scale/transformation.json").read_text())
        same_labels = original_plan["functions"][0]["graph"] == split_plan["functions"][0]["graph"]
        if not same_labels:
            raise ValueError("planned representation labels differ: do not attribute changes solely to split")
        summary["cases"].append({"case": case["id"], "cells": len(subset),
            "split_cells": len(splits), "split_cells_with_eligible_nodes": len(eligible),
            "eligible_split_cells_with_same_mnemonics": sum(not r["comparison"]["instruction_sequences_differ_from_control_flow_control"] for r in eligible),
            "same_planned_graph_labels": same_labels,
            "blackbox_recovered_on_heldout": sum(r["reconstruction"]["recovered_on_heldout"] for r in subset),
            "compiled_controls": [{"profile": r["profile"], "variant": r["variant"],
                "split_scales": r["split_scales"], "comparison": r["comparison"],
                "max_paired_runtime_ratio": r["timing"]["max_paired_ratio"],
                "binary_size_ratio": r["binary_size_ratio"]} for r in splits]})
    return summary


def observer_summary(path):
    report = json.loads(path.read_text())
    assert report["status"] == "completed"
    observations = report["observations"]
    return {"sha256": digest(path), "summary": report["summary"],
            "protocol": report["protocol"], "implementation": report["implementation"],
            "negative_controls_rejected": sum(o.get("negative_control", {}).get("verification") == "counterexample" for o in observations),
            "unsupported_reasons": dict(Counter(o["reason"] for o in observations if o["status"] == "unsupported-reconstruction")),
            "per_case": {case: dict(Counter(o["status"] for o in observations if o["case"] == case))
                         for case in sorted({o["case"] for o in observations})},
            "per_variant": {variant: dict(Counter(o["status"] for o in observations if o["variant"] == variant))
                            for variant in sorted({o["variant"] for o in observations})}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runs-root", type=Path, default=Path("experiments/runs"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = args.runs_root
    summary = {"implementation_commit": "1d059db24726879aaf61a71f458aa1d103c48bfc",
               "scope": "Descriptive counts of correlated cells on a small corpus; no statistical or protection guarantee",
               "development": matrix_summary(root / "decompiler-flow-linux-development-v2/matrix.json"),
               "heldout": matrix_summary(root / "decompiler-flow-linux-heldout/matrix.json"),
               "ghidra_development": observer_summary(root / "decompiler-flow-ghidra-development/decompiler.json"),
               "ghidra_heldout": observer_summary(root / "decompiler-flow-ghidra-heldout/decompiler.json")}
    rescoring_path = root / "decompiler-frozen-rescoring/rescoring.json"
    rescoring = json.loads(rescoring_path.read_text())
    assert rescoring["status"] == "completed"
    summary["frozen_reference_rescoring"] = {"sha256": digest(rescoring_path),
        "inference_changed": rescoring["inference_changed"],
        "outcomes": dict(Counter(r["verification"] for r in rescoring["rescored"]))}
    args.output.write_text(json.dumps(summary, indent=2) + "\n")


if __name__ == "__main__":
    main()
