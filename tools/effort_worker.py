"""Fixed observers. Configuration deliberately contains no reference or encoding seed.

Executed as a measured subprocess. Grading is a separate process after this
worker freezes its answer. Observer RNG seeds select inputs, not representations.
"""
import json
from pathlib import Path
import random
import re
import subprocess
import sys
import time

from effort_resources import save
from experiment_support import MASK, input_vectors
from observe_runtime import TRAINING, fit_affine
from pcode_reconstruct import reconstruct, Unsupported

ROOT = Path(__file__).resolve().parents[1]


def predict(model, vector):
    kind = model["kind"]
    if kind == "affine":
        return (model["offset"] + sum(a * x for a, x in zip(model["coefficients"], vector))) & MASK
    if kind == "popcount8":
        return (vector[0] & 255).bit_count()
    if kind == "xor":
        return vector[0] ^ vector[1]
    if kind == "minimum":
        return min(vector)
    raise ValueError("unknown model")


def model_source(function, arity, model, result_offset=0):
    if not re.fullmatch(r"[A-Za-z_][A-Za-z_0-9]*", function) or not 1 <= arity <= 4:
        raise ValueError("invalid public interface")
    names = [f"p{i}" for i in range(arity)]
    if model["kind"] == "affine":
        body = f"{model['offset']}u" + "".join(f" + {a}u * {p}" for a, p in zip(model["coefficients"], names))
    elif model["kind"] == "popcount8":
        body = " + ".join(f"((p0 >> {i}u) & 1u)" for i in range(8))
    elif model["kind"] == "xor":
        body = "p0 ^ p1"
    elif model["kind"] == "minimum":
        body = "p0 < p1 ? p0 : p1"
    else:
        raise ValueError("unknown model")
    return ("#include <stdint.h>\nuint32_t " + function + "(" +
            ", ".join("uint32_t " + n for n in names) + ") { return (" + body + ") + " +
            str(result_offset) + "u; }\n")


def query(binary, vectors, directory):
    save(directory / "queries.json", {"attempted": len(vectors), "completed": None, "inputs": vectors})
    result = subprocess.run([binary], input="".join(" ".join(map(str, v)) + "\n" for v in vectors),
                            text=True, capture_output=True, check=True)
    values = [int(v) for v in result.stdout.splitlines()]
    if len(values) != len(vectors) or any(v < 0 or v > MASK for v in values):
        raise ValueError("invalid query response")
    save(directory / "queries.json", {"attempted": len(vectors), "completed": len(values),
                                      "inputs": vectors, "outputs": values})
    return values


def blackbox(config, directory):
    arity, count = config["arity"], config["query_budget"]
    if not 1 <= arity <= 4 or not 1 <= count <= 4096:
        raise ValueError("arity 1..4 and query budget 1..4096 required")
    basis = [tuple([0] * arity)] + [tuple(int(i == j) for i in range(arity)) for j in range(arity)]
    pool = basis + input_vectors(arity, config["input_seed"], count)
    vectors = list(dict.fromkeys(pool))[:count]
    started = time.perf_counter()
    values = query(config["binary"], vectors, directory)
    query_seconds = time.perf_counter() - started
    models = []
    if count >= arity + 1:
        models.append({"kind": "affine", "offset": values[0],
                       "coefficients": [(v - values[0]) & MASK for v in values[1:arity + 1]]})
    if arity == 1:
        models.append({"kind": "popcount8"})
    if arity == 2:
        models += [{"kind": "xor"}, {"kind": "minimum"}]
    fitted = [m for m in models if all(predict(m, v) == y for v, y in zip(vectors, values))]
    # First fit in the declared, fixed order. Hidden scoring cannot choose a model.
    selected = fitted[0] if fitted else None
    if selected:
        (directory / "candidate.c").write_text(model_source(config["function"], arity, selected))
    return {"status": "candidate" if selected else "no-candidate", "model": selected,
            "training_queries": len(vectors), "models_tested": len(models), "training_fits": fitted,
            "query_seconds": query_seconds, "fit_seconds": time.perf_counter() - started - query_seconds}


