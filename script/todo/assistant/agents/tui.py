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

from script.todo.assistant.agents import detail as dl
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

# Combien de commandes le flux va chercher par tour. Une recherche coûte
# quarante millisecondes ; en faire soixante d'un coup dépasserait le pas de
# deux secondes. La colonne se remplit donc PROGRESSIVEMENT, et ce qui n'est
# pas encore lu montre des points de suspension plutôt qu'un vide, qui se
# lirait comme « cet appel n'a pas de commande ».
DETAILS_PAR_TOUR = 8

# Ce que les cinq autres colonnes du flux occupent — heure, session, outil,
# durée, fin — séparateurs compris. La commande prend ce qui reste : une
# largeur FIXE déborde d'un terminal de quatre-vingts colonnes tout en
# gaspillant la place d'un large.
FLUX_AUTRES = 42

# En dessous, la colonne ne montre plus rien d'utile : mieux vaut qu'elle
# déborde et se fasse défiler que de n'afficher que « cd … ».
COMMANDE_MIN = 12

# La barre de contexte, en caractères. Assez pour lire une pente, assez peu
# pour tenir dans une colonne à côté des chiffres. À vingt-quatre elle est la
# plus large du tableau et le pousse à cent quarante-trois colonnes, ce qui
# déborde d'à peu près tout terminal.
BARRE = 12

# Le nom de projet, borné. Coupé par la GAUCHE : une famille de dépôts partage
# son préfixe et se distingue par ce qui suit, donc couper par la droite les
# rendrait tous identiques à l'écran.
PROJET_MAX = 16


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
        return _borne_a_gauche(os.path.basename(lu.rstrip("/")))
    return _borne_a_gauche(
        os.path.basename(os.path.dirname(chemin)).split("-")[-1]
    )


def _borne_a_gauche(nom, largeur=PROJET_MAX) -> str:
    """Un nom borné, coupé par la GAUCHE. Fonction PURE.

    Une famille de dépôts partage son préfixe et se distingue par ce qui
    suit : couper par la droite les rendrait tous identiques à l'écran, ce que
    la colonne est justement là pour éviter.
    """
    if not nom or len(nom) <= largeur:
        return nom or ""
    return "…" + nom[-(largeur - 1) :]


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


def largeur_commande(largeur_ecran) -> int:
    """La place qui reste au flux pour la commande. Fonction PURE.

    Une largeur fixe se trompe des deux côtés : elle déborde d'un terminal
    étroit et gaspille celui d'un large. Le plancher existe parce qu'une
    colonne de six caractères ne montre plus rien — mieux vaut alors déborder
    et se faire défiler.
    """
    return max(COMMANDE_MIN, int(largeur_ecran or 0) - FLUX_AUTRES)


def lignes_flux(
    appels, limite=FLUX_MAX, commandes=None, largeur=None
) -> list[dict]:
    """Les derniers appels d'outil, du plus RÉCENT au plus ancien.

    Le panneau des outils dit ce qu'un outil coûte en moyenne ; celui-ci dit
    ce qui vient de se passer, et les deux répondent à des questions
    différentes — « lequel est lent » contre « pourquoi ça bloque depuis deux
    minutes ». Aucun contenu n'y paraît : un nom d'outil, une durée, une fin.

    L'ordre est inversé parce qu'un flux se lit par le haut : mettre le plus
    ancien en tête obligerait à faire défiler pour voir ce qui arrive.

    `commandes` est `{identifiant: commande}`, lu dans les transcriptions et
    jamais dans le journal, qui ne les garde pas. Une entrée absente montre
    des points de suspension — la recherche n'a pas encore eu lieu —, une
    entrée VIDE montre un tiret : la transcription a répondu, et cet appel n'a
    pas de commande à montrer. Les confondre ferait attendre une colonne qui
    ne viendra jamais.
    """
    derniers = sorted(appels, key=lambda a: a.debut_ms)[-limite:]
    return [
        {
            "heure": heure(a.debut_ms),
            "session": (a.session or "")[:8],
            "outil": a.outil or "—",
            "duree": "—" if a.duree_ms is None else duree(a.duree_ms),
            "issue": t(ISSUES.get(a.issue, "")) if ISSUES.get(a.issue) else "",
            "commande": _commande_vue(commandes, a.identifiant, largeur),
        }
        for a in reversed(derniers)
    ]


