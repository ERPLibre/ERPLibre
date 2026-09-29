#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Exécute un fichier de tests et note chaque test : son résultat, sa durée.

    unit_file.py FICHIER SORTIE.json

Lancé par `run_unit_test.py` à la place du fichier lui-même, quand on lui
demande un détail par test (--slowest, --junit). La sortie à l'écran est
celle de `unittest.main()` — une ligne de points, les erreurs, « Ran N »,
« OK » — et le lanceur la lit comme d'habitude ; SORTIE.json reçoit une
entrée par test.

Le fichier est chargé comme MODULE et non comme programme : son bloc
« __main__ » final ne tourne pas, et c'est le chargeur de unittest qui
trouve les tests, comme unittest.main() le ferait. Son répertoire passe en
tête du chemin d'import et son nom en argv[0], comme s'il était lancé seul :
les tests qui lisent un voisin par un import nu le trouvent.
"""

import importlib.util
import json
import os
import sys
import time
import unittest


class Resultat(unittest.TextTestResult):
    """Un TextTestResult qui garde, pour chaque test, son issue et sa durée."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.detail = []
        self._debut = {}

    def startTest(self, test):
        self._debut[test.id()] = time.perf_counter()
        super().startTest(test)

    @staticmethod
    def _nommer(test):
        """(classe, nom) du test, sous-test et fixture de classe compris.

        Un sous-test ignoré arrive comme un _SubTest, une erreur ou un saut
        de setUpClass comme un _ErrorHolder : on les range sous le test ou
        la classe dont ils viennent, et non sous ces classes internes."""
        parent = getattr(test, "test_case", None)
        if parent is not None:
            return (
                type(parent).__qualname__,
                f"{parent._testMethodName} {test._subDescription()}",
            )
        if hasattr(test, "_testMethodName"):
            return type(test).__qualname__, test._testMethodName
        # « setUpClass (module.Classe) »
        description = getattr(test, "description", test.id())
        nom, _, reste = description.partition(" (")
        return reste.rstrip(")").rsplit(".", 1)[-1], nom

    def _noter(self, test, etat, message=""):
        debut = self._debut.pop(test.id(), None)
        duree = time.perf_counter() - debut if debut is not None else 0.0
        classe, nom = self._nommer(test)
        self.detail.append(
            {
                "id": test.id(),
                "classe": classe,
                "nom": nom,
                "duree": round(duree, 4),
                "etat": etat,
                "message": message,
            }
        )

    def addSuccess(self, test):
        super().addSuccess(test)
        self._noter(test, "ok")

    def addFailure(self, test, err):
        super().addFailure(test, err)
        self._noter(test, "echec", self._exc_info_to_string(err, test))

    def addError(self, test, err):
        super().addError(test, err)
        # Une erreur de setUpClass ou de setUpModule arrive sous la forme
        # d'un _ErrorHolder, sans méthode de test : on la note quand même.
        self._noter(test, "erreur", self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._noter(test, "ignore", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._noter(test, "ok")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._noter(test, "echec", "succès inattendu")


def executer(chemin, sortie):
    """Charge `chemin`, exécute ses tests, écrit le détail dans `sortie`.

    Rend le code de sortie : 0 si tout est vert."""
    chemin = os.path.abspath(chemin)
    sys.path[0] = os.path.dirname(chemin)
    sys.argv = [chemin]
    nom = os.path.splitext(os.path.basename(chemin))[0]
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    suite = unittest.defaultTestLoader.loadTestsFromModule(module)
    resultat = unittest.TextTestRunner(resultclass=Resultat).run(suite)
    with open(sortie, "w", encoding="utf-8") as fh:
        json.dump(resultat.detail, fh)
    return 0 if resultat.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(executer(sys.argv[1], sys.argv[2]))
