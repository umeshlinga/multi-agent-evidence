#!/usr/bin/env bash
# Reproduce the evaluation end to end:
#   1. (re)build the fixed 36-variant evaluation set (seeded, deterministic)
#   2. run both systems over it (resumable — completed pairs are skipped;
#      delete eval/results/runs.jsonl to force a full re-run)
#   3. run the four coordination failure-mode exercises
# Requires: Build 1 (vus-evidence-agent) checked out alongside this
# project, network access to NCBI E-utilities, and the custom.openai
# connector helper for model calls.
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt
.venv/bin/python eval/select_variants.py
.venv/bin/python eval/run_eval.py
.venv/bin/python eval/failure_modes.py
echo "Done. Aggregates: eval/results/metrics.json — full record: RESULTS.md"
