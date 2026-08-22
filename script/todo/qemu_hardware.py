#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ressources matérielles d'une VM libvirt : lecture, et plan de modification.

Le menu d'état de `todo.py` démarre des VM. C'est le seul moment où leur
matériel est modifiable : libvirt refuse de changer vCPU, RAM ou écran d'un
domaine allumé, et l'accélération 3D n'est lue qu'au démarrage de QEMU. Ce
module tient la logique pure de ce moment-là.

- hw_state(xml)  : ce que la VM a aujourd'hui, lu dans son XML.
- hw_plan(...)   : les commandes qui l'amènent à l'état voulu, et RIEN de plus
                   — un plan vide quand rien ne change, et une ligne « skip »
                   expliquée quand une demande n'a pas d'objet.
- build_want(...) / run_hardware_form(...) : le formulaire Textual.

Aucune commande n'est lancée ici : `todo.py` les exécute, sous sudo, et les
affiche avant. Le plan reste donc vérifiable sans hyperviseur.

Deux pièges, appris sur l'hôte :

- « virt-xml --memory N » ne change que <currentMemory>, la cible du ballon.
  Élever la RAM au-delà du maximum exige les deux champs à la fois, sinon la
  VM plafonne en silence à son ancien maximum.
- « --add-device --graphics type=egl-headless » n'est PAS idempotent : appelé
  deux fois, il pose deux affichages. D'où la lecture de l'état AVANT le plan.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from script.todo.qemu_deploy_form import parse_ram, positive_int

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# URI système : sous sudo, root y va de lui-même, mais l'expliciter écarte le
# piège documenté dans deploy_qemu.py — un appel non root visant
# qemu:///session, où les domaines du parc n'existent pas.
CONNECT = "qemu:///system"

# Le virtio-gpu est le SEUL modèle qui porte virgl. Poser accel3d sur un qxl
# ou un cirrus est accepté par le schéma et ne fait rien.
GPU_VIDEO_MODEL = "virtio"

# Affichages qui donnent un écran à la VM. « egl-headless » n'en est pas un :
# il n'ouvre aucun port et n'existe que pour porter le contexte OpenGL.
SCREEN_TYPES = ("vnc", "spice", "sdl", "desktop")
EGL = "egl-headless"

# libvirt écrit KiB pour la mémoire, mais le schéma autorise les deux systèmes
# d'unités — KB vaut mille octets, KiB en vaut 1024. On convertit en octets
# d'abord : une table « à peu près » ferait dériver l'affichage de la VM.
_UNIT_BYTES = {
    "b": 1,
    "bytes": 1,
    "kb": 1000,
    "k": 1024,
    "kib": 1024,
    "mb": 1000**2,
    "m": 1024**2,
    "mib": 1024**2,
    "gb": 1000**3,
    "g": 1024**3,
    "gib": 1024**3,
    "tb": 1000**4,
    "t": 1024**4,
    "tib": 1024**4,
}


def _mib(node) -> int:
    """Valeur d'un élément mémoire libvirt, en mébioctets."""
    if node is None:
        return 0
    factor = _UNIT_BYTES.get((node.get("unit") or "KiB").lower(), 1024)
    try:
        return int(float((node.text or "0").strip()) * factor) // (1024 * 1024)
    except ValueError:
        return 0


def ram_field(mib) -> str:
    """Valeur du champ RAM : « 32G » plutôt que « 32768 ».

    parse_ram relit les deux, mais cinq chiffres ne tiennent pas dans le
    champ : la VM de 32 Go y affichait « 3276 », et un nombre tronqué qu'on
    valide sans regarder rétrécit la machine.
    """
    try:
        mib = int(mib or 0)
    except (TypeError, ValueError):
        return ""
    if mib <= 0:
        return ""
    return f"{mib // 1024}G" if mib % 1024 == 0 else str(mib)


