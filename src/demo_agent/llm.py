"""LLM backends for the demo agent: an offline mock and Claude.

WHY a mock: AgentGuard must be runnable and testable without an API key or
spend, and the seeded-regression experiment needs *controlled* behaviour changes.

HONESTY NOTE: results produced with MockLLM show that the evaluation machinery
works (it detects the behaviour changes the mock simulates). They say nothing
about how a real model behaves. Real-model numbers come from `--llm claude`.

Both backends return the same `LLMReply`:
  * a tool call (tool + args), or
  * a final text answer.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field

from agentguard.sdk import get_context

from .data import money
from .prompts import PROMPTS

# Illustrative prices in USD per million tokens (input, output).
# For the Claude backend, verify these against current published pricing.
PRICES = {
    "base": (1.0, 5.0),
    "base2": (0.8, 4.0),  # same behaviour as base, slightly cheaper
    "cheap": (0.25, 1.25),
    "slow": (1.0, 5.0),
}
# Simulated seconds per LLM call (mock only).
LATENCY_S = {"base": 0.04, "base2": 0.04, "cheap": 0.02, "slow": 0.20}
CLAUDE_MODELS = {"base": "claude-sonnet-5-5", "base2": "claude-sonnet-5-5", "cheap": "claude-haiku-5-5", "slow": "claude-sonnet-5-5"}


@dataclass
class LLMReply:
    tool: str | None = None
    args: dict = field(default_factory=dict)
    text: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    tool_use_id: str | None = None


def _cost(model: str, tin: int, tout: int) -> float:
    pin, pout = PRICES[model]
    return (tin * pin + tout * pout) / 1_000_000


# --------------------------------------------------------------------------- mock

_ORDER_RE = re.compile(r"ord-?\s?(\d+)", re.I)
_CATEGORIES = ["electronics", "clothing", "grocery", "books", "furniture"]


def _extract_order(question: str) -> str | None:
    m = _ORDER_RE.search(question)
    return f"ORD-{m.group(1)}" if m else None


def _extract_category(q: str) -> str | None:
    return next((c for c in _CATEGORIES if c in q), None)


def _intent(q: str, oid: str | None) -> str:
    if oid and "refund" in q:
        return "refund"
    if oid and any(w in q for w in ("where", "track", "status")):
        return "track"
    if oid and any(w in q for w in ("items", "total", "bought", "contain")):
        return "details"
    if _extract_category(q) and ("return" in q or "policy" in q):
        return "policy"
    return "out_of_scope"


def _noise(question: str, repeat: int, model: str) -> float:
    """Deterministic pseudo-random number in [0,1) per (question, repeat, model).

    WHY: the 'cheap' model needs run-to-run variation (to exercise the 3-repeat
    logic) yet runs must stay reproducible (N1).
    """
    h = hashlib.sha256(f"{question}|{repeat}|{model}".encode()).hexdigest()[:8]
    return int(h, 16) / 0xFFFFFFFF


class MockLLM:
    """Rule-based stand-in for a model. Behaviour depends on (model, prompt)."""

    def __init__(self, model: str, prompt: str) -> None:
        self.model, self.prompt = model, prompt

    def plan(self, *, system: str, question: str, tool_schemas: list[dict], observations: list[dict]) -> LLMReply:
        time.sleep(LATENCY_S[self.model])
        q = question.lower()
        ctx = get_context()
        repeat = ctx.repeat if ctx else 0
        oid = _extract_order(question)
        category = _extract_category(q)
        intent = _intent(q, oid)
        schemas = {s["name"]: s for s in tool_schemas}

        # cheap model: sometimes mis-reads the order number or category
        if self.model == "cheap" and _noise(question, repeat, self.model) < 0.30:
            if oid:
                oid = f"ORD-{int(oid[4:]) + 1}"
            if category:
                category = _CATEGORIES[(_CATEGORIES.index(category) + 1) % len(_CATEGORIES)]
        if self.prompt == "truncate_id" and oid:
            oid = oid.split("-")[1]  # pass only the digits

        def call(name: str, value: str) -> LLMReply:
            if name not in schemas:
                return self._final("I'm unable to look that up right now.", system, question, observations)
            arg = next(iter(schemas[name]["input_schema"]["properties"]))  # follow the schema
            return self._tool(name, {arg: value}, system, question, observations)

        n = len(observations)
        last = observations[-1]["result"] if observations else None
        if last is not None and isinstance(last, dict) and last.get("_exception"):
            return self._final("Sorry, something went wrong while looking that up.", system, question, observations)

        if intent == "out_of_scope":
            if self.prompt == "overeager" and n == 0:
                return call("lookup_order", "ORD-0000")
            if self.prompt == "no_refusal":
                return self._final("It's sunny and about 24 degrees today. Anything else?", system, question, observations)
            return self._final("I can only help with orders, shipping and returns.", system, question, observations)

        if intent in ("track", "details"):
            if n == 0:
                return call("track_shipment" if intent == "track" else "lookup_order", oid or "")
            return self._final(self._answer_order(intent, last, oid), system, question, observations)

        if intent == "policy":
            if n == 0:
                return call("check_refund_policy", category or "")
            return self._final(self._answer_policy(last), system, question, observations)

        # refund: calc_refund, then check_refund_policy (unless the prompt skips it)
        if n == 0:
            return call("calc_refund", oid or "")
        if n == 1 and self.prompt != "terse" and not last.get("error"):
            return call("check_refund_policy", last["category"])
        return self._final(self._answer_refund(observations), system, question, observations)

    # -- answer templates (facts here must match tool outputs) ------------------
    def _wrap(self, text: str) -> str:
        if self.prompt == "polite":
            return f"Happy to help! {text} Is there anything else I can do for you?"
        return text

    def _answer_order(self, intent: str, r: dict, oid: str | None) -> str:
        if r.get("error"):
            return self._wrap(f"I couldn't find order {r.get('order_id')}. Please check the order number.")
        if intent == "track":
            if r["status"] == "processing":
                return self._wrap(f"Order {r['order_id']} is processing and has not shipped yet.")
            if r["status"] == "shipped":
                return self._wrap(f"Order {r['order_id']} has shipped with {r['carrier']} and should arrive by {r['eta']}.")
            return self._wrap(f"Order {r['order_id']} was delivered by {r['carrier']} {r['delivered_days_ago']} days ago.")
        items = ", ".join(r["items"])
        return self._wrap(f"Order {r['order_id']} contains {items}. The total is {money(r['total'])}.")

    def _answer_policy(self, r: dict) -> str:
        if r.get("error"):
            return self._wrap("I couldn't find a policy for that category.")
        return self._wrap(_policy_sentence(r))

    def _answer_refund(self, obs: list[dict]) -> str:
        r = obs[0]["result"]
        if r.get("error"):
            return self._wrap(f"I couldn't find order {r.get('order_id')}. Please check the order number.")
        if r["eligible"]:
            text = f"You would receive a refund of {r['refund_text']} for order {r['order_id']}."
        else:
            text = f"Order {r['order_id']} is outside the return window, so the refund is {r['refund_text']}."
        if len(obs) > 1 and not obs[1]["result"].get("error"):
            text += " " + _policy_sentence(obs[1]["result"])
        return self._wrap(text)

    # -- reply builders with token/cost accounting ------------------------------
    def _tokens(self, system: str, question: str, observations: list[dict], out: str) -> tuple[int, int]:
        tin = (len(system) + len(question) + len(json.dumps(observations, default=str))) // 4 + 20
        return tin, len(out) // 4 + 5

    def _tool(self, name: str, args: dict, system: str, question: str, observations: list[dict]) -> LLMReply:
        tin, tout = self._tokens(system, question, observations, json.dumps(args))
        return LLMReply(tool=name, args=args, tokens_in=tin, tokens_out=tout, cost_usd=_cost(self.model, tin, tout))

    def _final(self, text: str, system: str, question: str, observations: list[dict]) -> LLMReply:
        text = self._wrap(text) if self.prompt == "polite" and not text.startswith("Happy") else text
        tin, tout = self._tokens(system, question, observations, text)
        return LLMReply(text=text, tokens_in=tin, tokens_out=tout, cost_usd=_cost(self.model, tin, tout))


def _policy_sentence(r: dict) -> str:
    cat = r["category"].capitalize()
    if r["return_days"] == 0:
        return f"{cat} items are non-returnable."
    fee = f" A {int(r['restocking_fee'] * 100)}% restocking fee applies." if r["restocking_fee"] else ""
    return f"{cat} items can be returned within {r['return_days']} days of delivery.{fee}"


# ------------------------------------------------------------------------- claude

class ClaudeLLM:
    """Real model via the Anthropic API (needs ANTHROPIC_API_KEY).

    NOT exercised by the offline tests. Run it yourself with `--llm claude`.
    Prompt variants change the actual system prompt text, so seeded prompt
    regressions are real here.
    """

    def __init__(self, model: str, prompt: str) -> None:
        import anthropic  # imported lazily so the offline path never needs a key

        self.client = anthropic.Anthropic()
        self.model, self.prompt = model, prompt

    def plan(self, *, system: str, question: str, tool_schemas: list[dict], observations: list[dict]) -> LLMReply:
        messages: list[dict] = [{"role": "user", "content": question}]
        for ob in observations:
            messages.append({"role": "assistant", "content": [{"type": "tool_use", "id": ob["tool_use_id"], "name": ob["tool"], "input": ob["args"]}]})
            messages.append({"role": "user", "content": [{"type": "tool_result", "tool_use_id": ob["tool_use_id"], "content": json.dumps(ob["result"], default=str)}]})
        resp = self.client.messages.create(
            model=CLAUDE_MODELS[self.model], max_tokens=512, system=system, tools=tool_schemas, messages=messages
        )
        tin, tout = resp.usage.input_tokens, resp.usage.output_tokens
        cost = _cost(self.model, tin, tout)
        for block in resp.content:
            if block.type == "tool_use":
                return LLMReply(tool=block.name, args=dict(block.input), tokens_in=tin, tokens_out=tout, cost_usd=cost, tool_use_id=block.id)
        text = "".join(b.text for b in resp.content if b.type == "text")
        return LLMReply(text=text, tokens_in=tin, tokens_out=tout, cost_usd=cost)


# ------------------------------------------------------------------------- gemini

# Illustrative USD per million tokens (input, output). VERIFY against Google's
# current pricing page before quoting any cost number.
GEMINI_PRICES = {"base": (0.30, 2.50), "base2": (0.30, 2.50), "cheap": (0.10, 0.40), "slow": (0.30, 2.50)}


def gemini_model_name(tier: str) -> str:
    """Model id for a tier. Override with AGENTGUARD_GEMINI_BASE / AGENTGUARD_GEMINI_CHEAP.

    The defaults are a guess at sensible current models; if the API says a model
    is not found, set the env vars to a model your key can use.
    """
    if tier == "cheap":
        return os.getenv("AGENTGUARD_GEMINI_CHEAP", "gemini-2.5-flash-lite")
    return os.getenv("AGENTGUARD_GEMINI_BASE", "gemini-2.5-flash")


class GeminiLLM:
    """Real model via the Google Gemini API (needs GEMINI_API_KEY).

    NOT exercised by the offline tests; run it yourself with `--llm gemini`.
    Prompt variants change the real system prompt, so seeded prompt regressions are
    real here. Tool-schema variants change the declarations the model sees.

    Rate limits (429) are retried with exponential backoff; free-tier keys hit them
    quickly, so use a small `--concurrency` (2 to 4) and `--repeats 1` to start.
    """

    def __init__(self, model: str, prompt: str) -> None:
        from google import genai  # lazy: the offline path never needs the SDK or a key

        self.client = genai.Client()  # reads GEMINI_API_KEY (or GOOGLE_API_KEY)
        self.model, self.prompt = model, prompt

    def plan(self, *, system: str, question: str, tool_schemas: list[dict], observations: list[dict]) -> LLMReply:
        from google.genai import types

        decls = [types.FunctionDeclaration(name=s["name"], description=s["description"], parameters_json_schema=s["input_schema"]) for s in tool_schemas]
        contents: list = [types.Content(role="user", parts=[types.Part(text=question)])]
        for ob in observations:
            contents.append(types.Content(role="model", parts=[types.Part(function_call=types.FunctionCall(name=ob["tool"], args=ob["args"]))]))
            contents.append(types.Content(role="user", parts=[types.Part.from_function_response(name=ob["tool"], response={"result": ob["result"]})]))
        cfg = types.GenerateContentConfig(
            system_instruction=system, tools=[types.Tool(function_declarations=decls)], temperature=0.0,
            # WHY manual: AgentGuard must see and trace every tool call itself.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        resp = self._generate(gemini_model_name(self.model), contents, cfg)
        um = resp.usage_metadata
        tin = int(getattr(um, "prompt_token_count", 0) or 0)
        # thinking tokens are billed as output
        tout = int(getattr(um, "candidates_token_count", 0) or 0) + int(getattr(um, "thoughts_token_count", 0) or 0)
        pin, pout = GEMINI_PRICES[self.model]
        cost = (tin * pin + tout * pout) / 1_000_000
        calls = resp.function_calls or []
        if calls:
            return LLMReply(tool=calls[0].name, args=dict(calls[0].args or {}), tokens_in=tin, tokens_out=tout, cost_usd=cost)
        return LLMReply(text=(resp.text or "").strip(), tokens_in=tin, tokens_out=tout, cost_usd=cost)

    def _generate(self, model: str, contents: list, cfg):
        delay = 2.0
        for attempt in range(6):
            try:
                return self.client.models.generate_content(model=model, contents=contents, config=cfg)
            except Exception as exc:
                transient = any(k in str(exc) for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE"))
                if not transient or attempt == 5:
                    raise
                time.sleep(delay)
                delay *= 2


def make_llm(backend: str, model: str, prompt: str):
    if backend == "gemini":
        if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
            raise RuntimeError("GEMINI_API_KEY is not set; export it or use --llm mock")
        return GeminiLLM(model, prompt)
    if backend == "claude":
        if not os.getenv("ANTHROPIC_API_KEY"):
            raise RuntimeError("ANTHROPIC_API_KEY is not set; use --llm mock or export the key")
        return ClaudeLLM(model, prompt)
    return MockLLM(model, prompt)


__all__ = ["make_llm", "MockLLM", "ClaudeLLM", "GeminiLLM", "LLMReply", "PROMPTS"]
