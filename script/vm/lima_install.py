#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Acquérir l'outil Lima : version ÉPINGLÉE, somme de contrôle VÉRIFIÉE.

CE QU'ON REFUSE DE FAIRE, et pourquoi c'est le sujet de ce module. Demander
« la dernière version » à une forge, la télécharger sans authentifier la
réponse et l'exécuter, c'est confier à quiconque peut se placer sur le trajet
le droit de choisir ce qui tourne sur la machine. Ce n'est pas une faiblesse
théorique : le binaire obtenu lance ensuite des VM et reçoit des secrets.

Trois refus, donc, et ils sont FERMÉS par défaut :

    version non épinglée      -> refus. « latest » désigne une chose
                                 différente à chaque appel, donc rien qu'on
                                 puisse vérifier.
    somme inconnue            -> refus. Une version qui ne figure pas dans
                                 la table n'a pas de référence à comparer.
    somme qui ne correspond   -> refus. C'est le seul moment où l'on peut
                                 encore ne rien exécuter.

LA TABLE EST VIDE, et c'est délibéré. Une somme de contrôle se RELÈVE ; en
inventer une donnerait un mécanisme qui refuse tout, ou pire, qui accepte ce
qu'il ne devrait pas si le format était mal deviné. Le mode d'emploi pour la
remplir est au-dessus de `RELEASES`.

Ce module ne télécharge rien et n'exécute rien : il calcule et il compare.
"""

from __future__ import annotations

import hashlib
import os
from typing import NamedTuple

# Le gabarit d'URL d'une publication. Le nom d'archive suit la convention de
# l'outil : <projet>-<version>-<Système>-<arch>.tar.gz.
URL_TEMPLATE = (
    "https://github.com/lima-vm/lima/releases/download/"
    "v{version}/lima-{version}-{system}-{arch}.tar.gz"
)

# Les jetons de système et d'architecture tels que les archives les nomment.
# Ce ne sont PAS ceux d'`uname` : les traduire ici évite que chaque appelant
# invente sa propre correspondance.
SYSTEMS = {"macos": "Darwin", "linux": "Linux"}
ARCHS = {
    "arm64": "arm64",
    "aarch64": "arm64",
    "amd64": "x86_64",
    "x86_64": "x86_64",
}

# Versions épinglées -> somme SHA-256 de l'archive, par (système, arch).
#
# POUR EN AJOUTER UNE : récupérer le fichier de sommes publié avec la
# version, en vérifier la signature auprès du projet, puis recopier ici la
# ligne qui correspond à l'archive visée. Ne jamais calculer la somme sur un
# fichier qu'on vient de télécharger sans l'avoir vérifié : on épinglerait
# alors ce qu'on a reçu, ce qui ne prouve rien.
#
# Vide, ce module REFUSE toute installation. C'est l'état correct tant que
# personne n'a relevé de somme : mieux vaut ne rien installer qu'installer
# ce qu'on n'a pas vérifié.
RELEASES: dict = {}

# Le vocabulaire des refus, clos.
OK = "ok"
UNPINNED = "unpinned-version"
UNKNOWN_RELEASE = "unknown-release"
UNKNOWN_TARGET = "unknown-target"
CHECKSUM_MISMATCH = "checksum-mismatch"
FILE_ABSENT = "file-absent"
REFUSALS = (
    OK,
    UNPINNED,
    UNKNOWN_RELEASE,
    UNKNOWN_TARGET,
    CHECKSUM_MISMATCH,
    FILE_ABSENT,
)


class Release(NamedTuple):
    """Ce qu'il faut pour aller chercher UNE archive et la reconnaître."""

    version: str
    url: str
    sha256: str


def target_tokens(system: str, arch: str) -> tuple:
    """(système, arch) tels que les archives les nomment, ou ("", "")."""
    return (
        SYSTEMS.get((system or "").lower(), ""),
        ARCHS.get((arch or "").lower(), ""),
    )


def plan(version: str, system: str, arch: str):
    """(Release, "ok") si tout est épinglé, sinon (None, la raison).

    Ne lève pas : l'appelant est un écran, et il doit pouvoir DIRE pourquoi
    il ne fera rien plutôt que s'interrompre.
    """
    propre = str(version or "").strip().lstrip("v")
    if not propre or propre.lower() in ("latest", "master", "main"):
        # « latest » désigne une chose différente à chaque appel : il n'y a
        # rien à comparer, donc rien à vérifier.
        return None, UNPINNED
    jeton_sys, jeton_arch = target_tokens(system, arch)
    if not (jeton_sys and jeton_arch):
        return None, UNKNOWN_TARGET
    sommes = RELEASES.get(propre) or {}
    somme = sommes.get((jeton_sys, jeton_arch)) or ""
    if not somme:
        return None, UNKNOWN_RELEASE
    return (
        Release(
            version=propre,
            url=URL_TEMPLATE.format(
                version=propre, system=jeton_sys, arch=jeton_arch
            ),
            sha256=somme,
        ),
        OK,
    )


def sha256_of(path: str) -> str:
    """La somme SHA-256 du fichier, ou "" s'il est illisible.

    Lu par blocs : une archive tient plusieurs dizaines de mégaoctets, et la
    charger d'un coup pour la hacher n'apporte rien.
    """
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as fh:
            for bloc in iter(lambda: fh.read(1024 * 1024), b""):
                digest.update(bloc)
    except OSError:
        return ""
    return digest.hexdigest()


def verify(path: str, expected: str) -> str:
    """« ok », ou la raison du refus. FERMÉ par défaut.

    Un fichier absent, une somme attendue vide, une somme qui ne correspond
    pas : trois refus, et aucun ne se confond avec un succès. C'est le
    dernier moment où l'on peut encore ne rien exécuter.
    """
    if not path or not os.path.exists(path):
        return FILE_ABSENT
    attendue = (expected or "").strip().lower()
    if not attendue:
        # Sans référence, il n'y a rien à vérifier — et « rien à vérifier »
        # ne veut pas dire « vérifié ».
        return UNKNOWN_RELEASE
    return OK if sha256_of(path) == attendue else CHECKSUM_MISMATCH
