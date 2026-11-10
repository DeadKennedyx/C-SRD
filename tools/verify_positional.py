#!/usr/bin/env python3
"""Universal 4/8-bit positional rules; independent of C++ generation.

Scale uses distributivity and an arbitrary-partial-product carry theorem. These
are arithmetic contracts, not authorization to publish unverified generated C.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

from verify_limbs import bv, op


def obligations(bits):
    count, mask = 32 // bits, (1 << bits) - 1
    cut = lambda value, i: op("bvand", op("bvlshr", value, bv(i * bits)), bv(mask))
    normalize = lambda value: op("bvand", value, bv(mask))
    def join(pieces):
        return op("bvor", *(op("bvshl", normalize(p), bv(i * bits)) for i, p in enumerate(pieces)))
    def positional_sum(pieces):
        return op("bvadd", *(op("bvmul", p, bv(1 << (i * bits))) for i, p in enumerate(pieces)))
    def carry(pieces):
        previous, result = bv(0), []
        for piece in pieces:
            total = op("bvadd", piece, previous)
            result.append(normalize(total))
            previous = op("bvlshr", total, bv(bits))
        return result
    a, b, c = [[cut(v, i) for i in range(count)] for v in ("x", "y", "k")]
    yield "roundtrip", join(a), "x", "unsat"
    yield "positional-sum", join(a), positional_sum(a), "unsat"
    yield "add", join(carry([op("bvadd", x, y) for x, y in zip(a, b)])), op("bvadd", "x", "y"), "unsat"
    borrow, difference = bv(0), []
    for x, y in zip(a, b):
        subtrahend = op("bvadd", y, borrow)
        difference.append(normalize(op("bvsub", x, subtrahend)))
        borrow = op("ite", op("bvult", x, subtrahend), bv(1), bv(0))
    yield "subtract", join(difference), op("bvsub", "x", "y"), "unsat"
    partials = [f"p{i}" for i in range(count)]
    yield "scale-partial-products", join(carry(partials)), positional_sum(partials), "unsat"
    yield "scale-distributivity", op("bvmul", positional_sum(a), "k"), \
        positional_sum([op("bvmul", piece, "k") for piece in a]), "unsat"
    outputs = [f"q{i}" for i in range(count)]
    carries = [bv(0), *(f"c{i}" for i in range(1, count)), bv(0)]
    errors = [op("bvsub", op("bvsub", op("bvadd", outputs[i], op("bvmul", bv(1 << bits), carries[i + 1])),
                 op("bvmul", partials[i], "k")), carries[i]) for i in range(count)]
    defect = op("bvsub", positional_sum(outputs), op("bvmul", positional_sum(partials), "k"))
    yield "scale-telescoping-bridge", positional_sum(errors), defect, "unsat"
    wrong_errors = list(errors)
    wrong_errors[1] = op("bvadd", wrong_errors[1], carries[1])
    yield "wrong-bridge-missing-carry", positional_sum(wrong_errors), defect, "sat"
    for name in ("bvand", "bvor", "bvxor"):
        yield name, join([op(name, x, y) for x, y in zip(a, b)]), op(name, "x", "y"), "unsat"
    yield "not", join([op("bvxor", x, bv(mask)) for x in a]), op("bvnot", "x"), "unsat"
    for amount in range(32):
        whole, rest = divmod(amount, bits)
        for left, name in ((True, "bvshl"), (False, "bvlshr")):
            result = []
            for i in range(count):
                source = i - whole if left else i + whole
                if not 0 <= source < count:
                    result.append(bv(0)); continue
                value = op(name, a[source], bv(rest))
                neighbor = source - 1 if left else source + 1
                if rest and 0 <= neighbor < count:
                    value = op("bvor", value, op("bvlshr" if left else "bvshl", a[neighbor], bv(bits - rest)))
                result.append(normalize(value))
            yield f"{name}-{amount}", join(result), op(name, "x", bv(amount)), "unsat"
    for name in ("=", "distinct", "bvult", "bvule", "bvugt", "bvuge"):
        result = op(name, a[0], b[0])
        for i in range(1, count):
            unequal = "false" if name == "=" else "true" if name == "distinct" else op(name, a[i], b[i])
            result = op("ite", op("=", a[i], b[i]), result, unequal)
        yield "compare-" + name, result, op(name, "x", "y"), "unsat"
    nonzero = op("distinct", op("bvor", *a), bv(0))
    yield "select", join([op("ite", nonzero, x, y) for x, y in zip(b, c)]), \
        op("ite", op("distinct", "x", bv(0)), "y", "k"), "unsat"
    yield "wrong-no-borrow", join([op("bvsub", x, y) for x, y in zip(a, b)]), op("bvsub", "x", "y"), "sat"
    yield "wrong-no-carry", join([op("bvadd", x, y) for x, y in zip(a, b)]), op("bvadd", "x", "y"), "sat"
    yield "wrong-truncated-factor", op("bvmul", "x", normalize("k")), op("bvmul", "x", "k"), "sat"


def verify(z3, report_path):
    report = {"scope": "universal arithmetic formulas; generated C requires independent translation validation",
              "status": "running", "obligations": []}
    for bits in (8, 4):
        variables = ["x", "y", "k", *(f"p{i}" for i in range(32 // bits)),
                     *(f"q{i}" for i in range(32 // bits)), *(f"c{i}" for i in range(1, 32 // bits))]
        for name, actual, expected, status in obligations(bits):
            text = "(set-logic QF_BV)\n(set-option :timeout 10000)\n"
            text += "".join(f"(declare-const {v} (_ BitVec 32))\n" for v in variables)
            text += f"(assert (not (= {actual} {expected})))\n"
            text += "(check-sat-using (then (using-params simplify :som true) bit-blast sat))\n"
            if status == "sat": text += "(get-value (" + " ".join(variables) + "))\n"
            answer = subprocess.run([z3, "-in"], input=text, text=True, capture_output=True, timeout=15)
            result = answer.stdout.splitlines()[0] if answer.stdout else "missing-answer"
            row = {"bits": bits, "name": name, "expected": status, "result": result,
                   "returncode": answer.returncode, "stdout": answer.stdout, "stderr": answer.stderr,
                   "smt2": text, "sha256": hashlib.sha256(text.encode()).hexdigest()}
            report["obligations"].append(row)
            ok = not answer.returncode and not answer.stderr and result == status
            if not ok: report["status"] = "failed"
            report_path.write_text(json.dumps(report, indent=2) + "\n")
            if not ok: raise AssertionError(f"limbs{bits} {name}: {answer.stdout} {answer.stderr}")
    report["status"] = "completed"
    report_path.write_text(json.dumps(report, indent=2) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--z3", default="z3")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    report = verify(args.z3, args.report)
    print(f"PASS {len(report['obligations'])} positional obligations, including eight incorrect-rule controls")
