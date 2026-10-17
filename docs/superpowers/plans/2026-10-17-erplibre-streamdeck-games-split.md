# Stream Deck games apart, deck program renamed — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename the deck program to `erplibre_streamdeck.py`, move the 45 games and the gallery into `script/stream_deck/games/`, and add a `GAMES=on|off` setting that every game entry point honours.

**Architecture:** Pure moves first (`git mv`), each with the path updates and tests of its consumers in the same commit, so every commit runs. The setting is read by one shell helper (`erplibre_home_settings.sh`: used by make, the hand-over and the gallery) and by the Python mirror (`erplibre_home_service.py`: used by TODO). Refusals are added entry point by entry point.

**Tech Stack:** bash, GNU make, Python 3 (stdlib `unittest`), GJS extension with node unit tests, mmg for docs.

**Spec:** `docs/superpowers/specs/2026-10-17-erplibre-streamdeck-games-split-design.md`

## Global Constraints

- `DECK_PROGRAM=tiler` keeps its value and its meaning. No settings file is rewritten.
- The rename of `game_tiler.py` and the change of the `tiler` mapping in `script/install/erplibre_home_settings.sh` land in the same commit.
- Moves use `git mv` and keep mode 100755.
- No game imports a sibling module; no `sys.path` code is added to `games/`.
- Every new user-facing TODO string has `fr` and `en` entries in `script/todo/todo_i18n.py`.
- Documentation changes go in `.base.md` files, regenerated with `source .venv.erplibre/bin/activate && mmg --yes <file>.base.md`. `script/gnome-extension/erplibre_home/ARCHITECTURE.md` and `DEBUG.md` are edited directly.
- `GAMES`: `on` or missing → enabled; `off` → disabled; any other value, `GAMES=` included → disabled and named by the diagnosis. The installer neither writes nor rewrites `GAMES`.
- Never gated by `GAMES`: the deck service, `erplibre_streamdeck.py`, `streamdeck` (controller), `streamdeck_erplibre` / `streamdeck_tiler`, the translator targets, `RESTART_AFTER_GAME`.
- Hand-over refusal: one line on stderr, exit 4, nothing stopped, nothing run.
- Repository rules (CLAUDE.md, `.claude/rules/*`): comments say how the code works, nothing identifying; Python lines ≤ 79; stage files by name; commit messages `[TAG] scope: subject` (EN ≤ 72), EN body, `--- FR ---`, FR subject under the same tag, FR body, ≤ 8 lines per language, trailer `Assisted-by: <model>`; validate with `python3 script/git/hooks/commit-msg <file>`; commit with `git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F <file>`.
- Test commands: Python `.venv.erplibre/bin/python -m unittest test.<module>`; full suite `./script/test/run_unit_test.sh`; extension `node --test script/gnome-extension/erplibre_home/test/unit/*.test.js`; tiler chunks `make streamdeck_tiler_unittest` (needs `.venv.streamdeck`; if absent, run `.venv.erplibre/bin/python -m unittest discover -s ./script/stream_deck -p "test_erplibre_streamdeck*.py"`).
- Safety: never call this host's real `systemctl --user`, `journalctl --user` to change anything, `gsettings` or `dconf`; tests use fakes and a temporary `HOME`.

## Review Focus

1. A gallery started while `GAMES=on` must refuse `/launch` once the user switches to `off`, without a restart: the gallery re-reads the setting on every launch (Task 6 test `test_launch_rereads_the_setting`).
2. `XDG_CONFIG_HOME` set: make, the hand-over, the gallery and TODO must all read the same file (Task 4 test `test_xdg_config_home_wins`, Task 5 test `test_handover_reads_xdg_config_home`).
3. A file edited on another system leaves `GAMES=on\r`: it is an unknown value, so games are disabled; Status must show it visibly, not as `on` (Task 7 test `test_status_shows_a_carriage_return_visibly`).
4. `GAMES=off` must not stop the deck program: `erplibre_home_deck.sh --check` and the deck entry point run as before (Task 5 test `test_games_off_never_gates_the_deck_entry_point`).
5. An untracked copy of an old `script/stream_deck/game_*.py` left in a checkout must not make the layout test fail or show in TODO: the layout test reads `git ls-files`, and TODO scans `games/` only (Task 2 tests).

---

### Task 1: Rename the deck program to `erplibre_streamdeck.py`

**Files:**
- Rename: `script/stream_deck/game_tiler.py` → `script/stream_deck/erplibre_streamdeck.py`
- Rename: `script/stream_deck/test_game_tiler_chunks.py` → `script/stream_deck/test_erplibre_streamdeck_chunks.py`
- Modify: `script/install/erplibre_home_settings.sh:44-55`
- Modify: `conf/make.streamdeck.Makefile:116-118,216-219`
- Modify: `test/test_deck_lock.py:39-40,483-485,1069,1079`
- Modify: `test/test_erplibre_home_deck.py:151,159,197`
- Modify: `test/test_streamdeck_entry_points.py:154-165`

**Interfaces:**
- Produces: `deck_program_path tiler` → `script/stream_deck/erplibre_streamdeck.py`; make targets `streamdeck_erplibre` (primary) and `streamdeck_tiler` (alias, prerequisite only).

- [ ] **Step 1: Write the failing test** — append to `test/test_erplibre_home_deck.py` (it already defines `BIBLIOTHEQUE`/the settings library path; if the constant has another name, use the one at the top of the file):

```python
class LesProgrammesExistent(unittest.TestCase):
    """deck_program_path nomme, pour chaque programme, un fichier du
    dépôt : un renommage oublié dans la bibliothèque arrête le service."""

    def test_each_program_names_a_file_that_exists(self):
        racine = Path(__file__).resolve().parent.parent
        bib = racine / "script/install/erplibre_home_settings.sh"
        for programme in ("tiler", "controller"):
            with self.subTest(programme=programme):
                fini = subprocess.run(
                    ["bash", "-c", '. "$0"; deck_program_path "$1"',
                     str(bib), programme],
                    capture_output=True, text=True, timeout=30,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
                chemin = racine / fini.stdout.strip()
                self.assertTrue(chemin.is_file(), chemin)
        fini = subprocess.run(
            ["bash", "-c", '. "$0"; deck_program_path tiler', str(bib)],
            capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(
            "script/stream_deck/erplibre_streamdeck.py", fini.stdout.strip()
        )
```

- [ ] **Step 2: Run it and watch it fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_deck.LesProgrammesExistent -v`
Expected: FAIL — `'script/stream_deck/game_tiler.py' != 'script/stream_deck/erplibre_streamdeck.py'`.

- [ ] **Step 3: Rename and update the mapping**

```bash
git mv script/stream_deck/game_tiler.py script/stream_deck/erplibre_streamdeck.py
git mv script/stream_deck/test_game_tiler_chunks.py \
       script/stream_deck/test_erplibre_streamdeck_chunks.py
