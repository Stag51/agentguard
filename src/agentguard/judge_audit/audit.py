"""Judge audit: how often is the LLM judge wrong?

Runs a judge over a trap set of (question, answer, rubric, human label) and
reports agreement, false-pass rate and false-fail rate.

  false pass  judge says PASS but the human label is FAIL  (dangerous: lets bad answers through)
  false fail  judge says FAIL but the human label is PASS  (annoying: blocks good answers)

The trap set must be labelled BY HAND. A judge audited against labels it helped
create proves nothing. Aim for 50 cases; datasets/judge_traps.jsonl starts small
and says so.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..scorers.llm_judge import Judge


def load_traps(path: str | Path) -> list[dict]:
    traps = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    for t in traps:
        if t.get("label") not in ("pass", "fail"):
            raise ValueError(f"trap {t.get('id')}: label must be 'pass' or 'fail'")
    return traps


def audit_judge(judge: Judge, traps: list[dict]) -> dict:
    tp = tn = fp = fn = 0
    wrong: list[dict] = []
    for t in traps:
        v = judge.judge(t["question"], t["answer"], t["rubric"])
        truth_pass = t["label"] == "pass"
        if v.passed and truth_pass:
            tp += 1
        elif not v.passed and not truth_pass:
            tn += 1
        elif v.passed and not truth_pass:
            fp += 1
            wrong.append({"id": t["id"], "error": "false_pass", "reason": v.reason})
        else:
            fn += 1
            wrong.append({"id": t["id"], "error": "false_fail", "reason": v.reason})
    n = len(traps)
    n_fail, n_pass = tn + fp, tp + fn
    return {
        "judge": judge.name,
        "n": n,
        "agreement": (tp + tn) / n if n else 0.0,
        "false_pass_rate": fp / n_fail if n_fail else 0.0,
        "false_fail_rate": fn / n_pass if n_pass else 0.0,
        "label_counts": {"pass": n_pass, "fail": n_fail},
        "wrong": wrong,
    }
