"""Shared fixtures: every test gets its own throwaway database and payload folder."""

import pytest

from agentguard import db


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTGUARD_JUDGE_CACHE", str(tmp_path / "judge"))
    db.configure(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    yield
