#!/usr/bin/env python3
"""Execute saved reconstructed byte-buffer answers against independent effects.

This is held-out grading, not observer work or additional observer queries.
Source-model proofs remain separate from this finite machine-code check.
"""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import random
import subprocess

from audit_protection import Runner, file_hash, write_json
from byte_observation_cases import cases, driver, expected, LAYOUTS
from effort_resources import environment, measurement_lock

ROOT = Path(__file__).resolve().parents[1]


def batch_driver(function, parameters, corpus="byte"):
    # Rename our own generated entry point, leaving recovered C untouched.
    from call_observation_cases import driver as call_driver
    return "#define main csrd_one_case\n" + (call_driver if corpus=="call" else driver)(function, parameters) + r'''
#undef main
#include <ctype.h>
int main(void) {
 int c;
 while ((c = getchar()) != EOF) {
  if (isspace((unsigned char)c)) continue;
  if (ungetc(c, stdin) == EOF) return 4;
  int status = csrd_one_case();
  if (status) return status;
 }
 return ferror(stdin) ? 5 : 0;
}
'''


def run(args, root):
    path = Path(args.replay_report).resolve()
    replay = json.loads(path.read_text())
    matrix_path = Path(replay["input_report"])
    matrix = json.loads(matrix_path.read_text())
    if replay["status"] != "completed" or file_hash(matrix_path) != replay["input_sha256"]:
        raise ValueError("requires unchanged, completed observer replay")
    rng = random.Random(args.seed)
    from call_observation_cases import expected as call_expected, LAYOUTS as call_layouts
    layouts=call_layouts if args.corpus=="call" else LAYOUTS
    vectors = cases() + [{"x": rng.getrandbits(32), "memory": [rng.getrandbits(32) for _ in range(64)]}
                         for _ in range(args.random_cases)]
    report = {"schema_version": 1, "status": "running", "commands": [], "records": [],
              "reference_checks": [], "environment": environment(), "seed": args.seed, "corpus":args.corpus,
              "replay_report": str(path), "replay_sha256": file_hash(path),
              "matrix_sha256": file_hash(matrix_path),
              "implementation_hashes": {name: file_hash(ROOT/name) for name in
                  ("tools/grade_byte_reconstruction.py", "tools/byte_observation_cases.py",
                   "tools/call_observation_cases.py", "tests/fixtures/call_environment.h")},
              "cases_per_answer": len(vectors)*len(layouts), "observer_target_queries": 0,
              "scope": "finite return and whole shared-memory execution grading; not a proof of lifting or C compilers"}
    command = Runner(report)
    artifacts = {path: report["replay_sha256"], matrix_path: report["matrix_sha256"]}
    for name, digest in report["implementation_hashes"].items(): artifacts[ROOT/name] = digest
    def bind(file, digest):
        file = Path(file)
        if file_hash(file) != digest: raise ValueError(f"changed artifact: {file}")
        artifacts[file] = digest
    def execute(binary, inputs, wanted):
        result = subprocess.run([binary], input=inputs, text=True, capture_output=True, timeout=30)
        values = list(map(int, result.stdout.split()))
        if result.returncode or values != wanted:
            mismatch = next((i for i, (a, b) in enumerate(zip(values, wanted)) if a != b), min(len(values), len(wanted)))
            raise ValueError(f"compiled answer mismatch: {binary}; status={result.returncode}; value={mismatch}; {result.stderr[:300]}")
        return hashlib.sha256(result.stdout.encode()).hexdigest()
    try:
        seen = set()
        corpus = {}
        for row in replay["records"]:
            if row["status"] != "recovered-under-source-model": raise ValueError("ungraded replay answer")
            group = matrix["groups"][row["group"]]
            key = (group["reference_sha256"], row["recovered_sha256"], row["function"])
            if key in seen: continue
            seen.add(key)
            bind(row["recovered_path"], row["recovered_sha256"])
            bind(group["reference"], group["reference_sha256"])
            folder = root/str(len(seen)-1); folder.mkdir()
            harness = folder/"driver.c"; harness.write_text(batch_driver(row["function"], group["parameters"],args.corpus))
            bind(harness, file_hash(harness))
            if row["group"] not in corpus:
                inputs, wanted = [], []
                for p, q in layouts:
                    for vector in vectors:
                        answer = (call_expected if args.corpus=="call" else expected)(row["function"], vector["memory"], p, q, vector["x"],
                                          plain_char_signed=group["parameters"][0].get("element_signed",False))
                        inputs.append(" ".join(map(str, [p, q, vector["x"], *vector["memory"]])))
                        wanted.extend([answer["return_value"], *answer["final_memory"]])
                        if args.corpus=="call":
                            wanted.extend([answer["external_state"],len(answer["events"])])
                            wanted.extend(v for event in answer["events"] for v in event)
                inputs = "\n".join(inputs)+"\n"
                corpus[row["group"]] = inputs, wanted
                reference = next(v for v in group["variants"] if v["variant"] == "original")
                bind(reference["binary"], reference["binary_sha256"])
                compiler = matrix["tools"]["clang"]
                bind(compiler["path"], compiler["sha256"])
                command([compiler["path"], "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                         harness, reference["binary"], "-o", folder/"reference"])
                digest = execute(folder/"reference", inputs, wanted)
                report["reference_checks"].append({"group": row["group"], "output_sha256": digest,
                                                    "binary_sha256": reference["binary_sha256"]})
            inputs, wanted = corpus[row["group"]]
            for name in ("clang", "gcc"):
                compiler = matrix["tools"][name]
                bind(compiler["path"], compiler["sha256"])
                binary = folder/name
                command([compiler["path"], "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                         harness, row["recovered_path"], "-o", binary])
                digest = execute(binary, inputs, wanted)
                bind(binary, file_hash(binary))
                report["records"].append({"function": row["function"], "group": row["group"],
                    "answer": row["recovered_path"], "answer_sha256": row["recovered_sha256"],
                    "compiler": name, "compiler_sha256": compiler["sha256"], "binary_sha256": artifacts[binary],
                    "input_sha256": hashlib.sha256(inputs.encode()).hexdigest(), "output_sha256": digest,
                    "cases": report["cases_per_answer"], "status": "passed"})
            if len(seen)%8 == 0: print(f"compiled {len(seen)} distinct answers", flush=True)
        for file, digest in artifacts.items():
            if file_hash(file) != digest: raise ValueError(f"artifact changed during grading: {file}")
        report.update(status="completed", distinct_answers=len(seen),
                      grader_reference_executions=len(corpus)*report["cases_per_answer"],
                      answer_executions=sum(r["cases"] for r in report["records"]))
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally: write_json(root/"grading.json", report)
    print(report["status"], report["distinct_answers"], report["answer_executions"], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--replay-report", required=True); p.add_argument("--output-dir", required=True)
    p.add_argument("--corpus",choices=("byte","call"),default="byte")
    p.add_argument("--random-cases", type=int, default=256); p.add_argument("--seed", type=int, default=20261113)
    args = p.parse_args()
    if args.random_cases < 1: p.error("positive random case count required")
    root = Path(args.output_dir).resolve(); root.mkdir(parents=True, exist_ok=False)
    with measurement_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); run(args, root)
