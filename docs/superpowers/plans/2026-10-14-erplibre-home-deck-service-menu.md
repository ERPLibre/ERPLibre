# ERPLibre Home Deck Service and Stream Deck Menu Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the chosen Stream Deck program (the window tiler by default) as a `systemd --user` service of the Stream Deck level, hand the deck over to games and back, make two deck programs refuse each other through a lock, and gather games, installs, service, status and diagnosis under one TODO **Stream Deck** submenu.

**Architecture:** A sourced shell library (`erplibre_home_settings.sh`) holds the names, paths and settings reader shared by three scripts: the service entry point `erplibre_home_deck.sh` (`--check` is the unit's `ExecCondition`, otherwise it `exec`s the program), the hand-over helper `erplibre_home_handover.sh` (stops the unit, runs a game, starts it again), and `install_erplibre_home.sh`, which writes the unit and the settings at the Stream Deck level and removes them in both uninstalls. Each deck program takes `deck_lock.py`'s `flock` at start. On the TODO side, `erplibre_home_service.py` mirrors the settings rules, `erplibre_home_status.py` turns recorded probe outputs into status and diagnosis lines, and the `StreamDeckMenuMixin` (`streamdeck_menu.py`) is the submenu. The GNOME extension's device indicator drives the unit through a pure `lib/deck-service.js`; the long test checks the unit on real VMs.

**Tech Stack:** bash, systemd user units, Python 3 (unittest, `fcntl`), GJS ES modules (`node --test` for the pure module), mmg for bilingual docs, libvirt/QEMU for the long test.

**Spec:** `docs/superpowers/specs/2026-10-14-erplibre-home-deck-service-menu-design.md`

## Global Constraints

- Unit `erplibre-home-streamdeck.service`, in `~/.config/systemd/user/`; settings `~/.config/erplibre-home/streamdeck.conf` (`$XDG_CONFIG_HOME` honoured, empty means unset); service entry point `script/install/erplibre_home_deck.sh`; hand-over helper `script/install/erplibre_home_handover.sh`; deck lock `$XDG_RUNTIME_DIR/erplibre-home/deck.lock`.
- Settings are plain `KEY=value` lines, never sourced: `DECK_PROGRAM=tiler|controller|none` (default `tiler`; `tiler` is `script/stream_deck/game_tiler.py`, `controller` is `script/stream_deck/erplibre_controller.py`), `RESTART_AFTER_GAME=yes|no` (default `yes`). A missing file or key means the default; an unknown value makes the entry point print one line and exit 1.
- The unit is the spec's text — `PartOf=`/`After=`/`WantedBy=graphical-session.target`, `Type=simple`, `WorkingDirectory=<checkout>`, `ExecCondition=<checkout>/script/install/erplibre_home_deck.sh --check`, `ExecStart=<checkout>/script/install/erplibre_home_deck.sh`, `Restart=on-failure`, `RestartSec=3` — plus `RestartPreventExitStatus=2`; `<checkout>` is quoted for systemd (double quotes on `Exec*` lines, `%` doubled everywhere).
- `--check` exits 0 only when `DECK_PROGRAM` is not `none`, `.venv.streamdeck/bin/python` exists and a USB device of vendor `0fd9` is under `/sys/bus/usb/devices/*/idVendor`; otherwise non-zero. Without `--check` the entry point `exec`s `.venv.streamdeck/bin/python <program>` and never takes the lock itself.
- Installer options, Stream Deck level only (a usage error, exit 1, without `--stream-deck` or with `--uninstall`): `--deck-program=tiler|controller|none`, `--autostart` (the only thing that enables the unit), `--restart-after-game` / `--no-restart-after-game` (both together: usage error). `--stream-deck` writes the settings: a given option writes its key, an option not given keeps the key's current value, the default (`tiler`, `yes`) only when the file or key is absent or empty, and other lines stay. It then writes the unit, runs `systemctl --user daemon-reload`, enables only with `--autostart`, never starts it. A failing `systemctl --user` is reported, never fatal; the summary then says to run `systemctl --user enable erplibre-home-streamdeck.service` after login. Both uninstalls stop, disable and remove the unit, `daemon-reload`, remove the settings. `--dry-run` prints the unit path, the settings and whether it would enable. A second identical run leaves unit and settings untouched.
- Deck lock: `fcntl.flock(…, LOCK_EX | LOCK_NB)` at start of `game_tiler.py` and `erplibre_controller.py`; a second holder prints the holder's program and PID and exits 2. The lock's directory must belong to the user with mode 0700 and the lock file is opened with `O_NOFOLLOW`, since the fallback directory without `$XDG_RUNTIME_DIR` lives in the shared temporary directory.
- Hand-over: if the unit is active, stop it; run the command in the foreground keeping its code; if it was active and `RESTART_AFTER_GAME=yes`, start it again; exit with the game's code. Without the unit file only the command runs. The gallery's replay loop stays inside one hand-over.
- TODO `Execute › [17]` becomes **Stream Deck**, opening exactly: `[1] Games`, `[2] Status`, `[3] Service`, `[4] Deck program`, `[5] Autostart`, `[6] Diagnosis`, `[7] Install ERPLibre Home (local)`, `[8] Install ERPLibre Home Stream Deck (local)`, `[9] Uninstall`, `[10] Extension`. `[18]` and `[19]` of Execute disappear. Every label and message has `fr` and `en` keys in `script/todo/todo_i18n.py`.
- The device indicator's "Open controller UI" runs `systemctl --user start erplibre-home-streamdeck.service` when the unit file exists and keeps its direct launch otherwise; "Restart deck" restarts the unit in the same case.
- Unit tests live in `test/`, run in seconds, need no VM and never touch the account that runs them: every test that reaches the unit, the settings or `systemctl` sets `HOME` to a temporary directory, removes `XDG_CONFIG_HOME`, and puts a fake `systemctl` first on `PATH` or as a shell function. Real VMs only in `long_test/`.
- Comments say how the code works, in the language of the file around them (French in `script/install/*.sh`, `script/todo/*.py`, `script/stream_deck/deck_lock.py` and the tests; English in `gallery_server.py` and the extension's JS); nothing identifying, invented examples only (`/srv/depot de test 100%`, `exemple`).
- Python formatting: `black -l 79` on new Python files and on the test files listed per task; never on `script/todo/todo.py` or `script/stream_deck/gallery_server.py`, which are not black-clean at HEAD.
- Docs: edit `.base.md` only, regenerate with `source .venv.erplibre/bin/activate && mmg --yes <file>.base.md`.
- Commits: `[TAG] scope: subject` in English, 72 characters at most; English body; `--- FR ---`; French subject under the same tag; French body; 8 lines per language at most; trailer `Assisted-by: Claude Opus 5.5`, plus one `Assisted-by:` line for the executor's own model when it differs; never an AI in `Co-authored-by`. Stage files by name, never `git add -A`. Validate with `python3 script/git/hooks/commit-msg "$SCRATCH/msg-N.txt"`, commit with `git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-N.txt"`.
- Every command runs from the checkout root. `SCRATCH=$(mktemp -d)` is a directory outside the repository, used for commit message files.

## Review Focus

- A checkout whose path holds a space or `%`: the unit loads and points at the right file (`systemd-analyze verify`); a path with `'`, `"`, `\` or a control character, which systemd refuses even quoted, stops the Stream Deck install before anything is written (Task 4: `test_systemd_loads_the_unit_of_a_checkout_with_space_and_percent`, `test_a_path_systemd_refuses_stops_the_install`).
- A game ended by Ctrl-C in TODO, or by the gallery's SIGTERM to the terminal's process group: the hand-over still starts the service again and exits with the game's code (Task 3: `test_an_interrupted_game_still_gives_the_deck_back`).
- The developer who runs the test suite has the service really installed and running: no test stops, restarts or deletes it, because every path is derived from a temporary `HOME` and every `systemctl` is a fake (Task 3: `environnement_isole`, Task 4: `sourcer` with a temporary `HOME`).
- A deck program started by hand (`make streamdeck_tiler`) while the service is enabled: the service's start exits 2 on the lock and systemd does not restart it every 3 s (Task 2: `test_a_second_holder_exits_two_and_names_the_first`; Task 4: `RestartPreventExitStatus=2` in `UNITE_ATTENDUE`).
- An install over ssh with no user session: the unit is written, the installer exits 0, and the summary names the command to run after login (Task 4: `test_without_a_user_manager_the_summary_says_what_to_run`).

## File Structure

| File | Responsibility |
|---|---|
| `script/install/erplibre_home_settings.sh` (new) | sourced library: unit name, unit and settings paths, settings reader, program → script, deck presence |
| `script/install/erplibre_home_deck.sh` (new) | the unit's `ExecCondition` (`--check`) and `ExecStart` (`exec` of the program) |
| `script/install/erplibre_home_handover.sh` (new) | stop the unit, run a game, start the unit again |
| `script/stream_deck/deck_lock.py` (new) | the deck `flock`, its holder, exit 2 |
| `script/stream_deck/game_tiler.py`, `erplibre_controller.py` | take the lock at start |
| `script/stream_deck/gallery_server.py` | run the replay loop through the hand-over |
| `script/install/install_erplibre_home.sh` | write/remove unit and settings, three options, dry-run lines |
| `script/todo/erplibre_home_service.py` (new) | TODO's side of the settings, `run_command` |
| `script/todo/erplibre_home_status.py` (new) | probes → facts → status and diagnosis lines |
| `script/todo/streamdeck_menu.py` (new) | `StreamDeckMenuMixin`: the ten-entry submenu |
| `script/todo/todo.py` | mixin, Execute `[17]`, hand-over in the game command, install questions |
| `script/todo/todo_i18n.py` | fr/en keys of the status, diagnosis and submenu |
| `script/gnome-extension/erplibre_home/lib/deck-service.js` (new) | pure choice between the unit and the direct launch |
| `script/gnome-extension/erplibre_home/indicators/device.js` | uses it |
| `long_test/install_erplibre_home.py` | stage 2 options and service checks, stages 3/4 service-gone |
| `script/stream_deck/INSTALL.base.md`, `long_test/README.base.md`, `CHANGELOG.base.md` | docs |

Task order differs from a strict reading of the spec's sections in one place: the status and diagnosis module (Task 5) comes before the submenu (Task 6), so the submenu never dispatches to a method that does not exist yet.

Baseline at HEAD `47bedbd4`: `./script/test/run_unit_test.sh` reports `8254 tests, tout vert`; `node --test script/gnome-extension/erplibre_home/test/unit/*.test.js` reports `tests 242`, `pass 242`. Per file: `test_install_erplibre_home` 76, `test_todo_menu` 54, `test_streamdeck_entry_points` 21, `test_longtest_install_erplibre_home` 114, `test_todo_erplibre_home_install` 6, `test_todo_i18n` 24. Run a single file with `.venv.erplibre/bin/python -m unittest test.<name>`.

---

### Task 1: Service entry point and settings library

**Files:**
- Create: `script/install/erplibre_home_settings.sh`
- Create: `script/install/erplibre_home_deck.sh` (mode 755)
- Test: `test/test_erplibre_home_deck.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (sourced by `. "${RACINE}/script/install/erplibre_home_settings.sh"`):
  - `DECK_UNIT_NAME="erplibre-home-streamdeck.service"`
  - `deck_config_home` → `${XDG_CONFIG_HOME:-$HOME/.config}`
  - `deck_settings_file` → `<config>/erplibre-home/streamdeck.conf`
  - `deck_unit_file` → `<config>/systemd/user/erplibre-home-streamdeck.service`
  - `deck_setting KEY DEFAULT` → last `KEY=` value of the settings file, or `DEFAULT`
  - `deck_program_path PROGRAM` → `script/stream_deck/game_tiler.py` | `script/stream_deck/erplibre_controller.py` | empty for `none`; return 1 for an unknown value
  - `deck_present` → 0 when a `0fd9` idVendor exists under `${ERPLIBRE_HOME_SYSFS:-/sys}/bus/usb/devices/*/`
- Produces: `script/install/erplibre_home_deck.sh [--check]`, exit 0/1 as in Global Constraints; `ERPLIBRE_HOME_SYSFS` replaces `/sys` for tests.

- [ ] **Step 1: Write the failing test**

Create `test/test_erplibre_home_deck.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le point d'entrée du service Stream Deck et ses réglages.

erplibre_home_deck.sh tourne ici dans une copie du dépôt dont le chemin
porte une espace, sous un HOME temporaire : le venv est un faux python qui
écrit ses arguments, et l'arbre sysfs un faux, désigné par
ERPLIBRE_HOME_SYSFS. Rien ne touche ni au vrai venv ni au vrai /sys.

Ce que ces tests gardent :

- --check rend 0 seulement avec un programme, le venv et un deck du vendeur
  0fd9 ; chaque manque rend 1 et le dit sur une ligne ;
- sans option, le script remplace son processus par le python du venv sur
  le programme de DECK_PROGRAM, tiler par défaut ;
- une valeur inconnue sort en 1 et nomme le fichier ; « none » ne lance
  rien ;
- les réglages se lisent sans être sourcés, la dernière ligne d'une clé
  l'emporte, et $XDG_CONFIG_HOME prime sur ~/.config.
"""

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
INSTALL = RACINE / "script/install"
SCRIPTS = ("erplibre_home_deck.sh", "erplibre_home_settings.sh")


class Copie(unittest.TestCase):
    """Une copie du dépôt réduite aux deux scripts, un HOME et un /sys
    jetables."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.depot = self.tmp / "copie du depot"
        (self.depot / "script/install").mkdir(parents=True)
        for nom in SCRIPTS:
            shutil.copy2(INSTALL / nom, self.depot / "script/install" / nom)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.sysfs = self.tmp / "sys"
        (self.sysfs / "bus/usb/devices").mkdir(parents=True)
        self.reglages = self.home / ".config/erplibre-home/streamdeck.conf"

    def venv(self):
        """Pose le faux python du venv : il écrit son répertoire courant
        puis chacun de ses arguments, un par ligne."""
        python = self.depot / ".venv.streamdeck/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text(
            '#!/bin/sh\npwd\nfor a in "$@"; do echo "$a"; done\n',
            encoding="utf-8",
        )
        python.chmod(0o755)

    def usb(self, nom, vendeur):
        """Un périphérique USB dans le faux sysfs."""
        appareil = self.sysfs / "bus/usb/devices" / nom
        appareil.mkdir()
        (appareil / "idVendor").write_text(vendeur + "\n", encoding="utf-8")

    def regler(self, texte):
        self.reglages.parent.mkdir(parents=True, exist_ok=True)
        self.reglages.write_text(texte, encoding="utf-8")

    def lancer(self, *options, env=None):
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ["HOME"] = str(self.home)
        environ["ERPLIBRE_HOME_SYSFS"] = str(self.sysfs)
        environ.update(env or {})
        return subprocess.run(
            [
                str(self.depot / "script/install/erplibre_home_deck.sh"),
                *options,
            ],
            capture_output=True,
            text=True,
            env=environ,
            cwd="/",
            timeout=30,
        )


class LeCheck(Copie):
    def test_everything_present_exits_zero(self):
        self.venv()
        self.usb("1-1", "1d6b")
        self.usb("3-2", "0fd9")
        fini = self.lancer("--check")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("", fini.stdout)

    def test_no_deck_exits_one_and_says_so(self):
        self.venv()
        self.usb("1-1", "1d6b")
        fini = self.lancer("--check")
        self.assertEqual(1, fini.returncode)
        self.assertIn("no Stream Deck plugged in", fini.stderr)
        self.assertEqual(1, len(fini.stderr.strip().splitlines()))

    def test_no_venv_exits_one_and_names_the_install(self):
        self.usb("3-2", "0fd9")
        fini = self.lancer("--check")
        self.assertEqual(1, fini.returncode)
        self.assertIn("make erplibre_home_streamdeck_install", fini.stderr)

    def test_program_none_exits_one(self):
        self.venv()
        self.usb("3-2", "0fd9")
        self.regler("DECK_PROGRAM=none\n")
        fini = self.lancer("--check")
        self.assertEqual(1, fini.returncode)
        self.assertIn("DECK_PROGRAM=none", fini.stderr)

    def test_an_unknown_program_exits_one_naming_the_file(self):
        self.venv()
        self.usb("3-2", "0fd9")
        self.regler("DECK_PROGRAM=exemple\n")
        for options in (("--check",), ()):
            with self.subTest(options=options):
                fini = self.lancer(*options)
                self.assertEqual(1, fini.returncode)
                self.assertIn("DECK_PROGRAM=exemple", fini.stderr)
                self.assertIn(str(self.reglages), fini.stderr)
                self.assertEqual("", fini.stdout)

    def test_an_unknown_option_exits_one(self):
        fini = self.lancer("--exemple")
        self.assertEqual(1, fini.returncode)
        self.assertIn("--exemple", fini.stderr)


class LeLancement(Copie):
    def test_the_tiler_runs_by_default_under_the_venv(self):
        self.venv()
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [
                str(self.depot),
                str(self.depot / "script/stream_deck/game_tiler.py"),
            ],
            fini.stdout.splitlines(),
        )

    def test_each_program_maps_to_its_script(self):
        self.venv()
        attendus = {
            "tiler": "script/stream_deck/game_tiler.py",
            "controller": "script/stream_deck/erplibre_controller.py",
        }
        for programme, script in attendus.items():
            with self.subTest(programme=programme):
                self.regler(f"DECK_PROGRAM={programme}\n")
                fini = self.lancer()
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(
                    str(self.depot / script), fini.stdout.splitlines()[-1]
                )

    def test_the_program_replaces_the_script(self):
        """exec : le PID du programme est celui du script, et aucun bash ne
        reste pour tenir le verrou du deck."""
        python = self.depot / ".venv.streamdeck/bin/python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\necho $$\n", encoding="utf-8")
        python.chmod(0o755)
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ["HOME"] = str(self.home)
        script = self.depot / "script/install/erplibre_home_deck.sh"
        proc = subprocess.Popen(
            [str(script)],
            stdout=subprocess.PIPE,
            text=True,
            env=environ,
        )
        sortie, _ = proc.communicate(timeout=30)
        self.assertEqual(str(proc.pid), sortie.strip())

    def test_none_runs_nothing(self):
        self.venv()
        self.regler("DECK_PROGRAM=none\n")
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertNotIn("game_tiler.py", fini.stdout)
        self.assertIn("nothing to run", fini.stdout)

    def test_without_the_venv_it_exits_one(self):
        fini = self.lancer()
        self.assertEqual(1, fini.returncode)
        self.assertIn("make erplibre_home_streamdeck_install", fini.stderr)


class LesReglages(Copie):
    def lire(self, cle, defaut, env=None):
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ.update(
            {
                "HOME": str(self.home),
                "BIBLIO": str(INSTALL / "erplibre_home_settings.sh"),
                "CLE": cle,
                "DEFAUT": defaut,
            }
        )
        environ.update(env or {})
        fini = subprocess.run(
            ["bash", "-c", '. "$BIBLIO"; deck_setting "$CLE" "$DEFAUT"'],
            capture_output=True,
            text=True,
            env=environ,
            timeout=30,
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        return fini.stdout.rstrip("\n")

    def test_a_missing_file_gives_the_default(self):
        self.assertEqual("tiler", self.lire("DECK_PROGRAM", "tiler"))

    def test_the_last_line_of_a_key_wins_and_comments_are_skipped(self):
        self.regler(
            "# DECK_PROGRAM=none\n"
            "DECK_PROGRAM=tiler\n"
            "RESTART_AFTER_GAME=no\n"
            "DECK_PROGRAM=controller"
        )
        self.assertEqual("controller", self.lire("DECK_PROGRAM", "tiler"))
        self.assertEqual("no", self.lire("RESTART_AFTER_GAME", "yes"))

    def test_a_key_prefix_is_not_the_key(self):
        self.regler("DECK_PROGRAM_OLD=none\n")
        self.assertEqual("tiler", self.lire("DECK_PROGRAM", "tiler"))

    def test_the_file_is_never_sourced(self):
        temoin = self.tmp / "execute"
        self.regler(f"DECK_PROGRAM=$(touch {temoin})\n")
        self.assertEqual(
            f"$(touch {temoin})", self.lire("DECK_PROGRAM", "tiler")
        )
        self.assertFalse(temoin.exists())

    def test_xdg_config_home_wins_over_dot_config(self):
        ailleurs = self.tmp / "config ailleurs"
        (ailleurs / "erplibre-home").mkdir(parents=True)
        (ailleurs / "erplibre-home/streamdeck.conf").write_text(
            "DECK_PROGRAM=controller\n", encoding="utf-8"
        )
        self.regler("DECK_PROGRAM=none\n")
        self.assertEqual(
            "controller",
            self.lire(
                "DECK_PROGRAM", "tiler", {"XDG_CONFIG_HOME": str(ailleurs)}
            ),
        )


class LesScripts(unittest.TestCase):
    def test_the_entry_point_is_executable_valid_shell(self):
        script = INSTALL / "erplibre_home_deck.sh"
        self.assertTrue(os.access(script, os.X_OK))
        for nom in SCRIPTS:
            with self.subTest(nom=nom):
                fini = subprocess.run(
                    ["bash", "-n", str(INSTALL / nom)],
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, fini.returncode, fini.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_deck`
Expected: `Ran 17 tests`, `FAILED (failures=1, errors=16)` — the errors are `FileNotFoundError` on `script/install/erplibre_home_deck.sh`, the failure is `test_the_entry_point_is_executable_valid_shell`.

- [ ] **Step 3: Write the settings library**

Create `script/install/erplibre_home_settings.sh`:

```bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Bibliothèque sourcée par l'installateur, le point d'entrée du service et
# l'outil de passation : les noms et les chemins du service Stream Deck, et
# la lecture de ses réglages. Elle ne lance rien et ne pose que des
# fonctions et la constante DECK_UNIT_NAME.
#
# Les réglages sont des lignes « CLÉ=valeur » ; une ligne qui ne commence pas
# par « CLÉ= » est ignorée, si bien qu'un commentaire « # … » est permis.
# Rien n'est sourcé : un fichier de réglages n'exécute jamais de code.

DECK_UNIT_NAME="erplibre-home-streamdeck.service"

# Le répertoire de configuration de l'utilisateur : $XDG_CONFIG_HOME, ou
# ~/.config quand il est vide ou absent, comme systemd --user le lit.
deck_config_home() {
    echo "${XDG_CONFIG_HOME:-${HOME}/.config}"
}

deck_settings_file() {
    echo "$(deck_config_home)/erplibre-home/streamdeck.conf"
}

deck_unit_file() {
    echo "$(deck_config_home)/systemd/user/${DECK_UNIT_NAME}"
}

# deck_setting CLÉ DÉFAUT rend la valeur de la dernière ligne « CLÉ=… » du
# fichier de réglages, ou DÉFAUT quand le fichier ou la clé manque. Une
# valeur vide est rendue vide : c'est à l'appelant de la refuser.
deck_setting() {
    local key="$1" value="$2" file line
    file="$(deck_settings_file)"
    if [ -f "${file}" ]; then
        while IFS= read -r line || [ -n "${line}" ]; do
            case "${line}" in
                "${key}="*) value="${line#*=}" ;;
            esac
        done <"${file}"
    fi
    echo "${value}"
}

# deck_program_path PROGRAMME rend le script, relatif à la racine du dépôt,
# que lance DECK_PROGRAM=PROGRAMME ; rien pour « none » ; code 1 pour une
# valeur inconnue.
deck_program_path() {
    case "$1" in
        tiler) echo "script/stream_deck/game_tiler.py" ;;
        controller) echo "script/stream_deck/erplibre_controller.py" ;;
        none) echo "" ;;
        *) return 1 ;;
    esac
}

