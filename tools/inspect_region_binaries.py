#!/usr/bin/env python3
"""Exact ELF64 code bytes and instruction-count controls for observed libraries."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct

from audit_protection import file_hash, write_json
from audit_region_observers import checked_artifacts, command
from region_observation_cases import FUNCTIONS


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


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--build",required=True);p.add_argument("--output",required=True);run(p.parse_args())
