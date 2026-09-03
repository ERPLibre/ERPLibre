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
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

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


def load() -> dict:
    try:
        return json.loads(_path().read_text())
    except (OSError, ValueError):
        return {"paths": {}}


def _save(data: dict) -> None:
    try:
        _path().write_text(json.dumps(data, ensure_ascii=False, indent=2))
    except OSError:
        pass


def record(path: str) -> None:
    """Incrémente le compteur du menu `path`. Best-effort : ne lève jamais
    (la télémétrie ne doit jamais casser la navigation)."""
    if not path or path == _LAST[0]:
        return
    _LAST[0] = path
    try:
        data = load()
        paths = data.setdefault("paths", {})
        paths[path] = paths.get(path, 0) + 1
        data["updated"] = int(time.time())
        _save(data)
    except Exception:
        pass


def reset() -> None:
    _save({"paths": {}})


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
# Métadonnées de navigation DÉRIVÉES DU CODE (structure réelle des menus)
# --------------------------------------------------------------------------- #
def _str_of(node) -> str | None:
    """Chaîne d'un nœud AST : littéral, t("…") ou f-string (parties Constant)."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "t"
        and node.args
        and isinstance(node.args[0], ast.Constant)
    ):
        return node.args[0].value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            p.value
            for p in node.values
            if isinstance(p, ast.Constant) and isinstance(p.value, str)
        )
    return None


def _choice_entries(func) -> list:
    """Entrées NUMÉROTÉES d'un menu « choices = [...] », dans l'ordre : chaque
    commande est {« label », « section »}, la section étant le dernier marqueur
    {"section": …} rencontré (fill_help_info ne numérote pas les sections)."""
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(tg, ast.Name) and tg.id == "choices"
                for tg in node.targets
            )
            and isinstance(node.value, ast.List)
        ):
            entries, section = [], None
            for el in node.value.elts:
                if not isinstance(el, ast.Dict):
                    continue
                d = {}
                for k, v in zip(el.keys, el.values):
                    if isinstance(k, ast.Constant):
                        d[k.value] = _str_of(v)
                if d.get("section"):
                    section = d["section"]
                    continue
                lab = d.get("prompt_description") or d.get(
                    "prompt_description_key"
                )
                if lab:
                    entries.append({"label": lab, "section": section})
            return entries
    return []


def _dispatch(func) -> dict:
    """{numéro: (nom_de_méthode, kwargs)} depuis « status == "N": self.X(...) ».
    Les kwargs LITTÉRAUX (ex. dry_run=True) sont capturés pour pouvoir rejouer
    la commande à l'identique depuis la télémétrie."""
    out = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "status"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
            and isinstance(test.comparators[0], ast.Constant)
        ):
            try:
                num = int(test.comparators[0].value)
            except (TypeError, ValueError):
                continue
            for stmt in node.body:
                found = None
                for n in ast.walk(stmt):
                    if (
                        isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and isinstance(n.func.value, ast.Name)
                        and n.func.value.id == "self"
                    ):
                        kwargs = {
                            kw.arg: kw.value.value
                            for kw in n.keywords
                            if kw.arg and isinstance(kw.value, ast.Constant)
                        }
                        found = (n.func.attr, kwargs)
                        break
                if found:
                    out[num] = found
                    break
    return out


def _menu_labels(cls) -> dict:
    """{méthode: label} depuis l'attribut de classe _MENU_LABELS."""
    for node in ast.walk(cls):
        if (
            isinstance(node, ast.Assign)
            and any(
                isinstance(tg, ast.Name) and tg.id == "_MENU_LABELS"
                for tg in node.targets
            )
            and isinstance(node.value, ast.Dict)
        ):
            return {
                k.value: v.value
                for k, v in zip(node.value.keys, node.value.values)
                if isinstance(k, ast.Constant) and isinstance(v, ast.Constant)
            }
    return {}


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


def _len_choices_offset(comp):
    """K pour « str(len(choices)) » -> 0 et « str(len(choices) - N) » -> N ;
    None si le nœud n'est pas de cette forme."""
    if not (
        isinstance(comp, ast.Call)
        and isinstance(comp.func, ast.Name)
        and comp.func.id == "str"
        and comp.args
    ):
        return None
    arg = comp.args[0]

    def is_len_choices(x):
        return (
            isinstance(x, ast.Call)
            and isinstance(x.func, ast.Name)
            and x.func.id == "len"
            and x.args
            and isinstance(x.args[0], ast.Name)
            and x.args[0].id == "choices"
        )

    if is_len_choices(arg):
        return 0
    if (
        isinstance(arg, ast.BinOp)
        and isinstance(arg.op, ast.Sub)
        and is_len_choices(arg.left)
        and isinstance(arg.right, ast.Constant)
    ):
        return int(arg.right.value)
    return None


