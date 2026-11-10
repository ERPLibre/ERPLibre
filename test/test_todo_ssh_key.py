#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La clé SSH de TODO › Execute › Security.

La phrase de passe ne passe jamais en argument : ssh-keygen la demande. Un
fichier existant n'est jamais remplacé, et un chemin que git pourrait
commiter est refusé. Les tests de génération lancent le vrai ssh-keygen,
avec une phrase vide ajoutée par le test seul, faute de terminal.
"""

import io
import os
import shutil
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from script.todo import ssh_key_menu
from script.todo.ssh_key_menu import SshKeyMenuMixin, commande_ssh_keygen

SSH_KEYGEN = shutil.which("ssh-keygen")


class TestCommande(unittest.TestCase):
    def test_ed25519_sans_taille_ni_phrase_en_argument(self):
        commande = commande_ssh_keygen("/d/id", "ed25519", "moi@poste")
        self.assertEqual(commande[:3], ["ssh-keygen", "-t", "ed25519"])
        self.assertNotIn("-b", commande)
        self.assertNotIn("-N", commande)
        self.assertIn("-a", commande)

    def test_rsa_en_4096_bits(self):
        commande = commande_ssh_keygen("/d/id", "rsa", "moi@poste")
        self.assertEqual(commande[commande.index("-b") + 1], "4096")


class _Menu(SshKeyMenuMixin):
    pass


@unittest.skipUnless(SSH_KEYGEN, "ssh-keygen absent")
class TestLeMenu(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)
        self.commandes = []

    def _lance(self, reponses):
        reel = subprocess.run

        def sans_terminal(commande, *args, **kwargs):
            # La génération lit la phrase dans le terminal : le test la
            # donne vide, en argument, ce que le menu ne fait jamais.
            if "-a" in commande:
                self.commandes.append(list(commande))
                commande = [*commande, "-N", ""]
                kwargs.setdefault("capture_output", True)
            return reel(commande, *args, **kwargs)

        sortie = io.StringIO()
        with patch("builtins.input", side_effect=list(reponses)), patch.object(
            ssh_key_menu.subprocess, "run", sans_terminal
        ), redirect_stdout(sortie):
            _Menu().execute_generate_ssh_key()
        return sortie.getvalue()

    def test_une_cle_ed25519_est_ecrite_et_montree(self):
        chemin = os.path.join(self.tmp, "ssh", "id_essai")
        sortie = self._lance(["", chemin, "essai@poste"])
        self.assertTrue(os.path.isfile(chemin))
        with open(f"{chemin}.pub") as fichier:
            publique = fichier.read().strip()
        self.assertTrue(publique.startswith("ssh-ed25519 "))
        self.assertTrue(publique.endswith("essai@poste"))
        self.assertIn(publique, sortie)
        self.assertIn("$ ssh-keygen", sortie)
        self.assertIn("SHA256:", sortie)
        self.assertIn("ssh-copy-id -i", sortie)
        self.assertNotIn("-N", self.commandes[0])

    def test_rsa_au_choix(self):
        chemin = os.path.join(self.tmp, "id_rsa_essai")
        self._lance(["2", chemin, ""])
        self.assertIn("4096", self.commandes[0])
        with open(f"{chemin}.pub") as fichier:
            self.assertTrue(fichier.read().startswith("ssh-rsa "))

    def test_une_cle_existante_n_est_jamais_remplacee(self):
        chemin = os.path.join(self.tmp, "id_ed25519")
        with open(f"{chemin}.pub", "w") as fichier:
            fichier.write("ancienne")
        sortie = self._lance(["", chemin])
        self.assertEqual(self.commandes, [])
        self.assertIn(f"{chemin}_2", sortie)
        with open(f"{chemin}.pub") as fichier:
            self.assertEqual(fichier.read(), "ancienne")

    def test_un_chemin_commitable_est_refuse(self):
        depot = os.path.join(self.tmp, "depot")
        os.makedirs(depot)
        subprocess.run(["git", "init", "-q", depot], check=True)
        chemin = os.path.join(depot, "id_ed25519")
        self._lance(["", chemin])
        self.assertEqual(self.commandes, [])
        self.assertFalse(os.path.exists(chemin))

    def test_un_lien_orphelin_compte_comme_une_cle_existante(self):
        """ssh-keygen écrit à travers un lien : un lien orphelin vers un
        dépôt git y déposerait la clé privée."""
        depot = os.path.join(self.tmp, "depot")
        os.makedirs(depot)
        subprocess.run(["git", "init", "-q", depot], check=True)
        dossier = os.path.join(self.tmp, "ssh")
        os.makedirs(dossier)
        chemin = os.path.join(dossier, "id_ed25519")
        os.symlink(os.path.join(depot, "id_ed25519"), chemin)
        self._lance(["", chemin])
        self.assertEqual(self.commandes, [])
        self.assertFalse(os.path.exists(os.path.join(depot, "id_ed25519")))

    def test_un_dossier_recoit_le_nom_par_defaut(self):
        dossier = os.path.join(self.tmp, "ssh")
        os.makedirs(dossier)
        self._lance(["", dossier + os.sep, "essai@poste"])
        self.assertTrue(os.path.isfile(os.path.join(dossier, "id_ed25519")))

    def test_un_dossier_impossible_est_refuse_sans_planter(self):
        fichier = os.path.join(self.tmp, "fichier")
        open(fichier, "w").close()
        sortie = self._lance(["", os.path.join(fichier, "id_z")])
        self.assertEqual(self.commandes, [])
        self.assertNotIn("$ ssh-keygen", sortie)

    def test_un_type_illisible_n_ecrit_rien(self):
        sortie = self._lance(["9"])
        self.assertIn("'9'", sortie)
        self.assertEqual(self.commandes, [])


if __name__ == "__main__":
    unittest.main()
