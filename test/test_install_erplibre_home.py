#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur d'ERPLibre Home : vérifications préalables et --dry-run.

Le script installe pour de vrai, sous le compte de l'utilisateur, avec sudo
pour les paquets. Ces tests n'exercent que ce qui ne touche rien : la
lecture de os-release et de la version de GNOME, que les variables
ERPLIBRE_HOME_* remplacent, et la sortie de --dry-run, qui est la
surface convenue du script.

Ce que ces tests gardent :

- chaque distribution visée tombe dans sa famille, avec la commande de
  paquets de cette famille ;
- les deux niveaux : la base ne pose ni règle udev, ni venv, ni paquet du
  deck ; --stream-deck ajoute les trois, et EPEL n'est activé qu'avec lui,
  sur les reconstructions d'EL, où wmctrl en dépend ;
- les traductions se compilent par « msgfmt --check », aux deux niveaux ;
- --uninstall retire tout, --uninstall --stream-deck la règle et le venv
  seulement, et aucun des deux ne vérifie le système ;
- un système non supporté sort en 2 avec UNE ligne « UNSUPPORTED: » sur la
  sortie d'erreur, celle que TODO et le test long affichent ;
- la liste des versions de GNOME acceptées est celle de metadata.json, lue
  sans python3 ;
- root est refusé, --extension-only refuse --stream-deck et --uninstall, et
  --dry-run n'appelle pas sudo ni n'écrit rien.
"""

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/install/install_erplibre_home.sh"
EXTENSION = RACINE / "script/gnome-extension/erplibre_home"
UUID = "erplibre-home@technolibre.ca"
REGLE = "/etc/udev/rules.d/70-streamdeck.rules"

# Des os-release réduits à ce que le script lit : ID et ID_LIKE.
OS_RELEASE = {
    "ubuntu:24.04": 'ID=ubuntu\nID_LIKE=debian\nVERSION_ID="24.04"\n',
    "debian:13": 'ID=debian\nVERSION_ID="13"\n',
    "fedora:43": "ID=fedora\nVERSION_ID=43\n",
    "almalinux:10": (
        'ID="almalinux"\nID_LIKE="rhel centos fedora"\nVERSION_ID="10.0"\n'
    ),
    "rocky:10": (
        'ID="rocky"\nID_LIKE="rhel centos fedora"\nVERSION_ID="10.0"\n'
    ),
    "opensuse-leap:16.0": (
        'ID="opensuse-leap"\nID_LIKE="suse opensuse"\nVERSION_ID="16.0"\n'
    ),
    "arch": "ID=arch\nBUILD_ID=rolling\n",
    "nixos": 'ID=nixos\nVERSION_ID="25.11"\n',
    # Inventés : un dérivé que seul ID_LIKE rattache, et un système que rien
    # ne rattache.
    "derive": 'ID=exemplelinux\nID_LIKE="ubuntu debian"\n',
    "inconnu": "ID=exempleos\n",
}

APT = (
    "sudo apt-get update -qq && sudo env DEBIAN_FRONTEND=noninteractive "
    "apt-get install -y --no-install-recommends "
)
# La base : schémas, gettext, python3 du système.
BASE = {
    "debian": APT + "libglib2.0-bin gettext python3",
    "rhel": "sudo dnf install -y glib2 gettext python3",
    "suse": "sudo zypper --non-interactive install glib2-tools gettext-tools"
    " python3",
    "arch": "sudo pacman -S --needed --noconfirm glib2 gettext python",
}
# --stream-deck : la base, puis les paquets du deck qu'elle ne porte pas.
DECK = {
    "debian": BASE["debian"]
    + " libhidapi-libusb0 libusb-1.0-0 python3-venv wmctrl",
    "rhel": BASE["rhel"] + " hidapi libusb1 wmctrl",
    "suse": BASE["suse"] + " libhidapi-libusb0 libusb-1_0-0 wmctrl",
    "arch": BASE["arch"] + " hidapi libusb wmctrl",
}
FAMILLES = {
    "ubuntu:24.04": "debian",
    "debian:13": "debian",
    "fedora:43": "rhel",
    "almalinux:10": "rhel",
    "rocky:10": "rhel",
    "opensuse-leap:16.0": "suse",
    "arch": "arch",
    "derive": "debian",
}


def versions_acceptees():
    """Les majeurs de « shell-version », en entiers."""
    with open(EXTENSION / "metadata.json", encoding="utf-8") as flux:
        return sorted(int(v) for v in json.load(flux)["shell-version"])


def langues():
    """Les langues de po/, gabarit .pot exclu, dans l'ordre du glob."""
    return sorted(p.stem for p in (EXTENSION / "po").glob("*.po"))