```

In `script/install/erplibre_home_settings.sh`, the `tiler)` line becomes:

```bash
        tiler) echo "script/stream_deck/erplibre_streamdeck.py" ;;
```

- [ ] **Step 4: Drop `GAME_META` and `--meta`, fix the docstring**

In `script/stream_deck/erplibre_streamdeck.py`:
- delete the `GAME_META = {...}` block (lines 42-50 before the rename);
- delete the block `if len(sys.argv) > 1 and sys.argv[1] == "--meta": ... sys.exit(0)` before `if __name__ == "__main__":`;
- replace the first docstring line `"""Window Tiler — tile windows via Stream Deck.` by `"""ERPLibre Stream Deck — the deck program of ERPLibre Home.` and add after the TIMER paragraph:

```
It runs as the erplibre-home-streamdeck user service (DECK_PROGRAM=tiler)
or by make streamdeck_erplibre. It is not a game: the gallery and the TODO
games menu do not list it.
```
- `grep -n "game_tiler\|GAME_META" script/stream_deck/erplibre_streamdeck.py` must print nothing; reword any hit (the docstring near line 1771 names the file).

- [ ] **Step 5: Update the chunks test loader**

In `script/stream_deck/test_erplibre_streamdeck_chunks.py`, replace every `game_tiler` by `erplibre_streamdeck` (function name `_load_erplibre_streamdeck`, module key, file name, docstrings):

```bash
sed -i 's/game_tiler/erplibre_streamdeck/g' \
    script/stream_deck/test_erplibre_streamdeck_chunks.py
```

- [ ] **Step 6: Makefile targets**

In `conf/make.streamdeck.Makefile`, replace the `streamdeck_tiler` block by:

```make
# The deck program of ERPLibre Home; streamdeck_tiler is its former name.
.PHONY: streamdeck_erplibre
streamdeck_erplibre: $(STREAMDECK_PY)
	$(STREAMDECK_PY) script/stream_deck/erplibre_streamdeck.py

.PHONY: streamdeck_tiler
streamdeck_tiler: streamdeck_erplibre
```

and in `streamdeck_tiler_unittest` the pattern `"test_game_tiler*.py"` becomes `"test_erplibre_streamdeck*.py"`.

- [ ] **Step 7: Update the existing tests**

- `test/test_deck_lock.py` lines 1069 and 1079: `DECK_DIR / "game_tiler.py"` → `DECK_DIR / "erplibre_streamdeck.py"`; docstrings at 39-40 and 483-485: "the tiler launched as a game by TODO or the gallery" becomes "a deck program launched inside a game".
- `test/test_erplibre_home_deck.py` lines 151, 159: `script/stream_deck/game_tiler.py` → `script/stream_deck/erplibre_streamdeck.py`; line 197: `self.assertNotIn("erplibre_streamdeck.py", fini.stdout)`.
- `test/test_streamdeck_entry_points.py` `attendus` (154-165): add

```python
            "streamdeck_erplibre": "erplibre_streamdeck.py",
```

and add a test after `test_the_spec_entry_points_use_the_venv`:

```python
    def test_the_tiler_target_is_an_alias(self):
        prerequis, commandes = self.regles["streamdeck_tiler"]
        self.assertEqual(["streamdeck_erplibre"], prerequis)
        self.assertEqual([], commandes)
```

- [ ] **Step 8: Run the tests**

Run: `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_deck test.test_deck_lock test.test_streamdeck_entry_points -v 2>&1 | tail -3` → `OK`.
Run the chunks test (see Global Constraints) → 26 tests OK.
Run: `grep -rn "game_tiler" --include=*.py --include=*.sh --include=*.Makefile --include=*.js script conf test long_test` → only docs remain (Task 8).

- [ ] **Step 9: Commit**

```bash
git add script/stream_deck/erplibre_streamdeck.py \
  script/stream_deck/test_erplibre_streamdeck_chunks.py \
  script/install/erplibre_home_settings.sh conf/make.streamdeck.Makefile \
  test/test_deck_lock.py test/test_erplibre_home_deck.py \
  test/test_streamdeck_entry_points.py
