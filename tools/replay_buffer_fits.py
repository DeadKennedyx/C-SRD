#!/usr/bin/env python3
"""Remeasure fitting on saved traces; no GDB or target process is executed."""
import argparse
from collections import Counter
import fcntl
import json
from pathlib import Path
import random
import sys

from audit_protection import file_hash,write_json
from effort_resources import environment,measure,measurement_lock

ROOT=Path(__file__).resolve().parents[1]


def run(args,root):
    path=Path(args.runtime_report).resolve();previous=json.loads(path.read_text())
    if previous["status"]!="completed":raise ValueError("requires a completed runtime observation")
    report={"schema_version":1,"status":"running","runtime_report":str(path),"runtime_sha256":file_hash(path),
            "environment":environment(),"records":[],"repetitions":args.repetitions,"fit_protocol":args.fit_protocol,
            "new_target_executions":0,"implementation":{p:file_hash(ROOT/p) for p in
                ("tools/replay_buffer_fits.py","tools/fit_buffer_traces.py","tools/observe_runtime.py","tools/effort_resources.py")},
            "scope":"new fit process/algorithm costs; original GDB costs and inputs are unchanged; finite held-out matches"}
    inputs={path:report["runtime_sha256"]}
    try:
        jobs=[]
        for index,observation in enumerate(previous["observations"]):
            if observation["status"]!="completed":raise ValueError("incomplete source observation")
            original=Path(observation["traces"][0]["path"]).parent/"fit-config.json"
            if file_hash(original)!=observation["fit"]["config_sha256"]:raise ValueError("original fit configuration changed")
            inputs[original]=file_hash(original)
            config=json.loads(original.read_text())
            if config["traces"]!=observation["traces"]:raise ValueError("trace list differs from frozen observation")
            config["fit_protocol"]=args.fit_protocol
            for trace in config["traces"]:
                if file_hash(trace["path"])!=trace["sha256"]:raise ValueError("trace changed")
                inputs[Path(trace["path"])]=trace["sha256"]
            file=root/f"config-{index}.json";write_json(file,config);inputs[file]=file_hash(file)
            jobs.extend((index,rep,observation,file) for rep in range(args.repetitions))
        random.Random(20261114).shuffle(jobs)
        for serial,(index,rep,old,config) in enumerate(jobs):
            directory=root/str(serial);directory.mkdir();output=directory/"fit.json"
            resources=measure([sys.executable,ROOT/"tools/fit_buffer_traces.py",config,output],directory/"resources",wall_seconds=60)
            fit=json.loads(output.read_text()) if output.is_file() else {"status":"missing-fit-result"}
            status=fit["status"] if resources["status"]=="completed" else resources["status"]
            report["records"].append({**{k:old[k] for k in ("function","profile","variant","layout")},
                "observation":index,"repetition":rep,"status":status,"resources":resources,
                "fit_path":str(output),"fit_sha256":file_hash(output) if output.is_file() else None})
            if serial%16==0:
                write_json(root/"replay.json",report);print(f"fit {serial+1}/{len(jobs)}",flush=True)
        for file,digest in inputs.items():
            if file_hash(file)!=digest:raise ValueError("input changed during fitting")
        for name,digest in report["implementation"].items():
            if file_hash(ROOT/name)!=digest:raise ValueError("fitter changed during measurement")
        report["outcomes"]=dict(Counter(r["status"] for r in report["records"]))
        report["status"]="completed" if set(report["outcomes"])=={"completed"} else "failed"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(root/"replay.json",report)
    print(report["status"],report.get("outcomes"),flush=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--runtime-report",required=True);p.add_argument("--output-dir",required=True)
    p.add_argument("--repetitions",type=int,default=3)
    p.add_argument("--fit-protocol",choices=("affine-v1","affine-literal-boundaries-v2"),default="affine-literal-boundaries-v2")
    args=p.parse_args()
    if not 1<=args.repetitions<=20:p.error("repetitions must be 1..20")
    root=Path(args.output_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    with measurement_lock() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);run(args,root)
