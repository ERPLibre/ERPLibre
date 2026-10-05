#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La chaine de proprietes passee a ModemManager pour creer un SMS.

Les regles viennent d'essais sur un vrai modem : sans guillemets, l'analyseur
coupe a la premiere espace ; entre guillemets, l'espace, la virgule, le signe
egal et les emoji passent ; aucun echappement n'existe.
"""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.modem import messaging  # noqa: E402


class TestProprietes(unittest.TestCase):
    def test_un_texte_ordinaire_est_entre_guillemets(self):
        """Sans eux, « coucou bobo » echoue des la premiere espace."""
        proprietes, raison = messaging.proprietes_sms("15145550142", "coucou bobo ⛔")
        self.assertEqual(raison, "")
        self.assertEqual(proprietes, 'number=15145550142,text="coucou bobo ⛔"')

    def test_la_virgule_et_le_signe_egal_passent(self):
        """La virgule separe deux proprietes : entre guillemets, elle appartient
        au texte."""
        proprietes, _ = messaging.proprietes_sms("1", "oui, non a=b")
        self.assertEqual(proprietes, 'number=1,text="oui, non a=b"')

    def test_une_apostrophe_garde_les_guillemets_doubles(self):
        proprietes, _ = messaging.proprietes_sms("1", "c'est l'ete")
        self.assertEqual(proprietes, "number=1,text=\"c'est l'ete\"")

    def test_un_guillemet_double_fait_passer_aux_apostrophes(self):
        proprietes, _ = messaging.proprietes_sms("1", 'il dit "oui"')
        self.assertEqual(proprietes, "number=1,text='il dit \"oui\"'")

    def test_les_deux_sortes_se_refusent_en_le_disant(self):
        """ModemManager n'echappe rien : alterer le texte en silence serait
        pire que refuser."""
        proprietes, raison = messaging.proprietes_sms("1", "il dit \"oui\", c'est ca")
        self.assertEqual(proprietes, "")
        self.assertIn("Retirez", raison)

    def test_un_texte_vide_reste_valide(self):
        proprietes, raison = messaging.proprietes_sms("1", "")
        self.assertEqual((proprietes, raison), ('number=1,text=""', ""))


class TestEnvoi(unittest.TestCase):
    def test_le_texte_part_entre_guillemets(self):
        appels = []

        def faux_run(args, **kwargs):
            appels.append(args)
            return 0, "/org/freedesktop/ModemManager1/SMS/7"

        with mock.patch.object(messaging, "mmcli_present", return_value=True), \
                mock.patch.object(messaging, "_run", side_effect=faux_run):
            ok, _ = messaging.envoyer(0, "15145550142", "coucou bobo")
        self.assertTrue(ok)
        self.assertIn('text="coucou bobo"', appels[0][-1])

    def test_un_texte_impossible_n_atteint_jamais_le_modem(self):
        with mock.patch.object(messaging, "mmcli_present", return_value=True), \
                mock.patch.object(messaging, "_run") as run:
            ok, raison = messaging.envoyer(0, "1", "il dit \"oui\", c'est ca")
        self.assertFalse(ok)
        run.assert_not_called()
        self.assertIn("ModemManager", raison)


if __name__ == "__main__":
    unittest.main()
