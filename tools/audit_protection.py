#!/usr/bin/env python3
"""Audit compiled representation differences after source equivalence validation.

This measures object code, not resistance to reverse engineering or debugging.
C syntax and eligibility are interpreted only by the Clang-based csrd frontend.
The compiled objects are never executed. No security-product queries are made.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

from evaluate import object_metrics


MODEL_GUARD = '''#include <limits.h>
#include <stdint.h>
_Static_assert(sizeof(int) * CHAR_BIT == 32, "C-SRD requires 32-bit int");
_Static_assert(sizeof(unsigned int) * CHAR_BIT == 32, "C-SRD requires 32-bit unsigned int");
_Static_assert(_Generic((uint32_t)0, unsigned int: 1, default: 0),
               "C-SRD requires uint32_t to be unsigned int");
'''


def file_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2) + "\n")


def executable(value):
    result = shutil.which(value)
    if result is None:
        raise ValueError(f"executable not found: {value}")
    # Preserve driver symlink spelling (clang++/gcc wrappers can select behavior).
    return str(Path(result).absolute())


class AuditError(RuntimeError):
    pass


class Runner:
    def __init__(self, report):
        self.report = report

    def __call__(self, args, timeout=120):
        argv = [str(arg) for arg in args]
        record = {"argv": argv}
        self.report["commands"].append(record)
        start = time.perf_counter()
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            def decoded(value):
                return value.decode(errors="replace") if isinstance(value, bytes) else value or ""
            record.update(returncode=None, stdout=decoded(error.stdout), stderr=decoded(error.stderr),
                          elapsed_seconds=time.perf_counter() - start, status="timeout")
            raise AuditError(f"command timed out: {argv[0]}") from error
        record.update(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr,
                      elapsed_seconds=time.perf_counter() - start, status="completed")
        if result.returncode:
            raise AuditError(f"command failed ({result.returncode}): {' '.join(argv)}\n{result.stderr}")
        return result.stdout


def require_one_function(analysis):
    functions = analysis.get("functions", [])
    if len(functions) != 1 or functions[0].get("status") != "supported":
        raise AuditError("each input must contain exactly one supported pure function")
    return functions[0]


def assert_snapshot(snapshot):
    for path, expected in snapshot.items():
        if file_hash(path) != expected:
            raise AuditError(f"input/header changed during audit: {path}")


def comparison(original, candidate):
    if not original["text_bytes"] or not candidate["text_bytes"]:
        raise AuditError("empty code section: no compiled function was observed")
    identical = original["text_sha256"] == candidate["text_sha256"]
    return {
        "code_section_bytes_identical": identical,
        "observation": "no-code-section-byte-difference" if identical else "code-section-bytes-differ",
        "text_size_ratio": candidate["text_bytes"] / original["text_bytes"],
        "instruction_histograms_identical": original["instruction_histogram"] == candidate["instruction_histogram"],
        "reverse_engineering_effort": "not-assessed",
        "memory_exposure": "not-assessed",
    }


def target_architecture(target):
    arch = target.split("-", 1)[0].lower()
    return {"arm64": "aarch64", "amd64": "x86_64", "i386": "x86", "i486": "x86",
            "i586": "x86", "i686": "x86"}.get(arch, arch)


def target_system(target):
    value = target.lower()
    for system, spellings in [("darwin", ("apple", "darwin", "macos")),
                              ("windows", ("mingw", "windows", "win32")),
                              ("linux", ("linux",)), ("freebsd", ("freebsd",))]:
        if any(spelling in value for spelling in spellings):
            return system
    return value


def run(args, root):
    report = {
        "schema_version": 1,
        "status": "incomplete",
        "platform": platform.platform(),
        "commands": [],
        "configurations": [],
        "claims": {
            "source_equivalence": "not-verified",
            "machine_code_equivalence": "not-proved",
            "reverse_engineering_effort": "not-assessed",
            "memory_exposure": "not-assessed",
            "confidentiality": "not-established",
        },
        "scope": (
            "One admitted pure function per file; native compilers with matching flags. "
            "Compares whole .text/__text object-section bytes, including padding. "
            "Relocations are not applied; other sections, linking and LTO are not compared. "
            "Byte differences and instruction histograms do not establish resistance to analysis. "
            "The compiled objects are not executed; no machine-code equivalence proof or "
            "memory/debugger observation is performed."
        ),
    }
    command = Runner(report)
    try:
        csrd, objdump = executable(args.csrd), executable(args.objdump)
        compilers = [executable(name) for name in args.compiler]
        original, candidate = Path(args.original).resolve(strict=True), Path(args.candidate).resolve(strict=True)
        snapshot = {str(path): file_hash(path) for path in (original, candidate)}
        report["inputs"] = {
            "original": {"path": str(original), "sha256": snapshot[str(original)]},
            "candidate": {"path": str(candidate), "sha256": snapshot[str(candidate)]},
        }
        report["source_bytes_differ"] = snapshot[str(original)] != snapshot[str(candidate)]
        report["tools"] = {
            "csrd": {"path": csrd, "version": command([csrd, "--version"]).splitlines()[0], "sha256": file_hash(csrd)},
            "objdump": {"path": objdump, "version": command([objdump, "--version"]).splitlines()[0], "sha256": file_hash(objdump)},
        }
        analyses = []
        for label, source in (("original", original), ("candidate", candidate)):
            path = root / f"{label}-analysis.json"
            command([csrd, "analyze", source, "--report", path])
            analysis = json.loads(path.read_text())
            require_one_function(analysis)
            if analysis["source_sha256"] != snapshot[str(source)]:
                raise AuditError("analyzed source does not match the input snapshot")
            analyses.append(analysis)
        left, right = (require_one_function(a) for a in analyses)
        if (left["function"], left["parameter_count"]) != (right["function"], right["parameter_count"]):
            raise AuditError("original and candidate must have the same function name and arity")
        if analyses[0]["target"] != analyses[1]["target"] or analyses[0]["dependencies"] != analyses[1]["dependencies"]:
            raise AuditError("analysis target/header environments differ")
        for dependency in analyses[0]["dependencies"]:
            path, sha = dependency["path"], dependency["sha256"]
            if path in snapshot and snapshot[path] != sha:
                raise AuditError("conflicting input/header snapshots")
            snapshot[path] = sha
        assert_snapshot(snapshot)
        report["function"] = left["function"]
        report["parameter_count"] = left["parameter_count"]
        report["analysis_target"] = analyses[0]["target"]
        report["header_snapshot"] = analyses[0]["dependencies"]
        report["source_metrics"] = {"original": left["source_metrics"], "candidate": right["source_metrics"]}
        proof_path = root / "verification.json"
        try:
            command([csrd, "verify", original, candidate, "--report", proof_path,
                     "--timeout-ms", args.timeout_ms], timeout=max(120, args.timeout_ms / 1000 + 30))
        finally:
            # Retain counterexamples and inconclusive statuses even when csrd exits nonzero.
            if proof_path.exists():
                report["verification"] = json.loads(proof_path.read_text())
                statuses = [f["verification"] for f in report["verification"].get("functions", [])]
                if len(statuses) == 1:
                    report["claims"]["source_equivalence"] = statuses[0]
        proof = report["verification"]
        if report["claims"]["source_equivalence"] != "proved-under-model":
            raise AuditError("source equivalence was not established under the supported model")
        if (proof["source_sha256"] != snapshot[str(original)] or
                proof["candidate_sha256"] != snapshot[str(candidate)] or
                proof["target"] != analyses[0]["target"] or
                proof["dependencies"] != analyses[0]["dependencies"] or
                proof["candidate_dependencies"] != analyses[1]["dependencies"]):
            raise AuditError("verification is not bound to the analyzed sources/environment")
        assert_snapshot(snapshot)
        model_guard = root / "model-guard.c"
        model_guard.write_text(MODEL_GUARD)
        report["model_guard_sha256"] = file_hash(model_guard)
        snapshot[str(model_guard)] = report["model_guard_sha256"]
        for index, compiler in enumerate(compilers):
            version = command([compiler, "--version"]).splitlines()[0]
            target = command([compiler, "-dumpmachine"]).strip()
            if (target_architecture(target) != target_architecture(analyses[0]["target"]) or
                    target_system(target) != target_system(analyses[0]["target"])):
                raise AuditError("cross-target compilation is outside this audit's model")
            for optimization in args.optimization or ["O0", "O2"]:
                directory = root / f"compiler-{index}-{optimization}"
                directory.mkdir()
                flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", f"-{optimization}"]
                config = {"compiler": compiler, "compiler_version": version, "compiler_sha256": file_hash(compiler),
                          "compiler_target": target, "flags": flags, "status": "incomplete", "objects": {}}
                report["configurations"].append(config)
                # Compile the data-model checks separately: forcing a header into
                # the tested source could itself change conditional preprocessing.
                command([compiler, *flags, "-c", model_guard, "-o", directory / "model-guard.o"])
                for label, source in (("original", original), ("candidate", candidate)):
                    assert_snapshot(snapshot)
                    obj = directory / f"{label}.o"
                    preprocessed = directory / f"{label}.i"
                    command([compiler, *flags, "-E", "-P", source, "-o", preprocessed])
                    assert_snapshot(snapshot)
                    preprocessed_hash = file_hash(preprocessed)
                    snapshot[str(preprocessed)] = preprocessed_hash
                    preprocessed_analysis = directory / f"{label}-preprocessed-analysis.json"
                    command([csrd, "analyze", preprocessed, "--report", preprocessed_analysis])
                    frozen_analysis = json.loads(preprocessed_analysis.read_text())
                    frozen_function = require_one_function(frozen_analysis)
                    if frozen_analysis["source_sha256"] != preprocessed_hash:
                        raise AuditError("preprocessed analysis changed the frozen input")
                    if (frozen_function["function"], frozen_function["parameter_count"]) != (left["function"], left["parameter_count"]):
                        raise AuditError("preprocessing changed the admitted function interface")
                    frozen_proof_path = directory / f"{label}-build-verification.json"
                    binding = {"preprocessed_path": str(preprocessed.relative_to(root)),
                               "preprocessed_sha256": preprocessed_hash,
                               "verification": "not-verified"}
                    config.setdefault("build_validation", {})[label] = binding
                    try:
                        command([csrd, "verify", source, preprocessed, "--report", frozen_proof_path,
                                 "--timeout-ms", args.timeout_ms], timeout=max(120, args.timeout_ms / 1000 + 30))
                    finally:
                        if frozen_proof_path.exists():
                            frozen_proof = json.loads(frozen_proof_path.read_text())
                            binding["proof"] = frozen_proof
                            statuses = [f["verification"] for f in frozen_proof.get("functions", [])]
                            if len(statuses) == 1:
                                binding["verification"] = statuses[0]
                    if (binding["verification"] != "proved-under-model" or
                            frozen_proof["source_sha256"] != snapshot[str(source)] or
                            frozen_proof["candidate_sha256"] != preprocessed_hash or
                            frozen_proof["dependencies"] != analyses[0]["dependencies"] or
                            frozen_proof["candidate_dependencies"] or
                            frozen_proof["target"] != analyses[0]["target"]):
                        raise AuditError("build input was not validated against the source snapshot")
                    assert_snapshot(snapshot)
                    # .i selects already-preprocessed C in Clang/GCC. This binds
                    # the compiled function to the concrete build's checked input.
                    command([compiler, *flags, "-c", preprocessed, "-o", obj])
                    assert_snapshot(snapshot)
                    # Shared extractor parses object-tool output, never C source text.
                    metrics = object_metrics(objdump, obj, lambda argv: (command(argv), 0.0))
                    if metrics["text_bytes"] == 0:
                        raise AuditError("empty code section: no compiled function was observed")
                    assembly = command([objdump, "--disassemble", "--no-show-raw-insn", obj])
                    relocations = command([objdump, "--reloc", obj])
                    (directory / f"{label}.asm").write_text(assembly)
                    (directory / f"{label}.relocations.txt").write_text(relocations)
                    config["objects"][label] = {"path": str(obj.relative_to(root)),
                                                "object_sha256": file_hash(obj), **metrics}
                config.update(comparison(config["objects"]["original"], config["objects"]["candidate"]))
                config["status"] = "completed"
        assert_snapshot(snapshot)
        report["summary"] = {
            "configurations": len(report["configurations"]),
            "identical_code_sections": sum(c["code_section_bytes_identical"] for c in report["configurations"]),
            "different_code_sections": sum(not c["code_section_bytes_identical"] for c in report["configurations"]),
        }
        report["status"] = "completed"
    except (AuditError, OSError, ValueError, KeyError, RuntimeError, subprocess.SubprocessError) as error:
        report["status"] = "failed"
        report["error"] = str(error)
    finally:
        write_json(root / "audit.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original")
    parser.add_argument("candidate")
    parser.add_argument("--csrd", default="build/csrd")
    parser.add_argument("--compiler", action="append", required=True)
    parser.add_argument("--objdump", required=True, help="llvm-objdump executable")
    parser.add_argument("--optimization", action="append", choices=["O0", "O1", "O2", "O3", "Os"])
    parser.add_argument("--timeout-ms", type=int, default=10000)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if not 1 <= args.timeout_ms <= 600000:
        parser.error("--timeout-ms must be 1..600000")
    if args.optimization and len(args.optimization) != len(set(args.optimization)):
        parser.error("repeated optimization setting")
    root = Path(args.output_dir).resolve()
    try:
        root.mkdir(parents=True, exist_ok=False)
    except OSError as error:
        parser.error(f"a new output directory is required: {error}")
    report = run(args, root)
    if report["status"] != "completed":
        print(f"Audit failed: {report['error']}\nEvidence: {root / 'audit.json'}", file=sys.stderr)
        return 1
    summary = report["summary"]
    print(f"Source equivalence: proved-under-model. Code sections: "
          f"{summary['identical_code_sections']} identical, {summary['different_code_sections']} different.\n"
          f"Reconstruction effort and memory exposure: not assessed.\nEvidence: {root / 'audit.json'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
