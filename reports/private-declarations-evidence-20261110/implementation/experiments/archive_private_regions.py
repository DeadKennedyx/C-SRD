#!/usr/bin/env python3
"""Archive the private-region prototype, matched cost runs and retained test failures."""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import shutil

from archive_effort import archive, compact_index
from archive_wide_observer import digest, validate_archive

ROOT = Path(__file__).resolve().parents[1]
SOURCES = ["CMakeLists.txt", "src/main.cpp", "src/frontend/frontend.cpp", "src/analysis/private_regions.cpp",
           "src/codegen/private_emitter.cpp", "include/csrd/frontend.hpp", "include/csrd/planner.hpp",
           "include/csrd/private_regions.hpp", "src/verification/memory.cpp", "src/verification/symbolic.hpp",
           "include/csrd/ir.hpp", "include/csrd/verification.hpp", "include/csrd/graph_emitter.hpp",
           "src/representation/representation.cpp", "include/csrd/representation.hpp",
           "tests/unit/private_regions_test.cpp", "tests/integration/test_private_regions.py",
           "tests/fixtures/private_regions.c", "tests/differential/run.py",
           "tests/fixtures/private_declarations.c",
           "experiments/measure_private_regions.py", "experiments/check_private_region_measurements.py",
           "experiments/archive_private_regions.py", "experiments/archive_effort.py", "experiments/archive_wide_observer.py"]


def main():
    p = argparse.ArgumentParser(description=__doc__);p.add_argument("--output-dir",type=Path,required=True)
    p.add_argument("--experiment",choices=("private-regions","private-declarations"),default="private-regions")
    args = p.parse_args(); output = args.output_dir.resolve();output.mkdir(parents=True,exist_ok=False)
    prefix = args.experiment
    index = {"created_utc":datetime.now(timezone.utc).isoformat(),"archives":[],
             "scope":prefix+" prototype; contextual scalar proofs, compiled event tests and linked application-cost development pilot",
             "protection_advantage_established":False}
    summary = {"hosts":{},"test_scope":"macOS full 31/31; Linux 29/31 initially then both new groups and CLI regression passed after test-fixture newline correction; optional checks remain explicit in raw logs"}
    if prefix == "private-declarations":
        summary["test_scope"] = "macOS and Linux full 31/31, followed by three report-ID/scope checks per host after a reporting-only change; optional skips and initial unused-variable failures retained"
        for host in ("native","linux"):
            log = (ROOT/f"experiments/runs/{prefix}-{host}-full-20261110.log").read_text()
            if not any(line.startswith("100% tests passed") and line.endswith("out of 31") for line in log.splitlines()):
                raise ValueError("full CTest result missing")
            followup = (ROOT/f"experiments/runs/{prefix}-{host}-report-followup-20261110.log").read_text()
            if "Ran 3 tests" not in followup or not followup.rstrip().endswith("OK"):
                raise ValueError("report-ID followup missing")
    for host in ("native","linux"):
        directory = ROOT / f"experiments/runs/{prefix}-cost-{host}-20261110"
        report = json.loads((directory/"measurement.json").read_text());check = json.loads((directory/"evidence-check.json").read_text())
        if report["status"] != "completed" or check["status"] != "checked" or check["report_sha256"] != digest(directory/"measurement.json"):
            raise ValueError("measurement evidence is incomplete or changed")
        for name in report["implementation"]:
            if name not in SOURCES: SOURCES.append(name)
        summary["hosts"][host] = {"report_sha256":digest(directory/"measurement.json"),"checks":check,"tools":report["tools"],
                                  "profiles":report["profiles"],"paired_results":report["summaries"]}
        index["archives"].append(archive(directory,output/(host+"-costs.tar.gz")))
    tests = ROOT / f"experiments/runs/{prefix}-tests-20261110";tests.mkdir(exist_ok=False)
    for log in sorted((ROOT/"experiments/runs").glob(prefix+"-*.log")): shutil.copy2(log,tests/log.name)
    for label, directory in (("native","build"),("linux","build-linux-regions")):
        shutil.copy2(ROOT/directory/"Testing/Temporary/LastTest.log",tests/(label+"-last-focused.log"))
    index["archives"].append(archive(tests,output/"tests.tar.gz"))
    index["archives"].append(archive(ROOT/f"experiments/runs/{prefix}-development-20261110",output/"prototype.tar.gz"))
    for name in SOURCES:
        target = output/"implementation"/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(ROOT/name,target)
    for label, directory in (("native","build"),("linux","build-linux-regions")):
        source = ROOT/directory/"csrd"
        expected = summary["hosts"][label]["tools"]["csrd"]["sha256"]
        if digest(source) != expected: raise ValueError("transformation binary changed")
        with (output/(label+"-csrd.gz")).open("wb") as raw,gzip.GzipFile(fileobj=raw,mode="wb",mtime=0) as zipped:
            zipped.write(source.read_bytes())
    (output/"summary.json").write_text(json.dumps(summary,indent=2)+"\n")
    index["implementation"] = {str(p.relative_to(output)):digest(p) for p in sorted((output/"implementation").rglob("*")) if p.is_file()}
    validation = {"all_passed":True,"archives":[validate_archive(output,a) for a in index["archives"]]}
    if any(a["bytes"] >= 100_000_000 for a in index["archives"]): raise ValueError("split oversized archive before publication")
    compact_index(index,output)
    (output/"archive-validation.json").write_text(json.dumps(validation,indent=2)+"\n")
    hashes = {str(p.relative_to(output)):digest(p) for p in sorted(output.rglob("*")) if p.is_file()}
    (output/"sha256.json").write_text(json.dumps(hashes,indent=2)+"\n")
    print("PASS",sum(a["files"] for a in validation["archives"]),"archived files verified")


if __name__ == "__main__": main()