def texte_du_detail(appel, detail) -> str:
    """Ce que le volet de détail affiche. Fonction PURE.

    La mention de contenu vient EN TÊTE et non en bas : un volet qui déroule
    une longue sortie la pousserait hors de l'écran, et l'avertissement ne
    servirait qu'à ceux qui n'en ont pas besoin.

    Une sortie ABSENTE et une sortie VIDE ne se disent pas pareil. La première
    est un appel encore en cours, ou une transcription qu'on n'a pas su lire ;
    la seconde est une commande qui n'a rien répondu. Les confondre ferait
    chercher une panne là où il n'y a qu'un silence.
    """
    lignes = [t("This pane shows conversation content."), ""]
    if not detail.trouve:
        lignes.append(t("This call was not found in the transcript."))
        return "\n".join(lignes)
    # Un tiret et non « 0 ms » : la durée d'un appel encore en cours n'est pas
    # zéro, elle est inconnue, et zéro se lirait « instantané ».
    mesure = "—" if appel.duree_ms is None else duree(appel.duree_ms)
    lignes.append(f"{detail.outil or appel.outil}  {mesure}")
    if detail.description:
        lignes.append(detail.description)
    lignes.append("")
    lignes.append(detail.commande or "—")
    lignes.append("")
    if detail.sortie is None:
        lignes.append(t("No answer yet."))
    elif not detail.sortie:
        lignes.append(t("The command answered nothing."))
    else:
        if detail.erreur:
            lignes.append(t("The tool reported an error."))
        lignes.append(dl.bornee(detail.sortie))
    return "\n".join(lignes)


def _commande_vue(commandes, identifiant, largeur=None) -> str:
    """Ce que la colonne montre : la commande, « … » ou « — »."""
    if commandes is None or identifiant not in commandes:
        return "…"
    coupee = dl.une_ligne(
        commandes[identifiant],
        largeur if largeur else dl.COLONNE_MAX,
    )
    return coupee or "—"


# Les colonnes du flux. La session y est abrégée : le flux réunit toutes les
# sessions de la machine, et sans elle deux terminaux se lisent comme un seul.
COLONNES_FLUX = (
    ("heure", "time"),
    ("session", "session"),
    ("outil", "tool"),
    ("duree", "duration"),
    ("issue", "outcome"),
    ("commande", "command"),
)


def adaptateur_claude():
    """L'adaptateur, importé à la demande.

    En tête de module il ferait payer son import à tout ce qui lit `tui` pour
    une fonction pure — et la frontière du paquet veut que rien ne tire plus
    que nécessaire.
    """
    from script.todo.assistant.harness import claude

    return claude


def agents_detaches(flotte) -> list:
    """Les agents détachés VIVANTS de la flotte, dans son ordre. Fonction PURE.

    Vivant ET détaché, et les deux comptent. La flotte réunit deux sources qui
    ne disent pas la même chose : le registre annonce ce qui TOURNE, un
    balayage des transcriptions annonce ce qui se REPREND. Une session
    dormante en sort sans genre ni processus — l'offrir ici proposerait `stop`
    sur un fichier, et l'outil répondrait « No job matching » avec un code de
    sortie NUL, donc sans que rien ne paraisse échouer.

    Séparé du formatage parce que l'ÉCRAN doit pouvoir remonter d'une ligne
    surlignée à la session qu'elle décrit. Refiltrer puis rapprocher par
    identifiant ferait dépendre le geste d'un aller-retour par du texte, là où
    un même index suffit.
    """
    from script.todo.assistant.harness import claude as adaptateur

    return [
        session
        for session in flotte or ()
        if getattr(session, "live", False)
        and adaptateur.est_arriere_plan(session)
    ]


def lignes_agents(agents) -> list[dict]:
    """Une ligne par agent détaché, dans l'ordre reçu. Fonction PURE.

    Prend ce que `agents_detaches` a filtré : l'index d'une ligne est donc
    l'index de sa session, et l'écran n'a rien à rapprocher.

    Aucun titre ni nom de conversation : ce que le registre appelle `name` est
    engendré par le modèle à partir de l'invite, donc c'est du contenu.
    """
    sorties = []
    for session in agents or ():
        sorties.append(
            {
                "id": session.poignee,
                "projet": os.path.basename((session.cwd or "").rstrip("/")),
                "etat": (
                    t(ETATS.get(session.status, "")) if session.status else ""
                ),
                "branche": session.branch or "—",
                "pid": str(session.pid or "—"),
            }
        )
    return sorties


