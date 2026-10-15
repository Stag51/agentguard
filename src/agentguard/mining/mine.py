"""Failure mining: turn failed attempts into candidate golden cases for review.

Flow:  failed attempts in a run  ->  candidates.jsonl (status: pending)
       -> a human reviews, fixes the expectations -> `approve` appends to a dataset.

WHY a human gate: a failure tells us the agent did something wrong, not what the
RIGHT behaviour is. Expectations must be written/confirmed by a person; otherwise
we would be grading the agent against its own mistakes.

The candidate's `expectations` start empty on purpose and `needs_expectations`
stays true until the reviewer fills them in.
"""

from __future__ import annotations

import json
from pathlib import Path

from sqlalchemy import select

from .. import db
from ..metrics import case_results


def mine_failures(run_id: str, out_path: str | Path) -> list[dict]:
    """Write one pending candidate per failed case in the run; return them."""
    results = case_results(run_id)
    out = Path(out_path)
    existing = {json.loads(l)["source"]["case_id"] + "|" + json.loads(l)["source"]["run_id"] for l in out.read_text(encoding="utf-8").splitlines() if l.strip()} if out.exists() else set()
    candidates = []
    with db.get_session() as s:
        for cid, r in results.items():
            if r["passed"] or f"{cid}|{run_id}" in existing:
                continue
            att = s.scalars(select(db.Attempt).where(db.Attempt.run_id == run_id, db.Attempt.case_id == cid).order_by(db.Attempt.repeat)).first()
            case = s.scalars(select(db.Case).where(db.Case.id == cid)).first()
            candidates.append({
                "id": f"mined-{run_id}-{cid}",
                "status": "pending",
                "needs_expectations": True,
                "tags": list(case.tags) + ["mined"] if case else ["mined"],
                "input": case.input if case else {},
                "expectations": {"tool_calls": [], "forbidden_tools": [], "required_facts": [], "judge_rubric": None},
                "source": {"run_id": run_id, "case_id": cid, "observed_answer": att.answer if att else None},
            })
    if candidates:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8") as f:
            for c in candidates:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
    return candidates


def approve(candidates_path: str | Path, candidate_id: str, dataset_path: str | Path) -> dict:
    """Move a reviewed candidate into a dataset. Refuses if expectations are still empty."""
    cpath = Path(candidates_path)
    rows = [json.loads(l) for l in cpath.read_text(encoding="utf-8").splitlines() if l.strip()]
    row = next((r for r in rows if r["id"] == candidate_id), None)
    if row is None:
        raise KeyError(f"candidate '{candidate_id}' not found")
    e = row["expectations"]
    if not (e["tool_calls"] or e["required_facts"] or e["judge_rubric"] or e["forbidden_tools"]):
        raise ValueError("fill in expectations (tool_calls / required_facts / ...) before approving")
    case = {"id": row["id"], "tags": row["tags"], "input": row["input"], "expectations": e}
    with Path(dataset_path).open("a", encoding="utf-8") as f:
        f.write(json.dumps(case, ensure_ascii=False) + "\n")
    row["status"] = "approved"
    row["needs_expectations"] = False
    cpath.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")
    return case
