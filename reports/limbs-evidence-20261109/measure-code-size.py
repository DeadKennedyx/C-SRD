#!/usr/bin/env python3
"""Read linked section sizes from existing hash-bound validated matrix binaries.

Executable file size can hide code growth through alignment/padding. This audit
records .text/__text separately. It does not execute or recompile the binaries.
"""
import argparse
import json
from pathlib import Path
import re
import sys

from audit_protection import Runner, AuditError, file_hash, write_json


def run(matrix_path, output):
    matrix = json.loads(matrix_path.read_text())
    if matrix.get("status") not in ("completed", "completed-with-gaps", "failed") or "summary" not in matrix or "error" in matrix:
        raise ValueError("finished matrix required; failed cells will be retained as omissions")
    report = {"status": "running", "schema_version": 1, "matrix_status": matrix["status"],
              "matrix_summary": matrix["summary"], "records": [], "commands": [],
              "scope": "linked code section including harness, runtime support and padding; not isolated function size or runtime RSS",
              "bindings": {str(matrix_path): file_hash(matrix_path), __file__: file_hash(__file__)}}
    command = Runner(report)
    objdump = matrix["tools"]["objdump"]
    if file_hash(objdump["path"]) != objdump["sha256"]:
        raise ValueError("objdump differs from bound matrix tool")
    report["bindings"][objdump["path"]] = objdump["sha256"]
    for cell in matrix["records"]:
        record = {k: cell[k] for k in ("case", "variant", "profile", "status")}
        report["records"].append(record)
        if cell["status"] != "completed":
            record.update(status="omitted-unvalidated", reason=cell.get("error", "incomplete cell"))
            continue
        path = cell["binary"]
        if file_hash(path) != cell["binary_sha256"]:
            raise ValueError("changed binary: " + path)
        report["bindings"][path] = cell["binary_sha256"]
        headers = command([objdump["path"], "--section-headers", path])
        sections = {}
        for line in headers.splitlines():
            match = re.match(r"^\s*\d+\s+(\S+)\s+([0-9a-fA-F]+)\s+[0-9a-fA-F]+\s+", line)
            if match:
                name, count = match.groups()
                if name in sections:
                    raise ValueError("ambiguous duplicate section name")
                sections[name] = int(count, 16)
        text = [(k, v) for k, v in sections.items() if k in (".text", "__text")]
        if len(text) != 1 or text[0][1] <= 0:
            raise ValueError("one nonempty linked text section required")
        record.update(status="measured", binary_sha256=cell["binary_sha256"], binary_bytes=Path(path).stat().st_size,
                      text_section=text[0][0], text_bytes=text[0][1], section_bytes=sections)
    baselines = {(r["case"], r["profile"]): r for r in report["records"] if r["variant"] == "original" and r["status"] == "measured"}
    for r in report["records"]:
        if r["status"] == "measured":
            baseline = baselines[(r["case"], r["profile"])]
            r["text_ratio_to_original"] = r["text_bytes"] / baseline["text_bytes"]
            r["text_delta_bytes"] = r["text_bytes"] - baseline["text_bytes"]
    if any(file_hash(p) != h for p, h in report["bindings"].items()):
        raise ValueError("bound artifact changed during size measurement")
    report["status"] = "completed"
    write_json(output / "sizes.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-report", required=True)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    output = Path(args.output_dir).resolve()
    try:
        output.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"new output directory required: {error}")
    try:
        report = run(Path(args.matrix_report).resolve(strict=True), output)
        print(report["status"] + ": " + str(output / "sizes.json"))
        return 0
    except (OSError, ValueError, KeyError, AuditError) as error:
        write_json(output / "failure.json", {"status": "failed", "error": str(error)})
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