# Ce que le registre appelle l'état d'un agent, traduit. La clé EST la chaîne
# anglaise ; un état inconnu d'une version future se montre tel quel plutôt
# que de disparaître.
ETATS = {"busy": "busy", "idle": "idle"}

# Les colonnes du panneau des agents. Ni titre ni nom : le `name` du registre
# est engendré par le modèle à partir de l'invite, donc c'est du contenu.
COLONNES_AGENTS = (
    ("id", "agent"),
    ("projet", "project"),
    ("etat", "state"),
    ("branche", "branch"),
    ("pid", "pid"),
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
    ("echoues", "failed calls"),
    ("interrompus", "interrupted calls"),
    ("inacheves", "unfinished"),
)

# Les colonnes du tableau : la clé dans la ligne, et sa clé i18n.
# L'icône qui dit de QUEL harnais vient la ligne. Le tableau en réunit deux
# qui ne mesurent pas les mêmes choses, et deux identifiants de huit
# caractères ne se distinguent pas d'un coup d'œil. Elles viennent du registre
# des harnais, pour qu'un seul endroit les décide.
ICONES = {"claude": "🤖", "opencode": "🧊"}

# Les colonnes du tableau des sessions, PAR ORDRE D'IMPORTANCE et non par
# parenté de sujet. L'ordre décide de ce qui reste à l'écran quand le terminal
# est étroit : les quatre premières répondent à « laquelle, où, combien ça
# coûte, où en est son contexte », qui est ce qu'on vient voir. Les dernières
# sont des détails qu'on va chercher.
#
# Les douze réclament cent vingt-quatre colonnes, donc un terminal de
# quatre-vingts n'en montre jamais la moitié. Les ordonner rend ce tronquage
# supportable ; les cacher franchement le rend lisible.
COLONNES = (
    ("id", "session"),
    ("projet", "project"),
    ("cout", "cost"),
    ("contexte", "context"),
    ("pente", "growth"),
    ("attention", "attention"),
    ("tours", "turns"),
    ("entree", "prompt"),
    ("sortie", "output"),
    ("outils", "tools"),
    ("cache", "cache"),
    ("api", "API"),
)

# Ce qu'une colonne coûte, séparateur compris. Sert à choisir combien en
# montrer AVANT de les créer — leur largeur réelle dépend de ce qu'elles
# contiennent, qu'on ne connaît pas encore au montage.
#
# Douze et non la moyenne de dix : les deux premières colonnes, celles qui
# nomment la session et le projet, sont les plus larges du lot. Une estimation
# juste en moyenne se trompe donc toujours du même côté, celui qui déborde.
COLONNE_LARGEUR = 12


