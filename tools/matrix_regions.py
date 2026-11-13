"""Region-pass recipes for the existing scalar benchmark matrix.

Compiler-preprocessed originals are admitted by the scalar model first. Each
region pass validates its own actual output; no scalar proof is claimed for a
dispatcher that lies outside that model. Unchanged passes remain visible.
"""
import json
from pathlib import Path

from audit_protection import AuditError, Runner, file_hash
from effort_resources import measure

RECIPES = {
    "private-affine": [("private-regions", "affine")],
    "control": [("control-regions", "identity")],
    "private-affine-control": [("private-regions", "affine"), ("control-regions", "identity")],
    "control-private-affine": [("control-regions", "identity"), ("private-regions", "affine")],
}
MODELS = {"private-regions": "private-integer-frame-c11-v3",
          "control-regions": "opaque-effects-control-graph-c11-v1"}


class ResourceRunner(Runner):
    """Measure outer build/transform commands; keep stdin grading unmeasured."""
    def __init__(self, report, directory):
        super().__init__(report)
        self.directory = directory

    def __call__(self, args, timeout=120, input=None):
        if input is not None:
            return super().__call__(args, timeout, input)
        directory = self.directory / f"{len(self.report['commands']):05d}"
        try:
            resources = measure(args, directory, wall_seconds=timeout)
        except RuntimeError as error:
            raise AuditError(str(error)) from error
        resources.pop("samples", None)
        stdout, stderr = ((directory/name).read_text() for name in ("stdout.txt", "stderr.txt"))
        self.report["commands"].append({"argv": list(map(str, args)), "returncode": resources.get("returncode"),
            "status": resources["status"], "elapsed_seconds": resources["wall_seconds"],
            "stdout": stdout, "stderr": stderr, "resources": resources, "directory": str(directory)})
        if resources["status"] != "completed":
            raise AuditError(f"measured command {resources['status']}: {directory}; {stderr}")
        return stdout


def variants(names, seeds, source):
    result = []
    for name in names:
        for seed in seeds:
            result.append({"id": f"{name}-{seed}", "region_recipe": name, "seed": seed,
                "strategy": "region-pipeline", "control": "identity", "path": str(source),
                "sha256": file_hash(source), "control_flow": "region-dispatch" if "control" in name else "none",
                "control_flow_control": f"private-affine-{seed}" if name in
                    ("private-affine-control", "control-private-affine") else "identity",
                "preparation": "deferred-until-profile-preprocessing"})
    return result


def check_pass(data, source, candidate, scope, seed, function, target):
    if (data.get("action") != "transform" or data.get("scope") != scope or data.get("seed") != str(seed)
            or not data.get("output_written") or data.get("target") != target
            or data.get("source_sha256") != file_hash(source) or data.get("candidate_sha256") != file_hash(candidate)
            or data.get("dependencies") != [] or data.get("candidate_dependencies") != []):
        raise ValueError("region pass input/output/environment binding mismatch")
    rows = data.get("functions", [])
    if len(rows) != 1 or (rows[0]["function"], rows[0]["parameter_count"]) != (function["function"], function["parameter_count"]):
        raise ValueError("region pass changed the scalar public interface")
    row = rows[0]
    transformed = "control-transformed" if scope == "control-regions" else "regions-transformed"
    if row["status"] == "unchanged":
        if data["source_sha256"] != data["candidate_sha256"]:
            raise ValueError("unchanged region pass changed source bytes")
    elif (row["status"] != transformed or row.get("verification") != "proved-under-model"
          or not row.get("context_bindings_verified") or row.get("semantic_model") != MODELS[scope]):
        raise ValueError("region pass lacks frame/graph/binding verification")
    return row


def apply_pipeline(command, csrd, source, variant, directory, function, target, timeout_ms):
    directory.mkdir()
    current, passes = source, []
    for index, (scope, strategy) in enumerate(RECIPES[variant["region_recipe"]]):
        candidate, report = directory/f"pass-{index}.i", directory/f"pass-{index}.json"
        options = ["--strategy", strategy] if scope == "private-regions" else []
        command([csrd, "transform", current, "-o", candidate, "--scope", scope, *options,
                 "--seed", variant["seed"], "--report", report, "--timeout-ms", timeout_ms],
                timeout=max(120, timeout_ms/1000+30))
        data = json.loads(report.read_text())
        row = check_pass(data, current, candidate, scope, variant["seed"], function, target)
        passes.append({"scope": scope, "strategy": strategy, "report": str(report), "sha256": file_hash(report),
                       "source": str(current), "source_sha256": file_hash(current),
                       "candidate": str(candidate), "candidate_sha256": file_hash(candidate),
                       "coverage": row})
        current = candidate
    return current, passes
