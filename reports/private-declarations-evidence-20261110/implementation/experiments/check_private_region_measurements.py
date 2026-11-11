#!/usr/bin/env python3
"""Check artifact bindings, frame proofs, raw counters and paired pilot summaries."""
import argparse
import json
from pathlib import Path
from statistics import median
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from audit_protection import file_hash, write_json


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("report",type=Path);p.add_argument("--output",type=Path,required=True)
    args = p.parse_args()
    result = {"status":"checking","report_sha256":file_hash(args.report)}

    def require(value, message):
        if not value: raise ValueError(message)

    def checked(path, sha):
        require(file_hash(path) == sha, "artifact changed: "+str(path))

    try:
        r = json.loads(args.report.read_text())
        require(r["status"] == "completed", "measurement incomplete")
        for path, sha in r["implementation"].items(): checked(ROOT/path,sha)
        for tool in r["tools"].values(): checked(tool["path"],tool["sha256"])
        checked(r["source"]["path"],r["source"]["sha256"])
        checked(args.report.parent/"harness.c",r["harness_sha256"])
        checked(args.report.parent/"model-guard.c",r["guard_sha256"])
        groups = {entry["profile"]["id"] for entry in r["profiles"] if entry["status"] == "available"}
        require(len(r["builds"]) == len(groups)*4, "incomplete build membership")
        membership = {(b["profile"],b["variant"]) for b in r["builds"]}
        require(membership == {(g,v) for g in groups for v in ("original","identity","affine","original-copy")}, "duplicate/unknown build")
        obligations = 0
        for build in r["builds"]:
            checked(build["binary"],build["binary_sha256"]); checked(build["source"],build["source_sha256"])
            original = next(b for b in r["builds"] if b["profile"] == build["profile"] and b["variant"] == "original")
            if build["variant"] == "original-copy": require(build["binary_sha256"] == original["binary_sha256"], "copy differs")
            if build["variant"] in ("identity","affine"):
                proof = json.loads(Path(build["source"]).with_suffix(".json").read_text())
                require(proof["source_sha256"] == original["source_sha256"] and proof["candidate_sha256"] == build["source_sha256"], "proof/source identity mismatch")
                require(proof["scope"] == "private-regions" and proof["output_written"] and len(proof["functions"]) == 2, "wrong proof scope")
                source = Path(original["source"]).read_bytes();candidate = Path(build["source"]).read_bytes()
                frames = sorted([g for f in proof["functions"] for g in f["private_regions"]],key=lambda g:g["candidate_begin"])
                expected_frames = 3 if r["protocol"].get("fixture","private_regions.c") == "private_regions.c" else 6
                require(len(frames) == expected_frames, "unexpected frame coverage")
                if r["protocol"].get("fixture") == "private_declarations.c":
                    require(all(f.get("context_bindings_verified") for f in proof["functions"]), "unchecked context bindings")
                    require(sum(len(g.get("declared_objects",[])) for g in frames) == 7, "unexpected declaration coverage")
                restored = candidate
                import hashlib
                for frame in reversed(frames):
                    old = source[frame["source_begin"]:frame["source_end"]]
                    new = candidate[frame["candidate_begin"]:frame["candidate_end"]]
                    require(hashlib.sha256(old).hexdigest() == frame["original_fragment_sha256"] and
                            hashlib.sha256(new).hexdigest() == frame["emitted_fragment_sha256"], "fragment mismatch")
                    require(frame["proof"]["status"] == "proved-under-model", "unproved frame")
                    restored = restored[:frame["candidate_begin"]]+old+restored[frame["candidate_end"]:]
                    obligations += 1
                require(restored == source, "outside-region bytes changed")
        expected = {(b,n) for b in range(len(r["builds"])) for n in range(r["protocol"]["repetitions"])}
        require(len(r["samples"]) == len(expected) and {(s["build"],s["repetition"]) for s in r["samples"]} == expected, "sample membership incomplete")
        for i,sample in enumerate(r["samples"]):
            directory = args.report.parent/f"sample-{i}"
            require(json.loads((directory/"resources.json").read_text()) == sample["resources"], "raw counters differ")
            require(sample["resources"]["status"] == "completed", "sample incomplete")
            build = r["builds"][sample["build"]]
            require(sample["resources"]["argv"] == [build["binary"],str(r["protocol"]["iterations"]),str(20261110+sample["repetition"])], "sample invoked wrong workload")
            stdout = (directory/"stdout.txt").read_text().split()
            require(float(stdout[0]) == sample["application_wall_seconds"] and list(map(int,stdout[1:])) == sample["outputs"], "raw output differs")
        require(len(r["summaries"]) == len(r["builds"]), "summary membership incomplete")
        for bi, summary in enumerate(r["summaries"]):
            build = r["builds"][bi]
            require((summary["profile"],summary["variant"]) == (build["profile"],build["variant"]), "summary/build mismatch")
            base = next(i for i,b in enumerate(r["builds"]) if b["profile"] == build["profile"] and b["variant"] == "original")
            values = sorted([s for s in r["samples"] if s["build"] == bi],key=lambda s:s["repetition"])
            original = sorted([s for s in r["samples"] if s["build"] == base],key=lambda s:s["repetition"])
            require([s["outputs"] for s in values] == [s["outputs"] for s in original], "benchmark outputs mismatch")
            for metric, counts in summary["paired_ratios"].items():
                sample_value = lambda s:s["application_wall_seconds"] if metric == "application_wall" else s["resources"][metric]
                ratios = [sample_value(a)/sample_value(b) for a,b in zip(values,original)]
                require(counts == {"samples":ratios,"min":min(ratios),"max":max(ratios),"median":median(ratios)}, "paired summary mismatch")
        result.update(status="checked",builds=len(r["builds"]),samples=len(r["samples"]),bound_frame_obligations=obligations,
                      scope="evidence identity and arithmetic summary checks; not independent binary equivalence or a solver replay")
    except Exception as e: result.update(status="failed",reason=str(e))
    write_json(args.output,result);print(json.dumps(result,indent=2))
    return int(result["status"] != "checked")


if __name__ == "__main__": raise SystemExit(main())
