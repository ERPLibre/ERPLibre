#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le rapprochement manifeste ↔ forge, et les trois pièges de nommage.

Ni forge, ni réseau. Le module reçoit deux listes de noms et rend un plan :
tout se vérifie sur deux cents noms depuis une station.

LES TROIS PIÈGES, chacun coûteux dans un sens différent.

« .GIT ». Le manifeste écrit « account-analytic.git », la forge nomme
« account-analytic ». Ne pas le retirer fait paraître TOUS les dépôts
manquants. Le retirer avec `rstrip` est pire : `rstrip` enlève un ENSEMBLE
de caractères et non un suffixe.

LA CASSE. Gitea et Forgejo tiennent l'unicité sans égard à la casse ; une
comparaison sensible à la casse ferait recréer un dépôt présent, et la
création échouerait en 409 sur toute la liste.

LES COLLISIONS. Deux entrées qui se réduisent au même nom de forge ne
peuvent y coexister. Les taire laisserait un miroir incomplet en silence.

Les noms qui illustrent un piège sont INVENTÉS : « digit.git » et
« tigit.git » n'existent nulle part dans ce dépôt, et un nom réel figé dans
une épreuve y reste pour toujours.
"""

import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.forge.mirror import Plan, forge_name, plan  # noqa: E402


class TestLeNomQuePorteLaForge(unittest.TestCase):
    def test_the_git_suffix_goes(self):
        self.assertEqual(
            "account-analytic", forge_name("account-analytic.git")
        )

    def test_rstrip_would_eat_the_name_and_removesuffix_does_not(self):
        """LE PIÈGE. `rstrip(".git")` enlève tout caractère final pris dans
        {'.', 'g', 'i', 't'} : « digit.git » deviendrait « d » et
        « tigit.git » la chaîne vide. Ces deux noms sont inventés."""
        self.assertEqual("digit", forge_name("digit.git"))
        self.assertEqual("tigit", forge_name("tigit.git"))
        # Ce que la forme fautive aurait rendu, pour que l'épreuve dise
        # POURQUOI elle existe et pas seulement ce qu'elle attend.
        self.assertEqual("d", "digit.git".rstrip(".git"))
        self.assertEqual("", "tigit.git".rstrip(".git"))

    def test_a_dot_that_is_not_the_suffix_stays(self):
        """Un nom peut contenir un point sans finir par « .git » : c'est
        son nom, et le tronquer créerait un dépôt qui n'est pas le bon."""
        self.assertEqual("whisper.cpp", forge_name("whisper.cpp"))
        self.assertEqual("a.b.c", forge_name("a.b.c"))

    def test_only_the_last_segment_counts(self):
        self.assertEqual("web", forge_name("OCA/web.git"))
        self.assertEqual("web", forge_name("un/deux/web"))

    def test_a_trailing_slash_does_not_empty_it(self):
        self.assertEqual("web", forge_name("OCA/web/"))

    def test_surrounding_space_is_dropped(self):
        self.assertEqual("web", forge_name("  web.git  "))

    def test_nothing_gives_nothing_and_does_not_crash(self):
        self.assertEqual("", forge_name(""))
        self.assertEqual("", forge_name(None))


class TestLEcart(unittest.TestCase):
    def test_what_is_absent_is_to_create(self):
        resultat = plan(["a.git", "b.git"], ["a"])
        self.assertEqual(("b",), resultat.to_create)
        self.assertEqual(("a",), resultat.already)

    def test_the_case_does_not_make_a_repository_look_missing(self):
        """Gitea tient l'unicité sans égard à la casse : recréer ferait
        échouer toute la liste en 409."""
        resultat = plan(["Server-Tools.git"], ["server-tools"])
        self.assertEqual((), resultat.to_create)
        self.assertEqual(("Server-Tools",), resultat.already)

    def test_a_full_name_from_the_forge_matches_too(self):
        """La forge rend « name » ou « full_name » selon l'appel ;
        l'appelant n'a pas à choisir."""
        resultat = plan(["outil.git"], ["proprietaire/outil"])
        self.assertEqual((), resultat.to_create)

    def test_the_created_name_carries_no_git_suffix(self):
        """Le créer avec son suffixe donnerait « outil.git » sur la forge,
        et le miroir suivant le trouverait encore manquant."""
        resultat = plan(["outil.git"], [])
        self.assertEqual(("outil",), resultat.to_create)

    def test_the_manifest_order_is_kept(self):
        """Un plan qu'on relit se lit dans l'ordre où on l'a écrit."""
        resultat = plan(["c.git", "a.git", "b.git"], [])
        self.assertEqual(("c", "a", "b"), resultat.to_create)

    def test_a_repeated_entry_is_planned_once(self):
        """Deux manifestes fusionnés portent les mêmes projets ; le créer
        deux fois échouerait la seconde fois."""
        resultat = plan(["a.git", "a.git", "A.git"], [])
        self.assertEqual(("a",), resultat.to_create)

    def test_an_empty_name_is_ignored_and_not_created(self):
        """« Créer un dépôt sans nom » n'a pas de sens."""
        resultat = plan(["", None, "  ", "a.git"], [])
        self.assertEqual(("a",), resultat.to_create)

    def test_a_forge_entry_without_a_name_does_not_hide_anything(self):
        resultat = plan(["a.git"], ["", None])
        self.assertEqual(("a",), resultat.to_create)

    def test_a_forge_richer_than_the_manifest_changes_nothing(self):
        """Un dépôt que la forge porte en plus n'est pas notre affaire :
        le plan CRÉE, il ne supprime jamais."""
        resultat = plan(["a.git"], ["a", "autre-chose", "encore"])
        self.assertEqual((), resultat.to_create)
        self.assertEqual(("a",), resultat.already)

    def test_both_lists_empty_is_an_empty_plan(self):
        self.assertEqual(Plan((), (), {}), plan([], []))
        self.assertEqual(Plan((), (), {}), plan(None, None))