def colonnes_visibles(largeur_ecran, colonnes=None) -> tuple:
    """Les colonnes qui tiennent, dans l'ordre d'importance. Fonction PURE.

    Toujours au moins les deux premières : un tableau qui ne dirait ni quelle
    session ni quel projet ne dirait rien du tout, et mieux vaut alors déborder
    et se faire défiler.
    """
    colonnes = colonnes or COLONNES
    combien = max(2, int(largeur_ecran or 0) // COLONNE_LARGEUR)
    return tuple(colonnes[:combien])


def run_tui(run_app: bool = True):
    """L'écran. `run_app=False` rend l'application sans la lancer, pour test.

    Textual est importé ICI et non en tête : le module est lu par le menu à
    chaque affichage, et Textual coûte près d'une seconde à l'import. Le CLI
    ne doit pas le payer pour un écran qu'on n'ouvre pas.
    """
    from textual.app import App, ComposeResult
    from textual.widgets import (
        DataTable,
        Footer,
        Header,
        Input,
        Static,
    )

    class Telemetrie(App):
        CSS = """
        #resume { height: auto; padding: 0 1; color: $text-muted; }
        #etat { height: auto; padding: 0 1; color: $warning; }
        #source { height: auto; padding: 0 1; color: $text-muted; }
        DataTable { height: 1fr; }
        """
        # Les libellés sont COURTS, et c'est une contrainte de place et non
        # de goût : le pied de page tient sur une ligne à toute largeur, donc
        # dix indications un peu bavardes réclament le double d'un terminal de
        # quatre-vingts colonnes, et les dernières touches disparaissent. Sur
        # un écran qui se pilote au clavier, une touche invisible n'existe pas.
        BINDINGS = [
            ("q", "quit", t("Quit")),
            ("f", "gel", t("Freeze")),
            ("r", "relire", t("Read again")),
            ("v", "vue", t("Panel")),
            ("n", "lancer", t("Start")),
            ("s", "arreter", t("Stop")),
            ("a", "attacher", t("Attach")),
            ("d", "detail", t("Detail")),
            ("l", "relancer", t("Restart")),
            ("x", "supprimer", t("Delete")),
        ]

        # Le panneau du bas PERMUTE au lieu de s'empiler : un terminal n'a pas
        # la hauteur pour trois tableaux, et empiler les réduirait tous à
        # quatre lignes. Les deux répondent à des questions différentes :
        # « quel outil est lent » contre « qu'est-ce qui vient de se passer ».
        VUES = ("outils", "flux", "agents")

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
            self._flotte: list = []
            self._agents: list = []
            # Ce qui est PEINT, par opposition à ce qui vient d'être relu. Le
            # curseur indexe l'écran, pas la lecture : pendant un gel les deux
            # divergent, et viser la ligne surlignée dans la liste fraîche
            # arrêterait un autre agent que celui qu'on regarde.
            self._agents_peints: list = []
            self._appels_peints: list = []
            # {identifiant: commande} — lu dans les transcriptions à la
            # demande, jamais écrit nulle part. Une entrée absente veut dire
            # « pas encore cherché », une entrée vide « cherché, rien à
            # montrer » : sans la distinction, on rechercherait sans fin ce
            # qui n'existe pas.
            self._commandes: dict = {}
            # Les colonnes actuellement posées, pour ne les refaire que
            # lorsque la largeur en change le nombre.
            self._colonnes: tuple = ()
            # Le redimensionnement arrive AVANT le montage : repeindre alors
            # remplirait des tableaux qui n'ont pas encore de colonnes.
            self._monte = False
            # Ce que la ligne de saisie attend, ou None quand elle est fermée.
            self._attente: str | None = None
            # La session visée par la saisie en cours. Gardée à part parce que
            # la flotte se relit toutes les deux secondes : chercher à nouveau
            # la ligne surlignée au moment de valider agirait sur une autre
            # session que celle qu'on a lue dans l'invite.
            self._cible = None

        def compose(self) -> ComposeResult:
            yield Header(show_clock=True)
            yield Static("", id="resume")
            yield DataTable(id="tableau", zebra_stripes=True)
            yield Static("", id="titre_outils")
            yield DataTable(id="outils", zebra_stripes=True)
            yield DataTable(id="flux", zebra_stripes=True)
            yield DataTable(id="agents", zebra_stripes=True)
            yield Input(id="saisie", placeholder="")
            yield Static("", id="detail")
            yield Static("", id="etat")
            yield Static("", id="source")
            yield Footer()

        def on_mount(self):
            self.title = t("Agent telemetry")
            self._poser_les_colonnes()
            outils = self.query_one("#outils", DataTable)
            for _, cle in COLONNES_OUTILS:
                outils.add_column(t(cle), key=cle)
            flux = self.query_one("#flux", DataTable)
            for _, cle in COLONNES_FLUX:
                flux.add_column(t(cle), key=cle)
            agents = self.query_one("#agents", DataTable)
            for _, cle in COLONNES_AGENTS:
                agents.add_column(t(cle), key=cle)
            self.query_one("#saisie", Input).display = False
            self.query_one("#etat", Static).display = False
            self.query_one("#detail", Static).display = False
            self._montrer_la_vue()
            # Les journaux périmés partent à l'ouverture : c'est le seul
            # moment où quelqu'un regarde, donc le seul où le ménage ne
            # surprend personne.
            jr.nettoyer()
            self._monte = True
            self._tick()
            self.set_interval(PAS, self._tick)

        def _poser_les_colonnes(self):
            """(Re)créer les colonnes du tableau selon la largeur de l'écran.

            Refaites seulement quand leur NOMBRE change : les recréer à chaque
            tour remettrait le curseur en haut toutes les deux secondes, sous
            les doigts de qui lit.
            """
            voulues = colonnes_visibles(self.size.width)
            if voulues == self._colonnes:
                return
            self._colonnes = voulues
            tableau = self.query_one("#tableau", DataTable)
            tableau.clear(columns=True)
            for _, cle in voulues:
                tableau.add_column(t(cle), key=cle)

        def on_resize(self, evenement):
            """Une fenêtre qu'on étire montre ce qu'elle peut montrer.

            Sans effet avant le montage : Textual annonce une taille dès la
            composition, et repeindre là remplirait des tableaux dont les
            colonnes ne sont pas encore posées.
            """
            if not self._monte:
                return
            self._poser_les_colonnes()
            self._peindre()

        def action_vue(self):
            """Passer au panneau suivant, en boucle."""
            self._vue = (self._vue + 1) % len(self.VUES)
            self._montrer_la_vue()
            # Remplir TOUT DE SUITE : sans cela, la colonne des commandes
            # reste en points de suspension jusqu'au tour suivant, soit deux
            # secondes après qu'on a demandé à la voir.
            self._completer_les_commandes()
            self._peindre()

        def _montrer_la_vue(self):
            """N'afficher que le panneau courant, et LUI donner le clavier.

            Le focus n'est pas un raffinement : Textual le donne au premier
            widget focalisable, soit le tableau du haut, et un panneau caché
            sort de la chaîne de focus. Les flèches pilotaient donc le tableau
            des sessions pendant que les touches agissaient sur le panneau
            visible — dont le curseur n'avait jamais bougé. « s » arrêtait le
            premier agent quel que soit celui qu'on croyait viser, et « s »
            est justement la seule action qui ne demande rien.
            """
            courant = self.VUES[self._vue]
            for nom in self.VUES:
                table = self.query_one(f"#{nom}", DataTable)
                table.display = nom == courant
                if nom == courant:
                    table.focus()

        # Ce que la ligne de saisie attend, et ce que valider déclenche.
        # Ce que la ligne de saisie attend. Trois modes, parce que trois
        # gestes ne coûtent pas la même chose : lancer ne détruit rien,
        # relancer coupe le travail en cours, supprimer efface l'arbre de
        # travail et rien ne le récupère.
        INVITE = "invite"
        CONFIRME = "confirme"
        RETAPE = "retape"

        def action_lancer(self):
            """Ouvrir la saisie d'une invite pour un agent détaché."""
            self._ouvrir_saisie(self.INVITE, t("Prompt for the new agent:"))

        def action_arreter(self):
            """Arrêter l'agent surligné. Sa conversation est GARDÉE.

            Rien de destructeur ici : un `attach` la rouvre. C'est pourquoi
            cette action-ci ne demande aucune confirmation, là où `rm` exige
            de retaper l'identifiant en entier.
            """
            session = self._agent_choisi()
            if session is None:
                self._dire(t("Pick a detached agent first."))
                return
            self._lancer_action(adaptateur_claude().ARRETER, session.poignee)

        def action_attacher(self):
            """Attacher l'agent surligné — ce qui FERME cet écran.

            `claude attach` prend le terminal : il ne peut pas cohabiter avec
            une application qui le tient déjà. L'écran quitte donc, et imprime
            la commande plutôt que de la lancer — reprendre la main sur un
            terminal qu'on vient de rendre est le genre de chose qui laisse un
            affichage à moitié effacé.
            """
            session = self._agent_choisi()
            if session is None:
                self._dire(t("Pick a detached agent first."))
                return
            argv = adaptateur_claude().argv_action(
                adaptateur_claude().ATTACHER, session.poignee
            )
            self.exit(" ".join(argv))

        def action_relancer(self):
            """Relancer l'agent surligné sur le binaire courant.

            Le travail en cours est COUPÉ, donc une confirmation est exigée —
            mais une confirmation simple : la conversation, elle, survit, et
            c'est ce qui sépare ce geste du suivant.
            """
            session = self._agent_choisi()
            if session is None:
                self._dire(t("Pick a detached agent first."))
                return
            self._cible = session
            self._ouvrir_saisie(
                self.CONFIRME,
                f"{t('The work in progress is cut. Type yes:')} "
                f"{session.poignee}",
            )

        def action_supprimer(self):
            """Supprimer l'agent surligné, ET son arbre de travail.

            Rien ne le récupère, donc l'identifiant se RETAPE en entier — le
            long, pas celui de huit caractères. Une frappe sur « o » se donne
            par réflexe ; recopier vingt-six caractères oblige à regarder ce
            qu'on détruit.
            """
            session = self._agent_choisi()
            if session is None:
                self._dire(t("Pick a detached agent first."))
                return
            self._cible = session
            self._ouvrir_saisie(
                self.RETAPE,
                f"{t('This deletes the session and its worktree. Retype:')} "
                f"{session.session_id}",
            )

        def _ouvrir_saisie(self, attente, invite):
            from textual.widgets import Input

            # Ce qu'un geste précédent avait dit ne vaut plus pour celui-ci.
            self._dire("")

            self._attente = attente
            champ = self.query_one("#saisie", Input)
            champ.placeholder = invite
            champ.value = ""
            champ.display = True
            champ.focus()

        def _fermer_saisie(self):
            from textual.widgets import Input

            self._attente = None
            champ = self.query_one("#saisie", Input)
            champ.value = ""
            champ.display = False

        def on_input_submitted(self, evenement):
            attente, self._attente = self._attente, None
            cible, self._cible = self._cible, None
            texte = (evenement.value or "").strip()
            self._fermer_saisie()
            if attente == self.INVITE:
                if texte:
                    self._lancer_agent(texte)
                return
            if cible is None:
                return
            if attente == self.CONFIRME:
                self._confirme(texte, adaptateur_claude().RELANCER, cible)
            elif attente == self.RETAPE:
                self._retape(texte, cible)

        def _confirme(self, frappe, sous_commande, session):
            """Un oui, dans l'une ou l'autre langue de l'écran."""
            if frappe.lower() in ("o", "oui", "y", "yes"):
                self._lancer_action(sous_commande, session.poignee)
            else:
                self._dire(t("Nothing has been sent."))

        def _retape(self, frappe, session):
            """L'identifiant ENTIER, ou rien ne part.

            Comparé au long et non à celui de huit caractères : c'est la
            longueur qui fait la garde, pas la forme.
            """
            # L'identifiant peut être VIDE — une version du listage qui ne
            # porte pas « sessionId » le laisse à "" — et la comparaison
            # devenait alors vraie sur une simple frappe d'Entrée. La garde la
            # plus forte du paquet s'ouvrait sur rien.
            if session.session_id and frappe == session.session_id:
                self._lancer_action(
                    adaptateur_claude().SUPPRIMER, session.poignee
                )
            else:
                self._dire(t("Nothing has been sent."))

        def on_key(self, evenement):
            """Échap referme la saisie sans rien envoyer."""
            if evenement.key == "escape" and self._attente is not None:
                self._fermer_saisie()
                evenement.stop()

        def _lancer_agent(self, invite):
            """Lancer un agent détaché, l'invite sur l'ENTRÉE STANDARD.

            Jamais en positionnel : `/proc/<pid>/cmdline` est lisible par tout
            compte de la machine. L'appel rend la main tout de suite — c'est
            ce que `--bg` promet — donc l'écran ne se fige pas.
            """
            import subprocess

            adaptateur = adaptateur_claude()
            try:
                fini = subprocess.run(
                    adaptateur.argv_lancer(),
                    input=invite,
                    text=True,
                    capture_output=True,
                    timeout=120,
                )
            except (OSError, subprocess.SubprocessError) as souci:
                self._dire(str(souci))
                return
            identifiant = adaptateur.identifiant_lance(fini.stdout)
            self._dire(
                f"{t('Agent started')} {identifiant}"
                if identifiant
                else t("The agent did not report an identifier.")
            )
            self._tick()

        def _lancer_action(self, sous_commande, poignee):
            """Une action sur un agent, et ce que l'outil en dit."""
            import subprocess

            try:
                argv = adaptateur_claude().argv_action(sous_commande, poignee)
                fini = subprocess.run(
                    argv, text=True, capture_output=True, timeout=60
                )
            except (OSError, ValueError, subprocess.SubprocessError) as souci:
                self._dire(str(souci))
                return
            # L'outil répond « No job matching » avec un code de sortie NUL :
            # se fier au code laisserait annoncer un geste qui n'a pas eu lieu.
            premiere = (fini.stdout or fini.stderr or "").strip().splitlines()
            self._dire(premiere[0] if premiere else t("Nothing was said."))
            self._tick()

        def _dire(self, message):
            """Ce que l'outil vient de répondre, dans un widget À LUI.

            Pas dans `#source` : `_resumer` y réécrit la phrase fixe sur la
            provenance des chiffres, et il est appelé par `_peindre`, que
            chaque action déclenche juste après avoir parlé. Les deux écritures
            tombaient dans la même itération de la boucle d'événements, donc
            le message n'existait pas une seule image.

            Ce qu'on perdait ainsi n'était pas du décor : `claude stop` répond
            « No job matching » avec un code de sortie NUL, et cette ligne est
            le SEUL endroit où l'échec se voit.
            """
            from textual.widgets import Static

            champ = self.query_one("#etat", Static)
            texte = str(message)[:200]
            champ.update(texte)
            champ.display = bool(texte)

        def action_detail(self):
            """Ouvrir ou fermer le détail de l'appel surligné.

            Le volet MONTRE du contenu — une commande et sa sortie — là où
            tout le reste de l'écran s'en tient à des noms, des comptes et des
            durées. Il le dit donc, en toutes lettres et à chaque ouverture :
            un partage d'écran ne doit pas révéler par distraction ce qu'un
            geste délibéré vient de demander.

            Rien de ce qu'il affiche n'est écrit : la commande est relue dans
            la transcription, où Claude Code l'avait déjà mise.
            """
            from textual.widgets import Static

            volet = self.query_one("#detail", Static)
            if volet.display:
                volet.display = False
                return
            appel = self._appel_choisi()
            if appel is None:
                self._dire(t("Pick a tool call in the stream first."))
                return
            volet.update(texte_du_detail(appel, dl.pour(appel)))
            volet.display = True

        def _appel_choisi(self):
            """L'appel de la ligne surlignée du flux, ou None.

            Le flux est peint depuis `_appels_peints`, donc l'index d'une
            ligne EST celui de son appel — y compris pendant un gel, où les
            lectures continuent dessous sans que l'écran bouge.
            """
            if self.VUES[self._vue] != "flux" or not self._appels_peints:
                return None
            rang = self.query_one("#flux", DataTable).cursor_row
            if rang is None or not 0 <= rang < len(self._appels_peints):
                return None
            return self._appels_peints[rang]

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
            # 0,15 s par tour, soit un quinzième du pas : c'est le prix d'un
            # panneau qui dit ce qui TOURNE, que le disque ne porte pas.
            self._flotte = self._lire_flotte()
            self._agents = agents_detaches(self._flotte)
            self._completer_les_commandes()
            if not self._gele:
                self._peindre()

        @staticmethod
        def _repeindre(table, lignes, colonnes, cle):
            """Refaire un tableau SANS perdre la ligne qu'on avait choisie.

            Le curseur est rattaché à la ligne par sa clé, jamais à son rang :
            un tour de rafraîchissement le remettait en tête, et le geste
            suivant visait la première ligne au lieu de celle qu'on avait
            surlignée. Deux secondes suffisaient, et « s » n'a pas de
            confirmation pour rattraper.

            Une ligne qui a disparu depuis le dernier tour ne se retrouve pas,
            et le curseur reste alors où Textual le met : l'agent visé n'existe
            plus, donc il n'y a rien à viser.
            """
            avant = None
            if table.row_count:
                try:
                    avant = table.coordinate_to_cell_key(
                        table.cursor_coordinate
                    ).row_key
                except Exception:
                    avant = None
            table.clear()
            for ligne in lignes:
                table.add_row(
                    *[ligne[c] for c, _ in colonnes], key=str(ligne[cle])
                )
            if avant is not None:
                # `move_cursor` ne prend qu'un RANG : la clé se retraduit donc
                # en index après le repeint, ce qui est précisément le point —
                # le rang a pu changer, la ligne non.
                try:
                    table.move_cursor(row=table.get_row_index(avant))
                except Exception:
                    pass

        def _peindre(self):
            tableau = self.query_one("#tableau", DataTable)
            tableau.clear()
            self._repeindre(
                tableau,
                lignes(self._lectures, self._temps)
                + lignes_opencode(self._seances),
                self._colonnes,
                "id",
            )
            outils = self.query_one("#outils", DataTable)
            groupes = jr.par_outil(self._appels)
            self._repeindre(
                outils, lignes_outils(groupes), COLONNES_OUTILS, "outil"
            )
            flux = self.query_one("#flux", DataTable)
            # La liste PEINTE est gardée : c'est elle que le curseur indexe,
            # et un gel la fige pendant que les lectures continuent dessous.
            self._appels_peints = sorted(
                self._appels, key=lambda a: a.debut_ms
            )[-FLUX_MAX:][::-1]
            self._repeindre(
                flux,
                lignes_flux(
                    self._appels,
                    commandes=self._commandes,
                    largeur=largeur_commande(self.size.width),
                ),
                COLONNES_FLUX,
                "heure",
            )
            agents = self.query_one("#agents", DataTable)
            self._agents_peints = list(self._agents)
            self._repeindre(
                agents, lignes_agents(self._agents), COLONNES_AGENTS, "id"
            )
            self.query_one("#titre_outils", Static).update(
                self._titre_du_panneau(groupes)
            )
            self._resumer()

        def _completer_les_commandes(self):
            """Chercher quelques commandes manquantes, et seulement au besoin.

            Seulement quand le flux est à l'écran : on ne paie que ce qu'on
            regarde. Et quelques-unes par tour, parce qu'une recherche coûte
            quarante millisecondes et que soixante d'un coup dépasseraient le
            pas de rafraîchissement — la colonne se remplit sous les yeux
            plutôt que de figer l'écran une fois.
            """
            if self.VUES[self._vue] != "flux":
                return
            manquants = [
                a
                for a in sorted(self._appels, key=lambda x: -x.debut_ms)[
                    :FLUX_MAX
                ]
                if a.identifiant and a.identifiant not in self._commandes
            ]
            for appel in manquants[:DETAILS_PAR_TOUR]:
                self._commandes[appel.identifiant] = dl.pour(appel).commande

        @staticmethod
        def _lire_flotte():
            """La flotte, ou une liste vide si l'outil ne répond pas.

            Une machine sans Claude Code n'est pas une panne de l'écran, et un
            listage qui échoue ne doit pas éteindre le rafraîchissement.
            """
            from script.todo.assistant import claude_sessions as cs

            try:
                return cs.fleet()
            except Exception:
                return []

        def _agent_choisi(self):
            """L'agent de la ligne surlignée du panneau, ou None.

            None a trois causes qui ne se distinguent pas ici et n'ont pas
            besoin de l'être : on n'est pas dans le panneau des agents, il est
            vide, ou aucune ligne n'est surlignée. Les trois se répondent par
            « rien à faire », et l'appelant le dit.

            L'index de la ligne EST l'index de la session PEINTE — pas de la
            dernière lue. Les deux divergent dès qu'on gèle l'écran, et viser
            dans la liste fraîche arrêterait un autre agent que celui qu'on
            regarde.
            """
            if self.VUES[self._vue] != "agents" or not self._agents_peints:
                return None
            rang = self.query_one("#agents", DataTable).cursor_row
            if rang is None or not 0 <= rang < len(self._agents_peints):
                return None
            return self._agents_peints[rang]

        def _titre_du_panneau(self, groupes):
            """Ce que le panneau du bas montre, et pourquoi il est vide.

            Les deux vues se vident pour la MÊME raison — aucun hook posé —
            et le dire vaut mieux qu'un tableau nu, qui se lit comme une panne.
            """
            if not self._appels and self.VUES[self._vue] != "agents":
                return t("No hook installed: the per-tool figures need one.")
            if self.VUES[self._vue] == "agents":
                if self._agents:
                    return t("Detached agents running now")
                return t("No detached agent. Press n to start one.")
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
    # Ce que l'écran rend en sortant, ou None. Aujourd'hui c'est la commande
    # d'attache : elle prend le terminal, donc l'écran quitte d'abord et
    # laisse l'appelant la lancer. La jeter ici fermait l'écran sans rien
    # dire, et l'utilisateur n'avait plus ni écran ni commande.
    return app.run()
