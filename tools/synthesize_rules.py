#!/usr/bin/env python3
"""Bounded template enumeration followed by universal bit-vector validation.

Searches p*X + q*Y + r*b for affine encoded addition/subtraction. This
rediscovers known rules; it neither establishes novelty nor synthesizes a
general C transformation. Concrete samples prune candidates, never prove them.
"""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess


def obligation(p, q, r, subtract):
    def bv(n):
        return f"(_ bv{n & 0xffffffff} 32)"
    op = "bvsub" if subtract else "bvadd"
    return f'''(set-logic QF_BV)
(declare-fun a () (_ BitVec 32))
(declare-fun b () (_ BitVec 32))
(declare-fun x () (_ BitVec 32))
(declare-fun y () (_ BitVec 32))
(assert (= (bvand a (_ bv1 32)) (_ bv1 32)))
(define-fun ex () (_ BitVec 32) (bvadd (bvmul a x) b))
(define-fun ey () (_ BitVec 32) (bvadd (bvmul a y) b))
(assert (distinct
 (bvadd (bvadd (bvmul {bv(p)} ex) (bvmul {bv(q)} ey)) (bvmul {bv(r)} b))
 (bvadd (bvmul a ({op} x y)) b)))
(check-sat-using (then (using-params simplify :som true) smt))
'''


def run(solver, directory):
    root = Path(directory); root.mkdir(parents=True, exist_ok=False)
    rng = random.Random(20261108)
    samples = [(rng.getrandbits(32) | 1, rng.getrandbits(32), rng.getrandbits(32), rng.getrandbits(32)) for _ in range(32)]
    results = []
    for subtract in (False, True):
        tested, survivors = 0, []
        for p, q, r in itertools.product((-1, 0, 1), repeat=3):
            tested += 1
            if any((p*(a*x+b) + q*(a*y+b) + r*b - (a*(x-y if subtract else x+y)+b)) & 0xffffffff
                   for a, b, x, y in samples):
                continue
            text = obligation(p, q, r, subtract)
            path = root / (f"{'subtract' if subtract else 'add'}-{len(survivors)}.smt2")
            path.write_text(text)
            output = subprocess.run([solver, "-T:10", str(path)], text=True, capture_output=True, timeout=12)
            status = output.stdout.strip()
            if output.returncode or status not in ("sat", "unsat", "unknown", "timeout"):
                raise RuntimeError(output.stdout + output.stderr)
            survivors.append({"p": p, "q": q, "r": r, "solver_answer": status,
                              "status": "proved-under-model" if status == "unsat" else "not-proved",
                              "obligation_sha256": hashlib.sha256(text.encode()).hexdigest(), "obligation": path.name})
        results.append({"operation": "subtract" if subtract else "add", "enumerated": tested, "sample_survivors": survivors})
    report = {"grammar": "p*X+q*Y+r*b, coefficients in {-1,0,1}", "width": 32,
              "sample_seed": 20261108, "sample_count": len(samples),
              "solver": subprocess.check_output([solver, "--version"], text=True).strip(), "results": results,
              "scope": "Universal fixed-width arithmetic identities under odd a, after finite template search. Known affine rules rediscovered; no novelty or whole-compiler proof claim."}
    (root / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--z3", default="z3")
    p.add_argument("--output-dir", required=True)
    args = p.parse_args()
    result = run(args.z3, args.output_dir)
    print(json.dumps(result, indent=2))
