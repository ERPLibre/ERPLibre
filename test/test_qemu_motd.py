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
    ("nixos", "25.11", "amd64"),
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
            "nixos": "nix",
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


class TestDesktopBlock(unittest.TestCase):
    """Le bloc « Bureau » : présent seulement là où un bureau existe.

    Vécu : une VM graphique restait sur une console texte, GNOME installé et
    gdm3 installé — graphical.target était déjà atteinte quand le paquet est
    arrivé. La commande qui répare tient sur une ligne, encore faut-il la lire
    quelque part. Sur un serveur, elle ne mènerait à aucune unité : le bloc
    n'y apparaît pas.
    """

    def _motd(self, desktop):
        return dq.build_motd(
            "ubuntu",
            "26.04",
            "amd64",
            "fr",
            "~/git/erplibre",
            "install_odoo_18",
            "vim",
            desktop,
        )

    def test_a_server_gets_no_desktop_block(self):
        self.assertNotIn("Bureau", self._motd(False))

    def test_a_graphical_vm_gets_it(self):
        self.assertIn("Bureau", self._motd(True))

    def test_it_carries_the_command_that_repairs(self):
        """« --now » et non « enable » seul : sur Debian et Ubuntu, l'unité n'a
        pas de WantedBy, et « enable » rend 0 sans rien faire."""
        motd = self._motd(True)
        self.assertIn("systemctl enable --now gdm", motd)
        self.assertIn("systemctl status display-manager", motd)

    def test_it_says_why_now_matters(self):
        self.assertIn("--now", self._motd(True))

    def test_it_stays_inside_the_frame(self):
        """Le guide est encadré : une ligne trop longue casse la boîte."""
        lines = self._motd(True).splitlines()
        width = max(len(line) for line in lines)
        border = [line for line in lines if line.startswith("╭")][0]
        self.assertEqual(len(border), width)

    def test_the_default_is_no_block(self):
        """Un appelant qui n'en sait rien n'annonce pas un bureau."""
        motd = dq.build_motd("ubuntu", "26.04", "amd64", "fr")
        self.assertNotIn("Bureau", motd)


class LeGuideNixosSeVoitEtDitVrai(unittest.TestCase):
    """Sur NixOS rien ne lisait /etc/motd — mesuré sur une VM installée :
    sshd en « printmotd no » et aucun pam_motd dans son PAM. Le fichier était
    écrit, complet, et personne ne le montrait. Le module le fait afficher ;
    ces tests gardent ce qu'il montre.
    """

    def _motd(self, distro="nixos", **kw):
        return dq.build_motd(
            distro, "25.11", "amd64", el_dir="~/git/erplibre", **kw
        )

    def test_the_file_that_gets_rewritten_is_named_as_such(self):
        """Le piège que ce bloc existe pour dire : « make install_os » repose
        /etc/nixos/erplibre.nix depuis le dépôt, et ce qu'on y avait ajouté
        disparaît sans un mot."""
        motd = self._motd()
        self.assertIn("/etc/nixos/erplibre.nix", motd)
        self.assertIn("make install_os", motd)

    def test_where_ones_own_declarations_survive(self):
        """Un guide qui nomme le piège sans nommer l'issue laisse l'opérateur
        devant un fichier qu'il n'ose plus toucher."""
        self.assertIn("/etc/nixos/configuration.nix", self._motd())

    def test_the_source_of_truth_is_the_repository(self):
        self.assertIn("conf/nixos/erplibre.nix", self._motd())

    def test_the_block_is_translated(self):
        for lang, attendu in (("fr", "déclaratif"), ("en", "declarative")):
            with self.subTest(lang=lang):
                self.assertIn(attendu, self._motd(lang=lang))

    def test_the_other_distributions_are_left_alone(self):
        """Rien de ceci ne veut dire quoi que ce soit ailleurs."""
        for distro in ("debian", "ubuntu", "fedora", "arch", "opensuse"):
            with self.subTest(distro=distro):
                self.assertNotIn("/etc/nixos/", self._motd(distro))

    def test_a_vm_without_erplibre_says_nothing_of_it(self):
        """Même règle que le bloc AUR : c'est l'installation qui pose le
        module dont ces lignes parlent."""
        nu = dq.build_motd("nixos", "25.11", "amd64")
        self.assertNotIn("conf/nixos/erplibre.nix", nu)

    def test_the_module_turns_the_display_on(self):
        """Écrire le guide sans rien pour le lire ne sert personne."""
        from pathlib import Path

        racine = Path(__file__).resolve().parent.parent
        module = (racine / "conf/nixos/erplibre.nix").read_text(
            encoding="utf-8"
        )
        self.assertIn("services.openssh.settings.PrintMotd = true;", module)


