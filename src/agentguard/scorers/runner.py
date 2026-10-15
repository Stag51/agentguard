"""Score every attempt of a run and store the results.

Reads Attempts and Steps from the database (scorers read traces, not agent
internals), writes Score rows. Idempotent: re-scoring a run replaces old scores
(unique key run/case/repeat/metric).
"""

from __future__ import annotations

from sqlalchemy import delete, select

from .. import db
from ..collector.payloads import load_payloads
from ..datasets.loader import GoldenCase
from .deterministic import ScoreResult, score_attempt
from .llm_judge import Judge


def score_run(run_id: str, cases: list[GoldenCase], judge: Judge | None = None) -> None:
    by_id = {c.id: c for c in cases}
    with db.get_session() as s:
        attempts = s.scalars(select(db.Attempt).where(db.Attempt.run_id == run_id)).all()
        steps = s.scalars(select(db.Step).where(db.Step.run_id == run_id)).all()
        steps_by_key: dict[tuple[str, int], list[db.Step]] = {}
        for st in steps:
            steps_by_key.setdefault((st.case_id, st.repeat), []).append(st)
        payloads = load_payloads([st.input_ref for st in steps if st.type in ("tool", "retrieval") and st.input_ref], s)
        s.execute(delete(db.Score).where(db.Score.run_id == run_id))
        for a in attempts:
            case = by_id.get(a.case_id)
            if case is None:
                continue
            results: list[ScoreResult] = score_attempt(case, a, steps_by_key.get((a.case_id, a.repeat), []), payloads)
            if case.expectations.judge_rubric and judge is not None and a.status == "ok":
                v = judge.judge(case.question, a.answer or "", case.expectations.judge_rubric)
                results.append(ScoreResult("judge", 1.0 if v.passed else 0.0, {"judge": judge.name, "reason": v.reason}))
            for r in results:
                s.add(db.Score(run_id=run_id, case_id=a.case_id, repeat=a.repeat, metric=r.metric, value=r.value, evidence=r.evidence))
        s.commit()
