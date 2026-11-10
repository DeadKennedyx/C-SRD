"""Paired summaries of fixed-observer experiments; never convert gaps to strength."""
from collections import Counter, defaultdict
import math
import random
import statistics

SUCCESS = {"recovered-under-source-model", "recovered-on-heldout"}
GAPS = {"unsupported-reconstruction", "missing-function", "unavailable", "inconclusive", "error"}
METRICS = ("wall_seconds", "cpu_seconds", "peak_process_rss_bytes", "peak_sampled_tree_rss_bytes")


def wilson(successes, total):
    if not total:
        return None
    z, p = 1.95996398454, successes / total
    denominator = 1 + z*z/total
    middle = (p + z*z/(2*total)) / denominator
    radius = z * math.sqrt(p*(1-p)/total + z*z/(4*total*total)) / denominator
    return [max(0, middle - radius), min(1, middle + radius)]


def distribution(values):
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None, "bootstrap_95_interval": None}
    result = {"n": len(values), "median": statistics.median(values), "min": min(values), "max": max(values)}
    # Tiny samples cannot support a useful bootstrap interval. Retain every raw value.
    if len(values) < 5:
        result["bootstrap_95_interval"] = None
    else:
        rng = random.Random(72813)
        medians = sorted(statistics.median(rng.choices(values, k=len(values))) for _ in range(2000))
        result["bootstrap_95_interval"] = [medians[49], medians[1949]]
    return result


def summarize(trials):
    measured = [t for t in trials if not t["warmup"]]
    groups = defaultdict(list)
    for t in measured:
        groups[(t["case"], t["profile"], t["variant"], t["budget_id"])].append(t)
    baselines = {(t["case"], t["profile"], t["budget_id"], t["repetition"]): t
                 for t in measured if t["variant"] == "original"}
    summaries = []
    for (case, profile, variant, budget), rows in sorted(groups.items()):
        counts = Counter(t["status"] for t in rows)
        success = sum(counts[s] for s in SUCCESS)
        wrong = counts["wrong-candidate"]
        summary = {"case": case, "profile": profile, "variant": variant, "budget_id": budget,
                   "budget": rows[0].get("budget"),
                   "attempts": len(rows), "outcomes": dict(counts), "successful": success,
                   "success_fraction_all_attempts": success / len(rows),
                   "success_wilson_95_interval": wilson(success, len(rows)),
                   "coverage_gaps": sum(counts[s] for s in GAPS),
                   "wrong_candidate_fraction_all_attempts": wrong / len(rows),
                   "correct_fraction_decidable_submissions": success / (success + wrong) if success + wrong else None,
                   "resource_cost_all_attempts": {}, "paired_successful_ratios": {},
                   "paired_successful_differences": {}}
        for metric in METRICS:
            summary["resource_cost_all_attempts"][metric] = distribution(
                [t["resources"][metric] for t in rows if t.get("resources", {}).get(metric) is not None])
            ratios, differences = [], []
            for t in rows:
                b = baselines.get((case, profile, budget, t["repetition"]))
                if not b or t["status"] not in SUCCESS or b["status"] not in SUCCESS:
                    continue
                a, base = t.get("resources", {}).get(metric), b.get("resources", {}).get(metric)
                if a is not None and base is not None and base > 0:
                    ratios.append(a / base)
                    differences.append(a - base)
            summary["paired_successful_ratios"][metric] = distribution(ratios)
            summary["paired_successful_differences"][metric] = distribution(differences)
        summary["observer_accuracy"] = distribution([t["accuracy"] for t in rows if t.get("accuracy") is not None])
        summary["queries"] = distribution([t["answer"]["training_queries"] for t in rows
                                             if t.get("answer", {}).get("training_queries") is not None])
        summaries.append(summary)
    frontiers = defaultdict(list)
    for group in summaries:
        if group["budget"] and group["successful"] == group["attempts"]:
            frontiers[(group["case"], group["profile"], group["variant"])].append(
                {"budget_id": group["budget_id"], "budget": group["budget"], "repetitions": group["attempts"]})
    return {"groups": summaries,
            "budget_points_succeeding_in_every_measured_repeat": [
                {"case": k[0], "profile": k[1], "variant": k[2], "points": v}
                for k, v in sorted(frontiers.items())],
            "budget_scope": "Minimum is only over the tested grid. No claim of a theoretical minimum, guaranteed success probability or unseen observers.",
            "interpretation": "Each budget group is a success-curve point. Repeats estimate execution noise on this artifact, not population robustness. Ratios condition on BOTH runs succeeding; inspect all outcome counts alongside them.",
            "timeouts": "not recovered within the measured budget; right-censored, not infinite effort",
            "interval_scope": "exploratory within-artifact repeated-run intervals; deterministic repeated successes are not independent program samples",
            "human_effort": "unassessed; separate participant sessions required"}
