"""LLM access — ONLY through the custom.openai connector helper.

Every model call is a subprocess invocation of
~/workspace/custom-connectors/custom.openai/bin/openai_call.py
(`chat gpt-4.1-mini <prompt> <max_tokens>`), which returns the model's
reply plus the API's own usage object. No API key is read here and no
other route to the model exists in this project.

The helper goes through a proxy that occasionally stalls, so calls are
retried up to 3 times with backoff. A call that still fails raises
LLMError; callers must log it, never silently swallow it.

Note: the helper's interface carries a single user message and a token
cap only — it does not expose temperature or a system role. All runs
therefore use the API defaults; this is recorded in RESULTS.md.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time

HELPER = "/home/hatch/workspace/custom-connectors/custom.openai/bin/openai_call.py"
MODEL = "gpt-4.1-mini"


class LLMError(RuntimeError):
    pass


class LLM:
    def __init__(self) -> None:
        self.calls: list[dict] = []  # one entry per successful API call

    def chat(self, prompt: str, max_tokens: int = 700, label: str = "") -> str:
        last_err = ""
        for attempt in range(3):
            try:
                proc = subprocess.run(
                    [sys.executable, HELPER, "chat", MODEL, prompt, str(max_tokens)],
                    capture_output=True, text=True, timeout=120,
                )
                if proc.returncode != 0:
                    raise LLMError(f"helper exit {proc.returncode}: {proc.stderr[-300:]}")
                out = json.loads(proc.stdout)
                content = out.get("content")
                if content is None:
                    raise LLMError(f"no content in response: {str(out)[:300]}")
                usage = out.get("usage") or {}
                self.calls.append({
                    "label": label,
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                })
                return content
            except (LLMError, subprocess.TimeoutExpired, json.JSONDecodeError) as e:
                last_err = str(e)
                if attempt < 2:
                    time.sleep(2 * (attempt + 1) ** 2)
        raise LLMError(f"LLM call failed after 3 attempts ({label}): {last_err}")

    def totals(self) -> dict:
        return {
            "calls": len(self.calls),
            "prompt_tokens": sum(c["prompt_tokens"] for c in self.calls),
            "completion_tokens": sum(c["completion_tokens"] for c in self.calls),
            "total_tokens": sum(c["total_tokens"] for c in self.calls),
        }
