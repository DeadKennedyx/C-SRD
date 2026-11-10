#!/usr/bin/env python3
"""Independent C-level comparison for one declared, finite buffer layout."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check(args):
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "status": "not-verified", "function": args.function,
              "words": args.words, "pointer_offsets": args.offsets, "timeout_seconds": args.timeout,
              "adapter_sha256": digest(Path(__file__)), "solver": args.solver,
              "scope": "One finite shared-object layout; all initial uint32 values and scalar arguments. Not arbitrary C or all pointer layouts."}
    try:
        cbmc = shutil.which(args.cbmc)
        if not cbmc:
            report["status"] = "unavailable"
            raise RuntimeError("CBMC executable not found")
        report["cbmc"] = {"path": cbmc, "sha256": digest(Path(cbmc)),
                          "version": subprocess.check_output([cbmc, "--version"], text=True).strip()}
        paths = [Path(args.original).resolve(strict=True), Path(args.candidate).resolve(strict=True)]
        analyses = []
        for label, path in zip(("original", "candidate"), paths):
            run = subprocess.run([args.csrd, "analyze", str(path)], text=True, capture_output=True, timeout=30)
            if run.returncode:
                raise RuntimeError(run.stderr)
            data = json.loads(run.stdout)
            (root / f"{label}-analysis.json").write_text(json.dumps(data, indent=2) + "\n")
            function = next((f for f in data["functions"] if f["function"] == args.function), None)
            if not function or function["status"] != "supported" or function.get("semantic_model") != "buffers-u32-c11-v1":
                raise ValueError("select a supported buffers-u32-c11-v1 function")
            analyses.append((data, function))
            (root / f"{label}-snapshot.c").write_bytes(path.read_bytes())
        left, right = (a[1] for a in analyses)
        if analyses[0][0]["target"] != analyses[1][0]["target"]:
            raise ValueError("target mismatch")
        if len(left["parameters"]) != len(right["parameters"]):
            raise ValueError("parameter arity mismatch")
        for a, b in zip(left["parameters"], right["parameters"]):
            if (a["kind"], a.get("read_only")) != (b["kind"], b.get("read_only")):
                raise ValueError("parameter kind or constness mismatch")
            if b.get("minimum_elements", 0) > a.get("minimum_elements", 0):
                raise ValueError("candidate exceeds original buffer footprint")
        buffers = [p for p in left["parameters"] if p["kind"] == "uint32-buffer"]
        if len(args.offsets) != len(buffers):
            raise ValueError("provide one offset per pointer parameter")
        if any(offset < 0 or offset + p["minimum_elements"] > args.words
               for offset, p in zip(args.offsets, buffers)):
            raise ValueError("layout does not satisfy the original buffer contract")
        wrappers = []
        for label, path, (data, _) in zip(("original", "candidate"), paths, analyses):
            wrapper = root / f"{label}-wrapper.c"
            definitions = "\n".join(f"#define {f['function']} csrd_{label}_{f['function']}" for f in data["functions"])
            wrapper.write_text(definitions + "\n#include " + json.dumps(str(path)) + "\n")
            wrappers.append(str(wrapper))
        types, original_args, candidate_args, declarations = [], [], [], []
        pointer = 0
        for index, p in enumerate(left["parameters"]):
            if p["kind"] == "uint32":
                types.append("uint32_t")
                name = f"scalar_{index}"
                declarations.append(f"uint32_t {name}=nondet_csrd_u32();")
                original_args.append(name); candidate_args.append(name)
            else:
                types.append(("const " if p["read_only"] else "") + "uint32_t*")
                offset = args.offsets[pointer]; pointer += 1
                original_args.append(f"a+{offset}"); candidate_args.append(f"b+{offset}")
        harness = root / "harness.c"
        harness.write_text("#include <stdint.h>\n"
            "_Static_assert(sizeof(unsigned int)*8==32,\"u32 model\");\n"
            "_Static_assert(_Generic((uint32_t)0,unsigned int:1,default:0),\"uint32 type\");\n"
            "extern uint32_t nondet_csrd_u32(void);\n" +
            "\n".join(f"uint32_t csrd_{label}_{args.function}({','.join(types)});" for label in ("original", "candidate")) +
            f"\nint main(void){{uint32_t a[{args.words}],b[{args.words}];\n" +
            "\n".join(f"a[{i}]=nondet_csrd_u32();b[{i}]=a[{i}];" for i in range(args.words)) +
            "\n" + "\n".join(declarations) +
            f"\nuint32_t original_result=csrd_original_{args.function}({','.join(original_args)});\n" +
            f"uint32_t candidate_result=csrd_candidate_{args.function}({','.join(candidate_args)});\n" +
            '__CPROVER_assert(original_result==candidate_result,"return equality");\n' +
            "\n".join(f'__CPROVER_assert(a[{i}]==b[{i}],"memory cell {i}");' for i in range(args.words)) +
            "\nreturn 0;}\n")
        report["inputs"] = [{"path": str(path), "sha256": digest(path)} for path in paths]
        snapshot = {item["path"]: item["sha256"] for item in report["inputs"]}
        for path, (data, _) in zip(paths, analyses):
            if data["source_sha256"] != snapshot[str(path)]:
                raise RuntimeError("source changed after Clang analysis")
            for dependency in data["dependencies"]:
                if digest(Path(dependency["path"])) != dependency["sha256"]:
                    raise RuntimeError("header changed after Clang analysis")
                snapshot[dependency["path"]] = dependency["sha256"]
        report["analyzed_source_environment"] = snapshot
        command = [cbmc, *wrappers, str(harness), "--c11", "--bounds-check", "--pointer-check",
                   "--pointer-overflow-check", "--signed-overflow-check", "--undefined-shift-check",
                   "--unwind", "2", "--unwinding-assertions", "--trace", "--json-ui"]
        if args.solver == "z3": command.append("--z3")
        report["command"] = command
        process = subprocess.Popen(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        try:
            stdout, stderr = process.communicate(timeout=args.timeout)
            report["exit_code"] = process.returncode
            (root / "cbmc.stdout.json").write_text(stdout)
            (root / "cbmc.stderr.txt").write_text(stderr)
            data = json.loads(stdout)
            status = next((r["cProverStatus"] for r in data if "cProverStatus" in r), None)
            properties = [p for item in data for p in item.get("result", [])]
            report["properties"] = [{k: p[k] for k in ("property", "description", "status") if k in p} for p in properties]
            if process.returncode == 0 and status == "success" and properties and all(p["status"] == "SUCCESS" for p in properties):
                report["status"] = "bounded-checked"
            elif process.returncode == 10 and status == "failure":
                if any(p.get("status") == "FAILURE" and ".no-body." in p.get("property", "") for p in properties):
                    report["status"] = "error"
                    report["reason"] = "CBMC harness has an unresolved function body"
                else:
                    report["status"] = "counterexample"
            else:
                report["status"] = "inconclusive"
        except subprocess.TimeoutExpired:
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            stdout, stderr = process.communicate()
            report["status"] = "inconclusive"
            report["reason"] = "CBMC wall-clock timeout"
        (root / "cbmc.stdout.json").write_text(stdout)
        (root / "cbmc.stderr.txt").write_text(stderr)
        for path, expected in snapshot.items():
            if digest(Path(path)) != expected:
                raise RuntimeError("source/header changed during CBMC check")
        # The adapter does not share C-SRD's symbolic executor; its results
        # remain supplemental, with the selected layout and artifacts retained.
    except (ValueError, RuntimeError, OSError, subprocess.SubprocessError) as error:
        report["reason"] = str(error)
        if report["status"] != "unavailable": report["status"] = "error"
    report["artifacts"] = {p.name: digest(p) for p in root.iterdir() if p.is_file()}
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(report["status"] + (": " + report["reason"] if "reason" in report else ""))
    return 0 if report["status"] == "bounded-checked" else 3


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("original")
    parser.add_argument("candidate")
    parser.add_argument("--csrd", required=True)
    parser.add_argument("--cbmc", default="cbmc")
    parser.add_argument("--function", required=True)
    parser.add_argument("--offsets", type=lambda s: [int(v) for v in s.split(",")], required=True)
    parser.add_argument("--words", type=int, default=32)
    parser.add_argument("--timeout", type=int, default=30)
    parser.add_argument("--solver", choices=("sat", "z3"), default="sat")
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if not 1 <= args.words <= 256 or not 1 <= args.timeout <= 600:
        parser.error("words must be in 1..256 and timeout in 1..600")
    sys.exit(check(args))
