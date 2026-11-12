#!/usr/bin/env python3
"""Independent AArch64 instruction/hardware controls for the isolated language fix."""
import argparse
import json
from pathlib import Path
import platform
from audit_protection import file_hash,write_json
from audit_region_observers import command
from region_observation_cases import driver,input_text,parse_output
from pcode_regions import reconstruct


def run(args):
    if platform.machine()!="aarch64":raise ValueError("these instruction controls require native Linux AArch64")
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=False)
    headless=Path(args.ghidra).resolve()
    language=headless.parent.parent/"Ghidra/Processors/AARCH64/data/languages"
    report={"status":"running","expected_observer":args.expect,"scope":"all 256 byte inputs at three LDURSB-W offsets; includes X-register upper-half control; no general AArch64 lifting proof",
            "language_hashes":{n:file_hash(language/n) for n in ("AARCH64base.sinc","AARCH64.sla")},"records":[]}
    try:
        for offset in (-1,0,1):
            folder=root/str(offset);folder.mkdir();assembly=folder/"probe.S"
            assembly.write_text(f'''.text
.global region_pipeline
.type region_pipeline,%function
region_pipeline:
    sub sp,sp,#16
    strb w1,[sp,#8]
    add x4,sp,#{8-offset}
    ldursb w3,[x4,#{offset}]
    add sp,sp,#16
    str w3,[x0]
    lsr x4,x3,#32
    str w4,[x0,#4]
    mov w0,w3
    ret
.size region_pipeline,.-region_pipeline
.section .note.GNU-stack,"",@progbits
''')
            library=folder/"probe.so"
            command(["clang-18","-shared","-fPIC",assembly,"-o",library],folder/"assemble")
            harness=folder/"driver.c";harness.write_text(driver("region_pipeline"))
            native=folder/"native"
            command(["clang-18",harness,library,"-o",native],folder/"link")
            cases=[{"x":x,"arg":0,"memory":[0,0,0x12345678],"mode":0} for x in range(256)]
            inputs="".join(input_text(v) for v in cases)
            expected=[{"return_value":x if x<128 else x+2**32-256,
                       "final_memory":[x if x<128 else x+2**32-256,0,0x12345678],"events":[]} for x in range(256)]
            actual=[parse_output(s) for s in command([native],folder/"hardware",stdin=inputs).splitlines()]
            if actual!=expected:raise ValueError("native instruction behavior disagrees with oracle")
            export=folder/"export";export.mkdir();project=folder/"project";project.mkdir()
            command([headless,project,"probe","-import",library,"-deleteProject","-max-cpu","2","-scriptPath",Path(__file__).resolve().parent/"ghidra",
                     "-postScript","ExportCSRDRegions.java","region_pipeline","p,u,s","15",export],folder/"decompile")
            recovered=folder/"recovered.c";recovered.write_text(reconstruct(json.loads((export/"export.json").read_text())))
            rows=[]
            for compiler in ("clang-18","gcc"):
                binary=folder/(compiler+"-recovered")
                command([compiler,"-std=c11","-O2",recovered,harness,"-o",binary],folder/(compiler+"-compile"))
                actual=[parse_output(s) for s in command([binary],folder/(compiler+"-execute"),stdin=inputs).splitlines()]
                mismatches=[i for i,(a,b) in enumerate(zip(actual,expected)) if a!=b]
                if len(actual)!=256 or len(mismatches)!=(128 if args.expect=="zero-extension-bug" else 0):
                    raise ValueError("unexpected reconstructed instruction behavior")
                rows.append({"compiler":compiler,"comparisons":256,"mismatches":len(mismatches),
                             "first_counterexample":None if not mismatches else {"byte":mismatches[0],"expected":expected[mismatches[0]],"actual":actual[mismatches[0]]}})
            report["records"].append({"offset":offset,"hardware_comparisons":256,"library_sha256":file_hash(library),
                                      "export_sha256":file_hash(export/"export.json"),"grading":rows})
        report["status"]="passed"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(root/"controls.json",report)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--ghidra",required=True);p.add_argument("--output",required=True)
    p.add_argument("--expect",choices=("correct","zero-extension-bug"),required=True);run(p.parse_args())
