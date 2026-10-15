# ADR 0006: Split into a batch evaluator and a read-only serverless web side

**Status:** accepted

**Context.** The project should be viewable at a public URL on Vercel. Vercel runs short-lived serverless functions: limited execution time, no persistent disk, no background processes, and a size limit on the deployed bundle. An evaluation (hundreds of model calls, minutes long, writes to a database) fits none of those limits. The first version also assumed a local SQLite file, local payload files and a Streamlit server, none of which exist on Vercel.

**Decision.**
1. Evaluation stays a batch job run from a laptop or GitHub Actions. It writes to a hosted Postgres.
2. The Vercel side is read-only: a FastAPI function (`api/index.py`) plus a static dashboard (`public/index.html`, no build step, no framework).
3. Everything the function needs lives in the database. Trace payloads moved from files to a content-addressed `payload` table.
4. Core dependencies are only what the web side imports (SQLAlchemy, psycopg, FastAPI, pydantic). The CLI, tracing, LangGraph and model SDKs are the optional `agent` extra, keeping the function bundle small and cold starts short.
5. Serverless-specific database settings: connection strings from any host are normalised, no connection pooling inside functions (`NullPool`; use the provider's pooler), no prepared statements (poolers break them), and no table creation on cold start.
6. API responses carry `Cache-Control: s-maxage=60, stale-while-revalidate`, so the CDN absorbs most traffic.

**Consequences.**
- A reviewer can open the dashboard without running anything; results are only as fresh as the last evaluation, by design.
- The public API exposes run metrics and failure evidence. That is acceptable only because the demo data is synthetic; a deployment over private data would need authentication, which is a documented non-goal.
- Streamlit was removed; the static page is simpler and deployable anywhere, at the cost of hand-written charts.
- The Vercel deployment and the hosted-Postgres path are untested against the real services as of this ADR; the local API, the dashboard and a simulated slim-install import are tested.
- Alternative considered: running evaluations from a Vercel function or cron. Rejected: time limits and cost make it fragile for jobs of this size.
