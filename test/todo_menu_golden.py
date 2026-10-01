#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Rendus de référence de menus de TODO : l'entrée [4] (Navigation
telemetry), Configuration, la famille Execute : Execute, Code et Debug,
Config et Generate from pre-configuration, Process, Test et Update, la
famille Run : Run, Database et son menu d'effacement, Analyse, Transform
data et Doc, la famille Git : Git, Git local server et ses deux menus
Actions, GPT code, Claude configs, Plugins, Claude Code, RTK et
Automation, la famille QEMU : Deploy, SSH, QEMU/KVM, QEMU cache et ses
sept menus, Network, Security, Docker / Podman et ses trois menus, la
famille Proxmox : Proxmox VE, VPN, Long test et Install, la famille
Assistant : Assistant, LLM, Servers, Search et les trois menus du
courriel, et le menu principal.

Module d'aide et non fichier de tests : son nom ne commence pas par
« test_ ». `capture()` rend, en français et en anglais :
- `terminal` : pour chaque menu de MENUS appelé seul, qui reçoit ses
  réponses (ANSWERS : une réponse vide, un numéro sans entrée, 0), ce que
  montre le terminal, réponses tapées comprises, ce que rend le menu, les
  clés de télémétrie qu'il enregistre et le nombre de sondes du hub web ;
  Run y montre l'entrée Mobile, son répertoire présent ; Install, qui
  pose ses questions par `input`, reçoit INPUTS ; un menu du courriel,
  une fonction de `script/todo/mail/menu.py`, reçoit le TODO ; le menu
  principal montre le logo, la langue tenue pour choisie ;
- `session` : quand le vrai TODO, sous la capture de la session web comme
  dans le worker, suit WALK, les messages `menu` des menus de CRUMBS, le fil
  d'Ariane de chaque menu traversé et les clés de télémétrie. WALK ne
  répond qu'à des menus, jamais à une feuille : une étape nomme l'entrée
  d'un sous-menu par sa clé de traduction, ou est « 0 ». Le répertoire
  de Mobile y est absent.
La configuration est CONFIG, les préférences celles d'un HOME vide où
l'hôte Proxmox HOST est retenu, le hub web ne tourne pas
(`launcher.status` rend None) et Claude Code n'a aucune session
(`claude_sessions.fleet` rend []). Ce que les menus des familles QEMU,
Proxmox et Assistant lisent du système en se dessinant vient de doubles
(`doubles`) : de faux programmes en tête du PATH, un faux binaire du
cache et son fichier de réglages, la place libre, les manifestes et
leurs miroirs, les fiches des moteurs de conteneurs, les préférences,
les versions d'Odoo, installées et active, qu'Install propose, les
réseaux que la machine porte, et un serveur de modèles qui ne répond
jamais : aucune sonde ne quitte la capture.

    python3 test/todo_menu_golden.py   (depuis la racine du dépôt)