class TestLesCollisions(unittest.TestCase):
    """Deux entrées qui se réduisent au même nom ne peuvent coexister."""

    def test_two_entries_that_collide_are_named(self):
        resultat = plan(["OCA/web.git", "autre/web.git"], [])
        self.assertIn("web", resultat.collisions)
        self.assertEqual(
            ["OCA/web.git", "autre/web.git"], resultat.collisions["web"]
        )

    def test_a_collision_across_case_is_seen_too(self):
        resultat = plan(["OCA/Web.git", "autre/web.git"], [])
        self.assertEqual(1, len(resultat.collisions))

    def test_only_one_of_them_is_planned(self):
        """Créer les deux ferait échouer le second en 409 ; le plan en
        retient un et NOMME le conflit pour que l'appelant tranche."""
        resultat = plan(["OCA/web.git", "autre/web.git"], [])
        self.assertEqual(("web",), resultat.to_create)

    def test_no_collision_when_names_differ(self):
        """Contrôle positif : tout déclarer en collision ne dirait rien."""
        self.assertEqual({}, plan(["a.git", "b.git"], []).collisions)

    def test_a_repeated_identical_entry_is_not_a_collision(self):
        """Le même projet listé deux fois n'est pas un conflit de nommage :
        le signaler ferait crier au loup sur deux manifestes fusionnés."""
        self.assertEqual({}, plan(["a.git", "a.git"], []).collisions)

    def test_a_collision_is_reported_even_when_present(self):
        """Elle reste vraie et reste un problème : un seul des deux projets
        est miroité, et le miroir est incomplet en silence."""
        resultat = plan(["OCA/web.git", "autre/web.git"], ["web"])
        self.assertEqual((), resultat.to_create)
        self.assertIn("web", resultat.collisions)


class TestSurLesVraisManifestes(unittest.TestCase):
    """Le contrôle qui compte : deux cents noms réels, pas trois inventés.

    Lit les manifestes du dépôt. Ce qui est éprouvé n'est PAS leur contenu —
    il change à chaque version d'Odoo — mais que le rapprochement tient sur
    la forme réelle des noms.
    """

    @staticmethod
    def noms_declares():
        import glob
        import xml.etree.ElementTree as ET

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        noms = []
        for fichier in sorted(
            glob.glob(os.path.join(racine, "manifest/*.xml"))
        ):
            try:
                arbre = ET.parse(fichier)
            except ET.ParseError:
                continue
            noms.extend(
                p.get("name") for p in arbre.getroot().findall("project")
            )
        return [n for n in noms if n]

    def setUp(self):
        self.noms = self.noms_declares()
        if not self.noms:
            self.skipTest("aucun manifeste lisible dans ce checkout")

    def test_an_empty_forge_needs_every_one_of_them(self):
        resultat = plan(self.noms, [])
        self.assertEqual(
            len(set(n.lower() for n in map(forge_name, self.noms))),
            len(resultat.to_create),
        )
        self.assertEqual((), resultat.already)

    def test_a_second_pass_creates_nothing(self):
        """LE contrôle du rapprochement : rejouer sur ce qu'on vient de
        créer doit être vide. Un suffixe mal retiré le ferait tout
        recréer, et le dire ici coûte moins qu'une forge à nettoyer."""
        premier = plan(self.noms, [])
        second = plan(self.noms, list(premier.to_create))
        self.assertEqual((), second.to_create, second.to_create[:5])

    def test_no_planned_name_carries_the_suffix(self):
        for nom in plan(self.noms, []).to_create:
            with self.subTest(nom=nom):
                self.assertFalse(nom.endswith(".git"), nom)
                self.assertTrue(nom, "un nom vide serait un dépôt sans nom")

    def test_a_forge_answering_full_names_matches_too(self):
        premier = plan(self.noms, [])
        avec_proprietaire = [f"proprietaire/{n}" for n in premier.to_create]
        self.assertEqual((), plan(self.noms, avec_proprietaire).to_create)


if __name__ == "__main__":
    unittest.main()
