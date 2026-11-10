#!/usr/bin/env python3
"""Repeat the full frozen width study with only declared observer changes.

Run serially in the recorded Linux image after tests and grading investigations.
The frontend, binaries, input/order seeds, budgets and repetitions remain
unchanged. The declared exporter change adds named user ops and immutable bytes.
This is a new observer experiment, not a rerun of the
old observer; old resource samples are never relabeled.
"""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import file_hash
from effort_resources import save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-repeat", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("run in the recorded Linux image")
    prior, output = args.prior_repeat.resolve(), args.output_dir.resolve()
    complete = json.loads((prior / "completion.json").read_text())
    if complete["status"] != "completed":
        raise ValueError("completed prior repeat required")
    protocol = json.loads((prior / "protocol.json").read_text())
    previous_effort = json.loads((prior / "effort/effort.json").read_text())
    if previous_effort["status"] != "completed":
        raise ValueError("completed prior effort required")
    allowed = {str(ROOT / "tools" / f) for f in ("pcode_cfg.py", "pcode_values.py", "pcode_reconstruct.py", "audit_decompiler.py", "measure_effort.py", "ghidra/ExportCSRD.java")}
    bindings, changes = {}, []
    for path, expected in previous_effort["artifact_bindings"].items():
        actual = file_hash(path)
        if actual != expected:
            if path not in allowed:
                raise ValueError("undeclared experiment input changed: " + path)
            changes.append({"path": path, "before_sha256": expected, "after_sha256": actual})
        bindings[path] = actual
    for path in (Path(__file__).resolve(), ROOT / "tools/pcode_wide.py", ROOT / "tools/pcode_vector.py", prior / "protocol.json", prior / "completion.json", prior / "effort/effort.json"):
        bindings[str(path)] = file_hash(path)
    output.mkdir(parents=True, exist_ok=False)
    command = list(protocol["repeat_argv"])
    command[command.index("--output-dir")+1] = str(output / "effort")
    save(output / "protocol.json", {"status": "declared-before-results", "original_argv": protocol["repeat_argv"],
         "repeat_argv": command, "changes": changes, "bindings": bindings,
         "policy": "all 40 cells, one warmup and five measured repeats; frozen binaries, frontend and budgets; changed observer only"})
    with (output / "ghidra.log").open("w") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if any(file_hash(path) != expected for path, expected in bindings.items()):
        raise ValueError("experiment input changed during execution")
    save(output / "completion.json", {"status": "completed" if result.returncode == 0 else "failed", "returncode": result.returncode,
         "bindings": bindings, "historical_records_modified": False})
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
