#!/usr/bin/env python3
"""Fit known intermediate labels from training traces; score untouched heldout traces."""
import json
from pathlib import Path
import resource
import sys
import time

from audit_protection import file_hash, write_json
from observe_runtime import fit_affine, locations, score_models


def location_scope(location):
    return "caller-memory" if ":caller:" in location or ":caller-byte:" in location else "register" if ":reg:" in location else "stack"


def run(config):
    traces = []
    for entry in config["traces"]:
        if file_hash(entry["path"]) != entry["sha256"]: raise ValueError("trace changed before fitting")
        trace = json.loads(Path(entry["path"]).read_text())
        if trace["status"] != "completed" or trace["stack_read_failures"]:
            raise ValueError("cannot score incomplete traces")
        traces.append(trace)
    training = [i for i, entry in enumerate(config["traces"]) if entry["split"] == "training"]
    heldout = [i for i, entry in enumerate(config["traces"]) if entry["split"] == "heldout"]
    if len(training) < 3 or not heldout or len(training)+len(heldout) != len(traces):
        raise ValueError("invalid training/heldout partition")
    result = {"status": "completed", "targets": {}, "training_traces": len(training), "heldout_traces": len(heldout),
              "scope": "known-intermediate affine fitting with finite heldout validation; no universal recovery proof"}
    for target, values in config["targets"].items():
        if len(values) != len(traces): raise ValueError("target/trace lengths differ")
        train_targets = [values[i] for i in training]
        train = [traces[i] for i in training]; test = [traces[i] for i in heldout]
        models, searched = fit_affine(train, train_targets)
        negative, _ = fit_affine(train, train_targets[1:] + train_targets[:1])
        score = score_models(models, test, [values[i] for i in heldout])
        controls = score_models(negative, test, [values[i] for i in heldout])
        by_scope = {key: {"validated_locations": 0, "false_locations": 0, "inconclusive_locations": 0}
                    for key in ("register", "stack", "caller-memory")}
        for model in score["models"]:
            label = "validated_locations" if model["correct"] == model["total"] else (
                "false_locations" if model["available"] == model["total"] else "inconclusive_locations")
            by_scope[location_scope(model["location"])][label] += 1
        presence = []
        for trace, value in zip(traces, values):
            count = {key: 0 for key in by_scope}
            for location, observed in locations(trace).items():
                if observed == value: count[location_scope(location)] += 1
            presence.append(count)
        result["targets"][target] = {"recovery": score, "negative_control": controls,
                                     "locations_searched": searched, "by_scope": by_scope,
                                     "literal_presence": presence}
    return result


def main():
    config_path, output = map(Path, sys.argv[1:])
    config_hash = file_hash(config_path)
    config = json.loads(config_path.read_text())
    wall, cpu = time.perf_counter(), time.process_time()
    try:
        result = run(config)
    except Exception as error:
        result = {"status": "error", "reason": str(error)}
    result.update(wall_seconds=time.perf_counter()-wall, cpu_seconds=time.process_time()-cpu,
                  peak_process_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024),
                  rss_scope="whole fit worker peak, including Python and trace loading", config_sha256=config_hash)
    if file_hash(config_path) != config_hash:
        result.update(status="error", reason="fit configuration changed")
    write_json(output, result)
    return int(result["status"] != "completed")


if __name__ == "__main__":
    raise SystemExit(main())