class LeCheminDuDepotEstEntierDansLeGuide(unittest.TestCase):
    """Le guide est lu par quelqu'un qui vient d'entrer en ssh, donc posé
    dans son foyer, et qui va TAPER ce qu'il lit.

    « conf/nixos/erplibre.nix » était la seule ligne du bloc à n'être ni un
    chemin absolu ni une commande : depuis le foyer elle ne désigne rien, et
    la racine change avec le profil — ~/git/erplibre en développement,
    /opt/erplibre en production. Elle porte donc la racine, comme les autres
    blocs le font déjà pour les leurs.
    """

    def _lignes(self, el_dir="~/git/erplibre"):
        return dq.nixos_rows(el_dir)

    def test_the_checkout_path_is_complete(self):
        chemins = [c for c, _, _ in self._lignes() if "conf/nixos" in c]
        self.assertEqual(len(chemins), 1)
        self.assertTrue(chemins[0].startswith("~/git/erplibre/"), chemins[0])

    def test_the_root_follows_the_profile(self):
        """Écrire « ~/git/erplibre » en dur enverrait une machine de
        production chercher un dépôt qui n'y est pas."""
        chemins = [
            c for c, _, _ in self._lignes("/opt/erplibre") if "conf/nixos" in c
        ]
        self.assertEqual(chemins, ["/opt/erplibre/conf/nixos/erplibre.nix"])

    def test_a_missing_root_falls_back_rather_than_breaking(self):
        """Un marqueur non substitué serait affiché tel quel."""
        rendu = "\n".join(c for c, _, _ in self._lignes(""))
        self.assertNotIn("{el_dir}", rendu)
        self.assertIn("~/git/erplibre/conf/nixos/erplibre.nix", rendu)

    def test_no_line_is_a_bare_relative_path(self):
        """La règle que la ligne fautive violait, sur TOUTES les lignes : ce
        qui n'est pas une commande est un chemin qu'on peut ouvrir d'où l'on
        est."""
        for cmd, _, _ in self._lignes():
            with self.subTest(cmd=cmd):
                if "/" not in cmd or " " in cmd:
                    continue  # une commande, pas un chemin
                self.assertTrue(
                    cmd.startswith(("/", "~/")),
                    f"{cmd} ne s'ouvre pas depuis le foyer",
                )


class LeGuideNixosDitCeQueNixosChange(unittest.TestCase):
    """Ce que le bloc ajoute, et qui ne se devine pas.

    Chaque ligne a été confrontée à une VM NixOS 25.11 vivante avant d'être
    écrite : « nixos-version » rend bien sa version, « --rollback » est dans
    le synopsis de nixos-rebuild, et « ls /bin » rend VIDE sur une machine où
    /bin/bash s'exécute.

    Une recherche de paquet a été ESSAYÉE puis écartée : « nix-env -qaP »
    ne rend rien sur cette image, dont le canal n'est pas peuplé, et
    « nix search » se met à tirer un canal entier. Un guide qui envoie taper
    une commande muette coûte plus qu'un guide qui se tait.
    """

    def _motd(self, **kw):
        return dq.build_motd(
            "nixos", "25.11", "amd64", el_dir="~/git/erplibre", **kw
        )

    def test_the_safety_net_of_editing_is_named(self):
        """Une déclaration fautive se défait par une commande ; ailleurs elle
        laisse un système à réparer à la main."""
        self.assertIn("nixos-rebuild switch --rollback", self._motd())

    def test_the_version_is_reachable(self):
        self.assertIn("nixos-version", self._motd())

    def test_the_trap_of_an_empty_bin_is_told(self):
        """envfs résout un nom sans jamais énumérer : tout ce qui cherche par
        motif ne trouve rien, quand le nom exact marche."""
        motd = self._motd()
        self.assertIn("ls /bin", motd)
        self.assertIn("envfs", motd)

    def test_it_does_not_repeat_the_package_block(self):
        """nix-shell, « nixos-rebuild switch » nu et nix-collect-garbage sont
        déjà dans le bloc du gestionnaire de paquets. Les redire userait la
        seule chose que ce bloc a — dire ce qui n'est écrit nulle part."""
        commandes = [c for c, _, _ in dq.nixos_rows("~/git/erplibre")]
        for deja in (
            "nix-shell -p <paquet>",
            "sudo nixos-rebuild switch",
            "sudo nix-collect-garbage -d",
        ):
            with self.subTest(commande=deja):
                self.assertNotIn(deja, commandes)

    def test_both_languages_carry_every_line(self):
        """Un bloc à moitié traduit se voit tout de suite, et fait douter du
        reste."""
        for _, fr, en in dq.nixos_rows("~/git/erplibre"):
            with self.subTest(fr=fr):
                self.assertTrue(fr.strip())
                self.assertTrue(en.strip())
                self.assertNotEqual(fr, en)


