#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Télémétrie de navigation du CLI TODO.

Enregistre les fils d'Ariane visités (« A › B › C » -> compteur) et affiche un
DIAGRAMME arborescent des fonctionnalités dans un TUI Textual, trié par usage.

- record(path) : appelé par Todo._menu_header à chaque affichage de menu ; on
  dédupe les ré-affichages consécutifs pour ne compter que les TRANSITIONS.
- run_tui() : ouvre l'arbre de navigation (compteurs par menu).
"""

from __future__ import annotations

import ast
import asyncio
import glob
import json
import logging
import os
import shutil
import subprocess
import time
from pathlib import Path

from script.todo import json_store

log = logging.getLogger(__name__)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# Dernier chemin enregistré : évite de recompter chaque ré-affichage du même
# menu (une commande qui revient au menu ne compte pas comme une navigation).
_LAST = [None]


def _path() -> Path:
    base = Path(os.path.expanduser("~/.erplibre"))
    base.mkdir(parents=True, exist_ok=True)
    return base / "todo_telemetry.json"


def _empty() -> dict:
    return {"paths": {}}


def load() -> dict:
    # _path() crée ~/.erplibre et peut lever OSError (répertoire parent en
    # lecture seule) : la télémétrie rend alors un magasin vide.
    try:
        data = json_store.read(_path(), _empty)
    except OSError:
        return _empty()
    return data if isinstance(data, dict) else _empty()


def _save(data: dict) -> None:
    try:
        json_store.write(_path(), data)
    except OSError:
        pass


def record(path: str) -> None:
    """Incrémente le compteur du menu `path`. Best-effort : ne lève jamais
    (la télémétrie ne doit jamais casser la navigation). Lecture et écriture
    se font sous un même verrou : deux processus TODO ne perdent aucun
    incrément."""
    if not path or path == _LAST[0]:
        return
    _LAST[0] = path

    def bump(data):
        if not isinstance(data, dict):
            data = _empty()
        paths = data.setdefault("paths", {})
        paths[path] = paths.get(path, 0) + 1
        data["updated"] = int(time.time())
        return data

    try:
        json_store.update(_path(), bump, _empty)
    except Exception:
        pass


def reset() -> None:
    _save(_empty())


def _nested(paths: dict) -> dict:
    """{« A › B › C »: count} -> arbre {nom: {'count', 'children'}}. Chaque
    menu enregistre son propre chemin, donc chaque nœud a son compteur."""
    root: dict = {}
    for path, count in paths.items():
        cur = root
        parts = path.split(" › ")
        for i, name in enumerate(parts):
            node = cur.setdefault(name, {"count": 0, "children": {}})
            if i == len(parts) - 1:
                node["count"] += count
            cur = node["children"]
    return root


# --------------------------------------------------------------------------- #
# L'arbre des menus, lu dans leurs déclarations (`menus/*.py`)
# --------------------------------------------------------------------------- #
def _config_list(config_key, todo_dir):
    """Entrées d'une liste de config de todo.json (ex. « code_from_makefile »),
    cherchée à n'importe quel niveau. [] si absente."""
    try:
        data = json.loads(
            (Path(todo_dir) / "todo.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return []
    found = []

    def walk(o):
        if isinstance(o, dict):
            for k, v in o.items():
                if k == config_key and isinstance(v, list):
                    found.extend(v)
                walk(v)
        elif isinstance(o, list):
            for x in o:
                walk(x)

    walk(data)
    return found


def _registry_fields(registry_py) -> dict:
    """{constructeur: [champ, …]} des classes de `registry_py`, le module du
    registre, leurs champs annotés dans l'ordre : le nom de chaque argument
    positionnel d'un fichier de menus. {} si le fichier ne se lit pas."""
    try:
        mod = ast.parse(Path(registry_py).read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}
    return {
        cls.name: [
            stmt.target.id
            for stmt in cls.body
            if isinstance(stmt, ast.AnnAssign)
            and isinstance(stmt.target, ast.Name)
        ]
        for cls in mod.body
        if isinstance(cls, ast.ClassDef)
    }


def _declared(node, fields):
    """Valeur de `node`, une expression d'un fichier de menus : l'appel
    d'un constructeur de `fields`, rendu en dict {"type": constructeur,
    champ: valeur, …}, une liste, ou un littéral. ValueError pour toute
    autre expression : un fichier de menus ne calcule rien."""
    if isinstance(node, ast.Call):
        name = node.func.id if isinstance(node.func, ast.Name) else None
        names = fields.get(name)
        if names is None or len(node.args) > len(names):
            raise ValueError(f"not a registry call: {ast.unparse(node)}")
        out = {"type": name}
        for field, arg in zip(names, node.args):
            out[field] = _declared(arg, fields)
        for keyword in node.keywords:
            if keyword.arg not in names:
                raise ValueError(f"no field {keyword.arg!r} in {name}")
            out[keyword.arg] = _declared(keyword.value, fields)
        return out
    if isinstance(node, ast.List):
        return [_declared(element, fields) for element in node.elts]
    return ast.literal_eval(node)


# Champs texte que lisent l'arbre et le navigateur, par constructeur, en
# trois groupes : ceux qu'un appel doit donner, faute de valeur par défaut
# au registre ; ceux qui peuvent valoir None ; ceux qui ont une valeur
# par défaut qui n'est pas None. Un champ donné est une chaîne, ou None
# s'il est du deuxième groupe ; un champ non donné prend sa valeur par
# défaut. `crumb`, sans valeur par défaut, se donne, et peut valoir None.
_TEXT_FIELDS = {
    "Menu": (
        ("name", "crumb"),
        ("crumb", "state", "intro", "opens", "before", "asks"),
        ("mark",),
    ),
    "Section": (("key",), (), ()),
    "Entry": (("key", "action"), ("suffix", "when", "hotkey", "crumb"), ()),
    "FromConfig": (("config_key", "action", "kwarg"), (), ()),
    "FromMethod": (("method", "action", "kwarg"), (), ()),
}


def _check_menu(menu) -> None:
    """ValueError si `menu`, le dict que `_declared` rend d'un appel de
    `Menu`, n'a pas la forme que lisent l'arbre et le navigateur : chaque
    champ de _TEXT_FIELDS donné s'il doit l'être, et une chaîne, ou None
    là où _TEXT_FIELDS le permet ; `entries` une liste de Section, Entry,
    FromConfig et FromMethod, les `kwargs` d'une Entry None ou un dict aux
    clés de chaîne, son `danger` None ou un booléen. TypeError si ces
    `kwargs` ne s'écrivent pas en JSON, comme l'arbre que sert le hub."""
    entries = menu.get("entries")
    if not isinstance(entries, list):
        raise ValueError(f"entries is not a list: {entries!r}")
    for item in [menu, *entries]:
        kind = item.get("type") if isinstance(item, dict) else None
        kinds = ("Menu",)
        if item is not menu:
            kinds = ("Section", "Entry", "FromConfig", "FromMethod")
        if kind not in kinds:
            raise ValueError(f"not one of {kinds}: {item!r}")
        required, nullable, defaulted = _TEXT_FIELDS[kind]
        for field in required + nullable + defaulted:
            if field not in item:
                if field in required:
                    raise ValueError(f"{kind}.{field} is missing")
                continue
            value = item[field]
            if not (
                isinstance(value, str) or (value is None and field in nullable)
            ):
                raise ValueError(f"{kind}.{field} is not a string: {value!r}")
        kwargs = item.get("kwargs")
        if kwargs is not None and not (
            isinstance(kwargs, dict)
            and all(isinstance(k, str) for k in kwargs)
        ):
            raise ValueError(f"kwargs is not a dict of names: {kwargs!r}")
        json.dumps(kwargs)
        danger = item.get("danger")
        if danger is not None and not isinstance(danger, bool):
            raise ValueError(f"danger is not a boolean: {danger!r}")


def _declared_menus(todo_dir, failed=None) -> dict:
    """{méthode: menu} des menus que déclarent `<todo_dir>/menus/*.py`, un
    menu étant le dict que `_declared` rend d'un appel de `Menu`. Lus par
    AST, sans rien importer : le hub, qui garde ses modules, lit toujours
    les fichiers tels qu'ils sont sur le disque. Un fichier qui ne se lit
    pas, dont une valeur se calcule, ou dont un menu n'a pas la forme que
    vérifie `_check_menu`, ne déclare rien : un avertissement du journal
    nomme le fichier et l'erreur, la liste `failed`, quand elle est
    donnée, reçoit son chemin, et rien ne lève."""
    todo_dir = Path(todo_dir)
    fields = _registry_fields(todo_dir / "ui" / "registry.py")
    menus = {}
    for path in sorted(todo_dir.glob("menus/*.py")):
        found = {}
        try:
            mod = ast.parse(path.read_text(encoding="utf-8"))
            for stmt in mod.body:
                if not isinstance(stmt, ast.Assign):
                    continue
                value = _declared(stmt.value, fields)
                if isinstance(value, dict) and value["type"] == "Menu":
                    _check_menu(value)
                    found[value["name"]] = value
        except (OSError, SyntaxError, TypeError, ValueError) as error:
            log.warning(
                "%s declares no menu: %s: %s",
                path,
                type(error).__name__,
                error,
            )
            if failed is not None:
                failed.append(path)
            continue
        menus.update(found)
    return menus


def _declared_children(menu, todo_dir, labels, build) -> list:
    """Nœuds des entrées de `menu`, un menu déclaré : le nœud de `build`
    pour une `Entry` qui ouvre un menu de `labels`, une feuille pour une
    autre, une feuille par élément de la liste d'un `FromConfig`, sauf un
    élément qui porte une section, qui nomme celle des suivants. Une
    entrée dont le libellé finit par un `suffix` calculé à l'affichage
    porte un `entry` vide : aucune entrée du menu ne s'écrit comme elle.
    Le nœud d'une `Entry` déclarée `danger=True` porte "danger": True ;
    ni la TUI ni la page web ne le lancent. Une feuille gardée (`when`) y
    est, quoi que rende sa garde, mais sans méthode : seul son menu lit
    la garde, et la TUI, qui lance une feuille par sa méthode, ne la
    lance pas. La garde ne protège qu'une feuille : une entrée gardée qui
    ouvre un menu de `labels` porte le nœud de `build`, dont les feuilles
    gardent leur méthode, et la TUI les lance quoi que rende la garde. Un
    `FromMethod` n'y donne aucune feuille : sa liste ne se lit qu'en
    appelant sa méthode. Chaque enfant d'un menu `asks` porte un `entry`
    vide : sa question n'est pas un message `menu`, où la page web
    chercherait l'entrée qu'elle répond. Une `Entry` qui n'ouvre pas un
    menu de `labels` mais déclare un segment (`crumb`) donne un menu sans
    feuille, sous ce segment, que ni la TUI ni la page web ne lancent."""
    children, section = [], None
    for item in menu.get("entries") or []:
        kind = item.get("type") if isinstance(item, dict) else None
        if kind == "Section":
            section = item.get("key")
        elif kind == "Entry" and (
            item.get("action") in labels or item.get("crumb")
        ):
            if item.get("action") in labels:
                child = build(item["action"])
            else:
                child = {
                    "label": item["crumb"],
                    "is_menu": True,
                    "children": [],
                }
            child["entry"] = "" if item.get("suffix") else item.get("key")
            if item.get("danger"):
                child["danger"] = True
            children.append(child)
        elif kind == "Entry":
            leaf = {
                "label": item.get("key"),
                "is_menu": False,
                "children": [],
                "method": None if item.get("when") else item.get("action"),
                "kwargs": dict(item.get("kwargs") or {}),
                "section": section,
            }
            if item.get("suffix"):
                leaf["entry"] = ""
            if item.get("danger"):
                leaf["danger"] = True
            children.append(leaf)
        elif kind == "FromConfig":
            for element in _config_list(item.get("config_key"), todo_dir):
                if element.get("section"):
                    section = element["section"]
                    continue
                children.append(
                    {
                        "label": element.get("prompt_description_key")
                        or element.get("prompt_description")
                        or "?",
                        "is_menu": False,
                        "children": [],
                        "method": item.get("action"),
                        "kwargs": {item.get("kwarg"): element},
                        "section": section,
                    }
                )
    if menu.get("asks"):
        for child in children:
            child["entry"] = ""
    return children


def build_code_tree(todo_path=None) -> dict | None:
    """L'arbre des menus de TODO, lu dans les menus que déclarent les
    fichiers `menus/*.py` du répertoire de `todo_path` (todo.py, qui ne se
    lit pas ; par défaut celui de ce paquet), avec le module du registre et
    todo.json : rien n'est importé ni appelé. La racine est le menu que
    `run` ouvre ; une `Entry` dont l'action est le `name` d'un menu déclaré
    qui a un segment ouvre ce menu, et son nœud porte ce segment
    (`_declared_children`). Un menu qui se contient lui-même n'est
    développé qu'une fois par chemin. None sans menu déclaré de `run`, ou
    dès qu'un fichier de menus ne déclare rien : l'entrée qui ouvre l'un
    de ses menus y serait une feuille, que la TUI lancerait."""
    todo_dir = Path(todo_path).parent if todo_path else Path(__file__).parent
    failed = []
    declared = _declared_menus(todo_dir, failed)
    labels = {
        name: menu["crumb"] for name, menu in declared.items() if menu["crumb"]
    }
    if failed or "run" not in labels:
        return None
    seen = set()

    def build(method):
        node = {"label": labels[method], "is_menu": True, "children": []}
        if method in seen:
            return node
        seen.add(method)
        node["children"] = _declared_children(
            declared[method], todo_dir, labels, build
        )
        seen.discard(method)
        return node

    return build("run")


def _command_columns(tree, paths):
    """Colonnes du Kanban : (label, chemin, count, [commandes]) pour CHAQUE
    menu qui contient des commandes directes (parcours profondeur d'abord)."""
    cols = []

    def walk(node, path):
        cmds = [c for c in node["children"] if not c["is_menu"]]
        if cmds:
            cols.append((node["label"], path, paths.get(path, 0), cmds))
        for c in node["children"]:
            if c["is_menu"]:
                walk(c, f"{path} › {c['label']}")

    if tree:
        walk(tree, "TODO")
    return cols


# --------------------------------------------------------------------------- #
# Télémétrie SYSTÈME (vue F2)
# --------------------------------------------------------------------------- #
def sensors_install_command():
    """Commande d'installation de lm-sensors, ou None si aucun gestionnaire
    de paquets connu.

    Le paquet change de nom : « lm-sensors » chez Debian, « lm_sensors »
    ailleurs. Cette écriture-ci ne connaissait pas zypper, et openSUSE ne
    pouvait donc pas l'installer."""
    # Importé ici et non en tête : l'import de todo_i18n de ce module est
    # protégé pour qu'il tourne en autonome, et todo_install en dépend.
    from script.todo import todo_install

    return todo_install.install_command(
        {
            "apt-get": ["lm-sensors"],
            "dnf": ["lm_sensors"],
            "pacman": ["lm_sensors"],
            "zypper": ["sensors"],
        }
    )


def _first_int(path):
    try:
        with open(path) as f:
            return int(f.read().strip())
    except (OSError, ValueError):
        return None


def _cpu_sample():
    try:
        with open("/proc/stat") as f:
            vals = [int(x) for x in f.readline().split()[1:]]
        idle = vals[3] + (vals[4] if len(vals) > 4 else 0)
        return idle, sum(vals)
    except (OSError, ValueError, IndexError):
        return None


def _net_sample():
    rx = tx = 0
    try:
        with open("/proc/net/dev") as f:
            for line in f.readlines()[2:]:
                iface, _, rest = line.partition(":")
                if iface.strip() in ("lo", ""):
                    continue
                cols = rest.split()
                if len(cols) >= 9:
                    rx += int(cols[0])
                    tx += int(cols[8])
    except (OSError, ValueError):
        return None
    return rx, tx


def _mem():
    info = {}
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                k, _, v = line.partition(":")
                info[k] = int(v.split()[0]) * 1024
    except (OSError, ValueError):
        return None
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", info.get("MemFree", 0))
    return total, total - avail


def _battery():
    for base in glob.glob("/sys/class/power_supply/BAT*"):
        cap = _first_int(os.path.join(base, "capacity"))
        try:
            with open(os.path.join(base, "status")) as f:
                status = f.read().strip()
        except OSError:
            status = ""
        if cap is not None:
            return cap, status
    return None


def read_temperature():
    """(source, [°C]) ou None. /sys/class/thermal d'abord (sans dépendance),
    puis lm-sensors si présent."""
    temps = []
    for zt in glob.glob("/sys/class/thermal/thermal_zone*/temp"):
        v = _first_int(zt)
        if v and v > 0:
            temps.append(round(v / 1000.0, 1))
    if temps:
        return "sysfs", temps
    if shutil.which("sensors"):
        try:
            out = subprocess.run(
                ["sensors", "-u"], capture_output=True, text=True, timeout=5
            ).stdout
            for line in out.splitlines():
                line = line.strip()
                if "_input:" in line:
                    try:
                        temps.append(round(float(line.split(":")[1]), 1))
                    except (ValueError, IndexError):
                        pass
            temps = [x for x in temps if x > 0]
            if temps:
                return "sensors", temps
        except (OSError, subprocess.SubprocessError):
            pass
    return None


def system_snapshot(prev, full=True):
    """Instantané des métriques système. `prev` = (cpu, net, t) pour calculer
    les taux CPU/réseau par delta. `full=False` saute la température (évite le
    subprocess sensors quand la vue système n'est pas affichée). Renvoie
    (métriques, nouveau_prev)."""
    now = time.time()
    cpu, net = _cpu_sample(), _net_sample()
    pcpu, pnet, pt = prev or (None, None, None)
    m = {}
    if cpu and pcpu and cpu[1] > pcpu[1]:
        m["cpu"] = max(
            0,
            min(
                100, round(100 * (1 - (cpu[0] - pcpu[0]) / (cpu[1] - pcpu[1])))
            ),
        )
    else:
        m["cpu"] = None
    if net and pnet and pt and now > pt:
        dt = now - pt
        m["net"] = ((net[0] - pnet[0]) / dt, (net[1] - pnet[1]) / dt)
    else:
        m["net"] = None
    m["mem"] = _mem()
    try:
        du = shutil.disk_usage("/")
        m["disk"] = (du.total, du.used, du.free)
    except OSError:
        m["disk"] = None
    m["battery"] = _battery()
    m["temp"] = read_temperature() if full else None
    try:
        with open("/proc/uptime") as f:
            m["uptime"] = float(f.read().split()[0])
    except (OSError, ValueError):
        m["uptime"] = None
    try:
        m["load"] = os.getloadavg()
    except OSError:
        m["load"] = None
    m["ncpu"] = os.cpu_count() or 1
    return m, (cpu, net, now)


def _fmt_size(nbytes):
    if nbytes is None:
        return "-"
    for unit, div in (("T", 1 << 40), ("G", 1 << 30), ("M", 1 << 20)):
        if nbytes >= div:
            return f"{nbytes / div:.1f}{unit}"
    return f"{nbytes // 1024}K"


def _fmt_rate(bps):
    if bps is None:
        return "?"
    for unit, div in (("Go/s", 1 << 30), ("Mo/s", 1 << 20), ("Ko/s", 1 << 10)):
        if bps >= div:
            return f"{bps / div:.1f} {unit}"
    return f"{int(bps)} o/s"


def _fmt_uptime(secs):
    if not secs:
        return "?"
    secs = int(secs)
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    mnt = r // 60
    if d:
        return f"{d}j {h}h"
    if h:
        return f"{h}h{mnt:02d}"
    return f"{mnt}min"


# Modes d'affichage du Kanban (F4 les fait défiler).
KANBAN_MODES = ("columns", "swimlanes", "grid")

# Les vues défilent avec F3 ; chaque vue affiche le NOM de la suivante.
VIEWS = ("tree", "kanban", "list")
VIEW_LABELS = {
    "tree": "Arbre",
    "kanban": "Kanban",
    "list": "Liste",
    "system": "Système",
}


def _disp(label: str) -> str:
    """Libellé d'affichage d'une commande : passe par t() pour récupérer la
    traduction ET l'icône (les valeurs i18n portent l'icône). Renvoie le
    libellé inchangé s'il n'est pas une clé de traduction."""
    return t(label) if label else label


_SENTINEL = object()


def _group_by_section(cmds):
    """Itère les commandes en groupes (section, [cmds]) dans l'ordre, la
    section pouvant être None (aucune)."""
    groups, cur, bucket = [], _SENTINEL, []
    for c in cmds:
        sec = c.get("section")
        if sec != cur:
            if bucket:
                groups.append((cur, bucket))
            cur, bucket = sec, []
        bucket.append(c)
    if bucket:
        groups.append((cur, bucket))
    return groups


def run_tui(run_app: bool = True, state: dict | None = None):
    """TUI de télémétrie : vue Arbre (issue du code) et vue Kanban (F3), la
    disposition du Kanban défilant par F4 (colonnes / swimlanes / grille).
    Sélectionner une COMMANDE = l'exécuter, sauf une commande dont le nœud
    porte "danger" : un avis le dit, et la TUI reste ouverte. `state`
    restaure la vue + le curseur au retour. Renvoie (action|None, state) ;
    run_app=False -> l'app.
    """
    from textual.app import App, ComposeResult
    from textual.containers import (
        Container,
        Grid,
        HorizontalScroll,
        Vertical,
        VerticalScroll,
    )
    from textual.widgets import (
        Footer,
        Header,
        Label,
        ListItem,
        ListView,
        Static,
        Tree,
    )

    paths = load().get("paths", {})
    code_tree = build_code_tree()
    columns = _command_columns(code_tree, paths)  # (label, path, cnt, cmds)
    state = state or {}

    class CmdItem(ListItem):
        """Carte : commande à exécuter, son chemin (pour restaurer le
        curseur) et son drapeau `danger`."""

        def __init__(self, label, method, kwargs, path, danger=False):
            super().__init__(Label(label))
            self.cmd_method = method
            self.cmd_kwargs = kwargs or {}
            self.cmd_path = path
            self.cmd_danger = bool(danger)

    class Telemetry(App):
        CSS = """
        #summary { height: 1; color: $text-muted; }
        Tree { border: solid $accent; }
        #kanban { display: none; height: 1fr; }
        #list { display: none; height: 1fr; }
        #system { display: none; height: 1fr; padding: 1 2; }
        .kcol { width: 40; border: solid $accent; margin: 0 1 0 0; }
        .ktitle { height: 1; color: $accent; }
        .ksec { height: 1; color: $secondary; text-style: italic; }
        .listmenu { height: 1; color: $accent; text-style: bold; }
        .listsec { height: 1; color: $secondary; text-style: italic; }
        .lane { height: auto; }
        .lanetitle { height: 1; color: $secondary; }
        .kgrid { grid-size: 3; grid-gutter: 1; }
        .kbig { row-span: 3; }
        """
        BINDINGS = [
            ("q", "quit", "Quitter"),
            ("f2", "system", "Système"),
            ("f3", "toggle_view", "Vue"),
            ("f4", "kanban_layout", "Disposition Kanban"),
            ("e", "expand_all", "Tout déplier"),
            ("i", "install_sensors", "Installer capteurs"),
            ("r", "reset", "Réinitialiser"),
        ]

        def __init__(self):
            super().__init__()
            self._action = None
            self._mode = state.get("mode", "tree")
            self._kanban_mode = state.get("kanban_mode", "columns")
            self._sys_prev = None

        # -- helpers de construction de widgets ------------------------------ #
        def _col_widget(self, label, cnt, cmds):
            # Regroupe par section pour aider au choix ; icônes via _disp().
            children = [Static(f"{label}  ({cnt})", classes="ktitle")]
            for section, group in _group_by_section(cmds):
                if section:
                    children.append(
                        Static(f"── {_disp(section)} ──", classes="ksec")
                    )
                children.append(
                    ListView(
                        *[
                            CmdItem(
                                f"· {_disp(c['label'])}",
                                c.get("method"),
                                c.get("kwargs"),
                                c.get("path"),
                                c.get("danger"),
                            )
                            for c in group
                        ]
                    )
                )
            return VerticalScroll(*children, classes="kcol")

        def _list_view_widget(self):
            # Vue Liste : tous les menus empilés verticalement, chaque menu
            # avec ses sections et ses commandes (icônes), pour aider le choix.
            blocks = []
            for label, path, cnt, cmds in columns:
                blocks.append(Static(f"▸ {path}  ({cnt})", classes="listmenu"))
                for section, group in _group_by_section(cmds):
                    if section:
                        blocks.append(
                            Static(
                                f"   ── {_disp(section)} ──", classes="listsec"
                            )
                        )
                    blocks.append(
                        ListView(
                            *[
                                CmdItem(
                                    f"   · {_disp(c['label'])}",
                                    c.get("method"),
                                    c.get("kwargs"),
                                    c.get("path"),
                                    c.get("danger"),
                                )
                                for c in group
                            ]
                        )
                    )
            if not blocks:
                return Static(t("No command found."))
            return VerticalScroll(*blocks)

        def _kanban_layout_widget(self):
            cols = [
                self._col_widget(label, cnt, cmds)
                for (label, _p, cnt, cmds) in columns
            ]
            if not cols:
                return Static(t("No command found."))
            if self._kanban_mode == "grid":
                return Grid(*cols, classes="kgrid")
            if self._kanban_mode == "swimlanes":
                # Une rangée (swimlane) par menu de NIVEAU 1 (Execute, …).
                groups, order = {}, []
                for label, path, cnt, cmds in columns:
                    parts = path.split(" › ")
                    g = parts[1] if len(parts) > 1 else "TODO"
                    if g not in groups:
                        groups[g] = []
                        order.append(g)
                    groups[g].append((label, cnt, cmds))
                lanes = []
                for g in order:
                    lane_cols = [
                        self._col_widget(lb, cn, cm)
                        for (lb, cn, cm) in groups[g]
                    ]
                    lanes.append(
                        Vertical(
                            Static(f"━━ {g} ━━", classes="lanetitle"),
                            HorizontalScroll(*lane_cols),
                            classes="lane",
                        )
                    )
                return VerticalScroll(*lanes)
            return HorizontalScroll(*cols)  # columns

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("", id="summary")
            yield Tree("📍 TODO", id="nav")
            yield Container(id="kanban")
            yield Container(id="list")
            yield Static("", id="system")
            yield Footer()

        def on_mount(self):
            self.title = t("TODO navigation telemetry")
            self._populate_tree()
            self._update_summary()
            # Télémétrie système rafraîchie toutes les 2 s (deltas CPU/réseau).
            self.set_interval(2.0, self._tick_system)
            # Restaure la vue / la disposition / le curseur au retour.
            self.run_worker(self._restore())

        def _apply_visibility(self):
            self.query_one("#nav").display = self._mode == "tree"
            self.query_one("#kanban").display = self._mode == "kanban"
            self.query_one("#list").display = self._mode == "list"
            self.query_one("#system").display = self._mode == "system"

        async def _restore(self):
            if self._mode == "kanban":
                await self._enter_kanban()
            elif self._mode == "list":
                await self._enter_list()
            elif self._mode == "tree":
                self._focus_tree_path(state.get("path"))
            self._apply_visibility()
            self._update_summary()

        # -- vue Kanban ------------------------------------------------------ #
        async def _enter_kanban(self):
            box = self.query_one("#kanban", Container)
            await box.remove_children()
            await box.mount(self._kanban_layout_widget())
            self._apply_visibility()
            self._focus_kanban_path(state.get("path"))

        # -- vue Liste ------------------------------------------------------- #
        async def _enter_list(self):
            box = self.query_one("#list", Container)
            await box.remove_children()
            await box.mount(self._list_view_widget())
            self._apply_visibility()
            self._focus_kanban_path(state.get("path"))

        def _focus_kanban_path(self, path):
            if not path:
                return
            for lv in self.query(ListView):
                for i, item in enumerate(lv.children):
                    if getattr(item, "cmd_path", None) == path:
                        lv.index = i
                        lv.focus()
                        return

        def _focus_tree_path(self, path):
            if not path:
                return
            tree = self.query_one("#nav", Tree)

            def walk(node):
                d = getattr(node, "data", None)
                if isinstance(d, dict) and d.get("path") == path:
                    return node
                for ch in node.children:
                    found = walk(ch)
                    if found:
                        return found
                return None

            node = walk(tree.root)
            if node is not None:
                tree.move_cursor(node)
                tree.scroll_to_node(node)

        def _next_view(self):
            cur = self._mode if self._mode in VIEWS else "tree"
            return VIEWS[(VIEWS.index(cur) + 1) % len(VIEWS)]

        def _update_f3_hint(self):
            # Le footer F3 annonce la PROCHAINE vue (ex. « → Liste »).
            nxt = VIEW_LABELS.get(self._next_view(), self._next_view())
            try:
                self.bind("f3", "toggle_view", description=f"→ {nxt}")
                self.refresh_bindings()
            except Exception:
                pass

        def _update_summary(self):
            total = sum(paths.values())
            src = t("tree from code") if code_tree else t("visited paths only")
            extra = f" [{self._kanban_mode}]" if self._mode == "kanban" else ""
            cur_lbl = VIEW_LABELS.get(self._mode, self._mode)
            nxt_lbl = VIEW_LABELS.get(self._next_view(), self._next_view())
            self._update_f3_hint()
            self.query_one("#summary", Static).update(
                f"  {total} {t('navigations')} · {len(paths)} {t('menus')} · "
                f"{src} · {t('view')}: {cur_lbl}{extra} · "
                f"F3 → {nxt_lbl} · "
                f"{t('F2 system · F3/F4 views · Enter run')}"
            )

        # -- vue Système (F2) ----------------------------------------------- #
        async def _tick_system(self):
            # I/O système déportées en thread (comme le dashboard) ; on saute
            # la température (subprocess sensors) tant que la vue n'est pas
            # affichée.
            try:
                m, self._sys_prev = await asyncio.to_thread(
                    system_snapshot, self._sys_prev, self._mode == "system"
                )
            except Exception:
                return
            if self._mode == "system":
                self.query_one("#system", Static).update(
                    self._render_system(m)
                )

        def _render_system(self, m):
            lines = []
            load = (
                " · "
                + t("load")
                + " "
                + "/".join(f"{x:.1f}" for x in m["load"])
                if m["load"]
                else ""
            )
            lines.append(
                f"  🖥  {t('State')}      : {t('uptime')} "
                f"{_fmt_uptime(m['uptime'])}{load}"
            )
            cpu = m["cpu"]
            lines.append(
                f"  ⚙  CPU        : {cpu if cpu is not None else '?'} %"
                f"  ({m['ncpu']} {t('cores')})"
            )
            if m["mem"]:
                tot, used = m["mem"]
                pct = int(used / tot * 100) if tot else 0
                lines.append(
                    f"  🧠 {t('Memory')}    : {_fmt_size(used)} / "
                    f"{_fmt_size(tot)}  ({pct} %)"
                )
            if m["disk"]:
                tot, used, free = m["disk"]
                pct = int(used / tot * 100) if tot else 0
                lines.append(
                    f"  💽 {t('Disk')} /    : {_fmt_size(used)} / "
                    f"{_fmt_size(tot)}  ({pct} %) · {t('free')} "
                    f"{_fmt_size(free)}"
                )
            if m["net"]:
                rx, tx = m["net"]
                lines.append(
                    f"  🌐 {t('Network')}   : ↓ {_fmt_rate(rx)}   "
                    f"↑ {_fmt_rate(tx)}"
                )
            if m["battery"]:
                cap, status = m["battery"]
                lines.append(f"  🔋 {t('Battery')}   : {cap} % ({status})")
            temp = m["temp"]
            if temp:
                lines.append(
                    f"  🌡  {t('Temperature')} : {max(temp[1]):.0f}°C "
                    f"({t('max')})"
                )
            else:
                lines.append(
                    f"  🌡  {t('Temperature')} : "
                    f"{t('lm-sensors absent — press i to install')}"
                )
            return "\n".join(lines)

        # -- actions --------------------------------------------------------- #
        def action_system(self):
            self._mode = "system"
            self._apply_visibility()
            self.run_worker(self._tick_system())  # rafraîchit tout de suite
            self._update_summary()

        def action_install_sensors(self):
            if self._mode != "system":
                return
            if read_temperature() is not None:
                self.notify(t("Sensors already available."))
                return
            cmd = sensors_install_command()
            if not cmd:
                self.notify(
                    t("Unknown package manager for lm-sensors."),
                    severity="warning",
                )
                return
            printable = " ".join(cmd)
            with self.suspend():
                print(f"{t('Proposed install command:')}")
                print(f"  {printable}")
                print("  sudo sensors-detect --auto")
                ans = (
                    input(t("Install lm-sensors now? (y/N): ")).strip().lower()
                )
                if ans in ("o", "oui", "y", "yes"):
                    os.system(printable + " || true")
                    os.system("sudo sensors-detect --auto || true")
            # Rafraîchit IMMÉDIATEMENT la vue système : on ré-échantillonne
            # (température incluse) et on réécrit la case pour que le message
            # « installer » disparaisse si les capteurs sont désormais lisibles.
            self._sys_prev = None
            try:
                m, self._sys_prev = system_snapshot(self._sys_prev, full=True)
                self.query_one("#system", Static).update(
                    self._render_system(m)
                )
            except Exception:
                pass
            self.refresh()
            if read_temperature() is not None:
                self.notify(t("Sensors now available."))
            else:
                self.notify(
                    t("Still no temperature (reboot/modprobe may be needed)."),
                    severity="warning",
                )

        def on_click(self, event):
            # Grille (mosaïque) : clic sur le TITRE d'une case -> l'agrandir
            # (row-span sur toute la hauteur) ; re-clic -> taille normale.
            if self._mode != "kanban" or self._kanban_mode != "grid":
                return
            w = getattr(event, "widget", None)
            if w is None or "ktitle" not in getattr(w, "classes", ()):
                return
            card = w
            while card is not None and "kcol" not in getattr(
                card, "classes", ()
            ):
                card = card.parent
            if card is not None:
                card.toggle_class("kbig")

        # -- actions --------------------------------------------------------- #
        async def action_toggle_view(self):
            # Cycle Arbre -> Kanban -> Liste -> Arbre (depuis Système on
            # revient dans le cycle sur la vue précédente).
            cur = self._mode if self._mode in VIEWS else "tree"
            self._mode = VIEWS[(VIEWS.index(cur) + 1) % len(VIEWS)]
            if self._mode == "kanban":
                await self._enter_kanban()
            elif self._mode == "list":
                await self._enter_list()
            self._apply_visibility()
            self._update_summary()

        def _populate_tree(self):
            tree = self.query_one("#nav", Tree)
            tree.clear()
            if code_tree is not None:
                tree.root.data = {"path": "TODO"}
                tree.root.set_label(f"📍 TODO  ({paths.get('TODO', 0)})")
                self._add_code(tree.root, code_tree["children"], "TODO")
            else:
                nested = _nested(paths)
                todo = nested.get("TODO", {"count": 0, "children": nested})
                tree.root.set_label(f"📍 TODO  ({todo['count']})")
                self._add_visited(tree.root, todo["children"])
            tree.root.expand()

        def _add_code(self, tnode, children, parent_path):
            for c in children:
                path = f"{parent_path} › {c['label']}"
                if c["is_menu"]:
                    child = tnode.add(
                        f"{c['label']}  ({paths.get(path, 0)})",
                        data={"path": path},
                        expand=True,
                    )
                    self._add_code(child, c["children"], path)
                else:
                    # Feuille EXÉCUTABLE : méthode, chemin et drapeau
                    # `danger` portés en data.
                    tnode.add_leaf(
                        f"· {c['label']}",
                        data={
                            "method": c.get("method"),
                            "kwargs": c.get("kwargs"),
                            "path": path,
                            "danger": bool(c.get("danger")),
                        },
                    )

        def _add_visited(self, tnode, children):
            for name, node in sorted(
                children.items(), key=lambda kv: -kv[1]["count"]
            ):
                child = tnode.add(f"{name}  ({node['count']})", expand=True)
                self._add_visited(child, node["children"])

        # -- sélection / exécution ------------------------------------------- #
        def _run(self, method, kwargs, path, danger=False):
            # Une commande dangereuse se lance depuis son menu seulement :
            # un avis, et ni action rendue ni sortie de la TUI.
            if not method:
                return
            if danger:
                self.notify(
                    t("Dangerous command: run it from its menu."),
                    severity="warning",
                )
                return
            self._action = (method, kwargs or {})
            self._exit_state = {
                "mode": self._mode,
                "kanban_mode": self._kanban_mode,
                "path": path,
            }
            self.exit()

        def on_tree_node_selected(self, event):
            d = getattr(event.node, "data", None)
            if isinstance(d, dict) and d.get("method"):
                self._run(
                    d["method"],
                    d.get("kwargs"),
                    d.get("path"),
                    d.get("danger"),
                )

        def on_list_view_selected(self, event):
            if isinstance(event.item, CmdItem):
                self._run(
                    event.item.cmd_method,
                    event.item.cmd_kwargs,
                    event.item.cmd_path,
                    event.item.cmd_danger,
                )

        async def action_kanban_layout(self):
            if self._mode != "kanban":
                return
            i = KANBAN_MODES.index(self._kanban_mode)
            self._kanban_mode = KANBAN_MODES[(i + 1) % len(KANBAN_MODES)]
            await self._enter_kanban()
            self._update_summary()

        def action_expand_all(self):
            if self._mode == "tree":
                self.query_one("#nav", Tree).root.expand_all()

        def action_reset(self):
            reset()
            paths.clear()
            self._populate_tree()
            self._update_summary()
            self.notify(t("Telemetry reset."))

    app = Telemetry()
    app._exit_state = state
    if run_app:
        app.run()
        return app._action, getattr(app, "_exit_state", state)
    return app
