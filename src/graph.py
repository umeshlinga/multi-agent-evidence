"""The multi-agent system, orchestrated with LangGraph.

Nodes:
  retriever    — takes the evidence packet built by the Retriever
                 component (src/retriever.py) and snapshots the gate
                 decision deterministically, in code.
  synthesiser  — LLM: drafts the summary from the packet (or declines).
  critic       — LLM: checks every drafted claim against the packet and
                 the gate rule; returns per-claim verdicts as JSON.
  revise       — LLM: rewrites the draft under the critic's findings
                 (at most MAX_REVISIONS rounds).
  finalise     — deterministic, no LLM: Build 1's guarantees enforced in
                 code. If the gate is not met the output is the decline,
                 whatever the draft said. Claims citing records that are
                 not in the packet are removed. This mirrors Build 1's
                 design rule: enforced in code, not just in a prompt.

Coordination accounting is kept in the run log: every critic rejection,
revision round, dropped claim, and gate override is an event.
"""
from __future__ import annotations

import json
import re
import time
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from . import prompts
from .checker import DECLINE_LINE
from .llm import LLM
from .retriever import Packet

MAX_REVISIONS = 2


class State(TypedDict, total=False):
    packet: Packet
    llm: LLM
    extra_instruction: str        # failure-mode exercises only
    gate_ok: bool
    draft: str
    findings: dict
    rounds: int                   # critic rounds so far
    rejections: int               # critic rounds that found problems
    problems: list                # problems found in the latest round
    final: str
    events: list[str]


def _node_retriever(state: State) -> State:
    packet = state["packet"]
    gate_ok = packet.variant.gate_summarises
    events = list(state.get("events", []))
    events.append(
        f"retriever: packet has {len(packet.records)} record(s); "
        f"gate (deterministic) = {'SUMMARISE' if gate_ok else 'DECLINE'}")
    for e in packet.events:
        events.append(f"retriever: {e}")
    for e in packet.live_errors:
        events.append(f"retriever: live error logged: {e}")
    return {"gate_ok": gate_ok, "events": events, "rounds": 0, "rejections": 0}


def _node_synthesiser(state: State) -> State:
    packet = state["packet"]
    prompt = prompts.TASK.format(name=packet.variant.name, gene=packet.variant.gene,
                                 packet=packet.render())
    if state.get("extra_instruction"):
        prompt += "\n\nAdditional instruction for this run: " + state["extra_instruction"]
    draft = state["llm"].chat(prompt, max_tokens=700, label="synthesiser")
    events = list(state.get("events", []))
    events.append("synthesiser: draft written")
    return {"draft": draft, "events": events}


def _parse_critic(raw: str) -> dict | None:
    m = re.search(r"\{.*\}", raw, re.S)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def _node_critic(state: State) -> State:
    packet = state["packet"]
    raw = state["llm"].chat(
        prompts.CRITIC.format(packet=packet.render(), draft=state["draft"]),
        max_tokens=600, label="critic")
    findings = _parse_critic(raw)
    events = list(state.get("events", []))
    rounds = state.get("rounds", 0) + 1
    rejections = state.get("rejections", 0)
    if findings is None:
        events.append("critic: UNPARSEABLE reply — round counted as a critic "
                      "failure; draft passes to finalise unreviewed (logged, not hidden)")
        return {"findings": {}, "problems": [], "rounds": rounds, "events": events}
    problems = [b for b in findings.get("bullets", [])
                if b.get("verdict") in ("unsupported", "overstated")]
    if not findings.get("verdict_ok", True):
        problems.append({"index": 0, "verdict": "unsupported",
                         "reason": "verdict line violates the gate rule"})
    if problems:
        rejections += 1
        events.append(f"critic: round {rounds} REJECTED draft — "
                      f"{len(problems)} problem(s): "
                      + "; ".join(f"bullet {p.get('index')}: {p.get('reason', '')}" for p in problems))
    else:
        events.append(f"critic: round {rounds} accepted draft")
    return {"findings": findings, "problems": problems, "rounds": rounds,
            "rejections": rejections, "events": events}


def _node_revise(state: State) -> State:
    packet = state["packet"]
    findings_text = "\n".join(
        f"- bullet {p.get('index')}: {p.get('verdict')} — {p.get('reason', '')}"
        for p in state.get("problems", []))
    draft = state["llm"].chat(
        prompts.REVISION.format(packet=packet.render(), draft=state["draft"],
                                findings=findings_text),
        max_tokens=700, label="revise")
    events = list(state.get("events", []))
    events.append("synthesiser: revised draft under critic findings")
    return {"draft": draft, "events": events}


def _node_finalise(state: State) -> State:
    packet = state["packet"]
    events = list(state.get("events", []))
    if not state["gate_ok"]:
        if "VERDICT: SUMMARY" in (state.get("draft") or ""):
            events.append("finalise: gate not met — code overrode a SUMMARY draft "
                          "with the decline (guarantee enforced in code)")
        final = f"VERDICT: DECLINE\n{DECLINE_LINE}"
        return {"final": final, "events": events}
    valid_ids = set(packet.record_ids())
    kept, dropped = [], 0
    for line in (state.get("draft") or "").splitlines():
        line = line.strip()
        if not line.startswith("- "):
            continue
        cited = re.findall(r"\[REC:([^\]]+)\]", line)
        if cited and all(c in valid_ids for c in cited):
            kept.append(line)
        elif not cited:
            dropped += 1
            events.append("finalise: dropped an uncited claim (code guard)")
        else:
            dropped += 1
            events.append(f"finalise: dropped a claim citing record(s) not in packet: {cited}")
    if not kept:
        events.append("finalise: no claim survived the guard — declining")
        return {"final": f"VERDICT: DECLINE\n{DECLINE_LINE}", "events": events}
    if dropped:
        events.append(f"finalise: {dropped} claim(s) dropped by the code guard")
    return {"final": "VERDICT: SUMMARY\n" + "\n".join(kept), "events": events}


def _route_after_critic(state: State) -> str:
    if state.get("problems") and state.get("rounds", 0) <= MAX_REVISIONS:
        return "revise"
    return "finalise"


def build_graph():
    g = StateGraph(State)
    g.add_node("retriever", _node_retriever)
    g.add_node("synthesiser", _node_synthesiser)
    g.add_node("critic", _node_critic)
    g.add_node("revise", _node_revise)
    g.add_node("finalise", _node_finalise)
    g.add_edge(START, "retriever")
    g.add_edge("retriever", "synthesiser")
    g.add_edge("synthesiser", "critic")
    g.add_conditional_edges("critic", _route_after_critic,
                            {"revise": "revise", "finalise": "finalise"})
    g.add_edge("revise", "critic")
    g.add_edge("finalise", END)
    return g.compile()


_GRAPH = build_graph()


def run(packet: Packet, llm: LLM, extra_instruction: str = "") -> dict:
    """Run the multi-agent system on one packet. Returns output + accounting."""
    started = time.time()
    state = _GRAPH.invoke({"packet": packet, "llm": llm,
                           "extra_instruction": extra_instruction, "events": []})
    return {
        "text": state["final"],
        "seconds": round(time.time() - started, 2),
        "critic_rounds": state.get("rounds", 0),
        "rejections": state.get("rejections", 0),
        "events": state.get("events", []),
        "usage": llm.totals(),
    }
