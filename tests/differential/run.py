#!/usr/bin/env python3
"""Compile real originals and generated variants into separate objects; compare in C."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import shutil
import subprocess
import tempfile
import time

ROOT = Path(__file__).resolve().parents[2]
FIXTURE_NAMES = ["calculate", "pipeline", "identities", "constants", "collisions", "line_sensitive", "unrelated"]
SEEDS = [0, 42, 18446744073709551615]
RANDOM_INPUTS = 20000
EDGES = [0, 1, 2, 3, 0x7fffffff, 0x80000000, 0x80000001, 0xfffffffe, 0xffffffff]


def execute(command):
    result = subprocess.run([str(x) for x in command], text=True, capture_output=True, timeout=90)
    if result.returncode:
        raise RuntimeError(f"command failed: {command}\n{result.stdout}\n{result.stderr}")
    return result


def compilers():
    # Never count Apple's gcc alias as GNU GCC.
    if os.environ.get("CSRD_TEST_COMPILERS"):
        candidates = os.environ["CSRD_TEST_COMPILERS"].split(os.pathsep)
    else:
        candidates = ["clang", "gcc"] + [f"gcc-{n}" for n in range(20, 10, -1)]
        if Path("/opt/homebrew/opt/llvm/bin/clang").exists():
            candidates.append("/opt/homebrew/opt/llvm/bin/clang")
    found, versions = [], set()
    for candidate in candidates:
        path = shutil.which(candidate)
        if not path:
            continue
        version = execute([path, "--version"]).stdout.splitlines()[0]
        if version in versions:
            continue
        versions.add(version)
        found.append((path, version, "clang" if "clang" in version.lower() else "gcc"))
    if not found:
        raise RuntimeError("no C compiler found")
    families = {c[2] for c in found}
    if families != {"clang", "gcc"}:
        message = f"missing compiler family: { {'clang', 'gcc'} - families }"
        if os.environ.get("CSRD_REQUIRE_BOTH_COMPILERS") == "1":
            raise RuntimeError(message)
        print("SKIP:", message)
    return found


def generated_corpus():
    rng = random.Random(20261107)
    functions = []
    names = []
    for i in range(24):
        name = f"generated_{i}"
        names.append(name)
        variables = ["x", "y"]
        lines = [f"uint32_t {name}(uint32_t x,uint32_t y) {{"]
        for j in range(8):
            lhs, rhs = rng.choice(variables), rng.choice(variables)
            k = rng.choice(EDGES + [rng.getrandbits(32)])
            expression = rng.choice([f"({lhs}+{rhs})", f"({lhs}-{rhs})", f"({k}u*{lhs})",
                                     f"({lhs}*{k}u)+({rhs}-1u)"])
            var = f"v{j}"
            lines.append(f"uint32_t {var}={expression};")
            variables.append(var)
            if j % 3 == 0:
                lines.append(f"x={var}+y;")
        lines.append("return " + "+".join(f"v{j}" for j in range(8)) + "-x+y;\n}")
        functions.append("\n".join(lines))
    return "\n".join(functions) + "\n", names


def harness(names):
    declarations = "\n".join(f"uint32_t {prefix}_{name}(uint32_t,uint32_t);" for name in names for prefix in ("original", "variant"))
    tests = "\n".join(f'''if (original_{n}(x,y) != variant_{n}(x,y)) {{
        fprintf(stderr,"mismatch {n} x=%" PRIu32 " y=%" PRIu32 "\\n", x, y); return 1;
    }}''' for n in names)
    return f'''#include <stdint.h>
#include <inttypes.h>
#include <stdio.h>
{declarations}
static int compare(uint32_t x,uint32_t y) {{ {tests} return 0; }}
static uint32_t state=0x43535244u;
static uint32_t next(void) {{state^=state<<13; state^=state>>17; state^=state<<5; return state;}}
int main(void) {{
    const uint32_t edges[]={{{','.join(str(e)+'u' for e in EDGES)}}};
    for(unsigned i=0;i<9;i++) for(unsigned j=0;j<9;j++) if(compare(edges[i],edges[j])) return 1;
    for(unsigned i=0;i<{RANDOM_INPUTS};i++) {{uint32_t x=next(); uint32_t y=next(); if(compare(x,y)) return 1;}}
    puts("PASS differential"); return 0;
}}
'''


def run(args):
    records = []
    corpus, generated_names = generated_corpus()
    source = (ROOT / "tests/fixtures/arithmetic.c").read_text() + corpus
    names = FIXTURE_NAMES + generated_names
    with tempfile.TemporaryDirectory(prefix="csrd-differential-") as directory:
        temp = Path(directory)
        original, variant, driver = [temp / n for n in ("original.c", "variant.c", "driver.c")]
        original.write_text(source)
        driver.write_text(harness(names))
        for seed in SEEDS:
            manifest = temp / "manifest.json"
            execute([args.csrd, "transform", original, "-o", variant, "--seed", seed, "--report", manifest])
            decisions = json.loads(manifest.read_text())["functions"]
            expected = set(names) - {"line_sensitive"}
            actual = {d["function"] for d in decisions if d["status"] == "transformed"}
            if actual != expected:
                raise AssertionError(f"unexpected transformation coverage: {actual ^ expected}")
            for compiler, version, family in compilers():
                configurations = [["-O0"], ["-O2"]]
                if family == "clang" and seed == 42:
                    configurations.append(["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"])
                for configuration in configurations:
                    flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", "-Werror", *configuration]
                    start = time.perf_counter()
                    for prefix, file in [("original", original), ("variant", variant)]:
                        rename = [f"-D{name}={prefix}_{name}" for name in names]
                        execute([compiler, *flags, *rename, "-c", file, "-o", temp / f"{prefix}.o"])
                    binary = temp / "compare"
                    execute([compiler, *flags, driver, temp / "original.o", temp / "variant.o", "-o", binary])
                    compile_seconds = time.perf_counter() - start
                    start = time.perf_counter()
                    execute([binary])
                    records.append({"compiler": version, "compiler_path": compiler, "flags": flags, "seed": str(seed),
                                    "functions_compared": len(names), "functions_transformed": len(actual),
                                    "input_pairs_per_function": RANDOM_INPUTS + len(EDGES)**2,
                                    "comparisons": len(names) * (RANDOM_INPUTS + len(EDGES)**2),
                                    "compile_and_link_seconds": compile_seconds,
                                    "harness_seconds": time.perf_counter() - start,
                                    "variant_sha256": hashlib.sha256(variant.read_bytes()).hexdigest(),
                                    "status": "tested-pass"})
                    print(f"PASS {version} {' '.join(configuration)} seed={seed}: {len(names)} functions", flush=True)
    result = {"schema_version": 1, "platform": platform.platform(), "corpus_seed": 20261107,
              "input_prng": "xorshift32, seed 0x43535244", "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
              "scope": "Empirical differential testing; timings are test costs, not runtime-overhead measurements.",
              "records": records, "total_comparisons": sum(r["comparisons"] for r in records)}
    if args.report:
        Path(args.report).write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS {len(records)} configurations; {result['total_comparisons']} comparisons")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csrd", required=True)
    parser.add_argument("--report")
    run(parser.parse_args())
