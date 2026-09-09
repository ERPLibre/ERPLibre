#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Écran de périmètre pour « Transform data », en TUI.

Deux décisions y sont prises, que les invites textuelles ne savent pas
poser :

- QUELLES LIGNES nomment les colonnes. Le moteur les mesure, mais la
  mesure se trompe dans les deux sens et l'opérateur doit pouvoir la
  contredire — y compris en désignant PLUSIEURS lignes, un export portant
  souvent une ligne de catégorie au-dessus de la ligne de champs.
- QUELLES COLONNES rester intactes. Sur un classeur ordinaire, neuf
  colonnes du même type, du même compte et sans bornes ne se départagent
  par rien d'autre que des VALEURS D'EXEMPLE, et taper des indices à
  l'aveugle dans une invite n'est pas une réponse.

- run_transform_form(ctx, run_app=True) : rend une spec, `None` si
  l'opérateur annule, `{}` pour retomber sur les invites textuelles.

Le contrat a TROIS valeurs et non deux : rendre `None` là où l'appelant
attend `{}` supprimerait le repli textuel en silence.

`ctx` est de la donnée PURE, bâtie par `contexte_depuis_rapport()` à
partir du JSON de `--report` déjà en main : aucune entrée-sortie et aucun
sous-processus depuis l'affichage.
"""
from __future__ import annotations

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# Ce que la ligne d'une colonne montre. Les largeurs sont en dur et la
# colonne des exemples vient EN DERNIER, pour absorber ce qui reste.
LARGEURS = ((6, 4), (4, 4), (22, 22), (9, 9), (8, 8), (9, 9))

# Le marqueur d'une colonne, à l'écran. Un caractère chacun : un glyphe
# double-largeur décalerait la colonne suivante.
MARQUE_EN_PORTEE = "[ ]"
MARQUE_INTACTE = "[x]"
MARQUE_PLANCHER = "[!]"


def contexte_depuis_rapport(rapport):
    """Le contexte de l'écran, tiré du rapport du moteur.

    Pure transformation de données : c'est ce qui rend l'écran testable
    sans fichier, et ce qui garantit qu'il n'ouvre rien lui-même.
    """
    return {
        "fichier": rapport.get("chemin", ""),
        "format": rapport.get("format", ""),
        "feuilles": [
            {
                "nom": feuille.get("nom", ""),
                "lignes": feuille.get("lignes", 0),
                "colonnes_n": feuille.get("colonnes_n", 0),
                "lignes_entete": list(feuille.get("lignes_entete") or []),
                "ligne_champs": feuille.get("ligne_champs"),
                "entete_declaree": bool(feuille.get("entete_declaree")),
                "lignes_sondees": list(feuille.get("lignes_sondees") or []),
                "colonnes": [
                    {
                        "index": colonne.get("index"),
                        "etiquette": colonne.get("etiquette") or "",
                        "type": colonne.get("type", ""),
                        "remplies": colonne.get("remplies", 0),
                        "distinctes": colonne.get("distinctes", 0),
                        "exemples": list(colonne.get("exemples") or []),
                        "plancher": bool(colonne.get("plancher")),
                    }
                    for colonne in (feuille.get("colonnes") or [])
                ],
            }
            for feuille in (rapport.get("feuilles") or [])
        ],
    }


def libelle_de_colonne(colonne, marque):
    """Les six cellules d'une ligne de colonne, prêtes à afficher.

    `‹sans libellé›` plutôt qu'un blanc : c'est le cas de la majorité des
    colonnes d'un export réel, et un blanc se lit comme une erreur
    d'affichage plutôt que comme un fait.
    """
    return (
        marque,
        str(colonne["index"]),
        colonne["etiquette"] or t("‹no label›"),
        colonne["type"],
        str(colonne["remplies"]),
        str(colonne["distinctes"]),
        " · ".join(colonne["exemples"]),
    )


def libelle_de_ligne_sondee(ligne, cochee):
    """Les quatre cellules d'une ligne sondée.

    Les mesures sont montrées pour que l'opérateur voie POURQUOI la
    mesure a tranché avant de la contredire — contredire un verdict qu'on
    ne voit pas est un pari.
    """
    mesure = ligne.get("mesure") or {}
    return (
        MARQUE_INTACTE if cochee else MARQUE_EN_PORTEE,
        str(ligne["numero"]),
        " · ".join(ligne.get("apercu") or []),
        (
            "%s %.2f  %s %.2f  %s %.2f"
            % (
                t("sig type"),
                mesure.get("contraste", 0.0),
                t("off-col"),
                mesure.get("hors_colonne", 0.0),
                t("shape"),
                mesure.get("accord", 0.0),
            )
            if mesure
            else ""
        ),
    )


def cle_de_colonne(colonne):
    """Ce par quoi une réponse DÉSIGNE cette colonne.

    L'étiquette quand il y en a une, l'index sinon — exactement la règle
    de `colonne_repondue`, faute de quoi l'écran cocherait une case dont
    la réponse ne porterait pas.
    """
    etiquette = (colonne.get("etiquette") or "").strip()
    return etiquette or str(colonne["index"])


def basculer(ensemble, valeur):
    """Ajouter ou retirer, et dire ce qui en résulte.

    Séparé du rendu pour être éprouvable : les méthodes de l'écran
    appellent celle-ci PUIS redessinent, si bien que la décision se teste
    sans monter un seul widget.
    """
    if valeur in ensemble:
        ensemble.discard(valeur)
        return False
    ensemble.add(valeur)
    return True


def spec_depuis_etat(ctx, intactes, entetes):
    """La spec rendue à l'appelant, en types SÉRIALISABLES.

    Un `set` et un dict à clés tuple sont refusés par `json.dumps`, et
    ces valeurs traversent le sous-processus du moteur : ce sont donc des
    listes triées, et des dicts à clés `str`.
    """
    return {
        "colonnes_intactes_par_feuille": {
            nom: sorted(cles) for nom, cles in intactes.items() if cles
        },
        "entetes_par_feuille": {
            feuille["nom"]: sorted(entetes.get(feuille["nom"], set()))
            for feuille in ctx["feuilles"]
        },
    }


def run_transform_form(ctx, run_app: bool = True):
    """Écran de périmètre. Rend une spec, None si annulé, {} pour les
    invites textuelles. `run_app=False` rend l'instance sans la lancer
    (tests headless)."""
    # TOUS les imports textual ICI : le CLI importe ce module pour ses
    # fonctions pures, et les libellés des BINDINGS ne doivent être
    # évalués qu'à l'appel, après le choix de la langue.
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, Vertical
    from textual.widgets import DataTable, Footer, Header, OptionList, Static
    from textual.widgets.option_list import Option

    resultat = {"spec": None}
    # Par feuille : les clés de colonne laissées intactes, et l'empan
    # d'en-tête. L'empan part de ce que le moteur a MESURÉ ; les cases de
    # colonne partent vides, une réponse n'étant jamais pré-cochée.
    intactes = {f["nom"]: set() for f in ctx["feuilles"]}
    entetes = {
        f["nom"]: set(f["lignes_entete"] or ()) for f in ctx["feuilles"]
    }
    corrigees = set()

    class Perimetre(App):
        CSS = """
        #tete { height: auto; padding: 0 1; color: $text-muted; }
        #feuilles { width: 30; border: solid $panel; }
        #colonnes { height: 1fr; border: solid $accent; }
        #sondees { height: 14; border: solid $panel; }
        #legende { height: auto; color: $text-muted; padding: 0 1; }
        """
        BINDINGS = [
            ("space", "basculer", t("Toggle the current row")),
            ("f2", "intacte", t("Leave this column untouched")),
            ("f4", "rendre", t("Clear this sheet")),
            ("f5", "accepter", t("Accept")),
            ("f9", "invites", t("Fall back to text prompts")),
            ("escape", "annuler", t("Cancel")),
        ]

        def __init__(self):
            super().__init__()
            self.rang_feuille = 0
            # Poser `highlighted` ÉMET l'événement de surbrillance,
            # délivré PLUS TARD : avant que les tableaux soient dans le
            # DOM au montage, et après qu'un verrou temporel se serait
            # relâché. D'où deux parades distinctes — tolérer un DOM
            # incomplet, et ne redessiner que si la feuille a VRAIMENT
            # changé. Mesuré sans la seconde : 327 rendus au montage et
            # 728 par touche, soit deux secondes par frappe.
            self._pret = False

        # -- montage ---------------------------------------------------- #
        def compose(self) -> ComposeResult:
            yield Header()
            yield Static(
                "  %s  ·  %s" % (ctx["fichier"], ctx["format"]), id="tete"
            )
            with Horizontal():
                yield OptionList(id="feuilles")
                with Vertical():
                    yield DataTable(id="colonnes")
                    yield DataTable(id="sondees")
            yield Static(
                "  %s" % t("[x] untouched · [!] floored, not answerable"),
                id="legende",
            )
            yield Footer()

        def on_mount(self) -> None:
            self.title = t("Transform — anonymisation scope")
            liste = self.query_one("#feuilles", OptionList)
            for feuille in ctx["feuilles"]:
                liste.add_option(
                    Option(self._resume_feuille(feuille), id=feuille["nom"])
                )
            colonnes = self.query_one("#colonnes", DataTable)
            colonnes.cursor_type = "row"
            colonnes.add_columns(
                "",
                "#",
                t("column label"),
                t("column type"),
                t("filled"),
                t("distinct"),
                t("examples"),
            )
            sondees = self.query_one("#sondees", DataTable)
            sondees.cursor_type = "row"
            sondees.add_columns(
                "",
                t("row no"),
                t("first values"),
                t("measures"),
            )
            self._pret = True
            if ctx["feuilles"]:
                liste.highlighted = 0
            self._remplir()

        # -- rendu ------------------------------------------------------ #
        def _feuille(self):
            if not ctx["feuilles"]:
                return None
            return ctx["feuilles"][self.rang_feuille]

        @staticmethod
        def _resume_feuille(feuille):
            """« Ventes  1 * » — le rang de la ligne de champs, ou « - ».

            L'astérisque dit que l'opérateur a corrigé la mesure : sans
            lui, une correction et un verdict se lisent pareil.
            """
            empan = sorted(entetes.get(feuille["nom"], set()))
            rang = str(max(empan)) if empan else "-"
            marque = " *" if feuille["nom"] in corrigees else ""
            return " %-20s %s%s" % (feuille["nom"][:20], rang, marque)

        def _widget(self, selecteur, genre):
            """Le widget s'il est DÉJÀ dans le DOM, sinon None.

            Textual délivre ses messages de façon asynchrone : un
            événement de surbrillance émis au montage arrive avant que
            les tableaux soient montés, et `query_one` y lève. Tolérer
            l'absence vaut mieux qu'un verrou temporel, qui suppose un
            ordre que rien ne garantit.
            """
            trouves = self.query(selecteur)
            return trouves.first(genre) if trouves else None

        def _remplir(self):
            feuille = self._feuille()
            if feuille is None or not self._pret:
                return
            colonnes = self._widget("#colonnes", DataTable)
            sondees_w = self._widget("#sondees", DataTable)
            liste_w = self._widget("#feuilles", OptionList)
            if colonnes is None or sondees_w is None or liste_w is None:
                return
            garde = colonnes.cursor_row
            colonnes.clear()
            for colonne in feuille["colonnes"]:
                if colonne["plancher"]:
                    marque = MARQUE_PLANCHER
                elif cle_de_colonne(colonne) in intactes[feuille["nom"]]:
                    marque = MARQUE_INTACTE
                else:
                    marque = MARQUE_EN_PORTEE
                colonnes.add_row(*libelle_de_colonne(colonne, marque))
            if 0 <= garde < len(feuille["colonnes"]):
                colonnes.move_cursor(row=garde)

            sondees = sondees_w
            garde = sondees.cursor_row
            sondees.clear()
            for ligne in feuille["lignes_sondees"]:
                sondees.add_row(
                    *libelle_de_ligne_sondee(
                        ligne,
                        ligne["numero"] in entetes[feuille["nom"]],
                    )
                )
            if 0 <= garde < len(feuille["lignes_sondees"]):
                sondees.move_cursor(row=garde)

        def _rafraichir_les_feuilles(self):
            """Le résumé d'une feuille change quand son EMPAN change.

            Hors du rendu des tableaux, et appelé seulement par ce qui
            touche l'empan : reconstruire la liste réémet la surbrillance,
            et le faire à chaque rendu bouclait.
            """
            liste = self._widget("#feuilles", OptionList)
            if liste is None:
                return
            rang = liste.highlighted
            liste.clear_options()
            for autre in ctx["feuilles"]:
                liste.add_option(
                    Option(self._resume_feuille(autre), id=autre["nom"])
                )
            if rang is not None:
                liste.highlighted = rang

        # -- navigation ------------------------------------------------- #
        def on_option_list_option_highlighted(self, event) -> None:
            if not self._pret:
                return
            noms = [f["nom"] for f in ctx["feuilles"]]
            if event.option.id not in noms:
                return
            rang = noms.index(event.option.id)
            # LA garde : reconstruire la liste réémet cet événement avec
            # le MÊME rang. Ne redessiner que sur un changement réel coupe
            # la boucle à sa racine, là où un verrou temporel échoue,
            # l'événement étant délivré après son relâchement.
            if rang == self.rang_feuille:
                return
            self.rang_feuille = rang
            self._remplir()

        # -- décisions -------------------------------------------------- #
        def basculer_colonne(self, rang):
            """Une colonne PLANCHÉIÉE ne se coche pas.

            Le plancher passe avant la réponse dans l'ordre des gardes :
            une case qui ne changerait rien serait un mensonge.
            """
            feuille = self._feuille()
            if feuille is None or not (0 <= rang < len(feuille["colonnes"])):
                return
            colonne = feuille["colonnes"][rang]
            if colonne["plancher"]:
                self.notify(t("This column is floored: no answer applies."))
                return
            basculer(intactes[feuille["nom"]], cle_de_colonne(colonne))
            self._remplir()

        def basculer_ligne(self, rang):
            feuille = self._feuille()
            sondees = feuille["lignes_sondees"] if feuille else []
            if not (0 <= rang < len(sondees)):
                return
            basculer(entetes[feuille["nom"]], sondees[rang]["numero"])
            corrigees.add(feuille["nom"])
            self._remplir()
            self._rafraichir_les_feuilles()

        def action_basculer(self) -> None:
            """L'espace agit sur le panneau qui a le focus."""
            focus = self.focused
            if focus is None:
                return
            if focus is self._widget("#sondees", DataTable):
                self.basculer_ligne(focus.cursor_row)
            elif focus is self._widget("#colonnes", DataTable):
                self.basculer_colonne(focus.cursor_row)

        def action_intacte(self) -> None:
            colonnes = self._widget("#colonnes", DataTable)
            if colonnes is not None:
                self.basculer_colonne(colonnes.cursor_row)

        def action_rendre(self) -> None:
            """Rendre la feuille à ce que le moteur a mesuré."""
            feuille = self._feuille()
            if feuille is None:
                return
            intactes[feuille["nom"]] = set()
            entetes[feuille["nom"]] = set(feuille["lignes_entete"] or ())
            corrigees.discard(feuille["nom"])
            self._remplir()
            self._rafraichir_les_feuilles()

        def action_accepter(self) -> None:
            resultat["spec"] = spec_depuis_etat(ctx, intactes, entetes)
            self.exit()

        def action_invites(self) -> None:
            """Rendre `{}` et non `None` : l'appelant distingue
            « poser les questions » de « annuler »."""
            resultat["spec"] = {}
            self.exit()

        def action_annuler(self) -> None:
            resultat["spec"] = None
            self.exit()

    app = Perimetre()
    # Lus par les tests headless, qui pilotent l'app sans écran.
    app._resultat = resultat
    app._intactes = intactes
    app._entetes = entetes
    app._corrigees = corrigees
    if not run_app:
        return app
    app.run()
    return resultat["spec"]
