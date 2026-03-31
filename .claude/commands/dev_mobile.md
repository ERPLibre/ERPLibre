# /dev_mobile — Add a feature to ERPLibre Home Mobile

Use the `mobile-orchestrator` agent to implement the following mobile feature:

**Feature request**: $ARGUMENTS

The orchestrator coordinates 3 focused phases (no irrelevant agents loaded):
1. **Analysis** — architecture + security (parallel)
2. **Implementation** — backend services/SQLite → frontend Owl/SCSS (sequential)
3. **Verification** — QA tests + code quality (parallel)

Stack: Capacitor 7, Owl 2.8.1, TypeScript, SQLite/SQLCipher, Vitest.

If no feature is specified, ask the user to describe the mobile feature before starting.
