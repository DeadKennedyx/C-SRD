"""Multi-file integration fixture and independent executable-behavior oracle."""
import json
from pathlib import Path
import shlex
import shutil
import subprocess

FIXTURE = Path(__file__).resolve().parents[1] / "benchmarks/projects/buffer_pipeline"


def create(directory, compiler, flags=()):
    directory = Path(directory).resolve()
    shutil.copytree(FIXTURE, directory)
    includes = directory / "include space"
    (directory / "include").rename(includes)
    build = directory / "build"
    build.mkdir()
    compiler = str(Path(compiler).absolute())
    entries = []
    for name in ("map", "reduce", "main"):
        arguments = [compiler, "-std=c11", *flags, "-I../include space", "-include", "../include space/settings.h",
                     "-DPROJECT_FACTOR=3u", "-c", f"../{name}.c", "-o", name + ".o"]
        # Exercise the POSIX command form emitted by ordinary CMake builds.
        entries.append({"directory": str(build), "file": f"../{name}.c", "command": shlex.join(arguments)})
    (build / "compile_commands.json").write_text(json.dumps(entries, indent=2) + "\n")
    spec = {"schema_version": 1, "compilation_database": "build/compile_commands.json",
            "variants": [
                {"name": "identity", "passes": [{"scope": "private-regions", "strategy": "identity", "seed": 42}]},
                {"name": "affine", "passes": [{"scope": "private-regions", "strategy": "affine", "seed": 42}]},
                {"name": "affine_identity", "passes": [{"scope": "private-regions", "strategy": "affine", "seed": 42},
                                                        {"scope": "private-regions", "strategy": "identity", "seed": 42}]}],
            "links": [{"name": "pipeline", "directory": "build", "arguments": [compiler, *flags,
                       "{object:0}", "{object:1}", "{object:2}", "-o", "{output}"]}]}
    path = directory / "project.json"
    path.write_text(json.dumps(spec, indent=2) + "\n")
    return path


def oracle(seed, count, repeats, offset):
    mask = (1 << 32) - 1
    values = [(seed + i) & mask for i in range(count)]
    checksum = 0
    for _ in range(repeats):
        values = [(3 * value + offset) & mask for value in values]
        reduced = 0
        for value in values:
            reduced = (5 * (reduced + value) + offset) & mask
        checksum = (checksum + reduced) & mask
    file_data = ("\n".join(map(str, [checksum, *values, 0x12345678])) + "\n").encode()
    stdout = f"../main.c:{offset}:{checksum}\n".encode()
    return stdout, file_data


def check(binary, directory, seed, count, repeats, offset):
    path = Path(directory) / "result.txt"
    path.unlink(missing_ok=True)
    result = subprocess.run([str(binary), str(seed), str(count), str(repeats), str(path)],
                            capture_output=True, timeout=30)
    actual = path.read_bytes() if path.exists() else None
    expected_stdout, expected_file = oracle(seed, count, repeats, offset)
    if result.returncode or result.stderr or result.stdout != expected_stdout or actual != expected_file:
        raise AssertionError({"binary": str(binary), "input": [seed, count, repeats], "returncode": result.returncode,
                              "stderr": result.stderr.decode(errors="replace"), "stdout": repr(result.stdout),
                              "expected_stdout": repr(expected_stdout), "file_matches": actual == expected_file})
    return result.stdout, actual