```

Message — EN subject `[MOV] stream_deck: game_tiler.py becomes erplibre_streamdeck.py`; FR subject `[MOV] stream_deck: game_tiler.py devient erplibre_streamdeck.py`. Body (both languages): the deck program is not a game; DECK_PROGRAM=tiler keeps its value and now names the new file, in the same commit so the service always finds its script; `--meta` is gone, so the gallery and TODO stop listing it; `streamdeck_tiler` is an alias of `streamdeck_erplibre`. Verified: the three test modules and the chunks test.

---

### Task 2: Move the games and the gallery into `games/`

**Files:**
- Move: `script/stream_deck/game_*.py` (45), `gallery_server.py`, `index.html`, `save/.gitkeep` → `script/stream_deck/games/`
- Modify: `script/stream_deck/games/gallery_server.py:27-28`
- Modify: `conf/make.streamdeck.Makefile` (45 recipes, `streamdeck_gallery`)
- Modify: `script/todo/todo.py:1903-1910`
- Modify: `script/gnome-extension/erplibre_home/lib/project-root.js:126`, `test/unit/project-root.test.js:215-225`
- Modify: `test/test_streamdeck_entry_points.py:50,69,103,151,215,243-250`
- Modify: `.gitignore:69`
- Test: `test/test_streamdeck_games_layout.py` (new)

**Interfaces:**
- Consumes: Task 1 (the tiler is no longer `game_*.py`).
- Produces: `GAMES_DIR = script/stream_deck/games`; gallery constants `SCRIPT_DIR` (= `games/`) and `ERPLIBRE_DIR` (= repository root).

- [ ] **Step 1: Write the failing layout and scan tests** — create `test/test_streamdeck_games_layout.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les jeux du Stream Deck vivent dans script/stream_deck/games/ ; le
programme du deck et ses outils restent dans script/stream_deck/."""

import importlib.util
import os
import re
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
DECK_DIR = ROOT / "script" / "stream_deck"
GAMES_DIR = DECK_DIR / "games"
sys.argv = ["todo.py"]
from script.todo import todo as todo_mod  # noqa: E402


def suivis(motif):
    """Les fichiers suivis par git qui répondent à `motif` : une copie
    non suivie laissée dans un checkout ne compte pas."""
    sortie = subprocess.run(
        ["git", "ls-files", motif], cwd=ROOT, capture_output=True,
        text=True, check=True,
    ).stdout
    return sorted(ROOT / ligne for ligne in sortie.splitlines())


class LaDisposition(unittest.TestCase):
    def test_no_game_is_left_next_to_the_deck_program(self):
        self.assertEqual([], suivis("script/stream_deck/game_*.py"))

    def test_the_games_moved_with_their_mode_and_shebang(self):
        jeux = suivis("script/stream_deck/games/game_*.py")
        self.assertEqual(45, len(jeux))
        for jeu in jeux:
            with self.subTest(jeu=jeu.name):
                self.assertTrue(os.access(jeu, os.X_OK))
                premiere = jeu.read_text(encoding="utf-8").split("\n")[0]
                self.assertTrue(premiere.startswith("#!"), premiere)

    def test_no_game_imports_a_sibling_module(self):
        voisins = {p.stem for p in DECK_DIR.glob("*.py")}
        voisins |= {p.stem for p in GAMES_DIR.glob("*.py")}
        motif = re.compile(r"^\s*(?:import|from)\s+(\w+)", re.M)
        for jeu in suivis("script/stream_deck/games/game_*.py"):
            with self.subTest(jeu=jeu.name):
                importes = set(motif.findall(jeu.read_text(encoding="utf-8")))
                self.assertEqual(set(), importes & voisins)

    def test_the_assets_stay_with_the_controller(self):
        self.assertTrue((DECK_DIR / "Assets").is_dir())
        self.assertTrue((DECK_DIR / "erplibre_controller.py").is_file())

    def test_the_gallery_and_its_page_are_in_games(self):
        self.assertTrue((GAMES_DIR / "gallery_server.py").is_file())
        self.assertTrue((GAMES_DIR / "index.html").is_file())


class LesVraisScans(unittest.TestCase):
    """Sans simulation : un chemin oublié ne montre qu'une liste vide."""

    def test_todo_finds_exactly_the_games_of_games_dir(self):
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        trouves = sorted(g["path"] for g in todo._scan_streamdeck_games())
        attendus = sorted(
            str(p) for p in suivis("script/stream_deck/games/game_*.py")
        )
        self.assertEqual(attendus, trouves)
        self.assertNotIn("tiler", " ".join(trouves))

    def test_the_gallery_lists_the_games_and_not_the_tiler(self):
        """Le vrai glob de la galerie ; seul « --meta » est simulé, car
        les jeux n'y répondent que sous .venv.streamdeck, qui porte leurs
        dépendances."""
        spec = importlib.util.spec_from_file_location(
            "gallery_server", GAMES_DIR / "gallery_server.py"
        )
        galerie = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(galerie)
        scannes = []

        def meta(argv, **_kw):
            scannes.append(argv[1])
            return subprocess.CompletedProcess(argv, 0, '{"name": "x"}', "")

        with mock.patch.object(galerie.subprocess, "run", side_effect=meta):
            ids = {g["id"] for g in galerie._scan_games()}
        attendus = [
            str(p) for p in suivis("script/stream_deck/games/game_*.py")
        ]
        self.assertEqual(attendus, sorted(scannes))
        self.assertIn("snake", ids)
        self.assertNotIn("tiler", ids)
        self.assertEqual(ROOT, Path(galerie.ERPLIBRE_DIR))


if __name__ == "__main__":
    unittest.main()
```

`_scan_streamdeck_games()` entries carry the file in their `"path"` key (`todo.py:1950`). `test_the_games_moved_with_their_mode_and_shebang` checks the shebang only: the games answer `--meta` only under `.venv.streamdeck`, which the unit runner does not require.

- [ ] **Step 2: Run and watch it fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_streamdeck_games_layout -v`
Expected: FAIL/ERROR — 45 games still next to the deck program, `games/gallery_server.py` missing.

- [ ] **Step 3: Move the files**

```bash
mkdir -p script/stream_deck/games
for f in script/stream_deck/game_*.py; do git mv "$f" script/stream_deck/games/; done
git mv script/stream_deck/gallery_server.py script/stream_deck/index.html \
       script/stream_deck/games/
git mv script/stream_deck/save script/stream_deck/games/save
git ls-files -s script/stream_deck/games/game_snake.py   # mode 100755
```

- [ ] **Step 4: Gallery root depth** — in `script/stream_deck/games/gallery_server.py`:

```python
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
# script/stream_deck/games/ -> the repository root, three levels up.
ERPLIBRE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", "..", ".."))
```

- [ ] **Step 5: Makefile recipes**

```bash
sed -i 's#script/stream_deck/game_#script/stream_deck/games/game_#; s#script/stream_deck/gallery_server.py#script/stream_deck/games/gallery_server.py#' conf/make.streamdeck.Makefile
grep -c "script/stream_deck/games/game_" conf/make.streamdeck.Makefile   # 45
```

- [ ] **Step 6: TODO scan** — in `script/todo/todo.py` `_scan_streamdeck_games`, docstring `"""Scan script/stream_deck/games/game_*.py and extract descriptions."""` and:

```python
        game_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "stream_deck",
            "games",
        )
```

- [ ] **Step 7: Extension gallery path** — `lib/project-root.js`:

```js
export const GALLERY_SERVER_REL = 'script/stream_deck/games/gallery_server.py';
```

and in `test/unit/project-root.test.js` replace the three expected `script/stream_deck/gallery_server.py` by `script/stream_deck/games/gallery_server.py`.

- [ ] **Step 8: Entry-point tests** — in `test/test_streamdeck_entry_points.py`:
  - after `DECK_DIR`: `GAMES_DIR = DECK_DIR / "games"`;
  - `SHEBANG_DECK = re.compile(r"\./script/stream_deck/[\w/]+\.py")`;
  - `jeux()` globs `GAMES_DIR.glob("game_*.py")`;
  - the expected recipe `f"{VENV_REF} script/stream_deck/games/game_{jeu}.py"`;
  - `"faux-python script/stream_deck/games/game_snake.py"`;
  - `charger_galerie()` loads `GAMES_DIR / "gallery_server.py"`.

- [ ] **Step 9: `.gitignore`** — keep `script/stream_deck/save/` and add below it:

```
script/stream_deck/games/save/
```

(if the existing line ignores `save/*` but un-ignores `.gitkeep`, copy that pair for the new path.)

- [ ] **Step 10: Run the tests**

Run: `.venv.erplibre/bin/python -m unittest test.test_streamdeck_games_layout test.test_streamdeck_entry_points test.test_todo_streamdeck_menu -v 2>&1 | tail -3` → `OK`.
Run: `node --test script/gnome-extension/erplibre_home/test/unit/*.test.js 2>&1 | grep -E "^ℹ (pass|fail)"` → fail 0.

- [ ] **Step 11: Commit** (all moved files, `conf/make.streamdeck.Makefile`, `script/todo/todo.py`, the two extension files, `test/test_streamdeck_entry_points.py`, `test/test_streamdeck_games_layout.py`, `.gitignore`; stage with `git add -u script/stream_deck` plus the named files).

