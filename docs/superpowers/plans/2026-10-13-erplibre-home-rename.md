# ERPLibre Home Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the GNOME extension `streamdeck-tiler@technolibre.ca` ("Stream Deck Tiler") to `erplibre-home@technolibre.ca` ("ERPLibre Home"), move it to `script/gnome-extension/erplibre_home/`, and carry an existing workstation's state over to the new identity.

**Architecture:** A directory move that keeps every target working, then a mechanical identifier rename driven by an explicit ordered rule table, then a stdlib-only Python migration (`tools/migrate_legacy.py`) run first by `make erplibre_home_install_extension`, then a sync-file fallback in `lib/git-sync.js`, then the not-yet-started deployment spec and plan amended to the new names. A last manual task proves the migration on a workstation that runs the old extension.

**Tech Stack:** GJS ES modules (GNOME Shell 45–51), node `--test` for pure JS, Python 3 stdlib + `unittest` for the migration, GNU make, `gsettings`/`dconf`, `mmg` for bilingual docs.

**Spec:** `docs/superpowers/specs/2026-10-13-erplibre-home-rename-design.md`

## Global Constraints

- New UUID `erplibre-home@technolibre.ca`; name `ERPLibre Home`; description `ERPLibre for personal environment`.
- Schema id `org.gnome.shell.extensions.erplibre-home`, dconf path `/org/gnome/shell/extensions/erplibre-home/`.
- D-Bus object `/org/gnome/Shell/Extensions/ERPLibreHome`, interface `org.gnome.Shell.Extensions.ERPLibreHome`; journal prefix `[ERPLibreHome]`.
- gettext domain, `.pot`, `.mo`, data directories (config, state, cache), hook script and tag, CSS classes, hot-reload prefix: `erplibre-home`.
- Make variables `ERPLIBRE_HOME_*`; make targets `erplibre_home_*` with the old suffixes.
- Capitalisation: `ERPLibre` wherever the name carries capitals; `erplibre-home` in lower-case identifiers; `erplibre_home` in Python/make names.
- **Unchanged:** `make streamdeck_tiler` and `make streamdeck_tiler_unittest` (they run and test `game_tiler.py`), `game_tiler.py`'s file name, the games, `script/stream_deck/screenshots/`, the April 2026 docs under `docs/superpowers/`.
- Legacy identifiers survive only in `tools/migrate_legacy.py`, its test, the extension `CHANGELOG.md`, and the sync-file fallback in `lib/git-sync.js`.
- The migration exits 0 on every path; a failing command prints `migrate: warning: …` on stderr and the next step runs.
- Repo rules (CLAUDE.md): edit `.base.md`, regenerate with `source .venv.erplibre/bin/activate && mmg --yes <file>.base.md`; nothing identifying in code, comments, commits or docs; stage files by name, never `git add -A`; bilingual commit messages (English, `--- FR ---`, French subject under the same tag), `Assisted-by: Claude Opus 5.5` trailer, validated with `script/git/hooks/commit-msg <file>` then `git commit --no-verify -F <file>`.
- Commit identity: `git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit …`.
- Task 2's commit changes more than 500 lines: `AI_POLICY.md` requires the maintainer's agreement, obtained when this plan is approved.

## Review Focus

