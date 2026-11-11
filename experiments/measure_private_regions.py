#!/usr/bin/env python3
"""Matched linked-build and application-cost pilot for the private-region fixture.

This does not infer reconstruction resistance from changed bytes or unsupported
observers. It uses the existing matrix catalog and original/copy controls.
"""
import argparse
import fcntl
import json
from pathlib import Path
import random
import shutil
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import Runner, AuditError, executable, file_hash, write_json, MODEL_GUARD
from effort_resources import measure, environment
from evaluate import object_metrics
from experiment_support import assembly_metrics
from run_matrix import flags_for

SYMBOLS = ["main", "region_pipeline", "region_outputs", "record_event", "next_value"]
HARNESS = r'''#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
uint32_t region_pipeline(uint32_t*,uint32_t,int);
int region_outputs(uint32_t*,uint32_t,uint32_t);
static uint32_t memory[3], event_hash;
void record_event(uint32_t v){event_hash=(event_hash*33u)^v;}
uint32_t next_value(uint32_t v){record_event(v);memory[1]+=v;return v+memory[1];}
int main(int argc,char**argv){
 if(argc!=3)return 2;
 unsigned long n=strtoul(argv[1],0,10);uint32_t x=(uint32_t)strtoul(argv[2],0,10),sum=0;
 struct timespec start,end;if(clock_gettime(CLOCK_MONOTONIC,&start))return 2;
 for(unsigned long i=0;i<n;i++){
  x^=x<<13;x^=x>>17;x^=x<<5;
  sum+=region_pipeline(memory,x,(int)(i%10)-1);
  sum+=(uint32_t)region_outputs(memory,x,sum);
 }
 if(clock_gettime(CLOCK_MONOTONIC,&end))return 2;
 double elapsed=(double)(end.tv_sec-start.tv_sec)+(double)(end.tv_nsec-start.tv_nsec)*1e-9;
 printf("%.9f %u %u %u %u %u\n",elapsed,sum,memory[0],memory[1],memory[2],event_hash);return 0;
}
'''


