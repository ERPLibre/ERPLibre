#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Guide de connexion SSH des VM QEMU et identité git injectée.

Ces fonctions sont PURES : elles rendent du texte. Les tester ne demande donc
ni VM ni réseau, alors qu'une erreur y coûte cher — un user-data invalide fait
rejeter TOUTE la configuration cloud-init, et la VM démarre sans utilisateur ni
clé SSH, donc inaccessible.
"""

import importlib.util
import os
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEPLOY_QEMU = os.path.join(REPO, "script", "qemu", "deploy_qemu.py")

# script/qemu/ n'est pas un paquet : todo.py importe déjà ce fichier de cette
# façon (_qemu_import_module), le test fait pareil.
_spec = importlib.util.spec_from_file_location("deploy_qemu", DEPLOY_QEMU)
dq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dq)

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML absent du venv d'outils
    yaml = None

# Une combinaison par distribution du catalogue, dont les DEUX produits
# openSUSE : ils n'ont pas la même commande de mise à jour.
COMBOS = (
    ("ubuntu", "24.04", "amd64"),
    ("debian", "12", "s390x"),
    ("fedora", "43", "amd64"),
    ("almalinux", "9", "arm64"),
    ("rocky", "10", "amd64"),
    ("opensuse", "16.0", "amd64"),
    ("opensuse", "tumbleweed", "amd64"),
    ("arch", "latest", "amd64"),
)

# Largeur d'un terminal standard. Au-delà, le guide se replie et devient
# illisible — c'est le seul défaut qui ne se voit qu'une fois la VM déployée.
TERM_WIDTH = 80


class TestMotdContent(unittest.TestCase):
    def test_each_distro_gets_its_package_manager(self):
        expected = {
            "ubuntu": "apt",
            "debian": "apt",
            "fedora": "dnf",
            "almalinux": "dnf",
            "rocky": "dnf",
            "opensuse": "zypper",
            "arch": "pacman",
        }
        for distro, version, arch in COMBOS:
            motd = dq.build_motd(distro, version, arch)
            mgr = expected[distro]
            self.assertIn(f"Paquets — {mgr}", motd, distro)
            for other in set(expected.values()) - {mgr}:
                self.assertNotIn(f" {other} install", motd, distro)

    def test_leap_updates_with_up_and_tumbleweed_with_dup(self):
        """La distinction coûte cher à rater : « up » sur Tumbleweed laisse
        traîner des paquets retirés des dépôts."""
        leap = dq.build_motd("opensuse", "16.0", "amd64")
        rolling = dq.build_motd("opensuse", "tumbleweed", "amd64")
        self.assertIn("sudo zypper up", leap)
        self.assertNotIn("sudo zypper dup", leap)
        self.assertIn("sudo zypper dup", rolling)
        self.assertNotIn("sudo zypper up ", rolling)

    def test_pacman_never_suggests_a_bare_sy(self):
        motd = dq.build_motd("arch", "latest", "amd64")
        for line in motd.splitlines():
            self.assertNotIn("pacman -Sy ", line)
            self.assertNotIn("pacman -Sy\n", line)

    def test_header_names_the_distribution(self):
        self.assertIn(
            "openSUSE Leap 16.0", dq.build_motd("opensuse", "16.0", "x")
        )
        self.assertIn(
            "openSUSE Tumbleweed", dq.build_motd("opensuse", "tumbleweed", "x")
        )
        # Rolling release : le numéro « latest » n'apprend rien.
        self.assertIn("Arch Linux ·", dq.build_motd("arch", "latest", "amd64"))


class TestMotdErplibreSection(unittest.TestCase):
    def test_absent_without_install_dir(self):
        """Une VM déployée sans ERPLibre ne doit pas annoncer un dépôt ni un
        service qui n'existent pas."""
        motd = dq.build_motd("ubuntu", "24.04", "amd64")
        self.assertNotIn("ERPLibre\n", motd.split("╯", 1)[1])
        self.assertNotIn("erplibre.service", motd)
        self.assertNotIn("make todo", motd)
        # En l'absence de section ERPLibre, les commandes de service doivent
        # apparaître dans le bloc système : sinon elles manqueraient partout.
        self.assertIn("systemctl status <service>", motd)
        self.assertIn("journalctl -u <service> -f", motd)

    def test_covers_what_an_operator_needs(self):
        motd = dq.build_motd(
            "ubuntu",
            "24.04",
            "amd64",
            "fr",
            "~/git/erplibre",
            "install_odoo_18",
            "vim",
        )
        for needed in (
            "cd ~/git/erplibre",  # aller au dépôt
            "make todo",  # menu ERPLibre
            "vim config.conf",  # éditer le serveur
            "sudo systemctl restart erplibre",  # redémarrer
            "systemctl status erplibre",  # inspecter
            "journalctl -u erplibre -f",  # inspecter
            "update_addons_all.sh <base>",  # mise à jour des modules
            "git pull && make install_odoo_18",  # mise à jour Odoo
            "http://<ip>:8069",  # interface web
        ):
            self.assertIn(needed, motd)

    def test_no_editor_names_no_command(self):
        """Sans éditeur connu, on nomme le fichier : « vi » n'est pas garanti
        sur toutes les images cloud, et un guide qui propose une commande
        absente est pire que muet."""
        motd = dq.build_motd("arch", "latest", "amd64", "fr", "/opt/erplibre")
        self.assertIn("config.conf", motd)
        self.assertNotIn("vi config.conf", motd)
        self.assertNotIn("nano config.conf", motd)

    def test_no_make_target_stops_at_git_pull(self):
        """Les profils sans Odoo (« ERPLibre seul », « mobile ») ne doivent pas
        se voir annoncer une cible make qui n'est pas la leur."""
        motd = dq.build_motd(
            "ubuntu", "24.04", "amd64", "fr", "~/git/erplibre", "", "vim"
        )
        self.assertIn("git pull", motd)
        self.assertNotIn("git pull && make", motd)


