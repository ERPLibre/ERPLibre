#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le formulaire Textual des réglages de production, tiré du catalogue.

- run_settings_form(contexte, run_app=True) : le formulaire ; rend un
  `Resultat(doc, secrets_a_definir, secrets_a_retirer)`, ou None quand on
  l'annule. `run_app=False` rend l'application sans la lancer (tests).

À gauche, les groupes du profil et leurs compteurs ; à droite, une ligne
par champ du groupe choisi : son option, le widget de son genre (`Input`
dont le texte d'attente est le défaut, `Switch`, `TextArea` à un élément
par ligne), son aide et son erreur. La validation passe par
`ops_settings.convertir_saisie` et `profil.convertir` à chaque perte de
focus et à l'enregistrement ; « Enregistrer » reste inactif tant qu'une
erreur demeure. `ctrl+s` enregistre, `esc` annule, `ctrl+r` remet le champ
qui a le focus à son défaut.

Aucun secret ne se saisit ici : une trace fatale de Textual imprime les
variables locales, et le formulaire n'en contient donc aucun. Un champ
secret montre son état, calculé avant l'application (`etats_secrets`),
et deux cases : « définir après fermeture », dont la valeur est lue par
getpass une fois le terminal rendu, et « retirer », qui retire le champ
du profil : todo demande ensuite, défaut non, s'il supprime aussi
l'entrée KeePass. La logique pure
(`entrees`, `valeur_initiale`, `lire_saisie`, `assembler`) est séparée de
l'affichage.
"""

import collections

from script.lib_ops import profil
from script.todo import ops_settings
from script.todo.todo_i18n import t

# `catalogue` (`ops_settings.Catalogue`), `doc` (le brouillon), `chemin`
# (affiché), `nom` (le service, ou la cible de l'hôte), `etats_secrets`
# ({(groupe, clé): état}, voir `OpsSettingsMixin._ops_etats_secrets`),
# `coffre_configure` (un fichier KeePass est désigné).
Contexte = collections.namedtuple(
    "Contexte", "catalogue doc chemin nom etats_secrets coffre_configure"
)

Resultat = collections.namedtuple(
    "Resultat", "doc secrets_a_definir secrets_a_retirer"
)


def entrees(contexte):
    """[(index, Champ)] de tous les champs du catalogue, dans son ordre ;
    l'index nomme les widgets du champ."""
    resultat = []
    for champs in contexte.catalogue.champs.values():
        for champ in champs:
            resultat.append((len(resultat), champ))
    return resultat


def valeur_brute(champ, doc):
    """La valeur du profil `doc` pour `champ`, ou None."""
    return (doc.get(champ.groupe) or {}).get(champ.cle)


def valeur_initiale(champ, doc):
    """Ce que le widget du champ montre à l'ouverture : un booléen pour un
    `Switch`, un élément par ligne pour une liste, le texte de la valeur
    sinon ("" quand le profil n'en donne pas)."""
    brut = valeur_brute(champ, doc)
    if champ.genre in ("bool_vrai", "bool_faux"):
        return bool(brut)
    if champ.genre in ("liste_append", "liste_nargs"):
        return "\n".join(str(element) for element in brut or [])
    if brut is None or isinstance(brut, dict):
        return ""
    return str(brut)


def lire_saisie(champ, saisie):
    """(valeur brute ou None, message d'erreur ou None) d'une saisie :
    None vaut « absente du profil », le défaut de l'outil."""
    if champ.genre in ("bool_vrai", "bool_faux"):
        return (True, None) if saisie else (None, None)
    if champ.genre in ("liste_append", "liste_nargs"):
        elements = [ligne.strip() for ligne in saisie.splitlines()]
        elements = [element for element in elements if element]
        if not elements:
            return None, None
        try:
            profil.convertir(champ, elements)
        except profil.ErreurProfil as err:
            return None, err.message(t)
        return elements, None
    texte = (saisie or "").strip()
    if not texte:
        return None, None
    try:
        return ops_settings.convertir_saisie(champ, texte), None
    except profil.ErreurProfil as err:
        return None, err.message(t)