réécrit GOLDEN, que test_todo_menu_golden.py compare au code courant.
"""

import io
import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import patch

REPO = Path(__file__).resolve().parent.parent
GOLDEN = Path(__file__).resolve().parent / "todo_menu_golden.json"
LANGS = ("en", "fr")
MENUS = (
    "prompt_telemetry",
    "prompt_configuration",
    "prompt_execute",
    "prompt_execute_code",
    "debug_ide",
    "prompt_execute_config",
    "generate_config_from_preconfiguration",
    "prompt_execute_process",
    "prompt_execute_test",
    "prompt_execute_update",
    "prompt_execute_instance",
    "prompt_execute_database",
    # Le menu d'effacement vit sur l'objet `db_manager` de TODO.
    "db_manager.drop_database",
    "prompt_execute_analyse",
    "prompt_execute_transform",
    "prompt_execute_doc",
    "prompt_execute_git",
    "prompt_execute_git_local_server",
    "prompt_execute_gpt_code",
    "_prompt_claude_configs",
    "prompt_execute_claude_plugins",
    "prompt_claude_sessions",
    "prompt_execute_rtk",
    "prompt_execute_function",
    "prompt_execute_deploy",
    "prompt_execute_deploy_ssh",
    "prompt_execute_qemu",
    "prompt_execute_qemu_cache",
    "_cache_service",
    "_cache_exceptions",
    "_cache_miroir_git",
    "_cache_age",
    "_cache_tests",
    "_cache_journaux",
    "_cache_nettoyage_auto",
    "prompt_execute_network",
    "prompt_execute_security",
    "prompt_execute_container",
    "_container_service",
    "_container_compose",
    "_container_erplibre",
    "prompt_execute_proxmox",
    "prompt_execute_vpn",
    "prompt_execute_longtest",
    "prompt_install",
    "prompt_assistant",
    "prompt_assistant_llm",
    "_llm_servers",
    "_llm_search",
    # Les menus du courriel sont des fonctions de ce module, qui reçoivent
    # le TODO.
    "script.todo.mail.menu.prompt_execute_mail",
    "script.todo.mail.menu.prompt_mail_accounts",
    "script.todo.mail.menu.prompt_mail_cache",
    "run",
)
CRUMBS = (
    "Navigation telemetry",
    "Configuration",
    "Execute",
    "Code",
    "Config",
    "Process",
    "Test",
    "Update",
    "Run",
    "Database",
    "Analyse",
    "Transform data",
    "Doc",
    "Git",
    "Git local server",
    "Actions",
    "GPT code",
    "Claude configs",
    "Plugins",
    "Claude Code",
    "RTK",
    "Automation",
    "Deploy",
    "SSH",
    "QEMU/KVM",
    "QEMU cache",
    "Service",
    "Exceptions",
    "Git mirrors",
    "Age and cleanup",
    "Tests",
    "Logs",
    "Automatic cleanup",
    "Network",
    "Security",
    "Docker / Podman",
    "Compose",
    "ERPLibre container",
    "Proxmox VE",
    "VPN",
    "Long test",
    # Les menus du courriel n'ont pas de segment : ils s'affichent sous
    # celui d'Assistant.
    "Assistant",
    "LLM",
    "Servers",
    "Search",
    "TODO",
)
ANSWERS = ("", "9", "0")
# Execute montre seize entrées : « 9 » y ouvrirait Git, « 17 » n'en a pas.
# Git en montre neuf avec CONFIG, Plugins neuf : « 9 » y lancerait une
# feuille. Git local server entre dans chacun de ses deux menus Actions,
# qui reçoit une réponse vide et un numéro sans entrée, puis en sort.
# Deploy en montre dix, SSH onze, QEMU/KVM vingt-deux avec CONFIG, QEMU
# cache douze, Docker / Podman treize, Proxmox VE vingt avec CONFIG, VPN
# onze, Long test dix : « 9 » y lancerait une entrée. Search en montre
# huit avec les deux réseaux de NETWORKS : « 9 » n'y est pas.
ANSWERS_OF = {
    "prompt_execute": ("", "17", "0"),
    "prompt_execute_git": ("", "10", "0"),
    "prompt_execute_git_local_server": (
        *("", "9"),
        *("1", "", "9", "0"),
        *("2", "", "9", "0"),
        "0",
    ),
    "prompt_execute_claude_plugins": ("", "10", "0"),
    "prompt_execute_deploy": ("", "11", "0"),
    "prompt_execute_deploy_ssh": ("", "12", "0"),
    "prompt_execute_qemu": ("", "23", "0"),
    "prompt_execute_qemu_cache": ("", "13", "0"),
    "prompt_execute_container": ("", "14", "0"),
    "prompt_execute_proxmox": ("", "21", "0"),
    "prompt_execute_vpn": ("", "12", "0"),
    "prompt_execute_longtest": ("", "11", "0"),
}
# Install pose ses questions par `input` : « n » à la première
# installation du système, puis, au choix de la version, une réponse
# vide, une touche qu'il ne montre pas, et 0.
INPUTS = {"prompt_install": ("n", "", "x", "0")}
# Largeur au-delà de laquelle le fichier de référence ouvre une liste ou
# un dict, un élément par ligne.
WIDTH = 200
CONFIG = {
    "code_from_makefile": [
        {
            "prompt_description_key": "Show code status",
            "makefile_cmd": "forged_status",
        },
        {"prompt_description": "Forged code", "makefile_cmd": "forged"},
    ],
    "update_from_makefile": [
        {
            "prompt_description_key": (
                "Update all erplibre_base on database test"
            ),
            "makefile_cmd": "forged_update_all",
            "database": "forged",
        },
        {"prompt_description": "Forged update", "makefile_cmd": "forged"},
    ],
    "instance": [
        {
            "prompt_description_key": "Test - Minimal base instance",
            "makefile_cmd": "forged_test",
            "database": "forged",
        },
        {"prompt_description": "Forged instance", "makefile_cmd": "forged"},
    ],
    "git_from_makefile": [
        {
            "prompt_description_key": "Configure git local editor to vim",
            "bash_command": "forged_editor",
        },
        {"prompt_description": "Forged git", "bash_command": "forged"},
    ],
    "function": [
        {
            "prompt_description_key": "Open ERPLibre with TODO 🤖",
            "command": "forged_command",
        },
        {"prompt_description": "Forged function", "command": "forged"},
    ],
    # Une section dans la liste : elle s'affiche sans prendre de numéro.
    "qemu_from_makefile": [
        {
            "prompt_description_key": (
                "QEMU - Sample dry-run (demo-vm, Ubuntu 24.04)"
            ),
            "bash_command": "forged_dry_run",
        },
        {"section": "Forged section"},
        {"prompt_description": "Forged QEMU", "bash_command": "forged"},
    ],
    "proxmox_from_makefile": [
        {"prompt_description": "Forged Proxmox", "bash_command": "forged"},
        {"section": "Forged section"},
        {"prompt_description": "Forged Proxmox two", "bash_command": "forged"},
    ],
    # Deux serveurs de modèles connus : LLM les compte, Servers les liste.
    "assistant": {
        "servers": [
            {
                "label": "Forged one",
                "host": "192.0.2.27",
                "port": 11434,
                "software": "ollama",
                "model": "forged:7b",
                "hosting": "lan",
            },
            {
                "label": "Forged two",
                "host": "198.51.100.5",
                "port": 8080,
                "software": "llamacpp",
                "hosting": "lan",
            },
        ]
    },
}
WALK = (
    ["Configuration"],
    "0",
    ["Navigation telemetry"],
    "0",
    ["Execute"],
    ["Code - Developer tools"],
    ["Update - Update all developed staging source code"],
    "0",
    "0",
    ["Config - Configuration file management"],
    "0",
    ["Process - Execution tools"],
    "0",
    ["Test - Test an Odoo module"],
    "0",
    ["Run - Execute and install an instance"],
    "0",
    ["Database - Database tools"],
    "0",
    ["Analyse - Odoo database analysis"],
    "0",
    ["Transform data - Transform your data"],
    "0",
    ["Doc - Documentation search"],
    "0",
    ["Git - Git and shell tools"],
    ["Local git server"],
    ["Deploy a local git server (~/.git-server)"],
    "0",
    ["Deploy a production git server (/srv/git, root required)"],
    "0",
    "0",
    "0",
    ["GPT code - AI assistant tools"],
    ["Configure Claude Code configurations"],
    "0",
    ["RTK - CLI proxy to reduce LLM token consumption"],
    "0",
    ["Claude Code plugins - marketplaces and ERPLibre list"],
    "0",
    ["Claude Code - local sessions"],
    "0",
    "0",
    ["Automation - Demonstration of developed features"],
    "0",
    ["Deploy - Deploy ERPLibre locally"],
    ["SSH (remote host)..."],
    "0",
    ["QEMU/KVM - Deploy an Ubuntu VM (libvirt)"],
    "0",
    ["QEMU cache - Download mirror for local VMs"],
    ["Cache - Service state"],
    "0",
    ["Cache - VMs kept out of the cache"],
    "0",
    ["Cache - Git mirrors: fill them ahead"],
    "0",
    ["Cache - Age and cleanup"],
    "0",
    ["Cache - Tests and performance report"],
    "0",
    ["Cache - Logs"],
    "0",
    ["Cache - Automatic cleanup"],
    "0",
    "0",
    "0",
    ["Network - Network tools"],
    "0",
    ["Security - Dependency security audit"],
    "0",
    ["Docker / Podman - Container engines"],
    ["Service - start, stop, enable at boot, journal"],
    "0",
    ["Compose - start, stop, logs, processes"],
    "0",
    ["ERPLibre container - shell, databases, tests, status"],
    "0",
    "0",
    ["Deploy - Deploy ERPLibre locally"],
    ["Proxmox VE - Deploy a VM on a remote host"],
    "0",
    ["VPN - Tunnels (L2TP/IPsec, WireGuard, OpenVPN...)"],
    "0",
    "0",
    ["Test - Test an Odoo module"],
    ["Long tests - real VMs, hours"],
    "0",
    "0",
    "0",
    ["Assistant"],
    ["AI question - Ask a model, local or remote"],
    ["Known servers"],
    "0",
    ["Search for a server…"],
    "0",
    "0",
    ["mail_menu"],
    ["mail_accounts_menu"],
    "0",
    ["mail_cache_menu"],
    "0",
    "0",
    "0",
    "0",
)
# Les programmes que les menus des familles QEMU et Proxmox lancent en se
# dessinant, et ceux que lancent leurs feuilles, qu'une capture n'atteint
# pas même si une réponse en choisissait une. Chaque faux rend 1 sans rien
# écrire : un service arrêté et pas au démarrage, aucune VM, une lecture
# de nft impossible, aucun PyCharm pour Install ; QEMU/KVM trouve virsh,
# ERPLibre container trouve docker.
STUBS = (
    "curl",
    "docker",
    "ip",
    "iptables",
    "journalctl",
    "nft",
    "openvpn",
    "pct",
    "podman",
    "psql",
    "pvesh",
    "qemu-img",
    "qemu-system-aarch64",
    "qemu-system-s390x",
    "qemu-system-x86_64",
    "qm",
    "rsync",
    "scp",
    "ssh",
    "sudo",
    "systemctl",
    "virsh",
    "wg",
    "wg-quick",
    "which",
)
# Le faux binaire du cache : l'exception d'une VM qui n'existe plus, et
# l'occupation des miroirs, dans la langue que le menu lit.
CACHE_BIN = """#!/bin/sh
case "$*" in
*--bypass-list*) echo "52:54:00:0f:0e:0d forged-vm" ;;
*--status*) echo "dépôts git : 2 dépôts, 1,5 Gio" ;;
esac
"""
CACHE_CONF = "EL_ACCESS_LOG=/forged/cache/access.log\nEL_PURGE_AGE=30j\n"
# Docker répond sans sudo, en mode sans privilège ; Podman est absent : le
# menu Service ne demande pas quel moteur piloter.
FICHES = (
    {
        "moteur": "docker",
        "binaire": "/forged/bin/docker",
        "version": "forged",
        "sans_sudo": True,
        "avec_sudo": False,
        "raison": "",
        "rootless": True,
        "compose": ["docker", "compose"],
        "service": True,
        "socket": None,
        "docker_host": None,
    },
    {
        "moteur": "podman",
        "binaire": None,
        "version": None,
        "sans_sudo": False,
        "avec_sudo": False,
        "raison": "",
        "rootless": None,
        "compose": None,
        "service": None,
        "socket": None,
        "docker_host": None,
    },
)
# L'hôte Proxmox retenu : Proxmox VE s'ouvre sur lui sans rien demander.
HOST = {"target": "root@forged-pve", "jump": "forged-jump", "version": "9.9"}
# Les versions qu'Install propose, la 18.0 active et par défaut, la 17.0
# installée, la 16.0 dépréciée.
VERSIONS = {
    "odoo16.0_forged": {"odoo_version": "16.0", "is_deprecated": True},
    "odoo17.0_forged": {"odoo_version": "17.0"},
    "odoo18.0_forged": {"odoo_version": "18.0", "default": True},
}
# Les réseaux que la machine porte, qu'offre Search : un réseau local et
# un pont de virtualisation, (interface, préfixe, pont).
NETWORKS = (
    ("forged0", "192.0.2.0/24", False),
    ("virbr-forged", "198.51.100.0/24", True),
)

# Le vrai TODO sous la capture, dans l'ordre du worker : urwid, la
# capture, puis `import todo` en mode script. argv : la langue, WALK en
# JSON, le todo.json à lire, le fichier du rapport.
SESSION = r"""
import json, os, sys
import click
import urwid
from script.config import config_file
from script.todo import todo_i18n, todo_telemetry
from script.todo.assistant import claude_sessions
from script.todo.ui import legacy, port
from script.todo.web import launcher

