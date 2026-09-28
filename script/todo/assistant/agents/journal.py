#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le journal des appels d'outils : une ligne par événement, et leur appariement.

Ce que le disque ne dit pas et que ce journal apporte : QUEL outil, combien de
fois, et combien de temps chacun. Une transcription porte `totalToolDuration`,
un agrégat — elle dit dix-neuf minutes sans jamais dire que Bash en prend les
trois quarts.

**La durée s'obtient par appariement, jamais d'un seul événement.** Aucun
événement de hook ne porte de durée : `PostToolUse` reçoit la réponse de
l'outil, pas le temps qu'il a mis. Deux événements sont donc écrits, avant et
après, et leur `tool_use_id` les recoud. Un appel dont l'après manque — un
outil interrompu, un agent tué — reste NON APPARIÉ, et se compte comme tel
plutôt que de se voir attribuer une durée inventée.

**Une ligne par événement, jamais un document réécrit.** Un journal réécrit à
chaque appel se corrompt dès que deux sessions écrivent en même temps, et
plusieurs sessions tournent toujours. Un ajout d'une ligne est atomique tant
qu'il tient dans un tampon de tuyau, et une lecture partielle d'un fichier de
lignes reste valide : la dernière ligne, coupée, est simplement sautée.

**Rien de tout cela ne va dans le dépôt.** Le journal vit sous
`~/.erplibre/agents/`, un fichier par jour, et les fichiers plus vieux que la
rétention sont retirés. Le dépôt ne porte ni trace d'exécution ni horodatage.
"""
from __future__ import annotations

import json
import os
import statistics
import time
from dataclasses import dataclass

# Où le journal vit. Le dépôt écrit déjà sa télémétrie de navigation sous
# « ~/.erplibre » : les agents prennent un sous-répertoire du même endroit.
RACINE = "~/.erplibre/agents"

# Combien de jours de journal sont gardés. Deux semaines couvrent la question
# à laquelle ce journal répond — quel outil a mangé le quota de la semaine —
# sans laisser le répertoire grossir sans fin.
RETENTION_JOURS = 14

# Les événements écrits. `PreToolUse` n'est pas là pour bloquer quoi que ce
# soit — il ne sert qu'à porter l'instant de départ, sans quoi aucune durée ne
# se calcule.
EVENEMENTS = (
    "PreToolUse",
    "PostToolUse",
    "PostToolUseFailure",
    "UserPromptSubmit",
    "SubagentStart",
    "SubagentStop",
    "PreCompact",
    "SessionEnd",
)

# Ce qui est retenu d'un événement. `tool_input` et `tool_response` n'y sont
# PAS : le premier porte la commande bash ou le contenu d'une édition, le
# second la sortie de l'outil. Le journal compte des appels, il ne recopie pas
# ce qu'ils disent.
CHAMPS = ("hook_event_name", "session_id", "tool_name", "tool_use_id", "cwd")

# Les champs NUMÉRIQUES et BOOLÉENS de la charge, gardés à part parce qu'un
# filtre à chaînes les écarte tous en silence — le défaut que le module voisin
# a déjà payé sur le code de sortie d'un hook. `duration_ms` est la durée que
# l'outil rapporte lui-même ; `is_interrupt` sépare une interruption d'un
# échec, deux issues que rien d'autre ne distingue.
CHAMPS_NOMBRE = ("duration_ms",)
CHAMPS_BOOLEEN = ("is_interrupt",)

# Les issues d'un appel d'outil. Les quatre sont distinctes à l'écran parce
# qu'elles n'appellent pas le même geste : un outil refusé se réautorise, un
# outil interrompu se relance, un outil en échec se corrige, et un appel sans
# fin connue ne dit rien du tout.
FINI = "fini"
ECHOUE = "echoue"
INTERROMPU = "interrompu"
INACHEVE = "inacheve"


def chemin_du_jour(*, racine=None, horloge=None) -> str:
    """Le fichier du jour, chemin absolu. Ne crée rien."""
    horloge = horloge or time.time
    jour = time.strftime("%Y-%m-%d", time.localtime(horloge()))
    return os.path.join(os.path.expanduser(racine or RACINE), f"{jour}.jsonl")


def fichiers(*, racine=None, lister=None) -> list[str]:
    """Les journaux présents, du plus ancien au plus récent."""
    import glob

    lister = lister or glob.glob
    motif = os.path.join(os.path.expanduser(racine or RACINE), "*.jsonl")
    return sorted(lister(motif))


def nettoyer(
    *, racine=None, jours=None, horloge=None, lister=None, retirer=None
):
    """Retirer les journaux plus vieux que la rétention. Rend leurs noms.

    Le nom de fichier porte la date, donc la décision ne demande pas de lire
    le contenu ni de faire confiance à l'horodatage du système de fichiers —
    qu'une copie ou une restauration remet à l'heure de la copie.
    """
    jours = RETENTION_JOURS if jours is None else jours
    horloge = horloge or time.time
    retirer = retirer or os.remove
    limite = time.strftime(
        "%Y-%m-%d", time.localtime(horloge() - jours * 86400)
    )
    retires = []
    for chemin in fichiers(racine=racine, lister=lister):
        jour = os.path.basename(chemin)[: -len(".jsonl")]
        if jour < limite:
            try:
                retirer(chemin)
                retires.append(chemin)
            except OSError:
                pass
    return retires


@dataclass(frozen=True)
class Appel:
    """Un appel d'outil recousu : son nom, sa durée, et comment il s'est fini.

    `duree_ms` vaut None quand rien ne la donne. Zéro dirait « instantané » là
    où l'on ne sait pas, et c'est la différence qui compte : un outil tué en
    plein vol ne doit pas se lire comme un outil rapide.

    `issue` distingue quatre fins que rien d'autre ne sépare — fini, échoué,
    interrompu, et inachevé quand aucun événement de clôture n'est venu. Les
    confondre en un seul compte donne un écran qui dit « inachevé » pour trois
    situations dont aucune n'appelle le même geste.
    """

    outil: str
    session: str
    debut_ms: int
    duree_ms: int | None = None
    issue: str = FINI
    # La clé qui mène à la transcription : le même identifiant y nomme le
    # bloc `tool_use` et son `tool_result`. Le journal ne garde ni la commande
    # ni sa sortie — il garde de quoi les RETROUVER, ce qui n'est pas pareil.
    identifiant: str = ""


def _duree(ferme, depart) -> int | None:
    """La durée d'un appel : celle que l'outil A MESURÉE, sinon l'écart.

    `duration_ms` est portée par l'événement de clôture et vaut mieux que la
    soustraction des deux instants : cet écart INCLUT le temps passé devant
    une demande d'autorisation, donc un appel approuvé au bout de quatre
    minutes se lirait comme un appel de quatre minutes.
    """
    mesuree = ferme.get("duration_ms")
    if isinstance(mesuree, int) and not isinstance(mesuree, bool):
        return max(0, mesuree)
    return max(0, int(ferme.get("ts") or 0) - int(depart.get("ts") or 0))


def apparier(lignes) -> list[Appel]:
    """Recoudre les paires avant/après par `tool_use_id`. Fonction PURE.

    Prend des dictionnaires déjà décodés, dans l'ordre du journal. Deux
    événements ferment un appel : `PostToolUse` le finit, `PostToolUseFailure`
    le fait échouer — et son `is_interrupt` sépare l'interruption de l'échec.
    Un `Pre` que rien ne ferme rend un appel INACHEVÉ, de durée inconnue ; un
    événement de clôture sans `Pre` — le cas d'un journal posé au milieu d'une
    session — est ignoré, faute d'instant de départ.
    """
    debuts = {}
    appels = []
    for ligne in lignes:
        if not isinstance(ligne, dict):
            continue
        cle = ligne.get("tool_use_id")
        genre = ligne.get("hook_event_name")
        if not cle:
            continue
        if genre == "PreToolUse":
            debuts[cle] = ligne
        elif genre in ("PostToolUse", "PostToolUseFailure"):
            depart = debuts.pop(cle, None)
            if depart is None:
                continue
            if genre == "PostToolUse":
                issue = FINI
            elif ligne.get("is_interrupt") is True:
                issue = INTERROMPU
            else:
                issue = ECHOUE
            appels.append(
                Appel(
                    outil=depart.get("tool_name") or "",
                    session=depart.get("session_id") or "",
                    debut_ms=int(depart.get("ts") or 0),
                    duree_ms=_duree(ligne, depart),
                    issue=issue,
                    identifiant=str(cle),
                )
            )
    for reste in debuts.values():
        appels.append(
            Appel(
                outil=reste.get("tool_name") or "",
                session=reste.get("session_id") or "",
                debut_ms=int(reste.get("ts") or 0),
                duree_ms=None,
                issue=INACHEVE,
                identifiant=str(reste.get("tool_use_id") or ""),
            )
        )
    return sorted(appels, key=lambda a: a.debut_ms)


@dataclass(frozen=True)
class ParOutil:
    """Ce qu'un outil a coûté : combien d'appels, et la médiane de leur durée.

    La MÉDIANE et non la moyenne : un seul appel de neuf secondes au milieu de
    trois cents appels de quarante millisecondes déplace la moyenne et ne dit
    rien de l'ordinaire. La pointe est donnée à côté, qui est ce qui surprend.

    Les trois façons de mal finir sont comptées SÉPARÉMENT. Un outil en échec
    se corrige, un outil interrompu se relance, un appel dont aucune clôture
    n'est venue ne dit rien du tout — les additionner en un seul compte donne
    un écran qui affiche « inachevé » pour trois situations sans rapport.
    """

    outil: str
    appels: int = 0
    mediane_ms: int = 0
    pointe_ms: int = 0
    inacheves: int = 0
    echoues: int = 0
    interrompus: int = 0


def par_outil(appels) -> list[ParOutil]:
    """Grouper par outil, le plus appelé d'abord. Fonction PURE."""
    groupes = {}
    for appel in appels:
        groupes.setdefault(appel.outil, []).append(appel)
    sorties = []
    for outil, liste in groupes.items():
        durees = sorted(a.duree_ms for a in liste if a.duree_ms is not None)
        # La vraie médiane, moyenne des deux valeurs centrales sur un compte
        # pair : prendre la plus haute des deux ferait lire « médiane 9 s » sur
        # deux appels de 0,4 et 9 secondes, ce qui est la pointe et non
        # l'ordinaire. Les appels inachevés ne pèsent pas — ils n'ont pas de
        # durée — mais ils restent comptés dans `appels`.
        milieu = int(statistics.median(durees)) if durees else 0
        sorties.append(
            ParOutil(
                outil=outil,
                appels=len(liste),
                mediane_ms=milieu,
                pointe_ms=durees[-1] if durees else 0,
                inacheves=sum(1 for a in liste if a.issue == INACHEVE),
                echoues=sum(1 for a in liste if a.issue == ECHOUE),
                interrompus=sum(1 for a in liste if a.issue == INTERROMPU),
            )
        )
    return sorted(sorties, key=lambda p: (-p.appels, p.outil))


