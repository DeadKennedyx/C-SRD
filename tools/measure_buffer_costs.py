#!/usr/bin/env python3
"""Paired cost pilot for the fixed benign buffer_update benchmark interface."""
import argparse
import json
from pathlib import Path
import platform
import shutil
import statistics

from audit_protection import Runner, file_hash, executable
from experiment_support import paired_costs

ROOT = Path(__file__).resolve().parents[1]
DRIVER = r'''#define _POSIX_C_SOURCE 200809L
#ifdef __APPLE__
#define _DARWIN_C_SOURCE
#endif
#include <stdint.h>
#include <inttypes.h>
#include <stdlib.h>
#include <stdio.h>
#include <time.h>
#include <sys/resource.h>
uint32_t buffer_update(uint32_t*,const uint32_t*,uint32_t);
static uint32_t next(uint32_t *s){*s^=*s<<13;*s^=*s>>17;*s^=*s<<5;return *s;}
static double seconds(struct timespec a,struct timespec b){return (double)(b.tv_sec-a.tv_sec)+(double)(b.tv_nsec-a.tv_nsec)*1e-9;}
int main(int argc,char**argv){
    if(argc!=3)return 3;
    unsigned long n=strtoul(argv[1],0,10);
    uint32_t state=(uint32_t)strtoul(argv[2],0,10),p[4]={0,0,7,9},q[4]={0,0,3,5};
    uint64_t sum=0;
    struct timespec wall_a,wall_b,cpu_a,cpu_b;
    if(clock_gettime(CLOCK_MONOTONIC,&wall_a)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&cpu_a))return 2;
    for(unsigned long i=0;i<n;++i){
        p[0]=next(&state);q[0]=next(&state);uint32_t x=next(&state);
        sum+=buffer_update(p,(i&1u)?p:q,x);sum+=p[1];
    }
    if(clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&cpu_b)||clock_gettime(CLOCK_MONOTONIC,&wall_b))return 2;
    if(p[2]!=7||p[3]!=9||q[2]!=3||q[3]!=5)return 4;
    struct rusage usage;if(getrusage(RUSAGE_SELF,&usage))return 2;
    uint64_t rss=(uint64_t)usage.ru_maxrss;
#ifndef __APPLE__
    rss*=1024u;
#endif
    printf("%.9f %" PRIu64 " %.9f %" PRIu64 "\n",seconds(wall_a,wall_b),sum,seconds(cpu_a,cpu_b),rss);
    return 0;
}
'''


def run(args):
    root = Path(args.output_dir).resolve(); root.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "status": "running", "platform": platform.platform(), "commands": [],
              "iterations": args.iterations, "repetitions": args.repetitions, "order_seed": 20261110,
              "warmup_executions_per_binary": 1, "source": str(ROOT / "benchmarks/arithmetic/buffer_update.c"),
              "scope": "Fixed mixed alias/disjoint buffer_update workload including input generation; no reconstruction result",
              "rss_scope": "Whole-process peak RSS, including loader/harness; not data confidentiality or incremental heap use",
              "cells": []}
    command = Runner(report)
    try:
        csrd = executable(args.csrd)
        original = Path(report["source"])
        report["source_sha256"] = file_hash(original)
        report["adapter_sha256"] = file_hash(Path(__file__))
        report["csrd_sha256"] = file_hash(Path(csrd))
        driver = root / "driver.c"; driver.write_text(DRIVER)
        sources = {"original": original}
        for strategy in ("identity", "affine"):
            sources[strategy] = root / f"{strategy}.c"
            command([csrd, "transform", original, "-o", sources[strategy], "--strategy", strategy,
                     "--seed", 42, "--report", root / f"{strategy}.json"])
            decision, = json.loads((root / f"{strategy}.json").read_text())["functions"]
            if decision["verification"] != "proved-under-model": raise ValueError("candidate not validated")
        # Complete every build before starting resource measurements.
        for compiler_index, name in enumerate(args.compiler):
            compiler = executable(name)
            version = command([compiler, "--version"]).splitlines()[0]
            for optimization in args.optimization:
                cell = {"compiler": compiler, "version": version, "optimization": optimization, "variants": []}
                directory = root / f"compiler-{compiler_index}-{optimization}"; directory.mkdir()
                flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", "-" + optimization]
                command([compiler, *flags, "-c", driver, "-o", directory / "driver.o"])
                for variant, source in sources.items():
                    obj = directory / f"{variant}.o"; binary = directory / variant
                    command([compiler, *flags, "-c", source, "-o", obj])
                    compile_seconds = report["commands"][-1]["elapsed_seconds"]
                    command([compiler, *flags, directory / "driver.o", obj, "-o", binary])
                    cell["variants"].append({"variant": variant, "binary": str(binary), "binary_bytes": binary.stat().st_size,
                                             "binary_sha256": file_hash(binary), "object_bytes": obj.stat().st_size,
                                             "source_compile_wall_seconds": compile_seconds,
                                             "link_wall_seconds": report["commands"][-1]["elapsed_seconds"]})
                baseline = cell["variants"][0]
                copy = directory / "original-copy"; shutil.copyfile(baseline["binary"], copy); copy.chmod(0o755)
                cell["variants"].append({**baseline, "variant": "original-copy", "binary": str(copy),
                                         "source_compile_wall_seconds": None, "link_wall_seconds": None,
                                         "copied_from": baseline["binary"]})
                report["cells"].append(cell)
        for cell in report["cells"]:
            variants = cell["variants"]
            by_binary = {r["binary"]: r for r in variants}
            for record in variants:
                record["cpu_seconds"] = []; record["peak_rss_bytes"] = []
                command([record["binary"], args.iterations, 20261109])

            def measured(argv):
                wall, checksum, cpu, rss = command(argv).split()
                record = by_binary[argv[0]]
                record["cpu_seconds"].append(float(cpu)); record["peak_rss_bytes"].append(int(rss))
                return wall + " " + checksum

            paired_costs(measured, variants, args.iterations, args.repetitions, 20261110)
            base = variants[0]
            for record in variants:
                if min(record["cpu_seconds"]) <= 0: raise ValueError("CPU timing resolution insufficient")
                record["cpu_paired_ratios"] = [x/y for x, y in zip(record["cpu_seconds"], base["cpu_seconds"])]
                record["cpu_median_paired_ratio"] = statistics.median(record["cpu_paired_ratios"])
                record["peak_rss_median_bytes"] = statistics.median(record["peak_rss_bytes"])
                if file_hash(Path(record["binary"])) != record["binary_sha256"]:
                    raise ValueError("binary changed during measurement")
        if file_hash(original) != report["source_sha256"]: raise ValueError("source changed")
        report["status"] = "measured"
    except Exception as error:
        report["status"] = "failed"
        report["error"] = str(error)
        raise
    finally:
        (root / "costs.json").write_text(json.dumps(report, indent=2) + "\n")
    print(f"Measured {len(report['cells'])} build conditions with identity and identical-byte controls")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csrd", required=True)
    parser.add_argument("--compiler", action="append", required=True)
    parser.add_argument("--optimization", choices=("O0", "O2", "O3", "Os"), action="append")
    parser.add_argument("--iterations", type=int, default=10000000)
    parser.add_argument("--repetitions", type=int, default=7)
    parser.add_argument("--output-dir", required=True)
    args = parser.parse_args()
    if args.iterations < 1 or args.repetitions < 2: parser.error("positive iterations and at least two repetitions required")
    args.optimization = args.optimization or ["O0", "O2"]
    run(args)
