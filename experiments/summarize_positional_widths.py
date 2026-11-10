#!/usr/bin/env python3
"""Summarize the frozen width comparison without selecting a protection winner."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import statistics
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from effort_statistics import summarize
from grade_saved_answers import bound_query


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def local(value):
    path = Path(value)
    if path.is_relative_to("/work"):
        return ROOT / path.relative_to("/work")
    return path if path.is_absolute() else ROOT / path


def distribution(values):
    return {"n": len(values), "median": statistics.median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def circuit_followup(circuit, effort, matrix, bindings):
    """Recheck the saved-answer chain; derive new grades without changing trials."""
    def bind(path, expected=None):
        path = local(path).resolve()
        actual = digest(path)
        if expected is not None and actual != expected:
            raise ValueError("circuit follow-up binding changed: " + str(path))
        bindings[str(path.relative_to(ROOT))] = actual
        return path

    protocol = json.loads(bind(circuit / "protocol.json").read_text())
    rows = json.loads(bind(circuit / "summary.json").read_text())
    completion = json.loads(bind(circuit / "completion.json").read_text())
    if (completion["status"] != "completed" or completion["controls_passed"] is not True or
            completion["historical_records_modified"] is not False or completion["results"] != len(rows)):
        raise ValueError("completed controlled circuit follow-up required")
    for name, expected in protocol["sources"].items():
        bind(ROOT / name, expected)
    selected = {t["id"]: t for t in effort["trials"] if not t["warmup"] and t["status"] == "inconclusive"}
    cases = {c["name"]: c for c in protocol["cases"]}
    if len(cases) != len(protocol["cases"]) or len({r["name"] for r in rows}) != len(rows) or set(cases) != {r["name"] for r in rows}:
        raise ValueError("missing or duplicate circuit result")
    matrix_rows = {(r["case"], r["profile"], r["variant"]): r for r in matrix["records"]}
    seen = {"saved-answer": set(), "negative-control": set()}
    changes, controls = [], []
    for row in rows:
        case = cases[row["name"]]
        report_path = bind(ROOT / row["report"])
        report = json.loads(report_path.read_text())
        query = bind(case["query"], row["query_sha256"])
        for field in ("status", "query_sha256", "circuit_validation", "total_wall_seconds", "child_cpu_seconds"):
            if report.get(field) != row.get(field):
                raise ValueError("circuit summary differs from report: " + field)
        if row["kind"] != case["kind"] or row["expected"] != case["expected"] or row["profile"] != case.get("profile"):
            raise ValueError("circuit case/result mismatch")
        if (report.get("circuit_validation", {}).get("status") != "circuit-validated" or
                report["solver_seconds"] != protocol["solver_seconds"] or report["stage_wall_seconds"] != protocol["stage_seconds"]):
            raise ValueError("unvalidated circuit or changed grading budget")
        for key, tool in report["tools"].items():
            if tool["sha256"] != protocol["tools"][key + "_sha256"]:
                raise ValueError("circuit tool identity mismatch")
        for name, expected in report["artifacts"].items():
            bind(report_path.parent / name, expected)
        if case["kind"] == "rule-control":
            if digest(query) != case["query_sha256"]:
                raise ValueError("rule query differs from protocol")
        else:
            trial_id = int(case["name"].split("-")[1])
            trial = selected[trial_id]
            directory = local(trial["directory"])
            trial_path = bind(directory / "trial.json", case["trial_sha256"])
            if json.loads(trial_path.read_text()) != trial:
                raise ValueError("individual trial differs from completed effort report")
            section = "grade" if case["kind"] == "saved-answer" else "negative-control"
            binding, text = bound_query(directory, section)
            if binding != case["binding"] or query.read_text() != text:
                raise ValueError("circuit query is not the bound saved assertion")
            bind(ROOT / binding["grade_report"], binding["grade_report_sha256"])
            bind(directory / section / "measurement/command.json", binding["command_sha256"])
            for item in binding["files"]:
                bind(ROOT / item["path"], item["sha256"])
            binary = matrix_rows[(trial["case"], trial["profile"], trial["variant"])]
            if case["binary_sha256"] != trial["binary_sha256"] or trial["binary_sha256"] != binary["binary_sha256"]:
                raise ValueError("trial and compiled-artifact binding disagree")
            bind(binary["binary"], trial["binary_sha256"])
            if (case["profile"], case["variant"]) != (trial["profile"], trial["variant"]):
                raise ValueError("circuit case identifies a different trial")
            if trial_id in seen[case["kind"]]:
                raise ValueError("duplicate trial grade")
            seen[case["kind"]].add(trial_id)
            if case["kind"] == "saved-answer":
                candidate = directory / "observer/candidate.c"
                bind(candidate, trial["candidate_sha256"])
                reference = matrix_rows[(trial["case"], trial["profile"], "original")]
                reference_path = local(reference["binary"]).parent / "function.i"
                if [local(f["path"]).resolve() for f in binding["files"]] != [reference_path.resolve(), candidate.resolve()]:
                    raise ValueError("saved grade compares different C artifacts")
                if row["status"] not in ("unsat", "inconclusive"):
                    raise ValueError("unexpected follow-up outcome; investigate before summarizing")
                changes.append({"trial": trial_id, "case": trial["case"], "profile": trial["profile"],
                                "variant": trial["variant"], "candidate_sha256": trial["candidate_sha256"],
                                "query_sha256": row["query_sha256"], "original_status": trial["status"],
                                "circuit_status": row["status"], "report": row["report"],
                                "derived_status": "recovered-under-source-model" if row["status"] == "unsat" else "inconclusive",
                                "separate_grader_wall_seconds": row["total_wall_seconds"],
                                "separate_grader_child_cpu_seconds": row["child_cpu_seconds"]})
        if case["expected"] is not None:
            if row["status"] != case["expected"] or row["control_passed"] is not True:
                raise ValueError("circuit control failed")
            controls.append({"name": row["name"], "kind": case["kind"], "status": row["status"]})
    if any(ids != set(selected) for ids in seen.values()) or len([c for c in controls if c["kind"] == "rule-control"]) != 3:
        raise ValueError("all selected grades and controls must be accounted for")
    statuses = {c["trial"]: c["derived_status"] for c in changes}
    derived = [{**t, "status": statuses.get(t["id"], t["status"])} for t in effort["trials"]]
    unresolved = [c for c in changes if c["derived_status"] == "inconclusive"]
    return {"selection": "all measured inconclusive grades; original files unchanged",
            "selected_trials": len(selected), "changes": changes, "controls": controls,
            "outcomes": dict(Counter(t["status"] for t in derived if not t["warmup"])),
            "distinct_selected_answers": len({c["candidate_sha256"] for c in changes}),
            "distinct_selected_queries": len({c["query_sha256"] for c in changes}),
            "unresolved_trials": [c["trial"] for c in unresolved],
            "distinct_unresolved_answers": len({c["candidate_sha256"] for c in unresolved}),
            "distinct_unresolved_queries": len({c["query_sha256"] for c in unresolved}),
            "summary": summarize(derived),
            "scope": "derived source-model grades only; observer resources unchanged, later grader costs separate; lifting remains trusted"}


def completion_timeline(directory):
    files = sorted(directory.glob("trial-*/trial.json"))
    entries = [{"path": str(p.relative_to(ROOT)), "sha256": digest(p), "host_mtime_ns": p.stat().st_mtime_ns} for p in files]
    gaps = [(b["host_mtime_ns"] - a["host_mtime_ns"]) / 1e9 for a, b in zip(entries, entries[1:])]
    return {"entries": entries, "adjacent_completion_seconds": distribution(gaps),
            "gaps_over_90_seconds": sum(g > 90 for g in gaps),
            "scope": "post hoc host filesystem timestamps; diagnostic only, not an observer duration or OS-sleep diagnosis"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--sizes", type=Path, required=True)
    parser.add_argument("--ghidra-repeat-dir", type=Path, required=True)
    parser.add_argument("--circuit-dir", type=Path, required=True)
    parser.add_argument("--finite-checks", type=Path, required=True)
    args = parser.parse_args()
    root = args.run_dir.resolve()
    repeat = args.ghidra_repeat_dir.resolve()
    paths = [repeat / "completion.json", root / "matrix/matrix.json", root / "frozen-protocol.json",
             root / "bitlinear/effort.json", repeat / "effort/effort.json", Path(__file__).resolve(),
             root / "interruption.json", root / "interruption-final.json", repeat / "protocol.json",
             ROOT / "tools/effort_statistics.py", args.finite_checks.resolve()]
    completion = json.loads(paths[0].read_text())
    if completion["status"] != "completed":
        raise ValueError("completed Ghidra repeat required")
    matrix = json.loads(paths[1].read_text())
    if matrix["status"] not in ("completed", "completed-with-gaps"):
        raise ValueError("successful matrix required; retain any failed run separately")
    if digest(root / "csrd") != matrix["tools"]["csrd"]["sha256"]:
        raise ValueError("frozen frontend hash differs from matrix")
    for filename, expected in completion["bindings"].items():
        if digest(local(filename)) != expected:
            raise ValueError("bound comparison input changed: " + filename)
    frozen = json.loads((root / "frozen-protocol.json").read_text())
    for filename, expected in frozen["bindings"].items():
        if digest(local(filename)) != expected:
            raise ValueError("frozen compiler-study input changed: " + filename)
    cases = {c["id"]: c for c in matrix["cases"]}
    paths.append(args.sizes.resolve())
    sizes = json.loads(args.sizes.read_text())
    if sizes["status"] != "completed" or sizes["matrix"]["sha256"] != digest(paths[1]):
        raise ValueError("completed size follow-up bound to this matrix required")
    size_rows = {(r["case"], r["profile"], r["variant"]): r for r in sizes["rows"]}
    baselines = {(r["case"], r["profile"]): r for r in matrix["records"] if r["variant"] == "original"}
    rows, auxiliary_bindings = [], {}
    for r in matrix["records"]:
        row = {k: r[k] for k in ("case", "profile", "variant", "status")}
        if r["status"] != "completed":
            row["error"] = r.get("error"); rows.append(row); continue
        base = baselines[(r["case"], r["profile"])]
        function = cases[r["case"]]["function"]
        instructions = r["linked"]["opcode_sequences"].get(function)
        base_instructions = base["linked"]["opcode_sequences"].get(function)
        count = len(instructions) if instructions is not None else None
        base_count = len(base_instructions) if base_instructions is not None else None
        build_dir = str(Path(r["binary"]).parent)
        compile_commands = [c for c in matrix["commands"] if "-o" in c["argv"] and
                            c["argv"][c["argv"].index("-o") + 1] in
                            [build_dir + "/" + name for name in ("function.o", "driver.o", "program")]]
        validation_path = local(r["validation"])
        auxiliary_bindings[str(validation_path.relative_to(ROOT))] = digest(validation_path)
        validation = json.loads(validation_path.read_text())
        row.update(runtime_ratio=r["timing"]["median_paired_ratio"], runtime_samples=r["timing"]["paired_ratios"],
                   binary_bytes=r["binary_bytes"], binary_size_ratio=r["binary_size_ratio"],
                   named_function_instructions=count,
                   named_function_instruction_ratio=count / base_count if count is not None and base_count else None,
                   main_and_named_function_instructions=r["linked"]["instruction_count"],
                   mnemonic_sequence_differs=r["comparison"]["instruction_sequences_differ_from_original"],
                   binary_bytes_identical_to_original=r["binary_sha256"] == base["binary_sha256"],
                   compile_link_command_seconds=sum(c["elapsed_seconds"] for c in compile_commands),
                   final_source_validation_command_seconds=sum(c["elapsed_seconds"] for c in validation["commands"]
                                                              if len(c["argv"]) > 1 and c["argv"][1] == "verify"),
                   source_verification=r["source_verification"], execution_comparisons=r["execution"]["comparisons"])
        size = size_rows[(r["case"], r["profile"], r["variant"])]
        if size["binary_sha256"] != r["binary_sha256"]:
            raise ValueError("size follow-up inspected different binary bytes")
        row.update({k: size[k] for k in ("text_section_bytes", "text_section_ratio", "function_symbol_bytes", "function_symbol_ratio", "symbol_status")})
        rows.append(row)
    transforms = []
    for case in matrix["cases"]:
        for variant in case["variants"]:
            if "manifest" not in variant:
                continue
            path = local(variant["manifest"])
            if digest(path) != variant["manifest_sha256"]:
                raise ValueError("transformation report changed")
            f = json.loads(path.read_text())["functions"][0]
            commands = [c for c in matrix["commands"] if len(c["argv"]) > 1 and c["argv"][1] == "transform" and
                        "--report" in c["argv"] and c["argv"][c["argv"].index("--report") + 1] == variant["manifest"]]
            transforms.append({"case": case["id"], "variant": variant["id"],
                "command_seconds": sum(c["elapsed_seconds"] for c in commands),
                **{k: f.get(k) for k in ("verification", "operations_transformed", "operations_without_decoding",
                                        "boundary_conversions", "internal_conversions", "ordinary_value_nodes")}})
    observers = {}
    for name in ("bitlinear", "ghidra"):
        path = repeat / "effort/effort.json" if name == "ghidra" else root / name / "effort.json"
        effort = json.loads(path.read_text())
        if effort["status"] != "completed":
            raise ValueError("completed observer run required")
        if effort["artifact_bindings"][str(local(paths[1])).replace(str(ROOT), "/work", 1)] != digest(paths[1]):
            raise ValueError("observer does not bind this matrix")
        measured = [t for t in effort["trials"] if not t["warmup"]]
        observers[name] = {
            "measured_trials": len(measured), "warmups": sum(t["warmup"] for t in effort["trials"]),
            "outcomes": dict(Counter(t["status"] for t in measured)),
            "negative_controls": dict(Counter(t["negative_control"]["status"] for t in measured if "negative_control" in t)),
            "unsupported_reasons": dict(Counter((t.get("answer") or {}).get("error", (t.get("answer") or {}).get("reason", "unspecified"))
                                                for t in measured if t["status"] == "unsupported-reconstruction")),
            "distinct_answer_artifacts": len({t["candidate_sha256"] for t in measured if "candidate_sha256" in t}),
            "groups": effort["summary"]["groups"],
            "budget_points": effort["summary"]["budget_points_succeeding_in_every_measured_repeat"],
            "stages_by_cell": []}
        for key in sorted({(t["case"], t["profile"], t["variant"], t["budget_id"]) for t in measured}):
            group = [t for t in measured if (t["case"], t["profile"], t["variant"], t["budget_id"]) == key]
            row = dict(zip(("case", "profile", "variant", "budget_id"), key))
            for field in ("headless_seconds", "reconstruction_seconds", "training_queries"):
                row[field] = distribution([t["answer"][field] for t in group if (t.get("answer") or {}).get(field) is not None])
            row["separate_grading_wall_seconds"] = distribution([
                t["verification"]["resources"]["wall_seconds"] for t in group if "verification" in t])
            observers[name]["stages_by_cell"].append(row)
        if name == "ghidra":
            observers[name]["circuit_followup"] = circuit_followup(args.circuit_dir.resolve(), effort, matrix, auxiliary_bindings)
    finite = json.loads(args.finite_checks.read_text())
    followup = observers["ghidra"]["circuit_followup"]
    finite_ids = [i for group in finite["groups"] for i in group["trials"]]
    if (finite["status"] != "completed" or len(finite_ids) != len(set(finite_ids)) or
            set(finite_ids) != set(followup["unresolved_trials"]) or
            len(finite["records"]) != 10 * len(finite["groups"]) or not all(r["passed"] for r in finite["records"])):
        raise ValueError("finite follow-up must cover every remaining unknown without changing grades")
    for name, expected in finite["bindings"].items():
        path = local(name)
        if path.is_relative_to(ROOT):
            if digest(path) != expected:
                raise ValueError("finite-check repository input changed: " + name)
            auxiliary_bindings[str(path.relative_to(ROOT))] = expected
    followup["finite_checks"] = {"scope": finite["scope"], "groups": finite["groups"], "records": finite["records"],
                                 "seed": finite["seed"], "random_inputs": finite["random_inputs"],
                                 "effect_on_grades": "none; ten trials remain inconclusive"}
    report = {"schema_version": 1, "status": "completed", "selection": "not-performed",
              "source_bindings": {str(p.relative_to(ROOT)): digest(p) for p in paths},
              "auxiliary_input_bindings": auxiliary_bindings,
              "frontend_sha256": matrix["tools"]["csrd"]["sha256"],
              "matrix": {"summary": matrix["summary"], "profiles": [
                  {k: p.get(k) for k in ("id", "status", "reason")} for p in matrix["profiles"]],
                  "rows": rows, "transformations": transforms, "recognition_scores": matrix["recognition_scores"]},
              "observers": observers,
              "interruption": {"retained": str((root / "ghidra").relative_to(ROOT)),
                               "primary_ghidra_run": str((repeat / "effort").relative_to(ROOT)),
                               "policy": "all Ghidra cells repeated; original partial run excluded from resource comparisons",
                               "repeat_host_timeline": completion_timeline(repeat / "effort")},
              "scope": {"runtime": "paired linked harness including input generation; seven repeats",
                        "size": "whole executable bytes, post hoc .text/symbol size, and named-function mnemonic count excluding NOPs; missing symbol is not zero cost",
                        "build": "compile/link command wall time includes PGO passes where used; final validation command time excludes PGO training validation",
                        "observer": "fixed observer process-tree resources; grading separate; successful ratios require matched baseline success",
                        "inference": "descriptive development exploration; neither unsupported nor grading-inconclusive is a protection success",
                        "unassessed": ["human effort", "multi-location memory inference", "reserved algorithm reconstruction", "broad C support"]}}
    with args.output.open("x") as stream:
        json.dump(report, stream, indent=2); stream.write("\n")
    print(args.output)


if __name__ == "__main__":
    main()
