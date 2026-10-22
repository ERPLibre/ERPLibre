#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le test long qui installe ERPLibre Home sur chaque distribution.

Lui crée une VM par système et prend des heures ; ceux-ci tiennent ses
fonctions pures en quelques millisecondes :

- la matrice : ses clés existent au catalogue QEMU, et chaque GNOME attendu
  est dans le « shell-version » de l'extension ;
- la lecture de « GetExtensionInfo » : ACTIVE, ERROR, OUT_OF_DATE, absente ;
- la lecture du journal de session : les indicateurs que l'extension n'a
  pas montés ;
- les cinq étapes de chaque VM, leurs commandes et leurs contrôles, et la
  lecture d'enabled-extensions ;
- l'autologin de chaque famille, rejoué sur un vrai fichier ;
- le verdict d'un système et le code de sortie de la course ;
- le refus d'un arbre de travail modifié.
"""

import configparser
import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "long_test"))

import install_erplibre_home as sd  # noqa: E402

EXTENSION = RACINE / "script/gnome-extension/erplibre_home"
# Un « Depuis= » de CMD_CONDITION : secondes epoch, microsecondes.
DEPUIS = "1700000000.250000"

# Sorties de « gdbus call … GetExtensionInfo », au format texte de GVariant.
INFO_ACTIVE = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'name': <'ERPLibre Home'>,"
    " 'type': <2.0>, 'state': <1.0>, 'error': <''>,"
    " 'hasPrefs': <true>, 'enabled': <true>},)"
)
INFO_ERREUR = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'type': <2.0>,"
    " 'state': <3.0>, 'error': <'TypeError: this.foo is not a function'>,"
    " 'enabled': <true>},)"
)
INFO_PERIMEE = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'type': <2.0>,"
    " 'state': <4.0>, 'error': <''>, 'enabled': <true>},)"
)
INFO_ABSENTE = "(@a{sv} {},)"
INFO_GUILLEMETS = (
    "({'uuid': <'erplibre-home@technolibre.ca'>, 'state': <3.0>,"
    ' \'error\': <"can\'t load \\"x\\"">},)'
)

# Le daemon.conf que livre le paquet gdm3 de Debian.
GDM_LIVRE = """# GDM configuration storage
#
# See /usr/share/gdm/gdm.schemas for a list of available options.

[daemon]
# Uncomment the line below to force the login screen to use Xorg
#WaylandEnable=false

# Enabling automatic login
#  AutomaticLoginEnable = true
#  AutomaticLogin = user1

# Enabling timed login
#  TimedLoginEnable = true
#  TimedLogin = user1
#  TimedLoginDelay = 10

[security]

[xdmcp]

[chooser]

[debug]
# Uncomment the line below to turn on debugging
#Enable=true
"""


class LaMatrice(unittest.TestCase):
    def test_the_keys_are_those_of_the_spec(self):
        self.assertEqual(
            [sd.cle(e) for e in sd.MATRICE],
            [
                "ubuntu:24.04",
                "ubuntu:25.10",
                "ubuntu:26.04",
                "debian:13",
                "fedora:41",
                "fedora:42",
                "fedora:43",
                "fedora:44",
                "almalinux:10",
                "rocky:10",
                "opensuse:16.0",
                "arch:latest",
                "opensuse:tumbleweed",
            ],
        )

    def test_only_the_rolling_ones_may_move_past_the_extension(self):
        roulantes = [sd.cle(e) for e in sd.MATRICE if e["roulante"]]
        self.assertEqual(roulantes, ["arch:latest", "opensuse:tumbleweed"])

    def test_every_key_is_in_the_qemu_catalog(self):
        """La clé part telle quelle vers deploy_qemu.py : une clé qu'il ne
        connaît pas fait tomber la VM avant qu'elle n'existe."""
        import descente

        catalogue = descente.module_qemu().DISTROS
        for entree in sd.MATRICE + sd.NON_SUPPORTES:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(entree["distro"], catalogue)
                self.assertIn(
                    entree["version"], catalogue[entree["distro"]][0]
                )

    def test_every_expected_gnome_is_declared_by_the_extension(self):
        """Un GNOME attendu hors « shell-version » promettrait ACTIVE là où
        l'installateur rendra 2."""
        meta = json.loads(
            (EXTENSION / "metadata.json").read_text(encoding="utf-8")
        )
        for entree in sd.MATRICE:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(entree["gnome_attendu"], meta["shell-version"])

    def test_every_distribution_has_a_family(self):
        for entree in sd.MATRICE:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(
                    sd.FAMILLE[entree["distro"]],
                    ("debian", "rhel", "suse", "arch"),
                )
                self.assertIn(sd.FAMILLE[entree["distro"]], sd.COMMANDE_GIT)

    def test_the_unsupported_ones_are_not_in_the_matrix(self):
        dans = {sd.cle(e) for e in sd.MATRICE}
        for entree in sd.NON_SUPPORTES:
            with self.subTest(cle=sd.cle(entree)):
                self.assertNotIn(sd.cle(entree), dans)
                self.assertTrue(entree["raison"])


class LePlan(unittest.TestCase):
    def test_no_filter_gives_the_whole_matrix(self):
        self.assertEqual(sd.plan(None), sd.MATRICE)
        self.assertEqual(sd.plan(""), sd.MATRICE)

    def test_the_plan_is_a_copy(self):
        sd.plan(None)[0]["distro"] = "autre"
        self.assertEqual(sd.MATRICE[0]["distro"], "ubuntu")

    def test_only_keeps_the_order_asked_for(self):
        choisis = sd.plan("fedora:43, ubuntu:24.04,fedora:43")
        self.assertEqual(
            [sd.cle(e) for e in choisis], ["fedora:43", "ubuntu:24.04"]
        )

    def test_an_unknown_key_is_refused(self):
        with self.assertRaises(ValueError) as ctx:
            sd.plan("ubuntu:22.04")
        self.assertIn("ubuntu:22.04", str(ctx.exception))

    def test_an_unsupported_key_says_why(self):
        with self.assertRaises(ValueError) as ctx:
            sd.plan("debian:12")
        self.assertIn("GNOME 43 < 45", str(ctx.exception))

    def test_an_empty_list_is_refused(self):
        with self.assertRaises(ValueError):
            sd.plan(" , ")


class LaReponseDeGnomeShell(unittest.TestCase):
    def test_active(self):
        info = sd.analyser_extension_info(INFO_ACTIVE)
        self.assertEqual(info, {"state": 1.0, "error": ""})
        self.assertTrue(sd.est_active(info))

    def test_error(self):
        info = sd.analyser_extension_info(INFO_ERREUR)
        self.assertEqual(info["state"], 3.0)
        self.assertEqual(
            info["error"], "TypeError: this.foo is not a function"
        )
        self.assertFalse(sd.est_active(info))

    def test_out_of_date(self):
        info = sd.analyser_extension_info(INFO_PERIMEE)
        self.assertEqual(info, {"state": 4.0, "error": ""})
        self.assertFalse(sd.est_active(info))

    def test_absent_extension(self):
        """GNOME Shell rend un dictionnaire vide pour un UUID qu'il ne
        connaît pas : ni état, ni erreur, et pas ACTIVE."""
        info = sd.analyser_extension_info(INFO_ABSENTE)
        self.assertEqual(info, {"state": None, "error": ""})
        self.assertFalse(sd.est_active(info))

    def test_no_answer_at_all(self):
        self.assertEqual(
            sd.analyser_extension_info(""), {"state": None, "error": ""}
        )
        self.assertFalse(sd.est_active(None))

    def test_a_double_quoted_error_is_read_and_unescaped(self):
        info = sd.analyser_extension_info(INFO_GUILLEMETS)
        self.assertEqual(info["error"], 'can\'t load "x"')

    def test_an_error_text_alone_is_not_active(self):
        """État 1 avec une erreur : l'extension a levé, elle n'est pas
        ACTIVE au sens du test."""
        self.assertFalse(sd.est_active({"state": 1.0, "error": "boom"}))


