**Live results:** https://omevra.github.io/
# multi-agent-evidence

**A multi-agent system for genetic-variant evidence work — measured
against the single-agent baseline it has to beat.**

> Not for clinical use. Research project only.

## What this is

Build 1 (vus-evidence-agent) showed that a single evidence agent can be
kept honest with a hard rule — *cite, or decline* — enforced in code.
This project asks the follow-up question: does splitting the work
across cooperating agents actually produce better evidence summaries
than one model writing in one pass?

Three agents, one guarantee layer:

- **Retriever** (deterministic, no model) — gathers the records for a
  variant from Build 1's local evidence universe (AlphaMissense, the
  ClinVar record frozen at the evaluation cutoff, the gene prior, and
  the calibrated model probability). For variants outside that universe
  it goes live, to ClinVar and PubMed, and marks what it brings back as
  live context. It assembles the *evidence packet*.
- **Synthesiser** (model) — drafts the evidence summary from the packet,
  one cited claim per bullet, or declines when the packet cannot meet
  the gate: a calibrated probability plus at least three local evidence
  records.
- **Critic** (model) — checks every drafted claim against the packet:
  does the cited record exist, and does its text support the claim as
  written, without added strength? Rejected drafts go back with the
  findings attached; the Synthesiser revises, at most twice.

Around them, a deterministic **finalise** step enforces in code what a
prompt can only request: if the gate is not met, the output is the
decline whatever the draft said, and any claim citing a record that is
not in the packet is removed. Orchestration is a LangGraph state graph:
retrieve → draft → critique → (revise → critique) → finalise.

## The evaluation

Architecture claims are cheap; this repo's point is the measurement.
`RESULTS.md` reports a head-to-head over a fixed set of 36 variants —
12 Build 1 summarises, 12 it declines, 12 that sit outside its universe
entirely. The baseline is the same model, the same packet, the same task
text, in a single pass, with no critic and no code guard. Both systems
are scored by a deterministic checker (does every stated value appear
in the record it cites?) plus a documented manual rubric for the claims
a checker cannot decide, on:

- **citation accuracy** — claims whose citations actually support them;
- **evidence completeness** — how much of the packet the summary uses;
- **decline correctness** — declining exactly when Build 1's gate does;
- **cost and latency** — tokens (counted from the API's own usage
  reports) and wall time per variant.

It also logs the coordination failure modes, exercised rather than
described: conflicting frozen-vs-live records, a critic rejecting a
sabotaged draft, stale and duplicated evidence in one packet, and a
forced failure of the live tools mid-run. Where the multi-agent system
does not beat the baseline, that is the published result.

## Layout

```
src/universe.py    Build 1's evidence records, rebuilt from its data
src/retriever.py   the Retriever: local lookup, live fallback, packet
src/live.py        NCBI E-utilities access (ClinVar, PubMed)
src/prompts.py     the shared task text, critic and revision prompts
src/graph.py       the LangGraph multi-agent system
src/baseline.py    the single-agent baseline
src/checker.py     the deterministic citation checker
src/llm.py         model access, only via the local connector helper
eval/              evaluation set, runner, failure-mode exercises
run_eval.sh        reproduces the evaluation end to end
```

## Running it

```bash
./run_eval.sh
```

Model calls go exclusively through the local OpenAI connector helper
(`gpt-4.1-mini`); retrieval and checking are local and deterministic.
The science the agents argue over is Build 1's — frozen records, a
calibrated probability, and an explicit allowed answer:
*"insufficient evidence — remains VUS."*