# Vrai quand un périphérique USB du vendeur 0fd9 (Elgato) est branché, lu
# dans les idVendor de sysfs. ERPLIBRE_HOME_SYSFS remplace /sys, pour les
# tests.
deck_present() {
    local vendor
    for vendor in "${ERPLIBRE_HOME_SYSFS:-/sys}"/bus/usb/devices/*/idVendor; do
        [ -r "${vendor}" ] || continue
        [ "$(cat "${vendor}")" = "0fd9" ] && return 0
    done
    return 1
}
```

- [ ] **Step 4: Write the entry point**

Create `script/install/erplibre_home_deck.sh`:

```bash
#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Point d'entrée du service erplibre-home-streamdeck.service : lance, sous
# .venv.streamdeck, le programme du deck que nomme DECK_PROGRAM dans
# ~/.config/erplibre-home/streamdeck.conf (tiler par défaut).
#
#   ./script/install/erplibre_home_deck.sh            lance le programme
#   ./script/install/erplibre_home_deck.sh --check    ExecCondition du service
#
# --check rend 0 quand un programme est choisi (pas « none »), que le venv
# existe et qu'un deck est branché ; 1 sinon, avec la raison sur une ligne
# de la sortie d'erreur. systemd saute alors le démarrage au lieu de boucler
# sur un programme qui sort aussitôt sans deck.
#
# Sans option, le script REMPLACE son processus par le programme (exec) :
# le verrou du deck appartient à la description de fichier que le programme
# ouvre lui-même, et un parent qui le tiendrait aussi le lui refuserait.
#
# Une valeur inconnue de DECK_PROGRAM sort en 1 avec une ligne. Le script se
# place à la racine du dépôt qui le contient.
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${RACINE}"
# shellcheck source=script/install/erplibre_home_settings.sh
. "${RACINE}/script/install/erplibre_home_settings.sh"

VENV_PYTHON="${RACINE}/.venv.streamdeck/bin/python"

fail() {
    echo "[ERPLibre Home] $*" >&2
    exit 1
}

PROGRAM="$(deck_setting DECK_PROGRAM tiler)"
SCRIPT="$(deck_program_path "${PROGRAM}")" \
    || fail "unknown DECK_PROGRAM=${PROGRAM} in $(deck_settings_file);" \
        "expected tiler, controller or none"

case "${1:-}" in
    --check)
        [ "${PROGRAM}" != none ] || fail "DECK_PROGRAM=none: no deck program"
        [ -x "${VENV_PYTHON}" ] \
            || fail "${VENV_PYTHON} missing: make erplibre_home_streamdeck_install"
        deck_present || fail "no Stream Deck plugged in (USB vendor 0fd9)"
        exit 0
        ;;
    "") ;;
    *) fail "unknown option: $1 (expected --check or nothing)" ;;
esac

if [ "${PROGRAM}" = none ]; then
    echo "[ERPLibre Home] DECK_PROGRAM=none: nothing to run"
    exit 0
fi
[ -x "${VENV_PYTHON}" ] \
    || fail "${VENV_PYTHON} missing: make erplibre_home_streamdeck_install"
exec "${VENV_PYTHON}" "${RACINE}/${SCRIPT}"
```

Run: `chmod 755 script/install/erplibre_home_deck.sh`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_deck`
Expected: `Ran 17 tests`, `OK`.

- [ ] **Step 6: Format and comment hygiene**

Run: `.venv.erplibre/bin/black -l 79 --check test/test_erplibre_home_deck.py && python3 script/analyse/check_comment_hygiene.py script/install/erplibre_home_settings.sh script/install/erplibre_home_deck.sh test/test_erplibre_home_deck.py`
Expected: `1 file would be left unchanged.` and no hygiene line.

- [ ] **Step 7: Commit**

Write `"$SCRATCH/msg-1.txt"`:

```text
[ADD] install: deck service entry point and its settings library

The Stream Deck service needs one command that runs the chosen deck
program and one that tells systemd whether to start it at all.
erplibre_home_deck.sh execs the .venv.streamdeck python on the script
that DECK_PROGRAM names, tiler by default; with --check it exits 1
unless a program is chosen, the venv exists and a 0fd9 deck is plugged
in. The settings are KEY=value lines, read and never sourced. Tests run
it from a copy whose path holds a space, with a fake venv and sysfs.

--- FR ---
[ADD] install : point d'entrée du service du deck et ses réglages

Le service Stream Deck demande une commande qui lance le programme du
deck choisi, et une qui dit à systemd s'il faut le démarrer.
erplibre_home_deck.sh remplace son processus par le python de
.venv.streamdeck sur le script que nomme DECK_PROGRAM, tiler par défaut ;
avec --check il sort en 1 sauf si un programme est choisi, que le venv
existe et qu'un deck 0fd9 est branché. Les réglages, lignes CLÉ=valeur,
se lisent sans être sourcés. Testé depuis une copie à chemin avec espace.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-1.txt"
git add script/install/erplibre_home_settings.sh script/install/erplibre_home_deck.sh test/test_erplibre_home_deck.py
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-1.txt"
```

---

### Task 2: Deck lock in the tiler and the controller

**Files:**
- Create: `script/stream_deck/deck_lock.py`
- Modify: `script/stream_deck/game_tiler.py` (imports near line 39, `main()` near line 3542)
- Modify: `script/stream_deck/erplibre_controller.py` (after the import block near line 35, `__main__` near line 1241)
- Test: `test/test_deck_lock.py`

**Interfaces:**
- Consumes: nothing from other tasks.
- Produces (`script/stream_deck/deck_lock.py`, standard library only, loaded by path since `script/stream_deck` is not a package):
  - `BUSY_EXIT = 2`, `LOCK_NAME = "deck.lock"`
  - `class DeckBusy(Exception)` with `.holder: tuple[str, str]` = `(pid, program)`
  - `lock_path(environ=None) -> str` — `$XDG_RUNTIME_DIR/erplibre-home/deck.lock`, else `<tempdir>/erplibre-home-<uid>/deck.lock`
  - `read_holder(path) -> tuple[str, str]` — `"?"` for what is missing
  - `acquire(program, path=None)` → the open file, kept open until exit; raises `DeckBusy`, or `OSError` when the directory is not the user's own 0700 one or the lock path is a symlink
  - `acquire_or_exit(program, path=None)` → `acquire`, or one stderr line `Stream Deck in use by <program> (PID <pid>); close it first.` and `sys.exit(2)`
  - `holder(path=None) -> tuple[str, str] | None`
- Produces: `game_tiler.main()` and the controller's `__main__` block start with `deck_lock.acquire_or_exit("tiler")` / `deck_lock.acquire_or_exit("controller")`.

- [ ] **Step 1: Write the failing test**

Create `test/test_deck_lock.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le verrou du Stream Deck : un programme du deck à la fois.

Les détenteurs sont de vrais processus python, chacun avec son propre
verrou dans un répertoire temporaire : flock appartient à la description de
fichier ouverte, et seul un autre processus prouve qu'il tient jusqu'à la
sortie et pas au-delà.

Ce que ces tests gardent :

- un second preneur sort en 2 et nomme le programme et le PID du premier ;
- le verrou part avec le processus qui le tient, et se reprend ensuite ;
- deux ouvertures du même fichier s'excluent, même dans un seul processus,
  d'où l'exec du point d'entrée du service ;
- holder() dit qui tient le deck sans le prendre ;
- un lien à la place du verrou, ou un dossier ouvert aux autres comptes,
  est refusé sans rien écrire ;
- le tiler et le contrôleur prennent le verrou avant d'ouvrir le deck.
"""

import ast
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
DECK_DIR = RACINE / "script/stream_deck"


def charger():
    """deck_lock.py par son chemin : script/stream_deck n'est pas un
    paquet."""
    spec = importlib.util.spec_from_file_location(
        "deck_lock", DECK_DIR / "deck_lock.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Le programme d'un preneur : argv = dossier du module, programme, chemin.
PRENDRE = (
    "import sys; sys.path.insert(0, sys.argv[1]); import deck_lock;"
    " deck_lock.{fonction}(sys.argv[2], sys.argv[3]);"
    " print('pret', flush=True); sys.stdin.read()"
)


class Verrou(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.chemin = os.path.join(dossier.name, "erplibre-home", "deck.lock")
        self.deck_lock = charger()

    def detenteur(self, programme="tiler"):
        """Un processus qui prend le verrou et le garde jusqu'à ce que son
        entrée standard se ferme. Rend le Popen une fois le verrou pris."""
        proc = subprocess.Popen(
            [
                sys.executable,
                "-c",
                PRENDRE.format(fonction="acquire"),
                str(DECK_DIR),
                programme,
                self.chemin,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
        )
        self.addCleanup(proc.wait, 10)
        self.addCleanup(proc.stdin.close)
        self.assertEqual("pret\n", proc.stdout.readline())
        return proc

    def second(self, programme="controller"):
        return subprocess.run(
            [
                sys.executable,
                "-c",
                PRENDRE.format(fonction="acquire_or_exit"),
                str(DECK_DIR),
                programme,
                self.chemin,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_a_second_holder_exits_two_and_names_the_first(self):
        premier = self.detenteur("tiler")
        fini = self.second("controller")
        self.assertEqual(2, fini.returncode, fini.stderr)
        self.assertEqual("", fini.stdout)
        self.assertIn("tiler", fini.stderr)
        self.assertIn("PID %d" % premier.pid, fini.stderr)

    def test_the_lock_leaves_with_its_process(self):
        premier = self.detenteur()
        premier.stdin.close()
        premier.wait(10)
        self.assertTrue(os.path.exists(self.chemin))
        fini = self.second()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("pret\n", fini.stdout)

    def test_two_opens_in_one_process_exclude_each_other(self):
        tenu = self.deck_lock.acquire("tiler", self.chemin)
        self.addCleanup(tenu.close)
        with self.assertRaises(self.deck_lock.DeckBusy) as pris:
            self.deck_lock.acquire("controller", self.chemin)
        self.assertEqual((str(os.getpid()), "tiler"), pris.exception.holder)

    def test_holder_names_who_holds_and_takes_nothing(self):
        self.assertIsNone(self.deck_lock.holder(self.chemin))
        premier = self.detenteur("tiler")
        for _fois in range(2):
            self.assertEqual(
                (str(premier.pid), "tiler"), self.deck_lock.holder(self.chemin)
            )
        premier.stdin.close()
        premier.wait(10)
        self.assertIsNone(self.deck_lock.holder(self.chemin))

    def test_the_directory_is_private(self):
        self.detenteur()
        mode = os.stat(os.path.dirname(self.chemin)).st_mode & 0o777
        self.assertEqual(0o700, mode)

    def test_a_symlinked_lock_is_refused_and_its_target_kept(self):
        """Un lien posé à la place du verrou n'est pas suivi : le fichier
        qu'il désigne garde son contenu."""
        dossier = os.path.dirname(self.chemin)
        os.makedirs(dossier, mode=0o700)
        cible = os.path.join(os.path.dirname(dossier), "cible")
        with open(cible, "w", encoding="utf-8") as fh:
            fh.write("exemple\n")
        os.symlink(cible, self.chemin)
        with self.assertRaises(OSError):
            self.deck_lock.acquire("tiler", self.chemin)
        with open(cible, encoding="utf-8") as fh:
            self.assertEqual("exemple\n", fh.read())

    def test_a_directory_open_to_others_is_refused(self):
        dossier = os.path.dirname(self.chemin)
        os.makedirs(dossier)
        os.chmod(dossier, 0o777)
        with self.assertRaises(OSError):
            self.deck_lock.acquire("tiler", self.chemin)
        self.assertFalse(os.path.exists(self.chemin))


class LeChemin(unittest.TestCase):
    def test_under_the_runtime_dir(self):
        deck_lock = charger()
        self.assertEqual(
            "/exemple/run/erplibre-home/deck.lock",
            deck_lock.lock_path({"XDG_RUNTIME_DIR": "/exemple/run"}),
        )

    def test_without_runtime_dir_a_per_user_temp_dir(self):
        deck_lock = charger()
        self.assertEqual(
            os.path.join(
                tempfile.gettempdir(),
                "erplibre-home-%d" % os.getuid(),
                "deck.lock",
            ),
            deck_lock.lock_path({}),
        )


def fonction(source, nom):
    arbre = ast.parse(source)
    return next(
        n
        for n in ast.walk(arbre)
        if isinstance(n, ast.FunctionDef) and n.name == nom
    )


def appel_du_verrou(instruction):
    """« deck_lock.acquire_or_exit('<programme>') » : rend le programme,
    None pour toute autre instruction."""
    if not isinstance(instruction, ast.Expr):
        return None
    appel = instruction.value
    if (
        isinstance(appel, ast.Call)
        and isinstance(appel.func, ast.Attribute)
        and isinstance(appel.func.value, ast.Name)
        and appel.func.value.id == "deck_lock"
        and appel.func.attr == "acquire_or_exit"
        and len(appel.args) == 1
        and isinstance(appel.args[0], ast.Constant)
    ):
        return appel.args[0].value
    return None


class LesProgrammesLePrennent(unittest.TestCase):
    """Le verrou se prend AVANT d'ouvrir le deck : le second programme sort
    sans avoir touché au périphérique du premier."""

    def test_the_tiler_takes_it_first_thing_in_main(self):
        source = (DECK_DIR / "game_tiler.py").read_text(encoding="utf-8")
        main = fonction(source, "main")
        self.assertEqual("tiler", appel_du_verrou(main.body[0]))
        self.assertIn("\nimport deck_lock\n", source)

    def test_the_controller_takes_it_before_its_pidfile(self):
        source = (DECK_DIR / "erplibre_controller.py").read_text(
            encoding="utf-8"
        )
        arbre = ast.parse(source)
        principal = next(
            n
            for n in arbre.body
            if isinstance(n, ast.If)
            and isinstance(n.test, ast.Compare)
            and isinstance(n.test.left, ast.Name)
            and n.test.left.id == "__name__"
        )
        self.assertEqual("controller", appel_du_verrou(principal.body[0]))
        self.assertIn("\nimport deck_lock\n", source)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv.erplibre/bin/python -m unittest test.test_deck_lock`
Expected: `Ran 11 tests`, `FAILED (failures=2, errors=9)` — `FileNotFoundError` on `deck_lock.py`, and the two wiring tests fail on the first statement of `main()` and of `__main__`.

- [ ] **Step 3: Write the lock module**

Create `script/stream_deck/deck_lock.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Verrou du Stream Deck : un seul programme du deck à la fois.

Deux programmes qui ouvrent le même périphérique HID se disputent ses
touches et son écran sans qu'aucun ne le dise. Chaque programme du deck
prend ce verrou au démarrage ; le second sort en BUSY_EXIT (2) en nommant
le premier.

Le verrou est un fcntl.flock exclusif sur $XDG_RUNTIME_DIR/erplibre-home/
deck.lock. flock appartient à la description de fichier ouverte : il tient
tant que le fichier reste ouvert, donc jusqu'à la fin du processus, et deux
open() du même fichier, même dans un seul processus, s'excluent. Le fichier
porte « PID programme » du détenteur ; il reste en place après lui, et seul
le flock dit si le deck est pris.

Bibliothèque standard seulement : TODO la charge hors du venv du deck.
"""

import fcntl
import os
import stat
import sys
import tempfile

BUSY_EXIT = 2
LOCK_NAME = "deck.lock"

# Les fichiers verrouillés par ce processus : les garder ouverts garde le
# verrou jusqu'à la sortie.
_held = []


class DeckBusy(Exception):
    """Le verrou est tenu ailleurs ; `holder` vaut (pid, programme)."""

    def __init__(self, holder):
        super().__init__("Stream Deck in use by %s (PID %s)" % holder[::-1])
        self.holder = holder


def lock_path(environ=None):
    """Le chemin du verrou : sous $XDG_RUNTIME_DIR/erplibre-home, ou, sans
    lui (une connexion sans session), sous le répertoire temporaire du
    système, dans un dossier propre à l'uid."""
    environ = os.environ if environ is None else environ
    runtime = environ.get("XDG_RUNTIME_DIR")
    if runtime:
        dossier = os.path.join(runtime, "erplibre-home")
    else:
        dossier = os.path.join(
            tempfile.gettempdir(), "erplibre-home-%d" % os.getuid()
        )
    return os.path.join(dossier, LOCK_NAME)


def read_holder(path):
    """(pid, programme) écrits dans le verrou, en chaînes ; « ? » pour ce
    qui manque ou ne se lit pas."""
    try:
        with open(path, encoding="utf-8") as fh:
            mots = fh.read().split()
    except OSError:
        mots = []
    mots += ["?", "?"]
    return mots[0], mots[1]


def _open_private(path):
    """Ouvre `path` en lecture-écriture, créé en 0600 dans un dossier créé
    en 0700. Le dossier doit appartenir à l'uid courant et rester fermé aux
    autres comptes, et `path` ne doit pas être un lien symbolique : sous le
    répertoire temporaire commun, un autre compte pourrait sinon poser le
    dossier, ou un lien vers un fichier que la troncature viderait. Lève
    OSError sinon."""
    dossier = os.path.dirname(path)
    os.makedirs(dossier, mode=0o700, exist_ok=True)
    etat = os.lstat(dossier)
    if (
        not stat.S_ISDIR(etat.st_mode)
        or etat.st_uid != os.getuid()
        or etat.st_mode & 0o077
    ):
        raise PermissionError("%s: not a private directory" % dossier)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    return os.fdopen(fd, "r+", encoding="utf-8")


def acquire(program, path=None):
    """Prend le verrou pour `program` et le garde jusqu'à la sortie du
    processus. Rend le fichier ouvert ; lève DeckBusy quand une autre
    description de fichier le tient, OSError quand le dossier ou le
    fichier n'est pas privé (voir _open_private)."""
    path = path or lock_path()
    fh = _open_private(path)
    try:
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        fh.close()
        raise DeckBusy(read_holder(path)) from None
    fh.seek(0)
    fh.truncate()
    fh.write("%d %s\n" % (os.getpid(), program))
    fh.flush()
    _held.append(fh)
    return fh


def acquire_or_exit(program, path=None):
    """acquire(), ou une ligne sur la sortie d'erreur qui nomme le
    détenteur et une sortie en BUSY_EXIT."""
    try:
        return acquire(program, path)
    except DeckBusy as busy:
        pid, detenteur = busy.holder
        print(
            "Stream Deck in use by %s (PID %s); close it first."
            % (detenteur, pid),
            file=sys.stderr,
        )
        sys.exit(BUSY_EXIT)


def holder(path=None):
    """(pid, programme) du détenteur, ou None quand le verrou est libre ou
    n'a jamais été pris. Sonde par un flock non bloquant aussitôt rendu."""
    path = path or lock_path()
    try:
        fh = open(path, encoding="utf-8")
    except OSError:
        return None
    with fh:
        try:
            fcntl.flock(fh, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return read_holder(path)
        fcntl.flock(fh, fcntl.LOCK_UN)
    return None
```

- [ ] **Step 4: Take the lock in the tiler**

In `script/stream_deck/game_tiler.py`:

Edit 1/2, replace:

```python
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

import translator as _translator

GAME_META = {
```

with:

```python
    print("pip install -r script/stream_deck/requirements.txt")
    raise e

import deck_lock
import translator as _translator

GAME_META = {
```

Edit 2/2, replace:

```python


def main():
    _init_font_scale()
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
```

with:

```python


def main():
    deck_lock.acquire_or_exit("tiler")
    _init_font_scale()
    streamdecks = DeviceManager().enumerate()
    deck = next((d for d in streamdecks if d.is_visual()), None)
```

- [ ] **Step 5: Take the lock in the controller, before its pidfile**

In `script/stream_deck/erplibre_controller.py`:

Edit 1/2, replace:

```python
    )
    raise e


ASSETS_PATH = os.path.join(os.path.dirname(__file__), "Assets")
DEFAULT_BRIGHTNESS = 30
```

with:

```python
    )
    raise e

import deck_lock

ASSETS_PATH = os.path.join(os.path.dirname(__file__), "Assets")
DEFAULT_BRIGHTNESS = 30
```

Edit 2/2, replace:

```python


if __name__ == "__main__":
    _write_pidfile()
    atexit.register(_remove_pidfile)
    sdc = StreamDeckController()
```

with:

```python


if __name__ == "__main__":
    deck_lock.acquire_or_exit("controller")
    _write_pidfile()
    atexit.register(_remove_pidfile)
    sdc = StreamDeckController()
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv.erplibre/bin/python -m unittest test.test_deck_lock test.test_erplibre_home_deck`
Expected: `Ran 28 tests`, `OK`.

- [ ] **Step 7: Format and comment hygiene**

Run: `.venv.erplibre/bin/black -l 79 --check script/stream_deck/deck_lock.py test/test_deck_lock.py && python3 script/analyse/check_comment_hygiene.py script/stream_deck/deck_lock.py test/test_deck_lock.py`
Expected: `2 files would be left unchanged.` and no hygiene line.

- [ ] **Step 8: Commit**

Write `"$SCRATCH/msg-2.txt"`:

```text
[ADD] stream_deck: deck lock taken by the tiler and the controller

Two deck programs opened together fight over one HID device without
either saying so. deck_lock.py takes an exclusive flock on
$XDG_RUNTIME_DIR/erplibre-home/deck.lock and keeps it for the process
lifetime; a second taker exits 2 and names the program and PID that
hold it. game_tiler.py and erplibre_controller.py take it before
opening the deck. The lock directory must be private and the lock file
is never opened through a symlink. Tests hold it from real processes.

--- FR ---
[ADD] stream_deck : verrou du deck pris par le tiler et le contrôleur

Deux programmes ouverts ensemble se disputent un même périphérique HID
sans qu'aucun ne le dise. deck_lock.py prend un flock exclusif sur
$XDG_RUNTIME_DIR/erplibre-home/deck.lock et le garde pour la vie du
processus ; un second preneur sort en 2 en nommant le programme et le PID
qui le tiennent. game_tiler.py et erplibre_controller.py le prennent
avant d'ouvrir le deck. Le dossier du verrou doit être privé, et le
fichier ne s'ouvre jamais par un lien. Testé par de vrais processus.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-2.txt"
git add script/stream_deck/deck_lock.py script/stream_deck/game_tiler.py script/stream_deck/erplibre_controller.py test/test_deck_lock.py
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-2.txt"
```

---

### Task 3: Hand-over helper, used by TODO's games and the gallery

**Files:**
- Create: `script/install/erplibre_home_handover.sh` (mode 755)
- Modify: `script/todo/todo.py` (`VENV_STREAMDECK_PYTHON` near line 62, `_streamdeck_game_command` near line 1894)
- Modify: `script/stream_deck/gallery_server.py` (constants near line 26, `_game_bash_cmd` near line 98)
- Test: `test/test_erplibre_home_handover.py` (new), `test/test_streamdeck_entry_points.py` (`TestGalleryLaunch`, `TestTodoGamesLauncher`)

**Interfaces:**
- Consumes: Task 1's `erplibre_home_settings.sh` (`DECK_UNIT_NAME`, `deck_unit_file`, `deck_setting`).
- Produces: `script/install/erplibre_home_handover.sh <command> [arguments…]`, exit code = the command's; exit 1 without a command.
- Produces: `script.todo.todo.ERPLIBRE_HOME_HANDOVER` (absolute path of the helper); `TODO._streamdeck_game_command(path) -> str` = `<helper> <venv python> <path>`, each word `shlex.quote`d.
- Produces: `gallery_server.HANDOVER`; `_game_bash_cmd(game_file) -> str` = `cd <root> && <helper> bash -c '<replay loop>'`.

- [ ] **Step 1: Write the failing hand-over test**

Create `test/test_erplibre_home_handover.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La passation du Stream Deck entre le service et un jeu.

erplibre_home_handover.sh tourne sous un HOME temporaire, un faux systemctl
en tête du PATH : il note chaque appel dans un journal et garde l'état de
l'unité dans un fichier. Le « jeu » est une commande sh qui note son tour
dans le même journal, si bien que l'ordre arrêt, jeu, relance se lit d'un
coup.

Ce que ces tests gardent :

- une unité active est arrêtée avant le jeu et relancée après ;
- une unité arrêtée le reste, et RESTART_AFTER_GAME=no la laisse arrêtée ;
- le code du jeu est celui du script ;
- sans fichier d'unité, systemctl n'est jamais appelé ;
- un jeu interrompu (SIGINT, SIGTERM) rend quand même le deck au service ;
- le réglage se lit après la partie.
"""

import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
PASSATION = RACINE / "script/install/erplibre_home_handover.sh"
UNITE = "erplibre-home-streamdeck.service"

SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >>"$JOURNAL"
case "$2" in
    is-active) [ "$(cat "$ETAT")" = active ] ;;
    stop) [ -z "${ECHEC_STOP:-}" ] && echo inactive >"$ETAT" ;;
    start) echo active >"$ETAT" ;;
esac
"""


class Passation(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.journal = self.tmp / "journal"
        self.journal.touch()
        self.etat = self.tmp / "etat"
        bin_ = self.tmp / "bin"
        bin_.mkdir()
        (bin_ / "systemctl").write_text(SYSTEMCTL, encoding="utf-8")
        (bin_ / "systemctl").chmod(0o755)
        self.path = "%s:%s" % (bin_, os.environ.get("PATH", ""))
        self.reglages = self.home / ".config/erplibre-home/streamdeck.conf"

    def unite(self, etat):
        """Pose le fichier d'unité et l'état que rend le faux systemctl."""
        fichier = self.home / ".config/systemd/user" / UNITE
        fichier.parent.mkdir(parents=True, exist_ok=True)
        fichier.write_text("[Unit]\n", encoding="utf-8")
        self.etat.write_text(etat + "\n", encoding="utf-8")

    def regler(self, texte):
        self.reglages.parent.mkdir(parents=True, exist_ok=True)
        self.reglages.write_text(texte, encoding="utf-8")

    def jouer(self, jeu='echo jeu >>"$JOURNAL"; exit 7', env=None):
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ.update(
            {
                "HOME": str(self.home),
                "PATH": self.path,
                "JOURNAL": str(self.journal),
                "ETAT": str(self.etat),
                "REGLAGES": str(self.reglages),
            }
        )
        environ.update(env or {})
        fini = subprocess.run(
            [str(PASSATION), "sh", "-c", jeu],
            capture_output=True,
            text=True,
            env=environ,
            timeout=30,
        )
        return fini, self.journal.read_text(encoding="utf-8").splitlines()

    def test_an_active_unit_is_stopped_then_started_again(self):
        self.unite("active")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(
            [
                f"systemctl --user is-active --quiet {UNITE}",
                f"systemctl --user stop {UNITE}",
                "jeu",
                f"systemctl --user start {UNITE}",
            ],
            journal,
        )
        self.assertEqual("active", self.etat.read_text().strip())

    def test_a_stopped_unit_stays_stopped(self):
        self.unite("inactive")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(
            [f"systemctl --user is-active --quiet {UNITE}", "jeu"], journal
        )

    def test_restart_after_game_no_leaves_it_stopped(self):
        self.unite("active")
        self.regler("RESTART_AFTER_GAME=no\n")
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertNotIn(f"systemctl --user start {UNITE}", journal)
        self.assertEqual("inactive", self.etat.read_text().strip())

    def test_the_setting_is_read_after_the_game(self):
        self.unite("active")
        fini, journal = self.jouer(
            'echo jeu >>"$JOURNAL"; mkdir -p "$(dirname "$REGLAGES")";'
            ' echo RESTART_AFTER_GAME=no >"$REGLAGES"'
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertNotIn(f"systemctl --user start {UNITE}", journal)

    def test_without_the_unit_only_the_command_runs(self):
        fini, journal = self.jouer()
        self.assertEqual(7, fini.returncode, fini.stderr)
        self.assertEqual(["jeu"], journal)

    def test_an_interrupted_game_still_gives_the_deck_back(self):
        """Le signal frappe le script et le jeu ensemble, comme un Ctrl-C
        au terminal : le jeu meurt du signal, le script relance le service
        puis sort avec le code du jeu, 128 + le numéro du signal."""
        for signal_, code in (("INT", 130), ("TERM", 143)):
            with self.subTest(signal=signal_):
                self.journal.write_text("", encoding="utf-8")
                self.unite("active")
                fini, journal = self.jouer(
                    f'echo jeu >>"$JOURNAL"; kill -{signal_} $PPID $$;'
                    " sleep 5"
                )
                self.assertEqual(code, fini.returncode, fini.stderr)
                self.assertEqual(
                    f"systemctl --user start {UNITE}", journal[-1]
                )

    def test_a_failed_stop_runs_the_game_and_restarts_nothing(self):
        self.unite("active")
        fini, journal = self.jouer(env={"ECHEC_STOP": "1"})
        self.assertEqual(7, fini.returncode)
        self.assertIn("could not stop", fini.stderr)
        self.assertIn("jeu", journal)
        self.assertNotIn(f"systemctl --user start {UNITE}", journal)

    def test_no_command_is_a_usage_error(self):
        fini = subprocess.run(
            [str(PASSATION)], capture_output=True, text=True, timeout=30
        )
        self.assertEqual(1, fini.returncode)
        self.assertIn("usage", fini.stderr)


class LeScript(unittest.TestCase):
    def test_it_is_executable_valid_shell(self):
        self.assertTrue(os.access(PASSATION, os.X_OK))
        fini = subprocess.run(
            ["bash", "-n", str(PASSATION)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Update the launcher tests**

In `test/test_streamdeck_entry_points.py`:

Edit 1/4, replace:

```python
  make erplibre_home_streamdeck_install ;
- requirements.txt porte ce que le code importe, et plus lz4, que le venv
  ne sert pas ;
- la galerie lance un jeu sous son propre interpréteur, cité pour bash ;
- le menu TODO lance un jeu sous le python du venv, et sans venv il le dit
  dans la langue de l'utilisateur sans rien lancer ;
- launch_game.sh, que rien n'appelait, n'existe plus.
"""

```

with:

```python
  make erplibre_home_streamdeck_install ;
- requirements.txt porte ce que le code importe, et plus lz4, que le venv
  ne sert pas ;
- la galerie lance un jeu sous son propre interpréteur, cité pour bash, et
  toute sa boucle de parties dans une seule passation du deck ;
- le menu TODO lance un jeu sous le python du venv, à travers la passation
  du deck, et sans venv il le dit dans la langue de l'utilisateur sans rien
  lancer ;
- launch_game.sh, que rien n'appelait, n'existe plus.
"""

```

Edit 2/4, replace:

```python
    return module


class TestGalleryLaunch(unittest.TestCase):
    def test_the_game_runs_under_the_server_interpreter(self):
        galerie = charger_galerie()
        jeu = "/srv/jeux de test/game_demo.py"
        commande = galerie._game_bash_cmd(jeu)
        self.assertIn(
            f"{shlex.quote(sys.executable)} {shlex.quote(jeu)};", commande
        )
        self.assertNotIn("python3 ", commande)

    def test_the_loop_really_starts_that_interpreter(self):
        galerie = charger_galerie()
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            jeu = os.path.join(tmp, "game_demo.py")
            with open(jeu, "w", encoding="utf-8") as f:
                f.write("import sys\nprint(sys.executable)\n")
```

with:

```python
    return module


# Un faux systemctl : chaque appel au journal, l'état de l'unité dans un
# fichier. Il n'est jamais le vrai : les tests qui lancent la passation
# posent aussi un HOME temporaire.
FAUX_SYSTEMCTL = """#!/bin/sh
echo "systemctl $*" >>"$JOURNAL"
case "$2" in
    is-active) [ "$(cat "$ETAT")" = active ] ;;
    stop) echo inactive >"$ETAT" ;;
    start) echo active >"$ETAT" ;;
esac
"""


def environnement_isole(tmp, unite_active):
    """Un environnement où la passation ne voit que des faux : HOME sous
    `tmp`, un fichier d'unité, le faux systemctl en tête du PATH. Rend
    (env, journal)."""
    home = os.path.join(tmp, "home")
    unite = os.path.join(
        home, ".config/systemd/user/erplibre-home-streamdeck.service"
    )
    os.makedirs(os.path.dirname(unite))
    with open(unite, "w", encoding="utf-8") as f:
        f.write("[Unit]\n")
    faux = os.path.join(tmp, "bin")
    os.makedirs(faux)
    with open(os.path.join(faux, "systemctl"), "w", encoding="utf-8") as f:
        f.write(FAUX_SYSTEMCTL)
    os.chmod(os.path.join(faux, "systemctl"), 0o755)
    etat = os.path.join(tmp, "etat")
    with open(etat, "w", encoding="utf-8") as f:
        f.write("active\n" if unite_active else "inactive\n")
    journal = os.path.join(tmp, "journal")
    open(journal, "w", encoding="utf-8").close()
    env = {k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"}
    env.update(
        {
            "HOME": home,
            "PATH": faux + os.pathsep + env.get("PATH", ""),
            "JOURNAL": journal,
            "ETAT": etat,
        }
    )
    return env, journal


class TestGalleryLaunch(unittest.TestCase):
    def test_the_game_runs_under_the_server_interpreter(self):
        galerie = charger_galerie()
        jeu = "/srv/jeux de test/game_demo.py"
        mots = shlex.split(galerie._game_bash_cmd(jeu))
        self.assertEqual(
            mots[:6],
            [
                "cd",
                galerie.ERPLIBRE_DIR,
                "&&",
                str(ROOT / "script/install/erplibre_home_handover.sh"),
                "bash",
                "-c",
            ],
        )
        boucle = mots[6]
        self.assertIn(
            f"{shlex.quote(sys.executable)} {shlex.quote(jeu)};", boucle
        )
        self.assertNotIn("python3 ", boucle)

    def test_the_loop_really_starts_that_interpreter(self):
        galerie = charger_galerie()
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            env, _journal = environnement_isole(tmp, unite_active=False)
            jeu = os.path.join(tmp, "game_demo.py")
            with open(jeu, "w", encoding="utf-8") as f:
                f.write("import sys\nprint(sys.executable)\n")
```

Edit 3/4, replace:

```python
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(res.stdout.splitlines()[0], sys.executable)


class TestLaunchGameScriptGone(unittest.TestCase):
```

with:

```python
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
        self.assertEqual(res.stdout.splitlines()[0], sys.executable)

    def test_two_rounds_run_inside_one_handover(self):
        """« r » puis Entrée relance la partie sans rendre le deck : le
        service s'arrête une fois avant la première, revient une fois après
        la dernière."""
        galerie = charger_galerie()
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            env, journal = environnement_isole(tmp, unite_active=True)
            jeu = os.path.join(tmp, "game_demo.py")
            with open(jeu, "w", encoding="utf-8") as f:
                f.write(
                    "import os\n"
                    "with open(os.environ['JOURNAL'], 'a') as j:\n"
                    "    j.write('partie\\n')\n"
                )
            res = subprocess.run(
                ["bash", "-c", galerie._game_bash_cmd(jeu)],
                input="r\n\n",
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
            with open(journal, encoding="utf-8") as f:
                appels = f.read().splitlines()
        unite = "erplibre-home-streamdeck.service"
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(
            appels,
            [
                f"systemctl --user is-active --quiet {unite}",
                f"systemctl --user stop {unite}",
                "partie",
                "partie",
                f"systemctl --user start {unite}",
            ],
        )


class TestLaunchGameScriptGone(unittest.TestCase):
```

Edit 4/4, replace:

```python
            rendu = todo.prompt_execute_streamdeck_games()
        return todo, rendu, sortie.getvalue()

    def test_the_command_names_the_streamdeck_venv(self):
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        commande = todo._streamdeck_game_command(self.JEU)
        python = commande.split(" ", 1)[0]
        self.assertTrue(
            python.endswith(os.path.join(".venv.streamdeck", "bin", "python"))
        )
        self.assertTrue(commande.endswith(" " + shlex.quote(self.JEU)))

    def test_the_menu_runs_the_chosen_game_with_that_command(self):
        todo, rendu, _sortie = self.menu(self.present)
        self.assertFalse(rendu)
        todo.execute.exec_command_live.assert_called_once_with(
            f"{shlex.quote(self.present)} {shlex.quote(self.JEU)}",
            source_erplibre=False,
        )

    def test_without_the_venv_it_says_so_and_launches_nothing(self):
        attendus = {
```

with:

```python
            rendu = todo.prompt_execute_streamdeck_games()
        return todo, rendu, sortie.getvalue()

    def test_the_command_hands_the_deck_over_to_the_streamdeck_venv(self):
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        mots = shlex.split(todo._streamdeck_game_command(self.JEU))
        self.assertEqual(
            mots,
            [
                str(ROOT / "script/install/erplibre_home_handover.sh"),
                str(ROOT / ".venv.streamdeck/bin/python"),
                self.JEU,
            ],
        )

    def test_the_menu_runs_the_chosen_game_with_that_command(self):
        todo, rendu, _sortie = self.menu(self.present)
        self.assertFalse(rendu)
        todo.execute.exec_command_live.assert_called_once_with(
            f"{shlex.quote(todo_mod.ERPLIBRE_HOME_HANDOVER)}"
            f" {shlex.quote(self.present)} {shlex.quote(self.JEU)}",
            source_erplibre=False,
        )

    def test_the_command_really_runs_the_game(self):
        """La commande, jouée par bash : la passation, sans unité, lance
        le python du venv sur le jeu."""
        with tempfile.TemporaryDirectory(prefix="jeu demo ") as tmp:
            env, _journal = environnement_isole(tmp, unite_active=False)
            python = os.path.join(tmp, "python")
            with open(python, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\necho "$1"\n')
            os.chmod(python, 0o755)
            todo = todo_mod.TODO.__new__(todo_mod.TODO)
            with mock.patch.object(todo_mod, "VENV_STREAMDECK_PYTHON", python):
                commande = todo._streamdeck_game_command(self.JEU)
            res = subprocess.run(
                ["bash", "-c", commande],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )
        self.assertEqual(0, res.returncode, res.stderr)
        self.assertEqual(self.JEU, res.stdout.strip())

    def test_without_the_venv_it_says_so_and_launches_nothing(self):
        attendus = {
```

- [ ] **Step 3: Run them to verify they fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_handover test.test_streamdeck_entry_points`
Expected: `Ran 32 tests`, `FAILED (failures=4, errors=10)` — the helper does not exist, the TODO command has no hand-over word, and the gallery command is a bare loop.

- [ ] **Step 4: Write the hand-over helper**

Create `script/install/erplibre_home_handover.sh`:

```bash
#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
# Passe le Stream Deck du service à une commande (un jeu), puis le lui rend.
#
#   ./script/install/erplibre_home_handover.sh <commande> [arguments…]
#
# 1. si erplibre-home-streamdeck.service est actif, il est arrêté ;
# 2. la commande tourne au premier plan, son code est gardé ;
# 3. si le service était actif et que RESTART_AFTER_GAME vaut yes (défaut),
#    il est relancé ;
# 4. le script sort avec le code de la commande.
#
# Sans fichier d'unité (niveau de base, ou installation à la main), seule la
# commande tourne : systemctl n'est pas appelé. Un Ctrl-C ou un SIGTERM
# pendant la commande arrive aussi à elle ; le script attend sa fin puis
# rend le deck au service, au lieu de mourir avec elle et de le garder
# arrêté. RESTART_AFTER_GAME se lit APRÈS la commande : un réglage changé
# pendant la partie compte.
set -uo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# shellcheck source=script/install/erplibre_home_settings.sh
. "${RACINE}/script/install/erplibre_home_settings.sh"

if [ $# -eq 0 ]; then
    echo "usage: $0 <command> [arguments…]" >&2
    exit 1
fi

was_active=0
if [ -e "$(deck_unit_file)" ] \
    && systemctl --user is-active --quiet "${DECK_UNIT_NAME}"; then
    if systemctl --user stop "${DECK_UNIT_NAME}"; then
        was_active=1
    else
        echo "[ERPLibre Home] could not stop ${DECK_UNIT_NAME};" \
            "the game may find the deck taken" >&2
    fi
fi

# Une action vide (et non « '' », qui ignorerait le signal) : le signal
# interrompt la commande, puis le script reprend après elle.
trap ':' INT TERM HUP
"$@"
rc=$?

if [ "${was_active}" = 1 ] \
    && [ "$(deck_setting RESTART_AFTER_GAME yes)" = yes ]; then
    systemctl --user start "${DECK_UNIT_NAME}" \
        || echo "[ERPLibre Home] could not start ${DECK_UNIT_NAME} again" >&2
fi
exit "${rc}"
```

Run: `chmod 755 script/install/erplibre_home_handover.sh`

- [ ] **Step 5: TODO's game command goes through it**

In `script/todo/todo.py`:

Edit 1/2, replace:

```python
# checkout, et le python du système n'a pas les modules du deck.
VENV_STREAMDECK_PYTHON = os.path.join(
    new_path, ".venv.streamdeck", "bin", "python"
)


```

with:

```python
# checkout, et le python du système n'a pas les modules du deck.
VENV_STREAMDECK_PYTHON = os.path.join(
    new_path, ".venv.streamdeck", "bin", "python"
)
# Passe le deck du service Stream Deck au jeu, puis le lui rend.
ERPLIBRE_HOME_HANDOVER = os.path.join(
    new_path, "script", "install", "erplibre_home_handover.sh"
)


```

Edit 2/2, replace:

```python

    def _streamdeck_game_command(self, path):
        """Rend la commande shell qui lance le jeu `path` sous le python de
        .venv.streamdeck ; les deux chemins sont cités pour bash."""
        return f"{shlex.quote(VENV_STREAMDECK_PYTHON)} {shlex.quote(path)}"

    def _scan_streamdeck_games(self):
        """Scan game_*.py files and extract descriptions."""
```

with:

```python

    def _streamdeck_game_command(self, path):
        """Rend la commande shell qui lance le jeu `path` sous le python de
        .venv.streamdeck, à travers erplibre_home_handover.sh : le service
        du deck s'arrête pendant la partie et revient après. Les trois
        chemins sont cités pour bash."""
        return (
            f"{shlex.quote(ERPLIBRE_HOME_HANDOVER)}"
            f" {shlex.quote(VENV_STREAMDECK_PYTHON)} {shlex.quote(path)}"
        )

    def _scan_streamdeck_games(self):
        """Scan game_*.py files and extract descriptions."""
```

- [ ] **Step 6: The gallery's loop goes through it, once**

In `script/stream_deck/gallery_server.py`:

Edit 1/3, replace:

```python
PORT = 8042
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERPLIBRE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))

# Game metadata cache (populated at startup)
_game_cache = []
```

with:

```python
PORT = 8042
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ERPLIBRE_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, "..", ".."))
# Hands the deck over from the service to a game, then back.
HANDOVER = os.path.join(
    ERPLIBRE_DIR, "script", "install", "erplibre_home_handover.sh"
)

# Game metadata cache (populated at startup)
_game_cache = []
```

Edit 2/3, replace:

```python
    PATH. Every path is quoted for bash. The loop restarts the game when the
    user types "r" + Enter at the end-of-game prompt, which avoids
    re-picking it from the gallery; any other answer, or a closed stdin,
    ends it.
    """
    return (
        f"cd {shlex.quote(ERPLIBRE_DIR)} && while true; do "
        f"{shlex.quote(sys.executable)} {shlex.quote(game_file)}; "
        f'echo ""; '
        f'echo "Game ended. Press [r]+enter to restart, '
```

with:

```python
    PATH. Every path is quoted for bash. The loop restarts the game when the
    user types "r" + Enter at the end-of-game prompt, which avoids
    re-picking it from the gallery; any other answer, or a closed stdin,
    ends it. The whole loop runs inside one erplibre_home_handover.sh: the
    deck service stops before the first game and comes back once, when the
    loop ends, not between two rounds.
    """
    loop = (
        f"while true; do "
        f"{shlex.quote(sys.executable)} {shlex.quote(game_file)}; "
        f'echo ""; '
        f'echo "Game ended. Press [r]+enter to restart, '
```

Edit 3/3, replace:

```python
        f"read -r ans; "
        f'if [ "$ans" != "r" ] && [ "$ans" != "R" ]; then break; fi; '
        f"done"
    )


```

with:

```python
        f"read -r ans; "
        f'if [ "$ans" != "r" ] && [ "$ans" != "R" ]; then break; fi; '
        f"done"
    )
    return (
        f"cd {shlex.quote(ERPLIBRE_DIR)} && "
        f"{shlex.quote(HANDOVER)} bash -c {shlex.quote(loop)}"
    )


```

- [ ] **Step 7: Run the tests to verify they pass**

Run: `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_handover test.test_streamdeck_entry_points`
Expected: `Ran 32 tests`, `OK`.

- [ ] **Step 8: Format and comment hygiene**

Run: `.venv.erplibre/bin/black -l 79 --check test/test_erplibre_home_handover.py test/test_streamdeck_entry_points.py && python3 script/analyse/check_comment_hygiene.py script/install/erplibre_home_handover.sh script/todo/todo.py script/stream_deck/gallery_server.py test/test_erplibre_home_handover.py test/test_streamdeck_entry_points.py`
Expected: `2 files would be left unchanged.` and no hygiene line.

- [ ] **Step 9: Commit**

Write `"$SCRATCH/msg-3.txt"`:

```text
[ADD] install: games hand the deck over from the service and back

A game started while the deck service runs would meet the deck taken.
erplibre_home_handover.sh stops an active unit, runs the game in the
foreground, starts the unit again unless RESTART_AFTER_GAME=no, and
exits with the game's code; a Ctrl-C or SIGTERM still gives the deck
back. Without the unit file it only runs the game. TODO's games menu
and the gallery go through it; the gallery's replay loop stays inside
one hand-over, so the service comes back once.

--- FR ---
[ADD] install : les jeux prennent le deck au service et le lui rendent

Un jeu lancé pendant que le service du deck tourne trouverait le deck
pris. erplibre_home_handover.sh arrête l'unité active, lance le jeu au
premier plan, relance l'unité sauf si RESTART_AFTER_GAME=no, et sort avec
le code du jeu ; un Ctrl-C ou un SIGTERM rend quand même le deck. Sans
fichier d'unité, il ne lance que le jeu. Le menu des jeux de TODO et la
galerie passent par lui ; la boucle de la galerie tient dans une seule
passation, et le service revient une fois.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-3.txt"
git add script/install/erplibre_home_handover.sh script/todo/todo.py script/stream_deck/gallery_server.py test/test_erplibre_home_handover.py test/test_streamdeck_entry_points.py
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-3.txt"
```

---

### Task 4: Installer writes, enables and removes the deck service

**Files:**
- Modify: `script/install/install_erplibre_home.sh` (header lines 5-12, variables lines 30-46, `usage` lines 67-96, `parse_args` lines 98-130, new section before `# ---------- Extension GNOME ----------` line 414, `uninstall_streamdeck` lines 582-595, `uninstall` comment lines 601-607, `summary` lines 633-645, new `step_service` before `step_extension` line 683, `step_uninstall` lines 713-734, `main` lines 736-770)
- Modify: `script/stream_deck/INSTALL.base.md` (options tables lines 75-82 and 92-99, new section after the udev rule section line 183); regenerate `INSTALL.md`, `INSTALL.fr.md`
- Test: `test/test_install_erplibre_home.py`

**Interfaces:**
- Consumes: Task 1's `erplibre_home_settings.sh` (`DECK_UNIT_NAME`, `deck_unit_file`, `deck_settings_file`, `deck_program_path`); Task 1's `erplibre_home_deck.sh` (copied by the `systemd-analyze` test).
- Produces (installer, callable with `ERPLIBRE_HOME_SOURCE_ONLY=1`): variables `UNIT_FILE`, `SETTINGS_FILE`, `DECK_PROGRAM` (`tiler`/`controller`/`none`, empty when the option is not given), `AUTOSTART` (0/1), `RESTART_AFTER_GAME` (`yes`/`no`, empty when not given), `SERVICE_OPTIONS` (count), `SERVICE_HINTS` (array); functions `check_checkout_path`, `set_restart_after_game OPTION`, `unit_content` (prints the unit for `RACINE`), `service_setting KEY GIVEN DEFAULT` (given, else the file's value, else default), `service_pairs` (the two `KEY=value` lines to write), `settings_content FILE KEY=value…`, `user_systemctl ARGS…` (= `on_session_bus systemctl --user`), `write_settings`, `write_unit` (return 1 when unchanged), `install_service`, `uninstall_service`, `step_service`.
- Produces: dry-run lines `write: <unit>`, `write: <settings>`, `setting: KEY=value` (the two lines `service_pairs` resolves), `systemctl: --user daemon-reload`, `systemctl: --user enable erplibre-home-streamdeck.service`; uninstall dry-run `systemctl: --user stop …`, `systemctl: --user disable …`, `remove: <unit>`, `systemctl: --user daemon-reload`, `remove: <settings>` before `remove: <udev rule>`.

- [ ] **Step 1: Write the failing tests**

In `test/test_install_erplibre_home.py` (the `sourcer` helper now runs under a temporary `HOME`, `Installateur.lancer` and `TestExtensionSeule.lancer` drop `XDG_CONFIG_HOME`, `TestExtensionSeule` copies the settings library next to the installer, and the new classes cover options, unit text, install and removal):

Edit 1/12, replace:

```python
  deck ; --stream-deck ajoute les trois, et EPEL n'est activé qu'avec lui,
  sur les reconstructions d'EL, où wmctrl en dépend ;
- les traductions se compilent par « msgfmt --check », aux deux niveaux ;
- --uninstall retire tout, --uninstall --stream-deck la règle et le venv
  seulement, et aucun des deux ne vérifie le système ;
- un système non supporté sort en 2 avec UNE ligne « UNSUPPORTED: » sur la
  sortie d'erreur, celle que TODO et le test long affichent ;
- la liste des versions de GNOME acceptées est celle de metadata.json, lue
```

with:

```python
  deck ; --stream-deck ajoute les trois, et EPEL n'est activé qu'avec lui,
  sur les reconstructions d'EL, où wmctrl en dépend ;
- les traductions se compilent par « msgfmt --check », aux deux niveaux ;
- --uninstall retire tout, --uninstall --stream-deck tout sauf
  l'extension, et aucun des deux ne vérifie le système ;
- le niveau Stream Deck écrit l'unité du service et ses réglages ; une
  option absente garde la valeur déjà en place, le défaut ne vaut que pour
  une clé absente ; il n'active l'unité qu'avec --autostart et ne la
  démarre jamais ; les deux désinstallations l'arrêtent et la retirent ;
- les options du service exigent --stream-deck, --restart-after-game et
  --no-restart-after-game s'excluent, et un dépôt dont le chemin porte un
  caractère que systemd refuse arrête l'installation ;
- un système non supporté sort en 2 avec UNE ligne « UNSUPPORTED: » sur la
  sortie d'erreur, celle que TODO et le test long affichent ;
- la liste des versions de GNOME acceptées est celle de metadata.json, lue
```

Edit 2/12, replace:

```python
EXTENSION = RACINE / "script/gnome-extension/erplibre_home"
UUID = "erplibre-home@technolibre.ca"
REGLE = "/etc/udev/rules.d/70-streamdeck.rules"

# Des os-release réduits à ce que le script lit : ID et ID_LIKE.
OS_RELEASE = {
```

with:

```python
EXTENSION = RACINE / "script/gnome-extension/erplibre_home"
UUID = "erplibre-home@technolibre.ca"
REGLE = "/etc/udev/rules.d/70-streamdeck.rules"
UNITE = "erplibre-home-streamdeck.service"

# Des os-release réduits à ce que le script lit : ID et ID_LIKE.
OS_RELEASE = {
```

Edit 3/12, replace:

```python
            self.home / ".local/share/gnome-shell/extensions" / UUID
        )
        self.venv = str(RACINE / ".venv.streamdeck")

    def _commande(self, nom, corps):
        """Pose une commande factice en tête du PATH du script."""
```

with:

```python
            self.home / ".local/share/gnome-shell/extensions" / UUID
        )
        self.venv = str(RACINE / ".venv.streamdeck")
        self.unite = str(self.home / ".config/systemd/user" / UNITE)
        self.reglages = str(
            self.home / ".config/erplibre-home/streamdeck.conf"
        )

    def _commande(self, nom, corps):
        """Pose une commande factice en tête du PATH du script."""
```

Edit 4/12, replace:

```python
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("STREAMDECK_")
        }
        env["HOME"] = str(self.home)
        env["PATH"] = "%s:%s" % (self.bin, env.get("PATH", ""))
```

with:

```python
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("STREAMDECK_") and k != "XDG_CONFIG_HOME"
        }
        env["HOME"] = str(self.home)
        env["PATH"] = "%s:%s" % (self.bin, env.get("PATH", ""))
```

Edit 5/12, replace:

```python
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [self.lien, REGLE, self.venv], self.lignes(fini, "remove: ")
        )
        self.assertEqual(
            ["org.gnome.shell enabled-extensions -" + UUID],
```

with:

```python
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [self.lien, self.unite, self.reglages, REGLE, self.venv],
            self.lignes(fini, "remove: "),
        )
        self.assertEqual(
            ["org.gnome.shell enabled-extensions -" + UUID],
```

Edit 6/12, replace:

```python
        )
        self.assertEqual([], self.lignes(fini, "packages: "))

    def test_uninstall_stream_deck_removes_the_rule_and_the_venv_only(self):
        """L'extension reste liée et active : ses indicateurs disent alors
        que le niveau Stream Deck n'est pas installé."""
        fini = self.lancer("--uninstall", "--stream-deck", "--dry-run")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual([REGLE, self.venv], self.lignes(fini, "remove: "))
        self.assertEqual([], self.lignes(fini, "gsettings: "))
        self.assertNotIn(self.lien, fini.stdout)
        self.assertNotIn("enabled-extensions", fini.stdout)
```

with:

```python
        )
        self.assertEqual([], self.lignes(fini, "packages: "))

    def test_uninstall_stream_deck_keeps_the_extension_only(self):
        """L'extension reste liée et active : ses indicateurs disent alors
        que le niveau Stream Deck n'est pas installé."""
        fini = self.lancer("--uninstall", "--stream-deck", "--dry-run")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [self.unite, self.reglages, REGLE, self.venv],
            self.lignes(fini, "remove: "),
        )
        self.assertEqual([], self.lignes(fini, "gsettings: "))
        self.assertNotIn(self.lien, fini.stdout)
        self.assertNotIn("enabled-extensions", fini.stdout)
```

Edit 7/12, replace:

```python


INSTALLEUR = SCRIPT
MAKEFILE_STREAMDECK = RACINE / "conf/make.streamdeck.Makefile"


```

with:

```python


INSTALLEUR = SCRIPT
BIBLIOTHEQUE = RACINE / "script/install/erplibre_home_settings.sh"
MAKEFILE_STREAMDECK = RACINE / "conf/make.streamdeck.Makefile"


```

Edit 8/12, replace:

```python
    ERPLIBRE_HOME_SOURCE_ONLY=1 définit les fonctions et s'arrête ; le
    fragment les redéfinit au besoin (sudo, gsettings_bus…) avant de les
    appeler. DBUS_SESSION_BUS_ADDRESS est retiré de l'environnement, sauf
    si `env` le pose. Rend le CompletedProcess.
    """
    if "ERPLIBRE_HOME_SOURCE_ONLY" not in INSTALLEUR.read_text(
        encoding="utf-8"
```

with:

```python
    ERPLIBRE_HOME_SOURCE_ONLY=1 définit les fonctions et s'arrête ; le
    fragment les redéfinit au besoin (sudo, gsettings_bus…) avant de les
    appeler. DBUS_SESSION_BUS_ADDRESS est retiré de l'environnement, sauf
    si `env` le pose. HOME est un répertoire temporaire et XDG_CONFIG_HOME
    est retiré : l'unité et les réglages du service que le script sourcé
    désigne ne sont jamais ceux du compte qui lance les tests. Rend le
    CompletedProcess.
    """
    if "ERPLIBRE_HOME_SOURCE_ONLY" not in INSTALLEUR.read_text(
        encoding="utf-8"
```

Edit 9/12, replace:

```python
            "sourcing it would run main"
        )
    code = 'ERPLIBRE_HOME_SOURCE_ONLY=1 source "$INSTALLEUR"\n' + fragment
    environ = dict(os.environ)
    environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
    environ["INSTALLEUR"] = str(INSTALLEUR)
    environ.update(env or {})
    return subprocess.run(
        ["bash", "-c", code],
        capture_output=True,
        text=True,
        env=environ,
        timeout=60,
    )


class TestListeEnabledExtensions(unittest.TestCase):
```

with:

```python
            "sourcing it would run main"
        )
    code = 'ERPLIBRE_HOME_SOURCE_ONLY=1 source "$INSTALLEUR"\n' + fragment
    with tempfile.TemporaryDirectory() as maison:
        environ = dict(os.environ)
        environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
        environ.pop("XDG_CONFIG_HOME", None)
        environ["HOME"] = maison
        environ["INSTALLEUR"] = str(INSTALLEUR)
        environ.update(env or {})
        return subprocess.run(
            ["bash", "-c", code],
            capture_output=True,
            text=True,
            env=environ,
            timeout=60,
        )


class TestListeEnabledExtensions(unittest.TestCase):
```

Edit 10/12, replace:

```python
            self.assertTrue((cible / "metadata.json").exists())


OUTILS_EXTENSION = shutil.which("glib-compile-schemas") and shutil.which(
    "msgfmt"
)
```

with:

```python
            self.assertTrue((cible / "metadata.json").exists())


class LesOptionsDuService(Installateur):
    """--deck-program, --autostart, --[no-]restart-after-game : au niveau
    Stream Deck seulement, et ce que --dry-run en annonce."""

    def test_help_lists_them(self):
        fini = self.lancer("--help")
        for option in (
            "--deck-program=tiler|controller|none",
            "--autostart",
            "--restart-after-game",
            "--no-restart-after-game",
        ):
            self.assertIn(option, fini.stdout)

    def test_without_stream_deck_they_are_a_usage_error(self):
        for option in (
            "--deck-program=tiler",
            "--autostart",
            "--restart-after-game",
            "--no-restart-after-game",
        ):
            with self.subTest(option=option):
                fini = self.lancer(option, "--dry-run")
                self.assertEqual(1, fini.returncode, fini.stdout)
                self.assertIn("--stream-deck", fini.stderr)
                self.assertNotIn("UNSUPPORTED", fini.stderr)
                self.assertEqual([], self.lignes(fini, "family="))

    def test_with_uninstall_they_are_a_usage_error(self):
        fini = self.lancer(
            "--uninstall", "--stream-deck", "--autostart", "--dry-run"
        )
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertEqual([], self.lignes(fini, "remove: "))

    def test_an_unknown_program_is_a_usage_error(self):
        fini = self.lancer(
            "--stream-deck", "--deck-program=exemple", "--dry-run"
        )
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("exemple", fini.stderr)
        self.assertEqual([], self.lignes(fini, "family="))

    def test_both_restart_options_are_a_usage_error(self):
        for ordre in (
            ("--restart-after-game", "--no-restart-after-game"),
            ("--no-restart-after-game", "--restart-after-game"),
        ):
            with self.subTest(ordre=ordre):
                fini = self.lancer("--stream-deck", *ordre, "--dry-run")
                self.assertEqual(1, fini.returncode, fini.stdout)
                self.assertIn("--no-restart-after-game", fini.stderr)
                self.assertEqual([], self.lignes(fini, "family="))

    def test_the_dry_run_shows_the_settings_kept_or_given(self):
        """Une option absente garde la valeur des réglages en place ; une
        option donnée la remplace."""
        Path(self.reglages).parent.mkdir(parents=True)
        Path(self.reglages).write_text(
            "DECK_PROGRAM=controller\nRESTART_AFTER_GAME=no\n",
            encoding="utf-8",
        )
        for options, attendus in (
            ((), ["DECK_PROGRAM=controller", "RESTART_AFTER_GAME=no"]),
            (
                ("--restart-after-game",),
                ["DECK_PROGRAM=controller", "RESTART_AFTER_GAME=yes"],
            ),
            (
                ("--deck-program=tiler",),
                ["DECK_PROGRAM=tiler", "RESTART_AFTER_GAME=no"],
            ),
        ):
            with self.subTest(options=options):
                fini = self.lancer("--stream-deck", *options, "--dry-run")
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(attendus, self.lignes(fini, "setting: "))

    def test_the_defaults_write_unit_and_settings_without_enabling(self):
        fini = self.lancer("--stream-deck", "--dry-run")
        self.assertEqual(0, fini.returncode, fini.stderr)
        ecrits = self.lignes(fini, "write: ")
        self.assertIn(self.unite, ecrits)
        self.assertIn(self.reglages, ecrits)
        self.assertEqual(
            ["DECK_PROGRAM=tiler", "RESTART_AFTER_GAME=yes"],
            self.lignes(fini, "setting: "),
        )
        self.assertEqual(
            ["--user daemon-reload"], self.lignes(fini, "systemctl: ")
        )

    def test_the_options_reach_the_settings_and_the_enable(self):
        fini = self.lancer(
            "--stream-deck",
            "--deck-program=controller",
            "--autostart",
            "--no-restart-after-game",
            "--dry-run",
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            ["DECK_PROGRAM=controller", "RESTART_AFTER_GAME=no"],
            self.lignes(fini, "setting: "),
        )
        self.assertEqual(
            ["--user daemon-reload", "--user enable " + UNITE],
            self.lignes(fini, "systemctl: "),
        )

    def test_the_base_has_no_service(self):
        fini = self.lancer("--dry-run", "--with-extras")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertNotIn(self.unite, fini.stdout)
        self.assertEqual([], self.lignes(fini, "setting: "))
        self.assertEqual([], self.lignes(fini, "systemctl: "))

    def test_both_uninstalls_stop_and_disable_it(self):
        for niveau in ((), ("--stream-deck",)):
            with self.subTest(niveau=niveau):
                fini = self.lancer("--uninstall", *niveau, "--dry-run")
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(
                    [
                        "--user stop " + UNITE,
                        "--user disable " + UNITE,
                        "--user daemon-reload",
                    ],
                    self.lignes(fini, "systemctl: "),
                )


# L'unité attendue pour un dépôt dont le chemin porte une espace et « % ».
UNITE_ATTENDUE = """[Unit]
Description=ERPLibre Home Stream Deck program
PartOf=graphical-session.target
After=graphical-session.target

[Service]
Type=simple
WorkingDirectory=/srv/depot de test 100%%
ExecCondition="/srv/depot de test 100%%/script/install/erplibre_home_deck.sh" --check
ExecStart="/srv/depot de test 100%%/script/install/erplibre_home_deck.sh"
Restart=on-failure
RestartSec=3
RestartPreventExitStatus=2

[Install]
WantedBy=graphical-session.target
"""


class TestUniteDuService(unittest.TestCase):
    def test_the_unit_text_quotes_and_escapes_the_checkout(self):
        fait = sourcer('RACINE="/srv/depot de test 100%"\nunit_content\n')
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(fait.stdout, UNITE_ATTENDUE)

    @unittest.skipUnless(
        shutil.which("systemd-analyze"), "systemd-analyze absent"
    )
    def test_systemd_loads_the_unit_of_a_checkout_with_space_and_percent(
        self,
    ):
        """systemd-analyze verify lit l'unité hors ligne et vérifie que
        ExecStart et ExecCondition désignent un exécutable : le chemin
        cité et échappé est bien celui du dépôt."""
        with tempfile.TemporaryDirectory() as dossier:
            depot = Path(dossier, "copie du depot 100%")
            (depot / "script/install").mkdir(parents=True)
            for nom in (
                "install_erplibre_home.sh",
                "erplibre_home_settings.sh",
                "erplibre_home_deck.sh",
            ):
                shutil.copy2(
                    RACINE / "script/install" / nom, depot / "script/install"
                )
            unite = Path(dossier, UNITE)
            fait = sourcer(
                'unit_content >"$UNITE"\n',
                {
                    "INSTALLEUR": str(
                        depot / "script/install/install_erplibre_home.sh"
                    ),
                    "UNITE": str(unite),
                },
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            verifie = subprocess.run(
                ["systemd-analyze", "verify", str(unite)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(
            verifie.returncode, 0, verifie.stdout + verifie.stderr
        )
        self.assertNotIn("not executable", verifie.stderr)

    def test_a_path_systemd_refuses_stops_the_install(self):
        for chemin in ("/srv/l'exemple", '/srv/le "depot"', "/srv/a\\b"):
            with self.subTest(chemin=chemin):
                fait = sourcer(
                    'RACINE="$CHEMIN"\ncheck_checkout_path\necho passe\n',
                    {"CHEMIN": chemin},
                )
                self.assertEqual(fait.returncode, 1)
                self.assertIn(chemin, fait.stderr)
                self.assertNotIn("passe", fait.stdout)

    def test_space_and_percent_pass(self):
        fait = sourcer(
            'RACINE="/srv/depot de test 100%"\ncheck_checkout_path\n'
            "echo passe\n"
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual("passe\n", fait.stdout)


# systemctl simulé : chaque appel au journal ; ENABLED fait réussir
# is-enabled, ECHEC fait échouer tout appel (pas de gestionnaire joignable).
SYSTEMCTL_FAUX = (
    'on_session_bus() { "$@"; }\n'
    "systemctl() {\n"
    '    echo "systemctl $*" >>"$JOURNAL"\n'
    '    [ -z "${ECHEC:-}" ] || return 1\n'
    '    case "$2" in is-enabled) [ -n "${ENABLED:-}" ] ;; esac\n'
    "}\n"
)


class TestServiceInstalle(unittest.TestCase):
    """install_service sur un HOME temporaire et un systemctl simulé."""

    def jouer(self, dossier, apres="", env=None, reglages=None):
        """Lance install_service, puis `apres`. T_PROGRAMME, T_RELANCE et
        T_AUTOSTART dans `env` tiennent lieu des options ; T_PROGRAMME ou
        T_RELANCE absent, l'option n'a pas été donnée. Rend (fait, appels,
        unité, réglages)."""
        unite = Path(dossier, "config/systemd/user", UNITE)
        conf = Path(dossier, "config/erplibre-home/streamdeck.conf")
        if reglages is not None:
            conf.parent.mkdir(parents=True, exist_ok=True)
            conf.write_text(reglages, encoding="utf-8")
        journal = Path(dossier, "appels")
        journal.touch()
        environ = {
            "XDG_CONFIG_HOME": str(Path(dossier, "config")),
            "JOURNAL": str(journal),
        }
        environ.update(env or {})
        fait = sourcer(
            'UNIT_FILE="$(deck_unit_file)"\n'
            'SETTINGS_FILE="$(deck_settings_file)"\n'
            'DECK_PROGRAM="${T_PROGRAMME:-}"\n'
            'RESTART_AFTER_GAME="${T_RELANCE:-}"\n'
            'AUTOSTART="${T_AUTOSTART:-0}"\n'
            + SYSTEMCTL_FAUX
            + "install_service\nsummary\n"
            + apres,
            environ,
        )
        return fait, journal.read_text().splitlines(), unite, conf

    def test_it_writes_unit_and_settings_and_reloads(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, appels, unite, conf = self.jouer(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("ExecStart=", unite.read_text())
            self.assertEqual(
                "DECK_PROGRAM=tiler\nRESTART_AFTER_GAME=yes\n",
                conf.read_text(),
            )
            self.assertEqual(["systemctl --user daemon-reload"], appels)

    def test_it_enables_only_with_autostart_and_never_starts(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, appels, _unite, _conf = self.jouer(
                dossier, env={"T_AUTOSTART": "1"}
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                [
                    "systemctl --user daemon-reload",
                    f"systemctl --user is-enabled --quiet {UNITE}",
                    f"systemctl --user enable {UNITE}",
                ],
                appels,
            )
            self.assertFalse([a for a in appels if " start " in a + " "])

    def test_the_options_land_in_the_settings_and_other_keys_stay(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, conf = self.jouer(
                dossier,
                env={"T_PROGRAMME": "controller", "T_RELANCE": "no"},
                reglages="# note\nEXEMPLE=1\nDECK_PROGRAM=none\n",
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                "# note\nEXEMPLE=1\nDECK_PROGRAM=controller\n"
                "RESTART_AFTER_GAME=no\n",
                conf.read_text(),
            )

    def test_an_install_without_options_keeps_earlier_choices(self):
        """Une option absente garde la valeur déjà dans les réglages : une
        réinstallation ne défait pas un choix fait par une installation
        antérieure ou par le menu Stream Deck de TODO."""
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, conf = self.jouer(
                dossier,
                reglages="DECK_PROGRAM=controller\nRESTART_AFTER_GAME=no\n",
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                "DECK_PROGRAM=controller\nRESTART_AFTER_GAME=no\n",
                conf.read_text(),
            )

    def test_one_option_changes_its_key_only(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, conf = self.jouer(
                dossier,
                env={"T_RELANCE": "yes"},
                reglages="DECK_PROGRAM=none\nRESTART_AFTER_GAME=no\n",
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                "DECK_PROGRAM=none\nRESTART_AFTER_GAME=yes\n",
                conf.read_text(),
            )

    def test_a_missing_or_empty_key_gets_its_default(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, conf = self.jouer(
                dossier, reglages="# note\nDECK_PROGRAM=\n"
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                "# note\nDECK_PROGRAM=tiler\nRESTART_AFTER_GAME=yes\n",
                conf.read_text(),
            )

    def test_a_second_identical_run_touches_nothing(self):
        with tempfile.TemporaryDirectory() as dossier:
            env = {"T_AUTOSTART": "1", "ENABLED": "1"}
            fait, _appels, unite, conf = self.jouer(dossier, env=env)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            avant = (unite.stat().st_mtime_ns, conf.stat().st_mtime_ns)
            Path(dossier, "appels").write_text("")
            fait, appels, unite, conf = self.jouer(dossier, env=env)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                avant, (unite.stat().st_mtime_ns, conf.stat().st_mtime_ns)
            )
            self.assertEqual(
                [f"systemctl --user is-enabled --quiet {UNITE}"], appels
            )
            self.assertIn("nothing to change", fait.stdout)

    def test_without_a_user_manager_the_summary_says_what_to_run(self):
        """Une installation par ssh sans session : l'unité est écrite, le
        script ne s'arrête pas, et le bilan nomme la commande d'après la
        connexion."""
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, unite, _conf = self.jouer(
                dossier, env={"T_AUTOSTART": "1", "ECHEC": "1"}
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertTrue(unite.exists())
            self.assertIn(
                "after the next login, run: systemctl --user enable " + UNITE,
                fait.stdout,
            )


class TestServiceRetire(unittest.TestCase):
    """uninstall_service, et les deux désinstallations qui l'appellent."""

    def preparer(self, dossier):
        config = Path(dossier, "config")
        unite = config / "systemd/user" / UNITE
        unite.parent.mkdir(parents=True)
        unite.write_text("[Unit]\n")
        voulu = config / "systemd/user/graphical-session.target.wants" / UNITE
        voulu.parent.mkdir()
        voulu.symlink_to(unite)
        conf = config / "erplibre-home/streamdeck.conf"
        conf.parent.mkdir()
        conf.write_text("DECK_PROGRAM=tiler\n")
        return config, unite, voulu, conf

    def test_stop_disable_remove_reload_then_settings(self):
        with tempfile.TemporaryDirectory() as dossier:
            config, unite, voulu, conf = self.preparer(dossier)
            journal = Path(dossier, "appels")
            journal.touch()
            fait = sourcer(
                'UNIT_FILE="$(deck_unit_file)"\n'
                'SETTINGS_FILE="$(deck_settings_file)"\n'
                + SYSTEMCTL_FAUX
                + "uninstall_service\n"
                'echo "--- second ---" >>"$JOURNAL"\n'
                "uninstall_service\n",
                {"XDG_CONFIG_HOME": str(config), "JOURNAL": str(journal)},
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            premier, second = journal.read_text().split("--- second ---\n")
            self.assertEqual(
                [
                    f"systemctl --user stop {UNITE}",
                    f"systemctl --user disable {UNITE}",
                    "systemctl --user daemon-reload",
                ],
                premier.splitlines(),
            )
            self.assertEqual("", second)
            for chemin in (unite, conf):
                self.assertFalse(chemin.exists(), chemin)
            self.assertFalse(os.path.lexists(voulu))

    def test_a_failing_systemctl_still_removes_the_files(self):
        with tempfile.TemporaryDirectory() as dossier:
            config, unite, voulu, conf = self.preparer(dossier)
            journal = Path(dossier, "appels")
            journal.touch()
            fait = sourcer(
                'UNIT_FILE="$(deck_unit_file)"\n'
                'SETTINGS_FILE="$(deck_settings_file)"\n'
                + SYSTEMCTL_FAUX
                + "uninstall_service\n",
                {
                    "XDG_CONFIG_HOME": str(config),
                    "JOURNAL": str(journal),
                    "ECHEC": "1",
                },
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("WARNING", fait.stdout)
            self.assertFalse(unite.exists())
            self.assertFalse(os.path.lexists(voulu))
            self.assertFalse(conf.exists())

    def test_both_uninstalls_remove_the_service(self):
        for niveau in ("1", "0"):
            with self.subTest(stream_deck=niveau):
                with tempfile.TemporaryDirectory() as dossier:
                    config, unite, _voulu, conf = self.preparer(dossier)
                    journal = Path(dossier, "appels")
                    journal.touch()
                    fait = sourcer(
                        'UNIT_FILE="$(deck_unit_file)"\n'
                        'SETTINGS_FILE="$(deck_settings_file)"\n'
                        'EXT_LINK="$DOSSIER/absent-link"\n'
                        'UDEV_RULE="$DOSSIER/absente.rules"\n'
                        'VENV="$DOSSIER/venv"\n'
                        "gsettings_bus() { echo '@as []'; }\n"
                        + SYSTEMCTL_FAUX
                        + 'STREAM_DECK="$NIVEAU"\nstep_uninstall\n',
                        {
                            "XDG_CONFIG_HOME": str(config),
                            "JOURNAL": str(journal),
                            "DOSSIER": dossier,
                            "NIVEAU": niveau,
                        },
                    )
                    self.assertEqual(fait.returncode, 0, fait.stderr)
                    self.assertFalse(unite.exists())
                    self.assertFalse(conf.exists())
                    self.assertIn(f"removed {unite}", fait.stdout)


OUTILS_EXTENSION = shutil.which("glib-compile-schemas") and shutil.which(
    "msgfmt"
)
```

Edit 11/12, replace:

```python
        self.home.mkdir()
        (self.depot / "script/install").mkdir(parents=True)
        shutil.copy2(INSTALLEUR, self.depot / "script/install")
        shutil.copytree(
            EXTENSION,
            self.depot / "script/gnome-extension/erplibre_home",
```

with:

```python
        self.home.mkdir()
        (self.depot / "script/install").mkdir(parents=True)
        shutil.copy2(INSTALLEUR, self.depot / "script/install")
        shutil.copy2(BIBLIOTHEQUE, self.depot / "script/install")
        shutil.copytree(
            EXTENSION,
            self.depot / "script/gnome-extension/erplibre_home",
```

Edit 12/12, replace:

```python

    def lancer(self, *options, env=None):
        environ = dict(os.environ)
        environ.update(
            {
                "HOME": str(self.home),
```

with:

```python

    def lancer(self, *options, env=None):
        environ = dict(os.environ)
        environ.pop("XDG_CONFIG_HOME", None)
        environ.update(
            {
                "HOME": str(self.home),
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_install_erplibre_home`
Expected: `Ran 101 tests`, `FAILED (failures=33)` — no `setting:` or `systemctl:` dry-run line, the four options are unknown, `unit_content`, `install_service`, `uninstall_service` and `check_checkout_path` are not defined.

- [ ] **Step 3: Implement the service in the installer**

In `script/install/install_erplibre_home.sh`:

Edit 1/16, replace:

```bash
# Installe ERPLibre Home sans Odoo, à deux niveaux. La base : l'extension
# GNOME liée au dépôt, ses schémas et ses traductions, puis activée ; ni
# accès au périphérique ni venv. --stream-deck ajoute le niveau Stream Deck
# par-dessus la base : paquets USB, règle udev, venv dédié .venv.streamdeck.
# Le niveau Stream Deck inclut toujours la base ; la base s'installe seule.
#
#   ./script/install/install_erplibre_home.sh [--stream-deck] [--no-enable]
#       [--extension-only] [--with-extras] [--uninstall] [--dry-run] [--help]
#
# Codes de sortie : 0 fait (installé ou désinstallé) ; 2 système non
# supporté, avec UNE ligne « UNSUPPORTED: <raison> » sur la sortie
```

with:

```bash
# Installe ERPLibre Home sans Odoo, à deux niveaux. La base : l'extension
# GNOME liée au dépôt, ses schémas et ses traductions, puis activée ; ni
# accès au périphérique ni venv. --stream-deck ajoute le niveau Stream Deck
# par-dessus la base : paquets USB, règle udev, venv dédié .venv.streamdeck,
# et le service systemd --user erplibre-home-streamdeck.service avec ses
# réglages. Le niveau Stream Deck inclut toujours la base ; la base
# s'installe seule.
#
#   ./script/install/install_erplibre_home.sh [--stream-deck] [--no-enable]
#       [--extension-only] [--with-extras] [--uninstall] [--dry-run] [--help]
#       [--deck-program=tiler|controller|none] [--autostart]
#       [--restart-after-game | --no-restart-after-game]
#
# Codes de sortie : 0 fait (installé ou désinstallé) ; 2 système non
# supporté, avec UNE ligne « UNSUPPORTED: <raison> » sur la sortie
```

Edit 2/16, replace:

```bash

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${RACINE}"

UUID="erplibre-home@technolibre.ca"
EXT_SRC="${RACINE}/script/gnome-extension/erplibre_home"
```

with:

```bash

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${RACINE}"
# shellcheck source=script/install/erplibre_home_settings.sh
. "${RACINE}/script/install/erplibre_home_settings.sh"

UUID="erplibre-home@technolibre.ca"
EXT_SRC="${RACINE}/script/gnome-extension/erplibre_home"
```

Edit 3/16, replace:

```bash
METADATA="${EXT_SRC}/metadata.json"
UDEV_RULE="/etc/udev/rules.d/70-streamdeck.rules"
VENV="${RACINE}/.venv.streamdeck"
OS_RELEASE="${ERPLIBRE_HOME_OS_RELEASE:-/etc/os-release}"

STREAM_DECK=0
```

with:

```bash
METADATA="${EXT_SRC}/metadata.json"
UDEV_RULE="/etc/udev/rules.d/70-streamdeck.rules"
VENV="${RACINE}/.venv.streamdeck"
UNIT_FILE="$(deck_unit_file)"
SETTINGS_FILE="$(deck_settings_file)"
OS_RELEASE="${ERPLIBRE_HOME_OS_RELEASE:-/etc/os-release}"

STREAM_DECK=0
```

Edit 4/16, replace:

```bash
WITH_EXTRAS=0
UNINSTALL=0
DRY_RUN=0

OS=""
OS_LIKE=""
```

with:

```bash
WITH_EXTRAS=0
UNINSTALL=0
DRY_RUN=0
# Les options du service, au niveau Stream Deck seulement. DECK_PROGRAM et
# RESTART_AFTER_GAME restent vides quand l'option manque : la valeur déjà
# dans les réglages est alors gardée (voir service_setting). SERVICE_OPTIONS
# compte les options données, pour refuser leur emploi ailleurs.
DECK_PROGRAM=""
AUTOSTART=0
RESTART_AFTER_GAME=""
SERVICE_OPTIONS=0

OS=""
OS_LIKE=""
```

Edit 5/16, replace:

```bash
  --with-extras     ajoute mpv, yt-dlp, nmap, keepassxc, xdotool et le
                    module Python lz4 du système ; un paquet absent est
                    signalé, jamais fatal
  --uninstall       retire tout : extension, règle udev, .venv.streamdeck ;
                    avec --stream-deck, la règle et le venv seulement, et
                    l'extension reste active ; les paquets système restent
  --dry-run         affiche ce qui serait fait, sans rien changer ni
                    appeler sudo
  -h, --help        cette aide
```

with:

```bash
  --with-extras     ajoute mpv, yt-dlp, nmap, keepassxc, xdotool et le
                    module Python lz4 du système ; un paquet absent est
                    signalé, jamais fatal
  --deck-program=tiler|controller|none
                    avec --stream-deck : le programme que lance le service
                    erplibre-home-streamdeck.service (défaut : tiler)
  --autostart       avec --stream-deck : active le service à l'ouverture de
                    session (défaut : non activé)
  --restart-after-game, --no-restart-after-game
                    avec --stream-deck : le service revient, ou non, après
                    un jeu (défaut : il revient)
                    Une option du service absente garde la valeur déjà
                    dans les réglages ; le défaut ne vaut que pour une clé
                    qui n'y est pas.
  --uninstall       retire tout : extension, règle udev, .venv.streamdeck,
                    service et réglages ; avec --stream-deck, tout sauf
                    l'extension, qui reste active ; les paquets système
                    restent
  --dry-run         affiche ce qui serait fait, sans rien changer ni
                    appeler sudo
  -h, --help        cette aide
```

Edit 6/16, replace:

```bash
            --with-extras) WITH_EXTRAS=1 ;;
            --uninstall) UNINSTALL=1 ;;
            --dry-run) DRY_RUN=1 ;;
            -h | --help)
                usage
                exit 0
```

with:

```bash
            --with-extras) WITH_EXTRAS=1 ;;
            --uninstall) UNINSTALL=1 ;;
            --dry-run) DRY_RUN=1 ;;
            --deck-program=*)
                DECK_PROGRAM="${1#*=}"
                deck_program_path "${DECK_PROGRAM}" >/dev/null \
                    || die "--deck-program=${DECK_PROGRAM} : tiler," \
                        "controller ou none"
                SERVICE_OPTIONS=$((SERVICE_OPTIONS + 1))
                ;;
            --autostart)
                AUTOSTART=1
                SERVICE_OPTIONS=$((SERVICE_OPTIONS + 1))
                ;;
            --restart-after-game | --no-restart-after-game)
                set_restart_after_game "$1"
                SERVICE_OPTIONS=$((SERVICE_OPTIONS + 1))
                ;;
            -h | --help)
                usage
                exit 0
```

Edit 7/16, replace:

```bash
            "--uninstall"
    fi
    if [ "${UNINSTALL}" = 1 ] \
        && [ $((NO_ENABLE + WITH_EXTRAS)) -gt 0 ]; then
        die "--uninstall ne se combine qu'avec --stream-deck et --dry-run"
    fi
}

check_not_root() {
```

with:

```bash
            "--uninstall"
    fi
    if [ "${UNINSTALL}" = 1 ] \
        && [ $((NO_ENABLE + WITH_EXTRAS + SERVICE_OPTIONS)) -gt 0 ]; then
        die "--uninstall ne se combine qu'avec --stream-deck et --dry-run"
    fi
    if [ "${SERVICE_OPTIONS}" -gt 0 ] && [ "${STREAM_DECK}" = 0 ]; then
        die "--deck-program, --autostart et --[no-]restart-after-game" \
            "demandent --stream-deck"
    fi
}

# --restart-after-game pose RESTART_AFTER_GAME=yes, --no-restart-after-game
# =no ; les deux ensemble se contredisent et sont une erreur d'usage.
set_restart_after_game() {
    local value=yes
    [ "$1" = --restart-after-game ] || value=no
    if [ -n "${RESTART_AFTER_GAME}" ] \
        && [ "${RESTART_AFTER_GAME}" != "${value}" ]; then
        die "--restart-after-game et --no-restart-after-game s'excluent"
    fi
    RESTART_AFTER_GAME="${value}"
}

check_not_root() {
```

Edit 8/16, replace:

```bash
        -r "${REQUIREMENTS}"
}

# ---------- Extension GNOME ----------

# Pose le lien vers le checkout, sauf s'il pointe déjà au bon endroit. Un
```

with:

```bash
        -r "${REQUIREMENTS}"
}

# ---------- Service du deck ----------

# Ce que le bilan demande de lancer après la prochaine connexion : les
# commandes systemctl --user qui n'ont pas pu passer faute de gestionnaire
# de l'utilisateur joignable (une installation par ssh sans session).
SERVICE_HINTS=()

# systemd refuse un chemin d'exécutable qui porte une apostrophe, un
# guillemet, une barre oblique inverse ou un caractère de contrôle, même
# cité : l'unité ne se chargerait pas. Le niveau Stream Deck s'arrête donc
# avant de rien installer, en nommant le chemin. Une espace et « % » passent.
check_checkout_path() {
    case "${RACINE}" in
        *\'* | *\"* | *\\*)
            die "${RACINE} : systemd refuse ' \" et \\ dans le chemin du" \
                "service ; déplacer le dépôt"
            ;;
    esac
    if [[ "${RACINE}" == *[[:cntrl:]]* ]]; then
        die "${RACINE} : caractère de contrôle refusé par systemd"
    fi
}

# Le texte de l'unité, pour le dépôt RACINE. Les chemins s'écrivent entiers :
# entre guillemets dans les lignes Exec*, où une espace séparerait sinon les
# arguments, et « % » doublé partout, sans quoi systemd le lit comme un
# spécificateur. RestartPreventExitStatus=2 : le programme sort en 2 quand
# un autre tient le verrou du deck, et le service ne doit pas alors boucler.
unit_content() {
    local dir entry
    dir="${RACINE//%/%%}"
    entry="\"${dir}/script/install/erplibre_home_deck.sh\""
    printf '%s\n' \
        "[Unit]" \
        "Description=ERPLibre Home Stream Deck program" \
        "PartOf=graphical-session.target" \
        "After=graphical-session.target" \
        "" \
        "[Service]" \
        "Type=simple" \
        "WorkingDirectory=${dir}" \
        "ExecCondition=${entry} --check" \
        "ExecStart=${entry}" \
        "Restart=on-failure" \
        "RestartSec=3" \
        "RestartPreventExitStatus=2" \
        "" \
        "[Install]" \
        "WantedBy=graphical-session.target"
}

# settings_content FICHIER CLÉ=valeur… rend les lignes de FICHIER (rien
# s'il manque), chaque ligne « CLÉ=… » d'une clé donnée remplacée sur place,
# puis les clés données qui n'y étaient pas. Les autres lignes restent
# telles quelles, dans leur ordre.
settings_content() {
    local file="$1" line pair seen=" "
    shift
    if [ -f "${file}" ]; then
        while IFS= read -r line || [ -n "${line}" ]; do
            for pair in "$@"; do
                case "${line}" in
                    "${pair%%=*}="*)
                        line="${pair}"
                        seen="${seen}${pair%%=*} "
                        ;;
                esac
            done
            printf '%s\n' "${line}"
        done <"${file}"
    fi
    for pair in "$@"; do
        case "${seen}" in
            *" ${pair%%=*} "*) ;;
            *) printf '%s\n' "${pair}" ;;
        esac
    done
}

# systemctl --user, sur le bus que choisit on_session_bus.
user_systemctl() {
    on_session_bus systemctl --user "$@"
}

# service_setting CLÉ DONNÉE DÉFAUT rend la valeur qu'une installation écrit
# pour CLÉ : DONNÉE quand l'option a été donnée (non vide), sinon la valeur
# déjà dans les réglages, sinon DÉFAUT quand le fichier ou la clé manque, ou
# que sa valeur est vide. Une option absente ne défait donc pas un choix
# antérieur, fait par une installation ou par le menu Stream Deck de TODO.
service_setting() {
    local key="$1" given="$2" default="$3" current
    if [ -n "${given}" ]; then
        echo "${given}"
        return 0
    fi
    current="$(deck_setting "${key}" "")"
    echo "${current:-${default}}"
}

# Les deux lignes « CLÉ=valeur » que l'installation pose, selon
# service_setting.
service_pairs() {
    local program restart
    program="$(service_setting DECK_PROGRAM "${DECK_PROGRAM}" tiler)"
    restart="$(service_setting RESTART_AFTER_GAME "${RESTART_AFTER_GAME}" yes)"
    printf '%s\n' "DECK_PROGRAM=${program}" "RESTART_AFTER_GAME=${restart}"
}

# Écrit les réglages par un fichier temporaire renommé, seulement quand le
# contenu change : une seconde exécution identique ne touche pas au
# fichier.
write_settings() {
    local tmp pairs
    mapfile -t pairs < <(service_pairs)
    mkdir -p "$(dirname "${SETTINGS_FILE}")"
    tmp="$(mktemp "${SETTINGS_FILE}.XXXXXX")"
    settings_content "${SETTINGS_FILE}" "${pairs[@]}" >"${tmp}"
    if cmp -s "${tmp}" "${SETTINGS_FILE}"; then
        rm -f "${tmp}"
        log "settings already in place: ${SETTINGS_FILE}"
        return 0
    fi
    mv "${tmp}" "${SETTINGS_FILE}"
    DONE+=("settings: ${SETTINGS_FILE}")
}

# Écrit l'unité seulement quand elle diffère ; vrai quand elle a été écrite.
write_unit() {
    mkdir -p "$(dirname "${UNIT_FILE}")"
    if cmp -s <(unit_content) "${UNIT_FILE}"; then
        log "unit already in place: ${UNIT_FILE}"
        return 1
    fi
    unit_content >"${UNIT_FILE}"
    DONE+=("unit: ${UNIT_FILE}")
}

# Les réglages, l'unité, daemon-reload quand l'unité a changé, et enable
# avec --autostart seulement. Jamais start : le programme demande
# l'extension chargée, ce qu'une installation neuve n'a qu'à la prochaine
# connexion. Un systemctl qui échoue n'arrête rien : daemon-reload est
# alors fait par la prochaine connexion, enable va au bilan.
install_service() {
    write_settings
    if write_unit; then
        if user_systemctl daemon-reload; then
            DONE+=("systemctl --user daemon-reload")
        else
            log "WARNING: systemctl --user daemon-reload failed; the next" \
                "login reads the unit"
        fi
    fi
    [ "${AUTOSTART}" = 1 ] || return 0
    if user_systemctl is-enabled --quiet "${DECK_UNIT_NAME}" 2>/dev/null; then
        log "unit already enabled: ${DECK_UNIT_NAME}"
    elif user_systemctl enable "${DECK_UNIT_NAME}"; then
        DONE+=("systemctl --user enable ${DECK_UNIT_NAME}")
    else
        SERVICE_HINTS+=("systemctl --user enable ${DECK_UNIT_NAME}")
    fi
}

# Arrête, désactive et retire l'unité, recharge systemd, puis retire les
# réglages. Le lien de graphical-session.target.wants part aussi quand
# disable n'a pas pu le retirer. Ce qui manque est sauté : une seconde
# exécution n'appelle pas systemctl. Un systemctl qui échoue n'arrête rien.
uninstall_service() {
    local wants
    wants="$(dirname "${UNIT_FILE}")/graphical-session.target.wants"
    wants="${wants}/${DECK_UNIT_NAME}"
    if [ -e "${UNIT_FILE}" ]; then
        user_systemctl stop "${DECK_UNIT_NAME}" \
            || log "WARNING: systemctl --user stop ${DECK_UNIT_NAME} failed"
        user_systemctl disable "${DECK_UNIT_NAME}" \
            || log "WARNING: systemctl --user disable ${DECK_UNIT_NAME} failed"
        rm -f "${UNIT_FILE}"
        DONE+=("removed ${UNIT_FILE}")
        user_systemctl daemon-reload \
            || log "WARNING: systemctl --user daemon-reload failed"
    fi
    if [ -L "${wants}" ]; then
        rm -f "${wants}"
        DONE+=("removed ${wants}")
    fi
    if [ -e "${SETTINGS_FILE}" ]; then
        rm -f "${SETTINGS_FILE}"
        DONE+=("removed ${SETTINGS_FILE}")
    fi
}

# ---------- Extension GNOME ----------

# Pose le lien vers le checkout, sauf s'il pointe déjà au bon endroit. Un
```

Edit 9/16, replace:

```bash

# ---------- Désinstallation ----------

# Retire le niveau Stream Deck : la règle udev, puis la relecture des règles,
# et le venv. Ce qui manque déjà est sauté, si bien qu'une seconde
# exécution n'appelle ni sudo ni udevadm.
uninstall_streamdeck() {
    if [ -e "${UDEV_RULE}" ]; then
        sudo rm -f "${UDEV_RULE}"
        sudo udevadm control --reload-rules
```

with:

```bash

# ---------- Désinstallation ----------

# Retire le niveau Stream Deck : le service et ses réglages d'abord, pour que
# le programme ne tourne plus quand son venv part, puis la règle udev, la
# relecture des règles, et le venv. Ce qui manque déjà est sauté, si bien
# qu'une seconde exécution n'appelle ni sudo, ni udevadm, ni systemctl.
uninstall_streamdeck() {
    uninstall_service
    if [ -e "${UDEV_RULE}" ]; then
        sudo rm -f "${UDEV_RULE}"
        sudo udevadm control --reload-rules
```

Edit 10/16, replace:

```bash
UNINSTALL_ERROR=""

# Défait tout ce que l'installation pose : l'UUID d'enabled-extensions, le
# lien, puis le niveau Stream Deck. Jamais de paquet système : d'autres
# logiciels peuvent s'en servir. Un répertoire ordinaire à la place du lien
# n'a pas été posé par ce script et reste en place. Une liste
# enabled-extensions qui ne se lit ou ne s'écrit pas (gsettings absent, bus
# en panne) n'arrête pas le reste, mais pose UNINSTALL_ERROR : l'UUID peut
# y rester, et la désinstallation n'est pas complète.
uninstall() {
    local current wanted
    if current="$(gsettings_bus get org.gnome.shell enabled-extensions 2>/dev/null)" \
```

with:

```bash
UNINSTALL_ERROR=""

# Défait tout ce que l'installation pose : l'UUID d'enabled-extensions, le
# lien, puis le niveau Stream Deck, service compris. Jamais de paquet
# système : d'autres logiciels peuvent s'en servir. Un répertoire ordinaire
# à la place du lien n'a pas été posé par ce script et reste en place. Une
# liste enabled-extensions qui ne se lit ou ne s'écrit pas (gsettings
# absent, bus en panne) n'arrête pas le reste, mais pose UNINSTALL_ERROR :
# l'UUID peut y rester, et la désinstallation n'est pas complète.
uninstall() {
    local current wanted
    if current="$(gsettings_bus get org.gnome.shell enabled-extensions 2>/dev/null)" \
```

Edit 11/16, replace:

```bash
            log "${line}"
        done
    fi
    if [ "${UNINSTALL}" = 0 ]; then
        log "log out and back in: GNOME Shell loads a new extension only at session start under Wayland"
    fi
```

with:

```bash
            log "${line}"
        done
    fi
    for line in "${SERVICE_HINTS[@]}"; do
        log "after the next login, run: ${line}"
    done
    if [ "${UNINSTALL}" = 0 ]; then
        log "log out and back in: GNOME Shell loads a new extension only at session start under Wayland"
    fi
```

Edit 12/16, replace:

```bash
    make_venv
}

step_extension() {
    local lang
    if [ "${DRY_RUN}" = 1 ]; then
```

with:

```bash
    make_venv
}

step_service() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "write: ${UNIT_FILE}"
        echo "write: ${SETTINGS_FILE}"
        service_pairs | sed 's/^/setting: /'
        echo "systemctl: --user daemon-reload"
        if [ "${AUTOSTART}" = 1 ]; then
            echo "systemctl: --user enable ${DECK_UNIT_NAME}"
        fi
        return 0
    fi
    install_service
}

step_extension() {
    local lang
    if [ "${DRY_RUN}" = 1 ]; then
```

Edit 13/16, replace:

```bash
}

# --uninstall retire tout ; --uninstall --stream-deck ne retire que le
# niveau Stream Deck, la règle et le venv, et laisse l'extension active.
# Le bilan dit ce qui est parti ; UNINSTALL_ERROR, posé par uninstall, fait
# ensuite sortir en 1.
step_uninstall() {
```

with:

```bash
}

# --uninstall retire tout ; --uninstall --stream-deck ne retire que le
# niveau Stream Deck, le service, la règle et le venv, et laisse
# l'extension active.
# Le bilan dit ce qui est parti ; UNINSTALL_ERROR, posé par uninstall, fait
# ensuite sortir en 1.
step_uninstall() {
```

Edit 14/16, replace:

```bash
            echo "gsettings: org.gnome.shell enabled-extensions -${UUID}"
            echo "remove: ${EXT_LINK}"
        fi
        echo "remove: ${UDEV_RULE}"
        echo "remove: ${VENV}"
        return 0
```

with:

```bash
            echo "gsettings: org.gnome.shell enabled-extensions -${UUID}"
            echo "remove: ${EXT_LINK}"
        fi
        echo "systemctl: --user stop ${DECK_UNIT_NAME}"
        echo "systemctl: --user disable ${DECK_UNIT_NAME}"
        echo "remove: ${UNIT_FILE}"
        echo "systemctl: --user daemon-reload"
        echo "remove: ${SETTINGS_FILE}"
        echo "remove: ${UDEV_RULE}"
        echo "remove: ${VENV}"
        return 0
```

Edit 15/16, replace:

```bash
# --uninstall et --extension-only ne lisent ni os-release ni la version de
# GNOME : ni l'un ni l'autre n'installe de paquet, et une désinstallation
# doit marcher sur un GNOME sorti de shell-version. La base passe toujours ;
# la règle udev et le venv n'arrivent qu'avec --stream-deck.
main() {
    parse_args "$@"
    check_not_root
    if [ "${UNINSTALL}" = 1 ]; then
        step_uninstall
        return 0
```

with:

```bash
# --uninstall et --extension-only ne lisent ni os-release ni la version de
# GNOME : ni l'un ni l'autre n'installe de paquet, et une désinstallation
# doit marcher sur un GNOME sorti de shell-version. La base passe toujours ;
# la règle udev, le venv et le service n'arrivent qu'avec --stream-deck, dont
# le chemin du dépôt se vérifie avant tout le reste.
main() {
    parse_args "$@"
    check_not_root
    if [ "${STREAM_DECK}" = 1 ] && [ "${UNINSTALL}" = 0 ]; then
        check_checkout_path
    fi
    if [ "${UNINSTALL}" = 1 ]; then
        step_uninstall
        return 0
```

Edit 16/16, replace:

```bash
        if [ "${STREAM_DECK}" = 1 ]; then
            step_udev
            step_venv
        fi
    fi
    step_extension
```

with:

```bash
        if [ "${STREAM_DECK}" = 1 ]; then
            step_udev
            step_venv
            step_service
        fi
    fi
    step_extension
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv.erplibre/bin/python -m unittest test.test_install_erplibre_home test.test_qemu_erplibre_home test.test_erplibre_home_enable_target test.test_todo_erplibre_home_install`
Expected: all `OK`; `test_install_erplibre_home` alone reports `Ran 101 tests`. Where `systemd-analyze` is absent, one test is reported skipped.

- [ ] **Step 5: Check a dry run by hand, under a throwaway HOME**

Run: `T=$(mktemp -d); env -u XDG_CONFIG_HOME HOME="$T" ERPLIBRE_HOME_GNOME_VERSION=48.1 ERPLIBRE_HOME_UID=1000 ./script/install/install_erplibre_home.sh --dry-run --stream-deck --autostart | grep -E '^(setting|systemctl):|streamdeck'; rm -rf "$T"`
Expected, among the lines:
```
write: <T>/.config/systemd/user/erplibre-home-streamdeck.service
write: <T>/.config/erplibre-home/streamdeck.conf
setting: DECK_PROGRAM=tiler
setting: RESTART_AFTER_GAME=yes
systemctl: --user daemon-reload
systemctl: --user enable erplibre-home-streamdeck.service
```

- [ ] **Step 6: Document the service**

In `script/stream_deck/INSTALL.base.md`:

Edit 1/3, replace:

```markdown
| `--no-enable` | install without enabling the extension; a workstation where the former extension was enabled keeps that state under the new name |
| `--extension-only` | migrate from the former extension, link the extension and compile its schemas and translations only; no `sudo`, no system check; not with `--stream-deck` nor `--uninstall` |
| `--with-extras` | also install `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` and the Python `lz4` module, at either level, one package manager command each; a missing one is skipped with a warning |
| `--uninstall` | remove everything: disable the extension, remove its link, the udev rule and `.venv.streamdeck`; with `--stream-deck`, only the udev rule and `.venv.streamdeck`, and the extension stays enabled; system packages always stay |
| `--dry-run` | print what would be done, change nothing |

Exit code `0` means done, `2` an unsupported system (one line on stderr
```

with:

```markdown
| `--no-enable` | install without enabling the extension; a workstation where the former extension was enabled keeps that state under the new name |
| `--extension-only` | migrate from the former extension, link the extension and compile its schemas and translations only; no `sudo`, no system check; not with `--stream-deck` nor `--uninstall` |
| `--with-extras` | also install `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` and the Python `lz4` module, at either level, one package manager command each; a missing one is skipped with a warning |
| `--deck-program=tiler\|controller\|none` | with `--stream-deck`: the program the deck service runs (default `tiler`) |
| `--autostart` | with `--stream-deck`: enable the deck service at login (default: not enabled) |
| `--restart-after-game`, `--no-restart-after-game` | with `--stream-deck`: the deck service comes back after a game, or not (default: it does); the two exclude each other |
| `--uninstall` | remove everything: disable the extension, remove its link, the deck service and its settings, the udev rule and `.venv.streamdeck`; with `--stream-deck`, everything but the extension, which stays enabled; system packages always stay |
| `--dry-run` | print what would be done, change nothing |

Exit code `0` means done, `2` an unsupported system (one line on stderr
```

Edit 2/3, replace:

```markdown
| `--no-enable` | installe sans activer l'extension ; un poste où l'ancienne extension était active garde cet état sous le nouveau nom |
| `--extension-only` | migre depuis l'ancienne extension, lie l'extension et compile ses schémas et ses traductions, rien d'autre ; ni `sudo` ni vérification du système ; ni avec `--stream-deck` ni avec `--uninstall` |
| `--with-extras` | installe aussi `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` et le module Python `lz4`, à l'un ou l'autre niveau, une commande du gestionnaire de paquets chacun ; un paquet absent est sauté avec un avertissement |
| `--uninstall` | retire tout : désactive l'extension, retire son lien, la règle udev et `.venv.streamdeck` ; avec `--stream-deck`, seulement la règle udev et `.venv.streamdeck`, et l'extension reste active ; les paquets système restent toujours |
| `--dry-run` | affiche ce qui serait fait, ne change rien |

Le code de sortie `0` veut dire fait, `2` un système non supporté (une
```

with:

```markdown
| `--no-enable` | installe sans activer l'extension ; un poste où l'ancienne extension était active garde cet état sous le nouveau nom |
| `--extension-only` | migre depuis l'ancienne extension, lie l'extension et compile ses schémas et ses traductions, rien d'autre ; ni `sudo` ni vérification du système ; ni avec `--stream-deck` ni avec `--uninstall` |
| `--with-extras` | installe aussi `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` et le module Python `lz4`, à l'un ou l'autre niveau, une commande du gestionnaire de paquets chacun ; un paquet absent est sauté avec un avertissement |
| `--deck-program=tiler\|controller\|none` | avec `--stream-deck` : le programme que lance le service du deck (défaut `tiler`) |
| `--autostart` | avec `--stream-deck` : active le service du deck à l'ouverture de session (défaut : non activé) |
| `--restart-after-game`, `--no-restart-after-game` | avec `--stream-deck` : le service du deck revient après un jeu, ou non (défaut : il revient) ; les deux s'excluent |
| `--uninstall` | retire tout : désactive l'extension, retire son lien, le service du deck et ses réglages, la règle udev et `.venv.streamdeck` ; avec `--stream-deck`, tout sauf l'extension, qui reste active ; les paquets système restent toujours |
| `--dry-run` | affiche ce qui serait fait, ne change rien |

Le code de sortie `0` veut dire fait, `2` un système non supporté (une
```

Edit 3/3, replace:

````markdown
<!-- [common] -->
```
sudo udevadm monitor
```

<!-- [end] -->
````

with:

````markdown
<!-- [common] -->
```
sudo udevadm monitor
```

<!-- [end] -->
<!-- [en] -->
### The deck service

A Stream Deck is driven by one program at a time. With `--stream-deck`, the
installer writes the `systemd --user` unit
`~/.config/systemd/user/erplibre-home-streamdeck.service`, which runs that
program from this checkout, and its settings
`~/.config/erplibre-home/streamdeck.conf` (`$XDG_CONFIG_HOME` honoured):

<!-- [fr] -->
### Le service du deck

Un Stream Deck est piloté par un seul programme à la fois. Avec
`--stream-deck`, l'installateur écrit l'unité `systemd --user`
`~/.config/systemd/user/erplibre-home-streamdeck.service`, qui lance ce
programme depuis ce dépôt, et ses réglages
`~/.config/erplibre-home/streamdeck.conf` (`$XDG_CONFIG_HOME` respecté) :

<!-- [end] -->
<!-- [common] -->
```
DECK_PROGRAM=tiler
RESTART_AFTER_GAME=yes
```

<!-- [end] -->
<!-- [en] -->
`DECK_PROGRAM` is `tiler` (`script/stream_deck/game_tiler.py`),
`controller` (`script/stream_deck/erplibre_controller.py`) or `none`. An
option given writes its key; an option left out keeps the value already in
the file, and the default applies only to a missing key, so a reinstall
keeps a program chosen in TODO. Any other line stays. The unit starts only
when a program is chosen, `.venv.streamdeck` exists and a deck is plugged
in; otherwise systemd skips it. The installer never starts
it: the program needs the extension, which a fresh install loads at the
next login. With `--autostart` the unit is enabled and starts at login.
Without a reachable user manager (an install over ssh with no session), the
summary names the command to run after the next login.

Games take the deck over: TODO's games menu and the gallery run each game
through `script/install/erplibre_home_handover.sh`, which stops the service,
runs the game, and starts the service again when the game ends, unless
`RESTART_AFTER_GAME=no`. Each deck program takes a lock,
`$XDG_RUNTIME_DIR/erplibre-home/deck.lock`; a second one exits with code 2
and names the program and PID that hold the deck. `systemctl --user`
controls the service:

<!-- [fr] -->
`DECK_PROGRAM` vaut `tiler` (`script/stream_deck/game_tiler.py`),
`controller` (`script/stream_deck/erplibre_controller.py`) ou `none`. Une
option donnée écrit sa clé ; une option absente garde la valeur déjà dans
le fichier, et le défaut ne vaut que pour une clé absente : une
réinstallation garde un programme choisi dans TODO. Toute autre ligne
reste. L'unité ne démarre que si un programme est choisi, que
`.venv.streamdeck` existe et qu'un deck est branché ; sinon systemd la saute.
L'installateur ne la démarre jamais : le programme a besoin de l'extension,
qu'une installation neuve charge à la prochaine ouverture de session. Avec
`--autostart`, l'unité est activée et démarre à l'ouverture de session. Sans
gestionnaire utilisateur joignable (une installation par ssh sans session),
le bilan nomme la commande à lancer après la prochaine connexion.

Les jeux prennent le deck : le menu des jeux de TODO et la galerie lancent
chaque jeu par `script/install/erplibre_home_handover.sh`, qui arrête le
service, lance le jeu, puis relance le service à la fin du jeu, sauf si
`RESTART_AFTER_GAME=no`. Chaque programme du deck prend un verrou,
`$XDG_RUNTIME_DIR/erplibre-home/deck.lock` ; un second sort avec le code 2
et nomme le programme et le PID qui tiennent le deck. `systemctl --user`
pilote le service :

<!-- [end] -->
<!-- [common] -->
```
systemctl --user status erplibre-home-streamdeck.service
systemctl --user enable erplibre-home-streamdeck.service
journalctl --user -u erplibre-home-streamdeck.service -f
```

<!-- [end] -->
````

Run: `source .venv.erplibre/bin/activate && mmg --yes script/stream_deck/INSTALL.base.md`
Expected: `1 base file has been converted.`; `git status --short` shows `INSTALL.base.md`, `INSTALL.md` and `INSTALL.fr.md` modified.

- [ ] **Step 7: Format and comment hygiene**

Run: `.venv.erplibre/bin/black -l 79 --check test/test_install_erplibre_home.py && python3 script/analyse/check_comment_hygiene.py script/install/install_erplibre_home.sh test/test_install_erplibre_home.py && bash -n script/install/install_erplibre_home.sh`
Expected: `1 file would be left unchanged.`, no hygiene line, `bash -n` silent.

- [ ] **Step 8: Commit**

Write `"$SCRATCH/msg-4.txt"`:

```text
[ADD] install_erplibre_home: deck service unit, settings and options

The Stream Deck level now writes erplibre-home-streamdeck.service and
its settings: --deck-program, --autostart (the only way it gets
enabled) and --[no-]restart-after-game, a usage error without
--stream-deck. An option left out keeps the value already set. It
never starts the unit; without a user manager the summary names the
enable command. Both uninstalls stop, disable and remove it. Paths are
quoted and % doubled, checked by systemd-analyze verify; a checkout
path systemd refuses stops the install first.

--- FR ---
[ADD] install_erplibre_home : unité, réglages et options du service

Le niveau Stream Deck écrit désormais erplibre-home-streamdeck.service
et ses réglages : --deck-program, --autostart (seul moyen de l'activer)
et --[no-]restart-after-game, erreur d'usage sans --stream-deck. Une
option absente garde la valeur en place. L'unité n'est jamais démarrée ;
sans gestionnaire utilisateur, le bilan nomme la commande enable. Les
deux désinstallations l'arrêtent, la désactivent et la retirent. Chemins
cités et % doublés, vérifiés par systemd-analyze verify ; un chemin que
systemd refuse arrête l'installation d'abord.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-4.txt"
git add script/install/install_erplibre_home.sh test/test_install_erplibre_home.py script/stream_deck/INSTALL.base.md script/stream_deck/INSTALL.md script/stream_deck/INSTALL.fr.md
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-4.txt"
```

---

### Task 5: Status and diagnosis from recorded probes

**Files:**
- Create: `script/todo/erplibre_home_service.py`
- Create: `script/todo/erplibre_home_status.py`
- Modify: `script/todo/todo_i18n.py` (insert before `    # Stream Deck game descriptions (42 games)`)
- Test: `test/test_erplibre_home_service.py`, `test/test_erplibre_home_status.py`

**Interfaces:**
- Consumes: Task 2's `deck_lock.py` (`lock_path(environ)`, `holder(path)`), loaded by path from `<root>/script/stream_deck/deck_lock.py`; Task 4's `settings_content` (the parity test sources the installer).
- Produces (`script.todo.erplibre_home_service`):
  - `UNIT_NAME = "erplibre-home-streamdeck.service"`, `PROGRAMS = ("tiler", "controller", "none")`, `DEFAULTS = {"DECK_PROGRAM": "tiler", "RESTART_AFTER_GAME": "yes"}`
  - `config_home(environ=None) -> str`, `settings_path(environ=None) -> str`, `unit_path(environ=None) -> str`
  - `read_settings(path) -> dict` (defaults merged), `settings_text(current: str, updates: dict) -> str`, `write_settings(path, updates: dict) -> bool` (True when written)
  - `run_command(argv, timeout=20) -> tuple[int | None, str]` — `(None, "")` for a missing command or a timeout
- Produces (`script.todo.erplibre_home_status`):
  - `CMD_EXTENSION_INFO`, `CMD_JOURNAL` (tuples), `JOURNAL_GREP` (str), `cmd_unit(verb) -> tuple`
  - `parse_extension_info(text) -> {"state": float | None, "error": str}`, `parse_journal(text) -> {"read": bool, "failed": list[str]}`, `plugged_decks(sysfs="/sys") -> list[{"product": str, "id_product": str}]`
  - `collect(run, root, environ=None, sysfs="/sys", udev_rule=UDEV_RULE, lock_path=None) -> dict` with keys `extension_linked`, `venv`, `udev_rule`, `extension`, `journal`, `unit_file`, `unit_enabled`, `unit_active`, `settings`, `lock`, `decks`; `run(argv) -> (code, stdout)`
  - `status_lines(facts) -> list[str]` (8 lines), `diagnosis_lines(facts) -> list[tuple[str, str]]` (problem, fix)

- [ ] **Step 1: Write the failing tests**

Create `test/test_erplibre_home_service.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les réglages du service Stream Deck, vus de TODO.

TODO lit et réécrit le même fichier que l'installateur, le point d'entrée
du service et l'outil de passation : ces tests gardent les mêmes règles des
deux côtés, et comparent l'écriture de Python à celle de l'installateur sur
les mêmes entrées.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import erplibre_home_service as service  # noqa: E402

INSTALLEUR = RACINE / "script/install/install_erplibre_home.sh"


class LesChemins(unittest.TestCase):
    def test_under_dot_config_by_default(self):
        env = {"HOME": "/exemple/maison"}
        self.assertEqual(
            "/exemple/maison/.config/erplibre-home/streamdeck.conf",
            service.settings_path(env),
        )
        self.assertEqual(
            "/exemple/maison/.config/systemd/user/"
            "erplibre-home-streamdeck.service",
            service.unit_path(env),
        )

    def test_xdg_config_home_wins_and_empty_means_unset(self):
        env = {"HOME": "/exemple/maison", "XDG_CONFIG_HOME": "/exemple/cfg"}
        self.assertEqual(
            "/exemple/cfg/erplibre-home/streamdeck.conf",
            service.settings_path(env),
        )
        env["XDG_CONFIG_HOME"] = ""
        self.assertTrue(
            service.settings_path(env).startswith("/exemple/maison/.config/")
        )


class LaLecture(unittest.TestCase):
    def test_a_missing_file_gives_the_defaults(self):
        self.assertEqual(
            {"DECK_PROGRAM": "tiler", "RESTART_AFTER_GAME": "yes"},
            service.read_settings("/exemple/absent.conf"),
        )

    def test_the_last_line_wins_and_comments_are_skipped(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier, "streamdeck.conf")
            chemin.write_text(
                "# DECK_PROGRAM=none\nDECK_PROGRAM=tiler\n"
                "sans egal\nDECK_PROGRAM=controller\n",
                encoding="utf-8",
            )
            reglages = service.read_settings(str(chemin))
        self.assertEqual("controller", reglages["DECK_PROGRAM"])
        self.assertEqual("yes", reglages["RESTART_AFTER_GAME"])


class LEcriture(unittest.TestCase):
    def test_a_key_is_replaced_in_place_and_others_stay(self):
        self.assertEqual(
            "# note\nDECK_PROGRAM=none\nEXEMPLE=1\nRESTART_AFTER_GAME=no\n",
            service.settings_text(
                "# note\nDECK_PROGRAM=tiler\nEXEMPLE=1\n",
                {"DECK_PROGRAM": "none", "RESTART_AFTER_GAME": "no"},
            ),
        )

    def test_write_creates_then_leaves_an_unchanged_file_alone(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = Path(dossier, "erplibre-home", "streamdeck.conf")
            self.assertTrue(
                service.write_settings(str(chemin), {"DECK_PROGRAM": "none"})
            )
            self.assertEqual("DECK_PROGRAM=none\n", chemin.read_text())
            avant = chemin.stat().st_mtime_ns
            self.assertFalse(
                service.write_settings(str(chemin), {"DECK_PROGRAM": "none"})
            )
            self.assertEqual(avant, chemin.stat().st_mtime_ns)

    def test_python_and_the_installer_write_the_same_text(self):
        """settings_text et settings_content de l'installateur, sur les
        mêmes entrées, rendent le même texte."""
        entrees = (
            "",
            "DECK_PROGRAM=none\n",
            "# note\nEXEMPLE=1\nRESTART_AFTER_GAME=yes\nDECK_PROGRAM=tiler",
        )
        maj = {"DECK_PROGRAM": "controller", "RESTART_AFTER_GAME": "no"}
        for entree in entrees:
            with self.subTest(entree=entree):
                with tempfile.TemporaryDirectory() as dossier:
                    chemin = Path(dossier, "streamdeck.conf")
                    if entree:
                        chemin.write_text(entree, encoding="utf-8")
                    env = {
                        k: v
                        for k, v in os.environ.items()
                        if k != "XDG_CONFIG_HOME"
                    }
                    env.update(
                        {
                            "HOME": dossier,
                            "INSTALLEUR": str(INSTALLEUR),
                            "FICHIER": str(chemin),
                        }
                    )
                    fini = subprocess.run(
                        [
                            "bash",
                            "-c",
                            'ERPLIBRE_HOME_SOURCE_ONLY=1 . "$INSTALLEUR"\n'
                            'settings_content "$FICHIER"'
                            " DECK_PROGRAM=controller RESTART_AFTER_GAME=no\n",
                        ],
                        capture_output=True,
                        text=True,
                        env=env,
                        timeout=30,
                    )
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(
                    service.settings_text(entree, maj), fini.stdout
                )


class LaCommande(unittest.TestCase):
    def test_code_and_stdout(self):
        self.assertEqual(
            (3, "sortie\n"),
            service.run_command(["sh", "-c", "echo sortie; exit 3"]),
        )

    def test_a_missing_command_gives_none(self):
        self.assertEqual(
            (None, ""), service.run_command(["/exemple/commande-absente"])
        )

    def test_a_timeout_gives_none(self):
        self.assertEqual(
            (None, ""), service.run_command(["sleep", "5"], timeout=0.2)
        )


if __name__ == "__main__":
    unittest.main()
```

Create `test/test_erplibre_home_status.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'état et le diagnostic d'ERPLibre Home, sur des sorties enregistrées.

collect() tourne sur un poste simulé : un HOME, un dépôt, un sysfs et un
verrou jetables, et une fonction `run` qui rend la sortie enregistrée de
chaque commande et note celles qu'on lui demande. status_lines() et
diagnosis_lines() se jouent sur des faits écrits à la main.

Ce que ces tests gardent :

- chaque sonde de la spec a sa ligne d'état ;
- chaque sonde qui n'est pas comme attendu a sa correction, et une
  installation saine n'en a aucune ;
- sans unité installée, systemctl n'est pas appelé ;
- chaque libellé a ses deux langues.
"""

import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import erplibre_home_status as statut  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

UNITE = "erplibre-home-streamdeck.service"
INFO_ACTIVE = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'name': <'ERPLibre Home'>,"
    " 'state': <1.0>, 'error': <''>},)"
)
INFO_ERREUR = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'state': <3.0>,"
    " 'error': <\"TypeError: can't read exemple\">},)"
)
INFO_INCONNUE = "(@a{sv} {},)"
JOURNAL_SAIN = "autre ligne\n[ERPLibreHome] enabled\n"
JOURNAL_ECHEC = (
    "[ERPLibreHome] mount device failed: exemple\n"
    "[ERPLibreHome] mount pencil failed: exemple\n"
    "[ERPLibreHome] mount device failed: exemple\n"
    "[ERPLibreHome] enabled\n"
)


def faits(**changes):
    """Les faits d'un poste sain au niveau Stream Deck, modifiés par
    `changes`."""
    base = {
        "extension_linked": True,
        "venv": True,
        "udev_rule": True,
        "extension": {"state": 1.0, "error": ""},
        "journal": {"read": True, "failed": []},
        "unit_file": True,
        "unit_enabled": "enabled",
        "unit_active": "active",
        "settings": {"DECK_PROGRAM": "tiler", "RESTART_AFTER_GAME": "yes"},
        "lock": ("4242", "tiler"),
        "decks": [{"product": "Stream Deck MK.2", "id_product": "0080"}],
    }
    base.update(changes)
    return base


class LesLectures(unittest.TestCase):
    def test_extension_info(self):
        self.assertEqual(
            {"state": 1.0, "error": ""},
            statut.parse_extension_info(INFO_ACTIVE),
        )
        self.assertEqual(
            {"state": 3.0, "error": "TypeError: can't read exemple"},
            statut.parse_extension_info(INFO_ERREUR),
        )
        for sortie in (INFO_INCONNUE, "", None):
            with self.subTest(sortie=sortie):
                self.assertIsNone(statut.parse_extension_info(sortie)["state"])

    def test_journal(self):
        self.assertEqual(
            {"read": True, "failed": []}, statut.parse_journal(JOURNAL_SAIN)
        )
        self.assertEqual(
            {"read": True, "failed": ["device", "pencil"]},
            statut.parse_journal(JOURNAL_ECHEC),
        )
        self.assertEqual(
            {"read": False, "failed": []}, statut.parse_journal("")
        )

    def test_plugged_decks_read_sysfs(self):
        with tempfile.TemporaryDirectory() as sysfs:
            appareils = {
                "1-1": {"idVendor": "1d6b", "idProduct": "0002"},
                "3-2": {
                    "idVendor": "0fd9",
                    "idProduct": "0080",
                    "product": "Stream Deck MK.2",
                },
                "3-4": {"idVendor": "0fd9", "idProduct": "006c"},
            }
            for nom, fichiers in appareils.items():
                dossier = Path(sysfs, "bus/usb/devices", nom)
                dossier.mkdir(parents=True)
                for fichier, valeur in fichiers.items():
                    (dossier / fichier).write_text(valeur + "\n")
            self.assertEqual(
                [
                    {"product": "Stream Deck MK.2", "id_product": "0080"},
                    {"product": "", "id_product": "006c"},
                ],
                statut.plugged_decks(sysfs),
            )


class LaCollecte(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.appels = []

    def run_enregistre(self, sorties):
        def run(argv):
            self.appels.append(tuple(argv))
            return sorties.get(tuple(argv), (1, ""))

        return run

    def collecter(self, sorties, unite=False):
        if unite:
            fichier = self.home / ".config/systemd/user" / UNITE
            fichier.parent.mkdir(parents=True)
            fichier.write_text("[Unit]\n")
        return statut.collect(
            self.run_enregistre(sorties),
            str(RACINE),
            environ={"HOME": str(self.home)},
            sysfs=str(self.tmp / "sys"),
            udev_rule=str(self.tmp / "absente.rules"),
            lock_path=str(self.tmp / "deck.lock"),
        )

    def test_a_bare_workstation(self):
        recu = self.collecter({})
        self.assertEqual(
            {
                "extension_linked": False,
                "venv": os.access(
                    RACINE / ".venv.streamdeck/bin/python", os.X_OK
                ),
                "udev_rule": False,
                "extension": {"state": None, "error": ""},
                "journal": {"read": False, "failed": []},
                "unit_file": False,
                "unit_enabled": "",
                "unit_active": "",
                "settings": {
                    "DECK_PROGRAM": "tiler",
                    "RESTART_AFTER_GAME": "yes",
                },
                "lock": None,
                "decks": [],
            },
            recu,
        )
        self.assertNotIn("systemctl", [a[0] for a in self.appels])

    def test_recorded_outputs_reach_the_facts(self):
        lien = self.home / ".local/share/gnome-shell/extensions"
        lien.mkdir(parents=True)
        (lien / "erplibre-home@technolibre.ca").symlink_to(self.tmp)
        sorties = {
            statut.CMD_EXTENSION_INFO: (0, INFO_ACTIVE),
            statut.CMD_JOURNAL: (0, JOURNAL_ECHEC),
            ("systemctl", "--user", "is-enabled", UNITE): (1, "disabled\n"),
            ("systemctl", "--user", "is-active", UNITE): (3, "inactive\n"),
        }
        recu = self.collecter(sorties, unite=True)
        self.assertTrue(recu["extension_linked"])
        self.assertEqual({"state": 1.0, "error": ""}, recu["extension"])
        self.assertEqual(["device", "pencil"], recu["journal"]["failed"])
        self.assertTrue(recu["unit_file"])
        self.assertEqual("disabled", recu["unit_enabled"])
        self.assertEqual("inactive", recu["unit_active"])


class LEtat(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def test_a_sound_stream_deck_workstation(self):
        self.assertEqual(
            [
                "Level: Stream Deck",
                "Extension: active",
                "Indicators: all mounted",
                "Service: enabled, active, program tiler",
                "Deck lock: held by tiler (PID 4242)",
                "Decks plugged in: Stream Deck MK.2",
                "udev rule: present",
                "Stream Deck venv: present",
            ],
            statut.status_lines(faits()),
        )

    def test_a_base_workstation_with_an_extension_in_error(self):
        lignes = statut.status_lines(
            faits(
                venv=False,
                udev_rule=False,
                extension={"state": 3.0, "error": "boom"},
                journal={"read": True, "failed": ["device"]},
                unit_file=False,
                unit_enabled="",
                unit_active="",
                lock=None,
                decks=[{"product": "", "id_product": "006c"}],
            )
        )
        self.assertEqual(
            [
                "Level: base",
                "Extension: state 3, error: boom",
                "Indicators: failed to mount: device",
                "Service: not installed",
                "Deck lock: free",
                "Decks plugged in: 006c",
                "udev rule: missing",
                "Stream Deck venv: missing",
            ],
            lignes,
        )

    def test_nothing_installed_and_nothing_read(self):
        lignes = statut.status_lines(
            faits(
                extension_linked=False,
                venv=False,
                extension={"state": None, "error": ""},
                journal={"read": False, "failed": []},
                decks=[],
            )
        )
        self.assertEqual("Level: not installed", lignes[0])
        self.assertEqual("Extension: not loaded in this session", lignes[1])
        self.assertEqual("Indicators: journal not read", lignes[2])
        self.assertEqual("Decks plugged in: none", lignes[5])


class LeDiagnostic(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def corrections(self, **changes):
        return [
            fix for _probleme, fix in statut.diagnosis_lines(faits(**changes))
        ]

    def test_a_sound_workstation_has_nothing_to_fix(self):
        self.assertEqual([], statut.diagnosis_lines(faits(lock=None)))

    def test_not_installed_stops_there(self):
        self.assertEqual(
            [("ERPLibre Home is not installed", "make erplibre_home_install")],
            statut.diagnosis_lines(
                faits(extension_linked=False, venv=False, decks=[])
            ),
        )

    def test_each_probe_names_its_fix(self):
        cas = (
            (
                {"extension": {"state": None, "error": ""}},
                "log out and back in",
            ),
            (
                {"extension": {"state": 3.0, "error": "boom"}},
                statut.JOURNAL_GREP,
            ),
            (
                {"journal": {"read": True, "failed": ["device"]}},
                statut.JOURNAL_GREP,
            ),
            ({"venv": False}, "make erplibre_home_streamdeck_install"),
            ({"udev_rule": False}, "make erplibre_home_streamdeck_install"),
            ({"unit_file": False}, "make erplibre_home_streamdeck_install"),
            (
                {"settings": {"DECK_PROGRAM": "exemple"}},
                "TODO › Stream Deck › Deck program",
            ),
            ({"decks": []}, "plug a Stream Deck in"),
            (
                {"unit_active": "inactive", "lock": None},
                f"systemctl --user start {UNITE}",
            ),
            (
                {"unit_active": "inactive", "lock": ("777", "controller")},
                "close it, or: kill 777",
            ),
            ({"unit_enabled": "disabled"}, f"systemctl --user enable {UNITE}"),
        )
        for changes, attendu in cas:
            with self.subTest(changes=changes):
                self.assertIn(attendu, self.corrections(**changes))

    def test_the_holder_is_named(self):
        problemes = statut.diagnosis_lines(
            faits(unit_active="inactive", lock=("777", "controller"))
        )
        self.assertIn(
            (
                "The deck is held by controller (PID 777)",
                "close it, or: kill 777",
            ),
            problemes,
        )

    def test_program_none_does_not_ask_to_start(self):
        self.assertEqual(
            [],
            self.corrections(
                settings={"DECK_PROGRAM": "none"}, unit_active="inactive"
            ),
        )


class LesTraductions(unittest.TestCase):
    def test_every_label_has_fr_and_en(self):
        source = Path(statut.__file__).read_text(encoding="utf-8")
        cles = set(re.findall(r'(?<![\w.])t\(\s*"([^"]+)"\s*\)', source))
        self.assertGreater(len(cles), 30)
        for cle in sorted(cles):
            with self.subTest(cle=cle):
                entree = todo_i18n.TRANSLATIONS.get(cle)
                self.assertIsNotNone(entree, cle)
                self.assertTrue(entree.get("fr") and entree.get("en"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_service test.test_erplibre_home_status`
Expected: `Ran 2 tests`, `FAILED (errors=2)` — `ModuleNotFoundError: No module named 'script.todo.erplibre_home_service'`.

- [ ] **Step 3: Write the settings module**

Create `script/todo/erplibre_home_service.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le service Stream Deck d'ERPLibre Home, vu de TODO : noms, chemins,
réglages, et l'appel d'une commande.

Les mêmes règles que script/install/erplibre_home_settings.sh, que lisent
l'installateur, le point d'entrée du service et l'outil de passation :
lignes « CLÉ=valeur », jamais sourcées, la dernière ligne d'une clé
l'emporte, $XDG_CONFIG_HOME prime sur ~/.config. Les fonctions prennent
`environ` pour que les tests désignent un HOME jetable.
"""

import os
import subprocess

UNIT_NAME = "erplibre-home-streamdeck.service"
PROGRAMS = ("tiler", "controller", "none")
DEFAULTS = {"DECK_PROGRAM": "tiler", "RESTART_AFTER_GAME": "yes"}


def config_home(environ=None):
    """$XDG_CONFIG_HOME, ou ~/.config quand il est vide ou absent."""
    environ = os.environ if environ is None else environ
    return environ.get("XDG_CONFIG_HOME") or os.path.join(
        environ.get("HOME", ""), ".config"
    )


def settings_path(environ=None):
    return os.path.join(
        config_home(environ), "erplibre-home", "streamdeck.conf"
    )


def unit_path(environ=None):
    return os.path.join(config_home(environ), "systemd", "user", UNIT_NAME)


def read_settings(path):
    """DEFAULTS, puis chaque ligne « CLÉ=valeur » de `path` ; la dernière
    ligne d'une clé l'emporte. Un fichier absent ou illisible rend
    DEFAULTS. Une ligne sans « = » est ignorée."""
    settings = dict(DEFAULTS)
    try:
        with open(path, encoding="utf-8") as fh:
            lignes = fh.read().splitlines()
    except (OSError, UnicodeDecodeError):
        return settings
    for ligne in lignes:
        cle, egal, valeur = ligne.partition("=")
        if egal and cle and not cle.startswith("#"):
            settings[cle] = valeur
    return settings


def settings_text(current, updates):
    """Le texte `current` avec chaque clé de `updates` posée : la ligne de
    la clé remplacée sur place, une clé absente ajoutée à la fin, toute
    autre ligne gardée dans son ordre. Rend un texte fini par « \\n »."""
    vues = set()
    lignes = []
    for ligne in current.splitlines():
        cle = ligne.partition("=")[0]
        if "=" in ligne and cle in updates:
            ligne = "%s=%s" % (cle, updates[cle])
            vues.add(cle)
        lignes.append(ligne)
    for cle, valeur in updates.items():
        if cle not in vues:
            lignes.append("%s=%s" % (cle, valeur))
    return "".join(ligne + "\n" for ligne in lignes)


def write_settings(path, updates):
    """Pose `updates` dans le fichier de réglages `path`, créé au besoin.
    N'écrit que si le texte change ; rend vrai quand il a écrit."""
    try:
        with open(path, encoding="utf-8") as fh:
            avant = fh.read()
    except FileNotFoundError:
        avant = ""
    apres = settings_text(avant, updates)
    if apres == avant:
        return False
    os.makedirs(os.path.dirname(path), exist_ok=True)
    temporaire = path + ".tmp"
    with open(temporaire, "w", encoding="utf-8") as fh:
        fh.write(apres)
    os.replace(temporaire, path)
    return True


def run_command(argv, timeout=20):
    """(code, sortie standard) de `argv`, lancé sans shell. Une commande
    absente ou qui dépasse `timeout` secondes rend (None, "")."""
    try:
        fini = subprocess.run(
            list(argv),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError):
        return None, ""
    return fini.returncode, fini.stdout
```

- [ ] **Step 4: Write the status module**

Create `script/todo/erplibre_home_status.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""État et diagnostic d'ERPLibre Home sur ce poste, pour le menu Stream
Deck de TODO.

collect() interroge le poste — fichiers, systemctl --user, GetExtensionInfo
par gdbus, journal de GNOME Shell, sysfs, verrou du deck — et rend un dict
de faits. status_lines() et diagnosis_lines() n'en font que du texte, sans
rien lancer : les tests les nourrissent de faits écrits à la main et de
sorties de commandes enregistrées.

Les faits :

- extension_linked, venv, udev_rule, unit_file : bool ;
- extension : {"state": float|None, "error": str} ;
- journal : {"read": bool, "failed": [id d'indicateur]} ;
- unit_enabled, unit_active : sortie de systemctl is-enabled / is-active,
  "" quand l'unité n'est pas installée ;
- settings : les réglages du service, défauts compris ;
- lock : (pid, programme) du détenteur du verrou du deck, ou None ;
- decks : [{"product": str, "id_product": str}], vendeur 0fd9.
"""

import glob
import importlib.util
import os
import re

from script.todo import erplibre_home_service as service
from script.todo.todo_i18n import t

EXTENSION_UUID = "erplibre-home@technolibre.ca"
UDEV_RULE = "/etc/udev/rules.d/70-streamdeck.rules"
DECK_VENDOR = "0fd9"

CMD_EXTENSION_INFO = (
    "gdbus",
    "call",
    "--session",
    "--dest",
    "org.gnome.Shell.Extensions",
    "--object-path",
    "/org/gnome/Shell/Extensions",
    "--method",
    "org.gnome.Shell.Extensions.GetExtensionInfo",
    EXTENSION_UUID,
)
# Le journal de GNOME Shell pour ce démarrage : l'extension y écrit
# « [ERPLibreHome] enabled » à la fin d'enable() et « mount <id> failed »
# pour un indicateur qui n'a pas pu se monter.
CMD_JOURNAL = (
    "journalctl",
    "--user",
    "-b",
    "-o",
    "cat",
    "--no-pager",
    "_COMM=gnome-shell",
)
JOURNAL_GREP = (
    "journalctl --user -b -o cat _COMM=gnome-shell | grep ERPLibreHome"
)
STREAMDECK_INSTALL = "make erplibre_home_streamdeck_install"


def cmd_unit(verb):
    return ("systemctl", "--user", verb, service.UNIT_NAME)


_ETAT = re.compile(r"'state': <(-?\d+(?:\.\d+)?)>")
_ERREUR = re.compile(
    r"""'error': <(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")>"""
)
_MONTAGE_ECHOUE = re.compile(r"\[ERPLibreHome\] mount (\S+) failed")


def parse_extension_info(text):
    """{"state": float|None, "error": str} lus dans la sortie de gdbus.

    GetExtensionInfo rend un a{sv} au format texte de GVariant ; une
    extension que GNOME Shell ne connaît pas rend un dictionnaire vide, lu
    comme state None. Une chaîne citée entre guillemets (elle contient une
    apostrophe) est lue aussi, ses échappements défaits."""
    texte = text or ""
    etat = _ETAT.search(texte)
    trouve = _ERREUR.search(texte)
    erreur = ""
    if trouve:
        brut = trouve.group(1)
        if brut is None:
            brut = trouve.group(2)
        erreur = re.sub(r"\\(.)", r"\1", brut)
    return {
        "state": float(etat.group(1)) if etat else None,
        "error": erreur,
    }


def parse_journal(text):
    """{"read": bool, "failed": [id]} : read quand la ligne
    « [ERPLibreHome] enabled » y est, preuve que le journal de la session a
    été lu ; failed, les indicateurs non montés, triés, sans doublon."""
    lignes = (text or "").splitlines()
    return {
        "read": any(
            ligne.strip().endswith("[ERPLibreHome] enabled")
            for ligne in lignes
        ),
        "failed": sorted(set(_MONTAGE_ECHOUE.findall(text or ""))),
    }


def _lire(chemin):
    try:
        with open(chemin, encoding="utf-8") as fh:
            return fh.read().strip()
    except (OSError, UnicodeDecodeError):
        return ""


def plugged_decks(sysfs="/sys"):
    """Les périphériques USB du vendeur 0fd9 sous `sysfs`, triés par
    chemin : {"product": nom lu dans « product », "" s'il manque,
    "id_product": idProduct}."""
    decks = []
    motif = os.path.join(sysfs, "bus/usb/devices/*/idVendor")
    for fichier in sorted(glob.glob(motif)):
        if _lire(fichier) != DECK_VENDOR:
            continue
        dossier = os.path.dirname(fichier)
        decks.append(
            {
                "product": _lire(os.path.join(dossier, "product")),
                "id_product": _lire(os.path.join(dossier, "idProduct")),
            }
        )
    return decks


def _deck_lock(root):
    """script/stream_deck/deck_lock.py chargé par son chemin :
    script/stream_deck n'est pas un paquet."""
    chemin = os.path.join(root, "script", "stream_deck", "deck_lock.py")
    spec = importlib.util.spec_from_file_location("deck_lock", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect(
    run,
    root,
    environ=None,
    sysfs="/sys",
    udev_rule=UDEV_RULE,
    lock_path=None,
):
    """Les faits du poste. `run(argv)` rend (code, sortie) ; `root` est la
    racine du dépôt. systemctl n'est appelé que si l'unité est installée.
    `lock_path` None prend le chemin que lit deck_lock."""
    environ = os.environ if environ is None else environ
    lien = os.path.join(
        environ.get("HOME", ""),
        ".local/share/gnome-shell/extensions",
        EXTENSION_UUID,
    )
    python = os.path.join(root, ".venv.streamdeck", "bin", "python")
    unit_file = os.path.exists(service.unit_path(environ))
    deck_lock = _deck_lock(root)
    return {
        "extension_linked": os.path.islink(lien),
        "venv": os.access(python, os.X_OK),
        "udev_rule": os.path.exists(udev_rule),
        "extension": parse_extension_info(run(CMD_EXTENSION_INFO)[1]),
        "journal": parse_journal(run(CMD_JOURNAL)[1]),
        "unit_file": unit_file,
        "unit_enabled": (
            run(cmd_unit("is-enabled"))[1].strip() if unit_file else ""
        ),
        "unit_active": (
            run(cmd_unit("is-active"))[1].strip() if unit_file else ""
        ),
        "settings": service.read_settings(service.settings_path(environ)),
        "lock": deck_lock.holder(lock_path or deck_lock.lock_path(environ)),
        "decks": plugged_decks(sysfs),
    }


def _actif(extension):
    return extension["state"] == 1 and extension["error"] == ""


def status_lines(facts):
    """Une ligne par sonde, dans la langue de l'utilisateur."""
    if not facts["extension_linked"]:
        niveau = t("Level: not installed")
    elif facts["venv"]:
        niveau = t("Level: Stream Deck")
    else:
        niveau = t("Level: base")
    extension = facts["extension"]
    if _actif(extension):
        ligne_ext = t("Extension: active")
    elif extension["state"] is None:
        ligne_ext = t("Extension: not loaded in this session")
    else:
        ligne_ext = "%s %g, %s %s" % (
            t("Extension: state"),
            extension["state"],
            t("error:"),
            extension["error"] or "-",
        )
    journal = facts["journal"]
    if not journal["read"]:
        indicateurs = t("Indicators: journal not read")
    elif journal["failed"]:
        indicateurs = "%s %s" % (
            t("Indicators: failed to mount:"),
            ", ".join(journal["failed"]),
        )
    else:
        indicateurs = t("Indicators: all mounted")
    if facts["unit_file"]:
        unite = "%s %s, %s, %s %s" % (
            t("Service:"),
            facts["unit_enabled"] or "?",
            facts["unit_active"] or "?",
            t("program"),
            facts["settings"]["DECK_PROGRAM"],
        )
    else:
        unite = t("Service: not installed")
    if facts["lock"]:
        verrou = "%s %s (PID %s)" % (
            t("Deck lock: held by"),
            facts["lock"][1],
            facts["lock"][0],
        )
    else:
        verrou = t("Deck lock: free")
    if facts["decks"]:
        decks = "%s %s" % (
            t("Decks plugged in:"),
            ", ".join(
                d["product"] or d["id_product"] or "?" for d in facts["decks"]
            ),
        )
    else:
        decks = t("Decks plugged in: none")
    return [
        niveau,
        ligne_ext,
        indicateurs,
        unite,
        verrou,
        decks,
        (
            t("udev rule: present")
            if facts["udev_rule"]
            else t("udev rule: missing")
        ),
        (
            t("Stream Deck venv: present")
            if facts["venv"]
            else t("Stream Deck venv: missing")
        ),
    ]


def diagnosis_lines(facts):
    """[(problème, correction)] pour chaque sonde qui n'est pas comme
    attendu, dans l'ordre où les corriger ; [] quand tout va. Sans
    l'extension, ou sans le niveau Stream Deck, la liste s'arrête là : ce
    qui suit en dépend."""
    if not facts["extension_linked"]:
        return [
            (t("ERPLibre Home is not installed"), "make erplibre_home_install")
        ]
    problemes = []
    extension = facts["extension"]
    if extension["state"] is None:
        problemes.append(
            (
                t("The extension is not loaded in this session"),
                t("log out and back in"),
            )
        )
    elif not _actif(extension):
        problemes.append(
            (
                "%s %s"
                % (t("The extension is in error:"), extension["error"]),
                JOURNAL_GREP,
            )
        )
    journal = facts["journal"]
    if journal["read"] and journal["failed"]:
        problemes.append(
            (
                "%s %s"
                % (
                    t("Indicators failed to mount:"),
                    ", ".join(journal["failed"]),
                ),
                JOURNAL_GREP,
            )
        )
    if not (facts["venv"] and facts["udev_rule"]):
        problemes.append(
            (t("The Stream Deck level is not installed"), STREAMDECK_INSTALL)
        )
        return problemes
    if not facts["unit_file"]:
        problemes.append(
            (t("The deck service is not installed"), STREAMDECK_INSTALL)
        )
        return problemes
    programme = facts["settings"]["DECK_PROGRAM"]
    if programme not in service.PROGRAMS:
        problemes.append(
            (
                "%s %s" % (t("Unknown DECK_PROGRAM:"), programme),
                t("TODO › Stream Deck › Deck program"),
            )
        )
    if not facts["decks"]:
        problemes.append(
            (t("No Stream Deck plugged in"), t("plug a Stream Deck in"))
        )
    elif programme != "none" and facts["unit_active"] != "active":
        if facts["lock"]:
            pid, detenteur = facts["lock"]
            problemes.append(
                (
                    "%s %s (PID %s)"
                    % (t("The deck is held by"), detenteur, pid),
                    "%s kill %s" % (t("close it, or:"), pid),
                )
            )
        else:
            problemes.append(
                (
                    t("The deck service is not running"),
                    "systemctl --user start %s" % service.UNIT_NAME,
                )
            )
    if facts["unit_enabled"] != "enabled":
        problemes.append(
            (
                t("The deck service does not start at login"),
                "systemctl --user enable %s" % service.UNIT_NAME,
            )
        )
    return problemes
```

- [ ] **Step 5: Add the translations**

In `script/todo/todo_i18n.py` (`"Service:"` already exists and is reused, not added):

Edit 1/1, replace:

```python
            "ERPLibre Home installed. Log out and back in to load"
            " the extension."
        ),
    },
    # Stream Deck game descriptions (42 games)
    "game_2048": {
```

with:

```python
            "ERPLibre Home installed. Log out and back in to load"
            " the extension."
        ),
    },
    # Stream Deck: status and diagnosis (script/todo/erplibre_home_status.py)
    "Level: not installed": {
        "fr": "Niveau : non installé",
        "en": "Level: not installed",
    },
    "Level: base": {
        "fr": "Niveau : base",
        "en": "Level: base",
    },
    "Level: Stream Deck": {
        "fr": "Niveau : Stream Deck",
        "en": "Level: Stream Deck",
    },
    "Extension: active": {
        "fr": "Extension : active",
        "en": "Extension: active",
    },
    "Extension: not loaded in this session": {
        "fr": "Extension : non chargée dans cette session",
        "en": "Extension: not loaded in this session",
    },
    "Extension: state": {
        "fr": "Extension : état",
        "en": "Extension: state",
    },
    "error:": {
        "fr": "erreur :",
        "en": "error:",
    },
    "Indicators: journal not read": {
        "fr": "Indicateurs : journal non lu",
        "en": "Indicators: journal not read",
    },
    "Indicators: failed to mount:": {
        "fr": "Indicateurs : non montés :",
        "en": "Indicators: failed to mount:",
    },
    "Indicators: all mounted": {
        "fr": "Indicateurs : tous montés",
        "en": "Indicators: all mounted",
    },
    "program": {
        "fr": "programme",
        "en": "program",
    },
    "Service: not installed": {
        "fr": "Service : non installé",
        "en": "Service: not installed",
    },
    "Deck lock: held by": {
        "fr": "Verrou du deck : tenu par",
        "en": "Deck lock: held by",
    },
    "Deck lock: free": {
        "fr": "Verrou du deck : libre",
        "en": "Deck lock: free",
    },
    "Decks plugged in:": {
        "fr": "Decks branchés :",
        "en": "Decks plugged in:",
    },
    "Decks plugged in: none": {
        "fr": "Decks branchés : aucun",
        "en": "Decks plugged in: none",
    },
    "udev rule: present": {
        "fr": "Règle udev : présente",
        "en": "udev rule: present",
    },
    "udev rule: missing": {
        "fr": "Règle udev : absente",
        "en": "udev rule: missing",
    },
    "Stream Deck venv: present": {
        "fr": "Venv Stream Deck : présent",
        "en": "Stream Deck venv: present",
    },
    "Stream Deck venv: missing": {
        "fr": "Venv Stream Deck : absent",
        "en": "Stream Deck venv: missing",
    },
    "ERPLibre Home is not installed": {
        "fr": "ERPLibre Home n'est pas installé",
        "en": "ERPLibre Home is not installed",
    },
    "The extension is not loaded in this session": {
        "fr": "L'extension n'est pas chargée dans cette session",
        "en": "The extension is not loaded in this session",
    },
    "log out and back in": {
        "fr": "fermer la session puis la rouvrir",
        "en": "log out and back in",
    },
    "The extension is in error:": {
        "fr": "L'extension est en erreur :",
        "en": "The extension is in error:",
    },
    "Indicators failed to mount:": {
        "fr": "Indicateurs non montés :",
        "en": "Indicators failed to mount:",
    },
    "The Stream Deck level is not installed": {
        "fr": "Le niveau Stream Deck n'est pas installé",
        "en": "The Stream Deck level is not installed",
    },
    "The deck service is not installed": {
        "fr": "Le service du deck n'est pas installé",
        "en": "The deck service is not installed",
    },
    "Unknown DECK_PROGRAM:": {
        "fr": "DECK_PROGRAM inconnu :",
        "en": "Unknown DECK_PROGRAM:",
    },
    "TODO › Stream Deck › Deck program": {
        "fr": "TODO › Stream Deck › Programme du deck",
        "en": "TODO › Stream Deck › Deck program",
    },
    "No Stream Deck plugged in": {
        "fr": "Aucun Stream Deck branché",
        "en": "No Stream Deck plugged in",
    },
    "plug a Stream Deck in": {
        "fr": "brancher un Stream Deck",
        "en": "plug a Stream Deck in",
    },
    "The deck is held by": {
        "fr": "Le deck est tenu par",
        "en": "The deck is held by",
    },
    "close it, or:": {
        "fr": "le fermer, ou :",
        "en": "close it, or:",
    },
    "The deck service is not running": {
        "fr": "Le service du deck ne tourne pas",
        "en": "The deck service is not running",
    },
    "The deck service does not start at login": {
        "fr": "Le service du deck ne démarre pas à l'ouverture de session",
        "en": "The deck service does not start at login",
    },
    # Stream Deck game descriptions (42 games)
    "game_2048": {
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv.erplibre/bin/python -m unittest test.test_erplibre_home_service test.test_erplibre_home_status test.test_todo_i18n`
Expected: `Ran 48 tests`, `OK` (10 + 14 + 24).

- [ ] **Step 7: Format and comment hygiene**

Run: `.venv.erplibre/bin/black -l 79 --check script/todo/erplibre_home_service.py script/todo/erplibre_home_status.py test/test_erplibre_home_service.py test/test_erplibre_home_status.py && python3 script/analyse/check_comment_hygiene.py script/todo/erplibre_home_service.py script/todo/erplibre_home_status.py test/test_erplibre_home_service.py test/test_erplibre_home_status.py`
Expected: `4 files would be left unchanged.` and no hygiene line.

- [ ] **Step 8: Commit**

Write `"$SCRATCH/msg-5.txt"`:

```text
[ADD] todo: ERPLibre Home status and diagnosis from recorded probes

The Stream Deck menu needs one view of what is installed and what runs,
and of what to do when something is not as expected.
erplibre_home_status.collect() reads the files, systemctl --user,
GetExtensionInfo, the GNOME Shell journal, sysfs and the deck lock;
status_lines() and diagnosis_lines() only turn those facts into text,
each problem with the command that fixes it. erplibre_home_service.py
reads and writes the settings by the installer's rules, checked against
it. Every label has its French and English keys.

--- FR ---
[ADD] todo : état et diagnostic d'ERPLibre Home sur sondes enregistrées

Le menu Stream Deck demande une vue de ce qui est installé et de ce qui
tourne, et de quoi faire quand une chose n'est pas comme attendu.
erplibre_home_status.collect() lit les fichiers, systemctl --user,
GetExtensionInfo, le journal de GNOME Shell, sysfs et le verrou du deck ;
status_lines() et diagnosis_lines() n'en font que du texte, chaque
problème avec sa commande. erplibre_home_service.py lit et écrit les
réglages selon les règles de l'installateur, comparé à lui. Chaque
libellé a ses clés française et anglaise.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-5.txt"
git add script/todo/erplibre_home_service.py script/todo/erplibre_home_status.py script/todo/todo_i18n.py test/test_erplibre_home_service.py test/test_erplibre_home_status.py
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-5.txt"
```

---

### Task 6: TODO Stream Deck submenu

**Files:**
- Create: `script/todo/streamdeck_menu.py`
- Modify: `script/todo/todo.py` (mixin import near line 140, class bases near line 212, `_MENU_LABELS` near line 741, `prompt_execute` lines 357-445, `_erplibre_home_*` near line 1958)
- Modify: `script/todo/todo_i18n.py` (insert before the Task 5 block's first line `    # Stream Deck: status and diagnosis (script/todo/erplibre_home_status.py)`)
- Modify: `script/stream_deck/INSTALL.base.md` (after the `systemctl --user` block of Task 4); regenerate `INSTALL.md`, `INSTALL.fr.md`
- Test: `test/test_todo_streamdeck_menu.py` (new), `test/test_todo_menu.py` (`EXPECTED` of Execute, new `TestStreamDeckMenuNumbering`), `test/test_todo_erplibre_home_install.py` (answers Enter to the questions; the Stream Deck command now ends with `--deck-program=tiler --restart-after-game`)

**Interfaces:**
- Consumes: Task 3's `TODO.prompt_execute_streamdeck_games` (unchanged name); Task 4's installer options; Task 5's `erplibre_home_service` (`UNIT_NAME`, `PROGRAMS`, `settings_path`, `unit_path`, `read_settings`, `write_settings`, `run_command`) and `erplibre_home_status` (`collect`, `status_lines`, `diagnosis_lines`, `cmd_unit`).
- Produces (`script.todo.streamdeck_menu`): `RACINE`, `INSTALLER = "./script/install/install_erplibre_home.sh"`, `EXTENSION_UUID`; `class StreamDeckMenuMixin` with `prompt_execute_streamdeck()`, `_streamdeck_probe(argv) -> (code, stdout)` (static, replaced by tests), `_streamdeck_choice(question, options, defaut="1")` (options are `(value, label)` pairs; returns the value or None), `_streamdeck_unit_installed() -> bool`, `_streamdeck_systemctl(*args)`, `_streamdeck_status()`, `_streamdeck_diagnosis()`, `_streamdeck_service()`, `_streamdeck_program()`, `_streamdeck_autostart()`, `_streamdeck_uninstall()`, `_streamdeck_extension()`, `_erplibre_home_streamdeck_options() -> list[str] | None`.
- Produces (`script.todo.todo.TODO`): `_erplibre_home_run_installer(commande, succes=<install key>)` — `succes` is the translation key printed after `✅` on exit 0; `_erplibre_home_streamdeck_install_local()` asks the four questions, prints `Will execute: <command>` and runs it; the command always carries `--deck-program=<answer>` and `--restart-after-game` or `--no-restart-after-game`, plus `--autostart` / `--with-extras` on a yes.

- [ ] **Step 1: Write the failing tests**

Create `test/test_todo_streamdeck_menu.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les actions du menu Stream Deck de TODO.

Chaque action se joue sur un TODO sans __init__, sous un HOME temporaire :
le lanceur est un double qui retient les commandes, les sondes muettes
rendent ce qu'on leur fixe, les réponses au clavier viennent d'une liste.
Aucune commande ne part.

Ce que ces tests gardent :

- les quatre questions de l'installation Stream Deck deviennent des
  options, le programme et la relance toujours explicites, la commande
  s'affiche avant de partir, et 0 n'installe rien ;
- service, autostart et programme disent quoi installer sans unité, et
  appellent systemctl --user sinon ; le programme change le réglage et ne
  redémarre l'unité que si elle tournait ;
- la désinstallation demande confirmation ;
- l'extension se recharge par make, ses préférences par gnome-extensions ;
- l'état et le diagnostic affichent ce que rend erplibre_home_status ;
- chaque libellé a ses deux langues.
"""

import contextlib
import io
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
sys.argv = ["todo.py"]

from script.todo import streamdeck_menu  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

UNITE = "erplibre-home-streamdeck.service"
INSTALLATEUR = "./script/install/install_erplibre_home.sh"


class ExecuteFactice:
    """Retient chaque commande ; rend (0, []) quand on lui demande code et
    lignes, comme exec_command_live."""

    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        if kwargs.get("return_status_and_output"):
            return 0, []
        return 0


class Menu(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.home = Path(dossier.name)
        environ = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        environ.start()
        self.addCleanup(environ.stop)
        os.environ.pop("XDG_CONFIG_HOME", None)
        self.reglages = self.home / ".config/erplibre-home/streamdeck.conf"
        self.sondes = []
        self.reponses_sondes = {}

    def unite(self):
        fichier = self.home / ".config/systemd/user" / UNITE
        fichier.parent.mkdir(parents=True)
        fichier.write_text("[Unit]\n")

    def jouer(self, methode, reponses):
        """Lance `methode` avec `reponses` au clavier. Rend (commandes
        lancées, sortie, valeur rendue)."""
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()

        def sonde(argv):
            self.sondes.append(tuple(argv))
            return self.reponses_sondes.get(tuple(argv), (1, ""))

        todo._streamdeck_probe = sonde
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch("builtins.input", side_effect=list(reponses)),
        ):
            rendu = getattr(todo, methode)()
        return todo.execute.commandes, sortie.getvalue(), rendu


class LInstallationStreamDeck(Menu):
    def test_each_answer_becomes_an_option(self):
        cas = (
            (("", "", "", ""), " --deck-program=tiler --restart-after-game"),
            (
                ("2", "y", "n", "y"),
                " --deck-program=controller --autostart"
                " --no-restart-after-game --with-extras",
            ),
            (
                ("3", "", "", ""),
                " --deck-program=none --restart-after-game",
            ),
            (
                ("1", "o", "", ""),
                " --deck-program=tiler --autostart --restart-after-game",
            ),
        )
        for reponses, options in cas:
            with self.subTest(reponses=reponses):
                commandes, sortie, rendu = self.jouer(
                    "_erplibre_home_streamdeck_install_local", reponses
                )
                commande = f"{INSTALLATEUR} --stream-deck{options}"
                self.assertEqual([commande], commandes)
                self.assertIn(f"Will execute: {commande}", sortie)
                self.assertIs(rendu, False)

    def test_zero_installs_nothing(self):
        commandes, _sortie, rendu = self.jouer(
            "_erplibre_home_streamdeck_install_local", ("0",)
        )
        self.assertEqual([], commandes)
        self.assertIs(rendu, False)


class LeService(Menu):
    def test_without_the_unit_it_names_the_install(self):
        for methode in (
            "_streamdeck_service",
            "_streamdeck_program",
            "_streamdeck_autostart",
        ):
            with self.subTest(methode=methode):
                commandes, sortie, _ = self.jouer(methode, ())
                self.assertEqual([], commandes)
                self.assertIn("make erplibre_home_streamdeck_install", sortie)

    def test_each_action_calls_systemctl_user(self):
        self.unite()
        attendus = {
            "1": f"systemctl --user start {UNITE}",
            "2": f"systemctl --user stop {UNITE}",
            "3": f"systemctl --user restart {UNITE}",
            "4": f"journalctl --user -u {UNITE} -f",
        }
        for reponse, commande in attendus.items():
            with self.subTest(reponse=reponse):
                commandes, _, _ = self.jouer("_streamdeck_service", (reponse,))
                self.assertEqual([commande], commandes)

    def test_autostart_enables_or_disables(self):
        self.unite()
        self.reponses_sondes[("systemctl", "--user", "is-enabled", UNITE)] = (
            1,
            "disabled\n",
        )
        for reponse, verbe in (("1", "enable"), ("2", "disable")):
            with self.subTest(verbe=verbe):
                commandes, sortie, _ = self.jouer(
                    "_streamdeck_autostart", (reponse,)
                )
                self.assertEqual(
                    [f"systemctl --user {verbe} {UNITE}"], commandes
                )
                self.assertIn("Autostart: disabled", sortie)


class LeProgramme(Menu):
    def test_it_rewrites_the_setting_and_restarts_an_active_unit(self):
        self.unite()
        self.reponses_sondes[("systemctl", "--user", "is-active", UNITE)] = (
            0,
            "active\n",
        )
        commandes, _, _ = self.jouer("_streamdeck_program", ("2",))
        self.assertEqual(
            "DECK_PROGRAM=controller\n", self.reglages.read_text()
        )
        self.assertEqual([f"systemctl --user restart {UNITE}"], commandes)

    def test_a_stopped_unit_stays_stopped(self):
        self.unite()
        commandes, _, _ = self.jouer("_streamdeck_program", ("3",))
        self.assertEqual("DECK_PROGRAM=none\n", self.reglages.read_text())
        self.assertEqual([], commandes)

    def test_the_same_program_changes_nothing(self):
        self.unite()
        self.reglages.parent.mkdir(parents=True)
        self.reglages.write_text("DECK_PROGRAM=tiler\n")
        commandes, sortie, _ = self.jouer("_streamdeck_program", ("",))
        self.assertEqual([], commandes)
        self.assertIn("Unchanged.", sortie)
        self.assertNotIn(
            ("systemctl", "--user", "is-active", UNITE), self.sondes
        )


class LaDesinstallation(Menu):
    def test_each_choice_runs_its_options_after_confirmation(self):
        for reponse, options in (
            ("1", "--uninstall --stream-deck"),
            ("2", "--uninstall"),
        ):
            with self.subTest(options=options):
                commandes, sortie, _ = self.jouer(
                    "_streamdeck_uninstall", (reponse, "y")
                )
                self.assertEqual([f"{INSTALLATEUR} {options}"], commandes)
                self.assertIn("ERPLibre Home uninstalled.", sortie)

    def test_no_confirmation_no_uninstall(self):
        commandes, _, _ = self.jouer("_streamdeck_uninstall", ("2", ""))
        self.assertEqual([], commandes)


class LExtension(Menu):
    def test_reload_and_preferences(self):
        for reponse, commande in (
            ("1", "make erplibre_home_reload"),
            ("2", "gnome-extensions prefs erplibre-home@technolibre.ca"),
        ):
            with self.subTest(commande=commande):
                commandes, _, _ = self.jouer(
                    "_streamdeck_extension", (reponse,)
                )
                self.assertEqual([commande], commandes)


class LEtatEtLeDiagnostic(Menu):
    FAITS = {"exemple": True}

    def test_status_prints_the_status_lines(self):
        with (
            mock.patch.object(
                streamdeck_menu.statut, "collect", return_value=self.FAITS
            ) as collect,
            mock.patch.object(
                streamdeck_menu.statut,
                "status_lines",
                return_value=["Level: base", "Deck lock: free"],
            ),
        ):
            _, sortie, _ = self.jouer("_streamdeck_status", ())
        self.assertEqual("  Level: base\n  Deck lock: free\n", sortie)
        self.assertEqual(streamdeck_menu.RACINE, collect.call_args[0][1])

    def test_diagnosis_prints_each_fix_or_nothing_to_fix(self):
        with (
            mock.patch.object(
                streamdeck_menu.statut, "collect", return_value=self.FAITS
            ),
            mock.patch.object(
                streamdeck_menu.statut,
                "diagnosis_lines",
                return_value=[("No Stream Deck plugged in", "plug it in")],
            ),
        ):
            _, sortie, _ = self.jouer("_streamdeck_diagnosis", ())
        self.assertEqual(
            "❌ No Stream Deck plugged in\n   → plug it in\n", sortie
        )
        with (
            mock.patch.object(
                streamdeck_menu.statut, "collect", return_value=self.FAITS
            ),
            mock.patch.object(
                streamdeck_menu.statut, "diagnosis_lines", return_value=[]
            ),
        ):
            _, sortie, _ = self.jouer("_streamdeck_diagnosis", ())
        self.assertEqual("✅ Nothing to fix.\n", sortie)


class LesTraductions(unittest.TestCase):
    def test_every_label_has_fr_and_en(self):
        source = Path(streamdeck_menu.__file__).read_text(encoding="utf-8")
        cles = set(re.findall(r'(?<![\w.])t\(\s*"([^"]+)"\s*\)', source))
        cles |= {
            "".join(morceaux)
            for morceaux in re.findall(
                r'(?<![\w.])t\(\s*\n\s*"([^"]+)"\s*\n\s*"([^"]+)"', source
            )
        }
        self.assertGreater(len(cles), 20)
        for cle in sorted(cles):
            with self.subTest(cle=cle):
                entree = todo_i18n.TRANSLATIONS.get(cle)
                self.assertIsNotNone(entree, cle)
                self.assertTrue(entree.get("fr") and entree.get("en"))


if __name__ == "__main__":
    unittest.main()
```

In `test/test_todo_menu.py`:

Edit 1/2, replace:

```python
        "Network": "prompt_execute_network",
        "Security": "prompt_execute_security",
        "Docker / Podman": "prompt_execute_container",
        "Games": "prompt_execute_streamdeck_games",
        "Install ERPLibre Home (local)": "_erplibre_home_install_local",
        "Install ERPLibre Home Stream Deck (local)": (
            "_erplibre_home_streamdeck_install_local"
        ),
    }

    def _entry_key(self, label):
```

with:

```python
        "Network": "prompt_execute_network",
        "Security": "prompt_execute_security",
        "Docker / Podman": "prompt_execute_container",
        "Stream Deck": "prompt_execute_streamdeck",
    }

    def _entry_key(self, label):
```

Edit 2/2, replace:

```python
    }


class TestAnalyseMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Analyse, qui n'avait aucun garde.

```

with:

```python
    }


class TestStreamDeckMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Stream Deck, dans script/todo/streamdeck_menu.py : jeux,
    installations, service, état, diagnostic, réunis sous une entrée
    d'Exécution."""

    SOURCE = TODO_DIR / "streamdeck_menu.py"
    ENTRY = "def prompt_execute_streamdeck(self):"
    END = "def _streamdeck_probe(argv):"
    MINIMUM = 9

    EXPECTED = {
        "Games": "prompt_execute_streamdeck_games",
        "Status": "_streamdeck_status",
        "Service": "_streamdeck_service",
        "Deck program": "_streamdeck_program",
        "Autostart": "_streamdeck_autostart",
        "Diagnosis": "_streamdeck_diagnosis",
        "Install ERPLibre Home (local)": "_erplibre_home_install_local",
        "Install ERPLibre Home Stream Deck (local)": (
            "_erplibre_home_streamdeck_install_local"
        ),
        "Uninstall": "_streamdeck_uninstall",
        "Extension": "_streamdeck_extension",
    }


class TestAnalyseMenuNumbering(MenuCoherence, unittest.TestCase):
    """Le menu Analyse, qui n'avait aucun garde.

```

In `test/test_todo_erplibre_home_install.py`:

Edit 1/4, replace:

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les deux entrées d'installation locale d'ERPLibre Home du menu Exécution.

« Installer ERPLibre Home (local) » pose la base, « Installer ERPLibre Home
Stream Deck (local) » le niveau Stream Deck, base comprise. Les deux lancent
le même installateur, la seconde avec --stream-deck.

L'installateur rend trois issues, et le menu les annonce chacune par une
seule ligne : 0 installé, 2 système hors périmètre — avec la raison que
```

with:

```python
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les deux entrées d'installation locale d'ERPLibre Home du menu Stream
Deck.

« Installer ERPLibre Home (local) » pose la base, « Installer ERPLibre Home
Stream Deck (local) » le niveau Stream Deck, base comprise. Les deux lancent
le même installateur, la seconde avec --stream-deck, après quatre questions
dont les réponses par défaut donnent --deck-program=tiler et
--restart-after-game : ces tests-ci répondent Entrée à chacune. Les autres
réponses sont gardées par test_todo_streamdeck_menu.py.

L'installateur rend trois issues, et le menu les annonce chacune par une
seule ligne : 0 installé, 2 système hors périmètre — avec la raison que
```

Edit 2/4, replace:

```python
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
```

with:

```python
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))
```

Edit 3/4, replace:

```python
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice(code, lignes)
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            rendu = getattr(todo, methode)()
        return todo.execute.appels, sortie.getvalue(), rendu