class LesCommandesVisentLExtension(unittest.TestCase):
    def test_the_uuid_is_the_one_of_metadata(self):
        meta = json.loads(
            (EXTENSION / "metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(sd.UUID_EXTENSION, meta["uuid"])

    def test_the_object_and_interface_are_those_extension_js_exports(self):
        src = (EXTENSION / "extension.js").read_text(encoding="utf-8")
        self.assertIn(f"'{sd.OBJET_EXTENSION}'", src)
        self.assertIn(f'<interface name="{sd.INTERFACE_EXTENSION}">', src)
        for methode in ("ListPaths", "ListDevices"):
            with self.subTest(methode=methode):
                self.assertIn(f'<method name="{methode}">', src)
                self.assertIn(
                    f"{sd.INTERFACE_EXTENSION}.{methode}",
                    sd.cmd_methode(methode),
                )

    def test_session_commands_name_the_user_bus(self):
        for commande in (sd.CMD_SESSION, sd.CMD_INFO, sd.CMD_EXT_INFO):
            with self.subTest(commande=commande[:60]):
                self.assertIn("/run/user/$(id -u)/bus", commande)

    def test_the_gnome_version_is_read(self):
        self.assertEqual(sd.version_gnome("GNOME Shell 46.0\n"), "46.0")
        self.assertEqual(sd.version_gnome("GNOME Shell 50.beta"), "50.beta")
        self.assertEqual(sd.version_gnome("bash: gnome-shell: not found"), "")
        self.assertEqual(sd.majeur("46.0"), "46")

    def test_the_unsupported_reason_is_the_installer_line(self):
        sortie = "family=arch\nUNSUPPORTED: GNOME 52 not in shell-version\n"
        self.assertEqual(
            sd.raison_non_supportee(sortie), "GNOME 52 not in shell-version"
        )
        self.assertEqual(sd.raison_non_supportee("ok\n"), "")
        # Les lignes de la migration ne sont pas une raison.
        self.assertEqual(
            sd.raison_non_supportee("migrate: no session bus\nok\n"), ""
        )


class LesIndicateursNonMontes(unittest.TestCase):
    """L'extension attrape l'exception du constructeur d'un indicateur et
    reste ACTIVE : seul le journal de session nomme ce qui manque."""

    def test_failed_mounts_are_listed_by_id(self):
        sortie = (
            "[ERPLibreHome] mount pencil failed:"
            " No property vertical on StBoxLayout\n"
            "[ERPLibreHome] mount device failed:"
            " No property vertical on StBoxLayout\n"
        )
        self.assertEqual(sd.indicateurs_en_echec(sortie), ["device", "pencil"])

    def test_other_journal_lines_are_ignored(self):
        sortie = (
            "[ERPLibreHome] enabled\n"
            "[ERPLibreHome] sync failed: timeout\n"
            "gnome-shell[4242]: mount point busy, failed\n"
        )
        self.assertEqual(sd.indicateurs_en_echec(sortie), [])

    def test_no_output_is_no_failure(self):
        self.assertEqual(sd.indicateurs_en_echec(None), [])
        self.assertEqual(sd.indicateurs_en_echec(""), [])

    def test_the_journal_is_read_when_enable_logged_its_end(self):
        sortie = (
            "[ERPLibreHome] mount device failed:"
            " No property vertical on StBoxLayout\n"
            "[ERPLibreHome] enabled\n"
        )
        self.assertTrue(sd.journal_lu(sortie))

    def test_no_enabled_line_is_an_unread_journal(self):
        """Sans la ligne de fin d'enable(), l'absence d'échec ne prouve
        rien : ssh a pu tomber ou le journal être vide."""
        self.assertFalse(sd.journal_lu(None))
        self.assertFalse(sd.journal_lu(""))
        self.assertFalse(
            sd.journal_lu(
                "[ERPLibreHome] mount pencil failed: boom\n"
                "[ERPLibreHome] disabled\n"
            )
        )

    def test_the_command_reads_the_lines_extension_js_writes(self):
        src = (EXTENSION / "extension.js").read_text(encoding="utf-8")
        self.assertIn("[ERPLibreHome] mount ${id} failed", src)
        self.assertIn("'[ERPLibreHome] enabled'", src)
        self.assertIn("journalctl --user -b", sd.CMD_MONTAGES)
        self.assertIn("mount", sd.CMD_MONTAGES)
        self.assertIn("enabled", sd.CMD_MONTAGES)


class LeJournalSansDroitDeLecture(unittest.TestCase):
    """Un journald volatil garde les entrées de l'utilisateur dans le
    journal système : `journalctl --user` n'imprime rien, et la commande
    relit par `sudo -n journalctl _UID=...`. Les commandes tournent ici
    pour de bon, sur un journalctl et un sudo factices."""

    LIGNES = "[ERPLibreHome] mount pencil failed: boom\n[ERPLibreHome] enabled"

    def lancer(self, commande, utilisateur, racine):
        bac = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, bac)
        journalctl = Path(bac) / "journalctl"
        journalctl.write_text(
            "#!/bin/sh\n"
            'case "$*" in\n'
            "  '--user '*) printf '%s' \"$FAUX_USER\" ;;\n"
            '  *) printf \'%s\' "$FAUX_ROOT" ;;\n'
            "esac\n"
        )
        sudo = Path(bac) / "sudo"
        sudo.write_text(
            '#!/bin/sh\n[ "$1" = -n ] || exit 9\nshift\nexec "$@"\n'
        )
        for f in (journalctl, sudo):
            f.chmod(0o755)
        env = dict(
            os.environ,
            PATH=bac + os.pathsep + os.environ["PATH"],
            FAUX_USER=utilisateur,
            FAUX_ROOT=racine,
        )
        return subprocess.run(
            ["sh", "-c", commande], env=env, capture_output=True, text=True
        ).stdout

    def test_empty_user_journal_falls_back_to_sudo(self):
        sortie = self.lancer(sd.CMD_MONTAGES, "", self.LIGNES)
        self.assertTrue(sd.journal_lu(sortie))
        self.assertEqual(sd.indicateurs_en_echec(sortie), ["pencil"])

    def test_journalctl_hint_alone_still_falls_back(self):
        sortie = self.lancer(
            sd.CMD_MONTAGES, "Hint: You are currently not seeing", self.LIGNES
        )
        self.assertTrue(sd.journal_lu(sortie))

    def test_a_readable_user_journal_needs_no_sudo(self):
        sortie = self.lancer(
            sd.CMD_MONTAGES, "[ERPLibreHome] enabled", "[ERPLibreHome] x"
        )
        self.assertEqual(sortie.strip(), "[ERPLibreHome] enabled")

    def test_both_empty_is_an_unread_journal(self):
        sortie = self.lancer(sd.CMD_MONTAGES, "", "")
        self.assertFalse(sd.journal_lu(sortie))

    def test_unit_journal_falls_back_to_the_unit_field(self):
        commande = sd.cmd_raison_saut(DEPUIS)
        sortie = self.lancer(commande, "", f"démarrage\n{sd.RAISON_SAUT}")
        self.assertIn(sd.RAISON_SAUT, sortie)
        champ = "_SYSTEMD_USER_UNIT=" + sd.UNITE_DECK
        self.assertIn(champ, commande)
        self.assertIn("_UID=$(id -u)", commande)

    def test_unit_journal_never_uses_user_unit_under_sudo(self):
        """--user-unit= ajoute _UID=getuid() de journalctl, 0 sous sudo :
        la requête ne trouverait jamais les entrées de l'utilisateur."""
        self.assertNotIn("--user-unit", sd.cmd_raison_saut(DEPUIS))

    def test_unit_journal_reads_only_after_the_checks_start(self):
        """Les deux lectures, --user et sudo, s'arrêtent à l'instant noté
        avant « systemctl start » : un saut antérieur du même boot ne
        fournit pas la raison."""
        commande = sd.cmd_raison_saut(DEPUIS)
        self.assertEqual(commande.count(f"--since @{DEPUIS} "), 2)
        self.assertLess(
            sd.CMD_CONDITION.index('echo "Depuis=$(date +%s.%6N)"'),
            sd.CMD_CONDITION.index("systemctl --user start"),
        )
        etat = sd.etat_systemd(f"Depuis={DEPUIS}\nActiveState=inactive")
        self.assertEqual(etat["Depuis"], DEPUIS)

    def test_diagnostic_journal_falls_back_too(self):
        sortie = self.lancer(sd.CMD_JOURNAL, "", "gnome-shell: boom")
        self.assertIn("gnome-shell: boom", sortie)
        self.assertEqual(self.lancer(sd.CMD_JOURNAL, "", ""), "\n")

    def test_el10_expects_gnome_49(self):
        gnomes = {
            (e["distro"], e["version"]): e["gnome_attendu"]
            for e in sd.MATRICE
        }
        self.assertEqual(gnomes[("almalinux", "10")], "49")
        self.assertEqual(gnomes[("rocky", "10")], "49")


class LesEtapes(unittest.TestCase):
    """Les cinq étapes de la spec, dans son ordre, avec ses noms."""

    def test_the_five_stages_in_order(self):
        self.assertEqual(
            [(e["nom"], e["commande"], e["option"]) for e in sd.ETAPES],
            [
                ("base", None, None),
                (
                    "stream-deck",
                    "install-stream-deck",
                    "--stream-deck --deck-program=tiler --autostart",
                ),
                (
                    "partial-uninstall",
                    "uninstall-stream-deck",
                    "--uninstall --stream-deck",
                ),
                ("uninstall", "uninstall", "--uninstall"),
                ("reinstall", "reinstall", ""),
            ],
        )

    def test_the_checks_of_each_stage(self):
        self.assertEqual(
            [list(e["controles"]) for e in sd.ETAPES],
            [
                [
                    "session",
                    "gnome-version",
                    "extension-active",
                    "extension-dbus",
                    "extension-indicators",
                    "base-no-udev",
                    "base-no-venv",
                    "base-idempotent",
                ],
                [
                    "udev",
                    "venv",
                    "games",
                    "service-unit",
                    "service-enabled",
                    "service-condition",
                    "stream-deck-active",
                    "stream-deck-idempotent",
                ],
                [
                    "partial-uninstall-gone",
                    "partial-uninstall-service-gone",
                    "partial-uninstall-kept",
                ],
                ["uninstall-gone", "uninstall-service-gone"],
                [
                    "reinstall-active",
                    "reinstall-indicators",
                    "reinstall-no-udev",
                ],
            ],
        )

    def test_every_name_is_unique(self):
        """« etape » dit seul quelle étape est tombée : aucun nom de
        commande ou de contrôle ne sert deux fois, ni ne reprend un échec
        d'avant les étapes."""
        noms = ["vm", "ssh", "desktop", "code", "install", "autologin"]
        for etape in sd.ETAPES:
            if etape["commande"]:
                noms.append(etape["commande"])
            noms.extend(etape["controles"])
        self.assertEqual(len(noms), len(set(noms)), noms)

    def test_the_plan_describes_each_stage(self):
        lignes = sd.decrire_etapes()
        self.assertEqual(len(lignes), 5)
        for ligne, etape in zip(lignes, sd.ETAPES, strict=True):
            with self.subTest(etape=etape["nom"]):
                for controle in etape["controles"]:
                    self.assertIn(controle, ligne)
                if etape["option"]:
                    self.assertIn(
                        "install_erplibre_home.sh " + etape["option"], ligne
                    )
        self.assertIn("redémarrage", lignes[4])
        self.assertNotIn("--with-extras", " ".join(lignes))
        extras = sd.decrire_etapes(extras=True)
        self.assertIn("--with-extras", extras[0])
        self.assertIn("--with-extras", extras[4])

    def test_the_venv_check_imports_what_the_entry_points_import(self):
        for module in ("StreamDeck", "pyudev", "PIL", "cv2", "requests"):
            with self.subTest(module=module):
                self.assertIn(module, sd.CMD_VENV)
        self.assertIn("keyboard", sd.CMD_VENV)

    def test_the_presence_checks_name_the_rule_venv_and_link(self):
        self.assertIn(sd.REGLE_UDEV, sd.CMD_SANS_REGLE)
        self.assertIn(".venv.streamdeck", sd.CMD_SANS_VENV)
        self.assertIn(sd.UUID_EXTENSION, sd.CMD_LIEN)
        self.assertIn(sd.UUID_EXTENSION, sd.CMD_SANS_LIEN)
        for commande in (
            sd.CMD_SANS_REGLE,
            sd.CMD_SANS_VENV,
            sd.CMD_LIEN,
            sd.CMD_SANS_LIEN,
        ):
            with self.subTest(commande=commande):
                self.assertTrue(commande.endswith("&& echo ok"))
        self.assertIn("/run/user/$(id -u)/bus", sd.CMD_ENABLED)

    def test_the_service_checks_name_the_unit_and_the_checkout(self):
        self.assertIn(sd.FICHIER_UNITE, sd.CMD_UNITE)
        self.assertIn(
            '"ExecStart=\\"$HOME/git/erplibre/script/install/'
            'erplibre_home_deck.sh\\""',
            sd.CMD_UNITE,
        )
        for commande in (
            sd.CMD_AUTOSTART,
            sd.CMD_CONDITION,
            sd.cmd_raison_saut(DEPUIS),
        ):
            with self.subTest(commande=commande):
                self.assertIn("XDG_RUNTIME_DIR=/run/user/$(id -u)", commande)
                self.assertIn("/run/user/$(id -u)/bus", commande)
                self.assertIn(sd.UNITE_DECK, commande)
        self.assertIn(sd.FICHIER_UNITE, sd.CMD_SANS_SERVICE)
        self.assertIn(sd.REGLAGES_DECK, sd.CMD_SANS_SERVICE)
        self.assertTrue(sd.CMD_SANS_SERVICE.endswith("&& echo ok"))
        # La seconde installation de l'étape 2 ne touche ni à l'unité ni
        # aux réglages.
        self.assertIn(sd.FICHIER_UNITE, sd.CMD_MTIMES)
        self.assertIn(sd.REGLAGES_DECK, sd.CMD_MTIMES)

    def test_the_systemctl_show_lines_are_read_in_any_order(self):
        """Un saut sur ExecCondition rend Result=exec-condition sous la
        plupart des systemd, Result=success sous d'autres : les deux
        valent, avec les trois autres preuves."""
        raison = f"[autre]\n{sd.RAISON_SAUT}\n"
        for sortie in (
            "ActiveState=inactive\nResult=success\n"
            "ExecMainStartTimestampMonotonic=0\n",
            "ExecMainStartTimestampMonotonic=0\nResult=success\n"
            "ActiveState=inactive",
            "ActiveState=inactive\nResult=exec-condition\n"
            "ExecMainStartTimestampMonotonic=0\n",
        ):
            with self.subTest(sortie=sortie):
                etat = sd.etat_systemd(sortie)
                self.assertTrue(sd.condition_sautee(etat, raison))
                # Sans la raison du point d'entrée, ce n'est pas prouvé.
                self.assertFalse(sd.condition_sautee(etat, "autre"))
                self.assertFalse(sd.condition_sautee(etat, None))
        for sortie in (
            "ActiveState=active\nResult=success\n"
            "ExecMainStartTimestampMonotonic=0\n",
            "ActiveState=failed\nResult=exit-code\n"
            "ExecMainStartTimestampMonotonic=0\n",
            "ActiveState=inactive\nResult=failed\n"
            "ExecMainStartTimestampMonotonic=0\n",
            # ExecCondition sorti en 255 : un échec, même Result.
            "ActiveState=failed\nResult=exec-condition\n"
            "ExecMainStartTimestampMonotonic=0\n",
            "ActiveState=inactive\nResult=exit-code\n"
            "ExecMainStartTimestampMonotonic=0\n",
            "ActiveState=inactive\nResult=start-limit-hit\n"
            "ExecMainStartTimestampMonotonic=0\n",
            "ActiveState=inactive\n" "ExecMainStartTimestampMonotonic=0\n",
            "ActiveState=inactive\nResult=success\n"
            "ExecMainStartTimestampMonotonic=123456\n",
            "ActiveState=inactive\nResult=exec-condition\n"
            "ExecMainStartTimestampMonotonic=123456\n",
            "ActiveState=inactive\nResult=success\n",
            "",
            None,
        ):
            with self.subTest(sortie=sortie):
                etat = sd.etat_systemd(sortie)
                self.assertFalse(sd.condition_sautee(etat, raison))

    def test_the_enabled_list_is_read(self):
        self.assertEqual(sd.liste_extensions("@as []"), [])
        self.assertEqual(
            sd.liste_extensions(
                "['autre@exemple.org', 'erplibre-home@technolibre.ca']\n"
            ),
            ["autre@exemple.org", "erplibre-home@technolibre.ca"],
        )

    def test_an_unread_list_is_none(self):
        """Une lecture ratée n'est ni une liste vide ni une liste pleine."""
        for sortie in (None, "", "No such schema", "[cassé"):
            with self.subTest(sortie=sortie):
                self.assertIsNone(sd.liste_extensions(sortie))


class LeServiceParti(unittest.TestCase):
    """CMD_SANS_SERVICE joué par bash sous un HOME temporaire, un faux
    systemctl en tête du PATH : il rend la ligne de REPONSE, ou échoue comme
    sans bus quand REPONSE est vide. Le constat ne passe que si tout est
    parti, systemd compris."""

    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.home = Path(dossier.name, "home")
        self.home.mkdir()
        bin_ = Path(dossier.name, "bin")
        bin_.mkdir()
        (bin_ / "systemctl").write_text(
            "#!/bin/sh\n"
            '[ -n "$REPONSE" ] || { echo "Failed to connect to bus:'
            ' No such file or directory" >&2; exit 1; }\n'
            'echo "$REPONSE"; exit 4\n',
            encoding="utf-8",
        )
        (bin_ / "systemctl").chmod(0o755)
        self.path = "%s:%s" % (bin_, os.environ.get("PATH", ""))

    def constat(self, reponse="not-found"):
        environ = {
            k: v for k, v in os.environ.items() if k != "XDG_CONFIG_HOME"
        }
        environ.update(
            {"HOME": str(self.home), "PATH": self.path, "REPONSE": reponse}
        )
        return subprocess.run(
            ["bash", "-c", sd.CMD_SANS_SERVICE],
            capture_output=True,
            text=True,
            env=environ,
            timeout=30,
        ).stdout.strip()

    def poser(self, relatif, lien=None):
        chemin = self.home / relatif
        chemin.parent.mkdir(parents=True, exist_ok=True)
        if lien:
            chemin.symlink_to(lien)
        else:
            chemin.write_text("x\n", encoding="utf-8")

    def test_all_gone_and_unknown_to_systemd_is_ok(self):
        for reponse in (
            "not-found",
            f"Failed to get unit file state for {sd.UNITE_DECK}:"
            " No such file or directory",
        ):
            with self.subTest(reponse=reponse):
                self.assertEqual("ok", self.constat(reponse))

    def test_a_unit_still_known_to_systemd_fails(self):
        for reponse in ("disabled", "enabled", "linked", ""):
            with self.subTest(reponse=reponse):
                self.assertEqual("", self.constat(reponse))

    def test_a_dangling_wants_link_fails(self):
        self.poser(
            ".config/systemd/user/graphical-session.target.wants/"
            + sd.UNITE_DECK,
            lien="/exemple/absent",
        )
        self.assertEqual("", self.constat())

    def test_a_unit_or_settings_left_fails(self):
        for relatif in (
            ".config/systemd/user/" + sd.UNITE_DECK,
            ".config/erplibre-home/streamdeck.conf",
        ):
            with self.subTest(relatif=relatif):
                self.poser(relatif)
                self.assertEqual("", self.constat())
                (self.home / relatif).unlink()


class LAutologin(unittest.TestCase):
    """La commande est rejouée pour de vrai sur un fichier temporaire, avec
    un « sudo » qui ne fait qu'exécuter son argument."""

    def setUp(self):
        self.dossier = tempfile.mkdtemp(prefix="sd-autologin-")
        self.addCleanup(shutil.rmtree, self.dossier, ignore_errors=True)
        faux = os.path.join(self.dossier, "bin")
        os.makedirs(faux)
        sudo = os.path.join(faux, "sudo")
        with open(sudo, "w", encoding="utf-8") as fh:
            fh.write('#!/bin/sh\nexec "$@"\n')
        os.chmod(sudo, 0o755)
        self.env = dict(os.environ, PATH=f"{faux}:{os.environ['PATH']}")

    def _jouer(self, famille, contenu=None, fois=1, distro=None):
        chemin, commande = sd.autologin(famille, "erplibre", distro)
        cible = os.path.join(self.dossier, "etc", os.path.basename(chemin))
        if contenu is not None:
            os.makedirs(os.path.dirname(cible), exist_ok=True)
            with open(cible, "w", encoding="utf-8") as fh:
                fh.write(contenu)
        commande = commande.replace(chemin, cible)
        for _ in range(fois):
            fini = subprocess.run(
                ["bash", "-c", commande],
                env=self.env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            self.assertEqual(0, fini.returncode, fini.stderr)
        with open(cible, encoding="utf-8") as fh:
            return fh.read()

    @staticmethod
    def _daemon(texte):
        cp = configparser.ConfigParser(strict=False, interpolation=None)
        cp.optionxform = str
        cp.read_string(texte)
        return dict(cp["daemon"])

    def test_the_file_of_each_family(self):
        self.assertEqual(
            sd.autologin("debian", "erplibre")[0], "/etc/gdm3/custom.conf"
        )
        self.assertEqual(
            sd.autologin("rhel", "erplibre")[0], "/etc/gdm/custom.conf"
        )
        self.assertEqual(
            sd.autologin("arch", "erplibre")[0], "/etc/gdm/custom.conf"
        )
        self.assertEqual(
            sd.autologin("suse", "erplibre")[0],
            "/etc/sysconfig/displaymanager",
        )

    def test_debian_and_ubuntu_have_their_own_gdm_file(self):
        self.assertEqual(
            sd.autologin("debian", "erplibre", "debian")[0],
            "/etc/gdm3/daemon.conf",
        )
        self.assertEqual(
            sd.autologin("debian", "erplibre", "ubuntu")[0],
            "/etc/gdm3/custom.conf",
        )

    def test_debian_daemon_conf_gets_the_keys_under_daemon(self):
        texte = self._jouer("debian", GDM_LIVRE, distro="debian")
        self.assertEqual(
            self._daemon(texte),
            {"AutomaticLoginEnable": "true", "AutomaticLogin": "erplibre"},
        )
        self.assertLess(
            texte.index("AutomaticLogin=erplibre"), texte.index("[security]")
        )

    def test_the_keys_go_under_daemon(self):
        texte = self._jouer("debian", GDM_LIVRE, distro="ubuntu")
        self.assertEqual(
            self._daemon(texte),
            {"AutomaticLoginEnable": "true", "AutomaticLogin": "erplibre"},
        )
        # Les commentaires et les autres sections restent.
        self.assertIn("#  AutomaticLogin = user1", texte)
        self.assertIn("[security]", texte)

    def test_a_second_run_changes_nothing(self):
        une = self._jouer("rhel", GDM_LIVRE)
        deux = self._jouer("rhel", GDM_LIVRE, fois=2)
        self.assertEqual(une, deux)

    def test_a_previous_user_is_replaced(self):
        texte = self._jouer(
            "arch", "[daemon]\nAutomaticLoginEnable=false\nAutomaticLogin=x\n"
        )
        self.assertEqual(
            self._daemon(texte),
            {"AutomaticLoginEnable": "true", "AutomaticLogin": "erplibre"},
        )

    def test_a_missing_file_gets_the_section(self):
        texte = self._jouer("arch")
        self.assertEqual(
            self._daemon(texte),
            {"AutomaticLoginEnable": "true", "AutomaticLogin": "erplibre"},
        )

    def test_suse_sets_its_sysconfig_key(self):
        livre = (
            '## Type: string\nDISPLAYMANAGER_AUTOLOGIN=""\n'
            'DISPLAYMANAGER="gdm"\n'
        )
        texte = self._jouer("suse", livre, fois=2)
        self.assertEqual(texte.count("DISPLAYMANAGER_AUTOLOGIN="), 1, texte)
        self.assertIn('DISPLAYMANAGER_AUTOLOGIN="erplibre"', texte)
        self.assertIn('DISPLAYMANAGER="gdm"', texte)

    def test_neither_sed_nor_crudini(self):
        for famille in ("debian", "rhel", "arch", "suse"):
            with self.subTest(famille=famille):
                commande = sd.autologin(famille, "erplibre")[1]
                self.assertNotIn("sed ", commande)
                self.assertNotIn("crudini", commande)

    def test_a_user_name_that_could_inject_is_refused(self):
        for nom in ("", "x; rm -rf /", "Root", "a b"):
            with self.subTest(nom=nom):
                with self.assertRaises(ValueError):
                    sd.autologin("debian", nom)

    def test_an_unknown_family_is_refused(self):
        with self.assertRaises(ValueError):
            sd.autologin("nixos", "erplibre")


class LeVerdict(unittest.TestCase):
    UBUNTU = sd.MATRICE[0]
    ARCH = next(e for e in sd.MATRICE if e["distro"] == "arch")

    def test_active(self):
        ligne = sd.verdict_systeme(
            self.UBUNTU,
            0,
            {"state": 1.0, "error": ""},
            "46.0",
            duree_s=12.7,
            journal="ubuntu-24.04.log",
        )
        self.assertEqual(
            ligne,
            {
                "distro": "ubuntu",
                "version": "24.04",
                "gnome_attendu": "46",
                "gnome_mesure": "46.0",
                "verdict": "ACTIVE",
                "etape": None,
                "duree_s": 12,
                "journal": "ubuntu-24.04.log",
            },
        )

    def test_a_failure_before_the_install_names_its_step(self):
        ligne = sd.verdict_systeme(self.UBUNTU, None, None, "", echec="vm")
        self.assertEqual((ligne["verdict"], ligne["etape"]), ("FAILED", "vm"))
        self.assertIsNone(ligne["gnome_mesure"])

    def test_an_install_without_a_code_is_an_install_failure(self):
        ligne = sd.verdict_systeme(self.UBUNTU, None, None, "")
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]), ("FAILED", "install")
        )

    def test_exit_2_is_unsupported_with_the_reason(self):
        ligne = sd.verdict_systeme(
            self.ARCH, 2, None, "", raison="GNOME 52 not in shell-version"
        )
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]),
            ("UNSUPPORTED", "GNOME 52 not in shell-version"),
        )

    def test_exit_1_is_an_install_failure(self):
        ligne = sd.verdict_systeme(self.UBUNTU, 1, None, "")
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]), ("FAILED", "install")
        )

    def test_a_failed_check_is_named(self):
        ligne = sd.verdict_systeme(
            self.UBUNTU, 0, None, "46.0", echec="session"
        )
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]), ("FAILED", "session")
        )

    def test_a_stage_command_or_check_is_named(self):
        """Après l'installation de la base, l'échec d'une étape porte le nom
        de sa commande ou de son contrôle."""
        for echec in ("install-stream-deck", "reinstall-no-udev"):
            with self.subTest(echec=echec):
                ligne = sd.verdict_systeme(
                    self.UBUNTU,
                    0,
                    {"state": 1.0, "error": ""},
                    "46.0",
                    echec=echec,
                )
                self.assertEqual(
                    (ligne["verdict"], ligne["etape"]), ("FAILED", echec)
                )

    def test_an_extension_in_error_is_not_active(self):
        ligne = sd.verdict_systeme(
            self.UBUNTU, 0, {"state": 3.0, "error": "boom"}, "46.0"
        )
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]),
            ("FAILED", "extension-active"),
        )

    def test_an_unsupported_line_has_no_vm(self):
        ligne = sd.ligne_non_supportee(sd.NON_SUPPORTES[0])
        self.assertEqual(ligne["verdict"], "UNSUPPORTED")
        self.assertEqual(ligne["etape"], "GNOME 43 < 45")
        self.assertIsNone(ligne["journal"])