def fmt_mib(mib) -> str:
    """1024 -> « 1 Go », 3072 -> « 3 Go », 1536 -> « 1,5 Go », 512 -> « 512 Mo »."""
    try:
        mib = int(mib)
    except (TypeError, ValueError):
        return "?"
    if mib <= 0:
        return "?"
    if mib % 1024 == 0:
        return f"{mib // 1024} Go"
    if mib > 1024:
        return f"{mib / 1024:.1f}".replace(".", ",") + " Go"
    return f"{mib} Mo"


def hw_state(xml: str, autostart=None) -> dict:
    """État matériel lu dans le XML du domaine.

    `autostart` n'est pas dans le XML — il vit dans un lien symbolique côté
    libvirt — donc l'appelant le passe (via « virsh dominfo »).
    """
    state = {
        "name": "",
        "vcpus": 0,
        "mem_mib": 0,
        "max_mem_mib": 0,
        "video": "",
        "accel3d": False,
        "egl": False,
        "render": "",
        "screen": False,
        "autostart": bool(autostart),
    }
    try:
        root = ET.fromstring(xml or "")
    except ET.ParseError:
        return state
    state["name"] = (root.findtext("name") or "").strip()
    try:
        state["vcpus"] = int((root.findtext("vcpu") or "0").strip())
    except ValueError:
        state["vcpus"] = 0
    state["max_mem_mib"] = _mib(root.find("memory"))
    state["mem_mib"] = _mib(root.find("currentMemory")) or state["max_mem_mib"]
    model = root.find("./devices/video/model")
    if model is not None:
        state["video"] = model.get("type") or ""
        accel = model.find("acceleration")
        state["accel3d"] = accel is not None and accel.get("accel3d") == "yes"
    for graphics in root.findall("./devices/graphics"):
        kind = graphics.get("type") or ""
        if kind in SCREEN_TYPES:
            state["screen"] = True
        elif kind == EGL:
            state["egl"] = True
            gl = graphics.find("gl")
            state["render"] = (
                (gl.get("rendernode") or "") if gl is not None else ""
            )
    return state


def _virt_xml(name: str, *args) -> list:
    """Commande virt-xml qui ÉCRIT la définition persistante du domaine.

    « --define » explicite : sans lui, virt-xml interroge l'utilisateur quand
    le domaine tourne, et une invite dans un menu piloté par un script bloque
    sans rien dire.
    """
    return ["virt-xml", "--connect", CONNECT, name, "--define", *args]


def hw_plan(state: dict, want: dict, node: str = "") -> list:
    """Commandes menant de `state` à `want`, dans l'ordre.

    Chaque entrée est un dict : {'what': …, 'cmd': [...]} pour ce qui sera
    lancé, {'what': …, 'skip': raison} pour ce qui est demandé mais sans
    objet. Rien à changer -> liste vide, et l'appelant n'exécute rien.
    """
    name = state.get("name") or want.get("name") or ""
    plan = []
    if not name:
        return plan

    vcpus = positive_int(want.get("vcpus"), 0)
    if vcpus and vcpus != state.get("vcpus"):
        plan.append(
            {
                "what": f"vCPU {state.get('vcpus')} → {vcpus}",
                "cmd": _virt_xml(name, "--edit", "--vcpus", str(vcpus)),
            }
        )

    ram = positive_int(want.get("ram"), 0)
    if ram and ram != state.get("mem_mib"):
        plan.append(
            {
                "what": f"RAM {fmt_mib(state.get('mem_mib'))} → {fmt_mib(ram)}",
                "cmd": _virt_xml(
                    name,
                    "--edit",
                    "--memory",
                    f"memory={ram},currentMemory={ram}",
                ),
            }
        )

    gpu = want.get("gpu")
    if gpu is not None:
        plan += _gpu_plan(name, state, bool(gpu), node)

    auto = want.get("autostart")
    if auto is not None and bool(auto) != bool(state.get("autostart")):
        args = ["virsh", "--connect", CONNECT, "autostart"]
        if not auto:
            args.append("--disable")
        plan.append(
            {
                "what": t("Autostart") + (" : on" if auto else " : off"),
                "cmd": args + [name],
            }
        )
    return plan


