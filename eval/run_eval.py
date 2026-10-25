"""Run the head-to-head evaluation.

For each of the 36 fixed variants: build the evidence packet once
(Retriever), run BOTH systems on the identical packet, check both
outputs with the deterministic checker, and record everything —
including errors. A variant whose run fails is recorded as an error,
never silently dropped.

Resumable: completed (variant, system) pairs in runs.jsonl are skipped
on re-run, so an interrupted evaluation continues where it stopped.

Outputs (eval/results/):
  runs.jsonl    one line per (variant, system): output, checks, usage,
                latency, coordination accounting (multi-agent), errors
  metrics.json  the aggregate comparison
"""
import json
import os
import sys
import time

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src import baseline, graph  # noqa: E402
from src.checker import check_output  # noqa: E402
from src.llm import LLM, LLMError  # noqa: E402
from src.retriever import build_packet  # noqa: E402
from src.universe import Universe, out_of_universe_variant  # noqa: E402

HERE = os.path.dirname(__file__)
RESULTS = os.path.join(HERE, "results")
RUNS = os.path.join(RESULTS, "runs.jsonl")


def load_done() -> dict:
    done = {}
    if os.path.exists(RUNS):
        with open(RUNS) as fh:
            for line in fh:
                rec = json.loads(line)
                if "error" not in rec:
                    done[(rec["key"], rec["system"])] = rec
    return done


def main() -> None:
    os.makedirs(RESULTS, exist_ok=True)
    eval_set = pd.read_csv(os.path.join(HERE, "eval_set.csv"), dtype={"key": str})
    uni = Universe()
    done = load_done()
    records = list(done.values())
    print(f"resuming with {len(done)} completed (variant, system) pairs", flush=True)

    for row in eval_set.itertuples():
        key = str(row.key)
        if row.stratum == "out_of_universe":
            aid = int(key.split(":")[1])
            variant = out_of_universe_variant(aid, row.gene, row.name)
        else:
            variant = uni.get(key)
        packet = build_packet(variant)
        gate = variant.gate_summarises
        for system in ("baseline", "multi_agent"):
            if (key, system) in done:
                continue
            llm = LLM()
            rec = {"key": key, "gene": row.gene, "name": row.name,
                   "stratum": row.stratum, "gate_summarises": gate,
                   "system": system, "packet_records": packet.record_ids(),
                   "live_errors": packet.live_errors}
            try:
                out = (baseline.run(packet, llm) if system == "baseline"
                       else graph.run(packet, llm))
                rec.update({"text": out["text"], "seconds": out["seconds"],
                            "usage": out["usage"]})
                if system == "multi_agent":
                    rec.update({"critic_rounds": out["critic_rounds"],
                                "rejections": out["rejections"],
                                "events": out["events"]})
                rec["check"] = check_output(packet, out["text"])
            except (LLMError, Exception) as e:  # recorded, never hidden
                rec["error"] = f"{type(e).__name__}: {e}"
            records.append(rec)
            with open(RUNS, "a") as fh:
                fh.write(json.dumps(rec) + "\n")
            status = rec.get("error", rec.get("check", {}).get("verdict", "?"))
            print(f"[{time.strftime('%H:%M:%S')}] {key} {system}: {status}", flush=True)

    write_metrics(records)


def write_metrics(records: list[dict]) -> None:
    metrics = {}
    for system in ("baseline", "multi_agent"):
        rs = [r for r in records if r["system"] == system]
        ok = [r for r in rs if "error" not in r]
        claims = [c for r in ok for c in r["check"]["claims"]]
        decided = [c for c in claims if c["status"] in ("SUPPORTED", "UNSUPPORTED")]
        decline_ok = sum(
            1 for r in ok
            if (r["check"]["verdict"] == "SUMMARY") == r["gate_summarises"])
        comps = [r["check"]["completeness"] for r in ok
                 if r["check"]["completeness"] is not None]
        metrics[system] = {
            "runs": len(rs), "errors": len(rs) - len(ok),
            "claims_total": len(claims),
            "claims_supported": sum(1 for c in claims if c["status"] == "SUPPORTED"),
            "claims_unsupported": sum(1 for c in claims if c["status"] == "UNSUPPORTED"),
            "claims_unverifiable_pending_manual": sum(
                1 for c in claims if c["status"] == "UNVERIFIABLE"),
            "claims_flagged_intensifier": sum(1 for c in claims if c.get("flag_manual")),
            "citation_accuracy_decided_only": (
                sum(1 for c in claims if c["status"] == "SUPPORTED") / len(decided)
                if decided else None),
            "decline_correct": decline_ok, "decline_total": len(ok),
            "mean_completeness": (sum(comps) / len(comps)) if comps else None,
            "mean_seconds": (sum(r["seconds"] for r in ok) / len(ok)) if ok else None,
            "tokens": {
                "calls": sum(r["usage"]["calls"] for r in ok),
                "prompt": sum(r["usage"]["prompt_tokens"] for r in ok),
                "completion": sum(r["usage"]["completion_tokens"] for r in ok),
                "total": sum(r["usage"]["total_tokens"] for r in ok),
            },
        }
        if system == "multi_agent":
            metrics[system]["critic_rounds"] = sum(r.get("critic_rounds", 0) for r in ok)
            metrics[system]["rejections"] = sum(r.get("rejections", 0) for r in ok)
    with open(os.path.join(RESULTS, "metrics.json"), "w") as fh:
        json.dump(metrics, fh, indent=2)
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
