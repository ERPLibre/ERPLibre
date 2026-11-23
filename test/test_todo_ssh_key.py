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

from script.todo import ssh_key_menu, ui
from script.todo.ssh_key_menu import SshKeyMenuMixin, commande_ssh_keygen
from script.todo.todo_i18n import t
from script.todo.ui.port import ScriptedPort

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


def _notices(port):
    """Les avis qu'a montrés le port."""
    return [
        e["text"]
        for e in port.events
        if isinstance(e, dict) and e.get("t") == "notice"
    ]


class TestLeType(unittest.TestCase):
    """Le type de clé suit les règles des listes : un numéro, le nom
    affiché, Entrée pour ed25519, [0] et Ctrl+D pour revenir, une faute
    nommée puis redemandée."""

    def _type(self, reponses):
        self.port = ScriptedPort(reponses)
        with ui.bind(self.port), redirect_stdout(io.StringIO()):
            return _Menu()._ssh_key_ask_type()

    def test_entree_prend_ed25519_que_la_liste_marque(self):
        self.assertEqual(self._type([""]), "ed25519")
        ecran = self.port.events[0]
        self.assertEqual(ecran["kind"], "choose")
        self.assertTrue(ecran["text"].startswith("💬 "))
        self.assertEqual(ecran["default"], "1")
        self.assertIn(t("(default)"), ecran["options"][0]["label"])
        self.assertEqual(ecran["options"][-1]["key"], "0")

    def test_par_numero(self):
        self.assertEqual(self._type(["1"]), "ed25519")
        self.assertEqual(self._type(["2"]), "rsa")

    def test_par_le_nom_affiche(self):
        for nom in ("ed25519", "rsa"):
            with self.subTest(nom=nom):
                self.assertEqual(self._type([nom]), nom)
                libelles = [o["label"] for o in self.port.events[0]["options"]]
                self.assertTrue(any(lib.startswith(nom) for lib in libelles))

    def test_une_faute_est_nommee_puis_redemandee(self):
        self.assertEqual(self._type(["9", "rsa"]), "rsa")
        self.assertEqual(len(_notices(self.port)), 1)
        self.assertTrue(_notices(self.port)[0].endswith(": 9"))

    def test_zero_et_ctrl_d_reviennent(self):
        self.assertIsNone(self._type(["0", "rsa"]))
        self.assertEqual(self.port.answers, ["rsa"])
        self.assertIsNone(self._type([EOFError()]))
        self.assertIsNone(self._type([]))


class TestLeRetour(unittest.TestCase):
    """Un retour, à n'importe quelle question, ne lance jamais ssh-keygen
    et ne pose plus aucune question."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp)

    def _lance(self, reponses):
        # `chemin_commitable` interroge git par le même `subprocess.run` :
        # doublé, il laisse l'espion ne compter que ssh-keygen, où que soit
        # le dossier temporaire.
        self.port = ScriptedPort([*reponses, "de trop"])
        with (
            ui.bind(self.port),
            patch.object(ssh_key_menu.subprocess, "run") as lancer,
            patch.object(
                ssh_key_menu, "chemin_commitable", return_value=False
            ),
            redirect_stdout(io.StringIO()),
        ):
            _Menu().execute_generate_ssh_key()
        lancer.assert_not_called()
        self.assertEqual(self.port.answers, ["de trop"])

    def test_zero_au_type(self):
        self._lance(["0"])

    def test_ctrl_d_au_type(self):
        self._lance([EOFError()])

    def test_ctrl_d_au_fichier(self):
        self._lance(["", EOFError()])

    def test_ctrl_d_au_commentaire(self):
        dossier = os.path.join(self.tmp, "ssh")
        self._lance(["rsa", os.path.join(dossier, "id_lagune"), EOFError()])
        self.assertFalse(os.path.lexists(dossier))


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
        self.port = ScriptedPort(reponses)
        with (
            ui.bind(self.port),
            patch.object(ssh_key_menu.subprocess, "run", sans_terminal),
            redirect_stdout(sortie),
        ):
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
        for reponse in ("2", "rsa"):
            with self.subTest(reponse=reponse):
                self.commandes = []
                chemin = os.path.join(self.tmp, f"id_rsa_essai_{reponse}")
                self._lance([reponse, chemin, ""])
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
        sortie = self._lance(
            ["", os.path.join(fichier, "id_z"), "essai@poste"]
        )
        self.assertEqual(self.port.answers, [])
        self.assertEqual(self.commandes, [])
        self.assertIn(t("Cannot create the folder of the key:"), sortie)
        self.assertNotIn("$ ssh-keygen", sortie)

    def test_un_type_illisible_est_redemande(self):
        chemin = os.path.join(self.tmp, "id_essai")
        self._lance(["9", "", chemin, "essai@poste"])
        self.assertTrue(_notices(self.port)[0].endswith(": 9"))
        with open(f"{chemin}.pub") as fichier:
            self.assertTrue(fichier.read().startswith("ssh-ed25519 "))


if __name__ == "__main__":
    unittest.main()
