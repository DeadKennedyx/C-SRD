#!/usr/bin/env python3
"""Read code-section and symbol sizes from frozen Linux matrix binaries.

This follow-up executes no benchmark. Whole-file alignment can conceal code
growth, so retain .text and named-function symbol sizes separately. A missing
symbol after LTO is unavailable, never interpreted as zero-size code.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import Runner, executable, file_hash, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-report", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--objdump", default="llvm-objdump-18")
    parser.add_argument("--nm", default="llvm-nm-18")
    args = parser.parse_args()
    matrix_path = args.matrix_report.resolve()
    matrix = json.loads(matrix_path.read_text())
    if matrix["status"] not in ("completed", "completed-with-gaps"):
        raise ValueError("completed matrix required")
    root = args.output_dir.resolve(); root.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "commands": [], "rows": [],
              "matrix": {"path": str(matrix_path), "sha256": file_hash(matrix_path)},
              "implementation_sha256": file_hash(__file__),
              "scope": "read-only post hoc ELF size inspection; .text includes harness/startup, symbol size may include padding; no timing, equivalence or protection conclusion"}
    command = Runner(report)
    try:
        objdump, nm = executable(args.objdump), executable(args.nm)
        report["tools"] = {name: {"path": path, "sha256": file_hash(path), "version": command([path, "--version"]).splitlines()[0]}
                           for name, path in (("objdump", objdump), ("nm", nm))}
        names = {c["id"]: c["function"] for c in matrix["cases"]}
        baselines = {}
        for cell in matrix["records"]:
            if cell["status"] != "completed":
                continue
            binary = cell["binary"]
            if file_hash(binary) != cell["binary_sha256"]:
                raise ValueError("frozen binary changed")
            sections = command([objdump, "--section-headers", binary])
            symbols = command([nm, "--print-size", "--defined-only", "--format=posix", binary])
            text = [int(f[2], 16) for line in sections.splitlines() if len(f := line.split()) >= 3 and f[1] == ".text"]
            if len(text) != 1:
                raise ValueError("expected exactly one linked .text section")
            sizes = [int(f[3], 16) for line in symbols.splitlines()
                     if len(f := line.split()) == 4 and f[0] == names[cell["case"]] and f[1] in ("T", "t")]
            if len(sizes) > 1:
                raise ValueError("ambiguous target function symbol")
            row = {k: cell[k] for k in ("case", "profile", "variant", "binary_sha256", "binary_bytes")}
            row.update(text_section_bytes=text[0], function_symbol=names[cell["case"]],
                       function_symbol_bytes=sizes[0] if sizes else None,
                       symbol_status="measured" if sizes else "not-present")
            if file_hash(binary) != cell["binary_sha256"]:
                raise ValueError("binary changed during inspection")
            if cell["variant"] == "original":
                baselines[(cell["case"], cell["profile"])] = row
            report["rows"].append(row)
        for row in report["rows"]:
            base = baselines[(row["case"], row["profile"])]
            row["text_section_ratio"] = row["text_section_bytes"] / base["text_section_bytes"]
            row["function_symbol_ratio"] = (row["function_symbol_bytes"] / base["function_symbol_bytes"]
                                             if row["function_symbol_bytes"] is not None and base["function_symbol_bytes"] else None)
        if file_hash(matrix_path) != report["matrix"]["sha256"]:
            raise ValueError("matrix changed during inspection")
        report["status"] = "completed"
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally:
        write_json(root / "sizes.json", report)
    print("PASS", len(report["rows"]), "frozen binary size inspections")


if __name__ == "__main__":
    main()
