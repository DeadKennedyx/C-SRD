#!/usr/bin/env python3
"""Descriptive controls and historical cold costs; no outcome selection or refit."""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tools"))
from effort_resources import save
from session_evidence import local
from summarize_wide_observer import distribution, Evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--summary-dir", type=Path, required=True)
    args = parser.parse_args(); evidence = Evidence()
    report = evidence.read(args.sessions)
    summary = evidence.read(args.summary_dir/"summary.json")
    medians = evidence.read(args.summary_dir/"session-medians.json")
    if report["status"] != "completed" or summary["status"] != "completed":
        raise ValueError("complete primary analysis required")
    native_ids, initial_calls, measured_calls = [], 0, 0
    resolutions = {r: set() for r in ("jvm", "native", "adapter")}
    trends = {r: [] for r in resolutions}; errors = 0
    for row in report["sessions"]:
        session = evidence.read(local(row["directory"])/"session.json", row["session_sha256"])
        identities = {r: set() for r in resolutions}
        for role in ("jvm", "adapter"):
            for phase in session[role]["phases"]:
                resource = phase["resources"]; errors += len(resource["sample_errors"])
                if resource["status"] != "completed": raise ValueError("invalid phase")
                for end in ("before", "after"):
                    for key, process in resource[end].items():
                        identities[process["role"]].add(key)
                        resolutions[process["role"]].add(process["clock_resolution_ns"])
                if role == "jvm" and phase["phase"] != "setup":
                    if phase["phase"].startswith("batch-"): measured_calls += phase["result"]["requests"]
                    else: initial_calls += phase["result"]["requests"]
        if any(len(values) != 1 for values in identities.values()):
            raise ValueError("process replacement between phases")
        native_ids.append({"session": row["id"], "identities": {k: list(v) for k, v in identities.items()}})
        for role in resolutions:
            phases = [p for p in session["adapter" if role == "adapter" else "jvm"]["phases"] if p["phase"].startswith("batch-")]
            first = phases[0]["resources"]["cpu_ns"][role]/phases[0]["result"]["requests"]
            last = phases[-1]["resources"]["cpu_ns"][role]/phases[-1]["result"]["requests"]
            trends[role].append({"session": row["id"], "last_over_first_cpu": last/first})
    prior_path = local(report["protocol"]["prior_cold"])
    prior = evidence.read(prior_path, report["bindings"][str(Path("/work")/prior_path.relative_to(ROOT))])
    cold = []
    for cell in summary["cells"]:
        trials = [t for t in prior["trials"] if not t["warmup"] and
                  (t["case"], t["profile"], t["variant"]) == (cell["case"], cell["profile"], cell["variant"])]
        if not trials: raise ValueError("missing historical cold control")
        cold.append({"case": cell["case"], "profile": cell["profile"], "variant": cell["variant"],
                     "cpu_seconds": distribution([t["resources"]["cpu_seconds"] for t in trials]),
                     "wall_seconds": distribution([t["resources"]["wall_seconds"] for t in trials]),
                     "peak_sampled_tree_rss_bytes": distribution([t["resources"]["peak_sampled_tree_rss_bytes"] for t in trials])})
    controls = []
    for cell in summary["cells"]:
        if cell["variant"] != "original" and cell["application"]["binary_bytes_identical_to_original"]:
            controls.append({"case": cell["case"], "profile": cell["profile"], "variant": cell["variant"],
                             "metrics": cell["metrics"]})
    evidence.bind(Path(__file__).resolve())
    output = args.summary_dir/"diagnostics.json"
    if output.exists(): raise ValueError("do not overwrite diagnostics")
    save(output, {"scope": "descriptive post-processing; no new measurement, selection or tuning",
         "source_bindings": evidence.bindings, "independent_sessions": len(native_ids),
         "measured_requests_per_stage": measured_calls, "excluded_initial_requests_per_stage": initial_calls,
         "cross_phase_identities": native_ids, "clock_resolution_ns": {k: sorted(v) for k, v in resolutions.items()},
         "rss_sample_errors": errors, "identical_binary_controls": controls,
         "last_over_first_batch_cpu_ratios": {k: distribution([t["last_over_first_cpu"] for t in v]) for k, v in trends.items()},
         "raw_batch_trends": trends,
         "cpu_outside_measured_phases_seconds": distribution([s["cpu_outside_phases_seconds"] for s in medians]),
         "historical_cold_scope": "different one-request protocol; retained context, not paired warm/cold comparisons",
         "historical_cold_cells": cold})


if __name__ == "__main__": main()
