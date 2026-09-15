#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""NixOS au catalogue des systèmes déployables.

NixOS ne publie AUCUNE image cloud : sa page de téléchargement offre des ISO,
des AMI Amazon et Docker, rien d'autre. L'image vient donc d'un tiers qui la
reconstruit depuis nixpkgs — ce qui change deux choses par rapport aux sept
autres distributions du catalogue, et ces tests gardent les deux :

- la release est ÉPINGLÉE et sa somme sha256 FIGÉE dans le dépôt. L'amont
  n'en publie pas ; celle-ci a été relevée une fois à la revue, et c'est la
  seule chose qui distingue l'image revue de n'importe quel fichier servi
  sous la même URL. Elle se vérifie donc sans drapeau à passer ;
- l'origine se DIT à l'écran avant de déployer : le système de base d'une VM
  n'est pas un détail d'implémentation.

Le reste est le lot commun d'une distribution qu'on ajoute : deux catalogues
à tenir d'accord, un nom de fichier de cache qui ne doit pas retomber sur
celui de Fedora, une famille de paquets, un groupe d'administration.

S'y ajoute ce qu'un système DÉCLARATIF ne peut pas recevoir : les outils de
VM qui posent un binaire par « curl | sh » ou écrivent dans /usr/local n'y
survivraient pas à la reconstruction suivante.
"""

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]

try:
    import yaml

    YAML = True
except Exception:  # pragma: no cover - dépend de l'environnement
    YAML = False


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()


class LeCatalogue(unittest.TestCase):
    def test_it_is_in_both_catalogues_with_the_same_versions(self):
        """Le sélecteur en ligne tient sa propre copie : deux tables à la
        main, dont une qu'on oublie."""
        self.assertIn("nixos", DQ.DISTROS)
        self.assertIn("nixos", TODO._QEMU_DISTROS)
        self.assertEqual(
            sorted(DQ.DISTROS["nixos"][0]),
            sorted(TODO._QEMU_DISTROS["nixos"][0]),
        )
        self.assertEqual(
            DQ.DISTROS["nixos"][1], TODO._QEMU_DISTROS["nixos"][1]
        )

    def test_the_version_is_the_one_inside_the_image(self):
        """Annoncer une version que l'image ne porte pas mentirait sur ce
        qu'on livre : la release épinglée embarque 25.11."""
        self.assertIn("25.11", DQ.DISTROS["nixos"][0])
        code, osinfo, ram, disque = DQ.DISTROS["nixos"][0]["25.11"]
        self.assertEqual("nixos-25.11", osinfo)
        self.assertEqual(2048, ram)
        self.assertEqual("40G", disque)

    def test_the_disk_floor_is_above_the_rolling_neighbour(self):
        """Le store Nix garde chaque génération et ne se purge qu'à la main :
        le plancher est plus haut que celui d'Arch, à dessein."""
        _c, _o, ram_arch, _d = DQ.DISTROS["arch"][0]["latest"]
        _c, _o, ram_nix, _d = DQ.DISTROS["nixos"][0]["25.11"]
        self.assertGreater(ram_nix, ram_arch)

    def test_it_is_x86_only(self):
        """Le tiers ne publie qu'un asset, sans architecture dans son nom."""
        self.assertNotIn("nixos", DQ.ARM64_DISTROS)
        self.assertNotIn("nixos", DQ.S390X_DISTROS)


