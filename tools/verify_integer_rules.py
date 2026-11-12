#!/usr/bin/env python3
"""Width-specific bit-vector obligations; not a proof of the C frontend/compiler."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

CHECK="(check-sat-using (then (using-params simplify :som true) smt))\n"


def verify(z3):
    records=[]
    def check(name, query, expected="unsat"):
        script="(set-option :timeout 10000)\n(set-logic QF_BV)\n"+query+CHECK
        start=time.perf_counter()
        result=subprocess.run([z3,"-in"],input=script,text=True,capture_output=True,timeout=15)
        records.append({"name":name,"expected":expected,"answer":result.stdout.strip(),"seconds":time.perf_counter()-start,
                        "smtlib":script,"sha256":hashlib.sha256(script.encode()).hexdigest()})
        if result.returncode or result.stderr or result.stdout.strip()!=expected:
            raise AssertionError(f"{name}: {result.stdout} {result.stderr}")
    for n in (1,8,16,32,64):
        header="\n".join(f"(declare-const {s} (_ BitVec {n}))" for s in ("a","b","x","y","k"))+"\n"
        header+=f"(define-fun E ((v (_ BitVec {n}))) (_ BitVec {n}) (bvadd (bvmul a v) b))\n"
        for name,left,right in (
            ("add","(bvsub (bvadd (E x) (E y)) b)","(E (bvadd x y))"),
            ("subtract","(bvadd (bvsub (E x) (E y)) b)","(E (bvsub x y))"),
            ("scale",f"(bvadd (bvmul k (E x)) (bvmul (bvsub (_ bv1 {n}) k) b))","(E (bvmul k x))"),
            ("complement",f"(bvsub (_ bv{(1<<n)-1} {n}) x)","(bvnot x)")):
            check(f"{name}-u{n}",header+f"(assert (distinct {left} {right}))\n")
        for m in (1,8,16,32):
            if m>=n: continue
            low=lambda x:f"((_ extract {m-1} 0) {x})"
            check(f"narrow-{n}-to-{m}",header+f"(assert (distinct {low('(E x)')} (bvadd (bvmul {low('a')} {low('x')}) {low('b')})))\n")
        if n>1:
            raw="x" if n==64 else f"((_ zero_extend {64-n}) x)"
            sign="x" if n==64 else f"((_ sign_extend {64-n}) x)"
            restored=f"(ite (bvule {raw} (_ bv{(1<<(n-1))-1} 64)) {raw} (bvnot (bvsub (_ bv{(1<<n)-1} 64) {raw})))"
            check(f"signed-restoration-{n}",header+f"(assert (distinct {restored} {sign}))\n")
    for n in (2,4,8,16,32,64):
        header=f"(declare-const error (_ BitVec {n}))\n(define-fun product () (_ BitVec {n}) (bvadd (_ bv1 {n}) (bvmul error (_ bv{1<<(n//2)} {n}))))\n"
        check(f"newton-{n//2}-to-{n}",header+f"(assert (distinct (bvmul product (bvsub (_ bv2 {n}) product)) (_ bv1 {n})))\n")
    check("wrong-complement-control","(declare-const x (_ BitVec 64))\n(assert (distinct (bvsub (_ bv0 64) x) (bvnot x)))\n","sat")
    return records


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--z3",default="z3");p.add_argument("--report",required=True);args=p.parse_args()
    records=verify(args.z3)
    report={"status":"passed","scope":"solver-checked fixed-width rules under the declared integer model; no proof certificate or whole-C correctness claim",
            "solver":subprocess.check_output([args.z3,"--version"],text=True).strip(),"records":records}
    Path(args.report).write_text(json.dumps(report,indent=2)+"\n")
    print(f"PASS {len(records)} integer obligations (including one false-rule control)")
