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
import json
import os
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

# Le custom.conf que livre le paquet GDM d'une distribution Debian.
GDM_LIVRE = """# GDM configuration storage
[daemon]
# Uncomment the line below to force the login screen to use Xorg
#WaylandEnable=false

# Enabling automatic login
#  AutomaticLoginEnable = true
#  AutomaticLogin = user1

[security]

[debug]
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


class LesEtapes(unittest.TestCase):
    """Les cinq étapes de la spec, dans son ordre, avec ses noms."""

    def test_the_five_stages_in_order(self):
        self.assertEqual(
            [(e["nom"], e["commande"], e["option"]) for e in sd.ETAPES],
            [
                ("base", None, None),
                ("stream-deck", "install-stream-deck", "--stream-deck"),
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
                    "stream-deck-active",
                    "stream-deck-idempotent",
                ],
                ["partial-uninstall-gone", "partial-uninstall-kept"],
                ["uninstall-gone"],
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

    def _jouer(self, famille, contenu=None, fois=1):
        chemin, commande = sd.autologin(famille, "erplibre")
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

    def test_the_keys_go_under_daemon(self):
        texte = self._jouer("debian", GDM_LIVRE)
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


if __name__ == "__main__":
    unittest.main()
