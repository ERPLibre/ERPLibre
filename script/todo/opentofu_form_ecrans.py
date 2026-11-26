#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Modales du formulaire d'un parc OpenTofu : confirmer, retaper le nom du
parc, éditer une VM.

Textual s'importe ici au niveau du module : `opentofu_form` n'importe ce
module qu'à l'ouverture de l'écran, ce qui garde ses fonctions pures
importables sans Textual. Chaque gestionnaire de bouton arrête son
événement : sans cela, le clic remonte jusqu'à l'application.
"""

import copy

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Checkbox, Input, Label, Static

from script.opentofu import spec as spec_parc
from script.todo.opentofu_form import (
    CHAMPS_VM,
    _texte,
    nouvelle_vm,
    vm_depuis_saisie,
)
from script.todo.todo_i18n import t

_CSS_MODALE = """
    {nom} {{ align: center middle; }}
    {nom} > Vertical {{
        width: 90%; max-width: 100; height: auto; max-height: 90%;
        border: thick $accent; background: $surface; padding: 0 1;
    }}
    {nom} VerticalScroll {{ height: auto; max-height: 24; }}
    {nom} .boutons {{ height: auto; align-horizontal: right; }}
"""


def ligne(libelle, ident, compact=False):
    """Libellé et champ de saisie sur une ligne ; `compact` les tient sur
    une seule rangée d'écran (classe `compacte`, réglée par le CSS de
    l'application, qui l'emporte sur celui des modales)."""
    return Horizontal(
        Label(libelle),
        Input(id=ident, compact=compact),
        classes="ligne compacte" if compact else "ligne",
    )


class EcranConfirmer(ModalScreen):
    """Lignes à confirmer, défilantes. Rend True à la confirmation, None
    sinon."""

    DEFAULT_CSS = _CSS_MODALE.format(nom="EcranConfirmer")
    BINDINGS = [("escape", "annuler", t("Cancel"))]

    def __init__(self, lignes):
        super().__init__()
        self._lignes = lignes

    def compose(self) -> ComposeResult:
        with Vertical():
            with VerticalScroll():
                yield Static("\n".join(self._lignes), markup=False)
            with Horizontal(classes="boutons"):
                yield Button(t("Cancel"), id="non")
                yield Button(t("Confirm"), variant="primary", id="oui")

    def on_button_pressed(self, event) -> None:
        event.stop()
        self.dismiss(True if event.button.id == "oui" else None)

    def action_annuler(self) -> None:
        self.dismiss(None)


class EcranNom(ModalScreen):
    """Nom du parc à retaper. Rend True s'il correspond, False sinon, None
    à l'annulation."""

    DEFAULT_CSS = _CSS_MODALE.format(nom="EcranNom")
    BINDINGS = [("escape", "annuler", t("Cancel"))]

    def __init__(self, message, nom):
        super().__init__()
        self._message = message
        self._nom = nom

    def compose(self) -> ComposeResult:
        invite = t("Type the fleet name ({nom}) to confirm: ")
        with Vertical():
            yield Static(self._message, markup=False)
            yield Static(invite.format(nom=self._nom), markup=False)
            yield Input(id="nom_saisie")
            with Horizontal(classes="boutons"):
                yield Button(t("Cancel"), id="nom_non")
                yield Button(t("Confirm"), variant="error", id="nom_ok")

    def _valider(self):
        saisie = self.query_one("#nom_saisie", Input).value.strip()
        self.dismiss(saisie == self._nom)

    def on_button_pressed(self, event) -> None:
        event.stop()
        if event.button.id == "nom_ok":
            self._valider()
        else:
            self.dismiss(None)

    def on_input_submitted(self, event) -> None:
        event.stop()
        self._valider()

    def action_annuler(self) -> None:
        self.dismiss(None)


class EcranVM(ModalScreen):
    """Une VM du parc. La saisie, placée dans une copie de la spec, passe
    par `spec.valider` : ses erreurs s'affichent ici et la modale reste
    ouverte. Rend la VM, ou None à l'annulation."""

    DEFAULT_CSS = (
        _CSS_MODALE.format(nom="EcranVM")
        + """
        #vmf_erreurs { color: $error; height: auto; }
    """
    )
    BINDINGS = [("escape", "annuler", t("Cancel"))]

    def __init__(self, spec, index):
        super().__init__()
        self._spec = spec
        self._index = index
        if index is None:
            self._base = nouvelle_vm(spec)
        else:
            self._base = copy.deepcopy(spec["vms"][index])

    def compose(self) -> ComposeResult:
        libelles = {
            "nom": t("Name"),
            "distro": t("Distro"),
            "version": t("Version"),
            "arch": t("Architecture"),
            "vcpus": t("vCPU"),
            "ram": t("RAM (MiB)"),
            "disque": t("Disk"),
            "ip": t("IP (auto, dhcp or a.b.c.d/nn)"),
            "passerelle": t("Gateway"),
            "dns": t("DNS (comma separated)"),
            "vmid": t("VMID (empty: chosen on the host)"),
            "branche": t("ERPLibre branch"),
        }
        titre = t("Add a VM") if self._index is None else t("Edit a VM")
        with Vertical():
            yield Static(titre)
            with VerticalScroll():
                for champ in CHAMPS_VM:
                    yield ligne(libelles[champ], f"vmf_{champ}", True)
            yield Checkbox(
                t("Start the VM"),
                bool(self._base.get("demarrer", True)),
                id="vmf_demarrer",
            )
            yield Checkbox(
                t("Install ERPLibre"),
                bool(self._base.get("installer_erplibre")),
                id="vmf_installer_erplibre",
            )
            yield Static("", id="vmf_erreurs", markup=False)
            with Horizontal(classes="boutons"):
                yield Button(t("Cancel"), id="vmf_non")
                yield Button(t("Confirm"), variant="primary", id="vmf_ok")

    def on_mount(self) -> None:
        for champ in CHAMPS_VM:
            self.query_one(f"#vmf_{champ}", Input).value = _texte(
                self._base.get(champ)
            )

    def on_button_pressed(self, event) -> None:
        event.stop()
        if event.button.id != "vmf_ok":
            self.dismiss(None)
            return
        valeurs = {
            c: self.query_one(f"#vmf_{c}", Input).value for c in CHAMPS_VM
        }
        for c in ("demarrer", "installer_erplibre"):
            valeurs[c] = self.query_one(f"#vmf_{c}", Checkbox).value
        vm = vm_depuis_saisie(self._base, valeurs)
        candidat = copy.deepcopy(self._spec)
        if self._index is None:
            candidat["vms"].append(vm)
        else:
            candidat["vms"][self._index] = vm
        erreurs = spec_parc.valider(candidat)
        if erreurs:
            texte = "\n".join(f"• {e}" for e in erreurs)
            self.query_one("#vmf_erreurs", Static).update(texte)
            return
        self.dismiss(vm)

    def action_annuler(self) -> None:
        self.dismiss(None)
