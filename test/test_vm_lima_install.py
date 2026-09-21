#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Acquérir l'outil : version épinglée, somme vérifiée, refus par défaut.

Ce qu'on refuse de faire est le sujet. Demander « la dernière version » à une
forge, la télécharger sans authentifier la réponse et l'exécuter, c'est
confier à quiconque se place sur le trajet le droit de choisir ce qui tourne
sur la machine — un binaire qui lancera ensuite des VM et recevra des
secrets.

Chaque épreuve de refus est doublée d'un contrôle positif : un mécanisme qui
refuse TOUT passerait la moitié de ce fichier sans rien protéger.
"""

import hashlib
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.vm import lima_install as I  # noqa: E402


class TestCeQuiNeSInstallePas(unittest.TestCase):
    def test_latest_is_refused(self):
        """Il désigne une chose différente à chaque appel : il n'y a rien à
        comparer, donc rien à vérifier."""
        for mot in ("latest", "LATEST", "main", "master", "", "   "):
            with self.subTest(version=mot):
                plan, raison = I.plan(mot, "macos", "arm64")
                self.assertIsNone(plan)
                self.assertIn(raison, (I.UNPINNED, I.UNKNOWN_RELEASE))

    def test_latest_is_refused_even_when_someone_pinned_it(self):
        """La garde porte sur le MOT, et non sur l'absence de la table. Un
        « latest » qu'on aurait épinglé désignerait quand même une archive
        différente à chaque publication — la somme deviendrait fausse sans
        que personne n'ait rien changé."""
        with patch.dict(
            I.RELEASES, {"latest": {("Darwin", "arm64"): "a" * 64}}
        ):
            plan, raison = I.plan("latest", "macos", "arm64")
        self.assertIsNone(plan)
        self.assertEqual(I.UNPINNED, raison)

    def test_a_version_absent_from_the_table_is_refused(self):
        plan, raison = I.plan("1.2.3", "macos", "arm64")
        self.assertIsNone(plan)
        self.assertEqual(I.UNKNOWN_RELEASE, raison)

    def test_an_unknown_system_or_arch_is_refused(self):
        for systeme, arch in (("plan9", "arm64"), ("macos", "vax")):
            with self.subTest(systeme=systeme, arch=arch):
                plan, raison = I.plan("1.2.3", systeme, arch)
                self.assertIsNone(plan)
                self.assertEqual(I.UNKNOWN_TARGET, raison)

    def test_every_refusal_is_in_the_closed_vocabulary(self):
        self.assertTrue(I.REFUSALS)
        cas = (
            ("latest", "macos", "arm64"),
            ("1.2.3", "macos", "arm64"),
            ("1.2.3", "plan9", "arm64"),
        )
        for version, systeme, arch in cas:
            with self.subTest(version=version):
                self.assertIn(I.plan(version, systeme, arch)[1], I.REFUSALS)


class TestCeQuiSInstalleQuandCEstEpingle(unittest.TestCase):
    """Contrôle positif : refuser tout ne protégerait rien."""

    SOMME = "a" * 64

    def test_a_pinned_version_yields_a_plan(self):
        with patch.dict(
            I.RELEASES, {"1.2.3": {("Darwin", "arm64"): self.SOMME}}
        ):
            plan, raison = I.plan("1.2.3", "macos", "arm64")
        self.assertEqual(I.OK, raison)
        self.assertEqual("1.2.3", plan.version)
        self.assertEqual(self.SOMME, plan.sha256)
        self.assertIn("v1.2.3", plan.url)
        self.assertIn("Darwin-arm64", plan.url)

    def test_the_leading_v_is_accepted_and_normalised(self):
        with patch.dict(
            I.RELEASES, {"1.2.3": {("Darwin", "arm64"): self.SOMME}}
        ):
            plan, raison = I.plan("v1.2.3", "macos", "arm64")
        self.assertEqual(I.OK, raison)
        self.assertEqual("1.2.3", plan.version)

    def test_aarch64_and_arm64_name_the_same_archive(self):
        """Deux mots pour une architecture ; inventer la correspondance chez
        chaque appelant la ferait diverger."""
        self.assertEqual(
            I.target_tokens("macos", "aarch64"),
            I.target_tokens("macos", "arm64"),
        )


