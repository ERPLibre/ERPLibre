#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Exécute un fichier de tests et note chaque test : son résultat, sa durée.

    unit_file.py FICHIER SORTIE.json [--tranche K/N] [-k MOTIF]...
                 [--ordre-aleatoire[=GRAINE]]

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

`-k MOTIF` filtre comme celui d'unittest : un MOTIF sans « * » devient
« *MOTIF* », comparé (casse comprise) au nom complet module.Classe.méthode ;
plusieurs -k s'additionnent. Le fichier lui-même ne peut pas recevoir -k :
il remplace sys.argv à l'import, avant que unittest.main() ne le lise.

`--ordre-aleatoire=GRAINE` mélange l'ordre des classes, puis celui des
tests de chaque classe ; les tests d'une classe restent groupés, si bien
que sa préparation (setUpClass) ne tourne qu'une fois. Pour une même graine
l'ordre est le même : il se rejoue. Sans graine, une est tirée ; dans les
deux cas elle est imprimée. Le mélange précède la tranche : toutes les
tranches d'un fichier, mélangées par la même graine, se partagent ses tests
sans recouvrement.

Une sélection que -k ou la tranche rend vide réussit : un passage -k sur
toute la suite ne compte pas comme échecs les fichiers sans test qui
corresponde.
"""

import argparse
import importlib.util
import json
import os
import random
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

    def addSubTest(self, test, subtest, err):
        super().addSubTest(test, subtest, err)
        # Un sous-test en échec ne passe ni par addFailure ni par addError,
        # et son test ne reçoit alors aucun verdict : sans cette note, le
        # test disparaîtrait du détail au lieu d'y paraître en échec.
        if err is not None:
            etat = "erreur"
            if issubclass(err[0], test.failureException):
                etat = "echec"
            self._noter(subtest, etat, self._exc_info_to_string(err, test))

    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self._noter(test, "ignore", reason)

    def addExpectedFailure(self, test, err):
        super().addExpectedFailure(test, err)
        self._noter(test, "ok")

    def addUnexpectedSuccess(self, test):
        super().addUnexpectedSuccess(test)
        self._noter(test, "echec", "succès inattendu")


def aplatir(suite):
    """Les tests de `suite`, dans l'ordre où unittest les lancerait."""
    for element in suite:
        if isinstance(element, unittest.TestSuite):
            yield from aplatir(element)
        else:
            yield element


def tranche(suite, rang, nombre):
    """Les tests de rang `rang` modulo `nombre`, dans leur ordre d'origine.

    Le rang alterne d'un test au suivant, si bien que des tests lents qui
    se suivent se répartissent entre les tranches. L'ordre d'origine garde
    contigus les tests d'une même classe : unittest ne rejoue pas sa
    préparation de classe entre deux d'entre eux."""
    return unittest.TestSuite(
        test
        for indice, test in enumerate(aplatir(suite))
        if indice % nombre == rang
    )


def motif_unittest(motif):
    """Le motif fnmatch que `python -m unittest -k MOTIF` en tire."""
    return motif if "*" in motif else f"*{motif}*"


def melanger(suite, graine):
    """Les tests de `suite` dans un ordre tiré de `graine`, déterministe.

    Les tests sont groupés par classe, dans l'ordre de première apparition
    de la classe ; l'ordre des groupes est mélangé, puis celui des tests
    de chaque groupe. Une graine texte donne le même tirage d'un processus
    à l'autre (random.Random la hache sans dépendre de PYTHONHASHSEED)."""
    groupes = {}
    for test in aplatir(suite):
        groupes.setdefault(type(test), []).append(test)
    tirage = random.Random(str(graine))
    ordre = list(groupes.values())
    tirage.shuffle(ordre)
    for tests in ordre:
        tirage.shuffle(tests)
    return unittest.TestSuite(test for tests in ordre for test in tests)


def executer(chemin, sortie, rang=None, nombre=None, motifs=(), graine=None):
    """Charge `chemin`, exécute ses tests, écrit le détail dans `sortie`.

    `motifs` filtre les tests comme -k d'unittest (voir `motif_unittest`) ;
    `graine` mélange leur ordre (voir `melanger`) ; avec `rang` et
    `nombre`, seule cette tranche s'exécute (voir `tranche`). Une sélection
    vidée par un filtre réussit. Rend le code de sortie : 0 si tout est
    vert."""
    chemin = os.path.abspath(chemin)
    sys.path[0] = os.path.dirname(chemin)
    sys.argv = [chemin]
    nom = os.path.splitext(os.path.basename(chemin))[0]
    spec = importlib.util.spec_from_file_location(nom, chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    chargeur = unittest.TestLoader()
    if motifs:
        chargeur.testNamePatterns = [motif_unittest(m) for m in motifs]
    suite = chargeur.loadTestsFromModule(module)
    if graine is not None:
        suite = melanger(suite, graine)
    if nombre:
        suite = tranche(suite, rang, nombre)
    if (nombre or motifs) and not suite.countTestCases():
        # unittest rend 5 sans test ; la sélection vide, elle, est réussie.
        print("Ran 0 tests in 0.000s\n\nOK", file=sys.stderr)
        with open(sortie, "w", encoding="utf-8") as fh:
            json.dump([], fh)
        return 0
    resultat = unittest.TextTestRunner(resultclass=Resultat).run(suite)
    with open(sortie, "w", encoding="utf-8") as fh:
        json.dump(resultat.detail, fh)
    return 0 if resultat.wasSuccessful() else 1


def analyser(arguments):
    """Les options de la ligne de commande ; --tranche K/N donne
    (rang, nombre), --ordre-aleatoire sans valeur tire une graine."""
    parser = argparse.ArgumentParser(prog="unit_file.py")
    parser.add_argument("chemin")
    parser.add_argument("sortie")
    parser.add_argument("--tranche", metavar="K/N")
    parser.add_argument(
        "-k", dest="motifs", action="append", default=[], metavar="MOTIF"
    )
    parser.add_argument(
        "--ordre-aleatoire",
        dest="graine",
        nargs="?",
        const="",
        default=None,
        metavar="GRAINE",
    )
    args = parser.parse_args(arguments)
    args.rang = args.nombre = None
    if args.tranche:
        args.rang, args.nombre = (int(x) for x in args.tranche.split("/"))
    if args.graine == "":
        args.graine = str(random.SystemRandom().randrange(1, 1_000_000))
    return args


if __name__ == "__main__":
    args = analyser(sys.argv[1:])
    if args.graine is not None:
        # Sur la sortie d'erreur, avec le reste du compte rendu d'unittest.
        print(
            f"Ordre aléatoire, graine {args.graine} : "
            f"--ordre-aleatoire={args.graine} le rejoue",
            file=sys.stderr,
        )
    sys.exit(
        executer(
            args.chemin,
            args.sortie,
            args.rang,
            args.nombre,
            args.motifs,
            args.graine,
        )
    )
