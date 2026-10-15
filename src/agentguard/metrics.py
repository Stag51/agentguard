"""Turn raw Attempts and Scores into the numbers the gate and dashboard use.

Definitions (docs/scoring-and-metrics.md):
  attempt passes   all of its scores equal 1.0 (deterministic checks + judge if present)
  case passes      a strict majority of its repeats pass (2 of 3)   <- handles non-determinism
  success_rate     cases passed / cases run, overall and per tag
  tool_correctness mean of the tool_calls score over attempts
  cost_per_task    mean over cases of mean attempt cost
  p95_latency_ms   95th percentile (nearest rank) of attempt wall-clock latency
  error_rate       share of attempts that errored or timed out
"""

from __future__ import annotations

import math
from collections import defaultdict
from statistics import mean

from sqlalchemy import select

from . import db


def percentile(values: list[float], pct: float) -> float:
    """Nearest-rank percentile. Empty list -> 0.0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[rank - 1]


def case_results(run_id: str) -> dict[str, dict]:
    """Per-case outcome: {case_id: {passed, pass_rate, tags, repeats}}."""
    with db.get_session() as s:
        run = s.get(db.Run, run_id)
        if run is None:
            raise KeyError(f"run '{run_id}' not found")
        attempts = s.scalars(select(db.Attempt).where(db.Attempt.run_id == run_id)).all()
        scores = s.scalars(select(db.Score).where(db.Score.run_id == run_id)).all()
        cases = {c.id: c for c in s.scalars(select(db.Case).where(db.Case.dataset_version == run.dataset_version)).all()}
    by_attempt: dict[tuple[str, int], list[float]] = defaultdict(list)
    for sc in scores:
        by_attempt[(sc.case_id, sc.repeat)].append(sc.value)
    per_case: dict[str, list[bool]] = defaultdict(list)
    for a in attempts:
        vals = by_attempt.get((a.case_id, a.repeat), [])
        per_case[a.case_id].append(bool(vals) and all(v >= 1.0 for v in vals))
    out = {}
    for cid, flags in per_case.items():
        out[cid] = {
            "passed": sum(flags) * 2 > len(flags),
            "pass_rate": sum(flags) / len(flags),
            "repeats": len(flags),
            "tags": list(cases[cid].tags) if cid in cases else [],
        }
    return out


def summarize_run(run_id: str) -> dict:
    """All headline numbers for a run, as plain JSON-able data."""
    with db.get_session() as s:
        run = s.get(db.Run, run_id)
        if run is None:
            raise KeyError(f"run '{run_id}' not found")
        attempts = s.scalars(select(db.Attempt).where(db.Attempt.run_id == run_id)).all()
        tool_scores = s.scalars(select(db.Score).where(db.Score.run_id == run_id, db.Score.metric == "tool_calls")).all()
        meta = dict(id=run.id, label=run.label, agent_version=run.agent_version, dataset_version=run.dataset_version, status=run.status, repeats=run.repeats)
    results = case_results(run_id)
    n = len(results)
    by_tag: dict[str, list[bool]] = defaultdict(list)
    for r in results.values():
        for t in r["tags"]:
            by_tag[t].append(r["passed"])
    cost_by_case: dict[str, list[float]] = defaultdict(list)
    for a in attempts:
        cost_by_case[a.case_id].append(a.cost_usd)
    return {
        **meta,
        "n_cases": n,
        "n_attempts": len(attempts),
        "success_rate": (sum(r["passed"] for r in results.values()) / n) if n else 0.0,
        "success_by_tag": {t: sum(v) / len(v) for t, v in sorted(by_tag.items())},
        "tool_correctness": mean(x.value for x in tool_scores) if tool_scores else 0.0,
        "cost_per_task": mean(mean(v) for v in cost_by_case.values()) if cost_by_case else 0.0,
        "p95_latency_ms": percentile([a.latency_ms for a in attempts], 95),
        "error_rate": (sum(a.status != "ok" for a in attempts) / len(attempts)) if attempts else 0.0,
    }
