#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le chemin macOS aarch64, composé de bout en bout depuis une station Linux.

AUCUNE MACHINE APPLE N'EST NÉCESSAIRE, et c'est le sujet. Chaque maillon du
chemin prend son hôte et son architecture en PARAMÈTRE : la résolution du
backend, la route d'acquisition, l'URL d'image, le rendu de configuration.
Composer les quatre depuis ici mesure ce qu'un poste Apple obtiendrait, et
ce qu'aucune épreuve ne vérifiait — chaque maillon était éprouvé seul.

CE QUE LES ÉPREUVES DE MAILLON NE VOIENT PAS : les ACCORDS entre eux. Une
architecture juste dans la configuration et fausse dans l'URL d'image
démarre une image amd64 sous Virtualization.framework sur un Apple Silicon,
et l'outil échoue sans nommer la cause. C'est exactement ce qu'un accord
vérifié attrape et qu'aucun maillon ne peut voir.

Les jetons d'architecture sont TROIS vocabulaires distincts, et c'est
pourquoi ils se croisent mal : « aarch64 » vient d'`uname`, « arm64 » est
celui d'ERPLibre et des images cloud, « arm64 » celui des archives de
l'outil — qui nomme le système « Darwin » là où ERPLibre dit « macos ».
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo import host_os, vm_backend_choice  # noqa: E402
from script.todo.lima_menu import config_path  # noqa: E402
from script.vm import backend as B  # noqa: E402
from script.vm import lima as L  # noqa: E402
from script.vm import lima_install as I  # noqa: E402

# L'hôte qu'on simule. Ces deux valeurs sont les jetons d'ERPLibre, ceux
# que `host_os` rend — pas ceux d'`uname`, ni ceux des archives.
HOTE = host_os.MACOS
ARCH = "arm64"

# Ce qu'`uname` rend sur une machine Apple Silicon, et qui doit se traduire.
UNAME_ARCH = "aarch64"


def image(arch):
    """L'URL d'image cloud, par la convention DÉJÀ EN SERVICE du dépôt.

    Chargée depuis le script de déploiement qemu plutôt que recopiée : un
    gabarit dupliqué diverge de sa copie au premier changement d'amont, et
    c'est précisément l'accord entre les deux qu'on veut mesurer.
    """
    import importlib.util

    chemin = os.path.join(RACINE, "script", "qemu", "deploy_qemu.py")
    spec = importlib.util.spec_from_file_location("deploy_qemu_banc", chemin)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.image_url("ubuntu", "noble", arch, "24.04")


class TestLesTroisVocabulairesDArchitecture(unittest.TestCase):
    """« aarch64 », « arm64 », « Darwin » : trois tables, trois sources."""

    def test_uname_arch_becomes_the_erplibre_token(self):
        """`host_os` traduit ce qu'`uname` rend. Sans cette table, le jeton
        d'Apple Silicon voyagerait tel quel jusqu'aux images cloud, qui ne
        publient pas « aarch64 »."""
        self.assertEqual(ARCH, host_os._ARCHS[UNAME_ARCH])

    def test_both_spellings_reach_the_same_archive_target(self):
        """L'archive de l'outil accepte les deux orthographes, et doit
        rendre la même cible : sinon un poste répondant « aarch64 » et un
        autre « arm64 » téléchargeraient des choses différentes."""
        self.assertEqual(
            I.target_tokens(HOTE, UNAME_ARCH),
            I.target_tokens(HOTE, ARCH),
        )

    def test_the_archive_names_the_system_its_own_way(self):
        """« macos » chez ERPLibre, « Darwin » sur l'archive. Confondre les
        deux rend « cible inconnue » et ferme la route."""
        systeme, arche = I.target_tokens(HOTE, ARCH)
        self.assertEqual("Darwin", systeme)
        self.assertEqual("arm64", arche)


class TestLeBackendQuAppleObtient(unittest.TestCase):
    def test_automatic_resolves_to_lima_when_the_tool_is_there(self):
        """libvirt n'existe pas sur macOS, faute de /dev/kvm et des ponts
        sur lesquels son réseau est bâti."""
        self.assertEqual(
            B.LIMA,
            vm_backend_choice.effective("auto", HOTE, limactl=True),
        )

    def test_without_the_tool_it_does_not_fall_back_to_libvirt(self):
        """Y retomber promettrait un hyperviseur que le système n'a pas."""
        resolu = vm_backend_choice.effective("auto", HOTE, limactl=False)
        self.assertNotEqual(B.LIBVIRT, resolu)

    def test_the_screen_says_this_backend_is_not_proven(self):
        """C'est le seul du dépôt dans cet état, et un écran muet
        là-dessus laisse croire l'inverse."""
        self.assertFalse(B.is_proven(B.LIMA))
        lignes = vm_backend_choice.render("auto", HOTE, True)
        self.assertTrue(any("*" in ligne for ligne in lignes), lignes)


class TestLaRouteDAcquisitionSurApple(unittest.TestCase):
    def test_the_manager_route_is_offered_when_brew_is_there(self):
        route = I.route(
            HOTE, ARCH, which=lambda nom: f"/opt/homebrew/bin/{nom}"
        )
        self.assertEqual(I.MANAGER, route.kind)
        self.assertIn("lima", route.command)

    def test_without_the_manager_it_says_which_one_is_missing(self):
        route = I.route(HOTE, ARCH, which=lambda _nom: None)
        self.assertEqual(I.MANAGER_ABSENT, route.kind)
        self.assertTrue(route.manager)

    def test_the_pinned_route_would_fetch_a_darwin_arm64_archive(self):
        """La table est vide dans le dépôt — délibérément — donc seul un
        cas remplit à la main prouve que le repli visait la bonne
        archive."""
        from unittest.mock import patch

        with patch.dict(
            I.RELEASES, {"9.9.9": {("Darwin", "arm64"): "a" * 64}}
        ):
            route = I.route(
                HOTE, UNAME_ARCH, version="9.9.9", which=lambda _n: None
            )
        self.assertEqual(I.OK, route.kind)
        self.assertIn("Darwin", route.release.url)
        self.assertIn("arm64", route.release.url)
        self.assertNotIn("x86_64", route.release.url)


