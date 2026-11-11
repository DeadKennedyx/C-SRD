#!/usr/bin/env python3
"""Fit fixed-path region traces, then score held-out known intermediate values."""
import gzip
import json
from pathlib import Path
import sys

from audit_protection import file_hash, write_json
from fit_region_values import fit_rows, score_models
from observe_runtime import locations


def run(config):
    traces = []
    for entry in config["traces"]:
        if file_hash(entry["path"]) != entry["sha256"]: raise ValueError("trace changed before fitting")
        with gzip.open(entry["path"], "rt") as source: trace = json.load(source)
        if trace["status"] != "completed" or trace["stack_read_failures"]: raise ValueError("incomplete trace")
        traces.append(trace)
    train = [i for i,t in enumerate(config["traces"]) if t["split"]=="training"]
    test = [i for i,t in enumerate(config["traces"]) if t["split"]=="heldout"]
    if len(train)<3 or not test or len(train)+len(test)!=len(traces): raise ValueError("bad partition")
    rows = [locations(t) for t in traces]
    train_rows = [rows[i] for i in train]
    tests = [traces[i] for i in test]
    result = {"status":"completed", "observer":"affine-congruence-v2", "targets":{},
              "training_traces":len(train), "heldout_traces":len(test),
              "scope":"known intermediates, fixed loop count; finite heldout scoring, not parameter recovery proof"}
    for name, values in config["targets"].items():
        if len(values)!=len(traces): raise ValueError("target/trace count mismatch")
        labels = [values[i] for i in train]
        fitted, meta = fit_rows(train_rows, labels)
        negative, negative_meta = fit_rows(train_rows, labels[1:]+labels[:1])
        score = score_models(fitted, tests, [values[i] for i in test])
        controls = score_models(negative, tests, [values[i] for i in test])
        scopes = {}
        for model in score["models"]:
            location = model["location"]
            area = "register" if ":reg:" in location else "stack" if ":stack+" in location else "caller-memory"
            code = "target" if location.startswith(config["function"]+" +") or location.startswith(config["function"]+":") else "callback-or-plt"
            key = code+"/"+area
            scope = scopes.setdefault(key, {"validated":0,"false":0,"inconclusive":0})
            category = "validated" if model["correct"]==model["total"] else "false" if model["available"]==model["total"] else "inconclusive"
            scope[category]+=1
        result["targets"][name] = {"fit":meta,"recovery":score,"negative_control":controls,
                                   "negative_fit":negative_meta,"by_scope":scopes}
    return result


if __name__ == "__main__":
    config_path, output = map(Path, sys.argv[1:])
    checksum = file_hash(config_path)
    try:
        result = run(json.loads(config_path.read_text()))
        if file_hash(config_path)!=checksum: raise ValueError("config changed")
    except Exception as error: result = {"status":"failed","error":str(error)}
    result["config_sha256"] = checksum
    write_json(output,result)
    raise SystemExit(int(result["status"]!="completed"))
