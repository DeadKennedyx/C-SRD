"""Measurements and bounded observers. No C source parsing or rewriting here."""
from collections import Counter
import hashlib
import itertools
import json
import math
from pathlib import Path
import random
import re
import statistics
from string import Template
import time

MASK = 2**32 - 1
EDGES = [0, 1, 2, 3, 0x7fffffff, 0x80000000, 0xfffffffe, MASK]


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def input_vectors(arity, seed, count):
    if not 1 <= arity <= 4:
        raise ValueError("experiment harness supports one to four u32 parameters")
    rng = random.Random(seed)
    # Bound edge combinations for four-argument functions.
    edges = list(itertools.product(EDGES, repeat=arity))[:512]
    return edges + [tuple(rng.getrandbits(32) for _ in range(arity)) for _ in range(count)]


def driver_source(function, arity):
    # Name/arity originate exclusively in Clang's admitted function report.
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", function) or not 1 <= arity <= 4:
        raise ValueError("invalid harness interface")
    prototype = ",".join(["uint32_t"] * arity)
    scan = " ".join(['"%" SCNu32'] * arity)
    addresses = ",".join(f"&x[{i}]" for i in range(arity))
    arguments = ",".join(f"x[{i}]" for i in range(arity))
    helper = "csrd_matrix_next_value"
    while helper == function:
        helper += "_1"
    return Template(r'''#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
uint32_t $function($prototype);
static uint32_t $helper(uint32_t *s) {
    *s ^= *s << 13; *s ^= *s >> 17; *s ^= *s << 5; return *s;
}
int main(int argc, char **argv) {
    uint32_t x[$arity];
    if (argc == 1) {
        while (scanf($scan, $addresses) == $arity)
            printf("%" PRIu32 "\n", $function($arguments));
        return 0;
    }
    if (argc != 3) return 3;
    unsigned long n = strtoul(argv[1], 0, 10);
    uint32_t state = (uint32_t)strtoul(argv[2], 0, 10);
    uint64_t sum = 0;
    struct timespec begin, end;
    if (clock_gettime(CLOCK_MONOTONIC, &begin)) return 2;
    for (unsigned long i = 0; i < n; ++i) {
        for (unsigned j = 0; j < $arity; ++j) x[j] = $helper(&state);
        sum += $function($arguments);
    }
    if (clock_gettime(CLOCK_MONOTONIC, &end)) return 2;
    double elapsed = (double)(end.tv_sec - begin.tv_sec) +
                     (double)(end.tv_nsec - begin.tv_nsec) * 1e-9;
    printf("%.9f %" PRIu64 "\n", elapsed, sum);
    return 0;
}
''').substitute(function=function, prototype=prototype, helper=helper, arity=arity,
                scan=scan, addresses=addresses, arguments=arguments)


def outputs(command, binary, vectors):
    result = command([binary], input="".join(" ".join(map(str, v)) + "\n" for v in vectors))
    values = [int(v) for v in result.splitlines()]
    if len(values) != len(vectors) or any(v < 0 or v > MASK for v in values):
        raise ValueError("invalid executable output stream")
    return values


def assembly_metrics(text, symbols):
    """Parse objdump, not C. Mnemonic sequences ignore operands/register allocation."""
    functions = {}
    current = None
    for line in text.splitlines():
        label = re.match(r"^\s*([0-9a-fA-F]+) <([^>]+)>:", line)
        if label:
            name = label[2] if label[2] in symbols else label[2].removeprefix("_")
            current = name if name in symbols else None
            if current:
                functions[current] = []
            continue
        insn = re.match(r"^\s*([0-9a-fA-F]+):\s+([a-zA-Z][a-zA-Z0-9.]*)\s*(.*)", line)
        if current and insn:
            functions[current].append({"address": int(insn[1], 16),
                                       "opcode": insn[2], "operands": insn[3].strip()})
    if "main" not in functions:
        raise ValueError("linked main was not found in disassembly")
    sequences = {k: [i["opcode"] for i in v if i["opcode"] not in ("nop", "nopl", "nopw")]
                 for k, v in sorted(functions.items())}
    histogram = dict(Counter(i for seq in sequences.values() for i in seq))
    return {"functions": functions, "opcode_sequences": sequences,
            "opcode_sha256": digest(sequences), "instruction_histogram": histogram,
            "instruction_count": sum(map(len, sequences.values())),
            "scope": "main and surviving named function; mnemonic sequences excluding nop/nopl/nopw; not machine data-flow equivalence"}


