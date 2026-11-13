#!/usr/bin/env python3
"""Matched application costs for the exact shared libraries used by the observers."""
import argparse
import fcntl
import json
from pathlib import Path
import random
import statistics
import sys

from audit_protection import file_hash, write_json
from audit_region_observers import checked_artifacts, command
from effort_resources import environment, measurement_lock
from evaluate import object_metrics

ROOT = Path(__file__).resolve().parents[1]
HARNESS = r'''#define _POSIX_C_SOURCE 200809L
#include <stdint.h>
#include <stdio.h>
#include <inttypes.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <sys/resource.h>
uint32_t region_pipeline(uint32_t*,uint32_t,int);
int region_outputs(uint32_t*,uint32_t,uint32_t);
static uint32_t memory[3],events[128],count;
void record_event(uint32_t value){if(count>=128u)exit(70);events[count++]=value;}
uint32_t next_value(uint32_t value){record_event(value);memory[1]+=value;return value+memory[1];}
static uint32_t next(uint32_t *s){*s^=*s<<13;*s^=*s>>17;*s^=*s<<5;return *s;}
static double elapsed(struct timespec a,struct timespec b){return (double)(b.tv_sec-a.tv_sec)+(double)(b.tv_nsec-a.tv_nsec)*1e-9;}
int main(int argc,char **argv){
 if(argc!=3)return 2;
 unsigned long n=strtoul(argv[1],0,10);uint32_t state=(uint32_t)strtoul(argv[2],0,10);uint64_t checksum=0;
 struct timespec a,b,c,d;
 if(clock_gettime(CLOCK_MONOTONIC,&a)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&c))return 3;
 for(unsigned long i=0;i<n;++i){
  uint32_t x=next(&state),y=next(&state);memory[0]=next(&state);memory[1]=next(&state);memory[2]=next(&state);count=0;
  checksum+=(uint64_t)region_pipeline(memory,x,(i&1u)?2:0);
  checksum+=(uint32_t)region_outputs(memory,x,y);
  for(uint32_t j=0;j<count;++j)checksum=checksum*33u^events[j];
  for(unsigned j=0;j<3;++j)checksum=checksum*33u^memory[j];
 }
 if(clock_gettime(CLOCK_MONOTONIC,&b)||clock_gettime(CLOCK_PROCESS_CPUTIME_ID,&d))return 3;
 struct rusage usage;if(getrusage(RUSAGE_SELF,&usage))return 3;
 /* Linux ru_maxrss can retain a pre-exec launcher high-water mark. VmHWM
    describes this executable's address space. Read it after timing ends. */
 FILE *status=fopen("/proc/self/status","r");if(!status)return 4;
 char line[256];unsigned long executable_peak=0;
 while(fgets(line,sizeof(line),status))if(strncmp(line,"VmHWM:",6)==0){
   if(sscanf(line+6,"%lu",&executable_peak)!=1)return 4;
 }
 if(fclose(status)||!executable_peak)return 4;
 printf("%.9f %.9f %lu %lu %" PRIu64 "\n",elapsed(a,b),elapsed(c,d),
        (unsigned long)usage.ru_maxrss*1024ul,executable_peak*1024ul,checksum);
 return 0;
}
'''


def sample(text):
    wall,cpu,rss,executable_rss,checksum=text.split()
    return {"wall_seconds":float(wall),"cpu_seconds":float(cpu),"peak_rss_bytes":int(rss),
            "executable_peak_rss_bytes":int(executable_rss),"checksum":int(checksum)}


