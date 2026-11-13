#!/usr/bin/env python3
"""Derive paired session costs only after checking request and grading chains."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"tools"))
from effort_resources import save
from session_evidence import local, read_sessions
from grade_saved_answers import bound_query
from session_evidence import Evidence, distribution


def grades(source, followup, expected_groups, evidence):
    protocol = evidence.read(source/"protocol.json")
    complete = evidence.read(source/"completion.json")
    rows = evidence.read(source/"summary.json")
    if complete["status"] != "completed" or complete["controls_passed"] is not True:
        raise ValueError("completed controlled source grades required")
    for path, sha in protocol["bindings"].items(): evidence.bind(path, sha)
    expected = {(g["reference_sha256"], g["candidate_sha256"]): g for g in expected_groups}
    if len(rows) != len(expected) or len({r["id"] for r in rows}) != len(rows):
        raise ValueError("duplicate or missing answer grade")
    initial, statuses, by_id = {}, {}, {}
    for row in rows:
        key = (row["reference_sha256"], row["candidate_sha256"])
        group = expected[key]
        if row["members"] != group["members"] or key in statuses:
            raise ValueError("source grade membership mismatch")
        directory = local(row["directory"])
        if evidence.read(directory/"answer.json") != row:
            raise ValueError("answer record differs from source summary")
        for field, sha in (("reference", key[0]), ("candidate", key[1]), ("export", row["export_sha256"])):
            evidence.bind(row[field], sha)
        evidence.bind(directory/"mutant.c", row["mutant_sha256"])
        for section, expected_status, sha in (("grade", row["status"], row["grade_sha256"]),
                                              ("negative-control", "counterexample", row["negative_sha256"])):
            proof = evidence.read(directory/section/"proof.json", sha)
            if len(proof["functions"]) != 1 or proof["functions"][0]["verification"] != expected_status:
                raise ValueError("source proof result differs from summary")
            expected_hashes = key if section == "grade" else (key[1], row["mutant_sha256"])
            if (proof["source_sha256"], proof["candidate_sha256"]) != expected_hashes:
                raise ValueError("proof binds different C")
            evidence.bind(directory/section/"measurement/command.json")
            evidence.bind(directory/section/"measurement/resources.json")
        initial[key] = statuses[key] = row["status"]; by_id[row["id"]] = row
    if set(statuses) != set(expected): raise ValueError("ungraded answer")
    if followup is None:
        return initial,statuses,[]
    replay_protocol = evidence.read(followup/"protocol.json")
    replay_rows = evidence.read(followup/"summary.json")
    replay_complete = evidence.read(followup/"completion.json")
    if replay_complete["status"] != "completed" or replay_complete["controls_passed"] is not True:
        raise ValueError("completed controlled circuit replay required")
    for path, sha in replay_protocol["bindings"].items(): evidence.bind(path, sha)
    selected = {r["id"] for r in rows if r["status"] == "inconclusive"}
    if set(replay_protocol["selected_answers"]) != selected:
        raise ValueError("follow-up must include every unknown answer")
    queries = {q["query_sha256"]: q for q in replay_protocol["queries"]}
    if len(replay_rows) != len(queries) or {r["query_sha256"] for r in replay_rows} != set(queries):
        raise ValueError("duplicate or missing replay result")
    seen = {"saved-answer": set(), "negative-control": set()}
    for row in replay_rows:
        group = queries[row["query_sha256"]]
        query = evidence.bind(group["query"], group["query_sha256"])
        report_path = evidence.bind(row["report"], row["report_sha256"])
        report = json.loads(report_path.read_text())
        if (report["status"] != row["status"] or report["query_sha256"] != group["query_sha256"] or
                (report["solver_seconds"], report["stage_wall_seconds"]) != (30, 35) or
                (row["kind"], row["expected"]) != (group["kind"], group["expected"])):
            raise ValueError("query report/summary mismatch")
        if report["status"] in ("sat", "unsat") and report.get("circuit_validation", {}).get("status") != "circuit-validated":
            raise ValueError("unchecked Boolean circuit")
        for artifact, sha in report.get("artifacts", {}).items(): evidence.bind(report_path.parent/artifact, sha)
        for tool in report["tools"].values(): evidence.bind(tool["path"], tool["sha256"])
        if group["expected"] is not None and (row["status"] != group["expected"] or row["control_passed"] is not True):
            raise ValueError("circuit control failed")
        if group["kind"] == "rule-control": continue
        for member in group["members"]:
            identifier = member["answer"]
            if identifier not in selected or identifier in seen[group["kind"]]:
                raise ValueError("unexpected or duplicate replay membership")
            seen[group["kind"]].add(identifier)
            answer = by_id[identifier]
            key = (answer["reference_sha256"], answer["candidate_sha256"])
            if (member["reference_sha256"], member["candidate_sha256"]) != key:
                raise ValueError("replay bound to different answer")
            section = "grade" if group["kind"] == "saved-answer" else "negative-control"
            binding, text = bound_query(local(answer["directory"]), section)
            if binding != member["binding"] or text != query.read_text():
                raise ValueError("saved source obligation differs from replay")
            if section == "grade":
                statuses[key] = {"unsat": "proved-under-model", "sat": "counterexample"}.get(row["status"], "inconclusive")
    if any(members != selected for members in seen.values()):
        raise ValueError("missing replay answer or negative control")
    return initial, statuses, replay_rows


def batch_metrics(native, adapter):
    nr, ar = native["resources"], adapter["resources"]
    n = native["result"]["requests"]
    result = {role+"_cpu_ns_per_request": record["cpu_ns"][role]/n
              for role, record in (("native", nr), ("jvm", nr), ("adapter", ar))}
    result["combined_cpu_ns_per_request"] = sum(result.values())
    result["phase_wall_ns_per_request"] = (nr["wall_ns"]+ar["wall_ns"])/n
    for metric, values in (("decompile", native["result"]["decompile_ns"]),
                           ("flush", native["result"]["flush_ns"]),
                           ("reconstruct", adapter["result"]["reconstruct_ns"])):
        result[metric+"_wall_ns_per_request"] = sum(values)/n
    for role, record in (("native", nr), ("jvm", nr), ("adapter", ar)):
        for key in ("before_rss_bytes", "after_rss_bytes", "peak_sampled_rss_bytes"):
            result[role+"_"+key] = record[key][role]
    emitted=[m["emitted_statements"] for a,m in zip(adapter["result"]["answers"],adapter["result"]["metrics"]) if a.get("status","reconstructed")=="reconstructed"]
    result["emitted_statements"] = statistics.median(emitted) if emitted else None
    return result


def summarize_costs(payloads, statuses):
    memberships = defaultdict(Counter)
    for group, status in statuses:
        for member in group["members"]:
            if member["phase"].startswith("batch-"):
                memberships[member["session"]][status] += member["requests"]
    sessions, batches, calibration = [], [], []
    for payload in payloads:
        row, session, resources = payload["record"], payload["session"], payload["resources"]
        identity = {k: row[k] for k in ("id", "case", "profile", "variant", "repetition", "binary_sha256")}
        own_batches = []
        for native, adapter in zip(session["jvm"]["phases"][1:], session["adapter"]["phases"]):
            if native["phase"].startswith("batch-"):
                own_batches.append({**identity, "phase": native["phase"], **batch_metrics(native, adapter)})
                memberships[row["id"]]["unsupported"]+=sum(a.get("status")=="unsupported" for a in adapter["result"]["answers"])
            else:
                calibration.append({**identity, "phase": native["phase"], "requests": native["result"]["requests"],
                    "jvm_cpu_ns": native["resources"]["cpu_ns"]["jvm"],
                    "native_cpu_ns": native["resources"]["cpu_ns"]["native"],
                    "adapter_cpu_ns": adapter["resources"]["cpu_ns"]["adapter"]})
        numeric = [k for k in own_batches[0] if k not in (*identity, "phase")]
        medians = {key: None if any(b[key] is None for b in own_batches) else statistics.median(b[key] for b in own_batches) for key in numeric}
        if sum(memberships[row["id"]].values())!=sum(p["result"]["requests"] for p in session["adapter"]["phases"] if p["phase"].startswith("batch-")):
            raise ValueError("missing request grading outcomes")
        own_grades={k:v for k,v in memberships[row["id"]].items() if v}
        phase_cpu = sum(sum(p["resources"]["cpu_ns"].values()) for role in ("jvm", "adapter") for p in session[role]["phases"])/1e9
        sessions.append({**identity, **medians, "batches": len(own_batches), "grades": own_grades,
                         "session_cpu_seconds": resources["cpu_seconds"], "session_wall_seconds": resources["wall_seconds"],
                         "cpu_outside_phases_seconds": resources["cpu_seconds"]-phase_cpu,
                         "session_peak_sampled_tree_rss_bytes": resources["peak_sampled_tree_rss_bytes"]})
        batches += own_batches
    return sessions, batches, calibration


def paired(sessions, application):
    indexed = {(s["case"], s["profile"], s["variant"], s["repetition"]): s for s in sessions}
    grouped = defaultdict(list)
    for s in sessions: grouped[(s["case"], s["profile"], s["variant"])].append(s)
    rows = []
    for (case, profile, variant), group in sorted(grouped.items()):
        group.sort(key=lambda s: s["repetition"])
        original = [indexed[(case, profile, "original", s["repetition"])] for s in group]
        success = lambda s: set(s["grades"]) == {"proved-under-model"}
        row = {"case": case, "profile": profile, "variant": variant, "sessions": len(group),
               "all_measured_requests_proved_under_model": all(success(s) for s in group),
               "application": application[(case, profile, variant)], "metrics": {}}
        metrics = [key for key in group[0] if key.endswith(("_per_request", "_rss_bytes")) or key == "emitted_statements"]
        for key in metrics:
            attempts=[{"repetition":s["repetition"],"candidate":s[key],"original":b[key],"ratio":s[key]/b[key]}
                      for s,b in zip(group,original) if s[key] is not None and b[key] is not None and b[key]>0]
            ratios = [{"repetition": s["repetition"], "candidate": s[key], "original": b[key], "ratio": s[key]/b[key]}
                      for s, b in zip(group, original) if success(s) and success(b) and s[key] is not None and b[key] is not None and b[key] > 0]
            row["metrics"][key] = {"absolute": distribution([s[key] for s in group]),
                                  "paired_ratios": distribution([r["ratio"] for r in ratios]), "pairs": ratios,
                                  "attempt_paired_ratios":distribution([r["ratio"] for r in attempts]),
                                  "attempt_scope":"resource cost regardless of reconstruction success; refusals are not recovery"}
        rows.append(row)
    return rows


def write_csv(path, rows):
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0])); writer.writeheader(); writer.writerows(rows)


def application_timing(timing):
    """Expose the same cost columns for initial and longer frozen-binary runs."""
    return {"timing": timing, "runtime_ratio": timing.get("median_paired_ratio"),
            "cpu_ratio": timing.get("cpu_median_paired_ratio"),
            "cpu_median_seconds": timing.get("cpu_median_seconds"),
            "executable_peak_rss_bytes": timing.get("executable_peak_rss_median_bytes"),
            "rusage_peak_rss_bytes": timing.get("peak_rss_median_bytes")}


def matrix_application(records):
    completed = [r for r in records if r["status"] == "completed"]
    baselines = {(r["case"], r["profile"]): r for r in completed if r["variant"] == "original"}
    rows = {}
    for record in completed:
        key = (record["case"], record["profile"], record["variant"])
        if key in rows:
            raise ValueError("duplicate application matrix cell")
        baseline = baselines[key[:2]]
        rows[key] = {**application_timing(record["timing"]),
                     "binary_bytes": record["binary_bytes"], "binary_size_ratio": record["binary_size_ratio"],
                     "binary_bytes_identical_to_original": record["binary_sha256"] == baseline["binary_sha256"],
                     "comparison": record.get("comparison"), "function_symbol_ratio": None,
                     "function_symbol_scope": "not measured by this matrix; linked text measured separately"}
    return rows


def flat_cells(cells):
    rows = []
    for cell in cells:
        row = {k: cell[k] for k in ("case", "profile", "variant", "sessions", "all_measured_requests_proved_under_model")}
        for key in ("runtime_ratio", "cpu_ratio", "cpu_median_seconds", "executable_peak_rss_bytes", "rusage_peak_rss_bytes",
                    "function_symbol_ratio", "binary_size_ratio", "binary_bytes_identical_to_original"):
            row["application_"+key] = cell["application"].get(key)
        for key, value in cell["metrics"].items():
            row[key+"_median"] = value["absolute"]["median"]
            for kind in ("paired_ratios", "attempt_paired_ratios"):
                for statistic in ("n", "median", "min", "max"):
                    row[key+"_"+kind.removesuffix("s")+"_"+statistic] = value[kind][statistic]
        rows.append(row)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=Path, required=True)
    parser.add_argument("--grades", type=Path, required=True)
    parser.add_argument("--followup", type=Path, help="optional circuit replay; otherwise preserve inconclusive source grades")
    application_group=parser.add_mutually_exclusive_group(required=True)
    application_group.add_argument("--application-summary",type=Path)
    application_group.add_argument("--matrix-report",type=Path,help="read application costs directly from the exact bound matrix")
    parser.add_argument("--application-costs",type=Path,help="optional longer cost repetitions from measure_matrix_costs.py; requires --matrix-report")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(); evidence = Evidence()
    if args.application_costs and not args.matrix_report:parser.error("--application-costs requires --matrix-report")
    report, _, payloads, groups = read_sessions(args.sessions)
    evidence.bind(args.sessions)
    for path, sha in report["bindings"].items(): evidence.bind(path, sha)
    initial, final, replay = grades(args.grades, args.followup, groups, evidence)
    matrix_path = next(p for p in report["bindings"] if p.endswith("/matrix/matrix.json"))
    matrix_key = str(local(matrix_path).relative_to(ROOT))
    if args.matrix_report:
        matrix=evidence.read(args.matrix_report,report["bindings"][matrix_path])
        app_rows=matrix_application(matrix["records"])
        if args.application_costs:
            costs=evidence.read(args.application_costs)
            if costs["status"]!="completed" or costs["matrix_sha256"]!=report["bindings"][matrix_path]:
                raise ValueError("repeated application costs use a different or incomplete matrix")
            for path,sha in costs["bindings"].items():evidence.bind(path,sha)
            originals={(r["case"],r["profile"],r["variant"]):r for r in matrix["records"]}
            seen=set()
            for row in costs["records"]:
                key=(row["case"],row["profile"],row["variant"])
                if key in seen or originals[key]["binary_sha256"]!=row["binary_sha256"]:
                    raise ValueError("repeated cost binary mismatch or duplicate cell")
                seen.add(key);app_rows[key].update(application_timing(row["timing"]))
                app_rows[key]["cost_source"]=str(args.application_costs)
            observed={(r["case"],r["profile"],r["variant"]) for r in report["sessions"]}
            if not observed<=seen:raise ValueError("repeated costs omit observed session cells")
    else:
        application=evidence.read(args.application_summary)
        if application["source_bindings"][matrix_key] != report["bindings"][matrix_path]:
            raise ValueError("application costs are from a different matrix")
        app_rows = {(r["case"], r["profile"], r["variant"]): r for r in application["matrix"]["rows"]}
    sessions, batches, calibration = summarize_costs(payloads, [(g, final[(g["reference_sha256"], g["candidate_sha256"])]) for g in groups])
    cells = paired(sessions, app_rows)
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=False)
    evidence.bind(Path(__file__).resolve()); evidence.bind(ROOT/"tools/session_evidence.py")
    measured = Counter(); initial_measured = Counter(); all_requests = Counter()
    for group in groups:
        key = (group["reference_sha256"], group["candidate_sha256"])
        for member in group["members"]:
            all_requests[final[key]] += member["requests"]
            if member["phase"].startswith("batch-"):
                measured[final[key]] += member["requests"]; initial_measured[initial[key]] += member["requests"]
    for payload in payloads:
        for phase in payload["session"]["adapter"]["phases"]:
            count=sum(a.get("status")=="unsupported" for a in phase["result"]["answers"])
            if count:
                all_requests["unsupported"]+=count
                if phase["phase"].startswith("batch-"):
                    measured["unsupported"]+=count;initial_measured["unsupported"]+=count
    summary = {"status": "completed", "source_bindings": evidence.bindings, "protocol": report["protocol"],
               "scope": "development corpus; independent sessions/cell, correlated batches; no human or runtime-secrecy inference",
               "initial_distinct_grades": dict(Counter(initial.values())), "final_distinct_grades": dict(Counter(final.values())),
               "initial_measured_request_grades": dict(initial_measured), "measured_request_grades": dict(measured),
               "all_request_grades": dict(all_requests), "session_count": len(sessions), "batch_count_per_stage": len(batches),
               "cells": cells, "circuit_replay": replay,
               "calibration": {phase: {role: distribution([r[role+"_cpu_ns"] for r in calibration if r["phase"] == phase])
                                       for role in ("native", "jvm", "adapter")} for phase in ("first", "warmup", "empty")}}
    save(output/"session-medians.json", sessions)
    write_csv(output/"batches.csv", batches); write_csv(output/"calibration.csv", calibration)
    write_csv(output/"cells.csv", flat_cells(cells))
    save(output/"summary.json", summary)
    print(json.dumps({k: summary[k] for k in ("session_count", "batch_count_per_stage", "final_distinct_grades", "measured_request_grades")}))


if __name__ == "__main__": main()
