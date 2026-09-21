#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Effacer les préférences : ce qu'on annonce doit être ce qu'on sait.

Le compte venait de la LECTURE, et la lecture retombe sur {} pour un
fichier absent comme pour un fichier tronqué. Sur le second, l'écran
annonçait « (0) » — « il n'y avait rien » — pendant que l'écriture
REMPLAÇAIT un fichier plein. Et l'écriture, elle, pouvait échouer en
silence : le nombre s'imprimait quand même, sur un fichier intact.

Aucune préférence de l'utilisateur n'est touchée : le chemin du fichier est
déplacé dans un temporaire.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo import todo_prefs as P  # noqa: E402


class CasDePrefs(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.fichier = Path(self.tmp.name) / "todo_prefs.json"
        correctif = patch.object(P, "_path", lambda: self.fichier)
        correctif.start()
        self.addCleanup(correctif.stop)

    def ecrire(self, texte):
        self.fichier.write_text(texte)


class TestUnFichierLisible(CasDePrefs):
    def test_it_counts_what_it_erased(self):
        self.ecrire(json.dumps({"a": 1, "b": 2, "c": 3}))
        self.assertEqual((P.EFFACE, 3), P.reset())

    def test_an_absent_file_is_really_nothing(self):
        """Contrôle : « il n'y avait rien » reste une réponse valable, et
        c'est justement celle qu'il ne faut pas donner par erreur."""
        self.assertEqual((P.EFFACE, 0), P.reset())

    def test_the_file_is_empty_afterwards(self):
        self.ecrire(json.dumps({"a": 1}))
        P.reset()
        self.assertEqual({}, json.loads(self.fichier.read_text()))


class TestUnFichierQuiNeSeRelitPas(CasDePrefs):
    """Le défaut lui-même : tronqué, il rendait « (0) » sur une
    destruction."""

    def test_a_truncated_file_refuses_the_count(self):
        self.ecrire('{"a": 1, "b":')
        verdict, combien = P.reset()
        self.assertEqual(P.EFFACE_SANS_COMPTE, verdict)
        self.assertEqual(0, combien)

    def test_a_json_that_is_not_an_object_refuses_it_too(self):
        """Une liste se relit sans erreur et n'est pas des préférences :
        la compter à zéro dirait la même chose de fausse."""
        self.ecrire("[1, 2, 3]")
        self.assertEqual(P.EFFACE_SANS_COMPTE, P.reset()[0])

    def test_it_is_erased_all_the_same(self):
        """On n'ABANDONNE pas : le fichier illisible est bien remplacé, ce
        qui est le geste demandé. Seul le compte est refusé."""
        self.ecrire('{"a": 1, "b":')
        P.reset()
        self.assertEqual({}, json.loads(self.fichier.read_text()))


class TestUneEcritureQuiEchoue(CasDePrefs):
    def test_a_write_that_fails_is_never_announced_as_a_reset(self):
        self.ecrire(json.dumps({"a": 1}))

        def refuse(*_a, **_k):
            raise OSError("read-only")

        with patch.object(Path, "write_text", refuse):
            self.assertEqual((P.ECHEC_ECRITURE, 0), P.reset())
        # Le fichier est INTACT : c'est ce que le verdict promet.
        self.assertEqual({"a": 1}, json.loads(self.fichier.read_text()))


class TestLeVocabulaireEstClos(unittest.TestCase):
    def test_the_three_verdicts_are_distinct(self):
        """Deux verdicts confondus rendraient l'un des trois écrans
        inatteignable, sans que rien ne le dise."""
        self.assertEqual(
            3, len({P.EFFACE, P.EFFACE_SANS_COMPTE, P.ECHEC_ECRITURE})
        )

    def test_the_menu_renders_every_one_of_them(self):
        """Un verdict sans branche retomberait sur le « sinon », qui
        annonce un succès chiffré."""
        import inspect

        from script.todo.todo import TODO

        source = inspect.getsource(TODO.prompt_configuration)
        for nom in ("ECHEC_ECRITURE", "EFFACE_SANS_COMPTE"):
            self.assertIn(nom, source)


if __name__ == "__main__":
    unittest.main()
