"""Database models and session handling.

Tables follow docs/data-model.md: Run, Case, Attempt, Step, Score.

WHY an Attempt table (added to the original Run/Step/Case/Score model): the
runner needs one row per (case, repeat) holding the final answer, status and
wall-clock latency. Steps are the inside of an attempt; Scores are judgements
about it. Gate metrics (p95 latency, cost per task) read from here.

Does NOT contain business logic; see runner/, scorers/ and gate/.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
    event,
)
from sqlalchemy.pool import NullPool
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker

from . import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Run(Base):
    """One evaluation of one agent version against one dataset version."""

    __tablename__ = "run"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    label: Mapped[str | None] = mapped_column(String(120), nullable=True)
    agent_version: Mapped[str] = mapped_column(String(120))
    dataset_version: Mapped[str] = mapped_column(String(120))
    config: Mapped[dict] = mapped_column(JSON, default=dict)
    repeats: Mapped[int] = mapped_column(Integer, default=3)
    # running | complete | partial | failed.  The gate refuses non-complete runs.
    status: Mapped[str] = mapped_column(String(16), default="running")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Case(Base):
    """Copy of a golden case, so scores can be joined to tags in SQL.

    The JSONL file in Git stays the source of truth.
    """

    __tablename__ = "case"
    dataset_version: Mapped[str] = mapped_column(String(120), primary_key=True)
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tags: Mapped[list] = mapped_column(JSON, default=list)
    input: Mapped[dict] = mapped_column(JSON, default=dict)
    expectations: Mapped[dict] = mapped_column(JSON, default=dict)


class Attempt(Base):
    """One execution of one case (case x repeat)."""

    __tablename__ = "attempt"
    __table_args__ = (UniqueConstraint("run_id", "case_id", "repeat"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(64))
    repeat: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))  # ok | error | timeout
    answer: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)


class Step(Base):
    """One span: an LLM call, tool call or retrieval inside an attempt."""

    __tablename__ = "step"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(32), index=True)
    case_id: Mapped[str] = mapped_column(String(64))
    repeat: Mapped[int] = mapped_column(Integer, default=0)
    type: Mapped[str] = mapped_column(String(16))  # llm | tool | retrieval
    name: Mapped[str] = mapped_column(String(120))
    input_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    output_ref: Mapped[str | None] = mapped_column(String(300), nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, default=0.0)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Score(Base):
    """One judgement: (run, case, repeat, metric) -> value + evidence.

    WHY the unique key: re-scoring the same attempt overwrites instead of
    duplicating (idempotency).
    """

    __tablename__ = "score"
    __table_args__ = (UniqueConstraint("run_id", "case_id", "repeat", "metric"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("run.id"), index=True)
    case_id: Mapped[str] = mapped_column(String(64))
    repeat: Mapped[int] = mapped_column(Integer)
    metric: Mapped[str] = mapped_column(String(40))
    value: Mapped[float] = mapped_column(Float)
    evidence: Mapped[dict] = mapped_column(JSON, default=dict)


class Payload(Base):
    """Large span inputs/outputs, keyed by content hash.

    WHY in the database and not files: a serverless host (Vercel) has no
    persistent disk, so trace payloads must live somewhere every process can read.
    Content-addressed keys deduplicate repeated prompts and make writes idempotent.
    Runs hold only a short reference ("payload:<hash>") in Step.input_ref/output_ref.
    """

    __tablename__ = "payload"
    hash: Mapped[str] = mapped_column(String(32), primary_key=True)
    content: Mapped[str] = mapped_column(Text)


_engine = None
_Session: sessionmaker | None = None


def normalize_url(url: str) -> str:
    """Accept the URL forms hosts hand out and return a SQLAlchemy+psycopg URL.

    Neon, Supabase and Vercel Postgres give `postgres://` or `postgresql://`;
    SQLAlchemy needs the driver named explicitly.
    """
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


def configure(url: str | None = None, create_tables: bool = True) -> None:
    """(Re)create the engine (and tables). Pass a URL in tests.

    create_tables=False is for read-only web processes: schema changes belong to
    the CLI that writes the data, not to every cold-started function.
    """
    global _engine, _Session
    url = normalize_url(url or config.db_url())
    kwargs: dict = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        # WHY: worker threads write spans concurrently; wait instead of failing.
        kwargs["connect_args"] = {"timeout": 30, "check_same_thread": False}
    else:
        # WHY: managed Postgres often sits behind a transaction pooler (pgbouncer),
        # which breaks server-side prepared statements.
        kwargs["connect_args"] = {"prepare_threshold": None}
        if config.is_serverless():
            # WHY: each function instance is short-lived; pooling connections across
            # invocations leaks them. Let the provider's pooler do the pooling.
            kwargs["poolclass"] = NullPool
    _engine = create_engine(url, **kwargs)
    if url.startswith("sqlite"):

        @event.listens_for(_engine, "connect")
        def _pragmas(dbapi_conn, _):  # pragma: no cover - trivial
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")
            cur.execute("PRAGMA busy_timeout=30000")
            cur.close()

    if create_tables:
        Base.metadata.create_all(_engine)
    _Session = sessionmaker(_engine, expire_on_commit=False)


def get_session():
    """Return a new session. Use as `with get_session() as s:`."""
    if _Session is None:
        configure(create_tables=not config.is_serverless())
    assert _Session is not None
    return _Session()


def insert_ignore(session, table_model, **values) -> None:
    """INSERT ... ON CONFLICT DO NOTHING on SQLite and Postgres.

    WHY: concurrent workers may write the same content-addressed row; the loser
    must not raise (and abort the rest of its transaction).
    """
    if session.get_bind().dialect.name == "postgresql":
        from sqlalchemy.dialects.postgresql import insert
    else:
        from sqlalchemy.dialects.sqlite import insert
    session.execute(insert(table_model).values(**values).on_conflict_do_nothing())