def assembler(contexte, saisies, cases):
    """Le profil que donnent les saisies.

    `saisies` : {index: saisie} des champs ordinaires ; `cases` : {index:
    (définir, retirer)} des champs secrets. Rend `(doc, erreurs,
    a_definir, a_retirer)` : `erreurs` ({index: message}),
    `a_definir` et `a_retirer` (chemins KeePass). « Retirer » l'emporte
    sur « définir » ; un secret défini prend la référence KeePass de son
    nom, jamais une valeur."""
    doc = {
        cle: valeur
        for cle, valeur in contexte.doc.items()
        if cle in profil.CLES_DOCUMENT
    }
    erreurs = {}
    a_definir = []
    a_retirer = []
    index_de = {}
    for index, champ in entrees(contexte):
        index_de[(champ.groupe, champ.cle)] = index
        if champ.secret:
            actuel = valeur_brute(champ, contexte.doc)
            definir, retirer = cases.get(index, (False, False))
            if retirer:
                if isinstance(actuel, dict):
                    a_retirer.append(actuel["kdbx"])
                continue
            if definir:
                reference = ops_settings.reference_secret(
                    contexte.nom, profil.SECRETS[(champ.groupe, champ.cle)]
                )
                brut = {"kdbx": reference}
                a_definir.append(reference)
            else:
                brut = actuel
        else:
            brut, erreur = lire_saisie(champ, saisies.get(index, ""))
            if erreur:
                erreurs[index] = erreur
                continue
        if brut is not None:
            doc.setdefault(champ.groupe, {})[champ.cle] = brut
    groupe, cles, _minimum = profil.BORNE_SOMME
    if groupe in contexte.catalogue.champs:
        try:
            profil.verifier_somme(
                doc.get(groupe) or {},
                ops_settings.defauts_du_groupe(contexte.catalogue, groupe),
            )
        except profil.ErreurProfil as err:
            for cle in cles:
                index = index_de.get((groupe, cle))
                if index is not None and index not in erreurs:
                    erreurs[index] = err.message(t)
                    break
    return doc, erreurs, a_definir, a_retirer


def etat_affiche(etat):
    """Le libellé de l'état d'un secret."""
    libelles = {
        "kdbx": t("in KeePass ✓"),
        "kdbx_attente": t("typed, stored in KeePass when saving"),
        "kdbx_absent": t("absent from KeePass"),
        "kdbx_inconnu": t("in KeePass, vault not opened"),
        "fichier": t("file given by its path"),
        "aucun": t("absent"),
    }
    return libelles.get(etat, etat)


