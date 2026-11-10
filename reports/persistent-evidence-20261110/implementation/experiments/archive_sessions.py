#!/usr/bin/env python3
"""Package persistent-session evidence and verify every archived file."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile

from archive_effort import archive, compact_index
from archive_wide_observer import digest, validate_archive

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("development", "sessions", "grades", "followup", "summary-dir", "output-dir"):
        parser.add_argument("--"+name, type=Path, required=True)
    args = parser.parse_args()
    summary = json.loads((args.summary_dir/"summary.json").read_text())
    if summary["status"] != "completed": raise ValueError("completed bound summary required")
    for path, sha in summary["source_bindings"].items():
        if digest(ROOT/path) != sha: raise ValueError("analysis evidence changed: "+path)
    diagnostics = json.loads((args.summary_dir/"diagnostics.json").read_text())
    for path, sha in diagnostics["source_bindings"].items():
        if digest(ROOT/path) != sha: raise ValueError("diagnostic evidence changed: "+path)
    groups = [("development", args.development), ("session-repeat", args.sessions),
              ("source-grading", args.grades), ("query-grading", args.followup)]
    for name, path in groups[1:]:
        if json.loads((path/"completion.json").read_text())["status"] != "completed":
            raise ValueError("incomplete evidence: "+name)
    output = args.output_dir.resolve(); output.mkdir(parents=True, exist_ok=False)
    index = {"created_utc": datetime.now(timezone.utc).isoformat(), "archives": [],
             "scope": "persistent per-function automated reconstruction; development corpus; no human or runtime-memory observations",
             "exclusion_reason": "Transient Ghidra project databases can be regenerated from frozen binaries and exports; excluded hashes retained."}
    for name, path in groups:
        print("archive", name, flush=True)
        entry = archive(path.resolve(), output/(name+".tar.gz"))
        if entry["bytes"] >= 100_000_000: raise ValueError("archive needs splitting before publication")
        index["archives"].append(entry)
    for path in args.summary_dir.iterdir():
        if path.is_file(): shutil.copy2(path, output/path.name)
    for name in ("validation-summary.json", "native-ctest.log", "linux-ctest.log",
                 "native-focused-final.log", "linux-focused-final.log"):
        shutil.copy2(args.development/name, output/name)
    for name, source in (("session", args.sessions), ("source-grade", args.grades), ("circuit-grade", args.followup)):
        for file in ("protocol.json", "completion.json"):
            shutil.copy2(source/file, output/(name+"-"+file))
    sources = ["experiments/"+name for name in ("archive_sessions.py", "archive_effort.py", "archive_wide_observer.py",
               "grade_session_answers.py", "grade_session_queries.py", "grade_saved_answers.py", "summarize_sessions.py", "diagnose_sessions.py",
               "summarize_wide_observer.py", "summarize_positional_widths.py")]
    sources += ["tools/"+name for name in ("process_counters.py", "measure_sessions.py", "session_worker.py", "session_evidence.py",
                "effort_resources.py", "effort_statistics.py", "measure_effort.py", "audit_decompiler.py", "audit_protection.py",
                "pcode_reconstruct.py", "pcode_values.py", "pcode_cfg.py", "pcode_wide.py", "pcode_vector.py",
                "ghidra/SessionCSRD.java", "ghidra/ExportCSRD.java", "verify_circuit.py", "verify_limbs.py", "query_circuit.cpp")]
    sources.append("tests/integration/test_sessions.py")
    for name in sources:
        target = output/"implementation"/name; target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT/name, target)
    index["implementation"] = {str(p.relative_to(output)): digest(p) for p in sorted((output/"implementation").rglob("*")) if p.is_file()}
    reused = {
        "reports/positional-widths-evidence-20261110": ("matrix.tar.gz", "scoring-verifier.gz", "summary.json", "linked-sizes.tar.gz", "index.json", "file-manifests.json.gz", "archive-validation.json"),
        "reports/pcode-wide-evidence-20261110": ("observer-repeat.tar.gz", "new-query-grading.tar.gz", "summary.json", "ghidra-language.tar.gz", "index.json", "file-manifests.json.gz", "archive-validation.json"),
        "reports/circuit-evidence-20261110": ("native-tools.tar.xz", "dependencies.json", "ABC-COPYRIGHT.txt")}
    index["reused_frozen_evidence"] = {str(Path(directory)/name): digest(ROOT/directory/name) for directory, names in reused.items() for name in names}
    protocol = json.loads((args.followup/"protocol.json").read_text())
    with tarfile.open(ROOT/"reports/circuit-evidence-20261110/native-tools.tar.xz", "r:xz") as tar:
        for name in ("build/csrd-query-circuit", "experiments/runs/solver-probes-20261110/abc-src/abc"):
            expected = protocol["bindings"][str(ROOT/name)]
            if hashlib.sha256(tar.extractfile(name).read()).hexdigest() != expected:
                raise ValueError("reused grading tool does not match this run")
    validation = {"all_passed": True, "archives": [validate_archive(output, entry) for entry in index["archives"]]}
    compact_index(index, output)
    (output/"archive-validation.json").write_text(json.dumps(validation, indent=2)+"\n")
    hashes = {str(p.relative_to(output)): digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output/"sha256.json").write_text(json.dumps(hashes, indent=2)+"\n")
    print("PASS", sum(row["files"] for row in validation["archives"]), "archived files verified")


if __name__ == "__main__": main()
