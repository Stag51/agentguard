"""AgentGuard: evaluation and observability for LLM agents.

Pipeline: trace an agent (sdk) -> store spans (collector) -> replay golden
cases (runner) -> score (scorers) -> compare with a baseline (gate).
"""

__version__ = "0.1.0"
