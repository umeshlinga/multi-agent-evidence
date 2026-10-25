"""The Retriever agent — deterministic, no LLM.

Builds the evidence packet for one variant:

  1. Local lookup in Build 1's universe (frozen prediction-time records).
  2. If the variant is outside the local universe, live retrieval from
     ClinVar and PubMed (marked LIVE; never counts toward the gate).

The packet is built once per variant and handed, identical, to both the
multi-agent system and the single-agent baseline — that is what makes
the comparison a comparison of architecture, not of inputs.

Fault-injection hooks (used only by the failure-mode exercises):
  force_live_failure=True  -> the live tools raise, as in an outage;
  extra_records=[...]      -> records appended to the packet (labelled
                              injections in the exercise log).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import live
from .universe import Record, Variant


@dataclass
class Packet:
    variant: Variant
    records: list[Record]
    events: list[str] = field(default_factory=list)
    live_errors: list[str] = field(default_factory=list)

    def render(self) -> str:
        if not self.records:
            return "(no records retrieved)"
        return "\n".join(r.render() for r in self.records)

    def record_ids(self) -> list[str]:
        return [r.record_id for r in self.records]


def _variant_token(name: str) -> str:
    m = re.search(r":(c\.\S+?)(?:\s|$)", name)
    return m.group(1) if m else name


def build_packet(variant: Variant, *, force_live_failure: bool = False,
                 extra_records: list[Record] | None = None) -> Packet:
    packet = Packet(variant=variant, records=list(variant.records))
    packet.events.append(
        f"local lookup: {len(variant.records)} record(s) in Build 1 universe")
    if not variant.records:
        # Outside the local universe -> live retrieval, as in Build 1's app.
        if force_live_failure:
            packet.live_errors.append("ClinVar live: RuntimeError: simulated tool outage (forced)")
            packet.live_errors.append("PubMed live: RuntimeError: simulated tool outage (forced)")
            packet.events.append("live retrieval FAILED (forced outage) — proceeding with no records")
        else:
            detail, err = live.clinvar_live(variant.name, variant.gene)
            if err:
                packet.live_errors.append(f"ClinVar live: {err}")
                packet.events.append("live ClinVar retrieval errored — logged, continuing")
            elif detail:
                packet.records.append(Record(
                    record_id=f"CLINVAR_LIVE:{variant.key}", source="CLINVAR_LIVE",
                    detail=detail, counts_for_gate=False))
                packet.events.append("live ClinVar record retrieved")
            else:
                packet.events.append("live ClinVar: no record found")
            detail, err = live.pubmed_live(variant.gene, _variant_token(variant.name))
            if err:
                packet.live_errors.append(f"PubMed live: {err}")
                packet.events.append("live PubMed retrieval errored — logged, continuing")
            elif detail:
                packet.records.append(Record(
                    record_id=f"PUBMED_LIVE:{variant.key}", source="PUBMED_LIVE",
                    detail=detail, counts_for_gate=False))
                packet.events.append("live PubMed record retrieved")
    if extra_records:
        packet.records.extend(extra_records)
        packet.events.append(f"{len(extra_records)} injected record(s) appended (failure-mode exercise)")
    return packet
