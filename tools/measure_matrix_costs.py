#!/usr/bin/env python3
"""Repeat application costs on existing validated matrix binaries, without rebuilds.

All variants in each selected cell are retained. The recorded timing protocol is
the linked harness, including input generation; this does not isolate the kernel.
"""
import argparse
from collections import defaultdict
import fcntl
import json
from pathlib import Path
import sys

from audit_protection import AuditError, Runner, file_hash, write_json
from effort_resources import environment, measurement_lock
from experiment_support import paired_costs

ROOT=Path(__file__).resolve().parents[1]


def run(args, root):
    path=Path(args.matrix_report).resolve(strict=True)
    matrix=json.loads(path.read_text())
    if matrix["status"] not in ("completed","completed-with-gaps"):
        raise ValueError("completed validated matrix required")
    selected=[r for r in matrix["records"] if r["profile"] in args.profile and (not args.case or r["case"] in args.case)]
    if not selected or set(args.profile)!={r["profile"] for r in selected} or (args.case and set(args.case)!={r["case"] for r in selected}):
        raise ValueError("requested case/profile missing")
    if any(r["status"]!="completed" for r in selected):raise ValueError("selected cell did not validate")
    records=[{k:r[k] for k in ("case","profile","variant","binary","binary_sha256","binary_bytes")} for r in selected]
    del selected, matrix
    bindings={str(path):file_hash(path),str(Path(__file__).resolve()):file_hash(__file__),
              **{str(ROOT/"tools"/name):file_hash(ROOT/"tools"/name) for name in ("experiment_support.py","audit_protection.py","effort_resources.py")}}
    for record in records:
        if file_hash(record["binary"])!=record["binary_sha256"]:raise ValueError("matrix binary changed")
        bindings[record["binary"]]=record["binary_sha256"]
    report={"schema_version":1,"status":"running","matrix":str(path),"matrix_sha256":bindings[str(path)],
            "protocol":vars(args),"environment":environment(),"bindings":bindings,"commands":[],"records":records,
            "scope":"frozen linked harness, all variants; input generation, kernel and checksum in timed loop; no rebuild or selection",
            "memory_counter_control":{"status":"unavailable","reason":"requires Linux resource-enabled harness"}}
    command=Runner(report)
    groups=defaultdict(list)
    for record in records:groups[(record["case"],record["profile"])].append(record)
    if any("original" not in {r["variant"] for r in rows} for rows in groups.values()):
        raise ValueError("every cell requires an original")
    output=root/"costs.json"
    write_json(output,report)
    try:
        if sys.platform.startswith("linux"):
            baseline=next(r["binary"] for r in records if r["variant"]=="original")
            direct=command([baseline,1,args.seed]).split()
            if len(direct)==5 and direct[4]!="unavailable":
                launcher="import os,sys; p=bytearray(64<<20); p[::4096]=b'x'*(len(p)//4096); os.execv(sys.argv[1],sys.argv[1:])"
                pressured=command([sys.executable,"-c",launcher,baseline,1,args.seed]).split()
                if len(pressured)!=5 or direct[1]!=pressured[1]:raise ValueError("memory counter control changed checksum")
                def counters(parts):
                    return {"checksum":int(parts[1]),"rusage_peak_bytes":int(parts[3]),"executable_peak_bytes":int(parts[4])}
                passed=int(pressured[3])>=64<<20 and int(pressured[4])<32<<20
                report["memory_counter_control"]={"status":"passed" if passed else "failed","launcher_bytes_touched":64<<20,
                                                   "direct":counters(direct),"after_exec":counters(pressured)}
                if not passed:raise ValueError("memory counter control did not distinguish launcher/address space")
        for group, rows in sorted(groups.items()):
            paired_costs(command,rows,args.iterations,args.repetitions,args.seed)
            write_json(output,report)
            print("measured "+"/".join(group),flush=True)
        if any(file_hash(p)!=h for p,h in bindings.items()):raise ValueError("bound measurement input changed")
        report["status"]="completed"
    except Exception as error:
        report.update(status="failed",error=str(error));raise
    finally:write_json(output,report)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--matrix-report",required=True);p.add_argument("--output-dir",required=True)
    p.add_argument("--profile",action="append",required=True);p.add_argument("--case",action="append")
    p.add_argument("--iterations",type=int,default=10000000);p.add_argument("--repetitions",type=int,default=7)
    p.add_argument("--seed",type=int,default=20261113)
    args=p.parse_args()
    if not 1<=args.iterations<=100000000 or not 3<=args.repetitions<=100 or not 0<args.seed<2**32-args.repetitions:
        p.error("positive iterations <= 100 million, 3..100 repetitions and nonzero uint32 seeds required")
    if len(set(args.profile))!=len(args.profile) or (args.case and len(set(args.case))!=len(args.case)):
        p.error("duplicate filters")
    root=Path(args.output_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    try:
        with measurement_lock() as lock:
            fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);run(args,root)
    except (ValueError,OSError,AuditError) as error:
        write_json(root/"failure.json",{"status":"failed","error":str(error)})
        raise