EN `[MOV] stream_deck: games and gallery move to script/stream_deck/games/`; FR `[MOV] stream_deck: les jeux et la galerie passent dans script/stream_deck/games/`. Body: the game library is apart from the deck program; make target names, the gallery URL and DECK_PROGRAM are unchanged; the gallery's root is three levels up; a real scan test guards against an empty list. Verified: test modules above and node tests.

---

### Task 3: Hide the extension's empty ERPLibre submenu

**Files:**
- Modify: `script/gnome-extension/erplibre_home/indicators/controller.js:118-121,240-244,302-311`
- Modify: `script/gnome-extension/erplibre_home/test/manual.md:11`
- Test: `script/gnome-extension/erplibre_home/test/unit/project-root.test.js` (source-text test, the existing pattern for `controller.js`)

- [ ] **Step 1: Write the failing test** — append to `test/unit/project-root.test.js`:

```js
test('the ERPLibre submenu shows only when the gallery lists a tool', () => {
    const src = extensionFile('indicators/controller.js');
    assert.ok(src.includes('this._erplibreSection.visible = false;'));
    assert.ok(src.includes(
        'this._erplibreSection.visible = erplibre.length > 0;'));
    assert.ok(!src.includes("_('No ERPLibre tools')"));
});
```

- [ ] **Step 2: Run** `node --test script/gnome-extension/erplibre_home/test/unit/project-root.test.js` → the new test fails.

- [ ] **Step 3: Implement** in `indicators/controller.js`:
  - after `this.menu.addMenuItem(this._erplibreSection);` replace the placeholder line by
    ```js
        // Shown only when the gallery lists a tool with section 'erplibre'.
        this._erplibreSection.visible = false;
    ```
  - in `_populateGamesPlaceholder(label)` drop the `_erplibreSection` line and add `this._erplibreSection.visible = false;`;
  - in `_populateGames` replace the `_fillSection(this._erplibreSection, ...)` call by
    ```js
        this._erplibreSection.visible = erplibre.length > 0;
        if (erplibre.length)
            this._fillSection(this._erplibreSection, erplibre, '');
    ```
  - `test/manual.md:11`: the ERPLibre submenu is expected hidden; "Window Tiler" is started from the `device` indicator's "Start deck program".

- [ ] **Step 4: Run** the node tests → fail 0. Run `msgfmt --check script/gnome-extension/erplibre_home/po/fr.po` (the removed string may stay in po files; nothing to regenerate).

- [ ] **Step 5: Commit** — EN `[IMP] erplibre_home: ERPLibre submenu hidden while it lists no tool`; FR `[IMP] erplibre_home: sous-menu ERPLibre caché tant qu'il ne liste aucun outil`. Body: the deck program left the gallery list, so the submenu would only say it is empty; it now shows when a gallery entry has section erplibre. Verified: node tests.

---

### Task 4: The `GAMES` setting readers

**Files:**
- Modify: `script/install/erplibre_home_settings.sh` (after `deck_program_path`)
- Modify: `script/todo/erplibre_home_service.py:19-20`
- Test: `test/test_erplibre_home_service.py:56-60` and a new class

**Interfaces:**
- Produces (shell): `deck_games_enabled` → exit 0 for `on`, 1 for `off`, 2 for an unknown value; `deck_games_message` → prints one line naming the value, the file, and how to enable.
- Produces (Python): `service.DEFAULTS["GAMES"] == "on"`, `service.GAMES_VALUES == ("on", "off")`, `service.games_enabled(settings) -> bool` (True only for `"on"`).

- [ ] **Step 1: Write the failing tests** — in `test/test_erplibre_home_service.py`, the missing-file expectation becomes `{"DECK_PROGRAM": "tiler", "RESTART_AFTER_GAME": "yes", "GAMES": "on"}`, and add:

```python
class LesJeux(unittest.TestCase):
    """GAMES : on ou absent active les jeux, off les coupe, toute autre
    valeur les coupe aussi ; le shell et Python disent la même chose."""

    def shell(self, contenu, env=None):
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier)
            environ = {
                k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
            }
            environ.update({"HOME": dossier, "BIB": str(BIBLIOTHEQUE)})
            environ.update(env or {})
            conf = Path(
                environ.get("XDG_CONFIG_HOME") or base / ".config"
            ) / "erplibre-home/streamdeck.conf"
            if contenu is not None:
                conf.parent.mkdir(parents=True, exist_ok=True)
                conf.write_text(contenu, encoding="utf-8")
            fini = subprocess.run(
                ["bash", "-c",
                 '. "$BIB"; deck_games_enabled; echo "rc=$?";'
                 ' deck_games_message'],
                capture_output=True, text=True, env=environ, timeout=30,
            )
            lu = service.read_settings(str(conf))
        return fini.stdout, lu

    def test_on_off_missing_and_unknown(self):
        cas = (
            (None, "rc=0", True),
            ("GAMES=on\n", "rc=0", True),
            ("GAMES=off\n", "rc=1", False),
            ("GAMES=\n", "rc=2", False),
            ("GAMES=yes\n", "rc=2", False),
            ("GAMES=on\r\n", "rc=2", False),
        )
        for contenu, code, actif in cas:
            with self.subTest(contenu=contenu):
                sortie, lu = self.shell(contenu)
                self.assertIn(code, sortie)
                self.assertEqual(actif, service.games_enabled(lu))

    def test_the_message_names_the_setting_and_the_way_back(self):
        sortie, _ = self.shell("GAMES=off\n")
        self.assertIn("GAMES=off", sortie)
        self.assertIn("streamdeck.conf", sortie)
        self.assertIn("TODO", sortie)

    def test_xdg_config_home_wins(self):
        with tempfile.TemporaryDirectory() as autre:
            sortie, _ = self.shell("GAMES=off\n", {"XDG_CONFIG_HOME": autre})
        self.assertIn("rc=1", sortie)
        self.assertIn(autre, sortie)
```

(`BIBLIOTHEQUE` is the settings library path already defined in this test module.)

- [ ] **Step 2: Run** `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_service -v` → FAIL (`deck_games_enabled: command not found`, `games_enabled` missing, DEFAULTS).

- [ ] **Step 3: Shell helpers** — append to `script/install/erplibre_home_settings.sh` after `deck_program_path`:

