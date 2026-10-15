"""LLM judge for open-ended answers, with a cache and an offline stand-in.

Used only when a case has `judge_rubric` (ADR 0001). A judge is a model grading a
model, so it can be wrong; `judge_audit` measures how wrong.

Judges:
  ClaudeJudge   real judge (needs ANTHROPIC_API_KEY). Small model, cached.
  KeywordJudge  OFFLINE STAND-IN to exercise the plumbing. It is a crude
                heuristic, NOT a quality signal. Never report its numbers as the
                judge's accuracy.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass
from typing import Protocol

from .. import config


@dataclass
class Verdict:
    passed: bool
    reason: str


class Judge(Protocol):
    name: str

    def judge(self, question: str, answer: str, rubric: str) -> Verdict: ...


class KeywordJudge:
    name = "keyword-offline"
    _BAD = ("something went wrong", "unable to", "i guess", "i'm not sure", "maybe", "sunny", "couldn't find")

    def judge(self, question: str, answer: str, rubric: str) -> Verdict:
        a = (answer or "").lower()
        if len(a.strip()) < 20:
            return Verdict(False, "answer too short")
        hit = next((b for b in self._BAD if b in a), None)
        if hit:
            return Verdict(False, f"contains '{hit}'")
        return Verdict(True, "no red flags found")


class ClaudeJudge:
    """Grades with a small Claude model and caches verdicts on disk (N3)."""

    PROMPT = (
        "You are a strict grader. Rubric:\n{rubric}\n\nQuestion: {question}\nAnswer: {answer}\n\n"
        'Reply with JSON only: {{"verdict": "pass" or "fail", "reason": "<one sentence>"}}'
    )

    def __init__(self, model: str = "claude-haiku-5-5") -> None:
        import anthropic

        self.client = anthropic.Anthropic()
        self.model = model
        self.name = f"claude:{model}"

    def judge(self, question: str, answer: str, rubric: str) -> Verdict:
        key = hashlib.sha256(json.dumps([self.model, rubric, question, answer]).encode()).hexdigest()[:32]
        folder = config.judge_cache_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{key}.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return Verdict(d["passed"], d["reason"])
        resp = self.client.messages.create(
            model=self.model, max_tokens=200, temperature=0,
            messages=[{"role": "user", "content": self.PROMPT.format(rubric=rubric, question=question, answer=answer)}],
        )
        text = "".join(b.text for b in resp.content if b.type == "text")
        try:
            d = json.loads(text[text.index("{"): text.rindex("}") + 1])
            v = Verdict(str(d.get("verdict", "")).lower() == "pass", str(d.get("reason", "")))
        except Exception:
            # WHY: an unparseable verdict must never count as a pass
            v = Verdict(False, f"unparseable judge output: {text[:80]}")
        path.write_text(json.dumps({"passed": v.passed, "reason": v.reason}), encoding="utf-8")
        return v


class GeminiJudge:
    """Grades with a small Gemini model and caches verdicts on disk (N3).

    Same prompt and parsing rules as ClaudeJudge: an unparseable verdict is a FAIL,
    never a pass. Uses the 'cheap' tier model (override AGENTGUARD_GEMINI_CHEAP).
    """

    def __init__(self, model: str | None = None) -> None:
        from google import genai

        self.client = genai.Client()  # reads GEMINI_API_KEY (or GOOGLE_API_KEY)
        self.model = model or os.getenv("AGENTGUARD_GEMINI_CHEAP", "gemini-2.5-flash-lite")
        self.name = f"gemini:{self.model}"

    def judge(self, question: str, answer: str, rubric: str) -> Verdict:
        key = hashlib.sha256(json.dumps([self.model, rubric, question, answer]).encode()).hexdigest()[:32]
        folder = config.judge_cache_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{key}.json"
        if path.exists():
            d = json.loads(path.read_text(encoding="utf-8"))
            return Verdict(d["passed"], d["reason"])
        from google.genai import types

        prompt = ClaudeJudge.PROMPT.format(rubric=rubric, question=question, answer=answer)
        text = ""
        delay = 2.0
        for attempt in range(6):
            try:
                resp = self.client.models.generate_content(model=self.model, contents=prompt, config=types.GenerateContentConfig(temperature=0.0))
                text = resp.text or ""
                break
            except Exception as exc:
                if not any(k in str(exc) for k in ("429", "RESOURCE_EXHAUSTED", "503", "UNAVAILABLE")) or attempt == 5:
                    raise
                time.sleep(delay)
                delay *= 2
        try:
            d = json.loads(text[text.index("{"): text.rindex("}") + 1])
            v = Verdict(str(d.get("verdict", "")).lower() == "pass", str(d.get("reason", "")))
        except Exception:
            v = Verdict(False, f"unparseable judge output: {text[:80]}")
        path.write_text(json.dumps({"passed": v.passed, "reason": v.reason}), encoding="utf-8")
        return v


def make_judge(kind: str) -> Judge | None:
    if kind == "none":
        return None
    if kind == "gemini":
        return GeminiJudge()
    if kind == "keyword":
        return KeywordJudge()
    if kind == "claude":
        return ClaudeJudge()
    raise ValueError(f"unknown judge '{kind}'")
