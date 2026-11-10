#!/usr/bin/env python3
"""Archive validated wide-observer evidence, preserving earlier studies by reference."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments"))
from archive_effort import archive, compact_index


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_archive(output, entry):
    expected = {p["path"]: p for p in entry["included"]}
    observed, byte_count = set(), 0
    with tarfile.open(output / entry["archive"], "r:gz") as tar:
        for member in tar:
            if not member.isfile() or member.name in observed or member.name not in expected:
                raise ValueError("unexpected or duplicate archive member")
            value = hashlib.sha256()
            stream = tar.extractfile(member)
            for block in iter(lambda: stream.read(1024*1024), b""):
                value.update(block)
            record = expected[member.name]
            if member.size != record["bytes"] or value.hexdigest() != record["sha256"]:
                raise ValueError("archive differs from retained evidence")
            observed.add(member.name); byte_count += member.size
    if observed != set(expected):
        raise ValueError("missing archive members")
    return {"archive": entry["archive"], "files": len(observed), "uncompressed_bytes": byte_count, "passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--development", type=Path, required=True)
    parser.add_argument("--observer-run", type=Path, required=True)
    parser.add_argument("--old-query-replay", type=Path, required=True)
    parser.add_argument("--new-query-replay", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    output = args.output_dir.resolve()
    summary = json.loads(args.summary.read_text())
    if summary["status"] != "completed":
        raise ValueError("completed bound analysis required")
    for path, expected in summary["source_bindings"].items():
        if digest(ROOT / path) != expected:
            raise ValueError("analysis input changed: " + path)
    groups = [("development", args.development.resolve()), ("observer-repeat", args.observer_run.resolve()),
              ("old-query-grading", args.old_query_replay.resolve()), ("new-query-grading", args.new_query_replay.resolve())]
    earlier_native = ROOT / "build/experiments/runs/pcode-wide-development-20261110/final-native"
    if earlier_native.exists():
        groups.append(("prevector-native-evidence", earlier_native))
    for name, directory in groups:
        if name in ("observer-repeat", "old-query-grading", "new-query-grading"):
            if json.loads((directory / "completion.json").read_text())["status"] != "completed":
                raise ValueError("incomplete experiment: " + name)
    output.mkdir(parents=True, exist_ok=False)
    index = {"created_utc": datetime.now(timezone.utc).isoformat(), "archives": [],
             "scope": "bounded wide/vector observer, tests, failed prototypes, unchanged-binary repeat and separate query grading",
             "exclusion_reason": "Transient Ghidra project databases are reproducible from retained binaries and exports; their hashes are retained.",
             "human_data": "none; human effort unassessed"}
    for name, directory in groups:
        print("archive", name, flush=True)
        index["archives"].append(archive(directory, output / (name + ".tar.gz")))
    shutil.copy2(args.summary, output / "summary.json")
    shutil.copy2(args.summary.with_suffix(".csv"), output / "tradeoffs.csv")
    for filename in ("validation-summary.json", "ctest-final-native.log", "ctest-final-linux.log", "final-source-bindings.json"):
        shutil.copy2(args.development / filename, output / filename)
    for filename in ("summary.json", "trials.csv", "protocol.json"):
        shutil.copy2(args.observer_run / "effort" / filename, output / ("observer-" + filename))
    for filename in ("protocol.json", "completion.json"):
        shutil.copy2(args.observer_run / filename, output / ("repeat-" + filename))
    scripts = output / "implementation"
    paths = ["experiments/" + name for name in ("archive_wide_observer.py", "archive_effort.py", "run_wide_observer.py",
             "grade_wide_observer.py", "investigate_width_grades.py", "grade_saved_answers.py", "summarize_wide_observer.py", "summarize_positional_widths.py")]
    paths += ["tools/" + name for name in ("pcode_values.py", "pcode_wide.py", "pcode_vector.py", "pcode_cfg.py",
              "pcode_reconstruct.py", "audit_decompiler.py", "measure_effort.py", "effort_statistics.py", "ghidra/ExportCSRD.java")]
    paths += ["tests/integration/test_pcode_wide.py", "tests/integration/test_pcode_vector.py"]
    for path in paths:
        destination = scripts / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / path, destination)
    index["implementation"] = {str(p.relative_to(output)): digest(p) for p in sorted(scripts.rglob("*")) if p.is_file()}
    # Supplemental provenance, captured at packaging time. The original protocol
    # binds the decompiler binaries/JAR and version, not the entire installation.
    ghidra = ROOT / "experiments/runs/dependencies/ghidra_12.2_PUBLIC"
    language = ghidra / "Ghidra/Processors/AARCH64/data/languages"
    references = output / "ghidra-language"; references.mkdir()
    reference_files = [ghidra / "LICENSE", *(language / name for name in
                       ("AARCH64neon.sinc", "AARCH64.sla", "AARCH64.ldefs", "AARCH64.pspec", "AARCH64.cspec"))]
    for path in reference_files:
        shutil.copy2(path, references / path.name)
    language_archive = archive(references, output / "ghidra-language.tar.gz")
    index["archives"].append(language_archive)
    index["supplemental_ghidra_language"] = {"capture": "post-run packaging; no claim of a pre-run full-installation attestation",
        "archive": language_archive["archive"],
        "members": {str(p.relative_to(ROOT)): digest(p) for p in sorted(references.iterdir())}}
    shutil.rmtree(references)
    old = ROOT / "reports/positional-widths-evidence-20261110"
    # Do not duplicate or modify the original 500-cell matrix and observer run.
    reused = ["matrix.tar.gz", "ghidra-repeat.tar.gz", "circuit-grading.tar.gz", "linked-sizes.tar.gz", "scoring-verifier.gz",
              "index.json", "file-manifests.json.gz", "summary.json", "sha256.json", "archive-validation.json"]
    index["reused_frozen_evidence"] = {str((old / p).relative_to(ROOT)): digest(old / p) for p in reused}
    dependencies = ROOT / "reports/circuit-evidence-20261110"
    protocol = json.loads((args.new_query_replay / "protocol.json").read_text())
    expected_tools = {"build/csrd-query-circuit": protocol["tools"]["circuit_sha256"],
                      "experiments/runs/solver-probes-20261110/abc-src/abc": protocol["tools"]["abc_sha256"]}
    with tarfile.open(dependencies / "native-tools.tar.xz", "r:xz") as tar:
        for name, expected in expected_tools.items():
            if hashlib.sha256(tar.extractfile(name).read()).hexdigest() != expected:
                raise ValueError("retained native grading tool differs from this experiment")
    index["reused_circuit_dependencies"] = {str((dependencies / name).relative_to(ROOT)): digest(dependencies / name)
                                            for name in ("native-tools.tar.xz", "dependencies.json", "ABC-COPYRIGHT.txt")}
    validation = {"archives": [validate_archive(output, entry) for entry in index["archives"]], "all_passed": True}
    compact_index(index, output)
    (output / "archive-validation.json").write_text(json.dumps(validation, indent=2)+"\n")
    hashes = {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "sha256.json").write_text(json.dumps(hashes, indent=2)+"\n")
    print("PASS", sum(v["files"] for v in validation["archives"]), "archived files verified")


if __name__ == "__main__":
    main()
