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
from dataclasses import dataclass, field

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

# Tous les combien de PAS la flotte est relue — soit six secondes. Le listage
# passe par un SOUS-PROCESSUS et coûte cent soixante millisecondes là où la
# lecture incrémentale des transcriptions n'en coûte que cinq. Un agent ne naît
# ni ne meurt toutes les deux secondes, donc la question se pose trois fois
# moins souvent ; un geste qui en change l'état la repose tout de suite.
#
# La cadence se compte en TEMPS et non en tours : les tours s'enchaînent en
# rafale tant que la colonne des commandes se remplit, et un compteur de tours
# lancerait alors un sous-processus toutes les trois rafales.
PAS_FLOTTE = 3

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
                # Ce qui IDENTIFIE la rangée, jamais affiché. Le chemin est
                # unique par construction là où les huit premiers caractères
                # d'un identifiant ne le sont que probablement.
                "cle": chemin,
                "id": f"{ICONES['claude']} {identifiant(chemin)}",
                "projet": projet(chemin, a),
                "tours": str(a.tours),
                "entree": jetons(a.entree + a.cache_lu + a.cache_cree),
                "sortie": jetons(a.sortie),
                "reflexion": jetons(a.reflexion),
                "cache": (
                    "—" if reutilisation is None else f"{reutilisation:.0%}"
                ),
                # Tout ce qui vient d'un `cost-state` rend un TIRET quand
                # aucun n'a été lu. Neuf des dix-huit transcriptions d'une
                # machine ordinaire n'en portent aucun — session interrompue,
                # version antérieure, session neuve — et « 0 ms » s'y lisait
                # « mesuré, et nul » là où rien ne l'avait été.
                "cout": f"{a.cout:.2f} $" if a.cout else "—",
                "horloge": _mesure(a.segments, duree, a.duree_horloge),
                "attention": "—" if attention is None else duree(attention),
                "api": _mesure(a.segments, duree, a.duree_api),
                "outils": _mesure(a.segments, duree, a.duree_outils),
                # Sans un seul tour, il n'y a pas d'invite dont donner la
                # taille : « 0 » se lirait « mesuré, et vide », et l'autre
                # harnais rend un tiret pour la MÊME absence.
                "contexte": jetons(a.contexte) if a.tours else "—",
                "pente": barre(a.serie),
                "segments": str(a.segments),
                "compactions": str(a.compactions),
                "code": _mesure(
                    a.segments,
                    lambda _: f"+{a.lignes_ajoutees}/−{a.lignes_retirees}",
                    0,
                ),
            }
        )
    return sorties


def _mesure(segments, rendu, valeur) -> str:
    """Une valeur de `cost-state`, ou un tiret quand aucun n'a été lu.

    Fonction PURE. `segments` compte les `cost-state` vus : à zéro, la valeur
    n'est pas nulle, elle est INCONNUE. Le coût le disait déjà, les durées et
    les lignes touchées non, alors qu'elles viennent du même enregistrement.
    """
    return rendu(valeur) if segments else "—"


