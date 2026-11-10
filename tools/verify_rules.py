#!/usr/bin/env python3
"""Check arithmetic obligations, including an intentionally false rule as a control.

No claim about the AST analyzer, emitter or complete generated C is made here.
Z3 is trusted; this script does not produce independently checked proof certificates.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
CHECK = "(check-sat-using (then (using-params simplify :som true) smt))\n"


def run(z3, smt):
    result = subprocess.run([z3, "-in"], input="(set-option :timeout 10000)\n" + smt,
                            capture_output=True, text=True, timeout=45)
    if result.returncode or result.stderr or "(error" in result.stdout:
        raise RuntimeError(result.stdout + result.stderr)
    return result.stdout.strip()


def main(args):
    start = time.perf_counter()
    contract = ROOT / "src/verification/affine-rules.smt2"
    output = run(args.z3, contract.read_text()).splitlines()
    if output != ["unsat"] * 3:
        raise AssertionError(f"rule obligations failed or were inconclusive: {output}")
    print("PASS add, subtract, scale: unsat counterexample queries over all 32-bit symbols")
    xor_contract = ROOT / "src/verification/xor-rules.smt2"
    xor_answers = run(args.z3, xor_contract.read_text()).splitlines()
    if xor_answers != ["unsat"] * 6:
        raise AssertionError(f"xor obligations failed or were inconclusive: {xor_answers}")
    print("PASS xor, and, or, not, left shift, right shift: all payloads/masks; shifts in 0..31")
    split_contract = ROOT / "src/verification/split-scale.smt2"
    split_answer = run(args.z3, split_contract.read_text())
    if split_answer != "unsat":
        raise AssertionError(f"split-scale obligation failed or inconclusive: {split_answer}")
    print("PASS parity split: all stored operands, scale factors and corrections")
    newton = []
    for width in (2, 4, 8, 16, 32):
        half = width // 2
        # If a*i is 1 modulo 2^half, write it as 1 + error*2^half.
        # The Newton update makes the product 1 modulo 2^width.
        smt = f"""(set-logic QF_BV)
(declare-const error (_ BitVec {width}))
(define-fun product () (_ BitVec {width}) (bvadd (_ bv1 {width}) (bvmul error (_ bv{1 << half} {width}))))
(assert (not (= (bvmul product (bvsub (_ bv2 {width}) product)) (_ bv1 {width}))))
""" + CHECK
        answer = run(args.z3, smt)
        if answer != "unsat":
            raise AssertionError(f"Newton low-bit step {half}->{width}: {answer}")
        newton.append({"from_correct_bits": half, "to_correct_bits": width, "result": answer})
    print("PASS Newton inverse correctness steps: 1 -> 2 -> 4 -> 8 -> 16 -> 32 bits")
    inverses = []
    # These are concrete-parameter proofs, explicitly distinct from all-parameter proofs.
    for a in (1, 3, 5, 0xffffffff, 0x80000001, 1789947473):
        inverse = pow(a, -1, 1 << 32)
        smt = f"""(set-logic QF_BV)
(declare-const x (_ BitVec 32))
(declare-const b (_ BitVec 32))
(assert (not (= (bvmul (_ bv{inverse} 32) (bvsub (bvadd (bvmul (_ bv{a} 32) x) b) b)) x)))
""" + CHECK
        answer = run(args.z3, smt)
        if answer != "unsat":
            raise AssertionError(f"round-trip a={a}: {answer}")
        inverses.append({"a": a, "inverse": inverse, "result": answer})
    print("PASS round-trip: all x and b, for six explicitly listed odd multipliers")
    # A missing -b correction must be falsifiable. Save a real counterexample.
    mutant = """(set-logic QF_BV)
(declare-const a (_ BitVec 32))
(declare-const b (_ BitVec 32))
(declare-const x (_ BitVec 32))
(declare-const y (_ BitVec 32))
(assert (= a (_ bv3 32)))
(assert (not (= (bvadd (bvadd (bvmul a x) b) (bvadd (bvmul a y) b))
               (bvadd (bvmul a (bvadd x y)) b))))
""" + CHECK
    if run(args.z3, mutant) != "sat":
        raise AssertionError("mutated addition rule did not produce a counterexample")
    counterexample = run(args.z3, mutant + "(get-value (a b x y))\n")
    print("PASS incorrect-rule control: sat with a counterexample")
    report = {"solver": subprocess.check_output([args.z3, "-version"], text=True).strip(),
              "contract_sha256": hashlib.sha256(contract.read_bytes()).hexdigest(),
              "generic_rules": dict(zip(("add", "subtract", "scale"), output)),
              "xor_contract_sha256": hashlib.sha256(xor_contract.read_bytes()).hexdigest(),
              "xor_rules": dict(zip(("xor", "and", "or", "not", "shl", "lshr"), xor_answers)),
              "newton_steps": newton,
              "split_scale": {"sha256": hashlib.sha256(split_contract.read_bytes()).hexdigest(), "result": split_answer},
              "concrete_multiplier_roundtrips": inverses,
              "negative_control": counterexample, "seconds": time.perf_counter() - start,
              "scope": "Solver-checked bit-vector formulas; not a proof of the C-to-C implementation."}
    if args.report:
        Path(args.report).write_text(json.dumps(report, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--z3", default="z3")
    parser.add_argument("--report")
    main(parser.parse_args())
