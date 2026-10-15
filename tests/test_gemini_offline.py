"""Gemini backend tests that need NO network or key: a fake client stands in for the API.

They check the request we build (tool declarations, history) and how we read the
reply (tool call vs text, token and cost accounting, retry on rate limits).
They cannot prove the live API accepts our request; that needs a real key.
"""

from types import SimpleNamespace

import pytest

from agentguard.scorers.llm_judge import GeminiJudge, make_judge
from demo_agent.llm import GeminiLLM, gemini_model_name, make_llm
from demo_agent.tools import tool_schemas


class FakeModels:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def generate_content(self, model, contents, config):
        self.calls.append((model, contents, config))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r


def reply(text=None, call=None, tin=100, tout=10, thoughts=5):
    fc = [SimpleNamespace(name=call[0], args=call[1])] if call else None
    um = SimpleNamespace(prompt_token_count=tin, candidates_token_count=tout, thoughts_token_count=thoughts)
    return SimpleNamespace(function_calls=fc, text=text, usage_metadata=um)


def make(replies, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    llm = GeminiLLM.__new__(GeminiLLM)
    llm.model, llm.prompt = "base", "v1"
    llm.client = SimpleNamespace(models=FakeModels(replies))
    return llm


def test_tool_call_reply_and_cost(monkeypatch):
    llm = make([reply(call=("track_shipment", {"order_id": "ORD-1001"}))], monkeypatch)
    r = llm.plan(system="s", question="q", tool_schemas=tool_schemas("v1"), observations=[])
    assert r.tool == "track_shipment" and r.args == {"order_id": "ORD-1001"}
    assert r.tokens_in == 100 and r.tokens_out == 15  # thinking tokens count as output
    assert r.cost_usd == pytest.approx((100 * 0.30 + 15 * 2.50) / 1e6)
    model, contents, cfg = llm.client.models.calls[0]
    assert model == gemini_model_name("base")
    assert [d.name for d in cfg.tools[0].function_declarations][0] == "lookup_order"
    assert cfg.automatic_function_calling.disable is True


def test_history_is_sent_after_a_tool_call(monkeypatch):
    llm = make([reply(text="done")], monkeypatch)
    obs = [{"tool": "lookup_order", "args": {"order_id": "ORD-1001"}, "tool_use_id": "x", "result": {"total": 5}}]
    r = llm.plan(system="s", question="q", tool_schemas=tool_schemas("v1"), observations=obs)
    assert r.text == "done" and r.tool is None
    contents = llm.client.models.calls[0][1]
    assert [c.role for c in contents] == ["user", "model", "user"]


def test_rate_limit_is_retried_then_succeeds(monkeypatch):
    llm = make([RuntimeError("429 RESOURCE_EXHAUSTED"), reply(text="ok")], monkeypatch)
    assert llm.plan(system="s", question="q", tool_schemas=[], observations=[]).text == "ok"
    assert len(llm.client.models.calls) == 2


def test_non_transient_error_is_not_retried(monkeypatch):
    llm = make([RuntimeError("400 INVALID_ARGUMENT")], monkeypatch)
    with pytest.raises(RuntimeError, match="400"):
        llm.plan(system="s", question="q", tool_schemas=[], observations=[])


def test_missing_key_gives_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="GEMINI_API_KEY"):
        make_llm("gemini", "base", "v1")


def judge_with(text, monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    j = GeminiJudge.__new__(GeminiJudge)
    j.model, j.name = "m", "gemini:m"
    j.client = SimpleNamespace(models=FakeModels([SimpleNamespace(text=text)]))
    return j


def test_judge_parses_pass_and_unparseable_is_fail(monkeypatch):
    assert judge_with('{"verdict": "pass", "reason": "good"}', monkeypatch).judge("q", "a1", "r").passed
    v = judge_with("I think it is fine", monkeypatch).judge("q", "a2", "r")
    assert not v.passed and "unparseable" in v.reason


def test_judge_caches(monkeypatch):
    j = judge_with('{"verdict": "pass", "reason": "ok"}', monkeypatch)
    j.judge("q", "same", "r")
    j.judge("q", "same", "r")  # second call served from cache: fake has only one reply
    assert len(j.client.models.calls) == 1


def test_make_judge_knows_gemini():
    assert make_judge("none") is None
