#!/usr/bin/env python3
"""Bounded register/stack observer and affine recovery on controlled benign runs.

This is observation, not debugger interference. A fitted affine map is learned
from training trace/value pairs, without receiving representation parameters.
"""
import argparse
import json
from pathlib import Path
import re
import sys
import time

from audit_protection import Runner, executable, file_hash, write_json, AuditError

MOD = 2**32
ROOT = Path(__file__).resolve().parents[1]
# Both inputs vary. Target sums include odd differences, allowing modular inversion.
TRAINING = [(3, 14), (8, 12), (105, 39), (0xfffffff0, 27)]
HELDOUT = [(9, 0xfffffff3), (123, 456), (0x7fffffff, 19), (0xffffffff, 0xffffffff)]


def locations(trace):
    return {f"{s['offset']}:{s['visit']}:{location}": value
            for s in trace["samples"] for location, value in s["values"].items()}


def fit_affine(traces, targets, *, identity_fallback=False):
    """Fit observed = a * target + b modulo 2^32; only invertible maps qualify."""
    if len(traces) != len(targets) or len(traces) < 3:
        raise ValueError("at least three paired training observations required")
    rows = [locations(t) for t in traces]
    common = set.intersection(*(set(r) for r in rows))
    pair = next(((i, j) for i in range(len(targets)) for j in range(i)
                 if (targets[i] - targets[j]) & 1), None)
    if pair is None and not identity_fallback:
        return [], len(common)
    if pair is not None:
        i, j = pair
        inverse = pow((targets[i] - targets[j]) % MOD, -1, MOD)
    models = []
    for location in sorted(common):
        if pair is None:
            # Observed plaintext is a candidate even when affine parameters
            # cannot be uniquely inferred from this training basis. Held-out
            # validation still decides whether the location is useful.
            if identity_fallback and all(row[location]==t for row,t in zip(rows,targets)):
                models.append({"location":location,"a":1,"b":0,"inverse":1,"method":"literal-identity"})
            continue
        a = ((rows[i][location] - rows[j][location]) * inverse) % MOD
        b = (rows[i][location] - a * targets[i]) % MOD
        if a & 1 and all((a * t + b) % MOD == row[location] for row, t in zip(rows, targets)):
            models.append({"location": location, "a": a, "b": b, "inverse": pow(a, -1, MOD)})
    return models, len(common)


def score_models(models, traces, targets):
    rows = [locations(t) for t in traces]
    scored = []
    for m in models:
        values = [None if m["location"] not in row else
                  ((row[m["location"]] - m["b"]) * m["inverse"]) % MOD for row in rows]
        scored.append({**m, "recovered": values, "correct": sum(a == b for a, b in zip(values, targets)),
                       "available": sum(v is not None for v in values), "total": len(targets)})
    return {"models": scored,
            "validated_models": sum(m["correct"] == m["total"] for m in scored),
            "false_models": sum(m["available"] == m["total"] and m["correct"] != m["total"] for m in scored),
            "inconclusive_models": sum(m["available"] != m["total"] for m in scored)}


