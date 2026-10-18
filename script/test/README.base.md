<!---------------------------->
<!-- multilingual suffix: en, fr -->
<!-- no suffix: en -->
<!---------------------------->

<!-- [en] -->
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

<!-- [fr] -->
# Consigner les tests Python des requis

`record_requirement_python_tests.py` écrit dans Odoo le résultat des tests
Python liés aux requis DevSecOps. Il lit par XML-RPC les lignes
`devops.requirement.test` de type `python`, dont la référence est un chemin
pointé `odoo.addons.<module>.tests.<fichier>.<Classe>[.<méthode>]`, puis
travaille selon l'un de deux modes :

- `--print-test-tags` affiche `modules=…` et `test_tags=…`, ce qu'il faut à
  `./test.sh -i` et à `--test-tags` pour lancer toutes les lignes (ou celles
  de `--code`), et sort sans rien écrire ;
- `--log FICHIER` lit le journal d'un `./test.sh --log-level=test` et appelle
  `devops.requirement.test.record_result` pour chaque ligne.

```bash
export ERPLIBRE_REQUIREMENT_RUNNER_LOGIN=<login de l'exécutant>
export ERPLIBRE_REQUIREMENT_RUNNER_PASSWORD=<mot de passe de l'exécutant>
.venv.erplibre/bin/python script/test/record_requirement_python_tests.py \
  --url http://127.0.0.1:8069 --db <base des requis> --print-test-tags
./test.sh -d <base jetable> -i <modules> --stop-after-init \
  --log-level=test --without-demo=all --test-tags <test_tags> > test.log 2>&1
.venv.erplibre/bin/python script/test/record_requirement_python_tests.py \
  --url http://127.0.0.1:8069 --db <base des requis> --log test.log
```

- Le verdict d'une ligne vient des tests du journal que couvre sa référence,
  classe entière ou méthode : `failed` sur un `FAIL:`, `error` sur un
  `ERROR:` ou quand le `setUpClass` ou le `tearDownClass` de la classe
  échoue, `skipped` quand tous les tests sont sautés, `passed` quand tous ont
  démarré sans échec. Un test relancé (`ODOO_TEST_FAILURE_RETRIES`) est jugé
  sur sa dernière tentative, et un sous-test sauté ne fait pas sauter son
  test. Une ligne dont aucun test n'apparaît au journal n'est PAS écrite :
  elle garde son dernier résultat et le rapport la compte non vue ;
  `--require_all_seen` en fait une erreur d'outil, pour une passe lancée avec
  les `--test-tags` de `--print-test-tags`.
- Rien n'est écrit d'un journal qui n'est pas celui d'une passe complète et
  unique : sans ligne `N failed, N error(s) of N tests`, ou avec plusieurs,
  ou avec un test après elle ; passe abandonnée (`Failed to initialize
  database`, `Failed to load registry`) ou coupée par
  `ODOO_TEST_MAX_FAILED_TESTS` ; tests démarrés, `FAIL` ou `ERROR` qui ne
  recoupent pas le bilan ; tests de plusieurs bases.
- Chaque étiquette de test commence par `*`, qui lève l'étiquette `standard`
  qu'Odoo exige sinon : une ligne lance son test même marqué `-standard`.
- Le journal consigné avec une ligne nomme ses tests et, en échec, un extrait
  borné de la trace ; la durée vient des horodatages du journal.
- Code de sortie : 0 toutes les lignes vues passent ou sont sautées, 1 une
  ligne échoue, 2 l'outil échoue (connexion, RPC, journal illisible ou
  refusé, référence illisible, code demandé sans ligne, résultat non
  remonté, aucune ligne vue). `--dry_run` analyse et rapporte sans écrire. Le
  rapport JSON va sous `./screencasts/requirement_python_tests` sauf
  `--report_json`.
- Le compte appartient au groupe « Lanceur de tests de requis » ou est un
  utilisateur système. Ses identifiants passent par des variables
  d'environnement seulement : tout utilisateur de la machine lit les
  arguments d'un processus.