def _gpu_plan(name: str, state: dict, gpu: bool, node: str) -> list:
    """Volet 3D du plan : accélération sur l'écran, et contexte GL."""
    plan = []
    if gpu:
        if not state.get("screen"):
            return [
                {
                    "what": t("3D acceleration (host GPU)"),
                    "skip": t("this VM has no virtual screen"),
                }
            ]
        if not node:
            return [
                {
                    "what": t("3D acceleration (host GPU)"),
                    "skip": t("no render node on the host"),
                }
            ]
        if not state.get("accel3d") or state.get("video") != GPU_VIDEO_MODEL:
            plan.append(
                {
                    "what": t("3D acceleration (host GPU)") + " : on",
                    "cmd": _virt_xml(
                        name,
                        "--edit",
                        "--video",
                        f"model.type={GPU_VIDEO_MODEL}"
                        ",model.acceleration.accel3d=on",
                    ),
                }
            )
        if state.get("render") != node:
            if state.get("egl"):
                # Déjà un affichage GL, mais sur un autre nœud : le corriger
                # en place. L'ajouter une seconde fois en poserait DEUX.
                plan.append(
                    {
                        "what": f"{t('Render node')} → {node}",
                        "cmd": _virt_xml(
                            name,
                            "--edit",
                            f"type={EGL}",
                            "--graphics",
                            f"gl.rendernode={node}",
                        ),
                    }
                )
            else:
                plan.append(
                    {
                        "what": f"{t('Render node')} : {node}",
                        "cmd": _virt_xml(
                            name,
                            "--add-device",
                            "--graphics",
                            f"type={EGL},gl.rendernode={node}",
                        ),
                    }
                )
        return plan
    if state.get("accel3d"):
        plan.append(
            {
                "what": t("3D acceleration (host GPU)") + " : off",
                "cmd": _virt_xml(
                    name,
                    "--edit",
                    "--video",
                    f"model.type={state.get('video') or GPU_VIDEO_MODEL}"
                    ",model.acceleration.accel3d=off",
                ),
            }
        )
    if state.get("egl"):
        # Ciblé par type : la console VNC de la VM, elle, doit survivre.
        plan.append(
            {
                "what": t("Render node") + " : —",
                "cmd": _virt_xml(
                    name, "--remove-device", "--graphics", f"type={EGL}"
                ),
            }
        )
    return plan


def build_want(state: dict, vcpus, ram, gpu, autostart) -> dict:
    """Valeurs de widgets -> intention, en retombant sur l'état actuel.

    Un champ vidé ou illisible ne veut pas dire « zéro vCPU » : il veut dire
    « n'y touche pas ». Sans ce repli, valider le formulaire sans rien saisir
    proposerait de rétrécir la VM à néant.
    """
    return {
        "name": state.get("name") or "",
        "vcpus": positive_int(vcpus, state.get("vcpus") or 0),
        "ram": parse_ram(ram) or state.get("mem_mib") or 0,
        "gpu": bool(gpu),
        "autostart": bool(autostart),
    }


def gpu_allowed(state: dict, node: str) -> str:
    """'' si la 3D est proposable pour cette VM, sinon la raison du refus."""
    if not node:
        return t("no render node on the host")
    if not state.get("screen"):
        return t("this VM has no virtual screen")
    return ""


def hw_summary(state: dict) -> str:
    """Ligne d'état lisible : « 8 vCPU, 32 Go, 3D on (renderD128) »."""
    bits = [f"{state.get('vcpus') or '?'} vCPU", fmt_mib(state.get("mem_mib"))]
    if state.get("accel3d") or state.get("render"):
        node = state.get("render") or "?"
        bits.append(f"3D {node.rsplit('/', 1)[-1]}")
    elif state.get("screen"):
        bits.append(t("software rendering"))
    return ", ".join(bits)


