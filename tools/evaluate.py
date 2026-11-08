#!/usr/bin/env python3
"""Independent finite behavioral recognition and controlled compiler measurements.

C structure is measured by Clang through `csrd analyze`, never by C text parsing.
The fingerprint classifier uses only outputs, not transformation metadata.
"""
import argparse
from collections import Counter
import hashlib
import itertools
import json
from pathlib import Path
import platform
import random
import re
import shutil
import statistics
import struct
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]
EDGES = [0, 1, 2, 3, 0x7fffffff, 0x80000000, 0x80000001, 0xfffffffe, 0xffffffff]
DRIVER = r'''#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
uint32_t kernel(uint32_t,uint32_t);
static uint32_t state=0x43535244u;
static uint32_t next(void){state^=state<<13;state^=state>>17;state^=state<<5;return state;}
int main(int argc,char **argv){
    if(argc==1){
        uint32_t x,y;
        while(scanf("%" SCNu32 " %" SCNu32,&x,&y)==2){
            printf("%" PRIu32 "\n",kernel(x,y));
        }
        return 0;
    }
    unsigned long count=strtoul(argv[1],0,10);
    uint32_t x[4096],y[4096];for(unsigned i=0;i<4096;++i){x[i]=next();y[i]=next();}
    uint64_t sum=0;for(unsigned i=0;i<4096;++i)sum+=kernel(x[i],y[i]);
    struct timespec start,end;
    if(clock_gettime(CLOCK_MONOTONIC,&start))return 2;
    for(unsigned long i=0;i<count;++i)sum+=kernel(x[i&4095u],y[i&4095u]);
    if(clock_gettime(CLOCK_MONOTONIC,&end))return 2;
    double elapsed=(double)(end.tv_sec-start.tv_sec)+(double)(end.tv_nsec-start.tv_nsec)*1e-9;
    printf("%.9f %" PRIu64 "\n",elapsed,sum);return 0;
}
'''


def command(args, **kwargs):
    start = time.perf_counter()
    p = subprocess.run([str(x) for x in args], text=True, capture_output=True, timeout=120, **kwargs)
    if p.returncode:
        raise RuntimeError(f"command failed ({p.returncode}): {args}\n{p.stdout}\n{p.stderr}")
    return p.stdout, time.perf_counter() - start


def digest(data):
    return hashlib.sha256(data).hexdigest()


def inputs(seed, count, challenge=False):
    rng = random.Random(seed)
    result = list(itertools.product(EDGES, repeat=2)) + [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(count)]
    if challenge:
        result.append((0x43535244, 0))
    return result


def fingerprint(binary, pairs):
    output, _ = command([binary], input="".join(f"{x} {y}\n" for x, y in pairs))
    values = [int(x) for x in output.splitlines()]
    if len(values) != len(pairs) or any(x < 0 or x > 0xffffffff for x in values):
        raise RuntimeError("invalid fingerprint output")
    return digest(b"".join(struct.pack("<I", x) for x in values))


def score(records, key):
    counts = {"true_positive": 0, "true_negative": 0, "false_positive": 0, "false_negative": 0}
    errors = []
    for a, b in itertools.combinations(records, 2):
        same = a[key] == b[key]
        truth = a["family"] == b["family"]
        label = ("true_" if same == truth else "false_") + ("positive" if same else "negative")
        counts[label] += 1
        if same != truth:
            errors.append({"left": a["id"], "right": b["id"], "classification": label})
    total = sum(counts.values())
    return {**counts, "pairs": total, "accuracy": (counts["true_positive"] + counts["true_negative"])/total if total else None,
            "errors": errors}


def histogram_distance(a, b):
    keys = set(a) | set(b)
    denominator = sum(max(a.get(k, 0), b.get(k, 0)) for k in keys)
    return sum(abs(a.get(k, 0)-b.get(k, 0)) for k in keys)/denominator if denominator else 0.0


def object_metrics(objdump, path):
    headers, _ = command([objdump, "--section-headers", path])
    sections = []
    for line in headers.splitlines():
        fields = line.split()
        if len(fields) >= 3 and fields[1] in (".text", "__text"):
            sections.append((fields[1], int(fields[2], 16)))
    if len(sections) != 1:
        raise RuntimeError(f"expected one code section in {path}: {sections}")
    section, size = sections[0]
    contents, _ = command([objdump, "--full-contents", "--section=" + section, path])
    raw = bytearray()
    for line in contents.splitlines():
        match = re.match(r"\s*[0-9a-fA-F]+\s+((?:[0-9a-fA-F]{2,8}(?:\s|$)){1,4})", line)
        if match:
            raw.extend(bytes.fromhex(match[1]))
    if len(raw) != size:
        raise RuntimeError(f"text extraction mismatch: {len(raw)} != {size}")
    assembly, _ = command([objdump, "--disassemble", "--no-show-raw-insn", path])
    opcodes = Counter()
    for line in assembly.splitlines():
        match = re.match(r"\s*[0-9a-fA-F]+:\s+([a-zA-Z][a-zA-Z0-9.]*)", line)
        if match:
            opcodes[match[1]] += 1
    return {"text_bytes": size, "text_sha256": digest(raw), "instruction_histogram": dict(opcodes),
            "scope": "whole single-function object code section, including padding; relocations not applied"}


