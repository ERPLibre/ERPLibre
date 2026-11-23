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
- l'extension et le programme du deck sont des projets Google Repo : repo
  init --standalone-manifest une seule fois, sans -g, jamais sur un .repo
  déjà initialisé ; leur projet ajouté au manifeste local, dont chaque
  autre octet reste ; puis « repo sync -n » et « repo sync -l » de leur
  seul chemin, l'extension avant la lecture de shell-version dans son
  metadata.json, le deck avant le venv, qui installe son requirements.txt ;
- un contenu qui n'est pas un checkout repo (clone git, copie,
  restes) est mis de côté entier, puis remis en place si la pose échoue ;
  un fetch qui échoue sur un checkout laisse l'ancien contenu en service et
  sort en 0 ; une sortie de repo ne va jamais sur la sortie d'erreur ;
- la garde de rétrécissement et celle du checkout imbriqué arrêtent
  l'installation avant tout sync ; sans git ni .venv.erplibre, la commande
  qui manque est nommée ; --dry-run annonce chaque effet sans appeler repo,
  et --uninstall ne touche ni à .repo ni au manifeste local ;
- un faux repo (ERPLIBRE_HOME_REPO) sert ces tests, et TestAvecVraiRepo
  rejoue le scénario avec le vrai, sur des dépôts nus file:// ;
- les traductions se compilent par « msgfmt --check », aux deux niveaux ;
- --uninstall retire tout, --uninstall --stream-deck tout sauf
  l'extension ; aucun des deux ne vérifie le système ;
- le niveau Stream Deck écrit l'unité du service et ses réglages ; une
  option absente garde la valeur déjà en place, le défaut ne vaut que pour
  une clé absente ; il n'active l'unité qu'avec --autostart et ne la
  démarre jamais ; les deux désinstallations l'arrêtent et la retirent ;
- les options du service exigent --stream-deck, et un dépôt dont le
  chemin porte un caractère que systemd refuse arrête l'installation ;
- un système non supporté sort en 2 avec UNE ligne « UNSUPPORTED: » sur la
  sortie d'erreur, celle que TODO et le test long affichent ; macOS se
  reconnaît à uname, avant os-release ;
- le venv manquant se crée par le python3 du système, le script tourne
  sous « set -euo pipefail », et le bilan d'une installation dit de
  rouvrir la session ;
- la liste des versions de GNOME acceptées est celle de metadata.json, lue
  sans python3 ;
- sans --with-extras ni --no-extras, sur un terminal seulement, la
  question des outils facultatifs nomme ceux qui manquent avec la commande
  de chacun ; « o » les installe un à un, toute autre réponse non, et
  --dry-run n'en affiche que les lignes « offer: » ;
- root est refusé, --extension-only refuse --stream-deck et --uninstall, et
  --dry-run n'appelle pas sudo ni n'écrit rien ;
- l'activation passe par l'aide de make, sur le bus de la session ouverte,
  et retire l'UUID de disabled-extensions avant de l'ajouter à
  enabled-extensions ;
- une reprise ne réécrit ni la règle udev ni le lien, et un répertoire
  ordinaire à la place du lien n'est jamais écrasé ;
- seul unsupported sort en 2 : le code 2 d'une commande appelée sort en 1.
- les .mo portent le domaine gettext de metadata.json, que le schéma
  déclare aussi ; « make test_gnome_extension » valide le schéma en
  --strict avant de lancer node sur chaque test unitaire, et
  « make extension_i18n_compile » compile chaque po/ sous ce domaine ;
  sans le checkout de l'extension, ces cibles s'arrêtent sur la commande
  qui l'installe.

Ce qui lit la vraie extension est sauté (SANS_EXTENSION) quand son checkout
manque.
"""

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from erplibre_home_extension import EXTENSION, SANS_EXTENSION  # noqa: E402
from streamdeck_deck import DECK as DECK_CLONE  # noqa: E402
from streamdeck_deck import PRESENT as DECK_PRESENT  # noqa: E402
from streamdeck_deck import charger as charger_du_deck  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/install/install_erplibre_home.sh"
UUID = "erplibre-home@technolibre.ca"
REGLE = "/etc/udev/rules.d/70-streamdeck.rules"
UNITE = "erplibre-home-streamdeck.service"

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
    "centos:10": 'ID="centos"\nID_LIKE="rhel fedora"\nVERSION_ID="10"\n',
    "rhel:10": 'ID="rhel"\nID_LIKE="fedora"\nVERSION_ID="10.0"\n',
    "opensuse-leap:16.0": (
        'ID="opensuse-leap"\nID_LIKE="suse opensuse"\nVERSION_ID="16.0"\n'
    ),
    "arch": "ID=arch\nBUILD_ID=rolling\n",
    "nixos": 'ID=nixos\nVERSION_ID="25.11"\n',
    # Inventés : un dérivé que seul ID_LIKE rattache, et un système que rien
    # ne rattache.
    "derive": 'ID=exemplelinux\nID_LIKE="ubuntu debian"\n',
    "derive-el": 'ID=exemplel\nID_LIKE="rhel fedora"\n',
    "derive-fedora": "ID=exemplefedora\nID_LIKE=fedora\n",
    "inconnu": "ID=exempleos\n",
    # Un fichier que le shell ne sait pas sourcer.
    "casse": "ID=exemple\nif then fi (\n",
}

APT = (
    "sudo apt-get -o DPkg::Lock::Timeout=600 update -qq && sudo env"
    " DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600"
    " install -y --no-install-recommends "
)
# La commande de chaque famille, avant ses paquets.
INSTALLE = {
    "debian": APT,
    "rhel": "sudo dnf install -y ",
    "suse": "sudo zypper --non-interactive install ",
    "arch": "sudo pacman -S --needed --noconfirm ",
}
# La base : schémas, gettext, python3 du système, make.
BASE = {
    "debian": INSTALLE["debian"] + "libglib2.0-bin gettext python3 make",
    "rhel": INSTALLE["rhel"] + "glib2 gettext python3 make",
    "suse": INSTALLE["suse"] + "glib2-tools gettext-tools python3 make",
    "arch": INSTALLE["arch"] + "glib2 gettext python make",
}
# --stream-deck : la base, puis les paquets du deck qu'elle ne porte pas.
DECK = {
    "debian": BASE["debian"]
    + " libhidapi-libusb0 libusb-1.0-0 python3-venv wmctrl",
    "rhel": BASE["rhel"] + " hidapi libusb1 wmctrl",
    "suse": BASE["suse"]
    + " libhidapi-libusb0 libusb-1_0-0 libgthread-2_0-0 wmctrl",
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


# Les commandes que extra_present cherche sur le PATH, une ou deux par extra.
COMMANDES_EXTRAS = (
    "mpv",
    "yt-dlp",
    "nmap",
    "keepassxc",
    "keepassxc-cli",
    "xdotool",
)


@contextlib.contextmanager
def terminal(frappe):
    """Un pseudo-terminal pour entrée standard, `frappe` déjà tapée : le
    script y voit « [ -t 0 ] ». b"\\x04" tape la fin de l'entrée. Rend le
    descripteur à passer en stdin."""
    maitre, esclave = os.openpty()
    try:
        os.write(maitre, frappe)
        yield esclave
    finally:
        os.close(esclave)
        os.close(maitre)


def sans_les_extras(dossier):
    """(PATH, PYTHONPATH) où aucun extra n'est présent : chaque répertoire
    du PATH qui porte une commande de COMMANDES_EXTRAS est remplacé, sous
    `dossier`, par des liens vers tout son contenu sauf elles ; un module
    lz4 qui lève ImportError masque celui du python3 de l'hôte."""
    dossier = Path(dossier)
    chemins = []
    for numero, chemin in enumerate(os.environ.get("PATH", "").split(":")):
        if not chemin or not os.path.isdir(chemin):
            continue
        noms = os.listdir(chemin)
        if not set(noms) & set(COMMANDES_EXTRAS):
            chemins.append(chemin)
            continue
        copie = dossier / ("path%d" % numero)
        copie.mkdir(parents=True)
        for nom in noms:
            if nom not in COMMANDES_EXTRAS:
                (copie / nom).symlink_to(os.path.join(chemin, nom))
        chemins.append(str(copie))
    modules = dossier / "pythonpath"
    modules.mkdir(parents=True)
    (modules / "lz4.py").write_text('raise ImportError("absent")\n')
    return ":".join(chemins), str(modules)


def avec_les_extras(dossier):
    """(répertoire à mettre en tête du PATH, PYTHONPATH) où chaque extra est
    présent : une fausse commande par outil, keepassxc par son seul
    keepassxc-cli, et un module lz4 vide."""
    dossier = Path(dossier)
    outils = dossier / "outils"
    outils.mkdir(parents=True)
    for nom in ("mpv", "yt-dlp", "nmap", "keepassxc-cli", "xdotool"):
        (outils / nom).write_text("#!/bin/sh\nexit 0\n")
        (outils / nom).chmod(0o755)
    modules = dossier / "pythonpath"
    modules.mkdir(parents=True)
    (modules / "lz4.py").write_text("")
    return str(outils), str(modules)


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
        # Un systemctl qui échoue : une étape du service lancée hors --dry-run
        # ne joint jamais le gestionnaire utilisateur du compte des tests.
        self._commande("systemctl", "exit 1\n")
        # Un repo qui note et échoue : ces tests lancent le script sur le
        # vrai checkout, en --dry-run, qui n'appelle jamais repo ; une
        # pose écrirait dans le checkout.
        self.trace_repo = self.tmp / "repo_appele"
        self._commande(
            "repo_interdit", 'echo "$@" >> "%s"\nexit 1\n' % self.trace_repo
        )
        self.lien = str(
            self.home / ".local/share/gnome-shell/extensions" / UUID
        )
        self.venv = str(RACINE / ".venv.streamdeck")
        self.unite = str(self.home / ".config/systemd/user" / UNITE)
        self.reglages = str(
            self.home / ".config/erplibre-home/streamdeck.conf"
        )

    def _commande(self, nom, corps):
        """Pose une commande factice en tête du PATH du script."""
        chemin = self.bin / nom
        chemin.write_text("#!/bin/sh\n" + corps, encoding="utf-8")
        chemin.chmod(0o755)

    def lancer(
        self,
        *options,
        systeme="ubuntu:24.04",
        gnome="48.1",
        uid="1000",
        entree=subprocess.DEVNULL,
        env=None,
    ):
        """Lance le script depuis un répertoire hors du dépôt.

        uid vaut 1000 par défaut : la suite peut tourner sous root, dans un
        conteneur, et le refus de root masquerait alors tout le reste.
        None laisse le script lire la vraie valeur. `entree` est l'entrée
        standard, jamais celle des tests : lancés d'un terminal, ils
        verraient sinon la question des outils facultatifs. `env` complète
        l'environnement en dernier.
        """
        environ = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("STREAMDECK_") and k != "XDG_CONFIG_HOME"
        }
        environ["HOME"] = str(self.home)
        environ["PATH"] = "%s:%s" % (self.bin, environ.get("PATH", ""))
        environ["ERPLIBRE_HOME_REPO"] = str(self.bin / "repo_interdit")
        if systeme is not None:
            fichier = self.tmp / "os-release"
            fichier.write_text(OS_RELEASE[systeme], encoding="utf-8")
            environ["ERPLIBRE_HOME_OS_RELEASE"] = str(fichier)
        if gnome is not None:
            environ["ERPLIBRE_HOME_GNOME_VERSION"] = gnome
        if uid is not None:
            environ["ERPLIBRE_HOME_UID"] = uid
        environ.update(env or {})
        return subprocess.run(
            [str(SCRIPT), *options],
            stdin=entree,
            capture_output=True,
            text=True,
            env=environ,
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
            "--no-extras",
            "--uninstall",
            "--dry-run",
        ):
            self.assertIn(option, fini.stdout)

    def test_an_unknown_option_exits_one(self):
        fini = self.lancer("--exemple", "--dry-run")
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("--exemple", fini.stderr)

    def test_uninstall_takes_no_install_option(self):
        for option in ("--with-extras", "--no-extras"):
            with self.subTest(option=option):
                fini = self.lancer("--uninstall", option, "--dry-run")
                self.assertEqual(1, fini.returncode, fini.stdout)

    def test_with_extras_and_no_extras_exclude_each_other(self):
        fini = self.lancer("--with-extras", "--no-extras", "--dry-run")
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("--with-extras", fini.stderr)
        self.assertIn("--no-extras", fini.stderr)
        self.assertNotIn("inconnue", fini.stderr)
        self.assertEqual([], self.lignes(fini, "packages: "))

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
        """EPEL suit la famille RHEL hors Fedora : un ID de RHEL ou de ses
        reconstructions, ou un ID_LIKE qui nomme rhel. Un dérivé que seul
        fedora rattache n'en a pas, comme Fedora."""
        for systeme in (
            "almalinux:10",
            "rocky:10",
            "centos:10",
            "rhel:10",
            "derive-el",
        ):
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
        for systeme in ("fedora:43", "derive-fedora"):
            with self.subTest(systeme=systeme):
                paquets = self.lignes(
                    self.lancer("--dry-run", "--stream-deck", systeme=systeme),
                    "packages: ",
                )
                self.assertEqual([DECK["rhel"]], paquets)

    def test_with_extras_adds_one_command_per_extra_at_both_levels(self):
        """Une commande par extra, celle même que l'installation lance : un
        extra absent du dépôt ne fait échouer que la sienne."""
        lz4 = {
            "ubuntu:24.04": "python3-lz4",
            "fedora:43": "python3-lz4",
            "opensuse-leap:16.0": "python3-lz4",
            "arch": "python-lz4",
        }
        for niveau in ((), ("--stream-deck",)):
            for systeme, module in lz4.items():
                with self.subTest(niveau=niveau, systeme=systeme):
                    prefixe = INSTALLE[FAMILLES[systeme]]
                    extras = ["mpv", "yt-dlp", "nmap", "keepassxc"]
                    extras += ["xdotool", module]
                    seul = self.lignes(
                        self.lancer("--dry-run", *niveau, systeme=systeme),
                        "packages: ",
                    )
                    paquets = self.lignes(
                        self.lancer(
                            "--dry-run",
                            "--with-extras",
                            *niveau,
                            systeme=systeme,
                        ),
                        "packages: ",
                    )
                    self.assertEqual(
                        seul + [prefixe + extra for extra in extras], paquets
                    )

    def test_without_extras_no_extra_package(self):
        fini = self.lancer("--dry-run", "--stream-deck")
        self.assertNotIn("lz4", fini.stdout)
        self.assertNotIn("keepassxc", fini.stdout)


class LOffreDesExtras(Installateur):
    """--dry-run sur un terminal : une ligne « offer: » par extra manquant,
    la commande même que la réponse « o » lancerait. Jamais de question
    sous --dry-run, jamais d'offre sans terminal, avec --no-extras ou
    --with-extras, ni quand rien ne manque."""

    def offres(self, *options, systeme="ubuntu:24.04", tty=True, extras=False):
        """Le --dry-run, sur un terminal où « o » est déjà tapé quand `tty`,
        sans aucun extra présent, ou avec tous quand `extras`. Aucune
        question n'y est posée."""
        dossier = tempfile.mkdtemp(dir=self.tmp)
        if extras:
            outils, modules = avec_les_extras(dossier)
            env = {
                "PATH": "%s:%s:%s"
                % (self.bin, outils, os.environ.get("PATH", "")),
                "PYTHONPATH": modules,
            }
        else:
            chemin, modules = sans_les_extras(dossier)
            env = {
                "PATH": "%s:%s" % (self.bin, chemin),
                "PYTHONPATH": modules,
            }
        if tty:
            with terminal(b"o\n") as entree:
                fini = self.lancer(
                    "--dry-run",
                    *options,
                    systeme=systeme,
                    entree=entree,
                    env=env,
                )
        else:
            fini = self.lancer("--dry-run", *options, systeme=systeme, env=env)
        self.assertEqual(0, fini.returncode, fini.stdout + fini.stderr)
        self.assertNotIn("(y/N)", fini.stdout)
        self.assertNotIn("(o/N)", fini.stdout)
        return fini

    def test_a_terminal_gets_one_offer_per_missing_extra(self):
        lz4 = {"ubuntu:24.04": "python3-lz4", "arch": "python-lz4"}
        for systeme, module in lz4.items():
            with self.subTest(systeme=systeme):
                fini = self.offres(systeme=systeme)
                prefixe = INSTALLE[FAMILLES[systeme]]
                extras = ["mpv", "yt-dlp", "nmap", "keepassxc", "xdotool"]
                self.assertEqual(
                    [prefixe + extra for extra in extras + [module]],
                    self.lignes(fini, "offer: "),
                )

    def test_no_offer_without_a_terminal_or_with_an_extras_option(self):
        for options, tty in (
            ((), False),
            (("--no-extras",), True),
            (("--with-extras",), True),
            (("--stream-deck", "--no-extras"), True),
        ):
            with self.subTest(options=options, tty=tty):
                fini = self.offres(*options, tty=tty)
                self.assertEqual([], self.lignes(fini, "offer: "))

    def test_no_offer_when_every_extra_is_present(self):
        fini = self.offres(extras=True)
        self.assertEqual([], self.lignes(fini, "offer: "))