```

with:

```python
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice(code, lignes)
        sortie = io.StringIO()
        with (
            contextlib.redirect_stdout(sortie),
            mock.patch("builtins.input", return_value=""),
        ):
            rendu = getattr(todo, methode)()
        return todo.execute.appels, sortie.getvalue(), rendu

```

Edit 4/4, replace:

```python
ENTREES = {
    "_erplibre_home_install_local": INSTALLATEUR,
    "_erplibre_home_streamdeck_install_local": INSTALLATEUR + " --stream-deck",
}
```

with:

```python
ENTREES = {
    "_erplibre_home_install_local": INSTALLATEUR,
    "_erplibre_home_streamdeck_install_local": (
        INSTALLATEUR + " --stream-deck --deck-program=tiler"
        " --restart-after-game"
    ),
}
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_todo_streamdeck_menu test.test_todo_menu test.test_todo_erplibre_home_install`
Expected: `Ran 67 tests`, `FAILED (failures=3, errors=7)` — `streamdeck_menu` cannot be imported, its numbering test cannot read the file, Execute still shows `Games` and the two installs instead of `Stream Deck`, and the Stream Deck install command lacks `--deck-program=tiler --restart-after-game`.

- [ ] **Step 3: Write the submenu mixin**

Create `script/todo/streamdeck_menu.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Stream Deck de TODO : jeux, installations, service, état.