class LImage(unittest.TestCase):
    def test_the_release_is_pinned(self):
        """« latest » changerait le système de base d'un déploiement à
        l'autre, sans que rien ne le dise."""
        url = DQ.image_candidates("nixos", "25.11", "amd64", "25.11", True)[0]
        self.assertIn(DQ.NIXOS_IMAGE_TAG, url)
        self.assertNotIn("latest", url)

    def test_the_cache_name_carries_the_tag(self):
        """Changer le tag doit RETÉLÉCHARGER, et non réutiliser une image qui
        ne répond plus à la somme figée."""
        nom = DQ.default_image_name("nixos", "25.11", "amd64", "25.11")
        self.assertIn(DQ.NIXOS_IMAGE_TAG, nom)

    def test_the_cache_name_never_falls_back_to_fedora(self):
        """Le repli de fin de default_image_name() nomme « fedora-cloud-* » :
        une distribution oubliée là met son image en cache sous le nom d'une
        autre, silencieusement."""
        nom = DQ.default_image_name("nixos", "25.11", "amd64", "25.11")
        self.assertNotIn("fedora", nom)

    def test_the_pinned_sum_looks_like_a_sha256(self):
        self.assertEqual(64, len(DQ.NIXOS_IMAGE_SHA256))
        int(DQ.NIXOS_IMAGE_SHA256, 16)

    def test_a_wrong_sum_stops_the_deployment(self):
        """Continuer reviendrait à installer un système que personne n'a
        regardé."""
        with mock.patch.object(DQ, "open", mock.mock_open(read_data=b"x")):
            with self.assertRaises(SystemExit):
                DQ.verify_pinned_sha256("nixos", Path("/x"), False)

    def test_other_distros_are_not_checked_against_it(self):
        """Leur somme, quand elle existe, vient de leur propre SHA256SUMS."""
        DQ.verify_pinned_sha256("ubuntu", Path("/inexistant"), False)

    def _refus(self, urls=()):
        with mock.patch.object(DQ, "open", mock.mock_open(read_data=b"x")):
            with self.assertRaises(SystemExit) as pris:
                DQ.verify_pinned_sha256("nixos", Path("/x"), False, urls)
        return str(pris.exception)

    def test_the_cache_entry_is_named_as_what_must_go_first(self):
        """Le remède ordinaire — effacer le fichier — ne suffit PAS derrière
        le cache : c'est lui qui resservira les mêmes octets, indéfiniment.
        Ni « --purge », qui efface tout, ni « --purge-older-than », qu'un
        objet servi rajeunit à chaque fois, ne l'atteignent."""
        msg = self._refus(("https://miroir.example/nixos.qcow2",))
        self.assertIn("--oublie", msg)
        self.assertIn("GET https://miroir.example/nixos.qcow2", msg)

    def test_without_a_url_the_message_stays_short(self):
        """Une commande qu'on ne peut pas recopier telle quelle vaut moins
        que pas de commande du tout."""
        msg = self._refus()
        self.assertNotIn("--oublie", msg)
        self.assertIn("attendu", msg)


class CeQuiSeDitALEcran(unittest.TestCase):
    def test_the_third_party_origin_is_named(self):
        note = DQ.image_source_note("nixos")
        self.assertIsNotNone(note)
        url, tag = note
        self.assertIn(tag, url)
        self.assertTrue(url.startswith("https://"))

    def test_an_official_image_says_nothing(self):
        """Commenter chaque image noierait la seule qui le mérite."""
        for distro in ("ubuntu", "debian", "fedora", "arch", "opensuse"):
            with self.subTest(distro=distro):
                self.assertIsNone(DQ.image_source_note(distro))

    def test_the_recap_shows_the_link_and_the_warning(self):
        todo = TODO.__new__(TODO)
        spec = {
            "vms": [{"name": "vm", "distro": "nixos"}],
            "install": {"branch": "develop"},
        }
        with mock.patch.object(TODO, "_qemu_import_module", return_value=DQ):
            lignes = todo._qemu_image_lines(spec)
        texte = " ".join(lignes)
        self.assertIn(DQ.NIXOS_IMAGE_TAG, texte)
        self.assertIn("https://", texte)
        self.assertIn("ERPLibre", texte)

    def test_without_an_install_the_warning_is_not_shown(self):
        """Une VM NixOS sans installation ERPLibre n'a rien qui échoue : le
        dire serait du bruit."""
        todo = TODO.__new__(TODO)
        spec = {"vms": [{"name": "vm", "distro": "nixos"}], "install": None}
        with mock.patch.object(TODO, "_qemu_import_module", return_value=DQ):
            lignes = todo._qemu_image_lines(spec)
        self.assertNotIn("ERPLibre", " ".join(lignes))

    def test_a_deployment_without_nixos_says_nothing(self):
        todo = TODO.__new__(TODO)
        spec = {"vms": [{"name": "vm", "distro": "debian"}], "install": None}
        with mock.patch.object(TODO, "_qemu_import_module", return_value=DQ):
            self.assertEqual([], todo._qemu_image_lines(spec))


