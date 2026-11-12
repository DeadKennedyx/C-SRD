#!/usr/bin/env python3
"""Controlled calls/loops GDB observations, full effect checks, congruence fitting."""
import argparse
import gzip
import fcntl
import json
from pathlib import Path
import random
import shutil
import sys

from audit_protection import file_hash, write_json
from audit_region_observers import checked_artifacts
from effort_resources import measure, environment, measurement_lock
from region_observation_cases import oracle, effects, input_text

ROOT = Path(__file__).resolve().parents[1]


def trace_vectors(function, loop_count):
    rng = random.Random(0x43535244)
    values = []
    for i in range(12):
        values.append({"x":rng.getrandbits(32),"arg":loop_count if function=="region_pipeline" else rng.getrandbits(32),
                       "memory":[rng.getrandbits(32) for _ in range(3)],"mode":0})
    # Independent basis variation, in addition to seeded random training values.
    values[0].update(x=0, memory=[0,0,0]); values[1].update(x=1,memory=[0,0,0])
    values[2].update(x=0,memory=[1,0,0]); values[3].update(x=0,memory=[0,1,0])
    return values


def run(args):
    manifest=Path(args.build).resolve(); build=json.loads(manifest.read_text())
    records=checked_artifacts(build)
    root=Path(args.output).resolve(); root.mkdir(parents=True,exist_ok=False)
    report={"schema_version":1,"status":"running","build":str(manifest),"build_sha256":file_hash(manifest),
            "environment":environment(),"groups":[],"protocol":{"training":6,"heldout":6,"pipeline_loop_counts":[0,2],"mode":0,
            "step_limit":args.step_limit,"observer":"affine-congruence-v2","no_simd_coverage":True,"known_intermediates":True},
            "hashes":{p.name:file_hash(p) for p in [Path(__file__),ROOT/"tools/gdb_region_trace.py",ROOT/"tools/fit_region_traces.py",ROOT/"tools/fit_region_values.py",ROOT/"tools/region_observation_cases.py"]}}
    gdb=shutil.which(args.gdb)
    if not gdb: raise ValueError("GDB unavailable")
    report["gdb"]={"path":gdb,"sha256":file_hash(gdb)}
    if any(r["fixture"]=="integers" for r in records):
        report["protocol"].update(observer="affine-congruence-widths-v3",integer_target_widths=[1,8,16,32,64],
                                   integer_storage_views="low32/full64 general registers; 4/8-byte stack views; low32 caller memory")
    jobs=[(r,function,n) for r in records for function,n in [("region_pipeline",0),("region_pipeline",2),("region_outputs",None)]]
    random.Random(20261110).shuffle(jobs)
    try:
        for serial,(record,function,n) in enumerate(jobs):
            directory=root/f"{serial:04d}";directory.mkdir()
            group={"artifact":record["id"],"function":function,"loop_count":n,"status":"observing","traces":[],"directory":str(directory)}
            report["groups"].append(group)
            cases=trace_vectors(function,n)
            predictions=[oracle(record["fixture"],function,v) for v in cases]
            for i,vector in enumerate(cases):
                input_path=directory/f"{i}.input";input_path.write_text(input_text(vector))
                config=directory/f"{i}.config.json";output=directory/f"{i}.trace.json.gz"
                write_json(config,{"function":function,"step_limit":args.step_limit,"input_file":str(input_path),"output":str(output),
                                   "wide_values":record["fixture"]=="integers"})
                script=directory/f"{i}.gdb"
                script.write_text("python\nimport sys\nsys.path.insert(0,"+repr(str(ROOT/"tools"))+")\nimport gdb_region_trace\ngdb_region_trace.main("+repr(str(config))+")\nend\n")
                resource=measure([gdb,"--nx","--batch","-iex","set auto-load off","-x",script,"--args",record["drivers"][function]["path"]],directory/f"{i}-resources",wall_seconds=120)
                resource.pop("samples",None)
                entry={"path":str(output),"split":"training" if i<6 else "heldout","input":vector,"resources":resource}
                group["traces"].append(entry)
                if not output.exists(): raise ValueError("no GDB result: "+str(directory))
                entry["sha256"]=file_hash(output)
                with gzip.open(output,"rt") as source:trace=json.load(source)
                entry.update(status=trace["status"],steps=trace.get("steps",0),
                             max_observed_stack_depth_bytes=trace.get("max_observed_stack_depth_bytes"))
                if resource["status"]!="completed" or trace["status"]!="completed" or trace["stack_read_failures"]:
                    group.update(status="incomplete-observation",error=trace.get("error",trace["status"])); break
                if effects(trace)!=effects(predictions[i]): raise ValueError("trace disagrees with return/memory/event oracle")
                entry["effects_validated"]=True
            if group["status"]=="observing": group["status"]="observed"
            write_json(root/"runtime.json",report)
            print(f"traced {serial+1}/{len(jobs)} {record['id']} {function}/{n}: {group['status']}",flush=True)
        # Fit after all debugger measurements so CPU/RSS data are not polluted.
        for group in report["groups"]:
            if group["status"]!="observed":continue
            directory=Path(group["directory"])
            record=next(r for r in records if r["id"]==group["artifact"])
            predictions=[oracle(record["fixture"],group["function"],t["input"]) for t in group["traces"]]
            targets={name:[p["targets"][name] for p in predictions] for name in predictions[0]["targets"]}
            config=directory/"fit-config.json";output=directory/"fit.json"
            widths={name:int(name.rsplit(".u",1)[1]) for name in targets} if record["fixture"]=="integers" else {}
            write_json(config,{"traces":group["traces"],"targets":targets,"function":group["function"],"target_widths":widths})
            resource=measure([sys.executable,ROOT/"tools/fit_region_traces.py",config,output],directory/"fit-resources",wall_seconds=120)
            resource.pop("samples",None);group["fit_resources"]=resource
            if output.exists():
                fit=json.loads(output.read_text())
                group.update(status=fit["status"],fit={"path":str(output),"sha256":file_hash(output)},targets={})
                for name,t in fit.get("targets",{}).items():
                    group["targets"][name]={"bits":t.get("bits",32),"fit_status":t["fit"]["status"],"parameter_solutions":t["fit"]["parameter_solutions"],
                         "recovery":{k:v for k,v in t["recovery"].items() if k!="models"},
                         "negative_control":{k:v for k,v in t["negative_control"].items() if k!="models"},"by_scope":t["by_scope"]}
            else:group["status"]="fit-failed"
            write_json(root/"runtime.json",report)
        checked_artifacts(build)
        if file_hash(manifest)!=report["build_sha256"]:raise ValueError("manifest changed")
        report["status"]="completed"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(root/"runtime.json",report)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--build",required=True);p.add_argument("--output",required=True);p.add_argument("--gdb",default="gdb")
    p.add_argument("--step-limit",type=int,default=6000)
    args=p.parse_args()
    if not 1<=args.step_limit<=20000:p.error("step limit must be 1..20000")
    with measurement_lock() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        run(args)
