"""Regression gate: compare a candidate run with a baseline and decide pass/fail.

The baseline is a small JSON file kept in Git (baselines/main.json) holding a run
summary. WHY in Git: changing the bar is a reviewed, visible change, and CI on a
fresh machine needs no database history.

Rules (defaults; set from measured noise, see docs/scoring-and-metrics.md):
  success_rate      may not drop more than 0.05 (absolute)
  tool_correctness  may not drop more than 0.05 (absolute)
  tag success       no tag may drop more than 0.20 (absolute)   <- small groups are noisy
  cost_per_task     may not rise more than 30% (relative)
  p95_latency_ms    may not rise more than 100% (relative)
  error_rate        may not rise more than 0.05 (absolute)
  run status        must be `complete`; partial/failed runs never pass
Individual checks can be switched off (e.g. latency in CI, where the machine
differs from the one that produced the baseline).
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Thresholds:
    max_success_drop: float = 0.05
    max_tool_drop: float = 0.05
    max_tag_drop: float = 0.20
    max_cost_rise: float = 0.30
    max_latency_rise: float = 1.00
    max_error_rise: float = 0.05
    ignore: set[str] = field(default_factory=set)  # names: success, tools, tags, cost, latency, errors


@dataclass
class Failure:
    check: str
    detail: str


@dataclass
class GateResult:
    passed: bool
    failures: list[Failure]
    deltas: dict

    def report(self) -> str:
        lines = ["GATE: " + ("PASS" if self.passed else "FAIL")]
        lines += [f"  - {f.check}: {f.detail}" for f in self.failures]
        return "\n".join(lines)


def _rel(new: float, old: float) -> float:
    if old <= 0:
        return 0.0 if new <= 0 else float("inf")
    return (new - old) / old


def compare(candidate: dict, baseline: dict, t: Thresholds | None = None) -> GateResult:
    """Compare two run summaries (from metrics.summarize_run)."""
    t = t or Thresholds()
    fails: list[Failure] = []
    deltas = {
        "success_rate": candidate["success_rate"] - baseline["success_rate"],
        "tool_correctness": candidate["tool_correctness"] - baseline["tool_correctness"],
        "cost_per_task_rel": _rel(candidate["cost_per_task"], baseline["cost_per_task"]),
        "p95_latency_rel": _rel(candidate["p95_latency_ms"], baseline["p95_latency_ms"]),
        "error_rate": candidate["error_rate"] - baseline["error_rate"],
    }
    if candidate["status"] != "complete":
        fails.append(Failure("status", f"run is '{candidate['status']}', not complete"))
    if candidate["dataset_version"] != baseline["dataset_version"]:
        fails.append(Failure("dataset", f"dataset differs: {candidate['dataset_version']} vs baseline {baseline['dataset_version']}"))
    if "success" not in t.ignore and deltas["success_rate"] < -t.max_success_drop:
        fails.append(Failure("success_rate", f"{baseline['success_rate']:.2f} -> {candidate['success_rate']:.2f}"))
    if "tools" not in t.ignore and deltas["tool_correctness"] < -t.max_tool_drop:
        fails.append(Failure("tool_correctness", f"{baseline['tool_correctness']:.2f} -> {candidate['tool_correctness']:.2f}"))
    if "tags" not in t.ignore:
        for tag, old in baseline["success_by_tag"].items():
            new = candidate["success_by_tag"].get(tag, 0.0)
            if new - old < -t.max_tag_drop:
                fails.append(Failure(f"tag:{tag}", f"{old:.2f} -> {new:.2f}"))
    if "cost" not in t.ignore and deltas["cost_per_task_rel"] > t.max_cost_rise:
        fails.append(Failure("cost_per_task", f"${baseline['cost_per_task']:.6f} -> ${candidate['cost_per_task']:.6f} ({deltas['cost_per_task_rel']:+.0%})"))
    if "latency" not in t.ignore and deltas["p95_latency_rel"] > t.max_latency_rise:
        fails.append(Failure("p95_latency", f"{baseline['p95_latency_ms']:.0f}ms -> {candidate['p95_latency_ms']:.0f}ms ({deltas['p95_latency_rel']:+.0%})"))
    if "errors" not in t.ignore and deltas["error_rate"] > t.max_error_rise:
        fails.append(Failure("error_rate", f"{baseline['error_rate']:.2f} -> {candidate['error_rate']:.2f}"))
    return GateResult(not fails, fails, deltas)


def save_baseline(summary: dict, path: str | Path) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")


def load_baseline(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))