# Au-delà de ce silence entre deux événements, ce n'est plus du travail mais
# une absence : la session est restée ouverte pendant qu'on faisait autre
# chose. Le seuil est un CHOIX de ce paquet et non une mesure — cinq minutes
# est ce qu'emploient les outils de suivi de temps pour la même question. Le
# dire importe plus que la valeur : sans coupure, une session ouverte trois
# jours compte trois jours.
INACTIVITE_MS = 5 * 60 * 1000


def lire_lignes(*, racine=None, lister=None, lire_texte=None) -> list[dict]:
    """Les événements des journaux présents, décodés, dans l'ordre du disque.

    Séparé de l'appariement parce que TOUS les événements portent un instant,
    là où seuls `PreToolUse` et `PostToolUse` se recousent en appels. Le temps
    passé se lit sur les premiers et serait amputé sur les seconds.

    Une ligne illisible est sautée : un journal en cours d'écriture finit sur
    une ligne coupée, et le hook d'une session qui travaille écrit pendant
    qu'on lit.
    """
    if lire_texte is None:

        def lire_texte(chemin):
            with open(chemin, encoding="utf-8", errors="replace") as fh:
                return fh.read()

    lignes = []
    for chemin in fichiers(racine=racine, lister=lister):
        try:
            texte = lire_texte(chemin)
        except OSError:
            continue
        for brute in texte.splitlines():
            brute = brute.strip()
            if not brute:
                continue
            try:
                decodee = json.loads(brute)
            except (ValueError, TypeError):
                continue
            if isinstance(decodee, dict):
                lignes.append(decodee)
    return lignes


