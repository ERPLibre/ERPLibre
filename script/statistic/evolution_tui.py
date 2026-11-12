#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran de l'évolution des modules Odoo par année.

Il lit les fichiers que show_evolution_module.py écrit à la racine de ses
clones (« evolution_modules*.json », un par filtre) : sans fichier, rien à
montrer, et l'appelant le dit plutôt que d'ouvrir un écran vide.

Le graphique se dessine en caractères braille, chaque cellule du terminal
portant 2 × 4 points : aucune bibliothèque de tracé n'est requise, et le
venv d'ERPLibre n'en installe pas. Une courbe par version d'Odoo, et une
courbe des modules UNIQUES, toutes versions confondues, tracée en dernier
pour rester visible là où elle croise les autres. Le tableau sous le
graphique donne les nombres exacts que le tracé arrondit ; « d » y ajoute
le détail par dépôt de la dernière année, quand la passe l'a enregistré.

Lecture seule : l'écran ne lance aucune passe et n'écrit rien.
"""

import glob
import json
import os
import sys

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


MOTIF = "evolution_modules*.json"
UNIQUES = "uniques"

# Une couleur par courbe, dans l'ordre des versions ; la courbe des uniques
# a la sienne, réservée.
PALETTE = (
    "cyan",
    "green",
    "yellow",
    "magenta",
    "blue",
    "red",
    "bright_cyan",
    "bright_green",
    "bright_yellow",
    "bright_magenta",
    "bright_blue",
    "bright_red",
    "orange3",
    "purple",
)
COULEUR_UNIQUES = "bold white"

# Bit de chaque point d'une cellule braille, indexé [x][y] : x de 0 à 1,
# y de 0 (haut) à 3 (bas).
_BITS = ((0x01, 0x02, 0x04, 0x40), (0x08, 0x10, 0x20, 0x80))


def lire_jeux(dossier):
    """[(fichier, données)] des fichiers de statistique de `dossier`,
    triés par nom ; un fichier illisible est ignoré."""
    jeux = []
    for chemin in sorted(glob.glob(os.path.join(dossier, MOTIF))):
        try:
            with open(chemin, encoding="utf-8") as fh:
                donnees = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(donnees, dict) and donnees.get("annees"):
            jeux.append((chemin, donnees))
    return jeux


def nom_du_jeu(donnees):
    """« Tous les dépôts », ou le filtre de la passe."""
    filtre = donnees.get("filtre") or ""
    return filtre.strip("/") or t("All repositories")


def series(donnees):
    """(étiquettes de l'axe x, {nom: [valeur ou None]}) : une série par
    version d'Odoo, dans l'ordre des versions, puis celle des uniques.

    Une version absente d'une année — sortie après la date de coupe — vaut
    None : la courbe commence là où la version existe."""
    annees = donnees.get("annees") or []
    etiquettes = [(a.get("date") or "—")[:4] for a in annees]
    versions = sorted(
        {v for a in annees for v in (a.get("par_version") or {})},
        key=lambda v: float(v),
    )
    res = {
        v: [(a.get("par_version") or {}).get(v) for a in annees]
        for v in versions
    }
    res[UNIQUES] = [a.get("uniques") for a in annees]
    return etiquettes, res


def couleurs(noms):
    """{nom: style} : la palette dans l'ordre, les uniques à part."""
    res = {}
    for i, nom in enumerate(n for n in noms if n != UNIQUES):
        res[nom] = PALETTE[i % len(PALETTE)]
    res[UNIQUES] = COULEUR_UNIQUES
    return res


def _segment(x0, y0, x1, y1):
    """Les points entiers d'un segment (Bresenham)."""
    dx, dy = abs(x1 - x0), -abs(y1 - y0)
    sx, sy = (1 if x0 < x1 else -1), (1 if y0 < y1 else -1)
    err = dx + dy
    while True:
        yield x0, y0
        if (x0, y0) == (x1, y1):
            return
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def tracer(courbes, largeur, hauteur, ymax=None):
    """La grille braille de `courbes` ({nom: [valeur ou None]}), dans l'ordre
    du dict : la dernière l'emporte sur une cellule partagée.

    Rend (lignes, ymax) : `hauteur` lignes de `largeur` cellules, chacune
    (caractère, nom de la courbe ou None)."""
    largeur, hauteur = max(largeur, 2), max(hauteur, 2)
    valeurs = [v for c in courbes.values() for v in c if v is not None]
    ymax = ymax or max(valeurs, default=0) or 1
    n = max((len(c) for c in courbes.values()), default=0)
    pts_x, pts_y = 2 * largeur - 1, 4 * hauteur - 1
    masques = [[0] * largeur for _ in range(hauteur)]
    proprio = [[None] * largeur for _ in range(hauteur)]

    def point(x, y, nom):
        cx, cy = x // 2, y // 4
        masques[cy][cx] |= _BITS[x % 2][y % 4]
        proprio[cy][cx] = nom

    for nom, valeurs_c in courbes.items():
        precedent = None
        for i, v in enumerate(valeurs_c):
            if v is None:
                precedent = None
                continue
            x = round(i * pts_x / (n - 1)) if n > 1 else 0
            y = pts_y - round(v / ymax * pts_y)
            if precedent:
                for px, py in _segment(*precedent, x, y):
                    point(px, py, nom)
            else:
                point(x, y, nom)
            precedent = (x, y)
    lignes = [
        [
            (
                chr(0x2800 + masques[r][c]) if masques[r][c] else " ",
                proprio[r][c],
            )
            for c in range(largeur)
        ]
        for r in range(hauteur)
    ]
    return lignes, ymax


def noms_des_courbes(jeux):
    """Les courbes de tous les jeux : versions d'Odoo dans leur ordre, puis
    celle des uniques. C'est la liste qu'on coche pour afficher ou cacher."""
    versions = {
        nom
        for _c, donnees in jeux
        for nom in series(donnees)[1]
        if nom != UNIQUES
    }
    return sorted(versions, key=float) + [UNIQUES]


def graphique(donnees, largeur, hauteur, cachees=frozenset()):
    """Le graphique de `donnees` en rich.text.Text : axe des y gradué à
    gauche, années sous l'axe des x, une couleur par courbe.

    Les courbes de `cachees` ne sont pas tracées, et l'axe des y se règle
    sur celles qui restent : cacher la courbe des uniques, la plus haute,
    agrandit les autres. Chaque courbe garde sa couleur quoi qu'on cache."""
    from rich.text import Text

    etiquettes, courbes = series(donnees)
    styles = couleurs(courbes)
    montrees = {n: v for n, v in courbes.items() if n not in cachees}
    marge = 7
    zone = max(largeur - marge, 10)
    lignes, ymax = tracer(montrees, zone, max(hauteur - 2, 4))
    texte = Text()
    for r, ligne in enumerate(lignes):
        if r == 0:
            graduation = f"{ymax:>6} "
        elif r == len(lignes) - 1:
            graduation = f"{0:>6} "
        elif r == len(lignes) // 2:
            graduation = f"{ymax // 2:>6} "
        else:
            graduation = " " * 6 + " "
        texte.append(graduation[:marge], style="dim")
        for car, nom in ligne:
            texte.append(car, style=styles.get(nom, ""))
        texte.append("\n")
    texte.append(" " * marge + "└" + "─" * (zone - 1) + "\n", style="dim")
    axe = [" "] * zone
    n = len(etiquettes)
    for i, etiquette in enumerate(etiquettes):
        debut = round(i * (zone - len(etiquette)) / (n - 1)) if n > 1 else 0
        for j, car in enumerate(etiquette):
            if 0 <= debut + j < zone:
                axe[debut + j] = car
    texte.append(" " * marge + "".join(axe), style="dim")
    return texte


def legende(donnees, cachees=frozenset()):
    """Les courbes et leur couleur, sur une ligne ; une courbe cachée y
    reste, estompée et barrée, pour qu'on sache qu'elle existe."""
    from rich.text import Text

    _, courbes = series(donnees)
    styles = couleurs(courbes)
    texte = Text()
    for nom in courbes:
        libelle = t("unique modules") if nom == UNIQUES else nom
        if nom in cachees:
            texte.append(f"── {libelle}   ", style="dim strike")
            continue
        texte.append("━━ ", style=styles[nom])
        texte.append(f"{libelle}   ")
    return texte


def lignes_tableau(donnees):
    """(en-têtes, rangées) des nombres exacts, une rangée par année."""
    etiquettes, courbes = series(donnees)
    entetes = [t("Year")] + [
        t("unique modules") if n == UNIQUES else n for n in courbes
    ]
    rangees = [
        [etiquette]
        + [
            "" if courbes[n][i] is None else str(courbes[n][i])
            for n in courbes
        ]
        for i, etiquette in enumerate(etiquettes)
    ]
    return entetes, rangees


def lignes_par_depot(donnees):
    """(date, en-têtes, rangées) du détail par dépôt de la DERNIÈRE année :
    une rangée par dépôt, ses modules par version puis leur somme, le plus
    gros dépôt d'abord. Rangées vides pour une passe qui n'a pas enregistré
    ce détail."""
    annees = donnees.get("annees") or []
    if not annees:
        return "", [], []
    derniere = annees[-1]
    par_depot = derniere.get("par_depot") or {}
    versions = sorted(
        {v for d in par_depot.values() for v in d}, key=lambda v: float(v)
    )
    rangees = sorted(
        (
            [depot]
            + [str(par_depot[depot].get(v, "")) for v in versions]
            + [str(sum(par_depot[depot].values()))]
            for depot in par_depot
        ),
        key=lambda r: (-int(r[-1]), r[0]),
    )
    entetes = [t("Repository")] + versions + [t("Total")]
    return (derniere.get("date") or "")[:10], entetes, rangees


def build_app(jeux):
    """L'application Textual sur `jeux` (rendu de lire_jeux, non vide).
    Une touche par jeu, et « b » pour les montrer tous l'un sous l'autre.

    La colonne de gauche coche les courbes à tracer — chaque version d'Odoo
    et les modules uniques — dans tous les jeux à la fois ; « a » les
    remet toutes. Le tableau garde toutes les colonnes : il donne les
    chiffres exacts, ce que le graphique montre ou non."""
    from textual.app import App, ComposeResult
    from textual.containers import Horizontal, VerticalScroll
    from textual.widgets import (
        DataTable,
        Footer,
        Header,
        SelectionList,
        Static,
    )
    from textual.widgets.selection_list import Selection

    noms = noms_des_courbes(jeux)

    class EvolutionApp(App):
        TITLE = t("Odoo module evolution per year")
        CSS = """
        .titre { padding: 1 1 0 1; text-style: bold; }
        .graphique { height: 22; padding: 0 1; }
        .legende { padding: 0 1; }
        DataTable { height: auto; max-height: 16; margin: 0 1 1 1; }
        DataTable.detail { max-height: 30; }
        #courbes { width: 22; border-right: solid $accent; }
        """
        BINDINGS = [
            ("q,escape", "quit", t("Quit")),
            ("b", "tous", t("Both")),
            ("a", "toutes_les_courbes", t("Every curve")),
            ("d", "detail", t("Per repository")),
        ] + [
            (str(i + 1), f"jeu({i})", nom_du_jeu(d)[:20])
            for i, (_c, d) in enumerate(jeux[:9])
        ]

        def __init__(self):
            super().__init__()
            self.affiches = list(range(min(len(jeux), 1)))
            self.cachees = set()
            self.detail = False

        def compose(self) -> ComposeResult:
            yield Header()
            with Horizontal():
                yield SelectionList(
                    *[
                        Selection(
                            t("unique modules") if nom == UNIQUES else nom,
                            nom,
                            True,
                        )
                        for nom in noms
                    ],
                    id="courbes",
                )
                yield VerticalScroll(id="corps")
            yield Footer()

        def on_selection_list_selected_changed(self, event):
            self.cachees = set(noms) - set(event.selection_list.selected)
            self.redessiner()

        def action_toutes_les_courbes(self):
            self.query_one("#courbes", SelectionList).select_all()

        def on_mount(self):
            self.redessiner()

        def on_resize(self):
            self.redessiner()

        def action_jeu(self, i):
            self.affiches = [i]
            self.redessiner()

        def action_detail(self):
            self.detail = not self.detail
            self.redessiner()

        def action_tous(self):
            self.affiches = list(range(len(jeux)))
            self.redessiner()

        def redessiner(self):
            corps = self.query_one("#corps", VerticalScroll)
            corps.remove_children()
            largeur = max(self.size.width - 22 - 4, 30)
            for i in self.affiches:
                chemin, donnees = jeux[i]
                titre = (
                    f"{nom_du_jeu(donnees)} · {donnees.get('depots', '?')}"
                    f" {t('repositories')} · {donnees.get('genere', '')}"
                )
                corps.mount(Static(titre, classes="titre"))
                corps.mount(
                    Static(
                        graphique(donnees, largeur, 20, self.cachees),
                        classes="graphique",
                    )
                )
                corps.mount(
                    Static(legende(donnees, self.cachees), classes="legende")
                )
                table = DataTable(zebra_stripes=True)
                entetes, rangees = lignes_tableau(donnees)
                corps.mount(table)
                table.add_columns(*entetes)
                table.add_rows(rangees)
                if not self.detail:
                    continue
                date, entetes, rangees = lignes_par_depot(donnees)
                if not rangees:
                    corps.mount(
                        Static(
                            t(
                                "No per-repository detail: run the statistics again."
                            ),
                            classes="legende",
                        )
                    )
                    continue
                corps.mount(
                    Static(
                        f"{t('Per repository')} · {date} · {len(rangees)}"
                        f" {t('repositories')}",
                        classes="titre",
                    )
                )
                table = DataTable(zebra_stripes=True, classes="detail")
                corps.mount(table)
                table.add_columns(*entetes)
                table.add_rows(rangees)

    return EvolutionApp()


def run(dossier, run_app=True):
    """Ouvre l'écran sur les données de `dossier`. Rend le nombre de jeux
    lus — 0 sans rien ouvrir —, ou l'application si `run_app` est faux."""
    jeux = lire_jeux(dossier)
    if not jeux:
        return 0
    app = build_app(jeux)
    if not run_app:
        return app
    app.run()
    return len(jeux)


if __name__ == "__main__":
    from script.statistic.show_evolution_module import CACHE_CLONE_PATH

    if not run(CACHE_CLONE_PATH):
        print(t("No module statistics yet: run entry 3 or 4 first."))
