#!/usr/bin/env python3
"""Matched byte-buffer throughput and exact code-size measurements on Linux ELF64."""
import argparse
import fcntl
import json
from pathlib import Path
import random
import statistics

from audit_protection import Runner, file_hash, write_json
from byte_observation_cases import signature
from effort_resources import environment, measurement_lock
from inspect_region_binaries import elf_functions


def harness(function,parameters):
    byte_type,declaration=signature(function,parameters)
    return r'''#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
#include <sys/resource.h>
'''+declaration+r'''
static uint32_t next(uint32_t*s){*s^=*s<<13;*s^=*s>>17;*s^=*s<<5;return *s;}
static double elapsed(struct timespec a,struct timespec b){return (double)(b.tv_sec-a.tv_sec)+(double)(b.tv_nsec-a.tv_nsec)*1e-9;}
int main(int argc,char**argv){
 if(argc!=3)return 2;
 unsigned long n=strtoul(argv[1],0,10);uint32_t state=(uint32_t)strtoul(argv[2],0,10);
 uint32_t memory[64];for(unsigned i=0;i<64;++i)memory[i]=next(&state);
 uint64_t checksum=0;struct timespec a,b,c,d;
 if(clock_gettime(CLOCK_MONOTONIC,&a)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&c))return 3;
 for(unsigned long i=0;i<n;++i){
  uint32_t x=next(&state);memory[4]=x;memory[5]=next(&state);
'''+f"  checksum+={function}(({byte_type}*)((unsigned char*)memory+16+(i&3u)),memory+4,x);\n"+r'''
 }
 if(clock_gettime(CLOCK_MONOTONIC,&b)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&d))return 3;
 for(unsigned i=0;i<64;++i)checksum=(checksum*33u)^memory[i];
 struct rusage usage;if(getrusage(RUSAGE_SELF,&usage))return 3;
 printf("%.9f %.9f %lu %" PRIu64 "\n",elapsed(a,b),elapsed(c,d),(unsigned long)usage.ru_maxrss*1024ul,checksum);
 return 0;
}
'''


def run(args,root):
    path=Path(args.reconstruction_report).resolve();matrix=json.loads(path.read_text())
    if matrix["status"] not in ("completed","completed-with-gaps"):raise ValueError("requires finished reconstruction run")
    report={"schema_version":1,"status":"running","environment":environment(),"matrix":str(path),"matrix_sha256":file_hash(path),
            "implementation_sha256":file_hash(__file__),
            "iterations":args.iterations,"repetitions":args.repetitions,"commands":[],"records":[],
            "scope":"application loop includes PRNG, two word resets, shared-library calls and return checksum; RSS is whole-process peak; function bytes include PC-relative operands"}
    command=Runner(report)
    try:
        for gi,group in enumerate(matrix["groups"]):
            profile=next(p for p in matrix["profiles"] if p["id"]==group["profile"])
            compiler=matrix["tools"][profile["compiler"]]
            if file_hash(compiler["path"])!=compiler["sha256"]:raise ValueError("compiler changed")
            for variant in group["variants"]:
                if file_hash(variant["binary"])!=variant["binary_sha256"]:raise ValueError("library changed")
                folder=root/f"{gi}-{variant['variant']}";folder.mkdir()
                source=folder/"driver.c";source.write_text(harness(group["function"],group["parameters"]))
                binary=folder/"run"
                command([compiler["path"],"-std=c11","-Wall","-Wextra","-Werror","-O2","-Wl,-z,now",source,variant["binary"],"-o",binary])
                code=elf_functions(Path(variant["binary"]).read_bytes(),[group["function"]])[group["function"]]
                report["records"].append({"group":gi,"function":group["function"],"profile":group["profile"],"variant":variant["variant"],
                    "binary":str(binary),"sha256":file_hash(binary),"harness_sha256":file_hash(source),
                    "library":variant["binary"],"library_sha256":variant["binary_sha256"],"library_bytes":variant["binary_bytes"],
                    "compile_link_wall_seconds":variant["compile_link_wall_seconds"],"code":code,"samples":[]})
        # All builds precede collection. A copy of each original is the noise control.
        for row in report["records"]:command([row["binary"],min(args.iterations,100000),0x43535244])
        rng=random.Random(20261112)
        for repetition in range(args.repetitions):
            jobs=list(report["records"]);rng.shuffle(jobs)
            for row in jobs:
                wall,cpu,rss,checksum=command([row["binary"],args.iterations,0x43535244+repetition]).split()
                row["samples"].append({"repetition":repetition,"wall_seconds":float(wall),"cpu_seconds":float(cpu),
                                       "peak_rss_bytes":int(rss),"checksum":int(checksum)})
            write_json(root/"costs.json",report)
            print(f"cost repetition {repetition+1}/{args.repetitions}",flush=True)
        for row in report["records"]:
            base=next(b for b in report["records"] if b["group"]==row["group"] and b["variant"]=="original")
            if any(a["checksum"]!=b["checksum"] for a,b in zip(row["samples"],base["samples"])):raise ValueError("application checksum mismatch")
            for field in ("wall_seconds","cpu_seconds"):
                if min(a[field] for a in row["samples"]+base["samples"])<=0:raise ValueError("timing resolution insufficient")
                row[field+"_paired_ratios"]=[a[field]/b[field] for a,b in zip(row["samples"],base["samples"])]
                row[field+"_median_paired_ratio"]=statistics.median(row[field+"_paired_ratios"])
            row["code_bytes_ratio"]=row["code"]["bytes"]/base["code"]["bytes"]
            row["code_bytes_identical"]=row["code"]["sha256"]==base["code"]["sha256"]
            if row["variant"]=="original-copy" and not row["code_bytes_identical"]:raise ValueError("copy control differs")
            if file_hash(row["binary"])!=row["sha256"] or file_hash(row["library"])!=row["library_sha256"]:raise ValueError("binary changed")
        if file_hash(path)!=report["matrix_sha256"]:raise ValueError("matrix changed")
        if file_hash(__file__)!=report["implementation_sha256"]:raise ValueError("measurement code changed")
        report["status"]="completed"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(root/"costs.json",report)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--reconstruction-report",required=True);p.add_argument("--output-dir",required=True)
    p.add_argument("--iterations",type=int,default=1000000);p.add_argument("--repetitions",type=int,default=7);args=p.parse_args()
    if args.iterations<1 or args.repetitions<3:p.error("positive iterations and at least three repetitions required")
    root=Path(args.output_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    with measurement_lock() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);run(args,root)
