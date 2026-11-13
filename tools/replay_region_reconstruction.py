#!/usr/bin/env python3
"""Re-run the region adapter on frozen, hash-bound Ghidra exports, then grade.

No binaries are rebuilt and Ghidra is not run. Adapter resources are measured
serially before independent grading, including optional sanitizer executions.
"""
import argparse
import fcntl
import json
from pathlib import Path
import random
import shutil
import sys

from audit_protection import file_hash, write_json
from audit_region_observers import checked_artifacts, grade
from effort_resources import environment, measure, measurement_lock

ROOT=Path(__file__).resolve().parents[1]


def run(args):
    source=Path(args.reconstruction).resolve()
    previous=json.loads(source.read_text())
    if previous["status"]!="completed":raise ValueError("requires a completed upstream report")
    manifest=Path(previous["build"]).resolve()
    if file_hash(manifest)!=previous["build_sha256"]:raise ValueError("upstream build manifest changed")
    build=json.loads(manifest.read_text());records={r["id"]:r for r in checked_artifacts(build)}
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=False)
    target=root/"reconstruction.json"
    report={"schema_version":2,"status":"observing","protocol":"frozen-region-adapter-replay-v1",
        "build":str(manifest),"build_sha256":file_hash(manifest),"environment":environment(),"records":[],
        "upstream_report":str(source),"upstream_sha256":file_hash(source),
        "source_repetition":args.source_repetition,
        "decompilation_scope":"not repeated; only the adapter is timed; upstream Ghidra times must not be counted as new repetitions",
        "grading_protocol":{"cases":args.grade_cases,"seed":args.grade_seed,"seed_per_repetition":True,"sanitizers":args.sanitizers},
        "claims":{"whole_function_proof":False,"human_effort":"unmeasured","target_execution_queries_during_reconstruction":0},
        "observer_hashes":{p.name:file_hash(p) for p in [ROOT/"tools/pcode_regions.py",ROOT/"tools/pcode_cfg.py",ROOT/"tools/pcode_values.py",ROOT/"tools/pcode_vector.py"]},
        "grader_hashes":{p.name:file_hash(p) for p in [Path(__file__),ROOT/"tools/audit_region_observers.py",ROOT/"tools/region_observation_cases.py"]}}
    exports=[];seen=set()
    for prior in previous["records"]:
        if prior["repetition"]!=args.source_repetition:continue
        key=(prior["artifact"],prior["function"])
        if key in seen:raise ValueError("source repetition has multiple exports for one task")
        seen.add(key)
        record=records[prior["artifact"]]
        if prior["library_sha256"]!=record["library_sha256"]:raise ValueError("upstream binary binding differs")
        path=Path(prior["directory"])/"export/export.json"
        if "export_sha256" in prior and file_hash(path)!=prior["export_sha256"]:raise ValueError("upstream export changed")
        exports.append((prior,path))
    if not exports:raise ValueError("source repetition selects no observations")
    jobs=[(index,prior,path,repetition) for index,(prior,path) in enumerate(exports) for repetition in range(args.repetitions)]
    random.Random(0x43535244).shuffle(jobs)
    try:
        for serial,(index,prior,path,repetition) in enumerate(jobs):
            directory=root/f"{serial:04d}";directory.mkdir()
            item={"artifact":prior["artifact"],"function":prior["function"],"repetition":repetition,
                  "source_observation":index,"source_repetition":prior["repetition"],"replayed_export":True,
                  "library_sha256":prior["library_sha256"],"directory":str(directory),"status":"observing"}
            report["records"].append(item)
            if "export_sha256" not in prior:
                item.update(status="unavailable-export",upstream_status=prior["status"])
            else:
                exported=directory/"export";exported.mkdir();snapshot=exported/"export.json";shutil.copy2(path,snapshot)
                item["export_sha256"]=file_hash(snapshot)
                if item["export_sha256"]!=prior["export_sha256"]:raise ValueError("export changed during copy")
                item["adapter"]=measure([sys.executable,ROOT/"tools/pcode_regions.py",snapshot,directory/"recovered.c"],directory/"adapter-resources",wall_seconds=30)
                item["adapter"].pop("samples",None)
                metadata=directory/"recovered.c.json"
                if metadata.exists():
                    item["reconstruction"]=json.loads(metadata.read_text());item["status"]=item["reconstruction"]["status"]
                    if item["adapter"]["status"]!="completed" and item["status"]!="unsupported":item["status"]=item["adapter"]["status"]
                else:item["status"]=item["adapter"]["status"] if item["adapter"]["status"]!="completed" else "missing-adapter-result"
                if (directory/"recovered.c").exists():item["recovered_sha256"]=file_hash(directory/"recovered.c")
            write_json(target,report)
            print(f"replayed {serial+1}/{len(jobs)} {item['artifact']} {item['function']}: {item['status']}",flush=True)
        # The adapter receives no source oracle, tests, or grading feedback.
        for item in report["records"]:
            if item["status"]!="reconstructed":continue
            directory=Path(item["directory"]);grading=directory/"grade";grading.mkdir()
            if file_hash(directory/"recovered.c")!=item["recovered_sha256"]:raise ValueError("candidate changed")
            original=records[item["artifact"].rsplit("/",1)[0]+"/original"]
            reference=original["drivers"][item["function"]]["path"]
            seed=(args.grade_seed+item["repetition"]) % 2**64
            item["grading"]=grade(records[item["artifact"]],item["function"],directory/"recovered.c",grading,
                                  args.grade_cases,reference,seed,args.sanitizers)
            item["status"]=item["grading"]["status"]
            write_json(target,report)
        # Repeat corruption controls with the revised adapter; do not relabel
        # the upstream controls as if they had been run by this version.
        from pcode_regions import reconstruct
        report["controls"]=[]
        for item in report["records"]:
            if not item["artifact"].endswith("/clang-O2/original") or item["repetition"]!=0 or item["status"]!="tested-equivalent":continue
            directory=Path(item["directory"]);export=json.loads((directory/"export/export.json").read_text())
            for mutation in ("return","store","call-argument","drop-call","branch"):
                if mutation=="branch" and item["function"]!="region_pipeline":continue
                control=directory/("control-"+mutation);control.mkdir();candidate=control/"mutant.c"
                candidate.write_text(reconstruct(export,mutation=mutation))
                result=grade(records[item["artifact"]],item["function"],candidate,control,args.grade_cases,seed=args.grade_seed)
                report["controls"].append({"artifact":item["artifact"],"function":item["function"],"mutation":mutation,"result":result,"directory":str(control)})
        checked_artifacts(build)
        if file_hash(source)!=report["upstream_sha256"] or file_hash(manifest)!=report["build_sha256"]:raise ValueError("upstream evidence changed")
        for prior,path in exports:
            if "export_sha256" in prior and file_hash(path)!=prior["export_sha256"]:raise ValueError("export changed during replay")
        report["status"]="completed"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(target,report)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--reconstruction",required=True);p.add_argument("--output",required=True)
    p.add_argument("--repetitions",type=int,default=3);p.add_argument("--grade-cases",type=int,default=2048)
    p.add_argument("--source-repetition",type=int,default=0,help="select one upstream export per artifact/function before repeating the adapter")
    p.add_argument("--grade-seed",type=int,default=0x43535245);p.add_argument("--sanitizers",action="store_true")
    args=p.parse_args()
    if args.repetitions<1 or args.source_repetition<0 or not 32<=args.grade_cases<=16384 or not 0<=args.grade_seed<2**64:p.error("positive repetitions, nonnegative source repetition, 32..16384 cases and a uint64 seed required")
    with measurement_lock() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);run(args)
