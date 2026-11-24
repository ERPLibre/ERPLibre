#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran de la couverture de code d'un jeu de mesures (Textual).

    couverture_tui.py [--jeu erplibre|odoo]

À gauche, l'arbre des dossiers et des fichiers mesurés, chacun avec son
pourcentage — instructions et branches réunies, comme coverage le calcule
— coloré selon les seuils `SEUIL_BON` et `SEUIL_MOYEN`. À droite, la
source du fichier sous le curseur, chaque ligne marquée exécutée,
manquante, partielle (une branche jamais prise) ou exclue. En bas,
l'historique : la courbe du total sur les passages COMPLETS, l'écart du
dernier passage avec le précédent comparable, et les derniers passages,
où un passage partiel est grisé et nommé comme tel.

Lecture seule à l'ouverture : l'écran lit coverage.json et
historique.jsonl par `couverture` et ne lance rien. Les mesures se lancent
par une touche, qui rend le terminal à la commande (App.suspend) puis
relit les données.

    j  jeu suivant          s  tri suivant (%, manquantes, nom)
    /  filtrer les chemins  r  passage complet avec couverture
    c  tests modifiés seulement (jeu erplibre)
    h  rapport HTML, ouvert dans le navigateur
    q  quitter

La lecture des fichiers et la production du HTML tournent dans des fils
de travail : l'écran ne gèle pas sur un gros rapport.

Le contenu d'un fichier source est affiché en `rich.text.Text` brut,
jamais en balisage : une source porte des crochets que le balisage
prendrait pour les siens.
"""

import argparse
import os
import shlex
import shutil
import subprocess
import sys

RACINE = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
if RACINE not in sys.path:
    # APPEND : lancé comme script, sys.path[0] est script/test, qui doit
    # garder la priorité sur la racine.
    sys.path.append(RACINE)

from script.test import couverture  # noqa: E402

SEUIL_BON = 80.0
SEUIL_MOYEN = 50.0

# Les tris, dans l'ordre où « s » les parcourt, et leur libellé.
TRIS = (
    ("pourcentage", "%"),
    ("manquantes", "lignes manquantes"),
    ("nom", "nom"),
)

# La commande d'un passage complet, par jeu, relative à la racine.
COMMANDES = {
    "erplibre": ["./script/test/run_unit_test.sh", "--coverage"],
    "odoo": ["./script/test/run_odoo_scenarios.sh", "--coverage"],
}
# Les seuls fichiers de tests touchés depuis HEAD : la suite unitaire seule
# sait les choisir.
COMMANDE_MODIFIES = [
    "./script/test/run_unit_test.sh",
    "--changed",
    "--coverage",
]

PASSAGES_MONTRES = 6


def couleur(pourcentage):
    """Le style rich d'un pourcentage selon les seuils."""
    if pourcentage >= SEUIL_BON:
        return "green"
    if pourcentage >= SEUIL_MOYEN:
        return "yellow"
    return "red"


def _pourcentage(couvertes, total):
    """Même calcul que coverage : 100 % quand il n'y a rien à couvrir."""
    return 100.0 * couvertes / total if total else 100.0


class Noeud:
    """Un dossier ou un fichier de l'arbre. Les sommes d'un dossier sont
    celles des fichiers retenus sous lui, filtre appliqué."""

    def __init__(self, nom, chemin, fichier=False):
        self.nom = nom
        self.chemin = chemin
        self.fichier = fichier
        self.enfants = {}
        self.lignes = 0
        self.couvertes = 0
        self.branches = 0
        self.branches_couvertes = 0
        self.manquantes = 0

    @property
    def pourcentage(self):
        return _pourcentage(
            self.couvertes + self.branches_couvertes,
            self.lignes + self.branches,
        )

    def ajouter(self, resume):
        self.lignes += resume.get("num_statements", 0)
        self.couvertes += resume.get("covered_lines", 0)
        self.branches += resume.get("num_branches", 0)
        self.branches_couvertes += resume.get("covered_branches", 0)
        self.manquantes += resume.get("missing_lines", 0)

    def nombre_de_fichiers(self):
        if self.fichier:
            return 1
        return sum(e.nombre_de_fichiers() for e in self.enfants.values())


