#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les conversations gardées : où elles s'écrivent, et comment on les reprend.

Une séance s'écrit AU FIL, un tour par ligne, et non à la fermeture. Une
conversation se termine rarement par la porte : on ferme le terminal, on perd
la connexion, on interrompt. Ce qui n'est écrit qu'à la sortie n'est écrit
presque jamais, et l'écriture continue coûte une ligne par tour là où un
modèle en met plusieurs secondes à répondre.

**Le fichier vit hors du dépôt.** `~/.erplibre/assistant/sessions/`, en 0700
pour le dossier et 0600 pour les fichiers, comme ce que `/save` y écrit déjà.
Une conversation porte ce que la personne y a tapé : le dépôt suit du code, et
`private/` lui-même devient public avec un fork public.

**Le nom porte la DATE et l'identifiant de séance.** La date pour que la liste
se trie et se lise ; l'identifiant pour que deux séances ne se marchent jamais
dessus. Un nom tiré du seul nombre de tours — ce que faisait l'export — écrase
en silence toute séance de la même longueur.

**Rien ici ne lève.** Un disque plein, un dossier en lecture seule, une ligne
coupée en deux : garder une conversation est un service rendu, pas une
condition pour en tenir une. Une ligne illisible est sautée et les voisines
restent, ce qui rend un fichier abîmé réparable en le tronquant.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# Où vivent les séances. `~/.erplibre` est le dossier des données de
# l'utilisateur, pas du dépôt, et il est déjà celui de l'export et des
# préférences.
BASE = ("~", ".erplibre", "assistant", "sessions")

# Les droits : un dossier que seul son propriétaire traverse, des fichiers que
# seul lui lit. `~/.erplibre` est lisible par tous les comptes de la machine,
# et une conversation porte ce qu'on lui a collé.
MODE_DOSSIER = 0o700
MODE_FICHIER = 0o600

# Ce qu'une ligne d'en-tête déclare, par opposition à un tour.
ENTETE = "entete"

# La longueur du titre tiré de la première question. De quoi reconnaître une
# séance dans une liste sans que la ligne déborde d'un terminal étroit.
TITRE_MAX = 60


@dataclass(frozen=True)
class Resume:
    """Ce qu'une séance montre d'elle-même dans une liste.

    `tours` compte les ÉCHANGES et non les lignes : une question et sa
    réponse font un tour, ce qui est la façon dont on compte une conversation
    quand on la relit.
    """

    chemin: str
    seance: str
    debut: str
    logiciel: str
    modele: str
    outil: str
    tours: int
    titre: str


def dossier(base=None) -> Path:
    """Le dossier des séances, créé au besoin. Jamais None."""
    if base is None:
        return Path(os.path.expanduser(os.path.join(*BASE)))
    return Path(base)


def chemin(seance: str, debut: str, *, base=None) -> Path:
    """Le fichier d'une séance : sa date, puis son identifiant.

    La date ouvre le nom pour que le tri du système de fichiers soit celui du
    temps, et l'identifiant le ferme pour que deux séances du même jour ne se
    confondent pas.
    """
    jour = (debut or "")[:10] or "0000-00-00"
    return dossier(base) / f"{jour}-{seance}.jsonl"


def maintenant() -> str:
    """L'instant, en ISO 8601 avec son décalage."""
    return (
        datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    )


def _ecrire(cible: Path, entree: dict) -> bool:
    """Ajoute une ligne JSON au fichier, en créant ce qu'il faut. Jamais lève.

    L'ouverture en AJOUT est ce qui rend deux écrivains inoffensifs l'un pour
    l'autre, et le fichier est créé en 0600 dès la première ligne : un
    `open` ordinaire le créerait avec le masque du compte, souvent lisible
    par tout le monde.
    """
    try:
        cible.parent.mkdir(parents=True, mode=MODE_DOSSIER, exist_ok=True)
        os.chmod(cible.parent, MODE_DOSSIER)
        drapeaux = os.O_WRONLY | os.O_CREAT | os.O_APPEND
        with os.fdopen(
            os.open(cible, drapeaux, MODE_FICHIER), "a", encoding="utf-8"
        ) as fichier:
            fichier.write(
                json.dumps(entree, ensure_ascii=False, sort_keys=False) + "\n"
            )
    except OSError:
        return False
    return True


