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

from script.forge.mirror import (  # noqa: E402
    Plan,
    clone_url,
    forge_name,
    parse_projects,
    plan,
)


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


class TestLAdresseDeClone(unittest.TestCase):
    """La jonction se normalise, parce que les manifestes ne le font pas."""

    def test_a_fetch_without_a_trailing_slash_still_joins(self):
        """Les URL de fetch d'un manifeste ne finissent pas toutes par une
        barre oblique — une sur vingt-neuf n'en porte pas. Concaténer
        donnerait « …/ORGANISATIONdepot.git », qui n'existe pas."""
        self.assertEqual(
            "https://exemple.invalid/ORG/outil.git",
            clone_url("https://exemple.invalid/ORG", "outil.git"),
        )

    def test_a_fetch_with_one_joins_the_same_way(self):
        self.assertEqual(
            "https://exemple.invalid/ORG/outil.git",
            clone_url("https://exemple.invalid/ORG/", "outil.git"),
        )

    def test_several_trailing_slashes_do_not_double(self):
        self.assertEqual(
            "https://exemple.invalid/ORG/outil.git",
            clone_url("https://exemple.invalid/ORG//", "outil.git"),
        )

    def test_a_leading_slash_on_the_name_does_not_double(self):
        self.assertEqual(
            "https://exemple.invalid/ORG/outil.git",
            clone_url("https://exemple.invalid/ORG/", "/outil.git"),
        )

    def test_the_name_keeps_its_git_suffix(self):
        """C'est l'URL de CLONE, pas le nom sur la forge : le tronquer
        viserait un dépôt qui n'existe pas en amont."""
        self.assertTrue(
            clone_url("https://exemple.invalid/o/", "outil.git").endswith(
                "outil.git"
            )
        )

    def test_a_missing_half_gives_nothing_rather_than_a_broken_url(self):
        """Une adresse à moitié bâtie ferait répondre la forge sans dire
        qu'il manque un remote."""
        self.assertEqual("", clone_url("", "outil.git"))
        self.assertEqual("", clone_url("https://exemple.invalid/", ""))
        self.assertEqual("", clone_url(None, None))


class TestLAnalyseDuManifeste(unittest.TestCase):
    """Elle prend du TEXTE : pure, donc vérifiable sans lire de fichier."""

    @staticmethod
    def xml(remotes, projets, defaut=None):
        r = "".join(
            f'<remote name="{n}" fetch="{u}"/>' for n, u in remotes.items()
        )
        d = f'<default remote="{defaut}"/>' if defaut else ""
        p = "".join(
            f'<project name="{n}"' + (f' remote="{rem}"' if rem else "") + "/>"
            for n, rem in projets
        )
        return f"<manifest>{r}{d}{p}</manifest>"

    def test_a_project_gets_its_remote_fetch(self):
        texte = self.xml(
            {"AMONT": "https://exemple.invalid/amont/"},
            [("outil.git", "AMONT")],
        )
        projets = parse_projects(texte)
        self.assertEqual(
            "https://exemple.invalid/amont/outil.git",
            projets[0]["clone_url"],
        )

    def test_the_remote_is_inherited_from_the_default(self):
        """UN SEUL projet sur neuf cents s'en sert dans ce dépôt, et c'est
        justement pour celui-là que l'ignorer donnerait une adresse vide."""
        texte = self.xml(
            {"AMONT": "https://exemple.invalid/amont/"},
            [("outil.git", None)],
            defaut="AMONT",
        )
        self.assertEqual(
            "https://exemple.invalid/amont/outil.git",
            parse_projects(texte)[0]["clone_url"],
        )

    def test_an_explicit_remote_wins_over_the_default(self):
        texte = self.xml(
            {
                "A": "https://exemple.invalid/a/",
                "B": "https://exemple.invalid/b/",
            },
            [("outil.git", "B")],
            defaut="A",
        )
        self.assertIn("/b/", parse_projects(texte)[0]["clone_url"])

    def test_an_unknown_remote_gives_no_address_rather_than_a_guess(self):
        texte = self.xml(
            {"A": "https://exemple.invalid/a/"}, [("outil.git", "JAMAIS-VU")]
        )
        self.assertEqual("", parse_projects(texte)[0]["clone_url"])

    def test_no_default_and_no_remote_gives_no_address(self):
        texte = self.xml(
            {"A": "https://exemple.invalid/a/"}, [("outil.git", None)]
        )
        self.assertEqual("", parse_projects(texte)[0]["clone_url"])

    def test_a_project_without_a_name_is_dropped(self):
        texte = (
            '<manifest><project path="x"/><project name="a.git"/></manifest>'
        )
        self.assertEqual(["a.git"], [p["name"] for p in parse_projects(texte)])

    def test_an_empty_manifest_is_an_empty_list(self):
        self.assertEqual([], parse_projects("<manifest/>"))

    def test_a_broken_xml_raises_rather_than_looking_empty(self):
        """« Aucun projet » et « manifeste tronqué » ne se corrigent pas
        pareil : rendre [] ferait passer le second pour le premier."""
        from xml.etree import ElementTree

        with self.assertRaises(ElementTree.ParseError):
            parse_projects("<manifest><project name=")

    def test_the_order_of_the_manifest_is_kept(self):
        texte = self.xml(
            {"A": "https://exemple.invalid/a/"},
            [("c.git", "A"), ("a.git", "A"), ("b.git", "A")],
        )
        self.assertEqual(
            ["c.git", "a.git", "b.git"],
            [p["name"] for p in parse_projects(texte)],
        )


