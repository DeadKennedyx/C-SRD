#!/usr/bin/env python3
"""Package the typed-integer checkpoint, including failed observer prototypes.

Run after the serialized 2026-11-12 measurements. This is the packaging recipe
for this particular experiment, not a generic experiment launcher.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil
import tarfile

from archive_effort import compact_index
from archive_wide_observer import digest, validate_archive

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "experiments/runs"
PARTS = {
    "build": "typed-integers-final-build-20261110",
    "reconstruction": "typed-integers-reconstruction-typed-final-20261112",
    "runtime": "typed-integers-runtime-20261112",
    "costs": "typed-integers-costs-20261112",
    "verification": "typed-integers-verification-20261112",
    "binaries": "typed-integers-binaries-20261112",
}


def package(paths, destination):
    included, excluded = [], []
    members = sorted({p for path in paths for p in
                      (path.rglob("*") if path.is_dir() else [path]) if p.is_file()})
    with destination.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w|") as archive:
            for path in members:
                if path.is_symlink():
                    raise ValueError("unexpected evidence symlink: " + str(path))
                name = str(path.relative_to(ROOT))
                entry = {"path": name, "sha256": digest(path), "bytes": path.stat().st_size}
                if "project" in path.relative_to(RUNS).parts:
                    excluded.append(entry)
                else:
                    archive.add(path, arcname=name, recursive=False)
                    included.append(entry)
    return {"archive": destination.name, "sha256": digest(destination), "bytes": destination.stat().st_size,
            "included": included, "excluded_transient_project_databases": excluded}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    summary_path = RUNS / "typed-integers-summary-20261112.json"
    summary = json.loads(summary_path.read_text())
    if summary["status"] != "summarized":
        raise ValueError("completed matched summary required")
    for label in ("build", "reconstruction", "runtime", "costs"):
        filename = "build.json" if label == "build" else label + ".json"
        if digest(RUNS / PARTS[label] / filename) != summary["report_hashes"][label]:
            raise ValueError("summary input changed: " + label)
    verification = json.loads((RUNS / PARTS["verification"] / "verification.json").read_text())
    if verification["status"] != "completed" or verification["build_sha256"] != summary["report_hashes"]["build"]:
        raise ValueError("query replay incomplete or on a different build")
    for host in ("native", "linux"):
        log = (RUNS / f"typed-integers-boolean-tests-{host}-20261112.log").read_text()
        if "Ran 11 tests" not in log or not log.rstrip().endswith("OK"):
            raise ValueError("observer regression evidence missing")
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    index = {"schema_version": 1, "created_utc": datetime.now(timezone.utc).isoformat(),
             "baseline": "3c26935", "transformer_version": "0.7.0",
             "docker_image": "sha256:880358a74512e1deac327db13818f10e5b0cf8538f3490996952b8d379541f00",
             "archives": [], "archive_paths": "Repository-relative paths; replay with the repository mounted at /work.",
             "scope": "Typed private-frame prototype and development observer follow-up; no whole-program or machine-code proof.",
             "exclusion_reason": "Transient Ghidra project databases are reproducible from retained binaries and exports; their hashes are retained."}
    selected = {RUNS / name for name in PARTS.values()}
    groups = [(label, [RUNS / name]) for label, name in PARTS.items()]
    other = sorted(p for p in RUNS.glob("typed-integer*") if p not in selected and p != summary_path)
    groups += [("development-and-tests", other)]
    for label, paths in groups:
        print("archive", label, flush=True)
        entry = package(paths, output / (label + ".tar.gz"))
        if entry["bytes"] >= 100_000_000:
            raise ValueError("split oversized archive before publication")
        index["archives"].append(entry)
    shutil.copy2(summary_path, output / "summary.json")
    validation = {"all_passed": True, "archives": [validate_archive(output, entry) for entry in index["archives"]]}
    compact_index(index, output)
    (output / "archive-validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    hashes = {str(p.relative_to(output)): digest(p) for p in sorted(output.iterdir()) if p.is_file()}
    (output / "sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print("PASS", sum(a["files"] for a in validation["archives"]), "archived files verified")


if __name__ == "__main__":
    main()
