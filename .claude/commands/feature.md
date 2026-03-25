# /feature — Orchestrate a new feature end-to-end

Use the `feature-orchestrator` agent to implement the following feature:

**Feature request**: $ARGUMENTS

The orchestrator will coordinate all specialist agents through 5 phases:
1. **Analysis** — architecture, security, UX, compliance (parallel)
2. **Design** — data governance, performance, accessibility (sequential)
3. **Implementation** — backend then frontend (sequential)
4. **Verification** — QA, code quality, risk (parallel)
5. **Documentation** — changelog, i18n, release commits (parallel)

A complete report will be produced at the end with all findings, decisions,
risks, and the recommended commit sequence.

If no feature is specified, ask the user to describe the feature before starting.
