
# Plan de test — ERPLibre `./test/`

## Vue d'ensemble

| Metric / Métrique | Value / Valeur |
|---|---|
| Test files / Fichiers de test | 13 |
| Test classes / Classes de test | 56 |
| Test methods / Méthodes de test | 262 |
| Framework | `unittest` (Python stdlib) |
| Command / Commande | `python3 -m unittest discover -s test -v` |

---

## 1. `test_config_file.py` — Configuration et fusion de fichiers

**Type** : Test unitaire (pure logique, aucun I/O réel)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestDeepMergeWithLists` | 11 | Fusion récursive de dicts avec stratégies de listes (`replace` vs `extend`), immutabilité du dict source |
| `TestGetConfig` | 6 | Chargement et fusion de configs depuis base + override + private JSON, précédence correcte |
| `TestGetConfigValue` | 2 | Navigation dans les valeurs imbriquées par chemin de clés |
| `TestGetLogoAsciiFilePath` | 1 | Retourne le chemin du fichier logo |

**Mocks** : `@patch` sur les chemins CONFIG_FILE, fichiers temporaires JSON

---

## 2. `test_execute.py` — Exécution de commandes shell

**Type** : Test d'intégration (exécute de vrais processus bash)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestExecuteInit` | 3 | Détection du terminal (gnome-terminal, osascript), configuration du venv |
| `TestExecCommandLive` | 15 | Exécution de commandes avec différents modes de retour (status, output, commande), activation de venv, variables d'environnement custom |

**Mocks** : `@patch("shutil.which")` pour le terminal. Les commandes bash sont exécutées réellement.

---

## 3. `test_git_tool.py` — Utilitaires Git et parsing de manifests

**Type** : Test unitaire

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestRepoAttrs` | 3 | Structure de données des attributs de repo |
| `TestGetUrl` | 3 | Conversion d'URL HTTPS ↔ SSH |
| `TestGetTransformedRepoInfo` | 10 | Extraction d'org, nom de repo, chemin depuis URL, forçage d'org, revision, clone_depth |
| `TestDefaultProperties` | 5 | Constantes par défaut, lecture de la version Odoo |
| `TestStrInsert` | 3 | Insertion de sous-chaîne à une position |
| `TestGetProjectConfig` | 1 | Lecture de `EL_GITHUB_TOKEN` depuis `env_var.sh` |
| `TestGetRepoInfoSubmodule` | 2 | Parsing de `.gitmodules` |
| `TestGetManifestXmlInfo` | 2 | Parsing de manifests XML Google Repo |
| `TestConstants` | 3 | Vérification des constantes définies |

**Mocks** : `@patch("builtins.open")`, fichiers temporaires pour `.gitmodules` et XML

---

## 4. `test_kill_process_by_port.py` — Gestion de processus

**Type** : Test unitaire (processus mockés, aucun kill réel)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestProcDesc` | 3 | Formatage de description de processus (pid, cmdline, username) |
| `TestGetAncestry` | 3 | Remontée de la chaîne de processus parents (arrêt à pid 1, ppid 0) |
| `TestChooseTarget` | 3 | Sélection du processus cible (détection de `./run.sh`, `./odoo_bin.sh`) |
| `TestKillProcess` | 2 | Terminaison de processus (gentle terminate vs force kill) |
| `TestKillTree` | 3 | Kill récursif de l'arbre de processus (enfants d'abord) |
| `TestFindListeners` | 5 | Énumération des sockets réseau par port (filtrage, dédoublonnage) |
| `TestProtectedNames` | 2 | Protection des processus système (systemd, gnome-shell, sshd) |
| `TestStopParentKill` | 2 | Détection des scripts wrapper |

**Mocks** : `_make_proc()` crée des objets `psutil.Process` mockés, `@patch` sur les fonctions psutil

---

## 5. `test_todo.py` — CLI interactif TODO

