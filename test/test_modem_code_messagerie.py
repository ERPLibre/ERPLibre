#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le code de la boite vocale : rangement dans le coffre, jamais affiche."""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.mail.secrets import SecretError  # noqa: E402
from script.todo.modem import code_messagerie as code_mod  # noqa: E402


class CoffreFactice:
    def __init__(self, backends=("kdbx",)):
        self.backends = list(backends)
        self.contenu = {}

    def available_backends(self):
        return self.backends

    def get(self, ref):
        return self.contenu.get(ref)

    def set(self, ref, secret):
        self.contenu[ref] = secret

    def delete(self, ref):
        self.contenu.pop(ref, None)


class TestCode(unittest.TestCase):
    def test_le_kdbx_est_prefere(self):
        """Le meme coffre que le courriel, groupe ERPLibre > Modem."""
        store = CoffreFactice(("kdbx", "keyring"))
        self.assertEqual(code_mod.enregistrer(store, "1234"), code_mod.REF_KDBX)
        self.assertEqual(code_mod.lire(store), "1234")

    def test_le_trousseau_sert_de_repli(self):
        store = CoffreFactice(("keyring",))
        self.assertEqual(code_mod.enregistrer(store, "1234"), code_mod.REF_KEYRING)

    def test_sans_coffre_chiffre_rien_n_est_ecrit(self):
        """Mieux vaut ne pas enregistrer le code que l'ecrire en clair."""
        store = CoffreFactice(())
        with self.assertRaises(SecretError):
            code_mod.enregistrer(store, "1234")
        self.assertEqual(store.contenu, {})

    def test_un_code_mal_forme_est_refuse(self):
        """Une faute de frappe composee ferait echouer chaque recuperation."""
        store = CoffreFactice()
        for mauvais in ("", "12", "12a4", "12345678901", "12 34"):
            with self.assertRaises(code_mod.CodeInvalide, msg=mauvais):
                code_mod.enregistrer(store, mauvais)
        self.assertEqual(store.contenu, {})

    def test_effacer(self):
        store = CoffreFactice()
        code_mod.enregistrer(store, "98765")
        self.assertTrue(code_mod.est_defini(store))
        code_mod.effacer(store)
        self.assertFalse(code_mod.est_defini(store))


class TestCoffreParFormulaire(unittest.TestCase):
    """Le coffre ouvert avec un mot de passe saisi dans une interface plein
    ecran, ou `getpass` n'a nulle part ou s'afficher."""

    def test_sans_fichier_declare_on_le_dit(self):
        config = mock.Mock()
        config.get_config_value.return_value = ""
        with self.assertRaises(SecretError):
            code_mod.coffre_avec_mot_de_passe("mdp", config=config)

    def test_le_coffre_s_ouvre_tout_de_suite(self):
        """Un mot de passe errone doit se voir sur le formulaire, pas plus
        tard sous la forme d'une recuperation qui echoue."""
        with mock.patch.object(code_mod.CoffreOuvert, "get_kdbx",
                               side_effect=ValueError("mot de passe errone")):
            with self.assertRaises(ValueError):
                code_mod.coffre_avec_mot_de_passe("mauvais", chemin="/coffre.kdbx")


class TestCoffreSansKdbx(unittest.TestCase):
    def test_sans_chemin_kdbx_le_kdbx_n_est_pas_ouvert(self):
        """L'ouvrir sans chemin ferait surgir un selecteur graphique."""
        todo = mock.Mock()
        todo.config_file.get_config_value.return_value = None
        store = code_mod.coffre(todo)
        self.assertNotIn("kdbx", store.available_backends())

    def test_avec_chemin_kdbx_le_kdbx_est_prefere(self):
        todo = mock.Mock()
        todo.config_file.get_config_value.return_value = "/coffre.kdbx"
        self.assertIn("kdbx", code_mod.coffre(todo).available_backends())


