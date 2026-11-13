#!/usr/bin/env python3
"""Compare fixed input/output observers with matched original executions.

Identical probes, outputs and learned candidates are reported separately from
source-model grading. A fitted hypothesis is never promoted to a recovery here.
"""
import argparse
from collections import Counter, defaultdict
import itertools
import json
from pathlib import Path

from effort_resources import save
from session_evidence import Evidence, distribution, local

ROOT = Path(__file__).resolve().parents[1]
SUCCESS = "recovered-under-source-model"


def read_report(path, evidence):
    report = evidence.read(path)
    if report["status"] != "completed" or report["observer"] not in ("bitlinear", "blackbox"):
        raise ValueError("completed input/output observer collection required")
    for artifact, sha in report["artifact_bindings"].items():
        evidence.bind(artifact, sha)
    protocol = report["protocol"]
    matrix_path = Path(protocol["matrix_report"])
    matrix_path = local(matrix_path if matrix_path.is_absolute() else ROOT/matrix_path)
    if matrix_path not in {local(p) for p in report["artifact_bindings"]}:
        raise ValueError("query collection lacks a bound build matrix")
    matrix = evidence.read(matrix_path)
    records = {(r["case"], r["profile"], r["variant"]): r for r in matrix["records"]}
    cases = {c["id"]: c for c in matrix["cases"]}
    expected = set(itertools.product(protocol["case"], protocol["profile"], protocol["variant"],
                                     range(len(protocol["budgets"])),
                                     range(-protocol["warmups"], protocol["repetitions"])))
    keys = [(t["case"], t["profile"], t["variant"], t["budget_id"], t["repetition"]) for t in report["trials"]]
    if (len(keys) != len(set(keys)) or set(keys) != expected or
            len({t["id"] for t in report["trials"]}) != len(keys)):
        raise ValueError("duplicate or missing query trial")
    queries = {}
    for trial in report["trials"]:
        directory = local(trial["directory"])
        if evidence.read(directory/"trial.json") != trial:
            raise ValueError("query trial differs from collection")
        if evidence.read(directory/"observer/measurement/resources.json") != trial["resources"]:
            raise ValueError("observer counters differ from trial")
        config = evidence.read(directory/"observer/config.json")
        built = records[(trial["case"], trial["profile"], trial["variant"])]
        original = records[(trial["case"], trial["profile"], "original")]
        case = cases[trial["case"]]
        if (built["status"] != "completed" or built["binary_sha256"] != trial["binary_sha256"] or
                local(built["binary"]) != local(config["binary"]) or
                (config["function"], config["arity"]) != (case["function"], case["arity"])):
            raise ValueError("observer artifact/interface differs from its matrix cell")
        if (config["observer"] != report["observer"] or
                trial["warmup"] != (trial["repetition"] < 0) or
                trial["budget"] != protocol["budgets"][trial["budget_id"]] or
                any(config[k] != v for k, v in trial["budget"].items()) or
                config["input_seed"] != protocol["input_seed"] + max(trial["repetition"], 0)):
            raise ValueError("observer configuration differs from protocol")
        evidence.bind(config["binary"], trial["binary_sha256"])
        answer = trial.get("answer")
        if answer is not None and evidence.read(directory/"observer/answer.json") != answer:
            raise ValueError("observer answer differs from trial")
        if "query_accounting" in trial:
            query = evidence.read(directory/"observer/queries.json")
            if {k: query[k] for k in ("attempted", "completed")} != trial["query_accounting"]:
                raise ValueError("query counts differ from transcript")
            if query["completed"] is not None:
                n = query["completed"]
                if n != len(query["inputs"]) or n != len(query["outputs"]) or n != query["attempted"]:
                    raise ValueError("incomplete query transcript")
                if answer is not None and n != answer["training_queries"]:
                    raise ValueError("answer query count differs from transcript")
                queries[trial["id"]] = query
        if "candidate_sha256" in trial:
            if trial["reference_preprocessed_sha256"] != original["preprocessed_sha256"]:
                raise ValueError("source grade uses a different original")
            evidence.bind(directory/"observer/candidate.c", trial["candidate_sha256"])
            verification = trial["verification"]
            if evidence.read(directory/"grade/measurement/resources.json") != verification["resources"]:
                raise ValueError("grade counters differ from trial")
            status = "inconclusive"
            if "proof" in verification:
                proof = evidence.read(directory/"grade/proof.json")
                if (proof["source_sha256"] != trial["reference_preprocessed_sha256"] or
                        proof["candidate_sha256"] != trial["candidate_sha256"] or
                        proof["functions"] != [verification["proof"]] or
                        verification["status"] != verification["proof"]["verification"]):
                    raise ValueError("candidate grade differs from trial")
                status = {"proved-under-model": SUCCESS, "counterexample": "wrong-candidate"}.get(
                    proof["functions"][0]["verification"], "inconclusive")
            elif verification["status"] != "inconclusive":
                raise ValueError("decidable grade lacks its proof record")
            if status != trial["status"]:
                raise ValueError("candidate outcome disagrees with source grade")
            negative = evidence.read(directory/"negative-control/proof.json")
            if (negative["source_sha256"] != trial["candidate_sha256"] or
                    negative["functions"] != [trial["negative_control"]["proof"]] or
                    trial["negative_control"]["status"] != "counterexample" or
                    negative["functions"][0]["verification"] != "counterexample"):
                raise ValueError("negative control missing or not rejected")
            evidence.bind(directory/"mutant.c", negative["candidate_sha256"])
    return report, queries


