#!/usr/bin/env python3
"""Run a fixed Ghidra reconstruction observer on hash-bound linked matrix artifacts.

Ghidra receives only the binary and known u32 ABI. Reference source is used solely
by the scoring verifier after reconstruction. Missing/unsupported/timeout != protected.
"""
import argparse
from collections import Counter
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from audit_protection import AuditError, Runner, executable, file_hash, write_json
from pcode_reconstruct import reconstruct, Unsupported
from pcode_cfg import LIMITS as PCODE_LIMITS

ROOT = Path(__file__).resolve().parents[1]


def scoring_reference(matrix, record):
    """Score against the exact header-free input of the matched original build."""
    original = next((r for r in matrix["records"] if r["case"] == record["case"]
                     and r["profile"] == record["profile"] and r["variant"] == "original"), None)
    if original is None or original["status"] != "completed":
        raise ValueError("original build did not complete")
    frozen = Path(original["binary"]).parent / "function.i"
    if file_hash(frozen) != original["preprocessed_sha256"]:
        raise ValueError("original preprocessed input changed since build validation")
    return frozen, original["preprocessed_sha256"]


def run_headless(report, argv, timeout):
    """Bound the launcher AND Java child; preserve output from failed/timed out runs."""
    argv = [str(a) for a in argv]
    record = {"argv": argv}
    report["commands"].append(record)
    start = time.perf_counter()
    with subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          text=True, start_new_session=True) as process:
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired as error:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
            record.update(stdout=stdout, stderr=stderr, returncode=None, status="timeout",
                          elapsed_seconds=time.perf_counter() - start)
            raise AuditError("headless process group timed out") from error
    record.update(stdout=stdout, stderr=stderr, returncode=process.returncode, status="completed",
                  elapsed_seconds=time.perf_counter() - start)
    if process.returncode:
        raise AuditError(f"headless failed ({process.returncode}); see retained command output")


def verify(command, csrd, reference, candidate, report_path, timeout_ms):
    try:
        command([csrd, "verify", reference, candidate, "--report", report_path,
                 "--timeout-ms", timeout_ms], timeout=timeout_ms / 1000 + 30)
    except AuditError:
        if not report_path.is_file():
            raise
    report = json.loads(report_path.read_text())
    functions = report["functions"]
    if len(functions) != 1:
        raise ValueError("scoring requires one function")
    return functions[0]