1. **A dangling symlink of the old UUID** (left by Task 1's move on any workstation that installed the old extension) must be removed by the migration, not skipped because `exists()` is false on it — Task 3 test `test_dangling_symlink_is_removed`.
2. **A `~/.claude/settings.json` that holds other tools' hooks** must keep every one of them when the legacy hook is replaced — Task 3 test `test_other_hooks_are_kept`.
3. **A machine without GNOME** (gsettings schema missing, `gsettings get` fails) must make the migration warn and exit 0, never block the install — Task 3 tests `test_gsettings_failure_warns_and_sets_nothing` and `test_main_without_bus_exits_zero_and_is_idempotent`.
4. **A sync repository shared with a workstation still on the old extension** holds only `streamdeck-tiler.json`; the import must read it, and prefer the new file when both exist — Task 4 tests.
5. **Both old and new data directories present** (a workstation where the new extension already ran once) must leave both untouched and say so — Task 3 test `test_conflict_leaves_both_and_warns`.

---

### Task 1: Move the extension directory, keep every target working

**Files:**
- Move: `script/stream_deck/gnome-extension/` → `script/gnome-extension/erplibre_home/`
- Modify (path strings only): `conf/make.streamdeck.Makefile:108`, `conf/make.test.Makefile:169,171`, `conf/make.installation.Makefile:193-195`, `script/gnome-extension/erplibre_home/indicators/device.js:151`, `script/gnome-extension/erplibre_home/indicators/erplibre.js:454,458`, `script/gnome-extension/erplibre_home/prefs.js:126,128`, `script/gnome-extension/erplibre_home/DEBUG.md:100`, `script/gnome-extension/erplibre_home/CHANGELOG.md` (the `[Unreleased]` link), `script/gnome-extension/erplibre_home/hooks/README.base.md:33,39`, `script/gnome-extension/erplibre_home/README.base.md:29-40` (screenshots link)
- Regenerate: `README.md`, `README.fr.md`, `hooks/README.md`, `hooks/README.fr.md` of the extension

**Interfaces:**
- Consumes: nothing.
- Produces: the extension lives at `script/gnome-extension/erplibre_home/`; every make target keeps its old name and works; identifiers are still the old ones.

- [ ] **Step 1: Move the directory**

```bash
cd "$(git rev-parse --show-toplevel)"
mkdir -p script/gnome-extension
git mv script/stream_deck/gnome-extension script/gnome-extension/erplibre_home
ls -A script/stream_deck/gnome-extension 2>/dev/null || echo "old directory gone"
```

Expected: `old directory gone`. If the old directory still exists, it may only hold gitignored build output (`schemas/gschemas.compiled`, `locale/`); list it, check that nothing else is there, then `rm -rf script/stream_deck/gnome-extension`.

- [ ] **Step 2: Fix the path strings**

The old and new directories sit at the same depth, so only strings that name the directory change. Run once from the checkout root:

```bash
python3 - <<'EOF'
import subprocess
from pathlib import Path

RULES = [
    ("stream_deck/gnome-extension", "gnome-extension/erplibre_home"),
    ("stream_deck\\/gnome-extension", "gnome-extension\\/erplibre_home"),
]
files = subprocess.run(
    ["git", "grep", "-l", "-e", "stream_deck/gnome-extension",
     "-e", "stream_deck\\\\/gnome-extension", "--", ".",
     ":!docs/superpowers"],
    capture_output=True, text=True, check=True).stdout.split()
for name in files:
    path = Path(name)
    base = path.name
    # A generated .md/.fr.md is rebuilt from its .base.md, never edited.
    stem = base[:-6] if base.endswith(".fr.md") else base[:-3]
    if base.endswith(".md") and not base.endswith(".base.md") \
            and (path.parent / f"{stem}.base.md").exists():
        continue
    text = path.read_text(encoding="utf-8")
    for old, new in RULES:
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")
    print("fixed", name)
EOF
sed -i 's#`\.\./screenshots/#`../../stream_deck/screenshots/#g' \
    script/gnome-extension/erplibre_home/README.base.md
source .venv.erplibre/bin/activate
mmg --yes script/gnome-extension/erplibre_home/README.base.md
mmg --yes script/gnome-extension/erplibre_home/hooks/README.base.md
deactivate
```

Expected: `fixed` lines for the three Makefile fragments, `device.js`, `erplibre.js`, `prefs.js`, `DEBUG.md`, `CHANGELOG.md`, `hooks/README.base.md`, `ARCHITECTURE.md` if it names the path; `mmg` rewrites the four generated READMEs.

- [ ] **Step 3: Check that no reference to the old directory is left**

```bash
git grep -n -e 'stream_deck/gnome-extension' -e 'stream_deck\\/gnome-extension' -- . ':!docs/superpowers'
grep -n 'screenshots' script/gnome-extension/erplibre_home/README.md
```

Expected: the first command prints nothing; the second shows `../../stream_deck/screenshots/`. `indicators/erplibre.js:454` still says the root is three directories up, which stays true.

- [ ] **Step 4: Run the tests**

```bash
make test_gnome_extension 2>&1 | tail -5
make streamdeck_tiler_e2e_nested
```

Expected: `# pass 212`, `# fail 0`; then `ok: GNOME Shell 51.0: ACTIVE, D-Bus up, every indicator mounted` (any GNOME 45–51 version string is fine). `make streamdeck_tiler_e2e_nested` needs `gnome-shell`, `dbus-launch`, `gdbus` and a GNOME install; on a host without them it exits 1 with `skip:`, and the task then relies on the node tests only — say so in the report.

- [ ] **Step 5: Commit**

```bash
git add script/stream_deck/gnome-extension script/gnome-extension/erplibre_home \
    conf/make.streamdeck.Makefile conf/make.test.Makefile conf/make.installation.Makefile
git status --short
```

Expected: every staged entry is a rename (`R`) or one of the files listed above. Message file:

```
[MOV] gnome extension: moved to script/gnome-extension/erplibre_home

The extension is no longer a part of the Stream Deck scripts: it becomes
the desktop side of ERPLibre Home, next to the mobile app. The directory
moves alone with the strings that name it, so git keeps its history and
every make target still works under its current name. The old and new
directories sit at the same depth: paths that climb to the checkout root
are unchanged. Node tests and the headless smoke test pass.

--- FR ---

[MOV] extension gnome : dossier script/gnome-extension/erplibre_home

L'extension ne fait plus partie des scripts Stream Deck : elle devient le
côté bureau d'ERPLibre Home, à côté de l'app mobile. Le dossier se
déplace seul avec les chaînes qui le nomment, git garde son historique et
chaque cible make marche encore sous son nom actuel. L'ancien et le
nouveau dossier ont la même profondeur : les chemins qui remontent à la
racine du checkout ne changent pas. Tests node et test headless verts.

Assisted-by: Claude Opus 5.5
```

```bash
script/git/hooks/commit-msg "$MSG" && \
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$MSG"
```

(`$MSG` is the path of the message file, written outside the repository.)

---

### Task 2: Rename every identifier to ERPLibre Home

**Files:**
- Rename: `script/gnome-extension/erplibre_home/schemas/org.gnome.shell.extensions.streamdeck-tiler.gschema.xml` → `…erplibre-home.gschema.xml`; `po/streamdeck-tiler.pot` → `po/erplibre-home.pot`; `hooks/streamdeck-tiler-hook.py` → `hooks/erplibre-home-hook.py`
- Modify (mechanical): every tracked text file outside `docs/superpowers/` that names a legacy identifier — the extension's JS, `po/`, docs, `dev_nested.sh`, `test/e2e_nested.sh`, `test/manual.md`, `hooks/`, `scripts/firefox_youtube_tabs.py`; `script/stream_deck/{game_tiler.py,erplibre_controller.py,translator.py,requirements.txt,INSTALL.base.md,gpt.base.md,screenshots/capture.sh}`; `conf/make.{streamdeck,test,installation}.Makefile`
- Modify (by hand): `metadata.json` description, `test/e2e_nested.sh` sandbox prefix, extension `CHANGELOG.md`
- Regenerate: `script/stream_deck/INSTALL.{md,fr.md}`, `script/stream_deck/gpt.{md,fr.md}`, the extension's two README pairs

**Interfaces:**
- Consumes: Task 1's directory `script/gnome-extension/erplibre_home/`.
- Produces: the names of the Global Constraints, notably make variable `ERPLIBRE_HOME_EXT_SRC`, targets `erplibre_home_install_extension`, `erplibre_home_enable_extension`, `erplibre_home_uninstall_extension`, `erplibre_home_e2e_nested`, `erplibre_home_compile_locale`; hook script `hooks/erplibre-home-hook.py`; sync file name `erplibre-home.json` written by `extension.js`.

- [ ] **Step 1: Rename the three files whose names carry the old identifier**

```bash
E=script/gnome-extension/erplibre_home
git mv $E/schemas/org.gnome.shell.extensions.streamdeck-tiler.gschema.xml \
       $E/schemas/org.gnome.shell.extensions.erplibre-home.gschema.xml
git mv $E/po/streamdeck-tiler.pot $E/po/erplibre-home.pot
git mv $E/hooks/streamdeck-tiler-hook.py $E/hooks/erplibre-home-hook.py
test -x $E/hooks/erplibre-home-hook.py && echo "hook still executable"
```

Expected: `hook still executable`.

- [ ] **Step 2: Rewrite the identifiers**

Save this script outside the repository (for example `$(mktemp -d)/rename_identifiers.py`) and run it from the checkout root. The rule order matters: upper-case and underscore forms first, the bare hyphen form last; `streamdeck_tiler_unittest` is protected because it tests `game_tiler.py`, and the bare `streamdeck_tiler` game target never matches a rule because every underscore rule needs the trailing `_`.

```python
#!/usr/bin/env python3
"""One-shot rename of the extension identifiers in tracked text files."""

import subprocess
from pathlib import Path

PROTECT = ["streamdeck_tiler_unittest"]
RULES = [
    ("STREAMDECK_TILER_", "ERPLIBRE_HOME_"),
    ("streamdeck_tiler_", "erplibre_home_"),
    ("StreamDeckTiler", "ERPLibreHome"),
    ("Stream Deck Tiler", "ERPLibre Home"),
    ("streamdeck-tiler", "erplibre-home"),
]
SKIP_PREFIXES = ("docs/superpowers/",)
SKIP_FILES = {"script/gnome-extension/erplibre_home/CHANGELOG.md"}


def is_generated_md(path: Path) -> bool:
    name = path.name
    if not name.endswith(".md") or name.endswith(".base.md"):
        return False
    stem = name[:-6] if name.endswith(".fr.md") else name[:-3]
    return (path.parent / f"{stem}.base.md").exists()


def main() -> None:
    pattern = "|".join(old for old, _ in RULES)
    files = subprocess.run(
        ["git", "grep", "-l", "-E", pattern], capture_output=True,
        text=True).stdout.split()
    for name in files:
        if name.startswith(SKIP_PREFIXES) or name in SKIP_FILES:
            continue
        path = Path(name)
        if is_generated_md(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        before = text
        for i, word in enumerate(PROTECT):
            text = text.replace(word, f"\0PROTECT{i}\0")
        for old, new in RULES:
            text = text.replace(old, new)
        for i, word in enumerate(PROTECT):
            text = text.replace(f"\0PROTECT{i}\0", word)
        if text != before:
            path.write_text(text, encoding="utf-8")
            print("renamed in", name)


if __name__ == "__main__":
    main()
```

```bash
python3 "$RENAME_SCRIPT"
```

Expected: about 45 `renamed in` lines, none under `docs/superpowers/`.

- [ ] **Step 3: The three hand edits**

1. `script/gnome-extension/erplibre_home/metadata.json`: set
   `"description": "ERPLibre for personal environment",`. The rest already reads
   `"uuid": "erplibre-home@technolibre.ca"`, `"name": "ERPLibre Home"`,
   `"gettext-domain": "erplibre-home"`,
   `"settings-schema": "org.gnome.shell.extensions.erplibre-home"`.
2. `script/gnome-extension/erplibre_home/test/e2e_nested.sh`: replace both
   `sdt-e2e` with `erh-e2e` (the `mktemp` template and `--wayland-display`).
3. `script/gnome-extension/erplibre_home/CHANGELOG.md`: under `## [Unreleased]`,
   add before `### Added`:

```markdown
### Changed
- The extension is now **ERPLibre Home** (`erplibre-home@technolibre.ca`),
  in `script/gnome-extension/erplibre_home/`. Every identifier follows:
  schema `org.gnome.shell.extensions.erplibre-home`, D-Bus interface
  `org.gnome.Shell.Extensions.ERPLibreHome`, journal prefix
  `[ERPLibreHome]`, data under `erplibre-home/` in the XDG config, state
  and cache directories, make targets `erplibre_home_*`. It replaces
  `streamdeck-tiler@technolibre.ca` ("Stream Deck Tiler");
  `make erplibre_home_install_extension` carries an existing
  installation over.
```

- [ ] **Step 4: Regenerate the bilingual docs and the compiled schema**

```bash
source .venv.erplibre/bin/activate
for f in script/stream_deck/INSTALL.base.md script/stream_deck/gpt.base.md \
         script/gnome-extension/erplibre_home/README.base.md \
         script/gnome-extension/erplibre_home/hooks/README.base.md; do
    mmg --yes "$f"
done
deactivate
glib-compile-schemas --strict script/gnome-extension/erplibre_home/schemas/
```

Expected: `mmg` rewrites the generated pairs; `glib-compile-schemas` prints nothing.

- [ ] **Step 5: Check that no legacy identifier is left**

```bash
git grep -n -E 'streamdeck-tiler|StreamDeckTiler|streamdeck_tiler_|STREAMDECK_TILER_|Stream Deck Tiler|stream_deck/gnome-extension' \
    -- . ':!docs/superpowers' ':!script/gnome-extension/erplibre_home/CHANGELOG.md' \
    | grep -v 'streamdeck_tiler_unittest'
grep -n -E '^streamdeck_tiler:|^streamdeck_tiler_unittest:' conf/make.streamdeck.Makefile
python3 -m py_compile script/stream_deck/game_tiler.py script/stream_deck/erplibre_controller.py \
    script/stream_deck/translator.py script/gnome-extension/erplibre_home/hooks/*.py \
    script/gnome-extension/erplibre_home/po/compile_locales.py
```

Expected: the first command prints nothing; the second prints both game targets; `py_compile` prints nothing.

- [ ] **Step 6: Run the tests**

```bash
make test_gnome_extension 2>&1 | tail -5
make erplibre_home_e2e_nested
make streamdeck_tiler_unittest 2>&1 | tail -3
```

Expected: `# pass 212`, `# fail 0`; `ok: GNOME Shell 51.0: ACTIVE, D-Bus up, every indicator mounted`; the game tests end with `OK`. The e2e script now checks the new UUID, calls `org.gnome.Shell.Extensions.ERPLibreHome.DebugClaudeIndex` and greps `\[ERPLibreHome\] mount .* failed`; open it to confirm all three after the rename.

- [ ] **Step 7: Hygiene and commit**

```bash
git add -u
git status --short
python3 script/analyse/check_comment_hygiene.py --staged
git diff --cached --shortstat
```

`git add -u` stages only tracked files, which is the whole of this rename; `git status --short` must show no untracked file you meant to add. Expected hygiene: no 🔴 finding. The shortstat exceeds 500 lines; the maintainer agreed to it when approving this plan. Message:

```
[REF] gnome extension: identifiers renamed to ERPLibre Home

The extension carries six indicators, a D-Bus interface and Claude hooks;
its window tiling name no longer described it. UUID, schema and dconf
path, D-Bus interface, journal prefix, gettext domain, data directories,
hook script, CSS classes and make targets all take the erplibre-home
form. make streamdeck_tiler and streamdeck_tiler_unittest keep their
names: they run and test game_tiler.py, not the extension. Node tests,
the game tests and the headless smoke test pass under the new UUID.

--- FR ---

[REF] extension gnome : identifiants renommés en ERPLibre Home

L'extension porte six indicateurs, une interface D-Bus et des hooks
Claude ; son nom de tuilage ne la décrivait plus. UUID, schéma et chemin
dconf, interface D-Bus, préfixe de journal, domaine gettext, dossiers de
données, script de hook, classes CSS et cibles make prennent la forme
erplibre-home. make streamdeck_tiler et streamdeck_tiler_unittest gardent
leur nom : ils lancent et testent game_tiler.py, pas l'extension. Tests
node, tests du jeu et test headless verts sous le nouvel UUID.

Assisted-by: Claude Opus 5.5
```

```bash
script/git/hooks/commit-msg "$MSG" && \
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$MSG"
```

---

### Task 3: Migrate an existing installation

**Files:**
- Create: `script/gnome-extension/erplibre_home/tools/migrate_legacy.py` (mode 755)
- Create: `test/test_erplibre_home_migrate_legacy.py`
- Modify: `conf/make.streamdeck.Makefile` (first line of the `erplibre_home_install_extension` recipe)

**Interfaces:**
- Consumes: `hooks/install_claude_hooks.py` module-level `SETTINGS: Path`, `HOOK_PATH: Path`, `install(data: dict, command: str) -> int`, `remove(data: dict, command: str) -> int`, `backup(data: dict) -> Path | None`, `write(data: dict) -> None` (unchanged by this plan); Task 2's target `erplibre_home_install_extension` and variable `ERPLIBRE_HOME_EXT_SRC`.
- Produces: `migrate_legacy.py` with `parse_strv(text: str) -> list[str]`, `format_strv(items: list[str]) -> str`, `plan_enabled(current: list[str]) -> list[str] | None`, `legacy_extension_entries(names: list[str]) -> list[str]`, `plan_dconf(old_dump: str, new_dump: str) -> bool`, `plan_data_dir(src: Path, dst: Path) -> str | None`, `legacy_hook_commands(settings: dict) -> list[str]`, `xdg_bases(env: dict, home: Path) -> list[Path]`, `extensions_dir(env: dict, home: Path) -> Path`, `session_bus_env(env: dict) -> dict | None`, `migrate_enabled(run, say, warn) -> None`, `migrate_dconf(run, say, warn) -> None`, `migrate_data_dirs(bases: list[Path], say, warn) -> None`, `remove_legacy_extensions(ext_dir: Path, say, warn) -> None`, `migrate_hooks(installer, say, warn) -> None`, `main() -> int`. A runner is `run(cmd: list[str], stdin: str | None = None) -> tuple[int, str]`.

- [ ] **Step 1: Write the failing tests**

Create `test/test_erplibre_home_migrate_legacy.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Migration of a workstation from the extension's previous identity.

The extension was ``streamdeck-tiler@technolibre.ca`` before it became
``erplibre-home@technolibre.ca``. These tests hold the decisions of each
step on the inputs a workstation can present: nothing to migrate, the old
state only, the new state only, both, and no session bus. Every step must
be idempotent and the script must never fail the install that follows.
"""

import importlib.util
import json
import os
import socket
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXT = ROOT / "script" / "gnome-extension" / "erplibre_home"
SCRIPT = EXT / "tools" / "migrate_legacy.py"


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


mig = _load("migrate_legacy", SCRIPT)

OLD = "streamdeck-tiler@technolibre.ca"
NEW = "erplibre-home@technolibre.ca"


class Recorder:
    """Collects say/warn lines and answers runner calls from a table."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.calls = []
        self.said = []
        self.warned = []

    def run(self, cmd, stdin=None):
        self.calls.append((tuple(cmd), stdin))
        return self.answers.get(tuple(cmd), (0, ""))

    def say(self, msg):
        self.said.append(msg)

    def warn(self, msg):
        self.warned.append(msg)


class TestStrv(unittest.TestCase):
    def test_empty_typed_list(self):
        self.assertEqual(mig.parse_strv("@as []\n"), [])

    def test_list(self):
        self.assertEqual(mig.parse_strv(f"['a@x', '{OLD}']\n"), ["a@x", OLD])

    def test_round_trip(self):
        items = ["a@x", NEW]
        self.assertEqual(mig.parse_strv(mig.format_strv(items)), items)


class TestPlanEnabled(unittest.TestCase):
    def test_absent_means_nothing_to_do(self):
        self.assertIsNone(mig.plan_enabled(["a@x", NEW]))

    def test_replaced_in_place(self):
        self.assertEqual(mig.plan_enabled(["a@x", OLD, "b@y"]),
                         ["a@x", NEW, "b@y"])

    def test_new_already_after_drops_old(self):
        self.assertEqual(mig.plan_enabled([OLD, "a@x", NEW]), [NEW, "a@x"])

    def test_new_already_before_drops_old(self):
        self.assertEqual(mig.plan_enabled([NEW, "a@x", OLD]), [NEW, "a@x"])


class TestLegacyExtensionEntries(unittest.TestCase):
    def test_picks_uuid_and_reload_copies_only(self):
        names = [OLD, NEW, "streamdeck-tiler-reload-123@technolibre.ca",
                 "streamdeck-tiler-reload-9@elsewhere.org", "other@x"]
        self.assertEqual(
            mig.legacy_extension_entries(names),
            ["streamdeck-tiler-reload-123@technolibre.ca", OLD])


class TestPlanDconf(unittest.TestCase):
    def test_nothing_on_either_side(self):
        self.assertFalse(mig.plan_dconf("", ""))

    def test_old_only(self):
        self.assertTrue(mig.plan_dconf("[/]\nenable-media=true\n", ""))

    def test_new_already_set(self):
        self.assertFalse(mig.plan_dconf("[/]\na=1\n", "[/]\nb=2\n"))

    def test_whitespace_is_empty(self):
        self.assertFalse(mig.plan_dconf("\n  \n", ""))


class TestDataDirs(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.bases = [self.tmp / "config", self.tmp / "state",
                      self.tmp / "cache"]
        for base in self.bases:
            base.mkdir()

    def test_old_only_is_moved_with_its_content(self):
        (self.bases[1] / "streamdeck-tiler" / "claude").mkdir(parents=True)
        (self.bases[1] / "streamdeck-tiler" / "log.jsonl").write_text("x")
        rec = Recorder()
        mig.migrate_data_dirs(self.bases, rec.say, rec.warn)
        self.assertFalse((self.bases[1] / "streamdeck-tiler").exists())
        self.assertEqual(
            (self.bases[1] / "erplibre-home" / "log.jsonl").read_text(), "x")
        self.assertTrue((self.bases[1] / "erplibre-home" / "claude").is_dir())
        self.assertEqual(len(rec.said), 1)
        rec2 = Recorder()
        mig.migrate_data_dirs(self.bases, rec2.say, rec2.warn)
        self.assertEqual((rec2.said, rec2.warned), ([], []))

    def test_conflict_leaves_both_and_warns(self):
        (self.bases[0] / "streamdeck-tiler").mkdir()
        (self.bases[0] / "erplibre-home").mkdir()
        rec = Recorder()
        mig.migrate_data_dirs(self.bases, rec.say, rec.warn)
        self.assertTrue((self.bases[0] / "streamdeck-tiler").is_dir())
        self.assertTrue((self.bases[0] / "erplibre-home").is_dir())
        self.assertEqual(len(rec.warned), 1)
        self.assertIn("streamdeck-tiler", rec.warned[0])

    def test_nothing_to_do_says_nothing(self):
        rec = Recorder()
        mig.migrate_data_dirs(self.bases, rec.say, rec.warn)
        self.assertEqual((rec.said, rec.warned), ([], []))


class TestRemoveLegacyExtensions(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.ext = self.tmp / "extensions"
        self.ext.mkdir()
        self.target = self.tmp / "checkout-ext"
        self.target.mkdir()
        (self.target / "keep.txt").write_text("k")

    def test_symlink_removed_target_untouched(self):
        (self.ext / OLD).symlink_to(self.target)
        rec = Recorder()
        mig.remove_legacy_extensions(self.ext, rec.say, rec.warn)
        self.assertFalse((self.ext / OLD).is_symlink())
        self.assertEqual((self.target / "keep.txt").read_text(), "k")

    def test_dangling_symlink_is_removed(self):
        (self.ext / OLD).symlink_to(self.tmp / "moved-away")
        rec = Recorder()
        mig.remove_legacy_extensions(self.ext, rec.say, rec.warn)
        self.assertFalse((self.ext / OLD).is_symlink())
        self.assertEqual(len(rec.said), 1)

    def test_reload_copy_removed_new_kept(self):
        reload_dir = self.ext / "streamdeck-tiler-reload-7@technolibre.ca"
        reload_dir.mkdir()
        (reload_dir / "extension.js").write_text("")
        (self.ext / NEW).symlink_to(self.target)
        rec = Recorder()
        mig.remove_legacy_extensions(self.ext, rec.say, rec.warn)
        self.assertFalse(reload_dir.exists())
        self.assertTrue((self.ext / NEW).is_symlink())

    def test_missing_directory_is_fine(self):
        rec = Recorder()
        mig.remove_legacy_extensions(self.tmp / "nope", rec.say, rec.warn)
        self.assertEqual((rec.said, rec.warned), ([], []))


GET = ("gsettings", "get", "org.gnome.shell", "enabled-extensions")


class TestMigrateEnabled(unittest.TestCase):
    def test_sets_the_replaced_list(self):
        rec = Recorder({GET: (0, f"['a@x', '{OLD}']\n")})
        mig.migrate_enabled(rec.run, rec.say, rec.warn)
        self.assertEqual(rec.calls[-1][0], (
            "gsettings", "set", "org.gnome.shell", "enabled-extensions",
            f"['a@x', '{NEW}']"))
        self.assertEqual(len(rec.said), 1)

    def test_nothing_to_do_sets_nothing(self):
        rec = Recorder({GET: (0, f"['{NEW}']\n")})
        mig.migrate_enabled(rec.run, rec.say, rec.warn)
        self.assertEqual([c[0] for c in rec.calls], [GET])
        self.assertEqual(rec.said, [])

    def test_gsettings_failure_warns_and_sets_nothing(self):
        rec = Recorder({GET: (1, "No such schema “org.gnome.shell”")})
        mig.migrate_enabled(rec.run, rec.say, rec.warn)
        self.assertEqual([c[0] for c in rec.calls], [GET])
        self.assertEqual(len(rec.warned), 1)


DUMP_OLD = ("dconf", "dump", "/org/gnome/shell/extensions/streamdeck-tiler/")
DUMP_NEW = ("dconf", "dump", "/org/gnome/shell/extensions/erplibre-home/")
LOAD_NEW = ("dconf", "load", "/org/gnome/shell/extensions/erplibre-home/")


class TestMigrateDconf(unittest.TestCase):
    def test_copies_old_into_empty_new(self):
        dump = "[/]\nenable-media=true\n"
        rec = Recorder({DUMP_OLD: (0, dump), DUMP_NEW: (0, "")})
        mig.migrate_dconf(rec.run, rec.say, rec.warn)
        self.assertIn((LOAD_NEW, dump), rec.calls)
        self.assertEqual(len(rec.said), 1)

    def test_new_already_set_loads_nothing(self):
        rec = Recorder({DUMP_OLD: (0, "[/]\na=1\n"),
                        DUMP_NEW: (0, "[/]\nb=2\n")})
        mig.migrate_dconf(rec.run, rec.say, rec.warn)
        self.assertNotIn(LOAD_NEW, [c[0] for c in rec.calls])

    def test_dump_failure_warns(self):
        rec = Recorder({DUMP_OLD: (1, "error")})
        mig.migrate_dconf(rec.run, rec.say, rec.warn)
        self.assertNotIn(LOAD_NEW, [c[0] for c in rec.calls])
        self.assertEqual(len(rec.warned), 1)


class TestHooks(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.installer = _load(
            "install_claude_hooks", EXT / "hooks" / "install_claude_hooks.py")
        self.installer.SETTINGS = self.tmp / ".claude" / "settings.json"
        self.installer.SETTINGS.parent.mkdir()
        self.new_cmd = str(self.installer.HOOK_PATH)
        self.old_cmd = ("/somewhere/script/stream_deck/gnome-extension/"
                        "hooks/streamdeck-tiler-hook.py")

    def _write(self, data):
        self.installer.SETTINGS.write_text(json.dumps(data), encoding="utf-8")

    def _read(self):
        return json.loads(self.installer.SETTINGS.read_text(encoding="utf-8"))

    def _commands(self, data):
        return [h["command"] for ms in data.get("hooks", {}).values()
                for m in ms for h in m["hooks"]]

    def test_legacy_replaced_by_new(self):
        self._write({"hooks": {"Stop": [{"hooks": [
            {"type": "command", "command": self.old_cmd}]}]}})
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        commands = self._commands(self._read())
        self.assertNotIn(self.old_cmd, commands)
        self.assertIn(self.new_cmd, commands)
        self.assertEqual(len(rec.said), 1)
        backups = list(self.installer.SETTINGS.parent.glob("settings.json.bak-*"))
        self.assertEqual(len(backups), 1)

    def test_other_hooks_are_kept(self):
        other = "/usr/local/bin/some-other-hook"
        self._write({"model": "x", "hooks": {"Stop": [
            {"hooks": [{"type": "command", "command": other}]},
            {"hooks": [{"type": "command", "command": self.old_cmd}]}]}})
        mig.migrate_hooks(self.installer, Recorder().say, Recorder().warn)
        data = self._read()
        self.assertEqual(data["model"], "x")
        self.assertIn(other, self._commands(data))

    def test_without_legacy_entry_file_untouched(self):
        self._write({"hooks": {}})
        before = self.installer.SETTINGS.read_bytes()
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        self.assertEqual(self.installer.SETTINGS.read_bytes(), before)
        self.assertEqual(rec.said, [])

    def test_missing_settings_is_fine(self):
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        self.assertFalse(self.installer.SETTINGS.exists())
        self.assertEqual((rec.said, rec.warned), ([], []))

    def test_invalid_json_warns(self):
        self.installer.SETTINGS.write_text("{", encoding="utf-8")
        rec = Recorder()
        mig.migrate_hooks(self.installer, rec.say, rec.warn)
        self.assertEqual(len(rec.warned), 1)


class TestSessionBus(unittest.TestCase):
    def test_address_in_environment(self):
        env = {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/x/bus"}
        self.assertEqual(mig.session_bus_env(env), env)

    def test_no_address_no_socket(self):
        tmp = tempfile.mkdtemp()
        self.assertIsNone(mig.session_bus_env({"XDG_RUNTIME_DIR": tmp}))

    def test_socket_in_runtime_dir(self):
        tmp = tempfile.mkdtemp()
        sock = socket.socket(socket.AF_UNIX)
        sock.bind(os.path.join(tmp, "bus"))
        self.addCleanup(sock.close)
        env = mig.session_bus_env({"XDG_RUNTIME_DIR": tmp})
        self.assertEqual(env["DBUS_SESSION_BUS_ADDRESS"],
                         f"unix:path={tmp}/bus")


class TestMain(unittest.TestCase):
    def test_main_without_bus_exits_zero_and_is_idempotent(self):
        home = Path(tempfile.mkdtemp())
        (home / ".local" / "state" / "streamdeck-tiler").mkdir(parents=True)
        runtime = tempfile.mkdtemp()
        env = {"HOME": str(home), "XDG_RUNTIME_DIR": runtime,
               "PATH": os.environ.get("PATH", "")}
        first = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                               capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertTrue((home / ".local" / "state" / "erplibre-home").is_dir())
        self.assertIn("no session bus", first.stdout)
        second = subprocess.run([sys.executable, str(SCRIPT)], env=env,
                                capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(second.stdout.strip().splitlines(),
                         [line for line in first.stdout.strip().splitlines()
                          if "no session bus" in line])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./script/test/run_unit_test.sh test/test_erplibre_home_migrate_legacy.py`
Expected: FAIL at import, `FileNotFoundError` (or `No such file or directory`) on `tools/migrate_legacy.py`.

- [ ] **Step 3: Write the migration**

Create `script/gnome-extension/erplibre_home/tools/migrate_legacy.py`, then `chmod 755` it:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Carry a workstation's state over from the extension's previous identity.

The extension was ``streamdeck-tiler@technolibre.ca`` before it became
``erplibre-home@technolibre.ca``. A workstation that ran it keeps, under
the old names: its entry in ``enabled-extensions``, a symlink (and maybe
hot-reload copies) in the extensions directory, a dconf path, data in the
XDG config, state and cache directories, and Claude hook entries pointing
at the old hook script. Each step below moves one of them over.

A pure function decides each step; the ``migrate_*`` functions apply the
decision. Every step is idempotent: a second run prints nothing but the
no-bus line. A failing command prints a warning and the next step runs;
the script always exits 0, so it never blocks the install that follows.
Uses the standard library only: it runs before any venv exists.
"""

from __future__ import annotations

import ast
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

LEGACY_UUID = "streamdeck-tiler@technolibre.ca"
NEW_UUID = "erplibre-home@technolibre.ca"
LEGACY_RELOAD_PREFIX = "streamdeck-tiler-reload-"
UUID_DOMAIN = "@technolibre.ca"
LEGACY_DCONF = "/org/gnome/shell/extensions/streamdeck-tiler/"
NEW_DCONF = "/org/gnome/shell/extensions/erplibre-home/"
LEGACY_DIR = "streamdeck-tiler"
NEW_DIR = "erplibre-home"
LEGACY_HOOK_SUFFIX = "/streamdeck-tiler-hook.py"

EXT_ROOT = Path(__file__).resolve().parent.parent
HOOKS_INSTALLER = EXT_ROOT / "hooks" / "install_claude_hooks.py"


def parse_strv(text: str) -> list[str]:
    """Parse the string array ``gsettings get`` prints.

    ``@as []`` is the empty array; any other value is a list literal of
    single-quoted strings, which Python reads as is.
    """
    text = text.strip()
    if text.startswith("@as"):
        text = text[3:].strip()
    return [str(item) for item in ast.literal_eval(text)] if text else []


def format_strv(items: list[str]) -> str:
    """The inverse of parse_strv, as ``gsettings set`` accepts it."""
    return "[" + ", ".join(repr(item) for item in items) + "]"


def plan_enabled(current: list[str]) -> list[str] | None:
    """The enabled-extensions list with the old UUID replaced in place.

    Returns None when the old UUID is not listed. When the new UUID is
    already listed, the old one is dropped; order is otherwise kept.
    """
    if LEGACY_UUID not in current:
        return None
    out: list[str] = []
    for uuid in current:
        if uuid == LEGACY_UUID:
            uuid = NEW_UUID
        if uuid not in out:
            out.append(uuid)
    return out


def legacy_extension_entries(names: list[str]) -> list[str]:
    """Entries of the extensions directory that belong to the old UUID."""
    return sorted(
        name for name in names
        if name == LEGACY_UUID
        or (name.startswith(LEGACY_RELOAD_PREFIX)
            and name.endswith(UUID_DOMAIN)))


def plan_dconf(old_dump: str, new_dump: str) -> bool:
    """Copy the old dconf path only into a new path that holds no key."""
    return bool(old_dump.strip()) and not new_dump.strip()


def plan_data_dir(src: Path, dst: Path) -> str | None:
    """'move', 'conflict' when both exist, or None when src is absent."""
    if not (src.exists() or src.is_symlink()):
        return None
    if dst.exists() or dst.is_symlink():
        return "conflict"
    return "move"


def legacy_hook_commands(settings: dict) -> list[str]:
    """Hook commands in a Claude settings dict that run the old script."""
    found: list[str] = []
    hooks = settings.get("hooks")
    if not isinstance(hooks, dict):
        return found
    for matchers in hooks.values():
        if not isinstance(matchers, list):
            continue
        for matcher in matchers:
            if not isinstance(matcher, dict):
                continue
            for hook in matcher.get("hooks") or []:
                command = hook.get("command") if isinstance(hook, dict) \
                    else None
                if isinstance(command, str) \
                        and command.endswith(LEGACY_HOOK_SUFFIX) \
                        and command not in found:
                    found.append(command)
    return found


def xdg_bases(env: dict, home: Path) -> list[Path]:
    """The XDG config, state and cache directories, in that order."""
    return [
        Path(env.get("XDG_CONFIG_HOME") or home / ".config"),
        Path(env.get("XDG_STATE_HOME") or home / ".local" / "state"),
        Path(env.get("XDG_CACHE_HOME") or home / ".cache"),
    ]


def extensions_dir(env: dict, home: Path) -> Path:
    data = Path(env.get("XDG_DATA_HOME") or home / ".local" / "share")
    return data / "gnome-shell" / "extensions"


def session_bus_env(env: dict) -> dict | None:
    """The environment to reach the session bus with, or None.

    An address already in the environment wins. Otherwise the user bus
    socket under XDG_RUNTIME_DIR (``/run/user/<uid>`` by default) is the
    one a systemd-managed desktop session uses, also from an ssh login.
    """
    if env.get("DBUS_SESSION_BUS_ADDRESS"):
        return dict(env)
    runtime = env.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    sock = Path(runtime) / "bus"
    if sock.is_socket():
        return {**env, "DBUS_SESSION_BUS_ADDRESS": f"unix:path={sock}"}
    return None


def make_runner(env: dict):
    """A runner: run(cmd, stdin=None) -> (returncode, stdout or error)."""
    def run(cmd: list[str], stdin: str | None = None) -> tuple[int, str]:
        try:
            proc = subprocess.run(cmd, input=stdin, capture_output=True,
                                  text=True, timeout=30, env=env)
        except (OSError, subprocess.TimeoutExpired) as exc:
            return 127, str(exc)
        if proc.returncode:
            return proc.returncode, (proc.stderr or proc.stdout).strip()
        return 0, proc.stdout
    return run


def migrate_enabled(run, say, warn) -> None:
    rc, out = run(["gsettings", "get", "org.gnome.shell",
                   "enabled-extensions"])
    if rc:
        warn(f"enabled-extensions not read: {out}")
        return
    try:
        new = plan_enabled(parse_strv(out))
    except (ValueError, SyntaxError) as exc:
        warn(f"enabled-extensions not understood: {exc}")
        return
    if new is None:
        return
    rc, err = run(["gsettings", "set", "org.gnome.shell",
                   "enabled-extensions", format_strv(new)])
    if rc:
        warn(f"enabled-extensions not written: {err}")
        return
    say(f"enabled-extensions: {LEGACY_UUID} replaced by {NEW_UUID}")


def migrate_dconf(run, say, warn) -> None:
    rc_old, old = run(["dconf", "dump", LEGACY_DCONF])
    rc_new, new = run(["dconf", "dump", NEW_DCONF]) if not rc_old \
        else (rc_old, old)
    if rc_old or rc_new:
        warn(f"dconf not read: {old if rc_old else new}")
        return
    if not plan_dconf(old, new):
        return
    rc, err = run(["dconf", "load", NEW_DCONF], stdin=old)
    if rc:
        warn(f"dconf not written: {err}")
        return
    say(f"dconf: {LEGACY_DCONF} copied to {NEW_DCONF}")


def migrate_data_dirs(bases: list[Path], say, warn) -> None:
    for base in bases:
        src, dst = base / LEGACY_DIR, base / NEW_DIR
        action = plan_data_dir(src, dst)
        if action == "move":
            try:
                os.rename(src, dst)
            except OSError as exc:
                warn(f"{src} not moved: {exc}")
                continue
            say(f"{src} moved to {dst}")
        elif action == "conflict":
            warn(f"{src} and {dst} both exist, both left as they are")


def remove_legacy_extensions(ext_dir: Path, say, warn) -> None:
    if not ext_dir.is_dir():
        return
    names = [entry.name for entry in ext_dir.iterdir()]
    for name in legacy_extension_entries(names):
        path = ext_dir / name
        try:
            if path.is_symlink() or path.is_file():
                path.unlink()
            else:
                shutil.rmtree(path)
        except OSError as exc:
            warn(f"{path} not removed: {exc}")
            continue
        say(f"{path} removed")


def load_hooks_installer():
    spec = importlib.util.spec_from_file_location(
        "install_claude_hooks", HOOKS_INSTALLER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def migrate_hooks(installer, say, warn) -> None:
    """Replace hook entries that run the old script with the new hook.

    ``installer`` is the hooks installer module; its SETTINGS, HOOK_PATH,
    remove, install, backup and write do the work, so the file is backed
    up and rewritten atomically the same way a manual install does.
    """
    settings = installer.SETTINGS
    if not settings.exists():
        return
    try:
        text = settings.read_text(encoding="utf-8")
        original = json.loads(text)
        data = json.loads(text)
    except (OSError, json.JSONDecodeError) as exc:
        warn(f"{settings} not read: {exc}")
        return
    legacy = legacy_hook_commands(data)
    if not legacy:
        return
    for command in legacy:
        installer.remove(data, command)
    installer.install(data, str(installer.HOOK_PATH))
    try:
        installer.backup(original)
        installer.write(data)
    except OSError as exc:
        warn(f"{settings} not written: {exc}")
        return
    say(f"Claude hooks: {len(legacy)} legacy command(s) replaced in "
        f"{settings}")


def main() -> int:
    env = dict(os.environ)
    home = Path(env.get("HOME") or Path.home())

    def say(msg: str) -> None:
        print(f"migrate: {msg}")

    def warn(msg: str) -> None:
        print(f"migrate: warning: {msg}", file=sys.stderr)

    remove_legacy_extensions(extensions_dir(env, home), say, warn)
    migrate_data_dirs(xdg_bases(env, home), say, warn)
    try:
        migrate_hooks(load_hooks_installer(), say, warn)
    except Exception as exc:  # the install must go on whatever happens here
        warn(f"Claude hooks not migrated: {exc}")
    bus_env = session_bus_env(env)
    if bus_env is None:
        say("no session bus: enabled-extensions and dconf are left for "
            "the next run")
        return 0
    run = make_runner(bus_env)
    migrate_enabled(run, say, warn)
    migrate_dconf(run, say, warn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

Note on `migrate_hooks` and `Path.home()`: `install_claude_hooks.SETTINGS` is computed from `Path.home()` at import, which reads `HOME`; the `TestMain` subprocess sets `HOME`, so it never touches the real `~/.claude`.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./script/test/run_unit_test.sh test/test_erplibre_home_migrate_legacy.py`
Expected: PASS, 34 tests.

- [ ] **Step 5: Call the migration from the install target**

In `conf/make.streamdeck.Makefile`, make the migration the first line of the `erplibre_home_install_extension` recipe. It is called by its path, through its shebang, on purpose: the deployment plan later rewrites every `python3 ` of a recipe into the deck venv's interpreter, and the migration must run before that venv exists.

```make
.PHONY: erplibre_home_install_extension
erplibre_home_install_extension:
	@"$(ERPLIBRE_HOME_EXT_SRC)/tools/migrate_legacy.py"
	@if [ -L "$(ERPLIBRE_HOME_EXT_DST)" ] || [ -d "$(ERPLIBRE_HOME_EXT_DST)" ]; then \
```

(only the `migrate_legacy.py` line is new; the recipe continues unchanged.)

Check it on a sandboxed home, never the real one:

```bash
T=$(mktemp -d); mkdir -p "$T/.local/state/streamdeck-tiler"
env -i HOME="$T" XDG_RUNTIME_DIR="$T" PATH="$PATH" \
    script/gnome-extension/erplibre_home/tools/migrate_legacy.py; echo "rc=$?"
ls "$T/.local/state"; rm -rf "$T"
```

Expected: `migrate: … moved to …/erplibre-home`, `migrate: no session bus: …`, `rc=0`, then `erplibre-home`.

- [ ] **Step 6: Commit**

```bash
git add script/gnome-extension/erplibre_home/tools/migrate_legacy.py \
    test/test_erplibre_home_migrate_legacy.py conf/make.streamdeck.Makefile
python3 script/analyse/check_comment_hygiene.py --staged
```

Message:

```
[ADD] gnome extension: migrate a workstation from the old identity

A workstation that ran streamdeck-tiler keeps its enabled state, dconf
settings, data directories and Claude hooks under the old names, and its
symlink points at a directory that moved. The install target now runs a
stdlib-only migration first: each step is idempotent, leaves both data
directories alone when both exist, and skips the bus steps when no
session bus is reachable. It always exits 0, so the install goes on.
34 unit tests cover each step's inputs.

--- FR ---

[ADD] extension gnome : migrer un poste depuis l'ancienne identité

Un poste qui a fait tourner streamdeck-tiler garde son activation, ses
réglages dconf, ses dossiers de données et ses hooks Claude sous les
anciens noms, et son lien pointe vers un dossier déplacé. La cible
d'installation lance d'abord une migration en stdlib : chaque étape est
idempotente, laisse les deux dossiers quand les deux existent, et saute
les étapes du bus de session quand il est injoignable. Elle sort à 0.
34 tests unitaires couvrent les entrées de chaque étape.

Assisted-by: Claude Opus 5.5
```

---

### Task 4: Git sync reads the legacy file name

**Files:**
- Modify: `script/gnome-extension/erplibre_home/lib/git-sync.js` (append constants and `syncImportPath`)
- Modify: `script/gnome-extension/erplibre_home/extension.js` (import line 20; `_syncDebounceWrite` and `_syncImport`, about lines 378-408)
- Test: `script/gnome-extension/erplibre_home/test/unit/git-sync.test.js`

**Interfaces:**
- Consumes: Task 2's `extension.js`, which writes and reads `${repo}/erplibre-home.json`.
- Produces: `SYNC_FILE = 'erplibre-home.json'`, `LEGACY_SYNC_FILE = 'streamdeck-tiler.json'`, `syncImportPath(repo: string, exists: (path: string) => boolean) -> string | null` in `lib/git-sync.js`.

- [ ] **Step 1: Write the failing tests**

Append to `test/unit/git-sync.test.js`, and extend its import line to
`import {Debouncer, SYNC_FILE, LEGACY_SYNC_FILE, syncImportPath} from '../../lib/git-sync.js';`:

```js
test('SYNC_FILE is the ERPLibre Home name', () => {
    assert.equal(SYNC_FILE, 'erplibre-home.json');
    assert.equal(LEGACY_SYNC_FILE, 'streamdeck-tiler.json');
});

test('syncImportPath prefers the new file when both exist', () => {
    const present = new Set(['/r/erplibre-home.json', '/r/streamdeck-tiler.json']);
    assert.equal(syncImportPath('/r', p => present.has(p)),
        '/r/erplibre-home.json');
});

test('syncImportPath falls back to the legacy file', () => {
    const present = new Set(['/r/streamdeck-tiler.json']);
    assert.equal(syncImportPath('/r', p => present.has(p)),
        '/r/streamdeck-tiler.json');
});

test('syncImportPath returns null when neither exists', () => {
    assert.equal(syncImportPath('/r', () => false), null);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `node --test script/gnome-extension/erplibre_home/test/unit/git-sync.test.js`
Expected: FAIL, `SyntaxError: The requested module '../../lib/git-sync.js' does not provide an export named 'LEGACY_SYNC_FILE'`.

- [ ] **Step 3: Implement**

Append to `lib/git-sync.js`:

```js
/** File the git sync writes in the user's sync repository. */
export const SYNC_FILE = 'erplibre-home.json';

/**
 * File name the extension wrote before it became ERPLibre Home. A sync
 * repository shared with a workstation that still runs the old extension
 * holds only this one, so the import falls back to it.
 */
export const LEGACY_SYNC_FILE = 'streamdeck-tiler.json';

/**
 * Path the import reads: SYNC_FILE when it exists, else LEGACY_SYNC_FILE,
 * else null. `exists(path)` is injected so Node tests run without Gio.
 */
export function syncImportPath(repo, exists) {
    for (const name of [SYNC_FILE, LEGACY_SYNC_FILE]) {
        const path = `${repo}/${name}`;
        if (exists(path)) return path;
    }
    return null;
}
```

In `extension.js`, change the import line to
`import {Debouncer, gitPull, gitCommitPush, SYNC_FILE, syncImportPath} from './lib/git-sync.js';`.
In `_syncDebounceWrite`, replace
`const file = Gio.File.new_for_path(\`${repo}/erplibre-home.json\`);` with
`const file = Gio.File.new_for_path(\`${repo}/${SYNC_FILE}\`);`.
Replace the first two statements of `_syncImport` with:

```js
    async _syncImport(repo) {
        const path = syncImportPath(repo,
            p => Gio.File.new_for_path(p).query_exists(null));
        if (!path) return;
        const file = Gio.File.new_for_path(path);
```

The rest of `_syncImport` is unchanged.

- [ ] **Step 4: Run the tests**

```bash
node --test script/gnome-extension/erplibre_home/test/unit/git-sync.test.js
make test_gnome_extension 2>&1 | tail -5
make erplibre_home_e2e_nested
```

Expected: git-sync tests pass; `# pass 216`, `# fail 0`; the e2e prints `ok: …` (proves `extension.js` still loads after the import change).

- [ ] **Step 5: Commit**

```bash
git add script/gnome-extension/erplibre_home/lib/git-sync.js \
    script/gnome-extension/erplibre_home/extension.js \
    script/gnome-extension/erplibre_home/test/unit/git-sync.test.js
```

Message:

```
[IMP] gnome extension: git sync reads the settings file's former name

The sync repository is shared between workstations, and one that still
runs the old extension writes streamdeck-tiler.json. The export now
writes erplibre-home.json; the import reads it, and the former name only
when the new file is absent, so a mixed set of workstations converges
instead of losing the settings. Four node tests cover both, either and
neither file present.

--- FR ---

[IMP] extension gnome : la synchro git lit l'ancien nom du fichier

Le dépôt de synchro est partagé entre postes, et un poste encore sur
l'ancienne extension écrit streamdeck-tiler.json. L'export écrit
désormais erplibre-home.json ; l'import le lit, et l'ancien nom seulement
quand le nouveau manque, si bien qu'un parc mixte converge au lieu de
perdre ses réglages. Quatre tests node couvrent les deux, l'un ou aucun
des fichiers.

Assisted-by: Claude Opus 5.5
```

---

### Task 5: Amend the deployment spec and plan to the new names

**Files:**
- Modify: `docs/superpowers/specs/2026-10-13-streamdeck-deployment-design.md`
- Modify: `docs/superpowers/plans/2026-10-13-streamdeck-deployment.md`

**Interfaces:**
- Consumes: every name produced by Tasks 1–4.
- Produces: deployment docs that name `script/install/install_erplibre_home.sh`, `make erplibre_home_install` / `erplibre_home_uninstall`, `long_test/install_erplibre_home.py`, `qemu_erplibre_home*`, `TODO._erplibre_home_install_local`, and the journal pattern `\[ERPLibreHome\] (mount [^ ]+ failed|enabled)`.

The rule (spec, "Deployment spec and plan"): what installs or tests the **product** takes `erplibre_home`; what belongs to the **Stream Deck hardware or its Python programs** keeps `streamdeck` (`.venv.streamdeck`, `STREAMDECK_PY`, `VENV_STREAMDECK_PYTHON`, `test_streamdeck_entry_points`, `_streamdeck_game_command`, `prompt_execute_streamdeck_games`, `_scan_streamdeck_games`, `make.streamdeck.Makefile`, `MAKEFILE_STREAMDECK`, `streamdeck_<game>`, `streamdeck_gallery`, `streamdeck_translator_*`, `streamdeck_tiler`, `streamdeck_tiler_unittest`, the udev `-streamdeck.rules`).

- [ ] **Step 1: Mechanical rewrite**

Run once from the checkout root (script saved outside the repository):

```python
#!/usr/bin/env python3
"""One-shot rename of the deployment spec and plan to ERPLibre Home."""

from pathlib import Path

DOCS = [
    Path("docs/superpowers/specs/2026-10-13-streamdeck-deployment-design.md"),
    Path("docs/superpowers/plans/2026-10-13-streamdeck-deployment.md"),
]
PROTECT = ["streamdeck_tiler_unittest"]
RULES = [
    # Extension directory, plain and regex-escaped.
    ("stream_deck/gnome-extension", "gnome-extension/erplibre_home"),
    ("stream_deck\\/gnome-extension", "gnome-extension\\/erplibre_home"),
    # Extension identifiers, same order as Task 2.
    ("STREAMDECK_TILER_", "ERPLIBRE_HOME_"),
    ("streamdeck_tiler_", "erplibre_home_"),
    ("StreamDeckTiler", "ERPLibreHome"),
    ("Stream Deck Tiler", "ERPLibre Home"),
    ("streamdeck-tiler", "erplibre-home"),
    # Product-level installer, tests and tooling.
    ("install_streamdeck", "install_erplibre_home"),
    ("streamdeck_install", "erplibre_home_install"),
    ("streamdeck_uninstall", "erplibre_home_uninstall"),
    ("qemu_streamdeck", "qemu_erplibre_home"),
    ("_STREAMDECK_INSTALLER", "_ERPLIBRE_HOME_INSTALLER"),
    ("_STREAMDECK_UNSUPPORTED", "_ERPLIBRE_HOME_UNSUPPORTED"),
    ("STREAMDECK_SOURCE_ONLY", "ERPLIBRE_HOME_SOURCE_ONLY"),
    ("STREAMDECK_GNOME_VERSION", "ERPLIBRE_HOME_GNOME_VERSION"),
    ("STREAMDECK_OS_RELEASE", "ERPLIBRE_HOME_OS_RELEASE"),
    ("STREAMDECK_UID", "ERPLIBRE_HOME_UID"),
    ("streamdeck.bundle", "erplibre_home.bundle"),
    ("/tmp/streamdeck_task", "/tmp/erplibre_home_task"),
]
for path in DOCS:
    text = path.read_text(encoding="utf-8")
    for i, word in enumerate(PROTECT):
        text = text.replace(word, f"\0PROTECT{i}\0")
    for old, new in RULES:
        text = text.replace(old, new)
    for i, word in enumerate(PROTECT):
        text = text.replace(f"\0PROTECT{i}\0", word)
    path.write_text(text, encoding="utf-8")
    print("rewritten", path)
```

Expected: two `rewritten` lines.

- [ ] **Step 2: Hand pass over what remains**

List the remaining product-level mentions:

```bash
grep -n -E 'Stream Deck|streamdeck' docs/superpowers/specs/2026-10-13-streamdeck-deployment-design.md \
    docs/superpowers/plans/2026-10-13-streamdeck-deployment.md \
    | grep -v -E '\.venv\.streamdeck|STREAMDECK_PY|VENV_STREAMDECK|streamdeck_entry_points|streamdeck_game|streamdeck_games|make\.streamdeck|MAKEFILE_STREAMDECK|streamdeck_(snake|gallery|translator|tiler)|-streamdeck\.rules'
```

For each line, apply the rule: a phrase about the product (the document titles, "Stream Deck installer", "Stream Deck deployment", the TODO menu text of the local install entry and its i18n strings, the QEMU profile name, the long test's name) becomes "ERPLibre Home"; a phrase about the device (the deck itself, its USB access, its udev rule, its games, its venv) stays "Stream Deck". The two document file names stay as they are; their `# ` titles change. Every code block that the rename touched must still be internally consistent: a test that asserts a string must assert the string the code now produces.

- [ ] **Step 3: Recheck line references into files this plan changed**

```bash
grep -n -o -E '(script/gnome-extension/erplibre_home/[^ `:)]+|conf/make\.[a-z]+\.Makefile):[0-9][0-9,-]*' \
    docs/superpowers/plans/2026-10-13-streamdeck-deployment.md | sort -u
```

Open each cited file at each cited line and check that it still holds what the deployment plan says it holds. Task 3 added one line near the top of `erplibre_home_install_extension` in `conf/make.streamdeck.Makefile`, and Task 4 changed `extension.js` and `lib/git-sync.js`; move any reference those shifted. Also check that the deployment plan's Task 1 Makefile rewrite (`\bpython3 ` → `$(STREAMDECK_PY) `) leaves the `migrate_legacy.py` line alone: it does, because that line calls the script by its path.

- [ ] **Step 4: Verify no stale name is left**

```bash
grep -n -E 'streamdeck-tiler|StreamDeckTiler|STREAMDECK_TILER_|stream_deck/gnome-extension|install_streamdeck|streamdeck_install|streamdeck_uninstall|qemu_streamdeck' \
    docs/superpowers/specs/2026-10-13-streamdeck-deployment-design.md \
    docs/superpowers/plans/2026-10-13-streamdeck-deployment.md
grep -c 'streamdeck_tiler_unittest' docs/superpowers/plans/2026-10-13-streamdeck-deployment.md
python3 script/analyse/check_comment_hygiene.py docs/superpowers/specs/2026-10-13-streamdeck-deployment-design.md
python3 script/analyse/check_comment_hygiene.py docs/superpowers/plans/2026-10-13-streamdeck-deployment.md
```

Expected: the first grep prints nothing; the count is 3 (unchanged); no 🔴 hygiene finding.

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-10-13-streamdeck-deployment-design.md \
    docs/superpowers/plans/2026-10-13-streamdeck-deployment.md
```

Message:

```
[IMP] doc: deployment spec and plan follow the ERPLibre Home rename

The deployment plan had not started, so it builds its installer under
the product name rather than being renamed after the fact. What installs
or tests the product becomes erplibre_home: the installer script, the
make targets, the long test, the QEMU tool and the TODO entry. What
belongs to the Stream Deck hardware keeps streamdeck: the deck venv, the
games, the translator and the udev rule. Line references into files the
rename touched were rechecked.

--- FR ---

[IMP] doc : spec et plan de déploiement suivent le nom ERPLibre Home

Le plan de déploiement n'avait pas démarré : il construit son
installateur sous le nom du produit plutôt que d'être renommé après coup.
Ce qui installe ou teste le produit devient erplibre_home : le script
d'installation, les cibles make, le test long, l'outil QEMU et l'entrée
TODO. Ce qui tient au matériel Stream Deck garde streamdeck : le venv du
deck, les jeux, le traducteur et la règle udev. Les renvois de ligne vers
les fichiers touchés par le renommage ont été revérifiés.

Assisted-by: Claude Opus 5.5
```

---

### Task 6: Prove the migration on a workstation that runs the old extension (manual)

This task runs on a workstation where `streamdeck-tiler@technolibre.ca` is installed and listed in `enabled-extensions`, with the live GNOME session open. It changes that session's state and needs the user to log out and back in once; the controller asks before running it. Nothing is committed; results go to `tasks/` (unversioned).

**Files:** none in the repository.

**Interfaces:**
- Consumes: `make erplibre_home_install_extension` (Tasks 2–3).
- Produces: the observed results, written to `tasks/` by the controller.

- [ ] **Step 1: Record the state before**

```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
gsettings get org.gnome.shell enabled-extensions
ls -la ~/.local/share/gnome-shell/extensions/
ls -d ~/.config/streamdeck-tiler ~/.local/state/streamdeck-tiler ~/.cache/streamdeck-tiler 2>&1
dconf dump /org/gnome/shell/extensions/streamdeck-tiler/ | head -5
```

- [ ] **Step 2: Install, which migrates**

```bash
make erplibre_home_install_extension
```

Expected: `migrate:` lines for the removed old symlink, each existing data directory moved, `enabled-extensions: streamdeck-tiler@technolibre.ca replaced by erplibre-home@technolibre.ca`, and the dconf copy if the old path held keys; then the usual `Symlinked …` lines.

- [ ] **Step 3: Second run prints no migrate line**

```bash
make erplibre_home_install_extension 2>&1 | grep '^migrate' || echo "no migrate line"
```

Expected: `no migrate line`.

- [ ] **Step 4: After the user logs out and back in**

```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus
gdbus call --session --dest org.gnome.Shell.Extensions --object-path /org/gnome/Shell/Extensions \
    --method org.gnome.Shell.Extensions.GetExtensionInfo erplibre-home@technolibre.ca | grep -o "'state': <[0-9.]*>"
journalctl --user -b -o cat --no-pager | grep -E '\[ERPLibreHome\] (mount [^ ]+ failed|enabled)'
gdbus call --session --dest org.gnome.Shell --object-path /org/gnome/Shell/Extensions/ERPLibreHome \
    --method org.gnome.Shell.Extensions.ERPLibreHome.ListWindows | head -c 300; echo
gsettings get org.gnome.shell enabled-extensions
```

Expected: `'state': <1.0>`; `[ERPLibreHome] enabled` and no `mount … failed`; a JSON window list; the list holds `erplibre-home@technolibre.ca` and not the old UUID.
