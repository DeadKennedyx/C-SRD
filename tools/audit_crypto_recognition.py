#!/usr/bin/env python3
"""Fixed benign AES-256 recognition/coverage study; never selects on scanner results.

Fetches public, pinned sources only with --fetch. Requires local compilers,
OpenSSL, YARA and capa; no uploads. Windows executables are scanned, not run.
Current cross-target support is deliberately NOT inferred from native proofs.
"""
import argparse
import collections
import hashlib
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import sys
import time

PINS = {
    "upstream": ("kokke/tiny-AES-c", "23856752fbd139da0b8ca6e471a13d5bcc99a08d"),
    "yara-rules": ("Yara-Rules/rules", "0f93570194a80d2f2032869055808b0ddcdfb360"),
    "findcrypt-yara": ("polymorf/findcrypt-yara", "044644b9c52ae3e7b2305bac15b0c12c9e31a282"),
    "crypto-detection": ("kionactf/crypto-detection", "1b1c7bfede7133f097ed823bed64df92f4a4bc96"),
    "capa-rules": ("mandiant/capa-rules", "801a792c60fb2c8ef79e1b5d61d7e3d2cab4d405"),
    "capa-source": ("mandiant/capa", "7a79f799a70f052e8382cdbeaec8115daba14a5b"),
}
PROFILES = [("gcc-O0", "gcc", ["-O0"]), ("gcc-O2", "gcc", ["-O2"]),
            ("gcc-Os", "gcc", ["-Os"]), ("gcc-O2-lto", "gcc", ["-O2", "-flto"]),
            ("clang-O0", "clang", ["-O0"]), ("clang-O2", "clang", ["-O2"]),
            ("clang-Os", "clang", ["-Os"])]

# Runtime input prevents compile-time specialization. Test vectors are never linked
# into scanner samples. The negative control consumes the same input without AES.
DRIVER = r'''#include <stdio.h>
#ifndef NO_CRYPTO
#include "aes.h"
#endif
int main(void) {
  int mode;
  while ((mode = getchar()) != EOF) {
    unsigned char key[32], iv[16], buffer[64];
    if (mode > 4 || fread(key, 1, 32, stdin) != 32 ||
        fread(iv, 1, 16, stdin) != 16 || fread(buffer, 1, 64, stdin) != 64) return 2;
#ifndef NO_CRYPTO
    struct AES_ctx ctx;
    AES_init_ctx_iv(&ctx, key, iv);
    switch (mode) {
    case 0: for (unsigned i=0; i<64; i+=16) AES_ECB_encrypt(&ctx, buffer+i); break;
    case 1: for (unsigned i=0; i<64; i+=16) AES_ECB_decrypt(&ctx, buffer+i); break;
    case 2: AES_CBC_encrypt_buffer(&ctx, buffer, 64); break;
    case 3: AES_CBC_decrypt_buffer(&ctx, buffer, 64); break;
    case 4: AES_CTR_xcrypt_buffer(&ctx, buffer, 64); break;
    }
#endif
    if (fwrite(buffer, 1, 64, stdout) != 64) return 3;
#ifdef STATE_CHECK
    if (fwrite(ctx.RoundKey, 1, sizeof(ctx.RoundKey), stdout) != sizeof(ctx.RoundKey) ||
        fwrite(ctx.Iv, 1, sizeof(ctx.Iv), stdout) != sizeof(ctx.Iv)) return 3;
#endif
  }
  return ferror(stdin) || fflush(stdout) == EOF;
}
'''

# The upstream verbose demonstration uses a 16-byte key even in AES256 builds,
# and phex then reads 32 bytes. Run the six proper known-answer tests only.
KAT_DRIVER = '''#define main unused_upstream_demo_main
#include "test.c"
#undef main
int main(void) {
  return test_encrypt_cbc() + test_decrypt_cbc() + test_encrypt_ctr() +
         test_decrypt_ctr() + test_decrypt_ecb() + test_encrypt_ecb();
}
'''