def _dispatch_len(func) -> dict:
    """{K: méthode} pour « status == str(len(choices) - K): self.M() »."""
    out = {}
    for node in ast.walk(func):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if not (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "status"
            and len(test.ops) == 1
            and isinstance(test.ops[0], ast.Eq)
        ):
            continue
        k = _len_choices_offset(test.comparators[0])
        if k is None:
            continue
        method = None
        for stmt in node.body:
            for n in ast.walk(stmt):
                if (
                    isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Attribute)
                    and isinstance(n.func.value, ast.Name)
                    and n.func.value.id == "self"
                ):
                    method = n.func.attr
                    break
            if method:
                break
        if method:
            out[k] = method
    return out


def _choices_children(func, todo_dir):
    """Commandes d'un menu bâti par « choices » (config_file.get_config +
    choices.append/extend) avec dispatch « str(len(choices)-N) ». Renvoie une
    liste de (label, méthode, kwargs) dans l'ordre affiché, ou None si le motif
    ne s'applique pas. Les entrées de CONFIG rejouent via
    execute_from_configuration ; les entrées APPENDÉES via leur méthode."""

    def _dict_label(dnode):
        d = {}
        for k, v in zip(dnode.keys, dnode.values):
            if isinstance(k, ast.Constant):
                d[k.value] = _str_of(v)
        return d.get("prompt_description") or d.get("prompt_description_key")

    # On collecte affectations et append AVEC leur n° de ligne pour rejouer
    # dans l'ORDRE (les entrées « menu_entry = {…}; choices.append(menu_entry) »
    # réutilisent la même variable -> il faut suivre la dernière valeur).
    config_key = None
    events = []  # (lineno, kind, payload)
    for node in ast.walk(func):
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            var = node.targets[0].id
            val = node.value
            if isinstance(val, ast.Dict):
                events.append((node.lineno, "assign", (var, val)))
            elif (
                var == "choices"
                and isinstance(val, ast.Call)
                and isinstance(val.func, ast.Attribute)
                and val.func.attr == "get_config"
                and val.args
                and isinstance(val.args[0], ast.Constant)
            ):
                config_key = val.args[0].value
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "append"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "choices"
            and node.args
        ):
            events.append((node.lineno, "append", node.args[0]))
    events.sort(key=lambda e: e[0])
    var_dict, appended = {}, []
    for _ln, kind, payload in events:
        if kind == "assign":
            var_dict[payload[0]] = payload[1]
        else:  # append : arg = Dict littéral ou Name (variable)
            arg = payload
            dnode = (
                arg
                if isinstance(arg, ast.Dict)
                else (
                    var_dict.get(arg.id) if isinstance(arg, ast.Name) else None
                )
            )
            if dnode is not None:
                lab = _dict_label(dnode)
                if lab:
                    appended.append(lab)
    if config_key is None and not appended:
        return None
    children = []
    for entry in _config_list(config_key, todo_dir) if config_key else []:
        lab = (
            entry.get("prompt_description_key")
            or entry.get("prompt_description")
            or "?"
        )
        children.append(
            (lab, "execute_from_configuration", {"instance": entry})
        )
    len_disp = _dispatch_len(func)
    n_config = len(children)  # figé : `children` grossit dans la boucle
    n_total = n_config + len(appended)
    for j, lab in enumerate(appended):
        pos = n_config + j  # 0-based dans la liste globale (stable)
        method = len_disp.get(n_total - 1 - pos)  # None si non mappé
        children.append((lab, method, {}))
    return children


def _mixin_files(todo_py: Path) -> list:
    """Les fichiers des mixins que todo.py assemble sur la classe TODO.

    Lus dans ses propres imports « from script.todo.X import YMixin » : la
    liste suit le code au lieu d'être recopiée ici, et un mixin ajouté demain
    apparaîtra sans qu'on y pense.
    """
    try:
        source = todo_py.read_text(encoding="utf-8")
    except OSError:
        return []
    noms = re.findall(
        r"^from script\.todo\.(\w+) import \w*Mixin", source, re.MULTILINE
    )
    fichiers = []
    for nom in noms:
        chemin = todo_py.parent / f"{nom}.py"
        if chemin.exists():
            fichiers.append(chemin)
    return fichiers