class Installateur(unittest.TestCase):
    """Lance le script dans un HOME jetable, sudo remplacé par un témoin."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.trace_sudo = self.tmp / "sudo_appele"
        self._commande("sudo", 'echo "$@" >> "%s"\nexit 1\n' % self.trace_sudo)
        self.lien = str(
            self.home / ".local/share/gnome-shell/extensions" / UUID
        )
        self.venv = str(RACINE / ".venv.streamdeck")

    def _commande(self, nom, corps):
        """Pose une commande factice en tête du PATH du script."""
        chemin = self.bin / nom
        chemin.write_text("#!/bin/sh\n" + corps, encoding="utf-8")
        chemin.chmod(0o755)

    def lancer(
        self, *options, systeme="ubuntu:24.04", gnome="48.1", uid="1000"
    ):
        """Lance le script depuis un répertoire hors du dépôt.

        uid vaut 1000 par défaut : la suite peut tourner sous root, dans un
        conteneur, et le refus de root masquerait alors tout le reste.
        None laisse le script lire la vraie valeur.
        """
        env = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("STREAMDECK_")
        }
        env["HOME"] = str(self.home)
        env["PATH"] = "%s:%s" % (self.bin, env.get("PATH", ""))
        if systeme is not None:
            fichier = self.tmp / "os-release"
            fichier.write_text(OS_RELEASE[systeme], encoding="utf-8")
            env["ERPLIBRE_HOME_OS_RELEASE"] = str(fichier)
        if gnome is not None:
            env["ERPLIBRE_HOME_GNOME_VERSION"] = gnome
        if uid is not None:
            env["ERPLIBRE_HOME_UID"] = uid
        return subprocess.run(
            [str(SCRIPT), *options],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(self.tmp),
            timeout=30,
        )

    @staticmethod
    def lignes(fini, prefixe):
        """Les lignes de stdout qui commencent par prefixe, sans lui."""
        return [
            ligne[len(prefixe) :]
            for ligne in fini.stdout.splitlines()
            if ligne.startswith(prefixe)
        ]

    def assertNonSupporte(self, fini, extrait):
        self.assertEqual(2, fini.returncode, fini.stdout + fini.stderr)
        erreurs = fini.stderr.strip().splitlines()
        self.assertEqual(1, len(erreurs), fini.stderr)
        self.assertTrue(erreurs[0].startswith("UNSUPPORTED: "), erreurs[0])
        self.assertIn(extrait, erreurs[0])
        self.assertEqual([], self.lignes(fini, "packages: "))


class LeScript(Installateur):
    def test_it_is_valid_shell(self):
        fini = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)

    def test_it_is_executable(self):
        """TODO, make et la VM l'appellent directement, sans « bash »."""
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_help_exits_zero_even_as_root(self):
        fini = self.lancer("--help", uid="0")
        self.assertEqual(0, fini.returncode, fini.stderr)
        for option in (
            "--stream-deck",
            "--no-enable",
            "--extension-only",
            "--with-extras",
            "--uninstall",
            "--dry-run",
        ):
            self.assertIn(option, fini.stdout)

    def test_an_unknown_option_exits_one(self):
        fini = self.lancer("--exemple", "--dry-run")
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("--exemple", fini.stderr)

    def test_uninstall_takes_no_install_option(self):
        fini = self.lancer("--uninstall", "--with-extras", "--dry-run")
        self.assertEqual(1, fini.returncode, fini.stdout)

    def test_extension_only_refuses_the_other_levels(self):
        """--extension-only est l'entrée étroite de make : ni le niveau
        Stream Deck ni la désinstallation n'y entrent."""
        for autre in ("--stream-deck", "--uninstall"):
            with self.subTest(autre=autre):
                fini = self.lancer("--extension-only", autre, "--dry-run")
                self.assertEqual(1, fini.returncode, fini.stdout)
                self.assertIn("--extension-only", fini.stderr)
                self.assertNotIn("UNSUPPORTED", fini.stderr)
                self.assertEqual([], self.lignes(fini, "write: "))


