
# Installation Ubuntu 24.04

 sudo apt install libcairo2-dev

# Requirement tours

`run_requirement_tours.py` plays the `web_tour` tours linked to DevSecOps
requirements and writes each verdict back to Odoo. It reads the
`devops.requirement.test` lines of kind `tour` over XML-RPC, logs in once,
plays every tour in `auto` mode from `/odoo`, then calls
`devops.requirement.test.record_result`. A failed tour leaves a screenshot,
and a JSON report sums up the run, both under `./screencasts/requirement_tours`.

```bash
export ERPLIBRE_REQUIREMENT_RUNNER_LOGIN=<runner login>
export ERPLIBRE_REQUIREMENT_RUNNER_PASSWORD=<runner password>
make robot_libre_requirement_tours bd=<database>
# or, to choose the requirements and keep the run readable:
.venv.erplibre/bin/python script/selenium/run_requirement_tours.py \
  --headless --no_dark_mode --db <database> --code <CODE> --step_delay 800
```

- The RPC account belongs to the group "Requirement test runner" or is a
  system user. Its credentials go through environment variables only, and the
  browser logs in with the same account unless `--default_email_auth` is
  given. Without these variables, the RPC uses the browser account only if its
  password comes from `--default_password_auth_env`; otherwise the run stops
  with exit code 2. Never put a password in `ARGS`: make prints the recipe,
  and any user on the machine can read a process's arguments.
- Exit code: 0 every tour passes, 1 a tour fails, 2 the tool fails (browser,
  login, RPC, missing tour, no verdict, verdict not recorded, nothing to play).
  What fails after the verdicts — the Onboarding not switched back on, the
  browser not closed — is listed under `alertes` in the report and leaves
  the exit code as it is.
- The tour must be in `web.assets_backend`: `/odoo` loads `web.assets_tests`
  only in test mode.
- Side effects on the target database: the browser account's Onboarding is
  switched off during the run and back on at the end if it was on; when it
  cannot be read, the run stops before touching it. The records a tour
  creates stay there.
