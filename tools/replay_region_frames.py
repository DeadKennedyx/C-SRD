#!/usr/bin/env python3
"""Replay hash-bound emitted-frame obligations; time solver processes separately."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import shutil

from audit_protection import file_hash, write_json
from audit_region_observers import checked_artifacts, command
from effort_resources import measure, environment

ROOT=Path(__file__).resolve().parents[1]


def run(args):
    manifest=Path(args.build).resolve();build=json.loads(manifest.read_text());records=checked_artifacts(build)
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=False)
    solver=shutil.which(args.z3)
    if not solver:raise ValueError("Z3 unavailable")
    report={"schema_version":1,"status":"running","build_sha256":file_hash(manifest),"environment":environment(),"records":[],
            "solver":{"path":solver,"sha256":file_hash(solver),"version":command([solver,"--version"],root/"solver-version").strip()},
            "scope":"replay of emitted private-u32 frame obligations; original CLI context/binding checks recorded separately; no whole-program/callback/loop proof"}
    try:
        for record in records:
            validation=record["frame_validation"]
            if validation is None:continue
            if file_hash(validation["path"])!=validation["sha256"]:raise ValueError("frame report changed")
            proof=json.loads(Path(validation["path"]).read_text())
            if file_hash(record["source"])!=proof["candidate_sha256"]:raise ValueError("candidate changed")
            for function in proof["functions"]:
                if not function["context_bindings_verified"]:raise ValueError("context not validated")
                for frame in function["private_regions"]:
                    saved=frame["proof"];query=saved["smtlib"]
                    if hashlib.sha256(query.encode()).hexdigest()!=saved["obligation_sha256"]:raise ValueError("query checksum mismatch")
                    directory=root/str(len(report["records"]));directory.mkdir();path=directory/"obligation.smt2";path.write_text(query)
                    resource=measure([solver,"-smt2",path],directory/"resources",wall_seconds=30)
                    resource.pop("samples",None)
                    answer=(directory/"resources/stdout.txt").read_text().strip()
                    report["records"].append({"artifact":record["id"],"function":function["function"],"source_begin":frame["source_begin"],
                        "candidate_sha256":proof["candidate_sha256"],"obligation_sha256":saved["obligation_sha256"],"answer":answer,
                        "status":"proved-under-frame-model" if resource["status"]=="completed" and answer=="unsat" else "not-proved",
                        "resources":resource,"operations":frame["operations"],"operations_without_decoding":frame["operations_without_decoding"],
                        "boundary_conversions":frame["boundary_conversions"]})
                    write_json(root/"verification.json",report)
        report["status"]="completed" if all(r["status"]=="proved-under-frame-model" for r in report["records"]) else "failed"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(root/"verification.json",report)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--build",required=True);p.add_argument("--output",required=True);p.add_argument("--z3",default="z3");args=p.parse_args()
    with (ROOT/"experiments/runs/effort.lock").open("a") as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);run(args)