class LesOutilsPosesSAnnoncent(unittest.TestCase):
    """Le guide ne disait rien des outils installés dans la VM : on entrait
    en ssh sans savoir que nix, PyCharm ou la forge étaient là, ni par quelle
    commande s'en servir.

    Ce qui est écrit doit être VRAI sur la machine : le lecteur va taper ces
    lignes, et une commande absente coûte plus qu'un guide muet.
    """

    def _motd(self, tools, **kw):
        return dq.build_motd(
            "ubuntu",
            "24.04",
            "amd64",
            el_dir="~/git/erplibre",
            tools=tools,
            **kw,
        )

    def test_only_what_was_installed_is_announced(self):
        motd = self._motd(("pycharm",))
        self.assertIn("PyCharm", motd)
        self.assertNotIn("nixos-anywhere", motd)
        self.assertNotIn("Forgejo", motd)

    def test_a_vm_without_tools_gains_nothing(self):
        """Le cas ordinaire ne doit pas gagner de bloc vide."""
        motd = self._motd(())
        for libelle, _lignes in dq.TOOL_GUIDE.values():
            with self.subTest(libelle=libelle):
                self.assertNotIn(libelle, motd)

    def test_the_checkout_root_is_substituted(self):
        """« {el_dir} » laissé tel quel ferait taper une accolade."""
        motd = self._motd(("pycharm",), el_make="install_odoo_18")
        self.assertIn("pycharm ~/git/erplibre", motd)
        self.assertNotIn("{el_dir}", motd)

    def test_nix_on_another_distribution_is_not_nixos(self):
        """L'outil pose nix en démon SUR une distribution ordinaire : il n'y a
        ni /etc/nixos ni nixos-rebuild, et reprendre les lignes du bloc NixOS
        enverrait chercher des commandes qui n'existent pas ici."""
        motd = self._motd(("nixanywhere",))
        self.assertIn("nix shell nixpkgs#", motd)
        self.assertNotIn("nixos-rebuild", motd)
        self.assertNotIn("/etc/nixos", motd)

    def test_the_deprecated_profile_verb_is_not_taught(self):
        """« nix profile install » est un alias déprécié depuis nix 2.30, et
        l'installateur amont sert une version postérieure : le proposer ferait
        répondre un avertissement à qui le tape."""
        motd = self._motd(("nixanywhere",))
        self.assertIn("nix profile add", motd)
        self.assertNotIn("nix profile install", motd)

    def test_every_key_exists_in_the_catalogue(self):
        """Une clé d'ici que le menu ne sait pas poser annoncerait un outil
        qui n'arrivera jamais."""
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        for cle in dq.TOOL_GUIDE:
            with self.subTest(cle=cle):
                self.assertIn(cle, TODO._QEMU_VM_TOOLS)

    def test_the_menu_hands_over_the_filtered_list(self):
        """La liste cochée vaut pour le parc ; celle-ci est filtrée par la
        machine. Android Studio n'existe qu'en x86_64 et PyCharm veut un
        bureau — les annoncer ailleurs enverrait chercher une commande qui ne
        sera jamais posée."""
        import sys

        sys.argv = ["todo.py"]
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        choisis = ("nixanywhere", "pycharm", "android")

        def parts(arch, desktop):
            p = todo._qemu_build_deploy_parts(
                "ubuntu",
                "24.04",
                arch,
                "vm",
                4096,
                2,
                "40G",
                None,
                "develop",
                desktop=desktop,
                vm_tools=choisis,
                dry_run=True,
            )
            return p[p.index("--vm-tools") + 1] if "--vm-tools" in p else ""

        self.assertEqual("nixanywhere,pycharm,android", parts("amd64", True))
        self.assertEqual("nixanywhere", parts("arm64", False))


if __name__ == "__main__":
    unittest.main()