def run(args, root):
    report = {"schema_version": 1, "status": "running", "commands": [], "observations": [],
              "protocol": {"observer": "ghidra-high-pcode-cfg-wide-v3", "known_interface": True,
                           "known_symbol": True, "source_or_seed_given_to_observer": False,
                           "analysis_seconds": args.analysis_seconds, "decompile_seconds": args.decompile_seconds,
                           "process_seconds": args.process_seconds, "verification_ms": args.timeout_ms,
                           "adapter_limits": PCODE_LIMITS},
              "claims": {"binary_lifting_proved": False, "human_effort": "not-assessed",
                         "unsupported_or_timeout_means_protection": False, "confidentiality": "not-established"}}
    command = Runner(report)
    try:
        matrix_path = Path(args.matrix_report).resolve(strict=True)
        matrix = json.loads(matrix_path.read_text())
        report["matrix"] = {"path": str(matrix_path), "sha256": file_hash(matrix_path)}
        if matrix["status"] not in ("completed", "completed-with-gaps"):
            raise ValueError("observer requires a completed matrix")
        try:
            headless = executable(args.headless)
        except ValueError as error:
            report.update(status="unavailable", error=str(error)); return report
        csrd = executable(args.csrd)
        if file_hash(csrd) != matrix["tools"]["csrd"]["sha256"]:
            raise ValueError("scoring verifier must match the matrix's frontend/model binary")
        installation = Path(headless).resolve().parent.parent
        properties = installation / "Ghidra/application.properties"
        report["tools"] = {"csrd": {"path": csrd, "sha256": file_hash(csrd),
                                      "version": command([csrd, "--version"]).strip()},
                           "headless": {"path": headless, "sha256": file_hash(headless)},
                           "application_properties": properties.read_text()}
        # Bind decompiler and Java libraries, including locally built ARM64 natives.
        components = sorted(set(installation.glob("Ghidra/Features/Decompiler/lib/*.jar")) |
                            set(installation.glob("Ghidra/Features/Decompiler/os/*/decompile")))
        report["ghidra_components"] = [{"path": str(p), "sha256": file_hash(p)} for p in components]
        implementation = [Path(__file__), ROOT / "tools/pcode_reconstruct.py", ROOT / "tools/pcode_cfg.py",
                          ROOT / "tools/pcode_values.py", ROOT / "tools/pcode_wide.py", ROOT / "tools/pcode_vector.py", ROOT / "tools/ghidra/ExportCSRD.java"]
        report["implementation"] = {str(p.relative_to(ROOT)): file_hash(p) for p in implementation}
        records = [r for r in matrix["records"] if all(not requested or r[key] in requested
                   for key, requested in (("case", args.case), ("profile", args.profile), ("variant", args.variant)))]
        if not records:
            raise ValueError("no selected matrix cells")
        for key, requested in (("case", args.case), ("profile", args.profile), ("variant", args.variant)):
            if requested and not set(requested) <= {r[key] for r in records}:
                raise ValueError(f"unknown {key} filter")
        for index, record in enumerate(records):
            observation = {k: record[k] for k in ("case", "profile", "variant")}
            observation["status"] = "inconclusive"
            report["observations"].append(observation)
            case = next(c for c in matrix["cases"] if c["id"] == record["case"])
            observation["split"] = case["split"]
            print(f"{index + 1}/{len(records)}: {record['case']}/{record['profile']}/{record['variant']}", flush=True)
            directory = root / str(index)
            directory.mkdir()
            try:
                if record["status"] != "completed":
                    raise ValueError("matrix cell did not complete")
                binary = Path(record["binary"]).resolve(strict=True)
                reference = case["variants"][0]
                if file_hash(binary) != record["binary_sha256"] or file_hash(reference["path"]) != reference["sha256"]:
                    raise ValueError("binary or reference changed since matrix validation")
                observation.update(binary_sha256=record["binary_sha256"], reference_sha256=reference["sha256"])
                frozen, frozen_hash = scoring_reference(matrix, record)
                observation.update(reference_preprocessed_path=str(frozen), reference_preprocessed_sha256=frozen_hash)
                project = directory / "project"
                project.mkdir()
                run_headless(report, [headless, project, "audit", "-import", binary, "-deleteProject", "-max-cpu", "2",
                         "-analysisTimeoutPerFile", args.analysis_seconds,
                         "-scriptPath", ROOT / "tools/ghidra", "-postScript", "ExportCSRD.java",
                         case["function"], case["arity"], args.decompile_seconds, directory],
                        timeout=args.process_seconds)
                export_path = directory / "export.json"
                export = json.loads(export_path.read_text())
                observation["export"] = {"path": str(export_path), "sha256": file_hash(export_path),
                                         "status": export["status"], "ghidra_version": export["ghidra_version"]}
                if export["status"] != "decompiled":
                    observation["status"] = export["status"]
                    continue
                observation["decompiled_c_sha256"] = file_hash(directory / "decompiled.c")
                recovered = directory / "recovered.c"
                observation["reconstruction"] = {}
                recovered.write_text(reconstruct(export, metrics=observation["reconstruction"]))
                observation["recovered_c_sha256"] = file_hash(recovered)
                proof = verify(command, csrd, frozen, recovered, directory / "verification.json", args.timeout_ms)
                observation["verification"] = proof
                observation["status"] = {"proved-under-model": "recovered-under-source-model",
                                         "counterexample": "counterexample"}.get(proof["verification"], "inconclusive")
                # Fixed corruption control: same generated graph, offset the result by one.
                mutated = directory / "mutant.c"
                mutated.write_text(reconstruct(export, result_offset=1))
                control = verify(command, csrd, recovered, mutated, directory / "negative-control.json", args.timeout_ms)
                observation["negative_control"] = control
                if control["verification"] != "counterexample":
                    raise ValueError("corruption control was not rejected by the scorer")
                if file_hash(binary) != record["binary_sha256"] or file_hash(reference["path"]) != reference["sha256"]:
                    raise ValueError("binary or reference changed during observation")
                if file_hash(frozen) != frozen_hash:
                    raise ValueError("original preprocessed input changed during observation")
            except Unsupported as error:
                observation.update(status="unsupported-reconstruction", reason=str(error))
            except (AuditError, OSError, ValueError, KeyError, IndexError) as error:
                timeout = report["commands"] and report["commands"][-1].get("status") == "timeout"
                observation.update(status="timeout" if timeout else "error", reason=str(error))
            finally:
                observation["artifacts"] = [{"path": str(p), "sha256": file_hash(p)}
                                             for p in sorted(directory.glob("*")) if p.is_file()]
                write_json(root / "decompiler.json", report)
        if file_hash(matrix_path) != report["matrix"]["sha256"]:
            raise ValueError("matrix changed during observation")
        if any(file_hash(p) != report["implementation"][str(p.relative_to(ROOT))] for p in implementation):
            raise ValueError("observer implementation changed during experiment")
        if file_hash(csrd) != report["tools"]["csrd"]["sha256"]:
            raise ValueError("scoring verifier changed during experiment")
        counts = dict(Counter(o["status"] for o in report["observations"]))
        report["summary"] = counts
        report["status"] = "failed" if counts.get("error") else "completed"
    except (AuditError, OSError, ValueError, KeyError) as error:
        report.update(status="failed", error=str(error))
    finally:
        write_json(root / "decompiler.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--matrix-report", required=True)
    parser.add_argument("--headless", default="analyzeHeadless")
    parser.add_argument("--csrd", default="build/csrd")
    for option in ("case", "profile", "variant"):
        parser.add_argument("--" + option, action="append")
    parser.add_argument("--analysis-seconds", type=int, default=30)
    parser.add_argument("--decompile-seconds", type=int, default=15)
    parser.add_argument("--process-seconds", type=int, default=120)
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if not all(1 <= getattr(args, name) <= 600 for name in ("analysis_seconds", "decompile_seconds", "process_seconds")) or not 1 <= args.timeout_ms <= 600000:
        parser.error("invalid timeout budget")
    root = Path(args.output_dir).resolve()
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"new output directory required: {error}")
    result = run(args, root)
    print(f"{result['status']}: {root / 'decompiler.json'}")
    return 2 if result["status"] == "unavailable" else int(result["status"] == "failed")


if __name__ == "__main__":
    sys.exit(main())
