#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le repondeur du modem, cote TUI : reglages, liste, effacement.

Rien ici ne touche au materiel : le service `erplibre_sip_go` decroche et
enregistre, la TUI ne fait que regler et consulter.
"""
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.modem import repondeur as rep  # noqa: E402


class TestReglages(unittest.TestCase):
    def setUp(self):
        self.dossier = self.enterContext(mock.patch.object(rep, "racine"))
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dossier.return_value = self.tmp.name

    def test_un_repondeur_neuf_est_eteint(self):
        """Decrocher a la place de quelqu'un s'entend.

        Un defaut actif ferait repondre une machine sur une ligne dont le
        proprietaire ignore qu'elle en a une.
        """
        self.assertFalse(rep.lire()["actif"])

    def test_un_fichier_absent_ne_casse_rien(self):
        """C'est l'etat d'une installation sans repondeur, pas une panne."""
        reglages = rep.lire()
        self.assertEqual(reglages["sonneries"], rep.SONNERIES_DEFAUT)
        self.assertTrue(
            reglages["dossier"].endswith("private/repondeur/messages")
        )

    def test_un_fichier_casse_laisse_le_menu_s_afficher(self):
        """Un JSON tronque ne doit pas rendre le menu inaccessible.

        C'est precisement le moment ou l'on vient reparer le reglage.
        """
        os.makedirs(os.path.dirname(rep.chemin_conf()), exist_ok=True)
        with open(rep.chemin_conf(), "w", encoding="utf-8") as flux:
            flux.write("{tronque")
        self.assertEqual(rep.lire()["sonneries"], rep.SONNERIES_DEFAUT)

    def test_les_reglages_font_l_aller_retour(self):
        rep.regler(actif=True, sonneries=3)
        relu = rep.lire()
        self.assertTrue(relu["actif"])
        self.assertEqual(relu["sonneries"], 3)
        with open(rep.chemin_conf(), encoding="utf-8") as flux:
            self.assertEqual(json.load(flux)["sonneries"], 3)

    def test_le_nombre_de_sonneries_est_borne(self):
        """La boite vocale de l'operateur prend l'appel vers trente secondes.

        Une sonnerie complete en dure six : au-dela de cinq, le repondeur ne
        decrocherait jamais, et la panne se lit « il ne marche pas ».
        """
        self.assertEqual(rep.borner_sonneries(40), rep.SONNERIES_MAX)
        self.assertEqual(rep.borner_sonneries(0), rep.SONNERIES_DEFAUT)
        self.assertEqual(rep.borner_sonneries("trois"), rep.SONNERIES_DEFAUT)
        self.assertEqual(rep.borner_sonneries("2"), 2)

    def test_cinq_sonneries_restent_sous_la_boite_vocale(self):
        """Le maximum n'est pas arbitraire : six secondes par sonnerie."""
        self.assertLess(rep.SONNERIES_MAX * 6, 31)


