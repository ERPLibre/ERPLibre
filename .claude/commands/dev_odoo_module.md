# /dev_odoo_module — Develop a new Odoo module or feature for ERPLibre

Use the `odoo-module-orchestrator` agent to implement the following Odoo module or feature:

**Feature request**: $ARGUMENTS

The orchestrator coordinates 3 focused phases (no mobile agents loaded):
1. **Analysis** — module architecture, OCA conventions, version compatibility
2. **Implementation** — Python models/views/wizards, XML, CSV, security
3. **Verification** — tests, Black/isort/Flake8, i18n audit (parallel)

Stack: Odoo 12-18, Python, XML, OCA, Black/isort, Poetry, code generator.

If no module or feature is specified, ask the user to describe what to build before starting.
