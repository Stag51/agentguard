# AgentGuard: Scoring and metrics

## Scoring order
1. **Deterministic checks** (cheap, repeatable): output schema valid, correct tool called, correct tool arguments, required facts present.
2. **LLM judge** (only when the answer is open-ended): scored against a rubric by a small model, with caching.
3. **Judge audit**: the judge is run on cases with known verdicts and its false-pass and false-fail rates are reported.

## Metrics
| Metric | Definition | Why it matters |
| --- | --- | --- |
| Task success rate | Cases passed / cases run, per tag. A case passes if at least 2 of 3 repeats pass. | The headline quality number |
| Tool-call correctness | Right tool and right arguments / tool calls expected | Catches schema and prompt regressions |
| Groundedness | Share of answer claims supported by retrieved text (RAG agents) | Catches hallucination |
| Cost per task | Sum of step cost per case, averaged | Catches silent cost growth |
| p95 latency | 95th percentile of end-to-end case time | Catches slowdowns |
| Judge agreement | Judge verdict equals human label, over 50 trap cases | Shows whether the judge can be trusted |

## Gate rule
A change is blocked when any gated metric moves past its threshold versus the baseline, when the run is incomplete, or when the dataset version differs from the baseline's.

| Check | Default threshold |
| --- | --- |
| success_rate | drop of more than 0.05 (absolute) |
| tool_correctness | drop of more than 0.05 |
| any single tag | drop of more than 0.20 (small groups are noisy) |
| cost_per_task | rise of more than 30% |
| p95 latency | rise of more than 100% (noisy; same machine only) |
| error_rate | rise of more than 0.05 |

The success/tool thresholds are a starting choice, informed by the identical-rerun control in the experiment (no difference observed on the deterministic mock). With a real model, measure the spread of the same agent run repeatedly and set thresholds above it.

## Honest reporting
- Report seeded regressions caught, and good changes wrongly blocked.
- Report noise: the spread of the same agent run several times.
