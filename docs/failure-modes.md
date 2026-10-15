# AgentGuard: Failure modes and trade-offs

| Risk | Effect | Mitigation |
| --- | --- | --- |
| Judge bias | Judge passes bad answers or fails good ones | Prefer deterministic checks; label 50 cases by hand; publish false-pass and false-fail rates |
| Non-determinism | A case flips between runs and the gate flaps | Three repeats per case; compare pass rates; thresholds set above measured noise |
| Judge cost | Evaluation becomes expensive | Small judge model; cache repeated calls; spend cap per run |
| Sensitive data in traces | Leak of secrets or personal data | Redaction in the SDK; synthetic data only in the public repo |
| Overfitting to the golden set | Agent tuned to the tests, not the task | Add mined production failures; keep a held-out slice |
| Tracing overhead | Agent slower | Export errors are swallowed and the span dropped. Spans are written synchronously when they end (`SimpleSpanProcessor`) so scorers can read them immediately; a batching exporter would be faster but needs an explicit flush |
| Timed-out attempt | Python cannot kill a thread, so the stray thread may still emit spans after the attempt was recorded as `timeout` | Attempt is scored as failed; late spans are harmless to scoring. A process-per-attempt runner would remove this |
| Latency is noisy | Same-behaviour reruns varied 244-454 ms p95 on one laptop; cross-machine comparison is meaningless | Latency threshold is loose (+100%) and CI ignores it. Gate latency only on the same hardware |
| Mock-LLM results | Regressions are programmed, so a perfect catch rate proves the machinery, not real-model behaviour | Results labelled by backend; real-model run required before quoting a headline number |
| Single-node runner | Limits scale | Documented path to queue plus workers |

## Trade-offs
- **Postgres over a trace-specific database:** simpler to run and query for this scale; revisit past millions of spans per day.
- **Git for datasets over a database:** reviewable and versioned with code, but non-engineers need a helper tool to edit.
- **Three repeats:** triples cost for much better stability.