Il réunit sous une entrée d'Exécution ce qui touche au Stream Deck : les
jeux, les deux installations locales d'ERPLibre Home, le service systemd
--user erplibre-home-streamdeck.service et ses réglages, l'état du poste et
son diagnostic, la désinstallation, l'extension GNOME.

Les commandes longues ou interactives (systemctl, journalctl -f,
l'installateur, make) passent par self.execute.exec_command_live, en
direct ; les sondes muettes par _streamdeck_probe, que les tests
remplacent. L'état et le diagnostic viennent d'erplibre_home_status.
"""

import os
import shlex

import click

from script.todo import erplibre_home_service as service
from script.todo import erplibre_home_status as statut
from script.todo.todo_i18n import t

# La racine du dépôt, d'où partent l'installateur et make.
RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
INSTALLER = "./script/install/install_erplibre_home.sh"
EXTENSION_UUID = "erplibre-home@technolibre.ca"


class StreamDeckMenuMixin:
    def prompt_execute_streamdeck(self):
        choices = [
            {"prompt_description": t("Games - Stream Deck games")},
            {
                "prompt_description": t(
                    "Status - What is installed and what runs"
                )
            },
            {
                "prompt_description": t(
                    "Service - Start, stop, restart, live log"
                )
            },
            {
                "prompt_description": t(
                    "Deck program - Tiler, controller or none"
                )
            },
            {"prompt_description": t("Autostart - Enable or disable")},
            {
                "prompt_description": t(
                    "Diagnosis - What is wrong and how to fix it"
                )
            },
            {"prompt_description": t("Install ERPLibre Home (local)")},
            {
                "prompt_description": t(
                    "Install ERPLibre Home Stream Deck (local)"
                )
            },
            {
                "prompt_description": t(
                    "Uninstall - Stream Deck level or everything"
                )
            },
            {"prompt_description": t("Extension - Reload or preferences")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self.prompt_execute_streamdeck_games()
            elif status == "2":
                self._streamdeck_status()
            elif status == "3":
                self._streamdeck_service()
            elif status == "4":
                self._streamdeck_program()
            elif status == "5":
                self._streamdeck_autostart()
            elif status == "6":
                self._streamdeck_diagnosis()
            elif status == "7":
                self._erplibre_home_install_local()
            elif status == "8":
                self._erplibre_home_streamdeck_install_local()
            elif status == "9":
                self._streamdeck_uninstall()
            elif status == "10":
                self._streamdeck_extension()
            else:
                print(t("Command not found !"))

    # -------------------------------------------------------------- #
    # Sondes et choix

    @staticmethod
    def _streamdeck_probe(argv):
        """(code, sortie) d'une commande muette ; les tests la remplacent."""
        return service.run_command(argv)

    @staticmethod
    def _streamdeck_choice(question, options, defaut="1"):
        """Affiche `question` puis `options`, des couples (valeur,
        libellé), numérotés à partir de 1, le défaut marqué d'une étoile.
        Rend la valeur choisie, celle du défaut sur une réponse vide, None
        sur 0 ou une réponse hors liste."""
        print(question)
        for rang, (_valeur, libelle) in enumerate(options, 1):
            marque = " *" if str(rang) == defaut else ""
            print(f"  [{rang}] {libelle}{marque}")
        print(f"  [0] {t('Back')}")
        reponse = input(t("Choice: ")).strip() or defaut
        if reponse.isdigit() and 1 <= int(reponse) <= len(options):
            return options[int(reponse) - 1][0]
        return None

    def _streamdeck_unit_installed(self):
        """Vrai quand l'unité du service existe ; sinon le dit avec la
        commande qui l'installe."""
        if os.path.exists(service.unit_path()):
            return True
        print(
            t(
                "The Stream Deck service is not installed:"
                " make erplibre_home_streamdeck_install"
            )
        )
        return False

    def _streamdeck_systemctl(self, *args):
        """systemctl --user <args> en direct, sortie affichée."""
        commande = "systemctl --user " + " ".join(shlex.quote(a) for a in args)
        self.execute.exec_command_live(commande, source_erplibre=False)

    # -------------------------------------------------------------- #
    # Entrées

    def _streamdeck_status(self):
        faits = statut.collect(self._streamdeck_probe, RACINE)
        for ligne in statut.status_lines(faits):
            print(f"  {ligne}")

    def _streamdeck_diagnosis(self):
        faits = statut.collect(self._streamdeck_probe, RACINE)
        problemes = statut.diagnosis_lines(faits)
        if not problemes:
            print(f"✅ {t('Nothing to fix.')}")
            return
        for probleme, correction in problemes:
            print(f"❌ {probleme}")
            print(f"   → {correction}")

    def _streamdeck_service(self):
        if not self._streamdeck_unit_installed():
            return
        choix = self._streamdeck_choice(
            t("Service action:"),
            (
                ("start", "start"),
                ("stop", "stop"),
                ("restart", "restart"),
                ("log", t("live log (Ctrl-C to leave)")),
            ),
        )
        if choix is None:
            return
        if choix != "log":
            self._streamdeck_systemctl(choix, service.UNIT_NAME)
            return
        try:
            self.execute.exec_command_live(
                f"journalctl --user -u {service.UNIT_NAME} -f",
                source_erplibre=False,
            )
        except KeyboardInterrupt:
            print()

    def _streamdeck_program(self):
        """Réécrit DECK_PROGRAM, puis redémarre l'unité si elle tournait,
        pour qu'elle lance le nouveau programme."""
        if not self._streamdeck_unit_installed():
            return
        chemin = service.settings_path()
        actuel = service.read_settings(chemin)["DECK_PROGRAM"]
        defaut = "1"
        if actuel in service.PROGRAMS:
            defaut = str(service.PROGRAMS.index(actuel) + 1)
        choix = self._streamdeck_choice(
            f"{t('Deck program:')} {actuel}",
            [(p, p) for p in service.PROGRAMS],
            defaut,
        )
        if choix is None:
            return
        if not service.write_settings(chemin, {"DECK_PROGRAM": choix}):
            print(t("Unchanged."))
            return
        print(f"{t('Deck program:')} {choix}")
        code, _sortie = self._streamdeck_probe(statut.cmd_unit("is-active"))
        if code == 0:
            self._streamdeck_systemctl("restart", service.UNIT_NAME)

    def _streamdeck_autostart(self):
        if not self._streamdeck_unit_installed():
            return
        _code, sortie = self._streamdeck_probe(statut.cmd_unit("is-enabled"))
        choix = self._streamdeck_choice(
            f"{t('Autostart:')} {sortie.strip() or '?'}",
            (("enable", "enable"), ("disable", "disable")),
        )
        if choix is not None:
            self._streamdeck_systemctl(choix, service.UNIT_NAME)

    def _streamdeck_uninstall(self):
        options = self._streamdeck_choice(
            t("Uninstall what?"),
            (
                ("--uninstall --stream-deck", t("The Stream Deck level")),
                ("--uninstall", t("Everything, the extension too")),
            ),
        )
        if options is None:
            return
        commande = f"{INSTALLER} {options}"
        print(f"{t('Will execute:')} {commande}")
        if not self._is_yes(input(t("Confirm? (y/N): "))):
            return
        self._erplibre_home_run_installer(
            commande, succes="ERPLibre Home uninstalled."
        )

    def _streamdeck_extension(self):
        commande = self._streamdeck_choice(
            t("Extension action:"),
            (
                ("make erplibre_home_reload", t("Reload the extension")),
                (
                    f"gnome-extensions prefs {EXTENSION_UUID}",
                    t("Open its preferences"),
                ),
            ),
        )
        if commande is not None:
            self.execute.exec_command_live(commande, source_erplibre=False)

    # -------------------------------------------------------------- #
    # Questions de l'installation Stream Deck

    def _erplibre_home_streamdeck_options(self):
        """Les quatre questions de l'installation Stream Deck, chacune
        devenue une option de l'installateur. Le programme et la relance
        après un jeu passent toujours leur option, défaut compris : sans
        elle, l'installateur garderait la valeur déjà dans les réglages.
        Le démarrage automatique et les outils facultatifs n'ont pas
        d'option négative : « non » n'ajoute rien. Rend la liste des options
        dans l'ordre des questions, ou None quand la première est abandonnée
        par 0."""
        programme = self._streamdeck_choice(
            t("Deck program:"), [(p, p) for p in service.PROGRAMS]
        )
        if programme is None:
            return None
        options = [f"--deck-program={programme}"]
        if self._is_yes(input(t("Start the deck program at login? (y/N): "))):
            options.append("--autostart")
        if self._is_no(
            input(t("Restart the deck program after a game? (Y/n): "))
        ):
            options.append("--no-restart-after-game")
        else:
            options.append("--restart-after-game")
        if self._is_yes(
            input(t("Install the optional tools (--with-extras)? (y/N): "))
        ):
            options.append("--with-extras")
        return options
```

- [ ] **Step 4: Wire it into TODO**

In `script/todo/todo.py`:

Edit 1/7, replace:

```python
from script.todo.qemu_menu import QemuMenuMixin
from script.todo.qemu_network import QemuNetworkMixin
from script.todo.qemu_recover import QemuRecoverMixin
from script.todo.todo_i18n import get_lang, lang_is_configured, set_lang, t
from script.todo.transform_menu import TransformMenuMixin
from script.todo.version_manager import get_odoo_version
```

with:

```python
from script.todo.qemu_menu import QemuMenuMixin
from script.todo.qemu_network import QemuNetworkMixin
from script.todo.qemu_recover import QemuRecoverMixin
from script.todo.streamdeck_menu import StreamDeckMenuMixin
from script.todo.todo_i18n import get_lang, lang_is_configured, set_lang, t
from script.todo.transform_menu import TransformMenuMixin
from script.todo.version_manager import get_odoo_version
```

Edit 2/7, replace:

```python
    VpnMenuMixin,
    AssistantMenuMixin,
    ContainerMenuMixin,
):
    def __init__(self):
        self.dir_path = None
