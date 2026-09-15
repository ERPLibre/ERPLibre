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
import time

from script.todo.assistant.agents import journal as jr
from script.todo.assistant.agents import statistiques as st
from script.todo.assistant.harness import opencode as oc
from script.todo.todo_i18n import t

# Où Claude Code écrit ses transcriptions, un répertoire par projet.
TRANSCRIPTIONS = "~/.claude/projects/*/*.jsonl"

# Le pas de rafraîchissement. Deux secondes est ce que la télémétrie de
# navigation emploie déjà, et un appel d'outil qui dure se voit dedans.
PAS = 2.0

# Combien d'appels le flux garde à l'écran. Au-delà, on ne lit plus : le
# panneau répond à « qu'est-ce qui vient de se passer », pas à « tout ».
FLUX_MAX = 60

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


def session_de(chemin) -> str:
    """L'identifiant ENTIER d'une session, tiré du nom de sa transcription.

    Distinct d'`identifiant`, qui l'abrège pour l'écran : le journal des hooks
    nomme les sessions en entier, et rapprocher les deux sur huit caractères
    marierait un jour deux sessions qui n'ont rien à voir.
    """
    return os.path.basename(chemin).split(".")[0]


def lignes(lectures, temps=None) -> list[dict]:
    """Une ligne de tableau par session, prête à afficher. Fonction PURE.

    Prend `{chemin: Lecture}` et rend des dictionnaires de chaînes. Séparer le
    calcul de l'affichage est ce qui permet de vérifier les colonnes sans
    ouvrir un terminal, et la TUI n'a plus qu'à poser les valeurs.

    `temps` est `{session: millisecondes}`, le temps d'ATTENTION lu dans le
    journal des hooks. Il vaut None quand les hooks ne sont pas posés, et la
    colonne rend alors un tiret : zéro dirait « cette session n'a pas
    travaillé », ce qui est le contraire de « on ne mesure pas ».
    """
    sorties = []
    for chemin, lecture in lectures.items():
        a = lecture.agregat
        reutilisation = a.reutilisation
        attention = (temps or {}).get(session_de(chemin))
        sorties.append(
            {
                "id": f"{ICONES['claude']} {identifiant(chemin)}",
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
                "attention": "—" if attention is None else duree(attention),
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


def lignes_opencode(seances) -> list[dict]:
    """Une ligne par séance d'Open Code, dans la MÊME forme que les autres.

    Le tableau réunit deux harnais qui ne mesurent pas les mêmes choses. Les
    champs qu'Open Code ne porte pas — les tours, le contexte, sa pente, les
    durées d'API et d'outils — rendent un tiret et JAMAIS un zéro : une
    colonne à zéro se lit « mesuré, et nul », ce qui est faux et décourage de
    chercher ailleurs ce que l'autre harnais, lui, donne.

    `seances` peut valoir None, qui veut dire « la base n'a pas répondu » :
    aucune ligne n'est alors ajoutée, et le tableau ne ment pas sur l'absence.
    """
    sorties = []
    for seance in seances or ():
        resume = seance.resume
        if resume is None:
            continue
        sorties.append(
            {
                "id": (
                    f"{ICONES['opencode']} "
                    f"{seance.identifiant.removeprefix('ses_')[:8]}"
                ),
                "projet": os.path.basename(seance.repertoire.rstrip("/")),
                "tours": "—",
                "entree": jetons(resume.entree + resume.cache_lu),
                "sortie": jetons(resume.sortie),
                "reflexion": jetons(resume.raisonnement),
                "cache": "—",
                "cout": f"{resume.cout:.2f} $" if resume.cout else "—",
                "horloge": "—",
                "attention": "—",
                "api": "—",
                "outils": "—",
                "contexte": "—",
                "pente": "",
                "segments": "—",
                "compactions": "—",
                "code": f"+{resume.lignes_ajoutees}/−{resume.lignes_retirees}",
            }
        )
    return sorties


def resume_opencode(seances) -> str:
    """« · 🧊 3 · coût 1.20 $ · 84 k » — ou "" quand il n'y a rien à dire.

    Un segment SÉPARÉ, et non un total fondu dans celui de l'autre harnais.
    Le coût de Claude Code est lu dans un `cost-state` qu'une compaction remet
    à zéro ; celui d'Open Code est un champ de base, stable. Les additionner
    donnerait un chiffre dont personne ne saurait dire ce qu'il vaut, alors
    que deux segments côte à côte se rapprochent du tableau sans arithmétique.
    """
    resumes = [s.resume for s in seances or () if s.resume is not None]
    if not resumes:
        return ""
    cout = sum(r.cout for r in resumes)
    total = sum(r.jetons for r in resumes)
    return (
        f" · {ICONES['opencode']} {len(resumes)}"
        f" · {t('cost')} {cout:.2f} $"
        f" · {jetons(total)}"
    )


def heure(millisecondes) -> str:
    """« 14:32:07 » — l'heure locale d'un instant du journal.

    En heure LOCALE, contrairement au jour d'une transcription : on lit cette
    colonne pour se rappeler ce qu'on faisait à ce moment-là, et c'est la
    pendule du mur qui répond à cette question-là.
    """
    if not millisecondes:
        return ""
    return time.strftime("%H:%M:%S", time.localtime(millisecondes / 1000))


# Comment une fin s'écrit à l'écran. La clé EST la chaîne anglaise, comme
# partout dans le paquet ; la colonne reste VIDE pour un appel fini, qui est
# le cas ordinaire et n'a rien à signaler.
#
# Des clés DISTINCTES de celles du tableau par outil, bien que l'anglais les
# confonde : là-bas ce sont des comptes et le français les accorde au pluriel
# — « échoués » —, ici c'est UN appel et la même clé donnerait « inachevés »
# sur une ligne qui en décrit un seul.
ISSUES = {
    jr.FINI: "",
    jr.ECHOUE: "failure",
    jr.INTERROMPU: "interruption",
    jr.INACHEVE: "no ending",
}


def lignes_flux(appels, limite=FLUX_MAX) -> list[dict]:
    """Les derniers appels d'outil, du plus RÉCENT au plus ancien.

    Le panneau des outils dit ce qu'un outil coûte en moyenne ; celui-ci dit
    ce qui vient de se passer, et les deux répondent à des questions
    différentes — « lequel est lent » contre « pourquoi ça bloque depuis deux
    minutes ». Aucun contenu n'y paraît : un nom d'outil, une durée, une fin.

    L'ordre est inversé parce qu'un flux se lit par le haut : mettre le plus
    ancien en tête obligerait à faire défiler pour voir ce qui arrive.
    """
    derniers = sorted(appels, key=lambda a: a.debut_ms)[-limite:]
    return [
        {
            "heure": heure(a.debut_ms),
            "session": (a.session or "")[:8],
            "outil": a.outil or "—",
            "duree": "—" if a.duree_ms is None else duree(a.duree_ms),
            "issue": t(ISSUES.get(a.issue, "")) if ISSUES.get(a.issue) else "",
        }
        for a in reversed(derniers)
    ]


# Les colonnes du flux. La session y est abrégée : le flux réunit toutes les
# sessions de la machine, et sans elle deux terminaux se lisent comme un seul.
COLONNES_FLUX = (
    ("heure", "time"),
    ("session", "session"),
    ("outil", "tool"),
    ("duree", "duration"),
    ("issue", "outcome"),
)


def lignes_outils(par_outil) -> list[dict]:
    """Une ligne par outil, prête à afficher. Fonction PURE.

    Ce panneau est le SEUL que le disque ne donne pas : une transcription
    porte la durée totale des outils, jamais celle de chacun. Sans hook posé,
    il est vide, et l'écran le dit au lieu d'afficher un tableau nu.

    Les trois façons de mal finir ont chacune leur colonne, et une colonne
    reste VIDE plutôt que d'afficher zéro : un tableau semé de zéros se lit
    mal, et ce qui compte ici est qu'une valeur y paraisse.
    """
    return [
        {
            "outil": p.outil or "—",
            "appels": str(p.appels),
            "mediane": duree(p.mediane_ms),
            "pointe": duree(p.pointe_ms),
            "echoues": str(p.echoues) if p.echoues else "",
            "interrompus": str(p.interrompus) if p.interrompus else "",
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
    ("echoues", "failed"),
    ("interrompus", "interrupted"),
    ("inacheves", "unfinished"),
)

# Les colonnes du tableau : la clé dans la ligne, et sa clé i18n.
# L'icône qui dit de QUEL harnais vient la ligne. Le tableau en réunit deux
# qui ne mesurent pas les mêmes choses, et deux identifiants de huit
# caractères ne se distinguent pas d'un coup d'œil. Elles viennent du registre
# des harnais, pour qu'un seul endroit les décide.
ICONES = {"claude": "🤖", "opencode": "🧊"}

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
    ("attention", "attention"),
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
            ("v", "vue", t("Switch the panel")),
        ]

        # Le panneau du bas PERMUTE au lieu de s'empiler : un terminal n'a pas
        # la hauteur pour trois tableaux, et empiler les réduirait tous à
        # quatre lignes. Les deux répondent à des questions différentes :
        # « quel outil est lent » contre « qu'est-ce qui vient de se passer ».
        VUES = ("outils", "flux")

        def __init__(self):
            super().__init__()
            self._lectures: dict[str, st.Lecture] = {}
            self._appels: list = []
            # None et non [] : « la base d'Open Code n'a pas répondu », ce qui
            # n'est pas « elle ne porte aucune séance ».
            self._seances: list | None = None
            # None et non {} : « les hooks ne sont pas posés », ce qui n'est
            # pas « aucune session n'a travaillé ».
            self._temps: dict | None = None
            self._gele = False
            self._vue = 0

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("", id="resume")
            yield DataTable(id="tableau", zebra_stripes=True)
            yield Static("", id="titre_outils")
            yield DataTable(id="outils", zebra_stripes=True)
            yield DataTable(id="flux", zebra_stripes=True)
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
            flux = self.query_one("#flux", DataTable)
            for _, cle in COLONNES_FLUX:
                flux.add_column(t(cle), key=cle)
            self._montrer_la_vue()
            # Les journaux périmés partent à l'ouverture : c'est le seul
            # moment où quelqu'un regarde, donc le seul où le ménage ne
            # surprend personne.
            jr.nettoyer()
            self._tick()
            self.set_interval(PAS, self._tick)

        def action_vue(self):
            """Passer au panneau suivant, en boucle."""
            self._vue = (self._vue + 1) % len(self.VUES)
            self._montrer_la_vue()
            self._peindre()

        def _montrer_la_vue(self):
            """N'afficher que le panneau courant, et rien d'autre."""
            for nom in self.VUES:
                self.query_one(f"#{nom}", DataTable).display = (
                    nom == self.VUES[self._vue]
                )

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
            evenements = jr.lire_lignes()
            self._appels = jr.apparier(evenements)
            # Le temps d'ATTENTION vient du journal, pas de l'horloge de
            # session : celle-ci compte aussi les heures où personne ne
            # regardait. Sans hooks posés, il n'y a rien et la colonne le dit.
            self._temps = jr.temps_actif(evenements) or None
            # La base d'Open Code se lit en moins d'une milliseconde, donc
            # elle tient dans un pas de deux secondes. Son `export`, lui, coûte
            # presque une seconde PAR séance et se tronque : il n'a rien à
            # faire dans un écran vivant.
            self._seances = oc.lire_base()
            if not self._gele:
                self._peindre()

        def _peindre(self):
            tableau = self.query_one("#tableau", DataTable)
            tableau.clear()
            for ligne in lignes(self._lectures, self._temps) + lignes_opencode(
                self._seances
            ):
                tableau.add_row(*[ligne[cle] for cle, _ in COLONNES])
            outils = self.query_one("#outils", DataTable)
            outils.clear()
            groupes = jr.par_outil(self._appels)
            for ligne in lignes_outils(groupes):
                outils.add_row(*[ligne[cle] for cle, _ in COLONNES_OUTILS])
            flux = self.query_one("#flux", DataTable)
            flux.clear()
            for ligne in lignes_flux(self._appels):
                flux.add_row(*[ligne[cle] for cle, _ in COLONNES_FLUX])
            self.query_one("#titre_outils", Static).update(
                self._titre_du_panneau(groupes)
            )
            self._resumer()

        def _titre_du_panneau(self, groupes):
            """Ce que le panneau du bas montre, et pourquoi il est vide.

            Les deux vues se vident pour la MÊME raison — aucun hook posé —
            et le dire vaut mieux qu'un tableau nu, qui se lit comme une panne.
            """
            if not self._appels:
                return t("No hook installed: the per-tool figures need one.")
            if self.VUES[self._vue] == "flux":
                return t("Latest tool calls, newest first")
            return t("Per tool")

        def _resumer(self):
            total = st.somme(l.agregat for l in self._lectures.values())
            compte = len(self._lectures)
            self.query_one("#resume", Static).update(
                f"{ICONES['claude']} {compte} {t('sessions')} · "
                f"{t('prompt')} {jetons(total.entree + total.cache_lu + total.cache_cree)}"
                f" · {t('output')} {jetons(total.sortie)}"
                f" · {t('thinking')} {jetons(total.reflexion)}"
                f" · {t('cost')} {total.cout:.2f} $"
                f" · {t('tools')} {duree(total.duree_outils)}"
                + resume_opencode(self._seances)
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
