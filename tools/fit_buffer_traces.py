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
    return "public-return" if ":boundary:return" in location else "heap-memory" if ":heap:" in location else "persistent-memory" if ":global:" in location else "caller-memory" if ":caller:" in location or ":caller-byte:" in location else "register" if ":reg:" in location else "stack"


def run(config):
    protocol=config.get("fit_protocol","affine-v1")
    if protocol not in ("affine-v1","affine-literal-boundaries-v2"):raise ValueError("unknown fit protocol")
    complete=protocol=="affine-literal-boundaries-v2"
    traces = []
    for entry in config["traces"]:
        if file_hash(entry["path"]) != entry["sha256"]: raise ValueError("trace changed before fitting")
        trace = json.loads(Path(entry["path"]).read_text())
        if trace["status"] != "completed" or trace["stack_read_failures"] or trace.get('heap_observer_errors'):
            raise ValueError("cannot score incomplete traces")
        if complete:
            if type(trace.get("return_value")) is not int or not 0<=trace["return_value"]<=0xffffffff:
                raise ValueError("return-boundary protocol requires a captured uint32 return")
            trace={**trace,"samples":[*trace["samples"],{"offset":"exit","visit":0,
                    "values":{"boundary:return":trace["return_value"]}}]}
        traces.append(trace)
    training = [i for i, entry in enumerate(config["traces"]) if entry["split"] == "training"]
    heldout = [i for i, entry in enumerate(config["traces"]) if entry["split"] == "heldout"]
    if len(training) < 3 or not heldout or len(training)+len(heldout) != len(traces):
        raise ValueError("invalid training/heldout partition")
    result = {"status": "completed", "fit_protocol":protocol, "targets": {}, "training_traces": len(training), "heldout_traces": len(heldout),
              "scope": "known-intermediate affine fitting with finite heldout validation; no universal recovery proof"}
    for target, values in config["targets"].items():
        if len(values) != len(traces): raise ValueError("target/trace lengths differ")
        if any(v is not None and (type(v) is not int or not 0<=v<=0xffffffff) for v in values):
            raise ValueError('target must be uint32 or absent on an unexecuted path')
        target_training=[i for i in training if values[i] is not None]
        target_heldout=[i for i in heldout if values[i] is not None]
        if len(target_training)<3 or not target_heldout:
            raise ValueError('insufficient executed paths for target fitting')
        train_targets = [values[i] for i in target_training]
        train = [traces[i] for i in target_training]; test = [traces[i] for i in target_heldout]
        models, searched = fit_affine(train, train_targets,identity_fallback=complete)
        negative_labels=train_targets[1:] + train_targets[:1]
        negative, _ = fit_affine(train, negative_labels,identity_fallback=complete)
        score = score_models(models, test, [values[i] for i in target_heldout])
        controls = score_models(negative, test, [values[i] for i in target_heldout])
        scopes=("register", "stack", "caller-memory")+(("public-return",) if complete else ())
        if any(":global:" in key for trace in traces for key in locations(trace)):scopes+=("persistent-memory",)
        if any(":heap:" in key for trace in traces for key in locations(trace)):scopes+=("heap-memory",)
        by_scope = {key: {"validated_locations": 0, "false_locations": 0, "inconclusive_locations": 0} for key in scopes}
        for model in score["models"]:
            label = "validated_locations" if model["correct"] == model["total"] else (
                "false_locations" if model["available"] == model["total"] else "inconclusive_locations")
            by_scope[location_scope(model["location"])][label] += 1
        presence = []
        for trace, value in zip(traces, values):
            if value is None:
                presence.append(None);continue
            count = {key: 0 for key in by_scope}
            for location, observed in locations(trace).items():
                if observed == value: count[location_scope(location)] += 1
            presence.append(count)
        result["targets"][target] = {"recovery": score, "negative_control": controls,
                                     "training_cases":target_training,"heldout_cases":target_heldout,
                                     "unexecuted_cases":[i for i,v in enumerate(values) if v is None],
                                     "negative_control_informative":negative_labels!=train_targets,
                                     "training_has_odd_difference":len({v&1 for v in train_targets})==2,
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
