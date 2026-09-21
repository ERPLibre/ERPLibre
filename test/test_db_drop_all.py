#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le chemin le plus large du dépôt, et ce qui l'ouvre désormais.

Sans aucun argument, ce script énumérait toutes les bases de l'instance et
les effaçait EN PARALLÈLE, sans une seule question. Son mode sûr était en
opt-in, et sa portée une heuristique de NOM — or le dépôt a mesuré qu'un nom
ne prouve rien.

CE QUI AUTORISE EST CE QUE LA BASE DIT D'ELLE-MÊME. Le filtre de nom
RESTREINT ce qu'on regarde ; il n'autorise plus rien.

Rien ici ne touche à PostgreSQL : le contrôle et l'exécution sont remplacés,
et un piège échoue si une base non prouvée atteint la commande d'effacement.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.database import db_drop_all as D  # noqa: E402
from script.database import drill_guard as G  # noqa: E402


class BancDEffacement(unittest.TestCase):
    def jouer(self, bases, verdicts, argv=(), drop_status=0):
        """Joue le script avec un inventaire et des verdicts de banc."""
        joues = []

        def faux_shell(cmd):
            joues.append(cmd)
            if "--list" in cmd:
                return 0, "\n".join(bases)
            return drop_status, "sortie de banc"

        def faux_inspect(nom, run_psql=None):
            return G.Inspection(verdicts[nom])

        vrai_argv = sys.argv
        sys.argv = ["db_drop_all.py", *argv]
        tampon = io.StringIO()
        try:
            with patch.object(D, "execute_shell", faux_shell), patch.object(
                D.drill_guard, "inspect", faux_inspect
            ), redirect_stdout(tampon):
                code = D.main()
        finally:
            sys.argv = vrai_argv
        drops = [c for c in joues if "--drop" in c]
        return code, tampon.getvalue(), (drops[0] if drops else "")


class TestSeuleUnePreuveOuvreLaPorte(BancDEffacement):
    def test_a_real_database_is_never_dropped(self):
        """Le cas qui compte : sans argument, tout partait."""
        code, vu, drop = self.jouer(
            ["une_base", "une_autre"],
            {"une_base": G.REAL, "une_autre": G.REAL},
        )
        self.assertEqual("", drop)
        self.assertIn("une_base", vu)
        self.assertNotEqual(0, code)

    def test_a_proven_drill_is_dropped(self):
        """Contrôle positif : tout refuser n'aiderait personne."""
        _code, _vu, drop = self.jouer(["exercice"], {"exercice": G.DRILL})
        self.assertIn("--drop --database exercice", drop)

    def test_the_unreadable_ones_are_kept_and_named(self):
        """Ce qu'on n'a pas pu lire n'est pas jetable."""
        code, vu, drop = self.jouer(["muette"], {"muette": G.UNREADABLE})
        self.assertEqual("", drop)
        self.assertIn("muette", vu)
        self.assertIn(G.UNREADABLE, vu)
        self.assertNotEqual(0, code)

    def test_the_good_ones_go_and_the_others_stay(self):
        _code, _vu, drop = self.jouer(
            ["exercice", "reelle"],
            {"exercice": G.DRILL, "reelle": G.REAL},
        )
        self.assertIn("exercice", drop)
        self.assertNotIn("reelle", drop)

    def test_a_check_that_falls_over_closes_the_door(self):
        """Un contrôle qui tombe ne doit pas ouvrir la porte qu'il tient."""

        def casse(_nom, run_psql=None):
            raise RuntimeError("psql introuvable")

        sys.argv = ["db_drop_all.py"]
        joues = []
        tampon = io.StringIO()
        with patch.object(
            D,
            "execute_shell",
            lambda cmd: joues.append(cmd) or (0, "une_base"),
        ), patch.object(D.drill_guard, "inspect", casse), redirect_stdout(
            tampon
        ):
            code = D.main()
        self.assertEqual([], [c for c in joues if "--drop" in c])
        self.assertNotEqual(0, code)


class TestLeNomNAutorisePlusRien(BancDEffacement):
    def test_a_name_that_looks_like_a_test_still_needs_the_proof(self):
        """L'heuristique de nom RESTREINT ce qu'on regarde ; elle
        n'autorise rien."""
        _code, _vu, drop = self.jouer(
            ["test_quelque_chose"],
            {"test_quelque_chose": G.REAL},
            argv=("--test_only",),
        )
        self.assertEqual("", drop)

    def test_the_restriction_still_narrows_what_is_looked_at(self):
        """Contrôle positif : le drapeau garde son effet de portée."""
        _code, _vu, drop = self.jouer(
            ["test_a", "autre"],
            {"test_a": G.DRILL, "autre": G.DRILL},
            argv=("--test_only",),
        )
        self.assertIn("test_a", drop)
        self.assertNotIn("autre", drop)

    def test_naming_a_database_does_not_authorise_it_either(self):
        _code, _vu, drop = self.jouer(
            ["reelle"], {"reelle": G.REAL}, argv=("--database", "reelle")
        )
        self.assertEqual("", drop)


class TestLePassageEnForce(BancDEffacement):
    def test_it_exists_and_it_is_said(self):
        """Une destruction qu'on s'autorise sans preuve doit rester lisible
        dans le journal de ce qui s'est passé."""
        _code, vu, drop = self.jouer(
            ["reelle"], {"reelle": G.REAL}, argv=("--force",)
        )
        self.assertIn("reelle", drop)
        self.assertIn("force", vu.lower())

    def test_without_it_nothing_is_forced(self):
        _code, vu, drop = self.jouer(["reelle"], {"reelle": G.REAL})
        self.assertEqual("", drop)
        self.assertNotIn("force", vu.lower())


class TestIlNAnnoncePlusCeQuIlNAPasFait(BancDEffacement):
    def test_a_failed_drop_is_not_announced_as_a_deletion(self):
        """« Database deleted » était imprimé quel que soit le résultat."""
        code, vu, _drop = self.jouer(
            ["exercice"], {"exercice": G.DRILL}, drop_status=1
        )
        self.assertNotIn("Database deleted", vu)
        self.assertNotEqual(0, code)

    def test_a_successful_drop_is_announced(self):
        code, vu, _drop = self.jouer(["exercice"], {"exercice": G.DRILL})
        self.assertIn("Database deleted", vu)
        self.assertEqual(0, code)

    def test_nothing_to_drop_says_so_rather_than_claiming_success(self):
        code, vu, _drop = self.jouer(["reelle"], {"reelle": G.REAL})
        self.assertIn("Aucune base", vu)
        self.assertNotEqual(0, code)


if __name__ == "__main__":
    unittest.main()
