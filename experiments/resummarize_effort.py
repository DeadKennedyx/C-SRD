#!/usr/bin/env python3
"""Recompute statistics from complete saved trials without changing observations.

Recovery for a failed summary step; preserve the original report and explicitly
record the postprocessing implementation. This does not rerun an observer.
"""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import file_hash
from effort_resources import environment, save
from effort_statistics import summarize
from measure_effort import export_csv


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    args = parser.parse_args()
    root = Path(args.run_dir).resolve()
    path = root / "effort.json"
    report = json.loads(path.read_text())
    if any(t["status"] == "running" for t in report["trials"]):
        raise ValueError("incomplete observations cannot be resummarized as a completed experiment")
    protocol = report["protocol"]
    expected = ((protocol["repetitions"] + protocol["warmups"]) * len(protocol["budgets"]) *
                len(protocol["case"]) * len(protocol["profile"]) * len(protocol["variant"]))
    if len(report["trials"]) != expected:
        raise ValueError("not all declared trials were collected")
    allowed = {str(ROOT / "tools/effort_statistics.py"), str(ROOT / "tools/measure_effort.py")}
    for file, sha in report["artifact_bindings"].items():
        if file not in allowed and file_hash(file) != sha:
            raise ValueError("observer or input artifact changed: " + file)
    original = root / "effort.before-resummary.json"
    if original.exists():
        raise ValueError("original report already saved; refuse to overwrite recovery provenance")
    shutil.copy2(path, original)
    provenance = {"original_report_sha256": file_hash(original), "reason": "summary failed on null answers in timed-out trials",
                  "resummary_script_sha256": file_hash(__file__), "changed_postprocessing": {
                      file: {"collection_sha256": report["artifact_bindings"][file], "current_sha256": file_hash(file)}
                      for file in sorted(allowed)}, "new_observations": False,
                  "environment_when_resummarized": environment()}
    report.update(status="failed" if any(t["status"] == "error" for t in report["trials"]) else "completed",
                  summary=summarize(report["trials"]), postprocessing_recovery=provenance)
    save(path, report)
    save(root / "summary.json", report["summary"])
    save(root / "resummary.json", provenance)
    export_csv(report, root / "trials.csv")
    print(report["status"])


if __name__ == "__main__":
    main()
