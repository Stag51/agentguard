# Seeded-regression results (mock backend)

- Dataset: `golden_v1@14c29d96`, repeats per case: 3
- **Regressions caught: 12 of 12**
- **Benign changes wrongly blocked: 0 of 4**

> Backend `mock`: regressions are simulated by an offline model. This validates the evaluation machinery, not real-model behaviour.

Baseline: success 1.00, tool correctness 1.00, cost/task $0.000542, p95 313 ms

| Change | Type | Blocked | Right call | Success | Tool corr. | Cost/task | p95 ms | Why |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| R01_terse_prompt | regression | yes | yes | 0.83 | 0.83 | $0.000309 | 230 | success_rate: 1.00 -> 0.83; tool_correctness: 1.00 -> 0.83; tag:multi_step: 1.00 -> 0.00 |
| R02_verbose_prompt | regression | yes | yes | 1.00 | 1.00 | $0.001327 | 300 | cost_per_task: $0.000542 -> $0.001327 (+145%) |
| R03_schema_renamed_order_id | regression | yes | yes | 0.33 | 0.33 | $0.000451 | 217 | success_rate: 1.00 -> 0.33; tool_correctness: 1.00 -> 0.33; tag:multi_step: 1.00 -> 0.00 |
| R04_schema_dropped_calc_refund | regression | yes | yes | 0.83 | 0.83 | $0.000428 | 282 | success_rate: 1.00 -> 0.83; tool_correctness: 1.00 -> 0.83; tag:multi_step: 1.00 -> 0.00 |
| R05_cheaper_model | regression | yes | yes | 0.87 | 0.73 | $0.000135 | 328 | success_rate: 1.00 -> 0.87; tool_correctness: 1.00 -> 0.73; tag:order_status: 1.00 -> 0.71 |
| R06_cheaper_model_terse | regression | yes | yes | 0.70 | 0.61 | $0.000077 | 380 | success_rate: 1.00 -> 0.70; tool_correctness: 1.00 -> 0.61; tag:multi_step: 1.00 -> 0.00 |
| R07_overeager_tools | regression | yes | yes | 0.90 | 0.90 | $0.000591 | 317 | success_rate: 1.00 -> 0.90; tool_correctness: 1.00 -> 0.90; tag:out_of_scope: 1.00 -> 0.00 |
| R08_no_refusal | regression | yes | yes | 0.90 | 1.00 | $0.000365 | 303 | success_rate: 1.00 -> 0.90; tag:out_of_scope: 1.00 -> 0.00; tag:refusal: 1.00 -> 0.00 |
| R09_slow_model | regression | yes | yes | 1.00 | 1.00 | $0.000542 | 667 | p95_latency: 313ms -> 667ms (+113%) |
| R10_schema_renamed_policy_arg | regression | yes | yes | 0.60 | 0.60 | $0.000519 | 333 | success_rate: 1.00 -> 0.60; tool_correctness: 1.00 -> 0.60; tag:multi_step: 1.00 -> 0.00 |
| R11_truncated_ids | regression | yes | yes | 0.33 | 0.33 | $0.000474 | 315 | success_rate: 1.00 -> 0.33; tool_correctness: 1.00 -> 0.33; tag:multi_step: 1.00 -> 0.00 |
| R12_cheaper_model_verbose | regression | yes | yes | 0.87 | 0.73 | $0.000331 | 775 | success_rate: 1.00 -> 0.87; tool_correctness: 1.00 -> 0.73; tag:order_status: 1.00 -> 0.71 |
| B01_polite_wording | benign | no | yes | 1.00 | 1.00 | $0.000637 | 279 | - |
| B02_equivalent_cheaper_model | benign | no | yes | 1.00 | 1.00 | $0.000433 | 454 | - |
| B03_shorter_prompt | benign | no | yes | 1.00 | 1.00 | $0.000396 | 276 | - |
| B04_identical_rerun | benign | no | yes | 1.00 | 1.00 | $0.000542 | 244 | - |