def build_code_tree(todo_path=None) -> dict | None:
    """Construit l'arbre des menus/commandes EN LISANT le code de todo.py
    (AST). Chaque menu (méthode de _MENU_LABELS) devient un nœud ; ses branches
    « status == N » deviennent des sous-menus (si la cible est un menu) ou des
    commandes (feuilles). None si l'analyse échoue."""
    p = Path(todo_path) if todo_path else (Path(__file__).parent / "todo.py")
    todo_dir = p.parent  # todo.json est à côté de todo.py
    try:
        mod = ast.parse(p.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    cls = next((n for n in ast.walk(mod) if isinstance(n, ast.ClassDef)), None)
    if cls is None:
        return None
    methods = {n.name: n for n in cls.body if isinstance(n, ast.FunctionDef)}
    # ET les mixins. Ce lecteur est STATIQUE : il ne voit pas la classe
    # assemblée, seulement le fichier qu'on lui donne. Depuis que les menus
    # QEMU/KVM et Proxmox vivent dans des mixins, leur colonne avait disparu
    # de cet écran — la commande s'exécutait toujours, mais on ne pouvait plus
    # la lancer d'ici ni la lire. Les fichiers sont ceux que todo.py importe,
    # donc rien à tenir à jour à la main.
    for voisin in _mixin_files(p):
        try:
            frere = ast.parse(voisin.read_text(encoding="utf-8"))
        except (OSError, SyntaxError):
            continue
        for autre in (n for n in frere.body if isinstance(n, ast.ClassDef)):
            for membre in autre.body:
                if isinstance(membre, ast.FunctionDef):
                    methods.setdefault(membre.name, membre)
    labels = _menu_labels(cls)
    if "run" not in methods or not labels:
        return None
    seen = set()

    def build(method):
        node = {
            "label": labels.get(method, method),
            "is_menu": True,
            "children": [],
        }
        if method in seen or method not in methods:
            return node
        seen.add(method)
        func = methods[method]
        disp = _dispatch(func)
        centries = _choice_entries(func)
        for num in sorted(disp):
            target, kwargs = disp[num]
            if target in labels:  # sous-menu
                node["children"].append(build(target))
            else:  # commande (feuille) exécutable
                entry = (
                    centries[num - 1] if 0 <= num - 1 < len(centries) else None
                )
                lab = (
                    entry["label"]
                    if entry
                    else target.lstrip("_").replace("_", " ")
                )
                node["children"].append(
                    {
                        "label": lab,
                        "is_menu": False,
                        "children": [],
                        "method": target,
                        "kwargs": kwargs,
                        "section": entry["section"] if entry else None,
                    }
                )
        # Menus bâtis par « choices » (get_config + append) sans dispatch
        # littéral « status == "N" » : Code, Update, Git, Database…
        if not disp:
            for lab, tmethod, tkwargs in (
                _choices_children(func, todo_dir) or []
            ):
                if tmethod in labels:  # une entrée qui ouvre un sous-menu
                    node["children"].append(build(tmethod))
                else:
                    node["children"].append(
                        {
                            "label": lab,
                            "is_menu": False,
                            "children": [],
                            "method": tmethod,
                            "kwargs": tkwargs,
                            "section": None,
                        }
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
        return int(open(path).read().strip())
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
        for line in open("/proc/meminfo"):
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
            status = open(os.path.join(base, "status")).read().strip()
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
        m["uptime"] = float(open("/proc/uptime").read().split()[0])
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
    Sélectionner une COMMANDE = l'exécuter. `state` restaure la vue + le
    curseur au retour. Renvoie (action|None, state) ; run_app=False -> l'app.
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
        """Carte : commande à exécuter + son chemin (pour restaurer le curseur)."""

        def __init__(self, label, method, kwargs, path):
            super().__init__(Label(label))
            self.cmd_method = method
            self.cmd_kwargs = kwargs or {}
            self.cmd_path = path

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
                    # Feuille EXÉCUTABLE : méthode + chemin portés en data.
                    tnode.add_leaf(
                        f"· {c['label']}",
                        data={
                            "method": c.get("method"),
                            "kwargs": c.get("kwargs"),
                            "path": path,
                        },
                    )

        def _add_visited(self, tnode, children):
            for name, node in sorted(
                children.items(), key=lambda kv: -kv[1]["count"]
            ):
                child = tnode.add(f"{name}  ({node['count']})", expand=True)
                self._add_visited(child, node["children"])

        # -- sélection / exécution ------------------------------------------- #
        def _run(self, method, kwargs, path):
            if not method:
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
                self._run(d["method"], d.get("kwargs"), d.get("path"))

        def on_list_view_selected(self, event):
            if isinstance(event.item, CmdItem):
                self._run(
                    event.item.cmd_method,
                    event.item.cmd_kwargs,
                    event.item.cmd_path,
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