lang, walk, config, report = sys.argv[1:5]
todo_i18n.use_lang(lang)
config_file.CONFIG_FILE = config
config_file.CONFIG_OVERRIDE_FILE = config + ".absent"
config_file.CONFIG_OVERRIDE_PRIVATE_FILE = config + ".absent"
launcher.status = lambda root: None
claude_sessions.fleet = lambda **kwargs: []
keys = []
todo_telemetry.record = keys.append


class Walk(port.ScriptedPort):
    # Une étape [clé] répond l'entrée dont le libellé est t(clé), suivi ou
    # non de ce qu'y ajoute un suffixe, « (…) » après deux espaces ; une
    # question qui n'est pas un menu arrête tout. Une entrée absente aussi,
    # par une EOFError qui nomme la clé, gardée dans `lost`.
    lost = None

    def _answer(self, message):
        if message["t"] != "menu" or not self.answers:
            self.answers = [EOFError(message.get("text"))]
        elif isinstance(self.answers[0], list):
            key = self.answers[0][0]
            label = todo_i18n.t(key)
            found = [
                item["key"]
                for item in message["items"]
                if item["label"] == label
                or item["label"].startswith(f"{label}  (")
            ]
            if not found:
                self.lost = key
            self.answers[0] = found[0] if found else EOFError(key)
        return super()._answer(message)


