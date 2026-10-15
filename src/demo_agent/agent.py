"""The demo agent: a small LangGraph graph  plan -> (act -> plan)* -> end.

It is deliberately ordinary. Its only AgentGuard-specific parts are the
`span(...)` blocks, which is all an existing agent needs to be traced.

    plan:  ask the LLM what to do next (tool call or final answer)
    act:   run the requested tool and record the observation

The loop is capped (MAX_STEPS) so a confused model cannot spin forever.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Callable, TypedDict

from langgraph.graph import END, StateGraph

from agentguard.sdk import span

from .llm import make_llm
from .prompts import PROMPTS
from .tools import RETRIEVAL_TOOLS, TOOL_IMPLS, tool_schemas

MAX_STEPS = 6


@dataclass(frozen=True)
class AgentConfig:
    """Everything that defines one version of the agent."""

    name: str = "base"
    model: str = "base"  # base | base2 | cheap | slow
    prompt: str = "v1"  # key in PROMPTS
    tools: str = "v1"  # tool schema variant
    backend: str = "mock"  # mock | gemini | claude

    def version(self) -> str:
        return f"{self.name}[{self.model}/{self.prompt}/{self.tools}/{self.backend}]"


class State(TypedDict):
    question: str
    observations: list[dict]
    pending: dict | None
    answer: str | None
    steps: int


def build_agent(cfg: AgentConfig) -> Callable[[str], str]:
    """Return a function question -> answer. Build one per attempt (no shared state)."""
    system = PROMPTS[cfg.prompt]
    schemas = tool_schemas(cfg.tools)
    llm = make_llm(cfg.backend, cfg.model, cfg.prompt)

    def plan(state: State) -> dict[str, Any]:
        with span("llm", cfg.model, input={"question": state["question"], "observations": state["observations"]}) as s:
            reply = llm.plan(system=system, question=state["question"], tool_schemas=schemas, observations=state["observations"])
            s.set_usage(reply.tokens_in, reply.tokens_out, reply.cost_usd)
            s.set_output({"tool": reply.tool, "args": reply.args, "text": reply.text})
        steps = state["steps"] + 1
        if reply.tool:
            return {"pending": {"tool": reply.tool, "args": reply.args, "tool_use_id": reply.tool_use_id or uuid.uuid4().hex[:8]}, "steps": steps}
        return {"pending": None, "answer": reply.text, "steps": steps}

    def act(state: State) -> dict[str, Any]:
        call = state["pending"]
        assert call is not None
        kind = "retrieval" if call["tool"] in RETRIEVAL_TOOLS else "tool"
        with span(kind, call["tool"], input=call["args"]) as s:
            try:
                result = TOOL_IMPLS[call["tool"]](**call["args"])
            except Exception as exc:  # WHY: a bad call becomes an observation, the agent decides what to do
                s.set_error(f"{type(exc).__name__}: {exc}")
                result = {"_exception": str(exc)}
            s.set_output(result)
        obs = state["observations"] + [{"tool": call["tool"], "args": call["args"], "tool_use_id": call["tool_use_id"], "result": result}]
        return {"observations": obs, "pending": None}

    def route(state: State) -> str:
        if state["pending"] is None:
            return END
        if state["steps"] >= MAX_STEPS:
            return END
        return "act"

    g = StateGraph(State)
    g.add_node("plan", plan)
    g.add_node("act", act)
    g.set_entry_point("plan")
    g.add_conditional_edges("plan", route, {"act": "act", END: END})
    g.add_edge("act", "plan")
    graph = g.compile()

    def run(question: str) -> str:
        out = graph.invoke({"question": question, "observations": [], "pending": None, "answer": None, "steps": 0})
        return out["answer"] or "I couldn't finish that request."

    return run
