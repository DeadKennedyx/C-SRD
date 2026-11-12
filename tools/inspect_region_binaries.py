#!/usr/bin/env python3
"""Exact ELF64 code bytes and instruction-count controls for observed libraries."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct

from audit_protection import file_hash, write_json
from audit_region_observers import checked_artifacts, command
from region_observation_cases import FUNCTIONS
from audit_buffer_reconstruction import load_matrix


def elf_functions(data, names=None):
    requested=set(FUNCTIONS if names is None else names)
    if data[:6] != b"\x7fELF\x02\x01": raise ValueError("requires little-endian ELF64")
    header=struct.unpack_from("<16sHHIQQQIHHHHHH",data)
    offset,entry_size,count=header[6],header[11],header[12]
    if entry_size!=64 or not count or offset+entry_size*count>len(data):raise ValueError("invalid ELF section table")
    sections=[struct.unpack_from("<IIQQQQIIQQ",data,offset+i*entry_size) for i in range(count)]
    found={}
    for section in sections:
        if section[1] not in (2,11):continue  # SYMTAB, DYNSYM
        if section[9]!=24 or section[6]>=count:raise ValueError("invalid ELF symbol table")
        strings=sections[section[6]];names=data[strings[4]:strings[4]+strings[5]]
        if section[4]+section[5]>len(data):raise ValueError("symbol table outside file")
        for pos in range(section[4],section[4]+section[5],24):
            name,info,other,index,value,size=struct.unpack_from("<IBBHQQ",data,pos)
            if info & 15 != 2 or index==0:continue
            if name>=len(names) or b"\0" not in names[name:]:raise ValueError("invalid symbol name")
            label=names[name:].split(b"\0",1)[0].decode("utf-8")
            if label not in requested:continue
            if index>=count:raise ValueError("unsupported special symbol section")
            target=sections[index];relative=value-target[3]
            if not size or relative<0 or relative+size>target[5] or target[4]+relative+size>len(data):raise ValueError("function outside code section")
            raw=data[target[4]+relative:target[4]+relative+size]
            item={"bytes":size,"sha256":hashlib.sha256(raw).hexdigest(),"address":value}
            if label in found and found[label]!=item:raise ValueError("ambiguous public symbol")
            found[label]=item
    if found.keys()!=requested:raise ValueError("missing public function")
    return found


def run(args):
    manifest=Path(args.build).resolve();build=json.loads(manifest.read_text());records=checked_artifacts(build)
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=False)
    report={"schema_version":1,"status":"running","build_sha256":file_hash(manifest),"records":[],
            "scope":"exact protected-function bytes include PC-relative encodings; opcode sequences discard operands and nops; neither is semantic equivalence"}
    for serial,record in enumerate(records):
        directory=root/str(serial);directory.mkdir()
        functions=elf_functions(Path(record["library"]).read_bytes())
        assembly=command(["objdump","-d","--no-show-raw-insn",record["library"]],directory/"objdump")
        current=None;sequences={name:[] for name in FUNCTIONS}
        for line in assembly.splitlines():
            match=re.match(r"^\s*([0-9a-fA-F]+) <([^>]+)>:",line)
            if match:current=match[2] if match[2] in sequences else None;continue
            match=re.match(r"^\s*[0-9a-fA-F]+:\s+([A-Za-z][A-Za-z0-9.]*)",line)
            if current and match and match[1] not in ("nop","nopl","nopw"):sequences[current].append(match[1])
        for name,value in functions.items():
            if not sequences[name]:raise ValueError("missing disassembly")
            value["instructions"]=len(sequences[name]);value["opcode_sha256"]=hashlib.sha256(json.dumps(sequences[name]).encode()).hexdigest()
        report["records"].append({"artifact":record["id"],"library_sha256":record["library_sha256"],"functions":functions})
    lookup={r["artifact"]:r for r in report["records"]}
    for record in report["records"]:
        baseline=lookup[record["artifact"].rsplit("/",1)[0]+"/original"]
        for name,value in record["functions"].items():
            value["exact_bytes_equal"]=value["sha256"]==baseline["functions"][name]["sha256"]
            value["opcode_sequence_equal"]=value["opcode_sha256"]==baseline["functions"][name]["opcode_sha256"]
        if record["artifact"].endswith("/original-copy") and any(not f["exact_bytes_equal"] for f in record["functions"].values()):raise ValueError("copy control differs")
    report["status"]="completed";write_json(root/"binaries.json",report)


def run_buffer_matrix(args):
    manifest=Path(args.reconstruction_report).resolve();matrix,replay=load_matrix(manifest,args.replay_report)
    root=Path(args.output).resolve();root.mkdir(parents=True,exist_ok=False)
    objdump=shutil.which("objdump")
    if not objdump:raise ValueError("objdump unavailable")
    report={"schema_version":1,"status":"running","matrix_sha256":file_hash(manifest),"records":[],
            "implementation_sha256":file_hash(__file__),"objdump":objdump,"objdump_sha256":file_hash(objdump),
            "scope":"raw function bytes include relocations/PC-relative operands; opcode sequences discard operands/nops; equality of opcode sequences is only structural"}
    cache={}
    if replay:report['observer_replay']=replay
    try:
        for gi,group in enumerate(matrix["groups"]):
            baseline=None
            for variant in group["variants"]:
                path=variant["binary"]
                if file_hash(path)!=variant["binary_sha256"]:raise ValueError("observed library changed")
                if path not in cache:
                    assembly=command([objdump,"-d","--no-show-raw-insn",path],root/str(len(cache)))
                    functions={};current=None
                    for line in assembly.splitlines():
                        match=re.match(r"^\s*([0-9a-fA-F]+) <([^>]+)>:",line)
                        if match:current=match[2];functions[current]=[];continue
                        match=re.match(r"^\s*[0-9a-fA-F]+:\s+([A-Za-z][A-Za-z0-9.]*)",line)
                        if current and match and match[1] not in ("nop","nopl","nopw"):functions[current].append(match[1])
                    cache[path]=functions
                ops=cache[path].get(group["function"])
                if not ops:raise ValueError("missing function disassembly")
                code=elf_functions(Path(path).read_bytes(),[group["function"]])[group["function"]]
                record={"group":gi,"function":group["function"],"profile":group["profile"],"variant":variant["variant"],
                        "binary":path,"binary_sha256":variant["binary_sha256"],"code":code,"instructions":len(ops),
                        "opcode_sha256":hashlib.sha256(json.dumps(ops).encode()).hexdigest()}
                if variant["variant"]=="original":baseline=record
                if baseline is None:raise ValueError("original must precede candidates")
                record["exact_bytes_equal"]=code["sha256"]==baseline["code"]["sha256"]
                record["opcode_sequence_equal"]=record["opcode_sha256"]==baseline["opcode_sha256"]
                if variant["variant"]=="original-copy" and not(record["exact_bytes_equal"] and record["opcode_sequence_equal"]):
                    raise ValueError("identical-copy control differs")
                report["records"].append(record)
        if file_hash(manifest)!=report["matrix_sha256"] or file_hash(__file__)!=report["implementation_sha256"] or file_hash(objdump)!=report["objdump_sha256"]:
            raise ValueError("measurement input/tool changed")
        if replay and file_hash(replay['path'])!=replay['sha256']:raise ValueError('observer replay changed')
        for row in report["records"]:
            if file_hash(row["binary"])!=row["binary_sha256"]:raise ValueError("library changed")
        report["status"]="completed"
    except Exception as error:report.update(status="failed",error=str(error));raise
    finally:write_json(root/"binaries.json",report)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    group=p.add_mutually_exclusive_group(required=True);group.add_argument("--build");group.add_argument("--reconstruction-report")
    p.add_argument('--replay-report',help='finished revised observer replay for the same frozen binaries')
    p.add_argument("--output",required=True);args=p.parse_args()
    (run_buffer_matrix if args.reconstruction_report else run)(args)
