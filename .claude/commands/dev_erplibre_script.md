# /dev_erplibre_script — Add a script or CLI feature to ERPLibre

Use the `erplibre-script-orchestrator` agent to implement the following script or CLI feature:

**Feature request**: $ARGUMENTS

The orchestrator coordinates 2 focused phases (lean, Sonnet model):
1. **Implementation** — Python/Bash script, Makefile target, or todo.py command with i18n
2. **Verification** — functional testing + mmg documentation (parallel)

Stack: script/ categories, todo.py/i18n, conf/make.*.Makefile, env_var.sh, mmg docs.

If no script or feature is specified, ask the user to describe the CLI/script feature before starting.
