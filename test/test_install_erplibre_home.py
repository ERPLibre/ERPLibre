#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'installateur d'ERPLibre Home : vérifications, --dry-run et étapes.

Le script installe pour de vrai, sous le compte de l'utilisateur, avec sudo
pour les paquets. Ces tests ne touchent ni le système ni la session : la
lecture de os-release et de la version de GNOME passe par les variables
ERPLIBRE_HOME_*, la sortie de --dry-run est la surface convenue du script,
et chaque étape se joue sur le script sourcé avec
ERPLIBRE_HOME_SOURCE_ONLY=1, sous un faux sudo, un faux gsettings et un
HOME temporaire.

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
  --dry-run n'appelle pas sudo ni n'écrit rien ;
- l'activation passe par l'aide de make, sur le bus de la session ouverte,
  et retire l'UUID de disabled-extensions avant de l'ajouter à
  enabled-extensions ;
- une reprise ne réécrit ni la règle udev ni le lien, et un répertoire
  ordinaire à la place du lien n'est jamais écrasé ;
- seul unsupported sort en 2 : le code 2 d'une commande appelée sort en 1.
"""

import json
import os
import shutil
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
    # Un fichier que le shell ne sait pas sourcer.
    "casse": "ID=exemple\nif then fi (\n",
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

    def test_a_failing_gnome_shell_exits_one_without_unsupported(self):
        """Le code de gnome-shell ne devient pas celui du script : 2 est
        réservé à la ligne UNSUPPORTED."""
        self._commande("gnome-shell", "exit 2\n")
        fini = self.lancer("--dry-run", gnome=None)
        self.assertEqual(1, fini.returncode, fini.stdout + fini.stderr)
        self.assertNotIn("UNSUPPORTED", fini.stderr)

    def test_a_broken_os_release_is_unsupported(self):
        self.assertNonSupporte(
            self.lancer("--dry-run", systeme="casse"), "unreadable"
        )

    def test_root_is_refused(self):
        fini = self.lancer("--dry-run", uid="0")
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("root", fini.stderr)
        self.assertNotIn("UNSUPPORTED", fini.stderr)
        self.assertEqual([], self.lignes(fini, "family="))


INSTALLEUR = SCRIPT
MAKEFILE_STREAMDECK = RACINE / "conf/make.streamdeck.Makefile"


def sourcer(fragment, env=None):
    """Source l'installateur sans lancer main, puis joue `fragment`.

    ERPLIBRE_HOME_SOURCE_ONLY=1 définit les fonctions et s'arrête ; le
    fragment les redéfinit au besoin (sudo, gsettings_bus…) avant de les
    appeler. DBUS_SESSION_BUS_ADDRESS est retiré de l'environnement, sauf
    si `env` le pose. Rend le CompletedProcess.
    """
    if "ERPLIBRE_HOME_SOURCE_ONLY" not in INSTALLEUR.read_text(
        encoding="utf-8"
    ):
        raise AssertionError(
            "install_erplibre_home.sh has no ERPLIBRE_HOME_SOURCE_ONLY guard: "
            "sourcing it would run main"
        )
    code = 'ERPLIBRE_HOME_SOURCE_ONLY=1 source "$INSTALLEUR"\n' + fragment
    environ = dict(os.environ)
    environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
    environ["INSTALLEUR"] = str(INSTALLEUR)
    environ.update(env or {})
    return subprocess.run(
        ["bash", "-c", code],
        capture_output=True,
        text=True,
        env=environ,
        timeout=60,
    )


class TestListeEnabledExtensions(unittest.TestCase):
    """uuid_list_edit : les deux formes que gsettings affiche, lues par
    tools/gsettings_strv.py."""

    def editer(self, mode, courant):
        fait = sourcer(
            'uuid_list_edit "$MODE" "$COURANT" "$UUID"\n',
            {"MODE": mode, "COURANT": courant, "UUID": UUID},
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        return fait.stdout.strip()

    def test_la_presence_se_lit_dans_les_deux_formes(self):
        self.assertEqual(self.editer("has", "@as []"), "no")
        self.assertEqual(
            self.editer("has", "['autre@exemple.org', '%s']" % UUID), "yes"
        )
        self.assertEqual(self.editer("has", "['autre@exemple.org']"), "no")

    def test_le_retrait_garde_les_autres(self):
        self.assertEqual(
            self.editer("remove", "['autre@exemple.org', '%s']" % UUID),
            "['autre@exemple.org']",
        )

    def test_le_retrait_au_milieu_garde_l_ordre_des_autres(self):
        """La forme de disabled-extensions quand l'application Extensions y
        a rangé l'UUID parmi d'autres."""
        courant = "['a@exemple.org', '%s', 'b@exemple.org']" % UUID
        self.assertEqual(
            self.editer("remove", courant),
            "['a@exemple.org', 'b@exemple.org']",
        )

    def test_le_retrait_du_dernier_rend_une_liste_vide(self):
        """La forme qu'écrit gsettings_strv.format_strv, que gsettings
        accepte pour une clé « as »."""
        self.assertEqual(self.editer("remove", "['%s']" % UUID), "[]")

    def test_retirer_un_absent_rend_l_entree_inchangee(self):
        self.assertEqual(self.editer("remove", "@as []"), "@as []")

    def test_une_liste_illisible_sort_en_erreur(self):
        fait = sourcer(
            'uuid_list_edit has "$COURANT" "$UUID"\n',
            {"COURANT": "No such schema", "UUID": UUID},
        )
        self.assertNotEqual(fait.returncode, 0)

    def test_le_lecteur_est_celui_des_outils(self):
        """Un seul lecteur des listes de gsettings : celui que partagent
        migrate_legacy.py et enable_next_login.py."""
        texte = INSTALLEUR.read_text(encoding="utf-8")
        self.assertIn(
            "from gsettings_strv import format_strv, parse_strv", texte
        )
        self.assertIn('"${EXT_SRC}/tools" "$@"', texte)


class TestRegleUdev(unittest.TestCase):
    def test_le_contenu_est_les_deux_lignes_uaccess(self):
        fait = sourcer("udev_rule_content\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(
            fait.stdout,
            'SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"\n'
            'KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"\n',
        )

    def test_une_regle_identique_n_est_ni_reecrite_ni_rechargee(self):
        """La seconde exécution ne touche ni au fichier ni à udev."""
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            fragment = (
                'UDEV_RULE="$DOSSIER/70-streamdeck.rules"\n'
                'sudo() { echo "sudo $*" >>"$JOURNAL"; "$@"; }\n'
                'udevadm() { echo "udevadm $*" >>"$JOURNAL"; }\n'
                "write_udev_rule\n"
                'echo "--- second ---" >>"$JOURNAL"\n'
                "write_udev_rule\n"
            )
            fait = sourcer(fragment, {"DOSSIER": dossier, "JOURNAL": journal})
            self.assertEqual(fait.returncode, 0, fait.stderr)
            appels = Path(journal).read_text().split("--- second ---\n")
            self.assertIn("udevadm control --reload-rules", appels[0])
            self.assertIn("udevadm trigger", appels[0])
            self.assertEqual(appels[1], "")
            self.assertIn(
                'TAG+="uaccess"',
                Path(dossier, "70-streamdeck.rules").read_text(),
            )


class TestPaquets(unittest.TestCase):
    """install_packages : les paquets du niveau sont fatals, chaque extra est
    facultatif, EPEL ne vient qu'avec --stream-deck."""

    FRAGMENT = (
        'packages_for() { echo "base1 base2"; }\n'
        'streamdeck_packages_for() { echo "deck1 base2"; }\n'
        'extras_for() { echo "extra1 extra2"; }\n'
        "sudo() {\n"
        '    echo "$*" >>"$JOURNAL"\n'
        '    case "$*" in *extra1*) return 1 ;; esac\n'
        "}\n"
        "FAMILY=rhel\n"
        'OS="$OS_TEST"\n'
        'STREAM_DECK="$NIVEAU"\n'
        'WITH_EXTRAS="$EXTRAS"\n'
        "install_packages\n"
    )

    def jouer(self, os_id, extras, stream_deck="0"):
        with tempfile.TemporaryDirectory() as dossier:
            journal = os.path.join(dossier, "appels")
            Path(journal).touch()
            fait = sourcer(
                self.FRAGMENT,
                {
                    "JOURNAL": journal,
                    "OS_TEST": os_id,
                    "EXTRAS": extras,
                    "NIVEAU": stream_deck,
                },
            )
            return fait, Path(journal).read_text().splitlines()

    def test_sans_extras_seule_la_base_est_installee(self):
        fait, appels = self.jouer("ubuntu", "0")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(appels, ["dnf install -y base1 base2"])

    def test_le_stream_deck_ajoute_ses_paquets_sans_doublon(self):
        fait, appels = self.jouer("fedora", "0", stream_deck="1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(appels, ["dnf install -y base1 base2 deck1"])

    def test_un_extra_absent_avertit_et_n_arrete_rien(self):
        fait, appels = self.jouer("ubuntu", "1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(
            appels,
            [
                "dnf install -y base1 base2",
                "dnf install -y extra1",
                "dnf install -y extra2",
            ],
        )
        self.assertIn("extra1", fait.stdout)
        self.assertIn("WARNING", fait.stdout)

    def test_epel_precede_le_stream_deck_sur_rocky_et_alma(self):
        for os_id in ("rocky", "almalinux"):
            with self.subTest(os_id=os_id):
                fait, appels = self.jouer(os_id, "0", stream_deck="1")
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(appels[0], "dnf install -y epel-release")

    def test_la_base_ne_touche_pas_a_epel(self):
        for os_id in ("rocky", "almalinux"):
            with self.subTest(os_id=os_id):
                fait, appels = self.jouer(os_id, "0")
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(appels, ["dnf install -y base1 base2"])

    def test_pas_d_epel_sur_fedora(self):
        fait, appels = self.jouer("fedora", "0", stream_deck="1")
        self.assertNotIn("dnf install -y epel-release", appels)


class TestActivation(unittest.TestCase):
    """enable_extension sur un gsettings simulé par des fichiers, en tête du
    PATH, qui note chacun de ses appels. tools/enable_next_login.py, que le
    script lance, l'appelle comme le script lui-même ; gdbus et
    gnome-extensions sont simulés aussi."""

    CLES = (
        "enabled-extensions",
        "disabled-extensions",
        "disable-user-extensions",
    )

    def jouer(
        self, enabled, disable_user, disabled="@as []", ecrit=True, shell=False
    ):
        with tempfile.TemporaryDirectory() as dossier:
            valeurs = {
                "enabled-extensions": enabled,
                "disabled-extensions": disabled,
                "disable-user-extensions": disable_user,
            }
            for cle, valeur in valeurs.items():
                Path(dossier, cle).write_text(valeur + "\n")
            Path(dossier, "appels").touch()
            faux = Path(dossier, "bin")
            faux.mkdir()
            ecriture = (
                'printf "%s\\n" "$4" >"$DOSSIER/$3"'
                if ecrit
                else ":"  # une écriture qui ne prend pas
            )
            commandes = {
                "gsettings": (
                    'echo "$*" >>"$DOSSIER/appels"\n'
                    'case "$1" in\n'
                    '    get) cat "$DOSSIER/$3" ;;\n'
                    "    set) " + ecriture + " ;;\n"
                    "esac\n"
                ),
                # NameHasOwner : GNOME Shell tourne-t-il sur le bus ?
                "gdbus": "echo '(%s,)'\n" % ("true" if shell else "false"),
                "gnome-extensions": (
                    'echo "gnome-extensions $*" >>"$DOSSIER/appels"\n'
                ),
            }
            for nom, corps in commandes.items():
                (faux / nom).write_text("#!/bin/sh\n" + corps)
                (faux / nom).chmod(0o755)
            fragment = (
                'PATH="$FAUX:$PATH"\n'
                'shell_bus_address() { echo "unix:path=$DOSSIER/bus"; }\n'
                "enable_extension\n"
            )
            fait = sourcer(fragment, {"DOSSIER": dossier, "FAUX": str(faux)})
            etat = {
                cle: Path(dossier, cle).read_text().strip()
                for cle in self.CLES
            }
            appels = Path(dossier, "appels").read_text().splitlines()
            return fait, etat, appels

    def test_l_uuid_est_ajoute_et_les_extensions_permises(self):
        fait, etat, _appels = self.jouer("@as []", "true")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["enabled-extensions"], "['%s']" % UUID)
        self.assertEqual(etat["disable-user-extensions"], "false")

    def test_une_liste_deja_complete_n_est_pas_reecrite(self):
        courant = "['autre@exemple.org', '%s']" % UUID
        fait, etat, appels = self.jouer(courant, "false")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["enabled-extensions"], courant)
        self.assertEqual([a for a in appels if a.startswith("set ")], [])

    def test_une_ecriture_qui_ne_prend_pas_fait_echouer(self):
        fait, _etat, _appels = self.jouer("@as []", "true", ecrit=False)
        self.assertEqual(fait.returncode, 1)
        self.assertIn(UUID, fait.stderr)

    def test_l_uuid_desactive_par_l_utilisateur_est_retire_d_abord(self):
        """Éteinte un jour dans l'application Extensions, l'extension reste
        dans disabled-extensions, qui l'emporte sur enabled-extensions.
        Elle en sort AVANT d'entrer dans enabled-extensions : un échec entre
        les deux ne la laisse jamais dans les deux listes."""
        fait, etat, appels = self.jouer(
            "@as []",
            "false",
            disabled="['autre@exemple.org', '%s']" % UUID,
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["disabled-extensions"], "['autre@exemple.org']")
        self.assertEqual(etat["enabled-extensions"], "['%s']" % UUID)
        retrait = (
            "set org.gnome.shell disabled-extensions ['autre@exemple.org']"
        )
        ajout = "set org.gnome.shell enabled-extensions ['%s']" % UUID
        self.assertLess(appels.index(retrait), appels.index(ajout))

    def test_disabled_extensions_sans_l_uuid_n_est_pas_reecrite(self):
        fait, etat, appels = self.jouer(
            "['%s']" % UUID, "false", disabled="['autre@exemple.org']"
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["disabled-extensions"], "['autre@exemple.org']")
        self.assertFalse([a for a in appels if a.startswith("set ")], appels)

    def test_l_activation_passe_par_l_aide_de_make(self):
        """make erplibre_home_enable_extension et l'installateur écrivent
        les listes par le même code."""
        texte = INSTALLEUR.read_text(encoding="utf-8")
        self.assertIn(
            'on_session_bus "${EXT_SRC}/tools/enable_next_login.py" "${UUID}"',
            texte,
        )
        self.assertNotIn("uuid_list_edit add", texte)

    def test_gnome_extensions_enable_seulement_shell_en_marche(self):
        for shell in (False, True):
            with self.subTest(shell=shell):
                fait, _etat, appels = self.jouer("@as []", "true", shell=shell)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(
                    shell, "gnome-extensions enable %s" % UUID in appels
                )


