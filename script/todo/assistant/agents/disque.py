#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que Claude Code occupe sur le disque, et ce qui se retire sans regret.

Un répertoire qui grossit ne dit pas POURQUOI il grossit, et « historique des
fichiers : 10 Go » n'est pas une information sur laquelle agir. Ce module
descend d'un cran : l'historique se range par session, et une session porte
un plus gros fichier capturé. C'est là que la réponse se trouve — sur la
machine qui a servi à écrire ce module, une seule session portait la
quasi-totalité du volume, et dans un seul fichier : une image disque de
machine virtuelle, entrée dans l'historique parce qu'une session l'a touchée.
Un tableau par répertoire n'aurait jamais montré ça.

**Ce module ne supprime rien.** Il mesure, il classe, et il dit ce qu'une
suppression ferait perdre. Le geste appartient à l'écran, qui exige
l'identifiant retapé — l'historique d'une session est ce qui permet de
restaurer une version antérieure d'un fichier, et rien ne le reconstitue.

**Une session VIVANTE n'est jamais proposée.** Elle écrit encore, et retirer
son historique sous elle laisserait une session qui croit pouvoir restaurer
ce qui n'existe plus.
"""
from __future__ import annotations

import os
from dataclasses import dataclass

# La maison de Claude Code, et les répertoires dont le volume se mesure. La
# liste est FERMÉE : mesurer tout ce qui traîne ferait varier le tableau d'une
# version à l'autre du logiciel, et un tableau qui change de lignes tout seul
# ne se compare pas d'une fois sur l'autre.
MAISON = "~/.claude"
REPERTOIRES = (
    "file-history",
    "projects",
    "plugins",
    "cache",
    "backups",
    "paste-cache",
    "shell-snapshots",
    "downloads",
    "sessions",
    "session-env",
    "teams",
    "tasks",
)

# Le sous-répertoire rangé par session, et le seul que l'écran propose de
# retirer. Les autres sont soit minuscules, soit nécessaires au fonctionnement.
HISTORIQUE = "file-history"


def _volume(chemin, *, marcher=None, taille=None) -> tuple[int, int]:
    """(octets, fichiers) d'une arborescence. Un chemin absent rend (0, 0)."""
    marcher = marcher or os.walk
    taille = taille or os.path.getsize
    octets = fichiers = 0
    for base, _dossiers, noms in marcher(chemin):
        for nom in noms:
            try:
                octets += taille(os.path.join(base, nom))
            except OSError:
                continue
            fichiers += 1
    return octets, fichiers


@dataclass(frozen=True)
class Poste:
    """Un répertoire mesuré. `present` distingue le vide de l'absent.

    Un répertoire absent et un répertoire vide pèsent tous deux zéro, et ce
    n'est pas la même chose : le premier n'a jamais servi, le second a été
    vidé. L'écran les affiche différemment.
    """

    nom: str
    octets: int = 0
    fichiers: int = 0
    present: bool = False


def mesurer(*, maison=None, marcher=None, taille=None, existe=None):
    """Le volume de chaque répertoire connu, le plus gros d'abord."""
    existe = existe or os.path.isdir
    base = os.path.expanduser(maison or MAISON)
    postes = []
    for nom in REPERTOIRES:
        chemin = os.path.join(base, nom)
        if not existe(chemin):
            postes.append(Poste(nom=nom))
            continue
        octets, fichiers = _volume(chemin, marcher=marcher, taille=taille)
        postes.append(
            Poste(nom=nom, octets=octets, fichiers=fichiers, present=True)
        )
    return sorted(postes, key=lambda p: -p.octets)


@dataclass(frozen=True)
class Historique:
    """L'historique d'UNE session : son volume, et sa plus grosse capture.

    `plus_gros` est ce qui rend la ligne actionnable. « 10 Go » sur une
    session ne dit pas quoi faire ; « 10 Go dont 10 Go en un seul fichier »
    dit que quelque chose d'énorme a été capturé par accident.
    """

    session: str
    octets: int = 0
    fichiers: int = 0
    plus_gros: int = 0
    vivante: bool = False

    @property
    def retirable(self) -> bool:
        """Une session vivante écrit encore : on ne retire pas sous elle."""
        return self.fichiers > 0 and not self.vivante


def historiques(
    *, maison=None, lister=None, marcher=None, taille=None, vivantes=()
):
    """L'historique par session, le plus volumineux d'abord.

    `vivantes` porte les identifiants qui tournent — le registre les donne —
    et sert à marquer ce qui ne doit pas être proposé.

    **None n'est pas l'ensemble vide.** Il dit « la question n'a pas pu être
    posée », et rien n'est alors proposé. Sans cette distinction, un listage
    qui échoue — l'outil hors du PATH du processus qui lance le menu — rend
    TOUTE session supprimable, y compris celle qui écrit en ce moment : une
    garde qui tombe en ouvert sur un geste destructeur.
    """
    import glob

    lister = lister or glob.glob
    base = os.path.join(os.path.expanduser(maison or MAISON), HISTORIQUE)
    taille = taille or os.path.getsize
    inconnu = vivantes is None
    vivants = set() if inconnu else set(vivantes)
    sorties = []
    for chemin in lister(os.path.join(base, "*")):
        octets, fichiers = _volume(chemin, marcher=marcher, taille=taille)
        plus_gros = 0
        for dossier, _d, noms in (marcher or os.walk)(chemin):
            for nom in noms:
                try:
                    plus_gros = max(
                        plus_gros, taille(os.path.join(dossier, nom))
                    )
                except OSError:
                    continue
        session = os.path.basename(chemin)
        sorties.append(
            Historique(
                session=session,
                octets=octets,
                fichiers=fichiers,
                plus_gros=plus_gros,
                vivante=inconnu or session in vivants,
            )
        )
    return sorted(sorties, key=lambda h: -h.octets)


def chemin_historique(session, *, maison=None) -> str:
    """Le répertoire d'historique d'une session, chemin absolu.

    L'identifiant est vérifié : un chemin composé sans contrôle laisserait un
    « .. » désigner autre chose que ce que l'écran a montré.
    """
    if not session or "/" in session or session.startswith("."):
        raise ValueError(f"identifiant de session refusé : {session!r}")
    return os.path.join(
        os.path.expanduser(maison or MAISON), HISTORIQUE, session
    )


def octets_lisibles(octets) -> str:
    """« 10,0 Go », « 44 ko », « 0 » — trois chiffres significatifs."""
    octets = int(octets or 0)
    for seuil, unite in ((1 << 30, "Go"), (1 << 20, "Mo"), (1 << 10, "ko")):
        if octets >= seuil:
            return f"{octets / seuil:.1f} {unite}"
    return str(octets)
