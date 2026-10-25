"""Deterministic citation checker — no LLM involved.

Parses a system output into a verdict + bullet claims, then checks each
claim against the packet it was given:

  SUPPORTED    every cited record exists in the packet, and every numeric
               value stated in the claim appears (within its own rounding)
               in one of the cited records.
  UNSUPPORTED  no citation, a cited record that is not in the packet, a
               numeric value that appears in none of the cited records,
               or a direction word (pathogenic/benign) that contradicts
               the cited AlphaMissense class.
  UNVERIFIABLE no numeric values to check and no contradiction the rules
               above can decide — these go to the documented manual rubric
               (eval/results/manual_review.csv) and are reclassified there.

Claims marked SUPPORTED but containing intensifiers ("proves", "confirms",
"definitively", "establishes") are additionally flagged for the manual
rubric, which may reclassify them OVERSTATED.

The checker is deliberately strict: a claim that restates a probability
as a percentage, or rounds beyond the record's precision, fails the
numeric test here and its fate is decided in the open, in the manual
review, not by quietly loosening the checker.
"""
from __future__ import annotations

import re

from .retriever import Packet

DECLINE_LINE = "insufficient evidence — remains VUS"
_NUM = re.compile(r"(?<![A-Za-z])\d+(?:\.\d+)?(?![A-Za-z])")
_CITE = re.compile(r"\[REC:([^\]]+)\]")
_HGVS = re.compile(r"[cp]\.\S+")
_ACCESSION = re.compile(r"[A-Z]{1,4}_\d+(?:\.\d+)?")  # e.g. NM_005327.7 — an identifier, not a value
_INTENSIFIERS = ("proves", "proven", "confirms", "confirmed", "definitively",
                 "establishes", "established", "certainly", "conclusively")


def parse_output(text: str) -> tuple[str, list[str]]:
    """Returns (verdict, bullets). verdict: SUMMARY | DECLINE | UNPARSEABLE."""
    if not text:
        return "UNPARSEABLE", []
    verdict = "UNPARSEABLE"
    if re.search(r"VERDICT:\s*SUMMARY", text, re.I):
        verdict = "SUMMARY"
    elif re.search(r"VERDICT:\s*DECLINE", text, re.I) or DECLINE_LINE in text:
        verdict = "DECLINE"
    bullets = [ln.strip()[2:].strip() for ln in text.splitlines()
               if ln.strip().startswith("- ")]
    return verdict, bullets


def _numbers(s: str) -> list[tuple[str, float]]:
    s = _ACCESSION.sub("", _HGVS.sub("", s))
    return [(m.group(0), float(m.group(0))) for m in _NUM.finditer(s)]


def _num_matches(token: str, value: float, detail: str) -> bool:
    if token in detail:
        return True
    dec = len(token.split(".")[1]) if "." in token else 0
    tol = 0.5 * (10 ** -dec) + 1e-9
    return any(abs(value - dv) <= tol for _, dv in _numbers(detail))


def check_claim(packet: Packet, claim: str) -> dict:
    cited = _CITE.findall(claim)
    text = _CITE.sub("", claim).strip()
    by_id = {r.record_id: r for r in packet.records}
    base = {"claim": claim, "cited": cited}
    if not cited:
        return {**base, "status": "UNSUPPORTED", "reason": "no citation"}
    missing = [c for c in cited if c not in by_id]
    if missing:
        return {**base, "status": "UNSUPPORTED",
                "reason": f"cited record not in packet: {missing}"}
    details = " | ".join(by_id[c].detail for c in cited)
    # direction contradiction vs AlphaMissense class
    am = next((by_id[c] for c in cited if by_id[c].source == "AM"), None)
    low = text.lower()
    if am is not None:
        if "likely_pathogenic" in am.detail and re.search(r"\bbenign\b", low) \
                and "pathogenic" not in low.replace("benign", ""):
            return {**base, "status": "UNSUPPORTED",
                    "reason": "claims benign; cited AM class is likely_pathogenic"}
        if "likely_benign" in am.detail and "pathogenic" in low and "benign" not in low:
            return {**base, "status": "UNSUPPORTED",
                    "reason": "claims pathogenic; cited AM class is likely_benign"}
    nums = _numbers(text)
    if nums:
        bad = [tok for tok, val in nums if not _num_matches(tok, val, details)]
        if bad:
            return {**base, "status": "UNSUPPORTED",
                    "reason": f"value(s) {bad} not in cited record(s)"}
        status = {"status": "SUPPORTED", "reason": "citations exist; values match"}
    else:
        status = {"status": "UNVERIFIABLE", "reason": "no numeric value to verify"}
    if any(w in low for w in _INTENSIFIERS):
        status["flag_manual"] = "intensifier wording — check for overstatement"
    return {**base, **status}


def check_output(packet: Packet, text: str) -> dict:
    verdict, bullets = parse_output(text)
    claims = [check_claim(packet, b) for b in bullets] if verdict == "SUMMARY" else []
    key_records = [r.record_id for r in packet.records]
    cited = {c for cl in claims for c in cl["cited"]}
    completeness = (len(cited & set(key_records)) / len(key_records)
                    if verdict == "SUMMARY" and key_records else None)
    return {"verdict": verdict, "claims": claims, "completeness": completeness,
            "n_claims": len(claims)}