class TestMotdLayout(unittest.TestCase):
    def test_never_wider_than_a_standard_terminal(self):
        for distro, version, arch in COMBOS:
            for lang in ("fr", "en"):
                for el_dir in ("", "~/git/erplibre", "/opt/erplibre"):
                    motd = dq.build_motd(
                        distro,
                        version,
                        arch,
                        lang,
                        el_dir,
                        "install_odoo_18" if el_dir else "",
                        "vim" if el_dir else "",
                    )
                    for line in motd.splitlines():
                        self.assertLessEqual(
                            len(line),
                            TERM_WIDTH,
                            f"{distro} {version} {lang} {el_dir} : {line}",
                        )

    def test_the_frame_is_never_narrower_than_what_it_frames(self):
        for distro, version, arch in COMBOS:
            motd = dq.build_motd(
                distro,
                version,
                arch,
                "fr",
                "~/git/erplibre",
                "install_odoo_18",
                "vim",
            )
            lines = motd.splitlines()
            frame = len(lines[0])
            self.assertTrue(lines[0].startswith("╭"))
            for line in lines:
                self.assertLessEqual(len(line), frame, f"{distro} : {line}")

    def test_no_tab_anywhere(self):
        """Une tabulation en tête de ligne est une erreur FATALE dans un
        scalaire bloc YAML : cloud-init rejette alors tout le user-data."""
        motd = dq.build_motd(
            "ubuntu",
            "24.04",
            "amd64",
            "fr",
            "~/git/erplibre",
            "install_odoo_18",
            "vim",
        )
        self.assertNotIn("\t", motd)

    def test_english_is_really_english(self):
        motd = dq.build_motd(
            "ubuntu",
            "24.04",
            "amd64",
            "en",
            "~/git/erplibre",
            "install_odoo_18",
            "vim",
        )
        self.assertIn("Packages — apt", motd)
        self.assertIn("upgrade the system", motd)
        self.assertNotIn("mettre à jour", motd)


class TestGitConfig(unittest.TestCase):
    def test_sections_and_values(self):
        cfg = dq.build_gitconfig("Ada Lovelace", "ada@example.org", "vim")
        self.assertIn("[user]", cfg)
        self.assertIn("name = Ada Lovelace", cfg)
        self.assertIn("email = ada@example.org", cfg)
        self.assertIn("[core]", cfg)
        self.assertIn("editor = vim", cfg)

    def test_indented_with_spaces_never_tabs(self):
        """git accepte les deux ; le scalaire bloc YAML qui transporte ce texte,
        non — une tabulation y fait rejeter tout le user-data."""
        self.assertNotIn("\t", dq.build_gitconfig("A", "a@b.c", "vim"))

    def test_empty_when_the_host_has_nothing_to_pass(self):
        self.assertEqual("", dq.build_gitconfig("", "", ""))

    def test_partial_identity_omits_the_missing_key(self):
        cfg = dq.build_gitconfig("Ada", "", "")
        self.assertIn("name = Ada", cfg)
        self.assertNotIn("email", cfg)
        self.assertNotIn("[core]", cfg)


