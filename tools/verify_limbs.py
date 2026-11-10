#!/usr/bin/env python3
"""Independent bit-vector obligations for positional two-limb arithmetic.

Scale is proved compositionally: distributivity for every factor, then a
universal carry/reassembly lemma for arbitrary partial products. This avoids a
large monolithic multiplier circuit. Neither lemma proves the C++ emitter.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def bv(value):
    return f"(_ bv{value} 32)"


def op(name, *args):
    return "(" + name + " " + " ".join(args) + ")"


def low(a):
    return op("bvand", a, bv(65535))


def high(a):
    return op("bvlshr", a, bv(16))


def join(a, b):
    return op("bvor", low(a), op("bvshl", low(b), bv(16)))


def obligations():
    a, h, b, j = low("x"), high("x"), low("y"), high("y")
    sum_low = op("bvadd", a, b)
    yield "roundtrip", join(a, h), "x", "unsat"
    yield "join-is-place-value-sum", join(a, h), op("bvadd", a, op("bvmul", h, bv(65536))), "unsat"
    yield "add", join(sum_low, op("bvadd", h, j, high(sum_low))), op("bvadd", "x", "y"), "unsat"
    borrow = op("ite", op("bvult", a, b), bv(1), bv(0))
    yield "subtract", join(op("bvsub", a, b), op("bvsub", op("bvsub", h, j), borrow)), op("bvsub", "x", "y"), "unsat"
    # For arbitrary p = low*k and q = high*k (mod 2^32):
    yield "scale-partial-products", join("x", op("bvadd", "y", high("x"))), op("bvadd", "x", op("bvmul", "y", bv(65536))), "unsat"
    # Arbitrary x/y here represent low/high, not necessarily normalized.
    yield "scale-distributivity", op("bvmul", op("bvadd", "x", op("bvmul", "y", bv(65536))), "k"), \
        op("bvadd", op("bvmul", "x", "k"), op("bvmul", "y", "k", bv(65536))), "unsat"
    for name in ("bvand", "bvor", "bvxor"):
        yield name, join(op(name, a, b), op(name, h, j)), op(name, "x", "y"), "unsat"
    yield "not", join(op("bvxor", a, bv(65535)), op("bvxor", h, bv(65535))), op("bvnot", "x"), "unsat"
    for n in range(32):
        left = (a, h) if n == 0 else ((bv(0), op("bvshl", a, bv(n-16))) if n >= 16 else
                (op("bvshl", a, bv(n)), op("bvor", op("bvshl", h, bv(n)), op("bvlshr", a, bv(16-n)))))
        right = (a, h) if n == 0 else ((op("bvlshr", h, bv(n-16)), bv(0)) if n >= 16 else
                 (op("bvor", op("bvlshr", a, bv(n)), op("bvshl", h, bv(16-n))), op("bvlshr", h, bv(n))))
        yield f"left-{n}", join(*left), op("bvshl", "x", bv(n)), "unsat"
        yield f"right-{n}", join(*right), op("bvlshr", "x", bv(n)), "unsat"
    for name in ("=", "distinct", "bvult", "bvule", "bvugt", "bvuge"):
        result = op("ite", op("=", h, j), op(name, a, b),
                    "false" if name == "=" else "true" if name == "distinct" else op(name, h, j))
        yield f"compare-{name}", result, op(name, "x", "y"), "unsat"
    condition = op("distinct", op("bvor", a, h), bv(0))
    yield "select", join(op("ite", condition, b, low("k")), op("ite", condition, j, high("k"))), \
        op("ite", op("distinct", "x", bv(0)), "y", "k"), "unsat"
    yield "wrong-no-borrow", join(op("bvsub", a, b), op("bvsub", h, j)), op("bvsub", "x", "y"), "sat"


def verify(z3):
    results = []
    for name, actual, expected, status in obligations():
        text = "(set-logic QF_BV)\n(set-option :timeout 10000)\n"
        text += "".join(f"(declare-const {v} (_ BitVec 32))\n" for v in ("x", "y", "k"))
        text += f"(assert (not (= {actual} {expected})))\n"
        text += "(check-sat-using (then (using-params simplify :som true) bit-blast sat))\n"
        if status == "sat":
            text += "(get-value (x y k))\n"
        answer = subprocess.run([z3, "-in"], input=text, text=True, capture_output=True, timeout=15)
        if answer.returncode or answer.stderr or answer.stdout.splitlines()[0] != status:
            raise AssertionError(f"limbs16 {name}: {answer.stdout} {answer.stderr}")
        results.append({"name": name, "result": status, "answer": answer.stdout.strip(),
                        "smt2": text, "sha256": hashlib.sha256(text.encode()).hexdigest()})
    return {"scope": "universal rule formulas with compositional scale proof; not proof of emitted C or secrecy",
            "obligations": results}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--z3", default="z3")
    parser.add_argument("--report", required=True)
    args = parser.parse_args()
    report = verify(args.z3)
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS {len(report['obligations'])} limb obligations (including incorrect-rule control)")