def run(args, root):
    report = {"schema_version": 1, "status": "running", "commands": [], "observations": [],
              "target": "sum of the two u32 inputs modulo 2^32",
              "claims": {"exhaustive_memory_coverage": False, "confidentiality": "not-established",
                         "human_reconstruction_effort": "not-assessed"}}
    command = Runner(report)
    try:
        matrix = json.loads(Path(args.matrix_report).read_text())
        report["matrix_sha256"] = file_hash(args.matrix_report)
        case = next(c for c in matrix["cases"] if c["id"] == args.case)
        if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", case["function"]):
            raise ValueError("invalid observed function name")
        if case["arity"] != 2:
            raise ValueError("current runtime protocol requires two u32 parameters")
        profile = next(p for p in matrix["profiles"] if p["id"] == args.profile)
        if profile.get("lto", "none") != "none" or profile.get("sanitizers") or profile.get("pgo"):
            raise ValueError("runtime observer currently requires an ordinary non-LTO, non-instrumented build")
        try:
            gdb = executable(args.gdb)
        except ValueError as error:
            report.update(status="unavailable", error=str(error))
            return report
        report["gdb"] = {"path": gdb, "sha256": file_hash(gdb),
                          "version": command([gdb, "--version"]).splitlines()[0]}
        report["protocol"] = {"training": TRAINING, "heldout": HELDOUT, "step_limit": args.step_limit,
                              "observer": "affine-map-fit-v1", "negative_control": "permuted training target labels"}
        selected = [r for r in matrix["records"] if r["case"] == args.case
                    and r["profile"] == args.profile and r["variant"] in args.variant]
        if {r["variant"] for r in selected} != set(args.variant):
            raise ValueError("requested variant missing")
        for record in selected:
            if record["status"] != "completed" or file_hash(record["binary"]) != record["binary_sha256"]:
                raise ValueError("binary is not a completed, unchanged matrix artifact")
            directory = root / record["variant"]
            directory.mkdir()
            observation = {"variant": record["variant"], "binary_sha256": record["binary_sha256"],
                           "status": "running", "traces": []}
            report["observations"].append(observation)
            start = time.perf_counter()
            for index, vector in enumerate(TRAINING + HELDOUT):
                input_path, config_path = directory / f"{index}.input", directory / f"{index}.json"
                output_path = directory / f"{index}.trace.json"
                input_path.write_text(" ".join(map(str, vector)) + "\n")
                write_json(config_path, {"function": case["function"], "step_limit": args.step_limit,
                                        "input_file": str(input_path), "output": str(output_path)})
                script = directory / f"{index}.gdb"
                # Python repr quotes paths; GDB source code is fixed, never supplied C.
                script.write_text("python\nimport sys\nsys.path.insert(0, " + repr(str(ROOT / "tools")) +
                                  ")\nimport gdb_trace\ngdb_trace.main(" + repr(str(config_path)) + ")\nend\n")
                command([gdb, "--nx", "--batch", "-iex", "set auto-load off",
                         "-x", script, "--args", record["binary"]], timeout=120)
                if file_hash(record["binary"]) != record["binary_sha256"]:
                    raise ValueError("observed binary changed during tracing")
                trace = json.loads(output_path.read_text())
                observation["traces"].append({"path": str(output_path), "sha256": file_hash(output_path),
                                               "status": trace["status"], "steps": trace.get("steps", 0)})
                if trace["status"] != "completed":
                    raise ValueError(f"trace incomplete: {trace.get('error', trace['status'])}")
            traces = [json.loads(Path(t["path"]).read_text()) for t in observation["traces"]]
            train_targets = [(x + y) % MOD for x, y in TRAINING]
            test_targets = [(x + y) % MOD for x, y in HELDOUT]
            models, searched = fit_affine(traces[:len(TRAINING)], train_targets)
            negative, _ = fit_affine(traces[:len(TRAINING)], train_targets[1:] + train_targets[:1])
            observation.update(status="completed", training_locations_searched=searched,
                               recovery=score_models(models, traces[len(TRAINING):], test_targets),
                               negative_control=score_models(negative, traces[len(TRAINING):], test_targets),
                               elapsed_seconds=time.perf_counter() - start,
                               instruction_steps=sum(t["steps"] for t in traces))
            observation["literal_presence"] = [
                {"input": list(v), "locations_equal_to_target": sum(value == target for value in locations(t).values())}
                for v, target, t in zip(TRAINING + HELDOUT, train_targets + test_targets, traces)]
        report["status"] = "completed"
    except (AuditError, OSError, ValueError, KeyError, StopIteration) as error:
        report.update(status="failed", error=str(error))
    finally:
        write_json(root / "observation.json", report)
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--matrix-report", required=True)
    p.add_argument("--case", default="calculate")
    p.add_argument("--profile", default="clang-O2")
    p.add_argument("--variant", action="append", default=None)
    p.add_argument("--gdb", default="gdb")
    p.add_argument("--step-limit", type=int, default=512)
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    args.variant = args.variant or ["original", "affine-42"]
    if not 1 <= args.step_limit <= 10000:
        p.error("step limit must be 1..10000")
    root = Path(args.output_dir).resolve()
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        p.error(f"new output directory required: {error}")
    result = run(args, root)
    print(f"{result['status']}: {root / 'observation.json'}")
    return 1 if result["status"] == "failed" else 2 if result["status"] == "unavailable" else 0


if __name__ == "__main__":
    sys.exit(main())