def run_hardware_form(rows, node: str = "", run_app: bool = True):
    """Formulaire d'ajustement matériel. Renvoie {nom: intention} ou None.

    `rows` est une liste d'états (hw_state). `run_app=False` renvoie
    l'instance sans la lancer — c'est ainsi que les tests l'inspectent.
    """
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import Button, Checkbox, Footer, Header, Input, Static

    states = [dict(r) for r in rows if r]

    class HardwareForm(App):
        TITLE = t("VM hardware")
        # L'intention se lit SUR l'instance, pas dans une fermeture : c'est
        # ainsi que les tests montent le formulaire et vérifient ce qu'il
        # rend, sans passer par un terminal.
        want = None
        CSS = """
        #rows { height: 1fr; }
        #host { padding: 0 1; }
        .vm { padding: 1 1 0 1; text-style: bold; }
        .row { height: auto; padding: 0 1; }
        .lbl { width: 7; height: 3; content-align: right middle; }
        .num { width: 10; }
        /* « auto » plutôt qu'une largeur fixe : le libellé traduit change de
           longueur, et une case tronquée ne dit plus ce qu'elle coche. */
        .cb3d { width: auto; margin: 0 2 0 1; }
        .cbauto { width: auto; }
        .warn { padding: 0 3; }
        #bar { height: auto; padding: 1; }
        """
        BINDINGS = [
            ("ctrl+s", "apply", t("Apply")),
            ("escape", "quit", t("Cancel")),
        ]

        def compose(self) -> ComposeResult:
            yield Header()
            head = t("Host GPU:") + " "
            head += node if node else t("none (software rendering)")
            yield Static(head, id="host")
            with VerticalScroll(id="rows"):
                for i, st in enumerate(states):
                    reason = gpu_allowed(st, node)
                    # Le nom sur SA ligne, avec l'état actuel : les noms du
                    # parc font trente caractères, en colonne ils seraient
                    # tronqués — et c'est le nom qui dit quelle VM on règle.
                    yield Static(
                        f"{st.get('name', '')} — {hw_summary(st)}",
                        classes="vm",
                    )
                    with Horizontal(classes="row"):
                        yield Static("vCPU", classes="lbl")
                        yield Input(
                            value=str(st.get("vcpus") or ""),
                            id=f"vcpus{i}",
                            classes="num",
                        )
                        yield Static("RAM", classes="lbl")
                        yield Input(
                            value=ram_field(st.get("mem_mib")),
                            id=f"ram{i}",
                            classes="num",
                            placeholder="Mo ou G",
                        )
                        yield Checkbox(
                            t("3D"),
                            value=bool(st.get("accel3d")),
                            id=f"gpu{i}",
                            disabled=bool(reason),
                            classes="cb3d",
                        )
                        yield Checkbox(
                            t("Autostart"),
                            value=bool(st.get("autostart")),
                            id=f"auto{i}",
                            classes="cbauto",
                        )
                    if reason:
                        yield Static(f"⚠ {reason}", classes="warn")
            with Horizontal(id="bar"):
                yield Button(t("Apply"), variant="primary", id="apply")
                yield Button(t("Cancel"), id="cancel")
            yield Footer()

        def action_apply(self) -> None:
            want = {}
            for i, st in enumerate(states):
                want[st.get("name", "")] = build_want(
                    st,
                    self.query_one(f"#vcpus{i}", Input).value,
                    self.query_one(f"#ram{i}", Input).value,
                    self.query_one(f"#gpu{i}", Checkbox).value,
                    self.query_one(f"#auto{i}", Checkbox).value,
                )
            self.want = want
            self.exit()

        def on_button_pressed(self, event) -> None:
            if event.button.id == "apply":
                self.action_apply()
            else:
                self.exit()

    app = HardwareForm()
    if not run_app:
        return app
    app.run()
    return app.want
