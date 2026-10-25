"""The single-agent baseline: one prompt, one pass, no critic, no guard.

It receives the identical packet and the identical task text as the
multi-agent Synthesiser. Whatever it emits — including any claim citing
a record that does not exist — is its final output. That asymmetry is
the thing being measured: it is what "no coordination, no code-enforced
guarantee" costs, stated in numbers.
"""
from __future__ import annotations

import time

from . import prompts
from .llm import LLM
from .retriever import Packet


def run(packet: Packet, llm: LLM) -> dict:
    started = time.time()
    text = llm.chat(
        prompts.TASK.format(name=packet.variant.name, gene=packet.variant.gene,
                            packet=packet.render()),
        max_tokens=700, label="baseline")
    return {"text": text, "seconds": round(time.time() - started, 2),
            "usage": llm.totals()}
