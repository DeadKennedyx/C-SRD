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
    result={"schema_version":2,"status":"summarized","builds":len(build["artifacts"]),
            "built_profiles":sorted({r['id'].split('/')[1] for r in build['artifacts']}),
            "reconstruction_profiles":sorted({r['artifact'].split('/')[1] for r in reconstruction['records']}),
            "runtime_profiles":sorted({r['artifact'].split('/')[1] for r in runtime['groups']}),
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
            if "export_sha256" not in row or "export_sha256" not in original:continue
            if file_hash(path)!=row["export_sha256"] or file_hash(base_path)!=original["export_sha256"]:raise ValueError("export changed")
            current=json.loads(path.read_text())["decompile_seconds"];base=json.loads(base_path.read_text())["decompile_seconds"]
            request_times.append(current)
            if base>0:request_ratios.append(current/base)
        item["decompiler_request_wall_seconds"]={"absolute":stats(request_times),"paired_ratios":stats(request_ratios),
            "scope":"decompileFunction request, excluding prior JVM/startup/analysis and later JSON export; not isolated native CPU"}
        item["recovered_operations"]=stats(r.get("reconstruction",{}).get("operations") for r in rows)
        item["recovered_blocks"]=stats(r.get("reconstruction",{}).get("blocks") for r in rows)
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
    result["static"]["repetitions_per_task"]=sorted({len(rows) for rows in groups.values()})
    result["static"]["timing_scope"]="fresh-process Ghidra includes startup/analysis/export; adapter includes Python startup; pilot measurements, no inferential interval"
    by_variant=defaultdict(list)
    for g in runtime["groups"]:by_variant[g["artifact"].rsplit("/",1)[1]].append(g)
    base_groups={(g["artifact"].rsplit("/",1)[0],g["function"],g["loop_count"]):g for g in runtime["groups"] if g["artifact"].endswith("/original")}
    for variant,rows in sorted(by_variant.items()):
        targets=[(g,name,t) for g in rows for name,t in g.get("targets",{}).items()]
        result["runtime"][variant]={"groups":len(rows),"outcomes":dict(Counter(g["status"] for g in rows)),
            "traces":sum(len(g["traces"]) for g in rows),"targets":len(targets),
            "recovered_targets":sum(t["recovery"]["validated_models"]>0 for _,_,t in targets),
            "recovered_within_target":sum(any(scope.startswith("target/") and counts["validated"]>0 for scope,counts in t["by_scope"].items()) for _,_,t in targets),
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
            item["queries"]=dict(Counter(t["split"] for t in g["traces"]))
            base_steps=sum(t["steps"] for t in original["traces"])
            item["instruction_step_ratio"]=item["instruction_steps"]/base_steps if base_steps and g["status"]==original["status"]=="completed" else None
            def combined(row,metric,reduce):
                values=[t["resources"].get(metric) for t in row["traces"]]+[row.get("fit_resources",{}).get(metric)]
                return reduce(values) if row["status"]=="completed" and all(v is not None for v in values) else None
            def total_cpu(row):return combined(row,"cpu_seconds",sum)
            def peak_rss(row):return combined(row,"peak_process_rss_bytes",max)
            item["observer_cpu_seconds"]=total_cpu(g)
            item["observer_cpu_ratio"]=total_cpu(g)/total_cpu(original) if total_cpu(g) is not None and total_cpu(original) else None
            item["observer_peak_process_rss_bytes"]=peak_rss(g)
            item["observer_peak_rss_ratio"]=peak_rss(g)/peak_rss(original) if peak_rss(g) is not None and peak_rss(original) else None
            for metric in METRICS:
                ratios=[a["resources"][metric]/b["resources"][metric] for a,b in zip(g["traces"],original["traces"])
                        if a["resources"].get(metric) is not None and b["resources"].get(metric)]
                item["debugger"][metric]={"absolute":stats(t["resources"].get(metric) for t in g["traces"]),"matched_input_ratios":stats(ratios)}
                a,b=g.get("fit_resources",{}).get(metric),original.get("fit_resources",{}).get(metric)
                item["fit"][metric]={"absolute":a,"ratio":a/b if a is not None and b else None}
            result["runtime"][variant]["paired_groups"].append(item)
        for field in ("observer_cpu_ratio","observer_peak_rss_ratio","instruction_step_ratio"):
            result["runtime"][variant][field+"s"]=stats(g[field] for g in result["runtime"][variant]["paired_groups"])
    result["application"]={"iterations":costs["iterations"],"repetitions":costs["repetitions"],
         "executions":sum(len(r["samples"]) for r in costs["records"]),
         "rss_scope":costs.get("rss_scope","whole-process getrusage high-water; may include pre-exec launcher"),
         "memory_counter_control":costs.get("memory_counter_control"),
         "records":[{k:r[k] for k in ("artifact","wall_seconds_median_paired_ratio","cpu_seconds_median_paired_ratio",
                                       "peak_rss_median_bytes","executable_peak_rss_median_bytes","text_size_ratio","text_identical_to_original","library_bytes") if k in r} for r in costs["records"]]}
    result["build_timings"]=[]
    for record in build["artifacts"]:
        directory=Path(record["library"]).parent
        row={"artifact":record["id"]}
        if "construction_measurements" in record:
            row["stages"]=[{"stage":Path(m["directory"]).name,**{k:m[k] for k in METRICS if k in m}} for m in record["construction_measurements"]]
            row["shared_preprocessing"]=[{k:m[k] for k in METRICS if k in m} for m in record["preprocessing_measurements"]]
            result["build_timings"].append(row)
            continue
        for stage in ("compile-library","transform"):
            path=directory/stage/"command.json"
            data=json.loads(path.read_text()) if path.exists() else {}
            # Old command records include a return code; collector configuration
            # files instead contain a wall-time budget, not an observation.
            row[stage+"_wall_seconds"]=data.get("wall_seconds") if "returncode" in data else None
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
