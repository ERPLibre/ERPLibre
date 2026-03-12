
# Test Plan — ERPLibre `./test/`

## Overview

| Metric / Métrique | Value / Valeur |
|---|---|
| Test files / Fichiers de test | 13 |
| Test classes / Classes de test | 56 |
| Test methods / Méthodes de test | 262 |
| Framework | `unittest` (Python stdlib) |
| Command / Commande | `python3 -m unittest discover -s test -v` |

---

## 1. `test_config_file.py` — Configuration and file merging

**Type**: Unit test (pure logic, no real I/O)

| Class | # Tests | What is validated |
|---|---|---|
| `TestDeepMergeWithLists` | 11 | Recursive dict merging with list strategies (`replace` vs `extend`), source dict immutability |
| `TestGetConfig` | 6 | Loading and merging configs from base + override + private JSON, correct precedence |
| `TestGetConfigValue` | 2 | Navigating nested values by key path |
| `TestGetLogoAsciiFilePath` | 1 | Returns the logo file path |

**Mocks**: `@patch` on CONFIG_FILE paths, temporary JSON files

---

## 2. `test_execute.py` — Shell command execution

**Type**: Integration test (executes real bash processes)

| Class | # Tests | What is validated |
|---|---|---|
| `TestExecuteInit` | 3 | Terminal detection (gnome-terminal, osascript), venv configuration |
| `TestExecCommandLive` | 15 | Command execution with various return modes (status, output, command), venv activation, custom environment variables |

**Mocks**: `@patch("shutil.which")` for terminal. Bash commands are actually executed.

---

## 3. `test_git_tool.py` — Git utilities and manifest parsing

**Type**: Unit test

| Class | # Tests | What is validated |
|---|---|---|
| `TestRepoAttrs` | 3 | Repo attributes data structure |
| `TestGetUrl` | 3 | URL format conversion HTTPS ↔ SSH |
| `TestGetTransformedRepoInfo` | 10 | Org, repo name, path extraction from URL, org forcing, revision, clone_depth |
| `TestDefaultProperties` | 5 | Default constants, Odoo version reading |
| `TestStrInsert` | 3 | Substring insertion at position |
| `TestGetProjectConfig` | 1 | Reading `EL_GITHUB_TOKEN` from `env_var.sh` |
| `TestGetRepoInfoSubmodule` | 2 | Parsing `.gitmodules` |
| `TestGetManifestXmlInfo` | 2 | Parsing Google Repo manifest XML |
| `TestConstants` | 3 | Verifying defined constants |

**Mocks**: `@patch("builtins.open")`, temporary files for `.gitmodules` and XML

---

## 4. `test_kill_process_by_port.py` — Process management

**Type**: Unit test (mocked processes, no real kill)

| Class | # Tests | What is validated |
|---|---|---|
| `TestProcDesc` | 3 | Process description formatting (pid, cmdline, username) |
| `TestGetAncestry` | 3 | Parent process chain walking (stops at pid 1, ppid 0) |
| `TestChooseTarget` | 3 | Target process selection (detection of `./run.sh`, `./odoo_bin.sh`) |
| `TestKillProcess` | 2 | Process termination (gentle terminate vs force kill) |
| `TestKillTree` | 3 | Recursive process tree killing (children first) |
| `TestFindListeners` | 5 | Network socket enumeration by port (filtering, deduplication) |
| `TestProtectedNames` | 2 | System process protection (systemd, gnome-shell, sshd) |
| `TestStopParentKill` | 2 | Wrapper script detection |

**Mocks**: `_make_proc()` creates mocked `psutil.Process` objects, `@patch` on psutil functions

---

## 5. `test_todo.py` — Interactive CLI TODO

**Type**: Unit test

| Class | # Tests | What is validated |
|---|---|---|
| `TestTODOInit` | 1 | TODO class initialization |
| `TestFillHelpInfo` | 3 | Help text generation, i18n key resolution |
| `TestGetOdooVersion` | 3 | Parsing `version.json`, active version detection |
| `TestOnDirSelected` | 1 | Directory selection |
| `TestExecuteFromConfiguration` | 5 | Executing commands/makefiles/callbacks from config dict |
| `TestConstants` | 7 | Path constants verification |
| `TestDeployGitServer` | 2 | Git daemon deployment logic |
| `TestProcessKillGitDaemon` | 1 | Git daemon process killing |
| `TestExecuteUnitTests` | 2 | Unit test execution |
| `TestKdbxGetExtraCommandUser` | 3 | KeePass integration |
| `TestSetupClaudeCommit` | 1 | Claude commit template setup |
| `TestSelectDatabase` | 2 | Database selection |
| `TestRestoreFromDatabase` | 2 | Database restoration |
| `TestCreateBackupFromDatabase` | 1 | Backup creation |

