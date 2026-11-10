#!/usr/bin/env python3
"""Freeze buffer observer results, deviations, implementation and compiler checks."""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil

from archive_effort import archive, compact_index
from archive_wide_observer import digest, validate_archive

ROOT = Path(__file__).resolve().parents[1]
RUNS = ["buffer-observer-dev-20261110", "buffer-reconstruction-smoke-20261110",
        "buffer-reconstruction-development-20261110", "buffer-reconstruction-controls-v2-20261110",
        "buffer-runtime-smoke-20261110", "buffer-runtime-development-20261110",
        "buffer-runtime-development-20261110-v2", "buffer-runtime-development-20261110-v3",
        "buffer-answers-native-20261110", "buffer-answers-linux-20261110", "buffer-observer-tests-20261110"]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output-dir", type=Path, required=True)
    args = p.parse_args()
    summary_path = ROOT / "experiments/runs/buffer-observer-tests-20261110/summary.json"
    summary = json.loads(summary_path.read_text())
    if summary["status"] != "completed": raise ValueError("completed summary required")
    for path, sha in summary["source_bindings"].items():
        if digest(ROOT / path) != sha: raise ValueError("summary input changed: "+path)
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=False)
    index = {"created_utc": datetime.now(timezone.utc).isoformat(), "archives": [],
             "scope": "bounded buffer reconstruction and known-intermediate runtime development evidence; includes interrupted and revised protocols",
             "exclusion_reason": "Only transient Ghidra project databases are excluded; their hashes remain in the manifest."}
    for name in RUNS:
        print("archive", name, flush=True)
        entry = archive(ROOT / "experiments/runs" / name, output / (name+".tar.gz"))
        if entry["bytes"] >= 100_000_000: raise ValueError("split oversized archive before publication")
        index["archives"].append(entry)
    shutil.copy2(summary_path, output / "summary.json")
    # Freeze all shared dependencies named by any completed observer report.
    sources = {"experiments/"+name for name in ("archive_buffer_observers.py", "summarize_buffer_observers.py",
                "check_buffer_evidence_controls.py", "archive_effort.py", "archive_wide_observer.py")}
    sources.update({"tools/check_buffer_evidence.py", "tests/integration/test_buffer_runtime.py", "tests/integration/test_pcode_memory.py"})
    for run in RUNS:
        for name in ("runtime.json", "reconstruction.json", "validation.json"):
            report = ROOT / "experiments/runs" / run / name
            if report.exists(): sources.update(json.loads(report.read_text()).get("implementation", {}))
    for name in sorted(sources):
        target = output / "implementation" / name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / name, target)
    tool = ROOT / "build-linux/csrd"
    study = json.loads((ROOT / "experiments/runs/buffer-reconstruction-development-20261110/reconstruction.json").read_text())
    expected = study["tools"]["csrd"]["sha256"]
    if digest(tool) != expected: raise ValueError("source grading binary changed")
    with (output / "scoring-verifier.gz").open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
        zipped.write(tool.read_bytes())
    index["scoring_verifier"] = {"uncompressed_sha256": expected, "archive": "scoring-verifier.gz",
                                "scope": "Linux ARM64 with LLVM18/Z3 development container libraries"}
    index["implementation"] = {str(p.relative_to(output)): digest(p) for p in sorted((output / "implementation").rglob("*")) if p.is_file()}
    validation = {"all_passed": True, "archives": [validate_archive(output, entry) for entry in index["archives"]]}
    compact_index(index, output)
    (output / "archive-validation.json").write_text(json.dumps(validation, indent=2)+"\n")
    hashes = {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "sha256.json").write_text(json.dumps(hashes, indent=2)+"\n")
    print("PASS", sum(a["files"] for a in validation["archives"]), "archived files verified", flush=True)


if __name__ == "__main__": main()
