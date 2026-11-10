#!/usr/bin/env python3
"""Archive a completed pilot's evidence without transient Ghidra project databases."""
import argparse
import gzip
import json
from pathlib import Path
import shutil
import sys
import tarfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import file_hash
from effort_resources import save


def archive(source, destination):
    excluded, included = [], []
    with destination.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w|") as tar:
            for path in sorted(source.rglob("*")):
                if path.is_symlink():
                    raise ValueError("unexpected symlink in evidence")
                if not path.is_file():
                    continue
                relative = path.relative_to(ROOT)
                record = {"path": str(relative), "sha256": file_hash(path), "bytes": path.stat().st_size}
                if "project" in path.relative_to(source).parts:
                    excluded.append(record)
                    continue
                tar.add(path, arcname=str(relative), recursive=False)
                included.append(record)
    return {"archive": destination.name, "sha256": file_hash(destination), "bytes": destination.stat().st_size,
            "included": included, "excluded_transient_project_databases": excluded}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--csrd", default="build-linux-release/csrd")
    args = parser.parse_args()
    source, output = Path(args.run_dir).resolve(), Path(args.output_dir).resolve()
    if json.loads((source / "completion.json").read_text())["status"] != "completed":
        parser.error("completed pilot required")
    output.mkdir(parents=True, exist_ok=False)
    index = {"created_utc": datetime.now(timezone.utc).isoformat(), "archives": [],
             "exclusion_reason": "Transient imported Ghidra project databases are reproducible from retained binaries, logs and export artifacts; hashes of excluded files are retained.",
             "human_data": "none; unassessed"}
    for name in ("matrix", "blackbox", "ghidra", "runtime"):
        print(name, flush=True)
        index["archives"].append(archive(source / name, output / (name + ".tar.gz")))
        if name != "matrix":
            shutil.copy2(source / name / "summary.json", output / (name + "-summary.json"))
            shutil.copy2(source / name / "trials.csv", output / (name + "-trials.csv"))
    for path in source.iterdir():
        if path.is_file():
            shutil.copy2(path, output / path.name)
    tool = Path(args.csrd).resolve()
    expected = json.loads((source / "matrix/matrix.json").read_text())["tools"]["csrd"]["sha256"]
    if file_hash(tool) != expected:
        raise ValueError("scoring binary differs from the matrix")
    with (output / "scoring-verifier.gz").open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
        zipped.write(tool.read_bytes())
    index["scoring_verifier"] = {"uncompressed_sha256": expected, "archive": "scoring-verifier.gz",
                                 "sha256": file_hash(output / "scoring-verifier.gz"),
                                 "scope": "Linux ARM64; requires the documented LLVM18/Z3 container libraries"}
    save(output / "index.json", index)
    return 0


if __name__ == "__main__":
    sys.exit(main())