def ir_metrics(path):
    # LLVM IR instruction spelling is parsed here; this is not a C parser.
    histogram = Counter()
    inside = False
    for line in path.read_text().splitlines():
        if line.startswith("define "):
            inside = True
        elif line == "}":
            inside = False
        elif inside:
            line = line.strip()
            if " = " in line:
                line = line.split(" = ", 1)[1]
            if line and not line.startswith((";", "!")) and not line.split(";", 1)[0].strip().endswith(":"):
                opcode = line.split()[0]
                if opcode.isalpha():
                    histogram[opcode] += 1
    return {"instruction_histogram": dict(histogram), "raw_sha256": digest(path.read_bytes())}


def analyze(csrd, source):
    output, _ = command([csrd, "analyze", source, "--function", "kernel"])
    report = json.loads(output)
    functions = report["functions"]
    if len(functions) != 1 or functions[0]["parameter_count"] != 2:
        raise RuntimeError("evaluation corpus requires one two-argument kernel")
    return functions[0]["source_metrics"]


def run(args):
    root = Path(args.output_dir).resolve()
    root.mkdir(parents=True, exist_ok=False)
    driver = root / "driver.c"
    driver.write_text(DRIVER)
    corpus_path = Path(args.corpus).resolve()
    corpus = json.loads(corpus_path.read_text())
    if corpus["function"] != "kernel" or corpus["arity"] != 2:
        raise RuntimeError("unsupported corpus interface")
    variants = []
    for case in corpus["cases"]:
        original = (corpus_path.parent / case["source"]).resolve()
        base = {**case, "id": case["id"] + "/original", "source": str(original), "strategy": "original",
                "baseline": case["id"] + "/original", "sha256": digest(original.read_bytes()),
                "source_metrics": analyze(args.csrd, original)}
        variants.append(base)
        for strategy in args.strategy:
            directory = root / case["id"] / strategy
            directory.mkdir(parents=True)
            source, manifest = directory / "variant.c", directory / "transform.json"
            _, elapsed = command([args.csrd, "transform", original, "-o", source, "--strategy", strategy,
                                  "--seed", args.seed, "--report", manifest, "--timeout-ms", 30000])
            record = json.loads(manifest.read_text())["functions"][0]
            if record["status"] != "transformed" or record["verification"] != "proved-under-model":
                raise RuntimeError(f"unverified transform: {case['id']}: {record}")
            validation = directory / "verification.json"
            _, verify_seconds = command([args.csrd, "verify", original, source, "--report", validation, "--timeout-ms", 30000])
            # Keep complete obligations in artifacts; report costs/status and hashes.
            record = {k: v for k, v in record.items() if k not in ("proof", "graph", "source_metrics")}
            variants.append({**base, "id": case["id"] + "/" + strategy, "source": str(source), "strategy": strategy,
                             "sha256": digest(source.read_bytes()), "source_metrics": analyze(args.csrd, source),
                             "transform_and_validation_seconds": elapsed, "standalone_verification_seconds": verify_seconds,
                             "transformation": record})
    discovery = inputs(20261108, args.inputs)
    heldout = inputs(20261109, args.inputs, challenge=True)
    configs = []
    for compiler in args.compiler:
        executable = shutil.which(compiler)
        if not executable:
            raise RuntimeError(f"compiler unavailable: {compiler}")
        version = command([executable, "--version"])[0].splitlines()[0]
        for optimization in ("-O0", "-O2"):
            print(f"Evaluating {version} {optimization}", flush=True)
            directory = root / (Path(executable).name + optimization)
            directory.mkdir()
            flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", optimization]
            driver_obj = directory / "driver.o"
            command([executable, *flags, "-c", driver, "-o", driver_obj])
            records = []
            for index, variant in enumerate(variants):
                stem = directory / str(index)
                obj, binary, ir = stem.with_suffix(".o"), stem.with_suffix(".exe"), stem.with_suffix(".ll")
                _, compile_seconds = command([executable, *flags, "-c", variant["source"], "-o", obj])
                command([executable, *flags, obj, driver_obj, "-o", binary])
                r = {**variant, "binary": str(binary), "compile_seconds": compile_seconds,
                     "object": object_metrics(args.objdump, obj), "samples_seconds": [], "checksums": [],
                     "discovery_fingerprint": fingerprint(binary, discovery), "heldout_fingerprint": fingerprint(binary, heldout)}
                if "clang" in version.lower():
                    command([executable, *flags, "-S", "-emit-llvm", variant["source"], "-o", ir])
                    r["llvm_ir"] = ir_metrics(ir)
                records.append(r)
            # Interleave variants; reproducibly shuffle each repetition to reduce order bias.
            rng = random.Random(20261110)
            for _ in range(args.repetitions):
                order = list(range(len(records))); rng.shuffle(order)
                for i in order:
                    values = command([records[i]["binary"], args.iterations])[0].split()
                    records[i]["samples_seconds"].append(float(values[0]))
                    records[i]["checksums"].append(int(values[1]))
            by_id = {r["id"]: r for r in records}
            for r in records:
                r["median_seconds"] = statistics.median(r["samples_seconds"])
                quartiles = statistics.quantiles(r["samples_seconds"], n=4)
                r["iqr_seconds"] = quartiles[2] - quartiles[0]
                baseline = by_id[r["baseline"]]
                if r["discovery_fingerprint"] != baseline["discovery_fingerprint"] or r["heldout_fingerprint"] != baseline["heldout_fingerprint"]:
                    raise RuntimeError(f"differential mismatch: {r['id']}")
                if r["checksums"] != baseline["checksums"]:
                    raise RuntimeError(f"benchmark checksum mismatch: {r['id']}")
                r["runtime_ratio"] = r["median_seconds"] / statistics.median(baseline["samples_seconds"])
                r["text_size_ratio"] = r["object"]["text_bytes"] / baseline["object"]["text_bytes"]
                r["machine_histogram_distance"] = histogram_distance(r["object"]["instruction_histogram"], baseline["object"]["instruction_histogram"])
                r["source_operator_distance"] = histogram_distance(r["source_metrics"]["operators"], baseline["source_metrics"]["operators"])
                if "llvm_ir" in r:
                    r["llvm_histogram_distance"] = histogram_distance(r["llvm_ir"]["instruction_histogram"], baseline["llvm_ir"]["instruction_histogram"])
            configs.append({"compiler": version, "compiler_path": executable, "flags": flags, "records": records,
                            "discovery_recognition": score(records, "discovery_fingerprint"),
                            "heldout_recognition": score(records, "heldout_fingerprint")})
    result = {"schema_version": 1, "platform": platform.platform(), "csrd": command([args.csrd, "--version"])[0].splitlines()[0],
              "objdump": command([args.objdump, "--version"])[0].splitlines()[0], "seed": args.seed,
              "corpus_sha256": digest(corpus_path.read_bytes()), "driver_sha256": digest(DRIVER.encode()),
              "random_inputs_per_split": args.inputs, "discovery_seed": 20261108, "heldout_seed": 20261109,
              "discovery_pairs": len(discovery), "heldout_pairs": len(heldout), "challenge": [0x43535244, 0],
              "iterations": args.iterations, "repetitions": args.repetitions, "configurations": configs,
              "scope": "Finite fingerprints are evidence, not proofs. Ground-truth families are curated independently. The explicit held-out challenge is an adversarial negative control, not unbiased generalization evidence. Timing includes call, array indexing and accumulation; one object compilation per case; no LTO; no CPU pinning. Size is object code, not executable size. Histograms and CFG adjacency hashes are structural proxies, not semantic or graph-isomorphism tests."}
    (root / "report.json").write_text(json.dumps(result, indent=2) + "\n")
    print(root / "report.json")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--csrd", required=True)
    p.add_argument("--corpus", default=str(ROOT / "benchmarks/corpus.json"))
    p.add_argument("--output-dir", required=True)
    p.add_argument("--compiler", action="append", required=True)
    p.add_argument("--objdump", default="llvm-objdump")
    p.add_argument("--strategy", action="append", choices=["identity", "affine", "xor", "independent", "planned"])
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--inputs", type=int, default=1024)
    p.add_argument("--iterations", type=int, default=1000000)
    p.add_argument("--repetitions", type=int, default=7)
    a = p.parse_args()
    if a.inputs < 1 or a.iterations < 1 or a.repetitions < 2:
        p.error("inputs/iterations must be positive and repetitions >= 2")
    a.strategy = a.strategy or ["affine", "independent", "planned"]
    run(a)
