#!/usr/bin/env python3
"""Prepare blinded task copies and record human effort; never invent participant data.

Keep private-key.json with the coordinator, away from participant packets. This
records local events, not tamper-proof telemetry or proof of human attention.
"""
import argparse
import json
from pathlib import Path
import random
import shutil
import sys
import time
from datetime import datetime, timezone

from audit_decompiler import scoring_reference
from audit_protection import file_hash
from effort_resources import save
from measure_effort import proof


def timestamp():
    return {"utc": datetime.now(timezone.utc).isoformat(), "unix_seconds": time.time(),
            "monotonic_seconds": time.monotonic()}


def elapsed(previous, now):
    monotonic = now["monotonic_seconds"] - previous["monotonic_seconds"]
    wall = now["unix_seconds"] - previous["unix_seconds"]
    if monotonic < 0 or abs(monotonic - wall) > 5:
        raise ValueError("clock discontinuity/reboot; session requires coordinator review")
    return monotonic


def prepare(args):
    matrix = json.loads(Path(args.matrix_report).read_text())
    if matrix["status"] not in ("completed", "completed-with-gaps"):
        raise ValueError("completed matrix required")
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    variants = ["original", args.variant]
    if args.variant == "original" or args.participants < 2 or args.budget_seconds <= 0:
        raise ValueError("one non-original candidate, >=2 participant slots and positive time budget required")
    cases = [c for c in matrix["cases"] if c["id"] in args.case]
    if {c["id"] for c in cases} != set(args.case):
        raise ValueError("unknown case")
    # One case per family: no participant sees multiple versions of a family.
    if len({c["family"] for c in cases}) != len(cases):
        raise ValueError("select at most one case per functional family to limit learning carryover")
    key = {"status": "awaiting-participants", "csrd_sha256": matrix["tools"]["csrd"]["sha256"],
           "matrix_sha256": file_hash(args.matrix_report), "tasks": {}, "assignment_seed": args.seed}
    rng = random.Random(args.seed)
    for participant in range(args.participants):
        participant_id = f"p{participant + 1:03d}"
        packet = root / "packets" / participant_id
        packet.mkdir(parents=True)
        order = list(enumerate(cases)); rng.shuffle(order)
        for ordinal, (family_index, case) in enumerate(order):
            variant = variants[(participant + family_index) % 2]
            record = next(r for r in matrix["records"] if r["case"] == case["id"] and
                          r["profile"] == args.profile and r["variant"] == variant)
            if record["status"] != "completed" or file_hash(record["binary"]) != record["binary_sha256"]:
                raise ValueError("changed or unvalidated binary")
            frozen, sha = scoring_reference(matrix, record)
            task_id = f"{participant_id}-t{ordinal + 1:02d}"
            task_dir = packet / task_id; task_dir.mkdir()
            shutil.copy2(record["binary"], task_dir / "program")
            public = {"task_id": task_id, "participant": participant_id, "function": case["function"],
                      "arity": case["arity"], "binary": "program", "binary_sha256": record["binary_sha256"],
                      "budget_seconds": args.budget_seconds,
                      "task": "Reconstruct the named pure u32 function in C. Submit initialized-u32 expressions admitted by the provided C-SRD contract. The binary reads space-separated decimal inputs and emits decimal returns.",
                      "pause_policy": "Pause only for interruptions; analysis and scripting time remain active.",
                      "feedback": "No correctness feedback until the session finishes."}
            save(task_dir / "task.json", public)
            key["tasks"][task_id] = {**public, "case": case["id"], "family": case["family"],
                                     "profile": args.profile, "variant": variant,
                                     "reference": str(frozen), "reference_sha256": sha}
    save(root / "private-key.json", key)
    return {"status": "awaiting-participants", "tasks": len(key["tasks"]), "directory": str(root)}


def start(task_path, session_path, experience, prior_exposure):
    task_path, session_path = Path(task_path).resolve(), Path(session_path).resolve()
    task = json.loads(task_path.read_text())
    if file_hash(task_path.parent / task["binary"]) != task["binary_sha256"]:
        raise ValueError("task binary changed")
    session_path.mkdir(parents=True, exist_ok=False)
    now = timestamp()
    state = {"schema_version": 1, "status": "active", "task": task, "task_sha256": file_hash(task_path),
             "experience": experience, "prior_exposure": prior_exposure, "started": now, "last_event": now,
             "active_seconds": 0.0, "submissions": [], "events": [{"action": "start", **now}]}
    save(session_path / "session.json", state)
    return state


