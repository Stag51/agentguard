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

from dataclasses import asdict
from pathlib import Path

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import select, text

from .. import db
from ..gate.gate import Thresholds, compare
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


@router.get("/dashboard")
def dashboard_data(limit: int = 60, baseline: str | None = None) -> dict:
    """Everything the dashboard needs in one call: runs, a baseline, and gate verdicts.

    Each run is compared with the baseline using the gate's default thresholds, so the
    page shows exactly what CI would decide. Baseline: the `baseline` query param, else
    the newest run labelled "experiment:baseline", else none (no verdicts).

    Only complete runs are shown, and for runs labelled "experiment:*" only the newest
    of each label (re-running the experiment replaces, not piles up).
    """
    limit = max(1, min(limit, 100))
    with db.get_session() as s:
        ids = s.scalars(select(db.Run.id).where(db.Run.status == "complete").order_by(db.Run.started_at.desc()).limit(limit)).all()
    summaries, seen = [], set()
    for i in ids:  # newest first
        sm = summarize_run(i)
        label = sm.get("label") or ""
        if label.startswith("experiment:"):
            if label in seen:
                continue
            seen.add(label)
        summaries.append(sm)
    base = next((x for x in summaries if x["id"] == baseline), None) if baseline else next((x for x in summaries if x.get("label") == "experiment:baseline"), None)
    for sm in summaries:
        if base is None:
            sm["verdict"] = None
        elif sm["id"] == base["id"]:
            sm["verdict"] = {"passed": True, "baseline": True, "failures": [], "deltas": {}}
        else:
            res = compare(sm, base)
            sm["verdict"] = {"passed": res.passed, "baseline": False, "failures": [{"check": f.check, "detail": f.detail} for f in res.failures], "deltas": res.deltas}
    t = Thresholds()
    return {
        "baseline_id": base["id"] if base else None,
        "thresholds": {k: v for k, v in asdict(t).items() if k != "ignore"},
        "runs": summaries,
    }


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
    # WHY open CORS: the API is read-only and public by design, and this lets the static
    # dashboard be opened from another origin (a dev server, a different host) during development.
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET"])
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