class LeCodeDeSortie(unittest.TestCase):
    @staticmethod
    def _ligne(entree, verdict):
        return dict(
            sd.ligne_non_supportee(dict(entree, raison="")), verdict=verdict
        )

    def test_all_active_is_zero(self):
        lignes = [self._ligne(e, "ACTIVE") for e in sd.MATRICE]
        self.assertEqual(sd.code_sortie(lignes), 0)

    def test_unsupported_is_allowed_only_where_rolling(self):
        arch = next(e for e in sd.MATRICE if e["distro"] == "arch")
        self.assertEqual(sd.code_sortie([self._ligne(arch, "UNSUPPORTED")]), 0)
        self.assertEqual(
            sd.code_sortie([self._ligne(sd.MATRICE[0], "UNSUPPORTED")]), 1
        )

    def test_one_failure_is_one(self):
        lignes = [self._ligne(e, "ACTIVE") for e in sd.MATRICE]
        lignes[3]["verdict"] = "FAILED"
        self.assertEqual(sd.code_sortie(lignes), 1)

    def test_out_of_scope_lines_do_not_count(self):
        lignes = [sd.ligne_non_supportee(e) for e in sd.NON_SUPPORTES]
        lignes.append(self._ligne(sd.MATRICE[0], "ACTIVE"))
        self.assertEqual(sd.code_sortie(lignes), 0)

    def test_the_summary_flags_a_gnome_mismatch(self):
        lignes = sd.resume(
            [
                sd.verdict_systeme(
                    sd.MATRICE[0], 0, {"state": 1.0, "error": ""}, "47.1"
                )
            ]
        )
        self.assertIn("ubuntu:24.04", lignes[1])
        self.assertIn("≠", lignes[1])
        self.assertIn("ACTIVE", lignes[1])


