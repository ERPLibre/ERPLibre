
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