def digest(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    return digest(Path(path).read_bytes())


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


class Runner:
    def __init__(self, root):
        self.root = root
        self.commands = []

    def run(self, label, command, *, data=None, timeout=180, allow_failure=False, env=None):
        command = [str(x) for x in command]
        prefix = self.root / "logs" / label
        prefix.parent.mkdir(parents=True, exist_ok=True)
        start = time.monotonic()
        timed_out = False
        try:
            proc = subprocess.run(command, input=data, capture_output=True, timeout=timeout, env=env)
            code, out, err = proc.returncode, proc.stdout, proc.stderr
        except subprocess.TimeoutExpired as exc:
            code, out, err = None, exc.stdout or b"", exc.stderr or b""
            timed_out = True
        prefix.with_suffix(".stdout").write_bytes(out)
        prefix.with_suffix(".stderr").write_bytes(err)
        record = {"label": label, "argv": command, "returncode": code, "timeout": timed_out,
                  "elapsed_seconds": time.monotonic()-start,
                  "stdin_sha256": digest(data) if data is not None else None,
                  "stdout_sha256": digest(out), "stderr_sha256": digest(err),
                  "environment_overrides": {k: env[k] for k in ("ASAN_OPTIONS", "UBSAN_OPTIONS", "SOURCE_DATE_EPOCH")
                                            if env and k in env}}
        self.commands.append(record)
        # Preserve progress if a compiler/scanner fails. Failure is not a zero match.
        write_json(self.root / "commands.json", self.commands)
        if (timed_out or code != 0) and not allow_failure:
            raise RuntimeError(f"{label} failed ({code}, timeout={timed_out}); see {prefix}.stderr")
        return record, out, err


def coverage(report):
    functions = report["functions"]
    frames = [p for f in functions for p in f.get("private_regions", [])]
    return {"target": report["target"], "function_count": len(functions),
            "statuses": dict(collections.Counter(f["status"] for f in functions)),
            "transformed_functions": [f["function"] for f in functions
                                      if f["status"] in ("transformed", "regions-transformed")],
            "regions": len(frames), "operations": sum(f.get("operations_transformed", 0) for f in functions),
            "operations_without_decoding": sum(f["operations_without_decoding"] for f in frames),
            "boundary_conversions": sum(f["boundary_conversions"] for f in frames),
            "source_sha256": report["source_sha256"], "candidate_sha256": report["candidate_sha256"],
            "reasons": dict(collections.Counter(f.get("reason", "") for f in functions if f.get("reason")))}


def parse_matches(engine, stdout):
    if engine == "capa":
        document = json.loads(stdout)
        rules = document["rules"]  # Malformed/failed analyses must not become no-match.
        if document["meta"]["analysis"]["extractor"] != "VivisectFeatureExtractor":
            raise ValueError("unexpected capa backend")
        names = sorted(rules)
        aes = sorted(name for name, rule in rules.items()
                     if rule["meta"].get("namespace", "").startswith("data-manipulation/encryption/aes"))
    else:
        names = sorted({line.split()[0] for line in stdout.decode().splitlines() if line.strip()})
        aes = [name for name in names if "aes" in name.lower() or "rijndael" in name.lower()]
    return {"status": "ok", "all_matches": names, "aes_matches": aes, "aes_recognized": bool(aes)}


def summarize(rows):
    table = {}
    for variant in ("stock", "csrd-raw", "no-crypto"):
        cells = [row for row in rows if row["variant"] == variant]
        table[variant] = {}
        for engine in ("yara-rules", "findcrypt-yara", "crypto-detection", "capa"):
            available = [row["scans"][engine] for row in cells if row["scans"][engine]["status"] == "ok"]
            table[variant][engine] = {"aes_positive": sum(c["aes_recognized"] for c in available),
                                      "successful_scans": len(available), "planned": len(PROFILES),
                                      "errors": len(cells)-len(available)}
    return table


def tool_path(value):
    result = shutil.which(value)
    if not result:
        raise ValueError("missing executable: " + value)
    return str(Path(result).absolute())


def prepare(args, run):
    for name, (repo, sha) in PINS.items():
        path = args.deps / name
        if not path.exists():
            if not args.fetch:
                raise ValueError(f"missing {path}; use --fetch to fetch pinned public dependencies")
            run.run(f"fetch/{name}-init", ["git", "init", "-q", path])
            run.run(f"fetch/{name}-fetch", ["git", "-C", path, "-c", "credential.helper=", "fetch", "--depth", "1",
                                           f"https://github.com/{repo}.git", sha])
            run.run(f"fetch/{name}-checkout", ["git", "-C", path, "checkout", "-q", "--detach", "FETCH_HEAD"])
        _, head, _ = run.run(f"pins/{name}", ["git", "-C", path, "rev-parse", "HEAD"])
        if head.decode().strip() != sha:
            raise ValueError(f"{name}: expected revision {sha}")
        _, status, _ = run.run(f"pins/{name}-clean", ["git", "-C", path, "status", "--porcelain"])
        if status.strip():
            raise ValueError(f"{name}: dependency has local changes")
    versions = {}
    for name in ("csrd", "mingw", "strip", "clang", "llvm_clang", "gcc", "yara", "capa", "openssl"):
        path = tool_path(getattr(args, name))
        setattr(args, name, path)
        _, version, _ = run.run(f"versions/{name}", [path, "version" if name == "openssl" else "--version"])
        versions[name] = {"path": path, "sha256": file_hash(path), "version": version.decode().strip()}
    # Protocol specifies these detector versions; do not silently pool changes.
    if versions["yara"]["version"] != "4.5.8" or versions["capa"]["version"] != "capa 9.4.0":
        raise ValueError("this protocol requires YARA 4.5.8 and capa 9.4.0")
    capa_python = Path(args.capa).parent / "python"
    if capa_python.exists():
        _, packages, _ = run.run("versions/capa-python-packages", [capa_python, "-m", "pip", "freeze", "--all"])
        versions["capa_python_packages"] = packages.decode().splitlines()
    versions["capa_signatures"] = {p.name: file_hash(p) for p in sorted((args.deps / "capa-source/sigs").glob("*.sig"))}
    if not versions["capa_signatures"]:
        raise ValueError("missing pinned capa library signatures")
    return versions


def generate_sources(args, run):
    source = args.output / "source"
    for name in ("stock", "csrd-raw", "frozen"):
        (source / name).mkdir(parents=True)
        shutil.copyfile(args.deps / "upstream/aes.h", source / name / "aes.h")
    original = source / "stock/aes.c"
    original.write_bytes(b"#define AES256 1\n#define CBC 1\n#define ECB 1\n#define CTR 1\n" +
                         (args.deps / "upstream/aes.c").read_bytes())
    (source / "driver.c").write_text(DRIVER)
    (source / "kat.c").write_text(KAT_DRIVER)
    reports = {}
    for scope in ("functions", "private-regions"):
        candidate = source / "csrd-raw" / ("aes.c" if scope == "private-regions" else "functions.c")
        report = source / f"raw-{scope}.json"
        run.run(f"transform/raw-{scope}", [args.csrd, "transform", original, "-o", candidate, "--scope", scope,
                                         "--seed", "42", "--report", report])
        reports["raw-" + scope] = coverage(json.loads(report.read_text()))
    # Existing native frontend only: cross-compiling a transformed native AST is
    # not licensed by these proofs. The Windows arm admits only byte-identical C.
    if original.read_bytes() != (source / "csrd-raw/aes.c").read_bytes():
        raise ValueError("raw output changed: Windows study requires explicit target-aware transformation support")
    frozen = source / "frozen/original.i"
    run.run("transform/preprocess", [args.llvm_clang, "-std=c11", "-E", "-P", original, "-o", frozen])
    report = source / "frozen/affine.json"
    run.run("transform/frozen", [args.csrd, "transform", frozen, "-o", source / "frozen/affine.i",
                                "--scope", "private-regions", "--strategy", "affine", "--seed", "42", "--report", report])
    document = json.loads(report.read_text())
    for function in document["functions"]:
        if function.get("private_regions") and (function["verification"] != "proved-under-model" or
                                                 not function["context_bindings_verified"]):
            raise ValueError("unverified private frame")
    reports["native-preprocessed"] = coverage(document)
    write_json(args.output / "coverage.json", reports)
    return reports


def native_validation(args, run):
    source = args.output / "source"
    rng = random.Random(42)
    vectors = [(bytes(32), bytes(16), bytes(64)), (b"\xff"*32, b"\xff"*16, b"\xff"*64),
               (bytes(range(32)), bytes(range(16)), bytes(range(64)))]
    vectors += [(rng.randbytes(32), rng.randbytes(16), rng.randbytes(64)) for _ in range(64)]
    records, expected = [], []
    for index, (key, iv, payload) in enumerate(vectors):
        for mode in range(5):
            cipher = ("ecb", "ecb", "cbc", "cbc", "ctr")[mode]
            command = [args.openssl, "enc", "-aes-256-"+cipher, "-nopad", "-nosalt", "-K", key.hex()]
            if cipher != "ecb": command += ["-iv", iv.hex()]
            if mode in (1, 3): command += ["-d"]
            _, out, _ = run.run(f"reference/{index}-{mode}", command, data=payload)
            if len(out) != 64: raise ValueError("invalid reference length")
            records.append(bytes([mode])+key+iv+payload)
            expected.append(out)
    inputs = b"".join(records)
    (args.output / "native-inputs.bin").write_bytes(inputs)
    (args.output / "openssl-outputs.bin").write_bytes(b"".join(expected))
    profiles = [("apple", args.clang, False, flag) for flag in (["-O0"], ["-O2"])]
    profiles += [("gcc", args.gcc, False, flag) for flag in (["-O0"], ["-O2"])]
    profiles += [("llvm-frozen", args.llvm_clang, True, flag) for flag in
                 (["-O0"], ["-O2"], ["-O1", "-g", "-fsanitize=address,undefined", "-fno-sanitize-recover=all"])]
    baseline = None
    results = []
    for family, compiler, frozen, flags in profiles:
        for variant in ("stock", "affine" if frozen else "csrd-raw"):
            name = family+"-"+flags[0][1:]+"-"+variant
            directory = args.output / "native" / name
            directory.mkdir(parents=True)
            implementation = source / ("frozen/original.i" if variant == "stock" else "frozen/affine.i") if frozen else source / variant / "aes.c"
            base = [compiler, "-std=c11", "-DAES256=1", *flags, "-I", source / "stock"]
            run.run(f"native/{name}-compile", [*base, "-DSTATE_CHECK", source / "driver.c", implementation, "-o", directory / "exercise"])
            env = dict(os.environ, ASAN_OPTIONS="detect_leaks=0:halt_on_error=1", UBSAN_OPTIONS="halt_on_error=1:print_stacktrace=1")
            _, output, _ = run.run(f"native/{name}-run", [directory / "exercise"], data=inputs, env=env)
            if len(output) != len(expected)*320: raise ValueError("incomplete native output")
            for i, wanted in enumerate(expected):
                if output[i*320:i*320+64] != wanted: raise ValueError(f"OpenSSL discrepancy: {name}/{i}")
            if baseline is None: baseline = output
            if output != baseline: raise ValueError("complete AES state/buffer discrepancy: "+name)
            run.run(f"native/{name}-kat-compile", [*base, "-I", args.deps / "upstream", source / "kat.c", implementation, "-o", directory / "kat"])
            _, kat, _ = run.run(f"native/{name}-kat", [directory / "kat"], env=env)
            if kat.count(b"SUCCESS!") != 6: raise ValueError("incomplete upstream known-answer tests")
            results.append({"profile": name, "cases": len(expected), "upstream_known_answers": 6,
                            "full_state_equal": True, "openssl_equal": True, "source_sha256": file_hash(implementation),
                            "binary_sha256": file_hash(directory / "exercise")})
    write_json(args.output / "native-validation.json", results)
    return results


def windows_matrix(args, run):
    source = args.output / "source"
    yara_rules = {"yara-rules": args.deps / "yara-rules/crypto/crypto_signatures.yar",
                  "findcrypt-yara": args.deps / "findcrypt-yara/findcrypt3.rules",
                  "crypto-detection": args.deps / "crypto-detection/yararules/rules.yar"}
    rows = []
    for profile, family, flags in PROFILES:
        for variant in ("stock", "csrd-raw", "no-crypto"):
            name = profile+"/"+variant
            print("Building/scanning "+name, flush=True)
            directory = args.output / "windows" / name
            directory.mkdir(parents=True)
            binary = directory / "sample.exe"
            compiler = args.mingw if family == "gcc" else args.clang
            target_flags = [] if family == "gcc" else ["--target=x86_64-w64-windows-gnu", "--sysroot="+str(args.mingw_sysroot)]
            objects = []
            sources = [source / "driver.c"]
            if variant != "no-crypto": sources.append(source / variant / "aes.c")
            for index, current in enumerate(sources):
                obj = directory / f"unit{index}.o"
                command = [compiler, *target_flags, "-std=c11", *flags, "-DAES256=1", "-I", source / "stock"]
                if variant == "no-crypto": command += ["-DNO_CRYPTO"]
                run.run(f"windows/{name}-compile{index}", [*command, "-c", current, "-o", obj])
                objects.append(obj)
            run.run(f"windows/{name}-link", [args.mingw, *flags, *objects, "-Wl,--no-insert-timestamp", "-o", binary])
            # GNU strip otherwise reinserts a wall-clock PE timestamp, despite
            # --no-insert-timestamp at link time. Set its reproducible-build epoch.
            run.run(f"windows/{name}-strip", [args.strip, "--strip-all", binary],
                    env=dict(os.environ, SOURCE_DATE_EPOCH="0"))
            pe = binary.read_bytes()
            offset = int.from_bytes(pe[60:64], "little")
            timestamp = int.from_bytes(pe[offset+8:offset+12], "little")
            symbols = int.from_bytes(pe[offset+16:offset+20], "little")
            if pe[:2] != b"MZ" or pe[offset:offset+6] != b"PE\0\0\x64\x86" or timestamp or symbols:
                raise ValueError("expected stripped x64 PE with zero timestamp")
            row = {"profile": profile, "variant": variant, "path": str(binary), "sha256": file_hash(binary),
                   "bytes": binary.stat().st_size, "pe_timestamp": timestamp, "coff_symbols": symbols,
                   "execution": "not-run-no-Windows-runtime", "scans": {}}
            for engine in (*yara_rules, "capa"):
                command = ([args.capa, "-b", "vivisect", "-f", "pe", "-r", args.deps / "capa-rules",
                            "-s", args.deps / "capa-source/sigs", "-j", binary]
                           if engine == "capa" else [args.yara, "-w", yara_rules[engine], binary])
                record, output, _ = run.run(f"scans/{name}-{engine}", command, timeout=300, allow_failure=True)
                if record["returncode"] != 0 or record["timeout"]:
                    row["scans"][engine] = {"status": "error", "returncode": record["returncode"], "timeout": record["timeout"]}
                else:
                    try: row["scans"][engine] = parse_matches(engine, output)
                    except (ValueError, KeyError, TypeError) as exc:
                        row["scans"][engine] = {"status": "error", "reason": str(exc)}
            rows.append(row)
            write_json(args.output / "windows-matrix.json", rows)
    return rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="new output directory (never overwritten)")
    parser.add_argument("--deps", type=Path, default=Path("build-aes-recognition"))
    parser.add_argument("--fetch", action="store_true")
    parser.add_argument("--csrd", default="build/csrd")
    parser.add_argument("--mingw", default="x86_64-w64-mingw32-gcc")
    parser.add_argument("--mingw-sysroot", type=Path, required=True)
    parser.add_argument("--strip", default="x86_64-w64-mingw32-strip")
    parser.add_argument("--clang", default="/usr/bin/clang")
    parser.add_argument("--llvm-clang", default="/opt/homebrew/opt/llvm/bin/clang")
    parser.add_argument("--gcc", default="gcc-16")
    parser.add_argument("--yara", default="yara")
    parser.add_argument("--capa", default="capa")
    parser.add_argument("--openssl", default="openssl")
    args = parser.parse_args()
    args.output, args.deps, args.mingw_sysroot = args.output.resolve(), args.deps.resolve(), args.mingw_sysroot.resolve()
    args.output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(__file__, args.output / "audit_crypto_recognition.py")
    run = Runner(args.output)
    protocol = {"schema": 1, "seed": 42, "corpus": "benign tiny-AES-C AES256, ECB/CBC/CTR", "pins": PINS,
                "profiles": PROFILES, "script_sha256": file_hash(__file__), "argv": sys.argv,
                "hypothesis": "Existing supported transformations change AES recognition; zero changes cannot test this hypothesis.",
                "classification": "AES-specific rule matches only; positive means recognized crypto, not malware.",
                "controls": ["stock positive control", "byte-identical pass-through", "no-crypto input/output negative control"],
                "limits": ["one library, one seed", "Windows binaries not executed", "no detector-guided tuning",
                           "native preprocessed proofs are not Windows proofs", "no runtime performance/protection claim",
                           "prior hidden-tiny-aes rows not rerun; same profiles/rule pins, different harness"]}
    write_json(args.output / "protocol.json", protocol)
    try:
        versions = prepare(args, run)
        write_json(args.output / "versions.json", versions)
        coverage_report = generate_sources(args, run)
        print("Coverage recorded; validating native AES outputs and state", flush=True)
        native = native_validation(args, run)
        rows = windows_matrix(args, run)
        identity = {}
        for profile, _, _ in PROFILES:
            hashes = {r["variant"]: r["sha256"] for r in rows if r["profile"] == profile}
            identity[profile] = hashes["stock"] == hashes["csrd-raw"]
        summary = {"recognition": summarize(rows), "binary_identity": identity, "coverage": coverage_report,
                   "native_executions": sum(r["cases"] for r in native),
                   "native_known_answer_checks": sum(r["upstream_known_answers"] for r in native),
                   "conclusion": "Raw C-SRD output is unchanged. Native preprocessing transforms only index arithmetic. No demonstrated protection advantage.",
                   "limits": protocol["limits"]}
        write_json(args.output / "summary.json", summary)
        print(json.dumps(summary["recognition"], indent=2))
        errors = sum(s["status"] != "ok" for r in rows for s in r["scans"].values())
        return 1 if errors else 0
    except Exception as exc:
        write_json(args.output / "failure.json", {"error": str(exc)})
        raise


if __name__ == "__main__":
    raise SystemExit(main())