class TestEditorResolution(unittest.TestCase):
    def test_known_editors_map_to_package_and_binary(self):
        self.assertEqual(("vim", "vim"), dq.EDITOR_PACKAGES["vi"])
        self.assertEqual(("neovim", "nvim"), dq.EDITOR_PACKAGES["nvim"])
        self.assertEqual(("nano", "nano"), dq.EDITOR_PACKAGES["nano"])

    def test_unknown_editor_is_ignored_not_guessed(self):
        """« code » n'est dans aucun dépôt de distribution : l'annoncer
        donnerait un core.editor qui fait échouer « git commit »."""
        self.assertNotIn("code", dq.EDITOR_PACKAGES)
        self.assertEqual(("", ""), dq.EDITOR_PACKAGES.get("code", ("", "")))

    def test_binary_drops_the_path_and_the_options(self):
        self.assertEqual("code", dq.editor_binary("/usr/bin/code --wait"))
        self.assertEqual("vim", dq.editor_binary("vim"))
        self.assertEqual("", dq.editor_binary("   "))


class TestWriteFilesBlock(unittest.TestCase):
    def _block(self):
        return dq.write_files_lines(
            [
                (
                    "/etc/motd",
                    "0644",
                    dq.build_motd("ubuntu", "24.04", "amd64"),
                    "",
                ),
                (
                    "/home/erplibre/.gitconfig",
                    "0644",
                    dq.build_gitconfig("Ada", "ada@example.org", "vim"),
                    "erplibre",
                ),
            ]
        )

    def test_permissions_are_quoted(self):
        """« permissions: 644 » non quoté est lu en DÉCIMAL et appliqué tel
        quel : 0o1204, soit le bit setuid, sans le moindre avertissement."""
        block = "\n".join(self._block())
        self.assertIn("permissions: '0644'", block)
        self.assertNotIn("permissions: 0644", block)

    def test_defer_only_for_owned_files(self):
        """write_files tourne AVANT la création des utilisateurs : sans
        « defer », le chown vers le compte de la VM échoue."""
        block = "\n".join(self._block())
        self.assertEqual(1, block.count("defer: true"))
        self.assertEqual(1, block.count("owner: erplibre:erplibre"))

    @unittest.skipIf(yaml is None, "PyYAML absent")
    def test_yaml_round_trip_is_byte_identical(self):
        """Le scalaire bloc doit rendre EXACTEMENT le texte d'origine : une
        indentation mal calculée passerait la validation en abîmant le fichier
        écrit dans la VM."""
        motd = dq.build_motd(
            "ubuntu",
            "24.04",
            "amd64",
            "fr",
            "~/git/erplibre",
            "install_odoo_18",
            "vim",
        )
        # « + "\n" » comme build_cloud_config, qui termine toujours le
        # document : sans ce saut final, un scalaire bloc en fin de flux perd sa
        # dernière fin de ligne.
        doc = (
            "\n".join(dq.write_files_lines([("/etc/motd", "0644", motd, "")]))
            + "\n"
        )
        self.assertEqual(
            motd, yaml.safe_load(doc)["write_files"][0]["content"]
        )

    @unittest.skipIf(yaml is None, "PyYAML absent")
    def test_every_distro_produces_parsable_yaml(self):
        for distro, version, arch in COMBOS:
            motd = dq.build_motd(
                distro,
                version,
                arch,
                "fr",
                "~/git/erplibre",
                "install_odoo_18",
                "vim",
            )
            doc = (
                "\n".join(
                    dq.write_files_lines([("/etc/motd", "0644", motd, "")])
                )
                + "\n"
            )
            self.assertEqual(
                motd, yaml.safe_load(doc)["write_files"][0]["content"], distro
            )


class TestInstallerGuideNames(unittest.TestCase):
    def test_names_are_flat(self):
        """Le cpio est déplié séquentiellement et ne crée pas les répertoires
        parents manquants : une entrée « erplibre/etc-motd » sans entrée
        « erplibre » ferait échouer le dépliage de l'initrd entier."""
        for path in ("/etc/motd", "/home/erplibre/.gitconfig"):
            name = dq.installer_guide_name(path)
            self.assertNotIn("/", name)
            self.assertTrue(name.startswith("erplibre-"))

    def test_two_paths_never_collide(self):
        self.assertNotEqual(
            dq.installer_guide_name("/etc/motd"),
            dq.installer_guide_name("/home/erplibre/.gitconfig"),
        )


if __name__ == "__main__":
    unittest.main()
