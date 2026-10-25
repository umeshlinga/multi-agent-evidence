"""Prompt text. The task block is shared verbatim by the single-agent
baseline and the multi-agent Synthesiser, so the only difference between
the two systems is architecture: one pass, versus draft -> critic ->
revision with guarantees enforced in code.
"""

TASK = """You are writing an evidence summary for one genetic variant.

Variant: {name} (gene {gene})

Evidence packet — every record has an id in square brackets:
{packet}

Rules:
1. Every factual claim must be a bullet line (starting with "- ") that ends
   with the citation [REC:<record_id>] of the record that supports it.
   One fact per bullet. No uncited claims, no claims in prose outside bullets.
2. Use only values that appear in the records. Never invent a number,
   a classification, or a study result.
3. Gate rule — summarise ONLY if the packet contains a MODEL record AND at
   least 3 local evidence records (sources AM, CLINVAR_FROZEN, GENEPRIOR).
   LIVE records are later context only and never count toward the gate.
   If the gate is not met, output exactly:
   VERDICT: DECLINE
   insufficient evidence — remains VUS
4. If the gate is met, output:
   VERDICT: SUMMARY
   followed by bullets covering each local evidence record and the model
   probability, each cited. Wording must not go beyond the records: a
   predictor score is not a clinical classification, and a frozen ClinVar
   status is a status at that freeze, not a current one.
Output only the verdict block, nothing else."""

CRITIC = """You are a strict evidence critic. Below is an evidence packet and a
draft summary written from it. Check the draft against the packet only.

Evidence packet:
{packet}

Draft:
{draft}

For each bullet in the draft, decide:
- "supported": the cited record exists in the packet and its text supports
  the claim as written, with no added strength or facts.
- "overstated": the cited record exists but the claim goes beyond it
  (e.g. treats a predictor score as a clinical classification, states a
  frozen status as current, or adds certainty the record does not have).
- "unsupported": the citation is missing, the cited record is not in the
  packet, or the record's text does not support the claim.
Also judge the verdict line: "verdict_ok" is false if the draft summarises
when the gate rule (a MODEL record AND at least 3 local records from
AM/CLINVAR_FROZEN/GENEPRIOR; LIVE records never count) is not met, or
declines when it is met.

Reply with JSON only, no prose:
{{"verdict_ok": true/false, "bullets": [{{"index": 1, "verdict": "supported|overstated|unsupported", "reason": "short reason"}}]}}"""

REVISION = """Your draft was reviewed by an evidence critic and must be revised.

Evidence packet:
{packet}

Your previous draft:
{draft}

Critic findings:
{findings}

Write the corrected full draft, following the original rules exactly:
every factual claim a bullet ending with [REC:<record_id>]; summarise only
if the gate is met (a MODEL record AND at least 3 local records from
AM/CLINVAR_FROZEN/GENEPRIOR; LIVE records never count), otherwise output
VERDICT: DECLINE and the line "insufficient evidence — remains VUS".
Remove or soften every claim the critic marked overstated or unsupported.
Output only the verdict block, nothing else."""
