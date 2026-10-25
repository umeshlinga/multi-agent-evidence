# Results — multi-agent evidence framework vs single-agent baseline

> Not for clinical use. Research project only.
> Raw record of everything reported here: `eval/results/` (runs.jsonl,
> metrics.json, manual_review.csv, final_metrics.json, failure_modes.jsonl).

## What was built

A three-agent system for genetic-variant evidence work, orchestrated as
a LangGraph state graph, deepening Build 1's evidence agent:

- **Retriever** (deterministic) builds an *evidence packet* per variant
  from Build 1's local universe — AlphaMissense, the ClinVar record
  frozen at the 2024-01 cutoff, the gene prior, and the calibrated
  model probability. Variants outside that universe trigger live
  retrieval from ClinVar and PubMed (NCBI E-utilities); live records are
  marked as later context and never count toward the gate.
- **Synthesiser** (gpt-4.1-mini) drafts the summary: one cited claim
  per bullet, or a decline when the gate — a calibrated probability
  plus at least three local evidence records — is not met.
- **Critic** (gpt-4.1-mini) checks every drafted claim against the
  packet and returns per-claim verdicts as JSON. Rejected drafts loop
  back with the findings attached (at most 2 revisions).
- **Finalise** (deterministic, no model) enforces Build 1's guarantees
  in code: gate not met → the output is the decline, whatever the draft
  said; claims citing records outside the packet are removed.

The baseline is the **same model, same packet, same task text, one
pass** — no critic, no revision, no code guard. Model access is only
through the local connector helper; the helper's interface does not
expose temperature, so all calls ran at API defaults (a limitation,
recorded below).

## Evaluation design

Fixed set of **36 variants** (seeded selection, `eval/eval_set.csv`):
12 that Build 1's gate summarises (sampled across the calibrated-
probability range), 12 it declines, 12 real ClinVar variants outside
Build 1's universe entirely. The packet for each variant was built once
and given, identical, to both systems.

Scoring: a deterministic checker (every stated value must appear in the
record it cites; citations must exist in the packet; direction words
must not contradict the cited predictor class), plus a manual rubric
audit of **all 96 claims** against their cited records
(`eval/results/manual_review.csv`). Completeness is the fraction of
packet records cited, scored on summaries. Decline correctness is
agreement with Build 1's gate on all 36.

## Headline comparison

| Measure | Single-agent baseline | Multi-agent system |
|---|---|---|
| Citation accuracy (final, after manual audit) | **48/48 = 1.00** | **48/48 = 1.00** |
| Citation accuracy (deterministic checker only) | 48/48 = 1.00 | 46/48 = 0.96 |
| Evidence completeness (mean, summaries) | 1.00 | 1.00 |
| Decline correctness (vs Build 1 gate) | 36/36 | 36/36 |
| LLM calls | 36 | 94 |
| Tokens (prompt + completion) | 14,710 + 2,352 = 17,062 | 39,597 + 6,628 = 46,225 |
| Mean latency per variant | 1.40 s | 3.74 s |
| Estimated cost for the 36 variants | $0.0096 | $0.0264 |

**The honest headline: on this evaluation the multi-agent system did
not beat the baseline on any quality axis.** Citation accuracy,
completeness, and decline correctness are identical — both systems sit
at the ceiling of what this task, as specified, can measure. The
multi-agent system cost **2.7× the tokens and 2.7× the latency** to get
there. That is the result, and it stands.

Two qualifications, both documented rather than buried:

1. The checker's 46/48 for the multi-agent system is two claims that
   restated a gene prior as a percentage (0.485 → "48.5%", 0.542 →
   "54.2%"). The strict checker fails any value not literally in the
   record; the manual audit rules a fraction and its percentage the
   same quantity and reclassifies both SUPPORTED. The baseline never
   used the percentage form. Reported both ways above.
2. The task is deliberately well-specified — a small structured packet,
   an explicit gate rule in the shared task text. A single strong pass
   is already reliable in that regime. This evaluation does **not**
   show coordination is useless; it shows where its value does and
   does not appear at this scale (next section).

## What the coordination actually did

The critic worked — it just had nothing left to fix in the final
outputs. Across 36 variants it ran **47 rounds and rejected drafts 16
times**:

- **13 of 16 rejections were on out-of-universe variants.** There, the
  packet holds a live ClinVar record with a definite current
  significance, and the Synthesiser repeatedly drafted as if that live
  record could carry a summary — or asserted "remains VUS" as a
  record-backed claim, which the packet does not support either. The
  critic caught the gate violation every time; on five variants the
  argument ran the full revision budget (3 critic rounds), after which
  the deterministic finalise step issued the correct decline anyway.
  Coordination lesson, stated plainly: persuasion between agents was
  the expensive path; the code guarantee was the reliable one.
- **3 rejections were one summarised variant (ASNS)** where the critic
  kept rejecting the phrase "likely pathogenic" for the AlphaMissense
  class — stricter than the record, which literally carries
  `class=likely_pathogenic`. A critic false-positive: two extra rounds
  spent, outcome unchanged.