```bash
# deck_games_enabled sort en 0 quand GAMES vaut « on » ou manque, en 1 pour
# « off », en 2 pour toute autre valeur, « GAMES= » compris : une valeur
# inconnue coupe les jeux, comme un DECK_PROGRAM inconnu coupe le service.
deck_games_enabled() {
    case "$(deck_setting GAMES on)" in
        on) return 0 ;;
        off) return 1 ;;
        *) return 2 ;;
    esac
}

# deck_games_message écrit, sur une ligne, pourquoi un jeu ne démarre pas :
# la valeur de GAMES, le fichier qui la porte, et comment les réactiver.
deck_games_message() {
    echo "[ERPLibre Home] Stream Deck games are disabled" \
        "(GAMES=$(deck_setting GAMES on) in $(deck_settings_file));" \
        "enable them from TODO › Stream Deck › Games, or set GAMES=on"
}
```

- [ ] **Step 4: Python mirror** — in `script/todo/erplibre_home_service.py`:

```python
PROGRAMS = ("tiler", "controller", "none")
GAMES_VALUES = ("on", "off")
DEFAULTS = {
    "DECK_PROGRAM": "tiler",
    "RESTART_AFTER_GAME": "yes",
    "GAMES": "on",
}


def games_enabled(settings):
    """Vrai quand les réglages lus par read_settings activent les jeux :
    GAMES vaut « on », ou manque (DEFAULTS). « off » et toute autre valeur
    les coupent, comme deck_games_enabled du shell."""
    return settings.get("GAMES", DEFAULTS["GAMES"]) == "on"
```

- [ ] **Step 5: Run** `test.test_erplibre_home_service`, `test.test_erplibre_home_status`, `test.test_todo_streamdeck_menu` → OK (fix any exact-dict expectation that now carries `"GAMES": "on"`).

- [ ] **Step 6: Commit** — EN `[ADD] erplibre_home: GAMES setting read by the shell library and TODO`; FR `[ADD] erplibre_home: réglage GAMES lu par la bibliothèque shell et TODO`. Body: on or missing enables, off disables, any other value disables like an unknown DECK_PROGRAM; one message names the value, the file and the way back. Verified: service, status and menu tests.

---

### Task 5: Shell refusals — hand-over and make

**Files:**
- Modify: `script/install/erplibre_home_handover.sh` (header comment and after the usage check)
- Modify: `conf/make.streamdeck.Makefile` (new guard target, 45 game prerequisites)
- Test: `test/test_erplibre_home_handover.py`, `test/test_streamdeck_entry_points.py`, `test/test_erplibre_home_deck.py`

**Interfaces:**
- Consumes: `deck_games_enabled`, `deck_games_message` (Task 4).
- Produces: hand-over exit code 4 for a refused game; make target `streamdeck_games_guard`.

- [ ] **Step 1: Write the failing hand-over tests** — in `test/test_erplibre_home_handover.py`, class `Passation`:

```python
    def test_games_off_refuses_before_stopping_anything(self):
        self.unite("active")
        for valeur in ("off", "", "yes"):
            with self.subTest(valeur=valeur):
                self.journal.write_text("", encoding="utf-8")
                self.regler(f"GAMES={valeur}\n")
                fini, journal = self.jouer()
                self.assertEqual(4, fini.returncode)
                self.assertEqual([], journal)
                self.assertIn("Stream Deck games are disabled", fini.stderr)
                self.assertEqual(1, len(fini.stderr.strip().splitlines()))

    def test_games_on_or_missing_still_play(self):
        self.unite("inactive")
        for texte in ("GAMES=on\n", "DECK_PROGRAM=tiler\n"):
            with self.subTest(texte=texte):
                self.journal.write_text("", encoding="utf-8")
                self.regler(texte)
                fini, journal = self.jouer()
                self.assertEqual(7, fini.returncode, fini.stderr)
                self.assertIn("jeu", journal)

    def test_handover_reads_xdg_config_home(self):
        self.unite("inactive")
        autre = self.tmp / "autre"
        (autre / "erplibre-home").mkdir(parents=True)
        (autre / "erplibre-home/streamdeck.conf").write_text("GAMES=off\n")
        fini, _ = self.jouer(env={"XDG_CONFIG_HOME": str(autre)})
        self.assertEqual(4, fini.returncode)
```

- [ ] **Step 2: Write the failing make tests** — in `test/test_streamdeck_entry_points.py`:

```python
GARDE = "streamdeck_games_guard"
```

in `TestMakefileUsesTheVenv`:

```python
    def test_every_game_target_requires_the_games_guard(self):
        for jeu in jeux():
            self.assertIn(GARDE, self.regles[f"streamdeck_{jeu}"][0], jeu)

    def test_the_deck_tools_are_never_gated(self):
        for cible in ("streamdeck", "streamdeck_erplibre", "streamdeck_tiler",
                      "streamdeck_translator_doctor", "streamdeck_gallery"):
            self.assertNotIn(GARDE, self.regles[cible][0], cible)
```

(`streamdeck_gallery` is not gated by make: the gallery refuses by itself, Task 6.) In `TestMakefileGuard`:

```python
    def test_games_off_stops_a_game_target_with_the_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "erplibre-home", "streamdeck.conf")
            os.makedirs(os.path.dirname(conf))
            with open(conf, "w", encoding="utf-8") as f:
                f.write("GAMES=off\n")
            faux = os.path.join(tmp, "python")
            with open(faux, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\necho "faux-python $*"\n')
            os.chmod(faux, 0o755)
            env = dict(os.environ, XDG_CONFIG_HOME=tmp)
            res = subprocess.run(
                ["make", "-s", "-f", str(MAKEFILE), f"STREAMDECK_PY={faux}",
                 "streamdeck_snake"],
                cwd=ROOT, capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertNotEqual(0, res.returncode)
            self.assertIn("Stream Deck games are disabled", res.stderr)
            self.assertNotIn("faux-python", res.stdout)
            res = subprocess.run(
                ["make", "-s", "-f", str(MAKEFILE), f"STREAMDECK_PY={faux}",
                 "streamdeck_erplibre"],
                cwd=ROOT, capture_output=True, text=True, timeout=30, env=env,
            )
            self.assertEqual(0, res.returncode, res.stderr)
```

- [ ] **Step 3: Write the failing deck entry-point test** — in `test/test_erplibre_home_deck.py`, using the existing harness that runs `erplibre_home_deck.sh --check` with a fake sysfs (reuse its helper; name the test):

```python
    def test_games_off_never_gates_the_deck_entry_point(self):
        """GAMES ne touche pas le programme du deck : --check rend la même
        chose avec GAMES=off qu'avec GAMES=on."""
```

body: run the existing `--check` scenario that succeeds, once with `GAMES=on` and once with `GAMES=off` in the settings file, and assert equal return codes and stdout.

- [ ] **Step 4: Run** the three modules → the new tests fail.

- [ ] **Step 5: Hand-over** — in `script/install/erplibre_home_handover.sh`, after the usage `exit 1` block:

```bash
# GAMES=off, ou une valeur inconnue, refuse tout jeu avant d'arrêter quoi
# que ce soit : le service garde le deck, la commande ne tourne pas.
if ! deck_games_enabled; then
    deck_games_message >&2
    exit 4
fi
```

and add to the header list, before "1.": `0. si GAMES ne vaut pas « on » (voir erplibre_home_settings.sh), le script sort en 4 sans rien arrêter ni lancer ;` plus one sentence after "4.": `Le code 4 peut aussi venir du jeu lui-même : la ligne sur stderr est le signal sûr.`

- [ ] **Step 6: Make guard** — in `conf/make.streamdeck.Makefile`, after the `$(STREAMDECK_PY):` rule:

```make
# A game target lists streamdeck_games_guard as a prerequisite: with
# GAMES=off, or an unknown value, in streamdeck.conf, it stops there with
# the reason. The deck program, the controller and the translator tools
# are never gated.
.PHONY: streamdeck_games_guard
streamdeck_games_guard:
	@bash -c '. script/install/erplibre_home_settings.sh && \
		{ deck_games_enabled || { deck_games_message >&2; exit 1; }; }'
```

and add the guard to the 45 game rules:

```bash
for id in $(ls script/stream_deck/games/game_*.py | sed 's#.*/game_##; s#\.py$##'); do
  sed -i "s#^streamdeck_${id}: \$(STREAMDECK_PY)\$#streamdeck_${id}: \$(STREAMDECK_PY) streamdeck_games_guard#" conf/make.streamdeck.Makefile
done
grep -c "streamdeck_games_guard$" conf/make.streamdeck.Makefile   # 45
```

- [ ] **Step 7: Run** `test.test_erplibre_home_handover test.test_streamdeck_entry_points test.test_erplibre_home_deck` → OK.

- [ ] **Step 8: Commit** — EN `[ADD] stream_deck: GAMES=off refused by the hand-over and make targets`; FR `[ADD] stream_deck: GAMES=off refusé par la passation et les cibles make`. Body: the hand-over exits 4 before stopping the service, one stderr line; the 45 game targets stop on a guard; the deck program, controller and translator are never gated; exit 4 can also be a game's code, the line is the signal. Verified: three modules.

---

### Task 6: Python refusals — gallery and TODO games menu

**Files:**
- Modify: `script/stream_deck/games/gallery_server.py` (new `_games_refusal`, `main`, `_launch_game`)
- Modify: `script/todo/todo.py` `prompt_execute_streamdeck_games` (after the venv guard)
- Modify: `script/todo/todo_i18n.py`
- Test: `test/test_streamdeck_entry_points.py` (gallery and TODO games classes)

**Interfaces:**
- Consumes: `deck_games_enabled`, `deck_games_message` (shell, Task 4); `service.games_enabled`, `service.read_settings`, `service.settings_path` (Task 4).
- Produces: gallery `_games_refusal() -> str | None` (None when enabled, else the message).

- [ ] **Step 1: Write the failing tests** — in `test/test_streamdeck_entry_points.py`:

```python
class TestGalleryGames(unittest.TestCase):
    """La galerie relit GAMES à chaque lancement : off refuse, sans
    redémarrage."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.conf = Path(dossier.name, "erplibre-home", "streamdeck.conf")
        self.conf.parent.mkdir(parents=True)
        env = mock.patch.dict(os.environ, {"XDG_CONFIG_HOME": dossier.name})
        env.start()
        self.addCleanup(env.stop)
        self.galerie = charger_galerie()

    def test_refusal_follows_the_file(self):
        self.assertIsNone(self.galerie._games_refusal())
        self.conf.write_text("GAMES=off\n", encoding="utf-8")
        self.assertIn("GAMES=off", self.galerie._games_refusal())
        self.conf.write_text("GAMES=on\n", encoding="utf-8")
        self.assertIsNone(self.galerie._games_refusal())

    def test_main_refuses_to_start(self):
        self.conf.write_text("GAMES=off\n", encoding="utf-8")
        with mock.patch.object(self.galerie.http.server, "HTTPServer") as srv, \
                mock.patch("sys.stderr", new_callable=io.StringIO) as err:
            with self.assertRaises(SystemExit) as fin:
                self.galerie.main()
        self.assertEqual(1, fin.exception.code)
        srv.assert_not_called()
        self.assertIn("Stream Deck games are disabled", err.getvalue())

    def test_launch_rereads_the_setting(self):
        """Une galerie lancée avec on refuse dès que le fichier dit off."""
        gestionnaire = self.galerie.GameHandler.__new__(
            self.galerie.GameHandler
        )
        gestionnaire.wfile = io.BytesIO()
        codes = []
        gestionnaire.send_response = codes.append
        gestionnaire.send_header = lambda *a: None
        gestionnaire.end_headers = lambda: None
        self.conf.write_text("GAMES=off\n", encoding="utf-8")
        with mock.patch.object(self.galerie.subprocess, "Popen") as popen:
            gestionnaire._launch_game("snake")
        self.assertEqual([403], codes)
        popen.assert_not_called()
        self.assertIn(b"GAMES=off", gestionnaire.wfile.getvalue())
```

(add `import io` at the top if missing.) And for TODO, next to the existing games-menu tests (template around lines 482-495, which patch `VENV_STREAMDECK_PYTHON`):

```python
    def test_games_off_says_so_and_scans_nothing(self):
        for langue, attendu in (("en", "Stream Deck games are disabled"),
                                ("fr", "Les jeux Stream Deck sont désactivés")):
            with self.subTest(langue=langue):
                todo_i18n._current_lang = langue
                self.addCleanup(setattr, todo_i18n, "_current_lang", None)
                todo = todo_mod.TODO.__new__(todo_mod.TODO)
                with mock.patch.object(todo_mod.os, "access",
                                       return_value=True), \
                        mock.patch.object(todo_mod.service, "read_settings",
                                          return_value={"GAMES": "off"}), \
                        mock.patch.object(todo_mod.TODO,
                                          "_scan_streamdeck_games") as scan, \
                        mock.patch("sys.stdout",
                                   new_callable=io.StringIO) as out:
                    self.assertFalse(todo.prompt_execute_streamdeck_games())
                scan.assert_not_called()
                self.assertIn(attendu, out.getvalue())
```

If `todo.py` does not import `erplibre_home_service` as `service`, import it at the top of `todo.py` as `from script.todo import erplibre_home_service as service` (check for an existing alias first and reuse it).

- [ ] **Step 2: Run** `.venv.erplibre/bin/python -m unittest test.test_streamdeck_entry_points -v` → the new tests fail.

- [ ] **Step 3: Gallery** — in `games/gallery_server.py`, after `HANDOVER`:

```python
SETTINGS_LIB = os.path.join(
    ERPLIBRE_DIR, "script", "install", "erplibre_home_settings.sh"
)


def _games_refusal():
    """None quand GAMES active les jeux ; sinon la ligne qui dit pourquoi.
    Le fichier se relit à chaque appel, par la bibliothèque shell qui le
    lit pour make et la passation : un changement compte sans redémarrer
    la galerie."""
    fini = subprocess.run(
        ["bash", "-c",
         '. "$0" && { deck_games_enabled || { deck_games_message; exit 1; }; }',
         SETTINGS_LIB],
        capture_output=True, text=True, timeout=10,
    )
    if fini.returncode == 0:
        return None
    return fini.stdout.strip() or fini.stderr.strip() or "games disabled"
```

At the top of `main()`:

```python
    refus = _games_refusal()
    if refus:
        print(refus, file=sys.stderr)
        sys.exit(1)
```

At the top of `_launch_game`, before the file check:

```python
        refus = _games_refusal()
        if refus:
            self.send_response(403)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(json.dumps({"error": refus}).encode())
            return
```

- [ ] **Step 4: TODO** — in `prompt_execute_streamdeck_games`, after the venv `return False`:

```python
        # GAMES=off, ou une valeur inconnue, coupe la bibliothèque de jeux ;
        # le programme du deck n'en dépend pas.
        if not service.games_enabled(
            service.read_settings(service.settings_path())
        ):
            print(
                t(
                    "Stream Deck games are disabled (GAMES):"
                    " enable them in TODO › Stream Deck › Games"
                )
            )
            return False
```

`todo_i18n.py`, next to the other Stream Deck strings:

```python
    "Stream Deck games are disabled (GAMES):"
    " enable them in TODO › Stream Deck › Games": {
        "fr": "Les jeux Stream Deck sont désactivés (GAMES) :"
        " activez-les dans TODO › Stream Deck › Jeux",
        "en": "Stream Deck games are disabled (GAMES):"
        " enable them in TODO › Stream Deck › Games",
    },
```

- [ ] **Step 5: Run** `test.test_streamdeck_entry_points test.test_todo_streamdeck_menu test.test_i18n_duplicates test.test_streamdeck_games_layout` → OK.

- [ ] **Step 6: Commit** — EN `[ADD] stream_deck: gallery and TODO games menu honour GAMES=off`; FR `[ADD] stream_deck: la galerie et le menu des jeux TODO suivent GAMES=off`. Body: the gallery refuses to start and answers 403, re-reading the file at each launch through the same shell library as make; TODO says how to enable and scans nothing. Verified: modules above.

---

### Task 7: TODO entry, Status line and diagnosis for `GAMES`

**Files:**
- Modify: `script/todo/streamdeck_menu.py` (new choice `[11]`, `_streamdeck_games_setting`)
- Modify: `script/todo/erplibre_home_status.py` (`status_lines`, `diagnosis_lines`)
- Modify: `script/todo/todo_i18n.py`
- Test: `test/test_todo_streamdeck_menu.py`, `test/test_erplibre_home_status.py`

**Interfaces:**
- Consumes: `service.GAMES_VALUES`, `service.read_settings`, `service.write_settings`, `service.settings_path` (Task 4); `_streamdeck_choice` (existing).

- [ ] **Step 1: Write the failing menu tests** — in `test/test_todo_streamdeck_menu.py`:

```python
class LeReglageDesJeux(Menu):
    def test_it_writes_off_without_the_unit_and_restarts_nothing(self):
        commandes, sortie, _ = self.jouer("_streamdeck_games_setting", ("2",))
        self.assertEqual("GAMES=off\n", self.reglages.read_text())
        self.assertEqual([], commandes)
        self.assertEqual([], self.sondes)

    def test_keeping_the_current_value_writes_nothing(self):
        _, sortie, _ = self.jouer("_streamdeck_games_setting", ("",))
        self.assertFalse(self.reglages.exists())
        self.assertIn("Unchanged.", sortie)

    def test_an_invalid_value_needs_an_explicit_choice(self):
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("GAMES=peut-etre\n")
        _, sortie, _ = self.jouer("_streamdeck_games_setting", ("", "1"))
        self.assertIn("invalid", sortie)
        self.assertEqual("GAMES=on\n", self.reglages.read_text())

    def test_the_submenu_offers_the_entry(self):
        todo = TODO.__new__(TODO)
        with mock.patch.object(TODO, "_streamdeck_games_setting") as entree, \
                mock.patch.object(streamdeck_menu.click, "prompt",
                                  side_effect=["11", "0"]), \
                mock.patch.object(TODO, "fill_help_info", return_value=""):
            todo.prompt_execute_streamdeck()
        entree.assert_called_once_with()
```

- [ ] **Step 2: Write the failing status tests** — in `test/test_erplibre_home_status.py` (reuse its facts builder; the facts dict carries `settings`):

```python
    def test_status_shows_games_even_without_a_unit(self):
        faits = self.faits(unit_file=False)          # existing helper
        faits["settings"]["GAMES"] = "off"
        self.assertIn("Games: off", statut.status_lines(faits))

    def test_status_shows_a_carriage_return_visibly(self):
        faits = self.faits()
        faits["settings"]["GAMES"] = "on\r"
        lignes = statut.status_lines(faits)
        self.assertIn("Games: unknown value 'on\\r'", lignes)

    def test_diagnosis_names_an_unknown_games_value(self):
        faits = self.faits(unit_file=False)
        faits["settings"]["GAMES"] = "yes"
        problemes = statut.diagnosis_lines(faits)
        self.assertIn(
            ("Unknown GAMES value: 'yes'", "TODO › Stream Deck › Games"),
            problemes,
        )
```

If the helper that builds facts has another name or signature in that file, use it as the other tests of the file do, with `unit_file` false where stated.

- [ ] **Step 3: Run** both modules → fail.

- [ ] **Step 4: Menu entry** — in `streamdeck_menu.py` append to `choices`:

```python
            {"prompt_description": t("Games - Enable or disable the games")},
```

and to the loop:

```python
            elif status == "11":
                self._streamdeck_games_setting()
```

and the method, next to `_streamdeck_program`:

```python
    def _streamdeck_games_setting(self):
        """Réécrit GAMES. Il ne faut pas l'unité, et rien ne redémarre :
        la galerie, make et la passation relisent le fichier à chaque jeu.
        La valeur en vigueur, celle du fichier ou « on » quand la clé
        manque, n'écrit rien ; une valeur invalide se montre comme telle et
        n'a pas de défaut, si bien qu'Entrée ne la remplace pas."""
        chemin = service.settings_path()
        actuel = service.read_settings(chemin)["GAMES"]
        libelles = (("on", t("Enabled")), ("off", t("Disabled")))
        connus = dict(libelles)
        affiche = connus.get(actuel, "%r (%s)" % (actuel, t("invalid")))
        defaut = (
            str(service.GAMES_VALUES.index(actuel) + 1)
            if actuel in service.GAMES_VALUES
            else None
        )
        choix = self._streamdeck_choice(
            f"{t('Games:')} {affiche}", libelles, defaut
        )
        if choix is None:
            return
        if choix == actuel or not service.write_settings(
            chemin, {"GAMES": choix}
        ):
            print(t("Unchanged."))
            return
        print(f"{t('Games:')} {connus[choix]}")
```