**Mocks**: `MagicMock()` for Execute and database manager, temporary files

---

## 6. `test_todo_i18n.py` — Internationalization (FR/EN)

**Type**: Unit test

| Class | # Tests | What is validated |
|---|---|---|
| `TestTranslations` | 3 | TRANSLATIONS dictionary completeness (all keys have `fr` and `en`, no empty values) |
| `TestT` | 4 | `t()` function: returns correct language, falls back to key if unknown |
| `TestGetLang` | 7 | Language detection: memory cache, `env_var.sh` reading, environment variable, fallback to `"fr"` |
| `TestSetLang` | 4 | Language persistence in `env_var.sh`, missing file handling |
| `TestLangIsConfigured` | 3 | Configuration state detection |

**Mocks**: `@patch.object` on `ENV_VAR_FILE`, `@patch.dict(os.environ)`, `setUp/tearDown` to reset `_current_lang`

---

## 7. `test_check_addons_exist.py` — Odoo addon validation

**Type**: Unit test (temporary files, no Odoo required)

| Class | # Tests | What is validated |
|---|---|---|
| `TestMainModuleFound` | 3 | Module found with valid `__manifest__.py`, JSON and formatted JSON output |
| `TestMainModuleMissing` | 2 | Missing module returns code 1, JSON output for missing module |
| `TestMainDuplicateModule` | 1 | Duplicate module in multiple paths returns code 2 |
| `TestMainMissingManifest` | 1 | Directory without `__manifest__.py` returns code 1 |
| `TestMainBadConfig` | 2 | INI config without `[options]` section or without `addons_path` key returns -1 |

**Mocks**: `@patch("sys.argv")`, temporary files for addons and INI config

---

## 8. `test_iscompatible.py` — Pip version compatibility

**Type**: Unit test (pure logic, no I/O)

| Class | # Tests | What is validated |
|---|---|---|
| `TestStringToTuple` | 4 | Version string to integer tuple conversion |
| `TestParseRequirements` | 7 | Parsing requirements.txt syntax (operators, multiple constraints, comments) |
| `TestIsCompatible` | 11 | Version compatibility checking with operators `==`, `>=`, `>`, `<`, `<=`, `!=` and ranges |

**Mocks**: None — pure functions

---

## 9. `test_format_file_to_commit.py` — Modified file detection for formatting

**Type**: Unit test (mocked git) + Integration test (`execute_shell` runs real processes)

| Class | # Tests | What is validated |
|---|---|---|
| `TestExecuteShell` | 5 | Shell command execution: success, failure (return code), stderr capture, empty output, multiline output |
| `TestGetModifiedFiles` | 9 | Parsing `git status --porcelain`: modified, added, deleted (ignored), ZIP/tar.gz (ignored), untracked, empty status, multiple statuses, git error |

**Mocks**: `@patch` on `subprocess.run`, `os.path.exists`, `os.path.isfile`

---

## 10. `test_version.py` — ERPLibre version management

**Type**: Unit test

| Class | # Tests | What is validated |
|---|---|---|
| `TestRemoveDotPath` | 6 | Removing `./` prefix from paths |
| `TestDie` | 3 | Conditional exit with configurable error code |
| `TestConstants` | 7 | Versioned file name templates (venv, manifest, pyproject, poetry lock, addons, odoo) |
| `TestUpdateValidateVersion` | 5 | Version resolution: explicit, by odoo_version, default fallback, detected version, expected paths |
| `TestUpdateDetectVersion` | 2 | Version detection: missing files, matching with `data_version` |
| `TestUpdatePrintLog` | 2 | Execution log display (empty and populated) |

**Mocks**: `@patch("sys.argv")`, temporary files for version files, `@patch` on path constants

---

## 11. `test_docker_update_version.py` — Docker version update

**Type**: Unit test (temporary files)

| Class | # Tests | What is validated |
|---|---|---|
| `TestEditText` | 2 | Image update in `docker-compose.yml` after ERPLibre service, other lines preserved |
| `TestEditDockerProd` | 3 | `FROM` line replacement in Dockerfile, RUN/COPY lines preserved, multi-FROM handling |