class TestMessages(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patch = mock.patch.object(rep, "racine", return_value=self.tmp.name)
        self.enterContext(patch)
        self.dossier = rep.chemin_messages()
        os.makedirs(self.dossier, exist_ok=True)

    def _poser(self, nom, debut, numero="15555550142"):
        son = os.path.join(self.dossier, nom + ".wav")
        with open(son, "wb") as flux:
            flux.write(b"RIFF")
        with open(
            os.path.join(self.dossier, nom + ".json"), "w", encoding="utf-8"
        ) as flux:
            json.dump(
                {
                    "numero": numero,
                    "debut": debut,
                    "fichier": son,
                    "duree_secondes": 7,
                },
                flux,
            )
        return son

    def test_les_messages_sortent_du_plus_recent(self):
        """Un repondeur se consulte pour ce qui vient d'arriver."""
        self._poser("vieux", "2026-09-01T08:00:00")
        self._poser("neuf", "2026-09-05T08:00:00")
        messages = rep.lister()
        self.assertEqual(len(messages), 2)
        self.assertTrue(messages[0]["fichier"].endswith("neuf.wav"))

    def test_un_son_sans_description_est_ignore(self):
        """Sans appelant ni date, la ligne n'apprend rien."""
        with open(os.path.join(self.dossier, "orphelin.wav"), "wb") as flux:
            flux.write(b"RIFF")
        self.assertEqual(rep.lister(), [])

    def test_un_dossier_absent_rend_une_liste_vide(self):
        rep.regler(dossier=os.path.join(self.tmp.name, "jamais"))
        self.assertEqual(rep.lister(), [])

    def test_effacer_emporte_les_deux_fichiers(self):
        """Une description orpheline ferait reapparaitre un message sans son."""
        son = self._poser("message", "2026-09-05T08:00:00")
        rep.effacer({"fichier": son})
        self.assertFalse(os.path.exists(son))
        self.assertEqual(rep.lister(), [])
        # Deux fois n'est pas une erreur : la TUI et Odoo peuvent le demander.
        rep.effacer({"fichier": son})


class TestAnnonce(unittest.TestCase):
    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.enterContext(
            mock.patch.object(rep, "racine", return_value=self.tmp.name)
        )

    def test_sans_arecord_le_refus_dit_quoi_installer(self):
        with mock.patch.object(rep, "_outil", return_value=""):
            succes, plainte = rep.enregistrer_annonce(3)
        self.assertFalse(succes)
        self.assertIn("alsa-utils", plainte)

    def test_une_capture_ratee_ne_laisse_pas_d_annonce_tronquee(self):
        """Le repondeur jouerait sinon la moitie d'une phrase au correspondant.

        L'ecriture passe par un fichier temporaire renomme a la fin.
        """
        echec = mock.Mock(returncode=1, stderr="carte occupee")
        with mock.patch.object(
            rep, "_outil", return_value="arecord"
        ), mock.patch.object(rep.subprocess, "run", return_value=echec):
            succes, plainte = rep.enregistrer_annonce(3)
        self.assertFalse(succes)
        self.assertIn("carte occupee", plainte)
        self.assertFalse(os.path.exists(rep.chemin_annonce()))
        self.assertFalse(os.path.exists(rep.chemin_annonce() + ".partiel"))

    def test_une_annonce_absente_se_dit_avant_de_jouer(self):
        succes, plainte = rep.jouer(os.path.join(self.tmp.name, "rien.wav"))
        self.assertFalse(succes)
        self.assertIn("introuvable", plainte)


class TestEcouteOperateur(unittest.TestCase):
    """L'ecoute d'un message recupere : jouer, puis proposer d'effacer."""

    def test_ecouter_puis_effacer(self):
        import io
        from contextlib import redirect_stdout

        from script.todo.modem import menu

        message = {"fichier": "/tmp/m.wav", "recupere_le": "2026-09-18T01:48:00",
                   "duree_secondes": 7.1, "enregistrement_complet": "/tmp/appel.wav"}
        effaces = []
        sortie = io.StringIO()
        with mock.patch.object(menu.rep_mod, "jouer", return_value=(True, "")) as jouer, \
                mock.patch("script.todo.modem.recuperation.effacer_message",
                           side_effect=effaces.append), \
                mock.patch("builtins.input", side_effect=["1", "o"]), \
                redirect_stdout(sortie):
            menu._repondeur_messages_recuperes([message])
        jouer.assert_called_once_with("/tmp/m.wav")
        self.assertEqual(effaces, [message])
        self.assertIn("/tmp/appel.wav", sortie.getvalue())

    def test_rien_n_est_efface_sans_reponse_affirmative(self):
        import io
        from contextlib import redirect_stdout

        from script.todo.modem import menu

        effaces = []
        with mock.patch.object(menu.rep_mod, "jouer", return_value=(True, "")), \
                mock.patch("script.todo.modem.recuperation.effacer_message",
                           side_effect=effaces.append), \
                mock.patch("builtins.input", side_effect=["1", ""]), \
                redirect_stdout(io.StringIO()):
            menu._repondeur_messages_recuperes([{"fichier": "/tmp/m.wav"}])
        self.assertEqual(effaces, [])


if __name__ == "__main__":
    unittest.main()
