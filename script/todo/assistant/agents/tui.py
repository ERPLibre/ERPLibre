#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran vivant de la télémétrie des agents.

Trois choses gouvernent cet écran, et les trois sont des contraintes mesurées
plutôt que des choix de goût.

**Il se rafraîchit sans relire.** Une transcription pèse des dizaines de
mégaoctets, et la dernière ligne de coût peut être à quatre mégaoctets de la
fin — aucune lecture de queue ne suffit. L'écran garde donc une `Lecture` par
session, avec l'offset où elle s'est arrêtée, et un tour de rafraîchissement
ne replie que les octets ajoutés depuis. Sur une transcription de dix
mégaoctets, la première lecture prend un dixième de seconde et les suivantes
rien du tout.

**Chaque chiffre dit sa source.** Les jetons sont des SOMMES exactes de ce que
chaque message a rapporté. Le coût et les durées sont LUS dans le dernier
`cost-state`, qu'une compaction remet à zéro — l'écran affiche donc le nombre
de segments à côté, sans quoi un coût qui vient de retomber ferait accuser le
mauvais composant. Un tableau qui mélange une mesure et une approximation sans
le dire est pire qu'un tableau vide.

**Le gel est une fonction, pas un confort.** L'écran bouge toutes les deux
secondes, et une ligne qu'on veut lire se dérobe. « f » l'arrête ; le
rafraîchissement continue en dessous et reprend l'affichage au dégel.
"""
from __future__ import annotations

import glob
import os

from script.todo.assistant.agents import journal as jr
from script.todo.assistant.agents import statistiques as st
from script.todo.todo_i18n import t

# Où Claude Code écrit ses transcriptions, un répertoire par projet.
TRANSCRIPTIONS = "~/.claude/projects/*/*.jsonl"

# Le pas de rafraîchissement. Deux secondes est ce que la télémétrie de
# navigation emploie déjà, et un appel d'outil qui dure se voit dedans.
PAS = 2.0

# La barre de contexte, en caractères. Assez pour lire une pente, assez peu
# pour tenir dans une colonne à côté des chiffres.
BARRE = 24


def transcriptions(*, motif=None, lister=None) -> list[str]:
    """Les transcriptions présentes, la plus grosse d'abord.

    La taille est un bon ordre par défaut : la session la plus lourde est
    celle qui a le plus consommé, donc celle qu'on vient regarder. Trier par
    date mettrait en tête une session ouverte il y a deux minutes et vide.
    """
    lister = lister or glob.glob
    chemins = lister(os.path.expanduser(motif or TRANSCRIPTIONS))
    return sorted(chemins, key=_taille, reverse=True)


def _taille(chemin) -> int:
    try:
        return os.path.getsize(chemin)
    except OSError:
        return 0


def identifiant(chemin) -> str:
    """Les huit premiers caractères de l'identifiant, comme le fait la liste."""
    return os.path.basename(chemin).split(".")[0][:8]


def projet(chemin, agregat=None) -> str:
    """Le nom de base du répertoire de travail de la session.

    Lu dans la transcription quand elle le porte. Le nom de RÉPERTOIRE de
    projet ne sert que de repli, et un mauvais repli : il encode le chemin en
    remplaçant les séparateurs par des tirets, et le point comme le tiret bas
    y deviennent aussi des tirets, donc la transformation ne s'inverse pas —
    « erplibre_new_feature_01 » y devient « 01 ».
    """
    lu = getattr(agregat, "cwd", "")
    if lu:
        return os.path.basename(lu.rstrip("/"))
    return os.path.basename(os.path.dirname(chemin)).split("-")[-1]


def duree(millisecondes) -> str:
    """« 2 h 05 », « 12 min », « 8 s », « 40 ms » — l'unité qui parle.

    Le palier des millisecondes n'est pas un raffinement : une durée d'outil
    se compte en dizaines de millisecondes, et l'arrondi à la seconde
    affichait « 0 s » sur une édition de quarante millisecondes — le même
    mensonge qu'un zéro mis à la place d'une absence.
    """
    ms = max(0, int(millisecondes or 0))
    if ms < 1000:
        return f"{ms} ms"
    secondes = ms // 1000
    if secondes >= 3600:
        return f"{secondes // 3600} h {(secondes % 3600) // 60:02d}"
    if secondes >= 60:
        return f"{secondes // 60} min"
    return f"{secondes} s"


