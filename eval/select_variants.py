"""Select the fixed evaluation set: 36 variants, stratified.

  12 summarised  — Build 1's gate summarises them; sampled across the
                   calibrated-probability range (4 high >=0.9, 4 mid,
                   4 low <=0.1) so easy and hard cases are both present.
  12 declined    — in Build 1's test set; the gate declines them.
  12 out-of-universe — real ClinVar variants (current ClinVar summary
                   file) that are NOT in Build 1's test set, in genes
                   Build 1 covers; the gate declines them and the
                   Retriever must go live.

Selection is seeded and deterministic; the set is written to
eval/eval_set.csv and never re-drawn.
"""
import gzip
import os
import random
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from src.universe import Universe  # noqa: E402

SEED = 20261025
OUT = os.path.join(os.path.dirname(__file__), "eval_set.csv")
CURRENT = os.path.expanduser("~/workspace/vus-evidence-agent/data/variant_summary_current.txt.gz")


def main() -> None:
    rng = random.Random(SEED)
    uni = Universe()
    pred = pd.read_csv(os.path.expanduser(
        "~/workspace/vus-evidence-agent/data/processed_v2/test_predictions_ensemble.csv"))
    prob = {int(r.allele_id): float(r.prob_ensemble) for r in pred.itertuples()}

    rows = []
    summ = uni.summarised_keys()
    high = [k for k in summ if prob[int(k)] >= 0.9]
    mid = [k for k in summ if 0.1 < prob[int(k)] < 0.9]
    low = [k for k in summ if prob[int(k)] <= 0.1]
    for pool in (high, mid, low):
        for k in rng.sample(sorted(pool, key=int), 4):
            v = uni.get(k)
            rows.append({"key": k, "gene": v.gene, "name": v.name,
                         "stratum": "summarised", "gate_summarises": True})
    for k in rng.sample(sorted(uni.declined_keys(), key=int), 12):
        v = uni.get(k)
        rows.append({"key": k, "gene": v.gene, "name": v.name,
                     "stratum": "declined", "gate_summarises": False})

    test_ids = {int(k) for k in uni.test_keys()}
    test_genes = {uni.get(k).gene for k in uni.test_keys()}
    candidates = []
    with gzip.open(CURRENT, "rt") as fh:
        header = fh.readline().lstrip("#").rstrip("\n").split("\t")
        idx = {name: i for i, name in enumerate(header)}
        for line in fh:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < len(header):
                continue
            try:
                aid = int(parts[idx["AlleleID"]])
            except ValueError:
                continue
            if aid in test_ids:
                continue
            if parts[idx["Type"]] != "single nucleotide variant":
                continue
            gene = parts[idx["GeneSymbol"]]
            name = parts[idx["Name"]]
            if gene not in test_genes or "(p." not in name or ":c." not in name:
                continue
            candidates.append((aid, gene, name))
    print(f"out-of-universe candidates: {len(candidates)}")
    for aid, gene, name in rng.sample(candidates, 12):
        rows.append({"key": f"OOU:{aid}", "gene": gene, "name": name,
                     "stratum": "out_of_universe", "gate_summarises": False})

    df = pd.DataFrame(rows)
    df.to_csv(OUT, index=False)
    print(df["stratum"].value_counts().to_string())
    print(f"wrote {OUT} ({len(df)} variants)")


if __name__ == "__main__":
    main()