def ir_structure(text, function):
    """Normalize SSA names/block labels while retaining operand relationships.

    LLVM textual IR only. Not a C parser, a semantic equivalence test, or a full
    LLVM parser. Attributes/metadata and other functions are outside this metric.
    """
    inside, lines, names = False, [], {}

    def rename(match):
        key = match[0]
        if key not in names:
            names[key] = f"%v{len(names)}"
        return names[key]

    for line in text.splitlines():
        if line.startswith("define ") and (f"@{function}(" in line or f'@"{function}"(' in line):
            inside = True
            for name in re.findall(r'%[-A-Za-z$._0-9]+', line):
                if name not in names:
                    names[name] = f"%v{len(names)}"
            continue
        if not inside:
            continue
        if line.strip() == "}":
            break
        line = line.split(";", 1)[0].strip()
        if not line:
            continue
        label = re.fullmatch(r"([-A-Za-z$._0-9]+):", line)
        if label:
            key = "%" + label[1]
            if key not in names:
                names[key] = f"%v{len(names)}"
            lines.append(names[key] + ":")
        else:
            line = re.sub(r",\s*![A-Za-z0-9_.]+\s+![0-9]+", "", line)
            lines.append(re.sub(r'%[-A-Za-z$._0-9]+', rename, line))
    if not inside or not lines:
        raise ValueError("named LLVM function not found")
    return {"normalized_ssa": lines, "ssa_sha256": digest(lines),
            "scope": "pre-link optimized LLVM function; normalized SSA operand/label relationships"}


def paired_costs(command, records, iterations, repetitions, seed):
    """Interleave executions; report paired ratios, never infer cost from bytes."""
    rng = random.Random(seed)
    for r in records:
        r["timing"] = {"samples_seconds": [], "checksums": [],
                       "iterations": iterations,
                       "scope": "linked harness including deterministic input generation; not isolated function latency"}
    for repetition in range(repetitions):
        order = records[:]
        rng.shuffle(order)
        for r in order:
            elapsed, checksum = command([r["binary"], iterations, seed + repetition]).split()
            elapsed = float(elapsed)
            if elapsed <= 0:
                raise ValueError("timing resolution insufficient")
            r["timing"]["samples_seconds"].append(elapsed)
            r["timing"]["checksums"].append(int(checksum))
    base = next(r for r in records if r["variant"] == "original")
    for r in records:
        if r["timing"]["checksums"] != base["timing"]["checksums"]:
            raise ValueError("benchmark checksum mismatch")
        t, b = r["timing"], base["timing"]
        ratios = [a / c for a, c in zip(t["samples_seconds"], b["samples_seconds"])]
        t.update(median_seconds=statistics.median(t["samples_seconds"]),
                 paired_ratios=ratios, median_paired_ratio=statistics.median(ratios),
                 min_paired_ratio=min(ratios), max_paired_ratio=max(ratios))
        r["binary_size_ratio"] = r["binary_bytes"] / base["binary_bytes"]