def collect_traces(config, directory, vectors):
    traces = []
    for index, vector in enumerate(vectors):
        prefix = directory / str(index)
        input_path, config_path = prefix.with_suffix(".input"), prefix.with_suffix(".json")
        output_path, script = prefix.with_suffix(".trace.json"), prefix.with_suffix(".gdb")
        input_path.write_text(" ".join(map(str, vector)) + "\n")
        save(config_path, {"function": config["function"], "step_limit": config["step_budget"],
                           "input_file": str(input_path), "output": str(output_path)})
        script.write_text("python\nimport sys\nsys.path.insert(0, " + repr(str(ROOT / "tools")) +
                          ")\nimport gdb_trace\ngdb_trace.main(" + repr(str(config_path)) + ")\nend\n")
        save(directory / "trace-progress.json", {"attempted": index + 1, "completed": len(traces)})
        with prefix.with_suffix(".log").open("w") as log:
            subprocess.run([config["gdb"], "--nx", "--batch", "-iex", "set auto-load off",
                            "-x", str(script), "--args", config["binary"]], stdout=log,
                           stderr=subprocess.STDOUT, check=True)
        trace = json.loads(output_path.read_text())
        if trace["status"] not in ("completed", "step-limit"):
            raise ValueError("trace collection failed: " + str(trace))
        # Prefixes are intentional budget-limited observations, never full traces.
        traces.append(trace)
        save(directory / "trace-progress.json", {"attempted": index + 1, "completed": len(traces)})
    return traces


def runtime(config, directory):
    count = config["query_budget"]
    if not 3 <= count <= 128 or not 1 <= config["step_budget"] <= 10000 or config["arity"] != 2:
        raise ValueError("runtime observer requires arity 2, 3..128 traces, 1..10000 steps")
    rng = random.Random(config["input_seed"])
    vectors = (TRAINING + [(rng.getrandbits(32), rng.getrandbits(32)) for _ in range(count)])[:count]
    start = time.perf_counter()
    traces = collect_traces(config, directory, vectors)
    traced = time.perf_counter()
    targets = [(x + y) & MASK for x, y in vectors]
    models, searched = fit_affine(traces, targets)
    negative, _ = fit_affine(traces, targets[1:] + targets[:1])
    return {"status": "candidate" if models else "no-candidate", "models": models,
            "selected_model": models[0] if models else None, "negative_models": negative,
            "target": "known sum x+y modulo 2^32", "training_inputs": vectors,
            "training_queries": len(vectors), "locations_searched": searched,
            "instruction_steps": sum(t["steps"] for t in traces),
            "value_observations": sum(len(s["values"]) for t in traces for s in t["samples"]),
            "trace_statuses": [t["status"] for t in traces],
            "stack_read_failures": sum(t["stack_read_failures"] for t in traces),
            "trace_seconds": traced - start, "fit_seconds": time.perf_counter() - traced}


def ghidra(config, directory):
    project = directory / "project"
    project.mkdir()
    start = time.perf_counter()
    subprocess.run([config["headless"], str(project), "effort", "-import", config["binary"],
                    "-deleteProject", "-max-cpu", "2", "-analysisTimeoutPerFile", str(config["analysis_seconds"]),
                    "-scriptPath", str(ROOT / "tools/ghidra"), "-postScript", "ExportCSRD.java",
                    config["function"], str(config["arity"]), str(config["decompile_seconds"]), str(directory)],
                   check=True)
    exported = time.perf_counter()
    export = json.loads((directory / "export.json").read_text())
    result = {"status": export["status"], "headless_seconds": exported - start,
              "target_decompile_requests": 1 if "decompile_seconds" in export else 0,
              "export": {k: v for k, v in export.items() if k not in ("nodes", "operations")},
              "pcode_nodes": len(export.get("nodes", [])), "pcode_operations": len(export.get("operations", [])),
              "training_queries": 0}
    if export["status"] == "decompiled":
        try:
            (directory / "candidate.c").write_text(reconstruct(export))
            result["status"] = "candidate"
        except Unsupported as error:
            result.update(status="unsupported-reconstruction", error=str(error))
    result["reconstruction_seconds"] = time.perf_counter() - exported
    return result


def main():
    path = Path(sys.argv[1]).resolve()
    config, directory = json.loads(path.read_text()), path.parent
    start = time.perf_counter()
    try:
        if config["observer"] == "runtime-grade":
            traces = collect_traces(config, directory, config["vectors"])
            result = {"status": "completed", "traces": traces}
        elif config["observer"] == "output-grade":
            values = query(config["binary"], config["vectors"], directory)
            predictions = [predict(config["model"], v) for v in config["vectors"]]
            correct = sum(a == b for a, b in zip(predictions, values))
            result = {"status": "completed", "correct": correct, "total": len(values),
                      "accuracy": correct / len(values), "predictions": predictions}
        else:
            result = {"blackbox": blackbox, "runtime": runtime, "ghidra": ghidra}[config["observer"]](config, directory)
        result["observer_seconds"] = time.perf_counter() - start
    except (OSError, ValueError, KeyError, subprocess.SubprocessError) as error:
        result = {"status": "error", "error": str(error), "observer_seconds": time.perf_counter() - start}
        save(directory / "answer.json", result)
        return 1
    save(directory / "answer.json", result)
    return 0


if __name__ == "__main__":
    sys.exit(main())
