#!/usr/bin/env python3
"""Bind the complete observer repeat and separate query replays to frozen inputs."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from effort_statistics import summarize
from grade_saved_answers import bound_query
from summarize_positional_widths import circuit_followup, completion_timeline


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(path):
    path = Path(path)
    if path.is_relative_to("/work"):
        return ROOT / path.relative_to("/work")
    return path if path.is_absolute() else ROOT / path


class Evidence:
    def __init__(self):
        self.bindings = {}

    def bind(self, path, expected=None):
        path = local(path).resolve()
        actual = digest(path)
        if expected is not None and actual != expected:
            raise ValueError("bound evidence changed: " + str(path))
        self.bindings[str(path.relative_to(ROOT))] = actual
        return path

    def read(self, path, expected=None):
        return json.loads(self.bind(path, expected).read_text())


def outcomes(trials):
    return dict(Counter(t["status"] for t in trials if not t["warmup"]))


def distribution(values):
    return {"n": len(values), "median": statistics.median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def replay(directory, trials, evidence, older=False):
    """Validate exact source/query/report/tool bindings before deriving statuses."""
    protocol = evidence.read(directory / "protocol.json")
    rows = evidence.read(directory / "summary.json")
    completion = evidence.read(directory / "completion.json")
    if (completion["status"] != "completed" or completion["controls_passed"] is not True or
            completion["historical_records_modified"] is not False):
        raise ValueError("complete controlled query replay required")
    for path, expected in protocol["bindings"].items():
        evidence.bind(path, expected)
    if older:
        if protocol["budgets_seconds"] != [30, 120] or protocol["stage_extra_seconds"] != 5:
            raise ValueError("changed prior budget grid")
    elif (protocol["solver_seconds"], protocol["stage_seconds"]) != (30, 35):
        raise ValueError("changed new grading budget")
    groups = {g["query_sha256"]: g for g in protocol["queries"]}
    if len(groups) != len(protocol["queries"]):
        raise ValueError("duplicate query group")
    selected = {t["id"]: t for t in trials if not t["warmup"] and t["status"] == "inconclusive"}
    if not older and set(protocol["selected_trials"]) != set(selected):
        raise ValueError("query selection differs from the full unknown cohort")
    verified, controls, reports, checked = {}, [], [], set()
    for row in rows:
        group = groups[row["query_sha256"]]
        if (row["kind"], row["expected"]) != (group["kind"], group["expected"]):
            raise ValueError("query role mismatch")
        report_path = evidence.bind(row["report"], row["report_sha256"])
        report = json.loads(report_path.read_text())
        query = evidence.bind(group["query"], group["query_sha256"])
        budget = row["budget_seconds"] if older else protocol["solver_seconds"]
        if (report["solver_seconds"], report["stage_wall_seconds"]) != (budget, budget+5):
            raise ValueError("query was run with a different budget")
        for field in ("status", "query_sha256", "total_wall_seconds", "child_cpu_seconds"):
            if row[field] != report[field]:
                raise ValueError("query summary/report mismatch: " + field)
        if report["status"] in ("sat", "unsat") and report.get("circuit_validation", {}).get("status") != "circuit-validated":
            raise ValueError("circuit was not independently validated")
        for artifact, expected in report["artifacts"].items():
            evidence.bind(report_path.parent / artifact, expected)
        for tool in report["tools"].values():
            evidence.bind(tool["path"], tool["sha256"])
            if protocol["bindings"].get(tool["path"]) != tool["sha256"]:
                raise ValueError("circuit tool is not bound in protocol")
        key = (group["query_sha256"], budget)
        if key in checked:
            raise ValueError("duplicate query result at one budget")
        checked.add(key)
        if group["expected"] is not None:
            if report["status"] != group["expected"] or row["control_passed"] is not True:
                raise ValueError("grading control failed")
            controls.append({"kind": group["kind"], "query_sha256": group["query_sha256"], "status": report["status"], "budget_seconds": budget})
        if group["query_sha256"] in verified and verified[group["query_sha256"]]["status"] != "inconclusive":
            raise ValueError("unexpected rerun of a decided query")
        verified[group["query_sha256"]] = row
        reports.append({"kind": group["kind"], "query_sha256": group["query_sha256"],
            "budget_seconds": budget, "status": report["status"], "report": str(report_path.relative_to(ROOT)),
            "total_wall_seconds": report["total_wall_seconds"], "child_cpu_seconds": report["child_cpu_seconds"],
            "stages": {k: {f: v.get(f) for f in ("status", "wall_seconds", "cpu_seconds", "peak_process_rss_bytes", "peak_sampled_tree_rss_bytes")}
                       for k, v in report["stages"].items()}})
    if set(verified) != set(groups):
        raise ValueError("missing query result")
    changes, seen = {}, {"saved-answer": set(), "negative-control": set()}
    for sha, group in groups.items():
        if group["kind"] == "rule-control":
            continue
        members = group["original_cases"] if older else group["members"]
        for member in members:
            identifier = int(member["name"].split("-")[1]) if older else member["trial"]
            if identifier not in selected or identifier in seen[group["kind"]]:
                raise ValueError("unexpected or duplicate trial membership")
            seen[group["kind"]].add(identifier)
            trial = selected[identifier]
            folder = local(trial["directory"])
            raw = evidence.read(folder / "trial.json", member["trial_sha256"])
            if any(raw[k] != trial[k] for k in raw if k != "status"):
                raise ValueError("derived trial changed fields other than status")
            section = "grade" if group["kind"] == "saved-answer" else "negative-control"
            binding, text = bound_query(folder, section)
            if binding != member["binding"] or digest(evidence.bind(group["query"])) != sha or text != local(group["query"]).read_text():
                raise ValueError("query does not equal the frozen source obligation")
            if member["binary_sha256"] != trial["binary_sha256"] or (member["profile"], member["variant"]) != (trial["profile"], trial["variant"]):
                raise ValueError("query bound to different artifact")
            for item in binding["files"]:
                evidence.bind(item["path"], item["sha256"])
            evidence.bind(binding["grade_report"], binding["grade_report_sha256"])
            evidence.bind(folder / section / "measurement/command.json", binding["command_sha256"])
            if group["kind"] == "saved-answer":
                evidence.bind(folder / "observer/candidate.c", trial["candidate_sha256"])
                status = verified[sha]["status"]
                if status not in ("unsat", "sat", "inconclusive"):
                    raise ValueError("unrecognized circuit result")
                changes[identifier] = {"trial": identifier, "case": trial["case"], "profile": trial["profile"],
                    "variant": trial["variant"], "query_sha256": sha, "candidate_sha256": trial["candidate_sha256"],
                    "original_status": trial["status"], "circuit_status": status,
                    "derived_status": {"unsat": "recovered-under-source-model", "sat": "wrong-candidate", "inconclusive": "inconclusive"}[status]}
    if any(ids != set(selected) for ids in seen.values()):
        raise ValueError("not every selected trial and negative control was covered")
    if len([g for g in groups.values() if g["kind"] == "rule-control"]) != 3:
        raise ValueError("three independent arithmetic controls required")
    derived = [{**t, "status": changes[t["id"]]["derived_status"] if t["id"] in changes else t["status"]} for t in trials]
    unknown = [sha for sha, row in verified.items() if row["kind"] == "saved-answer" and row["status"] == "inconclusive"]
    if set(unknown) != set(completion["unresolved_query_sha256"]):
        raise ValueError("completion unresolved list differs from query results")
    return derived, {"selected_trials": len(selected), "distinct_queries": len(groups), "controls": controls,
        "changes": list(changes.values()), "query_results": reports, "outcomes": outcomes(derived),
        "grader_wall_seconds_total": sum(r["total_wall_seconds"] for r in reports),
        "grader_cpu_seconds_total": sum(r["child_cpu_seconds"] for r in reports),
        "scope": "deduplicated query grading only, never observer CPU; per-trial memberships are not independent grader runs"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--observer-run", type=Path, required=True)
    parser.add_argument("--prior-repeat", type=Path, required=True)
    parser.add_argument("--prior-circuit", type=Path, required=True)
    parser.add_argument("--old-query-replay", type=Path, required=True)
    parser.add_argument("--new-query-replay", type=Path, required=True)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for name, value in vars(args).items():
        setattr(args, name, value.resolve())
    evidence = Evidence()
    for script in (Path(__file__).resolve(), ROOT / "tools/effort_statistics.py", ROOT / "experiments/summarize_positional_widths.py"):
        evidence.bind(script)
    old = evidence.read(args.prior_repeat / "effort/effort.json")
    new = evidence.read(args.observer_run / "effort/effort.json")
    complete = evidence.read(args.observer_run / "completion.json")
    protocol = evidence.read(args.observer_run / "protocol.json")
    if old["status"] != "completed" or new["status"] != "completed" or complete["status"] != "completed":
        raise ValueError("completed observer experiments required")
    if complete["bindings"] != protocol["bindings"]:
        raise ValueError("observer input bindings changed")
    for path, expected in complete["bindings"].items():
        evidence.bind(path, expected)
    matrix_path = next(p for p in new["artifact_bindings"] if p.endswith("/matrix/matrix.json"))
    matrix = evidence.read(matrix_path, new["artifact_bindings"][matrix_path])
    for path, expected in new["artifact_bindings"].items():
        evidence.bind(path, expected)
    by_cell = {(r["case"], r["profile"], r["variant"]): r for r in matrix["records"]}
    for trial in new["trials"]:
        folder = local(trial["directory"])
        raw = evidence.read(folder / "trial.json")
        if raw != trial:
            raise ValueError("individual trial differs from completed report")
        artifact = by_cell[(trial["case"], trial["profile"], trial["variant"])]
        evidence.bind(artifact["binary"], trial["binary_sha256"])
        if artifact["binary_sha256"] != trial["binary_sha256"]:
            raise ValueError("observer binary differs from matrix")
        export = folder / "observer/export.json"
        if export.exists():
            observed_export = evidence.read(export)
            retained_export = {k: v for k, v in observed_export.items() if k not in ("nodes", "operations", "blocks")}
            if retained_export != trial["answer"]["export"]:
                raise ValueError("export metadata differs from trial")
        if "candidate_sha256" in trial:
            evidence.bind(folder / "observer/candidate.c", trial["candidate_sha256"])
            baseline = by_cell[(trial["case"], trial["profile"], "original")]
            reference = local(baseline["binary"]).parent / "function.i"
            evidence.bind(reference, trial["reference_preprocessed_sha256"])
            binding, _ = bound_query(folder, "grade")
            if [local(f["path"]).resolve() for f in binding["files"]] != [reference.resolve(), (folder / "observer/candidate.c").resolve()]:
                raise ValueError("grade compares different source artifacts")
            if binding["original_status"] != trial["verification"]["status"]:
                raise ValueError("saved source proof differs from trial status")
            evidence.bind(binding["grade_report"], binding["grade_report_sha256"])
            evidence.bind(folder / "grade/measurement/command.json", binding["command_sha256"])
    previous = circuit_followup(args.prior_circuit.resolve(), old, matrix, evidence.bindings)
    old_status = {r["trial"]: r["derived_status"] for r in previous["changes"]}
    intermediate = [{**t, "status": old_status.get(t["id"], t["status"])} for t in old["trials"]]
    old_derived, old_replay = replay(args.old_query_replay.resolve(), intermediate, evidence, older=True)
    new_derived, new_replay = replay(args.new_query_replay.resolve(), new["trials"], evidence)
    def key(t):
        return tuple(t[f] for f in ("case", "profile", "variant", "budget_id", "repetition"))
    old_map, new_map = {key(t): t for t in old_derived}, {key(t): t for t in new_derived}
    if len(old_map) != len(old_derived) or len(new_map) != len(new_derived) or set(old_map) != set(new_map):
        raise ValueError("repeat cells are missing, duplicated or different")
    transitions, cells = Counter(), []
    for k, trial in new_map.items():
        before = old_map[k]
        if any(before[f] != trial[f] for f in ("binary_sha256", "budget", "warmup")):
            raise ValueError("changed artifact or budget in matched repeat")
        if not trial["warmup"]:
            transitions[(before["status"], trial["status"])] += 1
    measured = [t for t in new_derived if not t["warmup"]]
    for cell in sorted({(t["case"], t["profile"], t["variant"]) for t in measured}):
        rows = [t for t in measured if (t["case"], t["profile"], t["variant"]) == cell]
        row = dict(zip(("case", "profile", "variant"), cell))
        row["outcomes"] = outcomes(rows)
        row["stages"] = {field: distribution([t["answer"][field] for t in rows if (t.get("answer") or {}).get(field) is not None])
                         for field in ("headless_seconds", "reconstruction_seconds", "training_queries", "target_decompile_requests")}
        row["export_stages"] = {field: distribution([t["answer"]["export"][field] for t in rows if (t.get("answer") or {}).get("export", {}).get(field) is not None])
                                for field in ("setup_seconds", "decompile_seconds", "seconds")}
        metrics = sorted({f for t in rows for f in (t.get("answer") or {}).get("reconstruction", {})})
        row["reconstruction"] = {field: distribution([t["answer"]["reconstruction"][field] for t in rows if type(t["answer"].get("reconstruction", {}).get(field)) in (int, float)])
                                 for field in metrics if field != "mode"}
        row["original_grading_wall_seconds"] = distribution([t["verification"]["resources"]["wall_seconds"] for t in rows if "verification" in t])
        cells.append(row)
    validation = evidence.read(args.development / "validation-summary.json")
    for path, expected in evidence.read(args.development / "final-source-bindings.json").items():
        evidence.bind(path, expected)
    for filename in ("ctest-final-native.log", "ctest-final-linux.log", "ctest-final-native-detail.log", "ctest-final-linux-detail.log"):
        evidence.bind(args.development / filename)
    prior_package = ROOT / "reports/positional-widths-evidence-20261110"
    prior_hashes = evidence.read(prior_package / "sha256.json")
    application = evidence.read(prior_package / "summary.json", prior_hashes["summary.json"])
    if application["source_bindings"][str(local(matrix_path).relative_to(ROOT))] != digest(local(matrix_path)):
        raise ValueError("application costs came from a different matrix")
    cell_keys = {(t["case"], t["profile"], t["variant"]) for t in measured}
    application_rows = [r for r in application["matrix"]["rows"] if (r["case"], r["profile"], r["variant"]) in cell_keys]
    summary = {"status": "completed", "observer_protocol": protocol, "validation": validation,
               "historical": {"initial_outcomes": outcomes(old["trials"]), "after_five_second_replay": previous["outcomes"],
                              "after_thirty_second_replay": outcomes(old_derived), "query_replay": old_replay},
               "current": {"total_trials": len(new["trials"]), "measured_trials": len(measured),
                           "warmups": len(new["trials"])-len(measured), "initial_outcomes": outcomes(new["trials"]),
                           "derived_outcomes": outcomes(new_derived), "query_replay": new_replay,
                           "negative_controls": dict(Counter(t["negative_control"]["status"] for t in measured if "negative_control" in t)),
                           "summary_after_grading": summarize(new_derived), "stages_by_cell": cells},
               "matched_outcome_transitions": [{"old": a, "new": b, "trials": n} for (a, b), n in sorted(transitions.items())],
               "application_costs_from_prior_matrix": application_rows,
               "timeline": completion_timeline(args.observer_run / "effort"),
               "interpretation": "Observer expansion on unchanged development binaries. Paired costs compare each candidate to its original within the NEW observer run. Source-model grades trust binary lifting. Warmups excluded. No human or memory-protection claim.",
               "source_bindings": evidence.bindings}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.output.exists():
        raise ValueError("refusing to overwrite a completed analysis")
    args.output.write_text(json.dumps(summary, indent=2)+"\n")
    costs = {(r["case"], r["profile"], r["variant"]): r for r in application_rows}
    stages = {(r["case"], r["profile"], r["variant"]): r for r in cells}
    table = []
    for group in summary["current"]["summary_after_grading"]["groups"]:
        cost = costs[(group["case"], group["profile"], group["variant"])]
        row = {k: group[k] for k in ("case", "profile", "variant", "attempts", "successful")}
        row["outcomes"] = json.dumps(group["outcomes"], sort_keys=True)
        stage = stages[(group["case"], group["profile"], group["variant"])]
        row["adapter_wall_seconds_median"] = stage["stages"]["reconstruction_seconds"]["median"]
        row["target_decompile_wall_seconds_median"] = stage["export_stages"]["decompile_seconds"]["median"]
        row["source_grading_wall_seconds_median"] = stage["original_grading_wall_seconds"]["median"]
        row.update({k: cost[k] for k in ("runtime_ratio", "function_symbol_bytes", "function_symbol_ratio", "text_section_bytes", "binary_size_ratio")})
        for metric in ("cpu_seconds", "wall_seconds", "peak_process_rss_bytes", "peak_sampled_tree_rss_bytes"):
            row[metric + "_median"] = group["resource_cost_all_attempts"][metric]["median"]
            paired = group["paired_successful_ratios"][metric]
            row[metric + "_paired_ratio"] = paired["median"]
            interval = paired["bootstrap_95_interval"] or [None, None]
            row[metric + "_ratio_interval_low"], row[metric + "_ratio_interval_high"] = interval
        table.append(row)
    with args.output.with_suffix(".csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(table[0])); writer.writeheader(); writer.writerows(table)
    print(json.dumps({"old": summary["historical"]["after_thirty_second_replay"], "new": summary["current"]["derived_outcomes"]}))


if __name__ == "__main__":
    main()