def construire(rapport, filtre=""):
    """L'arbre (Noeud racine) des fichiers d'un coverage.json dont le
    chemin contient `filtre`, sans égard à la casse. Un dossier sans
    fichier retenu n'y figure pas."""
    racine = Noeud("", "")
    motif = filtre.strip().lower()
    for chemin, info in (rapport or {}).get("files", {}).items():
        normal = chemin.replace(os.sep, "/")
        if motif and motif not in normal.lower():
            continue
        resume = info.get("summary", {})
        parties = normal.split("/")
        noeud = racine
        noeud.ajouter(resume)
        for i, partie in enumerate(parties[:-1]):
            noeud = noeud.enfants.setdefault(
                partie, Noeud(partie, "/".join(parties[: i + 1]))
            )
            noeud.ajouter(resume)
        feuille = Noeud(parties[-1], chemin, fichier=True)
        feuille.ajouter(resume)
        noeud.enfants[parties[-1]] = feuille
    return racine


def trier(enfants, cle):
    """Les enfants dans l'ordre du tri `cle` : les dossiers d'abord, puis
    les fichiers. « pourcentage » met le moins couvert en tête,
    « manquantes » le plus de lignes manquantes, « nom » l'ordre
    alphabétique ; le nom départage toujours."""
    if cle == "pourcentage":

        def ordre(n):
            return (n.fichier, n.pourcentage, n.nom)

    elif cle == "manquantes":

        def ordre(n):
            return (n.fichier, -n.manquantes, n.nom)

    else:

        def ordre(n):
            return (n.fichier, n.nom)

    return sorted(enfants, key=ordre)


def plages(numeros):
    """[3, 4, 5, 9] -> « 3-5, 9 »."""
    morceaux = []
    debut = fin = None
    for n in sorted(numeros):
        if fin is not None and n == fin + 1:
            fin = n
            continue
        if debut is not None:
            morceaux.append(f"{debut}-{fin}" if fin != debut else f"{debut}")
        debut = fin = n
    if debut is not None:
        morceaux.append(f"{debut}-{fin}" if fin != debut else f"{debut}")
    return ", ".join(morceaux)


def etiquette(noeud):
    """Le libellé d'un nœud de l'arbre : un Text, jamais du balisage, car
    un nom de fichier peut porter des crochets."""
    from rich.text import Text

    texte = Text()
    texte.append(
        f"{noeud.pourcentage:5.1f} % ", style=couleur(noeud.pourcentage)
    )
    texte.append(noeud.nom + ("" if noeud.fichier else "/"))
    if noeud.manquantes:
        texte.append(f"  {noeud.manquantes}", style="dim")
    return texte


# Marque et style de chaque sorte de ligne de la source annotée.
EXECUTEE = ("▌", "green")
MANQUANTE = ("✗", "bold red")
PARTIELLE = ("◐", "yellow")
EXCLUE = ("·", "dim")
NEUTRE = (" ", "dim")


def sorte_des_lignes(info):
    """{numéro: (marque, style)} tiré de l'entrée d'un fichier de
    coverage.json. Une ligne exécutée d'où part une branche jamais prise
    est PARTIELLE."""
    executees = set(info.get("executed_lines", ()))
    manquantes = set(info.get("missing_lines", ()))
    exclues = set(info.get("excluded_lines", ()))
    partielles = {
        de for de, _vers in info.get("missing_branches", ()) if de > 0
    } & executees
    sortes = {}
    for n in exclues:
        sortes[n] = EXCLUE
    for n in executees:
        sortes[n] = EXECUTEE
    for n in partielles:
        sortes[n] = PARTIELLE
    for n in manquantes:
        sortes[n] = MANQUANTE
    return sortes


def annoter(source, info, chemin=""):
    """La source `source` (texte) annotée par l'entrée `info` d'un
    fichier de coverage.json, en Text : un en-tête (chemin, pourcentage,
    lignes manquantes), puis chaque ligne avec son numéro et sa marque."""
    from rich.text import Text

    resume = info.get("summary", {})
    pct = resume.get("percent_covered", 0.0)
    manquantes = info.get("missing_lines", ())
    texte = Text()
    texte.append(chemin, style="bold")
    texte.append(f"  {pct:.1f} %", style=f"bold {couleur(pct)}")
    if manquantes:
        texte.append(
            f"  — {len(manquantes)} ligne(s) manquante(s) : "
            f"{plages(manquantes)}",
            style="red",
        )
    texte.append("\n\n")
    sortes = sorte_des_lignes(info)
    lignes = source.splitlines()
    largeur = len(str(len(lignes)))
    for n, ligne in enumerate(lignes, 1):
        marque, style = sortes.get(n, NEUTRE)
        texte.append(f"{n:>{largeur}} ", style="dim")
        texte.append(f"{marque} ", style=style)
        texte.append(
            ligne.expandtabs(4) + "\n",
            style="red" if style == MANQUANTE[1] else None,
        )
    return texte


