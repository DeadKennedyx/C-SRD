#!/usr/bin/env python3
"""Build trusted C projects from compile commands and explicit link recipes.

Never executes a shell or guesses a project's link dependencies. Artifacts live
in a fresh directory. Each pass uses C-SRD's own translation validation. External
compiler preprocessing and whole-program behavior remain empirical obligations.
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

from effort_resources import environment, measure, measurement_lock, save


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def absolute(path, directory):
    return Path(os.path.abspath(Path(directory) / path))


def compiler_path(name, directory):
    if not re.fullmatch(r"(?:.*-)?(?:clang|gcc|cc)(?:-\d+(?:\.\d+)*)?", Path(name).name):
        raise ValueError("require a direct GCC/Clang C driver, without a wrapper: " + name)
    path = absolute(name, directory) if "/" in name else shutil.which(name)
    if path is None or not Path(path).is_file():
        raise ValueError("compiler not found: " + name)
    return str(path)


def adapt_compile(arguments, source, directory, output, *, frozen=None, preprocess=False):
    """Adapt supported driver arguments, never parse or edit C source here."""
    result = [compiler_path(arguments[0], directory)]
    source_token = None
    skip_value = {"-o", "-MF", "-MT", "-MQ", "-MJ"}
    skip = {"-c", "-S", "-E", "-fsyntax-only", "-MD", "-MMD", "-MP", "-MG", "-M", "-MM"}
    preprocessing_value = {"-D", "-U", "-I", "-isystem", "-iquote", "-idirafter", "-include", "-imacros"}
    keep_value = {"--target", "-target", "--sysroot", "-isysroot", "-arch", "-B", "--gcc-toolchain", "-resource-dir"}
    unsafe = ("-save-temps", "-ftime-trace", "-fprofile", "--coverage", "-fcoverage", "-fstack-usage",
              "-fdump", "-serialize-diagnostics", "-fdiagnostics-serialization", "-gen-reproducer",
              "-fsave-optimization-record", "-foptimization-record", "-Wp,", "-Wa,", "-Wl,",
              "-X", "-fplugin", "-specs", "--specs", "-wrapper", "-fmodules", "-fmodule",
              "-emit-llvm", "--config", "-ivfsoverlay", "-vfsoverlay", "-mllvm")
    i = 1
    after_separator = False
    while i < len(arguments):
        arg = arguments[i]
        i += 1
        if arg == "--":
            after_separator = True
            continue
        if absolute(arg, directory) == Path(source) and (after_separator or not arg.startswith("-")):
            if source_token is not None:
                raise ValueError("duplicate source input")
            source_token = arg
            continue
        if after_separator or not arg.startswith("-"):
            raise ValueError("unsupported extra input or option value: " + arg)
        if arg.startswith(unsafe):
            raise ValueError("unsupported replay option: " + arg)
        if arg in skip_value | preprocessing_value | keep_value | {"-x"}:
            if i == len(arguments):
                raise ValueError("missing compiler option value: " + arg)
            value = arguments[i]
            i += 1
            if arg == "-x":
                if value != "c":
                    raise ValueError("project runner currently requires C source inputs")
            elif arg not in skip_value and (frozen is None or arg not in preprocessing_value):
                result.extend([arg, value])
        elif arg in skip or any(arg.startswith(p) and len(arg) > len(p) for p in skip_value):
            continue
        elif arg.startswith(("-D", "-U", "-I")):
            if frozen is None:
                result.append(arg)
        elif arg.startswith(("-std=", "--target=", "--sysroot=", "--gcc-toolchain=", "-resource-dir=",
                             "-O", "-g", "-W", "-f", "-m")) or arg in {"-pthread", "-ansi", "-pedantic", "-pedantic-errors", "-nostdinc", "-nostdlibinc"}:
            result.append(arg)
        else:
            raise ValueError("unsupported compiler replay option: " + arg)
    if source_token is None or Path(source).suffix != ".c":
        raise ValueError("require exactly one .c source input per compile command")
    result.extend(["-x", "cpp-output" if frozen is not None else "c", "-E" if preprocess else "-c",
                   str(frozen) if frozen is not None else source_token, "-o", str(output)])
    return result


def pass_arguments(config, root):
    allowed = {"scope", "strategy", "seed", "control_flow", "algorithm", "call_contracts"}
    if set(config) - allowed:
        raise ValueError("unknown pass fields: " + str(sorted(set(config) - allowed)))
    arguments = []
    for key, value in config.items():
        if key == "call_contracts":
            value = str(absolute(value, root))
        arguments.extend(["--" + key.replace("_", "-"), str(value)])
    return arguments


def link_arguments(recipe, directory, objects, output):
    args = recipe["arguments"]
    if not isinstance(args, list) or not args or any(not isinstance(a, str) for a in args):
        raise ValueError("link recipe requires an argv array")
    if args.count("{output}") != 1 or args.count("-o") != 1 or args[-1] == "-o" or args[args.index("-o") + 1] != "{output}":
        raise ValueError("link recipe requires exactly '-o', '{output}'")
    result = [compiler_path(args[0], directory)]
    used = set()
    for arg in args[1:]:
        match = re.fullmatch(r"\{object:(\d+)\}", arg)
        if match:
            index = int(match[1])
            if index not in objects:
                raise ValueError("link recipe references unselected compile command")
            used.add(index)
            result.append(str(objects[index]))
        elif arg == "{output}":
            result.append(str(output))
        elif "{" in arg or "}" in arg or arg.startswith(("@", "-Wl,-Map", "-save-temps", "-fprofile", "-fplugin", "--config")):
            raise ValueError("unsupported link recipe argument: " + arg)
        else:
            result.append(arg)
    if not used:
        raise ValueError("link recipe must reference at least one compiled object")
    return result


def build_project(tool, specification, destination):
    specification, destination = Path(specification).resolve(), Path(destination).resolve()
    config = json.loads(specification.read_text())
    root = specification.parent
    if config.get("schema_version") != 1 or set(config) - {"schema_version", "compilation_database", "commands", "transform_commands", "variants", "links"}:
        raise ValueError("unsupported project specification schema")
    database = absolute(config["compilation_database"], root)
    if database.is_dir():
        database /= "compile_commands.json"
    entries = json.loads(database.read_text())
    selected = config.get("commands", list(range(len(entries))))
    if not selected or len(set(selected)) != len(selected) or any(type(i) is not int or i < 0 or i >= len(entries) for i in selected):
        raise ValueError("commands must select distinct database entry indexes")
    transform_selected = config.get("transform_commands", selected)
    if len(set(transform_selected)) != len(transform_selected) or any(type(i) is not int or i not in selected for i in transform_selected):
        raise ValueError("transform_commands must be a subset of commands")
    variants = config.get("variants", [
        {"name": "identity", "passes": [{"scope": "private-regions", "strategy": "identity", "seed": 42}]},
        {"name": "affine", "passes": [{"scope": "private-regions", "strategy": "affine", "seed": 42}]}])
    names = [v["name"] for v in variants]
    links = config.get("links", [])
    link_names = [link["name"] for link in links]
    if any(not re.fullmatch(r"[a-zA-Z0-9_-]+", n) for n in names + link_names) or len(set(names)) != len(names) or set(names) & {"original", "frozen"} or len(set(link_names)) != len(link_names):
        raise ValueError("variant/link names must be distinct safe artifact names")
    for variant in variants:
        if set(variant) != {"name", "passes"}:
            raise ValueError("variant requires only name and passes")
        if not variant["passes"]:
            raise ValueError("a variant requires at least one pass")
        for entry in variant["passes"]:
            pass_arguments(entry, root)
    for link in links:
        if set(link) - {"name", "directory", "arguments"}:
            raise ValueError("unknown link recipe field")
    destination.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(specification, destination / "project-input.json")
    shutil.copyfile(database, destination / "compile_commands-input.json")
    manifest = {"schema_version": 1, "status": "running", "environment": environment(),
                "build_environment": {key: os.environ.get(key) for key in ("PATH", "CPATH", "C_INCLUDE_PATH", "SDKROOT", "MACOSX_DEPLOYMENT_TARGET", "SOURCE_DATE_EPOCH", "GCC_EXEC_PREFIX", "COMPILER_PATH", "LIBRARY_PATH")},
                "specification": str(specification), "specification_sha256": digest(specification),
                "database": str(database), "database_sha256": digest(database),
                "tool": str(tool), "tool_sha256": digest(tool), "variants": variants,
                "transform_commands": transform_selected,
                "units": [], "builds": {}, "measurements": [],
                "correctness": "per-pass translation validation under reported models; preprocessing, compiler and whole-program behavior are not proved",
                "protection": "not measured by this build driver"}
    manifest_path = destination / "manifest.json"
    save(manifest_path, manifest)

    def run(argv, label, cwd, seconds=240):
        measurement = measure(argv, destination / "commands" / label, cwd=cwd, wall_seconds=seconds)
        # Full samples, stdout and stderr stay in the individual command directory.
        manifest["measurements"].append({"label": label, **{k: v for k, v in measurement.items() if k != "samples"}})
        save(manifest_path, manifest)
        if measurement["status"] != "completed":
            raise RuntimeError(label + ": " + measurement["status"] + "; see commands/" + label + "/stderr.txt")

    try:
        sources = {}
        compilers = set()
        for index in selected:
            entry = entries[index]
            directory = absolute(entry["directory"], database.parent)
            source = absolute(entry["file"], directory)
            unit = destination / "units" / str(index)
            unit.mkdir(parents=True)
            settings = unit / "configuration.json"
            run([str(tool), "compile-command", str(source), "--compilation-database", str(database),
                 "--compile-command", str(index), "--report", str(settings)], f"configure-{index}", root)
            command = json.loads(settings.read_text())["compilation_command"]
            if command["database_sha256"] != manifest["database_sha256"]:
                raise RuntimeError("compilation database changed during project build")
            arguments = command["expanded_arguments"]
            frozen = unit / "frozen.i"
            invocation = adapt_compile(arguments, source, directory, frozen, preprocess=True)
            if invocation[0] not in compilers:
                run([invocation[0], "--version"], f"compiler-{len(compilers)}", directory)
                compilers.add(invocation[0])
            source_hash = digest(source)
            run(invocation, f"preprocess-{index}", directory)
            record = {"index": index, "source": str(source), "source_sha256": source_hash,
                      "frozen": str(frozen), "frozen_sha256": digest(frozen), "passes": {},
                      "transformation_status": "selected" if index in transform_selected else "explicitly-excluded; not parsed or verified by C-SRD"}
            manifest["units"].append(record)
            outputs = {"original": None, "frozen": frozen}
            if index not in transform_selected:
                outputs.update({name: frozen for name in names})
                sources[index] = (source, directory, arguments, outputs)
                continue
            # Always parse frozen C even when no transformation variants are requested.
            run([str(tool), "analyze", str(frozen), "--scope", "private-regions", "--compilation-database", str(database),
                 "--compile-command", str(index), "--report", str(unit / "analysis.json")], f"analyze-{index}", root)
            for variant in variants:
                name, current = variant["name"], frozen
                records = record["passes"][name] = []
                for number, step in enumerate(variant["passes"]):
                    stem = f"{name}-{number}"
                    candidate, report = unit / (stem + ".i"), unit / (stem + ".json")
                    run([str(tool), "transform", str(current), "-o", str(candidate), "--report", str(report),
                         "--compilation-database", str(database), "--compile-command", str(index), *pass_arguments(step, root)],
                        f"transform-{index}-{stem}", root)
                    data = json.loads(report.read_text())
                    if not data["output_written"] or data["source_sha256"] != digest(current) or data["candidate_sha256"] != digest(candidate):
                        raise RuntimeError("transformation output/report provenance mismatch")
                    transformed = [f for f in data["functions"] if f["status"] in {"transformed", "regions-transformed", "control-transformed", "outline-transformed"}]
                    if any(f["verification"] != "proved-under-model" for f in transformed):
                        raise RuntimeError("unproved transformation in project")
                    records.append({"report": str(report), "source_sha256": data["source_sha256"],
                                    "candidate_sha256": data["candidate_sha256"], "functions_transformed": len(transformed),
                                    "operations_transformed": sum(f.get("operations_transformed", 0) for f in transformed),
                                    "control_nodes": sum(len(r["nodes"]) for f in transformed for r in f.get("control_regions", [])),
                                    "control_branches": sum(r["branches_lowered"] for f in transformed for r in f.get("control_regions", [])),
                                    "control_loops": sum(r["loops_lowered"] for f in transformed for r in f.get("control_regions", [])),
                                    "outlined_expressions": sum(len(f.get("outline_regions", [])) for f in transformed),
                                    "functions_unchanged": len(data["functions"]) - len(transformed)})
                    current = candidate
                outputs[name] = current
            sources[index] = (source, directory, arguments, outputs)
        for name in ["original", "frozen", *names]:
            build = destination / "builds" / name
            build.mkdir(parents=True)
            objects = {}
            record = manifest["builds"][name] = {"objects": [], "links": []}
            for index, (source, directory, arguments, outputs) in sources.items():
                obj = build / f"{index}.o"
                run(adapt_compile(arguments, source, directory, obj, frozen=outputs[name]), f"compile-{name}-{index}", directory)
                objects[index] = obj
                record["objects"].append({"index": index, "path": str(obj), "sha256": digest(obj), "bytes": obj.stat().st_size})
            for recipe in links:
                directory = absolute(recipe.get("directory", "."), root)
                binary = build / recipe["name"]
                run(link_arguments(recipe, directory, objects, binary), f"link-{name}-{recipe['name']}", directory)
                record["links"].append({"name": recipe["name"], "path": str(binary), "sha256": digest(binary), "bytes": binary.stat().st_size})
        if digest(database) != manifest["database_sha256"] or digest(specification) != manifest["specification_sha256"]:
            raise RuntimeError("project configuration changed during build")
        if any(digest(unit["source"]) != unit["source_sha256"] for unit in manifest["units"]):
            raise RuntimeError("source changed during project build")
        manifest["status"] = "built; application behavior not yet tested"
    except Exception as error:
        manifest["status"], manifest["error"] = "failed", str(error)
        raise
    finally:
        save(manifest_path, manifest)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("specification", type=Path)
    parser.add_argument("--csrd", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    with measurement_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            result = build_project(args.csrd.resolve(), args.specification, args.output)
        except (OSError, ValueError, RuntimeError, KeyError, TypeError, IndexError) as error:
            print("project build failed:", error, file=sys.stderr)
            return 1
    print(result["status"] + "; " + str(args.output / "manifest.json"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