```

with:

```python
    VpnMenuMixin,
    AssistantMenuMixin,
    ContainerMenuMixin,
    StreamDeckMenuMixin,
):
    def __init__(self):
        self.dir_path = None
```

Edit 3/7, replace:

```python
[16] {t("Docker / Podman - Container engines")}

── {t("Stream Deck")} ──
[17] {t("Games - Stream Deck games")}
[18] {t("Install ERPLibre Home (local)")}
[19] {t("Install ERPLibre Home Stream Deck (local)")}
[0] {t("Back")}
"""
        while True:
```

with:

```python
[16] {t("Docker / Podman - Container engines")}

── {t("Stream Deck")} ──
[17] {t("Stream Deck - Games, service, status, install")}
[0] {t("Back")}
"""
        while True:
```

Edit 4/7, replace:

```python
                if status is not False:
                    return
            elif status == "17":
                status = self.prompt_execute_streamdeck_games()
                if status is not False:
                    return
            elif status == "18":
                status = self._erplibre_home_install_local()
                if status is not False:
                    return
            elif status == "19":
                status = self._erplibre_home_streamdeck_install_local()
                if status is not False:
                    return
            else:
```

with:

```python
                if status is not False:
                    return
            elif status == "17":
                status = self.prompt_execute_streamdeck()
                if status is not False:
                    return
            else:
```

Edit 5/7, replace:

```python
        "_container_service": "Service",
        "_container_compose": "Compose",
        "_container_erplibre": "ERPLibre container",
        "prompt_execute_streamdeck_games": "Stream Deck games",
        "prompt_execute_test": "Test",
        "prompt_execute_longtest": "Long test",
        "prompt_configuration": "Configuration",
```

with:

```python
        "_container_service": "Service",
        "_container_compose": "Compose",
        "_container_erplibre": "ERPLibre container",
        "prompt_execute_streamdeck": "Stream Deck",
        "prompt_execute_streamdeck_games": "Games",
        "prompt_execute_test": "Test",
        "prompt_execute_longtest": "Long test",
        "prompt_configuration": "Configuration",
```

Edit 6/7, replace:

```python
    def _erplibre_home_install_local(self):
        """Installer la base d'ERPLibre Home sur ce poste, sans Odoo :
        l'extension GNOME, ses schémas et ses traductions, activée. Rend
        False : le menu Exécution reste ouvert."""
        return self._erplibre_home_run_installer(self._ERPLIBRE_HOME_INSTALLER)

    def _erplibre_home_streamdeck_install_local(self):
        """Installer le niveau Stream Deck d'ERPLibre Home : la base au
        besoin, puis les paquets USB, la règle udev et .venv.streamdeck.
        Rend False : le menu Exécution reste ouvert."""
        return self._erplibre_home_run_installer(
            f"{self._ERPLIBRE_HOME_INSTALLER} --stream-deck"
        )

    def _erplibre_home_run_installer(self, commande):
        """Lance `commande`, l'installateur et ses options, et en résume
        l'issue sur une ligne.

        L'installateur tourne en direct et hors du venv ERPLibre : la base
        n'a pas de venv, et le niveau Stream Deck crée le sien,
```

with:

```python
    def _erplibre_home_install_local(self):
        """Installer la base d'ERPLibre Home sur ce poste, sans Odoo :
        l'extension GNOME, ses schémas et ses traductions, activée. Rend
        False : le menu reste ouvert."""
        return self._erplibre_home_run_installer(self._ERPLIBRE_HOME_INSTALLER)

    def _erplibre_home_streamdeck_install_local(self):
        """Installer le niveau Stream Deck d'ERPLibre Home : la base au
        besoin, puis les paquets USB, la règle udev, .venv.streamdeck et le
        service du deck. Les quatre questions du service deviennent des
        options, et la commande s'affiche avant de partir. Rend False : le
        menu reste ouvert."""
        options = self._erplibre_home_streamdeck_options()
        if options is None:
            return False
        commande = " ".join(
            [self._ERPLIBRE_HOME_INSTALLER, "--stream-deck", *options]
        )
        print(f"{t('Will execute:')} {commande}")
        return self._erplibre_home_run_installer(commande)

    def _erplibre_home_run_installer(
        self,
        commande,
        succes=(
            "ERPLibre Home installed. Log out and back in to load the"
            " extension."
        ),
    ):
        """Lance `commande`, l'installateur et ses options, et en résume
        l'issue sur une ligne ; `succes` est la clé de traduction de la
        ligne d'un code 0.

        L'installateur tourne en direct et hors du venv ERPLibre : la base
        n'a pas de venv, et le niveau Stream Deck crée le sien,