def jetons(nombre) -> str:
    """« 2,40 G », « 1,9 M », « 84 k », « 512 » — trois chiffres suffisent."""
    nombre = int(nombre or 0)
    if nombre >= 1_000_000_000:
        return f"{nombre / 1_000_000_000:.2f} G"
    if nombre >= 1_000_000:
        return f"{nombre / 1_000_000:.1f} M"
    if nombre >= 1_000:
        return f"{nombre / 1_000:.0f} k"
    return str(nombre)


def barre(serie, largeur=BARRE) -> str:
    """La pente du contexte, en blocs. Vide quand rien n'a été mesuré.

    Échelonnée sur la POINTE de la série et non sur la fenêtre du modèle : la
    fenêtre n'est pas sur le disque, et une barre échelonnée sur une valeur
    supposée mentirait sur la marge restante. Ce que la barre montre est donc
    la forme de la croissance, et le décrochement qu'une compaction y laisse.
    """
    if not serie:
        return ""
    pointe = max(serie) or 1
    blocs = "▁▂▃▄▅▆▇█"
    pas = max(1, len(serie) // largeur)
    echantillon = serie[::pas][-largeur:]
    # L'échelle porte la pointe sur le DERNIER bloc : diviser par « pointe + 1
    # » pour éviter la division par zéro décalait tout d'un cran, et le maximum
    # d'une série croissante ne se dessinait jamais plein.
    return "".join(
        blocs[min(len(blocs) - 1, int(v * (len(blocs) - 1) / pointe))]
        for v in echantillon
    )


def lignes(lectures) -> list[dict]:
    """Une ligne de tableau par session, prête à afficher. Fonction PURE.

    Prend `{chemin: Lecture}` et rend des dictionnaires de chaînes. Séparer le
    calcul de l'affichage est ce qui permet de vérifier les colonnes sans
    ouvrir un terminal, et la TUI n'a plus qu'à poser les valeurs.
    """
    sorties = []
    for chemin, lecture in lectures.items():
        a = lecture.agregat
        reutilisation = a.reutilisation
        sorties.append(
            {
                "id": identifiant(chemin),
                "projet": projet(chemin, a),
                "tours": str(a.tours),
                "entree": jetons(a.entree + a.cache_lu + a.cache_cree),
                "sortie": jetons(a.sortie),
                "reflexion": jetons(a.reflexion),
                "cache": (
                    "—" if reutilisation is None else f"{reutilisation:.0%}"
                ),
                "cout": f"{a.cout:.2f} $" if a.cout else "—",
                "horloge": duree(a.duree_horloge),
                "api": duree(a.duree_api),
                "outils": duree(a.duree_outils),
                "contexte": jetons(a.contexte),
                "pente": barre(a.serie),
                "segments": str(a.segments),
                "compactions": str(a.compactions),
                "code": f"+{a.lignes_ajoutees}/−{a.lignes_retirees}",
            }
        )
    return sorties


def lignes_outils(par_outil) -> list[dict]:
    """Une ligne par outil, prête à afficher. Fonction PURE.

    Ce panneau est le SEUL que le disque ne donne pas : une transcription
    porte la durée totale des outils, jamais celle de chacun. Sans hook posé,
    il est vide, et l'écran le dit au lieu d'afficher un tableau nu.
    """
    return [
        {
            "outil": p.outil or "—",
            "appels": str(p.appels),
            "mediane": duree(p.mediane_ms),
            "pointe": duree(p.pointe_ms),
            "inacheves": str(p.inacheves) if p.inacheves else "",
        }
        for p in par_outil
    ]


# Les colonnes du tableau des outils, alimentées par le journal des hooks.
COLONNES_OUTILS = (
    ("outil", "tool"),
    ("appels", "calls"),
    ("mediane", "median"),
    ("pointe", "peak"),
    ("inacheves", "unfinished"),
)

# Les colonnes du tableau : la clé dans la ligne, et sa clé i18n.
COLONNES = (
    ("id", "session"),
    ("projet", "project"),
    ("tours", "turns"),
    ("entree", "prompt"),
    ("sortie", "output"),
    ("cache", "cache"),
    ("contexte", "context"),
    ("pente", "growth"),
    ("cout", "cost"),
    ("api", "API"),
    ("outils", "tools"),
)


def run_tui(run_app: bool = True):
    """L'écran. `run_app=False` rend l'application sans la lancer, pour test.

    Textual est importé ICI et non en tête : le module est lu par le menu à
    chaque affichage, et Textual coûte près d'une seconde à l'import. Le CLI
    ne doit pas le payer pour un écran qu'on n'ouvre pas.
    """
    from textual.app import App, ComposeResult
    from textual.widgets import DataTable, Footer, Header, Static

    class Telemetrie(App):
        CSS = """
        #resume { height: auto; padding: 0 1; color: $text-muted; }
        #source { height: auto; padding: 0 1; color: $text-muted; }
        DataTable { height: 1fr; }
        """
        BINDINGS = [
            ("q", "quit", t("Quit")),
            ("f", "gel", t("Freeze")),
            ("r", "relire", t("Read again")),
        ]

        def __init__(self):
            super().__init__()
            self._lectures: dict[str, st.Lecture] = {}
            self._appels: list = []
            self._gele = False

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("", id="resume")
            yield DataTable(id="tableau", zebra_stripes=True)
            yield Static("", id="titre_outils")
            yield DataTable(id="outils", zebra_stripes=True)
            yield Static("", id="source")
            yield Footer()

        def on_mount(self):
            self.title = t("Agent telemetry")
            tableau = self.query_one("#tableau", DataTable)
            for _, cle in COLONNES:
                tableau.add_column(t(cle), key=cle)
            outils = self.query_one("#outils", DataTable)
            for _, cle in COLONNES_OUTILS:
                outils.add_column(t(cle), key=cle)
            # Les journaux périmés partent à l'ouverture : c'est le seul
            # moment où quelqu'un regarde, donc le seul où le ménage ne
            # surprend personne.
            jr.nettoyer()
            self._tick()
            self.set_interval(PAS, self._tick)

        def action_gel(self):
            """Le rafraîchissement continue dessous ; l'affichage s'arrête."""
            self._gele = not self._gele
            self._resumer()

        def action_relire(self):
            """Tout relire depuis le début, quand un doute vient sur un total."""
            self._lectures = {}
            self._tick()

        def _tick(self):
            for chemin in transcriptions():
                self._lectures[chemin] = st.lire(
                    chemin, self._lectures.get(chemin)
                )
            # Le journal est relu en entier : il ne pèse que quelques lignes
            # par appel d'outil, là où une transcription pèse des mégaoctets.
            self._appels = jr.lire()
            if not self._gele:
                self._peindre()

        def _peindre(self):
            tableau = self.query_one("#tableau", DataTable)
            tableau.clear()
            for ligne in lignes(self._lectures):
                tableau.add_row(*[ligne[cle] for cle, _ in COLONNES])
            outils = self.query_one("#outils", DataTable)
            outils.clear()
            groupes = jr.par_outil(self._appels)
            for ligne in lignes_outils(groupes):
                outils.add_row(*[ligne[cle] for cle, _ in COLONNES_OUTILS])
            self.query_one("#titre_outils", Static).update(
                t("Per tool")
                if groupes
                else t("No hook installed: the per-tool figures need one.")
            )
            self._resumer()

        def _resumer(self):
            total = st.somme(l.agregat for l in self._lectures.values())
            compte = len(self._lectures)
            self.query_one("#resume", Static).update(
                f"{compte} {t('sessions')} · "
                f"{t('prompt')} {jetons(total.entree + total.cache_lu + total.cache_cree)}"
                f" · {t('output')} {jetons(total.sortie)}"
                f" · {t('thinking')} {jetons(total.reflexion)}"
                f" · {t('cost')} {total.cout:.2f} $"
                f" · {t('tools')} {duree(total.duree_outils)}"
                + (f"  [{t('frozen')}]" if self._gele else "")
            )
            self.query_one("#source", Static).update(
                t(
                    "Tokens are summed from each message. Cost and durations"
                    " are read from the last cost-state, which a compaction"
                    " resets."
                )
            )

    app = Telemetrie()
    if not run_app:
        return app
    app.run()
    return None
