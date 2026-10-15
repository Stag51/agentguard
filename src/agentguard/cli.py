"""Command-line interface.

    agentguard run --agent base --dataset datasets/golden_v1.jsonl
    agentguard summary <run_id>
    agentguard baseline set <run_id> --out baselines/main.json
    agentguard gate --run <run_id> --baseline baselines/main.json   (exit 1 on regression)
    agentguard compare <run_a> <run_b>
    agentguard audit-judge --judge keyword --traps datasets/judge_traps.jsonl
    agentguard mine --run <run_id> --out datasets/candidates.jsonl
    agentguard approve --candidates datasets/candidates.jsonl --id <id> --dataset datasets/golden_v1.jsonl
    agentguard experiment --backend mock
    agentguard serve

Exit codes: 0 ok / gate passed, 1 gate failed, 2 usage or input error.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import asdict

from sqlalchemy import select

from . import config, db
from .gate.gate import Thresholds, compare, load_baseline, save_baseline
from .metrics import summarize_run


def _print_summary(s: dict) -> None:
    print(f"run {s['id']}  {s['agent_version']}  [{s['status']}]")
    print(f"  dataset          {s['dataset_version']}  ({s['n_cases']} cases x {s['repeats']} repeats)")
    print(f"  success_rate     {s['success_rate']:.3f}")
    print(f"  tool_correctness {s['tool_correctness']:.3f}")
    print(f"  cost_per_task    ${s['cost_per_task']:.6f}")
    print(f"  p95_latency      {s['p95_latency_ms']:.0f} ms")
    print(f"  error_rate       {s['error_rate']:.3f}")
    print("  by tag:", ", ".join(f"{t}={v:.2f}" for t, v in s["success_by_tag"].items()))


def _thresholds(a: argparse.Namespace) -> Thresholds:
    return Thresholds(
        max_success_drop=a.max_success_drop, max_cost_rise=a.max_cost_rise, max_latency_rise=a.max_latency_rise,
        ignore=set(filter(None, (a.ignore or "").split(","))),
    )


def _add_threshold_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--max-success-drop", type=float, default=Thresholds.max_success_drop)
    p.add_argument("--max-cost-rise", type=float, default=Thresholds.max_cost_rise)
    p.add_argument("--max-latency-rise", type=float, default=Thresholds.max_latency_rise)
    p.add_argument("--ignore", default="", help="comma list of checks to skip: success,tools,tags,cost,latency,errors")


def cmd_run(a: argparse.Namespace) -> int:
    from demo_agent.agent import build_agent
    from demo_agent.variants import get_config

    from .datasets.loader import load_dataset
    from .runner.runner import run_evaluation
    from .scorers.llm_judge import make_judge

    dv, cases = load_dataset(a.dataset)
    cfg = get_config(a.agent, a.llm)
    build_agent(cfg)  # fail fast (e.g. missing API key) instead of recording a run of errors
    make_judge(a.judge)
    run_id = asyncio.run(run_evaluation(
        lambda: build_agent(cfg), cases, dataset_version=dv, agent_version=cfg.version(), config=asdict(cfg),
        repeats=a.repeats, concurrency=a.concurrency, timeout_s=a.timeout, budget_usd=a.budget, label=a.label, judge=make_judge(a.judge),
    ))
    _print_summary(summarize_run(run_id))
    return 0


def cmd_summary(a: argparse.Namespace) -> int:
    _print_summary(summarize_run(a.run))
    return 0


def cmd_runs(a: argparse.Namespace) -> int:
    with db.get_session() as s:
        ids = s.scalars(select(db.Run.id).order_by(db.Run.started_at.desc()).limit(a.limit)).all()
    for i in ids:
        x = summarize_run(i)
        print(f"{i}  {x['status']:9s} success={x['success_rate']:.2f}  {x['agent_version']}  {x['label'] or ''}")
    return 0


def cmd_baseline(a: argparse.Namespace) -> int:
    save_baseline(summarize_run(a.run), a.out)
    print(f"baseline saved to {a.out}")
    return 0


def cmd_gate(a: argparse.Namespace) -> int:
    res = compare(summarize_run(a.run), load_baseline(a.baseline), _thresholds(a))
    print(res.report())
    return 0 if res.passed else 1


def cmd_compare(a: argparse.Namespace) -> int:
    res = compare(summarize_run(a.new), summarize_run(a.old), _thresholds(a))
    print(res.report())
    print(json.dumps(res.deltas, indent=2))
    return 0 if res.passed else 1


def cmd_audit(a: argparse.Namespace) -> int:
    from .judge_audit.audit import audit_judge, load_traps
    from .scorers.llm_judge import make_judge

    judge = make_judge(a.judge)
    if judge is None:
        print("choose --judge keyword, gemini or claude", file=sys.stderr)
        return 2
    r = audit_judge(judge, load_traps(a.traps))
    print(f"judge {r['judge']}  n={r['n']}  agreement={r['agreement']:.2f}  false_pass={r['false_pass_rate']:.2f}  false_fail={r['false_fail_rate']:.2f}")
    for w in r["wrong"]:
        print(f"  wrong: {w['id']} ({w['error']}) {w['reason']}")
    if r["n"] < 50:
        print(f"  note: only {r['n']} traps; label 50 by hand before quoting these rates")
    return 0


def cmd_mine(a: argparse.Namespace) -> int:
    from .mining.mine import mine_failures

    c = mine_failures(a.run, a.out)
    print(f"{len(c)} candidate(s) written to {a.out}; fill in expectations, then run `approve`")
    return 0


def cmd_approve(a: argparse.Namespace) -> int:
    from .mining.mine import approve

    approve(a.candidates, a.id, a.dataset)
    print(f"approved {a.id} -> {a.dataset}")
    return 0


def cmd_experiment(a: argparse.Namespace) -> int:
    from .experiment import main as run_experiment

    r = run_experiment(a.dataset, a.backend, a.repeats, a.out, set(filter(None, (a.ignore or "").split(","))), a.concurrency)
    print(f"\ncaught {r['caught']} of {r['regressions']} regressions; wrongly blocked {r['false_blocks']} of {r['benign']} benign changes")
    return 0


def cmd_serve(a: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run("agentguard.api.app:app", host=a.host, port=a.port)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="agentguard", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    r = sub.add_parser("run", help="run an agent version against a dataset")
    r.add_argument("--agent", default="base")
    r.add_argument("--dataset", default="datasets/golden_v1.jsonl")
    r.add_argument("--llm", choices=["mock", "gemini", "claude"], default="mock")
    r.add_argument("--judge", choices=["none", "keyword", "gemini", "claude"], default="none")
    r.add_argument("--repeats", type=int, default=3)
    r.add_argument("--concurrency", type=int, default=8)
    r.add_argument("--timeout", type=float, default=30.0)
    r.add_argument("--budget", type=float, default=None, help="stop scheduling after this many USD")
    r.add_argument("--label", default=None)
    r.set_defaults(fn=cmd_run)

    s = sub.add_parser("summary"); s.add_argument("run"); s.set_defaults(fn=cmd_summary)
    ls = sub.add_parser("runs"); ls.add_argument("--limit", type=int, default=20); ls.set_defaults(fn=cmd_runs)

    b = sub.add_parser("baseline", help="save a run's summary as the baseline file")
    b.add_argument("action", choices=["set"]); b.add_argument("run"); b.add_argument("--out", default="baselines/main.json"); b.set_defaults(fn=cmd_baseline)

    g = sub.add_parser("gate", help="exit 1 if the run regressed vs the baseline file")
    g.add_argument("--run", required=True); g.add_argument("--baseline", default="baselines/main.json"); _add_threshold_args(g); g.set_defaults(fn=cmd_gate)

    c = sub.add_parser("compare", help="compare two runs"); c.add_argument("old"); c.add_argument("new"); _add_threshold_args(c); c.set_defaults(fn=cmd_compare)

    au = sub.add_parser("audit-judge"); au.add_argument("--judge", default="keyword"); au.add_argument("--traps", default="datasets/judge_traps.jsonl"); au.set_defaults(fn=cmd_audit)

    m = sub.add_parser("mine"); m.add_argument("--run", required=True); m.add_argument("--out", default="datasets/candidates.jsonl"); m.set_defaults(fn=cmd_mine)
    ap = sub.add_parser("approve"); ap.add_argument("--candidates", default="datasets/candidates.jsonl"); ap.add_argument("--id", required=True); ap.add_argument("--dataset", default="datasets/golden_v1.jsonl"); ap.set_defaults(fn=cmd_approve)

    e = sub.add_parser("experiment", help="seed regressions and measure how many the gate catches")
    e.add_argument("--backend", choices=["mock", "gemini", "claude"], default="mock"); e.add_argument("--dataset", default="datasets/golden_v1.jsonl")
    e.add_argument("--repeats", type=int, default=3); e.add_argument("--out", default="docs/results"); e.add_argument("--ignore", default=""); e.add_argument("--concurrency", type=int, default=8); e.set_defaults(fn=cmd_experiment)

    sv = sub.add_parser("serve"); sv.add_argument("--host", default="127.0.0.1"); sv.add_argument("--port", type=int, default=8000); sv.set_defaults(fn=cmd_serve)
    return p


def main(argv: list[str] | None = None) -> None:
    config.load_env()  # picks up GEMINI_API_KEY etc. from ./.env
    args = build_parser().parse_args(argv)
    try:
        code = args.fn(args)
    except (KeyError, ValueError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        code = 2
    sys.exit(code)


if __name__ == "__main__":
    main()
