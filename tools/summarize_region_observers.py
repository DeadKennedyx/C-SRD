#!/usr/bin/env python3
"""Check and summarize matched region observer/application evidence without pooling scopes."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics

from audit_protection import file_hash, write_json

METRICS=("wall_seconds","cpu_seconds","peak_process_rss_bytes","peak_sampled_tree_rss_bytes")


def stats(values):
    values=[v for v in values if v is not None]
    return {"n":len(values),"median":statistics.median(values) if values else None,
            "min":min(values) if values else None,"max":max(values) if values else None}


def summarize(build,reconstruction,runtime,costs):
    if build["status"]!="validated" or any(r["status"]!="completed" for r in (reconstruction,runtime,costs)):
        raise ValueError("all reports must be complete")
    result={"schema_version":1,"status":"summarized","builds":len(build["artifacts"]),
            "observed_build_profiles":sorted({r['id'].split('/')[1] for r in build['artifacts']}),
            "static":{},"runtime":{},"application":{},"claims":{"whole_function_proof":False,"human_effort":"unmeasured",
            "success_scope":"finite effect grading and known-target heldout recovery; no claim about every compiler/profile/input/observer"}}
    records=reconstruction["records"]
    result["static"].update(attempts=len(records),outcomes=dict(Counter(r["status"] for r in records)),
                            graded_comparisons=sum(r.get("grading",{}).get("comparisons",0) for r in records),
                            controls=[{k:r[k] for k in ("artifact","function","mutation","result")} for r in reconstruction.get("controls",[])])
    baseline={(r["artifact"].rsplit("/",1)[0],r["function"],r["repetition"]):r for r in records if r["artifact"].endswith("/original")}
    groups=defaultdict(list)
    for r in records:groups[(r["artifact"],r["function"])].append(r)
    paired=[]
    for (artifact,function),rows in sorted(groups.items()):
        item={"artifact":artifact,"function":function,"attempts":len(rows),"outcomes":dict(Counter(r["status"] for r in rows)),"phases":{}}
        request_times=[];request_ratios=[]
        for row in rows:
            path=Path(row["directory"])/"export/export.json"
            original=baseline[(artifact.rsplit("/",1)[0],function,row["repetition"])]
            base_path=Path(original["directory"])/"export/export.json"
            if file_hash(path)!=row["export_sha256"] or file_hash(base_path)!=original["export_sha256"]:raise ValueError("export changed")
            current=json.loads(path.read_text())["decompile_seconds"];base=json.loads(base_path.read_text())["decompile_seconds"]
            request_times.append(current)
            if base>0:request_ratios.append(current/base)
        item["decompiler_request_wall_seconds"]={"absolute":stats(request_times),"paired_ratios":stats(request_ratios),
            "scope":"decompileFunction request, excluding prior JVM/startup/analysis and later JSON export; not isolated native CPU"}
        item["recovered_operations"]=stats(r["reconstruction"].get("operations") for r in rows)
        item["recovered_blocks"]=stats(r["reconstruction"].get("blocks") for r in rows)
        for phase in ("decompilation","adapter"):
            measurements={}
            for metric in METRICS:
                ratios=[]
                for row in rows:
                    original=baseline[(artifact.rsplit("/",1)[0],function,row["repetition"])]
                    a,b=row.get(phase,{}).get(metric),original.get(phase,{}).get(metric)
                    if a is not None and b is not None and b>0:ratios.append(a/b)
                measurements[metric]={"absolute":stats(r.get(phase,{}).get(metric) for r in rows),"paired_ratios":stats(ratios)}
            item["phases"][phase]=measurements
        paired.append(item)
    result["static"]["matched_groups"]=paired
    result["static"]["timing_scope"]="fresh-process Ghidra includes startup/analysis/export; adapter includes Python startup; three repeats are a pilot, no inferential interval"
    by_variant=defaultdict(list)
    for g in runtime["groups"]:by_variant[g["artifact"].rsplit("/",1)[1]].append(g)
    base_groups={(g["artifact"].rsplit("/",1)[0],g["function"],g["loop_count"]):g for g in runtime["groups"] if g["artifact"].endswith("/original")}
    for variant,rows in sorted(by_variant.items()):
        targets=[(g,name,t) for g in rows for name,t in g.get("targets",{}).items()]
        result["runtime"][variant]={"groups":len(rows),"outcomes":dict(Counter(g["status"] for g in rows)),
            "traces":sum(len(g["traces"]) for g in rows),"targets":len(targets),
            "recovered_targets":sum(t["recovery"]["validated_models"]>0 for _,_,t in targets),
            "false_models":sum(t["recovery"]["false_models"] for _,_,t in targets),
            "inconclusive_models":sum(t["recovery"]["inconclusive_models"] for _,_,t in targets),
            "negative_control_validated_models":sum(t["negative_control"]["validated_models"] for _,_,t in targets),
            "misses":[{"artifact":g["artifact"],"function":g["function"],"loop_count":g["loop_count"],"target":name,"fit_status":t["fit_status"]}
                      for g,name,t in targets if not t["recovery"]["validated_models"]],"paired_groups":[]}
        widths=defaultdict(list)
        for _,_,target in targets:widths[target.get("bits",32)].append(target)
        result["runtime"][variant]["by_width"]={str(bits):{
            "targets":len(items),"recovered_targets":sum(t["recovery"]["validated_models"]>0 for t in items),
            "insufficient_variation":sum(t["fit_status"]=="insufficient-variation" for t in items),
            "false_models":sum(t["recovery"]["false_models"] for t in items),
            "negative_control_validated_models":sum(t["negative_control"]["validated_models"] for t in items)
        } for bits,items in sorted(widths.items())}
        for g in rows:
            original=base_groups[(g["artifact"].rsplit("/",1)[0],g["function"],g["loop_count"])]
            item={"artifact":g["artifact"],"function":g["function"],"loop_count":g["loop_count"],
                  "instruction_steps":sum(t["steps"] for t in g["traces"]),"debugger":{},"fit":{},
                  "sampled_stack_depth_bytes":stats(t.get("max_observed_stack_depth_bytes") for t in g["traces"])}
            for metric in METRICS:
                ratios=[a["resources"][metric]/b["resources"][metric] for a,b in zip(g["traces"],original["traces"])
                        if a["resources"].get(metric) is not None and b["resources"].get(metric)]
                item["debugger"][metric]={"absolute":stats(t["resources"].get(metric) for t in g["traces"]),"matched_input_ratios":stats(ratios)}
                a,b=g.get("fit_resources",{}).get(metric),original.get("fit_resources",{}).get(metric)
                item["fit"][metric]={"absolute":a,"ratio":a/b if a is not None and b else None}
            result["runtime"][variant]["paired_groups"].append(item)
    result["application"]={"iterations":costs["iterations"],"repetitions":costs["repetitions"],
         "executions":sum(len(r["samples"]) for r in costs["records"]),
         "records":[{k:r[k] for k in ("artifact","wall_seconds_median_paired_ratio","cpu_seconds_median_paired_ratio",
                                       "peak_rss_median_bytes","text_size_ratio","library_bytes")} for r in costs["records"]]}
    result["build_timings"]=[]
    for record in build["artifacts"]:
        directory=Path(record["library"]).parent
        row={"artifact":record["id"]}
        for stage in ("compile-library","transform"):
            path=directory/stage/"command.json"
            row[stage+"_wall_seconds"]=json.loads(path.read_text())["wall_seconds"] if path.exists() else None
        result["build_timings"].append(row)
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("build","reconstruction","runtime","costs","output"):p.add_argument("--"+name,required=True)
    args=p.parse_args();paths={k:Path(getattr(args,k)).resolve() for k in ("build","reconstruction","runtime","costs")}
    reports={k:json.loads(v.read_text()) for k,v in paths.items()}
    checksum=file_hash(paths["build"])
    if any(reports[k]["build_sha256"]!=checksum for k in ("reconstruction","runtime","costs")):raise ValueError("reports use different build manifests")
    summary=summarize(**reports)
    summary["report_hashes"]={k:file_hash(v) for k,v in paths.items()}
    write_json(Path(args.output),summary)
