"""Checks that matter for a serverless (Vercel) deployment."""

import subprocess
import sys
import textwrap
from pathlib import Path

from agentguard import config, db
from agentguard.collector.payloads import load_payloads, read_payload, write_payload

ROOT = Path(__file__).resolve().parents[1]

SLIM_IMPORT_SCRIPT = textwrap.dedent(
    """
    import importlib.abc
    import sys

    root = sys.argv[1]
    BLOCKED = ("opentelemetry.sdk", "langgraph", "anthropic", "google", "demo_agent", "uvicorn")


    class Block(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if any(name == b or name.startswith(b + ".") for b in BLOCKED):
                raise ImportError("blocked: " + name)


    sys.meta_path.insert(0, Block())
    sys.path.insert(0, root + "/src")
    sys.path.insert(0, root)
    import api.index

    print("LOADED", type(api.index.app).__name__)
    """
)


def test_web_function_loads_without_the_heavy_agent_dependencies():
    """Simulate the slim Vercel install: block the agent-only packages, then import the API.

    (FastAPI itself needs the light `opentelemetry-api`, which is fine; the
    OpenTelemetry *SDK* is what only the agent side uses.)
    """
    out = subprocess.run([sys.executable, "-c", SLIM_IMPORT_SCRIPT, str(ROOT)], capture_output=True, text=True, cwd=ROOT)
    assert "LOADED FastAPI" in out.stdout, out.stdout + out.stderr


def test_postgres_urls_are_normalised():
    assert db.normalize_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert db.normalize_url("postgresql://u:p@h/db?sslmode=require") == "postgresql+psycopg://u:p@h/db?sslmode=require"
    assert db.normalize_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert db.normalize_url("sqlite:///x.db") == "sqlite:///x.db"


def test_db_url_env_precedence(monkeypatch):
    for k in ("AGENTGUARD_DB", "DATABASE_URL", "POSTGRES_URL"):
        monkeypatch.delenv(k, raising=False)
    assert config.db_url().startswith("sqlite")
    monkeypatch.setenv("POSTGRES_URL", "p")
    assert config.db_url() == "p"
    monkeypatch.setenv("DATABASE_URL", "d")
    assert config.db_url() == "d"
    monkeypatch.setenv("AGENTGUARD_DB", "a")
    assert config.db_url() == "a"


def test_payloads_live_in_the_database_and_are_idempotent():
    ref = write_payload('{"a": 1}')
    assert ref == write_payload('{"a": 1}')  # same content, same reference, no error
    assert read_payload(ref) == '{"a": 1}'
    with db.get_session() as s:
        assert load_payloads([ref, "payload:missing"], s) == {ref: '{"a": 1}'}
        assert s.query(db.Payload).count() == 1


def test_serverless_flag(monkeypatch):
    monkeypatch.delenv("VERCEL", raising=False)
    assert not config.is_serverless()
    monkeypatch.setenv("VERCEL", "1")
    assert config.is_serverless()


def test_health_says_what_is_wrong_when_database_url_is_missing_on_vercel(monkeypatch):
    from fastapi.testclient import TestClient

    from agentguard.api.app import create_app

    for k in ("AGENTGUARD_DB", "DATABASE_URL", "POSTGRES_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("VERCEL", "1")
    body = TestClient(create_app()).get("/api/health").json()
    assert body["ok"] is False and "DATABASE_URL" in body["db"]
