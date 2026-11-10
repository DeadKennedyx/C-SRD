#!/usr/bin/env python3
"""Reproduce the declared Linux effort pilot, sequentially on one host.

Run inside the documented Ghidra container with ptrace enabled. No conclusions
are inferred here. Each child command preserves its own protocol and raw data.
"""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import file_hash
from effort_resources import save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--csrd", default="build-linux-release/csrd")
    parser.add_argument("--headless", default=os.environ.get("CSRD_GHIDRA_HEADLESS"))
    args = parser.parse_args()
    if not sys.platform.startswith("linux") or not args.headless:
        parser.error("Linux and --headless / CSRD_GHIDRA_HEADLESS required")
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    commands = {"script_sha256": file_hash(__file__), "commands": []}
    def run(name, argv):
        command = [sys.executable, *map(str, argv)]
        commands["commands"].append({"name": name, "argv": command, "status": "running"})
        save(root / "commands.json", commands)
        print(name, flush=True)
        with (root / (name + ".log")).open("w") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        commands["commands"][-1].update(status="completed" if result.returncode == 0 else "failed", returncode=result.returncode)
        save(root / "commands.json", commands)
        if result.returncode:
            raise RuntimeError(f"{name} failed; retained {root / (name + '.log')}")
    run("matrix", [ROOT / "tools/run_matrix.py", "--csrd", args.csrd, "--compiler", "clang=clang-18",
                   "--compiler", "gcc=gcc", "--objdump", "llvm-objdump-18", "--case", "calculate", "--case", "xor",
                   "--case", "rotate_mix", "--profile", "clang-O2", "--profile", "gcc-O2", "--strategies", "identity", "affine",
                   "--control-flows", "none", "split-scale", "--inputs", "64", "--iterations", "100000",
                   "--repetitions", "5", "--output-dir", root / "matrix"])
    common = [ROOT / "tools/measure_effort.py", "--csrd", args.csrd, "--matrix-report", root / "matrix/matrix.json",
              "--repetitions", "5", "--warmups", "1", "--variant", "original", "--variant", "affine-42",
              "--variant", "affine-42-split-scale"]
    profiles = ["--profile", "clang-O2", "--profile", "gcc-O2"]
    run("blackbox", [*common, *profiles, "--observer", "blackbox", "--case", "calculate", "--case", "xor",
                     "--variant", "identity", "--query-budgets", "3", "12", "64", "--wall-budgets", "5",
                     "--output-dir", root / "blackbox"])
    run("ghidra", [*common, *profiles, "--observer", "ghidra", "--headless", args.headless, "--case", "calculate",
                   "--case", "rotate_mix", "--wall-budgets", "1", "30", "--output-dir", root / "ghidra"])
    run("runtime", [*common, "--profile", "clang-O2", "--observer", "runtime", "--case", "calculate",
                    "--query-budgets", "3", "4", "8", "--step-budgets", "1", "4", "16", "64",
                    "--wall-budgets", "60", "--output-dir", root / "runtime"])
    save(root / "completion.json", {"status": "completed", "script_sha256": file_hash(__file__)})
    return 0


if __name__ == "__main__":
    sys.exit(main())
