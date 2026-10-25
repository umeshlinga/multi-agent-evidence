"""The local evidence universe — the same records Build 1 uses.

Build 1 (vus-evidence-agent) serves each variant in its temporal test set
from three prediction-time record kinds, all frozen at the 2024-01 cutoff:

  1. AlphaMissense score + class        -> record AM:chr:pos:ref>alt
  2. Frozen ClinVar status (sig_then)   -> record CLINVAR:allele<allele_id>
  3. Gene prior from frozen train       -> record GENEPRIOR:<gene>:frozen2024

plus the model's calibrated probability, which Build 1 prints on the
report but does not count as an evidence item:

  4. Ensemble calibrated P(pathogenic)  -> record MODEL:ensemble:<allele_id>

Build 1's gate (src/vus_agent/agent.py, MIN_EVIDENCE = 3) summarises a
variant only when it has all three evidence items AND a calibrated
probability; in the frozen data that is exactly the 10,373 variants with
an AlphaMissense score. Every other test-set variant, and every variant
outside the test set, is declined by the gate.

This module rebuilds those records deterministically from Build 1's own
processed files. The future reclassification (sig_now / label) is never
put in a record — it is evaluation truth only.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field

import pandas as pd

BUILD1 = os.path.expanduser("~/workspace/vus-evidence-agent")
PROCESSED = os.path.join(BUILD1, "data", "processed_v2")

MIN_EVIDENCE = 3  # Build 1's gate, mirrored


@dataclass
class Record:
    record_id: str
    source: str          # AM | CLINVAR_FROZEN | GENEPRIOR | MODEL | CLINVAR_LIVE | PUBMED_LIVE
    detail: str          # the fact text a claim may rest on
    counts_for_gate: bool = False

    def render(self) -> str:
        return f"[{self.record_id}] ({self.source}) {self.detail}"


@dataclass
class Variant:
    key: str             # allele id as str for test variants, "OOU:<allele_id>" otherwise
    gene: str
    name: str
    stratum: str = ""    # summarised | declined | out_of_universe
    records: list[Record] = field(default_factory=list)

    @property
    def gate_summarises(self) -> bool:
        """Build 1's gate decision for this variant, from the records alone."""
        n_evidence = sum(1 for r in self.records if r.counts_for_gate)
        has_model = any(r.source == "MODEL" for r in self.records)
        return n_evidence >= MIN_EVIDENCE and has_model


class Universe:
    def __init__(self) -> None:
        test = pd.read_csv(os.path.join(PROCESSED, "test_reclassified.csv"))
        pred = pd.read_csv(os.path.join(PROCESSED, "test_predictions_ensemble.csv"))
        feats = pd.read_csv(os.path.join(PROCESSED, "test_features.csv"))
        am_class_by_id = {int(r.allele_id): r.am_class for r in feats.itertuples()}
        pred_by_id = {int(r.allele_id): r for r in pred.itertuples()}
        self._variants: dict[str, Variant] = {}
        for row in test.itertuples():
            aid = int(row.allele_id)
            v = Variant(key=str(aid), gene=row.gene, name=row.name)
            v.records.append(Record(
                record_id=f"CLINVAR:allele{aid}",
                source="CLINVAR_FROZEN",
                detail=f"ClinVar status at the 2024-01 freeze: {row.sig_then}",
                counts_for_gate=True,
            ))
            prow = pred_by_id.get(aid)
            if prow is not None:
                v.stratum = "summarised"
                v.records.insert(0, Record(
                    record_id=f"AM:{row.chrom}:{row.pos}:{row.ref}>{row.alt}",
                    source="AM",
                    detail=(f"AlphaMissense score={prow.am_score:.3f} "
                            f"class={am_class_by_id.get(aid, 'unknown')}"),
                    counts_for_gate=True,
                ))
                v.records.append(Record(
                    record_id=f"GENEPRIOR:{row.gene}:frozen2024",
                    source="GENEPRIOR",
                    detail=(f"Gene prior from frozen train labels for {row.gene}: "
                            f"{prow.gene_prior:.3f} (fraction of the gene's frozen "
                            f"train variants labelled pathogenic)"),
                    counts_for_gate=True,
                ))
                v.records.append(Record(
                    record_id=f"MODEL:ensemble:{aid}",
                    source="MODEL",
                    detail=(f"Calibrated probability of pathogenic from Build 1's "
                            f"ensemble (isotonic-calibrated): {prow.prob_ensemble:.3f}"),
                    counts_for_gate=False,
                ))
            else:
                v.stratum = "declined"
            self._variants[v.key] = v

    def get(self, key: str) -> Variant | None:
        return self._variants.get(key)

    def test_keys(self) -> list[str]:
        return list(self._variants)

    def summarised_keys(self) -> list[str]:
        return [k for k, v in self._variants.items() if v.stratum == "summarised"]

    def declined_keys(self) -> list[str]:
        return [k for k, v in self._variants.items() if v.stratum == "declined"]


def out_of_universe_variant(allele_id: int, gene: str, name: str) -> Variant:
    """A variant absent from Build 1's test set: no local records at all."""
    return Variant(key=f"OOU:{allele_id}", gene=gene, name=name,
                   stratum="out_of_universe", records=[])