class LaCreation(unittest.TestCase):
    def test_the_vm_is_sized_here(self):
        argv = sd.argv_creation(
            sd.MATRICE[0], "long-sd-x", "/k.pub", ["--cache-bypass"]
        )
        ligne = " ".join(argv)
        for attendu in (
            "deploy_qemu.py",
            "--distro ubuntu",
            "--version 24.04",
            "--name long-sd-x",
            "--desktop",
            "--gpu off",
            "--vcpus 2",
            "--memory 4096",
            "--disk-size 26G",
            "--ssh-key /k.pub",
            "--cache-bypass",
        ):
            with self.subTest(attendu=attendu):
                self.assertIn(attendu, ligne)
        self.assertNotIn("sudo", argv)

    def test_without_a_key_none_is_passed(self):
        self.assertNotIn("--ssh-key", sd.argv_creation(sd.MATRICE[0], "n"))

    def test_the_vm_name_is_a_plain_host_name(self):
        opensuse = next(e for e in sd.MATRICE if e["version"] == "16.0")
        self.assertEqual(
            sd.nom_vm(opensuse, "120000"), "long-sd-opensuse-16-0-120000"
        )


class LArbreDeTravail(unittest.TestCase):
    def setUp(self):
        self.depot = tempfile.mkdtemp(prefix="sd-arbre-")
        self.addCleanup(shutil.rmtree, self.depot, ignore_errors=True)

    def _git(self, *args):
        subprocess.run(
            [
                "git",
                "-C",
                self.depot,
                "-c",
                "user.name=t",
                "-c",
                "user.email=t@example.invalid",
                *args,
            ],
            check=True,
            capture_output=True,
            timeout=60,
        )

    def _depot_commite(self):
        self._git("init", "-q")
        with open(os.path.join(self.depot, "a.txt"), "w") as fh:
            fh.write("a\n")
        self._git("add", "a.txt")
        self._git("commit", "-qm", "a")

    def test_a_committed_tree_is_clean(self):
        self._depot_commite()
        self.assertTrue(sd.arbre_propre(self.depot))

    def test_a_modified_tracked_file_is_refused(self):
        self._depot_commite()
        with open(os.path.join(self.depot, "a.txt"), "a") as fh:
            fh.write("b\n")
        self.assertFalse(sd.arbre_propre(self.depot))

    def test_an_untracked_file_does_not_count(self):
        """Il n'est ni dans HEAD ni dans le bundle."""
        self._depot_commite()
        with open(os.path.join(self.depot, "notes.txt"), "w") as fh:
            fh.write("x\n")
        self.assertTrue(sd.arbre_propre(self.depot))

    def test_a_directory_that_is_not_a_repository_is_refused(self):
        self.assertFalse(sd.arbre_propre(self.depot))


