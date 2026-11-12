#!/usr/bin/env python3
"""Memory/return differential checks using the existing compiler-profile catalog."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
from run_matrix import flags_for
from run import compilers, execute

NAMES = ("buffer_mix", "buffer_store", "buffer_snapshot", "buffer_boundary", "buffer_unused", "buffer_const")
SEEDS = (0, 42, 18446744073709551615)
CASES = 1024 + 9
LAYOUTS = ((4, 4), (4, 5), (5, 4), (4, 20), (20, 4), (12, 19), (0, 48), (48, 0))


def harness():
    declarations = []
    checks = []
    for name in NAMES:
        const = "const " if name == "buffer_const" else ""
        declarations += [f"uint32_t {prefix}_{name}({const}uint32_t*,uint32_t*,uint32_t);"
                         for prefix in ("original", "candidate")]
        checks.append(f'''memcpy(a,initial,sizeof a);memcpy(b,initial,sizeof b);
        if(original_{name}(a+po,a+qo,x)!=candidate_{name}(b+po,b+qo,x) || memcmp(a,b,sizeof a)) {{
            fprintf(stderr,"mismatch {name} layout=%u iteration=%u\\n",layout,iteration); return 1;
        }}''')
    offsets = ",".join(f"{{{p},{q}}}" for p, q in LAYOUTS)
    return f'''#include <stdint.h>
#include <stdio.h>
#include <string.h>
{chr(10).join(declarations)}
static uint32_t state=0x43535244u;
static uint32_t next(void){{state^=state<<13;state^=state>>17;state^=state<<5;return state;}}
int main(void){{
    const uint32_t edges[]={{0u,1u,2u,3u,2147483647u,2147483648u,2147483649u,4294967294u,4294967295u}};
    const unsigned offsets[][2]={{{offsets}}};
    uint32_t initial[64],a[64],b[64];
    for(unsigned layout=0;layout<{len(LAYOUTS)};layout++) for(unsigned iteration=0;iteration<{CASES};iteration++){{
        uint32_t x=iteration<9 ? edges[iteration] : next();
        for(unsigned i=0;i<64;i++) initial[i]=iteration<9 ? edges[(i+iteration)%9] : next();
        unsigned po=offsets[layout][0],qo=offsets[layout][1];
        {chr(10).join(checks)}
    }}
    if(original_buffer_unused(0,0,4294967295u)!=candidate_buffer_unused(0,0,4294967295u)) return 1;
    puts("PASS memory and return differential");return 0;
}}
'''


def run(args):
    source = ROOT / "tests/fixtures/buffers.c"
    catalog = ROOT / "benchmarks/matrix.json"
    profiles = json.loads(catalog.read_text())["profiles"]
    records, capabilities, transformations = [], [], []
    output = Path(args.output_dir).resolve() if args.output_dir else None
    if output:
        output.mkdir(parents=True, exist_ok=False)
    with tempfile.TemporaryDirectory(prefix="csrd-buffer-") as temp:
        root = output or Path(temp)
        driver = root / "driver.c"; driver.write_text(harness())
        probe = root / "probe.c"; probe.write_text("int main(void){return 0;}\n")
        available = []
        for compiler, version, family in compilers():
            for profile in profiles:
                if profile["compiler"] != family:
                    continue
                item = {"compiler": compiler, "version": version, "profile": profile["id"]}
                if profile.get("pgo") or profile.get("target"):
                    capabilities.append({**item, "status": "not-run", "reason": "PGO/cross-target harness not implemented for buffers"})
                    continue
                flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror",
                         "-" + profile["optimization"], *flags_for(profile, family)]
                command = [compiler, *flags, str(probe), "-o", str(root / "probe")]
                result = subprocess.run(command, text=True, capture_output=True, timeout=90)
                if result.returncode:
                    capabilities.append({**item, "status": "unavailable", "command": command, "reason": result.stderr})
                    continue
                execute([root / "probe"])
                capabilities.append({**item, "status": "available", "flags": flags})
                available.append((item, flags))
        for strategy, seeds in (("identity", (0,)), ("affine", SEEDS)):
            for seed in seeds:
                directory = root / f"{strategy}-{seed}"; directory.mkdir()
                variant = directory / "candidate.c"; manifest = directory / "transformation.json"
                execute([args.csrd, "transform", source, "-o", variant, "--strategy", strategy,
                         "--seed", str(seed), "--report", manifest])
                data = json.loads(manifest.read_text())
                if {f["function"] for f in data["functions"] if f["status"] == "transformed" and
                    f["verification"] == "proved-under-model"} != set(NAMES):
                    raise AssertionError("incomplete buffer transformation or validation")
                transformations.append({"strategy": strategy, "seed": str(seed), "source_sha256": data["source_sha256"],
                                        "candidate_sha256": data["candidate_sha256"], "functions": data["functions"]})
                for number, (item, flags) in enumerate(available):
                    cell = directory / f"cell-{number}"; cell.mkdir()
                    commands = []
                    for label, path in (("original", source), ("candidate", variant)):
                        cmd = [item["compiler"], *flags, *[f"-D{name}={label}_{name}" for name in NAMES],
                               "-c", str(path), "-o", str(cell / f"{label}.o")]
                        execute(cmd); commands.append(cmd)
                    cmd = [item["compiler"], *flags, str(driver), str(cell / "original.o"),
                           str(cell / "candidate.o"), "-o", str(cell / "compare")]
                    execute(cmd); commands.append(cmd)
                    cmd = [str(cell / "compare")]; result = execute(cmd); commands.append(cmd)
                    records.append({**item, "strategy": strategy, "seed": str(seed), "flags": flags,
                                    "commands": commands, "status": "tested-pass", "stdout": result.stdout,
                                    "comparisons": len(NAMES) * len(LAYOUTS) * CASES + 1})
                    print(f"PASS buffers {strategy}/{seed} {item['version']} {item['profile']}", flush=True)
    report = {"schema_version": 1, "model": "buffers-u32-c11-v1", "platform": platform.platform(),
              "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
              "profile_catalog_sha256": hashlib.sha256(catalog.read_bytes()).hexdigest(),
              "input_prng": "xorshift32 seed 0x43535244", "pointer_offsets": LAYOUTS, "storage_words": 64,
              "scope": "Finite correctness tests comparing returns and all 64 memory cells; no performance/protection claim",
              "capabilities": capabilities, "transformations": transformations, "records": records,
              "total_comparisons": sum(r["comparisons"] for r in records)}
    Path(args.report).write_text(json.dumps(report, indent=2) + "\n")
    print(f"PASS {len(records)} build cells; {report['total_comparisons']} function/memory comparisons")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csrd", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--output-dir")
    run(parser.parse_args())
