"""Deterministic scorers: exact, cheap, repeatable checks (ADR 0001).

Each scorer returns a ScoreResult with value 1.0 (pass) or 0.0 (fail) and
`evidence` explaining why, so every failure is debuggable.

Metrics produced:
  tool_calls     expected tool calls happened, in order, with matching args,
                 and no forbidden tool was called
  required_facts every required substring appears in the final answer
  tool_errors    no step raised an error and the attempt did not time out

Does NOT judge open-ended quality; that is the (audited) LLM judge's job.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from ..collector.payloads import read_payload
from ..datasets.loader import GoldenCase
from ..db import Attempt, Step


@dataclass
class ScoreResult:
    metric: str
    value: float
    evidence: dict = field(default_factory=dict)


def actual_tool_calls(steps: list[Step], payloads: dict[str, str] | None = None) -> list[dict]:
    """Tool/retrieval steps of an attempt as [{name, args}] in time order.

    `payloads` is an optional preloaded {reference: content} map (see
    collector.payloads.load_payloads); without it each payload is read on demand.
    """
    calls = []
    for s in sorted((s for s in steps if s.type in ("tool", "retrieval")), key=lambda s: (s.started_at, s.id)):
        raw = payloads.get(s.input_ref, "") if payloads is not None else read_payload(s.input_ref)
        try:
            args = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            args = {}
        calls.append({"name": s.name, "args": args if isinstance(args, dict) else {}})
    return calls


def _args_match(expected: dict, actual: dict) -> bool:
    return all(k in actual and str(actual[k]).strip().lower() == str(v).strip().lower() for k, v in expected.items())


def score_tool_calls(case: GoldenCase, steps: list[Step], payloads: dict[str, str] | None = None) -> ScoreResult:
    actual = actual_tool_calls(steps, payloads)
    exp = case.expectations
    forbidden_hit = [c["name"] for c in actual if c["name"] in exp.forbidden_tools]
    # Expected calls must form an ordered subsequence of the actual calls.
    i = 0
    for call in actual:
        if i < len(exp.tool_calls):
            want = exp.tool_calls[i]
            if call["name"] == want.name and _args_match(want.args, call["args"]):
                i += 1
    missing = [c.model_dump() for c in exp.tool_calls[i:]]
    # WHY: a case that expects NO tool calls must see none at all, whatever tool it
    # is (the forbidden list only adds named tools to that rule).
    unexpected = actual if not exp.tool_calls else []
    ok = not missing and not forbidden_hit and not unexpected
    return ScoreResult("tool_calls", 1.0 if ok else 0.0, {"expected": [c.model_dump() for c in exp.tool_calls], "actual": actual, "missing": missing, "forbidden_called": forbidden_hit})


def score_required_facts(case: GoldenCase, attempt: Attempt) -> ScoreResult:
    answer = (attempt.answer or "").lower()
    missing = [f for f in case.expectations.required_facts if f.lower() not in answer]
    return ScoreResult("required_facts", 0.0 if missing else 1.0, {"missing": missing, "answer": attempt.answer})


def score_tool_errors(attempt: Attempt, steps: list[Step]) -> ScoreResult:
    errors = [{"step": s.name, "error": s.error} for s in steps if s.error]
    bad = attempt.status != "ok" or bool(errors)
    return ScoreResult("tool_errors", 0.0 if bad else 1.0, {"attempt_status": attempt.status, "attempt_error": attempt.error, "step_errors": errors})


def score_attempt(case: GoldenCase, attempt: Attempt, steps: list[Step], payloads: dict[str, str] | None = None) -> list[ScoreResult]:
    return [score_tool_calls(case, steps, payloads), score_required_facts(case, attempt), score_tool_errors(attempt, steps)]
