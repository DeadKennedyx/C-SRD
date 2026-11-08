#!/usr/bin/env python3
"""Compile and compare the expanded subset under every representation strategy."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import tempfile
from run import execute, compilers, harness, RANDOM_INPUTS, EDGES

ROOT = Path(__file__).resolve().parents[2]
NAMES = ["bit_mix", "mixed_regions", "choose", "lookup", "bounded_sum", "table_loop", "comparisons", "zero_iterations"]


def main(args):
    records = []
    with tempfile.TemporaryDirectory(prefix="csrd-expanded-") as directory:
        root = Path(directory)
        original = ROOT / "tests/fixtures/expanded.c"
        variant = root / "variant.c"
        manifest = root / "manifest.json"
        driver = root / "driver.c"
        driver.write_text(harness(NAMES))
        for strategy in ("identity", "affine", "xor", "independent", "planned"):
            for seed in (0, 42):
                execute([args.csrd, "transform", original, "-o", variant, "--strategy", strategy,
                         "--seed", seed, "--report", manifest, "--timeout-ms", 30000])
                transformed = json.loads(manifest.read_text())
                decisions = transformed["functions"]
                if any(d["status"] != "transformed" or d["verification"] != "proved-under-model" for d in decisions):
                    raise AssertionError(f"missing expanded coverage: {decisions}")
                for compiler, version, family in compilers():
                    configurations = [["-O0"], ["-O2"]]
                    if family == "clang" and seed == 42 and strategy in ("planned", "independent"):
                        configurations.append(["-O1", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"])
                    for configuration in configurations:
                        # An intentional zero-trip unsigned loop is valid C; compilers
                        # warn about its comparison under -Wextra, so allow that warning.
                        flags = ["-std=c11", "-pedantic-errors", "-Wall", "-Wextra", *configuration]
                        for prefix, source in (("original", original), ("variant", variant)):
                            execute([compiler, *flags, *[f"-D{n}={prefix}_{n}" for n in NAMES], "-c", source, "-o", root / (prefix + ".o")])
                        binary = root / "compare"
                        execute([compiler, *flags, driver, root / "original.o", root / "variant.o", "-o", binary])
                        execute([binary])
                        records.append({"compiler": version, "flags": flags, "strategy": strategy, "seed": seed,
                                        "variant_sha256": transformed["candidate_sha256"],
                                        "translation_validation": [{"function": d["function"], "status": d["verification"],
                                                                    "obligation_sha256": d["proof"]["obligation_sha256"]} for d in decisions],
                                        "functions": len(NAMES), "comparisons": len(NAMES)*(RANDOM_INPUTS+len(EDGES)**2), "status": "tested-pass"})
                print(f"PASS expanded subset: {strategy}, seed {seed}", flush=True)
    result = {"schema_version": 1, "platform": platform.platform(), "source_sha256": hashlib.sha256(original.read_bytes()).hexdigest(),
              "input_prng": "xorshift32, seed 0x43535244", "random_inputs_per_function": RANDOM_INPUTS, "boundary_values": EDGES,
              "records": records, "total_comparisons": sum(x["comparisons"] for x in records),
              "scope": "Empirical compiled comparisons, plus a separate per-function bit-vector proof for each transformed artifact."}
    if args.report:
        Path(args.report).write_text(json.dumps(result, indent=2) + "\n")
    print(f"PASS {len(records)} configurations, {result['total_comparisons']} comparisons")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--csrd", required=True)
    parser.add_argument("--report")
    main(parser.parse_args())