scripted = Walk(json.loads(walk))
legacy.install(scripted)
sys.path.insert(0, "test")
import todo_menu_golden as golden
for double in golden.doubles(golden.Path(config).parent / "system"):
    double.start()
sys.path.insert(0, os.path.join(os.getcwd(), "script", "todo"))
import todo
todo.lang_is_configured = lambda: True
todo.MOBILE_HOME_PATH = config + ".absent"
legacy.wrap_menus(todo.TODO)
# Le rapport s'écrit aussi quand TODO sort par SystemExit.
try:
    todo.TODO().run()
except (EOFError, click.exceptions.Abort):
    pass
finally:
    with open(report, "w") as out:
        json.dump(
            {"events": scripted.events, "keys": keys, "lost": scripted.lost},
            out,
        )
"""


def doubles(base) -> list:
    """Écrit sous `base` un faux de chaque programme de STUBS, dans
    `base / "stubs"`, que le PATH doit nommer en tête, le faux binaire du
    cache et son fichier de réglages, les préférences où HOST est retenu,
    et les versions de VERSIONS, installées et active ; rend les patchers,
    à démarrer, qui y mènent les menus des familles QEMU et Proxmox et
    doublent la place libre, les manifestes et leurs miroirs, les fiches
    des moteurs de conteneurs, les réseaux de NETWORKS, et la collecte des
    réponses d'un serveur de modèles, qui ne rend rien et n'ouvre aucune
    connexion.
    """
    from script.todo.assistant.discover import Interface

    stubs = base / "stubs"
    stubs.mkdir(parents=True)
    for name in STUBS:
        (stubs / name).write_text("#!/bin/sh\nexit 1\n")
        (stubs / name).chmod(0o755)
    (base / "erplibre_go_qemu_cache").write_text(CACHE_BIN)
    (base / "erplibre_go_qemu_cache").chmod(0o755)
    (base / "cache.env").write_text(CACHE_CONF)
    (base / "todo_prefs.json").write_text(json.dumps({"proxmox_host": HOST}))
    (base / "versions.json").write_text(json.dumps(VERSIONS))
    (base / "installed.txt").write_text("odoo17.0\nodoo18.0\n")
    (base / "odoo-version").write_text("18.0\n")

    def depots(racine, version="", fichiers=None):
        # Un dépôt pour l'extra d'une version, trois pour sa base, cinq
        # pour tous les manifestes.
        count = 1 if fichiers else 3 if version else 5
        return [f"https://forge.invalid/forged_{n}.git" for n in range(count)]

    menu = "script.todo.qemu_cache_menu"
    return [
        patch(f"{menu}.CACHE_BIN", str(base / "erplibre_go_qemu_cache")),
        patch(f"{menu}.CACHE_CONF", str(base / "cache.env")),
        patch(
            f"{menu}.QemuCacheMenuMixin._cache_place_libre",
            staticmethod(lambda: "12.0 Gio"),
        ),
        patch(f"{menu}.version_active", lambda racine: "18.0"),
        patch(f"{menu}.depots_des_manifestes", depots),
        patch(
            "script.qemu.cache_offline.miroirs_absents",
            lambda depots, racine="": list(depots)[:1],
        ),
        patch(
            "script.todo.container_runtime.etats",
            lambda lanceur=None: [dict(fiche) for fiche in FICHES],
        ),
        patch(
            "script.todo.todo_prefs._path", lambda: base / "todo_prefs.json"
        ),
        patch(
            "script.todo.version_manager.VERSION_DATA_FILE",
            str(base / "versions.json"),
        ),
        patch(
            "script.todo.version_manager.INSTALLED_ODOO_VERSION_FILE",
            str(base / "installed.txt"),
        ),
        patch(
            "script.todo.version_manager.ODOO_VERSION_FILE",
            str(base / "odoo-version"),
        ),
        patch(
            "script.todo.assistant.discover.local_networks",
            lambda run=None: [Interface(*network) for network in NETWORKS],
        ),
        patch(
            "script.todo.assistant.fingerprint.collect",
            lambda host, port, **kwargs: {},
        ),
    ]


def _environment(base) -> dict:
    """L'environnement d'un TODO lancé à part : HOME et XDG_RUNTIME_DIR
    sous `base`, sans affichage ni canal de session web, les faux
    programmes de `doubles` en tête du PATH."""
    env = dict(os.environ, HOME=str(base / "home"))
    env["XDG_RUNTIME_DIR"] = str(base / "run")
    env["PATH"] = f"{base / 'system' / 'stubs'}{os.pathsep}{env['PATH']}"
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "TODO_WEB_FD", "TODO_WEB_PID"):
        env.pop(name, None)
    (base / "home").mkdir()
    (base / "run").mkdir(mode=0o700)
    return env


def terminal(method, lang) -> dict:
    """Ce que montre `TODO().<method>()`, en `lang`, quand il reçoit ses
    réponses, INPUTS[method] à `input`, sinon ANSWERS_OF[method] ou ANSWERS
    à `click.prompt` : `screen`, ses lignes ; `back`,
    ce qu'il rend ; `keys`, les clés de télémétrie enregistrées ; `probes`,
    les sondes du hub web. `method` peut être pointé : « a.b » appelle la
    méthode `b` de l'attribut `a` de TODO, « script.….f » la fonction `f`
    de ce module, avec le TODO. Le répertoire de Mobile est présent, la
    langue tenue pour choisie."""
    import importlib

    from script.config import config_file
    from script.todo import todo, todo_i18n
    from script.todo.todo import TODO
    from script.todo.web import launcher

    answers = INPUTS.get(method) or ANSWERS_OF.get(method, ANSWERS)
    shown, answers = io.StringIO(), iter(answers)

    def typed(prompt):
        # L'invite, puis la réponse et le saut de ligne que le terminal
        # fait écho.
        answer = next(answers)
        shown.write(f"{prompt}{answer}\n")
        return answer

    with ExitStack() as stack:
        saved = todo_i18n._current_lang
        stack.callback(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang(lang)
        base = Path(stack.enter_context(tempfile.TemporaryDirectory()))
        (base / "todo.json").write_text(json.dumps(CONFIG))
        absent = str(base / "absent.json")
        stubs = f"{base / 'system' / 'stubs'}{os.pathsep}{os.environ['PATH']}"
        for patcher in (
            patch.dict(os.environ, {"HOME": str(base), "PATH": stubs}),
            *doubles(base / "system"),
            patch.object(config_file, "CONFIG_FILE", str(base / "todo.json")),
            patch.object(config_file, "CONFIG_OVERRIDE_FILE", absent),
            patch.object(config_file, "CONFIG_OVERRIDE_PRIVATE_FILE", absent),
            patch.object(todo, "MOBILE_HOME_PATH", str(base)),
            patch.object(todo, "lang_is_configured", return_value=True),
            patch("click.termui.visible_prompt_func", typed),
            # Un menu qui lirait le terminal bloquerait le test : `input`,
            # sauf pour un menu d'INPUTS, une question masquée
            # (`click.prompt(hide_input=True)`, `getpass`) lèvent, et
            # l'entrée standard est vide.
            patch("builtins.input", typed)
            if method in INPUTS
            else patch("builtins.input", side_effect=AssertionError("input")),
            patch(
                "click.termui.hidden_prompt_func",
                side_effect=AssertionError("hidden_prompt_func"),
            ),
            patch("getpass.getpass", side_effect=AssertionError("getpass")),
            patch.object(sys, "stdin", io.StringIO()),
            # Claude Code lit sa flotte par `claude agents` : aucune
            # session, comme sur une machine sans Claude Code.
            patch(
                "script.todo.assistant.claude_sessions.fleet", return_value=[]
            ),
        ):
            stack.enter_context(patcher)
        probe = stack.enter_context(
            patch.object(launcher, "status", return_value=None)
        )
        record = stack.enter_context(
            patch("script.todo.todo_telemetry.record")
        )
        stack.enter_context(redirect_stdout(shown))
        target = TODO()
        if method.startswith("script."):
            module, _, name = method.rpartition(".")
            function = getattr(importlib.import_module(module), name)
            back = function(target)
        else:
            for name in method.split("."):
                target = getattr(target, name)
            back = target()
    return {
        "screen": shown.getvalue().split("\n"),
        "back": back,
        "keys": [call.args[0] for call in record.call_args_list],
        "probes": probe.call_count,
    }


def session(lang) -> dict:
    """Ce que voit la capture de la session web quand le vrai TODO, en
    `lang`, suit WALK : `crumbs`, le fil d'Ariane de chaque menu traversé ;
    `menus`, les messages `menu` des menus de CRUMBS, dans l'ordre ; `keys`,
    les clés de télémétrie enregistrées. EOFError, qui nomme sa clé, pour une
    étape de WALK dont le menu n'a pas l'entrée."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        config = base / "todo.json"
        config.write_text(json.dumps(CONFIG))
        report = base / "report.json"
        result = subprocess.run(
            [sys.executable, "-c", SESSION, lang, json.dumps(WALK)]
            + [str(config), str(report)],
            cwd=REPO,
            env=_environment(base),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        seen = json.loads(report.read_text())
    if seen["lost"] is not None:
        raise EOFError(f"no menu entry for the WALK step {seen['lost']!r}")
    menus = [event for event in seen["events"] if event["t"] == "menu"]
    return {
        "crumbs": [" › ".join(menu["crumbs"]) for menu in menus],
        "menus": [menu for menu in menus if menu["crumbs"][-1] in CRUMBS],
        "keys": seen["keys"],
    }


def capture() -> dict:
    return {
        "terminal": {
            lang: {method: terminal(method, lang) for method in MENUS}
            for lang in LANGS
        },
        "session": {lang: session(lang) for lang in LANGS},
    }


def dump(value, depth=0) -> str:
    """JSON de `value`, clés triées : une liste ou un dict tient sur une
    ligne s'il y tient en WIDTH caractères, retrait compris ; sinon un
    élément par ligne, en retrait de deux espaces."""
    flat = json.dumps(value, ensure_ascii=False, sort_keys=True)
    if not isinstance(value, (dict, list)) or len(flat) + depth <= WIDTH:
        return flat
    pad = "  " * (depth + 1)
    if isinstance(value, dict):
        lines = [
            f"{pad}{json.dumps(key, ensure_ascii=False)}: "
            + dump(value[key], depth + 1)
            for key in sorted(value)
        ]
        opening, closing = "{", "}"
    else:
        lines = [pad + dump(item, depth + 1) for item in value]
        opening, closing = "[", "]"
    return f"{opening}\n" + ",\n".join(lines) + f"\n{'  ' * depth}{closing}"


if __name__ == "__main__":
    GOLDEN.write_text(dump(capture()) + "\n", encoding="utf-8")
    print(GOLDEN)