class LaFamille(Installateur):
    def test_each_target_system_maps_to_its_family_and_base_packages(self):
        for systeme, famille in FAMILLES.items():
            with self.subTest(systeme=systeme):
                fini = self.lancer("--dry-run", systeme=systeme)
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual([famille], self.lignes(fini, "family="))
                self.assertEqual(["48.1"], self.lignes(fini, "gnome="))
                self.assertEqual(
                    [BASE[famille]], self.lignes(fini, "packages: ")
                )

    def test_stream_deck_adds_its_rows_to_the_base(self):
        for systeme, famille in FAMILLES.items():
            with self.subTest(systeme=systeme):
                fini = self.lancer(
                    "--dry-run", "--stream-deck", systeme=systeme
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(
                    DECK[famille], self.lignes(fini, "packages: ")[-1]
                )

    def test_epel_comes_first_with_stream_deck_on_el_rebuilds_only(self):
        for systeme in ("almalinux:10", "rocky:10"):
            with self.subTest(systeme=systeme):
                deck = self.lignes(
                    self.lancer("--dry-run", "--stream-deck", systeme=systeme),
                    "packages: ",
                )
                self.assertEqual(
                    ["sudo dnf install -y epel-release", DECK["rhel"]], deck
                )
                base = self.lignes(
                    self.lancer("--dry-run", systeme=systeme), "packages: "
                )
                self.assertEqual([BASE["rhel"]], base)
        paquets = self.lignes(
            self.lancer("--dry-run", "--stream-deck", systeme="fedora:43"),
            "packages: ",
        )
        self.assertEqual([DECK["rhel"]], paquets)

    def test_with_extras_adds_one_more_command_at_both_levels(self):
        lz4 = {
            "ubuntu:24.04": "python3-lz4",
            "fedora:43": "python3-lz4",
            "opensuse-leap:16.0": "python3-lz4",
            "arch": "python-lz4",
        }
        for niveau in ((), ("--stream-deck",)):
            for systeme, module in lz4.items():
                with self.subTest(niveau=niveau, systeme=systeme):
                    paquets = self.lignes(
                        self.lancer(
                            "--dry-run",
                            "--with-extras",
                            *niveau,
                            systeme=systeme,
                        ),
                        "packages: ",
                    )
                    self.assertTrue(
                        paquets[-1].endswith(
                            "mpv yt-dlp nmap keepassxc xdotool " + module
                        ),
                        paquets[-1],
                    )
                    self.assertNotIn("lz4", paquets[-2])

    def test_without_extras_no_extra_package(self):
        fini = self.lancer("--dry-run", "--stream-deck")
        self.assertNotIn("lz4", fini.stdout)
        self.assertNotIn("keepassxc", fini.stdout)


class LeDryRun(Installateur):
    def test_the_base_lists_its_files_and_neither_rule_nor_venv(self):
        fini = self.lancer("--dry-run")
        self.assertEqual(0, fini.returncode, fini.stderr)
        ecrits = self.lignes(fini, "write: ")
        self.assertNotIn(REGLE, ecrits)
        self.assertEqual([], self.lignes(fini, "venv: "))
        self.assertIn(self.lien, ecrits)
        self.assertIn(str(EXTENSION / "schemas/gschemas.compiled"), ecrits)
        self.assertIn(
            str(EXTENSION / "locale/fr/LC_MESSAGES/erplibre-home.mo"),
            ecrits,
        )
        # Le gabarit .pot n'est pas une langue.
        self.assertFalse(
            [e for e in ecrits if "locale/erplibre-home/" in e], ecrits
        )
        # La migration de l'ancienne identité précède le lien.
        migration = str(EXTENSION / "tools/migrate_legacy.py")
        sortie = fini.stdout.splitlines()
        self.assertEqual(migration, self.lignes(fini, "run: ")[0])
        self.assertLess(
            sortie.index("run: " + migration),
            sortie.index("write: " + self.lien),
        )

    def test_stream_deck_lists_the_rule_and_the_venv(self):
        fini = self.lancer("--dry-run", "--stream-deck")
        self.assertEqual(0, fini.returncode, fini.stderr)
        ecrits = self.lignes(fini, "write: ")
        self.assertIn(REGLE, ecrits)
        self.assertIn(self.lien, ecrits)
        # Lancé hors du dépôt, il se place quand même à sa racine.
        self.assertEqual([self.venv], self.lignes(fini, "venv: "))

    def test_the_translations_use_msgfmt_check_at_both_levels(self):
        attendus = [str(EXTENSION / "tools/migrate_legacy.py")] + [
            "msgfmt --check -o %s %s"
            % (
                EXTENSION / "locale" / langue / "LC_MESSAGES/erplibre-home.mo",
                EXTENSION / "po" / ("%s.po" % langue),
            )
            for langue in langues()
        ]
        self.assertIn("fr", langues())
        for niveau in ((), ("--stream-deck",)):
            with self.subTest(niveau=niveau):
                fini = self.lancer("--dry-run", *niveau)
                self.assertEqual(attendus, self.lignes(fini, "run: "))

    def test_it_calls_no_sudo_and_writes_nothing(self):
        fini = self.lancer("--dry-run", "--stream-deck", "--with-extras")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertFalse(self.trace_sudo.exists())
        self.assertEqual([], list(self.home.iterdir()))

    def test_it_shows_the_gsettings_keys_unless_no_enable(self):
        cles = [
            "org.gnome.shell enabled-extensions +" + UUID,
            "org.gnome.shell disable-user-extensions false",
        ]
        fini = self.lancer("--dry-run")
        self.assertEqual(cles, self.lignes(fini, "gsettings: "))
        fini = self.lancer("--dry-run", "--no-enable")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual([], self.lignes(fini, "gsettings: "))

    def test_extension_only_checks_no_system(self):
        """Ni os-release ni GNOME : un système refusé passe quand même."""
        fini = self.lancer(
            "--extension-only", "--dry-run", systeme="nixos", gnome="none"
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual([], self.lignes(fini, "family="))
        self.assertEqual([], self.lignes(fini, "packages: "))
        self.assertEqual([], self.lignes(fini, "venv: "))
        ecrits = self.lignes(fini, "write: ")
        self.assertNotIn(REGLE, ecrits)
        self.assertIn(self.lien, ecrits)
        self.assertEqual(
            str(EXTENSION / "tools/migrate_legacy.py"),
            self.lignes(fini, "run: ")[0],
        )
        self.assertEqual([], self.lignes(fini, "gsettings: "))

    def test_uninstall_lists_what_it_removes_and_keeps_packages(self):
        fini = self.lancer(
            "--uninstall", "--dry-run", systeme="nixos", gnome="none"
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [self.lien, REGLE, self.venv], self.lignes(fini, "remove: ")
        )
        self.assertEqual(
            ["org.gnome.shell enabled-extensions -" + UUID],
            self.lignes(fini, "gsettings: "),
        )
        self.assertEqual([], self.lignes(fini, "packages: "))

    def test_uninstall_stream_deck_removes_the_rule_and_the_venv_only(self):
        """L'extension reste liée et active : ses indicateurs disent alors
        que le niveau Stream Deck n'est pas installé."""
        fini = self.lancer("--uninstall", "--stream-deck", "--dry-run")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual([REGLE, self.venv], self.lignes(fini, "remove: "))
        self.assertEqual([], self.lignes(fini, "gsettings: "))
        self.assertNotIn(self.lien, fini.stdout)
        self.assertNotIn("enabled-extensions", fini.stdout)
        self.assertEqual([], self.lignes(fini, "packages: "))

    def test_uninstall_skips_the_gnome_version_check(self):
        """Une désinstallation marche encore quand GNOME a dépassé les
        versions que metadata.json déclare."""
        hors_liste = "%d.0" % (versions_acceptees()[-1] + 1)
        for niveau in ((), ("--stream-deck",)):
            with self.subTest(niveau=niveau):
                fini = self.lancer(
                    "--dry-run", "--uninstall", *niveau, gnome=hors_liste
                )
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertNotIn("UNSUPPORTED", fini.stderr)


class LesRefus(Installateur):
    def test_nixos_is_unsupported(self):
        self.assertNonSupporte(
            self.lancer("--dry-run", systeme="nixos"), "NixOS"
        )

    def test_an_unknown_distribution_is_unsupported(self):
        self.assertNonSupporte(
            self.lancer("--dry-run", systeme="inconnu"), "exempleos"
        )

    def test_no_gnome_shell_is_unsupported(self):
        self.assertNonSupporte(
            self.lancer("--dry-run", gnome="none"), "no GNOME Shell"
        )

    def test_gnome_outside_shell_version_is_unsupported(self):
        acceptees = versions_acceptees()
        liste = " ".join(str(v) for v in acceptees)
        for version in (
            "%d.0" % (acceptees[0] - 1),
            "%d.0" % (acceptees[-1] + 1),
        ):
            with self.subTest(version=version):
                self.assertNonSupporte(
                    self.lancer("--dry-run", gnome=version),
                    "GNOME %s not in shell-version (%s)" % (version, liste),
                )

    def test_both_bounds_of_shell_version_are_accepted(self):
        acceptees = versions_acceptees()
        for version in ("%d.0" % acceptees[0], "%d.2" % acceptees[-1]):
            with self.subTest(version=version):
                fini = self.lancer("--dry-run", gnome=version)
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual([version], self.lignes(fini, "gnome="))

    def test_shell_version_is_read_without_python(self):
        """python3 est un paquet de base, installé APRÈS cette lecture : un
        python3 qui échoue en tête du PATH ne change pas la liste lue, la
        même que celle de json.load."""
        trace = self.tmp / "python_appele"
        for nom in ("python3", "python"):
            self._commande(nom, 'echo "$@" >> "%s"\nexit 1\n' % trace)
        acceptees = versions_acceptees()
        fini = self.lancer("--dry-run", gnome="%d.1" % acceptees[0])
        self.assertEqual(0, fini.returncode, fini.stderr)
        hors_liste = "%d.0" % (acceptees[-1] + 1)
        self.assertNonSupporte(
            self.lancer("--dry-run", gnome=hors_liste),
            "(%s)" % " ".join(str(v) for v in acceptees),
        )
        self.assertFalse(trace.exists())

    def test_gnome_version_is_read_from_gnome_shell(self):
        self._commande("gnome-shell", 'echo "GNOME Shell 47.2"\n')
        fini = self.lancer("--dry-run", gnome=None)
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(["47.2"], self.lignes(fini, "gnome="))

    def test_root_is_refused(self):
        fini = self.lancer("--dry-run", uid="0")
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("root", fini.stderr)
        self.assertNotIn("UNSUPPORTED", fini.stderr)
        self.assertEqual([], self.lignes(fini, "family="))


if __name__ == "__main__":
    unittest.main()