def reconstruct(command, binary, arity, heldout, expected):
    """Fixed black-box observer: basis-query affine fit and small known-function library.

    Receives only the executable interface, never candidate source, seed, encoding
    parameters, compiler metrics, or truth labels. Held-out outputs score frozen fits.
    """
    start = time.perf_counter()
    basis = [tuple([0] * arity)] + [tuple(int(i == j) for i in range(arity)) for j in range(arity)]
    probes = basis + input_vectors(arity, 19011, 12)
    values = outputs(command, binary, probes)
    b = values[0]
    coefficients = [(values[j + 1] - b) & MASK for j in range(arity)]
    models = [("affine", {"coefficients": coefficients, "offset": b},
               lambda x: (b + sum(a * v for a, v in zip(coefficients, x))) & MASK)]
    if arity == 1:
        models.append(("popcount-low-byte", {}, lambda x: (x[0] & 255).bit_count()))
    if arity == 2:
        models.extend([("xor", {}, lambda x: x[0] ^ x[1]),
                       ("unsigned-minimum", {}, lambda x: min(x))])
    fitted = [(name, parameters, fn) for name, parameters, fn in models
              if all(fn(x) == y for x, y in zip(probes, values))]
    scored = [{"model": name, "parameters": parameters,
               "heldout_correct": sum(fn(x) == y for x, y in zip(heldout, expected)),
               "heldout_total": len(heldout)}
              for name, parameters, fn in fitted]
    recovered = any(m["heldout_correct"] == m["heldout_total"] for m in scored)
    return {"observer": "fixed-basis-affine-and-library-v1", "training_queries": len(probes),
            "heldout_queries": len(heldout), "elapsed_seconds": time.perf_counter() - start,
            "fitted_models": scored, "recovered_on_heldout": recovered,
            "false_models": sum(m["heldout_correct"] != m["heldout_total"] for m in scored),
            "evidence": "finite black-box recovery, not universal equivalence or human analyst effort"}


def select_candidates(records, required_profiles, max_runtime_ratio, max_size_ratio):
    """Selection uses development measurements only; incomplete candidates fail closed."""
    if (not required_profiles or not all(math.isfinite(v) and v >= 1
                                        for v in (max_runtime_ratio, max_size_ratio))):
        raise ValueError("selection requires profiles and budgets >= 1")
    if any(r.get("split") != "development" for r in records):
        raise ValueError("held-out measurements must not be used for selection")
    decisions = []
    for case in sorted({r["case"] for r in records}):
        subset = [r for r in records if r["case"] == case]
        variants = sorted({r["variant"] for r in subset} - {"original", "identity"})
        eligible = []
        for variant in variants:
            cells = [r for r in subset if r["variant"] == variant and r["profile"] in required_profiles]
            reasons = []
            if set(r["profile"] for r in cells if r["status"] == "completed") != set(required_profiles):
                reasons.append("missing-or-failed-required-profile")
            completed = [r for r in cells if r["status"] == "completed"]
            if any(not r["comparison"]["instruction_sequences_differ_from_original"] for r in completed):
                reasons.append("no-mnemonic-sequence-difference-in-required-profile")
            if any(r.get("strategy") in ("affine", "xor", "planned") and
                   r["comparison"].get("instruction_sequences_differ_from_algorithm_control") is not True
                   for r in completed):
                reasons.append("encoding-contribution-absent-or-unassessed")
            if any(r["timing"]["max_paired_ratio"] > max_runtime_ratio for r in completed):
                reasons.append("runtime-budget-exceeded")
            if any(r["binary_size_ratio"] > max_size_ratio for r in completed):
                reasons.append("binary-size-budget-exceeded")
            score = max((r["timing"]["max_paired_ratio"] for r in completed), default=None)
            decision = {"case": case, "variant": variant, "eligible": not reasons,
                        "reasons": reasons, "worst_observed_runtime_ratio": score}
            decisions.append(decision)
            if not reasons:
                eligible.append(decision)
        # Conservative candidate to investigate, not a claim of best protection.
        if eligible:
            min(eligible, key=lambda d: (d["worst_observed_runtime_ratio"], d["variant"]))["selected"] = True
    return {"decisions": decisions, "required_profiles": required_profiles,
            "budgets": {"max_runtime_ratio": max_runtime_ratio, "max_binary_size_ratio": max_size_ratio},
            "claim": "candidate prioritization using compiled measurements, not protection strength"}
