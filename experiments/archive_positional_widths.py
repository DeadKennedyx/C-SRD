#!/usr/bin/env python3
"""Package completed positional-width evidence and verify every included byte."""
import argparse
from datetime import datetime, timezone
import gzip
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--development-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--circuit-dir", type=Path)
    parser.add_argument("--sizes-dir", type=Path, required=True)
    parser.add_argument("--ghidra-repeat-dir", type=Path, required=True)
    parser.add_argument("--finite-checks-dir", type=Path, required=True)
    args = parser.parse_args()
    source, development, output = args.run_dir.resolve(), args.development_dir.resolve(), args.output_dir.resolve()
    repeat = args.ghidra_repeat_dir.resolve()
    if json.loads((repeat / "completion.json").read_text())["status"] != "completed":
        raise ValueError("completed Ghidra repeat required")
    summary = json.loads(args.summary.read_text())
    if summary["status"] != "completed":
        raise ValueError("completed summary required")
    for name, expected in {**summary["source_bindings"], **summary["auxiliary_input_bindings"]}.items():
        if digest(ROOT / name) != expected:
            raise ValueError("summary input changed: " + name)
    output.mkdir(parents=True, exist_ok=False)
    index = {"created_utc": datetime.now(timezone.utc).isoformat(), "archives": [],
             "scope": "frozen development comparison and retained failed prototypes; no human data",
             "exclusion_reason": "Transient Ghidra project databases are reproducible from retained binaries/exports; excluded file hashes remain in the manifest."}
    groups = [("development", development), *((name, source / name) for name in ("matrix", "bitlinear")),
              ("ghidra-interrupted", source / "ghidra"), ("ghidra-repeat", repeat),
              ("linked-sizes", args.sizes_dir.resolve()), ("finite-checks", args.finite_checks_dir.resolve())]
    if args.circuit_dir:
        circuit = args.circuit_dir.resolve()
        if json.loads((circuit / "completion.json").read_text())["status"] != "completed":
            raise ValueError("circuit follow-up is incomplete")
        groups.append(("circuit-grading", circuit))
    for name, path in groups:
        print("archive", name, flush=True)
        index["archives"].append(archive(path, output / (name + ".tar.gz")))
    for name in ("bitlinear", "ghidra"):
        observer = repeat / "effort" if name == "ghidra" else source / name
        for filename in ("summary.json", "trials.csv", "protocol.json"):
            shutil.copy2(observer / filename, output / (name + "-" + filename))
    for filename in ("commands.json", "frozen-protocol.json", "implementation-identity.json", "interruption.json", "interruption-final.json"):
        shutil.copy2(source / filename, output / filename)
    if (source / "ghidra-interruption-snapshot.json").is_file():
        with (output / "interruption-snapshot.json.gz").open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
            zipped.write((source / "ghidra-interruption-snapshot.json").read_bytes())
    shutil.copy2(repeat / "completion.json", output / "repeat-completion.json")
    for name in ("ctest-native.log", "ctest-linux.log", "final-source-bindings.json"):
        shutil.copy2(development / name, output / name)
    shutil.copy2(args.summary, output / "summary.json")
    # Keep the analysis and packaging implementation, including its dependencies.
    scripts = output / "implementation"; scripts.mkdir()
    for name in ("archive_positional_widths.py", "archive_effort.py", "run_positional_widths.py",
                 "repeat_positional_ghidra.py", "measure_linked_sizes.py", "summarize_positional_widths.py",
                 "check_positional_answers.py", "grade_saved_answers.py"):
        shutil.copy2(ROOT / "experiments" / name, scripts / name)
    shutil.copy2(ROOT / "tools/effort_statistics.py", scripts / "effort_statistics.py")
    index["analysis_sources"] = {str(p.relative_to(output)): digest(p) for p in sorted(scripts.iterdir())}
    if args.circuit_dir:
        # These exact native binaries are already retained with their licenses.
        dependencies = ROOT / "reports/circuit-evidence-20261110"
        protocol = json.loads((args.circuit_dir / "protocol.json").read_text())
        expected_tools = {"build/csrd-query-circuit": protocol["tools"]["circuit_sha256"],
                          "experiments/runs/solver-probes-20261110/abc-src/abc": protocol["tools"]["abc_sha256"]}
        with tarfile.open(dependencies / "native-tools.tar.xz", "r:xz") as tar:
            for name, expected in expected_tools.items():
                if hashlib.sha256(tar.extractfile(name).read()).hexdigest() != expected:
                    raise ValueError("retained circuit tool differs from this experiment")
        index["reused_circuit_dependencies"] = {
            str((dependencies / name).relative_to(ROOT)): digest(dependencies / name)
            for name in ("native-tools.tar.xz", "dependencies.json", "ABC-COPYRIGHT.txt")}
    with (output / "scoring-verifier.gz").open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0) as zipped:
        zipped.write((source / "csrd").read_bytes())
    index["scoring_verifier"] = {"archive": "scoring-verifier.gz", "uncompressed_sha256": digest(source / "csrd"),
                                 "scope": "Linux ARM64; LLVM18/Z3 libraries in the recorded container image"}
    # Validate archive members against their original per-file manifest, without extraction.
    validation = {"archives": [], "all_passed": True}
    for entry in index["archives"]:
        expected = {p["path"]: p for p in entry["included"]}
        observed, byte_count = {}, 0
        with tarfile.open(output / entry["archive"], "r:gz") as tar:
            for member in tar:
                if not member.isfile() or member.name in observed:
                    raise ValueError("unexpected or duplicate archive member")
                stream = tar.extractfile(member)
                value = hashlib.sha256()
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    value.update(block)
                observed[member.name] = value.hexdigest(); byte_count += member.size
                if member.name not in expected or member.size != expected[member.name]["bytes"] or observed[member.name] != expected[member.name]["sha256"]:
                    raise ValueError("archive member differs from original evidence")
        if set(observed) != set(expected):
            raise ValueError("missing archive members")
        validation["archives"].append({"archive": entry["archive"], "files": len(observed), "uncompressed_bytes": byte_count, "passed": True})
    with gzip.open(output / "scoring-verifier.gz", "rb") as stream:
        if hashlib.sha256(stream.read()).hexdigest() != index["scoring_verifier"]["uncompressed_sha256"]:
            raise ValueError("compressed frontend changed")
    compact_index(index, output)
    (output / "archive-validation.json").write_text(json.dumps(validation, indent=2) + "\n")
    hashes = {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output / "sha256.json").write_text(json.dumps(hashes, indent=2) + "\n")
    print("PASS", sum(x["files"] for x in validation["archives"]), "archived files verified")


if __name__ == "__main__":
    main()