**Type** : Test unitaire

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestTODOInit` | 1 | Initialisation de la classe TODO |
| `TestFillHelpInfo` | 3 | Génération de texte d'aide, résolution des clés i18n |
| `TestGetOdooVersion` | 3 | Parsing de `version.json`, détection de la version active |
| `TestOnDirSelected` | 1 | Sélection de répertoire |
| `TestExecuteFromConfiguration` | 5 | Exécution de commandes/makefiles/callbacks depuis config dict |
| `TestConstants` | 7 | Vérification des chemins constants |
| `TestDeployGitServer` | 2 | Logique de déploiement du git daemon |
| `TestProcessKillGitDaemon` | 1 | Kill du processus git daemon |
| `TestExecuteUnitTests` | 2 | Exécution des tests unitaires |
| `TestKdbxGetExtraCommandUser` | 3 | Intégration KeePass |
| `TestSetupClaudeCommit` | 1 | Setup du template de commit Claude |
| `TestSelectDatabase` | 2 | Sélection de base de données |
| `TestRestoreFromDatabase` | 2 | Restauration de base de données |
| `TestCreateBackupFromDatabase` | 1 | Création de backup |

**Mocks** : `MagicMock()` pour Execute et database manager, fichiers temporaires

---

## 6. `test_todo_i18n.py` — Internationalisation (FR/EN)

**Type** : Test unitaire

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestTranslations` | 3 | Complétude du dictionnaire TRANSLATIONS (toutes les clés ont `fr` et `en`, aucune valeur vide) |
| `TestT` | 4 | Fonction `t()` : retourne la bonne langue, fallback sur la clé si inconnue |
| `TestGetLang` | 7 | Détection de langue : cache mémoire, lecture de `env_var.sh`, variable d'environnement, fallback à `"fr"` |
| `TestSetLang` | 4 | Persistance de la langue dans `env_var.sh`, gestion de fichier manquant |
| `TestLangIsConfigured` | 3 | Détection de l'état de configuration |

**Mocks** : `@patch.object` sur `ENV_VAR_FILE`, `@patch.dict(os.environ)`, `setUp/tearDown` pour réinitialiser `_current_lang`

---

## 7. `test_check_addons_exist.py` — Validation des addons Odoo

**Type** : Test unitaire (fichiers temporaires, aucun Odoo requis)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestMainModuleFound` | 3 | Module trouvé avec `__manifest__.py` valide, sortie JSON et JSON formaté |
| `TestMainModuleMissing` | 2 | Module absent retourne code 1, sortie JSON pour module manquant |
| `TestMainDuplicateModule` | 1 | Module en double dans plusieurs chemins retourne code 2 |
| `TestMainMissingManifest` | 1 | Répertoire sans `__manifest__.py` retourne code 1 |
| `TestMainBadConfig` | 2 | Config INI sans section `[options]` ou sans clé `addons_path` retourne -1 |

**Mocks** : `@patch("sys.argv")`, fichiers temporaires pour addons et config INI

---

## 8. `test_iscompatible.py` — Compatibilité de versions pip

**Type** : Test unitaire (pure logique, aucun I/O)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestStringToTuple` | 4 | Conversion de chaîne de version en tuple d'entiers |
| `TestParseRequirements` | 7 | Parsing de la syntaxe requirements.txt (opérateurs, contraintes multiples, commentaires) |
| `TestIsCompatible` | 11 | Vérification de compatibilité de version avec opérateurs `==`, `>=`, `>`, `<`, `<=`, `!=` et plages |

**Mocks** : Aucun — fonctions pures

---

## 9. `test_format_file_to_commit.py` — Détection de fichiers modifiés pour formatage

**Type** : Test unitaire (git mocké) + Test d'intégration (`execute_shell` exécute de vrais processus)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestExecuteShell` | 5 | Exécution de commandes shell : succès, échec (code retour), capture stderr, sortie vide, sortie multiligne |
| `TestGetModifiedFiles` | 9 | Parsing du `git status --porcelain` : fichier modifié, ajouté, supprimé (ignoré), ZIP/tar.gz (ignorés), non suivi, statut vide, statuts multiples, erreur git |

**Mocks** : `@patch` sur `subprocess.run`, `os.path.exists`, `os.path.isfile`

---

## 10. `test_version.py` — Gestion des versions ERPLibre

**Type** : Test unitaire

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestRemoveDotPath` | 6 | Suppression du préfixe `./` des chemins |
| `TestDie` | 3 | Sortie conditionnelle avec code d'erreur configurable |
| `TestConstants` | 7 | Templates de noms de fichiers versionnés (venv, manifest, pyproject, poetry lock, addons, odoo) |
| `TestUpdateValidateVersion` | 5 | Résolution de version : explicite, par odoo_version, fallback par défaut, version détectée, chemins attendus |
| `TestUpdateDetectVersion` | 2 | Détection de version : fichiers absents, correspondance avec `data_version` |
| `TestUpdatePrintLog` | 2 | Affichage du log d'exécution vide et peuplé |

**Mocks** : `@patch("sys.argv")`, fichiers temporaires pour les fichiers de version, `@patch` sur les constantes de chemin

---

## 11. `test_docker_update_version.py` — Mise à jour de version Docker

**Type** : Test unitaire (fichiers temporaires)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestEditText` | 2 | Mise à jour de l'image dans `docker-compose.yml` après le service ERPLibre, préservation des autres lignes |
| `TestEditDockerProd` | 3 | Remplacement de la ligne `FROM` dans Dockerfile, préservation des lignes RUN/COPY, gestion multi-FROM |

**Mocks** : Aucun — utilise `tempfile.NamedTemporaryFile` pour les fichiers Docker

---

