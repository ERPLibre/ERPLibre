# ERPLibre Home Deployment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install ERPLibre Home in two levels with one shell installer on every supported amd64 GNOME 45–51 system: the base (the GNOME extension, its schemas and translations, enabled; no device access, no venv) and, with `--stream-deck`, the Stream Deck level (USB packages, udev rule, `.venv.streamdeck` for the deck code and games), which always includes the base. Prove it with a long test that reports the extension ACTIVE in a real session, then adds, removes and reinstalls the levels on the same VM.

**Architecture:** `script/install/install_erplibre_home.sh` is the only place that knows how to install; the level is its `--stream-deck` option, not a second script. The base links, compiles (`glib-compile-schemas`, `msgfmt --check`) and enables the extension; `--stream-deck` adds the deck packages, a `uaccess` udev rule and `.venv.streamdeck` (no Odoo). Make (two install/uninstall pairs), TODO (two local entries), two QEMU tools and a QEMU profile call it. Where the deck venv is missing, the deck entry points (make guard, `device`/`controller` indicators, TODO games entry) name `make erplibre_home_streamdeck_install`. `long_test/install_erplibre_home.py` creates one VM per system from a `git bundle` of HEAD, logs in through GDM autologin, reads `GetExtensionInfo` over the session bus, and runs five stages on the same VM.

**Tech Stack:** bash, Python 3 (unittest), GJS ES modules (node --test for pure modules), GNU make, libvirt/QEMU via `script/qemu/deploy_qemu.py`, gdbus/gsettings.

**Spec:** `docs/superpowers/specs/2026-10-13-streamdeck-deployment-design.md`

## Global Constraints

- Scope: amd64 only; GNOME `shell-version` 45–51 read from `script/gnome-extension/erplibre_home/metadata.json`, never hardcoded.
- Extension UUID: `erplibre-home@technolibre.ca`; installed as a symlink at `~/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca`.
- Two levels, one installer: `install_erplibre_home.sh [--stream-deck] [--no-enable] [--extension-only] [--with-extras] [--uninstall] [--dry-run]`. Without `--stream-deck` it installs the base only: packages `glib`/`gettext`/system `python3`, the extension linked, schemas, translations by `msgfmt --check`, enabled. `--stream-deck` adds the Stream Deck packages (hidapi, libusb, venv module, `wmctrl`; EPEL on AlmaLinux/Rocky only then), the udev rule and `.venv.streamdeck`, and runs the base steps too. `--uninstall` removes everything; `--uninstall --stream-deck` removes only the udev rule and `.venv.streamdeck`. `--extension-only` with `--stream-deck` or `--uninstall` is a usage error (exit 1).
- Deck venv: `.venv.streamdeck`, created by `--stream-deck` alone with the system `python3 -m venv`, no pyenv. A base install has no venv. ERPLibre tooling (`todo.py`, selenium, instance make targets) keeps `.venv.erplibre`; `po/compile_locales.py` and `make erplibre_home_compile_locale` keep the system `python3`.
- Missing deck venv: the deck entry points say how to add the level. The make guard prints `Stream Deck venv missing: make erplibre_home_streamdeck_install`; the `device`/`controller` indicators and the TODO games entry show `ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install` (translated) and start nothing.
- Installer exit codes: `0` done (installed or uninstalled), `2` unsupported (one stderr line `UNSUPPORTED: <reason>`), `1` anything else. Runs as the user, `sudo` only for packages and the udev rule. The `shell-version` pre-check reads `metadata.json` with `tr`/`grep`/`sed`, never `python3`.
- udev rule (Stream Deck level only): `/etc/udev/rules.d/70-streamdeck.rules`, `TAG+="uaccess"`, vendor `0fd9`, subsystems usb and hidraw.
- "Enabled" means `GetExtensionInfo` reports `state == 1` and an empty `error` in a running session.
- Long test VMs: `--desktop --gpu off --vcpus 2 --memory 4096 --disk-size 26G`; source is a `git bundle` of a clean HEAD. Per VM, after the base install and the autologin reboot: five stages (base, `install-stream-deck`, `uninstall-stream-deck`, `uninstall`, `reinstall` with a reboot); every command and check name is unique, and the first failure is the verdict.
- Commits: `[TAG] scope: subject` in English ≤ 72 chars; English body, `--- FR ---`, French subject under the same tag, French body; ≤ 8 lines per language; trailer `Assisted-by: Claude Opus 5.5`; never an AI in `Co-authored-by`; stage files by name; validate with `script/git/hooks/commit-msg <msgfile>`; identity `-c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca"`.
- Comments and docs: nothing identifying (no real hosts, IPs, emails, user paths); invented examples only; present tense, how the code works. Docs: edit `.base.md`, regenerate with `source .venv.erplibre/bin/activate && mmg --yes <file>.base.md`.
- Unit tests stay in `test/` and run in seconds without virtualization; real VMs only in `long_test/`.
- Every command runs from the checkout root. `$SCRATCH` is a scratch directory outside the repository (`SCRATCH=$(mktemp -d)`), used for commit message files.

## Review Focus

- A checkout path containing a space: every path the installer, the Makefile recipes and the long test build is quoted, and the install still succeeds (Task 4).
- An extension the user once turned off in the Extensions app: its UUID sits in `org.gnome.shell disabled-extensions`, which wins over `enabled-extensions`; the installer removes it from `disabled-extensions` when enabling (Task 4).
- A real directory, not a symlink, already at the extension path (a copy from an older manual install): the installer never deletes it; it stops with exit 1 and a message naming the path (Task 4).
- Running the installer inside an open GNOME session (`DBUS_SESSION_BUS_ADDRESS` set): gsettings writes go to the live bus, never through `dbus-run-session`, so the running dconf service does not overwrite them (Task 4).
- A base install never writes what belongs to the Stream Deck level: no udev rule, no `.venv.streamdeck`, no deck package, no EPEL (Task 3 dry-run tests, Task 4 package tests, long-test checks `base-no-udev`/`base-no-venv`).
- `--uninstall --stream-deck` leaves the extension linked, enabled and ACTIVE, and the `device`/`controller` indicators then show the missing-level message instead of failing (Tasks 2 and 4; long-test stage 3).
- Both QEMU tools ticked on one VM run the `--stream-deck` command only, once (Task 6).
- A workstation whose GNOME moved past `shell-version`: `--uninstall` still works, since it skips the version check (Task 3).
- Two long-test runs one after the other, the first with `--garder`: VM names are unique per run, so the second run never collides with or destroys the kept VMs (Task 9).

---

### Task 0: Spike — the spec's premises on one VM (manual gate)

Nothing in this task is committed. Commands are throwaway; notes go to `tasks/erplibre-home-spike.md` (unversioned).

**Files:** none in the repository.

**Interfaces:**
- Consumes: the current checkout at HEAD.
- Produces: a go / no-go on the spec's premises. A no-go stops the plan and returns to brainstorming.

- [ ] **Step 1: Create the VM**

```bash
sudo .venv.erplibre/bin/python script/qemu/deploy_qemu.py \
  --distro ubuntu --version 24.04 --name sd-spike \
  --desktop --gpu off --vcpus 2 --memory 4096 --disk-size 26G \
  --ssh-key ~/.ssh/id_ed25519.pub
```

Expected: the VM is created and its address is printed. Note it as `$VM` (for example `ubuntu@<address>`).

- [ ] **Step 2: Install the desktop with the menu's own script**

The Python lines are the body of Task 9's `commande_bureau()`: the same import, the same instance built with `TODO.__new__(TODO)` without running the menu's constructor, the same call. The spike sends the exact command the long test sends.

```bash
.venv.erplibre/bin/python - <<'PY' > /tmp/sd-desktop.sh
import sys
sys.argv = ["todo.py"]
from script.todo.todo import TODO
print(TODO.__new__(TODO)._qemu_erplibre_remote_cmd(None, desktop="gnome"))
PY
ssh $VM 'bash -s' < /tmp/sd-desktop.sh
```

Expected: exit 0, GNOME packages installed.

- [ ] **Step 3: Copy the checkout and install the extension by hand**

```bash
git bundle create /tmp/sd.bundle HEAD
scp /tmp/sd.bundle $VM:
ssh $VM 'sudo apt-get install -y git && git clone ~/sd.bundle ~/git/erplibre'
ssh $VM 'cd ~/git/erplibre && make erplibre_home_install_extension'
ssh $VM 'dbus-run-session -- gsettings set org.gnome.shell enabled-extensions "[\"erplibre-home@technolibre.ca\"]"'
```

Add one throwaway line in the VM's copy of `extension.js` `enable()`: `console.log("SDT-PATH " + this.path);`.

- [ ] **Step 4: Autologin and reboot**

```bash
ssh $VM 'sudo sed -i "s/^#\? *AutomaticLoginEnable.*/AutomaticLoginEnable=true/; s/^#\? *AutomaticLogin *=.*/AutomaticLogin=$USER/" /etc/gdm3/custom.conf && grep -n AutomaticLogin /etc/gdm3/custom.conf && sudo reboot'
```

Expected: both keys appear uncommented under `[daemon]`.

- [ ] **Step 5: Check the premises over ssh**

```bash
ssh $VM 'ls -l /run/user/$(id -u)/bus'
ssh $VM 'DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus gdbus call --session --dest org.gnome.Shell.Extensions --object-path /org/gnome/Shell/Extensions --method org.gnome.Shell.Extensions.GetExtensionInfo erplibre-home@technolibre.ca'
ssh $VM 'journalctl --user -b | grep SDT-PATH'
ssh $VM "journalctl --user -b -o cat | grep -E '\[ERPLibreHome\] (mount|enabled)'"
```

Expected, the five things of spec section 9:
1. GDM autologin reached a GNOME session under `--gpu off`: the reboot came back with the user logged in;
2. an ssh session reads the user's session bus: the socket `/run/user/<uid>/bus` exists and the next command answers through it;
3. the reply contains `'state': <1.0>` and `'error': <''>` for the symlinked extension;
4. `SDT-PATH /home/<user>/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca` — the unresolved symlink path;
5. the `[ERPLibreHome] enabled` line, and no `[ERPLibreHome] mount <id> failed` line: `enable()` ran to its end and every top-bar indicator mounted. The extension catches an indicator constructor's exception and keeps running, so expectation 3 holds even when no indicator mounted. The VM has no `.venv.streamdeck` (Step 3 creates none), so this also shows the `device` and `controller` indicators mount without the deck venv, the premise of the base level.

Also record `gnome-shell --version`, and the exact `gdbus` reply text, into `tasks/erplibre-home-spike.md`: Task 8 parses that format.

- [ ] **Step 6: Destroy the VM**

```bash
sudo virsh destroy sd-spike; sudo virsh undefine sd-spike --remove-all-storage
```

Go / no-go: all five expectations hold → continue with Task 1. Any one fails → stop, write what failed in `tasks/erplibre-home-spike.md`, and return to the spec.

---

### Task 1: Stream Deck venv entry points and requirements

**Files:**
- Create: `test/test_streamdeck_entry_points.py`
- Modify: `conf/make.streamdeck.Makefile:1-426` (header guard inserted after line 3; every deck python recipe rewritten mechanically; the three lines of `po/compile_locales.py`, at 122-123 and 426, keep the system `python3`; the `tools/enable_next_login.py` call of `erplibre_home_enable_extension` is not deck code and keeps its shebang)
- Modify: `script/stream_deck/requirements.txt:1-9` (whole file)
- Modify: `script/stream_deck/gallery_server.py:18-19` (import), `:97` (new function before `class GameHandler`), `:253-265` (launcher body)
- Modify: `script/todo/todo.py:58` (constant), `:1830-1831` (venv check at the top of `prompt_execute_streamdeck_games`), `:1857` (call), `:1867` (new method before `_scan_streamdeck_games`)
- Modify: `script/todo/todo_i18n.py:116-119` (one key after `"No Stream Deck games found."`)
- Delete: `script/stream_deck/launch_game.sh`
- Test: `test/test_streamdeck_entry_points.py`, `test/test_todo_menu.py`, `test/test_todo_i18n.py`, `test/test_i18n_duplicates.py`, `test/test_erplibre_home_enable_target.py` (the last four must stay green; the last one runs `make -s erplibre_home_enable_extension` on the fragment this task rewrites)

**Interfaces:**
- Consumes: nothing from other tasks. The guard message names `make erplibre_home_streamdeck_install`, which Task 4 defines.
- Produces:
  - Makefile variable `STREAMDECK_PY := .venv.streamdeck/bin/python`, defined at the top of `conf/make.streamdeck.Makefile`.
  - A file rule `$(STREAMDECK_PY):` that fails with exit 1 and the one stderr line `Stream Deck venv missing: make erplibre_home_streamdeck_install`.
  - Every deck python target lists `$(STREAMDECK_PY)` as a prerequisite: 55 targets. `po/compile_locales.py` is not deck code: `erplibre_home_compile_locale` and `erplibre_home_install_extension` keep the system `python3` and no venv prerequisite (Task 4 then moves `erplibre_home_install_extension` to the installer).
  - `gallery_server._game_bash_cmd(game_file) -> str`
  - `todo.VENV_STREAMDECK_PYTHON`
  - `TODO._streamdeck_game_command(self, path) -> str`
  - `TODO.prompt_execute_streamdeck_games` returns `False` at once, after printing `t("ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install")`, when `VENV_STREAMDECK_PYTHON` is not executable. That i18n key (fr: `ERPLibre Home Stream Deck n'est pas installé : make erplibre_home_streamdeck_install`) is Task 1's; Task 2 uses the same English text as a gettext msgid in the extension.
  - Task 1 does not touch `device.js`, `controller.js` or the `.po`/`.pot` files. Task 2 owns them.

- [ ] **Step 1: Write the failing test**

Create `test/test_streamdeck_entry_points.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les points d'entrée du Stream Deck tournent sous .venv.streamdeck.

Le code du deck importe StreamDeck, PIL, cv2, pyudev, requests et keyboard :
lancé par son shebang « #!/usr/bin/env python3 », il prend le python du
système, où ces modules manquent, et tombe à l'import. Chaque point d'entrée
nomme donc l'interpréteur du venv dédié.

Ce que ces tests gardent :

- toute recette du fragment make qui appelle python passe par
  $(STREAMDECK_PY), hors la migration de l'extension, son aide
  d'activation et le compilateur des locales, qui ne sont pas du code du
  deck et gardent le python du système ; toute cible qui s'en sert l'a en
  prérequis : sans venv, elle s'arrête sur la commande qui le bâtit,
  make erplibre_home_streamdeck_install ;
- requirements.txt porte ce que le code importe, et plus lz4, que le venv
  ne sert pas ;
- la galerie lance un jeu sous son propre interpréteur, cité pour bash ;
- le menu TODO lance un jeu sous le python du venv, et sans venv il le dit
  dans la langue de l'utilisateur sans rien lancer ;
- launch_game.sh, que rien n'appelait, n'existe plus.
"""

import contextlib
import importlib.util
import io
import os
import re
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import todo as todo_mod  # noqa: E402
from script.todo import todo_i18n  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
MAKEFILE = ROOT / "conf" / "make.streamdeck.Makefile"
DECK_DIR = ROOT / "script" / "stream_deck"
REQUIREMENTS = DECK_DIR / "requirements.txt"
VENV_REF = "$(STREAMDECK_PY)"
INSTALL_DECK = "make erplibre_home_streamdeck_install"
MESSAGE_SANS_VENV = (
    "ERPLibre Home Stream Deck is not installed:"
    " make erplibre_home_streamdeck_install"
)

# Un appel à python sous toutes ses formes : l'interpréteur nommé, pip, ou un
# fichier .py exécuté par son shebang.
APPEL_PYTHON = re.compile(r"\bpython3?\s|\bpip3?\s+install|\S+\.py\b")
# Trois appels restent hors du venv. La migration de l'ancienne identité de
# l'extension et son aide d'activation passent par leur shebang : elles
# n'importent que la bibliothèque standard et tournent avant que le venv
# existe. Le compilateur des locales n'est pas un point d'entrée du deck :
# il garde le python3 du système.
HORS_VENV = re.compile(
    r"/tools/(migrate_legacy|enable_next_login)\.py\b"
    r"|/po/compile_locales\.py\b"
)
SHEBANG_DECK = re.compile(r"\./script/stream_deck/\w+\.py")
REGLE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*):(?!=)(.*)$")


def regles(texte):
    """Rend {cible: (prérequis, [commandes])} des règles nommées du texte.

    Une commande est une ligne logique de recette : les lignes terminées par
    « \\ » y sont jointes. Une ligne à tabulation qui suit une affectation
    de variable n'est pas une recette et n'est rattachée à aucune cible.
    """
    resultat = {}
    cible = None
    en_cours = ""
    for ligne in texte.split("\n"):
        if ligne.startswith("\t") and cible is not None:
            en_cours += ligne.strip().rstrip("\\") + " "
            if not ligne.rstrip().endswith("\\"):
                resultat[cible][1].append(en_cours.strip())
                en_cours = ""
            continue
        if ligne.startswith("\t"):
            continue
        m = REGLE.match(ligne)
        if m:
            cible = m.group(1)
            resultat[cible] = (m.group(2).split(), [])
        elif ligne.strip() and not ligne.startswith("#"):
            cible = None
    return resultat


def jeux():
    """Les jeux du dépôt : game_<id>.py -> id."""
    return sorted(p.stem[len("game_") :] for p in DECK_DIR.glob("game_*.py"))


class TestMakefileUsesTheVenv(unittest.TestCase):
    def setUp(self):
        self.texte = MAKEFILE.read_text(encoding="utf-8")
        self.regles = regles(self.texte)

    def test_the_variable_is_defined(self):
        self.assertTrue(
            re.search(
                r"(?m)^STREAMDECK_PY := \.venv\.streamdeck/bin/python$",
                self.texte,
            ),
            "STREAMDECK_PY absent du fragment",
        )

    def test_the_rules_were_actually_parsed(self):
        # Une forme de fichier que l'analyse ne lit plus doit tomber ici,
        # plutôt que de déclarer conforme une liste vide.
        self.assertGreater(len(self.regles), 50)
        self.assertIn("streamdeck", self.regles)

    def test_no_recipe_calls_a_deck_script_by_its_shebang(self):
        for cible, (_, commandes) in self.regles.items():
            for commande in commandes:
                self.assertNotRegex(commande, SHEBANG_DECK, cible)

    def test_every_python_call_goes_through_the_venv(self):
        for cible, (_, commandes) in self.regles.items():
            for commande in commandes:
                if HORS_VENV.search(commande):
                    continue
                if APPEL_PYTHON.search(commande):
                    self.assertIn(VENV_REF, commande, cible)

    def test_every_target_using_the_venv_requires_it(self):
        for cible, (prerequis, commandes) in self.regles.items():
            if any(VENV_REF in c for c in commandes):
                self.assertIn(VENV_REF, prerequis, cible)

    def test_every_game_has_its_target_under_the_venv(self):
        self.assertIn("snake", jeux())
        for jeu in jeux():
            cible = f"streamdeck_{jeu}"
            self.assertIn(cible, self.regles)
            self.assertEqual(
                self.regles[cible][1],
                [f"{VENV_REF} script/stream_deck/game_{jeu}.py"],
            )

    def test_the_spec_entry_points_use_the_venv(self):
        attendus = {
            "streamdeck": "erplibre_controller.py",
            "streamdeck_gallery": "gallery_server.py",
            "streamdeck_translator_doctor": "translator_doctor.py",
            "streamdeck_translator_test": "translator_test.py",
            "streamdeck_translator_stream": "translator_stream.py",
            "streamdeck_translator_install_ollama": "translator_doctor.py",
            "streamdeck_translator_unittest": "-m unittest",
            "streamdeck_tiler_unittest": "-m unittest",
            "streamdeck_translator_install_vosk_fr": "-m pip install vosk",
        }
        for cible, fragment in attendus.items():
            commandes = " ".join(self.regles[cible][1])
            self.assertRegex(
                commandes,
                re.escape(VENV_REF) + r" [^;]*" + re.escape(fragment),
                cible,
            )

    def test_the_locale_compiler_keeps_the_system_python(self):
        """compile_locales.py n'est pas du code du deck : sa cible tourne
        sans venv, et ne l'exige pas."""
        prerequis, commandes = self.regles["erplibre_home_compile_locale"]
        self.assertEqual(
            commandes,
            ["@python3 $(ERPLIBRE_HOME_EXT_SRC)/po/compile_locales.py"],
        )
        self.assertNotIn(VENV_REF, prerequis)

    def test_pip_never_installs_for_the_user(self):
        self.assertNotIn("pip install --user", self.texte)


@unittest.skipUnless(shutil.which("make"), "make absent")
class TestMakefileGuard(unittest.TestCase):
    def make(self, *args):
        return subprocess.run(
            ["make", "-s", "-f", str(MAKEFILE), *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_a_missing_venv_stops_with_the_install_command(self):
        with tempfile.TemporaryDirectory() as tmp:
            absent = os.path.join(tmp, "absent", "python")
            res = self.make(f"STREAMDECK_PY={absent}", "streamdeck_snake")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("Stream Deck venv missing: " + INSTALL_DECK, res.stderr)

    def test_a_present_venv_runs_the_game_under_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            faux = os.path.join(tmp, "python")
            with open(faux, "w", encoding="utf-8") as f:
                f.write('#!/bin/sh\necho "faux-python $*"\n')
            os.chmod(faux, os.stat(faux).st_mode | stat.S_IXUSR)
            res = self.make(f"STREAMDECK_PY={faux}", "streamdeck_snake")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(
            res.stdout.strip(), "faux-python script/stream_deck/game_snake.py"
        )


class TestRequirements(unittest.TestCase):
    def noms(self):
        noms = set()
        for ligne in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
            ligne = ligne.split("#", 1)[0].strip()
            if ligne:
                noms.add(
                    re.split(r"[<>=!~\[; ]", ligne, maxsplit=1)[0].lower()
                )
        return noms

    def test_what_the_deck_imports_is_required(self):
        for nom in ("requests", "keyboard", "pyudev", "streamdeck"):
            self.assertIn(nom, self.noms())

    def test_lz4_left_the_venv(self):
        self.assertNotIn("lz4", self.noms())


def charger_galerie():
    """Charge gallery_server.py par son chemin : script/stream_deck n'est
    pas un paquet."""
    chemin = DECK_DIR / "gallery_server.py"
    spec = importlib.util.spec_from_file_location("gallery_server", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
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
            # stdin fermé : le « read » de fin de partie échoue et la boucle
            # s'arrête après un tour.
            res = subprocess.run(
                ["bash", "-c", galerie._game_bash_cmd(jeu)],
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(res.stdout.splitlines()[0], sys.executable)


class TestLaunchGameScriptGone(unittest.TestCase):
    def test_the_script_is_removed(self):
        self.assertFalse((DECK_DIR / "launch_game.sh").exists())

    def test_nothing_refers_to_it(self):
        for chemin in DECK_DIR.rglob("*"):
            if chemin.suffix not in {".py", ".js", ".html", ".md", ".sh"}:
                continue
            if "node_modules" in chemin.parts:
                continue
            texte = chemin.read_text(encoding="utf-8", errors="replace")
            self.assertNotIn("launch_game.sh", texte, str(chemin))


class TestTodoGamesLauncher(unittest.TestCase):
    """Le menu des jeux, sur un venv simulé : un faux python exécutable
    quand il est présent, un chemin qui n'existe pas quand il manque."""

    JEU = "/srv/jeux de test/game_demo.py"

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.present = os.path.join(dossier.name, "python")
        with open(self.present, "w", encoding="utf-8") as f:
            f.write("#!/bin/sh\n")
        os.chmod(self.present, 0o755)
        self.absent = os.path.join(dossier.name, "absent", "python")
        self.addCleanup(setattr, todo_i18n, "_current_lang", None)

    def menu(self, python, reponses=("1", "0")):
        """Joue le menu des jeux ; rend (todo, rendu, sortie)."""
        todo = todo_mod.TODO.__new__(todo_mod.TODO)
        todo._scan_streamdeck_games = mock.Mock(
            return_value=[
                {
                    "name": "Demo",
                    "description": "Demo — demo",
                    "path": self.JEU,
                }
            ]
        )
        todo.fill_help_info = lambda choices: ""
        todo.execute = mock.Mock()
        sortie = io.StringIO()
        with (
            mock.patch.object(todo_mod, "VENV_STREAMDECK_PYTHON", python),
            mock.patch.object(
                todo_mod.click, "prompt", side_effect=list(reponses)
            ),
            contextlib.redirect_stdout(sortie),
        ):
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
            "en": MESSAGE_SANS_VENV,
            "fr": "ERPLibre Home Stream Deck n'est pas installé :"
            " make erplibre_home_streamdeck_install",
        }
        for langue, message in attendus.items():
            with self.subTest(langue=langue):
                todo_i18n._current_lang = langue
                todo, rendu, sortie = self.menu(self.absent, reponses=())
                self.assertFalse(rendu)
                self.assertIn(message, sortie)
                todo.execute.exec_command_live.assert_not_called()
                todo._scan_streamdeck_games.assert_not_called()


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./script/test/run_unit_test.sh test/test_streamdeck_entry_points.py`
Expected: FAIL. Run in verbose mode (`PYTHONPATH=. .venv.erplibre/bin/python -m unittest -v test.test_streamdeck_entry_points`) to see the individual failures, `Ran 20 tests`, `FAILED (failures=12, errors=6)`:
- `AttributeError: module 'gallery_server' has no attribute '_game_bash_cmd'` (2)
- `AttributeError: <module 'script.todo.todo' …> does not have the attribute 'VENV_STREAMDECK_PYTHON'` (3, the missing-venv test counting once per language)
- `AttributeError: 'TODO' object has no attribute '_streamdeck_game_command'`
- `AssertionError: 'requests' not found in {...}`
- `'lz4' unexpectedly found`
- `STREAMDECK_PY absent du fragment`, and the shebang, venv, game-target, entry-point and `pip install --user` checks of the Makefile
- `True is not false` (launch_game.sh still exists), and `launch_game.sh` found by `test_nothing_refers_to_it`
- `TestMakefileGuard` fails: `make streamdeck_snake` runs the game by its shebang instead of stopping

- [ ] **Step 3: Implement. Makefile, a mechanical rewrite plus the guard**

From the checkout root, run this rewrite once. It does four things:
1. Inserts `STREAMDECK_PY` and the guard rule after the header.
2. Rewrites every `./script/stream_deck/<x>.py` and every `python3 ` in recipe lines to `$(STREAMDECK_PY) …`. This covers the 45 games, the tiler, the controller, the gallery, translator_{doctor,test,stream}, the `--recommend` call inside `$$(…)` and both `-m unittest` targets. The lines that run `po/compile_locales.py` are skipped: the locale compiler is not deck code and keeps the system `python3`.
3. Turns `pip install --user vosk` into `$(STREAMDECK_PY) -m pip install vosk`.
4. Adds `$(STREAMDECK_PY)` as a prerequisite to every target whose recipe now uses it.

```bash
python3 - <<'EOF'
import re
from pathlib import Path

mk = Path("conf/make.streamdeck.Makefile")
text = mk.read_text(encoding="utf-8")

header = "##############\n# STREAMDECK #\n##############\n\n"
guard = (
    "# Interpreter of the dedicated Stream Deck venv. Every deck entry point\n"
    "# runs under it explicitly: a shebang cannot name a path relative to\n"
    "# the checkout.\n"
    "STREAMDECK_PY := .venv.streamdeck/bin/python\n"
    "\n"
    "# A target that runs deck code lists $(STREAMDECK_PY) as a prerequisite.\n"
    "# The file has no prerequisite of its own, so make runs this recipe only\n"
    "# when the venv is missing, and the target stops there with the command\n"
    "# that builds it.\n"
    "$(STREAMDECK_PY):\n"
    '\t@echo "Stream Deck venv missing: make erplibre_home_streamdeck_install" >&2\n'
    "\t@exit 1\n"
    "\n"
)
assert text.startswith(header), "unexpected header"
text = header + guard + text[len(header):]

text = text.replace(
    "pip install --user vosk", "$(STREAMDECK_PY) -m pip install vosk"
)

out = []
for line in text.split("\n"):
    # The locale compiler is not deck code: it keeps the system python3.
    if line.startswith("\t") and "compile_locales.py" not in line:
        line = re.sub(
            r"\./script/stream_deck/(\w+\.py)",
            r"$(STREAMDECK_PY) script/stream_deck/\1",
            line,
        )
        line = re.sub(r"\bpython3 ", "$(STREAMDECK_PY) ", line)
    out.append(line)
text = "\n".join(out)

blocks = re.split(r"(?m)^(?=[A-Za-z_][A-Za-z0-9_]*:)", text)
fixed = []
for block in blocks:
    m = re.match(r"([A-Za-z_][A-Za-z0-9_]*):[ \t]*\n", block)
    if m and "$(STREAMDECK_PY)" in block[m.end():].split("\n\n")[0]:
        block = f"{m.group(1)}: $(STREAMDECK_PY)\n" + block[m.end():]
    fixed.append(block)
mk.write_text("".join(fixed), encoding="utf-8")
EOF
```

The rewrite produces 55 guarded targets: 46 `game_*` (45 games plus the tiler), plus `streamdeck`, `streamdeck_gallery`, `streamdeck_translator_{doctor,test,stream,unittest,install_ollama,install_vosk_fr}` and `streamdeck_tiler_unittest`. `erplibre_home_compile_locale` and `erplibre_home_install_extension` keep their `python3 …/po/compile_locales.py` lines and get no prerequisite. The line that opens `erplibre_home_install_extension`, `@"$(ERPLIBRE_HOME_EXT_SRC)/tools/migrate_legacy.py" || echo "legacy migration did not run" >&2`, calls the migration by its path: neither rewrite touches it, and it keeps running under the system python, before any venv exists. Typical results:

```make
.PHONY: streamdeck_snake
streamdeck_snake: $(STREAMDECK_PY)
	$(STREAMDECK_PY) script/stream_deck/game_snake.py
```

```make
	@model=$$($(STREAMDECK_PY) script/stream_deck/translator_doctor.py --recommend); \
```

Check that nothing is left. The first command must print nothing and end with `rc=1`. The second prints only the three lines of the locale compiler (two in `erplibre_home_install_extension`, the second of them its `python3-polib` hint, and one in `erplibre_home_compile_locale`). The third prints `55`:

```bash
grep -nE '\./script/stream_deck/[A-Za-z0-9_]+\.py|pip install --user' conf/make.streamdeck.Makefile; echo "rc=$?"
grep -n 'python3' conf/make.streamdeck.Makefile
grep -c '^[a-z_0-9]*: \$(STREAMDECK_PY)$' conf/make.streamdeck.Makefile
```

Check the guard by hand. The first command prints the one line `Stream Deck venv missing: make erplibre_home_streamdeck_install`, then make's own error line, and `rc=2`. The second prints `script/stream_deck/game_snake.py`:

```bash
make -s streamdeck_snake STREAMDECK_PY=/nonexistent/python; echo "rc=$?"
make -s streamdeck_snake STREAMDECK_PY=/bin/echo
```

- [ ] **Step 4: Implement. requirements.txt**

Replace the whole of `script/stream_deck/requirements.txt` with this content. `lz4` leaves the file, because the Firefox tab importer runs under the system `python3`. `polib` and its comment stay as they are: the spec asks for no change to them.

```
streamdeck
pyudev
Pillow>=9.0.0
opencv-python
# HTTP client of the controller (erplibre_controller.py).
requests
# Key events of keyboard_talk.py.
keyboard
# i18n compile helper for erplibre_home_compile_locale.
polib
```

- [ ] **Step 5: Implement. gallery_server.py**

At `script/stream_deck/gallery_server.py:18-19`, replace:

```python
import os
import signal
```
with:
```python
import os
import shlex
import signal
```

Insert this function right before line 97, `class GameHandler(http.server.SimpleHTTPRequestHandler):`, leaving two blank lines on each side:

```python
def _game_bash_cmd(game_file):
    """Return the bash command that runs game_file in a terminal.

    The game runs under sys.executable, the interpreter of this server, so
    it gets the server's venv instead of the python its shebang finds on
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
        f'or enter to close..."; '
        f"read -r ans; "
        f'if [ "$ans" != "r" ] && [ "$ans" != "R" ]; then break; fi; '
        f"done"
    )
```

In `_launch_game` (old lines 253-265), replace:

```python
        print(f"Launching game: {game_id}")
        # Loop so the user can restart the game by typing "r" + Enter at the
        # end-of-game prompt — avoids re-picking it from the gallery.
        bash_cmd = (
            f"cd {ERPLIBRE_DIR} && while true; do "
            f"python3 {game_file}; "
            f'echo ""; '
            f'echo "Game ended. Press [r]+enter to restart, '
            f'or enter to close..."; '
            f"read -r ans; "
            f'if [ "$ans" != "r" ] && [ "$ans" != "R" ]; then break; fi; '
            f"done"
        )
```
with:
```python
        print(f"Launching game: {game_id}")
        bash_cmd = _game_bash_cmd(game_file)
```

Do not run `ruff format` on `gallery_server.py` or `todo.py`. Neither file is ruff-clean today, so a whole-file reformat would bury this change.

- [ ] **Step 6: Implement. todo.py**

After `script/todo/todo.py:58`, `VENV_PYTHON = os.path.join(VENV_DIR, "bin", "python")`, insert:

```python
# Interpréteur du venv dédié au Stream Deck. Les jeux tournent sous lui et
# non par leur shebang : un shebang ne peut pas nommer un chemin relatif au
# checkout, et le python du système n'a pas les modules du deck.
VENV_STREAMDECK_PYTHON = os.path.join(
    new_path, ".venv.streamdeck", "bin", "python"
)
```

At the top of `prompt_execute_streamdeck_games` (lines 1830-1831), replace:

```python
    def prompt_execute_streamdeck_games(self):
        print(f"🎮 {t('Stream Deck games! Choose a game to play.')}")
```
with:
```python
    def prompt_execute_streamdeck_games(self):
        # Seul le niveau Stream Deck de l'installateur crée .venv.streamdeck :
        # sans lui, aucun jeu ne démarre, et le menu dit quelle commande
        # l'ajoute au lieu d'en lancer un.
        if not os.access(VENV_STREAMDECK_PYTHON, os.X_OK):
            print(
                t(
                    "ERPLibre Home Stream Deck is not installed:"
                    " make erplibre_home_streamdeck_install"
                )
            )
            return False
        print(f"🎮 {t('Stream Deck games! Choose a game to play.')}")
```

In the same method (line 1857 before this edit), replace:

```python
                        self.execute.exec_command_live(
                            game["path"],
                            source_erplibre=False,
                        )
```
with:
```python
                        self.execute.exec_command_live(
                            self._streamdeck_game_command(game["path"]),
                            source_erplibre=False,
                        )
```

Insert this method right before line 1867, `def _scan_streamdeck_games(self):`:

```python
    def _streamdeck_game_command(self, path):
        """Rend la commande shell qui lance le jeu `path` sous le python de
        .venv.streamdeck ; les deux chemins sont cités pour bash."""
        return f"{shlex.quote(VENV_STREAMDECK_PYTHON)} {shlex.quote(path)}"

```

`shlex` is already imported at `todo.py:15`.

In `script/todo/todo_i18n.py`, after the `"No Stream Deck games found."` entry (lines 116-119) and before `"Launching game:"`, insert the key. Task 5 anchors its own keys on `"Launching game:"`, after it, so the two edits do not overlap:

```python
    "ERPLibre Home Stream Deck is not installed:"
    " make erplibre_home_streamdeck_install": {
        "fr": "ERPLibre Home Stream Deck n'est pas installé :"
        " make erplibre_home_streamdeck_install",
        "en": "ERPLibre Home Stream Deck is not installed:"
        " make erplibre_home_streamdeck_install",
    },
```

- [ ] **Step 7: Implement. Remove launch_game.sh**

```bash
grep -rn "launch_game.sh" --include='*.py' --include='*.js' --include='*.html' --include='*.md' --include='*.sh' --include='*Makefile' script conf test | grep -v "^script/stream_deck/launch_game.sh:"; git rm -q script/stream_deck/launch_game.sh
```

The grep must print nothing. The only other hits are `gallery_server.py`'s own `_launch_game` method and the spec, and neither names `launch_game.sh`.

- [ ] **Step 8: Run tests to verify they pass**

```bash
.venv.erplibre/bin/ruff format test/test_streamdeck_entry_points.py && .venv.erplibre/bin/ruff check --select I test/test_streamdeck_entry_points.py
./script/test/run_unit_test.sh test/test_streamdeck_entry_points.py test/test_todo_menu.py test/test_todo_i18n.py test/test_i18n_duplicates.py test/test_erplibre_home_enable_target.py
python3 script/analyse/check_comment_hygiene.py test/test_streamdeck_entry_points.py script/stream_deck/gallery_server.py script/todo/todo.py
```

Expected:
- `1 file left unchanged` and `All checks passed!`
- `test_streamdeck_entry_points.py 20 tests OK`, `test_todo_menu.py 54 tests OK`, `test_todo_i18n.py 24 tests OK`, `test_i18n_duplicates.py 3 tests OK`, `test_erplibre_home_enable_target.py 10 tests OK`, `111 tests, tout vert`
- No 🔴 finding from the hygiene check.

- [ ] **Step 9: Commit**

```bash
git add conf/make.streamdeck.Makefile script/stream_deck/requirements.txt script/stream_deck/gallery_server.py script/todo/todo.py script/todo/todo_i18n.py test/test_streamdeck_entry_points.py
cat > $SCRATCH/task1_msg.txt <<'EOF'
[FIX] stream_deck: run every entry point under .venv.streamdeck

Deck scripts started by their shebang take the system python, which lacks
StreamDeck, cv2, requests and keyboard, so they fail at import. Every deck
make target runs $(STREAMDECK_PY) and, without the venv, stops on make
erplibre_home_streamdeck_install; the TODO games entry says the same and
launches nothing. The gallery runs a game under its own interpreter. The
locale compiler keeps the system python. requirements.txt gains requests
and keyboard, drops lz4; launch_game.sh goes.

--- FR ---

[FIX] stream_deck : chaque point d'entrée tourne sous .venv.streamdeck

Lancés par leur shebang, les scripts du deck prennent le python du système,
privé de StreamDeck, cv2, requests et keyboard : ils tombent à l'import.
Chaque cible make du deck passe par $(STREAMDECK_PY) et, sans venv,
s'arrête sur make erplibre_home_streamdeck_install ; l'entrée des jeux de
TODO le dit aussi et ne lance rien. La galerie lance un jeu sous son
propre interpréteur. Le compilateur des locales garde le python du système.
requirements.txt gagne requests et keyboard, perd lz4 ; launch_game.sh part.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/task1_msg.txt && git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/task1_msg.txt
```

The deletion of `launch_game.sh` is already staged by Step 7's `git rm`; naming the path in `git add` would fail (pathspec did not match) and stage nothing. The message passes `script/git/hooks/commit-msg` (exit 0, subject 63 characters).

*Drafting notes (not part of the task):*
- **Dry-run:** all of the above was run on a `git archive` copy of `dc841639`, and no repo file was edited. The test went red first (`failures=12, errors=6`), then reached 111/111 green with the i18n and enable-target suites, and the make guard behaved as described.

---

### Task 2: Extension project root resolves the symlink, deck venv and its absence

**Files:**
- Create: `script/gnome-extension/erplibre_home/lib/project-root.js`
- Create: `script/gnome-extension/erplibre_home/test/unit/project-root.test.js`
- Modify: `script/gnome-extension/erplibre_home/indicators/device.js:13-14` (import), `:149-164` (`_projectRoot`, `_launchController`)
- Modify: `script/gnome-extension/erplibre_home/indicators/erplibre.js:14` (import), `:452-458` (`_autoLoginSelenium` fallback)
- Modify: `script/gnome-extension/erplibre_home/po/erplibre-home.pot:809`, `po/en.po:845-846`, `po/fr.po:848-849`
- Modify: `script/gnome-extension/erplibre_home/indicators/controller.js:17` (import), `:199-212` (`_launchGalleryAt`)
- Modify: `script/gnome-extension/erplibre_home/CHANGELOG.md:67` (one `### Fixed` bullet)
- Test: `script/gnome-extension/erplibre_home/test/unit/project-root.test.js` (run by `make test_gnome_extension`)

**Interfaces:**
- Consumes: Gio, which `indicators/device.js` and `indicators/erplibre.js` already import statically (line 2 in both). It is passed in, and the new module never imports `gi://`.
- Produces: `lib/project-root.js` exports `projectRootFrom(path, readLink) -> string` and `makeGioReadLink(Gio) -> (p) => string|null`. It also exports the helpers `normalizePath(path)` and `resolveLinkTarget(linkPath, target)`, the constant `STREAMDECK_PYTHON_REL = '.venv.streamdeck/bin/python'`, and `streamDeckPython(root, fileExists) -> string|null`: `<root>/.venv.streamdeck/bin/python` when `fileExists` says it is there, else `null` (also for an empty root, or a `fileExists` that throws).
- `device.js` `_launchController` and `controller.js` `_launchGalleryAt` call `streamDeckPython` at the click, with `(p) => GLib.file_test(p, GLib.FileTest.IS_EXECUTABLE)`; `device.js` passes its `projectRootFrom` root, `controller.js` the path from its settings. On `null` they notify the msgid `ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install` (fr: `ERPLibre Home Stream Deck n'est pas installé : make erplibre_home_streamdeck_install`) and spawn nothing. That msgid replaces `Python venv not found at .venv.erplibre` in the `.pot` and both catalogs; it is the English text of Task 1's TODO i18n key. `erplibre.js` keeps `.venv.erplibre`.

Notes checked against the real code:
- `HotReload()` (`extension.js:1130`) runs `cp -r "<extensions>/erplibre-home@technolibre.ca" "<extensions>/erplibre-home-reload-<ms>@technolibre.ca"`. GNU `cp -r` copies a symlink operand as a symlink (checked), so the reload directory is also a link to the checkout.
- The `.mo` files are gitignored (`script/gnome-extension/erplibre_home/.gitignore`: `locale/`), so nothing compiled gets committed.
- The installer (Task 4) compiles the catalogs with `msgfmt --check`, not with `po/compile_locales.py`. This task checks them the same way: `msgfmt --check` prints warnings about header fields (`Project-Id-Version`, `PO-Revision-Date`…) that the catalogs do not carry, and still exits 0.
- Today's baseline: `make test_gnome_extension` gives `tests 216, pass 216`.

- [ ] **Step 1: Write the failing test**

Create `script/gnome-extension/erplibre_home/test/unit/project-root.test.js`. Its last two tests read the catalogs and the two indicators from disk: they stay red until Steps 5-7.

```js
import {test} from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {projectRootFrom, makeGioReadLink, normalizePath, resolveLinkTarget,
    streamDeckPython} from '../../lib/project-root.js';

const CHECKOUT = '/opt/depot';
const EXT_SRC = `${CHECKOUT}/script/gnome-extension/erplibre_home`;
const EXT_DIR = '/opt/maison/.local/share/gnome-shell/extensions';
const LINK = `${EXT_DIR}/erplibre-home@technolibre.ca`;

// readLink stub: a table of link path -> target, null for anything else.
function linksTo(table) {
    const calls = [];
    const readLink = (p) => {
        calls.push(p);
        return Object.prototype.hasOwnProperty.call(table, p)
            ? table[p] : null;
    };
    readLink.calls = calls;
    return readLink;
}

test('normalizePath folds . and .. segments', () => {
    assert.equal(normalizePath('/a/./b/../c/'), '/a/c');
    assert.equal(normalizePath('/../a'), '/a');
    assert.equal(normalizePath('a/../../b'), '../b');
    assert.equal(normalizePath('/'), '/');
});

test('resolveLinkTarget keeps absolute and joins relative targets', () => {
    assert.equal(resolveLinkTarget('/x/y/link', '/t/u'), '/t/u');
    assert.equal(resolveLinkTarget('/x/y/link', '../t'), '/x/t');
    assert.equal(resolveLinkTarget('/link', 't'), '/t');
});

test('direct path: same result as the former regex', () => {
    const readLink = linksTo({});
    assert.equal(projectRootFrom(EXT_SRC, readLink), CHECKOUT);
    assert.equal(projectRootFrom(`${EXT_SRC}/`, readLink), CHECKOUT);
    assert.deepEqual(readLink.calls, [EXT_SRC, EXT_SRC]);
});

test('direct path without readLink: same result as the former regex', () => {
    assert.equal(projectRootFrom(EXT_SRC), CHECKOUT);
    assert.equal(projectRootFrom(EXT_SRC, null), CHECKOUT);
});

test('path without the extension suffix comes back unchanged', () => {
    assert.equal(projectRootFrom('/opt/ailleurs/', linksTo({})),
        '/opt/ailleurs/');
});

test('absolute symlink: root of the link target', () => {
    assert.equal(projectRootFrom(LINK, linksTo({[LINK]: EXT_SRC})),
        CHECKOUT);
});

test('absolute symlink with a trailing slash on both sides', () => {
    assert.equal(projectRootFrom(`${LINK}/`, linksTo({[LINK]: `${EXT_SRC}/`})),
        CHECKOUT);
});

test('relative symlink: resolved against the link parent', () => {
    const target = '../../../../../depot/script/gnome-extension/erplibre_home';
    assert.equal(projectRootFrom(LINK, linksTo({[LINK]: target})), CHECKOUT);
});

test('hot-reload uuid dir: a copy of the link, same root', () => {
    const reload =
        `${EXT_DIR}/erplibre-home-reload-1700000000000@technolibre.ca`;
    assert.equal(projectRootFrom(reload, linksTo({[reload]: EXT_SRC})),
        CHECKOUT);
});

test('chained symlinks are followed', () => {
    const middle = '/opt/liens/extension';
    const readLink = linksTo({[LINK]: middle, [middle]: EXT_SRC});
    assert.equal(projectRootFrom(LINK, readLink), CHECKOUT);
});

test('a symlink cycle stops after a bounded number of hops', () => {
    const readLink = linksTo({[LINK]: 'erplibre-home@technolibre.ca'});
    assert.equal(projectRootFrom(LINK, readLink), LINK);
    assert.equal(readLink.calls.length, 8);
});

test('a readLink that throws counts as no symlink', () => {
    const readLink = () => { throw new Error('EACCES'); };
    assert.equal(projectRootFrom(EXT_SRC, readLink), CHECKOUT);
});

test('empty or non-string path gives an empty root', () => {
    assert.equal(projectRootFrom('', linksTo({})), '');
    assert.equal(projectRootFrom(undefined, linksTo({})), '');
});

// Gio stub: answers from a link table, records the query_info arguments.
function fakeGio({targets = {}, fail = false} = {}) {
    const seen = [];
    return {
        seen,
        FileQueryInfoFlags: {NOFOLLOW_SYMLINKS: 'nofollow'},
        File: {
            new_for_path: (p) => ({
                query_info: (attr, flags, cancellable) => {
                    seen.push({p, attr, flags, cancellable});
                    if (fail) throw new Error('No such file or directory');
                    return {get_symlink_target: () => targets[p] ?? null};
                },
            }),
        },
    };
}

test('makeGioReadLink returns the target, queried without following', () => {
    const Gio = fakeGio({targets: {[LINK]: EXT_SRC}});
    assert.equal(makeGioReadLink(Gio)(LINK), EXT_SRC);
    assert.deepEqual(Gio.seen, [{p: LINK, attr: 'standard::symlink-target',
        flags: 'nofollow', cancellable: null}]);
});

test('makeGioReadLink returns null for a non-symlink', () => {
    assert.equal(makeGioReadLink(fakeGio())(EXT_SRC), null);
});

test('makeGioReadLink returns null when Gio throws', () => {
    assert.equal(makeGioReadLink(fakeGio({fail: true}))('/opt/absent'), null);
});

test('makeGioReadLink plugs into projectRootFrom', () => {
    const readLink = makeGioReadLink(fakeGio({targets: {[LINK]: EXT_SRC}}));
    assert.equal(projectRootFrom(LINK, readLink), CHECKOUT);
});

// fileExists stub: true only for the paths listed, records each call.
function existing(...paths) {
    const calls = [];
    const fileExists = (p) => {
        calls.push(p);
        return paths.includes(p);
    };
    fileExists.calls = calls;
    return fileExists;
}

const DECK_PYTHON = `${CHECKOUT}/.venv.streamdeck/bin/python`;

test('streamDeckPython returns the venv python when it is present', () => {
    const fileExists = existing(DECK_PYTHON);
    assert.equal(streamDeckPython(CHECKOUT, fileExists), DECK_PYTHON);
    assert.deepEqual(fileExists.calls, [DECK_PYTHON]);
});

test('streamDeckPython returns null when the venv is absent', () => {
    assert.equal(streamDeckPython(CHECKOUT, existing()), null);
});

test('streamDeckPython tolerates a trailing slash on the root', () => {
    assert.equal(streamDeckPython(`${CHECKOUT}/`, existing(DECK_PYTHON)),
        DECK_PYTHON);
});

test('streamDeckPython: no root, or a fileExists that throws, gives null', () => {
    const fileExists = existing(DECK_PYTHON);
    assert.equal(streamDeckPython('', fileExists), null);
    assert.equal(streamDeckPython(undefined, fileExists), null);
    assert.deepEqual(fileExists.calls, []);
    assert.equal(streamDeckPython(CHECKOUT,
        () => { throw new Error('EACCES'); }), null);
});

// The message the device and controller indicators show without the venv.
const NOT_INSTALLED =
    'ERPLibre Home Stream Deck is not installed: ' +
    'make erplibre_home_streamdeck_install';
const OLD_MSGID = 'Python venv not found at .venv.erplibre';

function extensionFile(rel) {
    return readFileSync(new URL(`../../${rel}`, import.meta.url), 'utf8');
}

// msgstr of `msgid` in a catalog, or undefined when the msgid is absent.
function msgstrOf(catalog, msgid) {
    const quoted = JSON.stringify(msgid);
    const at = catalog.indexOf(`msgid ${quoted}\n`);
    if (at < 0) return undefined;
    const rest = catalog.slice(at).split('\n')[1];
    return JSON.parse(rest.replace(/^msgstr /, ''));
}

test('missing-venv message: a msgid of the .pot, translated in fr and en', () => {
    assert.equal(msgstrOf(extensionFile('po/erplibre-home.pot'),
        NOT_INSTALLED), '');
    assert.equal(msgstrOf(extensionFile('po/en.po'), NOT_INSTALLED),
        NOT_INSTALLED);
    assert.equal(msgstrOf(extensionFile('po/fr.po'), NOT_INSTALLED),
        "ERPLibre Home Stream Deck n'est pas installé : " +
        'make erplibre_home_streamdeck_install');
    for (const po of ['po/erplibre-home.pot', 'po/en.po', 'po/fr.po'])
        assert.equal(msgstrOf(extensionFile(po), OLD_MSGID), undefined, po);
});

test('both deck indicators show that message, and only through _()', () => {
    for (const js of ['indicators/device.js', 'indicators/controller.js']) {
        const src = extensionFile(js);
        assert.ok(src.includes(`_('${NOT_INSTALLED}')`), js);
        assert.ok(src.includes('streamDeckPython('), js);
        assert.ok(!src.includes('.venv.erplibre'), js);
    }
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --test script/gnome-extension/erplibre_home/test/unit/project-root.test.js`
Expected: FAIL with `Error [ERR_MODULE_NOT_FOUND]: Cannot find module '.../script/gnome-extension/erplibre_home/lib/project-root.js' imported from .../test/unit/project-root.test.js`

- [ ] **Step 3: Implement `lib/project-root.js`**

Create `script/gnome-extension/erplibre_home/lib/project-root.js`:

```js
/**
 * Project root of the checkout that holds this extension.
 *
 * GNOME Shell reports `extension.path` as the directory under
 * ~/.local/share/gnome-shell/extensions, and that directory is a symlink
 * to <checkout>/script/gnome-extension/erplibre_home (the hot-reload copy
 * too: `cp -r` copies the link, not the tree). The root is read on the
 * link target, not on the link path.
 *
 * Pure: the filesystem is reached only through the injected `readLink`,
 * so node --test loads this module without any gi:// import.
 */

const EXTENSION_SUFFIX_RE = /\/script\/gnome-extension\/erplibre_home\/?$/;

// Bound on chained links; a link cycle stops here instead of looping.
const MAX_LINK_HOPS = 8;

/**
 * Lexical normalisation: drops empty and `.` segments, folds `..` into
 * its parent. The parent directories are taken as written, like
 * `realpath -s`, not re-resolved on disk.
 */
export function normalizePath(path) {
    const absolute = path.startsWith('/');
    const out = [];
    for (const part of path.split('/')) {
        if (part === '' || part === '.') continue;
        if (part === '..') {
            if (out.length && out[out.length - 1] !== '..') out.pop();
            else if (!absolute) out.push('..');
            continue;
        }
        out.push(part);
    }
    const joined = out.join('/');
    if (absolute) return `/${joined}`;
    return joined || '.';
}

/**
 * Absolute path a link points to: an absolute target is kept, a relative
 * one is joined to the directory that contains the link.
 */
export function resolveLinkTarget(linkPath, target) {
    if (target.startsWith('/')) return normalizePath(target);
    const parent = linkPath.replace(/\/[^/]*$/, '') || '/';
    return normalizePath(`${parent}/${target}`);
}

function _readLinkOrNull(readLink, path) {
    if (typeof readLink !== 'function') return null;
    try {
        const target = readLink(path);
        return typeof target === 'string' && target !== '' ? target : null;
    } catch (_e) {
        return null;
    }
}

/**
 * Checkout root for an extension path.
 *
 * `readLink(p)` returns the symlink target of `p` (absolute or relative),
 * or null when `p` is not a symlink. Links are followed up to
 * MAX_LINK_HOPS, then the /script/gnome-extension/erplibre_home suffix is
 * stripped (trailing slash tolerated). A path that is not a symlink
 * gives exactly `path` minus that suffix; a path without the suffix
 * comes back resolved but otherwise unchanged.
 */
export function projectRootFrom(path, readLink) {
    if (typeof path !== 'string' || path === '') return '';
    let current = path;
    for (let hop = 0; hop < MAX_LINK_HOPS; hop++) {
        const link = current.length > 1 ? current.replace(/\/+$/, '') : current;
        const target = _readLinkOrNull(readLink, link);
        if (target === null) break;
        current = resolveLinkTarget(link, target);
    }
    return current.replace(EXTENSION_SUFFIX_RE, '');
}

/**
 * GJS `readLink` for projectRootFrom, built on the Gio namespace the
 * caller already imported. It queries `standard::symlink-target` without
 * following the link; a missing file, a non-link or any Gio error
 * gives null.
 */
export function makeGioReadLink(Gio) {
    return (path) => {
        try {
            const info = Gio.File.new_for_path(path).query_info(
                'standard::symlink-target',
                Gio.FileQueryInfoFlags.NOFOLLOW_SYMLINKS, null);
            return info.get_symlink_target() || null;
        } catch (_e) {
            return null;
        }
    };
}

// Interpreter of the Stream Deck venv, relative to the checkout root. Only
// the Stream Deck level of install_erplibre_home.sh creates it.
export const STREAMDECK_PYTHON_REL = '.venv.streamdeck/bin/python';

/**
 * Python of the Stream Deck venv under `root`, or null when it is absent.
 *
 * `fileExists(p)` tells whether the interpreter at `p` can be started; a
 * fileExists that throws counts as absent. An empty root gives null
 * without asking. The indicators call this at the time of the action, so a
 * Stream Deck level added after the session started is found.
 */
export function streamDeckPython(root, fileExists) {
    if (typeof root !== 'string' || root === '') return null;
    const base = root.length > 1 ? root.replace(/\/+$/, '') : root;
    const python = `${base}/${STREAMDECK_PYTHON_REL}`;
    try {
        return fileExists(python) ? python : null;
    } catch (_e) {
        return null;
    }
}
```

- [ ] **Step 4: Run the new test: the module's tests pass**

Run: `node --test script/gnome-extension/erplibre_home/test/unit/project-root.test.js`
Expected: `ℹ tests 23`, `ℹ pass 21`, `ℹ fail 2`. The two that fail are `missing-venv message: a msgid of the .pot, translated in fr and en` and `both deck indicators show that message, and only through _()`: Steps 5-7 make them pass.

- [ ] **Step 5: Wire `device.js` (root through the link, deck venv, its absence)**

In `script/gnome-extension/erplibre_home/indicators/device.js`, lines 12-14, before:

```js
import {makeBadgedIcon, bindBadgeOrientation, attachHoverTooltip,
    formatBadgeTooltip} from '../lib/badges.js';
import {_} from '../lib/i18n.js';
```

after:

```js
import {makeBadgedIcon, bindBadgeOrientation, attachHoverTooltip,
    formatBadgeTooltip} from '../lib/badges.js';
import {projectRootFrom, makeGioReadLink, streamDeckPython}
    from '../lib/project-root.js';
import {_} from '../lib/i18n.js';
```

Lines 149-164, before:

```js
    _projectRoot() {
        return this._extension.path.replace(
            /\/script\/gnome-extension\/erplibre_home\/?$/, '');
    }

    _launchController() {
        const root = this._projectRoot();
        const py = `${root}/.venv.erplibre/bin/python`;
        const script = `${root}/${CONTROLLER_REL}`;
        if (!GLib.file_test(py, GLib.FileTest.IS_EXECUTABLE)) {
            _notify('Stream Deck',
                _('Python venv not found at .venv.erplibre'));
            return;
        }
        spawnDetached([py, script], {notify: _notify, title: 'Stream Deck'});
    }
```

after:

```js
    _projectRoot() {
        // extension.path is the link under gnome-shell/extensions; the
        // checkout root is derived from the link target.
        return projectRootFrom(this._extension.path, makeGioReadLink(Gio));
    }

    _launchController() {
        const root = this._projectRoot();
        // .venv.streamdeck exists only once the Stream Deck level is
        // installed. It is looked up at the click, not in enable(), so a
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
```

The msgid stays on one line, inside `_()`, so the catalogs and the test find it whole.

- [ ] **Step 6: Wire the `erplibre.js` selenium fallback (it keeps `.venv.erplibre`)**

In `script/gnome-extension/erplibre_home/indicators/erplibre.js`, line 14, before:

```js
import {detectLocalInstancesGjs} from '../lib/erplibre-detect.js';
```

after:

```js
import {detectLocalInstancesGjs} from '../lib/erplibre-detect.js';
import {projectRootFrom, makeGioReadLink} from '../lib/project-root.js';
```

Lines 452-458, before:

```js
    _autoLoginSelenium(inst, user, pass) {
        // Resolve project root: assume extension lives in
        //   script/gnome-extension/erplibre_home; root is three dirs up.
        const home = GLib.get_home_dir();
        const root = this._settings.get_string('git-sync-path').trim()
            || this._extension.path.replace(
                /\/script\/gnome-extension\/erplibre_home\/?$/, '');
```

after:

```js
    _autoLoginSelenium(inst, user, pass) {
        // Project root: the git-sync-path setting, else the checkout the
        // extension link points to (lib/project-root.js).
        const home = GLib.get_home_dir();
        const root = this._settings.get_string('git-sync-path').trim()
            || projectRootFrom(this._extension.path, makeGioReadLink(Gio));
```

(Lines 459-470 do not change: `venv` stays `${root}/.venv.erplibre/bin/python`, and the xdotool fallback stays as it is.)

- [ ] **Step 6b: The gallery launcher checks the deck venv and lets make pick it**

`script/gnome-extension/erplibre_home/indicators/controller.js`, lines 16-17, before:
```js
import {buildTerminalArgv, findTerminal, spawnDetached}
    from '../lib/spawn.js';
```
after:
```js
import {buildTerminalArgv, findTerminal, spawnDetached}
    from '../lib/spawn.js';
import {streamDeckPython} from '../lib/project-root.js';
```

Lines 199-212, before:
```js
    async _launchGalleryAt(cwd) {
        const terminal = await findTerminal();
        if (!terminal) {
            _notify(PROJECT_NAME,
                _('No terminal found. Install gnome-terminal, kgx or xterm.'));
            return;
        }
        const argv = buildTerminalArgv({
            cwd,
            command:
                'source .venv.erplibre/bin/activate && ' +
                'make streamdeck_gallery',
            terminal,
        });
```
after:
```js
    async _launchGalleryAt(cwd) {
        // make streamdeck_gallery runs the gallery under .venv.streamdeck,
        // which only the Stream Deck level creates. It is looked up under
        // the configured path at the click, so a level added after the
        // session started is found.
        if (streamDeckPython(cwd,
            (p) => GLib.file_test(p, GLib.FileTest.IS_EXECUTABLE)) === null) {
            _notify(PROJECT_NAME,
                _('ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install'));
            return;
        }
        const terminal = await findTerminal();
        if (!terminal) {
            _notify(PROJECT_NAME,
                _('No terminal found. Install gnome-terminal, kgx or xterm.'));
            return;
        }
        const argv = buildTerminalArgv({
            cwd,
            command: 'make streamdeck_gallery',
            terminal,
        });
```

`controller.js` already imports `GLib` (line 6).

- [ ] **Step 7: Update the catalogs**

`script/gnome-extension/erplibre_home/po/erplibre-home.pot`, lines 809-810, before:

```
msgid "Python venv not found at .venv.erplibre"
msgstr ""
```

after:

```
msgid "ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install"
msgstr ""
```

`script/gnome-extension/erplibre_home/po/en.po`, lines 845-846, before:

```
msgid "Python venv not found at .venv.erplibre"
msgstr "Python venv not found at .venv.erplibre"
```

after:

```
msgid "ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install"
msgstr "ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install"
```

`script/gnome-extension/erplibre_home/po/fr.po`, lines 848-849, before:

```
msgid "Python venv not found at .venv.erplibre"
msgstr "Venv Python introuvable dans .venv.erplibre"
```

after:

```
msgid "ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install"
msgstr "ERPLibre Home Stream Deck n'est pas installé : make erplibre_home_streamdeck_install"
```

`script/gnome-extension/erplibre_home/CHANGELOG.md`: after line 67 (`  metadata.json in place — fewer accidental git diffs.`), at the end of `### Fixed` under `[Unreleased]`, add:

```markdown
- Device indicator finds the checkout through the extension symlink
  (installed link and hot-reload copy alike) and launches the
  controller with `.venv.streamdeck`; the gallery launcher runs
  `make streamdeck_gallery`. Without that venv, both say that
  ERPLibre Home Stream Deck is not installed and name
  `make erplibre_home_streamdeck_install`, instead of failing.
```

- [ ] **Step 8: Check the catalogs as the installer compiles them**

Run:
```bash
cd script/gnome-extension/erplibre_home
for f in po/fr.po po/en.po; do msgfmt --check -o /dev/null "$f" 2>/dev/null && echo "$f ok"; done
msgfmt --check-format -o /dev/null po/erplibre-home.pot && echo "pot ok"
grep -c 'ERPLibre Home Stream Deck is not installed: make erplibre_home_streamdeck_install' po/fr.po po/en.po po/erplibre-home.pot
grep -c 'Python venv not found at .venv.erplibre' po/fr.po po/en.po po/erplibre-home.pot
cd "$(git rev-parse --show-toplevel)"
git check-ignore -q script/gnome-extension/erplibre_home/locale/fr/LC_MESSAGES/erplibre-home.mo && echo "mo ignored"
```
Expected: `po/fr.po ok`, `po/en.po ok` and `pot ok` (the `.pot` is a template, checked for its format only). The first grep prints `:1` per file and the second prints `:0` per file. Last line: `mo ignored`.

- [ ] **Step 9: Run the full extension suite and syntax-check the touched GJS files**

Run:
```bash
cd "$(git rev-parse --show-toplevel)"
node --check script/gnome-extension/erplibre_home/indicators/device.js
node --check script/gnome-extension/erplibre_home/indicators/erplibre.js
node --check script/gnome-extension/erplibre_home/lib/project-root.js
node --check script/gnome-extension/erplibre_home/indicators/controller.js
grep -c 'venv.erplibre' script/gnome-extension/erplibre_home/indicators/controller.js
grep -n 'erplibre_home\\/?' script/gnome-extension/erplibre_home/indicators/*.js || echo "no leftover suffix regex"
grep -n 'venv' script/gnome-extension/erplibre_home/indicators/device.js
make test_gnome_extension
python3 script/analyse/check_comment_hygiene.py script/gnome-extension/erplibre_home/lib/project-root.js script/gnome-extension/erplibre_home/test/unit/project-root.test.js script/gnome-extension/erplibre_home/indicators/device.js script/gnome-extension/erplibre_home/indicators/controller.js
```
Expected: the four `node --check` produce no output (exit 0), and the `controller.js` grep prints `0`. Then `no leftover suffix regex`. The `device.js` grep shows one line, the comment `// .venv.streamdeck exists only once the Stream Deck level is` (line 159): the path itself now comes from `streamDeckPython`. `make test_gnome_extension` ends with `ℹ tests 239`, `ℹ pass 239`, `ℹ fail 0`, which is the 216 baseline plus 23. The hygiene check reports nothing and exits 0.

- [ ] **Step 10: Commit**

Write the message to the scratchpad, validate it, then commit:

```bash
cd "$(git rev-parse --show-toplevel)"
MSG=$SCRATCH/msg_task2.txt
cat > "$MSG" <<'EOF'
[FIX] gnome extension: extension root follows symlink, deck venv

GNOME Shell reports extension.path as the link under
~/.local/share/gnome-shell/extensions, so stripping the extension suffix
from it never matched and the controller looked for its venv in the wrong
place. lib/project-root.js resolves the link before stripping, and
streamDeckPython finds .venv.streamdeck at the click. Without it the
device and controller indicators name make
erplibre_home_streamdeck_install and start nothing; the selenium login
keeps .venv.erplibre.

--- FR ---
[FIX] extension gnome : racine de l'extension via le lien, venv du deck

GNOME Shell rapporte extension.path comme le lien situé sous
~/.local/share/gnome-shell/extensions : en retirer le suffixe de
l'extension n'aboutissait jamais, et le contrôleur cherchait son venv au
mauvais endroit. lib/project-root.js résout le lien avant de retirer le
suffixe, et streamDeckPython trouve .venv.streamdeck au clic. Sans lui,
les indicateurs Device et Controller nomment make
erplibre_home_streamdeck_install et ne lancent rien ; la connexion
selenium garde .venv.erplibre.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg "$MSG"
git add script/gnome-extension/erplibre_home/lib/project-root.js \
        script/gnome-extension/erplibre_home/test/unit/project-root.test.js \
        script/gnome-extension/erplibre_home/indicators/device.js \
        script/gnome-extension/erplibre_home/indicators/erplibre.js \
        script/gnome-extension/erplibre_home/indicators/controller.js \
        script/gnome-extension/erplibre_home/po/erplibre-home.pot \
        script/gnome-extension/erplibre_home/po/en.po \
        script/gnome-extension/erplibre_home/po/fr.po \
        script/gnome-extension/erplibre_home/CHANGELOG.md
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F "$MSG"
```
Expected: `commit-msg` exits 0 with no output. This exact message was checked against the hook, and its subject is 64 characters. The commit then contains the 9 files listed.

---

### Task 3: install_erplibre_home.sh: pre-checks, two levels, dry run

**Files:**
- Create: `script/install/install_erplibre_home.sh` (mode 755)
- Test: `test/test_install_erplibre_home.py`

**Interfaces:**
- Consumes:
  - `script/gnome-extension/erplibre_home/metadata.json`: the `shell-version` list, which is `["45" … "51"]` today, on one line. The script reads it with `tr`, `grep` and `sed`, never `python3`: the system `python3` is a base package that the package step installs after this check.
  - `script/gnome-extension/erplibre_home/po/*.po`: one `.mo` file per language, compiled by `msgfmt --check`. `--dry-run` lists these.
  - The detection logic of `script/install/install_vpn.sh:45-68` (`detect_os`/`family`). It is copied, with the family set in a global variable instead of echoed.
- Produces (Task 4 fills in the bodies that are still stubs; every name below stays the same):
  - Script globals: `RACINE`, `UUID`, `EXT_SRC`, `EXT_LINK` (`$HOME/.local/share/gnome-shell/extensions/erplibre-home@technolibre.ca`), `METADATA`, `UDEV_RULE` (`/etc/udev/rules.d/70-streamdeck.rules`), `VENV` (`$RACINE/.venv.streamdeck`), `STREAM_DECK`, `NO_ENABLE`, `EXTENSION_ONLY`, `WITH_EXTRAS`, `UNINSTALL`, `DRY_RUN`, `OS`, `OS_LIKE`, `FAMILY` (`debian|rhel|suse|arch`), `GNOME_VERSION`.
  - Pure helpers:
    - `packages_for FAMILY` returns the base package names: glib, gettext, the system python.
    - `streamdeck_packages_for FAMILY` returns the Stream Deck package names: hidapi, libusb, the venv module, `wmctrl`.
    - `level_packages FAMILY` returns the base names, plus, with `--stream-deck`, the Stream Deck names the base does not already carry.
    - `extras_for FAMILY` returns the extra package names (base level).
    - `needs_epel` returns 0 on almalinux and rocky; the callers ask it only with `--stream-deck`.
    - `shell_versions` prints the `shell-version` list of `METADATA`, space-separated, read without python; nothing when the key is missing.
    - `package_cmd FAMILY PACKAGE...` prints one line: the non-interactive `sudo …` install command.
    - `locale_langs` lists the languages of `po/*.po`; `mo_file LANG` prints `${EXT_SRC}/locale/<lang>/LC_MESSAGES/erplibre-home.mo`.
  - Other helpers: `log`, `die` (exit 1), `unsupported` (one `UNSUPPORTED: <reason>` line on stderr, exit 2).
  - Step functions:
    - `step_packages`, `step_udev`, `step_venv`, `step_extension`, `step_enable`, `step_summary`, `step_uninstall`. `main` calls `step_udev` and `step_venv` only with `--stream-deck`.
    - Under `--dry-run`, each prints its lines and returns.
    - Otherwise, each calls `not_implemented` (exit 1) until Task 4 replaces that branch.
  - Dry-run lines, each on its own line:
    - `family=<f>`, `gnome=<v>`;
    - `packages: <cmd>`: EPEL first with `--stream-deck` on AlmaLinux and Rocky only, then the packages of the level, then the extras with `--with-extras`;
    - `run: <path>` (the legacy migration, before the link's `write:`), `write: <path>` for the link and `gschemas.compiled`, then per language `run: msgfmt --check -o <mo> <po>` and `write: <mo>`;
    - with `--stream-deck` only: `write: /etc/udev/rules.d/70-streamdeck.rules` and `venv: <path>`;
    - `gsettings: org.gnome.shell enabled-extensions +<uuid>`, `gsettings: org.gnome.shell disable-user-extensions false` (not with `--no-enable`);
    - with `--uninstall`: `gsettings: org.gnome.shell enabled-extensions -<uuid>` and `remove: <path>` for the link, the rule and the venv; with `--uninstall --stream-deck`: `remove:` for the rule and the venv only.
  - Flags and exit codes: `0` done, `2` unsupported, `1` anything else. `--extension-only` with `--stream-deck` or `--uninstall`, and `--uninstall` with `--no-enable` or `--with-extras`, exit 1. `--extension-only` and `--uninstall` skip the OS and GNOME checks. `--help` exits 0, even when run as root.

- [ ] **Step 1: Write the failing test**

Create `test/test_install_erplibre_home.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur d'ERPLibre Home : vérifications préalables et --dry-run.

Le script installe pour de vrai, sous le compte de l'utilisateur, avec sudo
pour les paquets. Ces tests n'exercent que ce qui ne touche rien : la
lecture de os-release et de la version de GNOME, que les variables
ERPLIBRE_HOME_* remplacent, et la sortie de --dry-run, qui est la
surface convenue du script.

Ce que ces tests gardent :

- chaque distribution visée tombe dans sa famille, avec la commande de
  paquets de cette famille ;
- les deux niveaux : la base ne pose ni règle udev, ni venv, ni paquet du
  deck ; --stream-deck ajoute les trois, et EPEL n'est activé qu'avec lui,
  sur les reconstructions d'EL, où wmctrl en dépend ;
- les traductions se compilent par « msgfmt --check », aux deux niveaux ;
- --uninstall retire tout, --uninstall --stream-deck la règle et le venv
  seulement, et aucun des deux ne vérifie le système ;
- un système non supporté sort en 2 avec UNE ligne « UNSUPPORTED: » sur la
  sortie d'erreur, celle que TODO et le test long affichent ;
- la liste des versions de GNOME acceptées est celle de metadata.json, lue
  sans python3 ;
- root est refusé, --extension-only refuse --stream-deck et --uninstall, et
  --dry-run n'appelle pas sudo ni n'écrit rien.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/install/install_erplibre_home.sh"
EXTENSION = RACINE / "script/gnome-extension/erplibre_home"
UUID = "erplibre-home@technolibre.ca"
REGLE = "/etc/udev/rules.d/70-streamdeck.rules"

# Des os-release réduits à ce que le script lit : ID et ID_LIKE.
OS_RELEASE = {
    "ubuntu:24.04": 'ID=ubuntu\nID_LIKE=debian\nVERSION_ID="24.04"\n',
    "debian:13": 'ID=debian\nVERSION_ID="13"\n',
    "fedora:43": "ID=fedora\nVERSION_ID=43\n",
    "almalinux:10": (
        'ID="almalinux"\nID_LIKE="rhel centos fedora"\nVERSION_ID="10.0"\n'
    ),
    "rocky:10": (
        'ID="rocky"\nID_LIKE="rhel centos fedora"\nVERSION_ID="10.0"\n'
    ),
    "opensuse-leap:16.0": (
        'ID="opensuse-leap"\nID_LIKE="suse opensuse"\nVERSION_ID="16.0"\n'
    ),
    "arch": "ID=arch\nBUILD_ID=rolling\n",
    "nixos": 'ID=nixos\nVERSION_ID="25.11"\n',
    # Inventés : un dérivé que seul ID_LIKE rattache, et un système que rien
    # ne rattache.
    "derive": 'ID=exemplelinux\nID_LIKE="ubuntu debian"\n',
    "inconnu": "ID=exempleos\n",
}

APT = (
    "sudo apt-get update -qq && sudo env DEBIAN_FRONTEND=noninteractive "
    "apt-get install -y --no-install-recommends "
)
# La base : schémas, gettext, python3 du système.
BASE = {
    "debian": APT + "libglib2.0-bin gettext python3",
    "rhel": "sudo dnf install -y glib2 gettext python3",
    "suse": "sudo zypper --non-interactive install glib2-tools gettext-tools"
    " python3",
    "arch": "sudo pacman -S --needed --noconfirm glib2 gettext python",
}
# --stream-deck : la base, puis les paquets du deck qu'elle ne porte pas.
DECK = {
    "debian": BASE["debian"]
    + " libhidapi-libusb0 libusb-1.0-0 python3-venv wmctrl",
    "rhel": BASE["rhel"] + " hidapi libusb1 wmctrl",
    "suse": BASE["suse"] + " libhidapi-libusb0 libusb-1_0-0 wmctrl",
    "arch": BASE["arch"] + " hidapi libusb wmctrl",
}
FAMILLES = {
    "ubuntu:24.04": "debian",
    "debian:13": "debian",
    "fedora:43": "rhel",
    "almalinux:10": "rhel",
    "rocky:10": "rhel",
    "opensuse-leap:16.0": "suse",
    "arch": "arch",
    "derive": "debian",
}


def versions_acceptees():
    """Les majeurs de « shell-version », en entiers."""
    with open(EXTENSION / "metadata.json", encoding="utf-8") as flux:
        return sorted(int(v) for v in json.load(flux)["shell-version"])


def langues():
    """Les langues de po/, gabarit .pot exclu, dans l'ordre du glob."""
    return sorted(p.stem for p in (EXTENSION / "po").glob("*.po"))


class Installateur(unittest.TestCase):
    """Lance le script dans un HOME jetable, sudo remplacé par un témoin."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.trace_sudo = self.tmp / "sudo_appele"
        self._commande("sudo", 'echo "$@" >> "%s"\nexit 1\n' % self.trace_sudo)
        self.lien = str(
            self.home / ".local/share/gnome-shell/extensions" / UUID
        )
        self.venv = str(RACINE / ".venv.streamdeck")

    def _commande(self, nom, corps):
        """Pose une commande factice en tête du PATH du script."""
        chemin = self.bin / nom
        chemin.write_text("#!/bin/sh\n" + corps, encoding="utf-8")
        chemin.chmod(0o755)

    def lancer(
        self, *options, systeme="ubuntu:24.04", gnome="48.1", uid="1000"
    ):
        """Lance le script depuis un répertoire hors du dépôt.

        uid vaut 1000 par défaut : la suite peut tourner sous root, dans un
        conteneur, et le refus de root masquerait alors tout le reste.
        None laisse le script lire la vraie valeur.
        """
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("STREAMDECK_")
        }
        env["HOME"] = str(self.home)
        env["PATH"] = "%s:%s" % (self.bin, env.get("PATH", ""))
        if systeme is not None:
            fichier = self.tmp / "os-release"
            fichier.write_text(OS_RELEASE[systeme], encoding="utf-8")
            env["ERPLIBRE_HOME_OS_RELEASE"] = str(fichier)
        if gnome is not None:
            env["ERPLIBRE_HOME_GNOME_VERSION"] = gnome
        if uid is not None:
            env["ERPLIBRE_HOME_UID"] = uid
        return subprocess.run(
            [str(SCRIPT), *options],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.tmp),
            timeout=30,
        )

    @staticmethod
    def lignes(fini, prefixe):
        """Les lignes de stdout qui commencent par prefixe, sans lui."""
        return [
            ligne[len(prefixe) :]
            for ligne in fini.stdout.splitlines()
            if ligne.startswith(prefixe)
        ]

    def assertNonSupporte(self, fini, extrait):
        self.assertEqual(2, fini.returncode, fini.stdout + fini.stderr)
        erreurs = fini.stderr.strip().splitlines()
        self.assertEqual(1, len(erreurs), fini.stderr)
        self.assertTrue(erreurs[0].startswith("UNSUPPORTED: "), erreurs[0])
        self.assertIn(extrait, erreurs[0])
        self.assertEqual([], self.lignes(fini, "packages: "))


class LeScript(Installateur):
    def test_it_is_valid_shell(self):
        fini = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)

    def test_it_is_executable(self):
        """TODO, make et la VM l'appellent directement, sans « bash »."""
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_help_exits_zero_even_as_root(self):
        fini = self.lancer("--help", uid="0")
        self.assertEqual(0, fini.returncode, fini.stderr)
        for option in (
            "--stream-deck",
            "--no-enable",
            "--extension-only",
            "--with-extras",
            "--uninstall",
            "--dry-run",
        ):
            self.assertIn(option, fini.stdout)

    def test_an_unknown_option_exits_one(self):
        fini = self.lancer("--exemple", "--dry-run")
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("--exemple", fini.stderr)

    def test_uninstall_takes_no_install_option(self):
        fini = self.lancer("--uninstall", "--with-extras", "--dry-run")
        self.assertEqual(1, fini.returncode, fini.stdout)

    def test_extension_only_refuses_the_other_levels(self):
        """--extension-only est l'entrée étroite de make : ni le niveau
        Stream Deck ni la désinstallation n'y entrent."""
        for autre in ("--stream-deck", "--uninstall"):
            with self.subTest(autre=autre):
                fini = self.lancer("--extension-only", autre, "--dry-run")
                self.assertEqual(1, fini.returncode, fini.stdout)
                self.assertIn("--extension-only", fini.stderr)
                self.assertNotIn("UNSUPPORTED", fini.stderr)
                self.assertEqual([], self.lignes(fini, "write: "))


class LaFamille(Installateur):
    def test_each_target_system_maps_to_its_family_and_base_packages(self):
        for systeme, famille in FAMILLES.items():
            with self.subTest(systeme=systeme):
                fini = self.lancer("--dry-run", systeme=systeme)
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual([famille], self.lignes(fini, "family="))
                self.assertEqual(["48.1"], self.lignes(fini, "gnome="))
                self.assertEqual(
                    [BASE[famille]], self.lignes(fini, "packages: ")
                )

    def test_stream_deck_adds_its_rows_to_the_base(self):
        for systeme, famille in FAMILLES.items():
            with self.subTest(systeme=systeme):
                fini = self.lancer(
                    "--dry-run", "--stream-deck", systeme=systeme
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(
                    DECK[famille], self.lignes(fini, "packages: ")[-1]
                )

    def test_epel_comes_first_with_stream_deck_on_el_rebuilds_only(self):
        for systeme in ("almalinux:10", "rocky:10"):
            with self.subTest(systeme=systeme):
                deck = self.lignes(
                    self.lancer("--dry-run", "--stream-deck", systeme=systeme),
                    "packages: ",
                )
                self.assertEqual(
                    ["sudo dnf install -y epel-release", DECK["rhel"]], deck
                )
                base = self.lignes(
                    self.lancer("--dry-run", systeme=systeme), "packages: "
                )
                self.assertEqual([BASE["rhel"]], base)
        paquets = self.lignes(
            self.lancer("--dry-run", "--stream-deck", systeme="fedora:43"),
            "packages: ",
        )
        self.assertEqual([DECK["rhel"]], paquets)

    def test_with_extras_adds_one_more_command_at_both_levels(self):
        lz4 = {
            "ubuntu:24.04": "python3-lz4",
            "fedora:43": "python3-lz4",
            "opensuse-leap:16.0": "python3-lz4",
            "arch": "python-lz4",
        }
        for niveau in ((), ("--stream-deck",)):
            for systeme, module in lz4.items():
                with self.subTest(niveau=niveau, systeme=systeme):
                    paquets = self.lignes(
                        self.lancer(
                            "--dry-run",
                            "--with-extras",
                            *niveau,
                            systeme=systeme,
                        ),
                        "packages: ",
                    )
                    self.assertTrue(
                        paquets[-1].endswith(
                            "mpv yt-dlp nmap keepassxc xdotool " + module
                        ),
                        paquets[-1],
                    )
                    self.assertNotIn("lz4", paquets[-2])

    def test_without_extras_no_extra_package(self):
        fini = self.lancer("--dry-run", "--stream-deck")
        self.assertNotIn("lz4", fini.stdout)
        self.assertNotIn("keepassxc", fini.stdout)


class LeDryRun(Installateur):
    def test_the_base_lists_its_files_and_neither_rule_nor_venv(self):
        fini = self.lancer("--dry-run")
        self.assertEqual(0, fini.returncode, fini.stderr)
        ecrits = self.lignes(fini, "write: ")
        self.assertNotIn(REGLE, ecrits)
        self.assertEqual([], self.lignes(fini, "venv: "))
        self.assertIn(self.lien, ecrits)
        self.assertIn(str(EXTENSION / "schemas/gschemas.compiled"), ecrits)
        self.assertIn(
            str(EXTENSION / "locale/fr/LC_MESSAGES/erplibre-home.mo"),
            ecrits,
        )
        # Le gabarit .pot n'est pas une langue.
        self.assertFalse(
            [e for e in ecrits if "locale/erplibre-home/" in e], ecrits
        )
        # La migration de l'ancienne identité précède le lien.
        migration = str(EXTENSION / "tools/migrate_legacy.py")
        sortie = fini.stdout.splitlines()
        self.assertEqual(migration, self.lignes(fini, "run: ")[0])
        self.assertLess(
            sortie.index("run: " + migration),
            sortie.index("write: " + self.lien),
        )

    def test_stream_deck_lists_the_rule_and_the_venv(self):
        fini = self.lancer("--dry-run", "--stream-deck")
        self.assertEqual(0, fini.returncode, fini.stderr)
        ecrits = self.lignes(fini, "write: ")
        self.assertIn(REGLE, ecrits)
        self.assertIn(self.lien, ecrits)
        # Lancé hors du dépôt, il se place quand même à sa racine.
        self.assertEqual([self.venv], self.lignes(fini, "venv: "))

    def test_the_translations_use_msgfmt_check_at_both_levels(self):
        attendus = [str(EXTENSION / "tools/migrate_legacy.py")] + [
            "msgfmt --check -o %s %s"
            % (
                EXTENSION / "locale" / langue / "LC_MESSAGES/erplibre-home.mo",
                EXTENSION / "po" / ("%s.po" % langue),
            )
            for langue in langues()
        ]
        self.assertIn("fr", langues())
        for niveau in ((), ("--stream-deck",)):
            with self.subTest(niveau=niveau):
                fini = self.lancer("--dry-run", *niveau)
                self.assertEqual(attendus, self.lignes(fini, "run: "))

    def test_it_calls_no_sudo_and_writes_nothing(self):
        fini = self.lancer("--dry-run", "--stream-deck", "--with-extras")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertFalse(self.trace_sudo.exists())
        self.assertEqual([], list(self.home.iterdir()))

    def test_it_shows_the_gsettings_keys_unless_no_enable(self):
        cles = [
            "org.gnome.shell enabled-extensions +" + UUID,
            "org.gnome.shell disable-user-extensions false",
        ]
        fini = self.lancer("--dry-run")
        self.assertEqual(cles, self.lignes(fini, "gsettings: "))
        fini = self.lancer("--dry-run", "--no-enable")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual([], self.lignes(fini, "gsettings: "))

    def test_extension_only_checks_no_system(self):
        """Ni os-release ni GNOME : un système refusé passe quand même."""
        fini = self.lancer(
            "--extension-only", "--dry-run", systeme="nixos", gnome="none"
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual([], self.lignes(fini, "family="))
        self.assertEqual([], self.lignes(fini, "packages: "))
        self.assertEqual([], self.lignes(fini, "venv: "))
        ecrits = self.lignes(fini, "write: ")
        self.assertNotIn(REGLE, ecrits)
        self.assertIn(self.lien, ecrits)
        self.assertEqual(
            str(EXTENSION / "tools/migrate_legacy.py"),
            self.lignes(fini, "run: ")[0],
        )
        self.assertEqual([], self.lignes(fini, "gsettings: "))

    def test_uninstall_lists_what_it_removes_and_keeps_packages(self):
        fini = self.lancer(
            "--uninstall", "--dry-run", systeme="nixos", gnome="none"
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [self.lien, REGLE, self.venv], self.lignes(fini, "remove: ")
        )
        self.assertEqual(
            ["org.gnome.shell enabled-extensions -" + UUID],
            self.lignes(fini, "gsettings: "),
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
        self.assertEqual([], self.lignes(fini, "packages: "))

    def test_uninstall_skips_the_gnome_version_check(self):
        """Une désinstallation marche encore quand GNOME a dépassé les
        versions que metadata.json déclare."""
        hors_liste = "%d.0" % (versions_acceptees()[-1] + 1)
        for niveau in ((), ("--stream-deck",)):
            with self.subTest(niveau=niveau):
                fini = self.lancer(
                    "--dry-run", "--uninstall", *niveau, gnome=hors_liste
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertNotIn("UNSUPPORTED", fini.stderr)


class LesRefus(Installateur):
    def test_nixos_is_unsupported(self):
        self.assertNonSupporte(
            self.lancer("--dry-run", systeme="nixos"), "NixOS"
        )

    def test_an_unknown_distribution_is_unsupported(self):
        self.assertNonSupporte(
            self.lancer("--dry-run", systeme="inconnu"), "exempleos"
        )

    def test_no_gnome_shell_is_unsupported(self):
        self.assertNonSupporte(
            self.lancer("--dry-run", gnome="none"), "no GNOME Shell"
        )

    def test_gnome_outside_shell_version_is_unsupported(self):
        acceptees = versions_acceptees()
        liste = " ".join(str(v) for v in acceptees)
        for version in (
            "%d.0" % (acceptees[0] - 1),
            "%d.0" % (acceptees[-1] + 1),
        ):
            with self.subTest(version=version):
                self.assertNonSupporte(
                    self.lancer("--dry-run", gnome=version),
                    "GNOME %s not in shell-version (%s)" % (version, liste),
                )

    def test_both_bounds_of_shell_version_are_accepted(self):
        acceptees = versions_acceptees()
        for version in ("%d.0" % acceptees[0], "%d.2" % acceptees[-1]):
            with self.subTest(version=version):
                fini = self.lancer("--dry-run", gnome=version)
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual([version], self.lignes(fini, "gnome="))

    def test_shell_version_is_read_without_python(self):
        """python3 est un paquet de base, installé APRÈS cette lecture : un
        python3 qui échoue en tête du PATH ne change pas la liste lue, la
        même que celle de json.load."""
        trace = self.tmp / "python_appele"
        for nom in ("python3", "python"):
            self._commande(nom, 'echo "$@" >> "%s"\nexit 1\n' % trace)
        acceptees = versions_acceptees()
        fini = self.lancer("--dry-run", gnome="%d.1" % acceptees[0])
        self.assertEqual(0, fini.returncode, fini.stderr)
        hors_liste = "%d.0" % (acceptees[-1] + 1)
        self.assertNonSupporte(
            self.lancer("--dry-run", gnome=hors_liste),
            "(%s)" % " ".join(str(v) for v in acceptees),
        )
        self.assertFalse(trace.exists())

    def test_gnome_version_is_read_from_gnome_shell(self):
        self._commande("gnome-shell", 'echo "GNOME Shell 47.2"\n')
        fini = self.lancer("--dry-run", gnome=None)
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(["47.2"], self.lignes(fini, "gnome="))

    def test_root_is_refused(self):
        fini = self.lancer("--dry-run", uid="0")
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("root", fini.stderr)
        self.assertNotIn("UNSUPPORTED", fini.stderr)
        self.assertEqual([], self.lignes(fini, "family="))


if __name__ == "__main__":
    unittest.main()
```

The out-of-range GNOME versions come from `metadata.json`: today they are `44.0` and `52.0`. Deriving them keeps this test green when a later change adds a version. `48.1` is the in-range baseline for every other test. `test_shell_version_is_read_without_python` puts a `python3` and a `python` that fail first in `PATH`: the read must not call either.

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv.erplibre/bin/python test/test_install_erplibre_home.py`

Expected: `Ran 28 tests`, `FAILED (failures=2, errors=54)`, which breaks down as:
- every `lancer` call errors with `FileNotFoundError: [Errno 2] No such file or directory: '…/script/install/install_erplibre_home.sh'`, once per subtest;
- `test_it_is_valid_shell` fails with `0 != 127`;
- `test_it_is_executable` fails with `False is not true`.

- [ ] **Step 3: Implement**

Create `script/install/install_erplibre_home.sh`:

```bash
#!/usr/bin/env bash
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
#
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
# d'erreur ; 1 tout autre échec.
#
# Tourne sous le compte de l'utilisateur et refuse root : le venv,
# l'extension et les clés gsettings lui appartiennent. sudo ne sert qu'aux
# paquets système et à la règle udev. Se lance de n'importe où : le script
# se place à la racine du dépôt qui le contient.
#
# Trois variables remplacent une lecture du système, pour les tests :
#   ERPLIBRE_HOME_OS_RELEASE     fichier lu à la place de /etc/os-release
#   ERPLIBRE_HOME_GNOME_VERSION  version lue à la place de « gnome-shell
#                                --version » ; « none » : pas de GNOME Shell
#   ERPLIBRE_HOME_UID            remplace « id -u »
set -euo pipefail

RACINE="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${RACINE}"

UUID="erplibre-home@technolibre.ca"
EXT_SRC="${RACINE}/script/gnome-extension/erplibre_home"
EXT_LINK="${HOME}/.local/share/gnome-shell/extensions/${UUID}"
METADATA="${EXT_SRC}/metadata.json"
UDEV_RULE="/etc/udev/rules.d/70-streamdeck.rules"
VENV="${RACINE}/.venv.streamdeck"
OS_RELEASE="${ERPLIBRE_HOME_OS_RELEASE:-/etc/os-release}"

STREAM_DECK=0
NO_ENABLE=0
EXTENSION_ONLY=0
WITH_EXTRAS=0
UNINSTALL=0
DRY_RUN=0

OS=""
OS_LIKE=""
FAMILY=""
GNOME_VERSION=""

log() { echo "[ERPLibre Home] $*"; }
die() {
    echo "[ERPLibre Home] ERREUR : $*" >&2
    exit 1
}
# Le code 2 et la ligne « UNSUPPORTED: » sont lus par TODO et par le test
# long : la raison tient sur une ligne, en anglais, et rien d'autre ne part
# sur la sortie d'erreur avant elle.
unsupported() {
    echo "UNSUPPORTED: $*" >&2
    exit 2
}

usage() {
    cat <<'USAGE'
Usage : ./script/install/install_erplibre_home.sh [options]

Installe ERPLibre Home sans Odoo : l'extension GNOME erplibre-home, ses
schémas et ses traductions, activée. --stream-deck y ajoute le Stream Deck.

  --stream-deck     ajoute le niveau Stream Deck : paquets USB, règle udev,
                    .venv.streamdeck ; la base s'installe aussi, au besoin
  --no-enable       n'active pas l'extension ; un poste où l'ancienne
                    extension était active garde cet état sous le
                    nouveau nom (migration)
  --extension-only  migration de l'ancienne identité, lien, schémas et
                    traductions de l'extension seulement, sans sudo ni
                    vérification du système ; ne se combine ni avec
                    --stream-deck ni avec --uninstall
  --with-extras     ajoute mpv, yt-dlp, nmap, keepassxc, xdotool et le
                    module Python lz4 du système ; un paquet absent est
                    signalé, jamais fatal
  --uninstall       retire tout : extension, règle udev, .venv.streamdeck ;
                    avec --stream-deck, la règle et le venv seulement, et
                    l'extension reste active ; les paquets système restent
  --dry-run         affiche ce qui serait fait, sans rien changer ni
                    appeler sudo
  -h, --help        cette aide

Codes de sortie : 0 fait ; 2 système non supporté (une ligne
« UNSUPPORTED: <raison> » sur la sortie d'erreur) ; 1 autre échec.
USAGE
}

parse_args() {
    while [ $# -gt 0 ]; do
        case "$1" in
            --stream-deck) STREAM_DECK=1 ;;
            --no-enable) NO_ENABLE=1 ;;
            --extension-only) EXTENSION_ONLY=1 ;;
            --with-extras) WITH_EXTRAS=1 ;;
            --uninstall) UNINSTALL=1 ;;
            --dry-run) DRY_RUN=1 ;;
            -h | --help)
                usage
                exit 0
                ;;
            *)
                usage >&2
                die "option inconnue : $1"
                ;;
        esac
        shift
    done
    # --extension-only est l'entrée étroite de
    # « make erplibre_home_install_extension » : l'étape de l'extension
    # seule, que le niveau Stream Deck et la désinstallation dépassent.
    if [ "${EXTENSION_ONLY}" = 1 ] \
        && [ $((STREAM_DECK + UNINSTALL)) -gt 0 ]; then
        die "--extension-only ne se combine ni avec --stream-deck ni avec" \
            "--uninstall"
    fi
    if [ "${UNINSTALL}" = 1 ] \
        && [ $((NO_ENABLE + WITH_EXTRAS)) -gt 0 ]; then
        die "--uninstall ne se combine qu'avec --stream-deck et --dry-run"
    fi
}

check_not_root() {
    local uid="${ERPLIBRE_HOME_UID:-$(id -u)}"
    if [ "${uid}" = 0 ]; then
        die "à lancer sous votre compte, pas en root : le venv, l'extension" \
            "et gsettings appartiennent à l'utilisateur, et le script appelle" \
            "sudo lui-même pour les paquets et la règle udev"
    fi
}

# ID et ID_LIKE sont lus dans un sous-shell : sourcer os-release dans le
# script même y déposerait NAME, VERSION et le reste parmi ses variables.
detect_os() {
    if [ "$(uname -s)" = Darwin ]; then
        unsupported "macOS is not handled"
    fi
    [ -r "${OS_RELEASE}" ] || unsupported "unknown system (no ${OS_RELEASE})"
    # shellcheck disable=SC1090
    OS="$(. "${OS_RELEASE}" && echo "${ID:-}")"
    # shellcheck disable=SC1090
    OS_LIKE="$(. "${OS_RELEASE}" && echo "${ID_LIKE:-}")"
}

# Pose FAMILY plutôt que de l'écrire sur la sortie : appelée dans « $(…) »,
# le code 2 de unsupported se perdrait dans le sous-shell. L'ID exact passe
# avant ID_LIKE ; un dérivé inconnu est rattaché par son ID_LIKE.
detect_family() {
    case "${OS}" in
        nixos)
            unsupported "NixOS is not handled: its packages are declared" \
                "in the system configuration, not installed"
            ;;
        ubuntu | debian | linuxmint | pop | elementary | raspbian)
            FAMILY=debian
            return
            ;;
        arch | manjaro | endeavouros | artix | garuda)
            FAMILY=arch
            return
            ;;
        fedora | rhel | centos | almalinux | rocky)
            FAMILY=rhel
            return
            ;;
        opensuse* | sles | sled)
            FAMILY=suse
            return
            ;;
    esac
    case "${OS_LIKE}" in
        *debian* | *ubuntu*) FAMILY=debian ;;
        *arch*) FAMILY=arch ;;
        *rhel* | *fedora*) FAMILY=rhel ;;
        *suse*) FAMILY=suse ;;
        *) unsupported "unknown distribution ${OS} (ID_LIKE=${OS_LIKE})" ;;
    esac
}

# wmctrl, un paquet du niveau Stream Deck, n'est pas dans les dépôts de base
# d'AlmaLinux et de Rocky Linux : EPEL le porte. Fedora l'a dans les siens,
# et EPEL n'y existe pas. L'appelant n'active EPEL qu'avec --stream-deck.
needs_epel() {
    case "${OS}" in
        almalinux | rocky) return 0 ;;
    esac
    return 1
}

# Les versions de « shell-version » dans metadata.json, séparées par une
# espace. tr, grep et sed, et non python3 : le python3 du système est un
# paquet de base que l'étape des paquets installe, APRÈS cette lecture. Les
# sauts de ligne sont retirés d'abord, si bien que le tableau se lit qu'il
# tienne sur une ligne ou sur plusieurs. Ne rend rien quand la clé manque.
shell_versions() {
    tr -d '\n\r' <"${METADATA}" \
        | grep -o '"shell-version"[^]]*' \
        | grep -o '"[0-9][^"]*"' \
        | tr -d '"' | tr '\n' ' ' | sed 's/ *$//'
}

# Le majeur de la version doit figurer dans « shell-version » de
# metadata.json, la liste même que GNOME Shell confronte à sa version avant
# de charger l'extension. La lire là, plutôt que d'en tenir une copie ici,
# empêche les deux listes de diverger.
check_gnome() {
    local accepted major
    if [ -n "${ERPLIBRE_HOME_GNOME_VERSION:-}" ]; then
        GNOME_VERSION="${ERPLIBRE_HOME_GNOME_VERSION}"
    elif command -v gnome-shell >/dev/null 2>&1; then
        GNOME_VERSION="$(gnome-shell --version 2>/dev/null \
            | sed -n 's/^GNOME Shell //p')"
        [ -n "${GNOME_VERSION}" ] \
            || die "« gnome-shell --version » ne rend aucune version lisible"
    else
        GNOME_VERSION=none
    fi
    [ "${GNOME_VERSION}" != none ] || unsupported "no GNOME Shell"
    accepted="$(shell_versions)" || accepted=""
    [ -n "${accepted}" ] || die "shell-version illisible dans ${METADATA}"
    major="${GNOME_VERSION%%.*}"
    case " ${accepted} " in
        *" ${major} "*) ;;
        *) unsupported "GNOME ${GNOME_VERSION} not in shell-version (${accepted})" ;;
    esac
}

# Paquets de la base, par famille : de quoi compiler les schémas (glib) et
# les traductions (msgfmt, de gettext), et le python3 du système, qui lance
# la migration de l'ancienne identité de l'extension.
packages_for() {
    case "$1" in
        debian) echo "libglib2.0-bin gettext python3" ;;
        rhel) echo "glib2 gettext python3" ;;
        suse) echo "glib2-tools gettext-tools python3" ;;
        arch) echo "glib2 gettext python" ;;
        *) die "famille inconnue : $1" ;;
    esac
}

# Paquets du niveau Stream Deck, par famille : hidapi et libusb pour parler
# au deck, le module venv, et wmctrl pour keyboard_talk.py. opencv-python
# arrive en roue manylinux par pip et ne demande rien ici.
streamdeck_packages_for() {
    case "$1" in
        debian) echo "libhidapi-libusb0 libusb-1.0-0 python3-venv wmctrl" ;;
        rhel) echo "hidapi libusb1 python3 wmctrl" ;;
        suse) echo "libhidapi-libusb0 libusb-1_0-0 python3 wmctrl" ;;
        arch) echo "hidapi libusb python wmctrl" ;;
        *) die "famille inconnue : $1" ;;
    esac
}

# level_packages FAMILLE rend les paquets du niveau choisi : ceux de la
# base, puis, avec --stream-deck, ceux du deck que la base ne porte pas déjà
# (le python3 du venv est celui de la base sur dnf, zypper et pacman).
level_packages() {
    local pkgs pkg
    pkgs="$(packages_for "$1")"
    if [ "${STREAM_DECK}" = 1 ]; then
        for pkg in $(streamdeck_packages_for "$1"); do
            case " ${pkgs} " in
                *" ${pkg} "*) ;;
                *) pkgs="${pkgs} ${pkg}" ;;
            esac
        done
    fi
    echo "${pkgs}"
}

# Outils facultatifs des indicateurs, donc de la base. lz4 est le module
# Python du SYSTÈME : l'import des onglets Firefox tourne sous le python3 que
# lance prefs.js, et un lz4 posé dans le venv ne le servirait pas.
extras_for() {
    case "$1" in
        debian | rhel | suse) echo "mpv yt-dlp nmap keepassxc xdotool python3-lz4" ;;
        arch) echo "mpv yt-dlp nmap keepassxc xdotool python-lz4" ;;
        *) die "famille inconnue : $1" ;;
    esac
}

# package_cmd FAMILLE PAQUET... rend, sur une ligne, la commande non
# interactive qui installe ces paquets avec le gestionnaire de la famille.
# Fonction pure : --dry-run affiche cette ligne, l'installation exécute la
# même, et les deux ne peuvent pas diverger. Un paquet déjà présent est
# sauté par le gestionnaire lui-même.
package_cmd() {
    local fam="$1"
    shift
    case "${fam}" in
        debian)
            echo "sudo apt-get update -qq && sudo env" \
                "DEBIAN_FRONTEND=noninteractive apt-get install -y" \
                "--no-install-recommends $*"
            ;;
        rhel) echo "sudo dnf install -y $*" ;;
        suse) echo "sudo zypper --non-interactive install $*" ;;
        arch) echo "sudo pacman -S --needed --noconfirm $*" ;;
        *) die "famille inconnue : ${fam}" ;;
    esac
}

# Les langues des traductions : une par po/<langue>.po. Le gabarit
# erplibre-home.pot n'en est pas une.
locale_langs() {
    local po
    for po in "${EXT_SRC}"/po/*.po; do
        [ -e "${po}" ] || continue
        basename "${po}" .po
    done
}

# Le .mo que msgfmt écrit pour une langue, là où l'extension le cherche.
mo_file() {
    echo "${EXT_SRC}/locale/$1/LC_MESSAGES/erplibre-home.mo"
}

not_implemented() {
    die "étape pas encore implémentée : $1"
}

# Chaque étape affiche, sous --dry-run, une ligne par effet qu'elle aurait,
# puis rend la main ; elle agit sinon.
step_packages() {
    if [ "${DRY_RUN}" = 1 ]; then
        if [ "${STREAM_DECK}" = 1 ] && needs_epel; then
            echo "packages: $(package_cmd "${FAMILY}" epel-release)"
        fi
        # shellcheck disable=SC2046
        echo "packages: $(package_cmd "${FAMILY}" $(level_packages "${FAMILY}"))"
        if [ "${WITH_EXTRAS}" = 1 ]; then
            # shellcheck disable=SC2046
            echo "packages: $(package_cmd "${FAMILY}" $(extras_for "${FAMILY}"))"
        fi
        return 0
    fi
    not_implemented "paquets système"
}

step_udev() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "write: ${UDEV_RULE}"
        return 0
    fi
    not_implemented "règle udev"
}

step_venv() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "venv: ${VENV}"
        return 0
    fi
    not_implemented "venv"
}

step_extension() {
    local lang
    if [ "${DRY_RUN}" = 1 ]; then
        echo "run: ${EXT_SRC}/tools/migrate_legacy.py"
        echo "write: ${EXT_LINK}"
        echo "write: ${EXT_SRC}/schemas/gschemas.compiled"
        for lang in $(locale_langs); do
            echo "run: msgfmt --check -o $(mo_file "${lang}") ${EXT_SRC}/po/${lang}.po"
            echo "write: $(mo_file "${lang}")"
        done
        return 0
    fi
    not_implemented "extension"
}

step_enable() {
    if [ "${DRY_RUN}" = 1 ]; then
        echo "gsettings: org.gnome.shell enabled-extensions +${UUID}"
        echo "gsettings: org.gnome.shell disable-user-extensions false"
        return 0
    fi
    not_implemented "activation"
}

step_summary() {
    not_implemented "résumé"
}

# --uninstall retire tout ; --uninstall --stream-deck ne retire que le
# niveau Stream Deck, la règle et le venv, et laisse l'extension active.
step_uninstall() {
    if [ "${DRY_RUN}" = 1 ]; then
        if [ "${STREAM_DECK}" = 0 ]; then
            echo "gsettings: org.gnome.shell enabled-extensions -${UUID}"
            echo "remove: ${EXT_LINK}"
        fi
        echo "remove: ${UDEV_RULE}"
        echo "remove: ${VENV}"
        return 0
    fi
    not_implemented "désinstallation"
}

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
    fi
    if [ "${EXTENSION_ONLY}" = 0 ]; then
        detect_os
        detect_family
        check_gnome
        if [ "${DRY_RUN}" = 1 ]; then
            echo "family=${FAMILY}"
            echo "gnome=${GNOME_VERSION}"
        else
            log "famille ${FAMILY}, GNOME ${GNOME_VERSION}"
        fi
        step_packages
        if [ "${STREAM_DECK}" = 1 ]; then
            step_udev
            step_venv
        fi
    fi
    step_extension
    if [ "${EXTENSION_ONLY}" = 0 ] && [ "${NO_ENABLE}" = 0 ]; then
        step_enable
    fi
    if [ "${DRY_RUN}" = 0 ]; then
        step_summary
    fi
}

main "$@"
```

Then make the script executable. git records mode 755.

```bash
chmod +x script/install/install_erplibre_home.sh
```

Notes for Task 4:
- Keep `main`, `parse_args`, `check_not_root` and every `--dry-run` branch. Task 4 replaces the `not_implemented` function with the installation functions, each `not_implemented …` line of the `step_*` functions (the body of `step_summary` included) with calls to them, and the final `main "$@"` line with a source guard; it also makes `unsupported` record that it is the one exiting 2.
- Run the package lines through `eval "$(package_cmd "${FAMILY}" …)"`. Every word in that line is a literal from `packages_for`, `streamdeck_packages_for`, `extras_for` or `epel-release`, and no user input reaches it.
- Under `--extension-only`, `FAMILY` is empty. `step_extension` must not depend on it, except to name the gettext package in an error.

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd "$(git rev-parse --show-toplevel)"
.venv.erplibre/bin/python test/test_install_erplibre_home.py -v
```
Expected: `Ran 28 tests` … `OK`.

```bash
./script/test/run_unit_test.sh test/test_install_erplibre_home.py
```
Expected: one line `OK` for `test/test_install_erplibre_home.py`. The runner stubs `sudo`; the test puts its own `sudo` witness first in PATH.

```bash
bash -n script/install/install_erplibre_home.sh && echo syntax-ok
.venv.erplibre/bin/ruff format --check test/test_install_erplibre_home.py
.venv.erplibre/bin/ruff check --select I test/test_install_erplibre_home.py
python3 script/analyse/check_comment_hygiene.py script/install/install_erplibre_home.sh test/test_install_erplibre_home.py
```
Expected:
- `syntax-ok`;
- `1 file already formatted`;
- `All checks passed!`;
- the hygiene check reports nothing and exits 0.

Manual check (it changes nothing):

```bash
ERPLIBRE_HOME_OS_RELEASE=/etc/os-release ERPLIBRE_HOME_GNOME_VERSION=48.1 ./script/install/install_erplibre_home.sh --dry-run --with-extras
ERPLIBRE_HOME_OS_RELEASE=/etc/os-release ERPLIBRE_HOME_GNOME_VERSION=48.1 ./script/install/install_erplibre_home.sh --dry-run --stream-deck | grep -E '^(write: /etc|venv: )'
```
Expected: the first prints the `family=`, `gnome=48.1`, two `packages: …` lines (the base, the extras), the `run: …` lines (the migration, then one `msgfmt --check` per language), the `write: …` lines (link, schemas, one `.mo` per language) and the two `gsettings: …` lines, with no `venv:` line and no udev rule, then exits 0. The second prints `write: /etc/udev/rules.d/70-streamdeck.rules` and `venv: <checkout>/.venv.streamdeck`.

- [ ] **Step 5: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add script/install/install_erplibre_home.sh test/test_install_erplibre_home.py
cat > $SCRATCH/msg_task3.txt <<'EOF'
[ADD] install: ERPLibre Home installer pre-checks and dry run

install_erplibre_home.sh maps os-release to a family, refuses root, and
accepts only a GNOME major of shell-version, read without python; outside
it exits 2 with one UNSUPPORTED line. The base sets up the extension;
--stream-deck adds the deck packages, the udev rule and .venv.streamdeck,
EPEL only then. --uninstall --stream-deck removes the rule and the venv;
an uninstall checks no system. --dry-run prints both levels without sudo;
side-effecting steps stop with exit 1 for now.

--- FR ---

[ADD] install : installateur ERPLibre Home, contrôles et essai à blanc

install_erplibre_home.sh rattache os-release à une famille, refuse root et
n'accepte qu'un majeur de shell-version, lu sans python ; hors liste, il
sort en 2 avec une ligne UNSUPPORTED. La base pose l'extension ;
--stream-deck ajoute les paquets du deck, la règle udev et
.venv.streamdeck, EPEL seulement alors. --uninstall --stream-deck retire
la règle et le venv ; une désinstallation ne vérifie aucun système.
--dry-run affiche les deux niveaux sans sudo ; les étapes à effet sortent
en 1 pour l'instant.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task3.txt
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task3.txt
```

The script and the test were built and run in a `git archive HEAD` copy after Tasks 1-2; no repository file was changed:
- All 28 tests pass with the script in place.
- Without the script, the run gives `FAILED (failures=2, errors=54)`.
- `ruff format` has been applied to the test file.
- The comment-hygiene check reports nothing.
- The `commit-msg` hook accepts the message (`rc=0`).

---

### Task 4: install_erplibre_home.sh: install, enable, both uninstalls; make targets; INSTALL doc

**Files:**
- Modify: `script/install/install_erplibre_home.sh` (created by Task 3). Four edits, each anchored on Task 3's text:
  - `unsupported` records that it is the one exiting 2;
  - the 3-line `not_implemented` function is replaced by the block of installation functions;
  - each `not_implemented …` line in the `step_*` functions, and the body of `step_summary`, calls those functions;
  - the final `main "$@"` line becomes a guard with an `EXIT` trap.
- Modify: `conf/make.streamdeck.Makefile`: insert the four new targets before `ERPLIBRE_HOME_EXT_UUID       := …` (line 107 at HEAD `dc841639`), replace the `erplibre_home_install_extension` recipe (lines 114-125 at that HEAD; its first line, the legacy migration, moves into the installer's extension step, its `compile_locales.py` lines give way to the installer's `msgfmt`, and its closing `Then: make erplibre_home_enable_extension …` hint stays) and delete the `erplibre_home_uninstall` alias (lines 153-155). Task 1 shifts these lines, so find each edit by its anchor text.
- Modify: `test/test_streamdeck_entry_points.py` (created by Task 1): no recipe calls the migration any more, so its exemption leaves `HORS_VENV`; the enable helper's and the locale compiler's stay.
- Modify: `script/stream_deck/INSTALL.base.md:6-53`, then regenerate `script/stream_deck/INSTALL.md` and `script/stream_deck/INSTALL.fr.md`.
- Test: `test/test_install_erplibre_home.py` (created by Task 3, extended here), `test/test_erplibre_home_enable_target.py` (must stay green: it drives the fragment's `erplibre_home_enable_extension`, whose helper the installer now shares).

**Interfaces:**
- Consumes Task 3's script as it stands:
  - globals `RACINE UUID EXT_SRC EXT_LINK METADATA UDEV_RULE VENV STREAM_DECK FAMILY OS WITH_EXTRAS UNINSTALL`;
  - functions `needs_epel`, `packages_for FAMILY`, `streamdeck_packages_for FAMILY`, `level_packages FAMILY`, `extras_for FAMILY`, `shell_versions`, `package_cmd FAMILY PKG...` (which prints `sudo …`), `locale_langs`, `mo_file LANG`, `log`, `die`, `unsupported`, `parse_args`, `check_not_root`, `main` and the `step_*` functions;
  - `set -euo pipefail` and the top-level `cd "${RACINE}"`.
- Produces:
  - `REQUIREMENTS`, `DONE` and the functions `install_packages`, `udev_rule_content`, `write_udev_rule`, `make_venv`, `link_extension`, `compile_schemas`, `gettext_package FAMILY`, `compile_locales`, `on_session_bus CMD...`, `gsettings_bus`, `uuid_list_edit <has|remove> <gvariant-list> <uuid>`, `shell_bus_address`, `enable_extension`, `uninstall_streamdeck`, `uninstall`, `summary`.
  - Consumes from HEAD `dc841639`: `script/gnome-extension/erplibre_home/tools/enable_next_login.py UUID` (stdlib only; reads both lists with `gsettings`, writes `disabled-extensions` first, then `enabled-extensions`; exit 0 written, 1 gsettings failed, 2 usage) and `tools/gsettings_strv.py` (`parse_strv`, `format_strv`; `format_strv([])` is `[]`).
  - `on_session_bus CMD...` runs a command on the bus of an open session (`DBUS_SESSION_BUS_ADDRESS`, else `/run/user/<uid>/bus`), else under `dbus-run-session --`; `gsettings_bus` is `on_session_bus gsettings`.
  - `uuid_list_edit` reads the list with `gsettings_strv.parse_strv`, imported through `sys.path` from `${EXT_SRC}/tools`: `has` prints `yes`/`no`, `remove` prints the list without the UUID (`format_strv`) or the input unchanged when it is absent; an unreadable list exits non-zero. There is no `add` mode: enabling goes through the helper.
  - `install_packages` installs `level_packages` in one command, EPEL first only with `--stream-deck` on AlmaLinux and Rocky, then each extra alone.
  - `compile_locales` runs `msgfmt --check -o <mo> <po>` per language, no venv; a `msgfmt` failure, or a missing `msgfmt` (`msgfmt is missing; install <gettext_package>`), exits 1.
  - `uninstall_streamdeck` removes the udev rule (then `udevadm control --reload-rules`) and `.venv.streamdeck` when present; `uninstall` removes the UUID from `enabled-extensions` and the link, then calls it. `step_uninstall` runs `uninstall_streamdeck` with `--stream-deck`, `uninstall` without.
  - `gsettings_bus` writes on the bus of an open session (`DBUS_SESSION_BUS_ADDRESS`, else `/run/user/<uid>/bus`) and uses `dbus-run-session` only when neither exists. This refines spec 4.1 step 6, which names only the variable: over ssh into a machine whose GNOME session runs, as in Task 9's idempotence and reinstall checks, the variable is unset while the session's dconf-service is live.
  - `enable_extension` runs `on_session_bus "${EXT_SRC}/tools/enable_next_login.py" "${UUID}"`, the helper `make erplibre_home_enable_extension` falls back to, so the UUID leaves `disabled-extensions` before it enters `enabled-extensions`, by one implementation; then sets `disable-user-extensions` to `false` and reads the three keys back.
  - `link_extension` first runs `"${EXT_SRC}/tools/migrate_legacy.py"`, on every run and whatever the entry point (make, TODO, QEMU, long test), so the migration runs once per install; a migration that cannot start is logged and never stops the install. It then stops with exit 1 and a message naming `EXT_LINK` when a real directory or file sits there; it never deletes it.
  - The source guard: sourced with `ERPLIBRE_HOME_SOURCE_ONLY=1`, the script defines its functions and does not run `main`. Run normally, an `EXIT` trap turns a stray exit 2 from a called command into 1, so only `unsupported` exits 2.
  - Make targets, two pairs: `erplibre_home_install` (the installer, base) and `erplibre_home_uninstall` (`--uninstall`); `erplibre_home_streamdeck_install` (`--stream-deck`) and `erplibre_home_streamdeck_uninstall` (`--uninstall --stream-deck`). The new `erplibre_home_uninstall` replaces the alias of `erplibre_home_uninstall_extension` that carried the name. `erplibre_home_install_extension` delegates to `./script/install/install_erplibre_home.sh --extension-only`. Task 1's guard message already names `make erplibre_home_streamdeck_install`.
- The `--dry-run` output is unchanged from Task 3 (both levels, both uninstalls). There is no `enable:` line.

- [ ] **Step 1: Write the failing tests**

In the import block of `test/test_install_erplibre_home.py`, add `import shutil` between `import os` and `import subprocess`.

Append the following after Task 3's test classes and before the closing `if __name__ == "__main__":` block. The closing block must stay last. `RACINE`, `SCRIPT`, `EXTENSION`, `UUID` and the `json` import come from Task 3.
```python
INSTALLEUR = SCRIPT
MAKEFILE_STREAMDECK = RACINE / "conf/make.streamdeck.Makefile"


def sourcer(fragment, env=None):
    """Source l'installateur sans lancer main, puis joue `fragment`.

    ERPLIBRE_HOME_SOURCE_ONLY=1 définit les fonctions et s'arrête ; le
    fragment les redéfinit au besoin (sudo, gsettings_bus…) avant de les
    appeler. DBUS_SESSION_BUS_ADDRESS est retiré de l'environnement, sauf
    si `env` le pose. Rend le CompletedProcess.
    """
    if "ERPLIBRE_HOME_SOURCE_ONLY" not in INSTALLEUR.read_text(
        encoding="utf-8"
    ):
        raise AssertionError(
            "install_erplibre_home.sh has no ERPLIBRE_HOME_SOURCE_ONLY guard: "
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
    """uuid_list_edit : les deux formes que gsettings affiche, lues par
    tools/gsettings_strv.py."""

    def editer(self, mode, courant):
        fait = sourcer(
            'uuid_list_edit "$MODE" "$COURANT" "$UUID"\n',
            {"MODE": mode, "COURANT": courant, "UUID": UUID},
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        return fait.stdout.strip()

    def test_la_presence_se_lit_dans_les_deux_formes(self):
        self.assertEqual(self.editer("has", "@as []"), "no")
        self.assertEqual(
            self.editer("has", "['autre@exemple.org', '%s']" % UUID), "yes"
        )
        self.assertEqual(self.editer("has", "['autre@exemple.org']"), "no")

    def test_le_retrait_garde_les_autres(self):
        self.assertEqual(
            self.editer("remove", "['autre@exemple.org', '%s']" % UUID),
            "['autre@exemple.org']",
        )

    def test_le_retrait_au_milieu_garde_l_ordre_des_autres(self):
        """La forme de disabled-extensions quand l'application Extensions y
        a rangé l'UUID parmi d'autres."""
        courant = "['a@exemple.org', '%s', 'b@exemple.org']" % UUID
        self.assertEqual(
            self.editer("remove", courant),
            "['a@exemple.org', 'b@exemple.org']",
        )

    def test_le_retrait_du_dernier_rend_une_liste_vide(self):
        """La forme qu'écrit gsettings_strv.format_strv, que gsettings
        accepte pour une clé « as »."""
        self.assertEqual(self.editer("remove", "['%s']" % UUID), "[]")

    def test_retirer_un_absent_rend_l_entree_inchangee(self):
        self.assertEqual(self.editer("remove", "@as []"), "@as []")

    def test_une_liste_illisible_sort_en_erreur(self):
        fait = sourcer(
            'uuid_list_edit has "$COURANT" "$UUID"\n',
            {"COURANT": "No such schema", "UUID": UUID},
        )
        self.assertNotEqual(fait.returncode, 0)

    def test_le_lecteur_est_celui_des_outils(self):
        """Un seul lecteur des listes de gsettings : celui que partagent
        migrate_legacy.py et enable_next_login.py."""
        texte = INSTALLEUR.read_text(encoding="utf-8")
        self.assertIn(
            "from gsettings_strv import format_strv, parse_strv", texte
        )
        self.assertIn('"${EXT_SRC}/tools" "$@"', texte)


class TestRegleUdev(unittest.TestCase):
    def test_le_contenu_est_les_deux_lignes_uaccess(self):
        fait = sourcer("udev_rule_content\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(
            fait.stdout,
            'SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"\n'
            'KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"\n',
        )

    def test_une_regle_identique_n_est_ni_reecrite_ni_rechargee(self):
        """La seconde exécution ne touche ni au fichier ni à udev."""
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            fragment = (
                'UDEV_RULE="$DOSSIER/70-streamdeck.rules"\n'
                'sudo() { echo "sudo $*" >>"$JOURNAL"; "$@"; }\n'
                'udevadm() { echo "udevadm $*" >>"$JOURNAL"; }\n'
                "write_udev_rule\n"
                'echo "--- second ---" >>"$JOURNAL"\n'
                "write_udev_rule\n"
            )
            fait = sourcer(fragment, {"DOSSIER": dossier, "JOURNAL": journal})
            self.assertEqual(fait.returncode, 0, fait.stderr)
            appels = Path(journal).read_text().split("--- second ---\n")
            self.assertIn("udevadm control --reload-rules", appels[0])
            self.assertIn("udevadm trigger", appels[0])
            self.assertEqual(appels[1], "")
            self.assertIn(
                'TAG+="uaccess"',
                Path(dossier, "70-streamdeck.rules").read_text(),
            )


class TestPaquets(unittest.TestCase):
    """install_packages : les paquets du niveau sont fatals, chaque extra est
    facultatif, EPEL ne vient qu'avec --stream-deck."""

    FRAGMENT = (
        'packages_for() { echo "base1 base2"; }\n'
        'streamdeck_packages_for() { echo "deck1 base2"; }\n'
        'extras_for() { echo "extra1 extra2"; }\n'
        "sudo() {\n"
        '    echo "$*" >>"$JOURNAL"\n'
        '    case "$*" in *extra1*) return 1 ;; esac\n'
        "}\n"
        "FAMILY=rhel\n"
        'OS="$OS_TEST"\n'
        'STREAM_DECK="$NIVEAU"\n'
        'WITH_EXTRAS="$EXTRAS"\n'
        "install_packages\n"
    )

    def jouer(self, os_id, extras, stream_deck="0"):
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            Path(journal).touch()
            fait = sourcer(
                self.FRAGMENT,
                {
                    "JOURNAL": journal,
                    "OS_TEST": os_id,
                    "EXTRAS": extras,
                    "NIVEAU": stream_deck,
                },
            )
            return fait, Path(journal).read_text().splitlines()

    def test_sans_extras_seule_la_base_est_installee(self):
        fait, appels = self.jouer("ubuntu", "0")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(appels, ["dnf install -y base1 base2"])

    def test_le_stream_deck_ajoute_ses_paquets_sans_doublon(self):
        fait, appels = self.jouer("fedora", "0", stream_deck="1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(appels, ["dnf install -y base1 base2 deck1"])

    def test_un_extra_absent_avertit_et_n_arrete_rien(self):
        fait, appels = self.jouer("ubuntu", "1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(
            appels,
            [
                "dnf install -y base1 base2",
                "dnf install -y extra1",
                "dnf install -y extra2",
            ],
        )
        self.assertIn("extra1", fait.stdout)
        self.assertIn("WARNING", fait.stdout)

    def test_epel_precede_le_stream_deck_sur_rocky_et_alma(self):
        for os_id in ("rocky", "almalinux"):
            with self.subTest(os_id=os_id):
                fait, appels = self.jouer(os_id, "0", stream_deck="1")
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(appels[0], "dnf install -y epel-release")

    def test_la_base_ne_touche_pas_a_epel(self):
        for os_id in ("rocky", "almalinux"):
            with self.subTest(os_id=os_id):
                fait, appels = self.jouer(os_id, "0")
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(appels, ["dnf install -y base1 base2"])

    def test_pas_d_epel_sur_fedora(self):
        fait, appels = self.jouer("fedora", "0", stream_deck="1")
        self.assertNotIn("dnf install -y epel-release", appels)


class TestActivation(unittest.TestCase):
    """enable_extension sur un gsettings simulé par des fichiers, en tête du
    PATH, qui note chacun de ses appels. tools/enable_next_login.py, que le
    script lance, l'appelle comme le script lui-même ; gdbus et
    gnome-extensions sont simulés aussi."""

    CLES = (
        "enabled-extensions",
        "disabled-extensions",
        "disable-user-extensions",
    )

    def jouer(
        self, enabled, disable_user, disabled="@as []", ecrit=True, shell=False
    ):
        with tempfile.TemporaryDirectory() as dossier:
            valeurs = {
                "enabled-extensions": enabled,
                "disabled-extensions": disabled,
                "disable-user-extensions": disable_user,
            }
            for cle, valeur in valeurs.items():
                Path(dossier, cle).write_text(valeur + "\n")
            Path(dossier, "appels").touch()
            faux = Path(dossier, "bin")
            faux.mkdir()
            ecriture = (
                'printf "%s\\n" "$4" >"$DOSSIER/$3"'
                if ecrit
                else ":"  # une écriture qui ne prend pas
            )
            commandes = {
                "gsettings": (
                    'echo "$*" >>"$DOSSIER/appels"\n'
                    'case "$1" in\n'
                    '    get) cat "$DOSSIER/$3" ;;\n'
                    "    set) " + ecriture + " ;;\n"
                    "esac\n"
                ),
                # NameHasOwner : GNOME Shell tourne-t-il sur le bus ?
                "gdbus": "echo '(%s,)'\n" % ("true" if shell else "false"),
                "gnome-extensions": (
                    'echo "gnome-extensions $*" >>"$DOSSIER/appels"\n'
                ),
            }
            for nom, corps in commandes.items():
                (faux / nom).write_text("#!/bin/sh\n" + corps)
                (faux / nom).chmod(0o755)
            fragment = (
                'PATH="$FAUX:$PATH"\n'
                'shell_bus_address() { echo "unix:path=$DOSSIER/bus"; }\n'
                "enable_extension\n"
            )
            fait = sourcer(fragment, {"DOSSIER": dossier, "FAUX": str(faux)})
            etat = {
                cle: Path(dossier, cle).read_text().strip()
                for cle in self.CLES
            }
            appels = Path(dossier, "appels").read_text().splitlines()
            return fait, etat, appels

    def test_l_uuid_est_ajoute_et_les_extensions_permises(self):
        fait, etat, _appels = self.jouer("@as []", "true")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["enabled-extensions"], "['%s']" % UUID)
        self.assertEqual(etat["disable-user-extensions"], "false")

    def test_une_liste_deja_complete_n_est_pas_reecrite(self):
        courant = "['autre@exemple.org', '%s']" % UUID
        fait, etat, appels = self.jouer(courant, "false")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["enabled-extensions"], courant)
        self.assertEqual([a for a in appels if a.startswith("set ")], [])

    def test_une_ecriture_qui_ne_prend_pas_fait_echouer(self):
        fait, _etat, _appels = self.jouer("@as []", "true", ecrit=False)
        self.assertEqual(fait.returncode, 1)
        self.assertIn(UUID, fait.stderr)

    def test_l_uuid_desactive_par_l_utilisateur_est_retire_d_abord(self):
        """Éteinte un jour dans l'application Extensions, l'extension reste
        dans disabled-extensions, qui l'emporte sur enabled-extensions.
        Elle en sort AVANT d'entrer dans enabled-extensions : un échec entre
        les deux ne la laisse jamais dans les deux listes."""
        fait, etat, appels = self.jouer(
            "@as []",
            "false",
            disabled="['autre@exemple.org', '%s']" % UUID,
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["disabled-extensions"], "['autre@exemple.org']")
        self.assertEqual(etat["enabled-extensions"], "['%s']" % UUID)
        retrait = (
            "set org.gnome.shell disabled-extensions ['autre@exemple.org']"
        )
        ajout = "set org.gnome.shell enabled-extensions ['%s']" % UUID
        self.assertLess(appels.index(retrait), appels.index(ajout))

    def test_disabled_extensions_sans_l_uuid_n_est_pas_reecrite(self):
        fait, etat, appels = self.jouer(
            "['%s']" % UUID, "false", disabled="['autre@exemple.org']"
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["disabled-extensions"], "['autre@exemple.org']")
        self.assertFalse([a for a in appels if a.startswith("set ")], appels)

    def test_l_activation_passe_par_l_aide_de_make(self):
        """make erplibre_home_enable_extension et l'installateur écrivent
        les listes par le même code."""
        texte = INSTALLEUR.read_text(encoding="utf-8")
        self.assertIn(
            'on_session_bus "${EXT_SRC}/tools/enable_next_login.py" "${UUID}"',
            texte,
        )
        self.assertNotIn("uuid_list_edit add", texte)

    def test_gnome_extensions_enable_seulement_shell_en_marche(self):
        for shell in (False, True):
            with self.subTest(shell=shell):
                fait, _etat, appels = self.jouer("@as []", "true", shell=shell)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(
                    shell, "gnome-extensions enable %s" % UUID in appels
                )


class TestBusDeSession(unittest.TestCase):
    """gsettings_bus : le bus de la session ouverte d'abord.

    Une écriture faite sous dbus-run-session pendant qu'une session tourne
    passe par un second dconf-service ; celui de la session ne la voit pas
    et peut la recouvrir.
    """

    FRAGMENT = (
        "gsettings() {\n"
        '    echo "gsettings[${DBUS_SESSION_BUS_ADDRESS:-}] $*"\n'
        "}\n"
        'dbus-run-session() { echo "drs $*"; }\n'
        "gsettings_bus set org.gnome.shell disable-user-extensions false\n"
    )
    SUR_LE_BUS = (
        "gsettings[unix:path=/exemple/bus]"
        " set org.gnome.shell disable-user-extensions false"
    )

    def test_la_variable_de_session_recoit_l_ecriture(self):
        fait = sourcer(
            self.FRAGMENT,
            {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/exemple/bus"},
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(fait.stdout.strip(), self.SUR_LE_BUS)
        self.assertNotIn("drs", fait.stdout)

    def test_sans_variable_le_socket_du_compte_sert(self):
        """ssh dans une machine dont la session graphique est ouverte."""
        fait = sourcer(
            'shell_bus_address() { echo "unix:path=/exemple/bus"; }\n'
            + self.FRAGMENT
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(fait.stdout.strip(), self.SUR_LE_BUS)

    def test_sans_aucun_bus_dbus_run_session_prend_le_relais(self):
        fait = sourcer("shell_bus_address() { return 1; }\n" + self.FRAGMENT)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(
            fait.stdout.strip(),
            "drs -- gsettings set org.gnome.shell disable-user-extensions"
            " false",
        )


class TestDesinstallation(unittest.TestCase):
    def test_retire_lien_regle_venv_et_uuid(self):
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier, "extensions")
            base.mkdir()
            (base / UUID).symlink_to(EXTENSION)
            Path(dossier, "70-streamdeck.rules").write_text("x\n")
            Path(dossier, "venv/bin").mkdir(parents=True)
            Path(dossier, "enabled-extensions").write_text(
                "['autre@exemple.org', '%s']\n" % UUID
            )
            fragment = (
                'EXT_LINK="$DOSSIER/extensions/$UUID"\n'
                'UDEV_RULE="$DOSSIER/70-streamdeck.rules"\n'
                'VENV="$DOSSIER/venv"\n'
                'sudo() { "$@"; }\n'
                "udevadm() { :; }\n"
                "gsettings_bus() {\n"
                '    case "$1" in\n'
                '        get) cat "$DOSSIER/$3" ;;\n'
                '        set) printf "%s\\n" "$4" >"$DOSSIER/$3" ;;\n'
                "    esac\n"
                "}\n"
                "uninstall\n"
            )
            fait = sourcer(fragment, {"DOSSIER": dossier, "UUID": UUID})
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertFalse(os.path.lexists(base / UUID))
            self.assertFalse(Path(dossier, "70-streamdeck.rules").exists())
            self.assertFalse(Path(dossier, "venv").exists())
            self.assertEqual(
                Path(dossier, "enabled-extensions").read_text().strip(),
                "['autre@exemple.org']",
            )
            # Le checkout pointé par le lien n'est pas touché.
            self.assertTrue((EXTENSION / "metadata.json").exists())

    def test_le_niveau_stream_deck_seul_garde_l_extension(self):
        """--uninstall --stream-deck : la règle, la relecture des règles et
        le venv partent ; le lien et enabled-extensions restent. Une seconde
        exécution n'appelle plus ni sudo ni udevadm."""
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier, "extensions")
            base.mkdir()
            (base / UUID).symlink_to(EXTENSION)
            Path(dossier, "70-streamdeck.rules").write_text("x\n")
            Path(dossier, "venv/bin").mkdir(parents=True)
            journal = Path(dossier, "appels")
            journal.touch()
            fragment = (
                'EXT_LINK="$DOSSIER/extensions/$UUID"\n'
                'UDEV_RULE="$DOSSIER/70-streamdeck.rules"\n'
                'VENV="$DOSSIER/venv"\n'
                'sudo() { echo "sudo $*" >>"$JOURNAL"; "$@"; }\n'
                "udevadm() { :; }\n"
                'gsettings_bus() { echo "gsettings $*" >>"$JOURNAL"; }\n'
                "STREAM_DECK=1\n"
                "step_uninstall\n"
                'echo "--- second ---" >>"$JOURNAL"\n'
                "step_uninstall\n"
            )
            fait = sourcer(
                fragment,
                {"DOSSIER": dossier, "UUID": UUID, "JOURNAL": str(journal)},
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertFalse(Path(dossier, "70-streamdeck.rules").exists())
            self.assertFalse(Path(dossier, "venv").exists())
            self.assertTrue((base / UUID).is_symlink())
            premier, second = journal.read_text().split("--- second ---\n")
            self.assertIn("sudo udevadm control --reload-rules", premier)
            self.assertNotIn("gsettings", premier + second)
            self.assertEqual(second, "")

    def test_un_repertoire_ordinaire_reste_en_place(self):
        with tempfile.TemporaryDirectory() as dossier:
            cible = Path(dossier, "extensions", UUID)
            cible.mkdir(parents=True)
            (cible / "metadata.json").write_text("{}")
            fragment = (
                'EXT_LINK="$DOSSIER/extensions/$UUID"\n'
                'UDEV_RULE="$DOSSIER/absente.rules"\n'
                'VENV="$DOSSIER/venv"\n'
                "gsettings_bus() { return 1; }\n"
                "uninstall\n"
            )
            fait = sourcer(fragment, {"DOSSIER": dossier, "UUID": UUID})
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertTrue((cible / "metadata.json").exists())


OUTILS_EXTENSION = shutil.which("glib-compile-schemas") and shutil.which(
    "msgfmt"
)


class TestExtensionSeule(unittest.TestCase):
    """--extension-only sur une copie du checkout, HOME temporaire.

    La copie porte l'installateur et l'extension, sous un répertoire dont le
    nom contient une espace : chaque chemin que le script bâtit doit être
    cité. Les schémas et les traductions se compilent pour de vrai, par
    glib-compile-schemas et msgfmt, sans venv ni réseau, et rien n'est écrit
    dans le vrai checkout. Une fausse migration remplace la vraie dans la
    copie : la vraie lirait le bus de session de l'utilisateur et sa base
    dconf.
    """

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        racine = Path(self._dossier.name)
        self.depot = racine / "copie du depot"
        self.home = racine / "home"
        self.home.mkdir()
        (self.depot / "script/install").mkdir(parents=True)
        shutil.copy2(INSTALLEUR, self.depot / "script/install")
        shutil.copytree(
            EXTENSION,
            self.depot / "script/gnome-extension/erplibre_home",
            symlinks=True,
            ignore=shutil.ignore_patterns("locale", "gschemas.compiled"),
        )
        # Un faux sudo en tête du PATH : --extension-only ne doit jamais
        # l'appeler, et s'il le fait, rien ne s'exécute en root.
        self.trace_sudo = racine / "sudo.appele"
        self.faux_bin = racine / "bin"
        self.faux_bin.mkdir()
        sudo = self.faux_bin / "sudo"
        sudo.write_text(
            '#!/bin/sh\necho "$@" >>"%s"\nexit 1\n' % self.trace_sudo
        )
        sudo.chmod(0o755)
        self.path = "%s:%s" % (self.faux_bin, os.environ.get("PATH", ""))
        self.lien = self.home / ".local/share/gnome-shell/extensions" / UUID
        self.source = self.depot / "script/gnome-extension/erplibre_home"
        # La fausse migration note si le lien existait à son appel.
        self.migrations = racine / "migrations"
        migration = self.source / "tools/migrate_legacy.py"
        migration.write_text(
            "#!/bin/sh\n"
            'if [ -L "%s" ]; then echo apres; else echo avant; fi >>"%s"\n'
            % (self.lien, self.migrations)
        )
        migration.chmod(0o755)

    def tearDown(self):
        self._dossier.cleanup()

    def lancer(self, *options, env=None):
        environ = dict(os.environ)
        environ.update(
            {
                "HOME": str(self.home),
                "ERPLIBRE_HOME_UID": "1000",
                "PATH": self.path,
            }
        )
        environ.update(env or {})
        return subprocess.run(
            [
                "bash",
                str(self.depot / "script/install/install_erplibre_home.sh"),
                "--extension-only",
                *options,
            ],
            capture_output=True,
            text=True,
            env=environ,
            cwd="/",
            timeout=60,
        )

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_lien_schemas_et_locales(self):
        fait = self.lancer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(os.readlink(self.lien), str(self.source))
        # Une migration, avant que le lien existe.
        self.assertEqual("avant\n", self.migrations.read_text())
        self.assertTrue((self.source / "schemas/gschemas.compiled").exists())
        langues = sorted(p.stem for p in (self.source / "po").glob("*.po"))
        self.assertIn("fr", langues)
        for langue in langues:
            with self.subTest(langue=langue):
                self.assertTrue(
                    (
                        self.source
                        / "locale"
                        / langue
                        / "LC_MESSAGES/erplibre-home.mo"
                    )
                    .stat()
                    .st_size
                )
        self.assertFalse(self.trace_sudo.exists())
        # Ni venv ni polib : la base n'en a pas.
        self.assertFalse((self.depot / ".venv.streamdeck").exists())

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_un_checkout_dont_le_chemin_porte_une_espace(self):
        """Le lien vise le chemin entier, espace comprise, et non le
        morceau qui la précède."""
        self.assertIn(" ", str(self.source))
        fait = self.lancer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertTrue(self.lien.is_symlink())
        self.assertEqual(os.readlink(self.lien), str(self.source))
        self.assertTrue((self.lien / "metadata.json").exists())
        self.assertFalse(Path(str(self.depot).split(" ")[0]).exists())

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_une_seconde_execution_laisse_le_lien(self):
        self.assertEqual(self.lancer().returncode, 0)
        avant = os.lstat(self.lien).st_mtime_ns
        fait = self.lancer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(os.lstat(self.lien).st_mtime_ns, avant)

    def test_dry_run_n_ecrit_rien(self):
        fait = self.lancer("--dry-run")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("write: %s" % self.lien, fait.stdout)
        self.assertFalse(os.path.lexists(self.lien))

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_un_schema_invalide_fait_echouer(self):
        schema = next((self.source / "schemas").glob("*.gschema.xml"))
        schema.write_text("<schemalist><schema id='casse'>")
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1)

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_un_po_refuse_par_msgfmt_fait_echouer(self):
        (self.source / "po/fr.po").write_text('msgid "x"\n')
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1)

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_un_code_2_d_une_commande_sort_en_1(self):
        """2 est réservé à UNSUPPORTED : une commande qui rend 2 et arrête
        le script sous set -e le fait sortir en 1."""
        msgfmt = self.faux_bin / "msgfmt"
        msgfmt.write_text("#!/bin/sh\nexit 2\n")
        msgfmt.chmod(0o755)
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1, fait.stderr)
        self.assertNotIn("UNSUPPORTED", fait.stderr)

    def test_un_repertoire_ordinaire_arrete_l_installation_et_reste(self):
        """Une copie posée à la main par une ancienne installation : le
        script s'arrête en 1 en nommant le chemin, et n'y touche pas."""
        self.lien.mkdir(parents=True)
        (self.lien / "metadata.json").write_text("{}")
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1, fait.stdout)
        self.assertIn(str(self.lien), fait.stderr)
        self.assertNotIn("UNSUPPORTED", fait.stderr)
        self.assertEqual((self.lien / "metadata.json").read_text(), "{}")
        self.assertFalse(self.lien.is_symlink())


class TestTraductions(unittest.TestCase):
    """compile_locales sans msgfmt : l'installation s'arrête et nomme le
    paquet gettext de la famille."""

    def test_sans_msgfmt_le_message_nomme_le_paquet(self):
        attendus = {
            "debian": "install gettext",
            "suse": "install gettext-tools",
            "": "install gettext (gettext-tools on openSUSE)",
        }
        with tempfile.TemporaryDirectory() as vide:
            for famille, attendu in attendus.items():
                with self.subTest(famille=famille):
                    fait = sourcer(
                        'FAMILY="$FAM"\nPATH="$VIDE"\ncompile_locales\n',
                        {"FAM": famille, "VIDE": vide},
                    )
                    self.assertEqual(fait.returncode, 1, fait.stderr)
                    self.assertIn("msgfmt is missing; " + attendu, fait.stderr)


class TestLectureShellVersion(unittest.TestCase):
    """shell_versions lit metadata.json par tr, grep et sed : un python3
    qui échoue en tête du PATH ne change rien à ce qu'elle rend."""

    def lire(self, contenu=None):
        with tempfile.TemporaryDirectory() as dossier:
            faux = Path(dossier, "bin")
            faux.mkdir()
            for nom in ("python3", "python"):
                (faux / nom).write_text("#!/bin/sh\nexit 1\n")
                (faux / nom).chmod(0o755)
            env = {"FAUX": str(faux)}
            fragment = 'PATH="$FAUX:$PATH"\n'
            if contenu is not None:
                Path(dossier, "metadata.json").write_text(contenu)
                env["DOSSIER"] = dossier
                fragment += 'METADATA="$DOSSIER/metadata.json"\n'
            fait = sourcer(fragment + "shell_versions || true\n", env)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        return fait.stdout.strip()

    def test_la_liste_est_celle_de_json_load(self):
        with open(EXTENSION / "metadata.json", encoding="utf-8") as flux:
            attendu = " ".join(json.load(flux)["shell-version"])
        self.assertEqual(self.lire(), attendu)

    def test_un_tableau_sur_une_ligne(self):
        self.assertEqual(
            self.lire('{"uuid": "x", "shell-version": ["45", "46"], "v": 1}'),
            "45 46",
        )

    def test_un_tableau_sur_plusieurs_lignes(self):
        contenu = (
            '{\n  "shell-version": [\n    "47",\n    "48"\n  ],\n'
            '  "url": "https://exemple.invalid"\n}\n'
        )
        self.assertEqual(self.lire(contenu), "47 48")

    def test_sans_la_cle_la_liste_est_vide(self):
        self.assertEqual(self.lire('{"uuid": "x"}'), "")


def recette(cible):
    """Les lignes de recette de `cible` dans make.streamdeck.Makefile."""
    lignes = MAKEFILE_STREAMDECK.read_text().splitlines()
    debut = lignes.index("%s:" % cible) + 1
    recette_ = []
    for ligne in lignes[debut:]:
        if not ligne.startswith("\t"):
            break
        recette_.append(ligne.strip())
    return recette_


class TestMakefile(unittest.TestCase):
    def test_l_extension_passe_par_l_installateur(self):
        lignes = recette("erplibre_home_install_extension")
        self.assertEqual(
            lignes[0],
            "@./script/install/install_erplibre_home.sh --extension-only",
        )
        self.assertFalse(
            any("glib-compile-schemas" in ligne for ligne in lignes)
        )
        self.assertFalse(any("ln -s" in ligne for ligne in lignes))
        # La migration de l'ancienne identité a quitté la recette pour le
        # lien de l'installateur, qui la lance avant « ln -sfn » : elle
        # tourne une fois par installation, quel que soit le chemin d'entrée.
        self.assertFalse(any("migrate_legacy" in ligne for ligne in lignes))
        texte = INSTALLEUR.read_text(encoding="utf-8")
        self.assertLess(
            texte.index('"${EXT_SRC}/tools/migrate_legacy.py"'),
            texte.index('ln -sfn "${EXT_SRC}" "${EXT_LINK}"'),
        )
        # Les indications pour recharger restent.
        self.assertTrue(
            any(
                "make erplibre_home_enable_extension" in ligne
                for ligne in lignes
            )
        )

    def test_aucune_compilation_de_schema_n_avale_son_echec(self):
        for ligne in MAKEFILE_STREAMDECK.read_text().splitlines():
            if "glib-compile-schemas" in ligne:
                self.assertNotIn("|| true", ligne)
                self.assertNotIn("2>/dev/null", ligne)

    def test_les_deux_niveaux_s_installent_et_se_retirent(self):
        texte = MAKEFILE_STREAMDECK.read_text()
        attendues = {
            "erplibre_home_install": "",
            "erplibre_home_uninstall": " --uninstall",
            "erplibre_home_streamdeck_install": " --stream-deck",
            "erplibre_home_streamdeck_uninstall": " --uninstall --stream-deck",
        }
        for cible, options in attendues.items():
            with self.subTest(cible=cible):
                self.assertIn(".PHONY: %s\n" % cible, texte)
                self.assertEqual(
                    recette(cible),
                    ["./script/install/install_erplibre_home.sh" + options],
                )
```
`sourcer()` refuses to source a script that has no guard. Without the guard, sourcing would run Task 3's `main`. `TestActivation` puts fake `gsettings`, `gdbus` and `gnome-extensions` first in `PATH`, file-backed: the real `tools/enable_next_login.py` that the installer runs reaches the fake `gsettings`, never the user's session. `TestExtensionSeule` puts a fake `sudo` at the front of `PATH`, so nothing runs as root, even during the red phase; it compiles the schemas and the translations for real, so its tests that run the install need `glib-compile-schemas` and `msgfmt`, and are skipped where either is missing.

The Review Focus lines map to these tests:
- a checkout path with a space: `TestExtensionSeule` runs every case from `copie du depot`, and `test_un_checkout_dont_le_chemin_porte_une_espace` checks the link target;
- a UUID in `disabled-extensions`: `test_le_retrait_au_milieu_garde_l_ordre_des_autres`, `test_l_uuid_desactive_par_l_utilisateur_est_retire_d_abord` and `test_disabled_extensions_sans_l_uuid_n_est_pas_reecrite`;
- a real directory at the link path: `test_un_repertoire_ordinaire_arrete_l_installation_et_reste`;
- an open session: `TestBusDeSession`;
- one enable implementation for make and the installer, write order disabled → enabled: `test_l_activation_passe_par_l_aide_de_make`, `test_l_uuid_desactive_par_l_utilisateur_est_retire_d_abord`;
- a base install without the deck: `test_la_base_ne_touche_pas_a_epel`, and Task 3's dry-run tests;
- `--uninstall --stream-deck` keeps the extension: `test_le_niveau_stream_deck_seul_garde_l_extension`.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_install_erplibre_home -v`

Expected: FAIL, `Ran 72 tests`, `FAILED (failures=47, errors=1)`:
- every test that sources the script (`TestListeEnabledExtensions`, `TestRegleUdev`, `TestPaquets`, `TestActivation`, `TestBusDeSession`, `TestDesinstallation`, `TestTraductions`, `TestLectureShellVersion`) fails with `AssertionError: install_erplibre_home.sh has no ERPLIBRE_HOME_SOURCE_ONLY guard: sourcing it would run main`, once per subtest where it has some;
- the `TestMakefile` tests fail with `'|| true' unexpectedly found in …`, the old first recipe line (the migration call), and, in `test_les_deux_niveaux_s_installent_et_se_retirent`, three subtests on `'.PHONY: … \n' not found` (`erplibre_home_install` and the two Stream Deck targets) and one `ValueError` (the error) from `recette("erplibre_home_uninstall")`: HEAD's line is the alias `erplibre_home_uninstall: erplibre_home_uninstall_extension`, so `index("erplibre_home_uninstall:")` finds nothing;
- in `TestExtensionSeule`, the three tests that expect a link (`test_lien_schemas_et_locales`, `test_un_checkout_dont_le_chemin_porte_une_espace`, `test_une_seconde_execution_laisse_le_lien`) and `test_un_repertoire_ordinaire_arrete_l_installation_et_reste` fail: Task 3's stub dies with `étape pas encore implémentée : extension`. The three other non-dry tests expect exit 1 and pass by accident against that stub; `test_dry_run_n_ecrit_rien` already passes;
- Task 3's 28 tests still pass.

- [ ] **Step 3: Implement the installer steps**

Every edit below is in `script/install/install_erplibre_home.sh`, as Task 3 left it. Task 3's `main`, `parse_args`, `check_not_root` and dry-run branches stay as they are.

**3a.** Replace
```bash
unsupported() {
    echo "UNSUPPORTED: $*" >&2
    exit 2
}
```
with
```bash
unsupported() {
    UNSUPPORTED_EXIT=1
    echo "UNSUPPORTED: $*" >&2
    exit 2
}
```

**3b.** Replace the 3-line function
```bash
not_implemented() {
    die "étape pas encore implémentée : $1"
}
```
with this block:
```bash
# ---------- Installation ----------

REQUIREMENTS="${RACINE}/script/stream_deck/requirements.txt"

# Ce que l'exécution a réellement changé, une ligne par effet, pour le bilan.
DONE=()

# EPEL au besoin (--stream-deck sur AlmaLinux et Rocky Linux), les paquets
# du niveau, puis chaque extra seul. Chaque ligne est celle de package_cmd,
# celle même que --dry-run affiche ; eval l'exécute, et chacun de ses mots
# est un littéral de packages_for, streamdeck_packages_for, extras_for ou
# « epel-release ». L'échec des paquets du niveau arrête l'installation
# (set -e) ; celui d'un extra n'est qu'un avertissement, et un extra absent
# du dépôt ne fait échouer que sa propre commande.
install_packages() {
    local level pkg
    if [ "${STREAM_DECK}" = 1 ] && needs_epel; then
        eval "$(package_cmd "${FAMILY}" epel-release)"
    fi
    level="$(level_packages "${FAMILY}")"
    # shellcheck disable=SC2086
    eval "$(package_cmd "${FAMILY}" ${level})"
    DONE+=("system packages: ${level}")
    [ "${WITH_EXTRAS}" = 1 ] || return 0
    for pkg in $(extras_for "${FAMILY}"); do
        if eval "$(package_cmd "${FAMILY}" "${pkg}")"; then
            DONE+=("optional package: ${pkg}")
        else
            log "WARNING: optional package ${pkg} not installed, skipped"
        fi
    done
}

# ---------- Règle udev ----------

# Le contenu exact de la règle. « uaccess » donne l'accès à l'utilisateur
# assis devant le poste sur toutes les familles, là où le groupe plugdev
# n'existe que sur Debian et Ubuntu. Le préfixe 70- passe avant
# 73-seat-late.rules, qui applique uaccess.
udev_rule_content() {
    printf '%s\n' \
        'SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"' \
        'KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"'
}

# Écrit la règle seulement si le fichier en place diffère (cmp), et ne
# recharge udev que dans ce cas : une seconde exécution ne touche ni au
# fichier ni à son mtime.
write_udev_rule() {
    if cmp -s <(udev_rule_content) "${UDEV_RULE}"; then
        log "udev rule already in place: ${UDEV_RULE}"
        return 0
    fi
    udev_rule_content | sudo tee "${UDEV_RULE}" >/dev/null
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    DONE+=("udev rule: ${UDEV_RULE}")
}

# ---------- venv ----------

# Crée le venv avec le python3 du système s'il manque, puis y installe les
# dépendances. pip ne réinstalle pas ce qui est déjà satisfait : le venv
# existant garde son contenu.
make_venv() {
    if [ ! -x "${VENV}/bin/python" ]; then
        python3 -m venv "${VENV}"
        DONE+=("venv created: ${VENV}")
    fi
    "${VENV}/bin/python" -m pip install --quiet --disable-pip-version-check \
        -r "${REQUIREMENTS}"
}

# ---------- Extension GNOME ----------

# Pose le lien vers le checkout, sauf s'il pointe déjà au bon endroit. Un
# répertoire ou un fichier ordinaire à cette place (une copie posée à la
# main, une extension installée depuis une archive) n'est jamais écrasé :
# l'installation s'arrête en le nommant. « ln -sfn » sur un répertoire
# créerait d'ailleurs le lien DEDANS.
#
# La migration de l'ancienne identité passe d'abord, à chaque exécution :
# elle libère l'ancien UUID, ses réglages et ses données, et reprend au
# passage suivant ce qu'une session absente a laissé. Elle rend toujours
# 0 ; le « || » couvre un bit d'exécution perdu ou un python3 absent, que
# « set -e » changerait sinon en arrêt de l'installation.
link_extension() {
    "${EXT_SRC}/tools/migrate_legacy.py" ||
        log "legacy migration did not run; the install goes on"
    mkdir -p "$(dirname "${EXT_LINK}")"
    if [ "$(readlink "${EXT_LINK}" 2>/dev/null || true)" = "${EXT_SRC}" ]; then
        log "extension link already in place: ${EXT_LINK}"
        return 0
    fi
    if [ -e "${EXT_LINK}" ] && [ ! -L "${EXT_LINK}" ]; then
        die "${EXT_LINK} exists and is not a symlink; move it away and rerun"
    fi
    ln -sfn "${EXT_SRC}" "${EXT_LINK}"
    DONE+=("extension link: ${EXT_LINK} -> ${EXT_SRC}")
}

# --strict refuse un schéma douteux ; son échec arrête l'installation, faute
# de quoi l'extension se chargerait sans réglages.
compile_schemas() {
    glib-compile-schemas --strict "${EXT_SRC}/schemas/"
}

# Le paquet qui porte msgfmt dans la famille. Sous --extension-only, la
# famille n'est pas lue : le message nomme alors les deux noms.
gettext_package() {
    case "$1" in
        suse) echo "gettext-tools" ;;
        debian | rhel | arch) echo "gettext" ;;
        *) echo "gettext (gettext-tools on openSUSE)" ;;
    esac
}

# Un .mo par po/<langue>.po, là où l'extension le cherche, par « msgfmt
# --check » : ni polib ni venv, msgfmt vient du paquet gettext de la base.
# --check refuse un format ou un en-tête faux ; ce refus, comme un msgfmt
# absent, arrête l'installation, faute de quoi l'extension se chargerait
# sans traductions.
compile_locales() {
    local lang mo
    command -v msgfmt >/dev/null 2>&1 \
        || die "msgfmt is missing; install $(gettext_package "${FAMILY}")"
    for lang in $(locale_langs); do
        mo="$(mo_file "${lang}")"
        mkdir -p "$(dirname "${mo}")"
        msgfmt --check -o "${mo}" "${EXT_SRC}/po/${lang}.po"
    done
}

# Lance une commande sur le bus de la session ouverte quand il y en a une :
# celui de l'environnement, sinon le socket du compte (ssh dans une machine
# dont la session graphique tourne). Le dconf-service de cette session garde
# la base qu'il a lue et la réécrit en entier : une écriture faite à côté,
# sous un dbus-run-session, lui échappe et peut être recouverte. Sans
# aucune session (ssh, VM fraîche), dbus-run-session lance un dconf-service
# à part qui écrit le profil de l'utilisateur, que la prochaine session lit.
on_session_bus() {
    local bus
    if bus="$(shell_bus_address)"; then
        DBUS_SESSION_BUS_ADDRESS="${bus}" "$@"
    else
        dbus-run-session -- "$@"
    fi
}

# gsettings, sur le bus que choisit on_session_bus.
gsettings_bus() {
    on_session_bus gsettings "$@"
}

# uuid_list_edit has <liste> <uuid> rend « yes » ou « no » ;
# uuid_list_edit remove <liste> <uuid> rend la liste GVariant « as » sans
# <uuid>, ou l'entrée telle quelle quand il n'y a rien à retirer :
# l'appelant compare pour savoir s'il doit écrire. La liste se lit par
# tools/gsettings_strv.py, le lecteur que partagent les outils de
# l'extension, qui accepte les deux formes que gsettings affiche,
# « @as [] » et « ['a', 'b'] ». Une liste illisible sort en erreur.
uuid_list_edit() {
    python3 -c '
import sys
sys.path.insert(0, sys.argv[1])
from gsettings_strv import format_strv, parse_strv
mode, current, uuid = sys.argv[2:5]
items = parse_strv(current)
if mode == "has":
    print("yes" if uuid in items else "no")
elif uuid in items:
    print(format_strv([item for item in items if item != uuid]))
else:
    print(current.strip())
' "${EXT_SRC}/tools" "$@"
}

# L'adresse d'un bus de session joignable : celle de l'environnement, sinon
# le socket du compte sous /run/user. Rien, et un code 1, quand aucun
# n'existe.
shell_bus_address() {
    if [ -n "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
        echo "${DBUS_SESSION_BUS_ADDRESS}"
        return 0
    fi
    local sock
    sock="/run/user/$(id -u)/bus"
    [ -S "${sock}" ] || return 1
    echo "unix:path=${sock}"
}

# Active l'extension pour le compte. Les deux listes s'écrivent par
# tools/enable_next_login.py, l'aide de la cible make
# erplibre_home_enable_extension, sur le bus que choisit on_session_bus :
# l'UUID retiré de disabled-extensions, où l'application Extensions le range
# quand on l'y éteint et qui l'emporte sur enabled-extensions, puis ajouté à
# enabled-extensions sans doublon. make et l'installateur activent donc par
# le même code. disable-user-extensions passe ensuite à false. Les trois
# clés sont relues ; une écriture qui n'a pas pris arrête l'installation.
# gnome-extensions enable ne sert que si GNOME Shell tourne déjà sur un bus
# joignable, et son échec n'arrête rien : la prochaine session charge
# l'extension depuis les clés.
enable_extension() {
    local enabled disabled bus
    enabled="$(gsettings_bus get org.gnome.shell enabled-extensions)"
    disabled="$(gsettings_bus get org.gnome.shell disabled-extensions)"
    on_session_bus "${EXT_SRC}/tools/enable_next_login.py" "${UUID}" >/dev/null \
        || die "enabled-extensions not written for ${UUID}"
    if [ "$(uuid_list_edit has "${disabled}" "${UUID}")" = yes ]; then
        DONE+=("disabled-extensions -= ${UUID}")
    fi
    if [ "$(uuid_list_edit has "${enabled}" "${UUID}")" = no ]; then
        DONE+=("enabled-extensions += ${UUID}")
    fi
    if [ "$(gsettings_bus get org.gnome.shell disable-user-extensions)" != "false" ]; then
        gsettings_bus set org.gnome.shell disable-user-extensions false
        DONE+=("disable-user-extensions = false")
    fi
    enabled="$(gsettings_bus get org.gnome.shell enabled-extensions)"
    if [ "$(uuid_list_edit has "${enabled}" "${UUID}")" != yes ]; then
        die "enabled-extensions does not hold ${UUID} after writing it"
    fi
    disabled="$(gsettings_bus get org.gnome.shell disabled-extensions)"
    if [ "$(uuid_list_edit has "${disabled}" "${UUID}")" != no ]; then
        die "disabled-extensions still holds ${UUID} after removing it"
    fi
    if [ "$(gsettings_bus get org.gnome.shell disable-user-extensions)" != "false" ]; then
        die "disable-user-extensions is still true after writing it"
    fi
    bus="$(shell_bus_address || true)"
    if [ -n "${bus}" ] && DBUS_SESSION_BUS_ADDRESS="${bus}" gdbus call --session \
        --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus \
        --method org.freedesktop.DBus.NameHasOwner org.gnome.Shell \
        2>/dev/null | grep -q true; then
        DBUS_SESSION_BUS_ADDRESS="${bus}" gnome-extensions enable "${UUID}" \
            || log "gnome-extensions enable failed; the next session loads the extension"
    fi
}

# ---------- Désinstallation ----------

# Retire le niveau Stream Deck : la règle udev, puis la relecture des règles,
# et le venv. Ce qui manque déjà est sauté, si bien qu'une seconde
# exécution n'appelle ni sudo ni udevadm.
uninstall_streamdeck() {
    if [ -e "${UDEV_RULE}" ]; then
        sudo rm -f "${UDEV_RULE}"
        sudo udevadm control --reload-rules
        DONE+=("removed ${UDEV_RULE}")
    fi
    if [ -e "${VENV}" ]; then
        rm -rf "${VENV}"
        DONE+=("removed ${VENV}")
    fi
}

# Défait tout ce que l'installation pose : l'UUID d'enabled-extensions, le
# lien, puis le niveau Stream Deck. Jamais de paquet système : d'autres
# logiciels peuvent s'en servir. Un répertoire ordinaire à la place du lien
# n'a pas été posé par ce script et reste en place.
uninstall() {
    local current wanted
    current="$(gsettings_bus get org.gnome.shell enabled-extensions 2>/dev/null || true)"
    if [ -n "${current}" ]; then
        wanted="$(uuid_list_edit remove "${current}" "${UUID}")"
        if [ "${wanted}" != "${current}" ]; then
            gsettings_bus set org.gnome.shell enabled-extensions "${wanted}"
            DONE+=("enabled-extensions -= ${UUID}")
        fi
    fi
    if [ -L "${EXT_LINK}" ]; then
        rm -f "${EXT_LINK}"
        DONE+=("removed ${EXT_LINK}")
    elif [ -e "${EXT_LINK}" ]; then
        log "left in place, not a symlink: ${EXT_LINK}"
    fi
    uninstall_streamdeck
}

# ---------- Bilan ----------

summary() {
    local line
    if [ "${#DONE[@]}" -eq 0 ]; then
        log "nothing to change"
    else
        for line in "${DONE[@]}"; do
            log "${line}"
        done
    fi
    if [ "${UNINSTALL}" = 0 ]; then
        log "log out and back in: GNOME Shell loads a new extension only at session start under Wayland"
    fi
}
```

**3c.** In the `step_*` functions, replace each stub line:
- in `step_packages`, `not_implemented "paquets système"` with `install_packages`;
- in `step_udev`, `not_implemented "règle udev"` with `write_udev_rule`;
- in `step_venv`, `not_implemented "venv"` with `make_venv`;
- in `step_extension`, `not_implemented "extension"` with the three lines `link_extension`, `compile_schemas` and `compile_locales`;
- in `step_enable`, `not_implemented "activation"` with `enable_extension`;
- in `step_summary`, `not_implemented "résumé"` with `summary`;
- in `step_uninstall`, `not_implemented "désinstallation"` with:
  ```bash
      if [ "${STREAM_DECK}" = 1 ]; then
          uninstall_streamdeck
      else
          uninstall
      fi
      summary
  ```

Afterwards `grep -c not_implemented script/install/install_erplibre_home.sh` prints `0`.

**3d.** Replace the final line `main "$@"` with:
```bash
# Sourcé avec ERPLIBRE_HOME_SOURCE_ONLY=1, le script définit ses fonctions et
# s'arrête là : les tests unitaires les appellent une à une, sans sudo.
#
# Le code 2 est réservé à unsupported. Une commande appelée qui rend 2 (pip,
# un gestionnaire de paquets, msgfmt) et arrête le script sous set -e
# sortirait sinon en 2, et TODO comme le test long y liraient un système
# non supporté : le piège EXIT la ramène à 1.
if [ "${ERPLIBRE_HOME_SOURCE_ONLY:-0}" != "1" ]; then
    trap 'rc=$?; if [ "${rc}" = 2 ] && [ "${UNSUPPORTED_EXIT:-0}" != 1 ]; then exit 1; fi' EXIT
    main "$@"
fi
```

- [ ] **Step 4: Run the script tests (the Makefile tests still fail)**

Run: `bash -n script/install/install_erplibre_home.sh && .venv.erplibre/bin/python -m unittest test.test_install_erplibre_home -v`

Expected: `Ran 72 tests`, `FAILED (failures=5, errors=1)`: only the `TestMakefile` tests fail (`'|| true' unexpectedly found …`, the old first recipe line, and the four subtests of the two make pairs). Task 3's 28 tests pass unchanged, so the `--dry-run` surface did not move.

- [ ] **Step 5: Makefile targets**

In `conf/make.streamdeck.Makefile`, insert this before the line `ERPLIBRE_HOME_EXT_UUID       := erplibre-home@technolibre.ca`:
```make
# ERPLibre Home, two levels. The base: the GNOME extension, its schemas
# and translations, linked and enabled. The Stream Deck level adds the USB
# packages, the udev rule and .venv.streamdeck, and installs the base too.
# The installer holds every step; these targets only call it, so make and
# the installer cannot disagree.
.PHONY: erplibre_home_install
erplibre_home_install:
	./script/install/install_erplibre_home.sh

# Removes both levels, except the system packages.
.PHONY: erplibre_home_uninstall
erplibre_home_uninstall:
	./script/install/install_erplibre_home.sh --uninstall

.PHONY: erplibre_home_streamdeck_install
erplibre_home_streamdeck_install:
	./script/install/install_erplibre_home.sh --stream-deck

# Removes the udev rule and .venv.streamdeck only; the extension stays
# installed and enabled.
.PHONY: erplibre_home_streamdeck_uninstall
erplibre_home_streamdeck_uninstall:
	./script/install/install_erplibre_home.sh --uninstall --stream-deck

```
Replace the `erplibre_home_install_extension` recipe, which Task 1 left as it is at HEAD `dc841639` (lines 114-125 there):
```make
erplibre_home_install_extension:
	@"$(ERPLIBRE_HOME_EXT_SRC)/tools/migrate_legacy.py" || echo "legacy migration did not run" >&2
	@if [ -L "$(ERPLIBRE_HOME_EXT_DST)" ] || [ -d "$(ERPLIBRE_HOME_EXT_DST)" ]; then \
		rm -rf "$(ERPLIBRE_HOME_EXT_DST)"; \
	fi
	@mkdir -p "$(ERPLIBRE_HOME_EXT_BASE_DIR)"
	@ln -sfn "$(CURDIR)/$(ERPLIBRE_HOME_EXT_SRC)" "$(ERPLIBRE_HOME_EXT_DST)"
	@glib-compile-schemas "$(ERPLIBRE_HOME_EXT_SRC)/schemas/" 2>/dev/null || true
	@python3 "$(ERPLIBRE_HOME_EXT_SRC)/po/compile_locales.py" 2>/dev/null \
		|| echo "(locale compile skipped — install python3-polib for translations)"
	@echo "Symlinked $(ERPLIBRE_HOME_EXT_DST) -> $(CURDIR)/$(ERPLIBRE_HOME_EXT_SRC)"
	@echo "Then: make erplibre_home_enable_extension (Wayland: then log out / log in to load it; X11: Alt+F2, r)"
```
with:
```make
erplibre_home_install_extension:
	@./script/install/install_erplibre_home.sh --extension-only
	@echo "Symlinked $(ERPLIBRE_HOME_EXT_DST) -> $(CURDIR)/$(ERPLIBRE_HOME_EXT_SRC)"
	@echo "Then: make erplibre_home_enable_extension (Wayland: then log out / log in to load it; X11: Alt+F2, r)"
```
The closing hint keeps HEAD's order: enable first, then log out, since the running Wayland Shell does not know a fresh link until the setting is written.
The migration line leaves the recipe: `--extension-only` runs `link_extension`, which calls `tools/migrate_legacy.py` before the link. The migration then runs once per install, whether it starts from make, TODO, a QEMU tool or the long test. The translations now come from the installer's `msgfmt --check`; `erplibre_home_compile_locale` keeps `po/compile_locales.py` under the system `python3`, for developers.

Delete the convenience alias that carries the name of the new target, with its comment:
```make
# Convenience aliases for the common short names users actually type.
.PHONY: erplibre_home_uninstall
erplibre_home_uninstall: erplibre_home_uninstall_extension
```
Left in place, it would make `erplibre_home_uninstall_extension` a prerequisite of the new `erplibre_home_uninstall`. The installer's `--uninstall` removes the link as the alias did, and `erplibre_home_uninstall_extension` stays for the link alone.

Leave `.PHONY: erplibre_home_install_extension` and the `ERPLIBRE_HOME_EXT_*` variables unchanged. `erplibre_home_uninstall_extension`, `erplibre_home_reload_clean` and `dev_nested.sh` still use them. The old recipe deleted whatever sat at the link path, a copied directory included (`rm -rf`); the installer stops on it instead.

No recipe calls the migration any more, so its exemption leaves Task 1's test; `erplibre_home_enable_extension` still calls `tools/enable_next_login.py` and `erplibre_home_compile_locale` the locale compiler, so those two stay. In `test/test_streamdeck_entry_points.py`:
- replace the `HORS_VENV` constant and its five comment lines
  ```python
  # Trois appels restent hors du venv. La migration de l'ancienne identité de
  # l'extension et son aide d'activation passent par leur shebang : elles
  # n'importent que la bibliothèque standard et tournent avant que le venv
  # existe. Le compilateur des locales n'est pas un point d'entrée du deck :
  # il garde le python3 du système.
  HORS_VENV = re.compile(
      r"/tools/(migrate_legacy|enable_next_login)\.py\b"
      r"|/po/compile_locales\.py\b"
  )
  ```
  with
  ```python
  # Deux appels restent hors du venv. L'aide d'activation de l'extension passe
  # par son shebang : elle n'importe que la bibliothèque standard et tourne
  # avant que le venv existe. Le compilateur des locales n'est pas un point
  # d'entrée du deck : il garde le python3 du système.
  HORS_VENV = re.compile(
      r"/tools/enable_next_login\.py\b|/po/compile_locales\.py\b"
  )
  ```
- in the module docstring, the migration goes from the exemption. Replace
  ```
  - toute recette du fragment make qui appelle python passe par
    $(STREAMDECK_PY), hors la migration de l'extension, son aide
    d'activation et le compilateur des locales, qui ne sont pas du code du
    deck et gardent le python du système ; toute cible qui s'en sert l'a en
    prérequis : sans venv, elle s'arrête sur la commande qui le bâtit,
    make erplibre_home_streamdeck_install ;
  ```
  with
  ```
  - toute recette du fragment make qui appelle python passe par
    $(STREAMDECK_PY), hors l'aide d'activation de l'extension et le
    compilateur des locales, qui ne sont pas du code du deck et gardent le
    python du système ; toute cible qui s'en sert l'a en prérequis : sans
    venv, elle s'arrête sur la commande qui le bâtit,
    make erplibre_home_streamdeck_install ;
  ```

- [ ] **Step 6: Run the tests to verify they pass**

Run each command from the checkout root:
- `bash -n script/install/install_erplibre_home.sh`
- `.venv.erplibre/bin/python -m unittest test.test_install_erplibre_home -v`. Expected: `Ran 72 tests` … `OK`, Task 3's 28 tests and this task's 44. The `TestExtensionSeule` tests that run the install are skipped only when `glib-compile-schemas` or `msgfmt` is missing.
- `./script/test/run_unit_test.sh test/test_install_erplibre_home.py test/test_streamdeck_entry_points.py test/test_erplibre_home_enable_target.py`. Expected: `test_install_erplibre_home.py 72 tests OK`, `test_streamdeck_entry_points.py 20 tests OK`, `test_erplibre_home_enable_target.py 10 tests OK`, `102 tests, tout vert`, under the isolated runner, which puts stub `sudo` and `ssh` first in `PATH`.
- `.venv.erplibre/bin/ruff check --select I --fix test/test_install_erplibre_home.py && .venv.erplibre/bin/ruff format test/test_install_erplibre_home.py && .venv.erplibre/bin/ruff check --select E,F,W,B test/test_install_erplibre_home.py test/test_streamdeck_entry_points.py`. Expected: `All checks passed!`, and a second `ruff format` reports `1 file left unchanged`.
- `python3 script/analyse/check_comment_hygiene.py script/install/install_erplibre_home.sh test/test_install_erplibre_home.py test/test_streamdeck_entry_points.py`. Expected: no 🔴 finding.
- `make -n erplibre_home_install erplibre_home_uninstall erplibre_home_streamdeck_install erplibre_home_streamdeck_uninstall erplibre_home_install_extension | head -5`. Expected, in this order: `./script/install/install_erplibre_home.sh`, `… --uninstall`, `… --stream-deck`, `… --uninstall --stream-deck` and `… --extension-only`.
- `./script/install/install_erplibre_home.sh --dry-run; echo "rc=$?"`. Expected on a GNOME 45–51 workstation: the `family=`, `gnome=`, `packages: sudo …`, `run: …/tools/migrate_legacy.py`, `run: msgfmt --check …`, `write: …` and `gsettings: …` lines, no `venv:` line, and `rc=0`. On a system without GNOME: one `UNSUPPORTED:` line and `rc=2`.
- `make test_gnome_extension`. Expected: it passes, since the schemas did not change.

- [ ] **Step 7: Commit the installer and the Makefile**

```bash
cd "$(git rev-parse --show-toplevel)"
git add script/install/install_erplibre_home.sh conf/make.streamdeck.Makefile test/test_install_erplibre_home.py test/test_streamdeck_entry_points.py
cat > $SCRATCH/msg_task4a.txt <<'EOF'
[IMP] install_erplibre_home: packages, udev, venv, enable, uninstall

The installer only checked the system. The base now installs its
packages, runs the legacy migration, links the extension, compiles it
with msgfmt --check and enables it through make's own enable helper over
an open session's bus; --stream-deck adds the uaccess udev rule and
.venv.streamdeck. A rerun changes nothing; a failed write exits 1, only
UNSUPPORTED exits 2. --uninstall --stream-deck keeps the extension.
Checked: test_install_erplibre_home, the entry points, the enable target.

--- FR ---

[IMP] install_erplibre_home : paquets, udev, venv, activation, retrait

L'installateur ne faisait que vérifier le système. La base installe ses
paquets, lance la migration de l'ancienne identité, lie l'extension, la
compile par msgfmt --check et l'active par l'aide d'activation de make,
sur le bus d'une session ouverte ; --stream-deck ajoute la règle udev
uaccess et .venv.streamdeck. Une reprise ne change rien ; une écriture
ratée sort en 1, seul UNSUPPORTED en 2. --uninstall --stream-deck garde
l'extension. Vérifié : test_install_erplibre_home, points d'entrée, cible.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task4a.txt \
  && git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task4a.txt
```

- [ ] **Step 8: Write the INSTALL guide in INSTALL.base.md**

In `script/stream_deck/INSTALL.base.md`, keep lines 1-5 (the mmg header) and replace lines 6-53, from the first `<!-- [en] -->` through the closing fence of the `sudo apt install -y wmctrl` block, with the block below. Keep line 54 (blank) and everything from `<!-- [en] -->` / `## mpv film launcher — yt-dlp backend` onward. Every block ends with a blank line before the next marker, because mmg drops the blank lines that sit between markers.
````markdown
<!-- [en] -->
# Guide to install

ERPLibre Home installs in two levels, on Debian, Ubuntu, Fedora, AlmaLinux,
Rocky Linux, openSUSE and Arch Linux, with GNOME Shell 45 to 51, without
Odoo. The base is the GNOME extension, its schemas and its translations,
enabled: it needs no device access and no venv. The Stream Deck level adds
what the deck programs need, and installs the base too when it is missing.
Both run as your user and call `sudo` only for the system packages and the
udev rule.

<!-- [fr] -->
# Guide d'installation

ERPLibre Home s'installe en deux niveaux, sur Debian, Ubuntu, Fedora,
AlmaLinux, Rocky Linux, openSUSE et Arch Linux, avec GNOME Shell 45 à 51,
sans Odoo. La base est l'extension GNOME, ses schémas et ses traductions,
activée : elle ne demande ni accès au périphérique ni venv. Le niveau Stream
Deck ajoute ce dont les programmes du deck ont besoin, et installe aussi la
base quand elle manque. Les deux tournent sous ton compte et n'appellent
`sudo` que pour les paquets système et la règle udev.

<!-- [end] -->
<!-- [common] -->
```
make erplibre_home_install
make erplibre_home_streamdeck_install
```

<!-- [end] -->
<!-- [en] -->
The first command installs the base: the system packages of the base, then
it links the GNOME extension into `~/.local/share/gnome-shell/extensions/`,
compiles its schemas and its translations (with `msgfmt`), and enables it.
The second one, for a workstation with a Stream Deck, adds the Stream Deck
packages, writes the udev rule and creates `.venv.streamdeck` from
`script/stream_deck/requirements.txt`. Then log out and back in: under
Wayland, GNOME Shell loads a new extension only at session start. A second
run changes nothing. Without the Stream Deck level, the extension's
`device` and `controller` indicators say that ERPLibre Home Stream Deck is
not installed and name `make erplibre_home_streamdeck_install`.

Both targets run `script/install/install_erplibre_home.sh`, which takes
these options:

<!-- [fr] -->
La première commande installe la base : les paquets système de la base,
puis elle lie l'extension GNOME dans `~/.local/share/gnome-shell/extensions/`,
compile ses schémas et ses traductions (avec `msgfmt`), et l'active. La
seconde, pour un poste qui a un Stream Deck, ajoute les paquets du Stream
Deck, écrit la règle udev et crée `.venv.streamdeck` depuis
`script/stream_deck/requirements.txt`. Ferme ensuite ta session et
rouvre-la : sous Wayland, GNOME Shell ne charge une nouvelle extension qu'à
l'ouverture de session. Une seconde exécution ne change rien. Sans le niveau
Stream Deck, les indicateurs `device` et `controller` de l'extension disent
qu'ERPLibre Home Stream Deck n'est pas installé et nomment
`make erplibre_home_streamdeck_install`.

Les deux cibles lancent `script/install/install_erplibre_home.sh`, qui
accepte ces options :

<!-- [end] -->
<!-- [en] -->
| Option | Effect |
|---|---|
| `--stream-deck` | add the Stream Deck level: USB packages, udev rule, `.venv.streamdeck`; the base installs too when missing |
| `--no-enable` | install without enabling the extension; a workstation where the former extension was enabled keeps that state under the new name |
| `--extension-only` | migrate from the former extension, link the extension and compile its schemas and translations only; no `sudo`, no system check; not with `--stream-deck` nor `--uninstall` |
| `--with-extras` | also install `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` and the Python `lz4` module, at either level; a missing one is skipped with a warning |
| `--uninstall` | remove everything: disable the extension, remove its link, the udev rule and `.venv.streamdeck`; with `--stream-deck`, only the udev rule and `.venv.streamdeck`, and the extension stays enabled; system packages always stay |
| `--dry-run` | print what would be done, change nothing |

Exit code `0` means done, `2` an unsupported system (one line on stderr
starting with `UNSUPPORTED:`), `1` any other failure.
`make erplibre_home_uninstall` runs `--uninstall`, and
`make erplibre_home_streamdeck_uninstall` runs `--uninstall --stream-deck`.

<!-- [fr] -->
| Option | Effet |
|---|---|
| `--stream-deck` | ajoute le niveau Stream Deck : paquets USB, règle udev, `.venv.streamdeck` ; la base s'installe aussi quand elle manque |
| `--no-enable` | installe sans activer l'extension ; un poste où l'ancienne extension était active garde cet état sous le nouveau nom |
| `--extension-only` | migre depuis l'ancienne extension, lie l'extension et compile ses schémas et ses traductions, rien d'autre ; ni `sudo` ni vérification du système ; ni avec `--stream-deck` ni avec `--uninstall` |
| `--with-extras` | installe aussi `mpv`, `yt-dlp`, `nmap`, `keepassxc`, `xdotool` et le module Python `lz4`, à l'un ou l'autre niveau ; un paquet absent est sauté avec un avertissement |
| `--uninstall` | retire tout : désactive l'extension, retire son lien, la règle udev et `.venv.streamdeck` ; avec `--stream-deck`, seulement la règle udev et `.venv.streamdeck`, et l'extension reste active ; les paquets système restent toujours |
| `--dry-run` | affiche ce qui serait fait, ne change rien |

Le code de sortie `0` veut dire fait, `2` un système non supporté (une
ligne sur stderr qui commence par `UNSUPPORTED:`), `1` tout autre échec.
`make erplibre_home_uninstall` lance `--uninstall`, et
`make erplibre_home_streamdeck_uninstall` lance `--uninstall --stream-deck`.

<!-- [end] -->
<!-- [en] -->
### System packages, for reference

The installer picks the column of your distribution family: the base rows
always, the Stream Deck rows with `--stream-deck`. On AlmaLinux and Rocky
Linux, `--stream-deck` first enables EPEL (`dnf install -y epel-release`),
where `wmctrl` comes from; the base does not touch EPEL.

<!-- [fr] -->
### Paquets système, pour référence

L'installateur prend la colonne de ta famille de distribution : les lignes
de la base toujours, celles du Stream Deck avec `--stream-deck`. Sur
AlmaLinux et Rocky Linux, `--stream-deck` active d'abord EPEL
(`dnf install -y epel-release`), d'où vient `wmctrl` ; la base ne touche
pas à EPEL.

<!-- [end] -->
<!-- [common] -->
| Level | Role | apt | dnf | zypper | pacman |
|---|---|---|---|---|---|
| base | schemas | `libglib2.0-bin` | `glib2` | `glib2-tools` | `glib2` |
| base | gettext (`msgfmt`) | `gettext` | `gettext` | `gettext-tools` | `gettext` |
| base | system python | `python3` | `python3` | `python3` | `python` |
| Stream Deck | hidapi + libusb | `libhidapi-libusb0 libusb-1.0-0` | `hidapi libusb1` | `libhidapi-libusb0 libusb-1_0-0` | `hidapi libusb` |
| Stream Deck | venv | `python3-venv` | `python3` | `python3` | `python` |
| Stream Deck | window control | `wmctrl` | `wmctrl` | `wmctrl` | `wmctrl` |

<!-- [end] -->
<!-- [en] -->
### Device access: the udev rule

With `--stream-deck`, the installer writes
`/etc/udev/rules.d/70-streamdeck.rules`:

<!-- [fr] -->
### Accès au périphérique : la règle udev

Avec `--stream-deck`, l'installateur écrit
`/etc/udev/rules.d/70-streamdeck.rules` :

<!-- [end] -->
<!-- [common] -->
```
SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"
```

<!-- [end] -->
<!-- [en] -->
`0fd9` is Elgato's USB vendor id, so the rule covers every Stream Deck model.
`uaccess` gives the user logged in at the seat access to the device, on every
distribution family; no group membership is needed, unlike the `plugdev`
group, which exists only on Debian and Ubuntu. The `70-` prefix orders the
rule before `73-seat-late.rules`, where `uaccess` is applied. To diagnose a
device that is not seen, or to add new hardware, watch the events while you
plug it in:

<!-- [fr] -->
`0fd9` est l'identifiant de fabricant USB d'Elgato : la règle couvre tous les
modèles de Stream Deck. `uaccess` donne l'accès au périphérique à
l'utilisateur assis devant le poste, sur toutes les familles de distribution ;
aucun groupe n'est requis, contrairement au groupe `plugdev`, qui n'existe que
sur Debian et Ubuntu. Le préfixe `70-` place la règle avant
`73-seat-late.rules`, qui applique `uaccess`. Pour diagnostiquer un
périphérique qui n'est pas vu, ou ajouter du nouveau matériel, observer les
événements en le branchant :

<!-- [end] -->
<!-- [common] -->
```
sudo udevadm monitor
```

<!-- [end] -->
````

- [ ] **Step 9: Regenerate and check the docs**

Run: `cd script/stream_deck && source ../../.venv.erplibre/bin/activate && mmg --yes INSTALL.base.md && cd ../.. && grep -c "<!--" script/stream_deck/INSTALL.md script/stream_deck/INSTALL.fr.md; head -12 script/stream_deck/INSTALL.fr.md; grep -n "make erplibre_home_install\|make erplibre_home_streamdeck_install\|70-streamdeck.rules\|plugdev" script/stream_deck/INSTALL.md`

Expected:
- mmg prints `en: INSTALL.md`, `fr: INSTALL.fr.md` and `1 base file has been converted`.
- Both `grep -c` counts are `0`. Regenerating also removes the stray `<!-- [en] -->` markers that the committed `INSTALL.fr.md` carried in its later sections.
- The first heading of `INSTALL.fr.md` is `# Guide d'installation`, followed by the paragraph on the two levels.
- `INSTALL.md` names `make erplibre_home_install` and `make erplibre_home_streamdeck_install` in the fence (lines 13-14), `make erplibre_home_streamdeck_install` again in the paragraph on the missing level, and `70-streamdeck.rules`. `plugdev` appears only in the uaccess explanation.

- [ ] **Step 10: Commit the docs**

```bash
cd "$(git rev-parse --show-toplevel)"
git add script/stream_deck/INSTALL.base.md script/stream_deck/INSTALL.md script/stream_deck/INSTALL.fr.md
cat > $SCRATCH/msg_task4b.txt <<'EOF'
[UPD] stream_deck: INSTALL guide uses make erplibre_home_install

The guide described an Ubuntu-only manual setup with a plugdev group that
exists on Debian and Ubuntu alone. It now gives make erplibre_home_install
for the base, then make erplibre_home_streamdeck_install for a deck, lists
the installer's options and exit codes, keeps the package table split by
level for reference, and explains the uaccess udev rule. INSTALL.md and
INSTALL.fr.md are regenerated with mmg.

--- FR ---

[UPD] stream_deck : guide INSTALL via make erplibre_home_install

Le guide décrivait une installation manuelle pour Ubuntu seul, avec un
groupe plugdev qui n'existe que sur Debian et Ubuntu. Il donne désormais
make erplibre_home_install pour la base, puis make
erplibre_home_streamdeck_install pour un deck, liste les options et les
codes de sortie de l'installateur, garde la table des paquets par niveau
pour référence et explique la règle udev uaccess. INSTALL.md et
INSTALL.fr.md sont régénérés par mmg.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task4b.txt \
  && git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task4b.txt
```

---

### Task 5: TODO local install entries, base and Stream Deck

**Files:**
- Create: `test/test_todo_erplibre_home_install.py`
- Modify: `script/todo/todo.py:352-354` (menu text in `prompt_execute`), `script/todo/todo.py:425-429` (dispatch chain), `script/todo/todo.py:1911-1918` (new method after `_scan_streamdeck_games`'s `return games`)
- Modify: `script/todo/todo_i18n.py:120-123` (new keys after `"Launching game:"`)
- Modify: `test/test_todo_menu.py:109-110` (`TestExecuteMenuNumbering.EXPECTED`)
- Test: `test/test_todo_erplibre_home_install.py`, `test/test_todo_menu.py`

The line numbers refer to HEAD `dc841639`. Task 1 adds a venv check at the top of `prompt_execute_streamdeck_games`, a method before `_scan_streamdeck_games`, and an i18n key before `"Launching game:"`, which shift the line numbers. For that reason every edit below is anchored on an exact text snippet and not on a line number.

The games entry's missing-venv check is Task 1's (spec 3.1; it is a prerequisite fix of spec 9, step 2): this task adds only the two install entries.

**Interfaces:**
- Consumes:
  - `script/install/install_erplibre_home.sh` (Task 3). It must exist and be executable. Exit 0 means installed. Exit 2 means unsupported, with one stderr line starting `UNSUPPORTED: <reason>`. Exit 1 means any other failure.
  - `Execute.exec_command_live(command, source_erplibre=False, return_status_and_output=True)` in `script/execute/execute.py:119`. It returns `(exit_code: int, lines: list[str])`, with stdout and stderr merged, streamed live and kept without their trailing newline.
- Produces:
  - Menu entries `[18] {t("Install ERPLibre Home (local)")}` and `[19] {t("Install ERPLibre Home Stream Deck (local)")}` in `TODO › Execute › Stream Deck`. They are appended after `[17] Games`, so no existing entry is renumbered.
  - `TODO._erplibre_home_install_local(self) -> False` runs `./script/install/install_erplibre_home.sh`; `TODO._erplibre_home_streamdeck_install_local(self) -> False` runs `./script/install/install_erplibre_home.sh --stream-deck`. Both go through `TODO._erplibre_home_run_installer(self, commande) -> False`, which runs the command live and sums its exit up in one line. They always return False, so the Execute menu stays open.
  - Class constants `TODO._ERPLIBRE_HOME_INSTALLER = "./script/install/install_erplibre_home.sh"` and `TODO._ERPLIBRE_HOME_UNSUPPORTED = 2`.
  - Six i18n keys: `"Install ERPLibre Home (local)"`, `"Install ERPLibre Home Stream Deck (local)"`, `"ERPLibre Home not supported on this system:"`, `"no reason reported by the installer"`, `"ERPLibre Home installation failed, see the output above."`, `"ERPLibre Home installed. Log out and back in to load the extension."`.

- [ ] **Step 1: Write the failing tests**

Edit `test/test_todo_menu.py` to declare where the new entries lead. `_entry_key` splits on `" - "`, and these labels have no `" - "`, so each key is the whole label.

Before:
```python
        "Docker / Podman": "prompt_execute_container",
        "Games": "prompt_execute_streamdeck_games",
    }
```
After:
```python
        "Docker / Podman": "prompt_execute_container",
        "Games": "prompt_execute_streamdeck_games",
        "Install ERPLibre Home (local)": "_erplibre_home_install_local",
        "Install ERPLibre Home Stream Deck (local)": (
            "_erplibre_home_streamdeck_install_local"
        ),
    }
```

Create `test/test_todo_erplibre_home_install.py`:
```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les deux entrées d'installation locale d'ERPLibre Home du menu Exécution.

« Installer ERPLibre Home (local) » pose la base, « Installer ERPLibre Home
Stream Deck (local) » le niveau Stream Deck, base comprise. Les deux lancent
le même installateur, la seconde avec --stream-deck.

L'installateur rend trois issues, et le menu les annonce chacune par une
seule ligne : 0 installé, 2 système hors périmètre — avec la raison que
l'installateur écrit sur sa ligne « UNSUPPORTED: » —, tout autre code un
échec. Le lanceur est remplacé par un double qui retient la commande et ses
options et rend le code et les lignes qu'on lui fixe : aucun processus ne
part.
"""

import contextlib
import io
import os
import sys
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

INSTALLATEUR = "./script/install/install_erplibre_home.sh"
# Chaque entrée : la méthode que le menu appelle, la commande qu'elle lance.
ENTREES = {
    "_erplibre_home_install_local": INSTALLATEUR,
    "_erplibre_home_streamdeck_install_local": INSTALLATEUR + " --stream-deck",
}


class ExecuteFactice:
    """Rend (code, lignes), la forme de return_status_and_output=True."""

    def __init__(self, code, lignes=()):
        self.appels = []
        self.code = code
        self.lignes = list(lignes)

    def exec_command_live(self, cmd, **kwargs):
        self.appels.append((cmd, kwargs))
        return self.code, list(self.lignes)


class TestInstallationLocale(unittest.TestCase):
    def setUp(self):
        todo_i18n._current_lang = "en"

    def tearDown(self):
        todo_i18n._current_lang = None

    def lancer(self, methode, code, lignes=()):
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice(code, lignes)
        sortie = io.StringIO()
        with contextlib.redirect_stdout(sortie):
            rendu = getattr(todo, methode)()
        return todo.execute.appels, sortie.getvalue(), rendu

    def test_chaque_entree_lance_sa_commande_hors_du_venv_erplibre(self):
        for methode, commande in ENTREES.items():
            with self.subTest(methode=methode):
                appels, _, _ = self.lancer(methode, 0)
                self.assertEqual(len(appels), 1)
                cmd, kwargs = appels[0]
                self.assertEqual(cmd, commande)
                self.assertIs(kwargs.get("source_erplibre"), False)
                self.assertIs(kwargs.get("return_status_and_output"), True)

    def test_le_succes_dit_de_rouvrir_la_session(self):
        for methode in ENTREES:
            with self.subTest(methode=methode):
                _, sortie, rendu = self.lancer(methode, 0)
                self.assertIn("✅", sortie)
                self.assertIn("Log out and back in", sortie)
                self.assertIs(rendu, False)

    def test_le_code_2_montre_la_raison_seule(self):
        lignes = [
            "family=arch",
            "UNSUPPORTED: GNOME 52 not in shell-version",
        ]
        for methode in ENTREES:
            with self.subTest(methode=methode):
                _, sortie, rendu = self.lancer(methode, 2, lignes)
                self.assertIn(
                    "ERPLibre Home not supported on this system:"
                    " GNOME 52 not in shell-version",
                    sortie,
                )
                self.assertNotIn("UNSUPPORTED:", sortie)
                self.assertNotIn("❌", sortie)
                self.assertIs(rendu, False)

    def test_le_code_2_sans_raison_le_dit(self):
        _, sortie, _ = self.lancer(
            "_erplibre_home_install_local", 2, ["family=arch"]
        )
        self.assertIn(
            "ERPLibre Home not supported on this system:"
            " no reason reported by the installer",
            sortie,
        )

    def test_un_autre_code_renvoie_a_la_sortie(self):
        for methode in ENTREES:
            with self.subTest(methode=methode):
                _, sortie, rendu = self.lancer(
                    methode, 1, ["E: Unable to locate package"]
                )
                self.assertIn("❌", sortie)
                self.assertIn("see the output above", sortie)
                self.assertNotIn("not supported", sortie)
                self.assertIs(rendu, False)

    def test_l_installateur_appele_existe_et_s_execute(self):
        chemin = RACINE / INSTALLATEUR
        self.assertTrue(chemin.is_file(), f"{INSTALLATEUR} absent")
        self.assertTrue(
            os.access(chemin, os.X_OK), f"{INSTALLATEUR} non exécutable"
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_todo_erplibre_home_install test.test_todo_menu 2>&1 | grep -E "^(FAIL|ERROR|AttributeError|Ran|FAILED)"`

Expected: FAIL, `Ran 60 tests`, `FAILED (failures=1, errors=9)`. The output should show:
- 9 errors, one per subtest: 5 with `AttributeError: 'TODO' object has no attribute '_erplibre_home_install_local'` and 4 with `… '_erplibre_home_streamdeck_install_local'`.
- `FAIL: test_expected_table_has_no_stale_entry (test.test_todo_menu.TestExecuteMenuNumbering...)`, because the two labels are in EXPECTED but not shown in the menu.
- `test_l_installateur_appele_existe_et_s_execute` already passes when Task 3 is merged. Otherwise it also fails with `./script/install/install_erplibre_home.sh absent`.

- [ ] **Step 3: Implement**

3a. `script/todo/todo.py`, menu text in `prompt_execute`. Append `[18]` and `[19]` so that `[17] Games` keeps its number.

Before:
```python
── {t("Stream Deck")} ──
[17] {t("Games - Stream Deck games")}
[0] {t("Back")}
"""
```
After:
```python
── {t("Stream Deck")} ──
[17] {t("Games - Stream Deck games")}
[18] {t("Install ERPLibre Home (local)")}
[19] {t("Install ERPLibre Home Stream Deck (local)")}
[0] {t("Back")}
"""
```

3b. `script/todo/todo.py`, dispatch chain in `prompt_execute`. This uses the form `RE_DISPATCH` expects: `elif status == "N":` followed directly by `status = self.x()`.

Before:
```python
            elif status == "17":
                status = self.prompt_execute_streamdeck_games()
                if status is not False:
                    return
            else:
                print(t("Command not found !"))
```
After:
```python
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
                print(t("Command not found !"))
```

3c. `script/todo/todo.py`, after the end of `_scan_streamdeck_games` and before the `# Déploiement : catalogue (pur) -> collecte (CLI ou TUI) -> exécution` banner. The comments are in French, like the surrounding file. The methods call neither `fill_help_info` nor `_menu_header`, so `TestMenuLabels` needs no `_MENU_LABELS` entry.

Before:
```python
            games.append(
                {
                    "name": name,
                    "description": f"{name} — {description}",
                    "path": filepath,
                }
            )
        return games
```
After:
```python
            games.append(
                {
                    "name": name,
                    "description": f"{name} — {description}",
                    "path": filepath,
                }
            )
        return games

    # install_erplibre_home.sh sort en 2 pour un système hors périmètre
    # (distribution, version de GNOME) et en écrit la raison sur une ligne
    # « UNSUPPORTED: <raison> » ; tout autre code non nul est un échec.
    _ERPLIBRE_HOME_INSTALLER = "./script/install/install_erplibre_home.sh"
    _ERPLIBRE_HOME_UNSUPPORTED = 2

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
        .venv.streamdeck. exec_command_live fusionne stdout et stderr et en
        retient les lignes ; la ligne « UNSUPPORTED: » y est cherchée, pour
        qu'un code 2 se résume par sa raison et non par un code d'erreur nu.
        Rend False.
        """
        status, lignes = self.execute.exec_command_live(
            commande,
            source_erplibre=False,
            return_status_and_output=True,
        )
        if status == self._ERPLIBRE_HOME_UNSUPPORTED:
            prefixe = "UNSUPPORTED:"
            raison = next(
                (
                    ligne.strip()[len(prefixe) :].strip()
                    for ligne in lignes
                    if ligne.strip().startswith(prefixe)
                ),
                "",
            )
            if not raison:
                raison = t("no reason reported by the installer")
            print(
                f"⛔ {t('ERPLibre Home not supported on this system:')} {raison}"
            )
        elif status:
            print(
                "❌ "
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
```

3d. `script/todo/todo_i18n.py`. Add the keys right after `"Launching game:"`, inside the `# Stream Deck Games section` block. The menu labels carry their icon in both languages, as `"Games - Stream Deck games"` does.

Before:
```python
    "Launching game:": {
        "fr": "Lancement du jeu :",
        "en": "Launching game:",
    },
    # Stream Deck game descriptions (42 games)
```
After:
```python
    "Launching game:": {
        "fr": "Lancement du jeu :",
        "en": "Launching game:",
    },
    "Install ERPLibre Home (local)": {
        "fr": "📦 Installer ERPLibre Home (local)",
        "en": "📦 Install ERPLibre Home (local)",
    },
    "Install ERPLibre Home Stream Deck (local)": {
        "fr": "📦 Installer ERPLibre Home Stream Deck (local)",
        "en": "📦 Install ERPLibre Home Stream Deck (local)",
    },
    "ERPLibre Home not supported on this system:": {
        "fr": "ERPLibre Home non pris en charge sur ce système :",
        "en": "ERPLibre Home not supported on this system:",
    },
    "no reason reported by the installer": {
        "fr": "aucune raison donnée par l'installateur",
        "en": "no reason reported by the installer",
    },
    "ERPLibre Home installation failed, see the output above.": {
        "fr": (
            "L'installation d'ERPLibre Home a échoué, voir la sortie"
            " ci-dessus."
        ),
        "en": "ERPLibre Home installation failed, see the output above.",
    },
    "ERPLibre Home installed. Log out and back in to load the extension.": {
        "fr": (
            "ERPLibre Home installé. Fermer la session puis la rouvrir"
            " pour charger l'extension."
        ),
        "en": (
            "ERPLibre Home installed. Log out and back in to load"
            " the extension."
        ),
    },
    # Stream Deck game descriptions (42 games)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./script/test/run_unit_test.sh test/test_todo_erplibre_home_install.py test/test_todo_menu.py test/test_todo_i18n.py test/test_i18n_duplicates.py test/test_todo.py`

Expected: `164 tests, tout vert`. The counts are test_todo_erplibre_home_install 6, test_todo_menu 54, test_todo_i18n 24, test_i18n_duplicates 3, test_todo 77.

Equivalent direct run: `.venv.erplibre/bin/python -m unittest test.test_todo_erplibre_home_install test.test_todo_menu test.test_todo_i18n test.test_i18n_duplicates test.test_todo`
Expected: `OK`.

Formatting. There is no `pyproject.toml` at the root: tooling code is formatted by ruff through `.ruff.toml` (line-length 79), which `script/maintenance/format_python.sh` applies. Do not reformat the whole of `todo.py` or `todo_i18n.py`: both already have many unrelated ruff diffs. Check only the new file, and check that the added hunks are clean:
```bash
cd "$(git rev-parse --show-toplevel)"
.venv.erplibre/bin/ruff format --check test/test_todo_erplibre_home_install.py
.venv.erplibre/bin/ruff check --select I test/test_todo_erplibre_home_install.py
.venv.erplibre/bin/ruff format --diff script/todo/todo.py script/todo/todo_i18n.py 2>&1 | grep -c -e _erplibre_home_install_local -e _erplibre_home_streamdeck_install_local -e _erplibre_home_run_installer -e _ERPLIBRE_HOME -e "ERPLibre Home not supported" -e "Install ERPLibre Home" -e "ERPLibre Home install" -e "no reason reported"
python3 script/analyse/check_comment_hygiene.py test/test_todo_erplibre_home_install.py
```
Expected:
- The first command prints `1 file already formatted`.
- The second prints `All checks passed!`.
- The third prints `0`.
- The fourth reports no 🔴 finding.

- [ ] **Step 5: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add script/todo/todo.py script/todo/todo_i18n.py test/test_todo_menu.py test/test_todo_erplibre_home_install.py
MSG=$SCRATCH/msg_task5.txt
cat > "$MSG" <<'EOF'
[ADD] todo: ERPLibre Home local install entries in Execute

Execute > Stream Deck gets [18], the ERPLibre Home base, and [19], the
Stream Deck level, which runs the installer with --stream-deck. Both run
live, outside the ERPLibre venv. Exit 2 ends on the installer's
UNSUPPORTED reason alone, so an unsupported distribution or GNOME version
reads as one line, not as a bare error code; any other failure points at
the output above. test_todo_menu declares where both lead; a new test
covers each command, the exit-2 reason and the failure message.

--- FR ---
[ADD] todo : installation locale d'ERPLibre Home, base et Stream Deck

Exécution > Stream Deck gagne [18], la base d'ERPLibre Home, et [19], le
niveau Stream Deck, qui lance l'installateur avec --stream-deck. Les deux
tournent en direct, hors du venv ERPLibre. Un code 2 se conclut sur la
seule raison UNSUPPORTED de l'installateur : une distribution ou un GNOME
hors périmètre se lit en une ligne, et non en code d'erreur nu ; tout
autre échec renvoie à la sortie. test_todo_menu déclare où mènent les
deux ; un nouveau test couvre chaque commande, le code 2 et l'échec.

Assisted-by: Claude Opus 5.5
EOF
./script/git/hooks/commit-msg "$MSG" && git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F "$MSG"
```
Expected: the hook prints nothing and exits 0, and the commit is created with the 4 named files.

Verification note: this task was run end to end in a throwaway copy of HEAD with Tasks 1-4 applied. Step 2 failed as described. After Step 3, Step 4 gave 164 tests green, the ruff checks were clean on the added code, and the commit message passed `script/git/hooks/commit-msg` (exit 0).

---

### Task 6: QEMU erplibre_home and erplibre_home_streamdeck tools, ERPLibre Home profile

**Files:**
- Create: `test/test_qemu_erplibre_home.py`
- Modify: `script/todo/qemu_install.py:62-65` (profile list, insert after the "ERPLibre mobile (home)" tuple)
- Modify: `script/todo/qemu_install.py:921-925` (`_QEMU_VM_TOOLS`, insert both entries right after the `gnome_ext` entry)
- Modify: `script/todo/qemu_install.py:2253` (new method `_qemu_erplibre_home_remote_cmd` goes just before `_qemu_after_remote_cmd`)
- Modify: `script/todo/qemu_install.py:2265` (after-phase `picked` tuple) and `:2279-2280` (dispatch, after the forgejo block)
- Modify: `script/todo/todo_i18n.py:7259-7262` (profile label, after "ERPLibre mobile (home)") and `:7431-7434` (labels, hints and help lines, after "nixos-anywhere missing, see the log above")
- Modify: `test/test_qemu_desktop_tools.py:83-99` (`TestToolDisk.test_disk_follows_the_filtering`: arm64 also loses the two amd64-only ERPLibre Home tools)
- Test: `test/test_qemu_erplibre_home.py`

The line numbers refer to HEAD `dc841639`; Tasks 1 and 5 shift those of `todo_i18n.py`, so each edit below is anchored on its text.

**Interfaces:**
- Consumes: `script/install/install_erplibre_home.sh` (Tasks 3-4). It is called by its relative path from the checkout root, without option for the base and with `--stream-deck` for the Stream Deck level, and exits 0, 2 or 1. These unit tests replace it with a test double and do not need it to exist. Also consumes the existing `_qemu_install_dir(prod)`, `_qemu_after_remote_cmd`, `_qemu_tools_for`, `_qemu_installs_erplibre`, `_qemu_make_target` and `_qemu_deploy_parts_for`.
- Produces:
  - `_QEMU_VM_TOOLS["erplibre_home"]` and `_QEMU_VM_TOOLS["erplibre_home_streamdeck"]`, which are exactly the spec 5.2 dicts, in that order, right after `gnome_ext`.
  - `TODO._qemu_erplibre_home_remote_cmd(self, prod=False, stream_deck=False) -> str`. The fragment is `echo "== <t("ERPLibre Home")> =="; (cd "<install dir>" && ./script/install/install_erplibre_home.sh)`, or, with `stream_deck`, `echo "== <t("ERPLibre Home Stream Deck")> =="; (cd "<install dir>" && ./script/install/install_erplibre_home.sh --stream-deck)`. It has no trailing `;`.
  - The after-phase order `("aidev", "forgejo", "erplibre_home", "erplibre_home_streamdeck", "mobile", "avd")`. When both ERPLibre Home tools are ticked, only the `--stream-deck` block is emitted: the Stream Deck level includes the base.
  - The profile `(t("ERPLibre Home (no Odoo)"), "./script/install/install_erplibre_home.sh")`, placed right after "ERPLibre mobile (home)". It installs the base; the `erplibre_home_streamdeck` tool adds the rest.
  - New i18n keys: "ERPLibre Home", "ERPLibre Home Stream Deck", "ERPLibre Home (no Odoo)", "GNOME extension, no Stream Deck", "deck controller, games, GNOME extension", "script/install/install_erplibre_home.sh in the VM's checkout", "extension, schemas and translations, extension enabled", "script/install/install_erplibre_home.sh --stream-deck in the VM's checkout", "ERPLibre Home, plus USB packages, udev rule, .venv.streamdeck", "log out and back in to load the extension". Other tasks must not declare these keys again, because `test_todo_i18n.TestAucuneCleRepetee` forbids duplicate keys.
  - The label keys `"ERPLibre Home"` and `"ERPLibre Home Stream Deck"` do not exist yet: 3e adds them. Task 1's key `"ERPLibre Home Stream Deck is not installed: …"` is a different key. The existing `"Stream Deck"` key (`todo_i18n.py:104`, fr/en "🎛️ Stream Deck") stays the label of the Stream Deck menu section and is not touched.
- Expected behaviour of the profile, which needs **no change** in `qemu_deploy.py`. Tests in this task lock it in:
  - The command contains no `install_odoo`, so `_qemu_erplibre_remote_cmd` adds no `erplibre.service` (`qemu_deploy.py:107`) and `_qemu_make_target` returns `""`. As a result, there is no `--erplibre-make` and the login guide stops at `git pull`.
  - The checkout **is** cloned, because the installer lives in it. So `_qemu_installs_erplibre("develop", cmd)` stays True: `--erplibre-dir` is passed and the `ERPLIBRE_EXTRA_DISK_GB` (+5) margin stays.
  - `QEMU_DESKTOP_EXTRA_DISK_GB` (+6) is still added for a desktop VM (`qemu_deploy.py:1262-1265`).
  - The desktop block runs before `cd ~/git/erplibre && ./script/install/install_erplibre_home.sh`.
  - On a VM without GNOME, the installer exits 2 (`UNSUPPORTED: no GNOME Shell`) and the VM is marked failed. The tools themselves are filtered out of non-GNOME VMs by `desktops`/`needs_desktop`.
  - Ticking `erplibre_home` with this profile runs the base installer twice; the second run is a no-op. Ticking `erplibre_home_streamdeck` with it runs the base, then `--stream-deck`, whose base steps are no-ops.
  - A desktop-only VM (no clone) names both ticked tools as skipped, through the generic after-phase note of `qemu_deploy.py:76-86`.

- [ ] **Step 1: Write the failing test**

Create `test/test_qemu_erplibre_home.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre Home en VM : les deux cases et le profil sans Odoo.

Une seule autorité installe ERPLibre Home :
script/install/install_erplibre_home.sh. La case « erplibre_home » l'appelle
pour la base, la case « erplibre_home_streamdeck » avec --stream-deck, pour
le niveau Stream Deck, base comprise. Les deux passent APRÈS l'installation,
dans le checkout de la VM, quel que soit le profil ; le profil « ERPLibre
Home (no Odoo) » appelle la base SEULE, sans « make install_os ».

Ce que ces tests gardent :

- les deux cases sont au catalogue, juste après « gnome_ext », bornées à
  GNOME, à amd64 et aux quatre familles impératives, et chaque chaîne
  affichée existe dans les deux langues ;
- chaque bloc appelle sa commande DANS le checkout, lié par « && » :
  ERPLibre Home qui ne s'installe pas fait échouer la VM ;
- cochées ensemble, seule la commande du Stream Deck passe : elle inclut la
  base ;
- le profil est offert juste après « ERPLibre mobile (home) » et lance la
  base seule, après le bureau ;
- ce profil ne pose aucun service Odoo et n'annonce aucune cible make, mais
  la VM garde la marge du bureau et celle du checkout cloné.
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import TRANSLATIONS, t  # noqa: E402

BASE = "erplibre_home"
DECK = "erplibre_home_streamdeck"
OUTILS = (BASE, DECK)
INSTALLEUR = "./script/install/install_erplibre_home.sh"
STREAM_DECK = INSTALLEUR + " --stream-deck"
# La commande que chaque case lance, et son option.
COMMANDES = {BASE: INSTALLEUR, DECK: STREAM_DECK}
OPTIONS = {BASE: "", DECK: "--stream-deck"}
PROFIL = "ERPLibre Home (no Odoo)"


def bash_n(script):
    """« bash -n » : le shell accepte-t-il ce script, sans l'exécuter ?"""
    return subprocess.run(
        ["bash", "-n"],
        input="mstep() { :; }; mdiag() { :; };\n" + script,
        capture_output=True,
        text=True,
    )


class LesCases(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_they_follow_the_gnome_extensions(self):
        """Le formulaire suit l'ordre du catalogue : les cases qui touchent
        aux extensions GNOME se lisent ensemble, la base d'abord."""
        keys = [k for k, _l, _h in TODO._qemu_vm_tool_choices()]
        rang = keys.index("gnome_ext")
        self.assertEqual(rang + 1, keys.index(BASE))
        self.assertEqual(rang + 2, keys.index(DECK))

    def test_they_run_after_the_clone(self):
        """L'installateur vit dans le dépôt : il n'existe qu'après le clone."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                self.assertEqual("after", TODO._QEMU_VM_TOOLS[outil]["phase"])

    def test_they_need_a_gnome_desktop(self):
        """L'extension vise GNOME Shell : sans lui, l'installateur rend 2."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                spec = TODO._QEMU_VM_TOOLS[outil]
                self.assertTrue(spec["needs_desktop"])
                self.assertEqual(("gnome",), spec["desktops"])
                self.assertEqual(
                    [outil],
                    self.todo._qemu_tools_for(
                        (outil,), "amd64", "gnome", "ubuntu"
                    ),
                )
                for bureau in ("", "cinnamon"):
                    self.assertEqual(
                        [],
                        self.todo._qemu_tools_for(
                            (outil,), "amd64", bureau, "ubuntu"
                        ),
                    )

    def test_they_are_amd64_only(self):
        for outil in OUTILS:
            with self.subTest(outil=outil):
                self.assertEqual(
                    ("amd64",), TODO._QEMU_VM_TOOLS[outil]["arches"]
                )
                self.assertEqual(
                    [],
                    self.todo._qemu_tools_for(
                        (outil,), "arm64", "gnome", "ubuntu"
                    ),
                )

    def test_every_imperative_family_gets_them(self):
        """L'installateur connaît apt, dnf, zypper et pacman ; NixOS n'a pas
        de chemin de bureau GNOME dans l'installateur QEMU."""
        for outil in OUTILS:
            self.assertEqual(
                ("apt", "dnf", "pacman", "zypper"),
                TODO._QEMU_VM_TOOLS[outil]["families"],
            )
            for distro in (
                "ubuntu",
                "debian",
                "fedora",
                "almalinux",
                "rocky",
                "opensuse",
                "arch",
            ):
                with self.subTest(outil=outil, distro=distro):
                    self.assertEqual(
                        [outil],
                        self.todo._qemu_tools_for(
                            (outil,), "amd64", "gnome", distro
                        ),
                    )
            self.assertEqual(
                [],
                self.todo._qemu_tools_for((outil,), "amd64", "gnome", "nixos"),
            )

    def test_their_disk_cost_is_counted_in_the_plan(self):
        """La base : quelques paquets et les traductions. Le Stream Deck : le
        venv en plus, opencv-python et Pillow."""
        sans = self.todo._qemu_tools_disk_gb((), "amd64", "gnome", "ubuntu")
        for outil, taille in ((BASE, 1), (DECK, 2)):
            with self.subTest(outil=outil):
                self.assertEqual(taille, TODO._QEMU_VM_TOOLS[outil]["disk_gb"])
                avec = self.todo._qemu_tools_disk_gb(
                    (outil,), "amd64", "gnome", "ubuntu"
                )
                self.assertEqual(sans + taille, avec)


class LesBlocs(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_each_calls_its_command_in_the_checkout(self):
        """L'installateur se place lui-même à la racine du checkout ; le bloc
        y entre quand même, pour que le chemin relatif du profil et celui des
        cases soient la même commande."""
        for prod, racine in (
            (False, "$HOME/git/erplibre"),
            (True, "/opt/erplibre"),
        ):
            with self.subTest(prod=prod):
                base = self.todo._qemu_erplibre_home_remote_cmd(prod)
                self.assertIn(f'cd "{racine}" && {INSTALLEUR})', base)
                self.assertNotIn("--stream-deck", base)
                deck = self.todo._qemu_erplibre_home_remote_cmd(
                    prod, stream_deck=True
                )
                self.assertIn(f'cd "{racine}" && {STREAM_DECK})', deck)

    def test_the_after_phase_reaches_each(self):
        """Déclarer l'outil sans le brancher le laisserait cochable et sans
        effet. Seul, il n'entraîne pas le SDK Android."""
        for outil, commande in COMMANDES.items():
            with self.subTest(outil=outil):
                cmd = self.todo._qemu_after_remote_cmd((outil,), False)
                self.assertIn(commande + ")", cmd)
                self.assertNotIn("sdkmanager", cmd)
        self.assertNotIn(INSTALLEUR, self.todo._qemu_after_remote_cmd(()))

    def test_both_ticked_run_the_stream_deck_command_only(self):
        """Le niveau Stream Deck inclut la base : la lancer avant lui
        serait une installation de trop."""
        cmd = self.todo._qemu_after_remote_cmd((BASE, DECK), False)
        self.assertEqual(1, cmd.count(INSTALLEUR))
        self.assertIn(STREAM_DECK, cmd)

    def test_they_are_not_posed_before_the_clone(self):
        for outil in OUTILS:
            with self.subTest(outil=outil):
                self.assertEqual(
                    "",
                    self.todo._qemu_tools_remote_cmd(
                        (outil,), False, "before"
                    ),
                )

    def test_they_come_after_forgejo_and_before_the_android_sdk(self):
        """Quelques minutes de paquets et de venv : après la minute de
        Forgejo, avant l'heure du SDK. Un échec rapide se voit tôt."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                cmd = self.todo._qemu_after_remote_cmd(
                    ("forgejo", outil, "mobile"), False
                )
                self.assertLess(
                    cmd.index("install_forgejo.sh"), cmd.index(INSTALLEUR)
                )
                self.assertLess(cmd.index(INSTALLEUR), cmd.index("gradlew"))

    def test_a_failure_still_fails_the_vm(self):
        """Lié par « && », jamais par « ; » ni gardé par « || true » : une VM
        qui devait recevoir ERPLibre Home et ne l'a pas reçu n'est pas la VM
        demandée."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                cmd = self.todo._qemu_after_remote_cmd(
                    (outil, "mobile"), False
                )
                entre = cmd[
                    cmd.index(INSTALLEUR) : cmd.index("ERPLibre mobile")
                ]
                self.assertIn("&&", entre)
                self.assertNotIn("|| true", entre)

    def _joue(self, outil, code):
        """Joue la phase « after » comme la chaîne d'installation la lie, avec
        un installateur doublure qui note son répertoire et ses options, et
        rend `code`. Rend (résultat, répertoire vu, options vues, dépôt)."""
        cmd = self.todo._qemu_after_remote_cmd((outil,), False)
        with tempfile.TemporaryDirectory() as maison:
            depot = Path(maison) / "git" / "erplibre"
            script = depot / "script" / "install" / "install_erplibre_home.sh"
            script.parent.mkdir(parents=True)
            script.write_text(
                "#!/bin/bash\n"
                'pwd > "$HOME/vu"\n'
                'echo "$*" > "$HOME/options"\n'
                f"exit {code}\n"
            )
            script.chmod(0o755)
            res = subprocess.run(
                ["bash", "-c", "set -e; true && { " + cmd + " }"],
                capture_output=True,
                text=True,
                cwd=maison,
                env={"PATH": os.environ["PATH"], "HOME": maison},
            )
            vu = (Path(maison) / "vu").read_text().strip()
            options = (Path(maison) / "options").read_text().strip()
            return res, vu, options, str(depot)

    def test_the_installer_runs_from_the_checkout_with_its_option(self):
        for outil, option in OPTIONS.items():
            with self.subTest(outil=outil):
                res, vu, options, depot = self._joue(outil, 0)
                self.assertEqual(0, res.returncode, res.stderr)
                self.assertEqual(os.path.realpath(depot), os.path.realpath(vu))
                self.assertEqual(option, options)

    def test_its_exit_code_is_the_vm_verdict(self):
        """Le code 2 d'un système non pris en charge remonte tel quel : le
        tableau de bord le lit pour peindre la VM en rouge."""
        for outil in OUTILS:
            with self.subTest(outil=outil):
                res, _vu, _options, _depot = self._joue(outil, 2)
                self.assertEqual(2, res.returncode, res.stdout + res.stderr)

    def test_valid_shell_in_every_combination(self):
        for tools in (
            (BASE,),
            (DECK,),
            (BASE, DECK),
            (BASE, "forgejo"),
            ("aidev", "forgejo", BASE, DECK, "mobile", "avd"),
        ):
            with self.subTest(tools=tools):
                res = bash_n(self.todo._qemu_after_remote_cmd(tools, True))
                self.assertEqual(0, res.returncode, res.stderr)

    def test_a_desktop_only_vm_names_them_as_skipped(self):
        """Sans clone, l'installateur n'existe pas : une case cochée est
        NOMMÉE plutôt qu'écartée en silence."""
        cmd = self.todo._qemu_erplibre_remote_cmd(
            None, None, False, "gnome", "", "deb", OUTILS
        )
        self.assertIn(t("needs the ERPLibre install, skipped:"), cmd)
        self.assertIn(f"{BASE} {DECK}", cmd)
        self.assertNotIn(INSTALLEUR, cmd)

    def test_with_an_odoo_profile_they_come_after_the_make(self):
        for outil in OUTILS:
            with self.subTest(outil=outil):
                cmd = self.todo._qemu_erplibre_remote_cmd(
                    "develop", None, False, "gnome", "", "deb", (outil,)
                )
                self.assertLess(
                    cmd.index("make install_os"), cmd.index(INSTALLEUR)
                )
                self.assertEqual(0, bash_n(cmd).returncode)


class LeProfil(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.profils = self.todo._qemu_install_profiles()
        self.libelle = t(PROFIL)

    def test_it_is_offered_and_runs_the_base_alone(self):
        """Ni « make install_os » ni Odoo ni --stream-deck : l'installateur
        apporte ses paquets, et la VM est prête en quelques minutes."""
        self.assertEqual(INSTALLEUR, dict(self.profils)[self.libelle])

    def test_it_follows_the_mobile_profile(self):
        libelles = [libelle for libelle, _cmd in self.profils]
        self.assertEqual(
            libelles.index(t("ERPLibre mobile (home)")) + 1,
            libelles.index(self.libelle),
        )

    def test_odoo_stays_the_default(self):
        """Ajouter un profil ne doit pas déplacer le défaut de la réponse
        vide, le premier de la liste."""
        self.assertIn("install_odoo_18", self.profils[0][1])

    def test_the_vm_gets_the_desktop_first_and_no_odoo_service(self):
        """Le bureau est posé avant la commande du profil, sans quoi
        l'installateur ne trouve pas gnome-shell. Aucune cible install_odoo :
        aucun service erplibre.service."""
        cmd = self.todo._qemu_erplibre_remote_cmd(
            "develop", INSTALLEUR, False, "gnome", "", "deb", ()
        )
        self.assertIn(f"cd ~/git/erplibre && {INSTALLEUR}", cmd)
        self.assertLess(
            cmd.index(t("Installing the desktop (long):")),
            cmd.index(INSTALLEUR),
        )
        self.assertNotIn("make install_os", cmd)
        self.assertNotIn("erplibre.service", cmd)
        self.assertNotIn("--stream-deck", cmd)
        self.assertEqual(0, bash_n(cmd).returncode)

    def _avec(self, outil):
        return self.todo._qemu_erplibre_remote_cmd(
            "develop", INSTALLEUR, False, "gnome", "", "deb", (outil,)
        )

    def test_the_base_tool_with_the_profile_runs_it_twice(self):
        """Le second passage ne change rien : l'installateur est idempotent.
        Le bloc de la case n'est pas retiré pour autant — il porterait sinon
        une exception par profil."""
        cmd = self._avec(BASE)
        self.assertEqual(2, cmd.count(INSTALLEUR))
        self.assertNotIn("--stream-deck", cmd)

    def test_the_stream_deck_tool_adds_its_level_to_the_profile(self):
        """La base du profil d'abord ; la case n'y ajoute que le niveau
        Stream Deck, ses étapes de base n'ayant plus rien à faire."""
        cmd = self._avec(DECK)
        self.assertEqual(2, cmd.count(INSTALLEUR))
        self.assertEqual(1, cmd.count(STREAM_DECK))
        self.assertLess(
            cmd.index(f"cd ~/git/erplibre && {INSTALLEUR}"),
            cmd.index(STREAM_DECK),
        )

    def test_no_make_target_is_announced(self):
        """Le guide de connexion s'arrête à « git pull »."""
        self.assertEqual("", self.todo._qemu_make_target(INSTALLEUR))

    def test_the_checkout_is_still_cloned(self):
        """Le profil installe DEPUIS le dépôt : il le clone, et le guide le
        nomme. Il n'entre donc pas dans les commandes sans ERPLibre."""
        self.assertTrue(
            self.todo._qemu_installs_erplibre("develop", INSTALLEUR)
        )
        self.assertNotIn(INSTALLEUR, self.todo._qemu_no_erplibre_cmds())

    def _parts(self, bureau):
        vm = {
            "name": "essai",
            "distro": "ubuntu",
            "version": "24.04",
            "arch": "amd64",
            "vcpus": 2,
            "ram": 4096,
            "disk": "20G",
            "desktop": bureau,
            "branch": "",
            "install_cmd": INSTALLEUR,
            "install_label": self.libelle,
        }
        spec = {
            "vms": [vm],
            "existing": [],
            "ssh_key": "",
            "timezone": "",
            "desktop": bureau,
            "vm_tools": (),
            "python_provider": "",
            "app_store": "deb",
            "install": {
                "branch": "develop",
                "prod": False,
                "label": self.libelle,
                "monitor": True,
                "cmd": INSTALLEUR,
            },
        }
        return self.todo._qemu_deploy_parts_for(vm, spec, dry_run=True)

    def test_the_disk_keeps_the_desktop_and_checkout_margins(self):
        parts = self._parts("gnome")
        attendu = (
            20 + TODO.ERPLIBRE_EXTRA_DISK_GB + TODO.QEMU_DESKTOP_EXTRA_DISK_GB
        )
        self.assertEqual(f"{attendu}G", parts[parts.index("--disk-size") + 1])
        self.assertIn("--erplibre-dir", parts)
        self.assertNotIn("--erplibre-make", parts)


class LesLibelles(unittest.TestCase):
    def test_every_string_shown_is_translated(self):
        """Le libellé, l'indice, chaque ligne du « ? » et le profil : les
        deux langues sont obligatoires."""
        cles = [PROFIL]
        for outil in OUTILS:
            spec = TODO._QEMU_VM_TOOLS[outil]
            cles += [spec["label"], spec["hint"], *spec["help"]]
        for cle in cles:
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))

    def test_each_label_names_its_level(self):
        self.assertEqual("ERPLibre Home", TODO._QEMU_VM_TOOLS[BASE]["label"])
        self.assertEqual(
            "ERPLibre Home Stream Deck", TODO._QEMU_VM_TOOLS[DECK]["label"]
        )

    def test_the_help_names_the_command_and_the_logout(self):
        """GNOME Shell ne charge une extension neuve qu'au début d'une session
        sous Wayland : le « ? » le dit avant qu'on cherche une panne."""
        for outil, commande in COMMANDES.items():
            with self.subTest(outil=outil):
                aide = " ".join(TODO._QEMU_VM_TOOLS[outil]["help"])
                self.assertIn(commande[2:] + " in the VM's checkout", aide)
                self.assertIn("log out", aide)
        self.assertNotIn(
            "--stream-deck", " ".join(TODO._QEMU_VM_TOOLS[BASE]["help"])
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**
Run: `.venv.erplibre/bin/python -m unittest test.test_qemu_erplibre_home`
Expected: FAIL, `Ran 29 tests`, `FAILED (failures=6, errors=29)` (counted per subtest): `KeyError: 'erplibre_home'` or `KeyError: 'erplibre_home_streamdeck'` wherever a test reads the catalog, `AttributeError: … '_qemu_erplibre_home_remote_cmd'`, `KeyError` on the profile label, and failures where the after-phase script or the form lacks the installer.

- [ ] **Step 3: Implement**

3a. `script/todo/qemu_install.py`, `_qemu_install_profiles`: put the profile after the mobile one.

Before (lines 62-65):
```python
            (
                t("ERPLibre mobile (home)"),
                "make install_os && ./mobile/install_and_run.sh",
            ),
```
After:
```python
            (
                t("ERPLibre mobile (home)"),
                "make install_os && ./mobile/install_and_run.sh",
            ),
            # La base d'ERPLibre Home, sans « make install_os » :
            # l'installateur apporte ses propres paquets, et la VM est prête
            # en quelques minutes. Le bureau est posé avant cette commande,
            # d'où gnome-shell qu'il exige. La case « erplibre_home_streamdeck »
            # y ajoute le niveau Stream Deck.
            (
                t("ERPLibre Home (no Odoo)"),
                "./script/install/install_erplibre_home.sh",
            ),
```

3b. `script/todo/qemu_install.py`, `_QEMU_VM_TOOLS`: put both entries right after `gnome_ext`, base first.

Before (end of the `gnome_ext` entry, lines 921-925):
```python
            # Les paquets viennent des dépôts de la distribution, et le
            # gestionnaire d'extensions n'existe qu'à travers eux.
            "families": ("apt", "dnf", "pacman", "zypper"),
            "phase": "before",
        },
```
After:
```python
            # Les paquets viennent des dépôts de la distribution, et le
            # gestionnaire d'extensions n'existe qu'à travers eux.
            "families": ("apt", "dnf", "pacman", "zypper"),
            "phase": "before",
        },
        # ERPLibre Home, deux niveaux posés par
        # script/install/install_erplibre_home.sh, seule autorité de cette
        # installation — la même commande sert les cases, le profil « sans
        # Odoo », les entrées locales de TODO et le test long.
        # « erplibre_home » pose la base : l'extension GNOME, ses schémas et
        # ses traductions, activée. « erplibre_home_streamdeck » lance
        # --stream-deck : la base au besoin, puis les paquets USB, la règle
        # udev et .venv.streamdeck.
        #
        # « desktops » les borne à GNOME : l'extension déclare GNOME Shell 45
        # à 51, et l'installateur rend 2 là où gnome-shell manque. « arches »
        # les borne à amd64, seule architecture que la matrice de validation
        # couvre. « families » : les quatre gestionnaires dont l'installateur
        # porte la table de paquets.
        #
        # Disque : la base ne pose que glib, gettext et les traductions ; le
        # niveau Stream Deck y ajoute le venv (opencv-python en roue
        # manylinux, Pillow), hidapi, libusb et wmctrl.
        #
        # APRÈS l'installation : l'installateur vit dans le dépôt. Non
        # gardés, liés par « && » : une VM qui devait recevoir ERPLibre Home
        # et ne l'a pas reçu est rouge.
        "erplibre_home": {
            "label": "ERPLibre Home",
            "help": (
                "script/install/install_erplibre_home.sh in the VM's checkout",
                "extension, schemas and translations, extension enabled",
                "log out and back in to load the extension",
            ),
            "hint": "GNOME extension, no Stream Deck",
            "disk_gb": 1,
            "arches": ("amd64",),
            "desktops": ("gnome",),
            "needs_desktop": True,
            "families": ("apt", "dnf", "pacman", "zypper"),
            "phase": "after",
        },
        "erplibre_home_streamdeck": {
            "label": "ERPLibre Home Stream Deck",
            "help": (
                "script/install/install_erplibre_home.sh --stream-deck"
                " in the VM's checkout",
                "ERPLibre Home, plus USB packages, udev rule, .venv.streamdeck",
                "log out and back in to load the extension",
            ),
            "hint": "deck controller, games, GNOME extension",
            "disk_gb": 2,
            "arches": ("amd64",),
            "desktops": ("gnome",),
            "needs_desktop": True,
            "families": ("apt", "dnf", "pacman", "zypper"),
            "phase": "after",
        },
```

3c. `script/todo/qemu_install.py`: add the method just before `def _qemu_after_remote_cmd(self, tools, prod=False):` (line 2253):

```python
    def _qemu_erplibre_home_remote_cmd(self, prod=False, stream_deck=False):
        """Pose ERPLibre Home dans le checkout de la VM, par son installateur :
        la base, ou, avec `stream_deck`, le niveau Stream Deck, qui installe
        aussi la base au besoin.

        Rend un fragment shell sans « ; » final : le dernier maillon est
        l'installateur, dont le code de sortie devient celui du fragment — 2
        pour un système non pris en charge, 1 pour un autre échec. Aucune
        garde : la VM porte ce verdict.

        L'entrée dans le checkout se fait dans un sous-shell : les autres
        blocs de la phase « after » ne voient pas leur répertoire changer. Le
        chemin est entre guillemets doubles, qui laissent « $HOME » se
        développer.
        """
        el_dir = self._qemu_install_dir(prod)
        commande = "./script/install/install_erplibre_home.sh"
        titre = t("ERPLibre Home")
        if stream_deck:
            commande += " --stream-deck"
            titre = t("ERPLibre Home Stream Deck")
        return f'echo "== {titre} =="; (cd "{el_dir}" && {commande})'

```

3d. `script/todo/qemu_install.py`, `_qemu_after_remote_cmd`: change the `picked` tuple and add the dispatch.

Before (line 2265):
```python
            for k in ("aidev", "forgejo", "mobile", "avd")
```
After:
```python
            for k in (
                "aidev",
                "forgejo",
                "erplibre_home",
                "erplibre_home_streamdeck",
                "mobile",
                "avd",
            )
```

Before (lines 2279-2280):
```python
        if "forgejo" in picked:
            parts.append(f"{{ {self._qemu_forgejo_steps(el_dir)}; }}")
```
After:
```python
        if "forgejo" in picked:
            parts.append(f"{{ {self._qemu_forgejo_steps(el_dir)}; }}")
        # ERPLibre Home après Forgejo : quelques minutes de paquets, et de
        # venv pour le niveau Stream Deck, toujours moins que l'heure du SDK
        # Android. Le niveau Stream Deck inclut la base : cochées ensemble,
        # seule sa commande passe.
        if "erplibre_home_streamdeck" in picked:
            home = self._qemu_erplibre_home_remote_cmd(prod, stream_deck=True)
            parts.append(f"{{ {home}; }}")
        elif "erplibre_home" in picked:
            home = self._qemu_erplibre_home_remote_cmd(prod)
            parts.append(f"{{ {home}; }}")
```

3e. `script/todo/todo_i18n.py`. Add the label keys `"ERPLibre Home"` and `"ERPLibre Home Stream Deck"`: no key of those names exists yet. Leave `"Stream Deck"` (line 104), the label of the Stream Deck menu section, as it is.

Before (lines 7259-7262 at HEAD):
```python
    "ERPLibre mobile (home)": {
        "fr": "ERPLibre mobile (home)",
        "en": "ERPLibre mobile (home)",
    },
```
After:
```python
    "ERPLibre mobile (home)": {
        "fr": "ERPLibre mobile (home)",
        "en": "ERPLibre mobile (home)",
    },
    "ERPLibre Home (no Odoo)": {
        "fr": "ERPLibre Home (sans Odoo)",
        "en": "ERPLibre Home (no Odoo)",
    },
```

Before (lines 7431-7434 at HEAD):
```python
    "nixos-anywhere missing, see the log above": {
        "fr": "nixos-anywhere absent, voir le journal ci-dessus",
        "en": "nixos-anywhere missing, see the log above",
    },
```
After:
```python
    "nixos-anywhere missing, see the log above": {
        "fr": "nixos-anywhere absent, voir le journal ci-dessus",
        "en": "nixos-anywhere missing, see the log above",
    },
    # Outils QEMU « erplibre_home » et « erplibre_home_streamdeck » : leurs
    # libellés, leurs indices et les lignes de leur « ? ».
    "ERPLibre Home": {
        "fr": "ERPLibre Home",
        "en": "ERPLibre Home",
    },
    "ERPLibre Home Stream Deck": {
        "fr": "ERPLibre Home Stream Deck",
        "en": "ERPLibre Home Stream Deck",
    },
    "GNOME extension, no Stream Deck": {
        "fr": "extension GNOME, sans Stream Deck",
        "en": "GNOME extension, no Stream Deck",
    },
    "deck controller, games, GNOME extension": {
        "fr": "contrôleur du deck, jeux, extension GNOME",
        "en": "deck controller, games, GNOME extension",
    },
    "script/install/install_erplibre_home.sh in the VM's checkout": {
        "fr": "script/install/install_erplibre_home.sh dans le checkout de la VM",
        "en": "script/install/install_erplibre_home.sh in the VM's checkout",
    },
    "extension, schemas and translations, extension enabled": {
        "fr": "extension, schémas et traductions, extension activée",
        "en": "extension, schemas and translations, extension enabled",
    },
    "script/install/install_erplibre_home.sh --stream-deck"
    " in the VM's checkout": {
        "fr": "script/install/install_erplibre_home.sh --stream-deck"
        " dans le checkout de la VM",
        "en": "script/install/install_erplibre_home.sh --stream-deck"
        " in the VM's checkout",
    },
    "ERPLibre Home, plus USB packages, udev rule, .venv.streamdeck": {
        "fr": "ERPLibre Home, plus paquets USB, règle udev, .venv.streamdeck",
        "en": "ERPLibre Home, plus USB packages, udev rule, .venv.streamdeck",
    },
    "log out and back in to load the extension": {
        "fr": "fermer puis rouvrir la session pour charger l'extension",
        "en": "log out and back in to load the extension",
    },
```

- [ ] **Step 4: Run the new test, then see the existing disk test fail**
Run: `.venv.erplibre/bin/python -m unittest test.test_qemu_erplibre_home test.test_qemu_desktop_tools.TestToolDisk`
Expected: `Ran 32 tests`, `FAILED (failures=1)`: the 29 tests of `test_qemu_erplibre_home` pass. `FAIL: test_disk_follows_the_filtering` fails with "AssertionError: 29 != 26", because the arm64 VM now also loses the amd64-only `erplibre_home` (1 GB) and `erplibre_home_streamdeck` (2 GB).

- [ ] **Step 5: Update the existing disk test**

`test/test_qemu_desktop_tools.py`, `TestToolDisk.test_disk_follows_the_filtering`.

Before (lines 83-99):
```python
    def test_disk_follows_the_filtering(self):
        """Une VM qui ne recevra pas un outil ne doit pas se voir gonfler son
        disque de sa taille. En arm64 il en manque DEUX : Android Studio, que
        Google ne publie qu'en x86_64, et la compilation mobile, qui en
        dépend."""
        full = self.todo._qemu_tools_disk_gb(
            self.all, "amd64", "gnome", "ubuntu"
        )
        arm = self.todo._qemu_tools_disk_gb(
            self.all, "arm64", "gnome", "ubuntu"
        )
        self.assertEqual(
            full - arm,
            TODO._QEMU_VM_TOOLS["android"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["mobile"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["avd"]["disk_gb"],
        )
```
After:
```python
    def test_disk_follows_the_filtering(self):
        """Une VM qui ne recevra pas un outil ne doit pas se voir gonfler son
        disque de sa taille. En arm64 il en manque CINQ : Android Studio,
        que Google ne publie qu'en x86_64, la compilation mobile et
        l'émulateur, qui en dépendent, et les deux niveaux d'ERPLibre Home,
        bornés à amd64."""
        full = self.todo._qemu_tools_disk_gb(
            self.all, "amd64", "gnome", "ubuntu"
        )
        arm = self.todo._qemu_tools_disk_gb(
            self.all, "arm64", "gnome", "ubuntu"
        )
        self.assertEqual(
            full - arm,
            TODO._QEMU_VM_TOOLS["android"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["mobile"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["avd"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["erplibre_home"]["disk_gb"]
            + TODO._QEMU_VM_TOOLS["erplibre_home_streamdeck"]["disk_gb"],
        )
```

- [ ] **Step 6: Run tests to verify they pass, including every suite that touches tools, profiles and i18n**
Run:
```bash
cd "$(git rev-parse --show-toplevel)"
.venv.erplibre/bin/python -m unittest test.test_qemu_erplibre_home test.test_qemu_forgejo test.test_qemu_nixanywhere test.test_qemu_install_profile test.test_qemu_desktop_tools test.test_deploy_form_help test.test_qemu_motd test.test_qemu_nixos test.test_qemu_proxmox test.test_qemu_ai_tools test.test_todo_deploy_form_parity test.test_todo_i18n test.test_i18n_duplicates
./script/test/run_unit_test.sh test/test_qemu_erplibre_home.py test/test_qemu_desktop_tools.py test/test_qemu_install_profile.py test/test_deploy_form_help.py test/test_todo_i18n.py test/test_i18n_duplicates.py
.venv.erplibre/bin/ruff format --check script/todo/qemu_install.py test/test_qemu_erplibre_home.py test/test_qemu_desktop_tools.py
.venv.erplibre/bin/ruff check --select I script/todo/qemu_install.py test/test_qemu_erplibre_home.py
python3 script/analyse/check_comment_hygiene.py script/todo/qemu_install.py test/test_qemu_erplibre_home.py test/test_qemu_desktop_tools.py
```
Expected: `Ran 463 tests ... OK (skipped=2)` (434 at `dc841639`, plus this task's 29), where the 2 skips depend on Textual being present. `run_unit_test.sh` reports `216 tests, tout vert`. Ruff reports "3 files already formatted" and "All checks passed!". The hygiene check adds no new 🔴 and no new 🟡 compared with HEAD: qemu_install.py keeps its existing 31 signals, test_qemu_desktop_tools.py its 1 (`extensions.gnome.org`), test_qemu_erplibre_home.py has none. Do not run `ruff format` on `todo_i18n.py`: that file is not ruff-clean at HEAD, and reformatting it would rewrite thousands of unrelated lines.

- [ ] **Step 7: Commit**
```bash
cd "$(git rev-parse --show-toplevel)"
git add script/todo/qemu_install.py script/todo/todo_i18n.py test/test_qemu_erplibre_home.py test/test_qemu_desktop_tools.py
cat > $SCRATCH/msg_task6.txt <<'EOF'
[ADD] qemu: ERPLibre Home VM tools and no-Odoo install profile

The QEMU tools catalog gains "erplibre_home", the base, and
"erplibre_home_streamdeck", which runs the installer with --stream-deck;
both after-phase, bounded to GNOME, amd64 and four families, chained with
&&, so a failed or UNSUPPORTED install marks the VM failed. Ticked
together, only the Stream Deck command runs. The "ERPLibre Home (no
Odoo)" profile runs the base alone after the desktop: no make install_os,
no Odoo service; the desktop and checkout disk margins still apply.

--- FR ---
[ADD] qemu : outils de VM ERPLibre Home et profil sans Odoo

Le catalogue des outils QEMU gagne « erplibre_home », la base, et
« erplibre_home_streamdeck », qui lance l'installateur avec --stream-deck ;
tous deux en phase « after », bornés à GNOME, amd64 et quatre familles,
liés par &&, si bien qu'une installation échouée ou UNSUPPORTED rend la VM
rouge. Cochés ensemble, seule la commande du Stream Deck passe. Le profil
« ERPLibre Home (sans Odoo) » lance la base seule après le bureau : ni
make install_os ni service Odoo ; les marges disque restent.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task6.txt
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task6.txt
```
Expected: `commit-msg` exits 0. This message passes the hook unchanged.

Notes for the plan assembler:
- Everything above was run against a `git archive` copy of `dc841639` with Tasks 1-5 applied. The new test failed before the change and passed after it (29 tests). The disk test failed with 29 != 26 until it was updated. The full list passed with 463 tests OK. The commit message passed `script/git/hooks/commit-msg`.
- The tool labels are `"ERPLibre Home"` and `"ERPLibre Home Stream Deck"` as the spec says. Their i18n keys are new in 3e and carry no icon.
- `deploy_qemu.py` `TOOL_GUIDE` (the login guide) gets no entry for either tool. The spec does not ask for one, and `test_qemu_motd.test_every_key_exists_in_the_catalogue` only checks guide keys against the catalog, not the other way round.

---

### Task 7: descente.detruire undoes every level-1 VM

**Files:**
- Modify: `long_test/descente.py:1207-1316` (the whole `detruire` function; a new helper `racines_du_rapport` is inserted just before it)
- Test: `test/test_todo_longtest.py` (new class `TestDetruireChaqueEtage1`, inserted just before `class TestLeMenu(unittest.TestCase):` at line 1753)

**Interfaces:**
- Consumes: `descente.dernier_rapport(outil, prefixe)`, `a_defaire(rapport, nom_base)`, `detruire_etage1(journal, nom, dry_run=False, attendu=None, cree=True)`, `retirer_alias(rapport, journal, nom_base)`, `autre_descente()`, `nom_etage(niveau, base)`, `Famille(outil, nom_base, detruire_une)`, `Descente.uuid_libvirt` (all unchanged).
- Produces: `descente.racines_du_rapport(rapport, nom_base="") -> list[tuple[str, str|None, bool]]`. It returns `(nom, uuid, cree)` for each `niveau == 1` entry, in report order. When the report has no level-1 entry, it returns `[(nom_etage(1, nom_base), None, True)]`.
- Changes `descente.detruire(famille, journal=None, dry_run=False)`. It now calls `detruire_etage1` once for each level-1 entry. It still asks for confirmation once. The total is `len(liste) + len(racines)`, and the exit code is 0 only when every root is undone. A report with one level-1 entry (the `deep_*` and `install_nixos` shape) produces the same calls as before and the same `"N VM imbriquée(s) + l'étage 1 :"` header. With 2 or more roots the header reads `"N VM imbriquée(s) + K VM d'étage 1 :"`. The warning when a root survives still contains `l'étage 1 est DEBOUT`, followed by the names of the roots that are still up.
- Task 9 calls `detruire_etage1` and `retirer_alias` directly between systems. With `--detruire`, it relies on this function to undo every VM it kept.
- This task does not add `install_erplibre_home.py` to `SCRIPTS`; Task 9 does.

- [ ] **Step 1: Write the failing test**

In `test/test_todo_longtest.py`, insert this class immediately before the line `class TestLeMenu(unittest.TestCase):` (currently line 1753), keeping two blank lines on each side. The file already imports `contextlib`, `io`, `unittest` and `descente as moteur`.

```python
class TestDetruireChaqueEtage1(unittest.TestCase):
    """detruire défait CHAQUE machine de niveau 1 que le rapport nomme.

    Un test long qui crée une VM par système en laisse plusieurs au rapport,
    gardées par --garder ou laissées par un arrêt en route : chacune est une
    racine, identifiée par son UUID, et une seule confirmation les couvre
    toutes. Un rapport deep_* n'en porte qu'une, défaite seule et sous le nom
    que le rapport lui donne.
    """

    ALPHA = {
        "niveau": 1,
        "nom": "essai-sd-alpha",
        "uuid": "uuid-alpha",
        "alias": "essai-sd-alpha",
        "cree": True,
    }
    BETA = {
        "niveau": 1,
        "nom": "essai-sd-beta",
        "uuid": "uuid-beta",
        "alias": "essai-sd-beta",
        "cree": True,
    }
    IMBRIQUE = {
        "niveau": 2,
        "identite": "uuid-imbrique",
        "parent_alias": "essai-sd-alpha",
        "nom": "essai-sd-2",
    }

    def setUp(self):
        import builtins

        # Tout bouchon est posé sur le MOTEUR et rendu par addCleanup : un
        # bouchon qui fuit fausse les classes suivantes, qui inspectent la
        # vraie fonction.
        for nom in (
            "autre_descente",
            "dernier_rapport",
            "detruire_etage1",
            "retirer_alias",
        ):
            self.addCleanup(setattr, moteur, nom, getattr(moteur, nom))
        self.addCleanup(setattr, builtins, "input", builtins.input)
        self.addCleanup(
            setattr, moteur.subprocess, "run", moteur.subprocess.run
        )
        # Le staticmethod lui-même, pas la fonction qu'il enveloppe.
        self.addCleanup(
            setattr,
            moteur.Descente,
            "uuid_libvirt",
            moteur.Descente.__dict__["uuid_libvirt"],
        )
        moteur.autre_descente = lambda: []
        moteur.retirer_alias = lambda *a, **k: None
        self.questions = []
        builtins.input = lambda prompt="": (
            self.questions.append(prompt) or "OUI"
        )
        self.imbriques = []
        self.famille = moteur.Famille(
            "essai_multi",
            "essai-sd",
            lambda parent, identite, nom, journal: (
                self.imbriques.append(nom) or True
            ),
        )

    def _rapport(self, *etages):
        moteur.dernier_rapport = lambda outil="", prefixe="": {
            "fichier": "/essai.json",
            "outil": "essai_multi",
            "etages": list(etages),
        }

    def _espionner_etage1(self, debout=()):
        """Remplace detruire_etage1 ; rend la liste (nom, attendu, cree)."""
        appels = []

        def espion(journal, nom, dry_run=False, attendu=None, cree=True):
            appels.append((nom, attendu, cree))
            return nom not in debout

        moteur.detruire_etage1 = espion
        return appels

    def _lancer(self, dry_run=False):
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            code = moteur.detruire(self.famille, None, dry_run=dry_run)
        return code, sortie.getvalue()

    def test_every_level_one_entry_is_destroyed_by_its_uuid(self):
        self._rapport(self.ALPHA, self.BETA)
        appels = self._espionner_etage1()
        code, texte = self._lancer()
        self.assertEqual(
            appels,
            [
                ("essai-sd-alpha", "uuid-alpha", True),
                ("essai-sd-beta", "uuid-beta", True),
            ],
        )
        self.assertEqual(code, 0)
        self.assertIn("2 / 2 défait(s)", texte)
        self.assertEqual(len(self.questions), 1)

    def test_a_surviving_root_is_named_and_the_others_still_go(self):
        self._rapport(self.ALPHA, self.BETA)
        appels = self._espionner_etage1(debout=("essai-sd-alpha",))
        code, texte = self._lancer()
        # L'échec de la première n'arrête pas la seconde.
        self.assertEqual(len(appels), 2)
        self.assertEqual(code, 1)
        self.assertIn("1 / 2 défait(s)", texte)
        self.assertIn("l'étage 1 est DEBOUT", texte)
        self.assertIn("essai-sd-alpha", texte.split("DEBOUT")[1])

    def test_the_dry_run_lists_every_root_and_touches_nothing(self):
        self._rapport(self.ALPHA, self.BETA)
        appels = self._espionner_etage1()
        code, texte = self._lancer(dry_run=True)
        self.assertEqual(code, 0)
        self.assertEqual(appels, [])
        self.assertEqual(self.questions, [])
        self.assertIn("0 VM imbriquée(s) + 2 VM d'étage 1 :", texte)
        self.assertIn("étage  1  essai-sd-alpha (libvirt)", texte)
        self.assertIn("étage  1  essai-sd-beta (libvirt)", texte)

    def test_virsh_undefines_each_root_after_checking_its_uuid(self):
        """La vraie detruire_etage1, virsh bouchonné : chaque racine est
        lue (dominfo, UUID) puis effacée sous SON nom."""
        import types

        lances = []

        def faux(argv, **kw):
            lances.append(list(argv))
            return types.SimpleNamespace(returncode=0, stdout="", stderr="")

        moteur.subprocess.run = faux
        moteur.Descente.uuid_libvirt = staticmethod(
            lambda nom: {
                "essai-sd-alpha": "uuid-alpha",
                "essai-sd-beta": "uuid-beta",
            }.get(nom, "")
        )
        self._rapport(self.ALPHA, self.BETA)
        code, texte = self._lancer()
        effaces = [
            argv[3] for argv in lances if argv[1:3] == ["virsh", "undefine"]
        ]
        self.assertEqual(effaces, ["essai-sd-alpha", "essai-sd-beta"])
        self.assertEqual(code, 0)
        self.assertIn("2 / 2 défait(s)", texte)

    def test_a_single_root_report_is_undone_alone(self):
        """La forme d'un rapport deep_* : un étage imbriqué, une racine."""
        self._rapport(self.IMBRIQUE, self.ALPHA)
        appels = self._espionner_etage1()
        code, texte = self._lancer()
        self.assertEqual(appels, [("essai-sd-alpha", "uuid-alpha", True)])
        self.assertEqual(self.imbriques, ["essai-sd-2"])
        self.assertIn("1 VM imbriquée(s) + l'étage 1 :", texte)
        self.assertIn("2 / 2 défait(s)", texte)
        self.assertEqual(code, 0)

    def test_without_a_level_one_entry_the_root_is_the_base_name(self):
        self._rapport(self.IMBRIQUE)
        appels = self._espionner_etage1()
        code, _texte = self._lancer()
        self.assertEqual(appels, [("essai-sd-1", None, True)])
        self.assertEqual(code, 0)

    def test_a_borrowed_root_is_passed_as_not_created(self):
        self._rapport(dict(self.ALPHA, uuid=None, cree=False))
        appels = self._espionner_etage1()
        self._lancer()
        self.assertEqual(appels, [("essai-sd-alpha", None, False)])
```

- [ ] **Step 2: Run test to verify it fails**

Run (from the checkout root): `.venv.erplibre/bin/python -m unittest test.test_todo_longtest.TestDetruireChaqueEtage1 -v`
Expected: `FAILED (failures=4)`. These four tests fail:
- `test_every_level_one_entry_is_destroyed_by_its_uuid`: `Lists differ: [('essai-sd-alpha', 'uuid-alpha', True)] != [('essai-sd-alpha', 'uuid-alpha', True), ('essai-sd-beta', 'uuid-beta', True)]`
- `test_a_surviving_root_is_named_and_the_others_still_go`: `AssertionError: 1 != 2`
- `test_the_dry_run_lists_every_root_and_touches_nothing`: `"0 VM imbriquée(s) + 2 VM d'étage 1 :" not found in ...`
- `test_virsh_undefines_each_root_after_checking_its_uuid`: `Lists differ: ['essai-sd-alpha'] != ['essai-sd-alpha', 'essai-sd-beta']`

The other three tests (single root, base-name fallback, borrowed root) already pass. They guard the `deep_*` behaviour.

- [ ] **Step 3: Implement**

In `long_test/descente.py`, replace the whole function at lines 1207-1316, from `def detruire(famille, journal=None, dry_run=False):` up to and including its final `    return 1`, with the block below. The two blank lines before `def retirer_alias(` stay as they are.

```python
def racines_du_rapport(rapport, nom_base=""):
    """[(nom, uuid, cree)] des machines de niveau 1, dans l'ordre du rapport.

    Une descente en inscrit une ; un test long qui crée une VM par système en
    inscrit une par machine encore debout. Sans aucune entrée de niveau 1, la
    liste porte une seule racine, nommée `nom_etage(1, nom_base)` et sans
    UUID : detruire_etage1 la cherche alors par son nom, et le dit.
    """
    racines = [
        (
            e.get("nom") or nom_etage(1, nom_base),
            e.get("uuid"),
            bool(e.get("cree", True)),
        )
        for e in (rapport.get("etages") or [])
        if int(e.get("niveau", 0)) == 1
    ]
    return racines or [(nom_etage(1, nom_base), None, True)]


def detruire(famille, journal=None, dry_run=False):
    """Défait ce que le DERNIER rapport dit avoir créé, du plus profond.

    Rien d'autre : chaque machine visée est nommée par le rapport, avec
    l'identifiant noté à sa création, jamais choisie d'après un préfixe de
    nom. Les étages imbriqués partent d'abord, chez leur parent, puis CHAQUE
    machine de niveau 1 (racines_du_rapport). Une seule confirmation couvre
    le tout.

    Rend 0 quand toutes les racines sont défaites, 1 quand une descente
    tourne, quand la confirmation est refusée ou quand une racine reste
    debout.
    """
    # Avant tout : refuser tant qu'une descente tourne. Elle installe encore
    # sur les machines qu'on s'apprête à détruire, et son rapport peut être
    # celui qu'on vient de choisir.
    autres = autre_descente()
    if autres:
        dire(
            f"  ⛔ une descente tourne ({', '.join(map(str, autres))}) :"
            " rien ne sera détruit.",
            journal,
        )
        dire("  Attendre qu'elle finisse, ou l'arrêter d'abord.", journal)
        return 1
    rapport = dernier_rapport(famille.outil, famille.nom_base)
    if not rapport:
        dire("  aucun rapport de descente : rien à défaire.", journal)
        dire(
            "  (les entrées ~/.ssh/config orphelines : menu de nettoyage)",
            journal,
        )
        return 0
    liste = a_defaire(rapport, famille.nom_base)
    racines = racines_du_rapport(rapport, famille.nom_base)
    total = len(liste) + len(racines)
    dire(f"  rapport : {rapport.get('fichier')}", journal)
    dire(
        f"  {len(liste)} VM imbriquée(s) + "
        + (
            "l'étage 1 :"
            if len(racines) == 1
            else f"{len(racines)} VM d'étage 1 :"
        ),
        journal,
    )
    for niveau, parent_alias, identite, nom in liste:
        dire(
            f"    étage {niveau:2d}  {nom} ({identite}) sur {parent_alias}",
            journal,
        )
    for nom, _uuid, _cree in racines:
        dire(f"    étage  1  {nom} (libvirt)", journal)
    if dry_run:
        dire("\n  --dry-run : rien ne sera détruit.", journal)
        return 0
    # Une confirmation, parce que « --purge » emporte les disques et que le
    # menu lance cette option d'une seule touche.
    reponse = input("\n  Détruire tout cela ? (tapez OUI) : ").strip()
    if reponse != "OUI":
        dire("  annulé.", journal)
        return 1
    faits = sum(
        1
        for niveau, parent_alias, identite, nom in liste
        if famille.detruire_une(parent_alias, identite, nom, journal)
    )
    # Chaque racine compte pour un dans le total, défaite ou non : le
    # décompte final se lit contre len(liste) + len(racines). L'échec de
    # l'une n'arrête pas les suivantes.
    debout = []
    for nom, uuid, cree in racines:
        if detruire_etage1(journal, attendu=uuid, nom=nom, cree=cree):
            faits += 1
        else:
            debout.append(nom)
    retirer_alias(rapport, journal, famille.nom_base)
    if not debout:
        # Une racine est un DISQUE, et ses étages imbriqués vivent dedans.
        # « virsh undefine --remove-all-storage » l'a effacé : un étage
        # injoignable — son parent éteint — a disparu avec lui. Tout est
        # donc défait, et l'écart dit seulement combien l'ont été ainsi.
        reste = total - faits
        dire(
            f"\n  {total} / {total} défait(s)."
            + (
                f"  ({reste} injoignable(s), emporté(s) avec le disque de"
                " l'étage 1.)"
                if reste
                else ""
            ),
            journal,
        )
        return 0
    dire(
        f"\n  {faits} / {total} défait(s)."
        f"  ⚠ l'étage 1 est DEBOUT ({', '.join(debout)}) :"
        " ce qu'il contient vit encore.",
        journal,
    )
    return 1
```

Notes for the implementer:
- `detruire_etage1` is still looked up as a module global, so the existing tests that set `moteur.detruire_etage1 = ...` keep working.
- The `(libvirt)` lines now come from `racines`. A one-root report prints the same name as before, and a report with no root prints `nom_etage(1, famille.nom_base)` as before.
- In `TestLeDecompteDeLaDestruction` the report has no level-1 entry, so there is 1 fallback root and the result is still `"3 / 3"`.
- `test_longtest_install_nixos` also keeps passing: it checks `"0 VM imbriquée(s)"` and that `"long-nixos-1 "` does not appear.

- [ ] **Step 4: Run tests to verify they pass**

All from the checkout root:

```bash
.venv.erplibre/bin/python -m unittest test.test_todo_longtest.TestDetruireChaqueEtage1 -v
# Expected: Ran 7 tests ... OK

.venv.erplibre/bin/python -m unittest test.test_todo_longtest
# Expected: Ran 98 tests ... OK  (includes TestLeDecompteDeLaDestruction, TestLEtage1SIdentifiePasParSonNom,
#           TestNeJamaisDetruireSousUneDescenteVivante, TestNeDetruirePasCeQuOnNaPasCree)

.venv.erplibre/bin/python -m unittest test.test_longtest_install_nixos test.test_deep_qemu test.test_longtest_confirm test.test_qemu_cache_charge test.test_qemu_cache_mesure
# Expected: OK (install_nixos runs its real --detruire --dry-run against a one-root report)

./script/test/run_unit_test.sh test/test_todo_longtest.py test/test_longtest_install_nixos.py test/test_deep_qemu.py
# Expected: all green

.venv.erplibre/bin/ruff format --check long_test/descente.py test/test_todo_longtest.py
# Expected: 2 files already formatted
.venv.erplibre/bin/ruff check long_test/descente.py test/test_todo_longtest.py
# Expected: All checks passed!
python3 script/analyse/check_comment_hygiene.py long_test/descente.py test/test_todo_longtest.py
# Expected: "0 identifiant" (the 10 yellow lines already exist before this task and are unchanged)
```

- [ ] **Step 5: Commit**

```bash
cd "$(git rev-parse --show-toplevel)"
git add long_test/descente.py test/test_todo_longtest.py
mkdir -p tasks
cat > $SCRATCH/msg_task7.txt <<'EOF'
[IMP] long_test: undo every level-1 VM of the last report

descente.detruire undid only the first niveau == 1 entry of a report. A
long test that creates one VM per system leaves several such entries when
--garder keeps them or a run stops midway, and --detruire left all but one
running. Every level-1 entry is now listed, confirmed once, and destroyed
by its own name and UUID; a root that survives is named and the exit code
is 1. A report with a single root, the deep_* shape, is undone as before.

--- FR ---

[IMP] long_test : défaire chaque VM de niveau 1 du dernier rapport

descente.detruire ne défaisait que la première entrée niveau == 1 d'un
rapport. Un test long qui crée une VM par système en laisse plusieurs
quand --garder les garde ou qu'une course s'arrête en route, et
--detruire en laissait toutes sauf une debout. Chaque entrée de niveau 1
est désormais listée, confirmée une fois et détruite sous son nom et son
UUID ; une racine qui survit est nommée et le code de sortie vaut 1. Un
rapport à une seule racine, la forme deep_*, est défait comme avant.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task7.txt
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task7.txt
```

(This message passes `script/git/hooks/commit-msg` with exit code 0.)

---

### Task 8: Long test pure helpers

**Files:**
- Create: `long_test/install_erplibre_home.py`
- Test: `test/test_longtest_install_erplibre_home.py`

**Interfaces:**
- Consumes: `long_test/descente.py::module_qemu()` (only in the tests, to check that the matrix keys exist in `deploy_qemu.DISTROS`). It also reads `script/gnome-extension/erplibre_home/metadata.json` (`uuid`, `shell-version`) and `extension.js` (`IFACE_XML` interface `org.gnome.Shell.Extensions.ERPLibreHome`, object `/org/gnome/Shell/Extensions/ERPLibreHome`, methods `ListPaths` / `ListDevices`, the `[ERPLibreHome] mount ${id} failed` line that `_mount` logs when an indicator's constructor throws, and the `[ERPLibreHome] enabled` line that ends `enable()`).
- Produces (the names fixed by the shared interfaces): `MATRICE`, `NON_SUPPORTES`, `FAMILLE`, `plan(only)`, `analyser_extension_info(sortie)`, `est_active(info)`, `autologin(famille, user)`, `verdict_systeme(entree, code_install, info, gnome_mesure, *, echec=None, raison="", duree_s=0, journal=None)`, `code_sortie(systemes)`, `arbre_propre(racine)`.
  - `verdict_systeme` takes 4 extra keyword arguments, all with defaults, so the shared signature still holds. Task 9 uses them.
  - The task also adds these helpers for Task 9: `OUTIL="install_erplibre_home"`, `NOM_BASE="long-sd"`, `UUID_EXTENSION`, `UTILISATEUR="erplibre"`, `SYSTEME_EXTRAS="ubuntu:24.04"`, `VCPUS=2`, `MEMOIRE_MO=4096`, `DISQUE_GO=26`, `ARCHITECTURES_HORS_CHAMP`, `COMMANDE_GIT`, `FICHIER_AUTOLOGIN`, `CMD_SESSION`, `CMD_INFO`, `OBJET_EXTENSION`, `INTERFACE_EXTENSION`, `cmd_methode(m)`, `CMD_VENV` (imports `StreamDeck, pyudev, PIL, cv2, requests, keyboard`), `REGLE_UDEV`, `VENV_DECK`, `LIEN_EXTENSION`, `CMD_UDEV`, `CMD_SANS_REGLE`, `CMD_SANS_VENV`, `CMD_LIEN`, `CMD_SANS_LIEN` (each prints `ok` or nothing), `CMD_MTIME_LIEN` (the link alone, for `base-idempotent`), `CMD_MTIMES` (rule, venv and link, for `stream-deck-idempotent`), `CMD_ENABLED` (`gsettings get org.gnome.shell enabled-extensions` on the user bus), `liste_extensions(sortie) -> list|None` (wraps `gsettings_strv.parse_strv`, imported from `script/gnome-extension/erplibre_home/tools` through `sys.path`; `None` for an empty output or on `ValueError`/`SyntaxError`), `CMD_JOURNAL`, `CMD_EXT_INFO`, `CMD_MONTAGES`, `indicateurs_en_echec(sortie)`, `journal_lu(sortie)`, `cle(entree)`, `version_gnome(s)`, `majeur(v)`, `raison_non_supportee(s)`, `nom_vm(entree, horodatage)`, `argv_creation(entree, nom, cle_pub="", drapeaux=())`, `ligne_non_supportee(entree)`, `resume(systemes)`.
  - The five stages of spec 6.2, as data: `ETAPES`, a tuple of `{"nom", "commande", "option", "controles"}` dicts in the spec's order — `base` (no command; checks `session`, `gnome-version`, `extension-active`, `extension-dbus`, `extension-indicators`, `base-no-udev`, `base-no-venv`, `base-idempotent`), `stream-deck` (`install-stream-deck`, `--stream-deck`; `udev`, `venv`, `stream-deck-active`, `stream-deck-idempotent`), `partial-uninstall` (`uninstall-stream-deck`, `--uninstall --stream-deck`; `partial-uninstall-gone`, `partial-uninstall-kept`), `uninstall` (`uninstall`, `--uninstall`; `uninstall-gone`), `reinstall` (`reinstall`, `""` then a reboot; `reinstall-active`, `reinstall-indicators`, `reinstall-no-udev`). `OPTION` maps each command name to its installer option. `decrire_etapes(extras=False)` returns the five plan lines that Task 9's dry run prints. Every command and check name is unique.
  - `arbre_propre` uses `git status --porcelain --untracked-files=no`. This is a deliberate change from the literal `--porcelain` in the spec. An untracked file is in neither HEAD nor the bundle, and `private/` is not git-ignored, so counting untracked files would block every run.

- [ ] **Step 1: Write the failing test**

Create `test/test_longtest_install_erplibre_home.py`:

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long qui installe ERPLibre Home sur chaque distribution.

Lui crée une VM par système et prend des heures ; ceux-ci tiennent ses
fonctions pures en quelques millisecondes :

- la matrice : ses clés existent au catalogue QEMU, et chaque GNOME attendu
  est dans le « shell-version » de l'extension ;
- la lecture de « GetExtensionInfo » : ACTIVE, ERROR, OUT_OF_DATE, absente ;
- la lecture du journal de session : les indicateurs que l'extension n'a
  pas montés ;
- les cinq étapes de chaque VM, leurs commandes et leurs contrôles, et la
  lecture d'enabled-extensions ;
- l'autologin de chaque famille, rejoué sur un vrai fichier ;
- le verdict d'un système et le code de sortie de la course ;
- le refus d'un arbre de travail modifié.
"""

import configparser
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "long_test"))

import install_erplibre_home as sd  # noqa: E402

EXTENSION = RACINE / "script/gnome-extension/erplibre_home"

# Sorties de « gdbus call … GetExtensionInfo », au format texte de GVariant.
INFO_ACTIVE = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'name': <'ERPLibre Home'>,"
    " 'type': <2.0>, 'state': <1.0>, 'error': <''>,"
    " 'hasPrefs': <true>, 'enabled': <true>},)"
)
INFO_ERREUR = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'type': <2.0>,"
    " 'state': <3.0>, 'error': <'TypeError: this.foo is not a function'>,"
    " 'enabled': <true>},)"
)
INFO_PERIMEE = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'type': <2.0>,"
    " 'state': <4.0>, 'error': <''>, 'enabled': <true>},)"
)
INFO_ABSENTE = "(@a{sv} {},)"
INFO_GUILLEMETS = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'state': <3.0>,"
    ' \'error\': <"can\'t load \\"x\\"">},)'
)

# Le custom.conf que livre le paquet GDM d'une distribution Debian.
GDM_LIVRE = """# GDM configuration storage
[daemon]
# Uncomment the line below to force the login screen to use Xorg
#WaylandEnable=false

# Enabling automatic login
#  AutomaticLoginEnable = true
#  AutomaticLogin = user1

[security]

[debug]
#Enable=true
"""


class LaMatrice(unittest.TestCase):
    def test_the_keys_are_those_of_the_spec(self):
        self.assertEqual(
            [sd.cle(e) for e in sd.MATRICE],
            [
                "ubuntu:24.04",
                "ubuntu:25.10",
                "ubuntu:26.04",
                "debian:13",
                "fedora:41",
                "fedora:42",
                "fedora:43",
                "fedora:44",
                "almalinux:10",
                "rocky:10",
                "opensuse:16.0",
                "arch:latest",
                "opensuse:tumbleweed",
            ],
        )

    def test_only_the_rolling_ones_may_move_past_the_extension(self):
        roulantes = [sd.cle(e) for e in sd.MATRICE if e["roulante"]]
        self.assertEqual(roulantes, ["arch:latest", "opensuse:tumbleweed"])

    def test_every_key_is_in_the_qemu_catalog(self):
        """La clé part telle quelle vers deploy_qemu.py : une clé qu'il ne
        connaît pas fait tomber la VM avant qu'elle n'existe."""
        import descente

        catalogue = descente.module_qemu().DISTROS
        for entree in sd.MATRICE + sd.NON_SUPPORTES:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(entree["distro"], catalogue)
                self.assertIn(
                    entree["version"], catalogue[entree["distro"]][0]
                )

    def test_every_expected_gnome_is_declared_by_the_extension(self):
        """Un GNOME attendu hors « shell-version » promettrait ACTIVE là où
        l'installateur rendra 2."""
        meta = json.loads(
            (EXTENSION / "metadata.json").read_text(encoding="utf-8")
        )
        for entree in sd.MATRICE:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(entree["gnome_attendu"], meta["shell-version"])

    def test_every_distribution_has_a_family(self):
        for entree in sd.MATRICE:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(
                    sd.FAMILLE[entree["distro"]],
                    ("debian", "rhel", "suse", "arch"),
                )
                self.assertIn(sd.FAMILLE[entree["distro"]], sd.COMMANDE_GIT)

    def test_the_unsupported_ones_are_not_in_the_matrix(self):
        dans = {sd.cle(e) for e in sd.MATRICE}
        for entree in sd.NON_SUPPORTES:
            with self.subTest(cle=sd.cle(entree)):
                self.assertNotIn(sd.cle(entree), dans)
                self.assertTrue(entree["raison"])


class LePlan(unittest.TestCase):
    def test_no_filter_gives_the_whole_matrix(self):
        self.assertEqual(sd.plan(None), sd.MATRICE)
        self.assertEqual(sd.plan(""), sd.MATRICE)

    def test_the_plan_is_a_copy(self):
        sd.plan(None)[0]["distro"] = "autre"
        self.assertEqual(sd.MATRICE[0]["distro"], "ubuntu")

    def test_only_keeps_the_order_asked_for(self):
        choisis = sd.plan("fedora:43, ubuntu:24.04,fedora:43")
        self.assertEqual(
            [sd.cle(e) for e in choisis], ["fedora:43", "ubuntu:24.04"]
        )

    def test_an_unknown_key_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            sd.plan("ubuntu:22.04")
        self.assertIn("ubuntu:22.04", str(ctx.exception))

    def test_an_unsupported_key_says_why(self):
        with self.assertRaises(ValueError) as ctx:
            sd.plan("debian:12")
        self.assertIn("GNOME 43 < 45", str(ctx.exception))

    def test_an_empty_list_is_refused(self):
        with self.assertRaises(ValueError):
            sd.plan(" , ")


class LaReponseDeGnomeShell(unittest.TestCase):
    def test_active(self):
        info = sd.analyser_extension_info(INFO_ACTIVE)
        self.assertEqual(info, {"state": 1.0, "error": ""})
        self.assertTrue(sd.est_active(info))

    def test_error(self):
        info = sd.analyser_extension_info(INFO_ERREUR)
        self.assertEqual(info["state"], 3.0)
        self.assertEqual(
            info["error"], "TypeError: this.foo is not a function"
        )
        self.assertFalse(sd.est_active(info))

    def test_out_of_date(self):
        info = sd.analyser_extension_info(INFO_PERIMEE)
        self.assertEqual(info, {"state": 4.0, "error": ""})
        self.assertFalse(sd.est_active(info))

    def test_absent_extension(self):
        """GNOME Shell rend un dictionnaire vide pour un UUID qu'il ne
        connaît pas : ni état, ni erreur, et pas ACTIVE."""
        info = sd.analyser_extension_info(INFO_ABSENTE)
        self.assertEqual(info, {"state": None, "error": ""})
        self.assertFalse(sd.est_active(info))

    def test_no_answer_at_all(self):
        self.assertEqual(
            sd.analyser_extension_info(""), {"state": None, "error": ""}
        )
        self.assertFalse(sd.est_active(None))

    def test_a_double_quoted_error_is_read_and_unescaped(self):
        info = sd.analyser_extension_info(INFO_GUILLEMETS)
        self.assertEqual(info["error"], 'can\'t load "x"')

    def test_an_error_text_alone_is_not_active(self):
        """État 1 avec une erreur : l'extension a levé, elle n'est pas
        ACTIVE au sens du test."""
        self.assertFalse(sd.est_active({"state": 1.0, "error": "boom"}))


class LesCommandesVisentLExtension(unittest.TestCase):
    def test_the_uuid_is_the_one_of_metadata(self):
        meta = json.loads(
            (EXTENSION / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sd.UUID_EXTENSION, meta["uuid"])

    def test_the_object_and_interface_are_those_extension_js_exports(self):
        src = (EXTENSION / "extension.js").read_text(encoding="utf-8")
        self.assertIn(f"'{sd.OBJET_EXTENSION}'", src)
        self.assertIn(f'<interface name="{sd.INTERFACE_EXTENSION}">', src)
        for methode in ("ListPaths", "ListDevices"):
            with self.subTest(methode=methode):
                self.assertIn(f'<method name="{methode}">', src)
                self.assertIn(
                    f"{sd.INTERFACE_EXTENSION}.{methode}",
                    sd.cmd_methode(methode),
                )

    def test_session_commands_name_the_user_bus(self):
        for commande in (sd.CMD_SESSION, sd.CMD_INFO, sd.CMD_EXT_INFO):
            with self.subTest(commande=commande[:60]):
                self.assertIn("/run/user/$(id -u)/bus", commande)

    def test_the_gnome_version_is_read(self):
        self.assertEqual(sd.version_gnome("GNOME Shell 46.0\n"), "46.0")
        self.assertEqual(sd.version_gnome("GNOME Shell 50.beta"), "50.beta")
        self.assertEqual(sd.version_gnome("bash: gnome-shell: not found"), "")
        self.assertEqual(sd.majeur("46.0"), "46")

    def test_the_unsupported_reason_is_the_installer_line(self):
        sortie = "family=arch\nUNSUPPORTED: GNOME 52 not in shell-version\n"
        self.assertEqual(
            sd.raison_non_supportee(sortie), "GNOME 52 not in shell-version"
        )
        self.assertEqual(sd.raison_non_supportee("ok\n"), "")
        # Les lignes de la migration ne sont pas une raison.
        self.assertEqual(
            sd.raison_non_supportee("migrate: no session bus\nok\n"), ""
        )


class LesIndicateursNonMontes(unittest.TestCase):
    """L'extension attrape l'exception du constructeur d'un indicateur et
    reste ACTIVE : seul le journal de session nomme ce qui manque."""

    def test_failed_mounts_are_listed_by_id(self):
        sortie = (
            "[ERPLibreHome] mount pencil failed:"
            " No property vertical on StBoxLayout\n"
            "[ERPLibreHome] mount device failed:"
            " No property vertical on StBoxLayout\n"
        )
        self.assertEqual(sd.indicateurs_en_echec(sortie), ["device", "pencil"])

    def test_other_journal_lines_are_ignored(self):
        sortie = (
            "[ERPLibreHome] enabled\n"
            "[ERPLibreHome] sync failed: timeout\n"
            "gnome-shell[4242]: mount point busy, failed\n"
        )
        self.assertEqual(sd.indicateurs_en_echec(sortie), [])

    def test_no_output_is_no_failure(self):
        self.assertEqual(sd.indicateurs_en_echec(None), [])
        self.assertEqual(sd.indicateurs_en_echec(""), [])

    def test_the_journal_is_read_when_enable_logged_its_end(self):
        sortie = (
            "[ERPLibreHome] mount device failed:"
            " No property vertical on StBoxLayout\n"
            "[ERPLibreHome] enabled\n"
        )
        self.assertTrue(sd.journal_lu(sortie))

    def test_no_enabled_line_is_an_unread_journal(self):
        """Sans la ligne de fin d'enable(), l'absence d'échec ne prouve
        rien : ssh a pu tomber ou le journal être vide."""
        self.assertFalse(sd.journal_lu(None))
        self.assertFalse(sd.journal_lu(""))
        self.assertFalse(
            sd.journal_lu(
                "[ERPLibreHome] mount pencil failed: boom\n"
                "[ERPLibreHome] disabled\n"
            )
        )

    def test_the_command_reads_the_lines_extension_js_writes(self):
        src = (EXTENSION / "extension.js").read_text(encoding="utf-8")
        self.assertIn("[ERPLibreHome] mount ${id} failed", src)
        self.assertIn("'[ERPLibreHome] enabled'", src)
        self.assertIn("journalctl --user -b", sd.CMD_MONTAGES)
        self.assertIn("mount", sd.CMD_MONTAGES)
        self.assertIn("enabled", sd.CMD_MONTAGES)


class LesEtapes(unittest.TestCase):
    """Les cinq étapes de la spec, dans son ordre, avec ses noms."""

    def test_the_five_stages_in_order(self):
        self.assertEqual(
            [(e["nom"], e["commande"], e["option"]) for e in sd.ETAPES],
            [
                ("base", None, None),
                ("stream-deck", "install-stream-deck", "--stream-deck"),
                (
                    "partial-uninstall",
                    "uninstall-stream-deck",
                    "--uninstall --stream-deck",
                ),
                ("uninstall", "uninstall", "--uninstall"),
                ("reinstall", "reinstall", ""),
            ],
        )

    def test_the_checks_of_each_stage(self):
        self.assertEqual(
            [list(e["controles"]) for e in sd.ETAPES],
            [
                [
                    "session",
                    "gnome-version",
                    "extension-active",
                    "extension-dbus",
                    "extension-indicators",
                    "base-no-udev",
                    "base-no-venv",
                    "base-idempotent",
                ],
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
                    "reinstall-no-udev",
                ],
            ],
        )

    def test_every_name_is_unique(self):
        """« etape » dit seul quelle étape est tombée : aucun nom de
        commande ou de contrôle ne sert deux fois, ni ne reprend un échec
        d'avant les étapes."""
        noms = ["vm", "ssh", "desktop", "code", "install", "autologin"]
        for etape in sd.ETAPES:
            if etape["commande"]:
                noms.append(etape["commande"])
            noms.extend(etape["controles"])
        self.assertEqual(len(noms), len(set(noms)), noms)

    def test_the_plan_describes_each_stage(self):
        lignes = sd.decrire_etapes()
        self.assertEqual(len(lignes), 5)
        for ligne, etape in zip(lignes, sd.ETAPES, strict=True):
            with self.subTest(etape=etape["nom"]):
                for controle in etape["controles"]:
                    self.assertIn(controle, ligne)
                if etape["option"]:
                    self.assertIn(
                        "install_erplibre_home.sh " + etape["option"], ligne
                    )
        self.assertIn("redémarrage", lignes[4])
        self.assertNotIn("--with-extras", " ".join(lignes))
        extras = sd.decrire_etapes(extras=True)
        self.assertIn("--with-extras", extras[0])
        self.assertIn("--with-extras", extras[4])

    def test_the_venv_check_imports_what_the_entry_points_import(self):
        for module in ("StreamDeck", "pyudev", "PIL", "cv2", "requests"):
            with self.subTest(module=module):
                self.assertIn(module, sd.CMD_VENV)
        self.assertIn("keyboard", sd.CMD_VENV)

    def test_the_presence_checks_name_the_rule_venv_and_link(self):
        self.assertIn(sd.REGLE_UDEV, sd.CMD_SANS_REGLE)
        self.assertIn(".venv.streamdeck", sd.CMD_SANS_VENV)
        self.assertIn(sd.UUID_EXTENSION, sd.CMD_LIEN)
        self.assertIn(sd.UUID_EXTENSION, sd.CMD_SANS_LIEN)
        for commande in (
            sd.CMD_SANS_REGLE,
            sd.CMD_SANS_VENV,
            sd.CMD_LIEN,
            sd.CMD_SANS_LIEN,
        ):
            with self.subTest(commande=commande):
                self.assertTrue(commande.endswith("&& echo ok"))
        self.assertIn("/run/user/$(id -u)/bus", sd.CMD_ENABLED)

    def test_the_enabled_list_is_read(self):
        self.assertEqual(sd.liste_extensions("@as []"), [])
        self.assertEqual(
            sd.liste_extensions(
                "['autre@exemple.org', 'erplibre-home@technolibre.ca']\n"
            ),
            ["autre@exemple.org", "erplibre-home@technolibre.ca"],
        )

    def test_an_unread_list_is_none(self):
        """Une lecture ratée n'est ni une liste vide ni une liste pleine."""
        for sortie in (None, "", "No such schema", "[cassé"):
            with self.subTest(sortie=sortie):
                self.assertIsNone(sd.liste_extensions(sortie))


class LAutologin(unittest.TestCase):
    """La commande est rejouée pour de vrai sur un fichier temporaire, avec
    un « sudo » qui ne fait qu'exécuter son argument."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="sd-autologin-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        faux = os.path.join(self.dossier, "bin")
        os.makedirs(faux)
        sudo = os.path.join(faux, "sudo")
        with open(sudo, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "$@"\n')
        os.chmod(sudo, 0o755)
        self.env = dict(os.environ, PATH=f"{faux}:{os.environ['PATH']}")

    def _jouer(self, famille, contenu=None, fois=1):
        chemin, commande = sd.autologin(famille, "erplibre")
        cible = os.path.join(self.dossier, "etc", os.path.basename(chemin))
        if contenu is not None:
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            with open(cible, "w", encoding="utf-8") as fh:
                fh.write(contenu)
        commande = commande.replace(chemin, cible)
        for _ in range(fois):
            fini = subprocess.run(
                ["bash", "-c", commande],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, fini.returncode, fini.stderr)
        with open(cible, encoding="utf-8") as fh:
            return fh.read()

    @staticmethod
    def _daemon(texte):
        cp = configparser.ConfigParser(strict=False, interpolation=None)
        cp.optionxform = str
        cp.read_string(texte)
        return dict(cp["daemon"])

    def test_the_file_of_each_family(self):
        self.assertEqual(
            sd.autologin("debian", "erplibre")[0], "/etc/gdm3/custom.conf"
        )
        self.assertEqual(
            sd.autologin("rhel", "erplibre")[0], "/etc/gdm/custom.conf"
        )
        self.assertEqual(
            sd.autologin("arch", "erplibre")[0], "/etc/gdm/custom.conf"
        )
        self.assertEqual(
            sd.autologin("suse", "erplibre")[0],
            "/etc/sysconfig/displaymanager",
        )

    def test_the_keys_go_under_daemon(self):
        texte = self._jouer("debian", GDM_LIVRE)
        self.assertEqual(
            self._daemon(texte),
            {"AutomaticLoginEnable": "true", "AutomaticLogin": "erplibre"},
        )
        # Les commentaires et les autres sections restent.
        self.assertIn("#  AutomaticLogin = user1", texte)
        self.assertIn("[security]", texte)

    def test_a_second_run_changes_nothing(self):
        une = self._jouer("rhel", GDM_LIVRE)
        deux = self._jouer("rhel", GDM_LIVRE, fois=2)
        self.assertEqual(une, deux)

    def test_a_previous_user_is_replaced(self):
        texte = self._jouer(
            "arch", "[daemon]\nAutomaticLoginEnable=false\nAutomaticLogin=x\n"
        )
        self.assertEqual(
            self._daemon(texte),
            {"AutomaticLoginEnable": "true", "AutomaticLogin": "erplibre"},
        )

    def test_a_missing_file_gets_the_section(self):
        texte = self._jouer("arch")
        self.assertEqual(
            self._daemon(texte),
            {"AutomaticLoginEnable": "true", "AutomaticLogin": "erplibre"},
        )

    def test_suse_sets_its_sysconfig_key(self):
        livre = (
            '## Type: string\nDISPLAYMANAGER_AUTOLOGIN=""\n'
            'DISPLAYMANAGER="gdm"\n'
        )
        texte = self._jouer("suse", livre, fois=2)
        self.assertEqual(texte.count("DISPLAYMANAGER_AUTOLOGIN="), 1, texte)
        self.assertIn('DISPLAYMANAGER_AUTOLOGIN="erplibre"', texte)
        self.assertIn('DISPLAYMANAGER="gdm"', texte)

    def test_neither_sed_nor_crudini(self):
        for famille in ("debian", "rhel", "arch", "suse"):
            with self.subTest(famille=famille):
                commande = sd.autologin(famille, "erplibre")[1]
                self.assertNotIn("sed ", commande)
                self.assertNotIn("crudini", commande)

    def test_a_user_name_that_could_inject_is_refused(self):
        for nom in ("", "x; rm -rf /", "Root", "a b"):
            with self.subTest(nom=nom):
                with self.assertRaises(ValueError):
                    sd.autologin("debian", nom)

    def test_an_unknown_family_is_refused(self):
        with self.assertRaises(ValueError):
            sd.autologin("nixos", "erplibre")


class LeVerdict(unittest.TestCase):
    UBUNTU = sd.MATRICE[0]
    ARCH = next(e for e in sd.MATRICE if e["distro"] == "arch")

    def test_active(self):
        ligne = sd.verdict_systeme(
            self.UBUNTU,
            0,
            {"state": 1.0, "error": ""},
            "46.0",
            duree_s=12.7,
            journal="ubuntu-24.04.log",
        )
        self.assertEqual(
            ligne,
            {
                "distro": "ubuntu",
                "version": "24.04",
                "gnome_attendu": "46",
                "gnome_mesure": "46.0",
                "verdict": "ACTIVE",
                "etape": None,
                "duree_s": 12,
                "journal": "ubuntu-24.04.log",
            },
        )

    def test_a_failure_before_the_install_names_its_step(self):
        ligne = sd.verdict_systeme(self.UBUNTU, None, None, "", echec="vm")
        self.assertEqual((ligne["verdict"], ligne["etape"]), ("FAILED", "vm"))
        self.assertIsNone(ligne["gnome_mesure"])

    def test_an_install_without_a_code_is_an_install_failure(self):
        ligne = sd.verdict_systeme(self.UBUNTU, None, None, "")
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]), ("FAILED", "install")
        )

    def test_exit_2_is_unsupported_with_the_reason(self):
        ligne = sd.verdict_systeme(
            self.ARCH, 2, None, "", raison="GNOME 52 not in shell-version"
        )
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]),
            ("UNSUPPORTED", "GNOME 52 not in shell-version"),
        )

    def test_exit_1_is_an_install_failure(self):
        ligne = sd.verdict_systeme(self.UBUNTU, 1, None, "")
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]), ("FAILED", "install")
        )

    def test_a_failed_check_is_named(self):
        ligne = sd.verdict_systeme(
            self.UBUNTU, 0, None, "46.0", echec="session"
        )
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]), ("FAILED", "session")
        )

    def test_a_stage_command_or_check_is_named(self):
        """Après l'installation de la base, l'échec d'une étape porte le nom
        de sa commande ou de son contrôle."""
        for echec in ("install-stream-deck", "reinstall-no-udev"):
            with self.subTest(echec=echec):
                ligne = sd.verdict_systeme(
                    self.UBUNTU,
                    0,
                    {"state": 1.0, "error": ""},
                    "46.0",
                    echec=echec,
                )
                self.assertEqual(
                    (ligne["verdict"], ligne["etape"]), ("FAILED", echec)
                )

    def test_an_extension_in_error_is_not_active(self):
        ligne = sd.verdict_systeme(
            self.UBUNTU, 0, {"state": 3.0, "error": "boom"}, "46.0"
        )
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]),
            ("FAILED", "extension-active"),
        )

    def test_an_unsupported_line_has_no_vm(self):
        ligne = sd.ligne_non_supportee(sd.NON_SUPPORTES[0])
        self.assertEqual(ligne["verdict"], "UNSUPPORTED")
        self.assertEqual(ligne["etape"], "GNOME 43 < 45")
        self.assertIsNone(ligne["journal"])


class LeCodeDeSortie(unittest.TestCase):
    @staticmethod
    def _ligne(entree, verdict):
        return dict(
            sd.ligne_non_supportee(dict(entree, raison="")), verdict=verdict
        )

    def test_all_active_is_zero(self):
        lignes = [self._ligne(e, "ACTIVE") for e in sd.MATRICE]
        self.assertEqual(sd.code_sortie(lignes), 0)

    def test_unsupported_is_allowed_only_where_rolling(self):
        arch = next(e for e in sd.MATRICE if e["distro"] == "arch")
        self.assertEqual(sd.code_sortie([self._ligne(arch, "UNSUPPORTED")]), 0)
        self.assertEqual(
            sd.code_sortie([self._ligne(sd.MATRICE[0], "UNSUPPORTED")]), 1
        )

    def test_one_failure_is_one(self):
        lignes = [self._ligne(e, "ACTIVE") for e in sd.MATRICE]
        lignes[3]["verdict"] = "FAILED"
        self.assertEqual(sd.code_sortie(lignes), 1)

    def test_out_of_scope_lines_do_not_count(self):
        lignes = [sd.ligne_non_supportee(e) for e in sd.NON_SUPPORTES]
        lignes.append(self._ligne(sd.MATRICE[0], "ACTIVE"))
        self.assertEqual(sd.code_sortie(lignes), 0)

    def test_the_summary_flags_a_gnome_mismatch(self):
        lignes = sd.resume(
            [
                sd.verdict_systeme(
                    sd.MATRICE[0], 0, {"state": 1.0, "error": ""}, "47.1"
                )
            ]
        )
        self.assertIn("ubuntu:24.04", lignes[1])
        self.assertIn("≠", lignes[1])
        self.assertIn("ACTIVE", lignes[1])


class LaCreation(unittest.TestCase):
    def test_the_vm_is_sized_here(self):
        argv = sd.argv_creation(
            sd.MATRICE[0], "long-sd-x", "/k.pub", ["--cache-bypass"]
        )
        ligne = " ".join(argv)
        for attendu in (
            "deploy_qemu.py",
            "--distro ubuntu",
            "--version 24.04",
            "--name long-sd-x",
            "--desktop",
            "--gpu off",
            "--vcpus 2",
            "--memory 4096",
            "--disk-size 26G",
            "--ssh-key /k.pub",
            "--cache-bypass",
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, ligne)
        self.assertNotIn("sudo", argv)

    def test_without_a_key_none_is_passed(self):
        self.assertNotIn("--ssh-key", sd.argv_creation(sd.MATRICE[0], "n"))

    def test_the_vm_name_is_a_plain_host_name(self):
        opensuse = next(e for e in sd.MATRICE if e["version"] == "16.0")
        self.assertEqual(
            sd.nom_vm(opensuse, "120000"), "long-sd-opensuse-16-0-120000"
        )


class LArbreDeTravail(unittest.TestCase):
    def setUp(self):
        self.depot = tempfile.mkdtemp(prefix="sd-arbre-")
        self.addCleanup(shutil.rmtree, self.depot, ignore_errors=True)

    def _git(self, *args):
        subprocess.run(
            [
                "git",
                "-C",
                self.depot,
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.invalid",
                *args,
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )

    def _depot_commite(self):
        self._git("init", "-q")
        with open(os.path.join(self.depot, "a.txt"), "w") as fh:
            fh.write("a\n")
        self._git("add", "a.txt")
        self._git("commit", "-qm", "a")

    def test_a_committed_tree_is_clean(self):
        self._depot_commite()
        self.assertTrue(sd.arbre_propre(self.depot))

    def test_a_modified_tracked_file_is_refused(self):
        self._depot_commite()
        with open(os.path.join(self.depot, "a.txt"), "a") as fh:
            fh.write("b\n")
        self.assertFalse(sd.arbre_propre(self.depot))

    def test_an_untracked_file_does_not_count(self):
        """Il n'est ni dans HEAD ni dans le bundle."""
        self._depot_commite()
        with open(os.path.join(self.depot, "notes.txt"), "w") as fh:
            fh.write("x\n")
        self.assertTrue(sd.arbre_propre(self.depot))

    def test_a_directory_that_is_not_a_repository_is_refused(self):
        self.assertFalse(sd.arbre_propre(self.depot))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv.erplibre/bin/python -m unittest test.test_longtest_install_erplibre_home`
Expected: FAIL with `ModuleNotFoundError: No module named 'install_erplibre_home'`

- [ ] **Step 3: Implement**

Create `long_test/install_erplibre_home.py`. Task 9 adds the executable bit, so do not chmod it here.

```python
#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""ERPLibre Home s'installe-t-il, extension ACTIVE, sur chaque distribution ?

Une VM par version de distribution, l'une après l'autre. Chacune reçoit le
bureau GNOME par la commande du menu, le code du checkout par un bundle git,
puis la base d'ERPLibre Home par `script/install/install_erplibre_home.sh`.
Une session GNOME s'ouvre par autologin, et le verdict est ce que GNOME Shell
répond à `GetExtensionInfo` : état 1 et erreur vide. Figurer dans
`enabled-extensions` ne suffit pas — une extension qui lève dans `enable()`
y reste listée, en ERREUR.

Sur la même VM passent ensuite cinq étapes (ETAPES) : la base, l'ajout du
niveau Stream Deck, son retrait seul, le retrait de tout, puis la base de
nouveau. Chacune lance une commande de l'installateur et ses contrôles ; le
premier échec arrête la VM et nomme la commande ou le contrôle.

Il vit dans long_test/ et non dans test/ : il crée de vraies machines et
prend des heures.

CE QU'IL INSTALLE : HEAD, ET RIEN D'AUTRE

Le code part du checkout par « git bundle create … HEAD », et la VM ne joint
jamais GitHub pour lui. Un fichier suivi et modifié fait refuser la course :
ce qui serait installé ne serait pas ce qui est commité.

  ./long_test/install_erplibre_home.py                 # toute la matrice
  ./long_test/install_erplibre_home.py --only ubuntu:24.04,fedora:43
  ./long_test/install_erplibre_home.py --extras        # + --with-extras
  ./long_test/install_erplibre_home.py --dry-run       # le plan, rien de créé
  ./long_test/install_erplibre_home.py --garder        # garder les VM
  ./long_test/install_erplibre_home.py --detruire      # défaire la course
"""

import os
import re
import shlex
import subprocess
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Les listes que gsettings affiche se lisent par le lecteur que partagent
# les outils de l'extension.
sys.path.insert(
    0, os.path.join(RACINE, "script/gnome-extension/erplibre_home/tools")
)
from gsettings_strv import parse_strv  # noqa: E402

OUTIL = "install_erplibre_home"
NOM_BASE = "long-sd"
UUID_EXTENSION = "erplibre-home@technolibre.ca"
# L'utilisateur que deploy_qemu.py crée par défaut : celui de ssh, celui de
# l'autologin, donc celui dont le bus de session est sondé.
UTILISATEUR = "erplibre"
# Le seul système où « --extras » ajoute « --with-extras » à l'installation.
SYSTEME_EXTRAS = "ubuntu:24.04"

# Le gabarit de chaque VM. deploy_qemu.py n'ajoute rien pour un bureau : la
# taille se pose donc ici. « --gpu off » est le cas le plus contraint, le
# rendu logiciel, et un verdict obtenu là tient sur un hôte sans nœud de
# rendu.
VCPUS = 2
MEMOIRE_MO = 4096
DISQUE_GO = 26


def _entree(distro, version, gnome, roulante=False):
    return {
        "distro": distro,
        "version": version,
        "gnome_attendu": gnome,
        "roulante": roulante,
    }


# La matrice, dans l'ordre où les VM se succèdent. La clé « distro:version »
# est celle que deploy_qemu.py accepte et que « --only » reçoit.
#
# « gnome_attendu » est une AFFIRMATION, pas une mesure : chaque VM mesure
# « gnome-shell --version », le rapport porte les deux, et c'est d'après ces
# rapports que la colonne se corrige.
#
# « roulante » : la distribution avance sans numéro. Un GNOME au-delà de
# « shell-version » y rend UNSUPPORTED, et c'est le signal attendu pour mettre
# metadata.json à jour, non une panne.
MATRICE = [
    _entree("ubuntu", "24.04", "46"),
    _entree("ubuntu", "25.10", "49"),
    _entree("ubuntu", "26.04", "50"),
    _entree("debian", "13", "48"),
    _entree("fedora", "41", "47"),
    _entree("fedora", "42", "48"),
    _entree("fedora", "43", "49"),
    _entree("fedora", "44", "50"),
    _entree("almalinux", "10", "47"),
    _entree("rocky", "10", "47"),
    _entree("opensuse", "16.0", "48"),
    _entree("arch", "latest", "51", roulante=True),
    _entree("opensuse", "tumbleweed", "50", roulante=True),
]

# Hors champ, sans VM : le rapport les porte UNSUPPORTED avec leur raison. Les
# versions de GNOME viennent des notes de version amont, pas d'une mesure.
NON_SUPPORTES = [
    {"distro": "debian", "version": "12", "raison": "GNOME 43 < 45"},
    {"distro": "almalinux", "version": "9", "raison": "GNOME 40 < 45"},
    {"distro": "rocky", "version": "9", "raison": "GNOME 40 < 45"},
    {
        "distro": "nixos",
        "version": "25.11",
        "raison": "no GNOME desktop path in the QEMU installer",
    },
    {
        "distro": "proxmox",
        "version": "9",
        "raison": "hypervisor host, out of scope",
    },
]
ARCHITECTURES_HORS_CHAMP = ("arm64", "s390x", "ppc64le")

# La famille de chaque distribution de la matrice : elle choisit le
# gestionnaire de paquets et le fichier d'autologin.
FAMILLE = {
    "ubuntu": "debian",
    "debian": "debian",
    "fedora": "rhel",
    "almalinux": "rhel",
    "rocky": "rhel",
    "opensuse": "suse",
    "arch": "arch",
}

# git, que le chemin « bureau seul » du menu n'installe pas et que les images
# cloud minimales n'embarquent pas toujours.
COMMANDE_GIT = {
    "debian": "command -v git >/dev/null || sudo DEBIAN_FRONTEND="
    "noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y git",
    "rhel": "command -v git >/dev/null || sudo dnf install -y git",
    "suse": "command -v git >/dev/null || sudo zypper --non-interactive"
    " install git",
    "arch": "command -v git >/dev/null || sudo pacman -S --needed"
    " --noconfirm git",
}

# Le fichier que lit le gestionnaire de connexion de chaque famille.
FICHIER_AUTOLOGIN = {
    "debian": "/etc/gdm3/custom.conf",
    "rhel": "/etc/gdm/custom.conf",
    "arch": "/etc/gdm/custom.conf",
    "suse": "/etc/sysconfig/displaymanager",
}

# Les commandes de session lisent le bus de l'utilisateur connecté à GNOME :
# ssh n'en hérite pas, il faut le nommer.
BUS = "export DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/$(id -u)/bus; "
CMD_SESSION = (
    BUS + "test -S /run/user/$(id -u)/bus && gdbus call --session"
    " --dest org.freedesktop.DBus --object-path /org/freedesktop/DBus"
    " --method org.freedesktop.DBus.NameHasOwner org.gnome.Shell"
)
CMD_INFO = (
    BUS + "gdbus call --session --dest org.gnome.Shell.Extensions"
    " --object-path /org/gnome/Shell/Extensions"
    " --method org.gnome.Shell.Extensions.GetExtensionInfo " + UUID_EXTENSION
)
# L'objet que l'extension exporte elle-même, sur la connexion de GNOME Shell.
OBJET_EXTENSION = "/org/gnome/Shell/Extensions/ERPLibreHome"
INTERFACE_EXTENSION = "org.gnome.Shell.Extensions.ERPLibreHome"
# Les imports des points d'entrée du deck. keyboard s'importe sans root :
# il n'ouvre les périphériques d'entrée qu'au démarrage d'un crochet.
CMD_VENV = (
    "cd ~/git/erplibre && .venv.streamdeck/bin/python -c"
    " 'import StreamDeck, pyudev, PIL, cv2, requests, keyboard;"
    ' print("ok")\''
)
REGLE_UDEV = "/etc/udev/rules.d/70-streamdeck.rules"
VENV_DECK = "~/git/erplibre/.venv.streamdeck"
LIEN_EXTENSION = f"~/.local/share/gnome-shell/extensions/{UUID_EXTENSION}"
CMD_UDEV = (
    f"grep -q uaccess {REGLE_UDEV} && grep -q 0fd9 {REGLE_UDEV} && echo ok"
)
# Les constats d'absence et de présence rendent « ok » ou rien : une sortie
# vide, ssh tombé compris, ne passe jamais pour le constat attendu.
CMD_SANS_REGLE = f"test ! -e {REGLE_UDEV} && echo ok"
CMD_SANS_VENV = f"test ! -e {VENV_DECK} && echo ok"
CMD_LIEN = f"test -L {LIEN_EXTENSION} && echo ok"
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
    " | tail -200"
)
CMD_EXT_INFO = BUS + f"gnome-extensions info {UUID_EXTENSION} 2>&1"
# La clé que l'installateur écrit et que la désinstallation vide.
CMD_ENABLED = BUS + "gsettings get org.gnome.shell enabled-extensions"
# Deux sortes de lignes d'extension.js : « mount <id> failed », écrite par
# _mount() quand le constructeur d'un indicateur lève, et « enabled », écrite
# à la fin d'enable(), après les montages. L'extension attrape l'exception et
# continue : elle reste ACTIVE, et ListDevices rend « [] » sans l'indicateur
# des appareils comme sans appareil. « || true » garde le code 0 quand grep
# ne trouve rien ; une sortie sans « enabled » veut alors dire que le journal
# n'a pas été lu (ssh tombé, journal vide), jamais que tout est monté.
CMD_MONTAGES = (
    "journalctl --user -b -o cat --no-pager 2>&1"
    r" | grep -E '\[ERPLibreHome\] (mount [^ ]+ failed|enabled)' || true"
)


def _etape(nom, commande, option, controles):
    return {
        "nom": nom,
        "commande": commande,
        "option": option,
        "controles": controles,
    }


# Les cinq étapes, dans l'ordre où elles passent sur la même VM. « commande »
# nomme l'échec quand l'installateur lancé avec « option » ne rend pas 0 ; la
# base n'en a pas, son installation est celle qui précède l'autologin, et
# « reinstall » est suivie d'un redémarrage. « controles » vient ensuite,
# dans l'ordre. Chaque nom, de commande ou de contrôle, est unique : le champ
# « etape » du rapport dit seul quelle étape est tombée.
ETAPES = (
    _etape(
        "base",
        None,
        None,
        (
            "session",
            "gnome-version",
            "extension-active",
            "extension-dbus",
            "extension-indicators",
            "base-no-udev",
            "base-no-venv",
            "base-idempotent",
        ),
    ),
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
        "",
        ("reinstall-active", "reinstall-indicators", "reinstall-no-udev"),
    ),
)
# L'option de l'installateur de chaque commande d'étape.
OPTION = {e["commande"]: e["option"] for e in ETAPES if e["commande"]}


def decrire_etapes(extras=False):
    """Les lignes du plan qui décrivent les cinq étapes d'une VM.

    `extras` : la base s'installe avec « --with-extras » (SYSTEME_EXTRAS).
    """
    base = "install_erplibre_home.sh" + (" --with-extras" if extras else "")
    lignes = []
    for rang, etape in enumerate(ETAPES, 1):
        if etape["commande"] is None:
            quoi = f"{base}, autologin, redémarrage"
        elif etape["option"]:
            quoi = f"{etape['commande']} : install_erplibre_home.sh"
            quoi += f" {etape['option']}"
        else:
            quoi = f"{etape['commande']} : {base}, redémarrage"
        lignes.append(
            f"    étape {rang}, {etape['nom']} — {quoi} —"
            f" {', '.join(etape['controles'])}"
        )
    return lignes


def liste_extensions(sortie):
    """La liste qu'affiche « gsettings get … enabled-extensions », ou None.

    Lue par parse_strv, le lecteur des outils de l'extension : « @as [] »
    pour une liste vide, « ['a', 'b'] » sinon. None quand la sortie est vide
    ou n'est pas une telle liste : une lecture ratée ne passe ni pour une
    liste vide ni pour une liste pleine.
    """
    texte = (sortie or "").strip()
    if not texte:
        return None
    try:
        return parse_strv(texte)
    except (ValueError, SyntaxError):
        return None


def cmd_methode(methode):
    """L'appel d'une méthode de l'extension sur le bus de session."""
    return (
        BUS + "gdbus call --session --dest org.gnome.Shell"
        f" --object-path {OBJET_EXTENSION}"
        f" --method {INTERFACE_EXTENSION}.{methode}"
    )


def cle(entree):
    return f"{entree['distro']}:{entree['version']}"


def plan(only=None):
    """Les systèmes à mener, copies des entrées de MATRICE.

    `only` : clés « distro:version » séparées par des virgules, dans l'ordre
    voulu ; None ou "" donne toute la matrice. Une clé hors champ ou inconnue
    lève ValueError plutôt que d'être ignorée : un plan amputé en silence
    rendrait vert un système qui n'a jamais tourné.
    """
    if not only:
        return [dict(e) for e in MATRICE]
    connus = {cle(e): e for e in MATRICE}
    refuses = {cle(e): e["raison"] for e in NON_SUPPORTES}
    choisis = []
    for brut in only.split(","):
        k = brut.strip()
        if not k:
            continue
        if k in refuses:
            raise ValueError(f"{k} : UNSUPPORTED ({refuses[k]})")
        if k not in connus:
            raise ValueError(
                f"{k} : inconnu. Clés possibles : {', '.join(connus)}"
            )
        if all(cle(e) != k for e in choisis):
            choisis.append(dict(connus[k]))
    if not choisis:
        raise ValueError("--only ne nomme aucun système")
    return choisis


_ETAT = re.compile(r"'state': <(-?\d+(?:\.\d+)?)>")
_ERREUR = re.compile(
    r"""'error': <(?:'((?:[^'\\]|\\.)*)'|"((?:[^"\\]|\\.)*)")>"""
)


def analyser_extension_info(sortie):
    """{"state": float|None, "error": str} lus dans la sortie de gdbus.

    `GetExtensionInfo` rend un a{sv} au format texte de GVariant :
    « ({'uuid': <'…'>, 'state': <1.0>, 'error': <''>, …},) ». Une extension
    inconnue de GNOME Shell rend le dictionnaire vide « (@a{sv} {},) », lu
    comme state None. GVariant cite une chaîne entre apostrophes, ou entre
    guillemets quand elle contient une apostrophe ; les deux sont lus, et
    leurs échappements défaits.
    """
    texte = sortie or ""
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


def est_active(info):
    """ACTIVE : état 1 et erreur vide. Toute autre forme est un échec."""
    return bool(info) and info.get("state") == 1 and info.get("error") == ""


_MONTAGE_ECHOUE = re.compile(r"\[ERPLibreHome\] mount (\S+) failed")


def indicateurs_en_echec(sortie):
    """Les ids des indicateurs non montés, triés et sans doublon.

    Lus dans les lignes « [ERPLibreHome] mount <id> failed: <message> »
    de la sortie de CMD_MONTAGES ; un indicateur réactivé qui échoue de
    nouveau n'apparaît qu'une fois. Une sortie vide ou None rend [].
    """
    return sorted(set(_MONTAGE_ECHOUE.findall(sortie or "")))


def journal_lu(sortie):
    """Vrai quand la sortie de CMD_MONTAGES porte la ligne
    « [ERPLibreHome] enabled » qui clôt enable().

    C'est la preuve que le journal de la session a été lu : sans elle, une
    sortie sans « mount <id> failed » ne dit rien des indicateurs.
    """
    return any(
        ligne.strip().endswith("[ERPLibreHome] enabled")
        for ligne in (sortie or "").splitlines()
    )


_NOM_UTILISATEUR = re.compile(r"^[a-z_][a-z0-9_-]*$")

# Le programme awk de GDM : il retire toute ligne AutomaticLogin* existante,
# puis pose les deux clés juste sous « [daemon] », ou ajoute la section à la
# fin quand le fichier n'en a pas. Le rejouer rend le même fichier.
_AWK_GDM = (
    "/^[ \\t]*AutomaticLogin(Enable)?[ \\t]*=/ {next} "
    "{print} "
    "/^[ \\t]*\\[daemon\\][ \\t]*$/ && !fait "
    '{print "AutomaticLoginEnable=true"; print "AutomaticLogin=" u; fait=1} '
    'END {if (!fait) {print "[daemon]"; '
    'print "AutomaticLoginEnable=true"; print "AutomaticLogin=" u}}'
)
# Celui d'openSUSE : la clé sysconfig, retirée puis posée en dernière ligne.
_AWK_SUSE = (
    "/^DISPLAYMANAGER_AUTOLOGIN=/ {next} {print} "
    'END {print "DISPLAYMANAGER_AUTOLOGIN=\\"" u "\\""}'
)


def autologin(famille, user):
    """(chemin, commande shell) qui ouvre la session de `user` au démarrage.

    awk et non sed ni crudini : awk est dans l'image de base des quatre
    familles, crudini dans aucune, et une réécriture par awk rend le même
    fichier qu'on la joue une fois ou deux. Le résultat passe par un fichier
    temporaire puis « sudo tee », qui réécrit le fichier EN PLACE et garde
    son inode, donc son contexte SELinux. La commande rend 0 si et seulement
    si l'écriture a abouti.
    """
    if famille not in FICHIER_AUTOLOGIN:
        raise ValueError(f"famille inconnue : {famille}")
    if not _NOM_UTILISATEUR.match(user or ""):
        raise ValueError(f"nom d'utilisateur refusé : {user!r}")
    chemin = FICHIER_AUTOLOGIN[famille]
    programme = _AWK_SUSE if famille == "suse" else _AWK_GDM
    commande = (
        f"f={chemin}; t=$(mktemp) && "
        'sudo mkdir -p "$(dirname "$f")" && sudo touch "$f" && '
        f'sudo awk -v u={user} {shlex.quote(programme)} "$f" > "$t" && '
        'sudo tee "$f" < "$t" > /dev/null; '
        'rc=$?; rm -f "$t"; [ "$rc" -eq 0 ]'
    )
    return chemin, commande


def version_gnome(sortie):
    """« 46.0 » lu dans « GNOME Shell 46.0 », ou ""."""
    trouve = re.search(r"GNOME Shell (\d+(?:\.[0-9A-Za-z.]+)?)", sortie or "")
    return trouve.group(1) if trouve else ""


def majeur(version):
    """« 46 » pour « 46.0 », « » pour une version vide."""
    return (version or "").split(".")[0]


def raison_non_supportee(sortie):
    """La raison de la DERNIÈRE ligne « UNSUPPORTED: », ou ""."""
    raison = ""
    for ligne in (sortie or "").splitlines():
        if ligne.startswith("UNSUPPORTED:"):
            raison = ligne[len("UNSUPPORTED:") :].strip()
    return raison


def nom_vm(entree, horodatage):
    """Le nom de domaine libvirt : la base, le système, l'horodatage.

    `horodatage` est celui de la course (Course.horodatage) : deux courses
    ne nomment jamais la même VM, et une VM gardée par l'une ne porte pas le
    nom d'une VM que l'autre crée puis détruit.

    Réduit à [a-z0-9-] : il sert aussi d'alias ssh, et un point de « 24.04 »
    y serait pris pour un nom de domaine DNS.
    """
    brut = f"{NOM_BASE}-{entree['distro']}-{entree['version']}".lower()
    return re.sub(r"[^a-z0-9-]+", "-", brut) + f"-{horodatage}"


def argv_creation(entree, nom, cle_pub="", drapeaux=()):
    """La ligne de deploy_qemu.py pour une VM de la matrice, sans « sudo »."""
    argv = [
        os.path.join(RACINE, ".venv.erplibre/bin/python"),
        os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
        "--distro",
        entree["distro"],
        "--version",
        entree["version"],
        "--name",
        nom,
        "--desktop",
        "--gpu",
        "off",
        "--vcpus",
        str(VCPUS),
        "--memory",
        str(MEMOIRE_MO),
        "--disk-size",
        f"{DISQUE_GO}G",
    ]
    if cle_pub:
        argv += ["--ssh-key", cle_pub]
    return argv + list(drapeaux)


def verdict_systeme(
    entree,
    code_install,
    info,
    gnome_mesure,
    *,
    echec=None,
    raison="",
    duree_s=0,
    journal=None,
):
    """La ligne du rapport d'un système de la matrice.

    `code_install` : le code de sortie de l'installation de la base, ou
    None quand elle n'a pas été lancée ou n'a pas rendu de code. `echec` : le
    nom de la première étape tombée, dans l'ordre du test (vm, ssh, desktop,
    code, autologin, puis les commandes et contrôles d'ETAPES). `raison` : la
    ligne « UNSUPPORTED: » de l'installateur. L'ordre des branches est
    celui des étapes : un échec avant l'installation l'emporte sur tout le
    reste, un code 2 rend UNSUPPORTED, et le verdict ACTIVE exige
    `est_active(info)` : la dernière lecture, celle de la cinquième étape.
    """
    ligne = {
        "distro": entree["distro"],
        "version": entree["version"],
        "gnome_attendu": entree.get("gnome_attendu"),
        "gnome_mesure": gnome_mesure or None,
        "verdict": "ACTIVE",
        "etape": None,
        "duree_s": int(duree_s),
        "journal": journal,
    }
    if code_install is None:
        ligne.update(verdict="FAILED", etape=echec or "install")
    elif code_install == 2:
        ligne.update(verdict="UNSUPPORTED", etape=raison or "install exit 2")
    elif code_install != 0:
        ligne.update(verdict="FAILED", etape="install")
    elif echec:
        ligne.update(verdict="FAILED", etape=echec)
    elif not est_active(info):
        ligne.update(verdict="FAILED", etape="extension-active")
    return ligne


def ligne_non_supportee(entree):
    """La ligne du rapport d'un système hors champ : aucune VM, sa raison."""
    return {
        "distro": entree["distro"],
        "version": entree["version"],
        "gnome_attendu": None,
        "gnome_mesure": None,
        "verdict": "UNSUPPORTED",
        "etape": entree["raison"],
        "duree_s": 0,
        "journal": None,
    }


def code_sortie(systemes):
    """0 quand chaque système de la matrice est ACTIVE, ou UNSUPPORTED là où
    la matrice le permet (une distribution roulante) ; 1 sinon.

    Les lignes hors matrice — NON_SUPPORTES — ne comptent pas : elles n'ont
    jamais eu de VM.
    """
    roulantes = {cle(e): e["roulante"] for e in MATRICE}
    for ligne in systemes:
        k = cle(ligne)
        if k not in roulantes:
            continue
        if ligne["verdict"] == "ACTIVE":
            continue
        if ligne["verdict"] == "UNSUPPORTED" and roulantes[k]:
            continue
        return 1
    return 0


def resume(systemes):
    """Le tableau de fin de course, une chaîne par ligne.

    « ≠ » marque un GNOME mesuré dont la version majeure n'est pas celle de
    la matrice : la colonne est à corriger.
    """
    lignes = [f"  {'système':<22} {'GNOME':<14} verdict"]
    for s in systemes:
        attendu = s.get("gnome_attendu") or "—"
        mesure = s.get("gnome_mesure") or "—"
        ecart = (
            " ≠" if s.get("gnome_mesure") and majeur(mesure) != attendu else ""
        )
        detail = s["verdict"] + (f"({s['etape']})" if s.get("etape") else "")
        gnome = f"{attendu} → {mesure}{ecart}"
        lignes.append(f"  {cle(s):<22} {gnome:<14} {detail}")
    return lignes


def arbre_propre(racine):
    """Vrai quand aucun fichier SUIVI n'est modifié ni indexé sous `racine`.

    Les fichiers non suivis ne comptent pas : ils ne sont ni dans HEAD ni
    dans le bundle, donc ne changent rien à ce que la VM reçoit. Un dossier
    qui n'est pas un dépôt, ou un git qui ne répond pas, rend Faux.
    """
    try:
        fini = subprocess.run(
            [
                "git",
                "-C",
                racine,
                "status",
                "--porcelain",
                "--untracked-files=no",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return fini.returncode == 0 and not fini.stdout.strip()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
.venv.erplibre/bin/ruff check --select I --fix long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py
.venv.erplibre/bin/ruff format long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py
python3 script/analyse/check_comment_hygiene.py long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py
.venv.erplibre/bin/python -m unittest test.test_longtest_install_erplibre_home -v
.venv.erplibre/bin/python -m unittest test.test_todo_longtest test.test_longtest_install_nixos
```
Expected:
- ruff reports `All checks passed!` and leaves both files unchanged.
- The hygiene check prints no 🔴 line.
- `Ran 68 tests … OK`.
- Both existing suites stay `OK`.

- [ ] **Step 5: Commit**

```bash
git add long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py
cat > $SCRATCH/msg_task8.txt <<'EOF'
[ADD] long_test: ERPLibre Home matrix, GNOME verdict, autologin helpers

The ERPLibre Home long test needs pure parts that run without a VM: the
support matrix, the parsers of GetExtensionInfo, enabled-extensions and
failed indicator mounts, the per-family GDM autologin, the five stages
each VM goes through with their unique command and check names, the
verdict of one system and the exit code of a run. ACTIVE requires state 1
and an empty error. A rolling distribution may report UNSUPPORTED without
failing the run.
Checked: test_longtest_install_erplibre_home, autologin on real files.

--- FR ---

[ADD] long_test : matrice ERPLibre Home, verdict GNOME et autologin

Le test long d'ERPLibre Home a besoin de parties pures qui tournent sans
VM : la matrice de support, la lecture de GetExtensionInfo,
d'enabled-extensions et des indicateurs non montés, l'autologin GDM par
famille, les cinq étapes de chaque VM et leurs noms uniques de commande et
de contrôle, le verdict d'un système et le code de sortie d'une course.
ACTIVE exige l'état 1 et une erreur vide. Une distribution roulante peut
rendre UNSUPPORTED sans faire échouer la course.
Vérifié : test_longtest_install_erplibre_home, autologin sur vrais fichiers.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task8.txt
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task8.txt
```

---

### Task 9: Long test runner, menu and README

**Files:**
- Modify: `long_test/install_erplibre_home.py` (the import block, lines 36-42 after Task 8; then append the runner after `arbre_propre`), and make it executable
- Modify: `long_test/descente.py:40-45` (`SCRIPTS`)
- Modify: `script/todo/longtest_menu.py:29-34` (`SCRIPTS_DEFAISABLES`), `:129-130` (choices), `:139-140` (dispatch tables), `:158-160` (dispatch), `:177-178` (undo, renumbered)
- Modify: `script/todo/todo_i18n.py:6075-6078` (insert after the `"Use a NixOS machine you already have"` entry)
- Modify: `long_test/README.base.md:246` and `:524` (insert before `## Starting from a host you already have` and before `## Partir d'un hôte qu'on possède déjà`), then regenerate `long_test/README.md` and `long_test/README.fr.md`
- Test: `test/test_longtest_install_erplibre_home.py` (append)

**Interfaces:**
- Consumes:
  - Task 8 helpers, among them `CMD_MONTAGES`, `indicateurs_en_echec(sortie)` and `journal_lu(sortie)` for the `extension-indicators` and `reinstall-indicators` checks; `ETAPES`, `OPTION` and `decrire_etapes()` for the five stages; `CMD_UDEV`, `CMD_VENV`, `CMD_SANS_REGLE`, `CMD_SANS_VENV`, `CMD_LIEN`, `CMD_SANS_LIEN`, `CMD_MTIME_LIEN`, `CMD_MTIMES`, `CMD_ENABLED` and `liste_extensions(sortie)` for their checks.
  - From `descente`: `Descente.uuid_libvirt`, `Famille`, `capacite_hote`, `cle_publique()` (returns the path of `~/.ssh/id_ed25519.pub` or `id_rsa.pub`, or `""`), `detruire` (the Task 7 version, which undoes every `niveau == 1` entry), `detruire_etage1(journal, nom, dry_run=False, attendu=None, cree=True)`, `dire`, `drapeaux_cache`, `retirer_alias(rapport, journal, nom_base)`.
  - From `TODO.__new__(TODO)`: `_qemu_erplibre_remote_cmd(None, desktop="gnome")`, `_qemu_vm_ip(name, timeout)`, `_write_ssh_config_entry([name], user, ip, identity_file=)`.
  - `script/install/install_erplibre_home.sh` (Tasks 3-4): no option (the base), `--with-extras`, `--stream-deck`, `--uninstall --stream-deck`, `--uninstall`, exit 0/1/2, and a stderr line starting with `UNSUPPORTED:`.
- Produces:
  - Script flags: `--only --extras --dry-run --garder --detruire`, and `--detruire --dry-run`.
  - Report `~/.erplibre/longtest/long-sd-<stamp>.json` with `{"outil": "install_erplibre_home", "dry_run", "pid", "head", "etages": [niveau-1 entries], "systemes": [lines]}`.
  - Per-system logs and the bundle go in `~/.erplibre/longtest/long-sd-<stamp>/`.
  - VM names `long-sd-<distro>-<version>-<stamp>`, `<stamp>` being the run's own `%Y%m%d-%H%M%S` (`Course.horodatage`), so two runs never share a name. `creer_vm` refuses a name libvirt already defines: such a VM is never written to the report, so this run never destroys it.
  - Menu: choices 10 (plan) and 11 (run). Undo is renumbered to 12.
  - `installer(cible, log, options="") -> (code, sortie)`: the installer in the VM's checkout with `options` (`""` for the base, `"--with-extras"`, or an `OPTION[...]` value); command and output go to the system's log.
  - `attendre_extension(cible, log, delai=DELAIS_CONTROLE["extension-active"])`.
  - `controler(cible, entree, log, extras=False) -> (echec, info, gnome)`: the five stages of `ETAPES` in order, after the base install of `mener_un` (spec 6.2 step 5) and the autologin reboot. `echec` is the first failed command or check name, or `None`; `info` is the last `GetExtensionInfo` read (stage 5's when all pass). With `extras`, every base install of the stages (`base-idempotent`, `reinstall`) also runs `--with-extras`. Stage 5 reboots through `redemarrer`.
  - The dry run prints the five lines of `decrire_etapes()` after the systems.

- [ ] **Step 1: Write the failing tests**

In `test/test_longtest_install_erplibre_home.py`, change the import block from

```python
import configparser
import json
import os
import shutil
```

to

```python
import configparser
import contextlib
import io
import json
import os
import re
import shutil
```

Then insert the following just before the final `if __name__ == "__main__":` block. That block must stay last.

`_mener` runs the script in the test's own process, with `HOME` and `descente.autre_descente` patched. A live `install_erplibre_home.py` subprocess is, for the other descent tests that the unit runner runs in parallel, a descent in progress, and their `--detruire` then refuses to work; the lock between descents is not what these tests check. `VMSimulee` stands for a VM through the five stages: its `installer` applies what each option must do, then `apres[option]` to simulate a faulty installer.

```python
SCRIPT = RACINE / "long_test/install_erplibre_home.py"
SRC = SCRIPT.read_text(encoding="utf-8")


def _mener(*args, maison):
    """Le script mené dans ce processus, sur un HOME qui ne contient rien.
    Rend (code, sortie).

    Pas de sous-processus : un install_erplibre_home.py vivant est, pour les
    tests des autres descentes que le lanceur unitaire passe en parallèle,
    une descente en cours, et leur « --detruire » refuse alors de
    travailler. Le verrou entre descentes n'est pas le sujet de ces tests :
    autre_descente n'y voit rien.
    """
    from unittest import mock

    import descente

    sortie = io.StringIO()
    with (
        mock.patch.dict(os.environ, {"HOME": maison}),
        mock.patch.object(descente, "autre_descente", lambda: []),
        contextlib.redirect_stdout(sortie),
    ):
        code = sd.mener(list(args))
    return code, sortie.getvalue()


class LeScript(unittest.TestCase):
    def test_it_is_executable(self):
        """Le menu et le README l'appellent directement."""
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_the_desktop_comes_from_the_menu(self):
        """Deux copies d'une installation de bureau divergent, et c'est
        celle du test qui reste verte."""
        self.assertIn('_qemu_erplibre_remote_cmd(None, desktop="gnome")', SRC)

    def test_the_cache_flags_reach_the_creation(self):
        self.assertIn("drapeaux_cache()", SRC)

    def test_the_report_carries_the_pid_of_its_run(self):
        self.assertIn('"pid": os.getpid()', SRC)
        self.assertIn('"outil": OUTIL', SRC)

    def test_vms_are_destroyed_in_process_without_a_prompt(self):
        """detruire() demande « OUI » : entre deux systèmes, la course
        n'attend personne. Il ne sert qu'à --detruire."""
        self.assertEqual(SRC.count("detruire(famille"), 1)
        self.assertLess(
            SRC.index("if args.detruire:"), SRC.index("detruire(famille")
        )
        corps = SRC.split("for entree in systemes:\n        try:")[1]
        self.assertIn("detruire_etage1(", corps)
        self.assertIn("retirer_alias(", corps)

    def test_every_bounded_call_is_caught(self):
        """Un test lancé pour des heures rend un VERDICT, pas une trace :
        chaque subprocess.run borné vit dans un « try »."""
        import ast

        arbre = ast.parse(SRC)
        bornes = [
            n.lineno
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and ast.unparse(n.func) == "subprocess.run"
            and any(m.arg == "timeout" for m in n.keywords)
        ]
        self.assertGreaterEqual(len(bornes), 8)
        couvertes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Try):
                for corps in noeud.body:
                    for interne in ast.walk(corps):
                        if hasattr(interne, "lineno"):
                            couvertes.add(interne.lineno)
        for ligne in bornes:
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, couvertes)


class LEssaiABlanc(unittest.TestCase):
    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-blanc-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)

    def _rapports(self):
        dossier = os.path.join(self.maison, ".erplibre/longtest")
        return sorted(f for f in os.listdir(dossier) if f.endswith(".json"))

    def test_the_whole_plan_creates_nothing(self):
        code, sortie = _mener("--dry-run", maison=self.maison)
        self.assertEqual(0, code, sortie)
        self.assertIn("--dry-run", sortie)
        for entree in sd.MATRICE:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(sd.cle(entree), sortie)
                self.assertIn(
                    f"--distro {entree['distro']} --version"
                    f" {entree['version']}",
                    sortie,
                )
        for entree in sd.NON_SUPPORTES:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(f"UNSUPPORTED : {entree['raison']}", sortie)
        for attendu in (
            "--desktop --gpu off --vcpus 2 --memory 4096 --disk-size 26G",
            "ppc64le",
        ):
            self.assertIn(attendu, sortie)
        # Les cinq étapes de chaque VM, leurs commandes et leurs contrôles.
        for ligne in sd.decrire_etapes():
            self.assertIn(ligne, sortie)
        for option in ("--stream-deck", "--uninstall --stream-deck"):
            self.assertIn("install_erplibre_home.sh " + option, sortie)
        # Un essai qui n'écrit rien n'a aucune raison de demander sudo.
        self.assertNotIn("sudo", sortie)
        # Un rapport d'essai, nommé à part : dernier_rapport l'écarte.
        rapports = self._rapports()
        self.assertEqual(len(rapports), 1)
        self.assertTrue(rapports[0].endswith("-dryrun.json"))

    def test_the_report_holds_the_unsupported_lines(self):
        _mener("--dry-run", maison=self.maison)
        chemin = os.path.join(
            self.maison, ".erplibre/longtest", self._rapports()[0]
        )
        with open(chemin, encoding="utf-8") as fh:
            rapport = json.load(fh)
        self.assertEqual(rapport["outil"], "install_erplibre_home")
        self.assertTrue(rapport["dry_run"])
        self.assertEqual(rapport["etages"], [])
        self.assertEqual(
            [s["verdict"] for s in rapport["systemes"]],
            ["UNSUPPORTED"] * len(sd.NON_SUPPORTES),
        )

    def test_only_restricts_the_plan(self):
        code, sortie = _mener(
            "--dry-run", "--only", "fedora:43", "--extras", maison=self.maison
        )
        self.assertEqual(0, code, sortie)
        self.assertIn("--distro fedora --version 43", sortie)
        self.assertNotIn("--distro ubuntu", sortie)
        # Les hors-champ ne sont annoncés que pour la matrice entière.
        self.assertNotIn("debian:12", sortie)
        self.assertIn("--extras ne vaut que pour ubuntu:24.04", sortie)

    def test_an_unsupported_key_is_refused_with_its_reason(self):
        code, sortie = _mener(
            "--dry-run", "--only", "debian:12", maison=self.maison
        )
        self.assertEqual(1, code)
        self.assertIn("GNOME 43 < 45", sortie)


class LArbreModifieEstRefuse(unittest.TestCase):
    """La VM reçoit HEAD : un fichier suivi et modifié ne serait pas dans la
    VM, et le verdict porterait sur autre chose que ce qu'on lit."""

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-sale-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.addCleanup(os.environ.__setitem__, "HOME", os.environ["HOME"])
        os.environ["HOME"] = self.maison
        for nom in ("arbre_propre", "plan_tient", "creer_bundle", "creer_vm"):
            self.addCleanup(setattr, sd, nom, getattr(sd, nom))

    def test_a_dirty_tree_stops_before_anything(self):
        sd.arbre_propre = lambda racine: False
        sd.plan_tient = lambda journal: self.fail("plan_tient appelé")
        sd.creer_bundle = lambda *a: self.fail("bundle créé")
        sd.creer_vm = lambda *a, **k: self.fail("VM créée")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertEqual(1, sd.mener(["--only", "ubuntu:24.04"]))
        self.assertIn("fichiers suivis sont modifiés", sortie.getvalue())

    def test_the_dry_run_only_warns(self):
        sd.arbre_propre = lambda racine: False
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertEqual(
                0, sd.mener(["--dry-run", "--only", "ubuntu:24.04"])
            )
        self.assertIn("la course réelle refusera", sortie.getvalue())


class LeDefaire(unittest.TestCase):
    """La forme du rapport est le CONTRAT du défaire partagé : chaque VM
    gardée par --garder, ou laissée par une course tuée, y est une entrée de
    niveau 1, et --detruire les reprend toutes."""

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-defaire-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)

    def _etage(self, nom):
        return {
            "niveau": 1,
            "nom": nom,
            "uuid": "",
            "alias": nom,
            "cree": True,
        }

    def test_every_kept_vm_is_named(self):
        rapport = {
            "outil": "install_erplibre_home",
            "dry_run": False,
            "pid": 1,
            "etages": [
                self._etage("long-sd-ubuntu-24-04-000000"),
                self._etage("long-sd-fedora-43-000000"),
            ],
            "systemes": [],
        }
        with open(
            os.path.join(self.dossier, "long-sd-19990101-000000.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(rapport, fh)
        # Les journaux par système vivent dans un sous-dossier : jamais pris
        # pour un rapport.
        os.makedirs(os.path.join(self.dossier, "long-sd-19990101-000000"))
        code, sortie = _mener("--detruire", "--dry-run", maison=self.maison)
        self.assertEqual(0, code, sortie)
        self.assertIn("long-sd-ubuntu-24-04-000000", sortie)
        self.assertIn("long-sd-fedora-43-000000", sortie)
        self.assertIn("rien ne sera détruit", sortie)

    def test_another_tools_report_is_left_alone(self):
        with open(
            os.path.join(self.dossier, "long-nixos-19990101-000000.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(
                {
                    "outil": "install_nixos",
                    "dry_run": False,
                    "pid": 1,
                    "etages": [self._etage("long-nixos-000000")],
                },
                fh,
            )
        _code, sortie = _mener("--detruire", "--dry-run", maison=self.maison)
        self.assertIn("rien à défaire", sortie)
        self.assertNotIn("long-nixos-000000", sortie)


class LeVerrouEtLeMenu(unittest.TestCase):
    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)

    def test_it_shares_the_lock_and_the_undo(self):
        import descente

        from script.todo.longtest_menu import SCRIPTS_DEFAISABLES

        self.assertIn("install_erplibre_home.py", descente.SCRIPTS)
        self.assertIn("install_erplibre_home.py", SCRIPTS_DEFAISABLES)

    def test_the_menu_dispatches_plan_run_and_undo(self):
        """10 : le plan, 11 : la course, 12 : le défaire. Aucun ne passe
        « --depth » : il n'y a pas d'étages ici."""
        from unittest import mock

        vus = []
        self.todo.fill_help_info = lambda choix: ""
        self.todo._longtest_run = lambda nom, args="", demander=None: (
            vus.append((nom, args))
        )
        self.todo._longtest_defaire = lambda: vus.append("défaire")
        with mock.patch(
            "script.todo.longtest_menu.click.prompt",
            side_effect=["10", "11", "12", "0"],
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.todo.prompt_execute_longtest()
        self.assertEqual(
            vus,
            [
                ("install_erplibre_home.py", "--dry-run"),
                ("install_erplibre_home.py", ""),
                "défaire",
            ],
        )

    def test_every_label_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for cle in (
            "ERPLibre Home on every distribution: plan only (dry-run)",
            "ERPLibre Home on every distribution: run it",
        ):
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))


class DeuxCoursesDeSuite(unittest.TestCase):
    """Une course gardée par --garder, puis une autre : leurs VM ne portent
    jamais le même nom, et chaque course ne détruit que les VM que son
    propre rapport nomme."""

    PREMIERE = "long-sd-19990101-000000"

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-suite-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.addCleanup(os.environ.__setitem__, "HOME", os.environ["HOME"])
        os.environ["HOME"] = self.maison
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)

    def _course(self, nom):
        from unittest import mock

        dossier = os.path.join(self.dossier, nom)
        return sd.Course(mock.Mock(dry_run=False), dossier + ".log", dossier)

    def test_two_run_stamps_never_share_a_vm_name(self):
        systemes = sd.plan()
        premiere = {sd.nom_vm(e, "19990101-000000") for e in systemes}
        seconde = {sd.nom_vm(e, "19990101-000001") for e in systemes}
        self.assertEqual(len(premiere), len(systemes))
        self.assertFalse(premiere & seconde)

    def test_the_run_stamp_is_in_every_vm_name(self):
        course = self._course(self.PREMIERE)
        self.assertEqual(course.horodatage, "19990101-000000")
        self.assertTrue(
            sd.nom_vm(sd.MATRICE[0], course.horodatage).endswith(
                "-19990101-000000"
            )
        )

    def test_a_name_libvirt_already_defines_never_enters_the_report(self):
        """La VM d'une autre course porte ce nom : rien n'est créé, rien
        n'est inscrit, donc rien de ce qu'elle est ne sera détruit."""
        from unittest import mock

        course = self._course(self.PREMIERE)
        with (
            mock.patch.object(
                sd.Descente, "uuid_libvirt", return_value="u-ancienne"
            ),
            mock.patch.object(
                sd.subprocess,
                "run",
                side_effect=AssertionError("deploy_qemu.py lancé"),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            ligne = sd.mener_un(course, sd.MATRICE[0])
        self.assertEqual(course.rapport["etages"], [])
        self.assertEqual((ligne["verdict"], ligne["etape"]), ("FAILED", "vm"))

    def test_the_run_destroys_only_what_its_report_names(self):
        from unittest import mock

        # La VM qu'une course précédente a gardée, dans son propre rapport.
        gardee = "long-sd-ubuntu-24-04-19990101-000000"
        with open(
            os.path.join(self.dossier, self.PREMIERE + ".json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(
                {
                    "outil": "install_erplibre_home",
                    "dry_run": False,
                    "pid": 1,
                    "etages": [
                        {
                            "niveau": 1,
                            "nom": gardee,
                            "uuid": "u-gardee",
                            "alias": gardee,
                            "cree": True,
                        }
                    ],
                    "systemes": [],
                },
                fh,
            )
        inscrites, detruites = [], []

        def mener_un(course, entree):
            nom = sd.nom_vm(entree, course.horodatage)
            etage = {
                "niveau": 1,
                "nom": nom,
                "uuid": "u-" + nom,
                "alias": nom,
                "cree": True,
            }
            course.inscrire(etage)
            inscrites.append(etage)
            return sd.verdict_systeme(entree, None, None, "", echec="session")

        def detruire_etage1(journal, nom, dry_run=False, attendu=None, **k):
            detruites.append((nom, attendu))
            return True

        with (
            mock.patch.multiple(
                sd,
                arbre_propre=lambda racine: True,
                plan_tient=lambda journal: True,
                creer_bundle=lambda dossier, journal: ("0" * 40, "x.bundle"),
                mener_un=mener_un,
                detruire_etage1=detruire_etage1,
                retirer_alias=lambda *a, **k: None,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            sd.mener(["--only", "ubuntu:24.04,fedora:43"])
        self.assertEqual(len(inscrites), 2)
        self.assertNotIn(gardee, [e["nom"] for e in inscrites])
        self.assertEqual(detruites, [(e["nom"], e["uuid"]) for e in inscrites])


class VMSimulee:
    """Une VM réduite à ce que les étapes lisent et changent : la règle
    udev, le venv, le lien de l'extension, son UUID dans enabled-extensions,
    son état ACTIVE, et les lectures successives du journal de session.

    L'installateur simulé applique ce que chaque option doit faire, puis
    `apres[option]`, qui simule une installation fautive ; `echoue` nomme les
    options qui rendent 1. Elle part de l'état que laisse l'installation de
    la base à l'étape 5 du flux.
    """

    def __init__(self, journaux, echoue=(), apres=None, **etat):
        self.regle = self.venv = False
        self.lien = self.uuid = self.actif = True
        self.__dict__.update(etat)
        self.journaux = list(journaux)
        self.echoue = set(echoue)
        self.apres = apres or {}
        self.options = []
        self.lectures = 0
        self.redemarrages = 0

    def installer(self, cible, log, options=""):
        self.options.append(options)
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

    def sonder(self, cible, commande, delai=180):
        if commande == sd.CMD_MONTAGES:
            self.lectures += 1
            return self.journaux.pop(0)
        reponses = {
            "gnome-shell --version": "GNOME Shell 46.0",
            sd.CMD_SANS_REGLE: "" if self.regle else "ok",
            sd.CMD_SANS_VENV: "" if self.venv else "ok",
            sd.CMD_UDEV: "ok" if self.regle else "",
            sd.CMD_VENV: "ok" if self.venv else "",
            sd.CMD_LIEN: "ok" if self.lien else "",
            sd.CMD_SANS_LIEN: "" if self.lien else "ok",
            sd.CMD_ENABLED: (
                f"['{sd.UUID_EXTENSION}']" if self.uuid else "@as []"
            ),
            sd.CMD_MTIMES: "dates du deck",
            sd.CMD_MTIME_LIEN: "date du lien",
        }
        # Le reste : ListPaths et ListDevices.
        return reponses.get(commande, "('[]',)")

    def attendre_extension(self, cible, log, delai=0):
        if self.actif:
            return {"state": 1.0, "error": ""}
        return {"state": 3.0, "error": "boom"}

    def redemarrer(self, cible, log):
        self.redemarrages += 1
        self.__dict__.update(self.apres.get("redemarrage", {}))
        return True


class LesCinqEtapes(unittest.TestCase):
    """controler() mène les cinq étapes sur une VM simulée : l'ordre des
    commandes, et le nom que chaque faute laisse au rapport."""

    ENTIER = "[ERPLibreHome] enabled\n"
    ECHEC = (
        "[ERPLibreHome] mount device failed:"
        " No property vertical on StBoxLayout\n"
        "[ERPLibreHome] enabled\n"
    )

    def setUp(self):
        dossier = tempfile.mkdtemp(prefix="sd-etapes-")
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        self.log = os.path.join(dossier, "systeme.log")

    def _controler(self, vm, extras=False):
        from unittest import mock

        with mock.patch.multiple(
            sd,
            sonder=vm.sonder,
            session_ouverte=lambda cible: True,
            attendre_extension=vm.attendre_extension,
            installer=vm.installer,
            redemarrer=vm.redemarrer,
        ):
            return sd.controler("vm", sd.MATRICE[0], self.log, extras)

    def _journal(self):
        with open(self.log, encoding="utf-8") as fh:
            return fh.read()

    def test_a_sound_vm_passes_the_five_stages_in_order(self):
        vm = VMSimulee([self.ENTIER, self.ENTIER])
        echec, info, gnome = self._controler(vm)
        self.assertIsNone(echec)
        self.assertTrue(sd.est_active(info))
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

    def test_extras_go_with_every_base_install(self):
        vm = VMSimulee([self.ENTIER, self.ENTIER])
        echec, _info, _gnome = self._controler(vm, extras=True)
        self.assertIsNone(echec)
        self.assertEqual(vm.options[0], "--with-extras")
        self.assertEqual(vm.options[-1], "--with-extras")

    def test_a_failed_mount_stops_the_base_stage(self):
        vm = VMSimulee([self.ECHEC])
        echec, info, _gnome = self._controler(vm)
        self.assertEqual(echec, "extension-indicators")
        self.assertTrue(sd.est_active(info))
        self.assertEqual(vm.options, [])
        self.assertIn("indicateurs non montés : device", self._journal())

    def test_an_unread_journal_is_not_a_whole_panel(self):
        """Une lecture vide — ssh tombé, journal vide — ne passe pas pour
        « aucun échec »."""
        echec, _info, _gnome = self._controler(VMSimulee([""]))
        self.assertEqual(echec, "extension-indicators")
        self.assertIn("journal de session sans", self._journal())

    def test_the_base_must_leave_no_rule_nor_venv(self):
        for etat, attendu in (
            ({"regle": True}, "base-no-udev"),
            ({"venv": True}, "base-no-venv"),
        ):
            with self.subTest(attendu=attendu):
                vm = VMSimulee([self.ENTIER], **etat)
                self.assertEqual(self._controler(vm)[0], attendu)

    def test_a_failed_command_names_its_stage(self):
        for option, attendu in (
            ("", "base-idempotent"),
            ("--stream-deck", "install-stream-deck"),
            ("--uninstall --stream-deck", "uninstall-stream-deck"),
            ("--uninstall", "uninstall"),
        ):
            with self.subTest(attendu=attendu):
                vm = VMSimulee([self.ENTIER], echoue={option})
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
        ):
            with self.subTest(apres=apres):
                vm = VMSimulee(
                    [self.ENTIER],
                    apres={"--uninstall --stream-deck": apres},
                )
                self.assertEqual(self._controler(vm)[0], attendu)

    def test_the_uninstall_leaves_nothing(self):
        for apres in ({"uuid": True}, {"lien": True}, {"venv": True}):
            with self.subTest(apres=apres):
                vm = VMSimulee([self.ENTIER], apres={"--uninstall": apres})
                self.assertEqual(self._controler(vm)[0], "uninstall-gone")

    def test_the_reinstall_comes_back_whole_and_without_the_deck(self):
        cas = (
            (VMSimulee([self.ENTIER, self.ECHEC]), "reinstall-indicators"),
            (
                VMSimulee(
                    [self.ENTIER], apres={"redemarrage": {"actif": False}}
                ),
                "reinstall-active",
            ),
            (
                VMSimulee(
                    [self.ENTIER, self.ENTIER], apres={"": {"regle": True}}
                ),
                "reinstall-no-udev",
            ),
        )
        for vm, attendu in cas:
            with self.subTest(attendu=attendu):
                self.assertEqual(self._controler(vm)[0], attendu)
                self.assertEqual(vm.redemarrages, 1)

    def test_every_name_it_returns_is_declared(self):
        """Les noms que controler() rend sont ceux d'ETAPES : le rapport et
        la spec parlent la même langue."""
        declares = set()
        for etape in sd.ETAPES:
            declares.update(etape["controles"])
            if etape["commande"]:
                declares.add(etape["commande"])
        source = SRC[SRC.index("def _absents(") : SRC.index("def controler(")]
        rendus = set(re.findall(r'return "([a-z-]+)"', source))
        self.assertEqual(rendus, declares)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv.erplibre/bin/python -m unittest test.test_longtest_install_erplibre_home`
Expected: FAIL, `Ran 100 tests`, `FAILED (failures=10, errors=36)` (counted per subtest), with:
- `AttributeError: module 'install_erplibre_home' has no attribute 'mener'` (the dry-run, undo and dirty-tree tests, now run in-process), `… 'plan_tient'`, `… 'Course'`
- `AssertionError: False is not true` (not executable), and the source checks (`drapeaux_cache()`, `"pid": os.getpid()`, the menu's desktop command, the in-process destroy, at least 8 bounded calls)
- `AssertionError: 'install_erplibre_home.py' not found in (...)` (lock), the menu dispatch and the two untranslated labels
- `DeuxCoursesDeSuite`: errors for the three tests that build a run; `test_two_run_stamps_never_share_a_vm_name` already passes on Task 8's `nom_vm`
- `LesCinqEtapes`: `AttributeError: <module 'install_erplibre_home' …> does not have the attribute 'sonder'` for every subtest, and `ValueError: substring not found` in `test_every_name_it_returns_is_declared`

- [ ] **Step 3: Implement the runner**

In `long_test/install_erplibre_home.py`, replace the import block

```python
import os
import re
import shlex
import subprocess
import sys

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Les listes que gsettings affiche se lisent par le lecteur que partagent
```

with

```python
import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from descente import (  # noqa: E402
    Descente,
    Famille,
    capacite_hote,
    cle_publique,
    detruire,
    detruire_etage1,
    dire,
    drapeaux_cache,
    retirer_alias,
)

# Les listes que gsettings affiche se lisent par le lecteur que partagent
```

The comment line closes both blocks: it is the anchor, and the `sys.path` line and the `gsettings_strv` import that follow it stay as Task 8 wrote them.

Then append this at the end of the file, after `arbre_propre`, leaving two blank lines before the banner:

```python
# ---------------------------------------------------------------------------
# La course : ce qui touche aux machines.
# ---------------------------------------------------------------------------

# Chaque attente est bornée : une étape bloquée rend un verdict FAILED et la
# course passe au système suivant au lieu de s'arrêter.
DELAI_CREATION = 1800
DELAI_SSH = 600
DELAI_BUREAU = 5400
DELAI_CODE = 900
DELAI_INSTALL = 1800
DELAIS_CONTROLE = {
    "session": 300,
    "extension-active": 120,
    "extension-dbus": 30,
    "extension-indicators": 30,
    "venv": 60,
    "stream-deck-active": 120,
    "partial-uninstall-kept": 120,
    "reinstall-active": 300,
    "reinstall-indicators": 30,
}

# Ce que la machine doit avoir de libre AVANT de créer une VM. Les VM se
# suivent, une seule vit à la fois : la marge vaut pour une. Le disque se
# compare à ce qu'une VM ÉCRIT — un qcow2 n'est pas préalloué — et non à sa
# taille virtuelle. Estimation d'un bureau GNOME et du venv, à corriger
# d'après les rapports.
MARGE_RAM_MO = 1024
DISQUE_ECRIT_GO = 12
MARGE_DISQUE_GO = 8

OPTIONS_SSH = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
]
CMD_BOOT_ID = "cat /proc/sys/kernel/random/boot_id"


def ssh_base(cible):
    return ["ssh"] + OPTIONS_SSH + [cible]


def chemins_de_course():
    """(journal, dossier) de la course.

    Le dossier porte le même nom que le journal, sans extension : il reçoit
    le bundle et un « .log » par système. `dernier_rapport` ne lit que les
    « .json » du premier niveau de ~/.erplibre/longtest, donc rien de ce qui
    est rangé là n'est jamais pris pour un rapport.
    """
    base = os.path.expanduser(
        f"~/.erplibre/longtest/{NOM_BASE}-{time.strftime('%Y%m%d-%H%M%S')}"
    )
    os.makedirs(os.path.dirname(base), exist_ok=True)
    return base + ".log", base


def _ajouter(log, texte):
    """Ajoute `texte` au journal d'un système, terminé par un saut de
    ligne."""
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(texte if texte.endswith("\n") else texte + "\n")


class Course:
    """Le rapport d'une course, réécrit à chaque changement.

    Sa forme est le CONTRAT du défaire partagé (descente.py) : « outil »
    filtre les rapports, « pid » empêche de détruire sous une course vivante,
    et « etages » nomme une entrée de niveau 1 par VM encore en vie — c'est
    tout ce que « --detruire » sait reprendre. « systemes » est à ce test
    seul ; descente.py l'ignore.
    """

    def __init__(self, args, journal, dossier):
        self.args = args
        self.journal = journal
        self.dossier = dossier
        # « 20261013-142233 » pour « long-sd-20261013-142233 » : chaque VM
        # de la course le porte dans son nom.
        self.horodatage = os.path.basename(dossier)[len(NOM_BASE) + 1 :]
        self.chemin = journal[:-4] + (
            "-dryrun.json" if args.dry_run else ".json"
        )
        self.head = ""
        self.bundle = ""
        self.rapport = {
            "outil": OUTIL,
            "dry_run": args.dry_run,
            "pid": os.getpid(),
            "head": "",
            "etages": [],
            "systemes": [],
        }

    def ecrire(self):
        with open(self.chemin, "w", encoding="utf-8") as fh:
            json.dump(self.rapport, fh, indent=2)

    def inscrire(self, etage):
        """Écrit l'étage AVANT la suite : une course qui meurt en cours de
        route laisse de quoi défaire sa VM."""
        self.rapport["etages"].append(etage)
        self.ecrire()

    def retirer(self, etage):
        self.rapport["etages"].remove(etage)
        self.ecrire()

    def noter(self, ligne):
        self.rapport["systemes"].append(ligne)
        self.ecrire()


def commande_bureau():
    """Le bloc « bureau seul » du menu, pris tel quel : attente de
    cloud-init, coupure des mises à jour automatiques, GNOME et son accès
    distant. Ni clone ni Odoo.

    Importé plutôt que recopié : deux copies d'une installation de bureau
    divergent, et c'est celle du test qui reste verte.
    """
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)._qemu_erplibre_remote_cmd(None, desktop="gnome")


def creer_vm(nom, entree, journal, dry_run):
    """La VM, par la CLI du dépôt, sous sudo hors essai à blanc.

    Rend (nom, uuid, ok). Une création qui échoue après avoir défini le
    domaine rend quand même son nom et son UUID, avec ok faux : la VM existe,
    et c'est en l'inscrivant au rapport qu'elle reste défaisable.

    Un nom que libvirt définit déjà n'est pas à cette course : la création
    est refusée et rend (None, "", False), si bien que la VM d'une autre
    course n'entre jamais au rapport et n'est jamais détruite par celle-ci.
    """
    if not dry_run and Descente.uuid_libvirt(nom):
        dire(
            f"      ✗ {nom} existe déjà, elle n'est pas à cette course",
            journal,
        )
        return None, "", False
    argv = ([] if dry_run else ["sudo"]) + argv_creation(
        entree, nom, cle_publique(), drapeaux_cache()
    )
    if dry_run:
        dire("      " + " ".join(shlex.quote(a) for a in argv), journal)
        return nom, "", True
    ok = False
    try:
        fini = subprocess.run(argv, timeout=DELAI_CREATION)
        ok = fini.returncode == 0
    except (OSError, subprocess.SubprocessError) as souci:
        dire(f"      ✗ la création de {nom} s'est arrêtée : {souci}", journal)
    if not ok:
        dire(f"      ✗ la création de {nom} a échoué", journal)
    uuid = Descente.uuid_libvirt(nom)
    if not ok and not uuid:
        return None, "", False
    return nom, uuid, ok


def adresse_de(nom, journal):
    """L'adresse de la VM, et l'entrée ~/.ssh/config qui la nomme.

    La CLI n'écrit pas cette entrée : sans elle, « ssh <nom> » ne résout
    rien et chaque attente irait à son plein délai.
    """
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    todo = TODO.__new__(TODO)
    ip = todo._qemu_vm_ip(nom, timeout=DELAI_SSH)
    if not ip:
        dire(f"      ✗ {nom} créée mais sans adresse", journal)
        return ""
    pub = cle_publique()
    prive = pub[:-4] if pub else None
    todo._write_ssh_config_entry([nom], UTILISATEUR, ip, identity_file=prive)
    dire(f"      {nom} : {ip}", journal)
    return ip


def sonder(cible, commande, delai=180):
    """La sortie d'une commande distante, ou "" si elle échoue."""
    try:
        fini = subprocess.run(
            ssh_base(cible) + [commande],
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return fini.stdout.strip() if fini.returncode == 0 else ""


def attendre_ssh(cible, journal, delai=DELAI_SSH):
    """Vrai dès que la machine répond en ssh. Le port s'ouvre avant que
    cloud-init n'ait posé le compte : on attend une commande qui aboutit."""
    fin = time.time() + delai
    while time.time() < fin:
        try:
            fini = subprocess.run(
                ssh_base(cible) + ["true"],
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            # Un ssh pendu est un tour d'attente de plus, pas la fin de la
            # course.
            time.sleep(5)
            continue
        if fini.returncode == 0:
            return True
        time.sleep(5)
    dire(f"      ✗ {cible} jamais joignable en {delai} s", journal)
    return False


def lancer(argv, log, delai, entree=None):
    """Lance `argv`, sortie ajoutée au journal du système. Rend le code de
    retour, ou None quand la commande n'a pas abouti dans son délai."""
    try:
        with open(log, "a", encoding="utf-8") as fh:
            fini = subprocess.run(
                argv,
                input=entree,
                text=True,
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=delai,
            )
    except (OSError, subprocess.SubprocessError) as souci:
        _ajouter(log, f"✗ {argv[0]} interrompu : {souci}")
        return None
    return fini.returncode


def deposer_code(cible, famille, bundle, head, log):
    """git dans la VM, le bundle copié, cloné, HEAD extrait. Rend vrai si
    les trois étapes ont abouti. La VM ne joint jamais GitHub pour le
    code."""
    clone = (
        "test ! -e ~/git/erplibre && mkdir -p ~/git"
        " && git -c advice.detachedHead=false clone -q ~/erplibre_home.bundle"
        f" ~/git/erplibre && git -C ~/git/erplibre checkout -q {head}"
    )
    etapes = (
        ("git", ssh_base(cible) + [COMMANDE_GIT[famille]]),
        (
            "scp",
            ["scp"] + OPTIONS_SSH + [bundle, f"{cible}:erplibre_home.bundle"],
        ),
        ("clone", ssh_base(cible) + [clone]),
    )
    for nom, argv in etapes:
        if lancer(argv, log, DELAI_CODE) != 0:
            _ajouter(log, f"✗ code : {nom}")
            return False
    return True


def installer(cible, log, options=""):
    """L'installateur dans le checkout de la VM, avec `options` (« » pour la
    base, « --stream-deck », « --uninstall »…). Rend (code, sortie).

    La commande et toute sa sortie vont au journal du système : un échec y
    trouve la sortie de chaque commande lancée jusque-là. Le code est None
    quand l'installation n'a pas rendu de code dans son délai.
    """
    commande = "cd ~/git/erplibre && ./script/install/install_erplibre_home.sh"
    if options:
        commande += f" {options}"
    _ajouter(log, f"── {commande}")
    try:
        fini = subprocess.run(
            ssh_base(cible) + [commande],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=DELAI_INSTALL,
        )
    except (OSError, subprocess.SubprocessError) as souci:
        _ajouter(log, f"✗ installation interrompue : {souci}")
        return None, ""
    sortie = fini.stdout or ""
    _ajouter(log, sortie)
    _ajouter(log, f"── code de sortie : {fini.returncode}")
    return fini.returncode, sortie


def redemarrer(cible, log):
    """Redémarre la VM et attend qu'elle revienne. Vrai à son retour.

    Le retour se juge à l'identifiant de démarrage du noyau, qui change à
    chaque amorçage : un ssh qui répond encore AVANT l'arrêt ne passe pas
    pour un retour.
    """
    avant = sonder(cible, CMD_BOOT_ID, 30)
    if not avant:
        _ajouter(log, "✗ redémarrage : identifiant de démarrage illisible")
        return False
    try:
        subprocess.run(
            ssh_base(cible) + ["sudo systemctl reboot"],
            capture_output=True,
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError):
        # La connexion tombe avec la machine : c'est le cas attendu.
        pass
    fin = time.time() + DELAI_SSH
    while time.time() < fin:
        apres = sonder(cible, CMD_BOOT_ID, 30)
        if apres and apres != avant:
            return True
        time.sleep(5)
    _ajouter(log, f"✗ pas de retour du redémarrage en {DELAI_SSH} s")
    return False


def attendre(cible, commande, condition, delai):
    """Vrai dès que `condition(sortie)` tient, sondé toutes les 5 s."""
    fin = time.time() + delai
    while True:
        if condition(sonder(cible, commande, 60)):
            return True
        if time.time() >= fin:
            return False
        time.sleep(5)


def attendre_extension(cible, log, delai=DELAIS_CONTROLE["extension-active"]):
    """L'info de l'extension, dès qu'elle est ACTIVE ou au bout de `delai`
    secondes. La sortie brute de gdbus va au journal quand elle ne l'est
    pas."""
    fin = time.time() + delai
    while True:
        brut = sonder(cible, CMD_INFO, 60)
        info = analyser_extension_info(brut)
        if est_active(info) or time.time() >= fin:
            break
        time.sleep(5)
    if not est_active(info):
        _ajouter(log, f"GetExtensionInfo : {brut or '(aucune réponse)'}")
    return info


def indicateurs_non_montes(cible, log):
    """Les ids des indicateurs que le journal de session dit non montés.

    L'extension attrape l'exception du constructeur d'un indicateur et
    continue : ACTIVE et les réponses D-Bus tiennent même quand aucun
    indicateur n'est monté. Le journal se lit une fois ; sans la ligne
    « [ERPLibreHome] enabled », il n'est pas tenu pour lu et la fonction
    rend ["(journal non lu)"] plutôt qu'une liste vide qui passerait pour un
    succès. Ce qui manque va au journal du système.
    """
    sortie = sonder(
        cible, CMD_MONTAGES, DELAIS_CONTROLE["extension-indicators"]
    )
    if not journal_lu(sortie):
        _ajouter(
            log,
            "✗ journal de session sans « [ERPLibreHome] enabled » : "
            f"{sortie or '(rien)'}",
        )
        return ["(journal non lu)"]
    echecs = indicateurs_en_echec(sortie)
    if echecs:
        _ajouter(log, f"✗ indicateurs non montés : {', '.join(echecs)}")
    return echecs


def session_ouverte(cible):
    """Le bus de l'utilisateur existe et GNOME Shell y a pris son nom."""
    return attendre(
        cible,
        CMD_SESSION,
        lambda s: s == "(true,)",
        DELAIS_CONTROLE["session"],
    )


def _absents(cible):
    """Vrai quand ni la règle udev ni .venv.streamdeck n'existent."""
    return sonder(cible, CMD_SANS_REGLE) == "ok" and (
        sonder(cible, CMD_SANS_VENV) == "ok"
    )


def _idempotent(cible, log, options, commande_mtimes):
    """Une seconde installation rend 0 et laisse les dates de
    `commande_mtimes` telles quelles."""
    avant = sonder(cible, commande_mtimes)
    code, _sortie = installer(cible, log, options)
    apres = sonder(cible, commande_mtimes)
    if code != 0 or not avant or avant != apres:
        _ajouter(log, f"✗ idempotence : {avant!r} puis {apres!r}")
        return False
    return True


def _etape_base(cible, entree, log, base):
    """Étape 1, sur la base que l'étape 5 du flux a installée. Rend
    (echec, info, gnome)."""
    info, gnome = None, ""
    if not session_ouverte(cible):
        return "session", info, gnome
    gnome = version_gnome(sonder(cible, "gnome-shell --version"))
    if not gnome:
        return "gnome-version", info, gnome
    attendu = entree["gnome_attendu"]
    if majeur(gnome) != attendu:
        _ajouter(log, f"⚠ GNOME mesuré {gnome}, la matrice dit {attendu}")
    info = attendre_extension(cible, log)
    if not est_active(info):
        return "extension-active", info, gnome
    # L'objet D-Bus est exporté avant les réglages : une méthode qui ne les
    # touche pas répondrait même si enable() avait levé ensuite. ListPaths
    # les lit. ListDevices rend « [] » sans appareil branché comme sans
    # indicateur des appareils monté : sa réponse ne prouve pas l'indicateur,
    # d'où la lecture du journal qui suit. Sans venv du deck, celle-ci
    # prouve aussi que les indicateurs du deck se montent quand même.
    for methode in ("ListPaths", "ListDevices"):
        reponse = sonder(
            cible, cmd_methode(methode), DELAIS_CONTROLE["extension-dbus"]
        )
        if not reponse.startswith("('"):
            _ajouter(log, f"✗ {methode} : {reponse or '(aucune réponse)'}")
            return "extension-dbus", info, gnome
    if indicateurs_non_montes(cible, log):
        return "extension-indicators", info, gnome
    if sonder(cible, CMD_SANS_REGLE) != "ok":
        return "base-no-udev", info, gnome
    if sonder(cible, CMD_SANS_VENV) != "ok":
        return "base-no-venv", info, gnome
    if not _idempotent(cible, log, base, CMD_MTIME_LIEN):
        return "base-idempotent", info, gnome
    return None, info, gnome


def _etape_stream_deck(cible, log):
    """Étape 2 : le niveau Stream Deck par-dessus la base, sans
    redémarrage, l'extension étant déjà chargée. Rend (echec, info)."""
    option = OPTION["install-stream-deck"]
    code, _sortie = installer(cible, log, option)
    if code != 0:
        return "install-stream-deck", None
    if sonder(cible, CMD_UDEV) != "ok":
        return "udev", None
    if sonder(cible, CMD_VENV, DELAIS_CONTROLE["venv"]) != "ok":
        return "venv", None
    info = attendre_extension(
        cible, log, DELAIS_CONTROLE["stream-deck-active"]
    )
    if not est_active(info):
        return "stream-deck-active", info
    if not _idempotent(cible, log, option, CMD_MTIMES):
        return "stream-deck-idempotent", info
    return None, info


def _etape_retrait_partiel(cible, log):
    """Étape 3 : le niveau Stream Deck retiré seul ; l'extension reste liée,
    activée et ACTIVE. Rend (echec, info)."""
    code, _sortie = installer(cible, log, OPTION["uninstall-stream-deck"])
    if code != 0:
        return "uninstall-stream-deck", None
    if not _absents(cible):
        return "partial-uninstall-gone", None
    liste = liste_extensions(sonder(cible, CMD_ENABLED))
    if sonder(cible, CMD_LIEN) != "ok" or UUID_EXTENSION not in (liste or []):
        _ajouter(
            log, f"✗ après le retrait partiel : enabled-extensions {liste}"
        )
        return "partial-uninstall-kept", None
    info = attendre_extension(
        cible, log, DELAIS_CONTROLE["partial-uninstall-kept"]
    )
    if not est_active(info):
        return "partial-uninstall-kept", info
    return None, info


def _etape_retrait(cible, log):
    """Étape 4 : tout retiré. Rend l'échec ou None."""
    code, _sortie = installer(cible, log, OPTION["uninstall"])
    if code != 0:
        return "uninstall"
    liste = liste_extensions(sonder(cible, CMD_ENABLED))
    if (
        sonder(cible, CMD_SANS_LIEN) != "ok"
        or liste is None
        or UUID_EXTENSION in liste
        or not _absents(cible)
    ):
        _ajouter(log, f"✗ après le retrait : enabled-extensions {liste}")
        return "uninstall-gone"
    return None


def _etape_reinstallation(cible, log, base):
    """Étape 5 : la base de nouveau, puis un redémarrage, pour que GNOME
    Shell charge l'extension à neuf plutôt que de réactiver la copie qu'il
    tient de l'étape 1. Rend (echec, info)."""
    code, _sortie = installer(cible, log, base)
    if code != 0 or not redemarrer(cible, log):
        return "reinstall", None
    if not session_ouverte(cible):
        return "reinstall-active", None
    info = attendre_extension(cible, log, DELAIS_CONTROLE["reinstall-active"])
    if not est_active(info):
        return "reinstall-active", info
    if indicateurs_non_montes(cible, log):
        return "reinstall-indicators", info
    if not _absents(cible):
        return "reinstall-no-udev", info
    return None, info


def controler(cible, entree, log, extras=False):
    """Les cinq étapes d'ETAPES, dans l'ordre ; le premier échec, commande
    ou contrôle, arrête les suivantes.

    `extras` : la base s'installe avec « --with-extras », comme à l'étape 5
    du flux. Rend (echec, info, gnome) : le nom de l'étape tombée ou None,
    la dernière réponse de GetExtensionInfo, la version de GNOME mesurée.
    """
    base = "--with-extras" if extras else ""
    echec, info, gnome = _etape_base(cible, entree, log, base)
    if echec:
        return echec, info, gnome
    for etape in (_etape_stream_deck, _etape_retrait_partiel):
        echec, lue = etape(cible, log)
        info = lue or info
        if echec:
            return echec, info, gnome
    echec = _etape_retrait(cible, log)
    if echec:
        return echec, info, gnome
    echec, lue = _etape_reinstallation(cible, log, base)
    return echec, lue or info, gnome


def joindre_diagnostic(cible, log):
    """Ce qu'un échec joint au journal du système, après la sortie de
    l'installateur qui y est déjà."""
    for titre, commande in (
        ("journalctl --user -b", CMD_JOURNAL),
        (f"gnome-extensions info {UUID_EXTENSION}", CMD_EXT_INFO),
    ):
        _ajouter(log, f"── {titre}\n{sonder(cible, commande) or '(rien)'}")


def mener_un(course, entree):
    """Un système, de la création de sa VM à son verdict. Rend la ligne du
    rapport ; la VM reste inscrite dans course.rapport["etages"]."""
    debut = time.time()
    log = os.path.join(
        course.dossier, f"{entree['distro']}-{entree['version']}.log"
    )
    famille = FAMILLE[entree["distro"]]
    etat = {"code": None, "info": None, "gnome": "", "echec": None}
    raison = ""

    def ligne():
        return verdict_systeme(
            entree,
            etat["code"],
            etat["info"],
            etat["gnome"],
            echec=etat["echec"],
            raison=raison,
            duree_s=time.time() - debut,
            journal=os.path.basename(log),
        )

    dire(
        f"  ── {cle(entree)} (GNOME attendu {entree['gnome_attendu']})",
        course.journal,
    )
    nom, uuid, ok = creer_vm(
        nom_vm(entree, course.horodatage), entree, course.journal, False
    )
    if nom:
        course.inscrire(
            {"niveau": 1, "nom": nom, "uuid": uuid, "alias": nom, "cree": True}
        )
    if not ok:
        etat["echec"] = "vm"
        return ligne()
    if not adresse_de(nom, course.journal) or not attendre_ssh(
        nom, course.journal
    ):
        etat["echec"] = "ssh"
        return ligne()
    bureau = commande_bureau()
    if lancer(ssh_base(nom) + ["bash -s"], log, DELAI_BUREAU, bureau) != 0:
        etat["echec"] = "desktop"
        return ligne()
    if not deposer_code(nom, famille, course.bundle, course.head, log):
        etat["echec"] = "code"
        return ligne()
    extras = course.args.extras and cle(entree) == SYSTEME_EXTRAS
    etat["code"], sortie = installer(
        nom, log, "--with-extras" if extras else ""
    )
    if etat["code"] == 2:
        raison = raison_non_supportee(sortie)
    if etat["code"] != 0:
        if etat["code"] != 2:
            joindre_diagnostic(nom, log)
        return ligne()
    _chemin, commande = autologin(famille, UTILISATEUR)
    if lancer(ssh_base(nom) + [commande], log, 120) != 0:
        etat["echec"] = "autologin"
        return ligne()
    if not redemarrer(nom, log):
        etat["echec"] = "ssh"
        return ligne()
    etat["echec"], etat["info"], etat["gnome"] = controler(
        nom, entree, log, extras
    )
    if etat["echec"]:
        joindre_diagnostic(nom, log)
    return ligne()


def plan_tient(journal):
    """La machine peut-elle héberger une VM ? Le dire AVANT de la créer."""
    coeurs, ram, disque = capacite_hote()
    dire(
        f"  machine locale : {coeurs} cœurs, {ram} Mo disponibles,"
        f" {disque} Go de disque",
        journal,
    )
    manque = []
    if ram < MEMOIRE_MO + MARGE_RAM_MO:
        manque.append(f"RAM (il en faut {MEMOIRE_MO + MARGE_RAM_MO} Mo)")
    if disque < DISQUE_ECRIT_GO + MARGE_DISQUE_GO:
        manque.append(
            f"disque (il en faut {DISQUE_ECRIT_GO + MARGE_DISQUE_GO} Go"
            f" libres ; le disque virtuel fait {DISQUE_GO} Go, creux)"
        )
    if manque:
        dire(f"  ✗ pas assez de {' ni de '.join(manque)}", journal)
        return False
    return True


def creer_bundle(dossier, journal):
    """(sha de HEAD, chemin du bundle), ou ("", "") si git a échoué."""
    chemin = os.path.join(dossier, "erplibre_home.bundle")
    try:
        head = subprocess.run(
            ["git", "-C", RACINE, "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=60,
        )
        fini = subprocess.run(
            ["git", "-C", RACINE, "bundle", "create", chemin, "HEAD"],
            capture_output=True,
            text=True,
            timeout=600,
        )
    except (OSError, subprocess.SubprocessError) as souci:
        dire(f"  ✗ git bundle : {souci}", journal)
        return "", ""
    if head.returncode or fini.returncode:
        dire(f"  ✗ git bundle : {fini.stderr.strip()[:160]}", journal)
        return "", ""
    sha = head.stdout.strip()
    dire(f"  code : HEAD {sha[:12]}, {chemin}", journal)
    return sha, chemin


def annoncer(systemes, args, journal):
    """Le plan : chaque système, le gabarit des VM, ce qui est hors champ."""
    dire(
        f"  {len(systemes)} système(s), un à la fois ; chaque VM :"
        f" {VCPUS} vCPU, {MEMOIRE_MO} Mo, {DISQUE_GO} Go, --desktop --gpu off",
        journal,
    )
    for entree in systemes:
        roulante = " (roulante)" if entree["roulante"] else ""
        extras = (
            " + --with-extras"
            if args.extras and cle(entree) == SYSTEME_EXTRAS
            else ""
        )
        dire(
            f"    {cle(entree):<22} GNOME attendu"
            f" {entree['gnome_attendu']}{roulante}{extras}",
            journal,
        )
    if not args.only:
        for entree in NON_SUPPORTES:
            dire(
                f"    {cle(entree):<22} UNSUPPORTED : {entree['raison']}"
                " (aucune VM)",
                journal,
            )
        dire(
            f"    {', '.join(ARCHITECTURES_HORS_CHAMP)} : UNSUPPORTED,"
            " amd64 seulement",
            journal,
        )
    dire("  sur chaque VM, l'une après l'autre :", journal)
    for ligne in decrire_etapes():
        dire(ligne, journal)
    if args.extras and all(cle(e) != SYSTEME_EXTRAS for e in systemes):
        dire(f"  ⚠ --extras ne vaut que pour {SYSTEME_EXTRAS}", journal)


def mener(argv):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument(
        "--only",
        default="",
        help="clés distro:version séparées par des virgules"
        " (défaut : toute la matrice)",
    )
    parseur.add_argument(
        "--extras",
        action="store_true",
        help=f"installer avec --with-extras sur {SYSTEME_EXTRAS}",
    )
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument(
        "--garder",
        action="store_true",
        help="garder chaque VM après son verdict",
    )
    parseur.add_argument("--detruire", action="store_true")
    args = parseur.parse_args(argv)

    journal, dossier = chemins_de_course()

    # `detruire_une` défait une VM IMBRIQUÉE chez son parent ; ce test n'en
    # crée aucune, et le défaire partagé ne l'appelle donc jamais. Elle le
    # dit plutôt que d'être None : le jour où elle serait appelée, le journal
    # nommerait la raison au lieu de « NoneType is not callable ».
    def pas_d_imbrique(parent_alias, identite, nom, log=None):
        dire(f"      ✗ {nom} : ce test ne crée pas de VM imbriquée", log)
        return False

    if args.detruire:
        famille = Famille(OUTIL, NOM_BASE, pas_d_imbrique)
        return detruire(famille, journal, dry_run=args.dry_run)

    try:
        systemes = plan(args.only or None)
    except ValueError as souci:
        dire(f"  ✗ {souci}", journal)
        return 1

    dire(f"  journal : {journal}", journal)
    annoncer(systemes, args, journal)
    course = Course(args, journal, dossier)
    if not args.only:
        for entree in NON_SUPPORTES:
            course.rapport["systemes"].append(ligne_non_supportee(entree))

    if args.dry_run:
        dire(
            f"  bureau : {len(commande_bureau())} caractères de commande"
            " distante, celle du menu",
            journal,
        )
        for entree in systemes:
            creer_vm(nom_vm(entree, course.horodatage), entree, journal, True)
        if not arbre_propre(RACINE):
            dire(
                "  ⚠ des fichiers suivis sont modifiés : la course réelle"
                " refusera de partir",
                journal,
            )
        course.ecrire()
        dire(f"  rapport : {course.chemin}", journal)
        dire("  --dry-run : rien n'a été créé.", journal)
        return 0

    # La course installe HEAD : un fichier suivi et modifié ne serait pas
    # dans la VM, et le verdict porterait sur autre chose que ce qu'on lit.
    if not arbre_propre(RACINE):
        dire(
            "  ✗ des fichiers suivis sont modifiés ou indexés : commiter ou"
            " remiser d'abord, la VM reçoit HEAD.",
            journal,
        )
        return 1
    if not plan_tient(journal):
        return 1
    os.makedirs(dossier, exist_ok=True)
    course.head, course.bundle = creer_bundle(dossier, journal)
    if not course.bundle:
        return 1
    course.rapport["head"] = course.head
    course.ecrire()
    dire(f"  rapport : {course.chemin}", journal)

    for entree in systemes:
        try:
            ligne = mener_un(course, entree)
        except Exception as souci:  # noqa: BLE001 - un système, pas la course
            ligne = verdict_systeme(
                entree, None, None, "", echec=f"exception ({souci})"
            )
        course.noter(ligne)
        marque = {"ACTIVE": "✅", "UNSUPPORTED": "⚪"}.get(
            ligne["verdict"], "❌"
        )
        etape = f" ({ligne['etape']})" if ligne["etape"] else ""
        dire(f"  {marque} {cle(entree)} : {ligne['verdict']}{etape}", journal)
        if args.garder:
            continue
        # En cours de course, jamais detruire() : il demande « OUI ».
        for etage in list(course.rapport["etages"]):
            if detruire_etage1(
                journal, etage["nom"], attendu=etage["uuid"] or None
            ):
                retirer_alias({"etages": [etage]}, journal, NOM_BASE)
                course.retirer(etage)

    for ligne in resume(course.rapport["systemes"]):
        dire(ligne, journal)
    if course.rapport["etages"]:
        dire(
            f"  {len(course.rapport['etages'])} VM gardée(s) :"
            " --detruire les défait",
            journal,
        )
    return code_sortie(course.rapport["systemes"])


if __name__ == "__main__":
    sys.exit(mener(sys.argv[1:]))
```

Then run: `chmod +x long_test/install_erplibre_home.py`

- [ ] **Step 4: Lock, menu and i18n**

`long_test/descente.py:40-45`, before:

```python
SCRIPTS = (
    "deep_proxmox.py",
    "deep_qemu.py",
    "install_nixos.py",
    "qemu_cache.py",
)
```

after:

```python
SCRIPTS = (
    "deep_proxmox.py",
    "deep_qemu.py",
    "install_nixos.py",
    "install_erplibre_home.py",
    "qemu_cache.py",
)
```

`script/todo/longtest_menu.py:29-34`, before:

```python
SCRIPTS_DEFAISABLES = (
    "deep_proxmox.py",
    "deep_qemu.py",
    "qemu_cache.py",
    "install_nixos.py",
)
```

after:

```python
SCRIPTS_DEFAISABLES = (
    "deep_proxmox.py",
    "deep_qemu.py",
    "qemu_cache.py",
    "install_nixos.py",
    "install_erplibre_home.py",
)
```

`script/todo/longtest_menu.py:129-131`, before:

```python
            {"prompt_description": t("ERPLibre on NixOS: run it")},
            {"prompt_description": t("Undo what the descent created")},
        ]
```

after:

```python
            {"prompt_description": t("ERPLibre on NixOS: run it")},
            {
                "prompt_description": t(
                    "ERPLibre Home on every distribution: plan only (dry-run)"
                )
            },
            {
                "prompt_description": t(
                    "ERPLibre Home on every distribution: run it"
                )
            },
            {"prompt_description": t("Undo what the descent created")},
        ]
```

`script/todo/longtest_menu.py:140`, before:

```python
        # Chaque choix : le script, et s'il faut demander d'où l'on part.
```

after:

```python
        # ERPLibre Home non plus : une VM par système, ni profondeur ni hôte
        # de départ. Sa table est interrogée avant celle des piles.
        erplibre_home = {
            "10": "--dry-run",
            "11": "",
        }
        # Chaque choix : le script, et s'il faut demander d'où l'on part.
```

`script/todo/longtest_menu.py:158-160`, before:

```python
            if status in cache:
                self._longtest_run("qemu_cache.py", cache[status])
                continue
```

after:

```python
            if status in cache:
                self._longtest_run("qemu_cache.py", cache[status])
                continue
            if status in erplibre_home:
                self._longtest_run(
                    "install_erplibre_home.py", erplibre_home[status]
                )
                continue
```

`script/todo/longtest_menu.py:177-178`, before:

```python
            elif status == "10":
                self._longtest_defaire()
```

after:

```python
            elif status == "12":
                self._longtest_defaire()
```

`script/todo/todo_i18n.py`: insert right after the entry at 6075-6078 (`"Use a NixOS machine you already have": {…},`):

```python
    # ERPLibre Home installé sur chaque distribution, extension ACTIVE.
    "ERPLibre Home on every distribution: plan only (dry-run)": {
        "fr": "ERPLibre Home sur chaque distribution : le plan seulement"
        " (à blanc)",
        "en": "ERPLibre Home on every distribution: plan only (dry-run)",
    },
    "ERPLibre Home on every distribution: run it": {
        "fr": "ERPLibre Home sur chaque distribution : le lancer",
        "en": "ERPLibre Home on every distribution: run it",
    },
```

- [ ] **Step 5: Run tests to verify they pass**

Do not run `ruff format` on `todo_i18n.py`: that file is not ruff-formatted, and ruff would rewrite thousands of lines.

```bash
.venv.erplibre/bin/ruff check --select I --fix long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py script/todo/longtest_menu.py
.venv.erplibre/bin/ruff format long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py script/todo/longtest_menu.py
.venv.erplibre/bin/ruff check --select E,F,W,B long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py
python3 script/analyse/check_comment_hygiene.py long_test/install_erplibre_home.py test/test_longtest_install_erplibre_home.py
.venv.erplibre/bin/python -m unittest test.test_longtest_install_erplibre_home test.test_todo_longtest test.test_longtest_install_nixos test.test_todo_i18n test.test_i18n_duplicates -v
./script/test/run_unit_test.sh test/test_longtest_install_erplibre_home.py test/test_longtest_install_nixos.py
./long_test/install_erplibre_home.py --dry-run
```

Expected:
- ruff leaves the three files unchanged, and the E,F,W,B check prints `All checks passed!`.
- The hygiene check prints no 🔴 line.
- `Ran 255 tests` … `OK`: test_longtest_install_erplibre_home 100, test_todo_longtest 98, test_longtest_install_nixos 30, test_todo_i18n 24, test_i18n_duplicates 3. This includes `test_every_listed_choice_has_a_branch`: there are 12 entries, `"1"`…`"12"` are handled, and `"13"` is absent. It also includes `test_the_two_copies_of_the_list_agree`.
- The isolated runner prints `130 tests, tout vert`. Do not add `test/test_todo_longtest.py` to that parallel run: at HEAD already, it and `test/test_longtest_install_nixos.py` fail together under the parallel runner, each seeing the other's descent subprocess as a live descent (`une descente tourne`); the sequential `unittest` command above covers both.
- `DeuxCoursesDeSuite` covers the Review Focus line on two runs in a row: names built from two run stamps are disjoint, a name libvirt already defines never reaches the report, and the destroy loop only receives the `(nom, uuid)` pairs the run itself wrote, never a VM from an earlier run's report.
- `LeDefaire.test_every_kept_vm_is_named` needs Task 7's `detruire`, which names every `niveau == 1` entry. Before Task 7 it fails on the second VM name.
- `LesCinqEtapes` covers the five stages: the order of the installer calls on a sound VM (`""`, `--stream-deck` twice, `--uninstall --stream-deck`, `--uninstall`, `""`, one reboot), and the name each fault leaves (`base-no-udev`, `install-stream-deck`, `partial-uninstall-kept`, `uninstall-gone`, `reinstall-no-udev`…). `test_every_name_it_returns_is_declared` checks that the names `controler` can return are exactly those of `ETAPES`.
- The manual dry-run prints 13 `deploy_qemu.py` lines with `--desktop --gpu off --vcpus 2 --memory 4096 --disk-size 26G`, 5 `UNSUPPORTED :` lines, the five `étape N, …` lines with their commands and checks, and no `sudo`, then exits 0.

- [ ] **Step 6: Commit the runner**

```bash
git add long_test/install_erplibre_home.py long_test/descente.py script/todo/longtest_menu.py script/todo/todo_i18n.py test/test_longtest_install_erplibre_home.py
cat > $SCRATCH/msg_task9a.txt <<'EOF'
[ADD] long_test: ERPLibre Home install runner and its menu entries

install_erplibre_home.py creates one VM per supported system, sends HEAD
as a git bundle, installs the base, logs the user in through GDM and
requires GetExtensionInfo to report the extension ACTIVE. Five stages
follow on the same VM: base without rule nor venv, --stream-deck,
--uninstall --stream-deck, --uninstall, then the base again after a
reboot; the first failure names its command or check. A modified tracked
file refuses the run; --detruire undoes the VMs a run kept.
Checked: dry-run plan, the five stages, dirty tree, menu, lock, undo.

--- FR ---

[ADD] long_test : course d'installation ERPLibre Home, entrées de menu

install_erplibre_home.py crée une VM par système supporté, envoie HEAD en
bundle git, installe la base, ouvre la session par GDM et exige que
GetExtensionInfo rende l'extension ACTIVE. Cinq étapes suivent sur la même
VM : la base sans règle ni venv, --stream-deck, --uninstall --stream-deck,
--uninstall, puis la base de nouveau après un redémarrage ; le premier
échec nomme sa commande ou son contrôle. Un fichier suivi modifié fait
refuser la course ; --detruire défait les VM qu'une course a gardées.
Vérifié : plan à blanc, cinq étapes, arbre modifié, menu, verrou, défaire.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task9a.txt
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task9a.txt
```

- [ ] **Step 7: Write the failing README test**

Insert this class in `test/test_longtest_install_erplibre_home.py` just before the final `if __name__ == "__main__":` block:

```python
class LeReadme(unittest.TestCase):
    def test_the_readme_documents_it_in_both_languages(self):
        """La source est le .base.md ; les deux .md en sont générés."""
        base = (RACINE / "long_test/README.base.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(base.count("## install_erplibre_home.py"), 2)
        for nom in ("README.md", "README.fr.md"):
            with self.subTest(nom=nom):
                texte = (RACINE / "long_test" / nom).read_text(
                    encoding="utf-8"
                )
                self.assertIn("## install_erplibre_home.py", texte)
```

Run: `.venv.erplibre/bin/python -m unittest test.test_longtest_install_erplibre_home.LeReadme`
Expected: FAIL with `AssertionError: 0 != 2`

- [ ] **Step 8: Write the README section and regenerate**

In `long_test/README.base.md`, insert just before line 246, `## Starting from a host you already have`:

````markdown
## install_erplibre_home.py — does ERPLibre Home run on every distribution?

One VM per distribution version, one at a time: Ubuntu 24.04, 25.10 and
26.04, Debian 13, Fedora 41 to 44, AlmaLinux 10, Rocky Linux 10, openSUSE
Leap 16.0, and the two rolling ones, Arch Linux and openSUSE Tumbleweed. The
systems GNOME 45 to 51 does not reach — Debian 12, the EL9 rebuilds — and
those without a GNOME desktop path — NixOS, Proxmox — are listed
`UNSUPPORTED` and get no VM.

Each VM gets the GNOME desktop through the menu's own remote command, then
the code of **this checkout**, sent as a `git bundle` of `HEAD`: the VM never
reaches GitHub for it. A modified tracked file makes the run refuse to
start, since it would not be in the VM. Then `install_erplibre_home.sh` installs
the ERPLibre Home base, GDM logs the user in automatically, and the VM
reboots.

The verdict is what GNOME Shell answers, not a return code: `GetExtensionInfo`
must report state `1` and an empty `error`. Being listed in
`enabled-extensions` is not enough — an extension that throws in `enable()`
stays listed, in ERROR. The extension's own `ListPaths` and `ListDevices`
must answer too. ACTIVE does not prove the top bar either: the extension
catches an indicator constructor's exception and keeps running, so the
`extension-indicators` check reads the user journal: it requires the
`[ERPLibreHome] enabled` line that ends `enable()`, so an unread journal
fails too, and it fails on any `[ERPLibreHome] mount <id> failed` line.

That is the first of five stages, run in order on the same VM:

1. **base**: the checks above, then neither the udev rule nor
   `.venv.streamdeck` exists, and a second base install changes nothing;
2. **install-stream-deck**: `--stream-deck` writes the udev rule, the venv
   imports what the deck programs import, the extension stays ACTIVE, and a
   second run changes nothing;
3. **uninstall-stream-deck**: `--uninstall --stream-deck` removes the rule
   and the venv, and leaves the extension linked, enabled and ACTIVE;
4. **uninstall**: `--uninstall` leaves neither link, nor UUID in
   `enabled-extensions`, nor rule, nor venv;
5. **reinstall**: the base again, then a reboot: the extension comes back
   ACTIVE with every indicator mounted, without the rule or the venv.

A stage command that fails, or the first failed check, names the verdict
(`FAILED(install-stream-deck)`, `FAILED(reinstall-no-udev)`…): every name is
unique, so it tells which stage stopped.

```
./long_test/install_erplibre_home.py                 # the whole matrix
./long_test/install_erplibre_home.py --only ubuntu:24.04,fedora:43
./long_test/install_erplibre_home.py --extras        # --with-extras on 24.04
./long_test/install_erplibre_home.py --dry-run       # the plan, nothing created
./long_test/install_erplibre_home.py --garder        # keep the VMs
./long_test/install_erplibre_home.py --detruire      # undo the last run
```

The report lists one line per system, with the GNOME version expected and
the one measured: the matrix in the script is corrected from those lines. On
Arch and Tumbleweed, `UNSUPPORTED` means GNOME moved past 51, and it is the
expected signal to update `metadata.json`. Each system's log — installer
output, user journal, `gnome-extensions info` — is a `.log` in the run's
sub-directory.

````

And just before line 524 (shifted by the insertion above), `## Partir d'un hôte qu'on possède déjà`:

````markdown
## install_erplibre_home.py — ERPLibre Home tourne-t-il sur chaque distribution ?

Une VM par version de distribution, l'une après l'autre : Ubuntu 24.04, 25.10
et 26.04, Debian 13, Fedora 41 à 44, AlmaLinux 10, Rocky Linux 10, openSUSE
Leap 16.0, et les deux roulantes, Arch Linux et openSUSE Tumbleweed. Les
systèmes que GNOME 45 à 51 n'atteint pas — Debian 12, les reconstructions
EL9 — et ceux sans chemin de bureau GNOME — NixOS, Proxmox — sont listés
`UNSUPPORTED` et n'ont pas de VM.

Chaque VM reçoit le bureau GNOME par la commande distante du menu, puis le
code de **ce checkout**, envoyé en `git bundle` de `HEAD` : la VM ne joint
jamais GitHub pour lui. Un fichier suivi et modifié fait refuser la course,
puisqu'il ne serait pas dans la VM. Puis `install_erplibre_home.sh` installe
la base d'ERPLibre Home, GDM ouvre la session de l'utilisateur tout seul, et
la VM redémarre.

Le verdict est ce que GNOME Shell répond, pas un code de retour :
`GetExtensionInfo` doit rendre l'état `1` et une `error` vide. Figurer dans
`enabled-extensions` ne suffit pas — une extension qui lève dans `enable()` y
reste listée, en ERREUR. Les `ListPaths` et `ListDevices` de l'extension
doivent répondre aussi. ACTIVE ne prouve pas non plus la barre du haut :
l'extension attrape l'exception du constructeur d'un indicateur et continue,
alors le contrôle `extension-indicators` lit le journal utilisateur : il
exige la ligne `[ERPLibreHome] enabled` qui clôt `enable()`, si bien qu'un
journal non lu échoue aussi, et il échoue sur toute ligne
`[ERPLibreHome] mount <id> failed`.

C'est la première de cinq étapes, menées dans l'ordre sur la même VM :

1. **base** : les contrôles ci-dessus, puis ni la règle udev ni
   `.venv.streamdeck` n'existent, et une seconde installation de la base ne
   change rien ;
2. **install-stream-deck** : `--stream-deck` écrit la règle udev, le venv
   importe ce qu'importent les programmes du deck, l'extension reste ACTIVE,
   et une seconde exécution ne change rien ;
3. **uninstall-stream-deck** : `--uninstall --stream-deck` retire la règle
   et le venv, et laisse l'extension liée, activée et ACTIVE ;
4. **uninstall** : `--uninstall` ne laisse ni lien, ni UUID dans
   `enabled-extensions`, ni règle, ni venv ;
5. **reinstall** : la base de nouveau, puis un redémarrage : l'extension
   revient ACTIVE avec chaque indicateur monté, sans la règle ni le venv.

Une commande d'étape qui échoue, ou le premier contrôle tombé, nomme le
verdict (`FAILED(install-stream-deck)`, `FAILED(reinstall-no-udev)`…) :
chaque nom est unique, il dit donc quelle étape s'est arrêtée.

```
./long_test/install_erplibre_home.py                 # toute la matrice
./long_test/install_erplibre_home.py --only ubuntu:24.04,fedora:43
./long_test/install_erplibre_home.py --extras        # --with-extras sur 24.04
./long_test/install_erplibre_home.py --dry-run       # le plan, rien de créé
./long_test/install_erplibre_home.py --garder        # garder les VM
./long_test/install_erplibre_home.py --detruire      # défaire la dernière course
```

Le rapport porte une ligne par système, avec la version de GNOME attendue et
celle mesurée : c'est d'après ces lignes que la matrice du script se
corrige. Sur Arch et Tumbleweed, `UNSUPPORTED` veut dire que GNOME a dépassé
51, et c'est le signal attendu pour mettre `metadata.json` à jour. Le
journal de chaque système — sortie de l'installateur, journal utilisateur,
`gnome-extensions info` — est un `.log` dans le sous-dossier de la course.

````

Regenerate:

```bash
source .venv.erplibre/bin/activate && mmg --yes long_test/README.base.md
```

Expected: `=> 1 base file has been converted.` `long_test/README.md` and `long_test/README.fr.md` are modified.

- [ ] **Step 9: Run tests to verify they pass**

```bash
.venv.erplibre/bin/ruff format test/test_longtest_install_erplibre_home.py
.venv.erplibre/bin/python -m unittest test.test_longtest_install_erplibre_home test.test_todo_longtest
```

Expected: OK.

- [ ] **Step 10: Commit the README**

```bash
git add long_test/README.base.md long_test/README.md long_test/README.fr.md test/test_longtest_install_erplibre_home.py
cat > $SCRATCH/msg_task9b.txt <<'EOF'
[ADD] doc: long_test README section for the ERPLibre Home install test

The long test README describes each script: what it proves, how to run it
and how to undo it. The new section gives the ERPLibre Home matrix, why the
verdict is GetExtensionInfo and not a return code, the five stages each VM
goes through, why the code comes from a bundle of HEAD, and where each
system's log lands.

--- FR ---

[ADD] doc : section du README long_test pour le test ERPLibre Home

Le README des tests longs décrit chaque script : ce qu'il prouve, comment le
lancer et comment le défaire. La nouvelle section donne la matrice
d'ERPLibre Home, pourquoi le verdict est GetExtensionInfo et non un code
de retour, les cinq étapes de chaque VM, pourquoi le code vient d'un bundle
de HEAD, et où atterrit le journal de chaque système.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task9b.txt
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task9b.txt
```
---

### Task 10: Full matrix run (manual)

**Files:**
- Modify: `long_test/install_erplibre_home.py` (the `gnome_attendu` values of `MATRICE`, only where measured differently)

**Interfaces:**
- Consumes: everything above.
- Produces: a matrix whose expected GNOME versions are measured, not claimed.

- [ ] **Step 1: Check the plan**

Run: `./long_test/install_erplibre_home.py --dry-run`
Expected: 13 in-scope systems in the order of `MATRICE`, the unsupported lines of `NON_SUPPORTES`, the five stage lines of `decrire_etapes()`, no VM created.

- [ ] **Step 2: Run the matrix**

Run: `./long_test/install_erplibre_home.py` (several hours), then `./long_test/install_erplibre_home.py --only ubuntu:24.04 --extras`.
Expected: exit 0; every non-rolling system `ACTIVE`, which means the five stages passed on its VM; `arch:latest` and `opensuse:tumbleweed` `ACTIVE` or `UNSUPPORTED(GNOME <v> not in shell-version)`.

A `FAILED(<name>)` line is a defect to fix in the task that owns that command or check, with the attached journal; rerun with `--only <key>` after the fix. The name tells the stage: `install`, `session` … `base-idempotent` the base (Tasks 3-4, 2 for `extension-indicators`); `install-stream-deck`, `udev`, `venv`, `stream-deck-*` the Stream Deck level (Task 4; a missing package name on Leap 16.0 or the EL10 rebuilds shows here first, and is fixed in the package table of Task 3); `uninstall-stream-deck`, `partial-uninstall-*`, `uninstall`, `uninstall-gone` the uninstalls (Task 4); `reinstall*` an install after a full uninstall (Task 4).

- [ ] **Step 3: Correct the matrix from the measures**

For every report line whose `gnome_mesure` major differs from `gnome_attendu`, set `gnome_attendu` in `MATRICE` to the measured major. Run `./script/test/run_unit_test.sh test/test_longtest_install_erplibre_home.py`; expected PASS.

- [ ] **Step 4: Commit (only if Step 3 changed something)**

```bash
cd "$(git rev-parse --show-toplevel)"
git add long_test/install_erplibre_home.py
cat > $SCRATCH/msg_task10.txt <<'EOF'
[IMP] long_test: ERPLibre Home matrix GNOME versions from a full run

The expected GNOME version of each system was a claim from release notes.
A full run measured gnome-shell --version on every VM; the matrix now
holds the measured majors, so a later mismatch means the distribution
moved.

--- FR ---

[IMP] long_test : versions GNOME de la matrice ERPLibre Home mesurées

La version GNOME attendue de chaque système venait des notes de version.
Une course complète a mesuré gnome-shell --version sur chaque VM ; la
matrice porte désormais les versions mesurées, et un écart futur signale
que la distribution a bougé.

Assisted-by: Claude Opus 5.5
EOF
script/git/hooks/commit-msg $SCRATCH/msg_task10.txt
git -c user.name="Mathieu Benoit" -c user.email="mathben@technolibre.ca" commit -F $SCRATCH/msg_task10.txt
```
