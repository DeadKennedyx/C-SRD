#!/usr/bin/env python3
"""Execute saved reconstructed byte-buffer answers against independent effects.

This is held-out grading, not observer work or additional observer queries.
Source-model proofs remain separate from this finite machine-code check.
"""
import argparse
from collections import Counter
import fcntl
import hashlib
import json
from pathlib import Path
import random
import subprocess

from audit_protection import Runner, file_hash, write_json
from byte_observation_cases import cases, driver, expected, LAYOUTS
from effort_resources import environment, measurement_lock
from pcode_memory import reconstruct

ROOT = Path(__file__).resolve().parents[1]


def batch_driver(function, parameters, corpus="byte"):
    # Rename our own generated entry point, leaving recovered C untouched.
    from call_observation_cases import driver as call_driver
    from record_observation_cases import driver as record_driver
    from control_observation_cases import driver as control_driver
    from heap_observation_cases import driver as heap_driver
    from dispatch_observation_cases import driver as dispatch_driver
    return "#define main csrd_one_case\n" + (dispatch_driver if corpus=='dispatch' else heap_driver if corpus=='heap' else control_driver if corpus=='control' else record_driver if corpus=="record" else call_driver if corpus=="call" else driver)(function, parameters) + r'''
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
    if replay["status"] not in ("completed","completed-with-gaps") or file_hash(matrix_path) != replay["input_sha256"]:
        raise ValueError("requires unchanged, finished observer replay without correctness/control failures")
    rng = random.Random(args.seed)
    from call_observation_cases import expected as call_expected, LAYOUTS as call_layouts
    from record_observation_cases import expected as record_expected, LAYOUTS as record_layouts
    from control_observation_cases import cases as control_cases,expected as control_expected,LAYOUTS as control_layouts
    from heap_observation_cases import cases as heap_cases,expected as heap_expected,LAYOUTS as heap_layouts
    from dispatch_observation_cases import cases as dispatch_cases,expected as dispatch_expected,LAYOUTS as dispatch_layouts
    layouts=dispatch_layouts if args.corpus=='dispatch' else heap_layouts if args.corpus=='heap' else control_layouts if args.corpus=='control' else record_layouts if args.corpus=="record" else call_layouts if args.corpus=="call" else LAYOUTS
    vectors = (dispatch_cases() if args.corpus=='dispatch' else heap_cases() if args.corpus=='heap' else control_cases() if args.corpus=='control' else cases()) + [{"x": rng.getrandbits(32), "memory": [rng.getrandbits(32) for _ in range(64)]}
                         for _ in range(args.random_cases)]
    if args.corpus=='dispatch':
        for i,v in enumerate(vectors[24:]):
            if i%2:v['x']=i%10  # Exercise recursive bodies as well as full uint32 inputs.
    report = {"schema_version": 1, "status": "running", "commands": [], "records": [],
              "reference_checks": [], "skipped_observations":[], "source_model_outcomes":{}, "environment": environment(), "seed": args.seed, "corpus":args.corpus,
              "replay_report": str(path), "replay_sha256": file_hash(path),
              "matrix_sha256": file_hash(matrix_path),
              "heap_observation":replay.get('heap_observation','events'),
              "recursion_observation":replay.get('recursion_observation','events'),
              "implementation_hashes": {name: file_hash(ROOT/name) for name in
                  ("tools/grade_byte_reconstruction.py", "tools/byte_observation_cases.py",
                   "tools/call_observation_cases.py", "tests/fixtures/call_environment.h",
                   "tools/record_observation_cases.py","tests/fixtures/records.h","tools/control_observation_cases.py","tools/heap_observation_cases.py",
                   "tools/buffer_observation_cases.py","tools/pcode_memory.py","tools/pcode_memory_cfg.py",
                   "tools/pcode_values.py","tools/pcode_wide.py","tools/pcode_cfg.py")},
              "cases_per_answer": len(vectors)*len(layouts), "observer_target_queries": 0,
              "scope": "finite return and whole shared-memory execution grading; not a proof of lifting or C compilers"}
    if args.corpus=='dispatch':
        for p in ('tools/dispatch_observation_cases.py','tests/fixtures/dispatch_environment.h'):
            report['implementation_hashes'][p]=file_hash(ROOT/p)
    command = Runner(report)
    artifacts = {path: report["replay_sha256"], matrix_path: report["matrix_sha256"]}
    for name, digest in report["implementation_hashes"].items(): artifacts[ROOT/name] = digest
    def bind(file, digest):
        file = Path(file)
        if file_hash(file) != digest: raise ValueError(f"changed artifact: {file}")
        artifacts[file] = digest
    def execute(binary, inputs, wanted, negative=False):
        result = subprocess.run([binary], input=inputs, text=True, capture_output=True, timeout=30)
        values = list(map(int, result.stdout.split()))
        if result.returncode:raise ValueError(f"compiled grading process failed: {binary}; {result.returncode}; {result.stderr[:300]}")
        if negative:
            if values==wanted:raise ValueError(f"negative control was not rejected by execution: {binary}")
            # A guarded callback mutation can change the number of executed
            # events, hence the output length. That is a valid trace mismatch.
            mismatch=next((i for i,(a,b) in enumerate(zip(values,wanted)) if a!=b),min(len(values),len(wanted)))
            return {'status':'counterexample-by-execution','first_difference':mismatch,
                    'expected':wanted[mismatch] if mismatch<len(wanted) else None,
                    'actual':values[mismatch] if mismatch<len(values) else None,
                    'expected_values':len(wanted),'actual_values':len(values),
                    'output_sha256':hashlib.sha256(result.stdout.encode()).hexdigest()}
        if values != wanted:
            mismatch = next((i for i, (a, b) in enumerate(zip(values, wanted)) if a != b), min(len(values), len(wanted)))
            raise ValueError(f"compiled answer mismatch: {binary}; status={result.returncode}; value={mismatch}; {result.stderr[:300]}")
        return hashlib.sha256(result.stdout.encode()).hexdigest()
    try:
        seen = set()
        corpus = {}
        proof_counts=Counter()
        for row in replay["records"]:
            if row['status'] in ('false-reconstruction','control-failure'):raise ValueError('known reconstruction/control failure')
            if not row.get('recovered_path'):
                report['skipped_observations'].append({k:row[k] for k in ('function','profile','variant','status')});continue
            if row['status'] not in ('recovered-under-source-model','recovered-under-successful-allocations','recovered-under-bounded-recursion','inconclusive-grading','control-inconclusive'):
                raise ValueError('ungraded replay answer')
            group = matrix["groups"][row["group"]]
            key = (group["reference_sha256"], row["recovered_sha256"], row["function"])
            if key in seen: continue
            seen.add(key)
            proof_counts[row['verification']]+=1
            bind(row["recovered_path"], row["recovered_sha256"])
            bind(group["reference"], group["reference_sha256"])
            folder = root/str(len(seen)-1); folder.mkdir()
            harness = folder/"driver.c"; harness.write_text(batch_driver(row["function"], group["parameters"],args.corpus))
            bind(harness, file_hash(harness))
            support=[]
            if args.corpus=="record":
                from record_observation_cases import HEADER
                state=folder/"state.c"
                state.write_text(HEADER.read_text()+"\nuint32_t csrd_counter;struct csrd_pair csrd_state;union csrd_word csrd_mode;\n")
                bind(state,file_hash(state));support=[state]
            if row["group"] not in corpus:
                inputs, wanted = [], []
                for p, q in layouts:
                    for vector in vectors:
                        answer = (dispatch_expected if args.corpus=='dispatch' else heap_expected if args.corpus=='heap' else control_expected if args.corpus=='control' else record_expected if args.corpus=="record" else call_expected if args.corpus=="call" else expected)(row["function"], vector["memory"], p, q, vector["x"],
                                          plain_char_signed=group["parameters"][0].get("element_signed",False))
                        inputs.append(" ".join(map(str, [p, q, vector["x"], *vector["memory"]])))
                        wanted.extend([answer["return_value"], *answer["final_memory"]])
                        if args.corpus in ("call","dispatch"):
                            wanted.extend([answer["external_state"],len(answer["events"])])
                            wanted.extend(v for event in answer["events"] for v in event)
                        if args.corpus=="record":wanted.extend(answer["persistent_state"])
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
            controls={}
            export=json.loads(Path(row['export_path']).read_text());bind(row['export_path'],row['export_sha256'])
            mutations={'return-plus-one':{'result_offset':1},'last-store-plus-one':{'final_store_offset':1},
                       'call-argument-plus-one':{'call_argument_offset':1}}
            for label in row['controls']:
                if label not in mutations:raise ValueError('unknown reconstruction mutation')
                wrong=Path(row['proof_path']).parent/(label+'.c')
                if reconstruct(export,**mutations[label])!=wrong.read_text():raise ValueError('saved corruption control changed')
                bind(wrong,file_hash(wrong));controls[label]=wrong
            for name in ("clang", "gcc"):
                compiler = matrix["tools"][name]
                bind(compiler["path"], compiler["sha256"])
                binary = folder/name
                command([compiler["path"], "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                         harness, row["recovered_path"], *support, "-o", binary])
                digest = execute(binary, inputs, wanted)
                bind(binary, file_hash(binary))
                checked_controls={}
                for label,wrong in controls.items():
                    control_binary=folder/(name+'-'+label)
                    command([compiler['path'],'-std=c11','-O2','-Wall','-Wextra','-Werror',harness,wrong,*support,'-o',control_binary])
                    bind(control_binary,file_hash(control_binary))
                    checked_controls[label]={**execute(control_binary,inputs,wanted,negative=True),
                        'source_sha256':artifacts[wrong],'binary_sha256':artifacts[control_binary]}
                report["records"].append({"function": row["function"], "group": row["group"],
                    "answer": row["recovered_path"], "answer_sha256": row["recovered_sha256"],
                    "compiler": name, "compiler_sha256": compiler["sha256"], "binary_sha256": artifacts[binary],
                    "input_sha256": hashlib.sha256(inputs.encode()).hexdigest(), "output_sha256": digest,
                    "cases": report["cases_per_answer"], "status": "passed",
                    "source_verification":row['verification'],"source_controls":row['controls'],"execution_controls":checked_controls})
            if len(seen)%8 == 0: print(f"compiled {len(seen)} distinct answers", flush=True)
        for file, digest in artifacts.items():
            if file_hash(file) != digest: raise ValueError(f"artifact changed during grading: {file}")
        report.update(status="completed", distinct_answers=len(seen),
                      source_model_outcomes=dict(proof_counts),
                      grader_reference_executions=len(corpus)*report["cases_per_answer"],
                      answer_executions=sum(r["cases"] for r in report["records"]),
                      control_executions=sum(r['cases']*len(r['execution_controls']) for r in report['records']))
    except Exception as error:
        report.update(status="failed", error=str(error)); raise
    finally: write_json(root/"grading.json", report)
    print(report["status"], report["distinct_answers"], report["answer_executions"], flush=True)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--replay-report", required=True); p.add_argument("--output-dir", required=True)
    p.add_argument("--corpus",choices=("byte","call","record","control","heap","dispatch"),default="byte")
    p.add_argument("--random-cases", type=int, default=256); p.add_argument("--seed", type=int, default=20261113)
    args = p.parse_args()
    if args.random_cases < 1: p.error("positive random case count required")
    root = Path(args.output_dir).resolve(); root.mkdir(parents=True, exist_ok=False)
    with measurement_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB); run(args, root)
