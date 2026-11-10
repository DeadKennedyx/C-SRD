#!/usr/bin/env python3
"""Re-score unchanged saved reconstructions against hash-bound frozen references.

This does not rerun or modify the decompiler/reconstructor and is not a new
independent observer experiment. Run in the matrix's filesystem namespace.
"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_decompiler import scoring_reference, verify
from audit_protection import AuditError, Runner, executable, file_hash, write_json


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", action="append", required=True)
    parser.add_argument("--csrd", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    root = args.output_dir.resolve()
    root.mkdir(parents=True, exist_ok=False)
    result = {"status": "running", "commands": [], "sources": [], "rescored": [],
              "inference_changed": False,
              "implementation": {str(p.relative_to(ROOT)): file_hash(p) for p in
                  [Path(__file__), ROOT / "tools/audit_decompiler.py", ROOT / "tools/pcode_reconstruct.py"]}}
    command = Runner(result)
    try:
        csrd = executable(args.csrd)
        result["csrd_sha256"] = file_hash(csrd)
        for report_path in map(Path, args.report):
            prior = json.loads(report_path.read_text())
            if prior["status"] != "completed":
                raise ValueError("completed original observer report required")
            matrix_path = Path(prior["matrix"]["path"])
            if file_hash(matrix_path) != prior["matrix"]["sha256"]:
                raise ValueError("original matrix changed")
            matrix = json.loads(matrix_path.read_text())
            if result["csrd_sha256"] != matrix["tools"]["csrd"]["sha256"]:
                raise ValueError("same frontend/model verifier binary required")
            result["sources"].append({"path": str(report_path), "sha256": file_hash(report_path)})
            for observation in prior["observations"]:
                if observation["status"] != "recovered-under-source-model":
                    continue
                directory = Path(observation["export"]["path"]).parent
                recovered = directory / "recovered.c"
                if file_hash(recovered) != observation["recovered_c_sha256"]:
                    raise ValueError("saved reconstruction changed")
                cell = next(r for r in matrix["records"] if all(r[k] == observation[k] for k in ("case", "profile", "variant")))
                if file_hash(cell["binary"]) != observation["binary_sha256"]:
                    raise ValueError("observed binary changed")
                frozen, expected_hash = scoring_reference(matrix, cell)
                out = root / (str(len(result["rescored"])) + ".json")
                proof = verify(command, csrd, frozen, recovered, out, prior["protocol"]["verification_ms"])
                if file_hash(frozen) != expected_hash or file_hash(recovered) != observation["recovered_c_sha256"]:
                    raise ValueError("scoring input changed")
                result["rescored"].append({**{k: observation[k] for k in ("case", "profile", "variant")},
                    "recovered_sha256": file_hash(recovered), "frozen_reference_sha256": expected_hash,
                    "proof_path": str(out), "proof_sha256": file_hash(out), "verification": proof["verification"]})
                if proof["verification"] != "proved-under-model":
                    raise ValueError("frozen-reference scoring did not preserve the original positive result")
        result["status"] = "completed"
    except (AuditError, OSError, ValueError, KeyError, StopIteration) as error:
        result.update(status="failed", error=str(error))
    finally:
        write_json(root / "rescoring.json", result)
    print(result["status"], len(result["rescored"]), "rescored")
    return int(result["status"] != "completed")


if __name__ == "__main__":
    sys.exit(main())
