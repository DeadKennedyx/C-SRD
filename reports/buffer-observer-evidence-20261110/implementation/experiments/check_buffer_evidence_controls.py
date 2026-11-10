#!/usr/bin/env python3
"""Reject tampered copies of real buffer reports without modifying their artifacts."""
import argparse
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import file_hash, write_json
from check_buffer_evidence import check_reconstruction, check_runtime


def control(original, check, name, mutate, expected):
    data = json.loads(original.read_text()); mutate(data)
    # The copied report shares the original artifact parent, but gets a new
    # temporary filename. No recorded input, counter or result file is edited.
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", prefix="evidence-control-", dir=original.parent) as stream:
        json.dump(data, stream); stream.flush()
        try:
            check(Path(stream.name))
        except ValueError as error:
            if expected not in str(error): raise ValueError(f"{name} failed for an unrelated reason: {error}")
            return {"control": name, "status": "rejected", "reason": str(error)}
    raise ValueError(name + " was incorrectly accepted")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reconstruction-report", required=True)
    p.add_argument("--runtime-report", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = {"status": "running", "controls": []}
    reconstruction, runtime = Path(args.reconstruction_report), Path(args.runtime_report)
    before = {str(path): file_hash(path) for path in (reconstruction, runtime)}
    try:
        result["positive_reconstruction"] = check_reconstruction(reconstruction)
        result["positive_runtime"] = check_runtime(runtime)
        variants = [
            ("missing-observation", lambda r: r["observations"].pop(), "missing/duplicate attempts"),
            ("duplicate-schedule", lambda r: r["schedule"].__setitem__(1, r["schedule"][0]), "missing/duplicate attempts"),
            ("wrong-answer-identity", lambda r: r["observations"][0].__setitem__("recovered_sha256", "0"*64), "artifact hash mismatch"),
            ("invented-proof-status", lambda r: r["observations"][0].__setitem__("verification", "counterexample"), "proof selection/status mismatch"),
            ("missing-control", lambda r: r["observations"][0]["controls"].clear(), "missing corruption control")]
        for name, mutation, error in variants:
            result["controls"].append(control(reconstruction, check_reconstruction, name, mutation, error))

        def false_fit(r):
            target = next(iter(r["observations"][0]["fit"]["targets"].values()))
            target["recovery"]["validated_models"] += 1

        variants = [
            ("missing-runtime-group", lambda r: r["observations"].pop(), "runtime schedule incomplete"),
            ("changed-trace-hash", lambda r: r["observations"][0]["traces"][0].__setitem__("sha256", "0"*64), "artifact hash mismatch"),
            ("changed-training-membership", lambda r: r["observations"][0]["traces"][0].__setitem__("split", "heldout"), "wrong trace partition"),
            ("invented-recovery-count", false_fit, "fit replay differs")]
        for name, mutation, error in variants:
            result["controls"].append(control(runtime, check_runtime, name, mutation, error))
        if any(file_hash(path) != digest for path, digest in before.items()): raise ValueError("original report changed")
        result.update(status="passed", original_reports=before)
    except Exception as error:
        result.update(status="failed", error=str(error))
    write_json(Path(args.output), result)
    print(result["status"], len(result["controls"]), result.get("error", ""), flush=True)
    return int(result["status"] == "failed")


if __name__ == "__main__":
    raise SystemExit(main())
