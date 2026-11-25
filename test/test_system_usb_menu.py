#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu Clé USB amorçable : l'entrée [10] du menu Système, la
répartition du sous-menu, la confirmation par le nom retapé, la relecture
de lsblk avant d'écrire, l'arrêt au premier échec, le téléchargement
vérifié et le point d'accroche du constructeur d'ISO.

lsblk est remplacé par des arbres fabriqués (ceux de test_system_usb, aux
valeurs inventées), les commandes passent par un execute factice, et
subprocess.run lève s'il est appelé : un test ne lit aucun disque de la
machine qui le lance et n'écrit sur aucun.
"""

import ast
import json
import os
import shlex
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_usb as su  # noqa: E402
from script.todo import system_usb_menu as um  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from test.test_system_usb import (  # noqa: E402
    cle_montee,
    lsblk,
    noeud,
    nvme_systeme,
)


def setUpModule():
    ancienne = todo_i18n._current_lang
    todo_i18n._current_lang = "fr"
    unittest.addModuleCleanup(setattr, todo_i18n, "_current_lang", ancienne)


class Banc(unittest.TestCase):
    """Un TODO sans __init__, un execute factice, print et input captés,
    lsblk fabriqué, aucun lien by-id lu sur /dev."""

    def setUp(self):
        from script.todo.todo import TODO

        self.TODO = TODO
        self.todo = TODO.__new__(TODO)
        self.todo.execute = mock.Mock()
        self.todo.execute.exec_command_live.return_value = 0
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.iso = os.path.join(self.tmp.name, "image.iso")
        with open(self.iso, "wb") as fh:
            fh.write(b"\0" * 4096)
        self.vus = []
        for patch in (
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: self.vus.append(
                    " ".join(map(str, a))
                ),
            ),
            mock.patch(
                "subprocess.run",
                side_effect=AssertionError("subprocess.run inattendu"),
            ),
            mock.patch("script.todo.todo_telemetry.record", return_value=None),
            mock.patch.object(su, "lien_by_id", return_value=None),
            mock.patch.object(su.shutil, "which", return_value="/bin/eject"),
            mock.patch.object(um, "todo_file_browser", None),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def ecrire(self, lectures, reponses):
        """Lance l'écriture : `lectures` sont les JSON successifs de lsblk,
        `reponses` les saisies dans l'ordre."""
        with (
            mock.patch.object(su, "lire_lsblk", side_effect=list(lectures)),
            mock.patch("builtins.input", side_effect=list(reponses)),
        ):
            return self.todo._system_usb_ecrire()

    def reponses(self, nom="sdb", oui="o", numero="1"):
        # Parcourir (sans urwid : chemin tapé), la clé, son nom, le oui.
        return ["1", self.iso, numero, nom, oui]

    def lances(self):
        return [
            c.args[0]
            for c in self.todo.execute.exec_command_live.call_args_list
        ]

    def texte(self):
        return "\n".join(self.vus)


class TestLaNavigation(Banc):
    def test_entry_10_opens_the_usb_key_menu(self):
        with (
            mock.patch.object(self.TODO, "_system_usb") as usb,
            mock.patch("click.prompt", side_effect=["10", "0"]),
        ):
            self.todo.prompt_execute_system()
        usb.assert_called_once_with()

    def test_the_system_menu_lists_the_usb_key_tenth(self):
        with mock.patch("click.prompt", side_effect=["0"]) as invite:
            self.todo.prompt_execute_system()
        self.assertIn("[10] 🔌 Clé USB amorçable", invite.call_args.args[0])

    def test_each_submenu_entry_calls_its_action(self):
        attendus = {
            "1": "_system_usb_detecter",
            "2": "_system_usb_ecrire",
            "3": "_system_usb_construire_iso",
            "4": "_system_usb_catalogue",
            "5": "_system_usb_profils",
        }
        for touche, methode in attendus.items():
            with (
                self.subTest(touche=touche),
                mock.patch.object(self.TODO, methode) as action,
                mock.patch("click.prompt", side_effect=[touche, "0"]),
            ):
                self.assertFalse(self.todo._system_usb())
            action.assert_called_once_with()

    def test_the_breadcrumb_names_the_usb_key(self):
        with mock.patch("click.prompt", side_effect=["0"]) as invite:
            self.todo._system_usb()
        self.assertIn("Bootable USB key", invite.call_args.args[0])
        self.assertIn("_system_usb", self.TODO._MENU_LABELS)

    def test_each_profile_entry_calls_its_action(self):
        attendus = {
            "1": "_system_usb_profils_lister",
            "2": "_system_usb_profil_dupliquer",
            "3": "_system_usb_profil_editer",
            "4": "_system_usb_profil_supprimer",
            "5": "_system_usb_profil_apercu",
            "6": "_system_usb_profil_resume",
        }
        for touche, methode in attendus.items():
            with (
                self.subTest(touche=touche),
                mock.patch.object(self.TODO, methode) as action,
                mock.patch("click.prompt", side_effect=[touche, "0"]),
            ):
                self.assertFalse(self.todo._system_usb_profils())
            action.assert_called_once_with()
        with mock.patch("click.prompt", side_effect=["0"]) as invite:
            self.todo._system_usb_profils()
        self.assertIn("Machine profiles", invite.call_args.args[0])
        self.assertEqual(
            self.TODO._MENU_LABELS["_system_usb_profils"], "Machine profiles"
        )


