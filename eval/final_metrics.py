"""Merge the deterministic checker results with the manual rubric audit
into eval/results/final_metrics.json — the numbers RESULTS.md reports.
"""
import csv
import json
import os
from collections import defaultdict

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")

# gpt-4.1-mini list prices (USD per 1M tokens) — for cost estimates only;
# token counts themselves come from the API's usage reports.
PRICE_IN, PRICE_OUT = 0.40, 1.60


def main() -> None:
    runs = [json.loads(l) for l in open(os.path.join(RESULTS, "runs.jsonl"))]
    review = {}
    with open(os.path.join(RESULTS, "manual_review.csv")) as fh:
        for row in csv.DictReader(fh):
            review[(row["system"], row["key"], int(row["claim_index"]))] = row["final_status"]

    out = {}
    for system in ("baseline", "multi_agent"):
        rs = [r for r in runs if r["system"] == system]
        finals = []
        for r in rs:
            for i, c in enumerate(r.get("check", {}).get("claims", []), 1):
                finals.append(review[(system, r["key"], i)])
        decline_ok = sum(1 for r in rs
                         if (r["check"]["verdict"] == "SUMMARY") == r["gate_summarises"])
        comps = [r["check"]["completeness"] for r in rs
                 if r["check"]["completeness"] is not None]
        pin = sum(r["usage"]["prompt_tokens"] for r in rs)
        pout = sum(r["usage"]["completion_tokens"] for r in rs)
        entry = {
            "variants": len(rs),
            "claims": len(finals),
            "claims_supported_final": finals.count("SUPPORTED"),
            "claims_overstated_final": finals.count("OVERSTATED"),
            "claims_unsupported_final": finals.count("UNSUPPORTED"),
            "citation_accuracy_final": (finals.count("SUPPORTED") / len(finals)
                                        if finals else None),
            "decline_correct": decline_ok,
            "mean_completeness": sum(comps) / len(comps) if comps else None,
            "mean_seconds_per_variant": sum(r["seconds"] for r in rs) / len(rs),
            "llm_calls": sum(r["usage"]["calls"] for r in rs),
            "prompt_tokens": pin, "completion_tokens": pout,
            "total_tokens": pin + pout,
            "est_cost_usd": round(pin / 1e6 * PRICE_IN + pout / 1e6 * PRICE_OUT, 4),
        }
        if system == "multi_agent":
            entry["critic_rounds"] = sum(r.get("critic_rounds", 0) for r in rs)
            entry["critic_rejections"] = sum(r.get("rejections", 0) for r in rs)
        out[system] = entry
    with open(os.path.join(RESULTS, "final_metrics.json"), "w") as fh:
        json.dump(out, fh, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