class TestLaVerificationEstFermeeParDefaut(unittest.TestCase):
    """C'est le dernier moment où l'on peut encore ne rien exécuter."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chemin = os.path.join(self.tmp.name, "archive.tar.gz")
        self.contenu = b"une archive inventee, pas une vraie"
        with open(self.chemin, "wb") as fh:
            fh.write(self.contenu)
        self.somme = hashlib.sha256(self.contenu).hexdigest()

    def test_the_right_sum_passes(self):
        """Contrôle positif."""
        self.assertEqual(I.OK, I.verify(self.chemin, self.somme))

    def test_the_case_of_the_expected_sum_does_not_matter(self):
        self.assertEqual(I.OK, I.verify(self.chemin, self.somme.upper()))

    def test_one_changed_byte_is_refused(self):
        with open(self.chemin, "wb") as fh:
            fh.write(self.contenu + b"!")
        self.assertEqual(
            I.CHECKSUM_MISMATCH, I.verify(self.chemin, self.somme)
        )

    def test_a_sum_differing_only_at_the_end_is_refused(self):
        """Comparer un préfixe laisserait passer une archive dont la somme
        ne diffère que sur ses derniers caractères — et une collision de
        préfixe se fabrique, là où une collision entière ne se fabrique
        pas."""
        tordue = self.somme[:-1] + ("0" if self.somme[-1] != "0" else "1")
        self.assertEqual(I.CHECKSUM_MISMATCH, I.verify(self.chemin, tordue))

    def test_an_absent_file_is_refused_and_not_taken_for_success(self):
        manquant = os.path.join(self.tmp.name, "jamais-telecharge.tar.gz")
        self.assertEqual(I.FILE_ABSENT, I.verify(manquant, self.somme))

    def test_no_expected_sum_is_refused_too(self):
        """« Rien à vérifier » ne veut pas dire « vérifié ». C'est le refus
        qui manque le plus souvent, parce qu'il ressemble à un cas normal."""
        for attendue in ("", None, "   "):
            with self.subTest(attendue=attendue):
                self.assertNotEqual(I.OK, I.verify(self.chemin, attendue))

    def test_the_sum_is_read_in_chunks_and_still_correct(self):
        """Une archive pèse des dizaines de mégaoctets ; la charger d'un
        coup n'apporte rien, mais lire par blocs doit donner le même."""
        gros = os.path.join(self.tmp.name, "gros.bin")
        charge = os.urandom(3 * 1024 * 1024)
        with open(gros, "wb") as fh:
            fh.write(charge)
        self.assertEqual(hashlib.sha256(charge).hexdigest(), I.sha256_of(gros))

    def test_an_unreadable_file_hashes_to_nothing_rather_than_crashing(self):
        self.assertEqual("", I.sha256_of(os.path.join(self.tmp.name, "nul")))


class TestLaTableEllememe(unittest.TestCase):
    def test_it_ships_with_nothing_unverified_in_it(self):
        """Une somme se RELÈVE. En inventer une donnerait un mécanisme qui
        refuse tout, ou pire, qui accepte ce qu'il ne devrait pas. Cette
        épreuve n'interdit pas d'en ajouter — elle exige que ce qu'on ajoute
        ait la FORME d'une somme SHA-256."""
        for version, cibles in I.RELEASES.items():
            for cible, somme in cibles.items():
                with self.subTest(version=version, cible=cible):
                    self.assertRegex(somme, r"^[0-9a-fA-F]{64}$")
                    self.assertEqual(2, len(cible))


