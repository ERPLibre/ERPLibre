#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une sauvegarde tient-elle, sans la restaurer ?

CE QUI MENT SEUL, ET POURQUOI IL FAUT PLUSIEURS CONTRÔLES. Le
téléchargement d'une sauvegarde distante enregistre la réponse du serveur
telle quelle, sans exiger qu'elle soit un succès : un mot de passe maître
refusé produit une page d'erreur ÉCRITE SOUS LE NOM DU ZIP. Non vide,
horodatée, et annoncée comme réussie. La taille seule dit donc « oui » sur
un fichier qui ne contient rien de récupérable.

CINQ CONTRÔLES, DU MOINS CHER AU PLUS CHER, et chacun nommé dans le
verdict : dire « sauvegarde vérifiée » sans dire jusqu'où on est allé
ajoute une croyance de plus, au lieu d'en retirer une.

    présent      le fichier existe et n'est pas un répertoire
    non-vide     il pèse quelque chose
    zip          l'archive s'ouvre et son index se lit
    dump         « dump.sql » est là — la SEULE pièce indispensable
    intègre      chaque membre se décompresse, filestore compris

CE QU'IL NE DIT PAS, ET LE DIT. Il ne dit pas que la sauvegarde se
restaure : aucun contrôle ici n'exécute le dump. Il dit jusqu'où il est
allé, et rien de plus.

L'ABSENCE DU MANIFESTE N'EST PAS UNE ERREUR : une sauvegarde produite
ailleurs n'en porte aucune, et refuser le fichier pour cela reviendrait à
refuser précisément celles qu'on a le plus besoin de vérifier.
"""

from __future__ import annotations

import os
import zipfile
from typing import NamedTuple

# Le vocabulaire des verdicts, clos et ORDONNÉ du pire au meilleur : le rang
# d'un jeton est ce qui permet de dire « allé jusqu'à » sans écrire une
# deuxième table de comparaison.
ABSENT = "absent"
EMPTY = "empty"
NOT_A_ZIP = "not-a-zip"
NO_DUMP = "no-dump"
CORRUPT = "corrupt"
SOUND = "sound"
VERDICTS = (ABSENT, EMPTY, NOT_A_ZIP, NO_DUMP, CORRUPT, SOUND)

# La seule pièce indispensable : c'est elle qui porte les données.
DUMP = "dump.sql"


class Verification(NamedTuple):
    """Ce qu'on a pu constater d'une sauvegarde, et jusqu'où on est allé.

    `checks` liste les contrôles PASSÉS, dans l'ordre. Un verdict sans eux
    laisserait croire qu'on a tout regardé — et « vérifiée » est le mot le
    plus facile à croire.
    """

    verdict: str
    path: str = ""
    size: int = 0
    checks: tuple = ()
    detail: str = ""


def _membre(archive, nom):
    """Le membre `nom`, à la racine ou ailleurs. None s'il n'y est pas.

    Selon qui fabrique la sauvegarde, elle est mise à plat ou rangée sous un
    dossier : chercher à la racine seule refuserait la moitié des archives.
    """
    noms = archive.namelist()
    if nom in noms:
        return nom
    for candidat in noms:
        if candidat.rsplit("/", 1)[-1] == nom:
            return candidat
    return None


def verify(path, deep=True) -> Verification:
    """Constate ce qu'on peut d'une sauvegarde. Ne lève pas, n'affiche rien.

    `deep` faux s'arrête avant la décompression intégrale : elle est
    linéaire en taille, et un écran qui parcourt un répertoire ne peut pas
    la payer pour chaque fichier. Le verdict dit alors jusqu'où il est allé,
    ce qui n'est pas la même chose que d'avoir tout vu.
    """
    passes = []
    if not os.path.isfile(path):
        # Un répertoire portant ce nom compte pour une absence : ce qu'on
        # cherchait à ouvrir n'est pas là.
        return Verification(ABSENT, path=str(path))
    passes.append("present")

    taille = os.path.getsize(path)
    if not taille:
        return Verification(EMPTY, path=str(path), checks=tuple(passes))
    passes.append("non-empty")

    try:
        with zipfile.ZipFile(path) as archive:
            noms = archive.namelist()
            passes.append("zip")
            if _membre(archive, DUMP) is None:
                return Verification(
                    NO_DUMP,
                    path=str(path),
                    size=taille,
                    checks=tuple(passes),
                    detail=f"{len(noms)}",
                )
            passes.append("dump")
            if not deep:
                return Verification(
                    SOUND,
                    path=str(path),
                    size=taille,
                    checks=tuple(passes),
                )
            abime = archive.testzip()
    except (OSError, zipfile.BadZipFile, RuntimeError) as souci:
        # Une page d'erreur enregistrée sous le nom du zip arrive ICI : elle
        # pèse, elle est datée, et elle n'a pas d'index.
        return Verification(
            NOT_A_ZIP,
            path=str(path),
            size=taille,
            checks=tuple(passes),
            detail=str(souci),
        )
    if abime:
        return Verification(
            CORRUPT,
            path=str(path),
            size=taille,
            checks=tuple(passes),
            detail=abime,
        )
    passes.append("intact")
    return Verification(
        SOUND, path=str(path), size=taille, checks=tuple(passes)
    )