class TestBusDeSession(unittest.TestCase):
    """gsettings_bus : le bus de la session ouverte d'abord.

    Une écriture faite sous dbus-run-session pendant qu'une session tourne
    passe par un second dconf-service ; celui de la session ne la voit pas
    et peut la recouvrir.
    """

    FRAGMENT = (
        "gsettings() {\n"
        '    echo "gsettings[${DBUS_SESSION_BUS_ADDRESS:-}] $*"\n'
        "}\n"
        'dbus-run-session() { echo "drs $*"; }\n'
        "gsettings_bus set org.gnome.shell disable-user-extensions false\n"
    )
    SUR_LE_BUS = (
        "gsettings[unix:path=/exemple/bus]"
        " set org.gnome.shell disable-user-extensions false"
    )

    def test_la_variable_de_session_recoit_l_ecriture(self):
        fait = sourcer(
            self.FRAGMENT,
            {"DBUS_SESSION_BUS_ADDRESS": "unix:path=/exemple/bus"},
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(fait.stdout.strip(), self.SUR_LE_BUS)
        self.assertNotIn("drs", fait.stdout)

    def test_sans_variable_le_socket_du_compte_sert(self):
        """ssh dans une machine dont la session graphique est ouverte."""
        fait = sourcer(
            'shell_bus_address() { echo "unix:path=/exemple/bus"; }\n'
            + self.FRAGMENT
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(fait.stdout.strip(), self.SUR_LE_BUS)

    def test_sans_aucun_bus_dbus_run_session_prend_le_relais(self):
        fait = sourcer("shell_bus_address() { return 1; }\n" + self.FRAGMENT)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(
            fait.stdout.strip(),
            "drs -- gsettings set org.gnome.shell disable-user-extensions"
            " false",
        )


class TestDesinstallation(unittest.TestCase):
    def test_retire_lien_regle_venv_et_uuid(self):
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier, "extensions")
            base.mkdir()
            (base / UUID).symlink_to(EXTENSION)
            Path(dossier, "70-streamdeck.rules").write_text("x\n")
            Path(dossier, "venv/bin").mkdir(parents=True)
            Path(dossier, "enabled-extensions").write_text(
                "['autre@exemple.org', '%s']\n" % UUID
            )
            fragment = (
                'EXT_LINK="$DOSSIER/extensions/$UUID"\n'
                'UDEV_RULE="$DOSSIER/70-streamdeck.rules"\n'
                'VENV="$DOSSIER/venv"\n'
                'sudo() { "$@"; }\n'
                "udevadm() { :; }\n"
                "gsettings_bus() {\n"
                '    case "$1" in\n'
                '        get) cat "$DOSSIER/$3" ;;\n'
                '        set) printf "%s\\n" "$4" >"$DOSSIER/$3" ;;\n'
                "    esac\n"
                "}\n"
                "uninstall\n"
            )
            fait = sourcer(fragment, {"DOSSIER": dossier, "UUID": UUID})
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertFalse(os.path.lexists(base / UUID))
            self.assertFalse(Path(dossier, "70-streamdeck.rules").exists())
            self.assertFalse(Path(dossier, "venv").exists())
            self.assertEqual(
                Path(dossier, "enabled-extensions").read_text().strip(),
                "['autre@exemple.org']",
            )
            # Le checkout pointé par le lien n'est pas touché.
            self.assertTrue((EXTENSION / "metadata.json").exists())

    def test_le_niveau_stream_deck_seul_garde_l_extension(self):
        """--uninstall --stream-deck : la règle, la relecture des règles et
        le venv partent ; le lien et enabled-extensions restent. Une seconde
        exécution n'appelle plus ni sudo ni udevadm."""
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier, "extensions")
            base.mkdir()
            (base / UUID).symlink_to(EXTENSION)
            Path(dossier, "70-streamdeck.rules").write_text("x\n")
            Path(dossier, "venv/bin").mkdir(parents=True)
            journal = Path(dossier, "appels")
            journal.touch()
            fragment = (
                'EXT_LINK="$DOSSIER/extensions/$UUID"\n'
                'UDEV_RULE="$DOSSIER/70-streamdeck.rules"\n'
                'VENV="$DOSSIER/venv"\n'
                'sudo() { echo "sudo $*" >>"$JOURNAL"; "$@"; }\n'
                "udevadm() { :; }\n"
                'gsettings_bus() { echo "gsettings $*" >>"$JOURNAL"; }\n'
                "STREAM_DECK=1\n"
                "step_uninstall\n"
                'echo "--- second ---" >>"$JOURNAL"\n'
                "step_uninstall\n"
            )
            fait = sourcer(
                fragment,
                {"DOSSIER": dossier, "UUID": UUID, "JOURNAL": str(journal)},
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertFalse(Path(dossier, "70-streamdeck.rules").exists())
            self.assertFalse(Path(dossier, "venv").exists())
            self.assertTrue((base / UUID).is_symlink())
            premier, second = journal.read_text().split("--- second ---\n")
            self.assertIn("sudo udevadm control --reload-rules", premier)
            self.assertNotIn("gsettings", premier + second)
            self.assertEqual(second, "")

    def test_un_repertoire_ordinaire_reste_en_place(self):
        with tempfile.TemporaryDirectory() as dossier:
            cible = Path(dossier, "extensions", UUID)
            cible.mkdir(parents=True)
            (cible / "metadata.json").write_text("{}")
            fragment = (
                'EXT_LINK="$DOSSIER/extensions/$UUID"\n'
                'UDEV_RULE="$DOSSIER/absente.rules"\n'
                'VENV="$DOSSIER/venv"\n'
                "gsettings_bus() { return 1; }\n"
                "uninstall\n"
            )
            fait = sourcer(fragment, {"DOSSIER": dossier, "UUID": UUID})
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertTrue((cible / "metadata.json").exists())


OUTILS_EXTENSION = shutil.which("glib-compile-schemas") and shutil.which(
    "msgfmt"
)


class TestExtensionSeule(unittest.TestCase):
    """--extension-only sur une copie du checkout, HOME temporaire.

    La copie porte l'installateur et l'extension, sous un répertoire dont le
    nom contient une espace : chaque chemin que le script bâtit doit être
    cité. Les schémas et les traductions se compilent pour de vrai, par
    glib-compile-schemas et msgfmt, sans venv ni réseau, et rien n'est écrit
    dans le vrai checkout. Une fausse migration remplace la vraie dans la
    copie : la vraie lirait le bus de session de l'utilisateur et sa base
    dconf.
    """

    def setUp(self):
        self._dossier = tempfile.TemporaryDirectory()
        racine = Path(self._dossier.name)
        self.depot = racine / "copie du depot"
        self.home = racine / "home"
        self.home.mkdir()
        (self.depot / "script/install").mkdir(parents=True)
        shutil.copy2(INSTALLEUR, self.depot / "script/install")
        shutil.copytree(
            EXTENSION,
            self.depot / "script/gnome-extension/erplibre_home",
            symlinks=True,
            ignore=shutil.ignore_patterns("locale", "gschemas.compiled"),
        )
        # Un faux sudo en tête du PATH : --extension-only ne doit jamais
        # l'appeler, et s'il le fait, rien ne s'exécute en root.
        self.trace_sudo = racine / "sudo.appele"
        self.faux_bin = racine / "bin"
        self.faux_bin.mkdir()
        sudo = self.faux_bin / "sudo"
        sudo.write_text(
            '#!/bin/sh\necho "$@" >>"%s"\nexit 1\n' % self.trace_sudo
        )
        sudo.chmod(0o755)
        self.path = "%s:%s" % (self.faux_bin, os.environ.get("PATH", ""))
        self.lien = self.home / ".local/share/gnome-shell/extensions" / UUID
        self.source = self.depot / "script/gnome-extension/erplibre_home"
        # La fausse migration note si le lien existait à son appel.
        self.migrations = racine / "migrations"
        migration = self.source / "tools/migrate_legacy.py"
        migration.write_text(
            "#!/bin/sh\n"
            'if [ -L "%s" ]; then echo apres; else echo avant; fi >>"%s"\n'
            % (self.lien, self.migrations)
        )
        migration.chmod(0o755)

    def tearDown(self):
        self._dossier.cleanup()

    def lancer(self, *options, env=None):
        environ = dict(os.environ)
        environ.update(
            {
                "HOME": str(self.home),
                "ERPLIBRE_HOME_UID": "1000",
                "PATH": self.path,
            }
        )
        environ.update(env or {})
        return subprocess.run(
            [
                "bash",
                str(self.depot / "script/install/install_erplibre_home.sh"),
                "--extension-only",
                *options,
            ],
            capture_output=True,
            text=True,
            env=environ,
            cwd="/",
            timeout=60,
        )

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_lien_schemas_et_locales(self):
        fait = self.lancer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(os.readlink(self.lien), str(self.source))
        # Une migration, avant que le lien existe.
        self.assertEqual("avant\n", self.migrations.read_text())
        self.assertTrue((self.source / "schemas/gschemas.compiled").exists())
        langues = sorted(p.stem for p in (self.source / "po").glob("*.po"))
        self.assertIn("fr", langues)
        for langue in langues:
            with self.subTest(langue=langue):
                self.assertTrue(
                    (
                        self.source
                        / "locale"
                        / langue
                        / "LC_MESSAGES/erplibre-home.mo"
                    )
                    .stat()
                    .st_size
                )
        self.assertFalse(self.trace_sudo.exists())
        # Ni venv ni polib : la base n'en a pas.
        self.assertFalse((self.depot / ".venv.streamdeck").exists())

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_un_checkout_dont_le_chemin_porte_une_espace(self):
        """Le lien vise le chemin entier, espace comprise, et non le
        morceau qui la précède."""
        self.assertIn(" ", str(self.source))
        fait = self.lancer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertTrue(self.lien.is_symlink())
        self.assertEqual(os.readlink(self.lien), str(self.source))
        self.assertTrue((self.lien / "metadata.json").exists())
        self.assertFalse(Path(str(self.depot).split(" ")[0]).exists())

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_une_seconde_execution_laisse_le_lien(self):
        self.assertEqual(self.lancer().returncode, 0)
        avant = os.lstat(self.lien).st_mtime_ns
        fait = self.lancer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(os.lstat(self.lien).st_mtime_ns, avant)

    def test_dry_run_n_ecrit_rien(self):
        fait = self.lancer("--dry-run")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("write: %s" % self.lien, fait.stdout)
        self.assertFalse(os.path.lexists(self.lien))

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_un_schema_invalide_fait_echouer(self):
        schema = next((self.source / "schemas").glob("*.gschema.xml"))
        schema.write_text("<schemalist><schema id='casse'>")
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1)

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_un_po_refuse_par_msgfmt_fait_echouer(self):
        (self.source / "po/fr.po").write_text('msgid "x"\n')
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1)

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_un_code_2_d_une_commande_sort_en_1(self):
        """2 est réservé à UNSUPPORTED : une commande qui rend 2 et arrête
        le script sous set -e le fait sortir en 1."""
        msgfmt = self.faux_bin / "msgfmt"
        msgfmt.write_text("#!/bin/sh\nexit 2\n")
        msgfmt.chmod(0o755)
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1, fait.stderr)
        self.assertNotIn("UNSUPPORTED", fait.stderr)

    def test_un_repertoire_ordinaire_arrete_l_installation_et_reste(self):
        """Une copie posée à la main par une ancienne installation : le
        script s'arrête en 1 en nommant le chemin, et n'y touche pas."""
        self.lien.mkdir(parents=True)
        (self.lien / "metadata.json").write_text("{}")
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1, fait.stdout)
        self.assertIn(str(self.lien), fait.stderr)
        self.assertNotIn("UNSUPPORTED", fait.stderr)
        self.assertEqual((self.lien / "metadata.json").read_text(), "{}")
        self.assertFalse(self.lien.is_symlink())