def ouvrir(seance: str, serveur, *, outil="", debut=None, base=None):
    """Déclare une séance et rend son chemin, ou None si l'écriture échoue.

    L'en-tête porte de quoi reconnaître la séance sans lire ses tours : le
    logiciel et le modèle expliquent ce qui a été répondu, et l'outil gpt
    explique ce qui a été demandé.
    """
    debut = debut or maintenant()
    cible = chemin(seance, debut, base=base)
    entree = {
        "kind": ENTETE,
        "t": debut,
        "seance": seance,
        "logiciel": getattr(serveur, "software", ""),
        "modele": getattr(serveur, "model", ""),
        "hote": getattr(serveur, "host", ""),
        "port": getattr(serveur, "port", 0),
        "outil": outil,
    }
    return cible if _ecrire(cible, entree) else None


def noter(cible, tour, *, quand=None) -> bool:
    """Ajoute un tour à une séance. Rend faux si rien n'a pu être écrit.

    Le raisonnement d'un modèle qui réfléchit est gardé à part du texte,
    comme il arrive : il est payé dans les jetons de la réponse, et le
    confondre avec elle ferait relire comme dit ce qui n'a été que pensé.
    """
    if cible is None:
        return False
    entree = {
        "t": quand or maintenant(),
        "role": getattr(tour, "role", ""),
        "text": getattr(tour, "text", "") or "",
    }
    if getattr(tour, "interrupted", False):
        entree["interrupted"] = True
    pensee = getattr(tour, "reasoning", "") or ""
    if pensee:
        entree["reasoning"] = pensee
    return _ecrire(Path(cible), entree)


def _lignes(cible) -> list[dict]:
    """Les lignes lisibles d'un fichier de séance, les abîmées écartées."""
    trouves: list[dict] = []
    try:
        with open(cible, encoding="utf-8") as fichier:
            for brut in fichier:
                brut = brut.strip()
                if not brut:
                    continue
                try:
                    entree = json.loads(brut)
                except ValueError:
                    continue
                if isinstance(entree, dict):
                    trouves.append(entree)
    except OSError:
        return []
    return trouves


def _titre(lignes) -> str:
    """La première question, coupée. Ce qui fait reconnaître une séance.

    Une date et un modèle ne distinguent pas deux séances du même
    après-midi ; la question qui l'a ouverte, si.
    """
    for entree in lignes:
        if entree.get("role") == "user":
            texte = " ".join(str(entree.get("text", "")).split())
            if len(texte) > TITRE_MAX:
                return texte[: TITRE_MAX - 1] + "…"
            return texte
    return ""


def resume(cible) -> Resume | None:
    """Ce qu'une séance montre d'elle-même, ou None si elle ne dit rien.

    Une séance ouverte puis quittée sans un mot n'a pas de tour : la proposer
    à la reprise ferait rouvrir un fichier vide, donc elle est écartée.
    """
    lignes = _lignes(cible)
    if not lignes:
        return None
    entete = lignes[0] if lignes[0].get("kind") == ENTETE else {}
    echanges = [one for one in lignes if one.get("role") == "assistant"]
    if not echanges:
        return None
    return Resume(
        chemin=str(cible),
        seance=str(entete.get("seance", "")),
        debut=str(entete.get("t", "")),
        logiciel=str(entete.get("logiciel", "")),
        modele=str(entete.get("modele", "")),
        outil=str(entete.get("outil", "")),
        tours=len(echanges),
        titre=_titre(lignes),
    )


def lister(*, base=None, combien=None) -> list[Resume]:
    """Les séances gardées, la plus récente d'abord.

    Le tri se fait sur le NOM, qui ouvre par la date : lire chaque fichier
    pour trier sur son en-tête coûterait une ouverture par séance avant même
    d'afficher la liste.
    """
    racine = dossier(base)
    try:
        fichiers = sorted(racine.glob("*.jsonl"), reverse=True)
    except OSError:
        return []
    trouves = []
    for cible in fichiers:
        vu = resume(cible)
        if vu is not None:
            trouves.append(vu)
        if combien is not None and len(trouves) >= combien:
            break
    return trouves


def charger(cible) -> list:
    """Les tours d'une séance, prêts à reprendre la conversation.

    Rend des `chat.Turn`, donc l'historique repart tel qu'il était : le
    modèle reçoit au tour suivant ce qu'il aurait reçu sans l'interruption.
    Les tours en PANNE n'y sont pas — ils n'étaient pas dans l'historique
    non plus — et un rôle inconnu est sauté plutôt que de fabriquer un tour
    que la conversation ne saurait pas rejouer.
    """
    from script.todo.assistant.chat import Turn

    tours = []
    for entree in _lignes(cible):
        role = entree.get("role")
        if role not in ("user", "assistant"):
            continue
        tours.append(
            Turn(
                role,
                str(entree.get("text", "") or ""),
                interrupted=bool(entree.get("interrupted", False)),
                reasoning=str(entree.get("reasoning", "") or ""),
            )
        )
    return tours
