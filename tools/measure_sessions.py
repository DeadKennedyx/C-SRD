#!/usr/bin/env python3
"""Measure persistent reconstruction on frozen, previously studied binaries.

Resource collection completes before any grading. Every original/candidate cell
is retained, including invalid counters or timeouts. No performance cutoff is
used to select representations.
"""
import argparse
from collections import defaultdict
import fcntl
import json
from pathlib import Path
import random
import sys

from audit_protection import file_hash
from effort_resources import environment, measure, save, measurement_lock

ROOT=Path(__file__).resolve().parents[1]
FROZEN=("pcode_values.py","pcode_wide.py","pcode_vector.py","pcode_cfg.py","pcode_reconstruct.py","ghidra/ExportCSRD.java")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prior-cold",required=True)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--headless",required=True)
    for option in ("case","profile","variant"):
        parser.add_argument("--"+option,action="append",default=[])
    parser.add_argument("--repetitions",type=int,default=3)
    parser.add_argument("--batches",type=int,default=5)
    parser.add_argument("--calls",type=int,default=32)
    parser.add_argument("--warmup-calls",type=int,default=32)
    parser.add_argument("--order-seed",type=int,default=731123)
    parser.add_argument("--session-seconds",type=float,default=120)
    parser.add_argument("--analysis-seconds",type=int,default=30)
    parser.add_argument("--decompile-seconds",type=int,default=15)
    parser.add_argument("--retain-unsupported",action="store_true",
                        help="record adapter refusals per request and continue measuring; never grade them as recovered")
    args=parser.parse_args()
    if not sys.platform.startswith("linux"):
        parser.error("Linux process clocks and /proc are required")
    if (not 1<=args.repetitions<=20 or not 1<=args.batches<=100 or not 1<=args.calls<=1024 or
            not 1<=args.warmup_calls<=1024 or not 1<=args.decompile_seconds<=60 or
            not 1<=args.analysis_seconds<=120 or not 1<=args.session_seconds<=3600):
        parser.error("batch counts or deadlines outside bounded protocol")
    prior_path=Path(args.prior_cold).resolve(strict=True)
    prior=json.loads(prior_path.read_text())
    if prior["status"]!="completed" or prior["observer"]!="ghidra":
        raise ValueError("completed cold Ghidra comparison required")
    bindings={str(prior_path):file_hash(prior_path)}
    for name in FROZEN:
        path=str(ROOT/"tools"/name)
        if prior["artifact_bindings"].get(path)!=file_hash(path):
            raise ValueError("frozen semantic observer changed: "+path)
        bindings[path]=file_hash(path)
    matrix_path=next(p for p in prior["artifact_bindings"] if p.endswith("/matrix/matrix.json"))
    if file_hash(matrix_path)!=prior["artifact_bindings"][matrix_path]:
        raise ValueError("frozen matrix changed")
    matrix=json.loads(Path(matrix_path).read_text());bindings[matrix_path]=file_hash(matrix_path)
    keys={(t["case"],t["profile"],t["variant"]) for t in prior["trials"]}
    keys={k for k in keys if all(not requested or value in requested for value,requested in zip(k,(args.case,args.profile,args.variant)))}
    if not keys or any((case,profile,"original") not in keys for case,profile,variant in keys):
        raise ValueError("nonempty cells with matched original controls required")
    for index,requested in enumerate((args.case,args.profile,args.variant)):
        if requested and set(requested)!={key[index] for key in keys}:
            raise ValueError("requested cells missing from frozen comparison")
    records=[r for r in matrix["records"] if (r["case"],r["profile"],r["variant"]) in keys]
    if len(records)!=len(keys):raise ValueError("missing or duplicate matrix cells")
    for r in records:
        if r["status"]!="completed" or file_hash(r["binary"])!=r["binary_sha256"]:
            raise ValueError("unvalidated or changed binary")
        bindings[r["binary"]]=r["binary_sha256"]
    headless=Path(args.headless).resolve(strict=True);installation=headless.parent.parent
    # Pin language definitions and executable/library components before results.
    components=[headless,installation/"Ghidra/application.properties"]
    components+=list(installation.glob("Ghidra/**/*.jar"))
    components+=list(installation.glob("Ghidra/Features/Decompiler/os/linux_arm_64/decompile"))
    components+=list(installation.glob("Ghidra/Features/Decompiler/os/linux_x86_64/decompile"))
    components+=list((installation/"Ghidra/Processors/AARCH64/data/languages").glob("*"))
    components+=[ROOT/"tools"/name for name in ("process_counters.py","session_worker.py","measure_sessions.py","effort_resources.py","ghidra/SessionCSRD.java")]
    bindings.update({str(p):file_hash(p) for p in components if p.is_file()})
    output=Path(args.output_dir).resolve();output.mkdir(parents=True,exist_ok=False)
    groups=defaultdict(list)
    for r in records:groups[(r["case"],r["profile"])].append(r)
    rng=random.Random(args.order_seed);schedule=[]
    for repetition in range(args.repetitions):
        blocks=sorted(groups);rng.shuffle(blocks)
        for key in blocks:
            variants=sorted(groups[key],key=lambda r:r["variant"]);rng.shuffle(variants)
            schedule += [{"case":r["case"],"profile":r["profile"],"variant":r["variant"],"repetition":repetition} for r in variants]
    report={"status":"running","scope":"development only; repeated same-function requests; no human or debugger-secrecy inference",
            "protocol":vars(args),"environment_start":environment(),"bindings":bindings,"schedule":schedule,"sessions":[],
            "sampling":"one fresh JVM/native session per cell and repetition; cache flush before each request; batches are correlated within a session",
            "grading":"withheld source; all distinct answers graded separately after resource collection"}
    save(output/"protocol.json",report)
    indexed={(r["case"],r["profile"],r["variant"]):r for r in records}
    with measurement_lock() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        for i,cell in enumerate(schedule):
            r=indexed[(cell["case"],cell["profile"],cell["variant"])]
            case=next(c for c in matrix["cases"] if c["id"]==r["case"])
            directory=output/f"session-{i:04d}";directory.mkdir()
            config={"binary":r["binary"],"function":case["function"],"arity":case["arity"],"headless":str(headless),
                    **{k:getattr(args,k) for k in ("warmup_calls","calls","batches","analysis_seconds","decompile_seconds","session_seconds","retain_unsupported")}}
            save(directory/"config.json",config)
            print(i+1,len(schedule),cell,flush=True)
            row={**cell,"id":i,"directory":str(directory),"binary_sha256":r["binary_sha256"],
                 "config_sha256":file_hash(directory/"config.json")}
            try:
                resources=measure([sys.executable,ROOT/"tools/session_worker.py",directory/"config.json"],directory/"measurement",wall_seconds=args.session_seconds)
                path=directory/"session.json"
                session=json.loads(path.read_text()) if path.exists() else {}
                row.update(status="completed" if resources["status"]==session.get("status")=="completed" else "failed",
                           resource_status=resources["status"],session_status=session.get("status"),error=session.get("error"),
                           resources_sha256=file_hash(directory/"measurement/resources.json"),session_sha256=file_hash(path) if path.exists() else None)
            except Exception as error:
                row.update(status="failed",error=str(error))
            save(directory/"record.json",row);report["sessions"].append(row)
            save(output/"sessions.json",report)
        if any(file_hash(path)!=expected for path,expected in bindings.items()):
            raise ValueError("frozen experiment input changed")
    report.update(status="completed" if all(r["status"]=="completed" for r in report["sessions"]) else "failed",environment_end=environment())
    save(output/"sessions.json",report)
    save(output/"completion.json",{"status":report["status"],"sessions":len(report["sessions"]),"historical_records_modified":False})
    return 0 if report["status"]=="completed" else 3


if __name__=="__main__":sys.exit(main())
