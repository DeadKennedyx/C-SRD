#!/usr/bin/env python3
"""Create an isolated, hash-gated Ghidra 12.2 AArch64 signed-byte language fix.

The original installation is never modified. Compile AARCH64.slaspec in the
copied directory with Ghidra's support/sleigh before using the overlay.
"""
import argparse
import difflib
import hashlib
import json
from pathlib import Path
import shutil


def patch(source,output):
    path=source/"AARCH64base.sinc";old=path.read_text()
    if hashlib.sha256(path.read_bytes()).hexdigest()!="4c70fde74b15e456a73ab51d9636381c56a5f16b876f97fe65919b583dfdb9e6":
        raise ValueError("requires the pinned Ghidra 12.2 source checksum")
    marker=':ld^UnscPriv^"rsb" Rt_GPR32, addrIndexed\nis size.ldstr=0 & b_2729=7 & v=0 & b_2425=0 & b_2223=3 & b_2121=0 & UnscPriv & addrIndexed & Rt_GPR32 & Rt_GPR64\n{\n\tRt_GPR64 = zext(*:1 addrIndexed);\n}'
    if old.count(marker)!=1:raise ValueError("expected unique pinned LDURSB-W constructor not found")
    corrected=marker.replace('Rt_GPR64 = zext(*:1 addrIndexed);','local value:4 = sext(*:1 addrIndexed);\n\tRt_GPR64 = zext(value);')
    new=old.replace(marker,corrected)
    shutil.copytree(source,output)
    (output/"AARCH64base.sinc").write_text(new)
    manifest={"scope":"AArch64 unscaled/unprivileged signed byte load into W: sign extend to 32, then zero extend to X; independent hardware/decompiler controls required",
              "source_sha256":hashlib.sha256(path.read_bytes()).hexdigest(),
              "patched_sha256":hashlib.sha256(new.encode()).hexdigest(),
              "patch":"".join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile="original/AARCH64base.sinc",tofile="patched/AARCH64base.sinc"))}
    (output/"csrd-patch.json").write_text(json.dumps(manifest,indent=2)+"\n")
    return manifest


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__);p.add_argument("--language-dir",type=Path,required=True);p.add_argument("--output",type=Path,required=True);args=p.parse_args()
    print(json.dumps(patch(args.language_dir,args.output),indent=2))