def event(session_path, action, candidate=None, note=""):
    session_path = Path(session_path).resolve()
    path = session_path / "session.json"
    state = json.loads(path.read_text())
    if state["status"] == "finished":
        raise ValueError("session is finished")
    if action == "pause" and state["status"] != "active" or action == "resume" and state["status"] != "paused":
        raise ValueError("invalid session transition")
    if action == "submit" and state["status"] != "active":
        raise ValueError("resume before submitting")
    now = timestamp()
    delta = elapsed(state["last_event"], now)
    if state["status"] == "active":
        state["active_seconds"] += delta
    state["elapsed_wall_seconds"] = elapsed(state["started"], now)
    entry = {"action": action, **now, "active_seconds": state["active_seconds"], "note": note}
    if action == "submit":
        destination = session_path / f"submission-{len(state['submissions']) + 1:03d}.c"
        shutil.copyfile(candidate, destination)
        submission = {"path": str(destination), "sha256": file_hash(destination),
                      "active_seconds": state["active_seconds"], "elapsed_wall_seconds": state["elapsed_wall_seconds"],
                      "within_budget": state["active_seconds"] <= state["task"]["budget_seconds"]}
        state["submissions"].append(submission)
        entry["sha256"] = submission["sha256"]
    if action in ("pause", "resume", "finish"):
        state["status"] = {"pause": "paused", "resume": "active", "finish": "finished"}[action]
    state["last_event"] = now
    state["events"].append(entry)
    save(path, state)
    return state


def score(args):
    directory = Path(args.session_dir).resolve()
    state = json.loads((directory / "session.json").read_text())
    if state["status"] != "finished":
        raise ValueError("finish the session before receiving grading feedback")
    key = json.loads(Path(args.private_key).read_text())
    task = key["tasks"][state["task"]["task_id"]]
    if any(task.get(k) != v for k, v in state["task"].items()):
        raise ValueError("public task differs from coordinator key")
    if file_hash(args.csrd) != key["csrd_sha256"] or file_hash(task["reference"]) != task["reference_sha256"]:
        raise ValueError("grading model or frozen reference changed")
    destination = directory / "grading"
    destination.mkdir(exist_ok=False)
    scores = []
    for index, submission in enumerate(state["submissions"]):
        if file_hash(submission["path"]) != submission["sha256"]:
            raise ValueError("frozen submission changed")
        result = proof(str(Path(args.csrd).resolve()), task["reference"], submission["path"],
                       destination / str(index), args.timeout_ms)
        scores.append({**submission, **result})
    successes = [s for s in scores if s["status"] == "proved-under-model" and s["within_budget"]]
    report = {"task": task, "session_sha256": file_hash(directory / "session.json"), "submissions": scores,
              "submission_count": len(scores), "success_within_budget": bool(successes),
              "active_seconds_to_first_correct": successes[0]["active_seconds"] if successes else None,
              "wall_seconds_to_first_correct": successes[0]["elapsed_wall_seconds"] if successes else None,
              "observed_active_seconds": state["active_seconds"],
              "budget_exhausted": state["active_seconds"] >= task["budget_seconds"],
              "withdrawn_early_without_success": not successes and state["active_seconds"] < task["budget_seconds"],
              "correctness_scope": "source model; unsupported submissions remain grading gaps"}
    save(destination / "score.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("--matrix-report", required=True)
    prepare_parser.add_argument("--case", action="append", required=True)
    prepare_parser.add_argument("--profile", required=True)
    prepare_parser.add_argument("--variant", required=True)
    prepare_parser.add_argument("--participants", type=int, default=4)
    prepare_parser.add_argument("--budget-seconds", type=float, default=1800)
    prepare_parser.add_argument("--seed", type=int, default=42)
    prepare_parser.add_argument("--output-dir", required=True)
    start_parser = sub.add_parser("start")
    start_parser.add_argument("--task", required=True)
    start_parser.add_argument("--session-dir", required=True)
    start_parser.add_argument("--experience", required=True, help="Self-reported experience with the permitted tools")
    start_parser.add_argument("--prior-exposure", choices=["yes", "no", "unknown"], required=True)
    for action in ("pause", "resume", "submit", "finish"):
        p = sub.add_parser(action)
        p.add_argument("--session-dir", required=True)
        p.add_argument("--note", default="")
        if action == "submit":
            p.add_argument("--candidate", required=True)
    score_parser = sub.add_parser("score")
    score_parser.add_argument("--session-dir", required=True)
    score_parser.add_argument("--private-key", required=True)
    score_parser.add_argument("--csrd", required=True)
    score_parser.add_argument("--timeout-ms", type=int, default=10000)
    args = parser.parse_args()
    try:
        if args.command == "prepare":
            result = prepare(args)
        elif args.command == "start":
            result = start(args.task, args.session_dir, args.experience, args.prior_exposure)
        elif args.command == "score":
            result = score(args)
        else:
            result = event(args.session_dir, args.command, getattr(args, "candidate", None), args.note)
        print(json.dumps({k: result.get(k) for k in ("status", "active_seconds", "success_within_budget", "tasks")}, indent=2))
        return 0
    except (OSError, ValueError, KeyError, StopIteration) as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
