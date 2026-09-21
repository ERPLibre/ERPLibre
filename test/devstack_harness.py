#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un PATH où seuls les binaires déclarés existent, et qui dit qui a servi.

Quatre fichiers de test portent déjà la même dizaine de lignes — un dossier
temporaire, un script bash par binaire, `chmod(0o755)`, un PATH recomposé.
Les réunir ici évite la cinquième copie, mais ce n'est pas la raison
principale : aucune des quatre ne sait dire si le bouchon a SERVI.

C'est ce qui manque le plus. Un bouchon piégé prouve seulement que le vrai
binaire n'a pas tourné ; il ne prouve pas que le code testé a fait quoi que
ce soit. Sans un contrôle POSITIF — la même épreuve contre un bouchon qui
réussit, et l'assurance qu'il a été appelé — un test passe aussi bien quand
le code ne s'exécute pas du tout. `appels` existe pour rendre ce contrôle
aussi facile à écrire que son contraire.

Ce module n'est pas un cadre de simulation de sous-processus : il ne détourne
ni `subprocess`, ni `Popen`. Il déplace le PATH, ce que `shutil.which` et tout
appel shell respectent, et cela suffit à décider quels binaires EXISTENT.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from pathlib import Path

# Un binaire qui ne doit PAS être appelé. Le déclarer ainsi le rend visible
# dans le PATH — donc trouvable par `which` — mais son appel est enregistré
# et fait échouer la sortie du contexte.
PIEGE = object()


class BinPiege(AssertionError):
    """Un binaire déclaré comme à ne pas appeler l'a été."""


class ShimDir:
    """Un PATH temporaire où seuls les binaires déclarés existent.

    Chaque bouchon note son nom avant de jouer son corps, donc `appels` dit
    ce qui a réellement servi, dans l'ordre. Un bouchon déclaré `PIEGE`
    échoue à la sortie du contexte s'il a été appelé.

    `nu=True` retire `/usr/bin` et `/bin` du PATH : plus aucun binaire réel
    n'est joignable, ce qui rend l'épreuve indépendante de la station. Par
    défaut ils restent, comme dans les quatre copies que ce module remplace.
    """

    def __init__(self, nu: bool = False, **bouchons):
        self._nu = nu
        self._bouchons = bouchons
        self._tmp = None
        self.chemin = None
        self.journal = None

    def __enter__(self) -> "ShimDir":
        self._tmp = tempfile.TemporaryDirectory()
        racine = Path(self._tmp.name)
        self.chemin = racine / "bin"
        self.chemin.mkdir()
        self.journal = racine / "appels.txt"
        self.journal.touch()
        for nom, corps in self._bouchons.items():
            self._ecrire(nom, corps)
        return self

    def _ecrire(self, nom: str, corps) -> None:
        piege = corps is PIEGE
        script = (
            "#!/bin/bash\n" f'printf "%s\\n" "{nom}" >> "{self.journal}"\n'
        )
        script += "exit 127\n" if piege else f"{corps}\n"
        cible = self.chemin / nom
        cible.write_text(script, encoding="utf-8")
        cible.chmod(0o755)

    @property
    def appels(self) -> list:
        """Les noms des bouchons appelés, dans l'ordre."""
        if self.journal is None:
            return []
        return self.journal.read_text(encoding="utf-8").split()

    def path(self) -> str:
        """La valeur de PATH que ce shim impose."""
        if self._nu:
            return str(self.chemin)
        return f"{self.chemin}:/usr/bin:/bin"

    def env(self, **extra) -> dict:
        """L'environnement courant, PATH remplacé, plus `extra`."""
        return dict(os.environ, PATH=self.path(), **extra)

    def __exit__(self, *_exc):
        pieges = {
            nom
            for nom, corps in self._bouchons.items()
            if corps is PIEGE and nom in self.appels
        }
        try:
            if pieges:
                raise BinPiege(
                    "binaire(s) déclaré(s) à ne pas appeler, appelé(s) : "
                    + ", ".join(sorted(pieges))
                )
        finally:
            self._tmp.cleanup()
        return False


def which_sous(shim: ShimDir, nom: str):
    """Ce que `shutil.which` trouve sous le PATH du shim, et rien d'autre.

    Le passer explicitement évite de muter `os.environ`, qu'un test voisin
    lirait ensuite.
    """
    return shutil.which(nom, path=shim.path())
