"""Eval runner: replay every golden case against an agent, in parallel.

For each (case, repeat) it:
  1. runs the agent in a worker thread inside a trace context (so spans are tagged),
  2. enforces a timeout,
  3. records an Attempt (answer, status, wall-clock latency, token/cost totals).
After all attempts it scores the run and marks it complete/partial.

WHY threads (asyncio.to_thread): LangGraph agents and LLM SDK calls are usually
blocking. asyncio gives us concurrency control (semaphore) and per-attempt
timeouts without making the agent code async.

WHY a timeout does not kill the thread: Python cannot safely kill a thread. The
attempt is recorded as `timeout` and the run moves on; the stray thread may still
write spans later. That is a known limit, noted in docs/failure-modes.md.

Cost cap (N3): before starting each attempt we check money spent so far; past the
cap, remaining attempts are skipped and the run is `partial`. The gate refuses
partial runs.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from typing import Callable

from sqlalchemy import delete, func, select

from .. import db
from ..datasets.loader import GoldenCase
from ..scorers.llm_judge import Judge
from ..scorers.runner import score_run
from ..sdk import trace_context

AgentFn = Callable[[str], str]


def _invoke(agent: AgentFn, question: str, run_id: str, case_id: str, repeat: int) -> str:
    with trace_context(run_id, case_id, repeat):
        return agent(question)


def _spent(run_id: str) -> float:
    with db.get_session() as s:
        return float(s.scalar(select(func.coalesce(func.sum(db.Step.cost_usd), 0.0)).where(db.Step.run_id == run_id)) or 0.0)


async def run_evaluation(
    agent_factory: Callable[[], AgentFn],
    cases: list[GoldenCase],
    *,
    dataset_version: str,
    agent_version: str,
    config: dict | None = None,
    repeats: int = 3,
    concurrency: int = 8,
    timeout_s: float = 30.0,
    budget_usd: float | None = None,
    label: str | None = None,
    judge: Judge | None = None,
) -> str:
    """Run the evaluation and return the run id."""
    run_id = uuid.uuid4().hex[:12]
    with db.get_session() as s:
        s.add(db.Run(id=run_id, label=label, agent_version=agent_version, dataset_version=dataset_version, config=config or {}, repeats=repeats))
        for c in cases:  # upsert the case copies used for joins
            s.merge(db.Case(dataset_version=dataset_version, id=c.id, tags=c.tags, input=c.input, expectations=c.expectations.model_dump()))
        s.commit()

    sem = asyncio.Semaphore(concurrency)
    skipped = 0

    async def one(case: GoldenCase, repeat: int) -> None:
        nonlocal skipped
        async with sem:
            if budget_usd is not None and _spent(run_id) >= budget_usd:
                skipped += 1
                return
            status, answer, error = "ok", None, None
            t0 = time.perf_counter()
            try:
                agent = agent_factory()  # fresh agent per attempt: no shared state between repeats
                answer = await asyncio.wait_for(asyncio.to_thread(_invoke, agent, case.question, run_id, case.id, repeat), timeout_s)
            except asyncio.TimeoutError:
                status, error = "timeout", f"no answer within {timeout_s}s"
            except Exception as exc:  # WHY: one broken case must not abort the whole run
                status, error = "error", f"{type(exc).__name__}: {exc}"
            latency_ms = (time.perf_counter() - t0) * 1000
            with db.get_session() as s:
                s.execute(delete(db.Attempt).where(db.Attempt.run_id == run_id, db.Attempt.case_id == case.id, db.Attempt.repeat == repeat))  # idempotent
                s.add(db.Attempt(run_id=run_id, case_id=case.id, repeat=repeat, status=status, answer=answer, error=error, latency_ms=latency_ms))
                s.commit()

    await asyncio.gather(*(one(c, r) for c in cases for r in range(repeats)))

    # Fill token/cost totals from the spans (one aggregate query per run).
    with db.get_session() as s:
        for a in s.scalars(select(db.Attempt).where(db.Attempt.run_id == run_id)).all():
            tin, tout, cost = s.execute(
                select(func.coalesce(func.sum(db.Step.tokens_in), 0), func.coalesce(func.sum(db.Step.tokens_out), 0), func.coalesce(func.sum(db.Step.cost_usd), 0.0)).where(
                    db.Step.run_id == run_id, db.Step.case_id == a.case_id, db.Step.repeat == a.repeat
                )
            ).one()
            a.tokens_in, a.tokens_out, a.cost_usd = int(tin), int(tout), float(cost)
        s.commit()

    score_run(run_id, cases, judge)

    with db.get_session() as s:
        run = s.get(db.Run, run_id)
        assert run is not None
        run.status = "partial" if skipped else "complete"
        run.finished_at = db.utcnow()
        s.commit()
    return run_id
