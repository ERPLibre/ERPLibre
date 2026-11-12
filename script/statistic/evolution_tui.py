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
graphique donne les nombres exacts que le tracé arrondit.

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


def graphique(donnees, largeur, hauteur):
    """Le graphique de `donnees` en rich.text.Text : axe des y gradué à
    gauche, années sous l'axe des x, une couleur par courbe."""
    from rich.text import Text

    etiquettes, courbes = series(donnees)
    styles = couleurs(courbes)
    marge = 7
    zone = max(largeur - marge, 10)
    lignes, ymax = tracer(courbes, zone, max(hauteur - 2, 4))
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


def legende(donnees):
    """Les courbes et leur couleur, sur une ligne."""
    from rich.text import Text

    _, courbes = series(donnees)
    styles = couleurs(courbes)
    texte = Text()
    for nom in courbes:
        libelle = t("unique modules") if nom == UNIQUES else nom
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


def build_app(jeux):
    """L'application Textual sur `jeux` (rendu de lire_jeux, non vide).
    Une touche par jeu, et « b » pour les montrer tous l'un sous l'autre."""
    from textual.app import App, ComposeResult
    from textual.containers import VerticalScroll
    from textual.widgets import DataTable, Footer, Header, Static

    class EvolutionApp(App):
        TITLE = t("Odoo module evolution per year")
        CSS = """
        .titre { padding: 1 1 0 1; text-style: bold; }
        .graphique { height: 22; padding: 0 1; }
        .legende { padding: 0 1; }
        DataTable { height: auto; max-height: 16; margin: 0 1 1 1; }
        """
        BINDINGS = [
            ("q,escape", "quit", t("Quit")),
            ("b", "tous", t("Both")),
        ] + [
            (str(i + 1), f"jeu({i})", nom_du_jeu(d)[:20])
            for i, (_c, d) in enumerate(jeux[:9])
        ]

        def __init__(self):
            super().__init__()
            self.affiches = list(range(min(len(jeux), 1)))

        def compose(self) -> ComposeResult:
            yield Header()
            yield VerticalScroll(id="corps")
            yield Footer()

        def on_mount(self):
            self.redessiner()

        def on_resize(self):
            self.redessiner()

        def action_jeu(self, i):
            self.affiches = [i]
            self.redessiner()

        def action_tous(self):
            self.affiches = list(range(len(jeux)))
            self.redessiner()

        def redessiner(self):
            corps = self.query_one("#corps", VerticalScroll)
            corps.remove_children()
            largeur = max(self.size.width - 4, 30)
            for i in self.affiches:
                chemin, donnees = jeux[i]
                titre = (
                    f"{nom_du_jeu(donnees)} · {donnees.get('depots', '?')}"
                    f" {t('repositories')} · {donnees.get('genere', '')}"
                )
                corps.mount(Static(titre, classes="titre"))
                corps.mount(
                    Static(
                        graphique(donnees, largeur, 20), classes="graphique"
                    )
                )
                corps.mount(Static(legende(donnees), classes="legende"))
                table = DataTable(zebra_stripes=True)
                entetes, rangees = lignes_tableau(donnees)
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
