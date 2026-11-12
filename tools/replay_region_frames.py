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


def obligations(proof):
    if proof["status"]!="proved-under-model": raise ValueError("unproved frame/component")
    if proof.get("defined_domain_smtlib"):
        yield "defined-domain","sat",proof["defined_domain_smtlib"],proof["defined_domain_sha256"]
    if proof.get("smtlib"):
        yield proof.get("label","frame"),"unsat",proof["smtlib"],proof["obligation_sha256"]
    elif not proof.get("steps"): raise ValueError("frame has no replayable evidence")
    for step in proof.get("steps",[]):yield from obligations(step)


def run(args):
    manifest=Path(args.build).resolve();build=json.loads(manifest.read_text());records=checked_artifacts(build)
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=False)
    solver=shutil.which(args.z3)
    if not solver:raise ValueError("Z3 unavailable")
    report={"schema_version":1,"status":"running","build_sha256":file_hash(manifest),"environment":environment(),"records":[],
            "solver":{"path":solver,"sha256":file_hash(solver),"version":command([solver,"--version"],root/"solver-version").strip()},
            "scope":"replay of emitted scalar-frame obligations and defined-domain checks; original CLI context/binding/composition checks recorded separately; no whole-program/callback/loop proof"}
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
                    for label,expected,query,checksum in obligations(frame["proof"]):
                        if hashlib.sha256(query.encode()).hexdigest()!=checksum:raise ValueError("query checksum mismatch")
                        directory=root/str(len(report["records"]));directory.mkdir();path=directory/"obligation.smt2";path.write_text(query)
                        resource=measure([solver,"-smt2",path],directory/"resources",wall_seconds=30)
                        resource.pop("samples",None)
                        answer=(directory/"resources/stdout.txt").read_text().strip()
                        report["records"].append({"artifact":record["id"],"function":function["function"],"source_begin":frame["source_begin"],
                            "candidate_sha256":proof["candidate_sha256"],"obligation_sha256":checksum,"answer":answer,"expected":expected,"query_role":label,
                            "status":"proved-under-frame-model" if resource["status"]=="completed" and answer==expected else "not-proved",
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