class TestLaConfigurationQuAppleObtient(unittest.TestCase):
    def rendre(self, **options):
        return L.render_config(image(ARCH), arch=ARCH, macos=True, **options)

    def test_it_asks_for_virtualization_framework(self):
        """Il n'existe que sur macOS 13+, et y vaut nettement mieux que
        l'émulation."""
        self.assertIn(f"vmType: {L.VM_TYPE_MACOS}", self.rendre())

    def test_it_is_valid_yaml(self):
        """Le rendu est écrit LIGNE À LIGNE : un analyseur rattrape ce que
        l'écriture manuelle risque de casser."""
        import yaml

        charge = yaml.safe_load(self.rendre())
        self.assertEqual(L.VM_TYPE_MACOS, charge["vmType"])
        self.assertEqual(ARCH, charge["arch"])

    def test_the_arch_agrees_between_the_config_and_the_image(self):
        """L'ACCORD QUE NUL MAILLON NE VOIT. Une architecture juste dans la
        configuration et fausse dans l'URL démarre une image amd64 sous
        Virtualization.framework sur un Apple Silicon, et l'outil échoue
        sans nommer la cause."""
        import yaml

        charge = yaml.safe_load(self.rendre())
        self.assertEqual(ARCH, charge["arch"])
        emplacement = charge["images"][0]["location"]
        self.assertIn(ARCH, emplacement)
        self.assertNotIn("amd64", emplacement)
        self.assertEqual(ARCH, charge["images"][0]["arch"])

    def test_nothing_of_the_host_is_mounted(self):
        """L'outil monte par défaut le répertoire personnel dans l'invité :
        une VM censée être confinée y lirait tout ce que la personne
        possède, sans qu'une règle réseau soit en cause."""
        import yaml

        self.assertEqual([], yaml.safe_load(self.rendre())["mounts"])

    def test_the_host_keys_are_not_injected(self):
        import yaml

        charge = yaml.safe_load(self.rendre())
        self.assertIs(False, charge["ssh"]["loadDotSSHPubKeys"])

    def test_the_default_config_is_not_reachable_and_says_so(self):
        """Sur macOS l'adresse joignable est POSSIBLE, et pourtant absente
        si personne ne l'a demandée : socket_vmnet réclame une
        installation privilégiée à part."""
        self.assertEqual(
            ("reachable-address",), L.config_limits(self.rendre())
        )

    def test_asking_for_it_adds_the_block_on_apple(self):
        """Contrôle positif : c'est le seul système où la demande porte."""
        avec = self.rendre(reachable=True)
        self.assertIn(L.NETWORK_SHARED, avec)
        self.assertEqual((), L.config_limits(avec))


class TestLeCheminEntierSeTient(unittest.TestCase):
    """Les quatre maillons enchaînés, comme un poste Apple les enchaîne."""

    def test_from_uname_to_the_start_command(self):
        jeton = host_os._ARCHS[UNAME_ARCH]
        self.assertEqual(
            B.LIMA, vm_backend_choice.effective("auto", HOTE, True)
        )
        route = I.route(HOTE, jeton, which=lambda nom: f"/bin/{nom}")
        self.assertEqual(I.MANAGER, route.kind)
        texte = L.render_config(image(jeton), arch=jeton, macos=True)
        chemin = config_path("apple-de-banc")
        argv = L.start_argv("apple-de-banc", chemin)
        # Ce qui compte : la commande porte la configuration qu'on vient de
        # rendre, et cette configuration porte l'architecture du poste.
        self.assertEqual(chemin, argv[-1])
        self.assertIn("apple-de-banc", argv)
        self.assertIn(f"arch: {jeton}", texte)
        self.assertIn(jeton, image(jeton))
        self.assertIn(chemin, L.display(argv))

    def test_the_config_path_is_not_in_the_checkout(self):
        """Un fichier dans le checkout se ferait emporter par un ratissage
        d'indexation."""
        self.assertNotIn(RACINE, config_path("apple-de-banc"))

    def test_no_step_needs_an_apple_machine_to_be_measured(self):
        """LE CONTRÔLE DU BANC. Si un maillon sondait la station au lieu de
        prendre son hôte en paramètre, ce fichier dirait autre chose selon
        le poste qui le lance — et sur une station Linux il dirait que le
        chemin Apple va bien sans l'avoir composé.

        On le prouve en MENTANT sur l'hôte local : les valeurs composées ne
        doivent pas bouger d'un octet. Une assertion du genre « l'hôte
        local n'est pas macOS » ne prouverait rien et tomberait justement
        sur un Mac, seul endroit où ce fichier compte vraiment.
        """
        from unittest.mock import patch

        def compose():
            return (
                vm_backend_choice.effective("auto", HOTE, True),
                I.target_tokens(HOTE, ARCH),
                L.render_config(image(ARCH), arch=ARCH, macos=True),
            )

        attendu = compose()
        for menteur in (host_os.MACOS, host_os.DEBIAN, host_os.UNKNOWN):
            with self.subTest(hote_local=menteur):
                with patch.object(host_os, "host_os", return_value=menteur):
                    self.assertEqual(attendu, compose())


if __name__ == "__main__":
    unittest.main()