class TestSurLesVraiesAdresses(unittest.TestCase):
    """Neuf cents projets réels : chacun doit avoir une adresse."""

    def setUp(self):
        import glob

        racine = os.path.normpath(
            os.path.join(os.path.dirname(__file__), "..")
        )
        self.fichiers = sorted(
            glob.glob(os.path.join(racine, "manifest/*.xml"))
        )
        if not self.fichiers:
            self.skipTest("aucun manifeste dans ce checkout")

    def tous(self):
        from xml.etree import ElementTree

        projets = []
        for fichier in self.fichiers:
            with open(fichier, encoding="utf-8") as poignee:
                try:
                    projets.extend(parse_projects(poignee.read()))
                except ElementTree.ParseError:
                    continue
        return projets

    def test_almost_every_real_project_gets_a_clone_url(self):
        """Le gros du parc doit avoir une adresse, sans quoi le miroir ne
        sert à rien — mais pas forcément TOUS : voir l'épreuve suivante."""
        projets = self.tous()
        avec = [p for p in projets if p["clone_url"]]
        self.assertGreater(len(avec), 0.99 * len(projets), len(projets))

    def test_an_empty_address_is_always_explained_by_the_manifest(self):
        """L'INVARIANT qui compte : l'analyseur ne perd jamais une adresse
        qu'il pouvait bâtir. Une adresse vide veut dire que le manifeste
        vise un « remote » qu'il ne déclare pas — ce que ce dépôt porte
        réellement, dans un manifeste d'une version dépréciée.

        Sans cet invariant, un « remote » mal lu se confondrait avec un
        manifeste fautif, et le miroir sauterait des projets en silence.
        """
        from xml.etree import ElementTree

        vus = 0
        for fichier in self.fichiers:
            with open(fichier, encoding="utf-8") as poignee:
                texte = poignee.read()
            try:
                racine = ElementTree.fromstring(texte)
                projets = parse_projects(texte)
            except ElementTree.ParseError:
                continue
            declares = {r.get("name") for r in racine.findall("remote")}
            defaut = racine.find("default")
            nom_defaut = defaut.get("remote") if defaut is not None else None
            par_nom = {
                p.get("name"): (p.get("remote") or nom_defaut)
                for p in racine.findall("project")
            }
            for projet in projets:
                if projet["clone_url"]:
                    continue
                vus += 1
                with self.subTest(fichier=fichier, nom=projet["name"]):
                    self.assertNotIn(par_nom.get(projet["name"]), declares)
        self.assertGreater(vus, 0, "aucun cas vide : l'invariant est muet")

    def test_no_clone_url_carries_a_doubled_or_missing_slash(self):
        for projet in self.tous():
            if not projet["clone_url"]:
                continue
            with self.subTest(nom=projet["name"]):
                sans_schema = projet["clone_url"].split("://", 1)[-1]
                self.assertNotIn("//", sans_schema)
                self.assertIn("/", sans_schema)

    def test_the_sweep_read_something(self):
        self.assertGreater(len(self.tous()), 100)


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
