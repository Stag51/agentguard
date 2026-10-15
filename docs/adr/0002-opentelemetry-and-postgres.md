# ADR 0002: OpenTelemetry for spans, Postgres for storage

**Status:** accepted

**Context.** We need to capture what an agent did and query it later. Vendor-specific SDKs lock us in; a dedicated trace database adds operational weight.

**Decision.** Emit standard OpenTelemetry spans. Store runs, steps, cases and scores in Postgres; keep large payloads in a separate content-addressed table (no local disk is assumed, so the read side can run serverless).

**Consequences.** Any OTel-compatible agent can be traced. Plain SQL answers most questions. At very high volume we would move spans to a columnar store.
