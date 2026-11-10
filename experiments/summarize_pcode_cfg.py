#!/usr/bin/env python3
"""Summarize immutable CFG observer evidence without changing any prior grade."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def distribution(values):
    return {"n": len(values), "minimum": min(values), "median": statistics.median(values), "maximum": max(values)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("validation", "recovery", "prior", "compiled", "circuit"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    paths = {name: getattr(args, name) / filename for name, filename in
             (("validation", "effort.json"), ("recovery", "effort.json"), ("prior", "effort.json"),
              ("compiled", "checks.json"), ("circuit", "summary.json"))}
    data = {name: json.loads(path.read_text()) for name, path in paths.items()}
    if any(data[name]["status"] != "completed" for name in ("validation", "recovery", "prior", "compiled")):
        raise ValueError("completed raw experiments required")
    validation = data["validation"]["trials"]
    recovered = [t for t in data["recovery"]["trials"] if not t["warmup"]]
    prior = [t for t in data["prior"]["trials"] if not t["warmup"] and t["case"] == "jenkins_word" and
             t["profile"] == "gcc-O2" and t["variant"] == "original"]
    old_hashes = {t["binary_sha256"] for t in prior}
    if len(old_hashes) != 1 or old_hashes != {t["binary_sha256"] for t in recovered}:
        raise ValueError("old and new recovery records do not bind the same binary")
    compiled = data["compiled"]["records"]
    completion = args.circuit / "completion.json"
    circuit_done = json.loads(completion.read_text())
    protocol_path = args.circuit / "protocol.json"
    protocol = json.loads(protocol_path.read_text())
    paths.update(circuit_completion=completion, circuit_protocol=protocol_path, script=Path(__file__))
    report = {"schema_version": 1,
        "scope": "observer coverage; no candidate selection or protection gain; old grades retained",
        "source_bindings": {str(path): digest(path) for path in paths.values()},
        "validation": {
            "statuses": dict(Counter(t["status"] for t in validation)),
            "negative_control_statuses": dict(Counter(t.get("negative_control", {}).get("status") for t in validation)),
            "distinct_answer_artifacts": len({t["candidate_sha256"] for t in validation}),
            "rows": [{**{k: t[k] for k in ("id", "case", "profile", "variant", "status", "candidate_sha256")},
                      "adapter": t["answer"]["reconstruction"]} for t in validation]},
        "circuit_followup": {
            "controls_passed": circuit_done["controls_passed"],
            "saved_answer_statuses": dict(Counter(r["status"] for r in data["circuit"] if r["kind"] == "saved-answer")),
            "control_statuses": dict(Counter(r["status"] for r in data["circuit"] if r["kind"] != "saved-answer")),
            "distinct_saved_queries": len({c["binding"]["query_sha256"] for c in protocol["cases"] if c["kind"] == "saved-answer"})},
        "finite_checks": {
            "inputs_per_build": data["compiled"]["vectors"],
            "all_checks_passed": all(r["passed"] for r in compiled),
            "answer_builds": sum(r["kind"] == "answer" for r in compiled),
            "wrong_output_builds": sum(r["kind"] == "wrong-output" for r in compiled),
            "correct_answer_comparisons": sum(r["matches"] for r in compiled if r["kind"] == "answer"),
            "wrong_output_comparisons": sum(r["total"] for r in compiled if r["kind"] == "wrong-output"),
            "wrong_output_matches": sum(r["matches"] for r in compiled if r["kind"] == "wrong-output")},
        "jenkins_recovery": {
            "binary_sha256": next(iter(old_hashes)),
            "prior_measured_statuses": dict(Counter(t["status"] for t in prior)),
            "new_measured_statuses": dict(Counter(t["status"] for t in recovered)),
            "new_warmup_statuses": dict(Counter(t["status"] for t in data["recovery"]["trials"] if t["warmup"])),
            "distinct_answer_artifacts": len({t["candidate_sha256"] for t in recovered}),
            "negative_control_statuses": dict(Counter(t["negative_control"]["status"] for t in recovered)),
            "resources": {key: distribution([t["resources"][key] for t in recovered]) for key in
                          ("wall_seconds", "cpu_seconds", "peak_process_rss_bytes", "peak_sampled_tree_rss_bytes")},
            "stages": {key: distribution([t["answer"][key] for t in recovered]) for key in
                       ("headless_seconds", "reconstruction_seconds")},
            "grade_wall_seconds": distribution([t["verification"]["resources"]["wall_seconds"] for t in recovered]),
            "adapter": recovered[0]["answer"]["reconstruction"]}}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True); stream.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
