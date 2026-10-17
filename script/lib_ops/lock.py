# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un verrou par ressource, pris sans attendre.

`fcntl.flock` non bloquant sur un fichier `<dossier>/<nom>.lock`. Le
noyau libère le verrou à la fermeture du descripteur, donc aussi à la
mort du processus : un verrou ne survit jamais à son détenteur, et il n'y
a pas de fichier « périmé » à nettoyer.

Le dossier par défaut est `/run/lock`, vidé au démarrage de la machine.
Quand il n'est pas inscriptible, le verrou se replie sur le dossier
temporaire (`TMPDIR`) : deux exécutions qui se replient au même endroit
s'excluent toujours, ce qui suffit.

Le descripteur n'est pas hérité par les processus enfants (PEP 446) : un
enfant orphelin ne garde donc pas le verrou. L'appelant attend la fin de
ses enfants avant de le relâcher.

Bibliothèque standard seulement.
"""

from __future__ import annotations

import fcntl
import os
import re
import tempfile

DOSSIER_PAR_DEFAUT = "/run/lock"

# Caractères admis dans un nom de verrou : de quoi rester un nom de fichier.
RE_NOM = re.compile(r"[A-Za-z0-9_.@-]+")


class VerrouPris(Exception):
    """Le verrou est détenu par un autre processus. Porte le chemin."""

    def __init__(self, chemin):
        super().__init__(chemin)
        self.chemin = chemin


def dossier_verrou(dossier=None):
    """Le dossier où poser le verrou : celui demandé s'il est inscriptible,
    sinon le dossier temporaire."""
    dossier = dossier or DOSSIER_PAR_DEFAUT
    if os.path.isdir(dossier) and os.access(dossier, os.W_OK):
        return dossier
    return tempfile.gettempdir()


def chemin_verrou(nom, dossier=None):
    """Le chemin du fichier de verrou de `nom`. ValueError sur un nom qui ne
    ferait pas un nom de fichier sûr."""
    if not nom or RE_NOM.fullmatch(nom) is None:
        raise ValueError(nom)
    return os.path.join(dossier_verrou(dossier), f"{nom}.lock")


class Verrou:
    """Gestionnaire de contexte : `with Verrou("nom"):` ou acquérir/relâcher.

    `acquerir()` lève `VerrouPris` sans attendre si un autre processus le
    détient, et OSError si le fichier ne peut pas être ouvert.
    """

    def __init__(self, nom, dossier=None):
        self.chemin = chemin_verrou(nom, dossier)
        self._fichier = None

    def acquerir(self):
        fichier = open(self.chemin, "a")
        try:
            fcntl.flock(fichier.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, PermissionError):
            fichier.close()
            raise VerrouPris(self.chemin) from None
        self._fichier = fichier
        return self

    def relacher(self):
        if self._fichier is not None:
            try:
                fcntl.flock(self._fichier.fileno(), fcntl.LOCK_UN)
            finally:
                self._fichier.close()
                self._fichier = None

    def __enter__(self):
        return self.acquerir()

    def __exit__(self, *_exc):
        self.relacher()
        return False