def run(args, root):
    report = {"status": "running", "commands": [], "protocol": vars(args), "environment": environment(),
              "builds": [], "profiles": [], "samples": [], "summaries": [],
              "claims": {"binary_equivalence_proved": False, "protection_advantage_established": False,
                         "reconstruction": "not assessed: existing whole-function observers do not model these calls/loops",
                         "runtime_visibility": "not measured for private-region functions",
                         "application_cost_scope": "entire linked workload including callbacks, deterministic inputs and event hash; process counters include startup"}}
    command = Runner(report)
    try:
        csrd, objdump = executable(args.csrd), executable(args.objdump)
        tools = {"csrd": csrd, "objdump": objdump}
        for item in args.compiler:
            key, value = item.split("=", 1)
            if key not in ("clang", "gcc") or key in tools: raise ValueError("unique clang= and gcc= compilers required")
            tools[key] = executable(value)
        report["tools"] = {key: {"path": value, "sha256": file_hash(value), "version": command([value,"--version"]).splitlines()[0]}
                           for key,value in tools.items()}
        implementation = ["experiments/measure_private_regions.py", "tools/effort_resources.py", "tools/audit_protection.py",
                          "tools/evaluate.py", "tools/experiment_support.py", "tools/run_matrix.py", "experiments/matrix.json"]
        report["implementation"] = {p: file_hash(ROOT/p) for p in implementation}
        source = ROOT / "tests/fixtures" / args.fixture
        report["source"] = {"path": str(source), "sha256": file_hash(source)}
        harness = root / "harness.c"; harness.write_text(HARNESS)
        guard = root / "model-guard.c"; guard.write_text(MODEL_GUARD)
        report["harness_sha256"] = file_hash(harness); report["guard_sha256"] = file_hash(guard)
        catalog = json.loads((ROOT / "experiments/matrix.json").read_text())["profiles"]
        selected = args.profile or [f"{c}-{p}" for c in ("clang", "gcc") for p in ("O0", "O2", "O3", "Os", "O2-lto")]
        if set(selected) - {p["id"] for p in catalog}: raise ValueError("unknown profile")
        for profile in catalog:
            if profile["id"] not in selected: continue
            family = profile["compiler"]
            if family not in tools: raise ValueError("selected compiler unavailable")
            if profile.get("pgo") or profile.get("target") or profile.get("sanitizers"):
                raise ValueError("this application-cost pilot excludes PGO/cross-target/instrumented profiles")
            cc = tools[family]; directory = root / profile["id"]; directory.mkdir()
            flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-"+profile["optimization"], *flags_for(profile, family)]
            probe = directory / "probe.c"; probe.write_text("int main(void){return 0;}\n")
            entry = {"profile": profile, "flags": flags, "status": "available"}; report["profiles"].append(entry)
            try:
                command([cc,*flags,probe,"-o",directory/"probe"]); command([directory/"probe"])
            except AuditError as e:
                entry.update(status="unavailable", reason=str(e)); continue
            original = directory / "original.i"
            original.write_text(command([cc,*flags,"-E","-P",source]))
            variants = {"original": original}
            for strategy in ("identity", "affine"):
                output = directory / (strategy+".i"); proof = directory / (strategy+".json")
                command([csrd,"transform",original,"-o",output,"--scope","private-regions","--strategy",strategy,"--seed","42","--report",proof])
                data = json.loads(proof.read_text())
                if len(data["functions"]) != 2 or any(f["status"] != "regions-transformed" or f["verification"] != "proved-under-model" for f in data["functions"]):
                    raise ValueError("incomplete private-region transformation/validation")
                variants[strategy] = output
            for variant, path in variants.items():
                binary = directory / variant
                command([cc,*flags,"-x","c",guard,path,harness,"-o",binary])
                build_seconds = report["commands"][-1]["elapsed_seconds"]
                assembly = command([objdump,"--disassemble","--no-show-raw-insn",binary])
                (directory / (variant+".asm")).write_text(assembly)
                metrics = object_metrics(objdump, binary, lambda argv:(command(argv),0))
                metrics["scope"] = "entire linked executable text section including harness, helpers and padding"
                record = {"profile": profile["id"], "variant": variant, "source": str(path), "source_sha256": file_hash(path),
                          "binary": str(binary), "binary_sha256": file_hash(binary), "binary_bytes": binary.stat().st_size,
                          "build_seconds": build_seconds, "text": metrics,
                          "assembly": assembly_metrics(assembly,SYMBOLS)}
                report["builds"].append(record)
            baseline = next(b for b in report["builds"] if b["profile"] == profile["id"] and b["variant"] == "original")
            copy = directory / "original-copy"; shutil.copy2(baseline["binary"], copy)
            report["builds"].append({**baseline,"variant":"original-copy","binary":str(copy),"build_seconds":None})

        # All compilation, validation and disassembly precede serialized timings.
        rng = random.Random(args.order_seed)
        for repetition in range(args.repetitions):
            order = list(range(len(report["builds"]))); rng.shuffle(order)
            for bi in order:
                build = report["builds"][bi]; directory = root / f"sample-{len(report['samples'])}"
                if file_hash(build["binary"]) != build["binary_sha256"]: raise ValueError("binary changed")
                resources = measure([build["binary"],str(args.iterations),str(20261110+repetition)],directory,wall_seconds=60)
                if resources["status"] != "completed": raise ValueError("application measurement incomplete")
                values = (directory/"stdout.txt").read_text().split()
                if len(values) != 6 or float(values[0]) <= 0: raise ValueError("invalid workload output")
                report["samples"].append({"build":bi,"repetition":repetition,"application_wall_seconds":float(values[0]),
                                          "outputs":list(map(int,values[1:])),"resources":resources})
        for bi, build in enumerate(report["builds"]):
            base = next(i for i,b in enumerate(report["builds"]) if b["profile"] == build["profile"] and b["variant"] == "original")
            samples = sorted([s for s in report["samples"] if s["build"] == bi],key=lambda x:x["repetition"])
            original = sorted([s for s in report["samples"] if s["build"] == base],key=lambda x:x["repetition"])
            if [s["outputs"] for s in samples] != [s["outputs"] for s in original]: raise ValueError("return/state/event checksum mismatch")
            baseline = report["builds"][base]
            ratios = {"application_wall": [s["application_wall_seconds"]/b["application_wall_seconds"] for s,b in zip(samples,original)]}
            for metric in ("cpu_seconds","peak_sampled_tree_rss_bytes"):
                if all(b["resources"][metric] for b in original): ratios[metric] = [s["resources"][metric]/b["resources"][metric] for s,b in zip(samples,original)]
            report["summaries"].append({"profile":build["profile"],"variant":build["variant"],
                "paired_ratios":{k:{"samples":v,"median":median(v),"min":min(v),"max":max(v)} for k,v in ratios.items()},
                "linked_text_ratio":build["text"]["text_bytes"]/baseline["text"]["text_bytes"],
                "linked_text_identical":build["text"]["text_sha256"] == baseline["text"]["text_sha256"],
                "named_opcode_sequences_identical":build["assembly"]["opcode_sha256"] == baseline["assembly"]["opcode_sha256"]})
        for name, tool in report["tools"].items():
            if file_hash(tool["path"]) != tool["sha256"]: raise ValueError("tool changed: "+name)
        for path, sha in report["implementation"].items():
            if file_hash(ROOT/path) != sha: raise ValueError("implementation changed: "+path)
        if (file_hash(source) != report["source"]["sha256"] or file_hash(harness) != report["harness_sha256"] or
            file_hash(guard) != report["guard_sha256"]): raise ValueError("source/harness/guard changed")
        report["status"] = "completed"
    except Exception as e:
        report.update(status="failed",reason=str(e))
    write_json(root/"measurement.json",report)
    print(report["status"],len(report["builds"]),len(report["samples"]),report.get("reason",""),flush=True)
    return int(report["status"] != "completed")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--csrd",required=True);p.add_argument("--compiler",action="append",required=True)
    p.add_argument("--objdump",default="llvm-objdump");p.add_argument("--profile",action="append")
    p.add_argument("--output-dir",required=True);p.add_argument("--iterations",type=int,default=1000000)
    p.add_argument("--fixture",choices=("private_regions.c","private_declarations.c"),default="private_regions.c")
    p.add_argument("--repetitions",type=int,default=7);p.add_argument("--order-seed",type=int,default=20261110)
    args = p.parse_args()
    if args.iterations < 1 or args.repetitions < 2: p.error("positive iterations and at least two repetitions required")
    root = Path(args.output_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    with (ROOT/"experiments/runs/effort.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return run(args,root)


if __name__ == "__main__": raise SystemExit(main())