def run(args):
    manifest=Path(args.build).resolve();build=json.loads(manifest.read_text());records=checked_artifacts(build)
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=False)
    report={"schema_version":2,"status":"building","build":str(manifest),"build_sha256":file_hash(manifest),"environment":environment(),
            "script_sha256":file_hash(__file__),"iterations":args.iterations,"repetitions":args.repetitions,"records":[],
            "scope":"public shared-library calls including input generation and output checksum; application loop CPU/wall",
            "rss_scope":"peak_rss_bytes is getrusage high-water, possibly including pre-exec launcher; executable_peak_rss_bytes is Linux VmHWM for the current address space, including loader/harness, approximate page-granular kernel accounting and not isolated function allocations"}
    try:
        for i,record in enumerate(records):
            directory=root/str(i);directory.mkdir()
            source=directory/"driver.c";source.write_text(HARNESS);binary=directory/"run"
            command([record["compiler"],"-std=c11","-Wall","-Wextra","-Werror","-O2","-rdynamic","-Wl,-z,now",source,record["library"],"-o",binary],directory/"compile")
            text=command(["size","-A",record["library"]],directory/"size")
            sections={parts[0]:int(parts[1]) for line in text.splitlines() if len(parts:=line.split())==3 and parts[1].isdecimal()}
            metric_commands = []
            def metric_command(argv):
                path = directory/f"structure-{len(metric_commands)}"
                metric_commands.append(path)
                return command(argv, path), 0
            structure = object_metrics("objdump", record["library"], metric_command)
            row={"artifact":record["id"],"binary":str(binary),"sha256":file_hash(binary),"harness_sha256":file_hash(source),
                 "library_sha256":record["library_sha256"],"library_bytes":record["library_bytes"],"sections":sections,"structure":structure,"samples":[]}
            report["records"].append(row)
        # Separately validate the distinction between the two memory counters.
        # Pressure is in the launcher, which then execs the same small program.
        binary=report["records"][0]["binary"]
        direct=sample(command([binary,1,42],root/"memory-control-direct"))
        launcher="import os,sys; p=bytearray(64<<20); p[::4096]=b'x'*(len(p)//4096); os.execv(sys.argv[1],sys.argv[1:])"
        pressured=sample(command([sys.executable,"-c",launcher,binary,1,42],root/"memory-control-launcher"))
        if direct["checksum"]!=pressured["checksum"]:raise ValueError("memory counter control changed application result")
        report["memory_counter_control"]={"launcher_bytes_touched":64<<20,"direct":direct,"after_exec":pressured,
            "launcher_peak_visible_only_in_rusage":pressured["peak_rss_bytes"]>=64<<20 and pressured["executable_peak_rss_bytes"]<32<<20}
        report["status"]="measuring"
        rng=random.Random(20261110)
        for repetition in range(args.repetitions):
            jobs=list(enumerate(report["records"]));rng.shuffle(jobs)
            for i,row in jobs:
                values=sample(command([row["binary"],args.iterations,0x43535244+repetition],root/str(i)/f"sample-{repetition}"))
                row["samples"].append({"repetition":repetition,**values})
            write_json(root/"costs.json",report)
            print(f"application cost repetition {repetition+1}/{args.repetitions}",flush=True)
        lookup={r["artifact"]:r for r in report["records"]}
        for row in report["records"]:
            base=lookup[row["artifact"].rsplit("/",1)[0]+"/original"]
            if any(a["checksum"]!=b["checksum"] for a,b in zip(row["samples"],base["samples"])):raise ValueError("application checksum differs")
            for field in ("wall_seconds","cpu_seconds"):
                ratios=[a[field]/b[field] for a,b in zip(row["samples"],base["samples"])]
                row[field+"_paired_ratios"]=ratios;row[field+"_median_paired_ratio"]=statistics.median(ratios)
            row["peak_rss_median_bytes"]=statistics.median(s["peak_rss_bytes"] for s in row["samples"])
            row["executable_peak_rss_median_bytes"]=statistics.median(s["executable_peak_rss_bytes"] for s in row["samples"])
            row["text_size_ratio"]=row["sections"][".text"]/base["sections"][".text"]
            row["text_identical_to_original"]=row["structure"]["text_sha256"]==base["structure"]["text_sha256"]
            if file_hash(row["binary"])!=row["sha256"]:raise ValueError("driver changed")
        checked_artifacts(build)
        report["status"]="completed"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(root/"costs.json",report)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--build",required=True);p.add_argument("--output",required=True)
    p.add_argument("--iterations",type=int,default=1000000);p.add_argument("--repetitions",type=int,default=7);args=p.parse_args()
    if args.iterations<1 or args.repetitions<3:p.error("positive iterations and at least three repetitions required")
    with measurement_lock() as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);run(args)