- [ ] **Step 5: Status and diagnosis** — in `erplibre_home_status.py`, `status_lines`, before `return [`:

```python
    valeur_jeux = facts["settings"].get("GAMES", "on")
    if valeur_jeux in service.GAMES_VALUES:
        jeux = "%s %s" % (t("Games:"), valeur_jeux)
    else:
        jeux = "%s %r" % (t("Games: unknown value"), valeur_jeux)
```

and add `jeux,` after `unite,` in the returned list. In `diagnosis_lines`, just before `if not facts["unit_file"]:`:

```python
    valeur_jeux = facts["settings"].get("GAMES", "on")
    if valeur_jeux not in service.GAMES_VALUES:
        problemes.append(
            (
                "%s %r" % (t("Unknown GAMES value:"), valeur_jeux),
                t("TODO › Stream Deck › Games"),
            )
        )
```

- [ ] **Step 6: i18n** — add to `todo_i18n.py`:

```python
    "Games - Enable or disable the games": {
        "fr": "🎮 Jeux - Activer ou désactiver les jeux",
        "en": "🎮 Games - Enable or disable the games",
    },
    "Games:": {"fr": "Jeux :", "en": "Games:"},
    "Games: unknown value": {
        "fr": "Jeux : valeur inconnue",
        "en": "Games: unknown value",
    },
    "Unknown GAMES value:": {
        "fr": "Valeur GAMES inconnue :",
        "en": "Unknown GAMES value:",
    },
    "TODO › Stream Deck › Games": {
        "fr": "TODO › Stream Deck › Jeux",
        "en": "TODO › Stream Deck › Games",
    },
    "Enabled": {"fr": "Activés", "en": "Enabled"},
    "Disabled": {"fr": "Désactivés", "en": "Disabled"},
```

Before adding each key, `grep -n '"<key>"' script/todo/todo_i18n.py`: reuse an existing key instead of duplicating it (`test_i18n_duplicates` fails on duplicates). If `"Enabled"`/`"Disabled"` exist with other French, use new keys `"Games enabled"`/`"Games disabled"` instead and adapt `libelles`.

- [ ] **Step 7: Run** `test.test_todo_streamdeck_menu test.test_erplibre_home_status test.test_i18n_duplicates test.test_todo_i18n` → OK.

- [ ] **Step 8: Commit** — EN `[ADD] streamdeck menu: Games entry, Status line and GAMES diagnosis`; FR `[ADD] streamdeck menu: entrée Jeux, ligne d'état et diagnostic GAMES`. Body: the entry writes GAMES without the unit and restarts nothing; an invalid value needs an explicit choice; Status shows the value even without a unit, an unknown one with repr so a carriage return shows; the diagnosis names it. Verified: modules above.

---

### Task 8: Documentation and final verification

**Files:**
- Modify: `script/stream_deck/README.base.md` (paths, the tree near 1094-1105, the game count 45), `script/stream_deck/INSTALL.base.md` (tiler path at 218/247, the settings sample 210-215, the `GAMES` key in en and fr), `script/stream_deck/gpt.base.md:22,50`, `CHANGELOG.base.md` (top entry)
- Modify: `script/gnome-extension/erplibre_home/ARCHITECTURE.md:27,55,68`, `DEBUG.md:111`, `lib/mpv-state.js:15` (comment)
- Generated: the `.md` / `.fr.md` of each `.base.md`

- [ ] **Step 1: Find every stale reference**

Run: `grep -rn "game_tiler\|stream_deck/game_\|stream_deck/gallery_server\|stream_deck/index.html\|stream_deck/save" --include=*.base.md --include=ARCHITECTURE.md --include=DEBUG.md --include=*.js . | grep -v "^./docs/superpowers/\|^./addons/"` and fix each hit in the source file (`.base.md`, not the generated one).

- [ ] **Step 2: Write the `INSTALL.base.md` `GAMES` paragraph** (en; the fr block mirrors it):

```markdown
`GAMES=on|off` turns the Stream Deck game library on or off. `on`, or no
`GAMES` line, enables it; `off` disables it; any other value disables it
too and TODO › Stream Deck › Diagnosis names it. With the games off, the
TODO games menu, the gallery, `make streamdeck_<game>` and the hand-over
refuse to start a game and say how to enable them; the deck program, the
controller and the service are never affected. Set it from
TODO › Stream Deck › Games, or by hand in this file.
```

- [ ] **Step 3: `CHANGELOG.base.md` entry** (en and fr, following the file's existing format):
  - `script/stream_deck/game_tiler.py` → `script/stream_deck/erplibre_streamdeck.py` (`DECK_PROGRAM=tiler` and `make streamdeck_tiler` unchanged; new `make streamdeck_erplibre`);
  - `script/stream_deck/game_<id>.py`, `gallery_server.py`, `index.html`, `save/` → `script/stream_deck/games/`;
  - restart a gallery started before the update; GNOME Shell picks the new gallery path at the next login;
  - djscratch saves: `mv script/stream_deck/save/* script/stream_deck/games/save/`;
  - new setting `GAMES=on|off`.

- [ ] **Step 4: Regenerate**

```bash
source .venv.erplibre/bin/activate
for f in script/stream_deck/README.base.md script/stream_deck/INSTALL.base.md \
         script/stream_deck/gpt.base.md CHANGELOG.base.md; do mmg --yes "$f"; done
```

- [ ] **Step 5: Full verification**

Run: `./script/test/run_unit_test.sh` → all green.
Run: `node --test script/gnome-extension/erplibre_home/test/unit/*.test.js` → fail 0.
Run: the chunks test (Global Constraints) → OK.
Run: `python3 script/analyse/check_comment_hygiene.py --staged` after staging → 0 identifiant.
Run: `./long_test/install_erplibre_home.py --dry-run --only ubuntu:24.04` → plans without error.

- [ ] **Step 6: Commit** — EN `[UPD] doc: Stream Deck games in games/, erplibre_streamdeck.py, GAMES`; FR `[UPD] doc: jeux Stream Deck dans games/, erplibre_streamdeck.py, GAMES`. Body: the docs follow the new paths and describe the setting; the changelog maps old paths to new ones and the two restarts. Verified: mmg regenerated, full suite and node tests green.
