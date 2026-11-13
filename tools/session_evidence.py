"""Check persistent-session membership and hash chains before grading/analysis."""
from collections import Counter
import json
from pathlib import Path
import statistics

from audit_protection import file_hash

ROOT = Path(__file__).resolve().parents[1]


def local(value):
    path = Path(value)
    if path.is_relative_to("/work"):
        path = ROOT / path.relative_to("/work")
    return path.resolve()


def checked(path, expected):
    path = local(path)
    if file_hash(path) != expected:
        raise ValueError("changed evidence: " + str(path))
    return path


class Evidence:
    def __init__(self):
        self.bindings = {}

    def bind(self, path, expected=None):
        path = Path(path)
        if not path.is_absolute():
            path = ROOT / path
        path = local(path)
        actual = file_hash(path)
        if expected is not None and actual != expected:
            raise ValueError("bound evidence changed: " + str(path))
        key=str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        self.bindings[key] = actual
        return path

    def read(self, path, expected=None):
        return json.loads(self.bind(path, expected).read_text())


def distribution(values):
    values=[v for v in values if v is not None]
    return {"n": len(values), "median": statistics.median(values) if values else None,
            "min": min(values) if values else None, "max": max(values) if values else None}


def answer_candidate(answer, retain_unsupported):
    """An unsupported request cannot carry an executable or be silently omitted."""
    status=answer.get("status","reconstructed")
    if status=="unsupported":
        if not retain_unsupported or answer.get("candidate_sha256") is not None or not isinstance(answer.get("reason"),str) or not answer["reason"]:
            raise ValueError("invalid or undeclared unsupported adapter outcome")
        return None
    value=answer.get("candidate_sha256")
    if status!="reconstructed" or not isinstance(value,str) or len(value)!=64 or any(c not in "0123456789abcdef" for c in value):
        raise ValueError("invalid reconstructed answer hash/status")
    return value


def read_sessions(path):
    """Return validated report, matrix, session payloads and distinct answer groups.

    Original C is inspected here, after observation; this module is never imported
    by the measured worker. Memberships count requests, not independent samples.
    """
    path = local(path)
    report = json.loads(path.read_text())
    if report["status"] != "completed":
        raise ValueError("completed session experiment required; preserve failed run")
    for name, value in report["bindings"].items():
        checked(name, value)
    matrix_path = next(local(p) for p in report["bindings"] if p.endswith("/matrix/matrix.json"))
    matrix = json.loads(matrix_path.read_text())
    records = {(r["case"], r["profile"], r["variant"]): r for r in matrix["records"]}
    protocol = report["protocol"]
    expected = [("first", 1)]
    if protocol["warmup_calls"] > 1:
        expected.append(("warmup", protocol["warmup_calls"]-1))
    expected += [("empty", 0)] + [(f"batch-{i}", protocol["calls"]) for i in range(protocol["batches"])]
    if len(report["sessions"]) != len(report["schedule"]):
        raise ValueError("incomplete randomized schedule")
    payloads, groups = [], {}
    for index, (row, scheduled) in enumerate(zip(report["sessions"], report["schedule"])):
        directory = local(row["directory"])
        if (row["id"] != index or any(row[k] != v for k, v in scheduled.items()) or
                json.loads((directory/"record.json").read_text()) != row or row["status"] != "completed"):
            raise ValueError("session record/schedule mismatch")
        config = json.loads(checked(directory/"config.json", row["config_sha256"]).read_text())
        record = records[(row["case"], row["profile"], row["variant"])]
        if config["binary"] != record["binary"] or row["binary_sha256"] != record["binary_sha256"]:
            raise ValueError("session binary identity mismatch")
        checked(config["binary"], row["binary_sha256"])
        for name in ("warmup_calls", "calls", "batches", "analysis_seconds", "decompile_seconds", "session_seconds"):
            if config[name] != protocol[name]:
                raise ValueError("session configuration differs from protocol")
        if config.get("retain_unsupported",False)!=protocol.get("retain_unsupported",False):
            raise ValueError("unsupported-answer policy differs from protocol")
        resources = json.loads(checked(directory/"measurement/resources.json", row["resources_sha256"]).read_text())
        session = json.loads(checked(directory/"session.json", row["session_sha256"]).read_text())
        if resources["status"] != "completed" or session["status"] != "completed":
            raise ValueError("incomplete session")
        original = records[(row["case"], row["profile"], "original")]
        reference = checked(local(original["binary"]).parent/"function.i", original["preprocessed_sha256"])
        for role in ("jvm", "adapter"):
            phases = session[role]["phases"]
            pattern = [("setup", None)]+expected if role == "jvm" else expected
            if (session[role]["status"] != "completed" or
                    [p["phase"] for p in phases] != [name for name, _ in pattern]):
                raise ValueError("phase sequence mismatch")
            for phase, (_, count) in zip(phases, pattern):
                if phase["resources"]["status"] != "completed":
                    raise ValueError("invalid process counters")
                if count is not None and phase["result"]["requests"] != count:
                    raise ValueError("request count mismatch")
        for native, adapter in zip(session["jvm"]["phases"][1:], session["adapter"]["phases"]):
            nr, ar = native["result"], adapter["result"]
            n = nr["requests"]
            if not (n == len(nr["exports"]) == len(nr["decompile_ns"]) == len(nr["flush_ns"]) ==
                    len(ar["answers"]) == len(ar["metrics"]) == len(ar["reconstruct_ns"])):
                raise ValueError("missing per-request evidence")
            if nr["exports"] != [a["export_sha256"] for a in ar["answers"]]:
                raise ValueError("adapter replay differs from native request sequence")
            memberships = Counter()
            for answer in ar["answers"]:
                candidate_hash=answer_candidate(answer,protocol.get("retain_unsupported",False))
                export_hash=answer["export_sha256"]
                if not isinstance(export_hash,str) or len(export_hash)!=64 or any(c not in "0123456789abcdef" for c in export_hash):
                    raise ValueError("invalid export content hash")
                checked(directory/"exports"/(export_hash+".json"),export_hash)
                if candidate_hash is not None:memberships[(candidate_hash,export_hash)]+=1
            for (candidate_hash, export_hash), count in memberships.items():
                for sha in (candidate_hash, export_hash):
                    if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
                        raise ValueError("invalid content hash")
                candidate = checked(directory/"answers"/(candidate_hash+".c"), candidate_hash)
                export = checked(directory/"exports"/(export_hash+".json"), export_hash)
                key = (original["preprocessed_sha256"], candidate_hash)
                if key not in groups:
                    groups[key] = {"reference": str(reference), "reference_sha256": key[0],
                                   "candidate": str(candidate), "candidate_sha256": key[1],
                                   "export": str(export), "export_sha256": export_hash, "members": []}
                groups[key]["members"].append({"session": index, "phase": native["phase"], "requests": count,
                    "case": row["case"], "profile": row["profile"], "variant": row["variant"],
                    "repetition": row["repetition"], "binary_sha256": row["binary_sha256"],
                    "session_sha256": row["session_sha256"], "export_sha256": export_hash})
        payloads.append({"record": row, "session": session, "resources": resources})
    return report, matrix, payloads, list(groups.values())
