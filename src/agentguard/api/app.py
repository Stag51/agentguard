"""Run history API (read-only): runs, per-case results, failures.

Local:   agentguard serve   ->  http://127.0.0.1:8000  (dashboard at /, docs at /docs)
Vercel:  api/index.py exposes `app`; public/index.html is served as static files.

WHY read-only: runs are created by the CLI / CI, never by the web. A public
deployment therefore has no write surface to protect (documented non-goal: auth).

WHY the Cache-Control header: serverless functions pay a cold start and a database
round trip per request. Letting the host's CDN cache GET responses for a minute
keeps the dashboard fast and the database quiet; stale-while-revalidate hides the
refresh latency.

WHY routes under both /api and /: Vercel may forward either the original path or
the rewritten one; serving both makes the deployment independent of that detail.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select, text

from .. import db
from ..metrics import case_results, summarize_run

CACHE_HEADER = "public, s-maxage=60, stale-while-revalidate=300"

router = APIRouter()


@router.get("/health")
def health() -> dict:
    """Liveness plus a database check, so a misconfigured deploy is obvious."""
    try:
        with db.get_session() as s:
            s.execute(text("SELECT 1"))
        return {"ok": True, "db": "ok"}
    except Exception as exc:  # report, don't crash: this is the endpoint you debug with
        return {"ok": False, "db": f"{type(exc).__name__}"}


@router.get("/runs")
def runs(limit: int = 30) -> list[dict]:
    """Most recent runs with headline metrics, newest first (capped at 100)."""
    limit = max(1, min(limit, 100))
    with db.get_session() as s:
        ids = s.scalars(select(db.Run.id).order_by(db.Run.started_at.desc()).limit(limit)).all()
    return [summarize_run(i) for i in ids]


@router.get("/runs/{run_id}")
def run(run_id: str) -> dict:
    try:
        return summarize_run(run_id)
    except KeyError:
        raise HTTPException(404, f"run '{run_id}' not found")


@router.get("/runs/{run_id}/cases")
def cases(run_id: str) -> dict:
    try:
        return case_results(run_id)
    except KeyError:
        raise HTTPException(404, f"run '{run_id}' not found")


@router.get("/runs/{run_id}/failures")
def failures(run_id: str) -> list[dict]:
    """Failing scores with their evidence: the 'why' behind each failure."""
    with db.get_session() as s:
        if s.get(db.Run, run_id) is None:
            raise HTTPException(404, f"run '{run_id}' not found")
        rows = s.scalars(select(db.Score).where(db.Score.run_id == run_id, db.Score.value < 1.0)).all()
        return [{"case_id": r.case_id, "repeat": r.repeat, "metric": r.metric, "evidence": r.evidence} for r in rows]


def create_app() -> FastAPI:
    app = FastAPI(title="AgentGuard", version="0.1.0")
    app.include_router(router, prefix="/api")
    app.include_router(router, include_in_schema=False)  # same routes without the prefix

    @app.middleware("http")
    async def cache(request: Request, call_next):
        response = await call_next(request)
        if request.method == "GET" and response.status_code == 200 and "/health" not in request.url.path:
            response.headers.setdefault("Cache-Control", CACHE_HEADER)
        return response

    # Local convenience: serve the dashboard at "/". On Vercel the CDN serves public/ itself.
    index = Path(__file__).resolve().parents[3] / "public" / "index.html"
    if index.is_file():

        @app.get("/", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(index)

    return app


app = create_app()