class LeDryRun(Installateur):
    @SANS_EXTENSION
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
        self.assertEqual(
            ["install -r %s/requirements.txt" % DECK_CLONE],
            self.lignes(fini, "pip: "),
        )

    def test_stream_deck_brings_the_deck_sync_before_the_venv(self):
        """Une ligne « deck: repo sync » avant celle du venv, qui lit les
        dépendances du checkout ; la base n'en a pas."""
        fini = self.lancer("--dry-run", "--stream-deck")
        sortie = fini.stdout.splitlines()
        (deck,) = [s for s in sortie if s.startswith("deck: repo sync ")]
        self.assertTrue(deck.startswith("deck: repo sync %s (" % DECK_CLONE))
        self.assertLess(sortie.index(deck), sortie.index("venv: " + self.venv))
        self.assertEqual([], self.lignes(self.lancer("--dry-run"), "deck: "))

    @SANS_EXTENSION
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

    @SANS_EXTENSION
    def test_the_mo_files_carry_the_gettext_domain_of_metadata(self):
        """GNOME Shell loads <domain>.mo for the gettext-domain of
        metadata.json, and the schema names the same domain."""
        fini = self.lancer("--dry-run")
        sorties = [
            Path(ligne.split(" -o ")[1].split(" ")[0]).name
            for ligne in self.lignes(fini, "run: ")
            if ligne.startswith("msgfmt ")
        ]
        self.assertEqual(sorties, ["%s.mo" % domaine()] * len(langues()))
        schema = next((EXTENSION / "schemas").glob("*.gschema.xml"))
        self.assertEqual(
            ET.parse(schema).getroot().get("gettext-domain"), domaine()
        )

    def test_it_calls_no_sudo_and_writes_nothing(self):
        fini = self.lancer("--dry-run", "--stream-deck", "--with-extras")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertFalse(self.trace_sudo.exists())
        self.assertFalse(self.trace_repo.exists())
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

    def test_no_enable_still_migrates_and_links_the_extension(self):
        """--no-enable ne retire que l'activation : la migration passe
        quand même, et reporte sur le nouvel UUID un état déjà activé."""
        fini = self.lancer("--dry-run", "--no-enable")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn(
            str(EXTENSION / "tools/migrate_legacy.py"),
            self.lignes(fini, "run: "),
        )
        self.assertIn(self.lien, self.lignes(fini, "write: "))

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

    @SANS_EXTENSION
    def test_uninstall_lists_what_it_removes_and_keeps_packages(self):
        fini = self.lancer(
            "--uninstall", "--dry-run", systeme="nixos", gnome="none"
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [self.lien, self.unite, self.reglages, REGLE, self.venv],
            self.lignes(fini, "remove: "),
        )
        self.assertEqual(
            ["org.gnome.shell enabled-extensions -" + UUID],
            self.lignes(fini, "gsettings: "),
        )
        self.assertEqual([], self.lignes(fini, "packages: "))

    def test_uninstall_stream_deck_keeps_the_extension_only(self):
        """L'extension reste liée et active : ses indicateurs disent alors
        que le niveau Stream Deck n'est pas installé. Le clone du deck reste,
        comme celui de l'extension."""
        fini = self.lancer("--uninstall", "--stream-deck", "--dry-run")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            [self.unite, self.reglages, REGLE, self.venv],
            self.lignes(fini, "remove: "),
        )
        self.assertEqual([], self.lignes(fini, "deck: "))
        self.assertEqual([], self.lignes(fini, "gsettings: "))
        self.assertNotIn(self.lien, fini.stdout)
        self.assertNotIn("enabled-extensions", fini.stdout)
        self.assertEqual([], self.lignes(fini, "packages: "))

    @SANS_EXTENSION
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
    def test_macos_is_unsupported(self):
        """uname -s se lit avant os-release : un os-release présent ne
        fait pas passer macOS pour la distribution qu'il nomme."""
        self._commande("uname", "echo Darwin\n")
        self.assertNonSupporte(self.lancer("--dry-run"), "macOS")

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

    @SANS_EXTENSION
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

    @SANS_EXTENSION
    def test_both_bounds_of_shell_version_are_accepted(self):
        acceptees = versions_acceptees()
        for version in ("%d.0" % acceptees[0], "%d.2" % acceptees[-1]):
            with self.subTest(version=version):
                fini = self.lancer("--dry-run", gnome=version)
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual([version], self.lignes(fini, "gnome="))

    @SANS_EXTENSION
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
BIBLIOTHEQUE = RACINE / "script/install/erplibre_home_settings.sh"
MAKEFILE_STREAMDECK = RACINE / "conf/make.streamdeck.Makefile"


def sourcer(fragment, env=None, entree=subprocess.DEVNULL):
    """Source l'installateur sans lancer main, puis joue `fragment`.

    ERPLIBRE_HOME_SOURCE_ONLY=1 définit les fonctions et s'arrête ; le
    fragment les redéfinit au besoin (sudo, gsettings_bus…) avant de les
    appeler. DBUS_SESSION_BUS_ADDRESS est retiré de l'environnement, sauf
    si `env` le pose. HOME est un répertoire temporaire et XDG_CONFIG_HOME
    est retiré : l'unité et les réglages du service que le script sourcé
    désigne ne sont jamais ceux du compte qui lance les tests. `entree` est
    l'entrée standard, /dev/null par défaut. Rend le CompletedProcess.
    """
    if "ERPLIBRE_HOME_SOURCE_ONLY" not in INSTALLEUR.read_text(
        encoding="utf-8"
    ):
        raise AssertionError(
            "install_erplibre_home.sh has no ERPLIBRE_HOME_SOURCE_ONLY guard: "
            "sourcing it would run main"
        )
    code = 'ERPLIBRE_HOME_SOURCE_ONLY=1 source "$INSTALLEUR"\n' + fragment
    with tempfile.TemporaryDirectory() as maison:
        environ = dict(os.environ)
        environ.pop("DBUS_SESSION_BUS_ADDRESS", None)
        environ.pop("XDG_CONFIG_HOME", None)
        environ["HOME"] = maison
        environ["INSTALLEUR"] = str(INSTALLEUR)
        environ.update(env or {})
        return subprocess.run(
            ["bash", "-c", code],
            stdin=entree,
            capture_output=True,
            text=True,
            env=environ,
            timeout=60,
        )