```

Edit 7/7, replace:

```python
                + t("ERPLibre Home installation failed, see the output above.")
            )
        else:
            print(
                "✅ "
                + t(
                    "ERPLibre Home installed. Log out and back in to load"
                    " the extension."
                )
            )
        return False

    # ---------------------------------------------------------------- #
```

with:

```python
                + t("ERPLibre Home installation failed, see the output above.")
            )
        else:
            print("✅ " + t(succes))
        return False

    # ---------------------------------------------------------------- #
```

- [ ] **Step 5: Add the translations**

In `script/todo/todo_i18n.py` (`"Choice: "`, `"Confirm? (y/N): "`, `"Will execute:"`, `"Back"` and the existing install keys are reused):

Edit 1/1, replace:

```python
            "ERPLibre Home installed. Log out and back in to load"
            " the extension."
        ),
    },
    # Stream Deck: status and diagnosis (script/todo/erplibre_home_status.py)
    "Level: not installed": {
```

with:

```python
            "ERPLibre Home installed. Log out and back in to load"
            " the extension."
        ),
    },
    # Stream Deck submenu (script/todo/streamdeck_menu.py)
    "Stream Deck - Games, service, status, install": {
        "fr": "🎛️ Stream Deck - Jeux, service, état, installation",
        "en": "🎛️ Stream Deck - Games, service, status, install",
    },
    "Status - What is installed and what runs": {
        "fr": "📋 État - Ce qui est installé et ce qui tourne",
        "en": "📋 Status - What is installed and what runs",
    },
    "Service - Start, stop, restart, live log": {
        "fr": "⚙️ Service - Démarrer, arrêter, redémarrer, journal en direct",
        "en": "⚙️ Service - Start, stop, restart, live log",
    },
    "Deck program - Tiler, controller or none": {
        "fr": "🎛️ Programme du deck - Tiler, contrôleur ou aucun",
        "en": "🎛️ Deck program - Tiler, controller or none",
    },
    "Autostart - Enable or disable": {
        "fr": "🚀 Démarrage auto - Activer ou désactiver",
        "en": "🚀 Autostart - Enable or disable",
    },
    "Diagnosis - What is wrong and how to fix it": {
        "fr": "🩺 Diagnostic - Ce qui ne va pas et comment le corriger",
        "en": "🩺 Diagnosis - What is wrong and how to fix it",
    },
    "Uninstall - Stream Deck level or everything": {
        "fr": "🗑 Désinstaller - Niveau Stream Deck ou tout",
        "en": "🗑 Uninstall - Stream Deck level or everything",
    },
    "Extension - Reload or preferences": {
        "fr": "🧩 Extension - Recharger ou préférences",
        "en": "🧩 Extension - Reload or preferences",
    },
    "The Stream Deck service is not installed:"
    " make erplibre_home_streamdeck_install": {
        "fr": "Le service Stream Deck n'est pas installé :"
        " make erplibre_home_streamdeck_install",
        "en": "The Stream Deck service is not installed:"
        " make erplibre_home_streamdeck_install",
    },
    "Nothing to fix.": {
        "fr": "Rien à corriger.",
        "en": "Nothing to fix.",
    },
    "Service action:": {
        "fr": "Action sur le service :",
        "en": "Service action:",
    },
    "live log (Ctrl-C to leave)": {
        "fr": "journal en direct (Ctrl-C pour sortir)",
        "en": "live log (Ctrl-C to leave)",
    },
    "Deck program:": {
        "fr": "Programme du deck :",
        "en": "Deck program:",
    },
    "Unchanged.": {
        "fr": "Inchangé.",
        "en": "Unchanged.",
    },
    "Autostart:": {
        "fr": "Démarrage auto :",
        "en": "Autostart:",
    },
    "Uninstall what?": {
        "fr": "Désinstaller quoi ?",
        "en": "Uninstall what?",
    },
    "The Stream Deck level": {
        "fr": "Le niveau Stream Deck",
        "en": "The Stream Deck level",
    },
    "Everything, the extension too": {
        "fr": "Tout, l'extension aussi",
        "en": "Everything, the extension too",
    },
    "ERPLibre Home uninstalled.": {
        "fr": "ERPLibre Home désinstallé.",
        "en": "ERPLibre Home uninstalled.",
    },
    "Extension action:": {
        "fr": "Action sur l'extension :",
        "en": "Extension action:",
    },
    "Reload the extension": {
        "fr": "Recharger l'extension",
        "en": "Reload the extension",
    },
    "Open its preferences": {
        "fr": "Ouvrir ses préférences",
        "en": "Open its preferences",
    },
    "Start the deck program at login? (y/N): ": {
        "fr": "Démarrer le programme du deck à l'ouverture de session ?"
        " (o/N) : ",
        "en": "Start the deck program at login? (y/N): ",
    },
    "Restart the deck program after a game? (Y/n): ": {
        "fr": "Relancer le programme du deck après un jeu ? (O/n) : ",
        "en": "Restart the deck program after a game? (Y/n): ",
    },
    "Install the optional tools (--with-extras)? (y/N): ": {
        "fr": "Installer les outils facultatifs (--with-extras) ? (o/N) : ",
        "en": "Install the optional tools (--with-extras)? (y/N): ",
    },
    # Stream Deck: status and diagnosis (script/todo/erplibre_home_status.py)
    "Level: not installed": {
```

- [ ] **Step 6: Run the tests to verify they pass**

Run: `.venv.erplibre/bin/python -m unittest test.test_todo_streamdeck_menu test.test_todo_menu test.test_todo_erplibre_home_install test.test_todo_i18n test.test_streamdeck_entry_points`
Expected: `Ran 127 tests`, `OK` (14 + 60 + 6 + 24 + 23).

- [ ] **Step 7: Document the menu**

In `script/stream_deck/INSTALL.base.md`:

Edit 1/1, replace:

````markdown
```

<!-- [end] -->

<!-- [en] -->
## mpv film launcher — yt-dlp backend
````

with:

````markdown
```

<!-- [end] -->
<!-- [en] -->
TODO's **Execute › Stream Deck** menu gathers the games, both local
installs, the service, the deck program, autostart, a status view, a
diagnosis that names the command fixing each problem, both uninstalls, and
the extension's reload and preferences. Its Stream Deck install asks for
the program, autostart, the restart after a game and the optional tools,
then prints the installer command before running it.

<!-- [fr] -->
Le menu **Exécution › Stream Deck** de TODO réunit les jeux, les deux
installations locales, le service, le programme du deck, le démarrage
automatique, un état, un diagnostic qui nomme la commande corrigeant chaque
problème, les deux désinstallations, et le rechargement et les préférences
de l'extension. Son installation Stream Deck demande le programme, le
démarrage automatique, la relance après un jeu et les outils facultatifs,
puis affiche la commande de l'installateur avant de la lancer.

<!-- [end] -->

<!-- [en] -->
## mpv film launcher — yt-dlp backend
````

Run: `source .venv.erplibre/bin/activate && mmg --yes script/stream_deck/INSTALL.base.md`
Expected: `1 base file has been converted.`

- [ ] **Step 8: Format and comment hygiene**

Run: `.venv.erplibre/bin/black -l 79 --check script/todo/streamdeck_menu.py test/test_todo_streamdeck_menu.py test/test_todo_menu.py test/test_todo_erplibre_home_install.py && python3 script/analyse/check_comment_hygiene.py script/todo/streamdeck_menu.py script/todo/todo.py test/test_todo_streamdeck_menu.py`
Expected: `4 files would be left unchanged.` and no hygiene line.

- [ ] **Step 9: Commit**

Write `"$SCRATCH/msg-6.txt"`:

```text
[ADD] todo: Stream Deck submenu for games, installs, service, status

Execute's three Stream Deck entries become one submenu with ten:
games, status, service actions and live log, deck program, autostart,
diagnosis, both local installs, uninstall and the extension. The
Stream Deck install asks for the program, autostart, the restart after
a game and the optional tools, turns each answer into an option, the
program and the restart always explicit, and prints the command before
running it. Changing the program restarts the unit only when it was
active.

--- FR ---
[ADD] todo : sous-menu Stream Deck, jeux, installations, service, état

Les trois entrées Stream Deck d'Exécution deviennent un sous-menu de
dix : jeux, état, actions et journal du service, programme du deck,
démarrage automatique, diagnostic, les deux installations locales,
désinstallation et extension. L'installation Stream Deck demande le
programme, le démarrage automatique, la relance après un jeu et les
outils facultatifs, en fait des options, programme et relance toujours
explicites, et affiche la commande avant de la lancer. Changer le
programme ne redémarre l'unité que si elle tournait.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-6.txt"
git add script/todo/streamdeck_menu.py script/todo/todo.py script/todo/todo_i18n.py test/test_todo_streamdeck_menu.py test/test_todo_menu.py test/test_todo_erplibre_home_install.py script/stream_deck/INSTALL.base.md script/stream_deck/INSTALL.md script/stream_deck/INSTALL.fr.md
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-6.txt"
```

---

### Task 7: Device indicator drives the unit

**Files:**
- Create: `script/gnome-extension/erplibre_home/lib/deck-service.js`
- Modify: `script/gnome-extension/erplibre_home/indicators/device.js` (imports lines 14-16, `CONTROLLER_REL` line 24, `_launchController` and `_restart` lines 157-185)
- Test: `script/gnome-extension/erplibre_home/test/unit/deck-service.test.js`

**Interfaces:**
- Consumes: Task 4's unit name and path (`<config>/systemd/user/erplibre-home-streamdeck.service`); the existing `streamDeckPython(root, fileExists)` of `lib/project-root.js`.
- Produces (`lib/deck-service.js`, pure ES module): `DECK_UNIT`, `CONTROLLER_REL = 'script/stream_deck/erplibre_controller.py'`, `deckUnitPath(configDir) -> string`, `openDeckArgv({unitExists, python, root}) -> string[] | null`, `restartDeckArgv({unitExists}) -> string[] | null`.

- [ ] **Step 1: Write the failing test**

Create `script/gnome-extension/erplibre_home/test/unit/deck-service.test.js`:

```javascript
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {DECK_UNIT, CONTROLLER_REL, deckUnitPath, openDeckArgv,
    restartDeckArgv} from '../../lib/deck-service.js';

const ROOT = '/opt/mon depot';
const PYTHON = `${ROOT}/.venv.streamdeck/bin/python`;

function extensionFile(rel) {
    return readFileSync(new URL(`../../${rel}`, import.meta.url), 'utf8');
}

test('the unit name and path are those the installer writes', () => {
    assert.equal(DECK_UNIT, 'erplibre-home-streamdeck.service');
    assert.equal(deckUnitPath('/opt/maison/.config'),
        '/opt/maison/.config/systemd/user/erplibre-home-streamdeck.service');
});

test('with the unit, open starts the unit whatever the venv', () => {
    for (const python of [PYTHON, null]) {
        assert.deepEqual(
            openDeckArgv({unitExists: true, python, root: ROOT}),
            ['systemctl', '--user', 'start', DECK_UNIT]);
    }
});

test('without the unit, open runs the controller under the venv', () => {
    assert.deepEqual(
        openDeckArgv({unitExists: false, python: PYTHON, root: `${ROOT}/`}),
        [PYTHON, `${ROOT}/${CONTROLLER_REL}`]);
});

test('without the unit nor the venv, open gives null', () => {
    assert.equal(openDeckArgv({unitExists: false, python: null, root: ROOT}),
        null);
});

test('restart goes through the unit only when it exists', () => {
    assert.deepEqual(restartDeckArgv({unitExists: true}),
        ['systemctl', '--user', 'restart', DECK_UNIT]);
    assert.equal(restartDeckArgv({unitExists: false}), null);
});

test('the device indicator takes both argv from this module', () => {
    const src = extensionFile('indicators/device.js');
    assert.ok(src.includes("from '../lib/deck-service.js'"));
    assert.ok(src.includes('openDeckArgv('));
    assert.ok(src.includes('restartDeckArgv('));
    assert.ok(src.includes('deckUnitPath(GLib.get_user_config_dir())'));
    assert.ok(!src.includes("const CONTROLLER_REL"));
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `node --test script/gnome-extension/erplibre_home/test/unit/*.test.js 2>&1 | grep -E '^ℹ (tests|pass|fail)'`
Expected: `tests 243`, `pass 242`, `fail 1` — `ERR_MODULE_NOT_FOUND` for `lib/deck-service.js`.

- [ ] **Step 3: Write the pure module**

Create `script/gnome-extension/erplibre_home/lib/deck-service.js`:

```javascript
/**
 * What the device indicator runs to open or restart the deck program.
 *
 * With the Stream Deck level, the installer writes the systemd --user unit
 * erplibre-home-streamdeck.service, which runs the program chosen in
 * ~/.config/erplibre-home/streamdeck.conf. When that unit file exists the
 * indicator drives the unit, so the service and the indicator never start
 * two programs on one deck; without it (a manual setup) the indicator
 * starts the controller itself under the deck venv.
 *
 * Pure: the caller says whether the unit file exists and passes the venv
 * python, so node --test loads this module without any gi:// import.
 */

export const DECK_UNIT = 'erplibre-home-streamdeck.service';

// Controller script, relative to the checkout root.
export const CONTROLLER_REL = 'script/stream_deck/erplibre_controller.py';

/**
 * Path of the unit file under `configDir`, the user configuration
 * directory ($XDG_CONFIG_HOME, or ~/.config).
 */
export function deckUnitPath(configDir) {
    return `${configDir}/systemd/user/${DECK_UNIT}`;
}

/**
 * argv that opens the deck program: `systemctl --user start` on the unit
 * when `unitExists`, else the controller of `root` under `python`. null
 * when there is no unit and `python` is null (the deck venv is missing):
 * the caller then says the Stream Deck level is not installed.
 */
export function openDeckArgv({unitExists, python, root}) {
    if (unitExists)
        return ['systemctl', '--user', 'start', DECK_UNIT];
    if (python === null || python === undefined)
        return null;
    const base = root.length > 1 ? root.replace(/\/+$/, '') : root;
    return [python, `${base}/${CONTROLLER_REL}`];
}

/**
 * argv that restarts the deck program through the unit, or null when the
 * unit file does not exist: the caller then stops the controller by its
 * pidfile and opens it again.
 */
export function restartDeckArgv({unitExists}) {
    return unitExists ? ['systemctl', '--user', 'restart', DECK_UNIT] : null;
}
```

- [ ] **Step 4: Use it in the device indicator**

In `script/gnome-extension/erplibre_home/indicators/device.js`:

Edit 1/4, replace:

```javascript
    formatBadgeTooltip} from '../lib/badges.js';
import {projectRootFrom, makeGioReadLink, streamDeckPython}
    from '../lib/project-root.js';
import {_} from '../lib/i18n.js';

function _notify(title, body) {
```

with:

```javascript
    formatBadgeTooltip} from '../lib/badges.js';
import {projectRootFrom, makeGioReadLink, streamDeckPython}
    from '../lib/project-root.js';
import {deckUnitPath, openDeckArgv, restartDeckArgv}
    from '../lib/deck-service.js';
import {_} from '../lib/i18n.js';

function _notify(title, body) {
```

Edit 2/4, replace:

```javascript
}

const PIDFILE = `${GLib.get_user_cache_dir()}/erplibre-home/controller.pid`;
const CONTROLLER_REL = 'script/stream_deck/erplibre_controller.py';

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);
```

with:

```javascript
}

const PIDFILE = `${GLib.get_user_cache_dir()}/erplibre-home/controller.pid`;

// See indicators/controller.js for the rationale of the random suffix.
const _GTYPE_SUFFIX = Math.floor(Math.random() * 1e9).toString(36);
```

Edit 3/4, replace:

```javascript
        return projectRootFrom(this._extension.path, makeGioReadLink(Gio));
    }

    _launchController() {
        const root = this._projectRoot();
        // .venv.streamdeck exists only once the Stream Deck level is
```

with:

```javascript
        return projectRootFrom(this._extension.path, makeGioReadLink(Gio));
    }

    // The deck service unit, looked up at the click like the venv below.
    _deckUnitExists() {
        return GLib.file_test(deckUnitPath(GLib.get_user_config_dir()),
            GLib.FileTest.EXISTS);
    }

    _launchController() {
        const root = this._projectRoot();
        // .venv.streamdeck exists only once the Stream Deck level is
```

Edit 4/4, replace:

```javascript
        // level added after the session started is found.
        const py = streamDeckPython(root,
            (p) => GLib.file_test(p, GLib.FileTest.IS_EXECUTABLE));
        if (py === null) {
            _notify('Stream Deck',
                _('ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install'));
            return;
        }
        spawnDetached([py, `${root}/${CONTROLLER_REL}`],
            {notify: _notify, title: 'Stream Deck'});
    }

    _restart() {
        if (GLib.file_test(PIDFILE, GLib.FileTest.EXISTS)) {
            try {
                const [ok, contents] = GLib.file_get_contents(PIDFILE);
```

with:

```javascript
        // level added after the session started is found.
        const py = streamDeckPython(root,
            (p) => GLib.file_test(p, GLib.FileTest.IS_EXECUTABLE));
        const argv = openDeckArgv(
            {unitExists: this._deckUnitExists(), python: py, root});
        if (argv === null) {
            _notify('Stream Deck',
                _('ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install'));
            return;
        }
        spawnDetached(argv, {notify: _notify, title: 'Stream Deck'});
    }

    _restart() {
        // With the unit, systemd stops the program it runs and starts the
        // one the settings name; the pidfile is the controller's own.
        const viaUnit = restartDeckArgv({unitExists: this._deckUnitExists()});
        if (viaUnit !== null) {
            spawnDetached(viaUnit, {notify: _notify, title: 'Stream Deck'});
            return;
        }
        if (GLib.file_test(PIDFILE, GLib.FileTest.EXISTS)) {
            try {
                const [ok, contents] = GLib.file_get_contents(PIDFILE);
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `node --test script/gnome-extension/erplibre_home/test/unit/*.test.js 2>&1 | grep -E '^ℹ (tests|pass|fail)' && node --input-type=module --check < script/gnome-extension/erplibre_home/indicators/device.js && echo parse-ok`
Expected: `tests 248`, `pass 248`, `fail 0`, then `parse-ok`.

- [ ] **Step 6: Comment hygiene**

Run: `python3 script/analyse/check_comment_hygiene.py script/gnome-extension/erplibre_home/lib/deck-service.js script/gnome-extension/erplibre_home/indicators/device.js script/gnome-extension/erplibre_home/test/unit/deck-service.test.js`
Expected: no line.

- [ ] **Step 7: Commit**

Write `"$SCRATCH/msg-7.txt"`:

```text
[IMP] erplibre_home: device indicator drives the deck service unit

Opening the controller from the device indicator while the service
runs would start a second program on the same deck. When the unit file
exists, "Open controller UI" now runs systemctl --user start and
"Restart deck" systemctl --user restart; without it, the indicator
keeps its direct launch under the deck venv and its pidfile restart.
The choice lives in lib/deck-service.js, pure and covered by node
--test.

--- FR ---
[IMP] erplibre_home : l'indicateur device pilote l'unité du service

Ouvrir le contrôleur depuis l'indicateur device pendant que le service
tourne lancerait un second programme sur le même deck. Quand le fichier
d'unité existe, « Open controller UI » lance systemctl --user start et
« Restart deck » systemctl --user restart ; sans lui, l'indicateur garde
son lancement direct sous le venv du deck et son redémarrage par
pidfile. Le choix vit dans lib/deck-service.js, pur et couvert par node
--test.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-7.txt"
git add script/gnome-extension/erplibre_home/lib/deck-service.js script/gnome-extension/erplibre_home/indicators/device.js script/gnome-extension/erplibre_home/test/unit/deck-service.test.js
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-7.txt"
```

---

### Task 8: Long test checks the service

**Files:**
- Modify: `long_test/install_erplibre_home.py` (docstring line 14, commands lines 215-218, `ETAPES` lines 255-290, new helpers before `journal_lu` line 426, `_etape_stream_deck` line 1208, `_etape_retrait_partiel` line 1228, `_etape_retrait` line 1251)
- Modify: `long_test/README.base.md` (stage list, English near line 276, French near line 626); regenerate `README.md`, `README.fr.md`
- Test: `test/test_longtest_install_erplibre_home.py`

**Interfaces:**
- Consumes: Task 4's installer options `--deck-program=tiler --autostart`, the unit's `ExecStart` line, unit and settings paths; Task 1's `--check` (a VM has no deck).
- Produces (`long_test/install_erplibre_home.py`): `UNITE_DECK`, `FICHIER_UNITE`, `REGLAGES_DECK`, `SYSTEMD_USER`, `CMD_UNITE`, `CMD_AUTOSTART`, `CMD_CONDITION`, `CMD_SANS_SERVICE`; `etat_systemd(sortie) -> dict`; `condition_sautee(etat) -> bool`. Stage 2 option `--stream-deck --deck-program=tiler --autostart`; new check names `service-unit`, `service-enabled`, `service-condition`, `partial-uninstall-service-gone`, `uninstall-service-gone`.

- [ ] **Step 1: Write the failing tests**

In `test/test_longtest_install_erplibre_home.py`:

Edit 1/13, replace:

```python
            [(e["nom"], e["commande"], e["option"]) for e in sd.ETAPES],
            [
                ("base", None, None),
                ("stream-deck", "install-stream-deck", "--stream-deck"),
                (
                    "partial-uninstall",
                    "uninstall-stream-deck",
```

with:

```python
            [(e["nom"], e["commande"], e["option"]) for e in sd.ETAPES],
            [
                ("base", None, None),
                (
                    "stream-deck",
                    "install-stream-deck",
                    "--stream-deck --deck-program=tiler --autostart",
                ),
                (
                    "partial-uninstall",
                    "uninstall-stream-deck",
```

Edit 2/13, replace:

```python
                [
                    "udev",
                    "venv",
                    "stream-deck-active",
                    "stream-deck-idempotent",
                ],
                ["partial-uninstall-gone", "partial-uninstall-kept"],
                ["uninstall-gone"],
                [
                    "reinstall-active",
                    "reinstall-indicators",
```

with:

```python
                [
                    "udev",
                    "venv",
                    "service-unit",
                    "service-enabled",
                    "service-condition",
                    "stream-deck-active",
                    "stream-deck-idempotent",
                ],
                [
                    "partial-uninstall-gone",
                    "partial-uninstall-service-gone",
                    "partial-uninstall-kept",
                ],
                ["uninstall-gone", "uninstall-service-gone"],
                [
                    "reinstall-active",
                    "reinstall-indicators",
```

Edit 3/13, replace:

```python
            with self.subTest(commande=commande):
                self.assertTrue(commande.endswith("&& echo ok"))
        self.assertIn("/run/user/$(id -u)/bus", sd.CMD_ENABLED)

    def test_the_enabled_list_is_read(self):
        self.assertEqual(sd.liste_extensions("@as []"), [])
```

with:

```python
            with self.subTest(commande=commande):
                self.assertTrue(commande.endswith("&& echo ok"))
        self.assertIn("/run/user/$(id -u)/bus", sd.CMD_ENABLED)

    def test_the_service_checks_name_the_unit_and_the_checkout(self):
        self.assertIn(sd.FICHIER_UNITE, sd.CMD_UNITE)
        self.assertIn(
            '"ExecStart=\\"$HOME/git/erplibre/script/install/'
            'erplibre_home_deck.sh\\""',
            sd.CMD_UNITE,
        )
        for commande in (sd.CMD_AUTOSTART, sd.CMD_CONDITION):
            with self.subTest(commande=commande):
                self.assertIn("XDG_RUNTIME_DIR=/run/user/$(id -u)", commande)
                self.assertIn("/run/user/$(id -u)/bus", commande)
                self.assertIn(sd.UNITE_DECK, commande)
        self.assertIn(sd.FICHIER_UNITE, sd.CMD_SANS_SERVICE)
        self.assertIn(sd.REGLAGES_DECK, sd.CMD_SANS_SERVICE)
        self.assertTrue(sd.CMD_SANS_SERVICE.endswith("&& echo ok"))
        # La seconde installation de l'étape 2 ne touche ni à l'unité ni
        # aux réglages.
        self.assertIn(sd.FICHIER_UNITE, sd.CMD_MTIMES)
        self.assertIn(sd.REGLAGES_DECK, sd.CMD_MTIMES)

    def test_the_systemctl_show_lines_are_read_in_any_order(self):
        for sortie in (
            "ActiveState=inactive\nResult=exec-condition\n",
            "Result=exec-condition\nActiveState=inactive",
        ):
            with self.subTest(sortie=sortie):
                self.assertTrue(sd.condition_sautee(sd.etat_systemd(sortie)))
        for sortie in (
            "ActiveState=active\nResult=success\n",
            "ActiveState=failed\nResult=exit-code\n",
            "ActiveState=inactive\nResult=success\n",
            "",
            None,
        ):
            with self.subTest(sortie=sortie):
                self.assertFalse(sd.condition_sautee(sd.etat_systemd(sortie)))

    def test_the_enabled_list_is_read(self):
        self.assertEqual(sd.liste_extensions("@as []"), [])
```

Edit 4/13, replace:

```python
    """

    def __init__(self, journaux, echoue=(), apres=None, **etat):
        self.regle = self.venv = False
        self.lien = self.uuid = self.actif = True
        self.__dict__.update(etat)
        self.journaux = list(journaux)
        self.echoue = set(echoue)
```

with:

```python
    """

    def __init__(self, journaux, echoue=(), apres=None, **etat):
        self.regle = self.venv = self.service = self.autostart = False
        self.lien = self.uuid = self.actif = True
        # Sans deck, systemd saute le démarrage du service.
        self.condition = True
        self.__dict__.update(etat)
        self.journaux = list(journaux)
        self.echoue = set(echoue)
```

Edit 5/13, replace:

```python
        if options in self.echoue:
            return 1, ""
        if options == "--uninstall --stream-deck":
            self.regle = self.venv = False
        elif options == "--uninstall":
            self.regle = self.venv = self.lien = self.uuid = False
        else:
            self.lien = self.uuid = True
            if "--stream-deck" in options:
                self.regle = self.venv = True
        self.__dict__.update(self.apres.get(options, {}))
        return 0, ""

```

with:

```python
        if options in self.echoue:
            return 1, ""
        if options == "--uninstall --stream-deck":
            self.regle = self.venv = self.service = self.autostart = False
        elif options == "--uninstall":
            self.regle = self.venv = self.lien = self.uuid = False
            self.service = self.autostart = False
        else:
            self.lien = self.uuid = True
            if "--stream-deck" in options:
                self.regle = self.venv = self.service = True
                self.autostart = "--autostart" in options
        self.__dict__.update(self.apres.get(options, {}))
        return 0, ""

```

Edit 6/13, replace:

```python
            ),
            sd.CMD_MTIMES: "dates du deck",
            sd.CMD_MTIME_LIEN: "date du lien",
        }
        # Le reste : ListPaths et ListDevices.
        return reponses.get(commande, "('[]',)")
```

with:

```python
            ),
            sd.CMD_MTIMES: "dates du deck",
            sd.CMD_MTIME_LIEN: "date du lien",
            sd.CMD_UNITE: "ok" if self.service else "",
            sd.CMD_AUTOSTART: "enabled" if self.autostart else "disabled",
            sd.CMD_CONDITION: (
                "ActiveState=inactive\nResult=exec-condition"
                if self.condition
                else "ActiveState=failed\nResult=exit-code"
            ),
            sd.CMD_SANS_SERVICE: "" if self.service else "ok",
        }
        # Le reste : ListPaths et ListDevices.
        return reponses.get(commande, "('[]',)")
```

Edit 7/13, replace:

```python
        self.redemarrages += 1
        self.__dict__.update(self.apres.get("redemarrage", {}))
        return True


class LesCinqEtapes(unittest.TestCase):
```

with:

```python
        self.redemarrages += 1
        self.__dict__.update(self.apres.get("redemarrage", {}))
        return True


# L'option de l'installateur à l'étape 2.
DECK = sd.OPTION["install-stream-deck"]


class LesCinqEtapes(unittest.TestCase):
```

Edit 8/13, replace:

```python
        self.assertEqual(gnome, "46.0")
        self.assertEqual(
            vm.options,
            [
                "",
                "--stream-deck",
                "--stream-deck",
                "--uninstall --stream-deck",
                "--uninstall",
                "",
            ],
        )
        self.assertEqual((vm.lectures, vm.redemarrages), (2, 1))

```

with:

```python
        self.assertEqual(gnome, "46.0")
        self.assertEqual(
            vm.options,
            ["", DECK, DECK, "--uninstall --stream-deck", "--uninstall", ""],
        )
        self.assertEqual((vm.lectures, vm.redemarrages), (2, 1))

```

Edit 9/13, replace:

```python
    def test_a_failed_command_names_its_stage(self):
        for option, attendu in (
            ("", "base-idempotent"),
            ("--stream-deck", "install-stream-deck"),
            ("--uninstall --stream-deck", "uninstall-stream-deck"),
            ("--uninstall", "uninstall"),
        ):
```

with:

```python
    def test_a_failed_command_names_its_stage(self):
        for option, attendu in (
            ("", "base-idempotent"),
            (DECK, "install-stream-deck"),
            ("--uninstall --stream-deck", "uninstall-stream-deck"),
            ("--uninstall", "uninstall"),
        ):
```

Edit 10/13, replace:

```python
                self.assertEqual(self._controler(vm)[0], attendu)
                self.assertEqual(vm.options[-1], option)

    def test_the_stream_deck_stage_checks_rule_venv_and_extension(self):
        for apres, attendu in (
            ({"regle": False}, "udev"),
            ({"venv": False}, "venv"),
            ({"actif": False}, "stream-deck-active"),
        ):
            with self.subTest(attendu=attendu):
                vm = VMSimulee([self.ENTIER], apres={"--stream-deck": apres})
                self.assertEqual(self._controler(vm)[0], attendu)

    def test_the_partial_uninstall_keeps_the_extension(self):
        for apres, attendu in (
            ({"venv": True}, "partial-uninstall-gone"),
            ({"regle": True}, "partial-uninstall-gone"),
            ({"lien": False}, "partial-uninstall-kept"),
            ({"uuid": False}, "partial-uninstall-kept"),
            ({"actif": False}, "partial-uninstall-kept"),
```

with:

```python
                self.assertEqual(self._controler(vm)[0], attendu)
                self.assertEqual(vm.options[-1], option)

    def test_the_stream_deck_stage_checks_rule_venv_service_extension(self):
        for apres, attendu in (
            ({"regle": False}, "udev"),
            ({"venv": False}, "venv"),
            ({"service": False}, "service-unit"),
            ({"autostart": False}, "service-enabled"),
            ({"condition": False}, "service-condition"),
            ({"actif": False}, "stream-deck-active"),
        ):
            with self.subTest(attendu=attendu):
                vm = VMSimulee([self.ENTIER], apres={DECK: apres})
                self.assertEqual(self._controler(vm)[0], attendu)

    def test_the_partial_uninstall_keeps_the_extension(self):
        for apres, attendu in (
            ({"venv": True}, "partial-uninstall-gone"),
            ({"regle": True}, "partial-uninstall-gone"),
            ({"service": True}, "partial-uninstall-service-gone"),
            ({"lien": False}, "partial-uninstall-kept"),
            ({"uuid": False}, "partial-uninstall-kept"),
            ({"actif": False}, "partial-uninstall-kept"),
```

Edit 11/13, replace:

```python
            with self.subTest(apres=apres):
                vm = VMSimulee([self.ENTIER], apres={"--uninstall": apres})
                self.assertEqual(self._controler(vm)[0], "uninstall-gone")

    def test_the_reinstall_comes_back_whole_and_without_the_deck(self):
        cas = (
```

with:

```python
            with self.subTest(apres=apres):
                vm = VMSimulee([self.ENTIER], apres={"--uninstall": apres})
                self.assertEqual(self._controler(vm)[0], "uninstall-gone")
        vm = VMSimulee([self.ENTIER], apres={"--uninstall": {"service": True}})
        self.assertEqual(self._controler(vm)[0], "uninstall-service-gone")

    def test_the_reinstall_comes_back_whole_and_without_the_deck(self):
        cas = (
```

Edit 12/13, replace:

```python
        for bloc in journal.split("── contrôle ")[1:]:
            self.assertIn("\n   $ ", bloc, bloc)
        self.assertIn(f"   $ {sd.CMD_SANS_REGLE}\n", journal)
        self.assertIn("   $ install_erplibre_home.sh --stream-deck\n", journal)
        self.assertNotIn("   → ", journal)

    def test_a_failed_check_leaves_its_raw_reply(self):
```

with:

```python
        for bloc in journal.split("── contrôle ")[1:]:
            self.assertIn("\n   $ ", bloc, bloc)
        self.assertIn(f"   $ {sd.CMD_SANS_REGLE}\n", journal)
        self.assertIn(f"   $ install_erplibre_home.sh {DECK}\n", journal)
        self.assertNotIn("   → ", journal)

    def test_a_failed_check_leaves_its_raw_reply(self):
```

Edit 13/13, replace:

```python
                f"   $ {sd.CMD_ENABLED}\n   → @as []\n",
            ),
            (
                {"echoue": {"--stream-deck"}},
                "install-stream-deck",
                "   $ install_erplibre_home.sh --stream-deck\n"
                "   → code de sortie 1\n",
            ),
            (
                {"regle": True},
```

with:

```python
                f"   $ {sd.CMD_ENABLED}\n   → @as []\n",
            ),
            (
                {"echoue": {DECK}},
                "install-stream-deck",
                f"   $ install_erplibre_home.sh {DECK}\n"
                "   → code de sortie 1\n",
            ),
            (
                {"apres": {DECK: {"condition": False}}},
                "service-condition",
                f"   $ {sd.CMD_CONDITION}\n"
                "   → ActiveState=failed\nResult=exit-code\n",
            ),
            (
                {"regle": True},
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_longtest_install_erplibre_home`
Expected: `Ran 116 tests`, `FAILED (failures=2, errors=39)` — `KeyError`/`AttributeError` on `sd.CMD_UNITE`, `sd.etat_systemd`, and the stage table still has the old option and checks.

- [ ] **Step 3: Add the service checks**

In `long_test/install_erplibre_home.py`:

Edit 1/8, replace:

```python
y reste listée, en ERREUR.

Sur la même VM passent ensuite cinq étapes (ETAPES) : la base, l'ajout du
niveau Stream Deck, son retrait seul, le retrait de tout, puis la base de
nouveau. Chacune lance une commande de l'installateur et ses contrôles ; le
premier échec arrête la VM et nomme la commande ou le contrôle.

Il vit dans long_test/ et non dans test/ : il crée de vraies machines et
```

with:

```python
y reste listée, en ERREUR.

Sur la même VM passent ensuite cinq étapes (ETAPES) : la base, l'ajout du
niveau Stream Deck avec son service, son retrait seul, le retrait de tout,
puis la base de nouveau. Chacune lance une commande de l'installateur et ses contrôles ; le
premier échec arrête la VM et nomme la commande ou le contrôle.

Il vit dans long_test/ et non dans test/ : il crée de vraies machines et
```

Edit 2/8, replace:

```python
CMD_SANS_LIEN = (
    f"test ! -e {LIEN_EXTENSION} && test ! -L {LIEN_EXTENSION} && echo ok"
)
# « stat » sans « -L » lit le lien lui-même : c'est la date du LIEN que
# l'installateur ne doit pas réécrire, pas celle du dossier qu'il désigne.
CMD_MTIME_LIEN = f"stat -c '%n %Y' {LIEN_EXTENSION}"
CMD_MTIMES = f"stat -c '%n %Y' {REGLE_UDEV} {VENV_DECK} {LIEN_EXTENSION}"
CMD_JOURNAL = (
    "journalctl --user -b --no-pager 2>&1"
    " | grep -i -e erplibrehome -e erplibre-home -e gnome-shell"
```

with:

```python
CMD_SANS_LIEN = (
    f"test ! -e {LIEN_EXTENSION} && test ! -L {LIEN_EXTENSION} && echo ok"
)
# Le service du deck que pose le niveau Stream Deck, et ses réglages.
UNITE_DECK = "erplibre-home-streamdeck.service"
FICHIER_UNITE = f"~/.config/systemd/user/{UNITE_DECK}"
REGLAGES_DECK = "~/.config/erplibre-home/streamdeck.conf"
# systemctl --user par ssh : le gestionnaire de l'utilisateur se joint par
# XDG_RUNTIME_DIR, qu'une session ssh ne pose pas toujours, ou par le bus.
SYSTEMD_USER = BUS + "export XDG_RUNTIME_DIR=/run/user/$(id -u); "
# L'unité existe et lance le point d'entrée du checkout de la VM, chemin
# entier entre guillemets.
CMD_UNITE = (
    'grep -Fqx "ExecStart=\\"$HOME/git/erplibre/script/install/'
    f'erplibre_home_deck.sh\\"" {FICHIER_UNITE} && echo ok'
)
CMD_AUTOSTART = SYSTEMD_USER + f"systemctl --user is-enabled {UNITE_DECK}"
# Une VM n'a pas de deck : ExecCondition échoue, systemd saute le démarrage
# et l'unité reste inactive avec le résultat « exec-condition ».
CMD_CONDITION = SYSTEMD_USER + (
    f"systemctl --user start {UNITE_DECK};"
    f" systemctl --user show -p ActiveState -p Result {UNITE_DECK}"
)
CMD_SANS_SERVICE = (
    f"test ! -e {FICHIER_UNITE} && test ! -e {REGLAGES_DECK} && echo ok"
)
# « stat » sans « -L » lit le lien lui-même : c'est la date du LIEN que
# l'installateur ne doit pas réécrire, pas celle du dossier qu'il désigne.
CMD_MTIME_LIEN = f"stat -c '%n %Y' {LIEN_EXTENSION}"
CMD_MTIMES = (
    f"stat -c '%n %Y' {REGLE_UDEV} {VENV_DECK} {LIEN_EXTENSION}"
    f" {FICHIER_UNITE} {REGLAGES_DECK}"
)
CMD_JOURNAL = (
    "journalctl --user -b --no-pager 2>&1"
    " | grep -i -e erplibrehome -e erplibre-home -e gnome-shell"
```

Edit 3/8, replace:

```python
    _etape(
        "stream-deck",
        "install-stream-deck",
        "--stream-deck",
        ("udev", "venv", "stream-deck-active", "stream-deck-idempotent"),
    ),
    _etape(
        "partial-uninstall",
        "uninstall-stream-deck",
        "--uninstall --stream-deck",
        ("partial-uninstall-gone", "partial-uninstall-kept"),
    ),
    _etape("uninstall", "uninstall", "--uninstall", ("uninstall-gone",)),
    _etape(
        "reinstall",
        "reinstall",
```

with:

```python
    _etape(
        "stream-deck",
        "install-stream-deck",
        "--stream-deck --deck-program=tiler --autostart",
        (
            "udev",
            "venv",
            "service-unit",
            "service-enabled",
            "service-condition",
            "stream-deck-active",
            "stream-deck-idempotent",
        ),
    ),
    _etape(
        "partial-uninstall",
        "uninstall-stream-deck",
        "--uninstall --stream-deck",
        (
            "partial-uninstall-gone",
            "partial-uninstall-service-gone",
            "partial-uninstall-kept",
        ),
    ),
    _etape(
        "uninstall",
        "uninstall",
        "--uninstall",
        ("uninstall-gone", "uninstall-service-gone"),
    ),
    _etape(
        "reinstall",
        "reinstall",
```

Edit 4/8, replace:

```python
    nouveau n'apparaît qu'une fois. Une sortie vide ou None rend [].
    """
    return sorted(set(_MONTAGE_ECHOUE.findall(sortie or "")))


def journal_lu(sortie):
```

with:

```python
    nouveau n'apparaît qu'une fois. Une sortie vide ou None rend [].
    """
    return sorted(set(_MONTAGE_ECHOUE.findall(sortie or "")))


def etat_systemd(sortie):
    """{propriété: valeur} des lignes « Clé=valeur » de systemctl show,
    quel que soit leur ordre ; {} pour une sortie vide ou None."""
    etat = {}
    for ligne in (sortie or "").splitlines():
        cle_, egal, valeur = ligne.strip().partition("=")
        if egal:
            etat[cle_] = valeur
    return etat


def condition_sautee(etat):
    """Vrai quand systemd a sauté le démarrage sur ExecCondition : unité
    inactive, résultat « exec-condition »."""
    return (
        etat.get("ActiveState") == "inactive"
        and etat.get("Result") == "exec-condition"
    )


def journal_lu(sortie):
```

Edit 5/8, replace:

```python

def _etape_stream_deck(cible, log):
    """Étape 2 : le niveau Stream Deck par-dessus la base, sans
    redémarrage, l'extension étant déjà chargée. Rend (echec, info)."""
    option = OPTION["install-stream-deck"]
    if not commande_reussie(cible, log, "install-stream-deck", option):
        return "install-stream-deck", None
```

with:

```python

def _etape_stream_deck(cible, log):
    """Étape 2 : le niveau Stream Deck par-dessus la base, sans
    redémarrage, l'extension étant déjà chargée ; le service du deck est
    posé avec le tiler et activé à la connexion. Rend (echec, info)."""
    option = OPTION["install-stream-deck"]
    if not commande_reussie(cible, log, "install-stream-deck", option):
        return "install-stream-deck", None
```

Edit 6/8, replace:

```python
        return "udev", None
    if not constat(cible, log, "venv", CMD_VENV, DELAIS_CONTROLE["venv"]):
        return "venv", None
    controle = Controle(cible, log, "stream-deck-active")
    info = extension_active(controle, DELAIS_CONTROLE["stream-deck-active"])
    if not controle.clore(est_active(info)):
```

with:

```python
        return "udev", None
    if not constat(cible, log, "venv", CMD_VENV, DELAIS_CONTROLE["venv"]):
        return "venv", None
    if not constat(cible, log, "service-unit", CMD_UNITE):
        return "service-unit", None
    controle = Controle(cible, log, "service-enabled")
    if not controle.clore(controle.sonder(CMD_AUTOSTART) == "enabled"):
        return "service-enabled", None
    controle = Controle(cible, log, "service-condition")
    etat = etat_systemd(controle.sonder(CMD_CONDITION))
    if not controle.clore(condition_sautee(etat)):
        return "service-condition", None
    controle = Controle(cible, log, "stream-deck-active")
    info = extension_active(controle, DELAIS_CONTROLE["stream-deck-active"])
    if not controle.clore(est_active(info)):
```

Edit 7/8, replace:

```python
    controle = Controle(cible, log, "partial-uninstall-gone")
    if not controle.clore(_absents(controle)):
        return "partial-uninstall-gone", None
    controle = Controle(cible, log, "partial-uninstall-kept")
    garde = controle.sonder(CMD_LIEN) == "ok" and UUID_EXTENSION in (
        liste_extensions(controle.sonder(CMD_ENABLED)) or []
```

with:

```python
    controle = Controle(cible, log, "partial-uninstall-gone")
    if not controle.clore(_absents(controle)):
        return "partial-uninstall-gone", None
    if not constat(
        cible, log, "partial-uninstall-service-gone", CMD_SANS_SERVICE
    ):
        return "partial-uninstall-service-gone", None
    controle = Controle(cible, log, "partial-uninstall-kept")
    garde = controle.sonder(CMD_LIEN) == "ok" and UUID_EXTENSION in (
        liste_extensions(controle.sonder(CMD_ENABLED)) or []
```

Edit 8/8, replace:

```python
    )
    if not controle.clore(parti):
        return "uninstall-gone"
    return None


```

with:

```python
    )
    if not controle.clore(parti):
        return "uninstall-gone"
    if not constat(cible, log, "uninstall-service-gone", CMD_SANS_SERVICE):
        return "uninstall-service-gone"
    return None


```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv.erplibre/bin/python -m unittest test.test_longtest_install_erplibre_home test.test_todo_longtest`
Expected: `OK (skipped=7)`; `test_longtest_install_erplibre_home` alone reports `Ran 116 tests`.

- [ ] **Step 5: Check the plan of a dry run**

Run: `T=$(mktemp -d); HOME="$T" ./long_test/install_erplibre_home.py --only ubuntu:24.04 --dry-run | grep -E 'étape [234]'; rm -rf "$T"`
Expected (the throwaway `HOME` keeps the dry-run report out of `~/.erplibre/longtest`):
```
étape 2, stream-deck — install-stream-deck : install_erplibre_home.sh --stream-deck --deck-program=tiler --autostart — udev, venv, service-unit, service-enabled, service-condition, stream-deck-active, stream-deck-idempotent
étape 3, partial-uninstall — uninstall-stream-deck : install_erplibre_home.sh --uninstall --stream-deck — partial-uninstall-gone, partial-uninstall-service-gone, partial-uninstall-kept
étape 4, uninstall — uninstall : install_erplibre_home.sh --uninstall — uninstall-gone, uninstall-service-gone
```
each line prefixed by a time stamp.

- [ ] **Step 6: Update the README**

In `long_test/README.base.md`:

Edit 1/2, replace:

```markdown

1. **base**: the checks above, then neither the udev rule nor
   `.venv.streamdeck` exists, and a second base install changes nothing;
2. **stream-deck**: `--stream-deck` writes the udev rule, the venv
   imports what the deck programs import, the extension stays ACTIVE, and a
   second run changes nothing;
3. **partial-uninstall**: `--uninstall --stream-deck` removes the rule
   and the venv, and leaves the extension linked, enabled and ACTIVE;
4. **uninstall**: `--uninstall` leaves neither link, nor UUID in
   `enabled-extensions`, nor rule, nor venv;
5. **reinstall**: the base again, then a reboot: the extension comes back
   ACTIVE with every indicator mounted, without the rule or the venv.

```

with:

```markdown

1. **base**: the checks above, then neither the udev rule nor
   `.venv.streamdeck` exists, and a second base install changes nothing;
2. **stream-deck**: `--stream-deck --deck-program=tiler --autostart`
   writes the udev rule, the venv imports what the deck programs import,
   the deck service unit runs this checkout's entry point and is enabled,
   `systemctl --user start` leaves it inactive since a VM has no deck
   (`Result=exec-condition`), the extension stays ACTIVE, and a second run
   changes nothing, unit and settings included;
3. **partial-uninstall**: `--uninstall --stream-deck` removes the rule,
   the venv, the unit and its settings, and leaves the extension linked,
   enabled and ACTIVE;
4. **uninstall**: `--uninstall` leaves neither link, nor UUID in
   `enabled-extensions`, nor rule, nor venv, nor unit, nor settings;
5. **reinstall**: the base again, then a reboot: the extension comes back
   ACTIVE with every indicator mounted, without the rule or the venv.

```

Edit 2/2, replace:

```markdown
1. **base** : les contrôles ci-dessus, puis ni la règle udev ni
   `.venv.streamdeck` n'existent, et une seconde installation de la base ne
   change rien ;
2. **stream-deck** : `--stream-deck` écrit la règle udev, le venv
   importe ce qu'importent les programmes du deck, l'extension reste ACTIVE,
   et une seconde exécution ne change rien ;
3. **partial-uninstall** : `--uninstall --stream-deck` retire la règle
   et le venv, et laisse l'extension liée, activée et ACTIVE ;
4. **uninstall** : `--uninstall` ne laisse ni lien, ni UUID dans
   `enabled-extensions`, ni règle, ni venv ;
5. **reinstall** : la base de nouveau, puis un redémarrage : l'extension
   revient ACTIVE avec chaque indicateur monté, sans la règle ni le venv.

```

with:

```markdown
1. **base** : les contrôles ci-dessus, puis ni la règle udev ni
   `.venv.streamdeck` n'existent, et une seconde installation de la base ne
   change rien ;
2. **stream-deck** : `--stream-deck --deck-program=tiler --autostart`
   écrit la règle udev, le venv importe ce qu'importent les programmes du
   deck, l'unité du service du deck lance le point d'entrée de ce checkout
   et est activée, `systemctl --user start` la laisse inactive faute de
   deck dans une VM (`Result=exec-condition`), l'extension reste ACTIVE, et
   une seconde exécution ne change rien, unité et réglages compris ;
3. **partial-uninstall** : `--uninstall --stream-deck` retire la règle,
   le venv, l'unité et ses réglages, et laisse l'extension liée, activée et
   ACTIVE ;
4. **uninstall** : `--uninstall` ne laisse ni lien, ni UUID dans
   `enabled-extensions`, ni règle, ni venv, ni unité, ni réglages ;
5. **reinstall** : la base de nouveau, puis un redémarrage : l'extension
   revient ACTIVE avec chaque indicateur monté, sans la règle ni le venv.

```

Run: `source .venv.erplibre/bin/activate && mmg --yes long_test/README.base.md`
Expected: `1 base file has been converted.`; `git diff --stat long_test/` lists `README.base.md`, `README.md`, `README.fr.md` and `install_erplibre_home.py` only.

- [ ] **Step 7: Format and comment hygiene**

Run: `.venv.erplibre/bin/black -l 79 --check long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py && python3 script/analyse/check_comment_hygiene.py long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py`
Expected: `2 files would be left unchanged.` and no hygiene line.

- [ ] **Step 8: Commit**

Write `"$SCRATCH/msg-8.txt"`:

```text
[ADD] long_test: deck service checks in the ERPLibre Home stages

Stage 2 now installs with --deck-program=tiler --autostart and checks
that the unit runs the VM checkout's entry point, is enabled, and stays
inactive with Result=exec-condition after a start, since a VM has no
deck; its idempotence check covers the unit and the settings. Stages 3
and 4 check that both are gone. Every check name stays unique, so a
verdict still names its stage.

--- FR ---
[ADD] long_test : contrôles du service du deck dans les étapes

L'étape 2 installe désormais avec --deck-program=tiler --autostart et
vérifie que l'unité lance le point d'entrée du checkout de la VM, est
activée, et reste inactive avec Result=exec-condition après un start,
faute de deck dans une VM ; son contrôle d'idempotence couvre l'unité et
les réglages. Les étapes 3 et 4 vérifient que les deux sont partis.
Chaque nom de contrôle reste unique : un verdict nomme encore son étape.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-8.txt"
git add long_test/install_erplibre_home.py long_test/README.base.md long_test/README.md long_test/README.fr.md test/test_longtest_install_erplibre_home.py
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-8.txt"
```

---

### Task 9: Changelog

**Files:**
- Modify: `CHANGELOG.base.md` (after the `TODO › Execute › Stream Deck` bullet near line 150, and its French twin near line 276); regenerate `CHANGELOG.md`, `CHANGELOG.fr.md`

**Interfaces:**
- Consumes: Tasks 1-8 as delivered.
- Produces: two bullets per language under `Added` / `Ajouté`.

- [ ] **Step 1: Add the bullets**

In `CHANGELOG.base.md`:

Edit 1/2, replace:

```markdown
- stream_deck: multi-indicator GNOME extension (registry-based, six panel buttons: controller, pencil, film, ERPLibre, network, device); GSettings schema; KeepassXC + Selenium / xdotool auto-login; SSH discovery; git settings sync; backup/restore; FR/EN i18n.
- ERPLibre Home installs without Odoo, in two levels, through `script/install/install_erplibre_home.sh` on Debian, Ubuntu, Fedora, AlmaLinux, Rocky Linux, openSUSE and Arch Linux with GNOME Shell 45 to 51. The base links the GNOME extension, compiles its schemas and translations with `msgfmt --check` and enables it; `--stream-deck` adds the USB packages, a `uaccess` udev rule and `.venv.streamdeck`. `--uninstall` undoes either level, `--dry-run` prints the plan, and an unsupported system exits 2 with one `UNSUPPORTED:` line. `make erplibre_home_install` and `make erplibre_home_streamdeck_install` run the same commands
- `TODO › Execute › Stream Deck` installs either level on the local workstation, and shows the installer's `UNSUPPORTED` reason as one line
- Two QEMU VM tools, `erplibre_home` and `erplibre_home_streamdeck`, run the installer after the GNOME desktop; the "ERPLibre Home (no Odoo)" install profile installs the base alone, with no Odoo service
- `long_test/install_erplibre_home.py`, also in the long-test menu, creates one desktop VM per supported system, installs HEAD from a git bundle, and requires GetExtensionInfo to report the extension ACTIVE; five stages then install, partly and fully uninstall, and reinstall on the same VM, and each system's log names every check and its outcome

```

with:

```markdown
- stream_deck: multi-indicator GNOME extension (registry-based, six panel buttons: controller, pencil, film, ERPLibre, network, device); GSettings schema; KeepassXC + Selenium / xdotool auto-login; SSH discovery; git settings sync; backup/restore; FR/EN i18n.
- ERPLibre Home installs without Odoo, in two levels, through `script/install/install_erplibre_home.sh` on Debian, Ubuntu, Fedora, AlmaLinux, Rocky Linux, openSUSE and Arch Linux with GNOME Shell 45 to 51. The base links the GNOME extension, compiles its schemas and translations with `msgfmt --check` and enables it; `--stream-deck` adds the USB packages, a `uaccess` udev rule and `.venv.streamdeck`. `--uninstall` undoes either level, `--dry-run` prints the plan, and an unsupported system exits 2 with one `UNSUPPORTED:` line. `make erplibre_home_install` and `make erplibre_home_streamdeck_install` run the same commands
- `TODO › Execute › Stream Deck` installs either level on the local workstation, and shows the installer's `UNSUPPORTED` reason as one line
- `--stream-deck` also writes the `systemd --user` unit `erplibre-home-streamdeck.service`, which runs the deck program chosen with `--deck-program` (the window tiler by default) when a deck is plugged in, and at login with `--autostart`. Games started from TODO or from the gallery stop it and start it again when they end, and a lock makes a second deck program exit with code 2, naming the one that holds the deck
- `TODO › Execute › Stream Deck` is one submenu: the games, both installs (the Stream Deck one asks for the program, autostart, the restart after a game and the optional tools, then prints its command), the service and its program, autostart, a status view, a diagnosis that names the command fixing each problem, both uninstalls, and the extension's reload and preferences
- Two QEMU VM tools, `erplibre_home` and `erplibre_home_streamdeck`, run the installer after the GNOME desktop; the "ERPLibre Home (no Odoo)" install profile installs the base alone, with no Odoo service
- `long_test/install_erplibre_home.py`, also in the long-test menu, creates one desktop VM per supported system, installs HEAD from a git bundle, and requires GetExtensionInfo to report the extension ACTIVE; five stages then install, partly and fully uninstall, and reinstall on the same VM, and each system's log names every check and its outcome

```

Edit 2/2, replace:

```markdown
- stream_deck : extension GNOME multi-indicateurs (registry, six boutons : controller, pencil, film, ERPLibre, network, device) ; schéma GSettings ; auto-login KeepassXC + Selenium / xdotool ; découverte SSH ; sync Git des préférences ; sauvegarde/restauration ; i18n FR/EN.
- ERPLibre Home s'installe sans Odoo, en deux niveaux, par `script/install/install_erplibre_home.sh` sur Debian, Ubuntu, Fedora, AlmaLinux, Rocky Linux, openSUSE et Arch Linux avec GNOME Shell 45 à 51. La base lie l'extension GNOME, compile ses schémas et ses traductions par `msgfmt --check` et l'active ; `--stream-deck` ajoute les paquets USB, une règle udev `uaccess` et `.venv.streamdeck`. `--uninstall` défait l'un ou l'autre niveau, `--dry-run` affiche le plan, et un système non supporté sort en 2 avec une ligne `UNSUPPORTED:`. `make erplibre_home_install` et `make erplibre_home_streamdeck_install` lancent les mêmes commandes
- `TODO › Exécution › Stream Deck` installe l'un ou l'autre niveau sur le poste local, et montre la raison `UNSUPPORTED` de l'installateur en une ligne
- Deux outils de VM QEMU, `erplibre_home` et `erplibre_home_streamdeck`, lancent l'installateur après le bureau GNOME ; le profil d'installation « ERPLibre Home (sans Odoo) » installe la base seule, sans service Odoo
- `long_test/install_erplibre_home.py`, aussi dans le menu des tests longs, crée une VM de bureau par système supporté, y installe HEAD depuis un bundle git, et exige que GetExtensionInfo dise l'extension ACTIVE ; cinq étapes installent ensuite, désinstallent en partie puis en entier, et réinstallent sur la même VM, et le journal de chaque système nomme chaque contrôle et son issue

```

with:

```markdown
- stream_deck : extension GNOME multi-indicateurs (registry, six boutons : controller, pencil, film, ERPLibre, network, device) ; schéma GSettings ; auto-login KeepassXC + Selenium / xdotool ; découverte SSH ; sync Git des préférences ; sauvegarde/restauration ; i18n FR/EN.
- ERPLibre Home s'installe sans Odoo, en deux niveaux, par `script/install/install_erplibre_home.sh` sur Debian, Ubuntu, Fedora, AlmaLinux, Rocky Linux, openSUSE et Arch Linux avec GNOME Shell 45 à 51. La base lie l'extension GNOME, compile ses schémas et ses traductions par `msgfmt --check` et l'active ; `--stream-deck` ajoute les paquets USB, une règle udev `uaccess` et `.venv.streamdeck`. `--uninstall` défait l'un ou l'autre niveau, `--dry-run` affiche le plan, et un système non supporté sort en 2 avec une ligne `UNSUPPORTED:`. `make erplibre_home_install` et `make erplibre_home_streamdeck_install` lancent les mêmes commandes
- `TODO › Exécution › Stream Deck` installe l'un ou l'autre niveau sur le poste local, et montre la raison `UNSUPPORTED` de l'installateur en une ligne
- `--stream-deck` écrit aussi l'unité `systemd --user` `erplibre-home-streamdeck.service`, qui lance le programme du deck choisi par `--deck-program` (le window tiler par défaut) quand un deck est branché, et à l'ouverture de session avec `--autostart`. Les jeux lancés depuis TODO ou la galerie l'arrêtent et la relancent à leur fin, et un verrou fait sortir un second programme du deck avec le code 2, en nommant celui qui tient le deck
- `TODO › Exécution › Stream Deck` est un sous-menu : les jeux, les deux installations (celle du Stream Deck demande le programme, le démarrage automatique, la relance après un jeu et les outils facultatifs, puis affiche sa commande), le service et son programme, le démarrage automatique, un état, un diagnostic qui nomme la commande corrigeant chaque problème, les deux désinstallations, et le rechargement et les préférences de l'extension
- Deux outils de VM QEMU, `erplibre_home` et `erplibre_home_streamdeck`, lancent l'installateur après le bureau GNOME ; le profil d'installation « ERPLibre Home (sans Odoo) » installe la base seule, sans service Odoo
- `long_test/install_erplibre_home.py`, aussi dans le menu des tests longs, crée une VM de bureau par système supporté, y installe HEAD depuis un bundle git, et exige que GetExtensionInfo dise l'extension ACTIVE ; cinq étapes installent ensuite, désinstallent en partie puis en entier, et réinstallent sur la même VM, et le journal de chaque système nomme chaque contrôle et son issue

```

- [ ] **Step 2: Regenerate and check**

Run: `source .venv.erplibre/bin/activate && mmg --yes CHANGELOG.base.md && git diff --stat`
Expected: `CHANGELOG.base.md | 4 ++++`, `CHANGELOG.fr.md | 2 ++`, `CHANGELOG.md | 2 ++`, nothing else.

- [ ] **Step 3: Run the whole unit suite**

Run: `./script/test/run_unit_test.sh 2>&1 | tail -3 && node --test script/gnome-extension/erplibre_home/test/unit/*.test.js 2>&1 | grep -E '^ℹ (tests|pass|fail)'`
Expected: `8364 tests, tout vert` (8254 + 110) and `tests 248`, `pass 248`, `fail 0`. The line `Temporaires laissés … test_longtest_install_erplibre_home.py (4)` is there at HEAD too.

- [ ] **Step 4: Commit**

Write `"$SCRATCH/msg-9.txt"`:

```text
[UPD] changelog: ERPLibre Home deck service and Stream Deck submenu

Records for a reader choosing whether to upgrade that the Stream Deck
level now brings a systemd user service running the deck program, that
games hand the deck over and back, and that TODO gathers everything
Stream Deck under one submenu. Two bullets per language under Added,
regenerated by mmg from CHANGELOG.base.md.

--- FR ---
[UPD] changelog : service du deck et sous-menu Stream Deck

Consigne pour qui choisit de mettre à jour que le niveau Stream Deck
apporte un service systemd utilisateur qui lance le programme du deck,
que les jeux prennent le deck et le rendent, et que TODO réunit tout ce
qui touche au Stream Deck sous un sous-menu. Deux puces par langue sous
Ajouté, régénérées par mmg depuis CHANGELOG.base.md.

Assisted-by: Claude Opus 5.5
```

```bash
python3 script/git/hooks/commit-msg "$SCRATCH/msg-9.txt"
git add CHANGELOG.base.md CHANGELOG.md CHANGELOG.fr.md
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit --no-verify -F "$SCRATCH/msg-9.txt"
```

---

### Task 10: Long test rerun on five systems (manual gate)

Nothing in this task is committed unless a check fails; a fix then goes to the task that owns the code, as a new `[FIX]` commit with its own bilingual message. Notes, timings and verdicts go to `tasks/` (unversioned).

**Files:** none, unless a fix is needed (see the table in Step 5).

**Interfaces:**
- Consumes: Tasks 1-9 committed; a clean tree (the long test refuses a modified tracked file, since the VM receives a `git bundle` of HEAD).
- Produces: a go / no-go on the five systems.

- [ ] **Step 1: Make sure nothing else is running**

Run: `git status --short; pgrep -af 'long_test/install_erplibre_home.py'`
Expected: no output from either. If a run is in progress, wait for it to end; never kill it or touch its VMs.

- [ ] **Step 2: Dry run**

Run: `./long_test/install_erplibre_home.py --only ubuntu:24.04,debian:13,fedora:43,opensuse:16.0,arch:latest --dry-run`
Expected: exit 0, the five systems listed, the stage 2 line naming `--stream-deck --deck-program=tiler --autostart` and `service-unit, service-enabled, service-condition`, the stage 3 line naming `partial-uninstall-service-gone`, the stage 4 line naming `uninstall-service-gone`; no `sudo` asked.

- [ ] **Step 3: Real run**

Run: `sudo -v && ./long_test/install_erplibre_home.py --only ubuntu:24.04,debian:13,fedora:43,opensuse:16.0,arch:latest 2>&1 | tee "$SCRATCH/longtest.txt"`
Expected (hours): exit 0, every system `ACTIVE`; each system's `.log` holds `── contrôle service-unit : réussi`, `service-enabled`, `service-condition`, `partial-uninstall-service-gone` and `uninstall-service-gone`, each `réussi`. Keep the sudo session alive for the whole run (see `long_test/README.md`).

- [ ] **Step 4: Read each failure's raw reply**

For each `FAILED(<check>)`, open the system's `.log` in the run's sub-directory under `~/.erplibre/longtest/` and read the block `── contrôle <check> : ÉCHEC`: each command it ran is followed by its raw reply.

- [ ] **Step 5: Fix in the owning task, rerun that system only**

| Verdict | Owning code | First thing to compare |
|---|---|---|
| `install-stream-deck`, `stream-deck-idempotent` | Task 4, `install_service`, `write_unit`, `write_settings` | the installer output in the log; a second run must log `unit already in place` and `settings already in place` |
| `service-unit` | Task 4 `unit_content`, or Task 8 `CMD_UNITE` | the unit's `ExecStart=` line against `"$HOME/git/erplibre/script/install/erplibre_home_deck.sh"` |
| `service-enabled` | Task 4 `install_service` (`user_systemctl enable`) | whether the installer summary printed `after the next login, run:` (no user manager reached over ssh) |
| `service-condition` | Task 1 `--check`, Task 4 `ExecCondition=` line, or Task 8 `condition_sautee` | the raw `systemctl --user show` reply: if systemd reports the skip with another `Result=` value on that system, Task 8's expectation is what changes |
| `partial-uninstall-service-gone`, `uninstall-service-gone` | Task 4 `uninstall_service` | which of the unit file or the settings file is still there |
| `stream-deck-active`, `partial-uninstall-kept`, `reinstall-*` | not this plan's code unless the log names the device indicator | the journal lines `[ERPLibreHome] mount device failed` (Task 7) |

After each fix: its unit tests green, commit, then `./long_test/install_erplibre_home.py --only <that system>`.

- [ ] **Step 6: Undo what is left**

Run: `./long_test/install_erplibre_home.py --detruire`
Expected: the run's VMs listed then destroyed after the confirmation; nothing left from this run in `virsh list --all`.

- [ ] **Step 7: Manual, on a workstation with a Stream Deck (human only)**

An agent skips this step and reports it as not done. On a workstation with a deck plugged in, from this checkout: `./script/install/install_erplibre_home.sh --stream-deck --autostart`, log out and back in, then check: `systemctl --user is-active erplibre-home-streamdeck.service` prints `active` and the deck shows the tiler; TODO › Execute › Stream Deck › Status names `Deck lock: held by tiler`; a game from TODO › Stream Deck › Games stops the service and takes the deck, and closing it brings the tiler back; the same from the gallery with one `r` + Enter replay brings the tiler back once, at the end.
