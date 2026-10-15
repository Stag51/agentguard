"""Integration tests: run the real pipeline (mock LLM) on a few cases."""

import asyncio
import json
from dataclasses import asdict

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from agentguard import db
from agentguard.api.app import create_app
from agentguard.datasets.loader import load_dataset
from agentguard.gate.gate import Thresholds, compare
from agentguard.judge_audit.audit import audit_judge, load_traps
from agentguard.metrics import summarize_run
from agentguard.mining.mine import approve, mine_failures
from agentguard.runner.runner import run_evaluation
from agentguard.scorers.llm_judge import KeywordJudge, Verdict
from agentguard.scorers.runner import score_run
from agentguard.sdk import span, trace_context
from demo_agent.agent import build_agent
from demo_agent.variants import get_config

IDS = {"status-01", "details-01", "policy-01", "refund-01", "unknown-01", "oos-01", "open-01"}


def evaluate(agent="base", repeats=2, budget=None, timeout=30.0, judge=None):
    dv, cases = load_dataset("datasets/golden_v1.jsonl")
    cases = [c for c in cases if c.id in IDS]
    cfg = get_config(agent)
    run_id = asyncio.run(
        run_evaluation(
            lambda: build_agent(cfg), cases, dataset_version=dv, agent_version=cfg.version(), config=asdict(cfg),
            repeats=repeats, budget_usd=budget, timeout_s=timeout, judge=judge,
        )
    )
    return run_id, cases


def test_base_agent_passes_everything_and_is_traced():
    run_id, _ = evaluate()
    s = summarize_run(run_id)
    assert s["status"] == "complete" and s["success_rate"] == 1.0 and s["n_attempts"] == 14
    assert s["cost_per_task"] > 0 and s["p95_latency_ms"] > 0
    with db.get_session() as sess:
        types = {st.type for st in sess.scalars(select(db.Step).where(db.Step.run_id == run_id))}
    assert {"llm", "tool", "retrieval"} <= types


def test_gate_blocks_schema_regression_and_allows_same_agent():
    base, _ = evaluate()
    good, _ = evaluate()
    bad, _ = evaluate("R03_schema_renamed_order_id")
    t = Thresholds(ignore={"latency"})
    assert compare(summarize_run(good), summarize_run(base), t).passed
    assert not compare(summarize_run(bad), summarize_run(base), t).passed


def test_scoring_is_idempotent():
    run_id, cases = evaluate()
    with db.get_session() as s:
        n1 = len(s.scalars(select(db.Score).where(db.Score.run_id == run_id)).all())
    score_run(run_id, cases)
    with db.get_session() as s:
        n2 = len(s.scalars(select(db.Score).where(db.Score.run_id == run_id)).all())
    assert n1 == n2 > 0


def test_budget_cap_marks_run_partial():
    run_id, _ = evaluate(budget=0.0)
    assert summarize_run(run_id)["status"] == "partial"


def test_timeout_is_recorded_not_raised():
    run_id, _ = evaluate(timeout=0.001)
    s = summarize_run(run_id)
    assert s["error_rate"] == 1.0 and s["success_rate"] == 0.0


def test_judge_scores_open_ended_cases():
    run_id, _ = evaluate(judge=KeywordJudge())
    with db.get_session() as s:
        judged = s.scalars(select(db.Score).where(db.Score.run_id == run_id, db.Score.metric == "judge")).all()
    assert len(judged) == 2  # open-01 x 2 repeats


def test_sdk_never_hides_agent_errors_and_is_noop_outside_context():
    with span("tool", "x") as s:  # no context: no-op, must still work
        s.set_output(1)
    with pytest.raises(ZeroDivisionError):
        with trace_context("r", "c", 0):
            with span("tool", "boom"):
                1 / 0
    with db.get_session() as sess:
        step = sess.scalars(select(db.Step).where(db.Step.name == "boom")).one()
    assert "ZeroDivisionError" in step.error


def test_exporter_failure_does_not_crash_agent(monkeypatch):
    def broken():
        raise RuntimeError("db down")

    monkeypatch.setattr(db, "get_session", broken)
    with trace_context("r", "c", 0):
        with span("tool", "ok") as s:
            s.set_output("fine")  # must not raise


def test_mining_and_approval(tmp_path):
    run_id, _ = evaluate("R03_schema_renamed_order_id")
    cand = tmp_path / "cand.jsonl"
    mined = mine_failures(run_id, cand)
    assert mined and all(c["status"] == "pending" for c in mined)
    assert mine_failures(run_id, cand) == []  # no duplicates on re-mine
    target = tmp_path / "ds.jsonl"
    target.write_text("")
    with pytest.raises(ValueError, match="expectations"):
        approve(cand, mined[0]["id"], target)
    rows = [json.loads(line) for line in cand.read_text().splitlines()]
    rows[0]["expectations"]["required_facts"] = ["delivered"]
    cand.write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    approve(cand, mined[0]["id"], target)
    assert json.loads(target.read_text().splitlines()[0])["expectations"]["required_facts"] == ["delivered"]


def test_judge_audit_rates():
    class AlwaysPass:
        name = "always-pass"

        def judge(self, q, a, r):
            return Verdict(True, "")

    r = audit_judge(AlwaysPass(), load_traps("datasets/judge_traps.jsonl"))
    assert r["false_pass_rate"] == 1.0 and r["false_fail_rate"] == 0.0 and r["n"] == 12


def test_api_endpoints():
    run_id, _ = evaluate()
    c = TestClient(create_app())
    assert c.get("/api/health").json() == {"ok": True, "db": "ok"}
    assert c.get(f"/api/runs/{run_id}").json()["success_rate"] == 1.0
    assert len(c.get("/api/runs").json()) == 1
    assert c.get(f"/api/runs/{run_id}/failures").json() == []
    assert c.get("/api/runs/nope").status_code == 404
    # same routes without the prefix (hosting may or may not strip /api)
    assert c.get(f"/runs/{run_id}").json()["id"] == run_id


def test_api_is_cacheable_but_health_is_not():
    evaluate()
    c = TestClient(create_app())
    assert "s-maxage" in c.get("/api/runs").headers["cache-control"]
    assert "cache-control" not in c.get("/api/health").headers


def test_dashboard_served_locally():
    r = TestClient(create_app()).get("/")
    assert r.status_code == 200 and "AgentGuard" in r.text


def test_dashboard_endpoint_gives_verdicts_against_experiment_baseline():
    def labelled(agent, label):
        dv, cases = load_dataset("datasets/golden_v1.jsonl")
        cases = [c for c in cases if c.id in IDS]
        cfg = get_config(agent)
        return asyncio.run(run_evaluation(lambda: build_agent(cfg), cases, dataset_version=dv, agent_version=cfg.version(), repeats=2, label=label))

    base = labelled("base", "experiment:baseline")
    bad = labelled("R03_schema_renamed_order_id", "experiment:R03")
    body = TestClient(create_app()).get("/api/dashboard").json()
    assert body["baseline_id"] == base
    by_id = {r["id"]: r for r in body["runs"]}
    assert by_id[base]["verdict"]["baseline"] is True
    assert by_id[bad]["verdict"]["passed"] is False and by_id[bad]["verdict"]["failures"]


def test_dashboard_endpoint_without_baseline_has_no_verdicts():
    evaluate()
    body = TestClient(create_app()).get("/api/dashboard").json()
    assert body["baseline_id"] is None and body["runs"][0]["verdict"] is None
