#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les sessions Claude Code de la machine : lesquelles vivent, lesquelles
se reprennent.

Ce module ne fait que LISTER. Construire la ligne de commande qui interroge
une session appartient à `backends.py`, qui garde l'invite hors de l'argv et
impose la lecture seule par des drapeaux.

**Deux sources, et la première fait autorité.** `claude agents --json` est le
listage que l'outil publie ; il n'exige pas de terminal et rend pid,
répertoire, genre, identifiant, nom et état. Le registre par processus, sous
le répertoire de configuration, y ajoute la version et le moment de démarrage.
Un `claude -p` en cours n'est dans NI l'un NI l'autre : seules les sessions
interactives et d'arrière-plan s'y inscrivent, donc l'absence d'une session
de la liste ne prouve pas qu'aucune ne tourne.

**Un pid ne suffit pas à dire qu'une session vit.** Les pids se recyclent, et
une entrée laissée par un arrêt brutal désignerait alors le processus d'un
autre. Le registre porte le moment de démarrage du processus ; la vivacité se
prouve donc par pid vivant ET démarrage identique, jamais par le pid seul.

**Ce que l'affichage a le droit de montrer.** Le registre est lisible par tout
compte de la machine — pid, répertoire, nom, identifiant n'y sont donc pas des
secrets. Les TRANSCRIPTIONS, elles, sont sous un répertoire fermé à leur
propriétaire seul, et c'est une frontière que le système a déjà tracée : ni
titre, ni invite, ni message n'en sort ici. Un transcript n'est lu que pour
deux champs de STRUCTURE — le répertoire de travail et la branche git — parce
que le nom du répertoire qui les contient est une transformation à perte : les
séparateurs, les points et les tirets bas y deviennent tous des tirets, donc
deux dépôts voisins s'y confondent.

