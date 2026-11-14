"""Fixed supervised affine-congruence observer; held-out traces are withheld."""
import gzip
import json
from pathlib import Path
import sys

from audit_protection import file_hash
from effort_resources import save
from fit_region_values import fit_rows
from observe_runtime import locations


def read_trace(entry):
    if file_hash(entry["path"]) != entry["sha256"]:
        raise ValueError("trace digest mismatch")
    with gzip.open(entry["path"], "rt") as stream:
        return json.load(stream)


def fit(config):
    if any(t["split"] != "training" for t in config["traces"]):
        raise ValueError("held-out traces must not reach the observer")
    traces = [read_trace(t) for t in config["traces"]]
    if any(t["status"] != "completed" or t["stack_read_failures"] or t["vector_read_failures"] for t in traces):
        raise ValueError("complete observations required for the primary task")
    rows = [locations(t) for t in traces]
    result = {"status": "completed", "observer": "fixed-affine-congruence-runtime-v1", "targets": {}}
    for name, labels in config["labels"].items():
        models, metadata = fit_rows(rows, labels)
        negative, negative_metadata = fit_rows(rows, labels[1:]+labels[:1])
        result["targets"][name] = {"models": models, "selected": models[0] if models else None,
                                    "fit": metadata, "negative_models": negative,
                                    "negative_selected": negative[0] if negative else None,
                                    "negative_fit": negative_metadata}
    return result


if __name__ == "__main__":
    source, destination = map(Path, sys.argv[1:])
    checksum = file_hash(source)
    try:
        result = fit(json.loads(source.read_text()))
        if file_hash(source) != checksum:
            raise ValueError("observer configuration changed")
    except Exception as error:
        result = {"status": "error", "error": str(error)}
    save(destination, {**result, "config_sha256": checksum})
    raise SystemExit(int(result["status"] != "completed"))
