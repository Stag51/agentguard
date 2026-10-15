# ADR 0001: Deterministic scorers first, LLM judge as fallback

**Status:** accepted

**Context.** Agent output must be scored automatically. An LLM judge can grade anything but is costly, slow and biased. Many agent failures (wrong tool, wrong arguments, missing fact) can be checked exactly.

**Decision.** Run deterministic checks first. Call the LLM judge only for open-ended answers, and audit the judge against 50 hand-labelled cases.

**Consequences.** Cheaper and repeatable runs; failures come with exact evidence. Open-ended quality depends on a judge whose error rates we publish. Dataset authors must write explicit expectations.