def lignes_opencode(seances) -> list[dict]:
    """Une ligne par séance d'Open Code, dans la MÊME forme que les autres.

    Le tableau réunit deux harnais qui ne mesurent pas les mêmes choses. Les
    champs qu'Open Code ne porte pas — les tours, le contexte, sa pente, les
    durées d'API et d'outils — rendent un tiret et JAMAIS un zéro : une
    colonne à zéro se lit « mesuré, et nul », ce qui est faux et décourage de
    chercher ailleurs ce que l'autre harnais, lui, donne.

    Ce qu'il porte, en revanche, se compte comme en face. Les deux moitiés du
    cache sont là : les omettre de l'invite faisait une colonne dont la
    définition changeait d'une ligne à l'autre, et c'est le sens même d'un
    tableau commun qui s'y perdait. Le nom de projet se borne pareillement —
    une largeur de colonne ne dépend pas du harnais qui l'a remplie.

    `seances` peut valoir None, qui veut dire « la base n'a pas répondu » :
    aucune ligne n'est alors ajoutée, et le tableau ne ment pas sur l'absence.
    """
    sorties = []
    for seance in seances or ():
        resume = seance.resume
        if resume is None:
            continue
        reutilisation = resume.reutilisation
        sorties.append(
            {
                "cle": seance.identifiant,
                "id": (
                    f"{ICONES['opencode']} "
                    f"{seance.identifiant.removeprefix('ses_')[:8]}"
                ),
                "projet": _borne_a_gauche(
                    os.path.basename(seance.repertoire.rstrip("/"))
                ),
                "tours": "—",
                "entree": jetons(resume.invite),
                "sortie": jetons(resume.sortie),
                "reflexion": jetons(resume.raisonnement),
                "cache": (
                    "—" if reutilisation is None else f"{reutilisation:.0%}"
                ),
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
            # L'identifiant d'appel, et non l'heure affichée : celle-ci est à
            # la seconde, et deux appels par seconde sont l'ordinaire d'une
            # session qui travaille.
            "cle": a.identifiant or f"{a.debut_ms}-{rang}",
            "heure": heure(a.debut_ms),
            "session": (a.session or "")[:8],
            "outil": a.outil or "—",
            "duree": "—" if a.duree_ms is None else duree(a.duree_ms),
            "issue": t(ISSUES.get(a.issue, "")) if ISSUES.get(a.issue) else "",
            "commande": _commande_vue(commandes, a.identifiant, largeur),
        }
        for rang, a in enumerate(reversed(derniers))
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


# Ce que le cache retient à la place d'un contenu : rien, sinon sa PRÉSENCE.
# `None` dit « il y en a, et nous ne le gardons pas », là où la chaîne vide dit
# « cherché, il n'y a rien ». Les deux se lisent différemment à l'écran, et
# seul le premier évite de tenir une invite de sous-agent en mémoire pour toute
# la durée de la séance.
CONTENU_NON_GARDE = None


def _commande_vue(commandes, identifiant, largeur=None) -> str:
    """Ce que la colonne montre, et ce qu'elle refuse de montrer.

    Quatre états. « … » : pas encore cherché. « — » : cherché, rien à montrer.
    La valeur elle-même quand c'est une commande, un chemin ou une URL. Et
    « contenu » quand c'est du TEXTE LIBRE — l'invite d'un `Task`, le motif
    d'un `Grep` —, que le volet montre avec son avertissement et que cette
    colonne n'a pas le droit d'étaler : elle déclare ne montrer aucun contenu,
    et un appel `Task` y écrivait l'invite entière du sous-agent.

    Le quatrième état ne porte pas la valeur : le cache ne la garde pas.
    """
    if commandes is None or identifiant not in commandes:
        return "…"
    valeur, colonnable = commandes[identifiant]
    if valeur is CONTENU_NON_GARDE or (valeur and not colonnable):
        return t("content")
    coupee = dl.une_ligne(valeur, largeur if largeur else dl.COLONNE_MAX)
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
                "cle": session.poignee or session.session_id,
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
            "cle": p.outil or "—",
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


# Les touches, et c'est la SEULE liste. Le pied de page, le panneau d'aide et
# les numéros qui agissent la lisent tous, donc une touche ajoutée ne peut pas
# manquer à l'un des trois — c'est arrivé : quatre touches tombaient
# hors d'un pied de page de quatre-vingts colonnes, dont les deux qui
# détruisent, et rien à l'écran ne disait qu'elles existaient.
#
# (touche, action, libellé du pied de page, ce que la touche fait)
#
# Les libellés du pied de page sont COURTS par contrainte de place : il tient
# sur une ligne, et une douzaine d'indications bavardes réclament le double
# ordinaire. La phrase entière vit dans le panneau d'aide, qui a la place.
TOUCHES_AFFICHAGE = (
    ("q", "quit", "Quit", "Quit the screen"),
    ("f", "gel", "Freeze", "Freeze the display; the reads go on underneath"),
    ("r", "relire", "Read again", "Read everything again from the start"),
    ("v", "vue", "Panel", "Switch the bottom panel"),
    ("h", "aide", "Keys", "Show this panel"),
)

# Celles qui agissent sur la ligne SURLIGNÉE. Leur rang dans ce tuple est le
# numéro que le panneau d'aide affiche et accepte, donc les réordonner change
# ce que « 3 » fait : elles vont du geste qui ne coûte rien à celui que rien ne
# répare.
TOUCHES_LIGNE = (
    (
        "d",
        "detail",
        "Detail",
        "Detail of the highlighted call (shows content)",
    ),
    ("j", "journal", "Output", "Raw output of the agent (shows content)"),
    ("n", "lancer", "Start", "Start a detached agent"),
    ("s", "arreter", "Stop", "Stop the highlighted agent"),
    (
        "l",
        "relancer",
        "Restart",
        "Restart it on the current binary (confirms)",
    ),
    (
        "x",
        "supprimer",
        "Delete",
        "Delete it and its worktree (retype the identifier)",
    ),
    ("a", "attacher", "Attach", "Attach to it — this closes the screen"),
)

# Les chiffres que le panneau accepte : un par touche de ligne, dans l'ordre.
CHIFFRES = tuple(str(rang + 1) for rang in range(len(TOUCHES_LIGNE)))


def texte_de_l_aide(largeur=None) -> str:
    """Le panneau des touches, en toutes lettres. Fonction PURE.

    Bâti sur la table des touches et non recopié à côté : un panneau d'aide
    qui se maintient à la main finit par décrire un écran qui n'existe plus,
    et c'est justement l'écran qu'on vient consulter quand on ne sait plus.
    """
    lignes = [f"⌨  {t('Keys and actions')}", ""]
    lignes.append(f"  {t('Display')}")
    for touche, _action, _court, phrase in TOUCHES_AFFICHAGE:
        lignes.append(f"    {touche}  {t(phrase)}")
    lignes.append("")
    lignes.append(f"  {t('Act')}")
    for rang, (touche, _a, _c, phrase) in enumerate(TOUCHES_LIGNE):
        lignes.append(f"   [{rang + 1}] {touche}  {t(phrase)}")
    lignes.append("")
    lignes.append(f"  {t('A number acts · Esc closes')}")
    return "\n".join(lignes)


@dataclass(frozen=True)
class Releve:
    """Ce qu'un tour de lecture rapporte du disque.

    Aucun widget, aucune référence à l'application : cet objet TRAVERSE un
    fil, et tout ce qui le compose est recopié plutôt que partagé. C'est ce
    qui permet de lire hors de la boucle d'événements sans course — le fil
    produit, la boucle applique.
    """

    lectures: dict = field(default_factory=dict)
    appels: tuple = ()
    # None veut dire « les hooks ne sont pas posés », ce qui n'est pas
    # « aucune session n'a travaillé ».
    temps: dict | None = None
    # None veut dire « la base d'Open Code n'a pas répondu ».
    seances: list | None = None
    # None veut dire « pas relue ce tour », par opposition à une liste vide
    # qui veut dire « relue, et personne ne tourne ».
    flotte: list | None = None
    commandes: dict = field(default_factory=dict)


def relever(
    precedentes, *, besoins=(), avec_flotte=False, lire_flotte=None
) -> Releve:
    """Tout ce qu'un tour lit sur le disque. Ne touche à AUCUN widget.

    C'est la fonction qui tourne sur le fil d'arrière-plan, et la raison
    d'être de ce fil tient dans un chiffre : le listage des agents est un
    sous-processus dont le délai est de quinze secondes. Lu sur la boucle
    d'événements, un outil qui ne répond pas fige l'écran pour quinze
    secondes — plus une touche, plus même « q ».

    `precedentes` est `{chemin: Lecture}` du tour d'avant : la reprise
    incrémentale évite de relire des mégaoctets. Le dictionnaire rendu est
    RECONSTRUIT sur le listage du moment, donc une transcription effacée
    quitte le tableau.

    `besoins` est la liste d'appels dont la commande manque encore. Elle est
    choisie par l'appelant, sur le fil de l'affichage, parce qu'elle dépend
    de ce qui est à l'écran.
    """
    lectures = {
        chemin: st.lire(chemin, precedentes.get(chemin))
        for chemin in transcriptions()
    }
    # Le journal est relu en entier : il ne pèse que quelques lignes par
    # appel d'outil, là où une transcription pèse des mégaoctets.
    evenements = jr.lire_lignes()
    appels = jr.apparier(evenements)
    # Le temps d'ATTENTION vient du journal, pas de l'horloge de session :
    # celle-ci compte aussi les heures où personne ne regardait.
    temps = jr.temps_actif(evenements) or None
    # La base d'Open Code se lit en moins d'une milliseconde. Son `export`,
    # lui, coûte presque une seconde PAR séance et se tronque : il n'a rien à
    # faire dans un écran vivant.
    seances = oc.lire_base()
    flotte = (lire_flotte or (lambda: []))() if avec_flotte else None
    commandes = {}
    for appel in besoins:
        trouve = dl.pour(appel)
        # Ni la SORTIE ni le CONTENU ne sont gardés. Le cache ne sert qu'à la
        # colonne, donc il ne retient que ce qu'elle a le droit de montrer :
        # une invite de sous-agent ou un motif de recherche y restaient en
        # mémoire pour toute la durée de la séance alors que la colonne
        # affichait « contenu » à leur place. Le volet, lui, les relit dans la
        # transcription au moment où quelqu'un les demande.
        commandes[appel.identifiant] = (
            (trouve.commande, True)
            if trouve.colonnable
            else (CONTENU_NON_GARDE if trouve.commande else "", False)
        )
    return Releve(
        lectures=lectures,
        appels=tuple(appels),
        temps=temps,
        seances=seances,
        flotte=flotte,
        commandes=commandes,
    )


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
    from textual import work
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
        #aide { height: auto; padding: 1 2; background: $panel; }
        DataTable { height: 1fr; }
        """
        # DÉRIVÉES de la table des touches, jamais recopiées : c'est la
        # recopie qui avait laissé quatre touches sans mention nulle part.
        #
        # L'ordre compte. Le pied de page tient sur UNE ligne et se coupe à
        # droite : sur quatre-vingts colonnes, une douzaine d'indications perd
        # quatre. Les cinq premières sont donc celles qui ne détruisent rien
        # et « h », qui mène à toutes les autres — une touche invisible
        # n'existe pas, sauf si une touche visible la nomme.
        BINDINGS = [
            (touche, action, t(court))
            for touche, action, court, _ in TOUCHES_AFFICHAGE + TOUCHES_LIGNE
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
            # {identifiant: (valeur, colonnable)} — lu dans les
            # transcriptions à la demande, jamais écrit nulle part, et sans
            # la sortie. Une entrée absente veut dire « pas encore cherché »,
            # une valeur vide « cherché, rien à montrer » : sans la
            # distinction, on rechercherait sans fin ce qui n'existe pas.
            self._commandes: dict = {}
            # Les colonnes actuellement posées, pour ne les refaire que
            # lorsque la largeur en change le nombre.
            self._colonnes: tuple = ()
            # Ce que le panneau modal a masqué, pour le rendre en se fermant.
            self._caches: list = []
            # Le redimensionnement arrive AVANT le montage : repeindre alors
            # remplirait des tableaux qui n'ont pas encore de colonnes.
            self._monte = False
            # La demande de relire la flotte sans attendre : un geste qui
            # lance ou arrête un agent doit se voir au tour suivant, pas trois
            # tours plus tard. La cadence ordinaire se compte en TEMPS, sur
            # une horloge monotone — celle du mur reculerait.
            self._flotte_a_relire = True
            self._flotte_apres = 0.0
            # L'horloge est un attribut pour qu'un test avance le temps sans
            # attendre. MONOTONE : celle du mur recule à un changement d'heure,
            # et la flotte cesserait d'être relue pendant tout le décalage.
            self._horloge = time.monotonic
            # La place de lecture : elle porte la GÉNÉRATION du fil qui la
            # tient, ou None quand elle est libre. Un simple booléen ne
            # suffisait pas — celui qui rend la main doit pouvoir dire si la
            # place est encore la sienne, sans quoi un relevé périmé la
            # libérerait sous un fil qui lit toujours.
            self._lecture_en_cours = None
            self._generation = 0
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
            yield Static("", id="aide")
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
            self.query_one("#aide", Static).display = False
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

            Sans effet pendant un gel non plus, et les COLONNES avec : les
            reposer vide le tableau, ce qui est pire qu'un tableau trop large.
            Le gel est là pour qu'on lise une ligne pendant que les lectures
            continuent dessous ; un coup de souris sur le bord de la fenêtre
            la remplacerait par la mesure de l'instant. Le dégel rattrape.
            """
            if not self._monte or self._gele:
                return
            self._poser_les_colonnes()
            self._peindre()

        def action_vue(self):
            """Passer au panneau suivant, en boucle.

            Le volet de détail se ferme avec le panneau qu'il détaille. Il
            montre une commande et sa sortie — le seul endroit de l'écran qui
            montre du CONTENU — et il le doit à une ligne surlignée du flux.
            Le flux parti, plus rien ne désignait ce qui restait affiché, et
            la mention qui prévient ne se rapportait plus à rien de visible.
            """
            self._vue = (self._vue + 1) % len(self.VUES)
            self._fermer_le_detail()
            self._montrer_la_vue()
            # Le gel tient ICI AUSSI. Repeindre sous un écran qui s'annonce
            # gelé refait le tableau sur la flotte fraîche, remet le curseur
            # en tête et remplace la liste peinte : « s », qui ne demande
            # aucune confirmation, partait alors sur un agent que personne
            # n'avait choisi. Les quatre panneaux ont été peints au même
            # instant, donc celui qu'on découvre porte bien l'état figé.
            if not self._gele:
                self._peindre()
            # Demander TOUT DE SUITE ce que le nouveau panneau réclame : sans
            # cela, la colonne des commandes reste en points de suspension
            # jusqu'au tour suivant, soit deux secondes après qu'on a demandé
            # à la voir.
            self._tick()

        def _montrer_la_vue(self):
            """N'afficher que le panneau courant, et LUI donner le clavier.

            Le focus n'est pas un raffinement : Textual le donne au premier
            widget focalisable, soit le tableau du haut, et un panneau caché
            sort de la chaîne de focus. Les flèches pilotaient donc le tableau
            des sessions pendant que les touches agissaient sur le panneau
            visible — dont le curseur n'avait jamais bougé. « s » arrêtait le
            premier agent quel que soit celui qu'on croyait viser, et « s »
            est justement la seule action qui ne demande rien.

            Pendant que le panneau des touches est ouvert, AUCUN tableau n'est
            affiché : il est modal. C'est ici que cela se décide, et nulle part
            ailleurs — deux endroits se contrediraient au premier « v ».
            """
            modal = self.query_one("#aide").display
            # Le tableau des sessions AUSSI : c'est un tableau, donc il
            # échappe au masquage ordinaire, et il fait à lui seul la moitié
            # de la hauteur.
            self.query_one("#tableau", DataTable).display = not modal
            courant = self.VUES[self._vue]
            for nom in self.VUES:
                table = self.query_one(f"#{nom}", DataTable)
                table.display = not modal and nom == courant
                if table.display:
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

        def action_journal(self):
            """L'écran récent de l'agent surligné, dans le VRAI terminal.

            `claude logs` n'imprime pas un journal mais un ÉCRAN : quelques
            milliers d'octets pour un agent qui a répondu un mot, dont deux
            cents séquences d'échappement, des retours chariot et AUCUN saut
            de ligne. Les positions du curseur y sont absolues, donc dépouiller
            les codes rend une seule ligne illisible, et aucun panneau de
            tableau n'y peut rien. Le seul endroit où cette sortie veut dire
            quelque chose est un terminal : l'application se suspend, l'outil
            peint, et elle reprend là où elle était.

            **Ce qui paraît là est du CONTENU** — la conversation de l'agent,
            ses commandes, ce qu'il a lu. Rien n'en est gardé : la sortie va du
            processus au terminal sans passer par nous, donc il n'y a même pas
            de quoi écrire. L'avertissement s'imprime APRÈS, avec l'invite de
            retour, parce que l'outil ouvre par un effacement d'écran et que
            tout ce qui précède est perdu.
            """
            session = self._agent_choisi()
            if session is None:
                self._dire(t("Pick a detached agent first."))
                return
            adaptateur = adaptateur_claude()
            self._montrer_dans_le_terminal(
                adaptateur.argv_action(adaptateur.JOURNAL, session.poignee)
            )

        def _montrer_dans_le_terminal(self, argv):
            """Rendre le terminal à un outil le temps qu'il peigne.

            `subprocess.run` est appelé SANS capture : la sortie va du
            processus au terminal, et nous n'en tenons jamais une copie. C'est
            la garantie qu'un contenu montré ne peut pas être écrit — il
            faudrait d'abord l'avoir.

            Un environnement sans vrai terminal — un pilote de test, un tube —
            refuse la suspension, et l'écran le dit au lieu de mourir.
            """
            import subprocess

            from textual.app import SuspendNotSupported

            try:
                with self.suspend():
                    subprocess.run(argv)
                    print()
                    print(t("Shown, not kept: nothing of this was written."))
                    input(t("Enter to go back to the screen…"))
            except SuspendNotSupported:
                self._dire(t("This terminal cannot suspend the screen."))
            except (KeyboardInterrupt, EOFError):
                # Deux gestes ordinaires pendant qu'un outil tient le
                # terminal : Ctrl+C, qui va au GROUPE de processus et donc
                # aussi à nous, et Ctrl+D à l'invite de retour. Aucun des deux
                # n'est une OSError, et sans cette branche ils remontaient
                # jusqu'à Textual, qui ferme l'application — on perdait
                # l'écran pour avoir interrompu un affichage.
                self._dire(t("Interrupted; back to the screen."))
            except OSError as souci:
                self._dire(str(souci))

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
                t("yes"),
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
                t("the identifier in full"),
                f"{t('This deletes the session and its worktree. Retype:')} "
                f"{session.session_id}",
            )

        def _ouvrir_saisie(self, attente, invite, consigne=""):
            """Ouvrir la ligne de saisie, la consigne AU-DESSUS et non dedans.

            Un « placeholder » disparaît à la première frappe. La consigne de
            suppression porte l'identifiant de trente-six caractères à
            recopier, et le tableau ne montre que la poignée de huit : une
            fois la première touche tapée, il n'était plus nulle part à
            l'écran et il fallait le restituer de mémoire. En pratique la
            suppression n'aboutissait jamais.
            """
            from textual.widgets import Input

            # Ce qu'un geste précédent avait dit ne vaut plus pour celui-ci.
            self._dire(consigne)

            # Le panneau des touches se ferme : ses chiffres et cette invite
            # se disputeraient les mêmes frappes, et un « 3 » tapé dans une
            # invite est un caractère, pas un numéro de menu.
            if self.query_one("#aide").display:
                self._fermer_l_aide()
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

        # Ce qui reste à l'écran pendant que le panneau des touches est
        # ouvert. L'en-tête situe, le pied de page porte les touches : ni l'un
        # ni l'autre ne prend de hauteur au panneau.
        GARDES_EN_MODAL = ("Header", "Footer")

        def action_aide(self):
            """Ouvrir ou fermer le panneau des touches. Il prend TOUT l'écran.

            Il existe parce que le pied de page MENT par omission : il tient
            sur une ligne, se coupe à droite, et quatre touches tombaient hors
            d'un terminal de quatre-vingts colonnes — dont les deux qui
            détruisent. Rien à l'écran ne disait qu'elles existaient.

            Modal, et pour la même raison. Empilé sous les tableaux, il
            réclamait six lignes de plus qu'un terminal de vingt-quatre n'en
            offre : ses trois dernières entrées passaient sous le pli, dont les
            deux qui détruisent, et rien ne signalait qu'il fallait défiler. Un
            panneau qu'on ouvre PARCE QU'ON NE SAIT PLUS ne peut pas cacher ce
            qu'il est là pour montrer.

            Il sert aussi de menu : un chiffre y agit sur la ligne surlignée,
            pour qui ne veut pas les apprendre. Les deux sont la même chose, et
            les séparer donnerait deux listes à tenir d'accord.
            """
            from textual.widgets import DataTable, Static

            volet = self.query_one("#aide", Static)
            if volet.display:
                self._fermer_l_aide()
                return
            volet.update(texte_de_l_aide())
            # Ce qui est masqué est DÉDUIT de ce qui est à l'écran, jamais
            # énuméré : un widget ajouté plus tard repousserait le panneau
            # sous le pli sans que personne y pense.
            self._caches = [
                widget
                for widget in self.query("Screen > *")
                if widget.display
                and widget is not volet
                and not isinstance(widget, DataTable)
                and type(widget).__name__ not in self.GARDES_EN_MODAL
            ]
            for widget in self._caches:
                widget.display = False
            volet.display = True
            # Les tableaux se cachent par la fonction qui décide de leur
            # affichage, et non ici : deux endroits qui en décideraient se
            # contrediraient au premier « v ».
            self._montrer_la_vue()

        def _fermer_l_aide(self):
            """Rendre l'écran à ce qu'il montrait avant le panneau."""
            self.query_one("#aide").display = False
            for widget in self._caches:
                widget.display = True
            self._caches = []
            self._montrer_la_vue()

        def _agir_par_le_chiffre(self, chiffre):
            """Exécuter l'action que le panneau numérote, et se refermer.

            Se refermer fait partie du geste : c'est un menu, on choisit et il
            s'efface. Le rang du chiffre EST celui de la touche dans la table,
            donc rien ne se recopie et réordonner la table réordonne le menu.
            """
            rang = CHIFFRES.index(chiffre)
            self._fermer_l_aide()
            getattr(self, f"action_{TOUCHES_LIGNE[rang][1]}")()

        def on_key(self, evenement):
            """Échap referme ce qui est ouvert ; un chiffre agit depuis l'aide.

            Les deux ne sont jamais ouverts ensemble — ouvrir la saisie ferme
            le panneau — donc l'ordre des branches ne départage rien : il dit
            seulement que la saisie est le cas le plus fréquent.
            """
            if evenement.key == "escape" and self._attente is not None:
                self._fermer_saisie()
                evenement.stop()
                return
            if evenement.key == "escape":
                # Échap ferme ce qui est ouvert, dans l'ordre où les choses se
                # sont posées : la saisie, puis le panneau, puis le volet. Le
                # volet en était exclu, et la seule façon de le refermer était
                # de retrouver « d » — qui, à quatre-vingts colonnes, ne
                # paraît pas toujours au pied de page.
                for cible, fermer in (
                    ("#aide", self._fermer_l_aide),
                    ("#detail", self._fermer_le_detail),
                ):
                    if self.query_one(cible).display:
                        fermer()
                        evenement.stop()
                        return
                return
            if not self.query_one("#aide").display:
                return
            if evenement.key in CHIFFRES:
                self._agir_par_le_chiffre(evenement.key)
                evenement.stop()

        def _lancer_agent(self, invite):
            """Lancer un agent détaché, l'invite sur l'ENTRÉE STANDARD.

            Jamais en positionnel : `/proc/<pid>/cmdline` est lisible par tout
            compte de la machine.

            Sur un FIL, comme les autres sous-processus. « L'appel rend la main
            tout de suite » était faux : `capture_output` attend la fin des
            DEUX tubes, et un agent détaché en hérite — ils ne se ferment qu'à
            sa mort. L'écran tenait donc jusqu'à deux minutes sans une touche,
            juste après qu'on lui a confié une invite.
            """
            self._dire(t("Sent, waiting for the answer…"))
            self._lancer_en_fond(invite)

        @work(thread=True)
        def _lancer_en_fond(self, invite):
            """Lancer l'agent et rapporter son identifiant, ou ce qui a raté."""
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
                self.call_from_thread(self._dire, str(souci))
                return
            identifiant = adaptateur.identifiant_lance(fini.stdout)
            self.call_from_thread(
                self._action_repondue,
                (
                    f"{t('Agent started')} {identifiant}"
                    if identifiant
                    else t("The agent did not report an identifier.")
                ),
            )

        def _lancer_action(self, sous_commande, poignee):
            """Une action sur un agent, sur un FIL comme les lectures.

            `subprocess.run` attend ici jusqu'à soixante secondes. Lancé sur la
            boucle d'événements, un outil qui ne rend pas la main figeait
            l'écran d'autant — plus une touche, plus même « q ». C'est le même
            défaut que les lectures avaient, en pire : une minute au lieu de
            quinze secondes, et sur un geste qu'on vient de demander.

            L'argv est construit AVANT et non sur le fil : un identifiant vide
            ou une sous-commande inconnue sont des refus immédiats, et les
            faire voyager pour être refusés ailleurs retarderait le seul
            message qui apprenne quelque chose.
            """
            try:
                argv = adaptateur_claude().argv_action(sous_commande, poignee)
            except ValueError as souci:
                self._dire(str(souci))
                return
            # L'écran DIT qu'il attend. Sans cela, un outil lent se lit comme
            # un geste qui n'est pas parti, et on le redonne.
            self._dire(t("Sent, waiting for the answer…"))
            self._agir_en_fond(argv)

        @work(thread=True)
        def _agir_en_fond(self, argv):
            """Lancer la sous-commande, et rapporter ce qu'elle a dit."""
            import subprocess

            try:
                fini = subprocess.run(
                    argv, text=True, capture_output=True, timeout=60
                )
            except (OSError, subprocess.SubprocessError) as souci:
                self.call_from_thread(self._dire, str(souci))
                return
            # L'outil répond « No job matching » avec un code de sortie NUL :
            # se fier au code laisserait annoncer un geste qui n'a pas eu lieu.
            premiere = (fini.stdout or fini.stderr or "").strip().splitlines()
            self.call_from_thread(
                self._action_repondue,
                premiere[0] if premiere else t("Nothing was said."),
            )

        def _action_repondue(self, message):
            """Ce que l'outil a dit, et la flotte relue sans attendre.

            Sur le fil de l'affichage : un geste qui lance ou arrête un agent
            doit se voir au tour suivant, pas six secondes plus tard.
            """
            self._dire(message)
            self._flotte_a_relire = True
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
                self._fermer_le_detail()
                return
            appel = self._appel_choisi()
            if appel is None:
                self._dire(t("Pick a tool call in the stream first."))
                return
            volet.update(texte_du_detail(appel, dl.pour(appel)))
            volet.display = True

        def _fermer_le_detail(self):
            """Fermer le volet de contenu, et OUBLIER ce qu'il portait.

            Le texte est effacé en même temps que le volet est caché : un
            widget caché garde ce qu'on lui a donné, et le rouvrir sur un
            autre appel le montrerait le temps d'une image.
            """
            from textual.widgets import Static

            volet = self.query_one("#detail", Static)
            volet.update("")
            volet.display = False

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
            """Le rafraîchissement continue dessous ; l'affichage s'arrête.

            Le dégel rattrape ce que le gel a laissé passer : la fenêtre a pu
            changer de largeur pendant l'arrêt, et le nombre de colonnes en
            dépend. Sans ce rattrapage, un écran dégelé garde les colonnes
            d'une largeur qu'il n'a plus jusqu'au redimensionnement suivant.
            """
            self._gele = not self._gele
            if self._gele:
                self._resumer()
                return
            self._poser_les_colonnes()
            self._peindre()

        def action_relire(self):
            """Tout relire depuis le début, quand un doute vient sur un total.

            La relecture coûte plus d'une seconde sur une machine qui porte
            quatre cents mégaoctets de transcriptions. Elle se fait sur le
            fil, donc l'écran répond pendant ce temps — mais il montre encore
            les chiffres d'avant, et il le DIT plutôt que de laisser croire
            que le total affiché est déjà le nouveau.

            Le relevé d'un fil qui lisait encore le monde d'avant est jeté :
            c'est à cela que sert la génération.
            """
            self._dire(t("Reading everything again…"))
            self._generation += 1
            self._lectures = {}
            self._commandes = {}
            self._flotte_a_relire = True
            # Le drapeau n'est PAS rabaissé : il appartient au fil qui lit
            # encore, et le baisser ouvrirait un second fil par-dessus. Une
            # touche maintenue en ouvrait un par frappe, chacun relisant tout
            # depuis zéro et lançant son propre sous-processus. Le fil en vol
            # rendra la main, son relevé sera jeté par la génération, et le
            # tour suivant repartira du monde vide.
            self._tick()

        def _tick(self):
            """Demander une lecture au fil d'arrière-plan, et rendre la main.

            RIEN n'est lu ici. Tout ce que ce tour coûte — deux cent trente
            millisecondes sur une machine de dix-neuf sessions et sept mille
            appels, davantage quand la flotte se relit — se paie sur un fil,
            pas sur la boucle d'événements. Le chiffre qui tranche n'est pas
            la moyenne mais la queue : le listage des agents est un
            sous-processus dont le délai est de quinze secondes, et un outil
            qui ne répond pas figeait l'écran d'autant, « q » compris.
            """
            if self._lecture_en_cours is not None:
                # Un tour qui tombe pendant une lecture est SAUTÉ, et non mis
                # en file : sur une machine lente, la file grandirait sans
                # qu'aucun tour ne montre jamais l'état du moment.
                return
            self._lecture_en_cours = self._generation
            maintenant = self._horloge()
            avec_flotte = (
                self._flotte_a_relire or maintenant >= self._flotte_apres
            )
            if avec_flotte:
                # La cadence de la flotte se compte en TEMPS et non en tours :
                # les tours s'enchaînent en rafale tant que la colonne des
                # commandes se remplit, et un compteur de tours lancerait
                # alors un sous-processus toutes les trois rafales.
                self._flotte_apres = maintenant + PAS * PAS_FLOTTE
                self._flotte_a_relire = False
            self._lire_en_fond(
                self._generation,
                dict(self._lectures),
                self._besoins(),
                avec_flotte,
            )

        def _besoins(self):
            """Les appels dont la commande manque encore, et rien de plus.

            Choisis ICI, sur le fil de l'affichage, parce que la réponse
            dépend du panneau visible : on ne paie que ce qu'on regarde.
            Quelques-uns par relevé, parce qu'une recherche coûte quarante
            millisecondes — la colonne se remplit par vagues, chaque vague
            en demandant une autre tant qu'il en manque.
            """
            if self.VUES[self._vue] != "flux":
                return []
            manquants = [
                a
                for a in sorted(self._appels, key=lambda x: -x.debut_ms)[
                    :FLUX_MAX
                ]
                if a.identifiant and a.identifiant not in self._commandes
            ]
            return manquants[:DETAILS_PAR_TOUR]

        @work(thread=True)
        def _lire_en_fond(self, generation, lectures, besoins, avec_flotte):
            """Le fil : il LIT, et ne touche à rien de ce qui est affiché.

            L'exception est rattrapée ici parce qu'un fil qui meurt ne prévient
            personne : le drapeau resterait levé et l'écran cesserait de se
            rafraîchir, sans un mot.
            """
            try:
                releve = relever(
                    lectures,
                    besoins=besoins,
                    avec_flotte=avec_flotte,
                    lire_flotte=self._lire_flotte,
                )
            except Exception as souci:
                self.call_from_thread(
                    self._lecture_a_echoue, generation, str(souci)
                )
                return
            self.call_from_thread(self._appliquer, generation, releve)

        def _appliquer(self, generation, releve):
            """Poser le relevé sur l'écran. Toujours sur le fil de l'affichage.

            Deux choses, et elles ne se décident pas pareil. La PLACE se rend
            à celui qui la tenait, périmé ou non : la lui refuser arrêtait le
            rafraîchissement pour de bon dès qu'un « r » croisait une lecture.
            Le RELEVÉ, lui, est jeté s'il décrit le monde d'avant « r » —
            l'appliquer ressusciterait ce qu'on venait d'oublier — et le tour
            que « r » voulait est redemandé aussitôt.
            """
            if generation == self._lecture_en_cours:
                self._lecture_en_cours = None
            if generation != self._generation:
                self._tick()
                return
            self._lectures = releve.lectures
            self._appels = list(releve.appels)
            self._temps = releve.temps
            self._seances = releve.seances
            if releve.flotte is not None:
                self._flotte = releve.flotte
                self._agents = agents_detaches(releve.flotte)
            self._commandes.update(releve.commandes)
            if not self._gele:
                self._peindre()
            if self._besoins():
                # La vague suivante, tout de suite : sur un fil, remplir la
                # colonne en une seconde ne coûte plus rien à l'écran.
                self._tick()

        def _lecture_a_echoue(self, generation, message):
            """Une lecture qui a levé le dit, et le rafraîchissement reprend.

            La place se rend comme elle se rend après un relevé : un fil qui
            meurt sans la libérer arrête l'écran sans un mot.
            """
            if generation == self._lecture_en_cours:
                self._lecture_en_cours = None
            if generation != self._generation:
                return
            self._dire(message)

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

            Une clé en double ne ferme PAS l'écran. `add_row` lève
            `DuplicateKey`, et une exception dans un gestionnaire de message
            ferme l'application entière : la rangée suivante n'est pas la
            seule perdue, tout l'est. Le doublon est donc désambiguïsé par son
            rang, au prix du curseur sur cette rangée-là. C'est un filet :
            chaque faiseuse de lignes rend une clé qui identifie, distincte
            des colonnes qui décrivent.
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
            vues = set()
            for rang, ligne in enumerate(lignes):
                marque = str(ligne[cle])
                if marque in vues:
                    marque = f"{marque}#{rang}"
                vues.add(marque)
                table.add_row(*[ligne[c] for c, _ in colonnes], key=marque)
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
                "cle",
            )
            outils = self.query_one("#outils", DataTable)
            groupes = jr.par_outil(self._appels)
            self._repeindre(
                outils, lignes_outils(groupes), COLONNES_OUTILS, "cle"
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
                "cle",
            )
            agents = self.query_one("#agents", DataTable)
            self._agents_peints = list(self._agents)
            self._repeindre(
                agents, lignes_agents(self._agents), COLONNES_AGENTS, "cle"
            )
            self.query_one("#titre_outils", Static).update(
                self._titre_du_panneau(groupes)
            )
            self._resumer()

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
            # Le coût et les durées d'outils viennent d'un `cost-state`, et
            # `somme` ne rapporte pas le compte de segments — il n'a pas de
            # sens agrégé. La question se repose donc ici : une seule session
            # qui en porte un suffit à rendre le total mesuré. Sans aucune,
            # l'en-tête annonçait « 0.00 $ · 0 ms » au-dessus de rangées qui
            # disent toutes « — » pour la même absence.
            mesure = any(l.agregat.segments for l in self._lectures.values())
            self.query_one("#resume", Static).update(
                f"{ICONES['claude']} {compte} {t('sessions')} · "
                f"{t('prompt')} {jetons(total.entree + total.cache_lu + total.cache_cree)}"
                f" · {t('output')} {jetons(total.sortie)}"
                f" · {t('thinking')} {jetons(total.reflexion)}"
                f" · {t('cost')} {_mesure(mesure, lambda _: f'{total.cout:.2f} $', 0)}"
                f" · {t('tools')} {_mesure(mesure, duree, total.duree_outils)}"
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
