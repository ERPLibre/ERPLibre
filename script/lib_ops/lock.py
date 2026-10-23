# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un verrou par ressource, pris sans attendre.

`fcntl.flock` non bloquant sur un fichier `<dossier>/<nom>.lock`. Le
noyau libère le verrou à la fermeture du descripteur, donc aussi à la
mort du processus : un verrou ne survit jamais à son détenteur, et il n'y
a pas de fichier « périmé » à nettoyer.

Le fichier s'ouvre en LECTURE seule, sans `O_CREAT` quand il existe :
flock n'exige aucun droit d'écriture. Deux comptes se partagent ainsi le
même verrou — root et le compte d'un service, par exemple — quel que soit
celui qui a créé le fichier. Une ouverture avec `O_CREAT` d'un fichier
existant appartenant à un autre compte, dans un dossier collant ouvert à
tous comme `/run/lock`, est refusée par le noyau quand
`fs.protected_regular` vaut 2, root compris. Créé, le fichier reçoit le
mode 0644 quel que soit l'umask, pour que l'autre compte puisse l'ouvrir.

Le dossier par défaut est `/run/lock`, vidé au démarrage de la machine.
Un verrou ordinaire qui ne peut pas y être posé se replie sur le dossier
temporaire (`TMPDIR`) : deux exécutions du même compte qui se replient au
même endroit s'excluent toujours. Un verrou PARTAGÉ (`strict=True`) ne se
replie jamais : deux comptes, ou une unité à `PrivateTmp=`, n'ont pas le
même dossier temporaire, et deux verrous à deux endroits n'excluent rien.
Il refuse alors, par `VerrouIndisponible`.

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

MODE_FICHIER = 0o644


class VerrouPris(Exception):
    """Le verrou est détenu par un autre processus. Porte le chemin."""

    def __init__(self, chemin):
        super().__init__(chemin)
        self.chemin = chemin


class VerrouIndisponible(OSError):
    """Le verrou partagé ne peut être ni ouvert ni créé à son endroit.

    Hérite d'OSError : un appelant qui traite déjà « le fichier ne s'ouvre
    pas » le traite aussi. Porte le chemin visé.
    """

    def __init__(self, chemin, cause=""):
        super().__init__(f"{chemin}: {cause}" if cause else chemin)
        self.chemin = chemin


def dossier_verrou(dossier=None):
    """Le dossier où poser un verrou ordinaire : celui demandé s'il est
    inscriptible, sinon le dossier temporaire."""
    dossier = dossier or DOSSIER_PAR_DEFAUT
    if os.path.isdir(dossier) and os.access(dossier, os.W_OK):
        return dossier
    return tempfile.gettempdir()


def chemin_verrou(nom, dossier=None, strict=False):
    """Le chemin du fichier de verrou de `nom`. ValueError sur un nom qui ne
    ferait pas un nom de fichier sûr.

    `strict` : le dossier demandé tel quel, sans repli — VerrouIndisponible
    s'il n'existe pas.
    """
    if not nom or RE_NOM.fullmatch(nom) is None:
        raise ValueError(nom)
    if strict:
        dossier = dossier or DOSSIER_PAR_DEFAUT
        chemin = os.path.join(dossier, f"{nom}.lock")
        if not os.path.isdir(dossier):
            raise VerrouIndisponible(chemin, "no such directory")
        return chemin
    return os.path.join(dossier_verrou(dossier), f"{nom}.lock")


def ouvrir_fichier(chemin):
    """Un descripteur en lecture seule sur `chemin`, créé au besoin.

    D'abord `O_RDONLY` sans `O_CREAT` ; absent, `O_CREAT|O_EXCL` puis mode
    0644 ; si un autre processus l'a créé entre les deux, on rouvre sans
    `O_CREAT`. OSError si le fichier ne peut être ni ouvert ni créé.
    """
    for _essai in range(2):
        try:
            return os.open(chemin, os.O_RDONLY)
        except FileNotFoundError:
            pass
        try:
            fd = os.open(
                chemin, os.O_RDONLY | os.O_CREAT | os.O_EXCL, MODE_FICHIER
            )
        except FileExistsError:
            continue
        try:
            os.fchmod(fd, MODE_FICHIER)
        except OSError:
            pass
        return fd
    return os.open(chemin, os.O_RDONLY)


class Verrou:
    """Gestionnaire de contexte : `with Verrou("nom"):` ou acquérir/relâcher.

    `acquerir()` lève `VerrouPris` sans attendre si un autre processus le
    détient, et OSError si le fichier ne peut pas être ouvert —
    `VerrouIndisponible` pour un verrou `strict`. Un verrou `strict` dont
    le dossier n'existe pas lève `VerrouIndisponible` dès sa construction :
    l'appelant construit et acquiert dans le même `try`.
    """

    def __init__(self, nom, dossier=None, strict=False):
        self.strict = strict
        self.chemin = chemin_verrou(nom, dossier, strict)
        self._fd = None

    def acquerir(self):
        try:
            fd = ouvrir_fichier(self.chemin)
        except OSError as err:
            if self.strict:
                raise VerrouIndisponible(
                    self.chemin, err.strerror or str(err)
                ) from None
            raise
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (BlockingIOError, PermissionError):
            os.close(fd)
            raise VerrouPris(self.chemin) from None
        self._fd = fd
        return self

    def relacher(self):
        if self._fd is not None:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            finally:
                os.close(self._fd)
                self._fd = None

    def __enter__(self):
        return self.acquerir()

    def __exit__(self, *_exc):
        self.relacher()
        return False