def temps_actif(lignes, *, seuil_ms=None) -> dict:
    """{session: millisecondes travaillées} — le temps d'ATTENTION.

    Fonction PURE. Somme les écarts entre événements consécutifs d'une même
    session, chaque écart BORNÉ par le seuil d'inactivité. C'est ce qui
    sépare le temps passé du temps écoulé, et les deux ne se ressemblent pas :
    une horloge de session annonce des centaines d'heures dès qu'une session
    reste ouverte plusieurs jours, ce qui n'est pas du travail.

    Une session d'un seul événement rend zéro : on sait qu'elle a existé, pas
    combien de temps elle a duré. Zéro est ici une mesure et non une absence —
    il n'y a aucun intervalle à mesurer.
    """
    seuil = INACTIVITE_MS if seuil_ms is None else seuil_ms
    par_session: dict = {}
    for ligne in lignes:
        if not isinstance(ligne, dict):
            continue
        session = ligne.get("session_id")
        instant = ligne.get("ts")
        if not session or not isinstance(instant, int):
            continue
        par_session.setdefault(session, []).append(instant)
    totaux = {}
    for session, instants in par_session.items():
        instants.sort()
        totaux[session] = sum(
            min(max(0, apres - avant), seuil)
            for avant, apres in zip(instants, instants[1:])
        )
    return totaux


def lire(*, racine=None, lister=None, lire_texte=None) -> list[Appel]:
    """Tous les appels des journaux présents, appariés."""
    return apparier(
        lire_lignes(racine=racine, lister=lister, lire_texte=lire_texte)
    )