SCRIPT = RACINE / "long_test/install_erplibre_home.py"
SRC = SCRIPT.read_text(encoding="utf-8")


def _mener(*args, maison):
    """Le script mené dans ce processus, sur un HOME qui ne contient rien.
    Rend (code, sortie).

    Pas de sous-processus : un install_erplibre_home.py vivant est, pour les
    tests des autres descentes que le lanceur unitaire passe en parallèle,
    une descente en cours, et leur « --detruire » refuse alors de
    travailler. Le verrou entre descentes n'est pas le sujet de ces tests :
    autre_descente n'y voit rien.
    """
    from unittest import mock

    import descente

    sortie = io.StringIO()
    with (
        mock.patch.dict(os.environ, {"HOME": maison}),
        mock.patch.object(descente, "autre_descente", lambda: []),
        contextlib.redirect_stdout(sortie),
    ):
        code = sd.mener(list(args))
    return code, sortie.getvalue()


class LeScript(unittest.TestCase):
    def test_it_is_executable(self):
        """Le menu et le README l'appellent directement."""
        self.assertTrue(os.access(SCRIPT, os.X_OK))

    def test_the_desktop_comes_from_the_menu(self):
        """Deux copies d'une installation de bureau divergent, et c'est
        celle du test qui reste verte."""
        self.assertIn('_qemu_erplibre_remote_cmd(None, desktop="gnome")', SRC)

    def test_the_cache_flags_reach_the_creation(self):
        self.assertIn("drapeaux_cache()", SRC)

    def test_the_report_carries_the_pid_of_its_run(self):
        self.assertIn('"pid": os.getpid()', SRC)
        self.assertIn('"outil": OUTIL', SRC)

    def test_vms_are_destroyed_in_process_without_a_prompt(self):
        """detruire() demande « OUI » : entre deux systèmes, la course
        n'attend personne. Il ne sert qu'à --detruire."""
        self.assertEqual(SRC.count("detruire(famille"), 1)
        self.assertLess(
            SRC.index("if args.detruire:"), SRC.index("detruire(famille")
        )
        corps = SRC.split("for entree in systemes:\n        try:")[1]
        self.assertIn("detruire_etage1(", corps)
        self.assertIn("retirer_alias(", corps)

    def test_every_bounded_call_is_caught(self):
        """Un test lancé pour des heures rend un VERDICT, pas une trace :
        chaque subprocess.run borné vit dans un « try »."""
        import ast

        arbre = ast.parse(SRC)
        bornes = [
            n.lineno
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and ast.unparse(n.func) == "subprocess.run"
            and any(m.arg == "timeout" for m in n.keywords)
        ]
        self.assertGreaterEqual(len(bornes), 8)
        couvertes = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Try):
                for corps in noeud.body:
                    for interne in ast.walk(corps):
                        if hasattr(interne, "lineno"):
                            couvertes.add(interne.lineno)
        for ligne in bornes:
            with self.subTest(ligne=ligne):
                self.assertIn(ligne, couvertes)


class LEssaiABlanc(unittest.TestCase):
    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-blanc-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)

    def _rapports(self):
        dossier = os.path.join(self.maison, ".erplibre/longtest")
        return sorted(f for f in os.listdir(dossier) if f.endswith(".json"))

    def test_the_whole_plan_creates_nothing(self):
        code, sortie = _mener("--dry-run", maison=self.maison)
        self.assertEqual(0, code, sortie)
        self.assertIn("--dry-run", sortie)
        for entree in sd.MATRICE:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(sd.cle(entree), sortie)
                self.assertIn(
                    f"--distro {entree['distro']} --version"
                    f" {entree['version']}",
                    sortie,
                )
        for entree in sd.NON_SUPPORTES:
            with self.subTest(cle=sd.cle(entree)):
                self.assertIn(f"UNSUPPORTED : {entree['raison']}", sortie)
        for attendu in (
            "--desktop --gpu off --vcpus 2 --memory 4096 --disk-size 26G",
            "ppc64le",
        ):
            self.assertIn(attendu, sortie)
        # Les cinq étapes de chaque VM, leurs commandes et leurs contrôles.
        for ligne in sd.decrire_etapes():
            self.assertIn(ligne, sortie)
        for option in ("--stream-deck", "--uninstall --stream-deck"):
            self.assertIn("install_erplibre_home.sh " + option, sortie)
        # Un essai qui n'écrit rien n'a aucune raison de demander sudo.
        self.assertNotIn("sudo", sortie)
        # Un rapport d'essai, nommé à part : dernier_rapport l'écarte.
        rapports = self._rapports()
        self.assertEqual(len(rapports), 1)
        self.assertTrue(rapports[0].endswith("-dryrun.json"))

    def test_the_report_holds_the_unsupported_lines(self):
        _mener("--dry-run", maison=self.maison)
        chemin = os.path.join(
            self.maison, ".erplibre/longtest", self._rapports()[0]
        )
        with open(chemin, encoding="utf-8") as fh:
            rapport = json.load(fh)
        self.assertEqual(rapport["outil"], "install_erplibre_home")
        self.assertTrue(rapport["dry_run"])
        self.assertEqual(rapport["etages"], [])
        self.assertEqual(
            [s["verdict"] for s in rapport["systemes"]],
            ["UNSUPPORTED"] * len(sd.NON_SUPPORTES),
        )

    def test_only_restricts_the_plan(self):
        code, sortie = _mener(
            "--dry-run", "--only", "fedora:43", "--extras", maison=self.maison
        )
        self.assertEqual(0, code, sortie)
        self.assertIn("--distro fedora --version 43", sortie)
        self.assertNotIn("--distro ubuntu", sortie)
        # Les hors-champ ne sont annoncés que pour la matrice entière.
        self.assertNotIn("debian:12", sortie)
        self.assertIn("--extras ne vaut que pour ubuntu:24.04", sortie)

    def test_an_unsupported_key_is_refused_with_its_reason(self):
        code, sortie = _mener(
            "--dry-run", "--only", "debian:12", maison=self.maison
        )
        self.assertEqual(1, code)
        self.assertIn("GNOME 43 < 45", sortie)


class LArbreModifieEstRefuse(unittest.TestCase):
    """La VM reçoit HEAD : un fichier suivi et modifié ne serait pas dans la
    VM, et le verdict porterait sur autre chose que ce qu'on lit."""

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-sale-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.addCleanup(os.environ.__setitem__, "HOME", os.environ["HOME"])
        os.environ["HOME"] = self.maison
        for nom in ("arbre_propre", "plan_tient", "creer_bundle", "creer_vm"):
            self.addCleanup(setattr, sd, nom, getattr(sd, nom))

    def test_a_dirty_tree_stops_before_anything(self):
        sd.arbre_propre = lambda racine: False
        sd.plan_tient = lambda journal: self.fail("plan_tient appelé")
        sd.creer_bundle = lambda *a: self.fail("bundle créé")
        sd.creer_vm = lambda *a, **k: self.fail("VM créée")
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertEqual(1, sd.mener(["--only", "ubuntu:24.04"]))
        self.assertIn("fichiers suivis sont modifiés", sortie.getvalue())

    def test_the_dry_run_only_warns(self):
        sd.arbre_propre = lambda racine: False
        with contextlib.redirect_stdout(io.StringIO()) as sortie:
            self.assertEqual(
                0, sd.mener(["--dry-run", "--only", "ubuntu:24.04"])
            )
        self.assertIn("la course réelle refusera", sortie.getvalue())