The critic's rejections never changed a final verdict in this run —
finalise enforces the gate regardless — but the failure-mode exercises
below show the one case where the loop, not the guard, did the work:
a sabotaged draft whose false claim had a *valid-looking* citation,
which the code guard alone cannot detect.

## Failure-mode log (exercised, not described)

| # | Exercise | Outcome |
|---|---|---|
| FM1 | **Conflicting records** — CPS1 packet given its frozen record ("Uncertain significance", 2024-01) and a live ClinVar record ("Likely benign", evaluated 2024-06) | **No confusion, but no surfacing either.** Zero cross-citation violations — no claim mixed the two statuses up. But the final summary never cited the live record at all: the conflict passed silently. The architecture has no step whose job is to *raise* a disagreement; the critic only reviews claims that exist. Recorded as a design gap. |
| FM2 | **Critic rejection loop** — Synthesiser sabotaged (exercise-only instruction) into adding an ACMG PS3 claim citing the AlphaMissense record | **Handled by the loop.** Critic rejected round 1 (unsupported), the revision removed the claim, round 2 accepted. PS3 absent from the final output. This is the failure class the code guard cannot catch — the citation was real, the claim was not — and the critic earned its cost here. |
| FM3 | **Stale + duplicate evidence** — frozen ClinVar record duplicated (same id twice) plus a superseded 2019 record ("Likely benign") in one packet | **Handled.** The final summary claimed the variant's status exactly once, citing the 2024-01 record; the stale record was never cited. Duplication cannot flip the gate: it also requires a MODEL record, which duplicates do not create. |
| FM4 | **Forced tool failure** — live ClinVar and PubMed forced to raise for an out-of-universe variant | **Handled.** The run completed, declined, and the outage is visible in the run's event log and the packet's error list. No exception escaped, no record was fabricated to fill the gap. |

Full exercise records: `eval/results/failure_modes.jsonl`
(10 model calls, 6,583 tokens).

## Token accounting

All counts are the API's own usage figures, summed per run — not
estimates. Prices are gpt-4.1-mini list prices ($0.40 / $1.60 per 1M
input / output tokens) and are labelled estimates wherever used.

- Evaluation (36 variants × 2 systems): **63,287 tokens** (54,307 in,
  8,980 out) ≈ **$0.036**
- Failure-mode exercises: **6,583 tokens** ≈ **$0.004**
- Development smoke tests and probes during the build: ≈ 7,400 tokens
- **Whole build: ≈ 77,000 tokens, ≈ $0.045 of API credit.**

## Bugs found by this build, fixed, and disclosed

1. **ClinVar live parser read the wrong field.** The first live
   implementation read `clinical_significance` from ClinVar's esummary
   response; the current API carries the classification in
   `germline_classification`, so live records arrived with significance
   "not stated". Found when a tour of the numbers looked empty —
   before any results were published. Fixed in `src/live.py`; the 12
   out-of-universe variants were then **re-run** with corrected packets
   (the 24 in-universe pairs never touch live retrieval and stand as
   first run). This disclosure is why the critic-rejection counts
   concentrate on out-of-universe variants: with real live
   significances in the packets, there was finally something to argue
   about.
2. **Checker false positive on transcript accessions.** The checker's
   numeric extraction initially treated the digits of an accession like
   NM_005327.7 as a stated value. Fixed by stripping accessions and
   HGVS tokens before extraction; verified against the smoke set.

## Limitations

- **One run per variant per system.** No variance estimate; a different
  sampling of the model could move individual claims. The comparison
  is of these runs, not of distributions.
- **Temperature is not controllable** through the connector helper's
  interface; runs used API defaults. Prompts, packets, and the eval set
  are fixed and shipped, which bounds — but does not eliminate — this.
- **Ceiling regime.** Packets hold 1–4 short records and the gate rule
  is stated in the task text. The interesting differences between the
  architectures appeared in process (rejections, sabotage, conflicts),
  not in final-output quality. A harder regime — larger, messier
  packets, conflicting sources as the norm — is where a difference
  would be expected to show, and is the obvious next evaluation.
- **Live data moves.** Out-of-universe packets were retrieved from
  ClinVar/PubMed at run time; re-running later may fetch updated
  records. The frozen-universe results are exactly reproducible; the
  live ones are reproducible in method, not to the byte.
- **The manual audit is one reader** (the builder), applying the rubric
  written in `eval/make_manual_review.py`. Its two reclassifications
  are individually documented in `manual_review.csv`.

## Reproduce

```bash
./run_eval.sh
```

Rebuilds the eval set (seeded — identical), runs both systems
(resumable), runs the failure-mode exercises, and regenerates
`eval/results/metrics.json`. RESULTS.md's final numbers come from
`eval/final_metrics.py` merging the checker output with the manual
audit.
