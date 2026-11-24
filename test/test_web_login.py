#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La connexion du navigateur attend son issue au lieu d'une seconde fixe.

`attendre_issue_connexion` distingue trois issues : l'URL quitte /web/login
(connecté), une NOUVELLE page de connexion porte l'alerte de refus (refusé),
ou rien dans le délai (TimeoutException). Une page encore en chargement
n'est ni l'une ni l'autre : c'est elle qu'une attente fixe d'une seconde
prenait pour un refus, juste après un démarrage d'Odoo.

`run` ne retente avec test/test qu'après un refus, et jamais avec
`no_try_test`. Les identifiants sont inventés.

`garder_ouvert` demande Entrée seulement quand l'entrée standard est un
terminal ; sans terminal, il n'appelle jamais input() et attend que la
fenêtre du navigateur soit fermée. Le pilote est un simulacre ; aucun
navigateur ne s'ouvre.
"""

import os
import sys
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from selenium.common.exceptions import (  # noqa: E402
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)

from script.selenium import web_login  # noqa: E402

PAGE_CONNEXION = "http://odoo.essai.invalid/web/login?db=essai"
PAGE_ODOO = "http://odoo.essai.invalid/odoo"


class FauxPilote:
    """Rejoue une suite d'états ; le dernier reste en place.

    Chaque état : (url, page d'avant encore là, alerte visible, lève).
    """

    def __init__(self, etats):
        self.etats = list(etats)
        self.page_avant = FaussePage(self)

    def etat(self):
        return self.etats[0]

    def avancer(self):
        if len(self.etats) > 1:
            self.etats.pop(0)

    @property
    def current_url(self):
        url, _avant, _alerte, leve = self.etat()
        if leve:
            self.avancer()
            raise WebDriverException("page en cours de chargement")
        return url

    def find_elements(self, by, valeur):
        _url, _avant, alerte, _leve = self.etat()
        self.avancer()
        return ["alerte"] if alerte else []


class FaussePage:
    """L'élément html d'avant l'envoi ; périmé une fois la page remplacée."""

    def __init__(self, pilote):
        self.pilote = pilote

    @property
    def tag_name(self):
        _url, avant, _alerte, _leve = self.pilote.etat()
        if not avant:
            raise StaleElementReferenceException("page remplacée")
        self.pilote.avancer()
        return "html"


def attendre(etats, delai=2):
    pilote = FauxPilote(etats)
    return web_login.attendre_issue_connexion(
        pilote, pilote.page_avant, delai=delai, pas=0.01
    )


class TestAttendreIssueConnexion(unittest.TestCase):
    def test_une_page_lente_n_est_pas_un_refus(self):
        """La page d'avant reste affichée, puis le chargement lève, puis
        /odoo : l'issue est la connexion, pas un refus."""
        etats = [(PAGE_CONNEXION, True, False, False)] * 5
        etats += [(PAGE_CONNEXION, True, False, True)]
        etats += [(PAGE_ODOO, False, False, False)]
        self.assertTrue(attendre(etats))

    def test_l_alerte_d_une_nouvelle_page_est_un_refus(self):
        etats = [(PAGE_CONNEXION, True, False, False)] * 3
        etats += [(PAGE_CONNEXION, False, True, False)]
        self.assertFalse(attendre(etats))

    def test_l_alerte_de_la_page_d_avant_ne_compte_pas(self):
        """Le refus précédent est encore affiché tant que la page n'est pas
        remplacée : le compter rendrait un refus avant la réponse."""
        etats = [(PAGE_CONNEXION, True, True, False)] * 5
        etats += [(PAGE_ODOO, False, False, False)]
        self.assertTrue(attendre(etats))

    def test_ni_connecte_ni_refuse_leve_au_bout_du_delai(self):
        with self.assertRaises(TimeoutException) as leve:
            attendre([(PAGE_CONNEXION, True, False, False)], delai=0.1)
        self.assertIn("sans réponse", str(leve.exception))


def outil_selenium():
    outil = mock.Mock()
    outil.driver.current_url = PAGE_CONNEXION
    return outil


def config_essai():
    return mock.Mock(
        default_email_auth="compte_essai",
        default_password_auth="mdp_essai",
        default_password_auth_env=None,
        open_dashboard=False,
        no_dark_mode=True,
    )


class TestRun(unittest.TestCase):
    def setUp(self):
        patcheur = mock.patch.object(web_login.time, "sleep")
        patcheur.start()
        self.addCleanup(patcheur.stop)

    def lancer(self, issues, **kwargs):
        outil = outil_selenium()
        with mock.patch.object(
            web_login, "attendre_issue_connexion", side_effect=issues
        ) as attente:
            rendu = web_login.run(config_essai(), outil, **kwargs)
        saisies = [
            appel.args[0]
            for appel in outil.get_element.return_value.send_keys.call_args_list
        ]
        return rendu, attente.call_count, saisies, outil

    def test_connecte_du_premier_coup(self):
        rendu, essais, saisies, outil = self.lancer([True])
        self.assertTrue(rendu)
        self.assertEqual(1, essais)
        self.assertEqual(["compte_essai", "mdp_essai"], saisies)
        outil.check_bot_chat_and_close.assert_called_once()

    def test_un_refus_retente_avec_test(self):
        rendu, essais, saisies, _outil = self.lancer([False, True])
        self.assertTrue(rendu)
        self.assertEqual(2, essais)
        self.assertEqual(
            ["compte_essai", "mdp_essai", "test", "test"], saisies
        )

    def test_sans_repli_un_refus_rend_faux_sans_retenter(self):
        rendu, essais, _saisies, outil = self.lancer([False], no_try_test=True)
        self.assertFalse(rendu)
        self.assertEqual(1, essais)
        outil.check_bot_chat_and_close.assert_not_called()

    def test_deux_refus_rendent_faux(self):
        rendu, essais, _saisies, _outil = self.lancer([False, False])
        self.assertFalse(rendu)
        self.assertEqual(2, essais)


class FauxPiloteFenetres:
    """Garde sa fenêtre `interrogations` lectures, puis n'en a plus.

    Avec `leve`, la lecture qui suit la fermeture lève au lieu de rendre une
    liste vide : c'est ce que fait un pilote dont la session a pris fin.
    """

    def __init__(self, interrogations, leve=False):
        self.restantes = interrogations
        self.leve = leve
        self.lectures = 0
        self.quit = mock.Mock()

    @property
    def window_handles(self):
        self.lectures += 1
        if self.restantes > 0:
            self.restantes -= 1
            return ["fenetre-essai"]
        if self.leve:
            raise WebDriverException("session terminée")
        return []


class TestGarderOuvert(unittest.TestCase):
    def setUp(self):
        patcheur = mock.patch.object(web_login.time, "sleep")
        self.sommeil = patcheur.start()
        self.addCleanup(patcheur.stop)
        patcheur = mock.patch("builtins.print")
        patcheur.start()
        self.addCleanup(patcheur.stop)

    def garder(self, pilote, terminal, saisie=None, headless=False):
        with (
            mock.patch.object(
                web_login, "stdin_est_un_terminal", return_value=terminal
            ),
            mock.patch("builtins.input", side_effect=saisie) as entree,
        ):
            web_login.garder_ouvert(pilote, headless=headless, pas=0.5)
        return entree

    def test_avec_un_terminal_demande_entree(self):
        pilote = FauxPiloteFenetres(3)
        entree = self.garder(pilote, terminal=True, saisie=[""])
        entree.assert_called_once()
        self.assertEqual(0, pilote.lectures)
        pilote.quit.assert_called_once()

    def test_sans_terminal_attend_la_fermeture_de_la_fenetre(self):
        pilote = FauxPiloteFenetres(3)
        entree = self.garder(pilote, terminal=False)
        entree.assert_not_called()
        self.assertEqual(4, pilote.lectures)
        self.assertEqual(3, self.sommeil.call_count)
        self.sommeil.assert_called_with(0.5)
        pilote.quit.assert_called_once()

    def test_sans_terminal_une_session_terminee_met_fin_a_l_attente(self):
        pilote = FauxPiloteFenetres(2, leve=True)
        entree = self.garder(pilote, terminal=False)
        entree.assert_not_called()
        self.assertEqual(3, pilote.lectures)

    def test_sans_terminal_ni_fenetre_visible_n_attend_pas(self):
        pilote = FauxPiloteFenetres(3)
        entree = self.garder(pilote, terminal=False, headless=True)
        entree.assert_not_called()
        self.assertEqual(0, pilote.lectures)
        pilote.quit.assert_called_once()

    def test_fin_d_entree_termine_proprement(self):
        pilote = FauxPiloteFenetres(3)
        self.garder(pilote, terminal=True, saisie=EOFError)
        pilote.quit.assert_called_once()

    def test_ctrl_c_au_terminal_termine_proprement(self):
        pilote = FauxPiloteFenetres(3)
        self.garder(pilote, terminal=True, saisie=KeyboardInterrupt)
        pilote.quit.assert_called_once()

    def test_ctrl_c_pendant_l_attente_termine_proprement(self):
        pilote = FauxPiloteFenetres(10)
        self.sommeil.side_effect = [None, KeyboardInterrupt]
        self.garder(pilote, terminal=False)
        self.assertEqual(2, pilote.lectures)
        pilote.quit.assert_called_once()

    def test_un_pilote_deja_ferme_ne_fait_pas_echouer_la_sortie(self):
        pilote = FauxPiloteFenetres(0)
        pilote.quit.side_effect = WebDriverException("déjà fermé")
        self.garder(pilote, terminal=False)
        pilote.quit.assert_called_once()


class TestStdinEstUnTerminal(unittest.TestCase):
    def test_un_tube_n_est_pas_un_terminal(self):
        lecture, ecriture = os.pipe()
        self.addCleanup(os.close, ecriture)
        with open(lecture) as tube, mock.patch.object(sys, "stdin", tube):
            self.assertFalse(web_login.stdin_est_un_terminal())

    def test_une_entree_absente_ou_fermee_n_est_pas_un_terminal(self):
        with mock.patch.object(sys, "stdin", None):
            self.assertFalse(web_login.stdin_est_un_terminal())
        lecture, ecriture = os.pipe()
        os.close(ecriture)
        tube = open(lecture)
        tube.close()
        with mock.patch.object(sys, "stdin", tube):
            self.assertFalse(web_login.stdin_est_un_terminal())

    def test_un_terminal_en_est_un(self):
        entree = mock.Mock()
        entree.isatty.return_value = True
        with mock.patch.object(sys, "stdin", entree):
            self.assertTrue(web_login.stdin_est_un_terminal())


if __name__ == "__main__":
    unittest.main()