class TestLesTraductions(unittest.TestCase):
    def test_every_message_is_translated(self):
        with open(um.__file__, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        cles = [
            n.args[0].value
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and getattr(n.func, "id", None) == "t"
            and n.args
            and isinstance(n.args[0], ast.Constant)
        ]
        cles += list(um.RAISONS_USB.values()) + list(um.ALERTES_USB.values())
        for e in su.catalogue("/chemin/inexistant"):
            cles.append(e["libelle_key"])
            if e["raison_key"]:
                cles.append(e["raison_key"])
        cles.append("Bootable USB key")
        cles.append("Machine profiles")
        cles += list(um.RAISONS_PROFIL.values())
        cles += list(um.ALERTES_PROFIL.values())
        cles += list(um.JETONS_PROFIL.values()) + list(um.ORIGINES_PROFIL)
        cles += list(um.mp.SUMMARY_LABELS)
        manquantes = sorted(
            {c for c in cles if c not in todo_i18n.TRANSLATIONS}
        )
        self.assertEqual(manquantes, [])

    def test_every_refusal_code_has_a_sentence(self):
        with open(su.__file__, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        codes = set()
        for n in ast.walk(arbre):
            if (
                isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "_refus"
                and isinstance(n.args[0], ast.Constant)
            ):
                codes.add(n.args[0].value)
            # refus_ecriture rend (code, détails).
            if (
                isinstance(n, ast.Return)
                and isinstance(n.value, ast.Tuple)
                and isinstance(n.value.elts[0], ast.Constant)
            ):
                codes.add(n.value.elts[0].value)
        self.assertGreaterEqual(len(codes), 8)
        self.assertEqual(codes - set(um.RAISONS_USB), set())

    def test_every_profile_code_has_a_sentence(self):
        """Chaque code que machine_profile rend — tuple (code, {...}) de
        validate, ProfileError(code), {"code": ...} de resolve — a sa
        phrase."""
        with open(um.mp.__file__, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        codes, alertes = set(), set()
        for n in ast.walk(arbre):
            if (
                isinstance(n, ast.Tuple)
                and len(n.elts) == 2
                and isinstance(n.elts[0], ast.Constant)
                and isinstance(n.elts[0].value, str)
                and isinstance(n.elts[1], ast.Dict)
            ):
                codes.add(n.elts[0].value)
            if (
                isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "ProfileError"
            ):
                codes.add(n.args[0].value)
            if isinstance(n, ast.Dict):
                for k, v in zip(n.keys, n.values):
                    if (
                        isinstance(k, ast.Constant)
                        and k.value == "code"
                        and isinstance(v, ast.Constant)
                    ):
                        alertes.add(v.value)
        # Les codes rendus par les vérificateurs, sous forme de variable.
        for n in ast.walk(arbre):
            if (
                isinstance(n, ast.Call)
                and getattr(n.func, "id", None) == "_pattern"
                and isinstance(n.args[1], ast.Constant)
            ):
                codes.add(n.args[1].value)
        self.assertGreaterEqual(len(codes), 20)
        self.assertEqual(codes - set(um.RAISONS_PROFIL), set())
        self.assertGreaterEqual(len(alertes), 6)
        self.assertEqual(alertes - set(um.ALERTES_PROFIL), set())

    def test_a_refusal_reads_its_sizes(self):
        res = {
            "reason": "too-small",
            "details": {
                "device": "/dev/sdb",
                "size": su.GIO,
                "iso_size": 2 * su.GIO,
            },
        }
        phrase = um.message_refus(res)
        self.assertIn("/dev/sdb", phrase)
        self.assertIn("1.0 Gio", phrase)
        self.assertIn("2.0 Gio", phrase)


class TestLaDetection(Banc):
    def test_keys_are_listed_with_their_partitions(self):
        with mock.patch.object(
            su, "lire_lsblk", return_value=lsblk(nvme_systeme(), cle_montee())
        ):
            cles = self.todo._system_usb_detecter()
        self.assertEqual([c["nom"] for c in cles], ["sdb"])
        texte = self.texte()
        self.assertIn("Kestrel DataTwig 64", texte)
        self.assertIn("KT0042FAKE0001", texte)
        self.assertIn("/dev/sdb2  TWIGB  ext4", texte)
        self.assertIn("/mnt/exemple-b", texte)
        self.assertIn("Disques système exclus : 1", texte)

    def test_no_key_says_so(self):
        with mock.patch.object(
            su, "lire_lsblk", return_value=lsblk(nvme_systeme())
        ):
            self.assertEqual(self.todo._system_usb_detecter(), [])
        self.assertIn("Aucune clé USB détectée", self.texte())

    def test_lsblk_missing_says_so(self):
        with mock.patch.object(su, "lire_lsblk", return_value=None):
            self.assertEqual(self.todo._system_usb_detecter(), [])
        self.assertIn("lsblk", self.texte())


class TestLEcriture(Banc):
    def donnees(self):
        return lsblk(nvme_systeme(), cle_montee())

    def test_the_full_plan_runs_after_the_name_and_the_yes(self):
        self.assertTrue(
            self.ecrire([self.donnees(), self.donnees()], self.reponses())
        )
        self.assertEqual(
            self.lances(),
            [
                "sudo umount -A /dev/sdb1",
                "sudo umount -A /dev/sdb2",
                "sudo wipefs --all /dev/sdb",
                f"sudo dd if={self.iso} of=/dev/sdb bs=4M conv=fsync "
                "oflag=direct status=progress",
                "sync",
                f"sudo cmp -n 4096 {self.iso} /dev/sdb",
                "sudo eject /dev/sdb",
            ],
        )
        for appel in self.todo.execute.exec_command_live.call_args_list:
            self.assertEqual(appel.kwargs, {"source_erplibre": False})
        self.assertIn("TOUTES LES DONNÉES de /dev/sdb", self.texte())
        self.assertIn("La clé est prête", self.texte())

    def test_a_wrong_name_writes_nothing(self):
        for nom in ("sda", "/dev/sdb", "", "SDB"):
            with self.subTest(nom=nom):
                self.assertFalse(
                    self.ecrire([self.donnees()], ["1", self.iso, "1", nom])
                )
                self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("Rien à faire.", self.texte())

    def test_no_yes_writes_nothing(self):
        self.assertFalse(self.ecrire([self.donnees()], self.reponses(oui="")))
        self.todo.execute.exec_command_live.assert_not_called()

    def test_the_key_number_has_no_default(self):
        reponses = ["1", self.iso, "", "9", "1", "sdb", "o"]
        self.assertTrue(
            self.ecrire([self.donnees(), self.donnees()], reponses)
        )
        self.assertEqual(
            self.texte().count("Choisissez un numéro de la liste."), 2
        )

    def test_zero_cancels_the_key_choice(self):
        self.assertFalse(self.ecrire([self.donnees()], ["1", self.iso, "0"]))
        self.todo.execute.exec_command_live.assert_not_called()

    def test_a_swapped_key_aborts_before_writing(self):
        autre = lsblk(nvme_systeme(), cle_montee(serial="KT0042FAKE0002"))
        self.assertFalse(self.ecrire([self.donnees(), autre], self.reponses()))
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("La clé a changé depuis la confirmation", self.texte())

    def test_an_unplugged_key_aborts_before_writing(self):
        partie = lsblk(nvme_systeme())
        self.assertFalse(
            self.ecrire([self.donnees(), partie], self.reponses())
        )
        self.todo.execute.exec_command_live.assert_not_called()

    def relu_aborte(self, relu):
        self.assertFalse(self.ecrire([self.donnees(), relu], self.reponses()))
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("La clé a changé depuis la confirmation", self.texte())

    def test_a_whole_disk_mount_aborts_before_writing(self):
        relu = self.donnees()
        relu["blockdevices"][1]["mountpoints"] = ["/mnt/exemple-d"]
        self.relu_aborte(relu)

    def test_a_newly_mounted_partition_aborts_before_writing(self):
        avant = lsblk(nvme_systeme(), cle_montee())
        avant["blockdevices"][1]["children"][1]["mountpoints"] = [None]
        relu = lsblk(nvme_systeme(), cle_montee())
        with (
            mock.patch.object(su, "lire_lsblk", side_effect=[avant, relu]),
            mock.patch("builtins.input", side_effect=self.reponses()),
        ):
            self.assertFalse(self.todo._system_usb_ecrire())
        self.todo.execute.exec_command_live.assert_not_called()

    def test_an_extra_mount_on_a_mounted_partition_aborts(self):
        relu = self.donnees()
        relu["blockdevices"][1]["children"][1]["mountpoints"] = [
            "/mnt/exemple-b",
            "/mnt/exemple-c",
        ]
        self.relu_aborte(relu)

    def test_a_new_mapping_aborts_before_writing(self):
        relu = self.donnees()
        relu["blockdevices"][1]["children"][0]["children"] = [
            noeud("luks-cle", "crypt")
        ]
        self.relu_aborte(relu)

    def test_lsblk_silent_at_the_reread_aborts(self):
        self.relu_aborte(None)

    def test_a_luks_on_the_whole_key_is_refused(self):
        cle = cle_montee()
        cle["children"] = [
            noeud("luks-abc", "crypt", montages=["/mnt/exemple"], pkname="sdb")
        ]
        self.assertFalse(
            self.ecrire([lsblk(nvme_systeme(), cle)], self.reponses())
        )
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("/dev/mapper/luks-abc", self.texte())

    def test_a_failing_step_stops_the_rest(self):
        self.todo.execute.exec_command_live.side_effect = [0, 0, 0, 1]
        self.assertFalse(
            self.ecrire([self.donnees(), self.donnees()], self.reponses())
        )
        self.assertEqual(len(self.lances()), 4)
        texte = self.texte()
        self.assertIn(todo_i18n.t("Command failed:"), texte)
        self.assertIn(todo_i18n.t("Not run:"), texte)
        self.assertIn("    sync", texte)
        self.assertNotIn("La clé est prête", texte)

    def test_ctrl_c_stops_the_rest(self):
        self.todo.execute.exec_command_live.side_effect = [
            0,
            0,
            0,
            KeyboardInterrupt,
        ]
        self.assertFalse(
            self.ecrire([self.donnees(), self.donnees()], self.reponses())
        )
        self.assertEqual(len(self.lances()), 4)
        self.assertIn(todo_i18n.t("Interrupted at:"), self.texte())

    def test_a_refused_key_prints_why(self):
        petit = lsblk(nvme_systeme(), cle_montee())
        with open(self.iso, "wb") as fh:
            fh.truncate(65 * su.GIO)
        self.assertFalse(self.ecrire([petit], self.reponses()))
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("plus petit que l'image", self.texte())

    def test_a_missing_or_empty_file_stops_early(self):
        with mock.patch.object(su, "lire_lsblk") as lecture:
            with mock.patch(
                "builtins.input", side_effect=["1", "/chemin/inexistant.iso"]
            ):
                self.assertFalse(self.todo._system_usb_ecrire())
            vide = os.path.join(self.tmp.name, "vide.iso")
            open(vide, "w").close()
            with mock.patch("builtins.input", side_effect=["1", vide]):
                self.assertFalse(self.todo._system_usb_ecrire())
        lecture.assert_not_called()
        self.assertIn("Le fichier est vide", self.texte())

    def test_an_unknown_extension_only_warns(self):
        autre = os.path.join(self.tmp.name, "image.bin")
        os.rename(self.iso, autre)
        self.iso = autre
        self.assertTrue(
            self.ecrire([self.donnees(), self.donnees()], self.reponses())
        )
        self.assertIn("ne finit ni par .iso ni par .img", self.texte())

    def test_the_file_browser_choice_is_used(self):
        choisi = self.iso

        class Navigateur:
            def __init__(self, depart, rappel):
                self.rappel = rappel

            def run_main_frame(self):
                self.rappel(choisi)

        navigateur = mock.Mock(FileBrowser=Navigateur)
        with mock.patch.object(um, "todo_file_browser", navigateur):
            self.assertTrue(
                self.ecrire(
                    [self.donnees(), self.donnees()], ["1", "1", "sdb", "o"]
                )
            )
        self.assertIn(f"if={self.iso}", self.lances()[3])

    def test_leaving_the_file_browser_falls_back_to_a_typed_path(self):
        class Navigateur:
            def __init__(self, depart, rappel):
                pass

            def run_main_frame(self):
                pass

        navigateur = mock.Mock(FileBrowser=Navigateur)
        with mock.patch.object(um, "todo_file_browser", navigateur):
            self.assertTrue(
                self.ecrire(
                    [self.donnees(), self.donnees()],
                    ["1", self.iso, "1", "sdb", "o"],
                )
            )
        self.assertIn(f"if={self.iso}", self.lances()[3])


class TestLeCatalogue(Banc):
    def setUp(self):
        super().setUp()
        patch = mock.patch.object(su, "ISO_DIR", self.tmp.name)
        patch.start()
        self.addCleanup(patch.stop)

    def test_the_list_shows_reasons(self):
        self.todo._system_usb_catalogue()
        texte = self.texte()
        self.assertIn("✗ ERPLibre Arch Linux GNOME (amd64)", texte)
        self.assertIn("Pas encore construite", texte)
        self.assertIn("✓ Arch Linux officielle (amd64)", texte)
        self.assertIn("✗ ERPLibre Arch Linux (s390x)", texte)
        self.assertIn(su.URL_ARCH, texte)

    def test_an_unavailable_entry_is_not_selectable(self):
        with mock.patch("builtins.input", side_effect=["4"]):
            self.assertIsNone(self.todo._system_usb_iso_catalogue())
        self.todo.execute.exec_command_live.assert_not_called()

    def test_a_built_iso_is_selectable(self):
        construite = os.path.join(
            self.tmp.name, "erplibre-archlinux-2026.01.01-x86_64.iso"
        )
        open(construite, "w").close()
        with mock.patch("builtins.input", side_effect=["1"]):
            self.assertEqual(self.todo._system_usb_iso_catalogue(), construite)

    def curl_factice(self, contenu):
        """Un execute qui fait ce que curl ferait : écrire le fichier de
        -o avec le contenu prévu pour son URL."""
        somme = su.hashlib.sha256(b"image juste").hexdigest()
        corps = {
            su.URL_ARCH_SOMMES: f"{somme}  {su.FICHIER_ARCH}\n".encode(),
            su.URL_ARCH: contenu,
        }

        def executer(cmd, source_erplibre=True):
            args = cmd.split()
            sortie = args[args.index("-o") + 1]
            with open(sortie, "wb") as fh:
                fh.write(corps[args[-1]])
            return 0

        return executer

    def test_a_good_download_is_renamed(self):
        self.todo.execute.exec_command_live.side_effect = self.curl_factice(
            b"image juste"
        )
        with mock.patch("builtins.input", side_effect=["2", "o"]):
            chemin = self.todo._system_usb_iso_catalogue()
        self.assertEqual(chemin, os.path.join(self.tmp.name, su.FICHIER_ARCH))
        with open(chemin, "rb") as fh:
            self.assertEqual(fh.read(), b"image juste")
        self.assertFalse(os.path.exists(chemin + ".part"))

    def test_a_bad_checksum_deletes_the_partial_file(self):
        self.todo.execute.exec_command_live.side_effect = self.curl_factice(
            b"image fausse"
        )
        with mock.patch("builtins.input", side_effect=["2", "o"]):
            self.assertIsNone(self.todo._system_usb_iso_catalogue())
        chemin = os.path.join(self.tmp.name, su.FICHIER_ARCH)
        self.assertFalse(os.path.exists(chemin))
        self.assertFalse(os.path.exists(chemin + ".part"))
        self.assertIn("ne correspond pas", self.texte())

    def test_a_failed_checksum_list_download_stops(self):
        self.todo.execute.exec_command_live.return_value = 22
        with mock.patch("builtins.input", side_effect=["2", "o"]):
            self.assertIsNone(self.todo._system_usb_iso_catalogue())
        self.assertEqual(len(self.lances()), 1)
        chemin = os.path.join(self.tmp.name, su.FICHIER_ARCH)
        self.assertFalse(os.path.exists(chemin))

    def test_a_checksum_list_without_the_file_stops(self):
        def executer(cmd, source_erplibre=True):
            args = cmd.split()
            with open(args[args.index("-o") + 1], "w") as fh:
                fh.write(f"{'0' * 64}  autre-image.iso\n")
            return 0

        self.todo.execute.exec_command_live.side_effect = executer
        with mock.patch("builtins.input", side_effect=["2", "o"]):
            self.assertIsNone(self.todo._system_usb_iso_catalogue())
        self.assertEqual(len(self.lances()), 1)
        self.assertIn(
            f"La liste des sommes n'a aucune ligne pour {su.FICHIER_ARCH}.",
            self.texte(),
        )

    def test_a_failed_image_download_keeps_the_partial_file(self):
        executer = self.curl_factice(b"image ent")

        def echec_image(cmd, source_erplibre=True):
            executer(cmd, source_erplibre)
            return 0 if su.URL_ARCH_SOMMES in cmd else 18

        self.todo.execute.exec_command_live.side_effect = echec_image
        with mock.patch("builtins.input", side_effect=["2", "o"]):
            self.assertIsNone(self.todo._system_usb_iso_catalogue())
        chemin = os.path.join(self.tmp.name, su.FICHIER_ARCH)
        self.assertFalse(os.path.exists(chemin))
        self.assertTrue(os.path.exists(chemin + ".part"))

    def test_an_already_verified_image_is_not_downloaded_again(self):
        with open(os.path.join(self.tmp.name, su.FICHIER_ARCH), "wb") as fh:
            fh.write(b"image juste")
        self.todo.execute.exec_command_live.side_effect = self.curl_factice(
            b"jamais"
        )
        with mock.patch("builtins.input", side_effect=["2", "o"]):
            self.assertIsNotNone(self.todo._system_usb_iso_catalogue())
        self.assertEqual(len(self.lances()), 1)

    def test_no_yes_downloads_nothing(self):
        with mock.patch("builtins.input", side_effect=["2", ""]):
            self.assertIsNone(self.todo._system_usb_iso_catalogue())
        self.todo.execute.exec_command_live.assert_not_called()


class TestLaConstruction(Banc):
    def test_without_the_builder_nothing_runs(self):
        with mock.patch.object(su, "RACINE_DEPOT", self.tmp.name):
            self.assertFalse(self.todo._system_usb_construire_iso())
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("pas encore disponible", self.texte())

    def test_the_builder_runs_with_the_tools_python(self):
        script = os.path.join(self.tmp.name, su.SCRIPT_CONSTRUCTION)
        os.makedirs(os.path.dirname(script))
        open(script, "w").close()
        python = os.path.join(self.tmp.name, ".venv.erplibre", "bin", "python")
        os.makedirs(os.path.dirname(python))
        open(python, "w").close()
        os.chmod(python, 0o755)
        with mock.patch.object(su, "RACINE_DEPOT", self.tmp.name):
            self.assertTrue(self.todo._system_usb_construire_iso())
        self.assertEqual(
            self.lances(),
            [".venv.erplibre/bin/python script/iso/archlinux/build_iso.py"],
        )

    def test_without_tools_venv_the_running_python_builds(self):
        # Le TODO de la clé ERPLibre : un checkout sans venv d'outillage.
        script = os.path.join(self.tmp.name, su.SCRIPT_CONSTRUCTION)
        os.makedirs(os.path.dirname(script))
        open(script, "w").close()
        with (
            mock.patch.object(su, "RACINE_DEPOT", self.tmp.name),
            mock.patch.object(sys, "executable", "/usr/bin/python3"),
        ):
            self.assertTrue(self.todo._system_usb_construire_iso())
        self.assertEqual(
            self.lances(),
            ["/usr/bin/python3 script/iso/archlinux/build_iso.py"],
        )


class BancProfils(Banc):
    """Le dossier privé des profils et celui des ISO dérivées dans un
    dossier temporaire ; les profils du dépôt sont les vrais."""

    def setUp(self):
        super().setUp()
        self.prive = os.path.join(self.tmp.name, "private", "iso", "machine")
        self.derives = os.path.join(self.tmp.name, "derived")
        for patch in (
            mock.patch.object(su, "DOSSIER_PROFILS_PRIVES", self.prive),
            mock.patch.object(
                su, "dossier_derives", return_value=self.derives
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def prive_ecrire(self, nom, donnees):
        os.makedirs(self.prive, exist_ok=True)
        chemin = os.path.join(self.prive, nom + ".json")
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(donnees, fh)
        return chemin

    def prive_lire(self, nom):
        with open(os.path.join(self.prive, nom + ".json")) as fh:
            return json.load(fh)

    def numero(self, nom):
        """Le numéro du profil `nom` dans la liste complète."""
        noms = [e["name"] for e in um.mp.list_profiles(su.dossiers_profils())]
        return str(noms.index(nom) + 1)

    def lancer(self, methode, reponses):
        with mock.patch("builtins.input", side_effect=list(reponses)):
            return getattr(self.todo, methode)()


class TestLesProfilsMachine(BancProfils):
    def test_the_list_shows_origin_and_errors(self):
        self.prive_ecrire(
            "poste-quillon",
            {
                "name": "poste-quillon",
                "extends": "generic",
                "boot": {"timeout": -2},
            },
        )
        self.lancer("_system_usb_profils_lister", [])
        texte = self.texte()
        self.assertIn("✓ generic  (dépôt)", texte)
        self.assertIn("✓ workstation-luks  (dépôt)", texte)
        self.assertIn("✗ poste-quillon  (privé)", texte)
        self.assertIn("boot.timeout : -2 est sous le minimum (0).", texte)

    def test_duplicate_writes_a_0600_private_copy(self):
        chemin = self.lancer(
            "_system_usb_profil_dupliquer",
            [self.numero("workstation-luks"), "Poste Quillon"],
        )
        self.assertEqual(
            chemin, os.path.join(self.prive, "poste-quillon.json")
        )
        self.assertEqual(os.stat(chemin).st_mode & 0o777, 0o600)
        copie = self.prive_lire("poste-quillon")
        self.assertEqual(copie["name"], "poste-quillon")
        self.assertEqual(copie["extends"], "generic")
        self.assertEqual(copie["disk"]["layout"], "lvm_on_luks")

    def test_duplicate_refuses_a_taken_name(self):
        self.assertIsNone(
            self.lancer(
                "_system_usb_profil_dupliquer",
                [self.numero("generic"), "workstation-luks"],
            )
        )
        self.assertFalse(os.path.exists(self.prive))
        self.assertIn("existe déjà", self.texte())

    def test_edit_section_by_section(self):
        self.prive_ecrire(
            "poste-quillon",
            {"schema": 1, "name": "poste-quillon", "extends": "generic"},
        )
        section = str(um.mp.SECTIONS.index("user") + 1)
        # Profil, section « user », name refusé (réservé) puis accepté,
        # shell et sudo gardés par Entrée, fin.
        chemin = self.lancer(
            "_system_usb_profil_editer",
            ["1", section, "root", "quillon", "", "", "0"],
        )
        self.assertEqual(
            chemin, os.path.join(self.prive, "poste-quillon.json")
        )
        profil = self.prive_lire("poste-quillon")
        self.assertEqual(profil["user"], {"name": "quillon"})
        self.assertEqual(os.stat(chemin).st_mode & 0o777, 0o600)
        self.assertIn("réserve", self.texte())

    def test_edit_rewrites_the_opened_file_in_place(self):
        # Un fichier posé à la main dont le nom ne suit pas « name ».
        self.prive_ecrire(
            "boite",
            {"schema": 1, "name": "poste-quillon", "extends": "generic"},
        )
        section = str(um.mp.SECTIONS.index("user") + 1)
        chemin = self.lancer(
            "_system_usb_profil_editer",
            ["1", section, "quillon", "", "", "0"],
        )
        self.assertEqual(chemin, os.path.join(self.prive, "boite.json"))
        self.assertEqual(os.listdir(self.prive), ["boite.json"])
        self.assertEqual(self.prive_lire("boite")["user"], {"name": "quillon"})

    def test_summary_translates_the_optional_secret_volume(self):
        self.prive_ecrire(
            "poste-quillon",
            {
                "schema": 1,
                "name": "poste-quillon",
                "extends": "workstation-luks",
            },
        )
        self.lancer(
            "_system_usb_profil_resume", [self.numero("poste-quillon")]
        )
        self.assertIn("8 GiB, demandé pendant l'installation", self.texte())

    def test_edit_accepts_auto_and_ask_only_where_allowed(self):
        self.prive_ecrire("poste-quillon", {"name": "poste-quillon"})
        section = str(um.mp.SECTIONS.index("boot") + 1)
        # loader auto (permis), timeout « ask » refusé puis 5, editor « peut-être »
        # illisible puis non, uki et hibernation gardés.
        self.lancer(
            "_system_usb_profil_editer",
            [
                "1",
                section,
                "auto",
                "ask",
                "5",
                "peut-être",
                "non",
                "",
                "",
                "0",
            ],
        )
        profil = self.prive_lire("poste-quillon")
        self.assertEqual(
            profil["boot"], {"loader": "auto", "timeout": 5, "editor": False}
        )
        self.assertIn("n'est pas accepté pour ce champ", self.texte())
        self.assertIn("Valeur invalide pour boot.editor", self.texte())

    def test_edit_lists_only_private_profiles(self):
        self.assertIsNone(self.lancer("_system_usb_profil_editer", []))
        self.assertIn("Aucun profil privé", self.texte())

    def test_a_secret_in_a_private_file_is_never_saved_back(self):
        self.prive_ecrire(
            "poste-quillon",
            {"name": "poste-quillon", "user": {"password_hash": "$6$x$y"}},
        )
        section = str(um.mp.SECTIONS.index("user") + 1)
        self.assertIsNone(
            self.lancer(
                "_system_usb_profil_editer",
                ["1", section, "quillon", "", "", "0"],
            )
        )
        self.assertIn("Non enregistré", self.texte())
        self.assertIn("ne contient jamais de mot de passe", self.texte())
        self.assertNotIn("name", self.prive_lire("poste-quillon")["user"])

    def test_delete_needs_the_name(self):
        chemin = self.prive_ecrire("poste-quillon", {"name": "poste-quillon"})
        self.assertFalse(
            self.lancer("_system_usb_profil_supprimer", ["1", "poste"])
        )
        self.assertTrue(os.path.exists(chemin))
        self.assertTrue(
            self.lancer("_system_usb_profil_supprimer", ["1", "poste-quillon"])
        )
        self.assertFalse(os.path.exists(chemin))

    def test_preview_is_labelled_host_not_target(self):
        from test.test_iso_machine_profile import portable_uefi_amd

        with (
            mock.patch.object(um.mf, "snapshot", return_value={}) as releve,
            mock.patch.object(
                um.mf, "facts_from", return_value=portable_uefi_amd()
            ),
        ):
            self.lancer(
                "_system_usb_profil_apercu", [self.numero("workstation-luks")]
            )
        releve.assert_called_once_with()
        texte = self.texte()
        self.assertIn("Cet ordinateur (l'hôte, pas la cible)", texte)
        self.assertIn("Disque cible : /dev/nvme0n1 (953 GiB)", texte)
        self.assertIn("Taille de secteur LUKS : 4096", texte)
        self.assertIn("Demandé pendant l'installation :", texte)

    def test_summary_shows_auto_and_ask_as_words(self):
        self.lancer("_system_usb_profil_resume", [self.numero("generic")])
        texte = self.texte()
        self.assertIn("Disque cible : détecté pendant l'installation", texte)
        self.assertIn("Utilisateur : demandé pendant l'installation", texte)


class TestLEcritureAvecProfil(BancProfils):
    def setUp(self):
        super().setUp()
        self.base = os.path.join(
            self.tmp.name, "erplibre-archlinux-2099.01.02-x86_64.iso"
        )
        with open(self.base, "wb") as fh:
            fh.write(b"\1" * 4096)
        self.volume = mock.patch.object(
            su, "lire_volume_date", return_value="2099010203040500"
        )
        self.volume.start()
        self.addCleanup(self.volume.stop)
        self.todo.execute.exec_command_live.side_effect = self.xorriso_factice

    def xorriso_factice(self, cmd, source_erplibre=True):
        """Fait ce que xorriso ferait : -outdev reçoit la base suivie du
        profil de -map."""
        args = shlex.split(cmd)
        if args[0] == "xorriso":
            with open(args[args.index("-indev") + 1], "rb") as fh:
                contenu = fh.read()
            with open(args[args.index("-map") + 1], "rb") as fh:
                contenu += fh.read()
            with open(args[args.index("-outdev") + 1], "wb") as fh:
                fh.write(contenu)
        return 0

    def ecrire_avec(self, choix_profil, *suite):
        reponses = ["1", self.base, choix_profil, *suite]
        return self.ecrire([lsblk(nvme_systeme(), cle_montee())] * 2, reponses)

    def test_profile_zero_keeps_the_old_write_path(self):
        for choix in ("0", ""):
            with self.subTest(choix=choix):
                self.todo.execute.exec_command_live.reset_mock()
                self.assertTrue(self.ecrire_avec(choix, "1", "sdb", "o"))
                lances = self.lances()
                self.assertEqual(lances[0], "sudo umount -A /dev/sdb1")
                self.assertIn(
                    f"sudo dd if={self.base} of=/dev/sdb bs=4M conv=fsync "
                    "oflag=direct status=progress",
                    lances,
                )
                self.assertFalse(any("xorriso" in c for c in lances))
        self.assertFalse(os.path.exists(self.derives))

    def test_a_non_erplibre_iso_is_not_asked_a_profile(self):
        self.assertTrue(
            self.ecrire(
                [lsblk(nvme_systeme(), cle_montee())] * 2, self.reponses()
            )
        )
        self.assertNotIn("Profil machine :", self.texte())

    def test_a_profile_builds_a_derived_iso_then_writes_it(self):
        self.assertTrue(
            self.ecrire_avec(self.numero("generic"), "o", "1", "sdb", "o")
        )
        profil = um.mp.effective(
            um.mp.load(os.path.join(um.mp.REPO_DIR, "generic.json")),
            su.dossiers_profils(),
        )
        texte = um.mp.dump(profil)
        derive = su.chemin_derive(
            self.derives,
            su.sha256_fichier(self.base),
            su.sha256_texte(texte),
        )
        json_profil = derive[:-4] + ".json"
        lances = self.lances()
        self.assertEqual(
            lances[0],
            shlex.join(
                [
                    "xorriso",
                    "-indev",
                    self.base,
                    "-outdev",
                    derive,
                    "-boot_image",
                    "any",
                    "replay",
                    "-boot_image",
                    "any",
                    "gpt_disk_guid=volume_date_uuid",
                    "-volume_date",
                    "uuid",
                    "2099010203040500",
                    "-map",
                    json_profil,
                    "/erplibre/machine.json",
                    "-commit",
                ]
            ),
        )
        taille = os.path.getsize(derive)
        self.assertIn(
            f"sudo dd if={derive} of=/dev/sdb bs=4M conv=fsync "
            "oflag=direct status=progress",
            lances,
        )
        self.assertIn(f"sudo cmp -n {taille} {derive} /dev/sdb", lances)
        for chemin in (derive, su.chemin_somme(derive)):
            self.assertEqual(os.stat(chemin).st_mode & 0o777, 0o600, chemin)
        self.assertEqual(os.stat(self.derives).st_mode & 0o777, 0o700)
        # Le JSON n'a servi qu'à xorriso : l'ISO le porte, il est retiré.
        self.assertFalse(os.path.exists(json_profil))
        with open(derive, "rb") as fh:
            self.assertTrue(fh.read().endswith(texte.encode("utf-8")))
        self.assertNotRegex(texte, "(?i)pass|hash")
        self.assertIn(
            "Les mots de passe et les phrases secrètes LUKS", self.texte()
        )
        # Une seconde écriture reprend l'ISO dérivée sans relancer xorriso.
        self.todo.execute.exec_command_live.reset_mock()
        self.assertTrue(
            self.ecrire_avec(self.numero("generic"), "1", "sdb", "o")
        )
        self.assertFalse(any("xorriso" in c for c in self.lances()))
        self.assertIn("Déjà construite avec ce profil", self.texte())

    def test_no_yes_to_the_remaster_writes_nothing(self):
        self.assertFalse(self.ecrire_avec(self.numero("generic"), "n"))
        self.todo.execute.exec_command_live.assert_not_called()
        # Ni ISO ni profil JSON : un non ne laisse rien qui nomme l'hôte.
        self.assertFalse(os.path.exists(self.derives))

    def test_a_failed_xorriso_leaves_neither_iso_nor_profile(self):
        def echec(cmd, source_erplibre=True):
            args = shlex.split(cmd)
            with open(args[args.index("-outdev") + 1], "wb") as fh:
                fh.write(b"partielle")
            return 1

        self.todo.execute.exec_command_live.side_effect = echec
        self.assertFalse(self.ecrire_avec(self.numero("generic"), "o"))
        self.assertEqual(os.listdir(self.derives), [])

    def test_a_file_system_error_is_a_warning_not_a_traceback(self):
        with mock.patch.object(
            su, "ecrire_atomique", side_effect=OSError(122, "quota")
        ):
            self.assertFalse(self.ecrire_avec(self.numero("generic"), "o"))
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("Erreur du système de fichiers", self.texte())
        self.assertEqual(os.listdir(self.derives), [])

    def test_an_existing_derived_dir_is_tightened_to_0700(self):
        os.makedirs(self.derives, mode=0o755)
        os.chmod(self.derives, 0o755)
        self.assertTrue(
            self.ecrire_avec(self.numero("generic"), "o", "1", "sdb", "o")
        )
        self.assertEqual(os.stat(self.derives).st_mode & 0o777, 0o700)

    def test_outdated_derived_isos_are_removed_after_a_build(self):
        os.makedirs(self.derives)
        anciens = [
            "aaaaaaaaaaaa-bbbbbbbbbbbb.iso",
            "aaaaaaaaaaaa-bbbbbbbbbbbb.iso.sha256",
            "aaaaaaaaaaaa-cccccccccccc.json",
        ]
        for nom in [*anciens, "notes.txt"]:
            with open(os.path.join(self.derives, nom), "w") as fh:
                fh.write("x")
        self.assertTrue(
            self.ecrire_avec(self.numero("generic"), "o", "1", "sdb", "o")
        )
        restants = sorted(os.listdir(self.derives))
        self.assertEqual(len(restants), 3, restants)
        self.assertIn("notes.txt", restants)
        for nom in anciens:
            self.assertNotIn(nom, restants)

    def test_the_autotest_iso_is_not_asked_a_profile(self):
        autotest = os.path.join(
            self.tmp.name, "erplibre-archlinux-autotest-2099.01.02-x86_64.iso"
        )
        with open(autotest, "wb") as fh:
            fh.write(b"\1" * 4096)
        self.assertTrue(
            self.ecrire(
                [lsblk(nvme_systeme(), cle_montee())] * 2,
                ["1", autotest, "1", "sdb", "o"],
            )
        )
        self.assertNotIn("Profil machine :", self.texte())
        self.assertFalse(any("xorriso" in c for c in self.lances()))

    def test_a_profile_with_errors_is_refused(self):
        self.prive_ecrire(
            "poste-quillon",
            {"name": "poste-quillon", "user": {"password": "x"}},
        )
        self.assertFalse(self.ecrire_avec(self.numero("poste-quillon")))
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("Ce profil a des erreurs", self.texte())

    def test_an_unreadable_volume_date_stops(self):
        self.volume.stop()
        with mock.patch.object(su, "lire_volume_date", return_value=None):
            self.assertFalse(self.ecrire_avec(self.numero("generic")))
        self.volume.start()
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("date de volume", self.texte())

    def test_missing_xorriso_offers_libisoburn(self):
        with (
            mock.patch.object(
                su.shutil,
                "which",
                side_effect=lambda nom: None if nom == "xorriso" else "/bin/x",
            ),
            mock.patch(
                "script.todo.qemu_privilege.install_cmd_for",
                return_value=(
                    "sudo pacman -S --needed --noconfirm libisoburn",
                    "libisoburn",
                ),
            ) as installer,
        ):
            self.assertFalse(self.ecrire_avec(self.numero("generic"), "n"))
        installer.assert_called_once_with(su.PAQUETS_XORRISO)
        self.todo.execute.exec_command_live.assert_not_called()
        self.assertIn("libisoburn", self.texte())


if __name__ == "__main__":
    unittest.main()
