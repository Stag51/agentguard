"""Vercel entry point: exposes the read-only FastAPI app as `app`.

The evaluation (running agents, calling LLMs) never happens here; it runs on your
machine or in CI and writes to the same hosted Postgres this function reads.

Environment (set in the Vercel project settings):
    DATABASE_URL (or AGENTGUARD_DB / POSTGRES_URL)  hosted Postgres connection string
"""

import sys
from pathlib import Path

# WHY: the function bundle includes src/ (see vercel.json) but the package is not
# necessarily pip-installed, so make it importable explicitly.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from agentguard.api.app import app  # noqa: E402,F401