class LeSystemeInvite(unittest.TestCase):
    def test_the_package_family_is_its_own(self):
        """Aucune des quatre familles impératives : ce qui doit rester se
        déclare, et le guide de connexion le dit dans cet ordre."""
        self.assertEqual("nix", DQ.DISTRO_PKG["nixos"])
        self.assertEqual("nix", TODO._QEMU_DISTRO_FAMILY["nixos"])
        self.assertIn("nix", DQ.PKG_GUIDE)

    def test_the_guide_never_suggests_an_imperative_install(self):
        commandes = [c for c, _fr, _en in DQ.PKG_GUIDE["nix"]]
        self.assertTrue(any("nixos-rebuild" in c for c in commandes))
        self.assertTrue(
            any("configuration.nix" in c for c in commandes), commandes
        )
        for interdit in ("apt ", "dnf ", "pacman ", "zypper "):
            self.assertFalse(any(interdit in c for c in commandes), interdit)

    def test_the_admin_group_is_wheel(self):
        self.assertIn("wheel", DQ.user_groups("nixos").split(", "))

    def test_the_label_names_the_distribution(self):
        self.assertEqual("NixOS 25.11", DQ.distro_label("nixos", "25.11"))

    @unittest.skipUnless(YAML, "PyYAML absent")
    def test_the_cloud_config_stays_parsable(self):
        args = DQ.build_parser().parse_args(
            ["--distro", "fedora", "--hostname", "vm"]
        )
        args.distro = "nixos"
        vu = yaml.safe_load(
            DQ.build_cloud_config(args, None, ["ssh-ed25519 A"])
        )
        (compte,) = vu["users"]
        self.assertEqual("/bin/sh", compte["shell"])


class CeQuUnSystemeDeclaratifNeRecoitPas(unittest.TestCase):
    def test_no_vm_tool_is_offered(self):
        """Chacun pose un binaire par « curl | sh », écrit dans /usr/local ou
        installe par le gestionnaire du système. Aucun de ces gestes ne
        survit à la reconstruction suivante."""
        tous = list(TODO._QEMU_VM_TOOLS)
        self.assertEqual(
            [], TODO._qemu_tools_for(tous, "amd64", "gnome", "nixos")
        )

    def test_the_other_distros_keep_theirs(self):
        """Le bornage ne doit rien retirer à qui sait s'en servir."""
        tous = list(TODO._QEMU_VM_TOOLS)
        for distro in ("ubuntu", "debian", "arch", "fedora"):
            with self.subTest(distro=distro):
                self.assertTrue(
                    TODO._qemu_tools_for(tous, "amd64", "gnome", distro)
                )