**Une transcription ne se charge jamais en entier.** La plus grosse de cette
machine se compte en dizaines de mégaoctets ; seules les premières lignes sont
lues, et le listage se garde de les relire à chaque affichage.
"""
from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass, replace
from pathlib import Path

# Le listage que l'outil publie. Sans terminal, il refuse sa forme lisible et
# renvoie explicitement vers celle-ci, qui est donc la seule utilisable ici.
AGENTS_ARGV = ("claude", "agents", "--json")

# Le registre des processus vivants, un fichier par pid.
REGISTRE = "~/.claude/sessions"

# Les transcriptions persistées, un répertoire par projet.
PROJETS = "~/.claude/projects"

# Le champ de « /proc/<pid>/stat » qui porte le moment de démarrage, compté
# depuis le premier. C'est lui qui distingue un pid recyclé d'un pid vivant.
CHAMP_DEMARRAGE = 22

# Ce que le listage lit dans une transcription, et rien d'autre : deux champs
# de structure. Le contenu des messages n'est pas de ce côté-ci de la
# frontière que le système a posée sur le répertoire.
CHAMPS_TRANSCRIPT = ("cwd", "gitBranch")

# Le nombre de lignes lues en tête d'une transcription pour y trouver ces deux
# champs. Les premiers enregistrements les portent tous ; en lire plus
# coûterait des mégaoctets pour la même réponse.
LIGNES_EN_TETE = 40

# Le délai d'un appel au listage. Il borne l'attente si l'outil est absent ou
# occupé, pour que le menu rende la main.
DELAI = 15


@dataclass(frozen=True)
class Session:
    """Une session, telle que le registre l'annonce.

    `live` dit qu'un processus la tient EN CE MOMENT, prouvé par son moment
    de démarrage et non par son seul pid. `kind` vaut `interactive` ou
    `background`, et cette distinction décide du risque : reprendre une
    session tenue par un terminal n'est pas refusé par l'outil, là où une
    session d'arrière-plan l'est.
    """

    session_id: str
    pid: int = 0
    kind: str = ""
    status: str = ""
    cwd: str = ""
    name: str = ""
    version: str = ""
    branch: str = ""
    live: bool = False
    court: str = ""

    @property
    def poignee(self) -> str:
        """L'identifiant que les sous-commandes d'arrière-plan ACCEPTENT.

        Le listage porte deux identifiants pour un agent détaché : `id`, court,
        et `sessionId`, l'UUID complet. Les cinq sous-commandes — logs, attach,
        stop, respawn, rm — ne prennent QUE le court : passer l'UUID rend « No
        job matching », et avec un code de sortie NUL, donc sans qu'aucun
        appelant ne le voie échouer.

        Un listage qui ne porte pas `id` retombe sur le préfixe de l'UUID,
        qui est la forme que l'outil imprime aujourd'hui.
        """
        return self.court or self.session_id[:8]


def live(*, run=None, read_registry=None, read_stat=None) -> list[Session]:
    """Les sessions qu'un processus tient en ce moment.

    `run(argv)` rend le texte du listage, `read_registry()` les entrées du
    registre, `read_stat(pid)` le contenu de l'état d'un processus : les trois
    coutures permettent à un test de décrire une flotte entière sans qu'aucune
    session réelle ne soit lue ni dérangée.

    Rend None quand l'outil n'a pas RÉPONDU, et une liste vide quand il a
    répondu qu'aucune session ne tourne. Une machine sans Claude Code n'est
    pas une panne du menu, mais elle n'est pas non plus une machine où rien ne
    tourne : l'appelant qui protège un geste destructeur a besoin des deux.
    """
    lanceur = run or _lancer
    brutes = _agents(lanceur)
    if brutes is None:
        return None
    entrees = (read_registry or _lire_registre)()
    par_pid = {int(e.get("pid", 0) or 0): e for e in entrees}
    trouvees = []
    for brute in brutes:
        pid = int(brute.get("pid", 0) or 0)
        enrichie = par_pid.get(pid, {})
        vivante = is_live(pid, enrichie.get("procStart"), read_stat=read_stat)
        trouvees.append(
            Session(
                session_id=str(brute.get("sessionId") or ""),
                court=str(brute.get("id") or ""),
                pid=pid,
                kind=str(brute.get("kind") or ""),
                status=str(brute.get("status") or ""),
                cwd=str(brute.get("cwd") or ""),
                name=str(brute.get("name") or ""),
                version=str(enrichie.get("version") or ""),
                live=vivante,
            )
        )
    return trouvees


def is_live(pid, procstart, *, read_stat=None) -> bool:
    """Ce pid porte-t-il TOUJOURS la session que le registre y attachait ?

    Un pid vivant ne suffit pas : les pids se recyclent, et une entrée laissée
    par un arrêt brutal désignerait le processus d'un autre. Le moment de
    démarrage du processus tranche — il est propre à un démarrage, donc un pid
    réattribué ne le porte pas.

    Sans moment de démarrage connu, la réponse est la présence du pid : c'est
    ce que le listage de l'outil affirme déjà, et le prétendre mort serait
    plus faux que de le croire vivant.
    """
    lecteur = read_stat or _lire_stat
    contenu = lecteur(pid)
    if not contenu:
        return False
    if procstart in (None, ""):
        return True
    champs = contenu.rsplit(")", 1)[-1].split()
    # Le champ compté depuis le premier, et le nom du programme — qui peut
    # contenir des espaces — est déjà écarté par la coupe ci-dessus.
    rang = CHAMP_DEMARRAGE - 3
    if rang >= len(champs):
        return True
    return champs[rang] == str(procstart)


def resumable(*, projects_root=None, read_head=None) -> list[Session]:
    """Les sessions persistées, reprenables et sans processus.

    Le répertoire de travail se LIT dans la transcription, jamais dans le nom
    du répertoire qui la contient : cette transformation remplace les
    séparateurs, les points et les tirets bas par des tirets, donc elle ne
    s'inverse pas et confondrait deux dépôts voisins.

    Deux champs sont lus, et deux seulement — le répertoire et la branche.
    Aucun titre, aucune invite, aucun message : la transcription est sous un
    répertoire que le système ferme à son propriétaire, et cette frontière
    n'est pas à rouvrir pour décorer une liste.
    """
    racine = Path(projects_root or os.path.expanduser(PROJETS))
    lecteur = read_head or _lire_en_tete
    trouvees = []
    for chemin in _transcripts(racine):
        faits = _structure(lecteur(chemin))
        trouvees.append(
            Session(
                session_id=chemin.name[: -len(".jsonl")],
                cwd=faits.get("cwd", ""),
                branch=faits.get("gitBranch", ""),
                live=False,
            )
        )
    return sorted(trouvees, key=lambda s: s.session_id)


def fleet(
    *,
    run=None,
    read_registry=None,
    read_stat=None,
    projects_root=None,
    read_head=None,
) -> list[Session]:
    """La flotte : les sessions vivantes, puis celles qui se reprennent.

    Une session persistée est aussi présente tant qu'un processus la tient :
    les deux listages se recouvrent donc, et les présenter côte à côte
    montrerait deux fois la même session, une fois vivante et une fois comme
    reprenable. La fusion garde l'entrée VIVANTE, qui porte le pid, le genre
    et l'état — c'est-à-dire tout ce qui décide du risque.

    Les vivantes ouvrent la liste : ce sont celles où écrire coûte quelque
    chose.
    """
    persistees = {
        session.session_id: session
        for session in resumable(
            projects_root=projects_root, read_head=read_head
        )
    }
    # La branche vient de la transcription, que le listage de l'outil ne
    # connaît pas : sans cette reprise, elle paraîtrait pour les sessions
    # dormantes et manquerait pour les vivantes, ce qui se lit comme un
    # défaut alors que l'information est là.
    # La flotte rend TOUJOURS une liste : elle sert à montrer, et une
    # transcription reste une transcription même sans listage. Ce qui se perd
    # alors est la VIVACITÉ, et `live()` est là pour qui en a besoin.
    trouvees = live(run=run, read_registry=read_registry, read_stat=read_stat)
    vivantes = [
        replace(
            session,
            branch=getattr(persistees.get(session.session_id), "branch", ""),
        )
        for session in trouvees or ()
    ]
    connues = {session.session_id for session in vivantes}
    dormantes = [
        session
        for identifiant, session in persistees.items()
        if identifiant not in connues
    ]
    return vivantes + dormantes


def displayable(session) -> dict:
    """Ce qu'une session a le droit de montrer à l'écran.

    Le répertoire est réduit à son dernier segment et l'identifiant à son
    préfixe : les deux suffisent à reconnaître une session sans étaler le
    chemin d'un compte, que le détecteur du dépôt compte d'ailleurs parmi les
    données identifiantes.
    """
    return {
        "id": session.session_id[:8],
        "pid": session.pid,
        "kind": session.kind,
        "status": session.status,
        "dir": Path(session.cwd).name if session.cwd else "",
        "name": session.name,
        "version": session.version,
        "branch": session.branch,
        "live": session.live,
    }


def held_by(session) -> str:
    """Le pid qui tient cette session, ou "" quand personne ne la tient.

    Sert la seule question qui compte avant d'écrire dans une session : y
    a-t-il quelqu'un dedans. Reprendre une session tenue par un terminal n'est
    PAS refusé par l'outil, et deux écritures simultanées scindent la
    transcription en silence — une branche est alors orpheline. Le menu
    demande donc, et branche une copie par défaut.
    """
    return str(session.pid) if session.live and session.pid else ""


def _agents(lanceur):
    """Les entrées du listage, ou None quand l'outil n'a pas RÉPONDU.

    None et la liste vide disent le contraire l'un de l'autre : le premier est
    « la question n'a pas abouti » — binaire absent, compte déconnecté,
    version qui ignore la sous-commande, délai dépassé, sortie qui n'est pas
    du JSON —, le second « aucune session ne tourne ».

    Les confondre fait tomber en OUVERT la garde qui protège l'écran de
    ménage : sans session vivante connue, tout historique devient supprimable,
    y compris celui de la session qui écrit en ce moment.
    """
    texte = lanceur(list(AGENTS_ARGV))
    if not texte:
        return None
    try:
        charge = json.loads(texte)
    except ValueError:
        return None
    if not isinstance(charge, list):
        return None
    return [e for e in charge if isinstance(e, dict)]


def _lancer(argv):
    """La sortie standard du listage, ou "" quand l'outil manque."""
    try:
        answer = subprocess.run(
            argv, capture_output=True, text=True, timeout=DELAI
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return answer.stdout if answer.returncode == 0 else ""


def _lire_registre():
    """Les entrées du registre des processus vivants.

    Les fichiers de jetons voisins ne sont jamais ouverts : ils portent une
    autorisation de messagerie, et ce listage n'a rien à en faire.
    """
    racine = Path(os.path.expanduser(REGISTRE))
    entrees = []
    try:
        fichiers = sorted(racine.glob("*.json"))
    except OSError:
        return entrees
    for chemin in fichiers:
        try:
            entrees.append(json.loads(chemin.read_text()))
        except (OSError, ValueError):
            # Un registre à moitié écrit ne doit pas cacher les autres.
            continue
    return [e for e in entrees if isinstance(e, dict)]


def _lire_stat(pid):
    """Le contenu de l'état d'un processus, ou "" s'il n'existe plus."""
    try:
        return Path(f"/proc/{int(pid)}/stat").read_text()
    except (OSError, ValueError):
        return ""


def _transcripts(racine):
    """Les transcriptions persistées, triées, sans descendre plus bas.

    Les sous-répertoires par session portent des travaux dérivés — agents,
    flux — que ce listage n'a pas à parcourir.
    """
    try:
        return sorted(
            chemin
            for projet in sorted(racine.iterdir())
            if projet.is_dir()
            for chemin in sorted(projet.glob("*.jsonl"))
        )
    except OSError:
        return []


def _lire_en_tete(chemin):
    """Les premières lignes d'une transcription.

    En tête seulement : une transcription se compte en mégaoctets, et les
    premiers enregistrements portent déjà les deux champs cherchés.
    """
    lignes = []
    try:
        with open(chemin, encoding="utf-8", errors="replace") as fichier:
            for rang, ligne in enumerate(fichier):
                if rang >= LIGNES_EN_TETE:
                    break
                lignes.append(ligne)
    except OSError:
        return []
    return lignes


def _structure(lignes):
    """Les deux champs de structure, pris dans les premiers enregistrements.

    Ne lit que les clés déclarées : un enregistrement porte aussi le contenu
    des messages, et le parcourir pour en extraire deux champs ne donne aucun
    droit sur le reste.
    """
    faits = {}
    for ligne in lignes or ():
        try:
            enregistrement = json.loads(ligne)
        except ValueError:
            continue
        if not isinstance(enregistrement, dict):
            continue
        for champ in CHAMPS_TRANSCRIPT:
            valeur = enregistrement.get(champ)
            if champ not in faits and isinstance(valeur, str) and valeur:
                faits[champ] = valeur
        if len(faits) == len(CHAMPS_TRANSCRIPT):
            break
    return faits