def lire_source(chemin):
    """Le texte du fichier `chemin`, relatif à la racine ou absolu, ou
    None s'il n'existe plus."""
    complet = chemin if os.path.isabs(chemin) else os.path.join(RACINE, chemin)
    try:
        with open(complet, encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError:
        return None


def serie(historique):
    """Les pourcentages totaux des passages COMPLETS, dans l'ordre : un
    passage partiel ne mesure qu'une partie du code et fausserait la
    courbe."""
    return [
        ligne["total"]["pourcentage"]
        for ligne in historique
        if ligne.get("complet") and "total" in ligne
    ]


def texte_ecart(dernier, delta):
    """La ligne du dernier passage et de son écart, en Text."""
    from rich.text import Text

    if dernier is None:
        return Text("Aucun passage dans l'historique.", style="dim")
    pct = dernier["total"]["pourcentage"]
    texte = Text("Dernier passage : ")
    texte.append(f"{pct:.2f} %", style=f"bold {couleur(pct)}")
    if not dernier.get("complet"):
        texte.append("  passage partiel, sans écart", style="dim")
    elif delta is None:
        texte.append("  aucun précédent comparable", style="dim")
    else:
        style = "green" if delta > 0 else "red" if delta < 0 else "dim"
        texte.append(f"  {delta:+.2f} pt", style=style)
        texte.append(" depuis le passage complet précédent", style="dim")
    if dernier.get("incomplets"):
        texte.append(
            f"  — {len(dernier['incomplets'])} élément(s) tué(s)",
            style="yellow",
        )
    return texte


def texte_passages(historique, nombre=PASSAGES_MONTRES):
    """Les `nombre` derniers passages, du plus récent au plus ancien ; un
    passage partiel est grisé et marqué."""
    from rich.text import Text

    texte = Text()
    for ligne in reversed(historique[-nombre:]):
        complet = ligne.get("complet")
        style = None if complet else "dim"
        texte.append(
            f"{ligne.get('date', '?')[:16]:16}  "
            f"{ligne.get('commit', '')[:10]:10}  "
            f"{ligne['total']['pourcentage']:6.2f} %  ",
            style=style,
        )
        texte.append("complet" if complet else "partiel", style=style)
        if ligne.get("incomplets"):
            texte.append(
                f", {len(ligne['incomplets'])} tué(s)", style="yellow"
            )
        texte.append("\n")
    return texte


def ouvrir(chemin):
    """Ouvre `chemin` dans l'application par défaut du bureau, détachée
    dans sa propre session : elle survit à l'écran et ne reçoit pas son
    Ctrl+C. Rend faux sans programme d'ouverture."""
    programme = "open" if sys.platform == "darwin" else "xdg-open"
    if shutil.which(programme) is None:
        return False
    subprocess.Popen(
        [programme, chemin],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return True


def _jusqu_au_bout(cmd):
    """Lance `cmd` depuis la racine et rend son code, sans que Ctrl+C
    n'interrompe l'attente : le lanceur de tests le reçoit aussi, arrête
    ses groupes et démonte ce qu'il a créé. subprocess.run le tuerait par
    SIGKILL au milieu."""
    processus = subprocess.Popen(cmd, cwd=RACINE)
    while True:
        try:
            return processus.wait()
        except KeyboardInterrupt:
            continue


def _attendre_entree():
    """Laisse lire le bilan d'un passage avant que l'écran ne revienne."""
    try:
        input("\nEntrée pour revenir à l'écran de couverture… ")
    except (EOFError, KeyboardInterrupt):
        # Ctrl+C revient aussi à l'écran : après un passage interrompu,
        # c'est la touche qu'on a encore sous le doigt.
        print()


def build_app(jeu="erplibre"):
    """L'application Textual sur le jeu `jeu`."""
    from rich.text import Text
    from textual.app import App, SuspendNotSupported
    from textual.binding import Binding
    from textual.containers import Horizontal, Vertical, VerticalScroll
    from textual.widgets import (
        Footer,
        Header,
        Input,
        Sparkline,
        Static,
        Tree,
    )

    class CouvertureApp(App):
        TITLE = "Couverture de code"
        # Les touches vont à l'arbre ; « / » mène au filtre.
        AUTO_FOCUS = "#arbre"
        CSS = """
        #corps { height: 1fr; }
        #gauche { width: 2fr; border-right: solid $accent; }
        #source { width: 3fr; padding: 0 1; }
        #vide { height: 1fr; content-align: center middle; }
        #historique { height: 10; border-top: solid $accent; padding: 0 1; }
        #courbe { height: 2; margin: 0 0 1 0; }
        """
        BINDINGS = [
            Binding("q", "quit", "Quitter"),
            Binding("j", "jeu_suivant", "Jeu"),
            Binding("s", "tri_suivant", "Tri"),
            Binding("slash", "filtrer", "Filtrer"),
            Binding("r", "lancer", "Passage complet"),
            Binding("c", "lancer_modifies", "Tests modifiés"),
            Binding("h", "html", "HTML"),
            Binding("escape", "quitter_filtre", show=False),
        ]

        def __init__(self):
            super().__init__()
            self.jeu = jeu
            self.tri = TRIS[0][0]
            self.filtre = ""
            self.rapport = None
            self.historique = []
            self.dernier = None
            self.delta = None
            self.fichier_montre = None

        def compose(self):
            yield Header()
            with Horizontal(id="corps"):
                with Vertical(id="gauche"):
                    yield Input(
                        placeholder="filtrer les chemins ( / )", id="filtre"
                    )
                    yield Tree(Text(""), id="arbre")
                with VerticalScroll(id="source"):
                    yield Static(Text(""), id="code")
            yield Static(Text(""), id="vide")
            with Vertical(id="historique"):
                yield Static(Text(""), id="ecart")
                yield Sparkline([], id="courbe")
                yield Static(Text(""), id="passages")
            yield Footer()

        def on_mount(self):
            self.query_one("#vide").display = False
            self.charger()

        # Lecture des données, hors du fil de l'écran.

        def charger(self):
            self.sub_title = f"{self.jeu} — lecture…"
            self.run_worker(
                self._lire, thread=True, exclusive=True, group="charge"
            )

        def _lire(self):
            nom = self.jeu
            rapport = couverture.lire_json(nom)
            historique = couverture.lire_historique(nom)
            dernier, delta = couverture.ecart(nom)
            self.call_from_thread(
                self._afficher, nom, rapport, historique, dernier, delta
            )

        def _afficher(self, nom, rapport, historique, dernier, delta):
            if nom != self.jeu:
                # Un changement de jeu pendant la lecture : la lecture
                # suivante apporte les bonnes données.
                return
            self.rapport = rapport
            self.historique = historique
            self.dernier = dernier
            self.delta = delta
            vide = rapport is None
            self.query_one("#corps").display = not vide
            self.query_one("#vide").display = vide
            if vide:
                self.query_one("#vide", Static).update(
                    Text(
                        f"Jeu {nom} : aucune mesure : r pour lancer",
                        style="bold",
                    )
                )
            else:
                self.remplir_arbre()
                # Le fichier ouvert se relit avec le nouveau rapport : ses
                # marques datent sinon du passage précédent.
                montre = self.fichier_montre
                if montre and montre in rapport.get("files", {}):
                    self.montrer(montre)
                elif montre:
                    self.fichier_montre = None
                    self.query_one("#code", Static).update(Text(""))
            self.query_one("#ecart", Static).update(
                texte_ecart(dernier, delta)
            )
            self.query_one("#courbe", Sparkline).data = serie(historique)
            self.query_one("#passages", Static).update(
                texte_passages(historique)
            )
            self._titrer()

        def _titrer(self):
            libelle = dict(TRIS)[self.tri]
            morceaux = [self.jeu, f"tri : {libelle}"]
            if self.filtre:
                morceaux.append(f"filtre : {self.filtre}")
            self.sub_title = " — ".join(morceaux)

        # L'arbre.

        def remplir_arbre(self):
            arbre = self.query_one("#arbre", Tree)
            racine = construire(self.rapport, self.filtre)
            arbre.clear()
            total = (self.rapport or {}).get("totals", {})
            pct = total.get("percent_covered", racine.pourcentage)
            libelle = Text(f"{self.jeu}  ", style="bold")
            libelle.append(f"{pct:.1f} %", style=f"bold {couleur(pct)}")
            libelle.append(
                f"  {racine.nombre_de_fichiers()} fichier(s)", style="dim"
            )
            arbre.root.set_label(libelle)
            tout_ouvrir = bool(self.filtre)
            self._ajouter(arbre.root, racine, tout_ouvrir, profondeur=0)
            arbre.root.expand()

        def _ajouter(self, parent, noeud, tout_ouvrir, profondeur):
            for enfant in trier(noeud.enfants.values(), self.tri):
                if enfant.fichier:
                    parent.add_leaf(etiquette(enfant), data=enfant.chemin)
                    continue
                branche = parent.add(
                    etiquette(enfant),
                    data=None,
                    expand=tout_ouvrir or profondeur <= 1,
                )
                self._ajouter(branche, enfant, tout_ouvrir, profondeur + 1)

        def on_tree_node_highlighted(self, event):
            chemin = event.node.data
            if chemin:
                self.montrer(chemin)

        def montrer(self, chemin):
            """La source annotée de `chemin` dans le panneau de droite."""
            info = (self.rapport or {}).get("files", {}).get(chemin)
            if info is None:
                return
            self.fichier_montre = chemin
            source = lire_source(chemin)
            code = self.query_one("#code", Static)
            if source is None:
                code.update(
                    Text(f"{chemin} : fichier introuvable", style="yellow")
                )
            else:
                code.update(annoter(source, info, chemin))
            self.query_one("#source").scroll_home(animate=False)

        # Le filtre.

        def action_filtrer(self):
            self.query_one("#filtre", Input).focus()

        def action_quitter_filtre(self):
            self.query_one("#arbre", Tree).focus()

        def on_input_changed(self, event):
            self.filtre = event.value
            if self.rapport is not None:
                self.remplir_arbre()
            self._titrer()

        def on_input_submitted(self, event):
            self.query_one("#arbre", Tree).focus()

        # Le tri et le jeu.

        def action_tri_suivant(self):
            cles = [cle for cle, _ in TRIS]
            self.tri = cles[(cles.index(self.tri) + 1) % len(cles)]
            if self.rapport is not None:
                self.remplir_arbre()
            self._titrer()

        def action_jeu_suivant(self):
            jeux = list(couverture.JEUX)
            self.jeu = jeux[(jeux.index(self.jeu) + 1) % len(jeux)]
            self.fichier_montre = None
            self.query_one("#code", Static).update(Text(""))
            self.charger()

        # Les passages.

        def action_lancer(self):
            self.executer(list(COMMANDES[self.jeu]))

        def action_lancer_modifies(self):
            if self.jeu != "erplibre":
                self.notify(
                    "Les tests modifiés ne se choisissent que pour le jeu"
                    " erplibre.",
                    severity="warning",
                )
                return
            self.executer(list(COMMANDE_MODIFIES))

        def executer(self, cmd):
            """Rend le terminal à `cmd`, lancée depuis la racine, puis
            relit les données. Rend son code de retour, ou None si elle
            n'a pas pu partir."""
            if not os.path.exists(os.path.join(RACINE, cmd[0])):
                self.notify(f"{cmd[0]} introuvable", severity="error")
                return None
            try:
                with self.suspend():
                    print(f"$ {shlex.join(cmd)}", flush=True)
                    rc = _jusqu_au_bout(cmd)
                    _attendre_entree()
            except OSError as err:
                self.notify(f"{cmd[0]} : {err}", severity="error")
                return None
            except SuspendNotSupported:
                self.notify(
                    "Ce terminal ne peut pas être rendu à la commande :"
                    f" lancer {shlex.join(cmd)} à la main.",
                    severity="error",
                )
                return None
            self.notify(
                f"Passage terminé, code {rc}",
                severity="information" if rc == 0 else "warning",
            )
            self.charger()
            return rc

        # Le rapport HTML.

        def action_html(self):
            if self.rapport is None:
                self.notify("Aucune mesure : r pour lancer", severity="error")
                return
            self.notify("Production du rapport HTML…")
            self.run_worker(
                self._html, thread=True, exclusive=True, group="html"
            )

        def _html(self):
            try:
                chemin = couverture.produire_html(self.jeu)
            except (RuntimeError, OSError) as err:
                self.call_from_thread(self.notify, str(err), severity="error")
                return
            if ouvrir(chemin):
                self.call_from_thread(self.notify, chemin)
            else:
                self.call_from_thread(
                    self.notify, f"Rapport écrit : {chemin}", timeout=30
                )

    return CouvertureApp()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--jeu", default="erplibre", choices=couverture.JEUX)
    args = parser.parse_args(argv)
    from script.todo import textual_setup

    if not textual_setup.ensure():
        return 1
    build_app(args.jeu).run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
