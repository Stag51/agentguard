# AgentGuard

Evaluation and observability for LLM agents. Observability shows what an agent did; AgentGuard shows whether it did the task well, and fails the pull request when quality drops.

**Who has this problem:** any team shipping an agent. A prompt edit, a changed tool schema or a cheaper model can quietly make the agent worse, and traces alone do not say so.

## How it works
Trace the agent (OpenTelemetry spans) -> replay versioned golden cases, 3 repeats each -> score with exact checks first and an audited LLM judge for open-ended answers -> compare with a baseline -> gate CI.

```mermaid
flowchart LR
    A[Agent] -->|spans| B[(Trace store)]
    D[Golden dataset in Git] --> E[Eval runner] --> A
    B --> F[Scorers] --> G[Regression gate] --> CI[Pull request check]
    H[(Baseline JSON in Git)] --> G
```

Full design: [architecture](docs/architecture.md) | [requirements](docs/requirements.md) | [data model](docs/data-model.md) | [scoring](docs/scoring-and-metrics.md) | [failure modes](docs/failure-modes.md) | [decisions](docs/adr/)

## Results (measured)

Seeded-regression experiment: 12 known-bad changes and 4 harmless ones are run through the gate. Full table: [docs/results/seeded-regressions-mock.md](docs/results/seeded-regressions-mock.md).

| Metric | Result |
| --- | --- |
| Seeded regressions caught | **12 of 12** |
| Harmless changes wrongly blocked | **0 of 4** |
| Dataset / repeats | 30 golden cases x 3 repeats |
| Backend | offline `mock` model |

**Read this before quoting the numbers.** These results come from a *simulated* model: the regressions are behaviours I programmed into the mock, so catching them shows the evaluation machinery works end to end. It is not evidence about how real models regress. The real figure comes from `--llm gemini` (not yet run; needs your API key). The sample is also small (16 variants, 30 cases), and the regressions were written by me, so a catch rate of 12/12 should be read as "the gate does what it should on cases it was designed to see".

Other measured facts:
- p95 latency is noisy: identical-behaviour reruns ranged from 244 to 454 ms. Slow-model regression R09 was caught on latency alone at +113%, barely above the 100% threshold. Latency gating is only reliable on the same machine; CI ignores it.
- The offline `keyword` judge, audited on 12 hand-written traps, agreed with the labels 75% of the time and passed 50% of the bad answers (it cannot detect wrong facts). That is the reason the judge is audited and why exact checks come first. A real judge has not been audited yet, and 12 traps is too few to quote a rate; the target is 50.

## What failed and how I fixed it
- The first draft of the tool-call scorer would have let a case that expects *no* tool calls pass when the agent called an unlisted tool. Found in review before the first run; the rule is now "no expected calls means no calls at all", with a unit test.
- Latency turned out to be a poor gating signal: identical agents differed by up to 80% in p95 between runs. Thresholds were loosened and CI ignores latency (see Results).
- The offline keyword judge missed every factually wrong answer in the trap set. It stays only as a plumbing stand-in; the audit exists to expose exactly this.

## Run it (5 minutes, no API key)
```bash
uv sync --extra agent --extra dev
uv run pytest -q                                   # 30 tests
uv run agentguard run --agent base                 # evaluate the reference agent
uv run agentguard run --agent R03_schema_renamed_order_id   # evaluate a broken version
uv run agentguard gate --run <run_id> --ignore latency      # exit code 1 = regression
uv run agentguard experiment                       # the full seeded-regression table
uv run agentguard audit-judge                      # judge error rates on the trap set
uv run agentguard serve                            # dashboard at :8000, API docs at :8000/docs
# open http://127.0.0.1:8000 for the dashboard
```
Agent names are in `src/demo_agent/variants.py`.

