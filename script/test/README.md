
# Recording the Python tests of the requirements

`record_requirement_python_tests.py` writes the result of the Python tests
linked to DevSecOps requirements back to Odoo. It reads over XML-RPC the
`devops.requirement.test` lines of kind `python`, whose reference is a dotted
path `odoo.addons.<module>.tests.<file>.<Class>[.<method>]`, then works in one
of two modes:

- `--print-test-tags` prints `modules=…` and `test_tags=…`, what `./test.sh -i`
  and `--test-tags` need to run every line (or the lines of `--code`), and
  exits without writing anything;
- `--log FILE` reads the log of a `./test.sh --log-level=test` run and calls
  `devops.requirement.test.record_result` for each line.

```bash
export ERPLIBRE_REQUIREMENT_RUNNER_LOGIN=<runner login>
export ERPLIBRE_REQUIREMENT_RUNNER_PASSWORD=<runner password>
.venv.erplibre/bin/python script/test/record_requirement_python_tests.py \
  --url http://127.0.0.1:8069 --db <requirements database> --print-test-tags
./test.sh -d <disposable database> -i <modules> --stop-after-init \
  --log-level=test --without-demo=all --test-tags <test_tags> > test.log 2>&1
.venv.erplibre/bin/python script/test/record_requirement_python_tests.py \
  --url http://127.0.0.1:8069 --db <requirements database> --log test.log
```

- The verdict of a line comes from the tests of the log that its reference
  covers, a whole class or one method: `failed` on a `FAIL:`, `error` on an
  `ERROR:` or when the `setUpClass` or `tearDownClass` of the class fails,
  `skipped` when every test is skipped, `passed` when every test started
  without failure. A retried test (`ODOO_TEST_FAILURE_RETRIES`) is judged on
  its last attempt, and a skipped subtest does not skip its test. A line
  none of whose tests is in the log is NOT written: it keeps its last result
  and the report counts it as unseen; `--require_all_seen` makes it a tool
  error, for a run made with the `--test-tags` of `--print-test-tags`.
- Nothing is written from a log that is not the one of a single complete
  run: no line `N failed, N error(s) of N tests`, or several, or a test after
  it; a run aborted (`Failed to initialize database`, `Failed to load
  registry`) or halted by `ODOO_TEST_MAX_FAILED_TESTS`; started tests, `FAIL`
  or `ERROR` that do not add up to the summary line; tests of several
  databases.
- Each test tag starts with `*`, which lifts the `standard` tag that Odoo
  requires otherwise: a line runs its test even when it is tagged
  `-standard`.
- The log recorded with a line names its tests and, on failure, a bounded
  excerpt of the traceback; the duration comes from the log timestamps.
- Exit code: 0 every seen line passes or is skipped, 1 a line fails, 2 the
  tool fails (login, RPC, unreadable or refused log, unreadable reference,
  requested code without a line, result not recorded, no line seen).
  `--dry_run` analyses and reports without writing. The JSON report goes to
  `./screencasts/requirement_python_tests` unless `--report_json` is given.
- The account belongs to the group "Requirement test runner" or is a system
  user. Its credentials go through environment variables only: any user on
  the machine can read a process's arguments.

# Test runners and code coverage

One engine, `script/test/lanceur.py`, runs every test campaign. Each item —
a unit-test file, a slice of a slow one, an Odoo scenario — runs in its own
session (`script/lib_processus.py`), reads `/dev/null`, writes its log to a
file and gets its own `TMPDIR`; what it leaves there is counted, named and
removed. At the timeout, or on Ctrl+C, its whole process group receives
SIGTERM, then SIGKILL after the campaign's grace period. Phases run in
order, with a barrier between them; within a phase the longest items start
first, from the durations of the previous run. Only one campaign runs at a
time: both share the PostgreSQL server.

| Campaign | Command | Items |
|---|---|---|
| Unit tests | `./script/test/run_unit_test.sh` | every `test/test_*.py`, no database, no Odoo, no VM |
| Odoo scenarios | `./script/test/run_odoo_scenarios.sh` (`make test_full_fast`) | entries of `config_testcase.odoo<version>.json` |

```bash
./script/test/run_unit_test.sh --tui                 # table of files, log of the selected one
./script/test/run_unit_test.sh --changed --failed     # what a change reaches, what failed last time
./script/test/run_unit_test.sh -k proxy               # tests whose name contains « proxy »
./script/test/run_unit_test.sh --ordre-aleatoire      # shuffled order, replayable seed printed
./script/test/run_odoo_scenarios.sh --scenario=demo_test --tui
./script/test/run_odoo_scenarios.sh --purge           # drop leftover scenario databases
```

Code coverage has two sets, each with its interpreter and configuration:
`erplibre` (script/, long_test/, docker/, measured by the unit tests,
`conf/coverage.erplibre.toml`) and `odoo` (the code generator, measured by
the scenarios, `conf/coverage.odoo.cfg`). `--coverage` on either runner
measures each item under `coverage run -p` — the Python subprocesses it
starts included — then merges the data, writes the JSON report and appends
the run to the history in `~/.cache/erplibre/couverture/<set>/`. A partial
run (`--changed`, `--failed`, `-k`, named files) is marked as such and never
compared with a complete one. The durations of a measured run are not kept.

```bash
make test_unit_coverage                                    # unit tests under coverage
.venv.erplibre/bin/python script/test/couverture_tui.py    # tree, annotated source, history
.venv.erplibre/bin/python script/test/couverture.py html --jeu erplibre
make open_test_coverage JEU=erplibre                       # HTML report in the browser (JEU=odoo: the scenarios)
```

TODO › Execute › Development › [11] Coverage gathers the screen, the measured
runs, the HTML report and the erasing of a set's data.

What coverage does not see: a Python subprocess started with an environment
rebuilt from scratch or through a literal `python3` outside the venv, and code
that a test only reads (regex, AST) without running it.

Writing tests that keep the suite healthy: `test/test_suite_hygiene.py`
refuses a module-level helper named `test*`, `addModuleCleanup` (pytest never
runs it), and `logging.basicConfig` at import in a test file. Patch with
`mock.patch` as a context or with `addCleanup`, never by bare assignment; a
test that creates a real machine belongs in `long_test/`.
