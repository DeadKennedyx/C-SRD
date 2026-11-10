#!/usr/bin/env python3
"""Run the declared positional-width comparison, serially in the Linux image.

Run only after correctness tests. A new output directory and frozen frontend
prevent accidental mixing with historical measurements. Child tools retain raw
artifacts, hashes and all supported/unsupported outcomes. No selection is made.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import file_hash
from effort_resources import save


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--csrd", type=Path, default=Path("build-linux-release/csrd"))
    parser.add_argument("--headless", default=os.environ.get("CSRD_GHIDRA_HEADLESS"))
    args = parser.parse_args()
    if not sys.platform.startswith("linux") or not args.headless:
        parser.error("Linux and --headless / CSRD_GHIDRA_HEADLESS required")
    protocol_path = ROOT / "experiments/positional-widths-exploration.json"
    protocol = json.loads(protocol_path.read_text())
    corpus = ROOT / protocol["corpus"]
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    csrd = root / "csrd"
    shutil.copy2(args.csrd.resolve(strict=True), csrd)
    bindings = {str(p): file_hash(p) for p in (Path(__file__), protocol_path, corpus, csrd)}
    save(root / "frozen-protocol.json", {"protocol": protocol, "bindings": bindings})
    commands = {"commands": []}
    def run(name, argv):
        if any(file_hash(p) != digest for p, digest in bindings.items()):
            raise ValueError("frozen comparison input changed")
        command = [sys.executable, *map(str, argv)]
        record = {"name": name, "argv": command, "status": "running"}
        commands["commands"].append(record)
        save(root / "commands.json", commands)
        print(name, flush=True)
        with (root / (name + ".log")).open("w") as log:
            result = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
        record.update(status="completed" if result.returncode == 0 else "failed", returncode=result.returncode)
        save(root / "commands.json", commands)
        if result.returncode:
            raise RuntimeError(f"{name} failed; inspect retained raw data before any follow-up")
    matrix = protocol["matrix"]
    case_flags = [item for case in protocol["cases"] for item in ("--case", case)]
    run("matrix", [ROOT / "tools/run_matrix.py", "--csrd", csrd, "--matrix", corpus,
                   "--compiler", "clang=clang-18", "--compiler", "gcc=gcc", "--objdump", "llvm-objdump-18",
                   "--profdata", "llvm-profdata-18", "--tier", matrix["tier"], "--no-select", *case_flags,
                   "--strategies", *protocol["variants"][1:], "--inputs", matrix["inputs"],
                   "--iterations", matrix["iterations"], "--repetitions", matrix["repetitions"],
                   "--timeout-ms", matrix["timeout_ms"], "--output-dir", root / "matrix"])
    observers = protocol["observers"]
    profile_flags = [item for profile in observers["profiles"] for item in ("--profile", profile)]
    variant_flags = [item for variant in protocol["variants"] for item in ("--variant", variant)]
    common = [ROOT / "tools/measure_effort.py", "--csrd", csrd, "--matrix-report", root / "matrix/matrix.json",
              *case_flags, *profile_flags, *variant_flags, "--repetitions", observers["repetitions"],
              "--warmups", observers["warmups"], "--order-seed", observers["order_seed"],
              "--input-seed", observers["input_seed"], "--timeout-ms", observers["grading_timeout_ms"]]
    bitlinear = observers["bitlinear"]
    run("bitlinear", [*common, "--observer", "bitlinear", "--query-budgets", *bitlinear["query_budgets"],
                      "--wall-budgets", bitlinear["wall_seconds"], "--output-dir", root / "bitlinear"])
    ghidra = observers["ghidra"]
    run("ghidra", [*common, "--observer", "ghidra", "--headless", args.headless,
                   "--wall-budgets", ghidra["wall_seconds"], "--analysis-seconds", ghidra["analysis_seconds"],
                   "--decompile-seconds", ghidra["decompile_seconds"], "--output-dir", root / "ghidra"])
    save(root / "completion.json", {"status": "completed", "bindings": bindings})


if __name__ == "__main__":
    main()
