"""Runtime configuration, read from environment variables.

WHY: one place for settings keeps the rest of the code free of os.getenv calls
and makes tests easy (set the env var, reconfigure).

Does NOT hold secrets in code; API keys come from the environment only.
"""

from __future__ import annotations

import os
from pathlib import Path


def load_env(path: str | Path = ".env") -> None:
    """Load KEY=VALUE lines from a .env file into os.environ.

    WHY hand-rolled: it is ten lines and avoids a dependency. Real environment
    variables win over the file, and empty values are skipped so a blank
    `GEMINI_API_KEY=` placeholder never masks a key set in the shell.
    """
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and value and key not in os.environ:
            os.environ[key] = value


def is_serverless() -> bool:
    """True when running on Vercel (or another host that sets VERCEL)."""
    return bool(os.getenv("VERCEL"))


def db_url() -> str:
    """Database URL. SQLite by default (zero setup); hosted Postgres for deployment.

    Looked up in order: AGENTGUARD_DB, DATABASE_URL, POSTGRES_URL (the names Neon
    and Vercel's Postgres integrations set), then a local SQLite file.
    Example: postgresql://user:pass@host/dbname?sslmode=require
    """
    return (
        os.getenv("AGENTGUARD_DB")
        or os.getenv("DATABASE_URL")
        or os.getenv("POSTGRES_URL")
        or "sqlite:///agentguard.db"
    )


def judge_cache_dir() -> Path:
    """Folder where LLM-judge verdicts are cached by input hash."""
    return Path(os.getenv("AGENTGUARD_JUDGE_CACHE", "runs/judge_cache"))