## 12. `test_code_generator_tools.py` — Outils du générateur de code

**Type** : Test unitaire (pure logique AST et string)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestCountSpaceTab` | 9 | Comptage d'indentation : espaces, tabulations, mixte, `\n`/`\r`, group_space personnalisé |
| `TestExtractLambda` | 2 | Extraction d'expression lambda depuis un nœud AST, suppression des parenthèses externes |
| `TestFillSearchField` | 11 | Extraction récursive de valeurs AST : Constant (str, int, bool), UnaryOp (négatif), Name, Attribute, List, Dict, Tuple, Lambda, type non supporté |
| `TestSearchAndReplace` | 4 | Remplacement de valeurs dans du code Python : valeur entre guillemets, modèle vide, mot-clé absent, mot-clé personnalisé |
| `TestArgsTypeParam` | 6 | Validation du dictionnaire ARGS_TYPE_PARAM pour les types de champs Odoo |

**Mocks** : Aucun — fonctions pures sur AST et chaînes de caractères

---

## 13. `test_database_tools.py` — Outils de base de données

**Type** : Test unitaire (fichiers temporaires)

| Classe | # Tests | Ce qui est validé |
|---|---|---|
| `TestProcessZip` | 4 | Traitement de fichiers ZIP : suppression de lignes par mot-clé, préservation quand pas de correspondance, suppression totale, fichiers non ciblés intacts |
| `TestCompareDatabaseApplicationLogic` | 4 | Comparaison de CSV par ensembles : CSVs identiques, différents, vides, un seul vide |

**Mocks** : Aucun — utilise `tempfile` et `zipfile` pour les fichiers temporaires

---

## Matrice de couverture par composant

| Composant testé | Fichier source | Fichier test | Type |
|---|---|---|---|
| `ConfigFile` | `script/config/config_file.py` | `test_config_file.py` | Unitaire |
| `Execute` | `script/execute/execute.py` | `test_execute.py` | Intégration |
| `GitTool` | `script/git/git_tool.py` | `test_git_tool.py` | Unitaire |
| `kill_process_by_port` | `script/process/kill_process_by_port.py` | `test_kill_process_by_port.py` | Unitaire |
| `TODO` | `script/todo/todo.py` | `test_todo.py` | Unitaire |
| `todo_i18n` | `script/todo/todo_i18n.py` | `test_todo_i18n.py` | Unitaire |
| `check_addons_exist` | `script/addons/check_addons_exist.py` | `test_check_addons_exist.py` | Unitaire |
| `iscompatible` | `script/poetry/iscompatible.py` | `test_iscompatible.py` | Unitaire |
| `format_file_to_commit` | `script/maintenance/format_file_to_commit.py` | `test_format_file_to_commit.py` | Unitaire + Intégration |
| `update_env_version` | `script/version/update_env_version.py` | `test_version.py` | Unitaire |
| `docker_update_version` | `script/docker/docker_update_version.py` | `test_docker_update_version.py` | Unitaire |
| Code Generator (tools) | `script/code_generator/search_class_model.py` | `test_code_generator_tools.py` | Unitaire |
| Database (tools) | `script/database/migrate/process_backup_file.py` | `test_database_tools.py` | Unitaire |

## Composants partiellement couverts

Les composants suivants ont des tests pour leurs fonctions pures, mais les fonctions nécessitant une infrastructure (Odoo, PostgreSQL, réseau) ne sont pas testées unitairement :

- `script/database/` — `process_zip` et logique CSV testés ; `db_restore`, `image_db`, `list_remote` non testés (requièrent Odoo/PostgreSQL)
- `script/code_generator/` — `extract_lambda`, `fill_search_field`, `search_and_replace`, `count_space_tab` testés ; `generate_module`, `main` non testés (requièrent Odoo)
- `script/poetry/` — `iscompatible`, `parse_requirements`, `string_to_tuple` testés ; `combine_requirements`, `poetry_update.main` non testés (requièrent le filesystem complet)

---

## Patterns de test utilisés

| Pattern | Usage |
|---|---|
| **Mocking (`@patch`)** | Isolation des dépendances système (psutil, shutil, subprocess, os.path, fichiers) |
| **Fichiers temporaires** | `tempfile.mkdtemp()` et `tempfile.NamedTemporaryFile()` pour tester l'I/O sans effets de bord |
| **Helper factory** | `_make_proc()` dans test_kill_process, `_mock_git()` dans test_format, `_write_csv()` dans test_database |
| **État isolé** | `setUp/tearDown` pour réinitialiser les globals entre tests |
| **Exécution réelle** | `test_execute.py` et `TestExecuteShell` lancent de vrais processus bash |
| **SimpleNamespace** | Création de configs légères sans argparse dans test_docker |
| **AST inline** | `ast.parse(code, mode="eval").body` pour créer des nœuds AST de test |