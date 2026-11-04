
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