class TestTraductions(unittest.TestCase):
    """compile_locales sans msgfmt : l'installation s'arrête et nomme le
    paquet gettext de la famille."""

    def test_sans_msgfmt_le_message_nomme_le_paquet(self):
        attendus = {
            "debian": "install gettext",
            "suse": "install gettext-tools",
            "": "install gettext (gettext-tools on openSUSE)",
        }
        with tempfile.TemporaryDirectory() as vide:
            for famille, attendu in attendus.items():
                with self.subTest(famille=famille):
                    fait = sourcer(
                        'FAMILY="$FAM"\nPATH="$VIDE"\ncompile_locales\n',
                        {"FAM": famille, "VIDE": vide},
                    )
                    self.assertEqual(fait.returncode, 1, fait.stderr)
                    self.assertIn("msgfmt is missing; " + attendu, fait.stderr)


class TestLectureShellVersion(unittest.TestCase):
    """shell_versions lit metadata.json par tr, grep et sed : un python3
    qui échoue en tête du PATH ne change rien à ce qu'elle rend."""

    def lire(self, contenu=None):
        with tempfile.TemporaryDirectory() as dossier:
            faux = Path(dossier, "bin")
            faux.mkdir()
            for nom in ("python3", "python"):
                (faux / nom).write_text("#!/bin/sh\nexit 1\n")
                (faux / nom).chmod(0o755)
            env = {"FAUX": str(faux)}
            fragment = 'PATH="$FAUX:$PATH"\n'
            if contenu is not None:
                Path(dossier, "metadata.json").write_text(contenu)
                env["DOSSIER"] = dossier
                fragment += 'METADATA="$DOSSIER/metadata.json"\n'
            fait = sourcer(fragment + "shell_versions || true\n", env)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        return fait.stdout.strip()

    def test_la_liste_est_celle_de_json_load(self):
        with open(EXTENSION / "metadata.json", encoding="utf-8") as flux:
            attendu = " ".join(json.load(flux)["shell-version"])
        self.assertEqual(self.lire(), attendu)

    def test_un_tableau_sur_une_ligne(self):
        self.assertEqual(
            self.lire('{"uuid": "x", "shell-version": ["45", "46"], "v": 1}'),
            "45 46",
        )

    def test_un_tableau_sur_plusieurs_lignes(self):
        contenu = (
            '{\n  "shell-version": [\n    "47",\n    "48"\n  ],\n'
            '  "url": "https://exemple.invalid"\n}\n'
        )
        self.assertEqual(self.lire(contenu), "47 48")

    def test_sans_la_cle_la_liste_est_vide(self):
        self.assertEqual(self.lire('{"uuid": "x"}'), "")


