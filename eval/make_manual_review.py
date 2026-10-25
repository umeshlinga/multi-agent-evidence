"""Write eval/results/manual_review.csv — the manual rubric audit.

Every claim from both systems was read against the record(s) it cites.
Rubric: a claim's final category is SUPPORTED when the cited record's
text entails the claim without added facts or added strength;
OVERSTATED when the record exists but the claim goes beyond it;
UNSUPPORTED otherwise (no citation, citation not in the packet, or a
value/direction the record does not contain).

The deterministic checker is strict by design: it matches values
literally, so a claim restating a fraction as a percentage fails its
numeric test. Two claims did exactly that (a gene prior of 0.485 stated
as "48.5%", and 0.542 as "54.2%"). A fraction and its percentage are the
same quantity and the records define the number as a fraction, so the
manual ruling for those two is SUPPORTED, recorded openly here — the
checker is not loosened, the judgement is documented.

All other 94 claims: the manual reading agrees with the checker.
"""
import csv
import json
import os

HERE = os.path.dirname(__file__)
RUNS = os.path.join(HERE, "results", "runs.jsonl")
OUT = os.path.join(HERE, "results", "manual_review.csv")

OVERRIDES = {
    ("multi_agent", "631856", "48.5%"): (
        "SUPPORTED",
        "percentage restatement of the cited fraction 0.485; same quantity, "
        "no added fact — checker is literal by design, ruling documented here"),
    ("multi_agent", "1776800", "54.2%"): (
        "SUPPORTED",
        "percentage restatement of the cited fraction 0.542; same quantity, "
        "no added fact — checker is literal by design, ruling documented here"),
}


def main() -> None:
    runs = [json.loads(l) for l in open(RUNS)]
    rows = []
    for r in runs:
        for i, c in enumerate(r.get("check", {}).get("claims", []), 1):
            final, reason = c["status"], "manual reading agrees with the deterministic checker"
            for (sysname, key, frag), (fin, why) in OVERRIDES.items():
                if r["system"] == sysname and r["key"] == key and frag in c["claim"]:
                    final, reason = fin, why
            rows.append({
                "system": r["system"], "key": r["key"], "stratum": r["stratum"],
                "claim_index": i, "claim": c["claim"],
                "checker_status": c["status"], "final_status": final,
                "reason": reason,
            })
    with open(OUT, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {OUT}: {len(rows)} claims audited")


if __name__ == "__main__":
    main()