class TestElleNeTelechargeRien(unittest.TestCase):
    def test_the_module_fetches_nothing_and_runs_nothing(self):
        import ast

        chemin = os.path.join(RACINE, "script", "vm", "lima_install.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        racines = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                racines.update(a.name.split(".")[0] for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                racines.add(noeud.module.split(".")[0])
        self.assertTrue(racines, "aucun import lu : rien n'est prouvé")
        for interdit in ("urllib", "requests", "subprocess", "socket"):
            self.assertNotIn(interdit, racines)


class TestParOuLOutilSAcquiert(unittest.TestCase):
    """Deux routes, et l'ordre entre elles est une décision.

    LE GESTIONNAIRE D'ABORD. Sa chaîne de signature porte sur l'index
    entier, et la somme de chaque paquet en découle sans qu'une main la
    recopie. Un sha256 transcrit à l'œil dans une table est plus faible, et
    il vieillit ; la table reste pour les systèmes qui ne publient pas
    l'outil.

    Rien ici ne touche la machine : `which` est un paramètre, donc la
    décision se relit pour un système qui n'est pas le sien.
    """

    @staticmethod
    def rien(_nom):
        return None

    @staticmethod
    def seulement(*presents):
        return lambda nom: f"/usr/bin/{nom}" if nom in presents else None

    def test_the_manager_wins_when_it_is_there(self):
        route = I.route("macos", "arm64", which=self.seulement("brew"))
        self.assertEqual(I.MANAGER, route.kind)
        self.assertIn("lima", route.command)
        self.assertEqual("brew", route.manager)

    def test_each_known_host_names_its_own_manager(self):
        attendus = {
            "macos": "brew",
            "arch": "pacman",
            "debian": "apt-get",
            "proxmox": "apt-get",
        }
        self.assertTrue(attendus)
        for hote, gestionnaire in attendus.items():
            with self.subTest(hote=hote):
                route = I.route(
                    hote, "amd64", which=self.seulement(gestionnaire)
                )
                self.assertEqual(I.MANAGER, route.kind)
                self.assertEqual(gestionnaire, route.manager)

    def test_a_missing_manager_is_named_and_not_confused(self):
        """« Installer brew » et « relever une somme » ne se font ni au
        même endroit ni par la même personne."""
        route = I.route("macos", "arm64", which=self.rien)
        self.assertEqual(I.MANAGER_ABSENT, route.kind)
        self.assertEqual("brew", route.manager)

    def test_a_host_with_no_manager_and_no_pin_says_both_are_shut(self):
        route = I.route("unknown", "arm64", which=self.rien)
        self.assertEqual(I.NO_ROUTE, route.kind)

    def test_the_pinned_table_still_serves_when_it_is_filled(self):
        """LE CONTRÔLE POSITIF de la seconde route. La table est vide dans
        le dépôt — délibérément — donc sans ce cas, rien ne prouverait
        qu'elle est encore consultée."""
        somme = "a" * 64
        with patch.dict(
            I.RELEASES, {"1.2.3": {("Linux", "x86_64"): somme}}, clear=False
        ):
            route = I.route(
                "debian", "amd64", version="1.2.3", which=self.rien
            )
        self.assertEqual(I.OK, route.kind)
        self.assertEqual(somme, route.release.sha256)
        self.assertIn("1.2.3", route.release.url)

    def test_the_manager_is_preferred_even_when_the_pin_would_work(self):
        """L'ordre est le sujet : la table pourrait répondre, et pourtant
        c'est le gestionnaire qui gagne."""
        with patch.dict(
            I.RELEASES, {"1.2.3": {("Darwin", "arm64"): "b" * 64}}
        ):
            route = I.route(
                "macos", "arm64", version="1.2.3", which=self.seulement("brew")
            )
        self.assertEqual(I.MANAGER, route.kind)

    def test_exactly_one_of_the_two_fields_is_filled(self):
        """Un champ polymorphe ferait traiter une commande comme une
        archive : l'une se joue, l'autre se télécharge puis se vérifie."""
        gestionnaire = I.route("macos", "arm64", which=self.seulement("brew"))
        self.assertTrue(gestionnaire.command)
        self.assertIsNone(gestionnaire.release)
        with patch.dict(I.RELEASES, {"1.2.3": {("Linux", "arm64"): "c" * 64}}):
            epingle = I.route(
                "arch", "arm64", version="1.2.3", which=self.rien
            )
        self.assertEqual("", epingle.command)
        self.assertIsNotNone(epingle.release)

    def test_a_linux_host_reaches_the_pinned_table_at_all(self):
        """LE DÉFAUT que cette épreuve a trouvé : `host_os` distingue les
        distributions, une archive ne connaît que « Linux ». Passer le
        jeton d'hôte tel quel rendait « cible inconnue » sur TOUT hôte
        Linux, donc le repli était mort sans un mot."""
        for hote in ("debian", "arch", "proxmox"):
            with self.subTest(hote=hote):
                with patch.dict(
                    I.RELEASES, {"9.9.9": {("Linux", "x86_64"): "d" * 64}}
                ):
                    route = I.route(
                        hote, "amd64", version="9.9.9", which=self.rien
                    )
                self.assertEqual(I.OK, route.kind)
                self.assertIn("Linux", route.release.url)

    def test_a_macos_host_reaches_the_darwin_archive(self):
        with patch.dict(
            I.RELEASES, {"9.9.9": {("Darwin", "arm64"): "e" * 64}}
        ):
            route = I.route(
                "macos", "aarch64", version="9.9.9", which=self.rien
            )
        self.assertEqual(I.OK, route.kind)
        self.assertIn("Darwin", route.release.url)
        self.assertIn("arm64", route.release.url)

    def test_an_unrecognised_host_is_not_guessed_to_be_linux(self):
        """Deviner ferait télécharger une archive Linux sur ce qui n'en est
        peut-être pas un."""
        with patch.dict(
            I.RELEASES, {"9.9.9": {("Linux", "x86_64"): "f" * 64}}
        ):
            route = I.route(
                "unknown", "amd64", version="9.9.9", which=self.rien
            )
        self.assertEqual(I.NO_ROUTE, route.kind)

    def test_every_verdict_is_in_the_closed_vocabulary(self):
        self.assertTrue(I.REFUSALS, "vocabulaire vidé : rien n'est prouvé")
        cas = (
            ("macos", "arm64", "", self.seulement("brew")),
            ("macos", "arm64", "", self.rien),
            ("unknown", "arm64", "", self.rien),
            ("unknown", "arm64", "latest", self.rien),
            ("unknown", "sparc", "1.2.3", self.rien),
        )
        for hote, arch, version, which in cas:
            with self.subTest(hote=hote, version=version):
                self.assertIn(
                    I.route(hote, arch, version=version, which=which).kind,
                    I.REFUSALS,
                )

    def test_the_host_token_case_does_not_decide(self):
        route = I.route("MacOS", "arm64", which=self.seulement("brew"))
        self.assertEqual(I.MANAGER, route.kind)

    def test_it_probes_nothing_by_itself_in_the_tests(self):
        """Le banc doit VRAIMENT injecter : un `which` non transmis
        interrogerait la machine, et l'épreuve dirait autre chose selon le
        poste qui la lance."""
        vus = []

        def espion(nom):
            vus.append(nom)
            return None

        I.route("macos", "arm64", which=espion)
        self.assertEqual(["brew"], vus)


class TestLaTableDesGestionnairesNAffirmePasTrop(unittest.TestCase):
    """Elle dit QUEL gestionnaire fait autorité, pas que Lima y soit.

    Une note écrite ici sur le contenu d'un dépôt de paquets vieillirait
    mal ; le gestionnaire répond pour lui-même, et « no available formula »
    est une réponse claire.
    """

    def test_every_command_names_the_tool_it_installs(self):
        self.assertTrue(I.MANAGERS)
        for hote, (_gestionnaire, commande) in I.MANAGERS.items():
            with self.subTest(hote=hote):
                self.assertIn("lima", commande)

    def test_every_command_starts_with_its_own_manager(self):
        """Une commande qui appelle un autre binaire que celui qu'on a
        cherché s'exécuterait sur une machine où il manque."""
        for hote, (gestionnaire, commande) in I.MANAGERS.items():
            with self.subTest(hote=hote):
                mots = commande.split()
                self.assertIn(gestionnaire, mots[:2], commande)

    def test_no_command_asks_for_the_latest_of_anything(self):
        """La route du gestionnaire est signée ; elle n'a pas besoin d'un
        « latest » qui, lui, ne se vérifie pas."""
        for hote, (_g, commande) in I.MANAGERS.items():
            with self.subTest(hote=hote):
                self.assertNotIn("latest", commande)
                self.assertNotIn("curl", commande)
                self.assertNotIn("|", commande)

    def test_the_host_tokens_are_those_of_host_os(self):
        """Une clé qui n'est pas un jeton d'hôte ne serait jamais trouvée,
        et la route du gestionnaire serait morte sans un mot."""
        from script.todo import host_os

        for hote in I.MANAGERS:
            with self.subTest(hote=hote):
                self.assertIn(hote, host_os.HOSTS)


if __name__ == "__main__":
    unittest.main()
