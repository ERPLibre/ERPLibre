#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le drapeau de la boite vocale de l'operateur, tel que la TUI l'affiche.

Les reponses AT sont celles que rend un EC25 : l'enregistrement 1 d'EF_MWIS,
drapeau leve puis baisse, et le statut d'un fichier absent.
"""
import fcntl
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)

from script.todo.modem import messagerie_vocale as mv  # noqa: E402

LEVE = 'AT+CRSM=178,28618,1,4,5\n+CRSM: 144,0,"0100000000"\n\nOK\n'
BAISSE = '+CRSM: 144,0,"0000000000"\nOK\n'


class TestDecodage(unittest.TestCase):
    def test_le_drapeau_se_lit_dans_les_deux_sens(self):
        self.assertEqual(mv.decoder(LEVE)[0], mv.ATTENTE)
        self.assertEqual(mv.decoder(BAISSE)[0], mv.VIDE)

    def test_seul_le_bit_de_la_messagerie_vocale_compte(self):
        """Un fax en attente n'est pas un message vocal."""
        self.assertEqual(mv.decoder('+CRSM: 144,0,"0200000000"')[0], mv.VIDE)
        self.assertEqual(
            mv.decoder('+CRSM: 144,0,"0103000000"')[0], mv.ATTENTE
        )

    def test_un_fichier_absent_n_est_pas_une_boite_vide(self):
        """Une SIM sans ce fichier ne peut rien annoncer : dire « aucun
        message » laisserait croire qu'on le sait."""
        for reponse in ('+CRSM: 106,130,""', "ERROR", '+CRSM: 144,0,""', ""):
            self.assertEqual(mv.decoder(reponse)[0], mv.INCONNU, reponse)

    def test_meme_regle_que_le_service(self):
        """Le Go et le Python lisent le meme fichier : ils doivent s'accorder
        sur la commande, sinon l'un affiche ce que l'autre ne lit pas."""
        with open(
            os.path.join(RACINE, "script/erplibre_sip_go/messagerie.go"),
            encoding="utf-8",
        ) as flux:
            self.assertIn('"%s"' % mv.COMMANDE, flux.read())


class TestEtatDuService(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chemin = os.path.join(self.tmp.name, "messagerie.json")
        self.maintenant = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)

    def _poser(self, attente, il_y_a):
        lu = (self.maintenant - il_y_a).astimezone(
            timezone(timedelta(hours=-4))
        )
        with open(self.chemin, "w", encoding="utf-8") as flux:
            json.dump({"attente": attente, "lu_le": lu.isoformat()}, flux)

    def test_le_chemin_est_celui_du_service(self):
        ancien = os.environ.get("XDG_STATE_HOME")
        os.environ["XDG_STATE_HOME"] = "/tmp/etat-essai"
        try:
            self.assertEqual(
                mv.chemin_etat_service(),
                "/tmp/etat-essai/erplibre/messagerie.json",
            )
        finally:
            if ancien is None:
                del os.environ["XDG_STATE_HOME"]
            else:
                os.environ["XDG_STATE_HOME"] = ancien

    def test_un_etat_recent_porte_son_age(self):
        """Le fuseau du service n'importe pas : l'age est calcule en absolu."""
        self._poser(True, timedelta(minutes=2))
        etat = mv.lire_etat_service(self.maintenant, self.chemin)
        self.assertEqual(etat["etat"], mv.ATTENTE)
        self.assertEqual(etat["age"], 120)
        self.assertFalse(etat["perime"])

    def test_un_etat_ancien_se_dit_ancien(self):
        """Le service relit chaque minute : un etat vieux de plusieurs heures
        dit qu'il ne lit plus, et ne doit pas se presenter comme courant."""
        self._poser(False, timedelta(hours=3))
        self.assertTrue(
            mv.lire_etat_service(self.maintenant, self.chemin)["perime"]
        )

    def test_pas_de_fichier_pas_d_etat(self):
        self.assertIsNone(mv.lire_etat_service(self.maintenant, self.chemin))

    def test_un_fichier_casse_ne_casse_pas_le_menu(self):
        with open(self.chemin, "w", encoding="utf-8") as flux:
            flux.write("{tronque")
        self.assertIsNone(mv.lire_etat_service(self.maintenant, self.chemin))


class TestLecture(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.chemin = os.path.join(self.tmp.name, "messagerie.json")
        self.maintenant = datetime(2026, 9, 17, 15, 0, tzinfo=timezone.utc)

    def test_port_libre_la_sim_fait_foi(self):
        lecture = mv.lire(
            lambda _c: (True, LEVE), self.maintenant, self.chemin
        )
        self.assertEqual(
            (lecture["etat"], lecture["source"]), (mv.ATTENTE, "sim")
        )

    def test_port_tenu_l_etat_du_service_prend_le_relais(self):
        with open(self.chemin, "w", encoding="utf-8") as flux:
            json.dump(
                {
                    "attente": False,
                    "lu_le": (
                        self.maintenant - timedelta(seconds=40)
                    ).isoformat(),
                },
                flux,
            )
        tenu = lambda _c: (False, "PORT_TENU : le port est tenu")  # noqa: E731
        lecture = mv.lire(tenu, self.maintenant, self.chemin)
        self.assertEqual(
            (lecture["etat"], lecture["source"]), (mv.VIDE, "service")
        )
        self.assertEqual(lecture["age"], 40)

    def test_port_tenu_sans_etat_le_dit(self):
        """Ni SIM ni service : on ne sait pas, et on dit pourquoi."""
        tenu = lambda _c: (False, "PORT_TENU : le port est tenu")  # noqa: E731
        lecture = mv.lire(tenu, self.maintenant, self.chemin)
        self.assertEqual(lecture["etat"], mv.INCONNU)
        self.assertIn("service", lecture["detail"])

    def test_age_lisible(self):
        self.assertEqual(mv.age_lisible(40), "40 s")
        self.assertEqual(mv.age_lisible(600), "10 min")
        self.assertEqual(mv.age_lisible(7200), "2 h")


class TestVerrouDuPort(unittest.TestCase):
    """L'outil AT de la TUI prend le MEME verrou que le service.

    Sans lui, ses commandes s'entrelaceraient avec celles du service, et une
    reponse partirait vers l'autre programme. Verifie sur un vrai terminal
    virtuel : un fichier ordinaire refuserait les reglages termios avant
    meme d'atteindre le verrou.
    """

    def test_un_port_tenu_est_refuse_sans_rien_envoyer(self):
        maitre, esclave = os.openpty()
        self.addCleanup(os.close, maitre)
        self.addCleanup(os.close, esclave)
        chemin = os.ttyname(esclave)
        tenu = os.open(chemin, os.O_RDWR | os.O_NOCTTY)
        self.addCleanup(os.close, tenu)
        fcntl.flock(tenu, fcntl.LOCK_EX | fcntl.LOCK_NB)

        fait = subprocess.run(
            [
                sys.executable,
                os.path.join(RACINE, "script/todo/modem/at_direct.py"),
                chemin,
                "AT",
            ],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(fait.returncode, 3, fait.stderr)
        self.assertIn(mv.MARQUE_PORT_TENU, fait.stderr)
        os.set_blocking(maitre, False)
        try:
            envoye = os.read(maitre, 100)
        except BlockingIOError:
            envoye = b""
        self.assertEqual(
            envoye, b"", "une commande est partie malgre le verrou"
        )


if __name__ == "__main__":
    unittest.main()
