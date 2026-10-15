# AgentGuard: Requirements

## Problem
Teams ship LLM agents that pass a few manual tries, then regress in production: wrong tool arguments, a prompt edit that silently lowers quality, a cheaper model that costs accuracy, or runaway spend. Observability shows what an agent did. It does not show whether the agent did the task well. AgentGuard closes that gap by treating agent quality like a test suite.

## Users
| User | Need |
| --- | --- |
| Agent developer | Know before merging whether a change made the agent better or worse |
| Reviewer / tech lead | A pass/fail signal on the pull request with evidence |
| Team over time | Trends in quality, cost and latency per release |

## Functional requirements
| ID | Requirement |
| --- | --- |
| F1 | Instrument an agent (LangGraph first) so every LLM call, tool call and retrieval emits a span with tokens, cost and latency. |
| F2 | Store traces durably so a run can be inspected and replayed later. |
| F3 | Keep golden test cases as versioned files in Git (input, expected tool calls, required facts, tags). |
| F4 | Run every case against a chosen agent version, in parallel, with a per-case timeout. |
| F5 | Run each case 3 times and report a pass rate, because LLM output is non-deterministic. |
| F6 | Score with deterministic checks first (schema, tool name, tool arguments, required facts). |
| F7 | Use an LLM judge only for open-ended answers, and audit the judge against a labelled trap set. |
| F8 | Compare a run with a stored baseline and fail CI when a metric drops past a threshold. |
| F9 | Expose run history (per-tag scores, cost, p95 latency) through a read-only API and a static dashboard that can be hosted on Vercel. |
| F10 | Turn flagged production traces into candidate golden cases after human review. |

## Non-functional requirements
| ID | Requirement | Target |
| --- | --- | --- |
| N1 | Reproducibility | Pinned versions, recorded dataset and agent version per run |
| N2 | Speed | 30 cases x 3 repeats finish in about 5 minutes |
| N3 | Cost control | A configurable spend cap per run; judge calls cached |
| N4 | SDK overhead | Tracing adds negligible latency; it never crashes the agent |
| N5 | Safety | Secrets and personal data are redacted before storage |
| N6 | Local-first and deployable | Runs on a laptop with SQLite; the read side deploys to Vercel against hosted Postgres |
| N7 | Honest reporting | Every published number comes from a recorded run |

## Out of scope (and the scaling path)
- Multi-tenant SaaS, user accounts and billing.
- A distributed worker fleet. The runner uses asyncio and a job queue interface, so workers can be added later.
- Polished UI. The dashboard shows trends only.

## Success criteria
1. Seed 10 to 15 known regressions into the demo agent. Report how many the gate catches and how many good changes it wrongly blocks.
2. The judge's agreement with 50 hand-labelled cases is published, including false-pass and false-fail rates.
3. A new reader can run the project in five minutes.
