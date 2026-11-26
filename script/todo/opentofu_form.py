#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Formulaire Textual d'un parc OpenTofu : éditer la spec, planifier,
appliquer, détruire.

Le formulaire travaille sur une copie profonde de la spec reçue et ne la
transmet qu'à `enregistrer`, après `spec.valider`. Les appels au moteur
tournent dans un worker léger (thread) : l'écran reste vivant, et le journal
du moteur y arrive ligne à ligne par `call_from_thread`. Le moteur reçoit sa
propre copie ; les champs qu'il résout pendant le plan reviennent dans le
formulaire et sont sauvés. Le coffre n'est lu que pour dire si le jeton est
présent : sa valeur n'entre dans aucun widget. Les modales vivent dans
`opentofu_form_ecrans`, importé à l'ouverture de l'écran : les fonctions
pures d'ici restent importables sans Textual.
"""

import copy

from script.opentofu import coffre, resolution
from script.opentofu import spec as spec_parc
from script.opentofu.moteur import (
    Resultat,
    est_destructeur,
    formater_plan,
    vms_detruites,
    vms_nouvelles,
)
from script.todo.todo_i18n import t

# Champs texte de la modale d'une VM, dans l'ordre d'affichage ; les deux
# booléens (`demarrer`, `installer_erplibre`) y sont des cases à cocher.
CHAMPS_VM = (
    "nom",
    "distro",
    "version",
    "arch",
    "vcpus",
    "ram",
    "disque",
    "ip",
    "passerelle",
    "dns",
    "vmid",
    "branche",
)
COLONNES_VM = ("nom", "distro", "version", "vcpus", "ram", "disque", "ip")
# Champs d'onglet : id de l'Input -> chemin dans la spec.
CHAMPS_FORMULAIRE = {
    "c_target": ("cible", "hote", "target"),
    "c_api_url": ("cible", "api_url"),
    "c_noeud": ("cible", "noeud"),
    "c_stockage": ("cible", "stockage"),
    "c_stockage_snippets": ("cible", "stockage_snippets"),
    "c_pont": ("cible", "pont"),
    "o_user": ("compte", "user"),
    "o_ssh_key": ("compte", "ssh_key"),
}
# Actions qu'un appel au moteur en cours désactive. `quit` (ctrl+q, de
# priorité) et la palette, qui offre « Quitter », en sont : quitter pendant
# un apply fermerait le tube de sortie de `tofu` en plein travail.
_ACTIONS_EXCLUSIVES = (
    "save",
    "plan",
    "apply",
    "destroy",
    "quitter",
    "quit",
    "command_palette",
)


def _entier_ou_texte(texte):
    """Entier si `texte` n'est fait que de chiffres ASCII, sinon le texte :
    `spec.valider` refuse ensuite ce texte avec son propre message."""
    return int(texte) if texte.isascii() and texte.isdigit() else texte


def vm_depuis_saisie(base, valeurs):
    """Copie de `base` mise à jour par `valeurs` ({champ: saisie}).

    `vcpus` et `ram` deviennent des entiers quand la saisie en est un ;
    `vmid` vide vaut None ; `dns` se découpe aux virgules ; un booléen passe
    tel quel. `base` n'est pas modifiée.

    Renommer une VM la fait détruire et recréer par le moteur : un VMID
    laissé tel quel se vide alors, pour que la VM neuve n'entre pas en
    collision avec celle qui part, et une adresse dérivée de ce VMID
    (`resolution.ip_derivee`) laissée telle quelle redevient `auto`. Un
    VMID ou une adresse que la saisie change est gardé.
    """
    vm = copy.deepcopy(base)
    for champ, valeur in valeurs.items():
        if isinstance(valeur, bool):
            vm[champ] = valeur
            continue
        texte = valeur.strip()
        if champ in ("vcpus", "ram"):
            vm[champ] = _entier_ou_texte(texte)
        elif champ == "vmid":
            vm[champ] = _entier_ou_texte(texte) if texte else None
        elif champ == "dns":
            vm[champ] = [x.strip() for x in texte.split(",") if x.strip()]
        else:
            vm[champ] = texte
    renommee = base.get("nom") and vm.get("nom") != base.get("nom")
    if renommee and base.get("vmid") is not None:
        if vm.get("vmid") == base["vmid"]:
            vm["vmid"] = None
            if vm.get("ip") == base.get("ip") and resolution.ip_derivee(base):
                vm.update(ip="auto", passerelle="", dns=[])
    return vm


def nouvelle_vm(spec):
    """VM à ajouter : copie de la dernière, sous le premier nom
    `<parc>-vm-<n>` libre, sans VMID ni adresse fixe (deux VM ne partagent
    ni l'un ni l'autre)."""
    pris = {vm.get("nom") for vm in spec["vms"]}
    n = 1
    while f"{spec['nom']}-vm-{n}" in pris:
        n += 1
    vm = copy.deepcopy(spec["vms"][-1]) if spec["vms"] else {}
    vm.update(nom=f"{spec['nom']}-vm-{n}", vmid=None, ip="auto")
    vm["passerelle"] = ""
    return vm


def etat_jeton(nom, racine):
    """« présent », « absent » ou « illisible » : jamais la valeur."""
    try:
        present = bool(coffre.lire(nom, racine).get("jeton"))
    except (OSError, ValueError, AttributeError):
        return t("unreadable file")
    return t("present") if present else t("absent")


def _texte(valeur):
    """Valeur de spec en texte de saisie : None vide, liste à virgules."""
    if valeur is None:
        return ""
    if isinstance(valeur, list):
        return ", ".join(str(x) for x in valeur)
    return str(valeur)


def run_opentofu_form(
    spec,
    moteur,
    enregistrer,
    *,
    quand_applique=None,
    quand_detruit=None,
    run_app=True,
):
    """Formulaire du parc `spec`. Rend la dernière spec sauvée par
    `enregistrer`, ou None si rien n'a été sauvé.

    Les deux rappels s'appellent APRÈS la sortie de l'écran (ils peuvent
    alors écrire et questionner dans le terminal), `quand_detruit` d'abord.
    `quand_detruit(spec)` : un destroy a réussi ; `spec` est la spec
    détruite. `quand_applique(spec, nouvelles, detruites)` : un apply a
    réussi après le dernier destroy ; `spec` est la dernière spec appliquée,
    `nouvelles` les VM que les plans appliqués créaient ou remplaçaient,
    `detruites` celles qu'ils détruisaient et que `spec` n'a plus.
    `run_app=False` rend l'application sans la lancer (tests sans terminal) ;
    `app.conclure()` fait alors ce qui suit la sortie.
    """
    from rich.text import Text
    from textual.app import App, ComposeResult
    from textual.binding import Binding
    from textual.containers import Horizontal, VerticalScroll
    from textual.css.query import NoMatches
    from textual.widgets import (
        Button,
        DataTable,
        Footer,
        Header,
        Input,
        Log,
        Static,
        TabbedContent,
        TabPane,
    )

    from script.todo.opentofu_form_ecrans import (
        EcranConfirmer,
        EcranNom,
        EcranVM,
        ligne,
    )

    racine = getattr(moteur, "racine", spec_parc.RACINE_PARCS)

    class FormulaireParc(App):
        """Les onglets de la spec en haut, le plan et le journal en bas."""

        BINDINGS = [
            Binding("s", "save", t("Save")),
            Binding("p", "plan", t("Plan")),
            Binding("a", "apply", t("Apply")),
            Binding("d", "destroy", t("Destroy")),
            Binding("q", "quitter", t("Quit")),
        ]
        CSS = """
            #onglets { height: 1fr; }
            .ligne { height: auto; }
            .ligne Label { width: 30; padding-top: 1; }
            .ligne Input { width: 1fr; }
            .compacte { height: 1; }
            .compacte Label { width: 36; padding-top: 0; }
            .note { color: $text-muted; padding: 1 0; }
            .boutons { height: auto; }
            #bas { height: 14; }
            #plan, #journal { width: 1fr; border: round $accent; }
        """

        def __init__(self):
            super().__init__()
            self.moteur = moteur
            self.s = copy.deepcopy(spec)
            # Dernière spec connue sur disque : celle reçue, puis chaque
            # spec passée à `enregistrer`.
            self._sauve = copy.deepcopy(spec)
            self.result = None
            # Changements du dernier plan de la session, None sans plan
            # valable : `a` n'applique que ce qui a été montré.
            self._plan = None
            self._occupe = False
            self._quitter_arme = False
            # Apply réussi dans la séance : la spec appliquée, les VM
            # créées ou remplacées et les VM détruites, pour
            # `quand_applique` après la sortie.
            self.applique = False
            self.spec_appliquee = None
            self.nouvelles = set()
            self.detruites = set()
            # Spec du dernier destroy réussi, pour `quand_detruit`.
            self.detruit = None

        def compose(self) -> ComposeResult:
            yield Header()
            with TabbedContent(id="onglets"):
                with TabPane(t("Target"), id="tab_cible"):
                    with VerticalScroll():
                        yield ligne(t("SSH target of the host"), "c_target")
                        yield Static("", id="c_jump", markup=False)
                        yield ligne(t("API URL"), "c_api_url")
                        yield ligne(t("Node"), "c_noeud")
                        yield ligne(t("Storage"), "c_stockage")
                        yield ligne(
                            t("Snippet storage"), "c_stockage_snippets"
                        )
                        yield ligne(t("Bridge"), "c_pont")
                        yield Static(
                            t(
                                "An empty field is resolved on the host at the "
                                "next plan."
                            ),
                            classes="note",
                        )
                with TabPane(t("VM"), id="tab_vm"):
                    yield DataTable(id="vms", cursor_type="row")
                    with Horizontal(classes="boutons"):
                        yield Button(t("Add"), id="vm_ajouter")
                        yield Button(t("Edit"), id="vm_editer")
                        yield Button(
                            t("Remove"), variant="error", id="vm_retirer"
                        )
                with TabPane(t("Options"), id="tab_options"):
                    yield ligne(t("Account user"), "o_user")
                    yield ligne(t("SSH public key"), "o_ssh_key")
                    yield Static(
                        t("Per-VM options are edited in the VM tab (Edit)."),
                        classes="note",
                    )
                    yield DataTable(id="options", cursor_type="row")
                with TabPane(t("OpenTofu"), id="tab_tofu"):
                    yield Static("", id="t_outil", markup=False)
                    yield Static("", id="t_jeton", markup=False)
            with Horizontal(id="bas"):
                yield Log(id="plan")
                yield Log(id="journal")
            yield Footer()

        def on_mount(self) -> None:
            self.title = t("OpenTofu fleet {nom}").format(nom=self.s["nom"])
            self.query_one("#plan", Log).border_title = t("Plan")
            self.query_one("#journal", Log).border_title = t("Journal")
            self.query_one("#vms", DataTable).add_columns(
                t("Name"),
                t("Distro"),
                t("Version"),
                t("vCPU"),
                t("RAM (MiB)"),
                t("Disk"),
                t("IP"),
            )
            self.query_one("#options", DataTable).add_columns(
                t("Name"),
                t("Start the VM"),
                t("Install ERPLibre"),
                t("ERPLibre branch"),
            )
            self._remplir()
            self._remplir_tofu()

        # Formulaire <-> spec

        def _remplir(self):
            """Champs, note du rebond et tableaux depuis `self.s`."""
            for ident, chemin in CHAMPS_FORMULAIRE.items():
                valeur = self.s
                for cle in chemin:
                    valeur = (valeur or {}).get(cle, "")
                self.query_one(f"#{ident}", Input).value = _texte(valeur)
            rebond = self.s["cible"]["hote"].get("jump") or "—"
            self.query_one("#c_jump", Static).update(
                t("Jump host (refused in v1): {jump}").format(jump=rebond)
            )
            self._remplir_tables()

        def _remplir_tables(self):
            vms = self.query_one("#vms", DataTable)
            options = self.query_one("#options", DataTable)
            curseur = vms.cursor_row
            vms.clear()
            options.clear()
            for vm in self.s["vms"]:
                vms.add_row(*(Text(_texte(vm.get(c))) for c in COLONNES_VM))
                options.add_row(
                    Text(_texte(vm.get("nom"))),
                    "✓" if vm.get("demarrer", True) else "—",
                    "✓" if vm.get("installer_erplibre") else "—",
                    Text(_texte(vm.get("branche"))),
                )
            if self.s["vms"]:
                vms.move_cursor(row=min(curseur, len(self.s["vms"]) - 1))

        def _remplir_tofu(self):
            ok, info = self.moteur.disponible()
            if ok:
                texte = t("Engine {nom}: version {version}").format(
                    nom=getattr(self.moteur, "nom", ""), version=info
                )
            else:
                texte = f"✗ {info}"
            self.query_one("#t_outil", Static).update(texte)
            nom = self.s["nom"]
            self.query_one("#t_jeton", Static).update(
                t("API token tofu@pve!{nom}: {etat}").format(
                    nom=nom, etat=etat_jeton(nom, racine)
                )
            )

        def _lire_formulaire(self):
            """Recopie les champs des onglets dans `self.s`."""
            for ident, chemin in CHAMPS_FORMULAIRE.items():
                noeud = self.s
                for cle in chemin[:-1]:
                    noeud = noeud.setdefault(cle, {})
                saisie = self.query_one(f"#{ident}", Input).value.strip()
                noeud[chemin[-1]] = saisie

        def _journal(self, texte):
            self.query_one("#journal", Log).write_line(texte)

        # Sauvegarde

        def _enregistrer(self):
            """Passe une copie de `self.s` à `enregistrer` ; vrai si sauvé."""
            copie = copy.deepcopy(self.s)
            try:
                enregistrer(copie)
            except (OSError, ValueError) as exc:
                self._journal(
                    "✗ " + t("Cannot save the spec: {err}").format(err=exc)
                )
                return False
            self._sauve = copie
            self.result = copy.deepcopy(copie)
            self._quitter_arme = False
            self._journal("✓ " + t("Spec saved."))
            return True

        def _sauver(self, forcer):
            """Valide le formulaire puis le sauve ; sans `forcer`, seulement
            s'il diffère de la dernière sauvegarde. Une spec modifiée rend le
            plan précédent caduc."""
            self._lire_formulaire()
            erreurs = spec_parc.valider(self.s)
            if erreurs:
                self._journal("✗ " + t("The spec has errors, nothing saved:"))
                for erreur in erreurs:
                    self._journal(f"    - {erreur}")
                return False
            if self.s == self._sauve and not forcer:
                return True
            if self.s != self._sauve:
                self._plan = None
            return self._enregistrer()

        # Actions

        def check_action(self, action, parameters):
            if action in _ACTIONS_EXCLUSIVES and self._occupe:
                return None
            return True

        def action_save(self) -> None:
            if not self._occupe:
                self._sauver(forcer=True)

        def action_plan(self) -> None:
            if not self._occupe and self._sauver(forcer=False):
                self._lancer("planifier")

        def action_apply(self) -> None:
            if self._occupe:
                return
            self._lire_formulaire()
            if self._plan is None or self.s != self._sauve:
                self._plan = None
                self._journal("✗ " + t("Plan first."))
                return
            if not self._plan:
                self._journal(t("Nothing to apply."))
                return

            def suite(ok):
                if ok:
                    self._lancer("appliquer")
                else:
                    self._annule(ok)

            if est_destructeur(self._plan):
                message = t("This plan replaces or destroys VMs.")
                self.push_screen(EcranNom(message, self.s["nom"]), suite)
            else:
                lignes = formater_plan(self._plan) + [t("Apply this plan?")]
                self.push_screen(EcranConfirmer(lignes), suite)

        def action_destroy(self) -> None:
            if self._occupe:
                return
            message = t("This destroys every VM of fleet {nom}: {vms}").format(
                nom=self.s["nom"],
                vms=", ".join(vm["nom"] for vm in self.s["vms"]),
            )

            def suite(ok):
                if ok:
                    self._lancer("detruire")
                else:
                    self._annule(ok)

            self.push_screen(EcranNom(message, self.s["nom"]), suite)

        def _annule(self, ok):
            """False : nom retapé faux ; None : annulation."""
            if ok is False:
                self._journal("✗ " + t("The name does not match: cancelled."))
            else:
                self._journal(t("Cancelled."))

        def action_quitter(self) -> None:
            if self._occupe:
                return
            self._lire_formulaire()
            if self.s == self._sauve:
                self._quitter_arme = False
            elif not self._quitter_arme:
                self._quitter_arme = True
                self._journal(
                    t("Unsaved changes: press q again to quit without saving.")
                )
                return
            self.exit(self.result)

        # Tableau des VM

        def on_button_pressed(self, event) -> None:
            ident = event.button.id
            index = self.query_one("#vms", DataTable).cursor_row
            if ident == "vm_ajouter":
                self._ouvrir_vm(None)
            elif ident == "vm_editer" and 0 <= index < len(self.s["vms"]):
                self._ouvrir_vm(index)
            elif ident == "vm_retirer" and 0 <= index < len(self.s["vms"]):
                if len(self.s["vms"]) <= 1:
                    self._journal("✗ " + t("A fleet keeps at least one VM."))
                    return
                del self.s["vms"][index]
                self._remplir_tables()

        def _ouvrir_vm(self, index):
            self._lire_formulaire()

            def suite(vm):
                if vm is None:
                    return
                if index is None:
                    self.s["vms"].append(vm)
                else:
                    self.s["vms"][index] = vm
                self._remplir_tables()

            self.push_screen(EcranVM(self.s, index), suite)

        # Moteur

        def _occuper(self, occupe):
            """Pendant un appel au moteur, les onglets et les actions qui
            touchent la spec sont désactivés."""
            self._occupe = occupe
            self.query_one("#onglets").disabled = occupe
            self.refresh_bindings()

        def _lancer(self, operation):
            """Lance `planifier`, `appliquer` ou `detruire` dans un thread
            sur une copie de la spec ; `_fin` reprend la main dans l'écran."""
            self._occuper(True)
            travail = copy.deepcopy(self.s)

            def vers_ecran(fonction, *args):
                """Exécute `fonction` dans l'écran ; ne lève pas si l'écran
                a disparu : le moteur doit continuer à lire la sortie de
                `tofu`, sans quoi son tube se ferme en plein travail."""
                try:
                    self.call_from_thread(fonction, *args)
                except (NoMatches, RuntimeError):
                    pass

            def journal(texte):
                vers_ecran(self._journal, texte)

            def tache():
                changements = None
                try:
                    if operation == "planifier":
                        res, changements = moteur.planifier(travail, journal)
                    else:
                        res = getattr(moteur, operation)(travail, journal)
                # Une exception qui sortirait du thread fermerait l'écran et
                # son journal : elle devient un échec affiché.
                except Exception as exc:
                    res = Resultat(False, str(exc) or type(exc).__name__, 1)
                vers_ecran(self._fin, operation, res, changements, travail)

            self.run_worker(tache, thread=True, group="moteur")

        def _fin(self, operation, res, changements, travail):
            self._occuper(False)
            if res.message:
                self._journal(("✓ " if res.ok else "✗ ") + res.message)
            if operation == "appliquer" and res.ok:
                self.applique = True
                self.spec_appliquee = copy.deepcopy(travail)
                self.nouvelles |= vms_nouvelles(self._plan or ())
                self.detruites |= vms_detruites(self._plan or (), travail)
            if operation == "detruire" and res.ok:
                # Les VM d'un apply antérieur n'existent plus : rien à
                # attendre ni à installer, et les alias que cet apply
                # devait retirer partent avec ceux du destroy.
                self.detruit = copy.deepcopy(travail)
                self.detruit["vms"] += [
                    {"nom": nom}
                    for nom in sorted(self.detruites)
                    if nom not in {vm["nom"] for vm in travail["vms"]}
                ]
                self.applique = False
                self.spec_appliquee = None
                self.nouvelles = set()
                self.detruites = set()
            if operation != "planifier":
                self._plan = None
                return
            plan = self.query_one("#plan", Log)
            plan.clear()
            self._plan = changements if res.ok else None
            plan.write_lines(
                formater_plan(changements) if res.ok else [res.message]
            )
            # Champs résolus par le moteur (nœud, stockage, pont, VMID...).
            if travail != self.s:
                self.s = travail
                self._remplir()
                self._enregistrer()

        def conclure(self):
            """Après la sortie de l'écran : `quand_detruit` si un destroy a
            réussi, puis `quand_applique` si un apply a réussi après lui ;
            rend la dernière spec sauvée, ou None."""
            if self.detruit is not None and quand_detruit is not None:
                quand_detruit(copy.deepcopy(self.detruit))
            if self.applique and quand_applique is not None:
                gardees = {vm["nom"] for vm in self.spec_appliquee["vms"]}
                quand_applique(
                    copy.deepcopy(self.spec_appliquee),
                    set(self.nouvelles),
                    self.detruites - gardees,
                )
            return self.result

    app = FormulaireParc()
    if not run_app:
        return app
    app.run()
    return app.conclure()
