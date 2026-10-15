"""Unit tests for pure logic: loader, scorers, gate, metrics, redaction."""

import json
from datetime import datetime, timezone

import pytest

from agentguard.collector.payloads import write_payload
from agentguard.datasets.loader import GoldenCase, load_dataset
from agentguard.db import Attempt, Step
from agentguard.gate.gate import Thresholds, compare
from agentguard.metrics import percentile
from agentguard.redact import redact
from agentguard.scorers.deterministic import score_required_facts, score_tool_calls, score_tool_errors


def case(calls=(), facts=(), forbidden=()):
    return GoldenCase(
        id="c", tags=[], input={"question": "q"},
        expectations={"tool_calls": [{"name": n, "args": a} for n, a in calls], "required_facts": list(facts), "forbidden_tools": list(forbidden)},
    )


def step(name, args, i, type="tool", error=None):
    return Step(
        id=i, run_id="r", case_id="c", repeat=0, type=type, name=name, input_ref=write_payload(json.dumps(args)),
        started_at=datetime.fromtimestamp(i, tz=timezone.utc), error=error,
    )


def test_golden_dataset_is_valid():
    version, cases = load_dataset("datasets/golden_v1.jsonl")
    assert len(cases) == 30 and version.startswith("golden_v1@")


def test_loader_rejects_duplicates_and_missing_question(tmp_path):
    p = tmp_path / "d.jsonl"
    row = {"id": "a", "input": {"question": "x"}, "expectations": {}}
    p.write_text(json.dumps(row) + "\n" + json.dumps(row) + "\n")
    with pytest.raises(ValueError, match="duplicate"):
        load_dataset(p)
    p.write_text(json.dumps({"id": "a", "input": {}, "expectations": {}}) + "\n")
    with pytest.raises(ValueError, match="question"):
        load_dataset(p)


def test_tool_calls_ordered_subsequence_and_arg_subset():
    c = case(calls=[("a", {"x": "1"}), ("b", {})])
    ok = [step("a", {"x": "1", "extra": 2}, 1), step("noise", {}, 2), step("b", {}, 3)]
    assert score_tool_calls(c, ok).value == 1.0
    assert score_tool_calls(c, [step("b", {}, 1), step("a", {"x": "1"}, 2)]).value == 0.0
    assert score_tool_calls(c, [step("a", {"x": "2"}, 1), step("b", {}, 2)]).value == 0.0


def test_case_with_no_expected_calls_fails_on_any_call():
    c = case()
    assert score_tool_calls(c, []).value == 1.0
    assert score_tool_calls(c, [step("anything", {}, 1)]).value == 0.0


def test_forbidden_tool_fails():
    assert score_tool_calls(case(calls=[("a", {})], forbidden=["bad"]), [step("a", {}, 1), step("bad", {}, 2)]).value == 0.0


def test_required_facts_case_insensitive():
    c = case(facts=["15 days", "Blue"])
    assert score_required_facts(c, Attempt(answer="within 15 DAYS via blue")).value == 1.0
    r = score_required_facts(c, Attempt(answer="within 15 days"))
    assert r.value == 0.0 and r.evidence["missing"] == ["Blue"]


def test_tool_errors():
    assert score_tool_errors(Attempt(status="ok"), []).value == 1.0
    assert score_tool_errors(Attempt(status="timeout"), []).value == 0.0
    assert score_tool_errors(Attempt(status="ok"), [step("t", {}, 1, error="boom")]).value == 0.0


def summary(**kw):
    base = dict(
        status="complete", dataset_version="d", success_rate=1.0, tool_correctness=1.0, cost_per_task=1.0,
        p95_latency_ms=100.0, error_rate=0.0, success_by_tag={"t": 1.0},
    )
    return {**base, **kw}


def test_gate_passes_identical_and_noise():
    assert compare(summary(), summary()).passed
    assert compare(summary(success_rate=0.97), summary()).passed  # within 0.05


@pytest.mark.parametrize(
    "change,check",
    [
        (dict(success_rate=0.9), "success_rate"),
        (dict(tool_correctness=0.9), "tool_correctness"),
        (dict(cost_per_task=1.5), "cost_per_task"),
        (dict(p95_latency_ms=250.0), "p95_latency"),
        (dict(error_rate=0.2), "error_rate"),
        (dict(success_by_tag={"t": 0.5}), "tag:t"),
        (dict(status="partial"), "status"),
        (dict(dataset_version="other"), "dataset"),
    ],
)
def test_gate_blocks_each_regression(change, check):
    res = compare(summary(**change), summary())
    assert not res.passed and any(f.check == check for f in res.failures)


def test_gate_ignore_switch():
    assert compare(summary(p95_latency_ms=999.0), summary(), Thresholds(ignore={"latency"})).passed


def test_percentile_nearest_rank():
    assert percentile([], 95) == 0.0
    assert percentile(list(range(1, 101)), 95) == 95
    assert percentile([5.0], 95) == 5.0


def test_redact_masks_secrets_but_keeps_order_ids():
    out = redact("mail a@b.com key sk-abcdefghijklmnopqrstuv card 4111 1111 1111 1111 order ORD-1003")
    assert "a@b.com" not in out and "sk-abc" not in out and "4111" not in out and "ORD-1003" in out
