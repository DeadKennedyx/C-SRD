#!/usr/bin/env python3
"""Validate rich benchmark contracts independently of candidate selection.

Runs admitted original/control C with GCC and Clang, checks oracle results,
source-equivalence controls, explicit negative witnesses and finite fingerprints.
Reserved families receive correctness checks only, not reconstruction tuning.
"""
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import platform
import sys
import time

from audit_protection import Runner, AuditError, MODEL_GUARD, executable, file_hash, require_one_function
from benchmark_oracles import ORACLES, vectors
from effort_resources import save
from experiment_support import driver_source, outputs, input_vectors, digest

ROOT = Path(__file__).resolve().parents[1]


def proof(command, csrd, reference, other, destination, timeout_ms):
    try:
        command([csrd, "verify", reference, other, "--timeout-ms", timeout_ms, "--report", destination],
                timeout=timeout_ms/1000 + 20)
    except AuditError:
        if not destination.is_file():
            raise
    data = json.loads(destination.read_text())
    if len(data.get("functions", [])) != 1:
        raise ValueError("one source-level comparison required")
    return data["functions"][0]


def run(args, root):
    start = time.perf_counter()
    manifest_path = Path(args.manifest).resolve(strict=True)
    manifest = json.loads(manifest_path.read_text())
    cases = manifest["cases"]
    if args.case:
        cases = [c for c in cases if c["id"] in args.case]
        if {c["id"] for c in cases} != set(args.case):
            raise ValueError("unknown case")
    if len({c["family"] for c in manifest["cases"]}) != len(manifest["cases"]):
        raise ValueError("rich v1 requires distinct algorithm families")
    report = {"schema_version": 1, "status": "running", "commands": [], "records": [], "proofs": [],
              "cases": cases, "platform": platform.platform(), "settings": vars(args),
              "manifest_sha256": file_hash(manifest_path),
              "scope": "benchmark correctness and control validation; no protection or reconstruction measurements",
              "reserved_policy": "correctness-only; do not tune candidate/observer on reserved recovery outcomes",
              "source_bindings": {}, "fingerprint_pairs": []}
    command = Runner(report)
    args.csrd = executable(args.csrd)
    report["csrd"] = {"path": args.csrd, "sha256": file_hash(args.csrd),
                       "version": command([args.csrd, "--version"]).strip()}
    report["oracle_sha256"] = file_hash(ROOT / "tools/benchmark_oracles.py")
    report["implementation_sha256"] = file_hash(__file__)
    report["compilers"] = []
    for specification in args.compiler:
        family, name = specification.split("=", 1)
        path = executable(name)
        version = command([path, "--version"]).splitlines()[0]
        if family not in ("clang", "gcc") or family not in version.lower():
            raise ValueError("compiler family must match real driver, not an alias")
        report["compilers"].append({"family": family, "path": path, "version": version, "sha256": file_hash(path)})
    if {c["family"] for c in report["compilers"]} != {"clang", "gcc"}:
        raise ValueError("both GCC and Clang are required by this validation protocol")
    for case in cases:
        directory = root / case["id"]; directory.mkdir()
        probes = vectors(case["arity"], args.seed, args.inputs)
        oracle = ORACLES[case["oracle"]]
        expected = [oracle(*v) for v in probes]
        discovery = input_vectors(case["arity"], args.seed + 1, 64)
        save(directory / "oracle.json", {"inputs": probes, "expected": expected, "oracle": case["oracle"]})
        implementations = [{"id": "original", "source": case["source"], "relation": "equivalent"},
                           *case.get("controls", [])]
        for implementation in implementations:
            source = (ROOT / implementation["source"]).resolve(strict=True)
            report["source_bindings"][str(source)] = file_hash(source)
            target = directory / implementation["id"]; target.mkdir()
            analysis_path = target / "analysis.json"
            command([args.csrd, "analyze", source, "--report", analysis_path])
            analysis = json.loads(analysis_path.read_text())
            function = require_one_function(analysis)
            if function["function"] != "kernel" or function["parameter_count"] != case["arity"]:
                raise ValueError("neutral benchmark interface differs from manifest")
            if implementation["id"] != "original":
                evidence = proof(command, args.csrd, ROOT / case["source"], source,
                                 target / "proof.json", args.timeout_ms)
                wanted = "proved-under-model" if implementation["relation"] == "equivalent" else "counterexample"
                report["proofs"].append({"case": case["id"], "implementation": implementation["id"],
                                         "expected": wanted, "result": evidence})
                if evidence["verification"] != wanted:
                    raise ValueError(f"control {case['id']}/{implementation['id']}: expected {wanted}, got {evidence['verification']}")
            driver = target / "driver.c"
            driver.write_text(driver_source("kernel", case["arity"]) + "\n" + MODEL_GUARD)
            for compiler in report["compilers"]:
                for profile in ["O0", "O2"] + (["O1-sanitizers"] if args.sanitizers else []):
                    flags = ["-std=c11", "-Wall", "-Wextra", "-Wpedantic", "-Wconversion", "-Werror",
                             "-" + profile.split("-")[0]]
                    if profile.endswith("sanitizers"):
                        flags += ["-fsanitize=address,undefined", "-fno-sanitize-recover=all", "-fno-omit-frame-pointer"]
                    binary = target / (compiler["family"] + "-" + profile)
                    print(f"{case['id']}/{implementation['id']}/{binary.name}", flush=True)
                    command([compiler["path"], *flags, source, driver, "-o", binary])
                    actual = outputs(command, binary, probes)
                    differences = [i for i, (a, b) in enumerate(zip(actual, expected)) if a != b]
                    if implementation["relation"] == "equivalent" and differences:
                        i = differences[0]
                        raise ValueError(f"oracle mismatch: {case['id']} {probes[i]} expected {expected[i]} got {actual[i]}")
                    witness = implementation.get("witness")
                    if implementation["relation"] == "different":
                        if not witness or outputs(command, binary, [witness])[0] == oracle(*witness):
                            raise ValueError("negative control lacks its declared compiled counterexample")
                    fingerprint = outputs(command, binary, discovery)
                    record = {"case": case["id"], "family": case["family"], "split": case["split"],
                              "implementation": implementation["id"], "relation": implementation["relation"],
                              "arity": case["arity"], "compiler": compiler["family"], "profile": profile,
                              "source_sha256": file_hash(source), "binary_sha256": file_hash(binary),
                              "probes": len(probes), "oracle_mismatches": len(differences),
                              "inputs_sha256": digest(probes), "outputs_sha256": digest(actual),
                              "discovery_sha256": digest(fingerprint), "discovery_queries": len(discovery),
                              "known_answers": []}
                    for known in case.get("known_answers", []):
                        if implementation["relation"] == "equivalent":
                            observed = outputs(command, binary, [known["input"]])[0]
                            if observed != known["output"]:
                                raise ValueError("known-answer mismatch")
                            record["known_answers"].append({**known, "observed": observed})
                    # CRC standard check string also tests state composition through the compiled function.
                    if case["oracle"] == "crc32_byte" and implementation["relation"] == "equivalent":
                        crc = 0
                        for byte in b"123456789":
                            crc = outputs(command, binary, [(crc, byte)])[0]
                        if crc != 0xcbf43926:
                            raise ValueError("CRC check-string mismatch")
                        record["crc_check_string"] = {"input_ascii": "123456789", "output": crc}
                    report["records"].append(record)
            save(root / "validation.json", report)
    for a, b in itertools.combinations(report["records"], 2):
        if (a["compiler"], a["profile"], a["arity"]) != (b["compiler"], b["profile"], b["arity"]):
            continue
        # Every distinct family has its own contract. Wrong controls have explicit counterexamples.
        equivalent = a["family"] == b["family"] and a["relation"] == b["relation"] == "equivalent"
        match = a["discovery_sha256"] == b["discovery_sha256"]
        report["fingerprint_pairs"].append({"a": [a["case"], a["implementation"]], "b": [b["case"], b["implementation"]],
            "compiler": a["compiler"], "profile": a["profile"], "expected_equivalent": equivalent,
            "fingerprints_match": match, "classification": ("true-positive" if equivalent else "false-positive") if match
            else ("false-negative" if equivalent else "true-negative")})
    if any(file_hash(p) != h for p, h in report["source_bindings"].items()):
        raise ValueError("source changed during benchmark validation")
    if file_hash(manifest_path) != report["manifest_sha256"] or file_hash(ROOT / "tools/benchmark_oracles.py") != report["oracle_sha256"]:
        raise ValueError("manifest or oracle changed during validation")
    report.update(status="passed", seconds=time.perf_counter()-start,
                  fingerprint_confusion=dict(Counter(p["classification"] for p in report["fingerprint_pairs"])))
    save(root / "validation.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", default=str(ROOT / "experiments/rich-benchmarks.json"))
    parser.add_argument("--csrd", required=True)
    parser.add_argument("--compiler", action="append", required=True, help="clang=PATH and gcc=PATH")
    parser.add_argument("--case", action="append")
    parser.add_argument("--inputs", type=int, default=2048)
    parser.add_argument("--seed", type=int, default=20261110)
    parser.add_argument("--timeout-ms", type=int, default=30000)
    parser.add_argument("--sanitizers", action="store_true")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.inputs < 1 or args.timeout_ms < 1:
        parser.error("positive input count and proof timeout required")
    root = Path(args.output_dir).resolve()
    try:
        root.mkdir(parents=True, exist_ok=False)
        report = run(args, root)
        print(report["status"] + ": " + str(root / "validation.json"))
        return 0
    except (OSError, ValueError, KeyError, AuditError) as error:
        if root.exists():
            save(root / "failure.json", {"status": "failed", "error": str(error)})
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