class LeDefaire(unittest.TestCase):
    """La forme du rapport est le CONTRAT du défaire partagé : chaque VM
    gardée par --garder, ou laissée par une course tuée, y est une entrée de
    niveau 1, et --detruire les reprend toutes."""

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-defaire-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)

    def _etage(self, nom):
        return {
            "niveau": 1,
            "nom": nom,
            "uuid": "",
            "alias": nom,
            "cree": True,
        }

    def test_every_kept_vm_is_named(self):
        rapport = {
            "outil": "install_erplibre_home",
            "dry_run": False,
            "pid": 1,
            "etages": [
                self._etage("long-sd-ubuntu-24-04-000000"),
                self._etage("long-sd-fedora-43-000000"),
            ],
            "systemes": [],
        }
        with open(
            os.path.join(self.dossier, "long-sd-19990101-000000.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(rapport, fh)
        # Les journaux par système vivent dans un sous-dossier : jamais pris
        # pour un rapport.
        os.makedirs(os.path.join(self.dossier, "long-sd-19990101-000000"))
        code, sortie = _mener("--detruire", "--dry-run", maison=self.maison)
        self.assertEqual(0, code, sortie)
        self.assertIn("long-sd-ubuntu-24-04-000000", sortie)
        self.assertIn("long-sd-fedora-43-000000", sortie)
        self.assertIn("rien ne sera détruit", sortie)

    def test_an_empty_report_undoes_nothing_and_invents_no_root(self):
        """Une course finie sans --garder laisse « etages » vide : rien à
        défaire, ni racine « long-sd-1 » inventée, ni confirmation."""
        from unittest import mock

        with open(
            os.path.join(self.dossier, "long-sd-19990101-000000.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(
                {
                    "outil": "install_erplibre_home",
                    "dry_run": False,
                    "pid": 1,
                    "etages": [],
                    "systemes": [],
                },
                fh,
            )
        for options in (("--dry-run",), ()):
            with self.subTest(options=options):
                with mock.patch("builtins.input", side_effect=AssertionError):
                    code, sortie = _mener(
                        "--detruire", *options, maison=self.maison
                    )
                self.assertEqual(0, code, sortie)
                self.assertIn("rien à défaire", sortie)
                self.assertNotIn("long-sd-1", sortie)
                self.assertNotIn("défait(s)", sortie)

    def test_another_tools_report_is_left_alone(self):
        with open(
            os.path.join(self.dossier, "long-nixos-19990101-000000.json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(
                {
                    "outil": "install_nixos",
                    "dry_run": False,
                    "pid": 1,
                    "etages": [self._etage("long-nixos-000000")],
                },
                fh,
            )
        _code, sortie = _mener("--detruire", "--dry-run", maison=self.maison)
        self.assertIn("rien à défaire", sortie)
        self.assertNotIn("long-nixos-000000", sortie)


class LeVerrouEtLeMenu(unittest.TestCase):
    def setUp(self):
        from script.todo.todo import TODO

        self.todo = TODO.__new__(TODO)

    def test_it_shares_the_lock_and_the_undo(self):
        import descente

        from script.todo.longtest_menu import SCRIPTS_DEFAISABLES

        self.assertIn("install_erplibre_home.py", descente.SCRIPTS)
        self.assertIn("install_erplibre_home.py", SCRIPTS_DEFAISABLES)

    def test_the_menu_dispatches_plan_run_and_undo(self):
        """10 : le plan, 11 : la course, 12 : le défaire. Aucun ne passe
        « --depth » : il n'y a pas d'étages ici."""
        from unittest import mock

        vus = []
        self.todo.fill_help_info = lambda choix: ""
        self.todo._longtest_run = lambda nom, args="", demander=None: (
            vus.append((nom, args))
        )
        self.todo._longtest_defaire = lambda: vus.append("défaire")
        with mock.patch(
            "script.todo.longtest_menu.click.prompt",
            side_effect=["10", "11", "12", "0"],
        ):
            with contextlib.redirect_stdout(io.StringIO()):
                self.todo.prompt_execute_longtest()
        self.assertEqual(
            vus,
            [
                ("install_erplibre_home.py", "--dry-run"),
                ("install_erplibre_home.py", ""),
                "défaire",
            ],
        )

    def test_every_label_is_translated(self):
        from script.todo.todo_i18n import TRANSLATIONS

        for cle in (
            "ERPLibre Home on every distribution: plan only (dry-run)",
            "ERPLibre Home on every distribution: run it",
        ):
            with self.subTest(cle=cle):
                self.assertIn(cle, TRANSLATIONS)
                self.assertTrue(TRANSLATIONS[cle].get("fr"))
                self.assertTrue(TRANSLATIONS[cle].get("en"))


class DeuxCoursesDeSuite(unittest.TestCase):
    """Une course gardée par --garder, puis une autre : leurs VM ne portent
    jamais le même nom, et chaque course ne détruit que les VM que son
    propre rapport nomme."""

    PREMIERE = "long-sd-19990101-000000"

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-suite-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.addCleanup(os.environ.__setitem__, "HOME", os.environ["HOME"])
        os.environ["HOME"] = self.maison
        self.dossier = os.path.join(self.maison, ".erplibre/longtest")
        os.makedirs(self.dossier)

    def _course(self, nom):
        from unittest import mock

        dossier = os.path.join(self.dossier, nom)
        return sd.Course(mock.Mock(dry_run=False), dossier + ".log", dossier)

    def test_two_run_stamps_never_share_a_vm_name(self):
        systemes = sd.plan()
        premiere = {sd.nom_vm(e, "19990101-000000") for e in systemes}
        seconde = {sd.nom_vm(e, "19990101-000001") for e in systemes}
        self.assertEqual(len(premiere), len(systemes))
        self.assertFalse(premiere & seconde)

    def test_the_run_stamp_is_in_every_vm_name(self):
        course = self._course(self.PREMIERE)
        self.assertEqual(course.horodatage, "19990101-000000")
        self.assertTrue(
            sd.nom_vm(sd.MATRICE[0], course.horodatage).endswith(
                "-19990101-000000"
            )
        )

    def test_a_name_libvirt_already_defines_never_enters_the_report(self):
        """La VM d'une autre course porte ce nom : rien n'est créé, rien
        n'est inscrit, donc rien de ce qu'elle est ne sera détruit."""
        from unittest import mock

        course = self._course(self.PREMIERE)
        with (
            mock.patch.object(
                sd.Descente, "uuid_libvirt", return_value="u-ancienne"
            ),
            mock.patch.object(
                sd.subprocess,
                "run",
                side_effect=AssertionError("deploy_qemu.py lancé"),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            ligne = sd.mener_un(course, sd.MATRICE[0])
        self.assertEqual(course.rapport["etages"], [])
        self.assertEqual((ligne["verdict"], ligne["etape"]), ("FAILED", "vm"))

    def test_the_run_destroys_only_what_its_report_names(self):
        from unittest import mock

        # La VM qu'une course précédente a gardée, dans son propre rapport.
        gardee = "long-sd-ubuntu-24-04-19990101-000000"
        with open(
            os.path.join(self.dossier, self.PREMIERE + ".json"),
            "w",
            encoding="utf-8",
        ) as fh:
            json.dump(
                {
                    "outil": "install_erplibre_home",
                    "dry_run": False,
                    "pid": 1,
                    "etages": [
                        {
                            "niveau": 1,
                            "nom": gardee,
                            "uuid": "u-gardee",
                            "alias": gardee,
                            "cree": True,
                        }
                    ],
                    "systemes": [],
                },
                fh,
            )
        inscrites, detruites = [], []

        def mener_un(course, entree):
            nom = sd.nom_vm(entree, course.horodatage)
            etage = {
                "niveau": 1,
                "nom": nom,
                "uuid": "u-" + nom,
                "alias": nom,
                "cree": True,
            }
            course.inscrire(etage)
            inscrites.append(etage)
            return sd.verdict_systeme(entree, None, None, "", echec="session")

        def detruire_etage1(journal, nom, dry_run=False, attendu=None, **k):
            detruites.append((nom, attendu))
            return True

        with (
            mock.patch.multiple(
                sd,
                arbre_propre=lambda racine: True,
                plan_tient=lambda journal: True,
                creer_bundle=lambda dossier, journal: ("0" * 40, "x.bundle"),
                mener_un=mener_un,
                detruire_etage1=detruire_etage1,
                retirer_alias=lambda *a, **k: None,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            sd.mener(["--only", "ubuntu:24.04,fedora:43"])
        self.assertEqual(len(inscrites), 2)
        self.assertNotIn(gardee, [e["nom"] for e in inscrites])
        self.assertEqual(detruites, [(e["nom"], e["uuid"]) for e in inscrites])


class UneVMQuiSurvit:
    """Une VM que son défaire n'a pas pu détruire : sudo est renouvelé et le
    défaire retenté ; si elle vit encore, aucune autre n'est créée."""

    SYSTEMES = "ubuntu:24.04,fedora:43,debian:13"

    def setUp(self):
        self.maison = tempfile.mkdtemp(prefix="sd-survit-")
        self.addCleanup(shutil.rmtree, self.maison, ignore_errors=True)
        self.addCleanup(os.environ.__setitem__, "HOME", os.environ["HOME"])
        os.environ["HOME"] = self.maison
        self.creees, self.defaites, self.renouvellements = [], [], []

    def _mener(self, reponses, *options):
        """La course sur trois systèmes, `reponses` donnant le résultat de
        chaque appel à detruire_etage1 ; vrai une fois épuisées. Rend
        (code, rapport lu sur le disque)."""
        from unittest import mock

        reponses = list(reponses)

        def mener_un(course, entree):
            nom = sd.nom_vm(entree, course.horodatage)
            course.inscrire(
                {"niveau": 1, "nom": nom, "uuid": "", "alias": nom}
            )
            self.creees.append(nom)
            return sd.verdict_systeme(
                entree, 0, {"state": 1.0, "error": ""}, "46.0"
            )

        def detruire_etage1(journal, nom, dry_run=False, attendu=None, **k):
            self.defaites.append(nom)
            return reponses.pop(0) if reponses else True

        with (
            mock.patch.multiple(
                sd,
                arbre_propre=lambda racine: True,
                plan_tient=lambda journal: True,
                creer_bundle=lambda dossier, journal: ("0" * 40, "x.bundle"),
                mener_un=mener_un,
                detruire_etage1=detruire_etage1,
                retirer_alias=lambda *a, **k: None,
                rafraichir_sudo=lambda journal: self.renouvellements.append(
                    journal
                ),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            code = sd.mener(["--only", self.SYSTEMES, *options])
        dossier = os.path.join(self.maison, ".erplibre/longtest")
        (chemin,) = [f for f in os.listdir(dossier) if f.endswith(".json")]
        with open(os.path.join(dossier, chemin), encoding="utf-8") as fh:
            return code, json.load(fh)


class LaVMSuivanteAttend(UneVMQuiSurvit, unittest.TestCase):
    def test_a_destroy_that_succeeds_after_the_refresh_goes_on(self):
        code, rapport = self._mener([False, True])
        self.assertEqual(code, 0)
        self.assertEqual(len(self.creees), 3)
        self.assertEqual(len(self.renouvellements), 1)
        # Le premier défaire, sa reprise, puis un par VM suivante.
        self.assertEqual(self.defaites, [self.creees[0]] * 2 + self.creees[1:])
        self.assertEqual(rapport["etages"], [])

    def test_a_vm_still_up_stops_the_run(self):
        code, rapport = self._mener([False, False])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.creees), 1)
        self.assertEqual(len(self.renouvellements), 1)
        self.assertEqual([e["nom"] for e in rapport["etages"]], self.creees)
        self.assertEqual(
            [(s["verdict"], s["etape"]) for s in rapport["systemes"]],
            [("ACTIVE", None)] + [("FAILED", "previous-vm-still-up")] * 2,
        )

    def test_the_last_vm_still_up_fails_the_run(self):
        """Rien ne reste à créer, mais la course laisse une VM derrière
        elle : le code de sortie le dit."""
        code, rapport = self._mener([True, True, False, False])
        self.assertEqual(code, 1)
        self.assertEqual(len(self.creees), 3)
        self.assertEqual(len(rapport["etages"]), 1)

    def test_kept_vms_are_never_destroyed_nor_refreshed(self):
        code, rapport = self._mener([], "--garder")
        self.assertEqual(code, 0)
        self.assertEqual(len(self.creees), 3)
        self.assertEqual((self.defaites, self.renouvellements), ([], []))
        self.assertEqual(len(rapport["etages"]), 3)


class LeBureauInstalleParLaCourse(unittest.TestCase):
    """Le menu a rendu 0 : sans GNOME Shell dans la VM, c'est l'étape du
    bureau qui a échoué, non un système que l'installateur ne supporte pas."""

    def _mener(self, gnome_present):
        from unittest import mock

        dossier = tempfile.mkdtemp(prefix="sd-bureau-")
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        course = sd.Course(
            mock.Mock(dry_run=False, extras=False),
            dossier + ".log",
            dossier,
        )
        self.appels = []
        sondes = []

        def sonder(cible, commande, delai=180):
            sondes.append(commande)
            return "/usr/bin/gnome-shell" if gnome_present else ""

        def installer(cible, log, options=""):
            self.appels.append("installer")
            return 2, "no GNOME Shell"

        with (
            mock.patch.multiple(
                sd,
                creer_vm=lambda *a, **k: ("vm", "u-vm", True),
                adresse_de=lambda *a, **k: "192.0.2.1",
                attendre_ssh=lambda *a, **k: True,
                lancer=lambda *a, **k: 0,
                sonder=sonder,
                deposer_code=lambda *a, **k: True,
                installer=installer,
                joindre_diagnostic=lambda *a, **k: None,
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            ligne = sd.mener_un(course, sd.MATRICE[0])
        self.sondes = sondes
        return ligne

    def test_a_desktop_step_without_gnome_shell_fails_at_desktop(self):
        ligne = self._mener(False)
        self.assertEqual(
            (ligne["verdict"], ligne["etape"]), ("FAILED", "desktop")
        )
        self.assertEqual(self.appels, [])
        self.assertTrue(any("gnome-shell" in c for c in self.sondes))

    def test_a_desktop_step_with_gnome_shell_goes_on_to_the_installer(self):
        ligne = self._mener(True)
        self.assertEqual(self.appels, ["installer"])
        self.assertEqual(ligne["verdict"], "UNSUPPORTED")


class LeRenouvellementDeSudo(unittest.TestCase):
    """Interactif devant un terminal, jamais sans : une course sans
    terminal n'attend pas un mot de passe que personne ne tape."""

    def _argv(self, terminal, code=0):
        from unittest import mock

        vus = []

        def run(argv, **k):
            vus.append(argv)
            return subprocess.CompletedProcess(argv, code)

        with (
            mock.patch.object(sd.subprocess, "run", run),
            mock.patch.object(
                sd.sys, "stdin", mock.Mock(isatty=lambda: terminal)
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            rendu = sd.rafraichir_sudo(None)
        return vus, rendu

    def test_a_terminal_may_prompt(self):
        self.assertEqual(self._argv(True), ([["sudo", "-v"]], True))

    def test_without_a_terminal_it_never_prompts(self):
        self.assertEqual(
            self._argv(False, code=1), ([["sudo", "-n", "-v"]], False)
        )


class VMSimulee:
    """Une VM réduite à ce que les étapes lisent et changent : la règle
    udev, le venv, le lien de l'extension, son UUID dans enabled-extensions,
    son état ACTIVE, et les lectures successives du journal de session.

    L'installateur simulé applique ce que chaque option doit faire, puis
    `apres[option]`, qui simule une installation fautive ; `echoue` nomme les
    options qui rendent 1. Elle part de l'état que laisse l'installation de
    la base à l'étape 5 du flux.
    """

    def __init__(self, journaux, echoue=(), apres=None, **etat):
        self.regle = self.venv = self.service = self.autostart = False
        # Les jeux clonés : aucune désinstallation ne les retire.
        self.jeux = False
        self.lien = self.uuid = self.actif = True
        # Sans deck, systemd saute le démarrage du service et le point
        # d'entrée en écrit la raison au journal de l'unité. « resultat »
        # est le Result= de ce saut, exec-condition sur les systemd des
        # VM.
        self.condition = self.raison = True
        self.resultat = "exec-condition"
        # Les lectures du journal de l'unité, et combien d'entre elles
        # passent avant que journald n'y ait écrit la raison.
        self.lectures_raison = self.retard_raison = 0
        # L'instant que CMD_CONDITION note avant « systemctl start ».
        self.depuis = DEPUIS
        self.__dict__.update(etat)
        self.journaux = list(journaux)
        self.echoue = set(echoue)
        self.apres = apres or {}
        self.options = []
        self.lectures = 0
        self.redemarrages = 0

    def installer(self, cible, log, options=""):
        self.options.append(options)
        if options in self.echoue:
            return 1, ""
        if options == "--uninstall --stream-deck":
            self.regle = self.venv = self.service = self.autostart = False
        elif options == "--uninstall":
            self.regle = self.venv = self.lien = self.uuid = False
            self.service = self.autostart = False
        else:
            self.lien = self.uuid = True
            if "--stream-deck" in options:
                self.regle = self.venv = self.service = self.jeux = True
                self.autostart = "--autostart" in options
        self.__dict__.update(self.apres.get(options, {}))
        return 0, ""

    def sonder(self, cible, commande, delai=180):
        if commande == sd.CMD_MONTAGES:
            self.lectures += 1
            return self.journaux.pop(0)
        if commande == sd.cmd_raison_saut(self.depuis):
            self.lectures_raison += 1
            if self.raison and self.lectures_raison > self.retard_raison:
                return f"démarrage\n{sd.RAISON_SAUT}"
            return "démarrage"
        reponses = {
            "gnome-shell --version": "GNOME Shell 46.0",
            sd.CMD_SANS_REGLE: "" if self.regle else "ok",
            sd.CMD_SANS_VENV: "" if self.venv else "ok",
            sd.CMD_UDEV: "ok" if self.regle else "",
            sd.CMD_VENV: "ok" if self.venv else "",
            sd.CMD_JEUX: "ok" if self.jeux else "",
            sd.CMD_LIEN: "ok" if self.lien else "",
            sd.CMD_SANS_LIEN: "" if self.lien else "ok",
            sd.CMD_ENABLED: (
                f"['{sd.UUID_EXTENSION}']" if self.uuid else "@as []"
            ),
            sd.CMD_MTIMES: "dates du deck",
            sd.CMD_MTIME_LIEN: "date du lien",
            sd.CMD_UNITE: "ok" if self.service else "",
            sd.CMD_AUTOSTART: "enabled" if self.autostart else "disabled",
            sd.CMD_CONDITION: f"Depuis={self.depuis}\n"
            + (
                f"ActiveState=inactive\nResult={self.resultat}\n"
                "ExecMainStartTimestampMonotonic=0"
                if self.condition
                else "ActiveState=failed\nResult=exit-code\n"
                "ExecMainStartTimestampMonotonic=123456"
            ),
            sd.CMD_SANS_SERVICE: "" if self.service else "ok",
        }
        # Le reste : ListPaths et ListDevices.
        return reponses.get(commande, "('[]',)")

    def attendre_extension(self, cible, delai=0):
        if self.actif:
            return {"state": 1.0, "error": ""}, "({'state': <1.0>},)"
        return {"state": 3.0, "error": "boom"}, "({'state': <3.0>},)"

    def redemarrer(self, cible, log):
        self.redemarrages += 1
        self.__dict__.update(self.apres.get("redemarrage", {}))
        return True


# L'option de l'installateur à l'étape 2.
DECK = sd.OPTION["install-stream-deck"]


class LesCinqEtapes(unittest.TestCase):
    """controler() mène les cinq étapes sur une VM simulée : l'ordre des
    commandes, et le nom que chaque faute laisse au rapport."""

    ENTIER = "[ERPLibreHome] enabled\n"
    ECHEC = (
        "[ERPLibreHome] mount device failed:"
        " No property vertical on StBoxLayout\n"
        "[ERPLibreHome] enabled\n"
    )

    def setUp(self):
        dossier = tempfile.mkdtemp(prefix="sd-etapes-")
        self.addCleanup(shutil.rmtree, dossier, ignore_errors=True)
        self.log = os.path.join(dossier, "systeme.log")

    def _controler(self, vm, extras=False):
        from unittest import mock

        with mock.patch.multiple(
            sd,
            sonder=vm.sonder,
            session_ouverte=lambda cible: (True, "(true,)"),
            attendre_extension=vm.attendre_extension,
            installer=vm.installer,
            redemarrer=vm.redemarrer,
            # La reprise du journal de l'unité, sans attendre.
            PAUSE_RAISON=0,
        ):
            return sd.controler("vm", sd.MATRICE[0], self.log, extras)

    def _journal(self):
        with open(self.log, encoding="utf-8") as fh:
            return fh.read()

    def test_a_sound_vm_passes_the_five_stages_in_order(self):
        vm = VMSimulee([self.ENTIER, self.ENTIER])
        echec, info, gnome = self._controler(vm)
        self.assertIsNone(echec)
        self.assertTrue(sd.est_active(info))
        self.assertEqual(gnome, "46.0")
        self.assertEqual(
            vm.options,
            ["", DECK, DECK, "--uninstall --stream-deck", "--uninstall", ""],
        )
        self.assertEqual((vm.lectures, vm.redemarrages), (2, 1))

    def test_extras_go_with_every_base_install(self):
        vm = VMSimulee([self.ENTIER, self.ENTIER])
        echec, _info, _gnome = self._controler(vm, extras=True)
        self.assertIsNone(echec)
        self.assertEqual(vm.options[0], "--with-extras")
        self.assertEqual(vm.options[-1], "--with-extras")

    def test_a_failed_mount_stops_the_base_stage(self):
        vm = VMSimulee([self.ECHEC])
        echec, info, _gnome = self._controler(vm)
        self.assertEqual(echec, "extension-indicators")
        self.assertTrue(sd.est_active(info))
        self.assertEqual(vm.options, [])
        self.assertIn("indicateurs non montés : device", self._journal())

    def test_an_unread_journal_is_not_a_whole_panel(self):
        """Une lecture vide — ssh tombé, journal vide — ne passe pas pour
        « aucun échec »."""
        echec, _info, _gnome = self._controler(VMSimulee([""]))
        self.assertEqual(echec, "extension-indicators")
        self.assertIn("journal de session sans", self._journal())

    def test_the_base_must_leave_no_rule_nor_venv(self):
        for etat, attendu in (
            ({"regle": True}, "base-no-udev"),
            ({"venv": True}, "base-no-venv"),
        ):
            with self.subTest(attendu=attendu):
                vm = VMSimulee([self.ENTIER], **etat)
                self.assertEqual(self._controler(vm)[0], attendu)

    def test_a_failed_command_names_its_stage(self):
        for option, attendu in (
            ("", "base-idempotent"),
            (DECK, "install-stream-deck"),
            ("--uninstall --stream-deck", "uninstall-stream-deck"),
            ("--uninstall", "uninstall"),
        ):
            with self.subTest(attendu=attendu):
                vm = VMSimulee([self.ENTIER], echoue={option})
                self.assertEqual(self._controler(vm)[0], attendu)
                self.assertEqual(vm.options[-1], option)

    def test_the_stream_deck_stage_checks_rule_venv_service_extension(self):
        for apres, attendu in (
            ({"regle": False}, "udev"),
            ({"venv": False}, "venv"),
            ({"jeux": False}, "games"),
            ({"service": False}, "service-unit"),
            ({"autostart": False}, "service-enabled"),
            ({"condition": False}, "service-condition"),
            ({"raison": False}, "service-condition"),
            ({"resultat": "failed"}, "service-condition"),
            ({"resultat": "exit-code"}, "service-condition"),
            ({"actif": False}, "stream-deck-active"),
        ):
            with self.subTest(attendu=attendu):
                vm = VMSimulee([self.ENTIER], apres={DECK: apres})
                self.assertEqual(self._controler(vm)[0], attendu)

    def test_a_late_reason_is_reread_a_bounded_number_of_times(self):
        """journald écrit la raison un peu après le retour de systemctl :
        la lecture est reprise, jamais plus de TENTATIVES_RAISON fois, et
        une raison absente jusqu'au bout reste un échec."""
        vm = VMSimulee([self.ENTIER] * 3)
        vm.retard_raison = 1
        self.assertIsNone(self._controler(vm)[0])
        self.assertEqual(vm.lectures_raison, 2)
        vm = VMSimulee([self.ENTIER], apres={DECK: {"raison": False}})
        self.assertEqual(self._controler(vm)[0], "service-condition")
        self.assertEqual(vm.lectures_raison, sd.TENTATIVES_RAISON)

    def test_no_skip_reads_the_unit_journal_once(self):
        vm = VMSimulee([self.ENTIER], apres={DECK: {"condition": False}})
        self.assertEqual(self._controler(vm)[0], "service-condition")
        self.assertEqual(vm.lectures_raison, 1)

    def test_no_start_instant_fails_without_reading_the_journal(self):
        """Sans l'instant noté avant le démarrage, aucune borne : le
        journal n'est pas lu et le contrôle échoue. Une valeur qui n'est
        pas un nombre n'entre pas dans une commande shell."""
        for depuis in ("", "1; touch x", "@1"):
            with self.subTest(depuis=depuis):
                vm = VMSimulee([self.ENTIER])
                vm.depuis = depuis
                self.assertEqual(self._controler(vm)[0], "service-condition")
                self.assertEqual(vm.lectures_raison, 0)

    def test_a_skip_passes_with_either_result_of_systemd(self):
        for resultat in ("exec-condition", "success"):
            with self.subTest(resultat=resultat):
                vm = VMSimulee(
                    [self.ENTIER] * 3, apres={DECK: {"resultat": resultat}}
                )
                self.assertIsNone(self._controler(vm)[0])

    def test_the_partial_uninstall_keeps_the_extension(self):
        for apres, attendu in (
            ({"venv": True}, "partial-uninstall-gone"),
            ({"regle": True}, "partial-uninstall-gone"),
            ({"service": True}, "partial-uninstall-service-gone"),
            ({"lien": False}, "partial-uninstall-kept"),
            ({"uuid": False}, "partial-uninstall-kept"),
            ({"actif": False}, "partial-uninstall-kept"),
        ):
            with self.subTest(apres=apres):
                vm = VMSimulee(
                    [self.ENTIER],
                    apres={"--uninstall --stream-deck": apres},
                )
                self.assertEqual(self._controler(vm)[0], attendu)

    def test_the_uninstall_leaves_nothing(self):
        for apres in ({"uuid": True}, {"lien": True}, {"venv": True}):
            with self.subTest(apres=apres):
                vm = VMSimulee([self.ENTIER], apres={"--uninstall": apres})
                self.assertEqual(self._controler(vm)[0], "uninstall-gone")
        vm = VMSimulee([self.ENTIER], apres={"--uninstall": {"service": True}})
        self.assertEqual(self._controler(vm)[0], "uninstall-service-gone")

    def test_the_reinstall_comes_back_whole_and_without_the_deck(self):
        cas = (
            (VMSimulee([self.ENTIER, self.ECHEC]), "reinstall-indicators"),
            (
                VMSimulee(
                    [self.ENTIER], apres={"redemarrage": {"actif": False}}
                ),
                "reinstall-active",
            ),
            (
                VMSimulee(
                    [self.ENTIER, self.ENTIER], apres={"": {"regle": True}}
                ),
                "reinstall-no-udev",
            ),
        )
        for vm, attendu in cas:
            with self.subTest(attendu=attendu):
                self.assertEqual(self._controler(vm)[0], attendu)
                self.assertEqual(vm.redemarrages, 1)

    def _controles(self):
        """(nom, issue) de chaque ligne « ── contrôle » du journal, dans
        l'ordre."""
        return re.findall(
            r"^── contrôle (\S+) : (\S+)$", self._journal(), re.MULTILINE
        )

    def test_the_log_names_every_check_and_its_command(self):
        """Le journal d'une VM saine prouve chaque contrôle et chaque
        commande d'étape, dans l'ordre d'ETAPES : son nom, son issue, et la
        commande qu'il a lancée. Une réussite n'y recopie pas les
        réponses."""
        vm = VMSimulee([self.ENTIER, self.ENTIER])
        self.assertIsNone(self._controler(vm)[0])
        attendus = []
        for etape in sd.ETAPES:
            if etape["commande"]:
                attendus.append(etape["commande"])
            attendus.extend(etape["controles"])
        self.assertEqual(
            self._controles(), [(nom, "réussi") for nom in attendus]
        )
        journal = self._journal()
        for bloc in journal.split("── contrôle ")[1:]:
            self.assertIn("\n   $ ", bloc, bloc)
        self.assertIn(f"   $ {sd.CMD_SANS_REGLE}\n", journal)
        self.assertIn(f"   $ install_erplibre_home.sh {DECK}\n", journal)
        self.assertNotIn("   → ", journal)

    def test_a_failed_check_leaves_its_raw_reply(self):
        """Le contrôle tombé est le dernier du journal, ÉCHEC, et chaque
        commande qu'il a lancée y est suivie de sa réponse brute."""
        cas = (
            (
                {"apres": {"--uninstall --stream-deck": {"uuid": False}}},
                "partial-uninstall-kept",
                f"   $ {sd.CMD_ENABLED}\n   → @as []\n",
            ),
            (
                {"echoue": {DECK}},
                "install-stream-deck",
                f"   $ install_erplibre_home.sh {DECK}\n"
                "   → code de sortie 1\n",
            ),
            (
                {"apres": {DECK: {"condition": False}}},
                "service-condition",
                f"   $ {sd.CMD_CONDITION}\n   → Depuis={DEPUIS}\n"
                "ActiveState=failed\nResult=exit-code\n"
                "ExecMainStartTimestampMonotonic=123456\n",
            ),
            (
                {"apres": {DECK: {"raison": False}}},
                "service-condition",
                f"   $ {sd.cmd_raison_saut(DEPUIS)}\n   → démarrage\n",
            ),
            (
                {"regle": True},
                "base-no-udev",
                f"   $ {sd.CMD_SANS_REGLE}\n   → (aucune réponse)\n",
            ),
        )
        for options, nom, preuve in cas:
            with self.subTest(nom=nom):
                open(self.log, "w", encoding="utf-8").close()
                vm = VMSimulee([self.ENTIER], **options)
                self.assertEqual(self._controler(vm)[0], nom)
                self.assertEqual(self._controles()[-1], (nom, "ÉCHEC"))
                bloc = self._journal().split(f"── contrôle {nom} : ÉCHEC\n")
                self.assertIn(preuve, bloc[1])

    def test_every_name_it_returns_is_declared(self):
        """Les noms que controler() rend sont ceux d'ETAPES : le rapport et
        la spec parlent la même langue."""
        declares = set()
        for etape in sd.ETAPES:
            declares.update(etape["controles"])
            if etape["commande"]:
                declares.add(etape["commande"])
        source = SRC[SRC.index("def _absents(") : SRC.index("def controler(")]
        rendus = set(re.findall(r'return "([a-z-]+)"', source))
        self.assertEqual(rendus, declares)


class LeReadme(unittest.TestCase):
    def test_the_readme_documents_it_in_both_languages(self):
        """La source est le .base.md ; les deux .md en sont générés."""
        base = (RACINE / "long_test/README.base.md").read_text(
            encoding="utf-8"
        )
        self.assertEqual(base.count("## install_erplibre_home.py"), 2)
        for nom in ("README.md", "README.fr.md"):
            with self.subTest(nom=nom):
                texte = (RACINE / "long_test" / nom).read_text(
                    encoding="utf-8"
                )
                self.assertIn("## install_erplibre_home.py", texte)


if __name__ == "__main__":
    unittest.main()
