
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

# Lanceurs de tests et couverture de code

Un seul moteur, `script/test/lanceur.py`, exécute toutes les campagnes de
tests. Chaque élément — un fichier de tests unitaires, une tranche d'un
fichier lent, un scénario Odoo — tourne dans sa propre session
(`script/lib_processus.py`), lit `/dev/null`, écrit son journal dans un
fichier et reçoit son propre `TMPDIR` ; ce qu'il y laisse est compté, nommé
puis supprimé. Au délai, ou sur Ctrl+C, tout son groupe de processus reçoit
SIGTERM, puis SIGKILL après la grâce de la campagne. Les phases s'enchaînent
dans l'ordre, avec une barrière entre elles ; dans une phase, les éléments
les plus longs partent d'abord, d'après les durées du passage précédent. Une
seule campagne tourne à la fois : toutes deux partagent le serveur
PostgreSQL.

| Campagne | Commande | Éléments |
|---|---|---|
| Tests unitaires | `./script/test/run_unit_test.sh` | tout `test/test_*.py`, sans base, sans Odoo, sans VM |
| Scénarios Odoo | `./script/test/run_odoo_scenarios.sh` (`make test_full_fast`) | les entrées de `config_testcase.odoo<version>.json` |

```bash
./script/test/run_unit_test.sh --tui                 # tableau des fichiers, journal du fichier choisi
./script/test/run_unit_test.sh --changed --failed     # ce qu'un changement atteint, ce qui a échoué
./script/test/run_unit_test.sh -k proxy               # les tests dont le nom contient « proxy »
./script/test/run_unit_test.sh --ordre-aleatoire      # ordre mélangé, graine rejouable imprimée
./script/test/run_odoo_scenarios.sh --scenario=demo_test --tui
./script/test/run_odoo_scenarios.sh --purge           # supprimer les bases de scénarios restées
```

La couverture de code a deux jeux, chacun avec son interpréteur et sa
configuration : `erplibre` (script/, long_test/, docker/, mesurés par les
tests unitaires, `conf/coverage.erplibre.toml`) et `odoo` (le générateur
de code, mesuré par les scénarios, `conf/coverage.odoo.cfg`). `--coverage`
sur l'un ou l'autre lanceur mesure chaque élément sous `coverage run -p` —
les sous-processus Python qu'il lance compris —, puis fusionne les données,
écrit le rapport JSON et ajoute le passage à l'historique, dans
`~/.cache/erplibre/couverture/<jeu>/`. Un passage partiel (`--changed`,
`--failed`, `-k`, des fichiers nommés) est marqué comme tel et jamais
comparé à un passage complet. Les durées d'un passage mesuré ne sont pas
retenues.

```bash
make test_unit_coverage                                    # tests unitaires sous couverture
.venv.erplibre/bin/python script/test/couverture_tui.py    # arbre, source annotée, historique
.venv.erplibre/bin/python script/test/couverture.py html --jeu erplibre
```

TODO › Exécution › Développement › [11] Couverture regroupe l'écran, les
passages mesurés, le rapport HTML et l'effacement des données d'un jeu.

Ce que la couverture ne voit pas : un sous-processus Python lancé avec un
environnement reconstruit de zéro, ou par un `python3` littéral hors du
venv, et le code qu'un test ne fait que lire (regex, AST) sans l'exécuter.

Écrire des tests qui gardent la suite saine : `test/test_suite_hygiene.py`
refuse une fonction d'aide de module nommée `test*`, `addModuleCleanup`
(pytest ne l'exécute jamais) et `logging.basicConfig` à l'import dans un
fichier de test. Remplacer avec `mock.patch` en contexte ou avec
`addCleanup`, jamais par une affectation nue ; un test qui crée une vraie
machine va dans `long_test/`.