#!/usr/bin/env python3
"""Measure a revised adapter against hash-bound saved Ghidra buffer exports.

Ghidra is not rerun. Its prior resource measurements remain in the input report.
Only adapter process/algorithm costs are new; source grading follows observation.
"""
import argparse
from collections import Counter
import fcntl
import json
from pathlib import Path
import random
import sys

from audit_protection import Runner, file_hash, write_json, executable
from audit_buffer_reconstruction import grade
from effort_resources import measure, measurement_lock, environment
from pcode_memory import reconstruct

ROOT=Path(__file__).resolve().parents[1]
FILES=("tools/replay_buffer_observers.py","tools/pcode_memory.py","tools/pcode_memory_cfg.py",
       "tools/pcode_values.py","tools/pcode_wide.py","tools/pcode_cfg.py","tools/effort_resources.py",
       "tools/audit_buffer_reconstruction.py","tools/audit_protection.py")


def run(args,root):
    path=Path(args.reconstruction_report).resolve();previous=json.loads(path.read_text())
    if previous["status"] not in ("completed","completed-with-gaps") and not (previous["status"]=="failed" and "outcomes" in previous):
        raise ValueError("requires finished reconstruction/grading report")
    tool=executable(args.csrd)
    contracts=previous.get("call_contracts")
    if contracts and file_hash(contracts["path"])!=contracts["sha256"]:raise ValueError("call contracts changed")
    contract_path=contracts["path"] if contracts else None
    heap_observation=getattr(args,'heap_observation','events')
    report={"schema_version":1,"status":"running","environment":environment(),"commands":[],"records":[],
        "control_reference":"original-source",
        "heap_observation":heap_observation,
        "input_report":str(path),"input_sha256":file_hash(path),"csrd":tool,"csrd_sha256":file_hash(tool),
        "prior_status":previous["status"],"prior_outcomes":previous["outcomes"],
        "adapter_hashes":{f:file_hash(ROOT/f) for f in FILES},"repetitions":args.repetitions,
        "scope":"same saved binary-only exports; new adapter costs; prior Ghidra costs are not rerun; mutations graded against original source; no proof of binary lifting"}
    command=Runner(report)
    try:
        eligible=[r for r in previous["observations"] if r.get("export_path") and
                  json.loads(Path(r["export_path"]).read_text()).get("status")=="decompiled"]
        jobs=[(rep,r) for rep in range(args.repetitions) for r in eligible]
        random.Random(20261112).shuffle(jobs)
        for serial,(rep,old) in enumerate(jobs):
            group=previous["groups"][old["group"]]
            if file_hash(old["export_path"])!=old["export_sha256"]:raise ValueError("export changed")
            if file_hash(group["reference"])!=group["reference_sha256"]:raise ValueError("reference changed")
            variant=next(v for v in group["variants"] if v["variant"]==old["variant"])
            if file_hash(variant["binary"])!=old["binary_sha256"]:raise ValueError("observed binary changed")
            folder=root/str(serial);folder.mkdir()
            row={k:old[k] for k in ("function","profile","variant","export_path","export_sha256","binary_sha256","group")}
            row.update(attempt=serial,prior_attempt=old["attempt"],repetition=rep,target_queries=0)
            row["resources"]=measure([sys.executable,ROOT/"tools/pcode_memory.py","--export",old["export_path"],"--output-dir",folder/"adapter"],folder/"resources",wall_seconds=30)
            adapter=folder/"adapter/adapter.json"
            row["adapter"]=json.loads(adapter.read_text()) if adapter.is_file() else {"status":"missing-adapter-result"}
            row["status"]=row["adapter"]["status"]
            if row["status"]=="candidate":
                if row["resources"]["status"]!="completed":row["status"]=row["resources"]["status"]
                else:
                    row["recovered_path"]=str(folder/"adapter/recovered.c")
                    row["recovered_sha256"]=file_hash(row["recovered_path"])
            report["records"].append(row)
            if serial%16==0:
                write_json(root/"replay.json",report);print(f"adapter {serial+1}/{len(jobs)}",flush=True)
        # Identical answer/reference hashes share one saved proof and controls.
        # Counts of observations and distinct graded answers remain separate.
        cache={}
        for row in report["records"]:
            if row["status"]!="candidate":continue
            group=previous["groups"][row["group"]];folder=root/str(row["attempt"])
            key=(group["reference_sha256"],row["recovered_sha256"],row["function"])
            if key not in cache:
                proof=grade(command,tool,group["reference"],row["recovered_path"],row["function"],folder/"verification.json",args.timeout_ms,contract_path,heap_observation)
                control_status={}
                export=json.loads(Path(row["export_path"]).read_text())
                controls={"return-plus-one":{"result_offset":1}}
                if row["adapter"]["metrics"].get("public_stores",row["adapter"]["metrics"]["stores"]):controls["last-store-plus-one"]={"final_store_offset":1}
                if row["adapter"]["metrics"].get("calls") and any(
                    p["kind"]=="uint32" for op in export["operations"] if op["opcode"]=="CALL"
                    for p in export.get("call_signatures",{}).get(op.get("callee"),{}).get("parameters",[])):
                    controls["call-argument-plus-one"]={"call_argument_offset":1}
                for name,mutation in controls.items():
                    wrong=folder/(name+".c");wrong.write_text(reconstruct(export,**mutation))
                    checked=grade(command,tool,group["reference"],wrong,row["function"],folder/(name+".json"),args.timeout_ms,contract_path,heap_observation)
                    control_status[name]=checked["verification"]
                cache[key]={"verification":proof["verification"],"proof_path":str(folder/"verification.json"),
                            "proof_sha256":file_hash(folder/"verification.json"),"controls":control_status}
                if row["adapter"]["metrics"].get("calls") and "call-argument-plus-one" not in controls:
                    cache[key]["control_skips"]={"call-argument-plus-one":"no scalar call argument to mutate"}
            row.update(cache[key])
            row["status"]={"proved-under-model":"recovered-under-source-model","counterexample":"false-reconstruction"}.get(row["verification"],"inconclusive-grading")
            if heap_observation=='successful-private' and row['status']=='recovered-under-source-model':
                row['status']='recovered-under-successful-allocations'
            if any(status=="proved-under-model" for status in row["controls"].values()):row["status"]="control-failure"
            elif any(status!="counterexample" for status in row["controls"].values()) and row["status"]!='false-reconstruction':row["status"]="control-inconclusive"
        report["distinct_graded_answers"]=len(cache)
        report["outcomes"]=dict(Counter(r["status"] for r in report["records"]))
        for name,expected in report["adapter_hashes"].items():
            if file_hash(ROOT/name)!=expected:raise ValueError("adapter changed during measurement")
        if file_hash(path)!=report["input_sha256"] or file_hash(tool)!=report["csrd_sha256"]:raise ValueError("input/tool changed")
        for row in report["records"]:
            if file_hash(row["export_path"])!=row["export_sha256"]:raise ValueError("export changed")
            if "recovered_path" in row and file_hash(row["recovered_path"])!=row["recovered_sha256"]:raise ValueError("answer changed")
        for group in previous["groups"]:
            if "public_abi" in group and file_hash(group["public_abi"])!=group["public_abi_sha256"]:
                raise ValueError("public object interface changed")
            if file_hash(group["reference"])!=group["reference_sha256"]:raise ValueError("reference changed")
            for variant in group["variants"]:
                if file_hash(variant["binary"])!=variant["binary_sha256"]:raise ValueError("observed binary changed")
        if contracts and file_hash(contracts["path"])!=contracts["sha256"]:raise ValueError("call contracts changed")
        if any(report["outcomes"].get(s) for s in ("false-reconstruction","control-failure")):report["status"]="failed"
        else:report["status"]="completed" if set(report["outcomes"])=={"recovered-under-source-model"} else "completed-with-gaps"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(root/"replay.json",report)
    print(report["status"],report["outcomes"],flush=True)
    return report


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--reconstruction-report",required=True);p.add_argument("--csrd",required=True)
    p.add_argument("--output-dir",required=True);p.add_argument("--repetitions",type=int,default=3);p.add_argument("--timeout-ms",type=int,default=10000)
    p.add_argument('--heap-observation',choices=('events','successful-private'),default='events',help='explicit supplemental grading assumption; never changes prior results')
    args=p.parse_args()
    if not 1<=args.repetitions<=20 or not 1<=args.timeout_ms<=120000:p.error("invalid repetition or verification budget")
    root=Path(args.output_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    with measurement_lock() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);result=run(args,root)
    raise SystemExit(int(result["status"]=="failed"))