class TestMenu(unittest.TestCase):
    def test_le_code_n_apparait_jamais_a_l_ecran(self):
        """Saisi sans echo, confirme, et jamais recopie dans la sortie."""
        from script.todo.modem import menu

        store = CoffreFactice()
        sortie = io.StringIO()
        with mock.patch.object(code_mod, "coffre", return_value=store), \
                mock.patch("builtins.input", return_value="1"), \
                mock.patch("getpass.getpass", side_effect=["864209", "864209"]), \
                redirect_stdout(sortie):
            menu._repondeur_code(todo=None)
        self.assertEqual(store.contenu[code_mod.REF_KDBX], "864209")
        self.assertNotIn("864209", sortie.getvalue())

    def test_deux_saisies_differentes_n_enregistrent_rien(self):
        from script.todo.modem import menu

        store = CoffreFactice()
        with mock.patch.object(code_mod, "coffre", return_value=store), \
                mock.patch("builtins.input", return_value="1"), \
                mock.patch("getpass.getpass", side_effect=["864209", "864208"]), \
                redirect_stdout(io.StringIO()):
            menu._repondeur_code(todo=None)
        self.assertEqual(store.contenu, {})

    def test_l_etat_ne_force_pas_l_ouverture_du_coffre(self):
        """Afficher le menu ne doit pas demander le mot de passe KeePass."""
        from script.todo.modem import menu

        todo = mock.Mock()
        todo.kdbx_manager = mock.Mock(_kdbx=None)
        with mock.patch.object(code_mod, "coffre") as ouvrir:
            etat = menu._etat_code_messagerie(todo)
        ouvrir.assert_not_called()
        self.assertTrue(etat)


class ServiceFactice:
    """Un service de voix en toc, sur une vraie socket de domaine Unix.

    Rejoue le dialogue du service : une ligne recue, une ligne rendue, et la
    connexion se ferme. Ce qu'on verifie ici n'est pas la socket mais ce qui y
    passe — et surtout ce qui n'y passe pas.
    """

    def __init__(self, chemin, reponse="OK"):
        import socket
        import threading

        self.chemin = chemin
        self.reponse = reponse
        self.recu = []
        self.prise = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.prise.bind(chemin)
        self.prise.listen(1)
        self.fil = threading.Thread(target=self._servir, daemon=True)
        self.fil.start()

    def _servir(self):
        while True:
            try:
                conn, _ = self.prise.accept()
            except OSError:
                return
            with conn:
                self.recu.append(conn.recv(256).decode("utf-8").strip())
                conn.sendall((self.reponse + "\n").encode("utf-8"))

    def fermer(self):
        self.prise.close()


class TestRemiseAuService(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chemin = os.path.join(self.tmp.name, "controle.sock")

    def test_un_code_invalide_ne_touche_pas_la_socket(self):
        """Refuser AVANT d'ouvrir la socket : une saisie fautive n'a aucune
        raison d'atteindre le service."""
        service = ServiceFactice(self.chemin)
        self.addCleanup(service.fermer)
        remis, detail = code_mod.remettre_au_service("abc", self.chemin)
        self.assertFalse(remis)
        self.assertEqual(service.recu, [])
        self.assertIn("chiffres", detail)

    def test_le_code_traverse_la_socket_et_le_service_accuse(self):
        service = ServiceFactice(self.chemin)
        self.addCleanup(service.fermer)
        remis, _ = code_mod.remettre_au_service("864209", self.chemin)
        self.assertTrue(remis)
        self.assertEqual(service.recu, ["NIP 864209"])

    def test_un_refus_du_service_se_rapporte_tel_quel(self):
        service = ServiceFactice(self.chemin, reponse="ERREUR aucun code")
        self.addCleanup(service.fermer)
        remis, detail = code_mod.remettre_au_service("864209", self.chemin)
        self.assertFalse(remis)
        self.assertIn("ERREUR", detail)

    def test_sans_service_on_le_dit_au_lieu_d_echouer(self):
        """Un service arrete n'est pas une panne du CLI : c'est l'etat le plus
        courant, juste apres un redemarrage."""
        remis, detail = code_mod.remettre_au_service("864209", self.chemin)
        self.assertFalse(remis)
        self.assertIn("ne tourne pas", detail)
        self.assertIsNone(code_mod.service_a_le_code(self.chemin))

    def test_l_etat_dit_oui_ou_non_sans_rendre_le_code(self):
        service = ServiceFactice(self.chemin, reponse="OK nip=oui")
        self.addCleanup(service.fermer)
        self.assertTrue(code_mod.service_a_le_code(self.chemin))
        service.reponse = "OK nip=non"
        self.assertFalse(code_mod.service_a_le_code(self.chemin))

    def test_le_code_n_apparait_pas_a_l_ecran_de_la_remise(self):
        """Meme chemin que la saisie : ce qui est dit a l'ecran ne porte
        jamais la valeur."""
        from script.todo.modem import menu

        sortie = io.StringIO()
        with mock.patch("script.todo.modem.code_messagerie.coffre"), \
                mock.patch("script.todo.modem.code_messagerie.lire",
                           return_value="864209"), \
                mock.patch("script.todo.modem.code_messagerie.remettre_au_service",
                           return_value=(True, "")) as remise, \
                redirect_stdout(sortie):
            menu._repondeur_remettre_code(todo=None)
        self.assertNotIn("864209", sortie.getvalue())
        remise.assert_called_once_with("864209")


if __name__ == "__main__":
    unittest.main()