**Mocks**: None — uses `tempfile.NamedTemporaryFile` for Docker files

---

## 12. `test_code_generator_tools.py` — Code generator tools

**Type**: Unit test (pure AST and string logic)

| Class | # Tests | What is validated |
|---|---|---|
| `TestCountSpaceTab` | 9 | Indentation counting: spaces, tabs, mixed, `\n`/`\r`, custom group_space |
| `TestExtractLambda` | 2 | Lambda expression extraction from AST node, outer parentheses removal |
| `TestFillSearchField` | 11 | Recursive AST value extraction: Constant (str, int, bool), UnaryOp (negative), Name, Attribute, List, Dict, Tuple, Lambda, unsupported type |
| `TestSearchAndReplace` | 4 | Value replacement in Python code: quoted value, empty model, missing keyword, custom keyword |
| `TestArgsTypeParam` | 6 | ARGS_TYPE_PARAM dictionary validation for Odoo field types |

**Mocks**: None — pure functions on AST and strings

---

## 13. `test_database_tools.py` — Database tools

**Type**: Unit test (temporary files)

| Class | # Tests | What is validated |
|---|---|---|
| `TestProcessZip` | 4 | ZIP file processing: line removal by keyword, preservation when no match, total removal, non-targeted files intact |
| `TestCompareDatabaseApplicationLogic` | 4 | CSV set comparison: identical CSVs, different, empty, one empty |

**Mocks**: None — uses `tempfile` and `zipfile` for temporary files

---

## Coverage matrix by component

| Tested component | Source file | Test file | Type |
|---|---|---|---|
| `ConfigFile` | `script/config/config_file.py` | `test_config_file.py` | Unit |
| `Execute` | `script/execute/execute.py` | `test_execute.py` | Integration |
| `GitTool` | `script/git/git_tool.py` | `test_git_tool.py` | Unit |
| `kill_process_by_port` | `script/process/kill_process_by_port.py` | `test_kill_process_by_port.py` | Unit |
| `TODO` | `script/todo/todo.py` | `test_todo.py` | Unit |
| `todo_i18n` | `script/todo/todo_i18n.py` | `test_todo_i18n.py` | Unit |
| `check_addons_exist` | `script/addons/check_addons_exist.py` | `test_check_addons_exist.py` | Unit |
| `iscompatible` | `script/poetry/iscompatible.py` | `test_iscompatible.py` | Unit |
| `format_file_to_commit` | `script/maintenance/format_file_to_commit.py` | `test_format_file_to_commit.py` | Unit + Integration |
| `update_env_version` | `script/version/update_env_version.py` | `test_version.py` | Unit |
| `docker_update_version` | `script/docker/docker_update_version.py` | `test_docker_update_version.py` | Unit |
| Code Generator (tools) | `script/code_generator/search_class_model.py` | `test_code_generator_tools.py` | Unit |
| Database (tools) | `script/database/migrate/process_backup_file.py` | `test_database_tools.py` | Unit |

## Partially covered components

The following components have tests for their pure functions, but functions requiring infrastructure (Odoo, PostgreSQL, network) are not unit tested:

- `script/database/` — `process_zip` and CSV logic tested; `db_restore`, `image_db`, `list_remote` not tested (require Odoo/PostgreSQL)
- `script/code_generator/` — `extract_lambda`, `fill_search_field`, `search_and_replace`, `count_space_tab` tested; `generate_module`, `main` not tested (require Odoo)
- `script/poetry/` — `iscompatible`, `parse_requirements`, `string_to_tuple` tested; `combine_requirements`, `poetry_update.main` not tested (require full filesystem)

---

## Test patterns used

| Pattern | Usage |
|---|---|
| **Mocking (`@patch`)** | System dependency isolation (psutil, shutil, subprocess, os.path, files) |
| **Temporary files** | `tempfile.mkdtemp()` and `tempfile.NamedTemporaryFile()` for side-effect-free I/O testing |
| **Helper factory** | `_make_proc()` in test_kill_process, `_mock_git()` in test_format, `_write_csv()` in test_database |
| **Isolated state** | `setUp/tearDown` to reset globals between tests |
| **Real execution** | `test_execute.py` and `TestExecuteShell` launch real bash processes |
| **SimpleNamespace** | Lightweight config creation without argparse in test_docker |
| **AST inline** | `ast.parse(code, mode="eval").body` to create test AST nodes |
