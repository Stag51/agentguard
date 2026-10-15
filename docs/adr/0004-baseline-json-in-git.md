# ADR 0004: Baseline stored as a JSON summary in Git

**Status:** accepted

**Context.** The gate needs something to compare against. A database row works locally but not for a CI job on a fresh machine, and changing the bar silently would defeat the gate.

**Decision.** `agentguard baseline set <run>` writes that run's summary to `baselines/main.json`. The gate compares a candidate run to that file.

**Consequences.** Raising or lowering the bar appears in a pull request and is reviewed. The baseline is tied to one dataset version; the gate fails if the dataset changed and the baseline was not regenerated. The baseline depends on the machine only for latency, which CI therefore ignores.