class LesDeuxCheminsLisentLaMemeSomme(unittest.TestCase):
    """L'image tierce se vérifie sur les DEUX chemins de déploiement.

    Aucune distribution ne publie cette image : la somme a été relevée une
    fois à la revue, et c'est la seule chose qui distingue le fichier revu de
    n'importe quel autre servi sous la même URL. Le chemin qemu vérifie ce
    qu'il vient de télécharger ; celui de Proxmox fait vérifier sur l'hôte,
    où l'image descend.

    Deux copies de la somme dériveraient, et la copie oubliée serait celle
    qui laisse passer une image que personne n'a regardée.
    """

    def test_one_accessor_carries_it(self):
        self.assertEqual(DQ.NIXOS_IMAGE_SHA256, DQ.pinned_sha256("nixos"))
        self.assertEqual(64, len(DQ.pinned_sha256("nixos")))

    def test_the_distros_that_publish_their_own_have_none(self):
        """--verify lit alors le SHA256SUMS de la distribution : porter une
        somme figée en plus ferait deux autorités."""
        for distro in ("ubuntu", "debian", "fedora", "arch", ""):
            with self.subTest(distro=distro):
                self.assertEqual("", DQ.pinned_sha256(distro))

    def test_the_qemu_side_reads_the_accessor(self):
        """Un second test « distro == nixos » ailleurs se désaccorderait du
        jour où une autre image tierce entre au catalogue."""
        src = (RACINE / "script/qemu/deploy_qemu.py").read_text(
            encoding="utf-8"
        )
        i = src.index("def verify_pinned_sha256")
        self.assertIn("pinned_sha256(distro)", src[i : i + 700])

    def test_the_proxmox_side_verifies_on_the_host(self):
        from script.proxmox import proxmox_deploy as pve

        cmd = pve.image_fetch_cmd(
            "http://x/i.qcow2", "i.qcow2", sha256="a" * 64
        )
        self.assertIn("sha256sum -c -", cmd)
        # Par « && » : une somme qui ne correspond pas doit ARRÊTER la suite,
        # et non se contenter d'un avertissement dans le journal.
        self.assertIn("&& echo", cmd)

    def test_the_download_lands_on_its_final_name_only_when_complete(self):
        """« wget -O » écrivait dans la CIBLE : une coupure — réseau, disque
        plein, Ctrl-C — y figeait une image tronquée que le test de présence
        acceptait à chaque déploiement suivant. Avec une somme, elle échouait
        pour toujours sans dire quoi effacer ; sans somme, elle servait à
        créer une VM.

        Mesuré : un « .partiel » laissé par une coupure est repris et la
        cible finit identique à l'amont."""
        from script.proxmox import proxmox_deploy as pve

        cmd = pve.image_fetch_cmd("http://x/i.qcow2", "i.qcow2")
        self.assertIn("-O", cmd)
        self.assertIn(".partiel", cmd)
        # Le « mv » suit le téléchargement, et par « && » : un wget en échec
        # ne doit RIEN mettre en place.
        self.assertLess(cmd.index("wget"), cmd.index("mv "))
        self.assertIn("&& mv ", cmd)

    def test_a_fresh_download_is_checked_before_it_is_installed(self):
        """Une image fausse ne doit jamais devenir celle que le prochain
        déploiement trouvera « déjà présente »."""
        from script.proxmox import proxmox_deploy as pve

        cmd = pve.image_fetch_cmd(
            "http://x/i.qcow2", "i.qcow2", sha256="c" * 64
        )
        i_somme = cmd.index("sha256sum")
        self.assertLess(i_somme, cmd.index("mv "))

    def test_a_cached_image_is_verified_too(self):
        """Le cas qu'on veut prendre est un fichier substitué ou tronqué
        entre deux déploiements : le test de présence ne regarde que la
        taille, et la vérification vient donc APRÈS le « fi »."""
        from script.proxmox import proxmox_deploy as pve

        cmd = pve.image_fetch_cmd(
            "http://x/i.qcow2", "i.qcow2", sha256="b" * 64
        )
        # La DERNIÈRE vérification, celle qui porte sur le fichier en
        # place : la première garde le téléchargement frais avant de
        # l'installer, et se trouve donc AVANT le « fi ».
        self.assertLess(cmd.index("fi"), cmd.rindex("sha256sum"))
        self.assertEqual(2, cmd.count("sha256sum"))

    def test_nothing_is_appended_without_a_sum(self):
        from script.proxmox import proxmox_deploy as pve

        self.assertNotIn(
            "sha256sum", pve.image_fetch_cmd("http://x/i.qcow2", "i.qcow2")
        )

    def test_the_menu_passes_it_at_every_call_site(self):
        """Un appel qui l'oublie télécharge sans regarder."""
        src = (RACINE / "script/todo/proxmox_menu.py").read_text(
            encoding="utf-8"
        )
        # Les appels qui TÉLÉCHARGENT, l'exemple d'affichage excepté : les
        # trois du déploiement, plus celui du téléchargement d'avance — une
        # image posée par lui est celle qu'un déploiement futur trouvera
        # « déjà présente », et il ne la regardera pas mieux.
        vrais = [
            l
            for l in src.splitlines()
            if "pve.image_fetch_cmd(" in l and "https://…" not in l
        ]
        self.assertEqual(4, len(vrais))
        for ligne in vrais:
            with self.subTest(ligne=ligne.strip()[:50]):
                self.assertIn("sha256=", ligne)


if __name__ == "__main__":
    unittest.main()