def recette(cible):
    """Les lignes de recette de `cible` dans make.streamdeck.Makefile."""
    lignes = MAKEFILE_STREAMDECK.read_text().splitlines()
    debut = lignes.index("%s:" % cible) + 1
    recette_ = []
    for ligne in lignes[debut:]:
        if not ligne.startswith("\t"):
            break
        recette_.append(ligne.strip())
    return recette_


class TestMakefile(unittest.TestCase):
    def test_l_extension_passe_par_l_installateur(self):
        lignes = recette("erplibre_home_install_extension")
        self.assertEqual(
            lignes[0],
            "@./script/install/install_erplibre_home.sh --extension-only",
        )
        self.assertFalse(
            any("glib-compile-schemas" in ligne for ligne in lignes)
        )
        self.assertFalse(any("ln -s" in ligne for ligne in lignes))
        # La migration de l'ancienne identité a quitté la recette pour le
        # lien de l'installateur, qui la lance avant « ln -sfn » : elle
        # tourne une fois par installation, quel que soit le chemin d'entrée.
        self.assertFalse(any("migrate_legacy" in ligne for ligne in lignes))
        texte = INSTALLEUR.read_text(encoding="utf-8")
        self.assertLess(
            texte.index('"${EXT_SRC}/tools/migrate_legacy.py"'),
            texte.index('ln -sfn "${EXT_SRC}" "${EXT_LINK}"'),
        )
        # Les indications pour recharger restent.
        self.assertTrue(
            any(
                "make erplibre_home_enable_extension" in ligne
                for ligne in lignes
            )
        )

    def test_aucune_compilation_de_schema_n_avale_son_echec(self):
        for ligne in MAKEFILE_STREAMDECK.read_text().splitlines():
            if "glib-compile-schemas" in ligne:
                self.assertNotIn("|| true", ligne)
                self.assertNotIn("2>/dev/null", ligne)

    def test_les_deux_niveaux_s_installent_et_se_retirent(self):
        texte = MAKEFILE_STREAMDECK.read_text()
        attendues = {
            "erplibre_home_install": "",
            "erplibre_home_uninstall": " --uninstall",
            "erplibre_home_streamdeck_install": " --stream-deck",
            "erplibre_home_streamdeck_uninstall": " --uninstall --stream-deck",
        }
        for cible, options in attendues.items():
            with self.subTest(cible=cible):
                self.assertIn(".PHONY: %s\n" % cible, texte)
                self.assertEqual(
                    recette(cible),
                    ["./script/install/install_erplibre_home.sh" + options],
                )


if __name__ == "__main__":
    unittest.main()
