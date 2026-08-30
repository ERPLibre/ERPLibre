#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le trou dans un manifeste, et ce qui le distingue d'une absence normale.

Beaucoup de dépôts n'ont pas de branche pour toutes les versions d'Odoo.
Les signaler tous ferait 46 % de bruit — mesuré : 35 trous, 19 vraies
omissions. L'outil ne vaut que par ce tri, et c'est donc lui qu'on teste.

Aucun test ne touche au réseau : `judge` reçoit son lecteur d'amont, et
les tests lui en donnent un qui répond de mémoire. Un test qui appelle
GitHub échoue dans un train, et l'on finit par ne plus le lancer.
"""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from script.analyse import check_manifest_gaps as gaps  # noqa: E402

MANIFESTE = """<?xml version="1.0" encoding="UTF-8"?>
<manifest>
  <remote name="OCA" fetch="https://github.com/OCA/" />
  <remote name="autre" fetch="https://example.org/eq/" />
%s
</manifest>
"""

PROJET = """  <project
      name="%s"
      path="odoo%s/addons/%s"
      remote="%s"
      revision="%s"
      groups="addons,odoo%s"
  />"""


def projet(nom, version, remote="OCA"):
    court = nom.replace(".git", "")
    return PROJET % (nom, version, court, remote, version, version)


class Base(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, self.dossier)

    def ecrire(self, version, noms, remote="OCA"):
        corps = "\n".join(projet(n, version, remote) for n in noms)
        chemin = os.path.join(
            self.dossier, "git_manifest_odoo%s.xml" % version
        )
        with io.open(chemin, "w", encoding="utf-8") as handle:
            handle.write(MANIFESTE % corps)
        return chemin

    def trous(self):
        ordre = [v for v, _ in gaps.versions(self.dossier)]
        return gaps.gaps(gaps.declarations(self.dossier), ordre)


class TestReadingTheManifests(Base):
    def test_the_versions_come_from_the_files_not_a_list(self):
        # Une version ajoutée au dépôt doit entrer dans l'analyse sans
        # qu'on pense à toucher le code.
        for v in ("12.0", "14.0", "18.0"):
            self.ecrire(v, ["a.git"])
        self.assertEqual(
            ["12.0", "14.0", "18.0"],
            [v for v, _ in gaps.versions(self.dossier)],
        )

    def test_ten_comes_after_nine_not_before(self):
        # Trier des versions comme du texte met « 10.0 » avant « 9.0 ».
        self.assertLess(gaps.rang("9.0"), gaps.rang("10.0"))

    def test_the_dev_manifests_are_left_out(self):
        # Ils COMPLÈTENT le principal : un dépôt qui n'est que là n'a
        # aucune raison d'être partout, et le compter créerait des trous
        # imaginaires dans toutes les versions.
        self.ecrire("14.0", ["a.git"])
        with io.open(
            os.path.join(self.dossier, "git_manifest_odoo14.0_dev.xml"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write(MANIFESTE % projet("b.git", "14.0"))
        self.assertEqual(["14.0"], [v for v, _ in gaps.versions(self.dossier)])

    def test_the_url_is_rebuilt_from_its_remote(self):
        self.ecrire("14.0", ["donation.git"])
        dct = gaps.declarations(self.dossier)
        self.assertEqual(
            "https://github.com/OCA/donation.git",
            dct["donation.git"]["14.0"],
        )

    def test_an_unparsable_manifest_does_not_stop_the_others(self):
        self.ecrire("14.0", ["a.git"])
        with io.open(
            os.path.join(self.dossier, "git_manifest_odoo16.0.xml"),
            "w",
            encoding="utf-8",
        ) as handle:
            handle.write("<manifest><project")
        self.assertIn("a.git", gaps.declarations(self.dossier))


class TestWhatCountsAsAHole(Base):
    def test_absent_in_the_middle_is_a_hole(self):
        self.ecrire("16.0", ["sale-channel.git"])
        self.ecrire("17.0", [])
        self.ecrire("18.0", ["sale-channel.git"])
        trous = self.trous()
        self.assertEqual(1, len(trous))
        self.assertEqual(["17.0"], trous[0][2])

    def test_absent_before_the_first_is_not_a_hole(self):
        # Un dépôt né en 16 n'a rien à faire en 12 ; l'exiger crierait
        # sur presque tout le fichier.
        self.ecrire("12.0", [])
        self.ecrire("16.0", ["neuf.git"])
        self.ecrire("18.0", ["neuf.git"])
        self.assertEqual([], self.trous())

    def test_absent_after_the_last_is_not_a_hole(self):
        # Un dépôt abandonné après la 14 non plus.
        self.ecrire("12.0", ["vieux.git"])
        self.ecrire("14.0", ["vieux.git"])
        self.ecrire("18.0", [])
        self.assertEqual([], self.trous())

    def test_a_single_appearance_is_never_a_hole(self):
        self.ecrire("12.0", [])
        self.ecrire("14.0", ["seul.git"])
        self.ecrire("18.0", [])
        self.assertEqual([], self.trous())

    def test_several_missing_steps_are_all_named(self):
        self.ecrire("12.0", ["long.git"])
        self.ecrire("13.0", [])
        self.ecrire("14.0", [])
        self.ecrire("15.0", [])
        self.ecrire("16.0", ["long.git"])
        self.assertEqual(["13.0", "14.0", "15.0"], self.trous()[0][2])


class TestSettlingAHole(Base):
    """Le tri qui fait tout l'intérêt de l'outil."""

    def setUp(self):
        super().setUp()
        self.ecrire("16.0", ["a.git", "b.git"])
        self.ecrire("17.0", [])
        self.ecrire("18.0", ["a.git", "b.git"])
        self.appels = []

    def lecteur(self, reponses):
        def lire(url):
            self.appels.append(url)
            return reponses.get(url.rsplit("/", 1)[-1])

        return lire

    def test_without_asking_nothing_is_settled(self):
        juges = gaps.judge(self.trous(), verifier=False)
        self.assertEqual({"inconnu"}, {j[3] for j in juges})
        self.assertEqual([], self.appels)

    def test_a_branch_upstream_makes_it_an_omission(self):
        juges = gaps.judge(
            self.trous(),
            verifier=True,
            lecteur=self.lecteur({"a.git": {"17.0"}, "b.git": {"17.0"}}),
        )
        self.assertEqual({"omission"}, {j[3] for j in juges})

    def test_no_branch_upstream_makes_it_legitimate(self):
        juges = gaps.judge(
            self.trous(),
            verifier=True,
            lecteur=self.lecteur({"a.git": {"16.0", "18.0"}, "b.git": set()}),
        )
        self.assertEqual({"legitime"}, {j[3] for j in juges})

    def test_unreachable_is_not_absolution(self):
        # None dit « je n'ai pas pu demander », l'ensemble vide dit « il
        # n'y en a pas ». Les confondre transformerait une coupure réseau
        # en rapport tout vert.
        juges = gaps.judge(
            self.trous(),
            verifier=True,
            lecteur=self.lecteur({"a.git": None, "b.git": None}),
        )
        self.assertEqual({"inconnu"}, {j[3] for j in juges})

    def test_each_repository_is_asked_once(self):
        gaps.judge(
            self.trous(),
            verifier=True,
            lecteur=self.lecteur({"a.git": set(), "b.git": set()}),
        )
        self.assertEqual(len(self.appels), len(set(self.appels)))
        self.assertEqual(2, len(self.appels))


class TestAskingTheRemote(unittest.TestCase):
    """La seule fonction qui parle au réseau — bouchonnée, jamais appelée."""

    def setUp(self):
        self.vrai = gaps.subprocess
        self.addCleanup(setattr, gaps, "subprocess", self.vrai)

    def repondre(self, sortie="", code=0, leve=None):
        essai = self

        class Faux:
            @staticmethod
            def run(argv, capture_output=None, text=None, timeout=None):
                essai.argv = argv
                if leve:
                    raise leve
                return type("R", (), {"returncode": code, "stdout": sortie})

        Faux.SubprocessError = self.vrai.SubprocessError
        Faux.TimeoutExpired = self.vrai.TimeoutExpired
        gaps.subprocess = Faux

    def test_no_url_asks_nothing_and_settles_nothing(self):
        # Sans URL on ne peut pas demander ; rendre un ensemble vide
        # dirait « l'amont n'a pas la branche », ce qu'on ignore.
        self.repondre()
        self.assertIsNone(gaps.branches(""))
        self.assertFalse(hasattr(self, "argv"))

    def test_only_version_branches_are_kept(self):
        # « master » et « main » ne sont pas des paliers d'Odoo.
        self.repondre(
            "abc\trefs/heads/16.0\n"
            "def\trefs/heads/master\n"
            "012\trefs/heads/17.0\n"
            "345\trefs/heads/feature/x\n"
        )
        self.assertEqual({"16.0", "17.0"}, gaps.branches("https://x/y.git"))

    def test_a_failed_call_is_not_settled(self):
        self.repondre(code=128)
        self.assertIsNone(gaps.branches("https://x/y.git"))

    def test_a_timeout_is_not_settled(self):
        self.repondre(leve=self.vrai.TimeoutExpired("git", 1))
        self.assertIsNone(gaps.branches("https://x/y.git"))

    def test_a_missing_git_is_not_settled(self):
        self.repondre(leve=OSError("git introuvable"))
        self.assertIsNone(gaps.branches("https://x/y.git"))

    def test_a_repository_with_no_version_branch_is_settled_as_empty(self):
        # Là, on a DEMANDÉ et la réponse est « aucune » : c'est un
        # verdict, pas une ignorance.
        self.repondre("abc\trefs/heads/master\n")
        self.assertEqual(set(), gaps.branches("https://x/y.git"))

    def test_it_only_reads_never_clones(self):
        self.repondre("")
        gaps.branches("https://x/y.git")
        self.assertEqual(
            ["git", "ls-remote", "--heads", "https://x/y.git"], self.argv
        )


class TestTheReport(Base):
    def rapport(self, juges, verifie=True):
        return gaps.render(juges, verifie, colour=False)

    def test_an_omission_names_the_repository_and_the_step(self):
        texte = self.rapport(
            [("sale-channel.git", ["17.0"], ["17.0"], "omission")]
        )
        self.assertIn("sale-channel.git", texte)
        self.assertIn("17.0", texte)

    def test_an_omission_says_what_to_do(self):
        texte = self.rapport([("a.git", ["17.0"], ["17.0"], "omission")])
        self.assertIn("git_manifest_odoo", texte)

    def test_a_legitimate_hole_is_counted_not_listed(self):
        # Seize lignes de « tout va bien » noieraient les dix-neuf qui
        # comptent.
        texte = self.rapport([("a.git", ["13.0"], [], "legitime")])
        self.assertNotIn("a.git", texte)
        self.assertIn("1", texte)

    def test_offline_says_it_did_not_ask(self):
        texte = self.rapport(
            [("a.git", ["17.0"], [], "inconnu")], verifie=False
        )
        self.assertIn(gaps.t("not asked: run with --upstream"), texte)

    def test_unreachable_does_not_read_like_offline(self):
        texte = self.rapport(
            [("a.git", ["17.0"], [], "inconnu")], verifie=True
        )
        self.assertIn(gaps.t("upstream unreachable"), texte)

    def test_nothing_at_all_is_stated(self):
        self.assertIn(
            gaps.t("Every repository is declared without a hole."),
            self.rapport([]),
        )


class TestTheCommand(Base):
    def lancer(self, argv):
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = gaps.main(argv)
        return code, tampon.getvalue()

    def test_a_missing_directory_is_a_tool_failure(self):
        code, _ = self.lancer(
            ["--manifest-dir", os.path.join(self.dossier, "absent")]
        )
        self.assertEqual(2, code)

    def test_no_hole_exits_zero(self):
        self.ecrire("16.0", ["a.git"])
        self.ecrire("18.0", ["a.git"])
        code, _ = self.lancer(["--manifest-dir", self.dossier, "--no-color"])
        self.assertEqual(0, code)

    def test_an_unsettled_hole_alone_does_not_exit_one(self):
        # Sans --upstream on ne SAIT pas : sortir 1 ferait échouer une
        # chaîne d'intégration sur une question qu'on n'a pas posée.
        self.ecrire("16.0", ["a.git"])
        self.ecrire("17.0", [])
        self.ecrire("18.0", ["a.git"])
        code, texte = self.lancer(
            ["--manifest-dir", self.dossier, "--no-color"]
        )
        self.assertEqual(0, code)
        self.assertIn("a.git", texte)

    def test_the_json_carries_the_state_of_each_hole(self):
        import json

        self.ecrire("16.0", ["a.git"])
        self.ecrire("17.0", [])
        self.ecrire("18.0", ["a.git"])
        _code, texte = self.lancer(["--manifest-dir", self.dossier, "--json"])
        dct = json.loads(texte)
        self.assertFalse(dct["checked_upstream"])
        self.assertEqual("a.git", dct["gaps"][0]["repository"])
        self.assertEqual("inconnu", dct["gaps"][0]["state"])


class TestAgainstTheRealManifests(unittest.TestCase):
    """Sur le vrai dossier — sans réseau, donc sans trancher."""

    def test_the_repository_manifests_parse(self):
        lst = gaps.versions()
        self.assertGreaterEqual(len(lst), 7)
        dct = gaps.declarations()
        self.assertGreater(len(dct), 100)

    def test_development_is_declared_at_every_step_it_spans(self):
        # Les paliers 13 et 15 lui manquaient, et une migration 12 → 18
        # les traverse tous les deux.
        dct = gaps.declarations()
        presentes = set(dct.get("development.git", {}))
        for version in (
            "12.0",
            "13.0",
            "14.0",
            "15.0",
            "16.0",
            "17.0",
            "18.0",
        ):
            self.assertIn(version, presentes, version)


if __name__ == "__main__":
    unittest.main()