def paired_trials(trials, queries):
    measured = [t for t in trials if not t["warmup"]]
    originals = {(t["case"], t["profile"], t["budget_id"], t["repetition"]): t
                 for t in measured if t["variant"] == "original"}
    rows = []
    for trial in measured:
        original = originals[(trial["case"], trial["profile"], trial["budget_id"], trial["repetition"])]
        query, base_query = queries.get(trial["id"]), queries.get(original["id"])
        inputs_equal = None if query is None or base_query is None else query["inputs"] == base_query["inputs"]
        outputs_equal = None if inputs_equal is not True else query["outputs"] == base_query["outputs"]
        answer, baseline = trial.get("answer") or {}, original.get("answer") or {}
        model, base_model = answer.get("model"), baseline.get("model")
        recovered = trial["status"] == original["status"] == SUCCESS
        count, base_count = answer.get("training_queries"), baseline.get("training_queries")
        rows.append({**{k: trial[k] for k in ("id", "case", "profile", "variant", "budget_id", "repetition", "status")},
                     "query_budget": trial["budget"]["query_budget"], "original_status": original["status"],
                     "inputs_identical": inputs_equal, "outputs_identical": outputs_equal,
                     "models_identical": None if model is None or base_model is None else model == base_model,
                     "candidates_identical": (trial["candidate_sha256"] == original["candidate_sha256"]
                         if "candidate_sha256" in trial and "candidate_sha256" in original else None),
                     "both_recovered_under_source_model": recovered,
                     "recovery_query_ratio": (count/base_count if recovered and query is not None and base_query is not None
                                               and count is not None and base_count else None),
                     "cpu_ratio_on_success": (trial["resources"]["cpu_seconds"]/original["resources"]["cpu_seconds"]
                         if recovered and original["resources"].get("cpu_seconds", 0) > 0 else None)})
    return rows


def summarize(rows):
    grouped = defaultdict(list)
    for row in rows:
        grouped[(row["case"], row["profile"], row["variant"], row["budget_id"])].append(row)
    result = []
    for key, group in sorted(grouped.items()):
        result.append({**dict(zip(("case", "profile", "variant", "budget_id"), key)),
                       "query_budget": group[0]["query_budget"], "attempts": len(group),
                       "outcomes": dict(Counter(r["status"] for r in group)),
                       "original_outcomes": dict(Counter(r["original_status"] for r in group)),
                       "comparisons": {k: {"compared": sum(r[k] is not None for r in group),
                                             "identical": sum(r[k] is True for r in group)}
                           for k in ("inputs_identical", "outputs_identical", "models_identical", "candidates_identical")},
                       "paired_recovery_query_ratio": distribution([r["recovery_query_ratio"] for r in group]),
                       "paired_recovery_cpu_ratio": distribution([r["cpu_ratio_on_success"] for r in group])})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--effort-report", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    evidence = Evidence()
    report, queries = read_report(args.effort_report, evidence)
    rows = paired_trials(report["trials"], queries)
    for path in (Path(__file__), ROOT/"tools/session_evidence.py", ROOT/"tools/effort_resources.py"):
        evidence.bind(path)
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=False)
    save(output/"pairs.json", rows)
    summary = {"status": "completed", "observer": report["observer"], "protocol": report["protocol"],
               "source_bindings": evidence.bindings, "trial_pairs": len(rows), "cells": summarize(rows),
               "scope": "same-artifact repeated experiments; source-model grading trusts compilation; no human-effort claim",
               "query_scope": "minimum only on this observer's tested grid; matching transcripts alone are finite evidence",
               "cpu_scope": "whole observer process plus child query execution, including Python startup; grading excluded",
               "outcomes": dict(Counter(r["status"] for r in rows))}
    save(output/"summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("status", "trial_pairs", "outcomes")}))


if __name__ == "__main__":
    main()
