# ADR 0003: Golden datasets live in Git as JSONL

**Status:** accepted

**Context.** Test cases decide whether a change ships, so they need review and history.

**Decision.** Store cases as JSONL files in the repository, validated by a schema on load. A run records the dataset version.

**Consequences.** Dataset changes appear in pull requests and can be diffed. Editing requires a text editor or a helper command; a review UI is future work.
