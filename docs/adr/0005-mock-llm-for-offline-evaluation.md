# ADR 0005: Offline mock LLM next to the real Claude backend

**Status:** accepted

**Context.** The platform must be runnable by anyone in minutes, testable in CI without secrets or spend, and able to reproduce a seeded regression on demand. A real model cannot guarantee controlled, repeatable behaviour changes.

**Decision.** The demo agent takes a pluggable LLM. `MockLLM` is rule-based, deterministic per (question, repeat, model), and reproduces named regressions. `GeminiLLM` (primary) and `ClaudeLLM` call real APIs for real measurements. The backend is a one-flag choice (`--llm`), so the project is not tied to one provider.

**Consequences.** Tests and CI are free and stable. Results from the mock validate the evaluation machinery only; every results file records its backend, and the README states the limit. A real-model run is required before quoting a headline number.