def run_settings_form(contexte, run_app=True):
    """Le formulaire des réglages ; rend un `Resultat` ou None (annulé).
    `run_app=False` rend l'application sans la lancer."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import (
        Button,
        Checkbox,
        Footer,
        Header,
        Input,
        Label,
        OptionList,
        Static,
        Switch,
        TextArea,
    )
    from textual.widgets.option_list import Option

    liste = entrees(contexte)
    groupes = list(contexte.catalogue.champs)

    class FormulaireReglages(App):
        CSS = """
        #corps { height: 1fr; }
        #groupes { width: 34; border: solid $accent; }
        #champs { width: 1fr; padding: 0 1; }
        .titre { color: $accent; text-style: bold; padding: 1 0 0 0; }
        .champ { height: auto; padding: 0 0 1 0; }
        .champ TextArea { height: 5; }
        .aide { color: $text-muted; }
        .erreur { color: $error; }
        #actions { height: auto; padding: 0 1; }
        """
        BINDINGS = [
            ("ctrl+s", "enregistrer", t("Save")),
            ("escape", "annuler", t("Cancel")),
            ("ctrl+r", "defaut", t("Default value")),
        ]

        def __init__(self):
            super().__init__()
            self.resultat = None
            self.erreurs = {}

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal(id="corps"):
                yield OptionList(
                    *[
                        Option(
                            f"{ops_settings.nom_groupe(groupe)}"
                            f" {len(contexte.doc.get(groupe) or {})}"
                            f"/{len(contexte.catalogue.champs[groupe])}",
                            id=f"o-{rang}",
                        )
                        for rang, groupe in enumerate(groupes)
                    ],
                    id="groupes",
                )
                with VerticalScroll(id="champs"):
                    for rang, groupe in enumerate(groupes):
                        with Vertical(id=f"g-{rang}", classes="groupe"):
                            yield Static(
                                ops_settings.nom_groupe(groupe),
                                classes="titre",
                            )
                            for index, champ in liste:
                                if champ.groupe != groupe:
                                    continue
                                with Vertical(
                                    classes="champ", id=f"l-{index}"
                                ):
                                    yield Label(champ.option)
                                    yield from self._widgets(index, champ)
                                    yield Static(
                                        self._aide(champ), classes="aide"
                                    )
                                    yield Static(
                                        "", classes="erreur", id=f"e-{index}"
                                    )
            with Horizontal(id="actions"):
                yield Button(t("Save"), id="enregistrer", variant="primary")
                yield Button(t("Cancel"), id="annuler")
            yield Footer()

        @staticmethod
        def _aide(champ):
            texte = ops_settings.aide(champ)
            texte += f" ({t('default:')} {ops_settings.defaut_affiche(champ)})"
            if champ.portee == "installation":
                texte += " " + t(
                    "Applies at the next installation of the timer."
                )
            return texte.strip()

        def _widgets(self, index, champ):
            initiale = valeur_initiale(champ, contexte.doc)
            if champ.secret:
                etat = contexte.etats_secrets.get(
                    (champ.groupe, champ.cle), "aucun"
                )
                yield Static(etat_affiche(etat), id=f"s-{index}")
                yield Checkbox(
                    t("Set after closing"),
                    id=f"d-{index}",
                    disabled=not contexte.coffre_configure,
                )
                yield Checkbox(
                    t("Remove"),
                    id=f"r-{index}",
                    disabled=valeur_brute(champ, contexte.doc) is None,
                )
            elif champ.genre in ("bool_vrai", "bool_faux"):
                yield Switch(value=initiale, id=f"w-{index}")
            elif champ.genre in ("liste_append", "liste_nargs"):
                yield TextArea(initiale, id=f"w-{index}")
            else:
                yield Input(
                    value=initiale,
                    placeholder=ops_settings.defaut_affiche(champ),
                    id=f"w-{index}",
                )

        def on_mount(self) -> None:
            self._afficher_groupe(0)
            self._valider()

        def _afficher_groupe(self, rang):
            for autre in range(len(groupes)):
                self.query_one(f"#g-{autre}").display = autre == rang

        def on_option_list_option_highlighted(self, event) -> None:
            if event.option_index is not None:
                self._afficher_groupe(event.option_index)

        def _lire(self):
            saisies = {}
            cases = {}
            for index, champ in liste:
                if champ.secret:
                    cases[index] = (
                        self.query_one(f"#d-{index}", Checkbox).value,
                        self.query_one(f"#r-{index}", Checkbox).value,
                    )
                elif champ.genre in ("bool_vrai", "bool_faux"):
                    saisies[index] = self.query_one(
                        f"#w-{index}", Switch
                    ).value
                elif champ.genre in ("liste_append", "liste_nargs"):
                    saisies[index] = self.query_one(
                        f"#w-{index}", TextArea
                    ).text
                else:
                    saisies[index] = self.query_one(f"#w-{index}", Input).value
            return saisies, cases

        def _valider(self):
            saisies, cases = self._lire()
            resultat = assembler(contexte, saisies, cases)
            self.erreurs = resultat[1]
            for index, _champ in liste:
                self.query_one(f"#e-{index}", Static).update(
                    self.erreurs.get(index, "")
                )
            self.query_one("#enregistrer", Button).disabled = bool(
                self.erreurs
            )
            return resultat

        def on_descendant_blur(self, event) -> None:
            self._valider()

        def on_input_submitted(self, event) -> None:
            self._valider()

        def on_switch_changed(self, event) -> None:
            self._valider()

        def on_checkbox_changed(self, event) -> None:
            self._valider()

        def on_button_pressed(self, event) -> None:
            if event.button.id == "enregistrer":
                self.action_enregistrer()
            elif event.button.id == "annuler":
                self.action_annuler()

        def action_enregistrer(self) -> None:
            doc, erreurs, a_definir, a_retirer = self._valider()
            if erreurs:
                self.notify(t("Fix the errors first."), severity="error")
                return
            self.resultat = Resultat(doc, a_definir, a_retirer)
            self.exit(self.resultat)

        def action_annuler(self) -> None:
            self.resultat = None
            self.exit(None)

        def action_defaut(self) -> None:
            widget = self.focused
            identifiant = getattr(widget, "id", None) or ""
            if identifiant[:2] not in ("w-", "d-", "r-"):
                return
            if isinstance(widget, Switch):
                widget.value = False
            elif isinstance(widget, TextArea):
                widget.text = ""
            elif isinstance(widget, Input):
                widget.value = ""
            elif isinstance(widget, Checkbox):
                index = identifiant[2:]
                self.query_one(f"#d-{index}", Checkbox).value = False
                self.query_one(f"#r-{index}", Checkbox).value = False
            self._valider()

    app = FormulaireReglages()
    app.title = t("Production settings")
    app.sub_title = contexte.chemin
    if not run_app:
        return app
    app.run()
    return app.resultat
