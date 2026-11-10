#!/usr/bin/env python3
"""Repeat every declared Ghidra trial after an interrupted host session.

Reuse the frozen matrix, frontend and observer arguments. Preserve the original
partial experiment. This script changes only the output directory, and requires
unchanged bound implementations. Run inside the Linux image; wrap Docker with
macOS caffeinate -i to prevent idle host sleep during measurements.
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
    parser.add_argument("--prior-run", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    prior, output = args.prior_run.resolve(), args.output_dir.resolve()
    if not sys.platform.startswith("linux"):
        parser.error("run in the recorded Linux image")
    interruption = prior / "interruption.json"
    if json.loads(interruption.read_text())["status"] != "interrupted":
        raise ValueError("documented interruption required")
    commands_path = prior / "commands.json"
    commands = json.loads(commands_path.read_text())["commands"]
    if any(next(c for c in commands if c["name"] == name)["status"] != "completed" for name in ("matrix", "bitlinear")):
        raise ValueError("reuse requires completed matrix and bitlinear stages")
    original = next(c["argv"] for c in commands if c["name"] == "ghidra")
    frozen_path = prior / "ghidra/protocol.json"
    frozen = json.loads(frozen_path.read_text())
    bindings = {**frozen["artifact_bindings"], str(commands_path): file_hash(commands_path),
                str(interruption): file_hash(interruption), str(frozen_path): file_hash(frozen_path),
                str(prior / "bitlinear/effort.json"): file_hash(prior / "bitlinear/effort.json"),
                str(Path(__file__).resolve()): file_hash(__file__)}
    if any(file_hash(path) != expected for path, expected in bindings.items()):
        raise ValueError("prior experiment binding changed")
    output.mkdir(parents=True, exist_ok=False)
    command = list(original)
    command[command.index("--output-dir") + 1] = str(output / "effort")
    save(output / "protocol.json", {"status": "declared-before-repeat", "reason": json.loads(interruption.read_text())["reason"],
        "original_argv": original, "repeat_argv": command, "bindings": bindings,
        "policy": "repeat all 240 Ghidra trials, including 40 excluded warmups; no outcome-based cell selection; original data retained"})
    with (output / "ghidra.log").open("w") as log:
        result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
    if any(file_hash(path) != expected for path, expected in bindings.items()):
        raise ValueError("bound input changed during repeat")
    save(output / "completion.json", {"status": "completed" if result.returncode == 0 else "failed",
        "returncode": result.returncode, "bindings": bindings, "historical_records_modified": False})
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
