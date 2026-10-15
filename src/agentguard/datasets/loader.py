"""Golden dataset loading and validation.

A dataset is a JSONL file; each line is one Case:

    {"id": "track-01", "tags": ["order_status"],
     "input": {"question": "Where is my order ORD-1003?"},
     "expectations": {
        "tool_calls": [{"name": "track_shipment", "args": {"order_id": "ORD-1003"}}],
        "forbidden_tools": [],
        "required_facts": ["shipped", "TCS"],
        "judge_rubric": null}}

WHY JSONL in Git: cases are reviewed like code (ADR 0003). The dataset *version*
is the file stem plus a short content hash, so any edit produces a new version
and a run always records exactly what it was tested on.

Validation happens on load, so a malformed case fails fast instead of silently
scoring wrong.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, Field, model_validator


class ExpectedCall(BaseModel):
    name: str
    args: dict = Field(default_factory=dict)  # subset match: listed args must equal


class Expectations(BaseModel):
    # Calls that must appear, in this order (other calls may appear in between).
    tool_calls: list[ExpectedCall] = Field(default_factory=list)
    forbidden_tools: list[str] = Field(default_factory=list)
    # Substrings (case-insensitive) that must appear in the final answer.
    required_facts: list[str] = Field(default_factory=list)
    # If set, an LLM judge also grades the answer against this rubric.
    judge_rubric: str | None = None


class GoldenCase(BaseModel):
    id: str
    tags: list[str] = Field(default_factory=list)
    input: dict
    expectations: Expectations

    @model_validator(mode="after")
    def _has_question(self) -> "GoldenCase":
        if not isinstance(self.input.get("question"), str) or not self.input["question"].strip():
            raise ValueError(f"case {self.id}: input.question is required")
        return self

    @property
    def question(self) -> str:
        return self.input["question"]


def load_dataset(path: str | Path) -> tuple[str, list[GoldenCase]]:
    """Return (dataset_version, cases). Raises ValueError on invalid files."""
    p = Path(path)
    raw = p.read_text(encoding="utf-8")
    cases: list[GoldenCase] = []
    for n, line in enumerate(raw.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            cases.append(GoldenCase.model_validate(json.loads(line)))
        except Exception as exc:
            raise ValueError(f"{p.name}:{n}: {exc}") from exc
    ids = [c.id for c in cases]
    dupes = {i for i in ids if ids.count(i) > 1}
    if dupes:
        raise ValueError(f"{p.name}: duplicate case ids: {sorted(dupes)}")
    if not cases:
        raise ValueError(f"{p.name}: no cases")
    version = f"{p.stem}@{hashlib.sha256(raw.encode()).hexdigest()[:8]}"
    return version, cases
