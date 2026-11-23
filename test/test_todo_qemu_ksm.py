#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""KSM de la station : l'état lu, les quatre gestes, leur verdict.

Tout se joue sur des fichiers temporaires qui imitent sysfs et
/etc/tmpfiles.d : ni root, ni vrai noyau. Les commandes sont les VRAIES
commandes shell du module, lancées sans sudo, ou avec un faux « sudo » qui
refuse — c'est ce qui prouve que l'écriture passe par lui.
"""

import io
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from script.todo import qemu_ksm
from script.todo.qemu_ksm import QemuKsmMixin

PAGE = 4096


def shell(env=None):
    """Exécuteur réel : la commande part dans bash, son code revient."""

    def executer(cmd):
        return subprocess.run(
            cmd, shell=True, executable="/bin/bash", env=env
        ).returncode

    return executer


class _Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.sysfs = os.path.join(self.tmp, "ksm")
        os.mkdir(self.sysfs)
        self.tmpfiles = os.path.join(self.tmp, "erplibre-ksm.conf")
        self.ecrire("run", "0")
        self.ecrire("pages_sharing", "0")

    def ecrire(self, nom, valeur):
        with open(os.path.join(self.sysfs, nom), "w") as fichier:
            fichier.write(f"{valeur}\n")

    def lire_run(self):
        with open(os.path.join(self.sysfs, "run")) as fichier:
            return fichier.read().strip()

    def etat(self):
        return qemu_ksm.lire_etat(self.sysfs, self.tmpfiles, PAGE)

    def appliquer(self, action, executer, sudo=""):
        return qemu_ksm.appliquer(
            action, executer, self.sysfs, self.tmpfiles, sudo, PAGE
        )


class TestLireEtat(_Fixture):
    def test_actif_et_pages_converties_en_mio(self):
        self.ecrire("run", "1")
        self.ecrire("pages_sharing", "256")
        etat = self.etat()
        self.assertTrue(etat["lisible"])
        self.assertEqual(etat["run"], 1)
        self.assertEqual(etat["pages_sharing"], 256)
        self.assertEqual(etat["mio"], 1.0)

    def test_la_taille_de_page_compte(self):
        self.ecrire("pages_sharing", "256")
        etat = qemu_ksm.lire_etat(self.sysfs, self.tmpfiles, 16384)
        self.assertEqual(etat["mio"], 4.0)

    def test_inactif_reste_lisible(self):
        etat = self.etat()
        self.assertTrue(etat["lisible"])
        self.assertEqual(etat["run"], 0)

    def test_noyau_sans_ksm_est_illisible_pas_inactif(self):
        etat = qemu_ksm.lire_etat(
            os.path.join(self.tmp, "absent"), self.tmpfiles, PAGE
        )
        self.assertFalse(etat["lisible"])
        self.assertEqual(etat["raison"], "absent")
        self.assertIsNone(etat["run"])

    @unittest.skipIf(os.geteuid() == 0, "root lit tout")
    def test_lecture_refusee(self):
        os.chmod(os.path.join(self.sysfs, "run"), 0)
        etat = self.etat()
        self.assertFalse(etat["lisible"])
        self.assertEqual(etat["raison"], "droits")

    def test_contenu_non_numerique(self):
        self.ecrire("pages_sharing", "n/a")
        etat = self.etat()
        self.assertFalse(etat["lisible"])
        self.assertEqual(etat["raison"], "invalide")

    def test_permanence_lue_meme_sysfs_illisible(self):
        open(self.tmpfiles, "w").close()
        etat = qemu_ksm.lire_etat(
            os.path.join(self.tmp, "absent"), self.tmpfiles, PAGE
        )
        self.assertTrue(etat["permanent"])


class TestLesGestesReels(_Fixture):
    """Les commandes du module, lancées pour de vrai, sans sudo."""

    def test_activer_puis_desactiver(self):
        verdict, code, etat = self.appliquer("activer", shell())
        self.assertEqual((verdict, code, self.lire_run()), ("fait", 0, "1"))
        verdict, _code, etat = self.appliquer("desactiver", shell())
        self.assertEqual((verdict, self.lire_run()), ("fait", "0"))
        self.assertEqual(etat["run"], 0)

    def test_rendre_permanent_puis_retirer(self):
        verdict, _c, etat = self.appliquer("permanent", shell())
        self.assertEqual(verdict, "fait")
        self.assertTrue(etat["permanent"])
        with open(self.tmpfiles) as fichier:
            self.assertEqual(
                fichier.read(), qemu_ksm.ligne_tmpfiles(self.sysfs) + "\n"
            )
        verdict, _c, etat = self.appliquer("retirer", shell())
        self.assertEqual(verdict, "fait")
        self.assertFalse(os.path.exists(self.tmpfiles))

    def test_la_permanence_ne_touche_pas_l_etat_courant(self):
        self.appliquer("permanent", shell())
        self.assertEqual(self.lire_run(), "0")

    @unittest.skipUnless(
        shutil.which("systemd-tmpfiles"), "systemd-tmpfiles absent"
    )
    def test_systemd_tmpfiles_active_ksm_avec_le_fichier_ecrit(self):
        """La syntaxe n'est pas supposée : l'outil du démarrage la lit."""
        self.appliquer("permanent", shell())
        subprocess.run(
            ["systemd-tmpfiles", "--create", self.tmpfiles],
            check=True,
            capture_output=True,
        )
        self.assertEqual(self.lire_run(), "1")


class TestLesVerdicts(_Fixture):
    def test_un_refus_est_dit_et_rien_ne_change(self):
        verdict, code, etat = self.appliquer("activer", lambda c: 1)
        self.assertEqual((verdict, code), ("refuse", 1))
        self.assertEqual(etat["run"], 0)

    def test_code_nul_sans_effet_n_est_pas_un_succes(self):
        for action in qemu_ksm.ACTIONS:
            if action == "retirer":
                open(self.tmpfiles, "w").close()
            verdict, _c, _e = self.appliquer(action, lambda c: 0)
            if action == "desactiver":
                # run vaut déjà 0 : l'état visé est tenu.
                self.assertEqual(verdict, "fait")
            else:
                self.assertEqual(verdict, "sans_effet", action)

    def test_toute_ecriture_passe_par_sudo(self):
        """Un faux sudo qui refuse : si une commande écrivait sans lui, le
        fichier changerait malgré le refus."""
        bin_dir = os.path.join(self.tmp, "bin")
        os.mkdir(bin_dir)
        faux = os.path.join(bin_dir, "sudo")
        with open(faux, "w") as fichier:
            fichier.write("#!/bin/sh\nexit 1\n")
        os.chmod(faux, stat.S_IRWXU)
        env = dict(os.environ, PATH=bin_dir + os.pathsep + os.environ["PATH"])
        open(self.tmpfiles, "w").close()
        for action in ("activer", "retirer"):
            verdict, code, _e = self.appliquer(action, shell(env), "sudo")
            self.assertEqual(verdict, "refuse", action)
        self.assertEqual(self.lire_run(), "0")
        self.assertTrue(os.path.exists(self.tmpfiles))
        os.remove(self.tmpfiles)
        self.ecrire("run", "1")
        for action in ("desactiver", "permanent"):
            verdict, code, _e = self.appliquer(action, shell(env), "sudo")
            self.assertEqual(verdict, "refuse", action)
        self.assertEqual(self.lire_run(), "1")
        self.assertFalse(os.path.exists(self.tmpfiles))


class _Menu(QemuKsmMixin):
    def __init__(self, sysfs, tmpfiles, code):
        self._KSM_SYSFS = sysfs
        self._KSM_TMPFILES = tmpfiles
        self._KSM_SUDO = ""
        self.lances = []
        menu = self

        class _Execute:
            def exec_command_live(self, cmd, source_erplibre=True):
                menu.lances.append(cmd)
                return code

        self.execute = _Execute()

    @staticmethod
    def _is_yes_default_yes(ans):
        return ans.strip().lower() in ("", "y", "o")


class TestLeMenu(_Fixture):
    def action(self, menu, reponse, action="activer"):
        sortie = io.StringIO()
        with patch("builtins.input", return_value=reponse):
            with redirect_stdout(sortie):
                menu._qemu_ksm_action(action)
        return sortie.getvalue()

    def test_la_commande_est_montree_et_un_non_n_execute_rien(self):
        menu = _Menu(self.sysfs, self.tmpfiles, 0)
        sortie = self.action(menu, "n")
        self.assertIn(os.path.join(self.sysfs, "run"), sortie)
        self.assertEqual(menu.lances, [])

    def test_un_refus_de_sudo_est_annonce_pas_avale(self):
        menu = _Menu(self.sysfs, self.tmpfiles, 1)
        with patch.object(qemu_ksm, "t", lambda cle: cle):
            sortie = self.action(menu, "")
        self.assertEqual(len(menu.lances), 1)
        self.assertIn("Refused (code 1)", sortie)
        self.assertNotIn("Done", sortie)

    def test_l_etat_s_affiche_avec_ses_trois_lignes(self):
        self.ecrire("run", "1")
        self.ecrire("pages_sharing", "512")
        menu = _Menu(self.sysfs, self.tmpfiles, 0)
        sortie = io.StringIO()
        with patch.object(qemu_ksm, "t", lambda cle: cle):
            with redirect_stdout(sortie):
                menu._qemu_ksm_show_state(menu._qemu_ksm_state())
        texte = sortie.getvalue()
        self.assertIn("active (run = 1)", texte)
        self.assertIn("512 pages, 2 MiB", texte)
        self.assertIn("no (lost at the next reboot)", texte)

    def test_noyau_sans_ksm_ne_lance_rien(self):
        menu = _Menu(os.path.join(self.tmp, "absent"), self.tmpfiles, 0)
        self.action(menu, "")
        self.assertEqual(menu.lances, [])


if __name__ == "__main__":
    unittest.main()