@SANS_EXTENSION
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
    def test_le_contenu_est_uaccess_puis_l_unite_du_deck(self):
        """Deux lignes uaccess, puis le périphérique USB entier, tagué
        pour systemd sous le nom stable que WantedBy= de l'unité nomme."""
        fait = sourcer("udev_rule_content\n")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(
            fait.stdout,
            'SUBSYSTEM=="usb", ATTRS{idVendor}=="0fd9", TAG+="uaccess"\n'
            'KERNEL=="hidraw*", ATTRS{idVendor}=="0fd9", TAG+="uaccess"\n'
            'SUBSYSTEM=="usb", ENV{DEVTYPE}=="usb_device",'
            ' ATTR{idVendor}=="0fd9", TAG+="systemd",'
            ' ENV{SYSTEMD_ALIAS}="/sys/subsystem/erplibre/streamdeck"\n',
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


class TestQuestionDesExtras(unittest.TestCase):
    """step_packages sans --with-extras, sous un PATH réduit à de fausses
    commandes : mpv, keepassxc-cli et un python3 qui importe lz4 sont
    présents, yt-dlp, nmap et xdotool manquent. Le python3 du système,
    ERPLIBRE_HOME_SYSTEM_PYTHON, n'existe pas, sauf quand `systeme` le
    simule. La question nomme les manquants seuls, avec leur commande, puis
    o, oui, y ou yes les installent un à un ; toute autre réponse, et la fin
    de l'entrée, non."""

    PACMAN = "sudo pacman -S --needed --noconfirm "
    BASE = "pacman -S --needed --noconfirm glib2 gettext python make"
    MANQUANTS = ("yt-dlp", "nmap", "xdotool")
    FRAGMENT = (
        "sudo() {\n"
        '    echo "$*" >>"$JOURNAL"\n'
        '    case "$*" in *" $ECHEC") return 1 ;; esac\n'
        "}\n"
        "FAMILY=arch\n"
        'DRY_RUN="$SEC"\n'
        'WITH_EXTRAS="$AVEC"\n'
        'NO_EXTRAS="$SANS"\n'
        'PATH="$FAUX"\n'
        "step_packages\n"
    )
    ANGLAIS = "Install the optional tools? (y/N): "
    FRANCAIS = "Installer les outils facultatifs ? (o/N) : "

    @classmethod
    def installes(cls, noms=MANQUANTS):
        """Les appels de sudo qui installent `noms`, un par extra."""
        return [cls.PACMAN[len("sudo ") :] + nom for nom in noms]

    def jouer(
        self,
        frappe=b"o\n",
        tty=True,
        presents=("mpv", "keepassxc-cli", "python3"),
        dry_run="0",
        avec="0",
        sans="0",
        echec="",
        langue=None,
        echouent=(),
        systeme=None,
    ):
        """Rend (CompletedProcess, appels de sudo, une ligne par appel).
        `echouent` nomme de fausses commandes du PATH qui sortent en 1 ;
        `systeme` est le code de sortie du faux python3 du système, absent
        quand il vaut None."""
        with tempfile.TemporaryDirectory() as dossier:
            faux = Path(dossier, "bin")
            faux.mkdir()
            codes = {nom: 0 for nom in presents}
            codes.update({nom: 1 for nom in echouent})
            for nom, code in codes.items():
                (faux / nom).write_text("#!/bin/sh\nexit %d\n" % code)
                (faux / nom).chmod(0o755)
            python_systeme = Path(dossier, "systeme", "python3")
            if systeme is not None:
                python_systeme.parent.mkdir()
                python_systeme.write_text("#!/bin/sh\nexit %d\n" % systeme)
                python_systeme.chmod(0o755)
            journal = Path(dossier, "appels")
            journal.touch()
            env = {
                "ERPLIBRE_HOME_SYSTEM_PYTHON": str(python_systeme),
                "JOURNAL": str(journal),
                "FAUX": str(faux),
                "SEC": dry_run,
                "AVEC": avec,
                "SANS": sans,
                "ECHEC": echec,
                "LC_ALL": "",
                "LC_MESSAGES": "",
                "LANG": "C",
            }
            env.update(langue or {})
            if tty:
                with terminal(frappe) as entree:
                    fait = sourcer(self.FRAGMENT, env, entree)
            else:
                fait = sourcer(self.FRAGMENT, env)
            return fait, journal.read_text().splitlines()

    def test_the_question_names_the_missing_tools_and_their_command(self):
        fait, _ = self.jouer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("yt-dlp nmap xdotool", fait.stdout)
        for nom in self.MANQUANTS:
            self.assertIn("    " + self.PACMAN + nom + "\n", fait.stdout)
        for present in ("mpv", "keepassxc", "python-lz4"):
            self.assertNotIn(present, fait.stdout)
        self.assertIn(self.ANGLAIS, fait.stdout)

    def test_yes_installs_the_missing_extras_one_by_one(self):
        for frappe in (b"o\n", b"OUI\n", b"y\n", b"Yes\n"):
            with self.subTest(frappe=frappe):
                fait, appels = self.jouer(frappe)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual([self.BASE] + self.installes(), appels)

    def test_anything_else_installs_no_extra(self):
        for frappe in (b"n\n", b"\n", b"\x04", b"non merci\n"):
            with self.subTest(frappe=frappe):
                fait, appels = self.jouer(frappe)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertIn(self.ANGLAIS, fait.stdout)
                self.assertEqual([self.BASE], appels)

    def test_a_failed_extra_only_warns(self):
        fait, appels = self.jouer(echec="nmap")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual([self.BASE] + self.installes(), appels)
        self.assertIn("WARNING: optional package nmap", fait.stdout)

    def test_no_question_when_nothing_is_missing(self):
        tous = ("mpv", "yt-dlp", "nmap", "keepassxc", "xdotool", "python3")
        fait, appels = self.jouer(presents=tous)
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn(self.ANGLAIS, fait.stdout)
        self.assertEqual([self.BASE], appels)

    def test_lz4_is_judged_by_the_system_python(self):
        """Le paquet pose lz4 dans le python3 du système. Le python3 du
        PATH d'un terminal est souvent un venv activé ou un shim : son
        import ne décide pas, sauf quand le système n'a pas de python3."""
        for nom, options, manque in (
            (
                "système oui, PATH non",
                {"systeme": 0, "echouent": ("python3",)},
                False,
            ),
            ("système non, PATH oui", {"systeme": 1}, True),
            ("pas de python3 du système", {"echouent": ("python3",)}, True),
        ):
            with self.subTest(nom):
                fait, _ = self.jouer(b"n\n", **options)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertEqual(manque, "python-lz4" in fait.stdout)

    def test_the_system_python_is_usr_bin_python3_by_default(self):
        fait = sourcer(
            'echo "$SYSTEM_PYTHON"\n', {"ERPLIBRE_HOME_SYSTEM_PYTHON": ""}
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual("/usr/bin/python3\n", fait.stdout)

    def test_no_question_without_terminal_or_with_an_extras_option(self):
        for nom, options in (
            ("pas de terminal", {"tty": False}),
            ("--no-extras", {"sans": "1"}),
        ):
            with self.subTest(nom):
                fait, appels = self.jouer(**options)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertNotIn(self.ANGLAIS, fait.stdout)
                self.assertEqual([self.BASE], appels)

    def test_with_extras_installs_every_extra_without_question(self):
        fait, appels = self.jouer(avec="1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn(self.ANGLAIS, fait.stdout)
        tous = ("mpv", "yt-dlp", "nmap", "keepassxc", "xdotool", "python-lz4")
        self.assertEqual([self.BASE] + self.installes(tous), appels)

    def test_the_dry_run_offers_without_asking(self):
        fait, appels = self.jouer(dry_run="1")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertNotIn(self.ANGLAIS, fait.stdout)
        self.assertEqual([], appels)
        self.assertEqual(
            ["offer: " + self.PACMAN + nom for nom in self.MANQUANTS],
            [
                ligne
                for ligne in fait.stdout.splitlines()
                if ligne.startswith("offer: ")
            ],
        )

    def test_the_question_follows_the_message_language(self):
        for langue, question in (
            ({"LANG": "fr_CA.UTF-8"}, self.FRANCAIS),
            ({"LC_MESSAGES": "fr_FR.UTF-8"}, self.FRANCAIS),
            ({"LANG": "fr_CA.UTF-8", "LC_ALL": "C"}, self.ANGLAIS),
            ({"LANG": "en_CA.UTF-8"}, self.ANGLAIS),
        ):
            with self.subTest(langue=langue):
                fait, appels = self.jouer(b"oui\n", langue=langue)
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertIn(question, fait.stdout)
                self.assertEqual(4, len(appels))


def _git(depot, *args):
    """git dans `depot`, sous une identité de test ; rend sa sortie."""
    return subprocess.run(
        [
            "git",
            "-C",
            str(depot),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            *args,
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


# Un faux git-repo, que ERPLIBRE_HOME_REPO met à la place du vrai. Il note
# chaque appel, ses arguments sur une ligne, dans $FAUX_REPO_TRACE, et écrit
# du bruit sur sa sortie d'erreur, comme le mode standalone du vrai.
# FAUX_REPO_ECHEC nomme, séparés par des virgules, les appels qui échouent :
# init, fetch (sync -n) ou local (sync -l). « sync -l -c CHEMIN » pose
# CHEMIN depuis le dépôt nu $FAUX_REPO_DEPOTS/<dernier nom de CHEMIN>.git,
# en HEAD détaché sur main, son .git en lien vers .repo/projects/, qu'il
# reprend quand il existe, puis l'inscrit dans .repo/project.list ; un
# CHEMIN déjà posé passe au main du dépôt nu. « list -p --all » rend les chemins que nomment les manifestes
# locaux.
FAUX_REPO = r"""#!/bin/bash
printf '%s\n' "$*" >>"${FAUX_REPO_TRACE:-/dev/null}"
echo "project .repo/manifests: unparseable HEAD; trying to recover." >&2
echoue() {
    case ",${FAUX_REPO_ECHEC:-}," in *",$1,"*) exit 1 ;; esac
}
case "$1" in
    init)
        echoue init
        mkdir -p .repo/repo
        : >.repo/repo/main.py
        echo '<manifest />' >.repo/manifest.xml
        ;;
    sync)
        chemin="$4"
        if [ "$2" = -n ]; then
            echoue fetch
            exit 0
        fi
        echoue local
        depot="${FAUX_REPO_DEPOTS}/$(basename "${chemin}").git"
        projet="${PWD}/.repo/projects/${chemin}.git"
        if [ ! -e "${chemin}/.git" ]; then
            if [ ! -d "${projet}" ]; then
                tmp="$(mktemp -d)"
                git clone -q --no-checkout "${depot}" "${tmp}/c" || exit 1
                mkdir -p "$(dirname "${projet}")"
                mv "${tmp}/c/.git" "${projet}"
                rm -rf "${tmp}"
            fi
            mkdir -p "${chemin}"
            ln -s "${projet}" "${chemin}/.git"
        fi
        git -C "${chemin}" fetch -q "${depot}" main || exit 1
        git -C "${chemin}" -c advice.detachedHead=false \
            checkout -q --detach FETCH_HEAD || exit 1
        grep -qxF "${chemin}" .repo/project.list 2>/dev/null \
            || echo "${chemin}" >>.repo/project.list
        ;;
    list)
        cat .repo/local_manifests/*.xml 2>/dev/null | tr '\n' ' ' \
            | grep -o ' path="[^"]*"' | sed 's/^ path="//; s/"$//'
        ;;
esac
exit 0
"""

EXT_CHEMIN = "script/gnome-extension/erplibre_home"
DECK_CHEMIN = "script/stream_deck/deck"
MANIFESTE_EXT = "manifest/git_manifest_erplibre_home_gnome_extension.xml"
MANIFESTE_DECK = "manifest/git_manifest_erplibre_streamdeck_deck.xml"
MANIFESTE_INIT = "manifest/git_manifest_erplibre.xml"


def depot_nu(amont, nom, fichiers):
    """Le dépôt nu `amont`/`nom`.git, sur main, d'un premier commit qui porte
    `fichiers` ({chemin relatif: texte}) ou, quand `fichiers` est un
    dossier, une copie de ce dossier sans .git. Son dépôt de travail,
    `amont`/travail/`nom`, reste pour pousser la suite. Rend le chemin du
    dépôt nu."""
    travail = Path(amont, "travail", nom)
    if isinstance(fichiers, Path):
        shutil.copytree(
            fichiers,
            travail,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".git", "locale", "gschemas.compiled", "__pycache__"
            ),
        )
    else:
        for chemin, texte in fichiers.items():
            (travail / chemin).parent.mkdir(parents=True, exist_ok=True)
            (travail / chemin).write_text(texte, encoding="utf-8")
    _git(travail, "init", "-q", "-b", "main")
    _git(travail, "add", "-A")
    _git(travail, "commit", "-q", "-m", "un")
    nu = Path(amont, nom + ".git")
    subprocess.run(
        ["git", "clone", "-q", "--bare", str(travail), str(nu)], check=True
    )
    return nu


def pousser(amont, nom, fichier, texte=""):
    """Un commit de plus sur le main du dépôt nu `amont`/`nom`.git, qui
    pose `fichier` ; rend son sha."""
    travail = Path(amont, "travail", nom)
    (travail / fichier).parent.mkdir(parents=True, exist_ok=True)
    (travail / fichier).write_text(texte, encoding="utf-8")
    _git(travail, "add", "-A")
    _git(travail, "commit", "-q", "-m", "suite")
    _git(travail, "push", "-q", str(Path(amont, nom + ".git")), "main")
    return _git(travail, "rev-parse", "HEAD")


class CopieDuCheckout(unittest.TestCase):
    """Une copie du checkout dans un dossier temporaire : l'installateur, sa
    bibliothèque et les trois manifestes, sans .repo, sans l'extension ni le
    deck. Deux dépôts nus, amont/erplibre_home.git et amont/deck.git,
    portent un main minimal de chacun, que le faux repo pose. Le script
    sourcé ou lancé depuis la copie la prend pour racine : rien ne s'écrit
    dans le vrai checkout, et HOME est temporaire."""

    NOM_DE_LA_COPIE = "depot"

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        self.depot = self.tmp / self.NOM_DE_LA_COPIE
        (self.depot / "script/install").mkdir(parents=True)
        (self.depot / "manifest").mkdir()
        shutil.copy2(INSTALLEUR, self.depot / "script/install")
        shutil.copy2(BIBLIOTHEQUE, self.depot / "script/install")
        for manifeste in (MANIFESTE_INIT, MANIFESTE_EXT, MANIFESTE_DECK):
            shutil.copy2(RACINE / manifeste, self.depot / manifeste)
        self.home = self.tmp / "home"
        self.home.mkdir()
        self.amont = self.tmp / "amont"
        self.depot_amont_ext()
        depot_nu(
            self.amont,
            "deck",
            {
                "erplibre_streamdeck/__main__.py": "",
                "requirements.txt": "streamdeck\n",
            },
        )
        self.bin = self.tmp / "bin"
        self.bin.mkdir()
        self.faux_repo = self.bin / "faux_repo"
        self.faux_repo.write_text(FAUX_REPO, encoding="utf-8")
        self.faux_repo.chmod(0o755)
        self.trace = self.tmp / "repo.trace"
        self.ext = self.depot / EXT_CHEMIN
        self.deck = self.depot / DECK_CHEMIN
        self.local = self.depot / ".repo/local_manifests/erplibre_manifest.xml"
        self.installeur = (
            self.depot / "script/install/install_erplibre_home.sh"
        )

    def depot_amont_ext(self):
        """Le dépôt nu de l'extension ; une sous-classe en pose un autre."""
        depot_nu(
            self.amont, "erplibre_home", {"metadata.json": METADATA_MINIMAL}
        )

    def environ(self, env=None):
        environ = {
            k: v
            for k, v in os.environ.items()
            if k not in ("XDG_CONFIG_HOME", "DBUS_SESSION_BUS_ADDRESS")
            and not k.startswith(("ERPLIBRE_HOME_", "FAUX_REPO_"))
        }
        environ.update(
            {
                "HOME": str(self.home),
                "ERPLIBRE_HOME_UID": "1000",
                "ERPLIBRE_HOME_REPO": str(self.faux_repo),
                "FAUX_REPO_TRACE": str(self.trace),
                "FAUX_REPO_DEPOTS": str(self.amont),
                "INSTALLEUR": str(self.installeur),
                # Les journaux de repo, gardés quand une pose échoue.
                "TMPDIR": str(self.tmp),
            }
        )
        environ.update(env or {})
        return {k: v for k, v in environ.items() if v is not None}

    def jouer(self, fragment, env=None):
        """Source l'installateur de la copie sans lancer main, puis joue
        `fragment`."""
        return subprocess.run(
            [
                "bash",
                "-c",
                'ERPLIBRE_HOME_SOURCE_ONLY=1 source "$INSTALLEUR"\n'
                + fragment,
            ],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            env=self.environ(env),
            cwd="/",
            timeout=60,
        )

    def poser(self, *etapes, env=None, dry_run=False):
        """check_fetch_tools puis les étapes nommées, « extension »
        (step_extension_source) ou « deck » (step_deck au niveau Stream
        Deck) ; le bilan, une ligne par effet, sur la sortie standard."""
        fragment = "DRY_RUN=%d\ncheck_fetch_tools\n" % dry_run
        for etape in etapes or ("extension",):
            fragment += {
                "extension": "step_extension_source\n",
                "deck": "STREAM_DECK=1\nstep_deck\n",
            }[etape]
        if not dry_run:
            fragment += 'printf "%s\\n" "${DONE[@]}"\n'
        return self.jouer(fragment, env)

    def lancer(
        self, *options, gnome="48.1", env=None, entree=subprocess.DEVNULL
    ):
        """Lance le script entier de la copie, sous Ubuntu et GNOME
        `gnome`, un faux sudo en tête du PATH ; `entree` est son entrée
        standard."""
        os_release = self.tmp / "os-release"
        os_release.write_text(OS_RELEASE["ubuntu:24.04"], encoding="utf-8")
        sudo = self.bin / "sudo"
        if not sudo.exists():
            sudo.write_text("#!/bin/sh\nexit 1\n")
            sudo.chmod(0o755)
        environ = {
            "ERPLIBRE_HOME_OS_RELEASE": str(os_release),
            "ERPLIBRE_HOME_GNOME_VERSION": gnome,
            "PATH": "%s:%s" % (self.bin, os.environ.get("PATH", "")),
        }
        environ.update(env or {})
        return subprocess.run(
            ["bash", str(self.installeur), *options],
            stdin=entree,
            capture_output=True,
            text=True,
            env=self.environ(environ),
            cwd="/",
            timeout=60,
        )

    def appels(self):
        """Les appels au faux repo, un par ligne, depuis le dernier."""
        if not self.trace.exists():
            return []
        lignes = self.trace.read_text().splitlines()
        self.trace.unlink()
        return lignes

    def assertPose(self, dossier):
        """`dossier` est un checkout de repo : .git en lien."""
        self.assertTrue((dossier / ".git").is_symlink(), dossier)

    def mis_de_cote(self, dossier):
        """Les répertoires voisins de `dossier` que l'installateur a mis de
        côté avant la pose."""
        return sorted(
            p.name
            for p in dossier.parent.iterdir()
            if p.name.startswith(dossier.name + ".avant-repo-")
        )


# Le metadata.json du dépôt nu de l'extension : la version 48 de GNOME, que
# lancer() annonce.
METADATA_MINIMAL = '{"shell-version": ["48"]}\n'


@unittest.skipUnless(shutil.which("git"), "git absent")
class TestPoseParRepo(CopieDuCheckout):
    """step_extension_source et step_deck : repo init une seule fois, sans
    -g, le projet ajouté au manifeste local sans rien en retirer, puis
    « repo sync -n » et « repo sync -l » du seul chemin. Un contenu qui
    n'est pas un checkout de repo est mis de côté, puis remis en place si
    la pose échoue."""

    def test_a_first_pose_inits_once_without_groups_then_syncs_the_path(self):
        fait = self.poser()
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual(
            [
                "init --standalone-manifest -u file://%s/%s"
                % (self.depot, MANIFESTE_INIT),
                "sync -n -c " + EXT_CHEMIN,
                "sync -l -c " + EXT_CHEMIN,
            ],
            self.appels(),
        )
        self.assertPose(self.ext)
        self.assertTrue((self.ext / "metadata.json").is_file())
        bilan = fait.stdout.splitlines()
        self.assertIn("repo init: %s/.repo" % self.depot, bilan)
        self.assertIn(
            "manifest: %s added to %s" % (EXT_CHEMIN, self.local), bilan
        )
        self.assertIn("extension synced: %s (main)" % self.ext, bilan)
        # Le bruit de repo va au journal, jamais sur la sortie d'erreur.
        self.assertEqual("", fait.stderr)
        # Une relance : ni init, ni ajout, et le manifeste garde ses octets.
        manifeste = self.local.read_bytes()
        fait = self.poser()
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual(
            [
                "list -p --all",
                "sync -n -c " + EXT_CHEMIN,
                "sync -l -c " + EXT_CHEMIN,
            ],
            self.appels(),
        )
        self.assertEqual(manifeste, self.local.read_bytes())
        self.assertEqual("\n", fait.stdout)

    def test_the_created_manifest_holds_the_remote_and_the_project(self):
        self.assertEqual(0, self.poser().returncode)
        texte = self.local.read_text()
        self.assertEqual(1, texte.count("<manifest>"))
        self.assertTrue(texte.rstrip().endswith("</manifest>"), texte)
        racine = ET.fromstring(texte)
        (remote,) = racine.findall("remote")
        self.assertEqual("TechnoLibre", remote.get("name"))
        self.assertEqual(
            "https://github.com/TechnoLibre/", remote.get("fetch")
        )
        (projet,) = racine.findall("project")
        self.assertEqual(EXT_CHEMIN, projet.get("path"))
        self.assertEqual("TechnoLibre", projet.get("remote"))
        self.assertEqual("main", projet.get("revision"))
        self.assertEqual("erplibre_home", projet.get("groups"))

    def manifeste_etranger(self, avec_remote):
        """Un .repo déjà initialisé et un manifeste local au format de la
        fusion, qui porte un projet d'addon et, au choix, le remote
        TechnoLibre. Rend ses octets."""
        (self.depot / ".repo/repo").mkdir(parents=True)
        (self.depot / ".repo/repo/main.py").write_text("")
        (self.depot / ".repo/manifest.xml").write_text("<manifest />\n")
        self.local.parent.mkdir(parents=True)
        remote = (
            '  <remote name="TechnoLibre"'
            ' fetch="https://github.com/TechnoLibre/"/>\n'
            if avec_remote
            else ""
        )
        texte = (
            '<?xml version="1.0" encoding="UTF-8"?>\n<manifest>\n'
            '  <remote name="OCA" fetch="https://github.com/OCA/"/>\n'
            + remote
            + '  <project name="web.git" path="odoo18.0/addons/OCA_web"'
            ' remote="OCA" revision="0123456789abcdef0123456789abcdef01234567"'
            ' groups="addons,odoo18.0" upstream="18.0"/>\n</manifest>\n'
        ).encode()
        self.local.write_bytes(texte)
        return texte

    def test_an_existing_manifest_keeps_its_bytes_plus_the_project(self):
        """Seul s'ajoute, avant le dernier </manifest>, le <project> du
        manifeste de l'extension, et son <remote> quand il manque : rien
        n'est retiré ni réécrit, freeze-revision des addons compris."""
        for avec_remote in (True, False):
            with self.subTest(avec_remote=avec_remote):
                avant = self.manifeste_etranger(avec_remote)
                fait = self.poser()
                self.assertEqual(0, fait.returncode, fait.stderr)
                apres = self.local.read_bytes()
                fin = avant.rindex(b"</manifest>")
                self.assertTrue(apres.startswith(avant[:fin]), apres)
                self.assertTrue(apres.endswith(avant[fin:]), apres)
                ajout = apres[fin : len(apres) - len(avant) + fin].decode()
                self.assertEqual(
                    0 if avec_remote else 1, ajout.count("<remote ")
                )
                self.assertEqual(1, ajout.count("<project"))
                self.assertIn('path="%s"' % EXT_CHEMIN, ajout)
                self.assertNotIn("init", "".join(self.appels()))
                shutil.rmtree(self.depot / ".repo")
                shutil.rmtree(self.ext)

    def test_the_base_after_stream_deck_keeps_the_deck(self):
        self.assertEqual(0, self.poser("extension", "deck").returncode)
        self.appels()
        avant = self.local.read_bytes()
        fait = self.poser("extension")
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual(avant, self.local.read_bytes())
        self.assertIn('path="%s"' % DECK_CHEMIN, self.local.read_text())
        self.assertTrue(
            (self.deck / "erplibre_streamdeck/__main__.py").is_file()
        )
        self.assertEqual(
            [
                "list -p --all",
                "sync -n -c " + EXT_CHEMIN,
                "sync -l -c " + EXT_CHEMIN,
            ],
            self.appels(),
        )

    def test_a_self_closing_local_manifest_stops_before_any_sync(self):
        (self.depot / ".repo/repo").mkdir(parents=True)
        (self.depot / ".repo/repo/main.py").write_text("")
        (self.depot / ".repo/manifest.xml").write_text("<manifest />\n")
        self.local.parent.mkdir(parents=True)
        self.local.write_text("<manifest/>\n")
        fait = self.poser()
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertEqual(1, len(fait.stderr.splitlines()), fait.stderr)
        self.assertIn("make", fait.stderr)
        self.assertEqual("<manifest/>\n", self.local.read_text())
        self.assertEqual([], self.appels())

    def test_a_synced_checkout_follows_main(self):
        self.assertEqual(0, self.poser().returncode)
        self.appels()
        voulu = pousser(self.amont, "erplibre_home", "extension.js")
        fait = self.poser()
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual(voulu, _git(self.ext, "rev-parse", "HEAD"))
        self.assertEqual(
            "extension updated: %s (main)\n" % self.ext, fait.stdout
        )

    def test_a_failed_fetch_on_a_checkout_exits_zero_not_updated(self):
        self.assertEqual(0, self.poser().returncode)
        self.appels()
        avant = _git(self.ext, "rev-parse", "HEAD")
        pousser(self.amont, "erplibre_home", "extension.js")
        fait = self.poser(env={"FAUX_REPO_ECHEC": "fetch"})
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual("", fait.stderr)
        self.assertRegex(
            fait.stdout, r"^extension NOT updated: fetch failed; log: \S+\n$"
        )
        self.assertEqual(
            ["list -p --all", "sync -n -c " + EXT_CHEMIN], self.appels()
        )
        self.assertEqual(avant, _git(self.ext, "rev-parse", "HEAD"))

    def test_a_refused_local_sync_on_a_checkout_exits_zero(self):
        self.assertEqual(0, self.poser().returncode)
        fait = self.poser(env={"FAUX_REPO_ECHEC": "local"})
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertRegex(
            fait.stdout,
            r"^extension NOT updated: repo sync -l failed; log: \S+\n$",
        )

    def test_the_old_repo_layout_is_a_checkout(self):
        """Un .git répertoire dont objects/ est un lien : l'ancienne
        disposition de repo, synchronisée comme l'autre, jamais mise de
        côté."""
        self.assertEqual(0, self.poser().returncode)
        self.appels()
        projet = Path(os.readlink(self.ext / ".git"))
        (self.ext / ".git").unlink()
        shutil.copytree(
            projet, self.ext / ".git", ignore=shutil.ignore_patterns("objects")
        )
        (self.ext / ".git/objects").symlink_to(projet / "objects")
        fait = self.poser()
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual([], self.mis_de_cote(self.ext))
        self.assertEqual(
            [
                "list -p --all",
                "sync -n -c " + EXT_CHEMIN,
                "sync -l -c " + EXT_CHEMIN,
            ],
            self.appels(),
        )

    def contenus_etrangers(self):
        """(nom, fonction qui pose ce contenu à la place de l'extension) :
        tout ce qui n'est pas un checkout de repo."""

        def clone_git(dossier):
            subprocess.run(
                [
                    "git",
                    "clone",
                    "-q",
                    str(self.amont / "erplibre_home.git"),
                    str(dossier),
                ],
                check=True,
            )
            (dossier / "local.js").write_text("travail")

        def copie(dossier):
            dossier.mkdir(parents=True)
            (dossier / "metadata.json").write_text("{}")

        def restes(dossier):
            for reste in (
                "locale/fr/LC_MESSAGES/erplibre-home.mo",
                "schemas/gschemas.compiled",
            ):
                (dossier / reste).parent.mkdir(parents=True, exist_ok=True)
                (dossier / reste).write_text("")

        def fichier(dossier):
            dossier.parent.mkdir(parents=True, exist_ok=True)
            dossier.write_text("x")

        return (
            ("clone git", clone_git),
            ("copie sans .git", copie),
            ("restes ignorés", restes),
            ("fichier", fichier),
        )

    @staticmethod
    def arbre(dossier):
        """{chemin relatif: octets} des fichiers sous `dossier`, ou ses
        octets quand c'est un fichier."""
        if dossier.is_file():
            return dossier.read_bytes()
        return {
            str(p.relative_to(dossier)): p.read_bytes()
            for p in sorted(dossier.rglob("*"))
            if p.is_file() and not p.is_symlink()
        }

    def test_foreign_content_is_set_aside_whole_then_posed(self):
        for nom, poser_contenu in self.contenus_etrangers():
            with self.subTest(contenu=nom):
                poser_contenu(self.ext)
                avant = self.arbre(self.ext)
                fait = self.poser()
                self.assertEqual(0, fait.returncode, fait.stderr)
                self.assertPose(self.ext)
                self.assertTrue((self.ext / "metadata.json").is_file())
                (sauvegarde,) = self.mis_de_cote(self.ext)
                sauvegarde = self.ext.parent / sauvegarde
                self.assertEqual(avant, self.arbre(sauvegarde))
                self.assertIn(
                    "extension set aside: %s moved to %s"
                    % (self.ext, sauvegarde),
                    fait.stdout.splitlines(),
                )
                shutil.rmtree(self.ext)
                if sauvegarde.is_dir():
                    shutil.rmtree(sauvegarde)
                else:
                    sauvegarde.unlink()
                shutil.rmtree(self.depot / ".repo")

    def test_an_empty_directory_is_posed_without_a_set_aside(self):
        self.ext.mkdir(parents=True)
        fait = self.poser()
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertPose(self.ext)
        self.assertEqual([], self.mis_de_cote(self.ext))

    def test_a_failed_pose_puts_the_set_aside_content_back(self):
        """La pose qui échoue, au fetch ou à l'extraction, remet le contenu
        mis de côté à sa place : le répertoire, que GNOME charge, n'est
        jamais laissé absent ni vide. Une ligne sur la sortie d'erreur, qui
        nomme le journal de repo."""
        for echec in ("fetch", "local", "init"):
            for nom, poser_contenu in self.contenus_etrangers():
                with self.subTest(echec=echec, contenu=nom):
                    poser_contenu(self.ext)
                    avant = self.arbre(self.ext)
                    fait = self.poser(env={"FAUX_REPO_ECHEC": echec})
                    self.assertEqual(1, fait.returncode, fait.stdout)
                    erreurs = fait.stderr.splitlines()
                    self.assertEqual(1, len(erreurs), fait.stderr)
                    self.assertIn("erplibre_home_repo.", erreurs[0])
                    self.assertEqual(avant, self.arbre(self.ext))
                    self.assertFalse((self.ext / ".git").is_symlink())
                    self.assertEqual([], self.mis_de_cote(self.ext))
                    if self.ext.is_dir():
                        shutil.rmtree(self.ext)
                    else:
                        self.ext.unlink()
                    shutil.rmtree(self.depot / ".repo", ignore_errors=True)
                    self.appels()

    def test_a_failed_first_pose_without_content_exits_one(self):
        fait = self.poser(env={"FAUX_REPO_ECHEC": "fetch"})
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertEqual(1, len(fait.stderr.splitlines()), fait.stderr)
        self.assertFalse((self.ext / ".git").exists())

    def test_a_failed_pose_over_a_left_set_aside_puts_it_back(self):
        """Un arrêt qui échappe au piège de sortie (SIGKILL, coupure) laisse
        le contenu mis de côté et le répertoire absent. La pose suivante
        qui échoue y remet la sauvegarde la plus récente, qu'elle nomme ;
        celle qui réussit la laisse où elle est."""
        ancienne = self.ext.parent / (self.ext.name + ".avant-repo-20190101")
        recente = self.ext.parent / (self.ext.name + ".avant-repo-20200101")
        for sauvegarde in (ancienne, recente):
            sauvegarde.mkdir(parents=True)
            (sauvegarde / "notes.txt").write_text(sauvegarde.name)
        fait = self.poser(env={"FAUX_REPO_ECHEC": "fetch"})
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertEqual(1, len(fait.stderr.splitlines()), fait.stderr)
        self.assertIn("remis en place depuis %s" % recente, fait.stderr)
        self.assertEqual(
            {"notes.txt": recente.name.encode()}, self.arbre(self.ext)
        )
        self.assertEqual([ancienne.name], self.mis_de_cote(self.ext))
        # Remis en place, ce contenu est mis de côté à la pose suivante.
        fait = self.poser()
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertPose(self.ext)
        self.assertEqual(2, len(self.mis_de_cote(self.ext)))
        # Le répertoire absent et une sauvegarde là : la pose réussie la
        # laisse. Sans .repo, le faux repo repose le répertoire entier.
        shutil.rmtree(self.ext)
        shutil.rmtree(self.depot / ".repo")
        fait = self.poser()
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertPose(self.ext)
        self.assertEqual(2, len(self.mis_de_cote(self.ext)))

    def test_a_failed_init_leaves_no_repo_directory(self):
        fait = self.poser(env={"FAUX_REPO_ECHEC": "init"})
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertFalse((self.depot / ".repo").exists())
        self.assertEqual(
            [
                "init --standalone-manifest -u file://%s/%s"
                % (self.depot, MANIFESTE_INIT)
            ],
            self.appels(),
        )

    def test_a_sync_without_the_witness_fails_and_restores(self):
        """Le témoin, metadata.json pour l'extension, se vérifie après le
        sync : un dépôt qui ne le porte pas arrête l'installation, et le
        contenu mis de côté revient."""
        shutil.rmtree(self.amont / "erplibre_home.git")
        shutil.rmtree(self.amont / "travail/erplibre_home")
        depot_nu(self.amont, "erplibre_home", {"README": ""})
        self.ext.mkdir(parents=True)
        (self.ext / "notes.txt").write_text("x")
        fait = self.poser()
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertIn("metadata.json", fait.stderr)
        self.assertEqual({"notes.txt": b"x"}, self.arbre(self.ext))
        self.assertEqual([], self.mis_de_cote(self.ext))
        # Sans contenu d'avant, ce que repo a posé part.
        shutil.rmtree(self.ext)
        fait = self.poser()
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertFalse(os.path.lexists(self.ext))
        self.assertTrue((self.depot / ".repo/manifest.xml").is_file())

    @unittest.skipUnless(shutil.which("flock"), "flock absent")
    def test_a_second_run_waits_for_the_first_pose(self):
        """Deux installations sur le même checkout : la seconde attend la
        fin de la première. Sinon elle lirait « absent » le répertoire que
        la première a mis de côté, et son propre échec supprimerait la pose
        de la première. Ici, le fetch de la seconde échoue après celui de
        la première : sur le checkout posé, cet échec ne retire rien."""
        self.ext.mkdir(parents=True)
        (self.ext / "notes.txt").write_text("x")
        lent = self.bin / "repo_lent"
        lent.write_text(
            "#!/bin/bash\n"
            'if [ "$1 $2" = "sync -n" ]; then sleep 1; fi\n'
            'exec "%s" "$@"\n' % self.faux_repo
        )
        lent.chmod(0o755)
        en_echec = self.bin / "repo_en_echec"
        en_echec.write_text(
            "#!/bin/bash\n"
            'if [ "$1 $2" = "sync -n" ]; then sleep 3; exit 1; fi\n'
            'exec "%s" "$@"\n' % self.faux_repo
        )
        en_echec.chmod(0o755)

        def lancer(repo):
            return subprocess.Popen(
                [
                    "bash",
                    "-c",
                    'ERPLIBRE_HOME_SOURCE_ONLY=1 source "$INSTALLEUR"\n'
                    "trap repo_restore EXIT\n"
                    "check_fetch_tools\n"
                    "step_extension_source\n"
                    'printf "%s\\n" "${DONE[@]}"\n',
                ],
                env=self.environ({"ERPLIBRE_HOME_REPO": str(repo)}),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd="/",
            )

        premiere = lancer(lent)
        for _ in range(100):
            if self.mis_de_cote(self.ext):
                break
            time.sleep(0.05)
        seconde = lancer(en_echec)
        sorties = [p.communicate(timeout=60) for p in (premiere, seconde)]
        self.assertEqual(0, premiere.returncode, sorties[0])
        self.assertEqual(0, seconde.returncode, sorties[1])
        self.assertIn("attente de sa fin", sorties[1][0])
        self.assertIn("extension NOT updated: fetch failed", sorties[1][0])
        self.assertPose(self.ext)
        self.assertTrue((self.ext / "metadata.json").is_file())

    def test_the_deck_is_posed_like_the_extension(self):
        fait = self.poser("extension", "deck")
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertPose(self.deck)
        self.assertTrue(
            (self.deck / "erplibre_streamdeck/__main__.py").is_file()
        )
        self.assertIn(
            "deck synced: %s (main)" % self.deck, fait.stdout.splitlines()
        )
        appels = self.appels()
        self.assertEqual(1, sum(a.startswith("init ") for a in appels))
        self.assertEqual(
            ["sync -n -c " + DECK_CHEMIN, "sync -l -c " + DECK_CHEMIN],
            appels[-2:],
        )
        racine = ET.fromstring(self.local.read_text())
        self.assertEqual(1, len(racine.findall("remote")))
        self.assertEqual(
            [EXT_CHEMIN, DECK_CHEMIN],
            [p.get("path") for p in racine.findall("project")],
        )

    def test_the_shrink_guard_stops_before_a_sync_that_would_delete(self):
        """Tout repo sync, même d'un seul chemin, supprime les chemins de
        project.list que le manifeste ne nomme plus : l'installateur refuse
        tant qu'un tel chemin existe, et ne lance aucun sync."""
        self.assertEqual(0, self.poser().returncode)
        orphelin = self.depot / "odoo18.0/addons/OCA_web"
        (orphelin / ".git").mkdir(parents=True)
        liste = self.depot / ".repo/project.list"
        liste.write_text(liste.read_text() + "odoo18.0/addons/OCA_web\n")
        self.appels()
        fait = self.poser()
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertEqual(1, len(fait.stderr.splitlines()), fait.stderr)
        self.assertIn("odoo18.0/addons/OCA_web", fait.stderr)
        self.assertIn("make", fait.stderr)
        self.assertEqual(["list -p --all"], self.appels())
        self.assertTrue((orphelin / ".git").is_dir())
        # Absent du disque, il ne serait pas supprimé : rien n'est refusé.
        shutil.rmtree(orphelin)
        self.assertEqual(0, self.poser().returncode)

    def test_a_nested_checkout_is_refused_before_repo(self):
        """Le lanceur de repo remonte jusqu'au .repo d'un parent : un
        checkout imbriqué dans un autre, sans .repo à lui, initialiserait
        celui du parent."""
        parent = self.tmp
        (parent / ".repo/repo").mkdir(parents=True)
        (parent / ".repo/repo/main.py").write_text("")
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                fait = self.poser(dry_run=dry_run)
                self.assertEqual(1, fait.returncode, fait.stdout)
                self.assertEqual(1, len(fait.stderr.splitlines()))
                self.assertIn(str(parent), fait.stderr)
                self.assertEqual([], self.appels())
        # Avec son propre .repo, le checkout n'est plus imbriqué.
        (self.depot / ".repo/repo").mkdir(parents=True)
        (self.depot / ".repo/repo/main.py").write_text("")
        self.assertEqual(0, self.poser().returncode)

    def test_without_venv_erplibre_it_names_install_erplibre(self):
        fait = self.poser(env={"ERPLIBRE_HOME_REPO": None})
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertEqual(1, len(fait.stderr.splitlines()), fait.stderr)
        self.assertIn("./script/install/install_erplibre.sh", fait.stderr)
        self.assertFalse((self.depot / ".repo").exists())

    def test_a_venv_without_repo_gets_it_from_install_git_repo(self):
        """.venv.erplibre sans bin/repo : install_git_repo.sh le pose, puis
        l'installateur le lance depuis la racine. --dry-run l'annonce sans
        le lancer."""
        (self.depot / ".venv.erplibre/bin").mkdir(parents=True)
        trace = self.tmp / "install_git_repo.trace"
        script = self.depot / "script/install/install_git_repo.sh"
        script.write_text(
            "#!/bin/bash\n"
            'echo "$PWD" >>"%s"\n'
            'cp "%s" .venv.erplibre/bin/repo\n' % (trace, self.faux_repo)
        )
        script.chmod(0o755)
        env = {"ERPLIBRE_HOME_REPO": None}
        fait = self.poser(env=env, dry_run=True)
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertIn(
            "repo: ./script/install/install_git_repo.sh",
            fait.stdout.splitlines(),
        )
        self.assertFalse(trace.exists())
        fait = self.poser(env=env)
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual("%s\n" % self.depot, trace.read_text())
        self.assertPose(self.ext)
        self.assertIn("sync -l -c " + EXT_CHEMIN, self.appels())

    def test_without_git_it_exits_one_naming_the_package(self):
        fait = self.jouer("PATH=/nonexistent\ncheck_fetch_tools\n")
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertEqual(1, len(fait.stderr.splitlines()), fait.stderr)
        self.assertIn("git", fait.stderr)
        self.assertEqual([], self.appels())

    def test_the_dry_run_names_each_effect_and_calls_no_repo(self):
        fait = self.poser("extension", "deck", dry_run=True)
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual(
            [
                "init: repo --standalone-manifest",
                "manifest: add " + EXT_CHEMIN,
                "extension: repo sync %s (https://github.com/TechnoLibre/"
                "erplibre-home-gnome-extension.git at main)" % self.ext,
                "manifest: add " + DECK_CHEMIN,
                "deck: repo sync %s (https://github.com/TechnoLibre/"
                "erplibre_streamdeck.git at main)" % self.deck,
            ],
            fait.stdout.splitlines(),
        )
        self.assertEqual([], self.appels())
        self.assertFalse((self.depot / ".repo").exists())
        self.assertFalse(self.ext.exists())

    def test_the_dry_run_names_the_set_aside_and_moves_nothing(self):
        self.ext.mkdir(parents=True)
        (self.ext / "notes.txt").write_text("x")
        fait = self.poser(dry_run=True)
        self.assertEqual(0, fait.returncode, fait.stderr)
        lignes = fait.stdout.splitlines()
        (ligne,) = [l for l in lignes if "set aside" in l]
        self.assertRegex(
            ligne,
            r"^extension: set aside %s to %s\.avant-repo-\d{8}-\d{6}$"
            % (self.ext, self.ext),
        )
        self.assertLess(
            lignes.index(ligne),
            lignes.index(
                "extension: repo sync %s (https://github.com/TechnoLibre/"
                "erplibre-home-gnome-extension.git at main)" % self.ext
            ),
        )
        self.assertEqual({"notes.txt": b"x"}, self.arbre(self.ext))

    def test_a_checkout_has_no_init_or_manifest_line(self):
        self.assertEqual(0, self.poser().returncode)
        self.appels()
        fait = self.poser(dry_run=True)
        self.assertEqual(
            [
                "extension: repo sync %s (https://github.com/TechnoLibre/"
                "erplibre-home-gnome-extension.git at main)" % self.ext
            ],
            fait.stdout.splitlines(),
        )
        self.assertEqual([], self.appels())

    def test_the_dry_run_line_reads_the_project_of_its_manifest(self):
        """Les attributs du projet se lisent sur plusieurs lignes, et l'URL
        est le fetch de son remote suivi de son name."""
        (self.depot / MANIFESTE_EXT).write_text(
            '<?xml version="1.0" encoding="UTF-8" ?>\n<manifest>\n'
            '  <remote name="local"\n          fetch="file:///amont/" />\n'
            "  <project\n"
            '      name="ext.git"\n'
            '      path="%s"\n'
            '      remote="local"\n'
            '      revision="refs/tags/v1.0.0"\n'
            "  />\n</manifest>\n" % EXT_CHEMIN
        )
        fait = self.poser(dry_run=True)
        self.assertIn(
            "extension: repo sync %s (file:///amont/ext.git at"
            " refs/tags/v1.0.0)" % self.ext,
            fait.stdout.splitlines(),
        )

    def test_uninstall_leaves_repo_and_the_manifest(self):
        """La désinstallation ne touche ni à .repo, ni au manifeste local,
        ni au checkout : sans le projet au manifeste, le sync suivant
        supprimerait le répertoire."""
        self.assertEqual(0, self.poser("extension", "deck").returncode)
        self.appels()
        manifeste = self.local.read_bytes()
        liste = (self.depot / ".repo/project.list").read_bytes()
        lien = self.tmp / "extensions" / UUID
        lien.parent.mkdir()
        lien.symlink_to(self.ext)
        fait = self.jouer(
            'EXT_LINK="$LIEN"\n'
            'UDEV_RULE="$DOSSIER/absente.rules"\n'
            'VENV="$DOSSIER/venv"\n'
            "uninstall_service() { :; }\n"
            'gsettings_bus() { echo "@as []"; }\n'
            "uninstall\n",
            {"LIEN": str(lien), "DOSSIER": str(self.tmp)},
        )
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertFalse(os.path.lexists(lien))
        self.assertEqual(manifeste, self.local.read_bytes())
        self.assertEqual(
            liste, (self.depot / ".repo/project.list").read_bytes()
        )
        self.assertPose(self.ext)
        self.assertPose(self.deck)
        self.assertEqual([], self.appels())

    def test_the_extension_comes_before_the_shell_version_it_carries(self):
        """main vérifie les outils de la récupération, puis amène
        l'extension après la version de GNOME, qui ne lit rien d'elle, et
        avant shell-version, qui lit son metadata.json ; la désinstallation
        n'appelle jamais repo."""
        texte = INSTALLEUR.read_text(encoding="utf-8")
        corps = texte[texte.index("\nmain() {") :]
        ordre = [
            "read_gnome_version",
            "check_fetch_tools",
            "step_extension_source",
            "step_shell_version",
        ]
        self.assertEqual(ordre, sorted(ordre, key=corps.index))
        self.assertLess(
            corps.index("step_uninstall"), corps.index("check_fetch_tools")
        )

    def test_the_deck_comes_before_the_venv_at_the_stream_deck_level(self):
        texte = INSTALLEUR.read_text(encoding="utf-8")
        corps = texte[texte.index("\nmain() {") :]
        self.assertLess(corps.index("step_udev"), corps.index("step_deck"))
        self.assertLess(corps.index("step_deck"), corps.index("step_venv"))

    def test_uninstall_without_the_extension_removes_the_link(self):
        """Sans l'extension, la liste enabled-extensions ne se lit pas par
        gsettings_strv.py : le lien part quand même, et le bilan dit que
        l'UUID peut y rester."""
        lien = self.tmp / "extensions" / UUID
        lien.parent.mkdir()
        lien.symlink_to(self.ext)
        fait = self.jouer(
            'EXT_LINK="$LIEN"\n'
            'UDEV_RULE="$DOSSIER/absente.rules"\n'
            'VENV="$DOSSIER/venv"\n'
            "uninstall_service() { :; }\n"
            'gsettings_bus() { echo "gsettings $*"; }\n'
            'uninstall\nprintf "%s\\n" "${DONE[@]}"\n',
            {"LIEN": str(lien), "DOSSIER": str(self.tmp)},
        )
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertNotIn("gsettings get", fait.stdout)
        self.assertFalse(os.path.lexists(lien))
        self.assertIn(
            "enabled-extensions NOT edited: no %s/tools/gsettings_strv.py;"
            " %s may still be listed" % (self.ext, UUID),
            fait.stdout,
        )


@unittest.skipUnless(shutil.which("git"), "git absent")
class TestLeScriptEntier(CopieDuCheckout):
    """Le script entier de la copie, sans l'extension : --dry-run annonce
    la pose sans rien poser, et ne prétend pas vérifier shell-version ;
    --uninstall n'appelle pas repo ; une installation pose l'extension par
    le faux repo avant de lire shell-version."""

    def test_the_dry_run_announces_the_pose_first(self):
        for options in (("--dry-run",), ("--dry-run", "--extension-only")):
            with self.subTest(options=options):
                fait = self.lancer(*options)
                self.assertEqual(0, fait.returncode, fait.stderr)
                self.assertEqual(
                    [
                        "init: repo --standalone-manifest",
                        "manifest: add " + EXT_CHEMIN,
                        "extension: repo sync %s (https://github.com/"
                        "TechnoLibre/erplibre-home-gnome-extension.git at"
                        " main)" % self.ext,
                    ],
                    fait.stdout.splitlines()[:3],
                )
                self.assertFalse(self.ext.exists())
                self.assertEqual([], self.appels())
        fait = self.lancer("--dry-run")
        self.assertIn(
            "check: shell-version of %s/metadata.json after the sync"
            % self.ext,
            fait.stdout.splitlines(),
        )
        self.assertIn("gnome=48.1", fait.stdout.splitlines())

    def test_uninstall_calls_no_repo(self):
        """Ni pose, ni lecture d'enabled-extensions sans le lecteur des
        outils de l'extension : la ligne le dit, le lien part quand même."""
        fait = self.lancer("--dry-run", "--uninstall")
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertNotIn("extension: ", fait.stdout)
        self.assertNotIn("init: ", fait.stdout)
        self.assertFalse(self.ext.exists())
        lignes = fait.stdout.splitlines()
        self.assertIn(
            "skip: enabled-extensions -%s, no %s/tools/gsettings_strv.py"
            % (UUID, self.ext),
            lignes,
        )
        self.assertNotIn("gsettings: ", fait.stdout)
        self.assertIn(
            "remove: %s/.local/share/gnome-shell/extensions/%s"
            % (self.home, UUID),
            lignes,
        )
        self.assertEqual([], self.appels())

    def test_no_gnome_shell_is_refused_before_any_repo_call(self):
        fait = self.lancer("--dry-run", gnome="none")
        self.assertEqual(2, fait.returncode, fait.stdout + fait.stderr)
        fait = self.lancer(gnome="none")
        self.assertEqual(2, fait.returncode, fait.stdout + fait.stderr)
        self.assertEqual([], self.appels())
        self.assertFalse((self.depot / ".repo").exists())

    def test_the_shell_version_refusal_is_the_only_error_line(self):
        """La pose précède shell-version : son bruit va au journal, et la
        ligne UNSUPPORTED reste seule sur la sortie d'erreur."""
        fait = self.lancer(gnome="99.0")
        self.assertEqual(2, fait.returncode, fait.stdout + fait.stderr)
        self.assertEqual(
            ["UNSUPPORTED: GNOME 99.0 not in shell-version (48)"],
            fait.stderr.splitlines(),
        )
        self.assertPose(self.ext)

    def test_a_package_manager_failure_exits_one(self):
        """Le code d'un gestionnaire de paquets (100 pour apt-get) ne
        devient pas celui du script : tout échec autre qu'UNSUPPORTED sort
        en 1. Le faux sudo ne lance que le faux apt-get."""
        sudo = self.bin / "sudo"
        sudo.write_text(
            '#!/bin/sh\ncase "$1" in apt-get) exec "$@" ;; esac\nexit 1\n'
        )
        sudo.chmod(0o755)
        apt = self.bin / "apt-get"
        apt.write_text("#!/bin/sh\nexit 100\n")
        apt.chmod(0o755)
        fait = self.lancer()
        self.assertEqual(1, fait.returncode, fait.stdout + fait.stderr)
        self.assertNotIn("UNSUPPORTED", fait.stderr)
        self.assertPose(self.ext)

    def trace_sudo(self):
        """Le journal du faux sudo qui note et réussit."""
        return self.tmp / "sudo.trace"

    def test_the_answer_on_a_terminal_decides_the_extras(self):
        """Le script entier sur un terminal, sans aucun extra présent :
        la question porte la commande d'apt-get de chaque extra, « o » les
        fait passer par sudo, « n » non. Le faux sudo note et réussit."""
        sudo = self.bin / "sudo"
        sudo.write_text('#!/bin/sh\necho "$*" >>"%s"\n' % self.trace_sudo())
        sudo.chmod(0o755)
        chemin, modules = sans_les_extras(self.tmp / "sans_extras")
        env = {
            "PATH": "%s:%s" % (self.bin, chemin),
            "PYTHONPATH": modules,
            "LC_ALL": "C",
        }
        extras = ["mpv", "yt-dlp", "nmap", "keepassxc", "xdotool"]
        extras.append("python3-lz4")
        for frappe, installes in ((b"o\n", extras), (b"n\n", [])):
            with self.subTest(frappe=frappe):
                with terminal(frappe) as entree:
                    fait = self.lancer(env=env, entree=entree)
                self.assertIn(
                    "Install the optional tools? (y/N): ", fait.stdout
                )
                for extra in extras:
                    self.assertIn("    " + APT + extra + "\n", fait.stdout)
                appels = self.trace_sudo().read_text().splitlines()
                self.trace_sudo().unlink()
                self.assertEqual(
                    [
                        "env DEBIAN_FRONTEND=noninteractive apt-get -o"
                        " DPkg::Lock::Timeout=600 install -y"
                        " --no-install-recommends " + extra
                        for extra in installes
                    ],
                    [a for a in appels if a.split()[-1] in extras],
                )

    def test_an_interrupted_pose_puts_the_content_back(self):
        """Un arrêt du script entre la mise de côté et la fin de la pose
        (ici un repo qui tue son parent) remet le contenu en place par le
        piège de sortie."""
        self.ext.mkdir(parents=True)
        (self.ext / "notes.txt").write_text("x")
        tueur = self.bin / "repo_tueur"
        tueur.write_text(
            "#!/bin/bash\n"
            'if [ "$1" = sync ]; then kill -TERM "$PPID"; sleep 5; fi\n'
            'exec "%s" "$@"\n' % self.faux_repo
        )
        tueur.chmod(0o755)
        fait = self.lancer(env={"ERPLIBRE_HOME_REPO": str(tueur)})
        self.assertNotEqual(0, fait.returncode)
        self.assertEqual(["notes.txt"], os.listdir(self.ext))
        self.assertEqual([], self.mis_de_cote(self.ext))

    @unittest.skipIf(os.geteuid() == 0, "root écrit dans un répertoire 0555")
    def test_a_failed_set_aside_leaves_the_content_untouched(self):
        """Un renommage refusé (parent en lecture seule, point de montage)
        arrête l'installation avant toute pose : le piège de sortie ne
        supprime pas le contenu qu'il n'a pas pu déplacer."""
        self.ext.mkdir(parents=True)
        (self.ext / "metadata.json").write_text("{}")
        (self.ext / "travail.js").write_text("x")
        self.ext.parent.chmod(0o555)
        try:
            fait = self.lancer("--extension-only")
        finally:
            self.ext.parent.chmod(0o755)
        self.assertEqual(1, fait.returncode, fait.stdout)
        self.assertIn("mise de côté impossible", fait.stderr)
        self.assertEqual(
            ["metadata.json", "travail.js"], sorted(os.listdir(self.ext))
        )
        self.assertEqual([], self.mis_de_cote(self.ext))


def chercher_git_repo():
    """La source de git-repo que le vrai lanceur clone à l'init : celle que
    nomme ERPLIBRE_HOME_TEST_GIT_REPO, sinon le .repo/repo du checkout ;
    None quand aucune n'a de main.py."""
    for source in (
        os.environ.get("ERPLIBRE_HOME_TEST_GIT_REPO"),
        str(RACINE / ".repo/repo"),
    ):
        if source and Path(source, "main.py").is_file():
            return Path(source)
    return None


GIT_REPO = chercher_git_repo()
VRAI_REPO = RACINE / ".venv.erplibre/bin/repo"


@unittest.skipUnless(
    GIT_REPO and os.access(VRAI_REPO, os.X_OK) and shutil.which("git"),
    "git-repo absent : .venv.erplibre/bin/repo et .repo/repo (ou"
    " ERPLIBRE_HOME_TEST_GIT_REPO)",
)
class TestAvecVraiRepo(CopieDuCheckout):
    """Le vrai repo de .venv.erplibre, sur des dépôts nus file:// : le
    lanceur clone git-repo depuis GIT_REPO (REPO_URL), jamais depuis le
    réseau. Un seul scénario enchaîné, chaque étape sur l'état de la
    précédente. Le nom de la copie porte une espace."""

    NOM_DE_LA_COPIE = "vrai depot"

    def setUp(self):
        super().setUp()
        (self.depot / ".venv.erplibre").symlink_to(RACINE / ".venv.erplibre")
        for nom, manifeste in (
            ("erplibre_home", MANIFESTE_EXT),
            ("deck", MANIFESTE_DECK),
        ):
            texte = (self.depot / manifeste).read_text()
            texte = texte.replace(
                "https://github.com/TechnoLibre/", "file://%s/" % self.amont
            )
            for vrai in (
                "erplibre-home-gnome-extension.git",
                "erplibre_streamdeck.git",
            ):
                if vrai in texte:
                    texte = texte.replace(vrai, nom + ".git")
            (self.depot / manifeste).write_text(texte)
        depot_nu(self.amont, "addon", {"__init__.py": ""})
        branche = _git(GIT_REPO, "symbolic-ref", "--short", "HEAD")
        self.env = {
            "ERPLIBRE_HOME_REPO": None,
            "REPO_URL": "file://%s" % GIT_REPO,
            "REPO_REV": branche,
        }

    def repo(self, *args):
        return subprocess.run(
            ["./.venv.erplibre/bin/repo", *args],
            cwd=str(self.depot),
            env=self.environ(self.env),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def liste(self):
        return sorted(self.repo("list", "-p").stdout.split())

    def test_pose_addon_kept_base_after_deck_follow_and_offline(self):
        # Pose fraîche : init, manifeste créé, extension posée par repo.
        fait = self.poser(env=self.env)
        self.assertEqual(0, fait.returncode, fait.stdout + fait.stderr)
        self.assertEqual("", fait.stderr)
        self.assertPose(self.ext)
        self.assertEqual(
            ["TechnoLibre"], _git(self.ext, "remote").splitlines()
        )
        self.assertEqual([EXT_CHEMIN], self.liste())
        # Un projet d'addon, comme la fusion en écrit, synchronisé à part.
        texte = self.local.read_text().replace(
            "</manifest>",
            '  <project name="addon.git" path="odoo18.0/addons/addon"'
            ' remote="TechnoLibre" revision="main"/>\n</manifest>',
        )
        self.local.write_text(texte)
        self.assertEqual(
            0, self.repo("sync", "odoo18.0/addons/addon").returncode
        )
        # Le deck : ajouté au manifeste, l'addon et l'extension restent.
        fait = self.poser("deck", env=self.env)
        self.assertEqual(0, fait.returncode, fait.stdout + fait.stderr)
        attendus = sorted([EXT_CHEMIN, DECK_CHEMIN, "odoo18.0/addons/addon"])
        self.assertEqual(attendus, self.liste())
        self.assertIn('path="odoo18.0/addons/addon"', self.local.read_text())
        # La base relancée après le deck garde le deck.
        fait = self.poser(env=self.env)
        self.assertEqual(0, fait.returncode, fait.stdout + fait.stderr)
        self.assertEqual(attendus, self.liste())
        self.assertTrue(
            (self.deck / "erplibre_streamdeck/__main__.py").is_file()
        )
        self.assertTrue((self.depot / "odoo18.0/addons/addon/.git").exists())
        # main avance en amont : la relance l'amène.
        voulu = pousser(self.amont, "erplibre_home", "extension.js")
        fait = self.poser(env=self.env)
        self.assertEqual(0, fait.returncode, fait.stdout + fait.stderr)
        self.assertEqual(voulu, _git(self.ext, "rev-parse", "HEAD"))
        self.assertIn("extension updated: %s (main)" % self.ext, fait.stdout)
        # Amont injoignable : exit 0, le bilan le dit, rien ne bouge.
        (self.amont / "erplibre_home.git").rename(self.amont / "ailleurs.git")
        fait = self.poser(env=self.env)
        self.assertEqual(0, fait.returncode, fait.stdout + fait.stderr)
        self.assertIn("extension NOT updated: fetch failed", fait.stdout)
        self.assertEqual(voulu, _git(self.ext, "rev-parse", "HEAD"))
        (self.amont / "ailleurs.git").rename(self.amont / "erplibre_home.git")
        # Un clone git à la place du deck : mis de côté, puis posé.
        shutil.rmtree(self.deck)
        subprocess.run(
            [
                "git",
                "clone",
                "-q",
                str(self.amont / "deck.git"),
                str(self.deck),
            ],
            check=True,
        )
        fait = self.poser("deck", env=self.env)
        self.assertEqual(0, fait.returncode, fait.stdout + fait.stderr)
        self.assertPose(self.deck)
        self.assertEqual(1, len(self.mis_de_cote(self.deck)))
        self.assertEqual(attendus, self.liste())


class TestVenv(unittest.TestCase):
    """make_venv sous un faux python3 en tête du PATH : celui que le
    système fournit, et non un python de pyenv."""

    # « -m venv <dossier> » y pose un bin/python qui note ses appels de pip.
    PYTHON3 = (
        '#!/bin/sh\necho "python3 $*" >>"$DOSSIER/appels"\n'
        'if [ "$1 $2" = "-m venv" ]; then\n'
        '    mkdir -p "$3/bin"\n'
        '    printf \'#!/bin/sh\\necho "venv $*" >>"$DOSSIER/appels"\\n\''
        ' >"$3/bin/python"\n'
        '    chmod 755 "$3/bin/python"\n'
        "fi\n"
    )

    def test_an_absent_venv_is_created_by_the_system_python3(self):
        with tempfile.TemporaryDirectory() as dossier:
            faux = Path(dossier, "bin")
            faux.mkdir()
            for nom, corps in (
                ("python3", self.PYTHON3),
                ("pyenv", '#!/bin/sh\necho "pyenv $*" >>"$DOSSIER/appels"\n'),
            ):
                (faux / nom).write_text(corps)
                (faux / nom).chmod(0o755)
            fragment = (
                'PATH="$FAUX:$PATH"\nVENV="$DOSSIER/venv"\n'
                'make_venv\nprintf "%s\\n" "${DONE[@]}"\n'
            )
            env = {"DOSSIER": dossier, "FAUX": str(faux)}
            fait = sourcer(fragment, env)
            premier = Path(dossier, "appels").read_text().splitlines()
            Path(dossier, "appels").unlink()
            reprise = sourcer(fragment, env)
            second = Path(dossier, "appels").read_text().splitlines()
        venv = "%s/venv" % dossier
        deck = "%s/requirements.txt" % DECK_CLONE
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual("python3 -m venv %s" % venv, premier[0])
        self.assertEqual(2, len(premier), premier)
        self.assertTrue(premier[1].startswith("venv -m pip install"))
        self.assertTrue(premier[1].endswith("-r %s" % deck), premier)
        self.assertIn("venv created: %s" % venv, fait.stdout)
        # Un venv déjà là n'est pas recréé : seul pip repasse.
        self.assertEqual(0, reprise.returncode, reprise.stderr)
        self.assertEqual(1, len(second), second)
        self.assertTrue(second[0].startswith("venv -m pip install"))
        self.assertNotIn("venv created", reprise.stdout)


@SANS_EXTENSION
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
        self,
        enabled,
        disable_user,
        disabled="@as []",
        ecrit=True,
        shell=False,
        env=None,
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
                # ECHEC_EXT=absente : refusé comme sous Wayland juste
                # après le lien, GNOME Shell n'ayant pas encore relu ses
                # extensions, dans la langue des messages comme le fait
                # gettext. ECHEC_EXT=bus : une autre erreur de l'outil.
                "gnome-extensions": (
                    'echo "gnome-extensions $*" >>"$DOSSIER/appels"\n'
                    'case "${ECHEC_EXT:-}" in\n'
                    "    absente)\n"
                    '        case "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" in\n'
                    "            fr*) echo \"L'extension « $2 » est"
                    ' inconnue" >&2 ;;\n'
                    '            *) echo "Extension \u201c$2\u201d does not'
                    ' exist" >&2 ;;\n'
                    "        esac\n"
                    "        exit 2 ;;\n"
                    '    bus) echo "Error: Timeout was reached" >&2\n'
                    "        exit 1 ;;\n"
                    "esac\n"
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
            environ = {"DOSSIER": dossier, "FAUX": str(faux)}
            environ.update(env or {})
            fait = sourcer(fragment, environ)
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

    def test_a_refused_gnome_extensions_enable_stays_quiet(self):
        """Juste après le lien, GNOME Shell ne connaît pas encore
        l'extension et gnome-extensions enable la dit absente. Les clés
        gsettings sont déjà écrites : le message de l'outil ne passe pas,
        quelle que soit la langue des messages, une seule ligne dit que la
        prochaine connexion la charge, et l'installation continue."""
        for langue in ({}, {"LANG": "fr_CA.UTF-8"}):
            with self.subTest(langue=langue):
                env = {"ECHEC_EXT": "absente", "LC_ALL": "", "LANG": "C"}
                env["LC_MESSAGES"] = ""
                env.update(langue)
                fait, etat, appels = self.jouer(
                    "@as []", "true", shell=True, env=env
                )
                self.assertEqual(fait.returncode, 0, fait.stderr)
                self.assertIn("gnome-extensions enable %s" % UUID, appels)
                self.assertEqual(etat["enabled-extensions"], "['%s']" % UUID)
                self.assertEqual("", fait.stderr)
                self.assertNotIn(UUID, fait.stdout)
                lignes = [
                    ligne
                    for ligne in fait.stdout.splitlines()
                    if "extension enabled" in ligne
                ]
                self.assertEqual(1, len(lignes), fait.stdout)

    def test_another_gnome_extensions_error_is_shown_as_a_failure(self):
        """Une autre erreur de gnome-extensions enable passe sur la sortie
        d'erreur, et le journal dit l'échec plutôt qu'une activation.
        L'installation continue : les clés gsettings sont écrites."""
        fait, etat, _appels = self.jouer(
            "@as []", "true", shell=True, env={"ECHEC_EXT": "bus"}
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(etat["enabled-extensions"], "['%s']" % UUID)
        self.assertIn("Error: Timeout was reached", fait.stderr)
        self.assertNotIn("extension enabled", fait.stdout)
        self.assertIn("gnome-extensions enable failed", fait.stdout)


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
    @SANS_EXTENSION
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

    # gsettings simulé : « get » lit le fichier de la clé, « set »
    # l'écrit ; ECHEC_GET ou ECHEC_SET font échouer l'opération.
    GSETTINGS_FAUX = (
        "gsettings_bus() {\n"
        '    case "$1" in\n'
        '        get) [ -z "${ECHEC_GET:-}" ] && cat "$DOSSIER/$3" ;;\n'
        '        set) [ -z "${ECHEC_SET:-}" ]'
        ' && printf "%s\\n" "$4" >"$DOSSIER/$3" ;;\n'
        "    esac\n"
        "}\n"
    )

    def jouer_desinstallation(self, dossier, echec):
        base = Path(dossier, "extensions")
        base.mkdir()
        (base / UUID).symlink_to(EXTENSION)
        Path(dossier, "venv/bin").mkdir(parents=True)
        Path(dossier, "enabled-extensions").write_text("['%s']\n" % UUID)
        fragment = (
            'EXT_LINK="$DOSSIER/extensions/$UUID"\n'
            'UDEV_RULE="$DOSSIER/absente.rules"\n'
            'VENV="$DOSSIER/venv"\n' + self.GSETTINGS_FAUX + "step_uninstall\n"
        )
        env = {"DOSSIER": dossier, "UUID": UUID, echec: "1"}
        return sourcer(fragment, env), base / UUID

    @SANS_EXTENSION
    def test_a_second_full_uninstall_changes_nothing(self):
        """La seconde exécution lit une liste où l'UUID n'est plus, sous la
        forme « @as [] » que gsettings rend d'une liste vide : elle n'y
        écrit rien, et sort en 0."""
        with tempfile.TemporaryDirectory() as dossier:
            base = Path(dossier, "extensions")
            base.mkdir()
            (base / UUID).symlink_to(EXTENSION)
            Path(dossier, "venv/bin").mkdir(parents=True)
            Path(dossier, "enabled-extensions").write_text("['%s']\n" % UUID)
            journal = Path(dossier, "appels")
            journal.touch()
            fragment = (
                'EXT_LINK="$DOSSIER/extensions/$UUID"\n'
                'UDEV_RULE="$DOSSIER/absente.rules"\n'
                'VENV="$DOSSIER/venv"\n'
                "gsettings_bus() {\n"
                '    case "$1" in\n'
                "        get) sed 's/^\\[\\]$/@as []/' \"$DOSSIER/$3\" ;;\n"
                '        set) echo "set $3 $4" >>"$JOURNAL"\n'
                '            printf "%s\\n" "$4" >"$DOSSIER/$3" ;;\n'
                "    esac\n"
                "}\n"
                "step_uninstall\n"
                'echo "--- second ---" >>"$JOURNAL"\n'
                "step_uninstall\n"
            )
            fait = sourcer(
                fragment,
                {"DOSSIER": dossier, "UUID": UUID, "JOURNAL": str(journal)},
            )
            premier, second = journal.read_text().split("--- second ---\n")
            liste = Path(dossier, "enabled-extensions").read_text().strip()
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertEqual("set enabled-extensions []\n", premier)
        self.assertEqual("", second)
        self.assertEqual("[]", liste)

    @SANS_EXTENSION
    def test_une_liste_illisible_ne_passe_pas_pour_un_succes(self):
        """gsettings absent ou bus en panne : le reste part quand même, puis
        le script sort en 1 en nommant l'UUID qui peut rester activé."""
        for echec in ("ECHEC_GET", "ECHEC_SET"):
            with self.subTest(echec=echec):
                with tempfile.TemporaryDirectory() as dossier:
                    fait, lien = self.jouer_desinstallation(dossier, echec)
                    self.assertEqual(fait.returncode, 1, fait.stdout)
                    self.assertIn("enabled-extensions", fait.stderr)
                    self.assertIn(UUID, fait.stderr)
                    self.assertFalse(os.path.lexists(lien))
                    self.assertFalse(Path(dossier, "venv").exists())

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


class LesOptionsDuService(Installateur):
    """--deck-program et --autostart : au niveau Stream Deck seulement, et
    ce que --dry-run en annonce."""

    def test_help_lists_them(self):
        fini = self.lancer("--help")
        for option in (
            "--deck-program=tiler|controller|none",
            "--autostart",
        ):
            self.assertIn(option, fini.stdout)

    def test_without_stream_deck_they_are_a_usage_error(self):
        for option in (
            "--deck-program=tiler",
            "--autostart",
        ):
            with self.subTest(option=option):
                fini = self.lancer(option, "--dry-run")
                self.assertEqual(1, fini.returncode, fini.stdout)
                self.assertIn("--stream-deck", fini.stderr)
                self.assertNotIn("UNSUPPORTED", fini.stderr)
                self.assertEqual([], self.lignes(fini, "family="))

    def test_with_uninstall_they_are_a_usage_error(self):
        fini = self.lancer(
            "--uninstall", "--stream-deck", "--autostart", "--dry-run"
        )
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertEqual([], self.lignes(fini, "remove: "))

    def test_an_unknown_program_is_a_usage_error(self):
        fini = self.lancer(
            "--stream-deck", "--deck-program=exemple", "--dry-run"
        )
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("exemple", fini.stderr)
        self.assertEqual([], self.lignes(fini, "family="))

    def test_the_dry_run_shows_the_settings_kept_or_given(self):
        """Une option absente garde la valeur des réglages en place ; une
        option donnée la remplace."""
        Path(self.reglages).parent.mkdir(parents=True)
        Path(self.reglages).write_text(
            "DECK_PROGRAM=controller\n", encoding="utf-8"
        )
        for options, attendus in (
            ((), ["DECK_PROGRAM=controller"]),
            (("--deck-program=tiler",), ["DECK_PROGRAM=tiler"]),
        ):
            with self.subTest(options=options):
                fini = self.lancer("--stream-deck", *options, "--dry-run")
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(attendus, self.lignes(fini, "setting: "))

    def test_the_defaults_write_unit_and_settings_without_enabling(self):
        fini = self.lancer("--stream-deck", "--dry-run")
        self.assertEqual(0, fini.returncode, fini.stderr)
        ecrits = self.lignes(fini, "write: ")
        self.assertIn(self.unite, ecrits)
        self.assertIn(self.reglages, ecrits)
        self.assertEqual(
            ["DECK_PROGRAM=tiler"], self.lignes(fini, "setting: ")
        )
        self.assertEqual(
            ["--user daemon-reload"], self.lignes(fini, "systemctl: ")
        )

    def test_the_options_reach_the_settings_and_the_enable(self):
        fini = self.lancer(
            "--stream-deck",
            "--deck-program=controller",
            "--autostart",
            "--dry-run",
        )
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            ["DECK_PROGRAM=controller"], self.lignes(fini, "setting: ")
        )
        self.assertEqual(
            ["--user daemon-reload", "--user enable " + UNITE],
            self.lignes(fini, "systemctl: "),
        )

    def test_the_base_has_no_service(self):
        fini = self.lancer("--dry-run", "--with-extras")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertNotIn(self.unite, fini.stdout)
        self.assertEqual([], self.lignes(fini, "setting: "))
        self.assertEqual([], self.lignes(fini, "systemctl: "))

    def test_both_uninstalls_stop_and_disable_it(self):
        for niveau in ((), ("--stream-deck",)):
            with self.subTest(niveau=niveau):
                fini = self.lancer("--uninstall", *niveau, "--dry-run")
                self.assertEqual(0, fini.returncode, fini.stderr)
                self.assertEqual(
                    [
                        "--user stop " + UNITE,
                        "--user disable " + UNITE,
                        "--user daemon-reload",
                    ],
                    self.lignes(fini, "systemctl: "),
                )


# L'unité attendue pour un dépôt dont le chemin porte une espace et « % ».
UNITE_ATTENDUE = """[Unit]
Description=ERPLibre Home Stream Deck program
PartOf=graphical-session.target
After=graphical-session.target
StartLimitIntervalSec=60
StartLimitBurst=5

[Service]
Type=simple
WorkingDirectory=/srv/depot de test 100%%
Environment=PYTHONUNBUFFERED=1
ExecCondition="/srv/depot de test 100%%/script/install/erplibre_home_deck.sh" --check
ExecStart="/srv/depot de test 100%%/script/install/erplibre_home_deck.sh"
Restart=on-failure
RestartSec=3
RestartPreventExitStatus=2 3
SuccessExitStatus=143
TimeoutStopSec=10

[Install]
WantedBy=graphical-session.target sys-subsystem-erplibre-streamdeck.device
"""


class TestUniteDuService(unittest.TestCase):
    def test_the_unit_text_quotes_and_escapes_the_checkout(self):
        fait = sourcer('RACINE="/srv/depot de test 100%"\nunit_content\n')
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual(fait.stdout, UNITE_ATTENDUE)

    def test_the_exit_codes_are_those_of_the_deck_programs(self):
        """2 : le deck est pris ; 3 : le tiler ne trouve aucun deck à écran.
        Ni l'un ni l'autre ne se corrige en relançant. 143 : la sortie
        propre d'un programme du deck sur SIGTERM (deck_lock.exit_on_sigterm),
        que systemd compterait sinon comme un échec à l'arrêt."""
        if not DECK_PRESENT:
            self.skipTest("script/stream_deck/deck absent")
        deck_lock = charger_du_deck("deck_lock", "deck_lock.py")
        lignes = UNITE_ATTENDUE.splitlines()
        self.assertIn(
            "RestartPreventExitStatus=%d %d"
            % (deck_lock.BUSY_EXIT, deck_lock.NO_DECK_EXIT),
            lignes,
        )
        self.assertIn("SuccessExitStatus=%d" % (128 + signal.SIGTERM), lignes)

    def test_a_stop_is_bounded(self):
        """Un fil non démon d'un programme du deck retient SystemExit après
        SIGTERM : sans borne, systemctl stop (Deck program = none, la
        désinstallation) attendrait le défaut de 90 s."""
        fait = sourcer('RACINE="/srv/exemple"\nunit_content\n')
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("TimeoutStopSec=10", fait.stdout.splitlines())

    def test_a_dollar_in_the_checkout_is_written_as_is(self):
        """systemd ne développe les variables que dans les ARGUMENTS d'une
        ligne Exec*, jamais dans le chemin de l'exécutable ni dans
        WorkingDirectory : l'unité n'en porte pas d'autre, et un « $$ » y
        resterait doublé (le test systemd-analyze ci-dessous le charge)."""
        fait = sourcer(
            'RACINE="$CHEMIN"\nunit_content\n',
            {"CHEMIN": "/srv/depot ${exemple} $exemple"},
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn(
            'ExecStart="/srv/depot ${exemple} $exemple/script/install/'
            'erplibre_home_deck.sh"',
            fait.stdout.splitlines(),
        )
        self.assertNotIn("$$", fait.stdout)

    @unittest.skipUnless(
        shutil.which("systemd-analyze"), "systemd-analyze absent"
    )
    def test_systemd_loads_the_unit_of_a_checkout_with_space_and_percent(
        self,
    ):
        """systemd-analyze verify lit l'unité hors ligne et vérifie que
        ExecStart et ExecCondition désignent un exécutable : le chemin
        cité et échappé, « $ » et « ${…} » compris, est bien celui du
        dépôt. Une clé mal placée (StartLimit* hors de [Unit]) y serait
        dite inconnue."""
        with tempfile.TemporaryDirectory() as dossier:
            depot = Path(dossier, "copie du depot $exemple ${exemple} 100%")
            (depot / "script/install").mkdir(parents=True)
            for nom in (
                "install_erplibre_home.sh",
                "erplibre_home_settings.sh",
                "erplibre_home_deck.sh",
            ):
                shutil.copy2(
                    RACINE / "script/install" / nom, depot / "script/install"
                )
            unite = Path(dossier, UNITE)
            fait = sourcer(
                'unit_content >"$UNITE"\n',
                {
                    "INSTALLEUR": str(
                        depot / "script/install/install_erplibre_home.sh"
                    ),
                    "UNITE": str(unite),
                },
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            verifie = subprocess.run(
                ["systemd-analyze", "verify", str(unite)],
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(
            verifie.returncode, 0, verifie.stdout + verifie.stderr
        )
        self.assertNotIn("not executable", verifie.stderr)
        self.assertNotIn("Unknown key", verifie.stderr)

    def test_a_path_systemd_refuses_stops_the_install(self):
        for chemin in ("/srv/l'exemple", '/srv/le "depot"', "/srv/a\\b"):
            with self.subTest(chemin=chemin):
                fait = sourcer(
                    'RACINE="$CHEMIN"\ncheck_checkout_path\necho passe\n',
                    {"CHEMIN": chemin},
                )
                self.assertEqual(fait.returncode, 1)
                self.assertIn(chemin, fait.stderr)
                self.assertNotIn("passe", fait.stdout)

    def test_space_and_percent_pass(self):
        fait = sourcer(
            'RACINE="/srv/depot de test 100%"\ncheck_checkout_path\n'
            "echo passe\n"
        )
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertEqual("passe\n", fait.stdout)


# systemctl simulé : chaque appel au journal ; ENABLED fait réussir
# is-enabled, ECHEC fait échouer tout appel (pas de gestionnaire joignable).
# STDERR, interprété par printf %b, part sur la sortie d'erreur de enable et
# de reenable, comme les lignes que le vrai y écrit.
SYSTEMCTL_FAUX = (
    'on_session_bus() { "$@"; }\n'
    "systemctl() {\n"
    '    echo "systemctl $*" >>"$JOURNAL"\n'
    '    case "$2" in enable|reenable)\n'
    '        [ -z "${STDERR:-}" ] || printf "%b\\n" "$STDERR" >&2 ;;\n'
    "    esac\n"
    '    [ -z "${ECHEC:-}" ] || return 1\n'
    '    case "$2" in is-enabled) [ -n "${ENABLED:-}" ] ;; esac\n'
    "}\n"
)


class TestServiceInstalle(unittest.TestCase):
    """install_service sur un HOME temporaire et un systemctl simulé."""

    def jouer(self, dossier, apres="", env=None, reglages=None):
        """Lance install_service, puis `apres`. T_PROGRAMME et T_AUTOSTART
        dans `env` tiennent lieu des options ; T_PROGRAMME absent, l'option
        n'a pas été donnée. Rend (fait, appels, unité, réglages)."""
        unite = Path(dossier, "config/systemd/user", UNITE)
        conf = Path(dossier, "config/erplibre-home/streamdeck.conf")
        if reglages is not None:
            conf.parent.mkdir(parents=True, exist_ok=True)
            conf.write_text(reglages, encoding="utf-8")
        journal = Path(dossier, "appels")
        journal.touch()
        environ = {
            "XDG_CONFIG_HOME": str(Path(dossier, "config")),
            "JOURNAL": str(journal),
        }
        environ.update(env or {})
        fait = sourcer(
            'UNIT_FILE="$(deck_unit_file)"\n'
            'SETTINGS_FILE="$(deck_settings_file)"\n'
            'DECK_PROGRAM="${T_PROGRAMME:-}"\n'
            'AUTOSTART="${T_AUTOSTART:-0}"\n'
            + SYSTEMCTL_FAUX
            + "install_service\nsummary\n"
            + apres,
            environ,
        )
        return fait, journal.read_text().splitlines(), unite, conf

    def test_it_writes_unit_and_settings_and_reloads(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, appels, unite, conf = self.jouer(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("ExecStart=", unite.read_text())
            self.assertEqual("DECK_PROGRAM=tiler\n", conf.read_text())
            self.assertEqual(["systemctl --user daemon-reload"], appels)

    def test_it_enables_only_with_autostart_and_never_starts(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, appels, _unite, _conf = self.jouer(
                dossier, env={"T_AUTOSTART": "1"}
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                [
                    "systemctl --user daemon-reload",
                    f"systemctl --user is-enabled --quiet {UNITE}",
                    f"systemctl --user enable {UNITE}",
                ],
                appels,
            )
            self.assertFalse([a for a in appels if " start " in a + " "])

    def test_the_options_land_in_the_settings_and_other_keys_stay(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, conf = self.jouer(
                dossier,
                env={"T_PROGRAMME": "controller"},
                reglages="# note\nEXEMPLE=1\nDECK_PROGRAM=none\n",
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                "# note\nEXEMPLE=1\nDECK_PROGRAM=controller\n",
                conf.read_text(),
            )

    def test_an_install_without_options_keeps_earlier_choices(self):
        """Une option absente garde la valeur déjà dans les réglages : une
        réinstallation ne défait pas un choix fait par une installation
        antérieure ou par le menu ERPLibre Home de TODO."""
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, conf = self.jouer(
                dossier,
                reglages="DECK_PROGRAM=controller\nDECK_PLUGINS_OFF=sound\n",
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                "DECK_PROGRAM=controller\nDECK_PLUGINS_OFF=sound\n",
                conf.read_text(),
            )

    def test_one_option_changes_its_key_only(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, conf = self.jouer(
                dossier,
                env={"T_PROGRAMME": "controller"},
                reglages="DECK_PROGRAM=none\nDECK_PLUGINS_OFF=sound\n",
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                "DECK_PROGRAM=controller\nDECK_PLUGINS_OFF=sound\n",
                conf.read_text(),
            )

    def test_a_missing_or_empty_key_gets_its_default(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, conf = self.jouer(
                dossier, reglages="# note\nDECK_PROGRAM=\n"
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual("# note\nDECK_PROGRAM=tiler\n", conf.read_text())

    def test_a_second_identical_run_touches_nothing(self):
        with tempfile.TemporaryDirectory() as dossier:
            env = {"T_AUTOSTART": "1", "ENABLED": "1"}
            fait, _appels, unite, conf = self.jouer(dossier, env=env)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            avant = (unite.stat().st_mtime_ns, conf.stat().st_mtime_ns)
            Path(dossier, "appels").write_text("")
            fait, appels, unite, conf = self.jouer(dossier, env=env)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(
                avant, (unite.stat().st_mtime_ns, conf.stat().st_mtime_ns)
            )
            self.assertEqual(
                [
                    "systemctl --user daemon-reload",
                    f"systemctl --user is-enabled --quiet {UNITE}",
                ],
                appels,
            )
            self.assertIn("nothing to change", fait.stdout)

    def test_a_rewritten_enabled_unit_is_reenabled(self):
        """Une unité en place qui change et qui est activée est
        réactivée : les liens de son nouveau WantedBy= sont posés.
        Désactivée, elle le reste."""
        for active, attendu in (("1", ["reenable"]), ("", [])):
            with self.subTest(enabled=bool(active)):
                with tempfile.TemporaryDirectory() as dossier:
                    unite = Path(dossier, "config/systemd/user", UNITE)
                    unite.parent.mkdir(parents=True)
                    unite.write_text("[Unit]\n")
                    fait, appels, _unite, _conf = self.jouer(
                        dossier, env={"ENABLED": active}
                    )
                    self.assertEqual(fait.returncode, 0, fait.stderr)
                    self.assertEqual(
                        attendu,
                        [
                            a.split()[2]
                            for a in appels
                            if a.split()[2] in ("reenable", "enable")
                        ],
                    )
                    self.assertIn(
                        f"systemctl --user is-enabled --quiet {UNITE}",
                        appels,
                    )

    def test_a_failed_reload_is_named_and_retried(self):
        """daemon-reload passe à chaque installation : celui qu'un premier
        passage sans gestionnaire n'a pas pu faire est refait par le
        suivant, même si l'unité n'a pas changé."""
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, _unite, _conf = self.jouer(
                dossier, env={"ECHEC": "1"}
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn(
                "after the next login, run: systemctl --user daemon-reload",
                fait.stdout,
            )
            Path(dossier, "appels").write_text("")
            fait, appels, _unite, _conf = self.jouer(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(["systemctl --user daemon-reload"], appels)
            self.assertNotIn("after the next login", fait.stdout)

    @unittest.skipIf(os.geteuid() == 0, "root écrit dans un répertoire 0555")
    def test_an_unwritable_directory_fails_the_install(self):
        """Un répertoire de configuration en lecture seule arrête
        l'installation en 1, sur une ligne ERREUR qui le nomme ; rien n'est
        annoncé comme fait et systemctl n'est pas appelé pour l'unité."""
        for sous_dossier in ("systemd", "erplibre-home"):
            with self.subTest(sous_dossier=sous_dossier):
                with tempfile.TemporaryDirectory() as dossier:
                    bloque = Path(dossier, "config", sous_dossier)
                    bloque.mkdir(parents=True)
                    bloque.chmod(0o555)
                    try:
                        fait, appels, unite, _conf = self.jouer(dossier)
                    finally:
                        bloque.chmod(0o755)
                    self.assertEqual(fait.returncode, 1, fait.stdout)
                    erreurs = [
                        ligne
                        for ligne in fait.stderr.splitlines()
                        if "ERREUR" in ligne
                    ]
                    self.assertEqual(1, len(erreurs), fait.stderr)
                    self.assertIn(str(bloque), erreurs[0])
                    self.assertNotIn("unit: ", fait.stdout)
                    self.assertNotIn("settings: ", fait.stdout)
                    self.assertEqual([], appels)
                    self.assertFalse(unite.exists())
                    self.assertEqual([], list(bloque.parent.rglob("*.conf.*")))

    def test_the_settings_keep_their_mode_and_new_files_get_0644(self):
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, unite, conf = self.jouer(dossier)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertEqual(0o644, conf.stat().st_mode & 0o777)
            self.assertEqual(0o644, unite.stat().st_mode & 0o777)
            conf.chmod(0o640)
            fait, _appels, _unite, conf = self.jouer(
                dossier, env={"T_PROGRAMME": "none"}
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("DECK_PROGRAM=none", conf.read_text())
            self.assertEqual(0o640, conf.stat().st_mode & 0o777)

    def test_the_missing_deck_warning_is_dropped_other_lines_stay(self):
        """Sans deck branché, enable et reenable préviennent que l'unité
        .device du WantedBy= n'existe pas : attendu, la ligne ne passe pas.
        Les autres lignes de systemctl passent, celle qui nomme une autre
        unité absente comprise, et le code de retour garde son effet."""
        attendu = (
            f"Unit {UNITE} is added as a dependency to a non-existent unit "
            "sys-subsystem-erplibre-streamdeck.device."
        )
        autre = (
            f"Unit {UNITE} is added as a dependency to a non-existent unit "
            "exemple-absente.target."
        )
        lien = "Created symlink exemple.wants/" + UNITE
        cas = {
            "enable": ({"T_AUTOSTART": "1"}, False),
            "reenable": ({"ENABLED": "1"}, True),
            "echec": ({"T_AUTOSTART": "1", "ECHEC": "1"}, False),
        }
        for nom, (env, existe) in cas.items():
            with self.subTest(cas=nom):
                with tempfile.TemporaryDirectory() as dossier:
                    if existe:
                        unite = Path(dossier, "config/systemd/user", UNITE)
                        unite.parent.mkdir(parents=True)
                        unite.write_text("[Unit]\n")
                    env = dict(env, STDERR="\\n".join((attendu, lien, autre)))
                    fait, appels, _unite, _conf = self.jouer(dossier, env=env)
                    self.assertEqual(fait.returncode, 0, fait.stderr)
                    commande = [a for a in appels if "enable " + UNITE in a]
                    self.assertTrue(commande, appels)
                    self.assertNotIn(attendu, fait.stderr + fait.stdout)
                    self.assertIn(lien, fait.stderr)
                    self.assertIn(autre, fait.stderr)
                    if nom == "echec":
                        self.assertIn(
                            "after the next login, run: systemctl --user "
                            "enable " + UNITE,
                            fait.stdout,
                        )
                    else:
                        self.assertNotIn("after the next login", fait.stdout)

    def test_without_a_user_manager_the_summary_says_what_to_run(self):
        """Une installation par ssh sans session : l'unité est écrite, le
        script ne s'arrête pas, et le bilan nomme la commande d'après la
        connexion."""
        with tempfile.TemporaryDirectory() as dossier:
            fait, _appels, unite, _conf = self.jouer(
                dossier, env={"T_AUTOSTART": "1", "ECHEC": "1"}
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertTrue(unite.exists())
            self.assertIn(
                "after the next login, run: systemctl --user enable " + UNITE,
                fait.stdout,
            )


class TestServiceSurLeBus(unittest.TestCase):
    """Le vrai on_session_bus reste en place : chaque systemctl --user du
    service passe par le bus de session qu'il choisit, jamais en direct.
    systemctl, id et dbus-run-session sont des fonctions simulées ; le
    journal porte, devant chaque appel, le bus que systemctl a reçu."""

    FRAGMENT = (
        'UNIT_FILE="$(deck_unit_file)"\n'
        'SETTINGS_FILE="$(deck_settings_file)"\n'
        "AUTOSTART=1\n"
        "systemctl() {\n"
        '    echo "${DBUS_SESSION_BUS_ADDRESS:-aucun} systemctl $*"'
        ' >>"$JOURNAL"\n'
        '    [ "$2" != is-enabled ]\n'
        "}\n"
        "id() { echo 999999; }\n"
        "dbus-run-session() {\n"
        "    shift\n"
        '    DBUS_SESSION_BUS_ADDRESS=dbus-run-session "$@"\n'
        "}\n"
        "install_service\nuninstall_service\n"
    )

    def appels(self, env):
        with tempfile.TemporaryDirectory() as dossier:
            journal = Path(dossier, "appels")
            journal.touch()
            environ = {
                "XDG_CONFIG_HOME": str(Path(dossier, "config")),
                "JOURNAL": str(journal),
            }
            environ.update(env)
            fait = sourcer(self.FRAGMENT, environ)
            self.assertEqual(fait.returncode, 0, fait.stderr)
            return journal.read_text().splitlines()

    def verifier(self, bus, appels):
        self.assertEqual(
            [
                "daemon-reload",
                f"is-enabled --quiet {UNITE}",
                f"enable {UNITE}",
                f"stop {UNITE}",
                f"disable {UNITE}",
                "daemon-reload",
            ],
            [a.split(" systemctl --user ", 1)[1] for a in appels],
        )
        for appel in appels:
            self.assertTrue(appel.startswith(bus + " systemctl"), appel)

    def test_the_session_bus_of_the_environment(self):
        bus = "unix:path=/exemple/bus"
        self.verifier(bus, self.appels({"DBUS_SESSION_BUS_ADDRESS": bus}))

    def test_a_private_bus_without_a_session(self):
        self.verifier("dbus-run-session", self.appels({}))


class TestServiceRetire(unittest.TestCase):
    """uninstall_service, et les deux désinstallations qui l'appellent."""

    def preparer(self, dossier):
        config = Path(dossier, "config")
        unite = config / "systemd/user" / UNITE
        unite.parent.mkdir(parents=True)
        unite.write_text("[Unit]\n")
        for cible in (
            "graphical-session.target",
            "sys-subsystem-erplibre-streamdeck.device",
        ):
            voulu = config / "systemd/user" / f"{cible}.wants" / UNITE
            voulu.parent.mkdir()
            voulu.symlink_to(unite)
            self.liens.append(voulu)
        conf = config / "erplibre-home/streamdeck.conf"
        conf.parent.mkdir()
        conf.write_text("DECK_PROGRAM=tiler\n")
        return config, unite, voulu, conf

    def setUp(self):
        self.liens = []

    def test_stop_disable_remove_reload_then_settings(self):
        with tempfile.TemporaryDirectory() as dossier:
            config, unite, voulu, conf = self.preparer(dossier)
            journal = Path(dossier, "appels")
            journal.touch()
            fait = sourcer(
                'UNIT_FILE="$(deck_unit_file)"\n'
                'SETTINGS_FILE="$(deck_settings_file)"\n'
                + SYSTEMCTL_FAUX
                + "uninstall_service\n"
                'echo "--- second ---" >>"$JOURNAL"\n'
                "uninstall_service\n",
                {"XDG_CONFIG_HOME": str(config), "JOURNAL": str(journal)},
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            premier, second = journal.read_text().split("--- second ---\n")
            self.assertEqual(
                [
                    f"systemctl --user stop {UNITE}",
                    f"systemctl --user disable {UNITE}",
                    "systemctl --user daemon-reload",
                ],
                premier.splitlines(),
            )
            self.assertEqual("", second)
            for chemin in (unite, conf):
                self.assertFalse(chemin.exists(), chemin)
            for lien in self.liens:
                self.assertFalse(os.path.lexists(lien), lien)

    def test_a_failing_systemctl_still_removes_the_files(self):
        with tempfile.TemporaryDirectory() as dossier:
            config, unite, voulu, conf = self.preparer(dossier)
            journal = Path(dossier, "appels")
            journal.touch()
            fait = sourcer(
                'UNIT_FILE="$(deck_unit_file)"\n'
                'SETTINGS_FILE="$(deck_settings_file)"\n'
                + SYSTEMCTL_FAUX
                + "uninstall_service\n",
                {
                    "XDG_CONFIG_HOME": str(config),
                    "JOURNAL": str(journal),
                    "ECHEC": "1",
                },
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            self.assertIn("WARNING", fait.stdout)
            self.assertFalse(unite.exists())
            for lien in self.liens:
                self.assertFalse(os.path.lexists(lien), lien)
            self.assertFalse(conf.exists())

    def test_both_uninstalls_remove_the_service(self):
        for niveau in ("1", "0"):
            with self.subTest(stream_deck=niveau):
                with tempfile.TemporaryDirectory() as dossier:
                    config, unite, _voulu, conf = self.preparer(dossier)
                    journal = Path(dossier, "appels")
                    journal.touch()
                    fait = sourcer(
                        'UNIT_FILE="$(deck_unit_file)"\n'
                        'SETTINGS_FILE="$(deck_settings_file)"\n'
                        'EXT_LINK="$DOSSIER/absent-link"\n'
                        'UDEV_RULE="$DOSSIER/absente.rules"\n'
                        'VENV="$DOSSIER/venv"\n'
                        "gsettings_bus() { echo '@as []'; }\n"
                        + SYSTEMCTL_FAUX
                        + 'STREAM_DECK="$NIVEAU"\nstep_uninstall\n',
                        {
                            "XDG_CONFIG_HOME": str(config),
                            "JOURNAL": str(journal),
                            "DOSSIER": dossier,
                            "NIVEAU": niveau,
                        },
                    )
                    self.assertEqual(fait.returncode, 0, fait.stderr)
                    self.assertFalse(unite.exists())
                    self.assertFalse(conf.exists())
                    self.assertIn(f"removed {unite}", fait.stdout)


OUTILS_EXTENSION = shutil.which("glib-compile-schemas") and shutil.which(
    "msgfmt"
)


@SANS_EXTENSION
@unittest.skipUnless(shutil.which("git"), "git absent")
class TestExtensionSeule(CopieDuCheckout):
    """--extension-only sur une copie du checkout, HOME temporaire.

    Le dépôt nu de l'extension porte une copie de la vraie, que le faux
    repo pose dans la copie du checkout, sous un répertoire dont le nom
    contient une espace : chaque chemin que le script bâtit doit être cité.
    setUp la pose une première fois ; chaque lancement la synchronise
    ensuite, sans toucher aux modifications d'un test. Les schémas et les
    traductions se compilent pour de vrai, par glib-compile-schemas et
    msgfmt, sans venv ni réseau, et rien n'est écrit dans le vrai checkout.
    Une fausse migration remplace la vraie dans le dépôt nu : la vraie
    lirait le bus de session de l'utilisateur et sa base dconf.
    """

    NOM_DE_LA_COPIE = "copie du depot"

    def depot_amont_ext(self):
        self.lien = self.home / ".local/share/gnome-shell/extensions" / UUID
        # La fausse migration note si le lien existait à son appel.
        self.migrations = self.tmp / "migrations"
        copie = self.tmp / "extension"
        shutil.copytree(
            EXTENSION,
            copie,
            symlinks=True,
            ignore=shutil.ignore_patterns(
                ".git", "locale", "gschemas.compiled", "__pycache__"
            ),
        )
        migration = copie / "tools/migrate_legacy.py"
        migration.write_text(
            "#!/bin/sh\n"
            'if [ -L "%s" ]; then echo apres; else echo avant; fi >>"%s"\n'
            % (self.lien, self.migrations)
        )
        migration.chmod(0o755)
        depot_nu(self.amont, "erplibre_home", copie)

    def setUp(self):
        super().setUp()
        # Un faux sudo en tête du PATH : --extension-only ne doit jamais
        # l'appeler, et s'il le fait, rien ne s'exécute en root.
        self.trace_sudo = self.tmp / "sudo.appele"
        sudo = self.bin / "sudo"
        sudo.write_text(
            '#!/bin/sh\necho "$@" >>"%s"\nexit 1\n' % self.trace_sudo
        )
        sudo.chmod(0o755)
        self.source = self.ext
        fait = self.poser()
        self.assertEqual(0, fait.returncode, fait.stderr)

    def lancer(self, *options, env=None):
        return super().lancer("--extension-only", *options, env=env)

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
        msgfmt = self.bin / "msgfmt"
        msgfmt.write_text("#!/bin/sh\nexit 2\n")
        msgfmt.chmod(0o755)
        fait = self.lancer()
        self.assertEqual(fait.returncode, 1, fait.stderr)
        self.assertNotIn("UNSUPPORTED", fait.stderr)

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_une_migration_en_echec_n_arrete_pas_l_installation(self):
        """Sous « set -e », une migration qui rend non nul arrêterait
        l'installation avant le lien : elle est notée et le lien se pose."""
        migration = self.source / "tools/migrate_legacy.py"
        migration.write_text("#!/bin/sh\nexit 3\n")
        fait = self.lancer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("legacy migration did not run", fait.stdout)
        self.assertEqual(os.readlink(self.lien), str(self.source))

    @unittest.skipUnless(
        OUTILS_EXTENSION, "glib-compile-schemas ou msgfmt absent"
    )
    def test_une_migration_sans_bit_d_execution_n_arrete_rien(self):
        (self.source / "tools/migrate_legacy.py").chmod(0o644)
        fait = self.lancer()
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("legacy migration did not run", fait.stdout)
        self.assertEqual(os.readlink(self.lien), str(self.source))

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


class TestOptionsDuShell(unittest.TestCase):
    """Le script tourne sous « set -euo pipefail » : une variable non
    définie et l'échec d'une commande au milieu d'un tube l'arrêtent,
    comme l'échec d'une commande seule."""

    def jouer(self, fragment):
        fait = sourcer(fragment + "echo apres\n")
        self.assertNotEqual(0, fait.returncode, fait.stdout)
        self.assertNotIn("apres", fait.stdout)

    def test_a_failed_command_stops_the_script(self):
        self.jouer("false\n")

    def test_an_unset_variable_stops_the_script(self):
        self.jouer('echo "${EXEMPLE_NON_DEFINIE}"\n')

    def test_a_failure_inside_a_pipe_stops_the_script(self):
        self.jouer("false | cat\n")


class TestBilan(unittest.TestCase):
    """Le bilan d'une installation dit de rouvrir la session : sous
    Wayland, GNOME Shell ne charge une extension nouvelle qu'à
    l'ouverture de session, et sans l'indication le nouvel UUID semble ne
    pas marcher. Une désinstallation ne le dit pas."""

    LIGNE = (
        "[ERPLibre Home] log out and back in: GNOME Shell loads a new"
        " extension only at session start under Wayland"
    )

    def test_an_install_says_to_log_out_and_back_in(self):
        fait = sourcer("UNINSTALL=0\nsummary\n")
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertIn(self.LIGNE, fait.stdout.splitlines())

    def test_an_uninstall_does_not(self):
        fait = sourcer("UNINSTALL=1\nsummary\n")
        self.assertEqual(0, fait.returncode, fait.stderr)
        self.assertNotIn("log out", fait.stdout)


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


@SANS_EXTENSION
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
    """Les lignes de recette de `cible` dans make.streamdeck.Makefile,
    que la règle nomme des prérequis ou non."""
    lignes = MAKEFILE_STREAMDECK.read_text().splitlines()
    debut = 1 + next(
        i
        for i, ligne in enumerate(lignes)
        if ligne == "%s:" % cible or ligne.startswith("%s: " % cible)
    )
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

    def test_l_installation_dit_de_rouvrir_la_session_sous_wayland(self):
        """Wayland ne lit le répertoire des extensions qu'à l'ouverture de
        session : sans l'indication, le nouvel UUID semble ne pas marcher."""
        indication = [
            ligne
            for ligne in recette("erplibre_home_install_extension")
            if "Wayland" in ligne
        ]
        self.assertEqual(len(indication), 1)
        self.assertIn("log out", indication[0])
        self.assertIn("log in", indication[0])

    @SANS_EXTENSION
    def test_les_cibles_de_l_extension_existent(self):
        """Chaque cible porte le nom erplibre_home_ et lance ce qu'elle
        annonce."""
        texte = MAKEFILE_STREAMDECK.read_text()
        attendues = {
            "uninstall_extension": '@rm -rf "$(ERPLIBRE_HOME_EXT_DST)"',
            "reload": "$(ERPLIBRE_HOME_DBUS_IFACE).HotReload",
            "reload_clean": "$(ERPLIBRE_HOME_DBUS_IFACE).HotExit",
            "dev_nested": "$(ERPLIBRE_HOME_EXT_SRC)/dev_nested.sh",
            "e2e_nested": "$(ERPLIBRE_HOME_EXT_SRC)/test/e2e_nested.sh",
        }
        for suffixe, extrait in attendues.items():
            cible = "erplibre_home_" + suffixe
            with self.subTest(cible=cible):
                self.assertIn(".PHONY: %s\n" % cible, texte)
                self.assertTrue(
                    any(extrait in ligne for ligne in recette(cible))
                )
        for script in ("dev_nested.sh", "test/e2e_nested.sh"):
            with self.subTest(script=script):
                self.assertTrue(os.access(EXTENSION / script, os.X_OK))

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


MAKEFILE_TEST = RACINE / "conf/make.test.Makefile"
MAKEFILE_INSTALLATION = RACINE / "conf/make.installation.Makefile"
EXT_REL = "script/gnome-extension/erplibre_home"


def domaine():
    """Le domaine gettext que metadata.json déclare à GNOME Shell."""
    with open(EXTENSION / "metadata.json", encoding="utf-8") as flux:
        return json.load(flux)["gettext-domain"]


class TestCiblesDeLExtension(unittest.TestCase):
    """Les cibles make de l'extension, lancées pour de vrai dans une copie.

    La copie ne porte que ce que la cible lit, sous le chemin relatif que
    sa recette nomme, plus la bibliothèque des réglages et un metadata.json
    pour le garde erplibre_home_extension_present du fragment Stream Deck ;
    node et python3 sont remplacés par des témoins qui notent leurs
    arguments, glib-compile-schemas et msgfmt sont les vrais.
    """

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.depot = Path(dossier.name) / "depot"
        self.source = self.depot / EXT_REL
        self.bin = Path(dossier.name) / "bin"
        self.bin.mkdir()
        self.trace_node = Path(dossier.name) / "node.appele"
        node = self.bin / "node"
        node.write_text('#!/bin/sh\necho "$@" >>"%s"\n' % self.trace_node)
        node.chmod(0o755)
        self.trace_python = Path(dossier.name) / "python3.appele"
        python = self.bin / "python3"
        python.write_text('#!/bin/sh\necho "$@" >>"%s"\n' % self.trace_python)
        python.chmod(0o755)
        reglages = self.depot / "script/install/erplibre_home_settings.sh"
        reglages.parent.mkdir(parents=True)
        shutil.copy2(
            RACINE / "script/install/erplibre_home_settings.sh", reglages
        )
        self.source.mkdir(parents=True)
        (self.source / "metadata.json").write_text("{}")

    def faire(self, makefile, cible):
        return subprocess.run(
            [
                "make",
                "--no-print-directory",
                "-f",
                str(MAKEFILE_STREAMDECK),
                "-f",
                str(makefile),
                cible,
            ],
            cwd=self.depot,
            env=dict(
                os.environ,
                PATH="%s:%s" % (self.bin, os.environ.get("PATH", "")),
            ),
            capture_output=True,
            text=True,
            timeout=60,
        )

    def copier_l_extension(self):
        shutil.copytree(EXTENSION / "schemas", self.source / "schemas")
        (self.source / "test/unit").mkdir(parents=True)
        for test in (EXTENSION / "test/unit").glob("*.test.js"):
            (self.source / "test/unit" / test.name).write_text("")

    @unittest.skipUnless(
        shutil.which("glib-compile-schemas"), "glib-compile-schemas absent"
    )
    @SANS_EXTENSION
    def test_test_gnome_extension_valide_le_schema_puis_lance_node(self):
        self.copier_l_extension()
        fait = self.faire(MAKEFILE_TEST, "test_gnome_extension")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        tests = sorted(
            "%s/test/unit/%s" % (EXT_REL, p.name)
            for p in (EXTENSION / "test/unit").glob("*.test.js")
        )
        # Les commandes de test que l'article 2 du contrat énonce.
        self.assertTrue(tests)
        self.assertEqual(
            self.trace_node.read_text().split(), ["--test", *tests]
        )
        # Les tests Python des outils, que le dépôt de l'extension porte.
        self.assertEqual(
            self.trace_python.read_text().split(),
            ["-m", "unittest", "discover", "-s", EXT_REL + "/test/python"],
        )
        self.assertIn(
            "test_gnome_extension",
            next(
                ligne
                for ligne in MAKEFILE_TEST.read_text().splitlines()
                if ligne.startswith("test_full_fast:")
            ),
        )

    @unittest.skipUnless(
        shutil.which("glib-compile-schemas"), "glib-compile-schemas absent"
    )
    @SANS_EXTENSION
    def test_un_schema_refuse_en_strict_arrete_test_gnome_extension(self):
        """Un défaut qui ne se lit pas dans son type : sans --strict,
        glib-compile-schemas ignore le fichier et sort en 0."""
        self.copier_l_extension()
        schema = next((self.source / "schemas").glob("*.gschema.xml"))
        schema.write_text(
            '<schemalist><schema id="org.example.casse" '
            'path="/org/example/casse/"><key name="k" type="b">'
            "<default>peut-etre</default></key></schema></schemalist>"
        )
        fait = self.faire(MAKEFILE_TEST, "test_gnome_extension")
        self.assertNotEqual(fait.returncode, 0)
        self.assertFalse(self.trace_node.exists())
        self.assertFalse(self.trace_python.exists())

    def test_sans_l_extension_chaque_cible_qui_la_lit_s_arrete(self):
        """Un checkout sans le clone de l'extension : la cible s'arrête sur
        la commande qui l'installe, avant de lancer quoi que ce soit."""
        (self.source / "metadata.json").unlink()
        cibles = [
            (MAKEFILE_TEST, "test_gnome_extension"),
            (MAKEFILE_INSTALLATION, "extension_i18n_compile"),
        ] + [
            (MAKEFILE_STREAMDECK, cible)
            for cible in (
                "erplibre_home_enable_extension",
                "erplibre_home_dev_nested",
                "erplibre_home_e2e_nested",
                "erplibre_home_compile_locale",
                "claude_install_hooks",
                "claude_install_hooks_dry_run",
                "claude_uninstall_hooks",
            )
        ]
        for makefile, cible in cibles:
            with self.subTest(cible=cible):
                fait = self.faire(makefile, cible)
                self.assertNotEqual(fait.returncode, 0)
                self.assertIn(
                    "no metadata.json in script/gnome-extension/"
                    "erplibre_home/); install it with make"
                    " erplibre_home_install_extension",
                    fait.stderr,
                )
        self.assertFalse(self.trace_node.exists())
        self.assertFalse(self.trace_python.exists())

    def test_test_full_fast_saute_l_extension_absente(self):
        """La suite Odoo ne demande pas l'extension : sans le clone, elle
        annonce ses tests sautés au lieu de s'arrêter sur le garde."""
        prevu = {}
        for cas in ("avec", "sans"):
            if cas == "sans":
                (self.source / "metadata.json").unlink()
            fait = subprocess.run(
                [
                    "make",
                    "-n",
                    "--no-print-directory",
                    "-f",
                    str(MAKEFILE_STREAMDECK),
                    "-f",
                    str(MAKEFILE_TEST),
                    "test_full_fast",
                ],
                cwd=self.depot,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(fait.returncode, 0, fait.stderr)
            prevu[cas] = fait.stdout
        self.assertIn("node --test", prevu["avec"])
        self.assertNotIn("skip test_gnome_extension", prevu["avec"])
        self.assertNotIn("node --test", prevu["sans"])
        self.assertNotIn("erplibre_home_extension_present", prevu["sans"])
        self.assertIn(
            "skip test_gnome_extension: script/gnome-extension/"
            "erplibre_home/ is not installed (make"
            " erplibre_home_install_extension)",
            prevu["sans"],
        )
        self.assertIn("run_parallel_test.py", prevu["sans"])

    @SANS_EXTENSION
    @unittest.skipUnless(shutil.which("msgfmt"), "msgfmt absent")
    def test_extension_i18n_compile_compile_chaque_po_au_nom_du_domaine(
        self,
    ):
        (self.source / "po").mkdir()
        for po in (EXTENSION / "po").glob("*.po"):
            shutil.copy2(po, self.source / "po")
        fait = self.faire(MAKEFILE_INSTALLATION, "extension_i18n_compile")
        self.assertEqual(fait.returncode, 0, fait.stderr)
        self.assertIn("fr", langues())
        self.assertEqual(
            sorted(
                str(p.relative_to(self.source / "locale"))
                for p in (self.source / "locale").rglob("*.mo")
            ),
            [
                "%s/LC_MESSAGES/%s.mo" % (langue, domaine())
                for langue in langues()
            ],
        )


@unittest.skipUnless(
    shutil.which("git") and (RACINE / ".git").exists(), "not a git checkout"
)
class TestLaDocumentation(unittest.TestCase):
    """L'installateur pose l'extension et le deck par Google Repo : chaque
    page qui décrit la pose, dans ses deux langues, nomme le venv qui porte
    repo, la mise de côté et repo start."""

    DOCS = (
        "doc/erplibre_home_gnome_extension",
        "doc/erplibre_streamdeck_deck",
        "script/stream_deck/INSTALL",
    )

    def test_the_docs_name_the_repo_venv_and_the_set_aside(self):
        for doc in self.DOCS:
            for suffixe in (".md", ".fr.md"):
                chemin = RACINE / (doc + suffixe)
                with self.subTest(doc=chemin.name):
                    texte = chemin.read_text(encoding="utf-8")
                    absents = [
                        mot
                        for mot in (
                            "install_erplibre.sh",
                            ".avant-repo-",
                            "repo start",
                        )
                        if mot not in texte
                    ]
                    self.assertEqual(absents, [])


if __name__ == "__main__":
    unittest.main()
