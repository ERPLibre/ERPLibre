#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La structure du menu Modem : sept entrees, et rien d'inatteignable.

Un menu se reorganise rarement, et c'est justement le moment ou une entree se
perd : elle disparait de l'ecran sans que rien ne le signale.
"""
import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.modem import menu  # noqa: E402

#: Tout ce que le menu doit rendre atteignable, premier ecran et sous-menus.
ACTIONS = {
    "_clavier", "_etat_detaille", "_diagnostic", "_appeler", "_raccrocher",
    "_lister_appels", "_appel_voip", "_envoyer_sms", "_lister_sms",
    "_passerelle", "_repondeur", "_sonder_audio", "_essai_combine",
    "_basculer_uac", "_regle_audio", "_regle_udev", "_installer_voip",
    "_etat_voip",
}

SOUS_MENUS = ("_sous_menu_etat", "_sous_menu_appels", "_sous_menu_sms",
              "_sous_menu_audio", "_sous_menu_voip")


def entrees_du_sous_menu(nom, todo=None):
    """Les (libelle, action) d'un sous-menu, sans l'afficher."""
    capture = {}

    def faux(titre, entrees):
        capture["titre"], capture["entrees"] = titre, entrees

    fonction = getattr(menu, nom)
    with mock.patch.object(menu, "_sous_menu", faux):
        fonction(todo) if fonction.__code__.co_argcount else fonction()
    return capture["titre"], capture["entrees"]


class TestStructure(unittest.TestCase):
    def test_le_premier_ecran_tient_en_sept_entrees(self):
        """Dix-huit entrees demandaient de lire l'ecran pour en trouver une."""
        source = open(menu.__file__, encoding="utf-8").read()
        debut = source.index("def prompt_execute_modem")
        fin = source.index("def _sous_menu(")
        corps = source[debut:fin]
        numeros = {ligne.split("]")[0].strip("[")
                   for ligne in corps.splitlines() if ligne.startswith("[")}
        self.assertEqual(numeros, {"1", "2", "3", "4", "5", "6", "7", "0"})

    def test_rien_ne_s_est_perdu_dans_le_rangement(self):
        atteignables = {"_clavier", "_repondeur"}
        for nom in SOUS_MENUS:
            _titre, entrees = entrees_du_sous_menu(nom, todo=mock.Mock())
            for _libelle, action in entrees:
                # Les actions qui prennent `todo` passent par une lambda :
                # on lit alors ce qu'elle appelle.
                nom_action = getattr(action, "__name__", "<lambda>")
                if nom_action == "<lambda>":
                    nom_action = action.__code__.co_names[0]
                atteignables.add(nom_action)
        self.assertEqual(ACTIONS - atteignables, set())

    def test_chaque_sous_menu_porte_un_titre_et_des_entrees(self):
        for nom in SOUS_MENUS:
            titre, entrees = entrees_du_sous_menu(nom, todo=mock.Mock())
            self.assertTrue(titre, nom)
            self.assertTrue(entrees, nom)

    def test_le_choix_appelle_l_action_de_sa_ligne(self):
        """La numerotation se deduit de l'ordre : une entree ajoutee au milieu
        ne peut pas se brancher sur l'action d'une autre."""
        appels = []
        entrees = (("un", lambda: appels.append("un")),
                   ("deux", lambda: appels.append("deux")))
        with mock.patch.object(menu.click, "prompt", side_effect=["2", "0"]), \
                redirect_stdout(io.StringIO()):
            menu._sous_menu("essai", entrees)
        self.assertEqual(appels, ["deux"])

    def test_un_choix_hors_liste_ne_fait_rien(self):
        appels = []
        entrees = (("un", lambda: appels.append("un")),)
        with mock.patch.object(menu.click, "prompt", side_effect=["9", "x", "0"]), \
                redirect_stdout(io.StringIO()):
            menu._sous_menu("essai", entrees)
        self.assertEqual(appels, [])

    def test_les_etats_restent_visibles_au_premier_ecran(self):
        """Ils vivaient a cote de leurs entrees, parties en sous-menu : savoir
        d'un coup d'oeil que le repondeur est eteint evite d'attendre en vain
        un message."""
        with mock.patch.object(menu, "_etat_repondeur", return_value="eteint"), \
                mock.patch.object(menu, "_etat_regle_audio", return_value="posee"), \
                mock.patch.object(menu, "_etat_messagerie", return_value="📭"), \
                mock.patch.object(menu.device_mod, "premier_modem", return_value=0), \
                mock.patch.object(menu.device_mod, "etat", return_value={}), \
                mock.patch.object(menu.calls_mod, "voix_disponible", return_value=(True, "")), \
                mock.patch.object(menu.udev_mod, "port_reserve", return_value="/dev/x"):
            bandeau = menu._bandeau()
        self.assertIn("eteint", bandeau)
        self.assertIn("posee", bandeau)


if __name__ == "__main__":
    unittest.main()
