"""Seeded-regression experiment: does the gate catch known-bad changes?

Procedure:
  1. Run the reference agent (`base`) -> this is the baseline.
  2. Run each seeded regression (should be blocked) and each benign change
     (should NOT be blocked).
  3. Apply the gate to each and tabulate:
       caught         regressions blocked / regressions seeded
       false blocks   benign changes blocked / benign changes tried

HONESTY: with `--llm mock` the regressions are *simulated* by the offline mock
model, so this validates the evaluation machinery, not real-model behaviour. The
results file records which backend produced it.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import asdict
from pathlib import Path

from demo_agent.agent import build_agent
from demo_agent.variants import BENIGN, REGRESSIONS, get_config

from .datasets.loader import load_dataset
from .gate.gate import Thresholds, compare
from .metrics import summarize_run
from .runner.runner import run_evaluation


async def _run(cfg, cases, dv, repeats, label, concurrency=8):
    return await run_evaluation(
        lambda: build_agent(cfg), cases, dataset_version=dv, agent_version=cfg.version(), config=asdict(cfg),
        repeats=repeats, concurrency=concurrency, label=label,
    )


async def run_experiment(dataset: str, backend: str, repeats: int, thresholds: Thresholds, out_dir: str | Path, concurrency: int = 8) -> dict:
    dv, cases = load_dataset(dataset)
    base_cfg = get_config("base", backend)
    build_agent(base_cfg)  # fail fast on a missing API key
    base_id = await _run(base_cfg, cases, dv, repeats, "experiment:baseline", concurrency)
    baseline = summarize_run(base_id)
    rows = []
    for group, expect_block in (("regression", True), ("benign", False)):
        for name in (REGRESSIONS if expect_block else BENIGN):
            cfg = get_config(name, backend)
            rid = await _run(cfg, cases, dv, repeats, f"experiment:{name}", concurrency)
            summ = summarize_run(rid)
            res = compare(summ, baseline, thresholds)
            rows.append({
                "name": name, "group": group, "blocked": not res.passed, "correct": (not res.passed) == expect_block,
                "success_rate": summ["success_rate"], "tool_correctness": summ["tool_correctness"],
                "cost_per_task": summ["cost_per_task"], "p95_latency_ms": summ["p95_latency_ms"],
                "reasons": [f"{f.check}: {f.detail}" for f in res.failures], "run_id": rid,
            })
            print(f"{name:34s} blocked={not res.passed!s:5s} {'OK ' if rows[-1]['correct'] else 'MISS'}")
    regs = [r for r in rows if r["group"] == "regression"]
    bens = [r for r in rows if r["group"] == "benign"]
    result = {
        "backend": backend, "repeats": repeats, "dataset": dv, "baseline_run": base_id,
        "baseline": {k: baseline[k] for k in ("success_rate", "tool_correctness", "cost_per_task", "p95_latency_ms")},
        "thresholds": {k: (sorted(v) if isinstance(v, set) else v) for k, v in asdict(thresholds).items()},
        "caught": sum(r["blocked"] for r in regs), "regressions": len(regs),
        "false_blocks": sum(r["blocked"] for r in bens), "benign": len(bens), "rows": rows,
    }
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / f"seeded-regressions-{backend}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    (out / f"seeded-regressions-{backend}.md").write_text(_markdown(result), encoding="utf-8")
    return result


def _markdown(r: dict) -> str:
    lines = [
        f"# Seeded-regression results ({r['backend']} backend)",
        "",
        f"- Dataset: `{r['dataset']}`, repeats per case: {r['repeats']}",
        f"- **Regressions caught: {r['caught']} of {r['regressions']}**",
        f"- **Benign changes wrongly blocked: {r['false_blocks']} of {r['benign']}**",
        "",
    ]
    if r["backend"] == "mock":
        lines += ["> Backend `mock`: regressions are simulated by an offline model. This validates the evaluation machinery, not real-model behaviour.", ""]
    b = r["baseline"]
    lines += [
        f"Baseline: success {b['success_rate']:.2f}, tool correctness {b['tool_correctness']:.2f}, cost/task ${b['cost_per_task']:.6f}, p95 {b['p95_latency_ms']:.0f} ms",
        "",
        "| Change | Type | Blocked | Right call | Success | Tool corr. | Cost/task | p95 ms | Why |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for x in r["rows"]:
        why = "; ".join(x["reasons"][:3]) or "-"
        lines.append(f"| {x['name']} | {x['group']} | {'yes' if x['blocked'] else 'no'} | {'yes' if x['correct'] else '**NO**'} | {x['success_rate']:.2f} | {x['tool_correctness']:.2f} | ${x['cost_per_task']:.6f} | {x['p95_latency_ms']:.0f} | {why} |")
    return "\n".join(lines) + "\n"


def main(dataset: str, backend: str, repeats: int, out_dir: str, ignore: set[str], concurrency: int = 8) -> dict:
    return asyncio.run(run_experiment(dataset, backend, repeats, Thresholds(ignore=ignore), out_dir, concurrency))