### With a real model (Gemini)
```powershell
$env:GEMINI_API_KEY = "your-key"          # PowerShell;  bash: export GEMINI_API_KEY=...
uv run agentguard run --llm gemini --repeats 1 --concurrency 2        # smoke test, ~75 model calls
uv run agentguard run --llm gemini --judge gemini --concurrency 3     # full run + LLM judge on open-ended cases
uv run agentguard baseline set <run_id> --out baselines/gemini.json   # YOUR baseline for this model
uv run agentguard experiment --backend gemini --repeats 2 --concurrency 3 --ignore latency
uv run agentguard audit-judge --judge gemini                          # needs your 50 hand-labelled traps
```
Models default to `gemini-2.5-flash` (agent) and `gemini-2.5-flash-lite` (cheap tier and judge). If the API reports a model as not found, set `AGENTGUARD_GEMINI_BASE` / `AGENTGUARD_GEMINI_CHEAP` to one your key supports. Prices in `src/demo_agent/llm.py` are illustrative: check Google's pricing page before quoting any cost.

Call volume: one run is about 90 attempts x 2-3 model calls (roughly 250). The full experiment is 17 runs, so thousands of calls. Free-tier keys are rate limited; calls retry on 429 with backoff, but keep `--concurrency` low and start with the smoke test. Use `--budget <usd>` on `run` to cap spend.

Anthropic is also supported (`--llm claude`, `ANTHROPIC_API_KEY`). `baselines/main.json` was made with the mock model and is what CI uses; a real model needs its own baseline file passed with `--baseline`.

Postgres instead of SQLite: set `DATABASE_URL` (or `AGENTGUARD_DB`) to any Postgres URL. Local: `docker compose up -d` then `postgresql://agentguard:agentguard@localhost:5432/agentguard`. Hosted (Neon, Supabase, Vercel Postgres): paste the connection string they give you; `postgres://` and `postgresql://` forms are both accepted.

## Deploy the dashboard to Vercel
Evaluations run on your machine or in GitHub Actions; Vercel only *reads* the results. Design and reasons: [ADR 0006](docs/adr/0006-serverless-deployment.md).

1. Create a hosted Postgres (Neon free tier works). Copy its connection string.
2. Put it in `.env` as `DATABASE_URL=...` and run an evaluation. Results now live in the hosted database:
   `uv run agentguard run --llm gemini --judge gemini --concurrency 3`
3. Push the repo to GitHub, import it in Vercel, and add the environment variable `DATABASE_URL` (same string).
4. Deploy. `public/index.html` is the dashboard; `api/index.py` serves `/api/*`. Check `https://<your-app>.vercel.app/api/health` returns `{"ok": true, "db": "ok"}`.
5. To refresh results later: run the CLI again, or trigger the **publish-results** GitHub Action (needs repository secrets `DATABASE_URL` and `GEMINI_API_KEY`). The dashboard picks them up within a minute (CDN cache).

Status: the API and dashboard run locally and are covered by tests (including a slim-install import test). The actual Vercel deployment and the hosted-Postgres path have **not** been run yet.

The dashboard and API are read-only and public if you deploy them: they show run metrics and failure evidence (model answers to synthetic questions). Do not point a public deployment at a database holding private data.

## What has and has not been verified
| Verified | Not yet verified |
| --- | --- |
| 30 automated tests pass; full pipeline on SQLite; CLI exit codes (0 pass, 1 regression, 2 bad input) | Postgres path (Docker was not running when built) |
| Seeded-regression experiment on the mock backend | live Gemini API (`--llm gemini`) |
| | The Vercel deployment itself and the GitHub Actions (written, not executed); static dashboard loads locally |
| | Judge audit on 50 hand-labelled traps (12 exist) |

## Project layout
`src/agentguard/` (sdk, collector, datasets, runner, scorers, judge_audit, gate, mining, api, cli) | `src/demo_agent/` (public LangGraph demo agent, synthetic data) | `datasets/` (golden cases, judge traps) | `baselines/main.json` | `docs/`

## Data note
The demo agent uses synthetic data only. No employer or customer data or code is included.
