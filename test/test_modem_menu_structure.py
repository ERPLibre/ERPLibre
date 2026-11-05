#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La structure des menus du modem : neuf entrees au premier ecran, rien
d'inatteignable, et chaque choix numerote revient AVANT d'agir sur [0],
une reponse vide ou Ctrl+D.

Un menu se reorganise rarement, et c'est justement le moment ou une entree se
perd : elle disparait de l'ecran sans que rien ne le signale. Aucun test ne
touche un modem, un port serie, ModemManager ni un service : chaque fonction
qui les atteindrait est doublee.
"""

import io
import os
import sys
import unittest
from contextlib import ExitStack, redirect_stdout
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from script.todo.menus import modem as menus_modem  # noqa: E402
from script.todo.modem import menu  # noqa: E402
from script.todo.ui.navigator import navigate  # noqa: E402
from script.todo.ui.registry import Entry, Menu  # noqa: E402

#: Tout ce que les menus du modem doivent rendre atteignable, premier ecran
#: et sous-menus : les fonctions de `modem/menu.py` que leurs actions
#: appellent.
ACTIONS = {
    "_clavier",
    "_etat_detaille",
    "_diagnostic",
    "_appeler",
    "_raccrocher",
    "_lister_appels",
    "_appel_voip",
    "_envoyer_sms",
    "_lister_sms",
    "_passerelle",
    "_sonder_audio",
    "_essai_combine",
    "_basculer_uac",
    "_regle_audio",
    "_regle_udev",
    "_installer_voip",
    "_etat_voip",
    "_declarer_softphone",
    "_service_etat",
    "_service_environnement",
    "_service_poser",
    "_service_commander",
    "_service_journal",
    "_service_retirer",
    "_repondeur_messages",
    "_repondeur_enregistrer_annonce",
    "_repondeur_jouer_annonce",
    "_repondeur_sonneries",
    "_repondeur_basculer",
    "_repondeur_code",
    "_repondeur_remettre_code",
    "_repondeur_recuperer",
}

#: Les menus declares de `menus/modem.py` qu'ouvre le premier ecran.
SOUS_MENUS = (
    menus_modem.MODEM_STATE,
    menus_modem.MODEM_CALLS,
    menus_modem.MODEM_SMS,
    menus_modem.MODEM_ANSWERING,
    menus_modem.MODEM_AUDIO,
    menus_modem.MODEM_VOIP,
    menus_modem.MODEM_SERVICE,
)


class Faux(menu.ModemMenuMixin):
    """Les menus du modem sur un objet qui n'est pas TODO : son en-tete est
    une chaine fixe, et chaque dessin garde les libelles montres."""

    def __init__(self):
        self.dessins = []

    def fill_help_info(self, choices, state=None):
        self.dessins.append([c.get("prompt_description") for c in choices])
        return "menu"


def _menus_atteints():
    """Les menus declares qu'atteint le premier ecran, lui compris."""
    par_nom = {
        m.name: m for m in vars(menus_modem).values() if isinstance(m, Menu)
    }
    atteints, a_voir = [], [menus_modem.MODEM]
    while a_voir:
        courant = a_voir.pop()
        atteints.append(courant)
        for entree in courant.entries:
            if isinstance(entree, Entry) and entree.action in par_nom:
                a_voir.append(par_nom[entree.action])
    return atteints


class TestStructure(unittest.TestCase):
    def test_le_premier_ecran_tient_en_neuf_entrees(self):
        """Dix-huit entrees demandaient de lire l'ecran pour en trouver une.

        La neuvieme ouvre la demonstration de la passerelle du modem. Elle est
        au premier ecran et non dans le sous-menu SMS : elle installe un Odoo
        et le relie au modem, ce qui n'est pas un geste de messagerie.
        """
        entrees = [e.action for e in menus_modem.MODEM.entries]
        self.assertEqual(len(entrees), 9)
        self.assertEqual(entrees[-1], "_modem_gateway")
        self.assertEqual(menus_modem.MODEM.state, "_modem_banner")

    def test_rien_ne_s_est_perdu_dans_le_rangement(self):
        # Chaque action est une methode du mixin, qui appelle la fonction du
        # module par son nom : ce nom est dans les siens.
        atteignables = set()
        for declare in _menus_atteints():
            for entree in declare.entries:
                methode = getattr(menu.ModemMenuMixin, entree.action)
                atteignables |= set(methode.__code__.co_names)
        self.assertEqual(ACTIONS - atteignables, set())

    def test_chaque_sous_menu_porte_un_segment_et_des_entrees(self):
        atteints = {m.name for m in _menus_atteints()}
        for sous_menu in SOUS_MENUS:
            with self.subTest(menu=sous_menu.name):
                self.assertIn(sous_menu.name, atteints)
                self.assertTrue(sous_menu.crumb)
                self.assertTrue(sous_menu.entries)

    def test_le_choix_appelle_l_action_de_sa_ligne(self):
        """La numerotation se deduit de l'ordre : une entree ajoutee au milieu
        ne peut pas se brancher sur l'action d'une autre."""
        with mock.patch.object(
            menu, "_raccrocher"
        ) as raccrocher, mock.patch.object(
            menu, "_appeler"
        ) as appeler, mock.patch(
            "click.prompt", side_effect=["2", "0"]
        ), redirect_stdout(
            io.StringIO()
        ):
            navigate(Faux(), menus_modem.MODEM_CALLS)
        raccrocher.assert_called_once_with()
        appeler.assert_not_called()

    def test_un_choix_hors_liste_ne_fait_rien(self):
        noms = ("_appeler", "_raccrocher", "_lister_appels", "_appel_voip")
        with ExitStack() as pile:
            doubles = [
                pile.enter_context(mock.patch.object(menu, nom))
                for nom in noms
            ]
            pile.enter_context(
                mock.patch("click.prompt", side_effect=["9", "x", "0"])
            )
            pile.enter_context(redirect_stdout(io.StringIO()))
            navigate(Faux(), menus_modem.MODEM_CALLS)
        for double in doubles:
            double.assert_not_called()

    def test_le_service_commande_chaque_action_par_son_entree(self):
        with mock.patch.object(
            menu, "_service_commander"
        ) as commander, mock.patch(
            "click.prompt", side_effect=["4", "7", "0"]
        ), redirect_stdout(
            io.StringIO()
        ):
            navigate(Faux(), menus_modem.MODEM_SERVICE)
        self.assertEqual(
            [appel.args for appel in commander.call_args_list],
            [("start",), ("disable",)],
        )

    def test_les_etats_restent_visibles_au_premier_ecran(self):
        """Ils vivaient a cote de leurs entrees, parties en sous-menu : savoir
        d'un coup d'oeil que le repondeur est eteint evite d'attendre en vain
        un message."""
        with mock.patch.object(
            menu, "_etat_repondeur", return_value="eteint"
        ), mock.patch.object(
            menu, "_etat_regle_audio", return_value="posee"
        ), mock.patch.object(
            menu, "_etat_messagerie", return_value="📭"
        ), mock.patch.object(
            menu.device_mod, "premier_modem", return_value=0
        ), mock.patch.object(
            menu.device_mod, "etat", return_value={}
        ), mock.patch.object(
            menu.calls_mod, "voix_disponible", return_value=(True, "")
        ), mock.patch.object(
            menu.udev_mod, "port_reserve", return_value="/dev/x"
        ):
            bandeau = menu._bandeau()
        self.assertIn("eteint", bandeau)
        self.assertIn("posee", bandeau)

    def test_le_repondeur_dit_son_etat_et_celui_du_code_sans_le_coffre(self):
        """L'etat du repondeur sous le fil d'Ariane, celui du code de la
        messagerie entre parentheses : le coffre ferme ne s'ouvre pas pour
        un simple affichage."""
        faux = Faux()
        faux.kdbx_manager = mock.Mock(_kdbx=None)
        with mock.patch.object(
            menu, "_etat_repondeur", return_value="eteint"
        ), mock.patch.object(
            menu.rep_mod, "lire", return_value={}
        ), mock.patch.object(
            menu, "_etat_nip_du_service", return_value="?"
        ), mock.patch(
            "script.todo.modem.code_messagerie.coffre"
        ) as coffre, mock.patch(
            "click.prompt", side_effect=["0"]
        ), redirect_stdout(
            io.StringIO()
        ):
            self.assertIsNone(navigate(faux, menus_modem.MODEM_ANSWERING))
            etat = faux._modem_answering_state()
        coffre.assert_not_called()
        self.assertIn("eteint", etat)
        [dessin] = faux.dessins
        self.assertIn(
            f"{menu.t('modem_ans_pin')}  ({menu.t('modem_ans_pin_locked')})",
            dessin,
        )


class TestLesChoixReviennentAvantDAgir(unittest.TestCase):
    """[0], une reponse vide sans defaut ou Ctrl+D a un choix numerote :
    rien n'est ouvert, appele, joue, efface ni pose."""

    RETOURS = (["0"], [""], [EOFError()])

    def _repondre(self, reponses):
        """`input` repond `reponses` ; la sortie est jetee."""
        pile = ExitStack()
        pile.enter_context(mock.patch("builtins.input", side_effect=reponses))
        pile.enter_context(redirect_stdout(io.StringIO()))
        return pile

    def test_le_code_de_la_messagerie(self):
        for reponses in self.RETOURS:
            with self.subTest(reponses=reponses), self._repondre(
                reponses
            ), mock.patch(
                "script.todo.modem.code_messagerie.coffre"
            ) as coffre, mock.patch(
                "getpass.getpass"
            ) as secret:
                menu._repondeur_code(todo=None)
            coffre.assert_not_called()
            secret.assert_not_called()

    def test_la_recuperation_chez_l_operateur(self):
        for reponses in self.RETOURS:
            with self.subTest(reponses=reponses), self._repondre(
                reponses
            ), mock.patch.object(
                menu.device_mod, "port_reserve", return_value="/dev/p"
            ), mock.patch(
                "script.todo.modem.recuperation.ligne_occupee", return_value=""
            ), mock.patch.object(
                menu.mv_mod,
                "numero_messagerie",
                return_value=("+10000000000", ""),
            ), mock.patch(
                "os.path.exists", return_value=True
            ), mock.patch(
                "script.todo.modem.recuperation.jouer"
            ) as jouer, mock.patch(
                "script.todo.modem.code_messagerie.coffre"
            ) as coffre, mock.patch(
                "click.confirm"
            ) as confirme:
                menu._repondeur_recuperer(todo=None)
            jouer.assert_not_called()
            coffre.assert_not_called()
            confirme.assert_not_called()

    def test_les_trois_boites_de_messages(self):
        noms = (
            "_repondeur_messages_erplibre",
            "_repondeur_messagerie_operateur",
            "_repondeur_messages_recuperes",
        )
        for reponses in [*self.RETOURS, ["3"]]:
            with self.subTest(reponses=reponses), self._repondre(
                reponses
            ), ExitStack() as pile:
                pile.enter_context(
                    mock.patch.object(menu.rep_mod, "lister", return_value=[])
                )
                pile.enter_context(
                    mock.patch(
                        "script.todo.modem.recuperation.lister_messages",
                        return_value=[],
                    )
                )
                pile.enter_context(
                    mock.patch.object(
                        menu, "_etat_messagerie", return_value="?"
                    )
                )
                doubles = [
                    pile.enter_context(mock.patch.object(menu, nom))
                    for nom in noms
                ]
                menu._repondeur_messages()
            appeles = [nom for nom, d in zip(noms, doubles) if d.called]
            self.assertEqual(
                appeles,
                ["_repondeur_messages_recuperes"] if reponses == ["3"] else [],
            )

    def test_un_message_du_repondeur_ou_recupere(self):
        message = {"fichier": "/forged/m.wav"}
        for reponses in self.RETOURS:
            with self.subTest(reponses=reponses), mock.patch.object(
                menu.rep_mod, "lister", return_value=[message]
            ), mock.patch.object(menu.rep_mod, "jouer") as jouer:
                with self._repondre(list(reponses)):
                    menu._repondeur_messages_erplibre()
                with self._repondre(list(reponses)):
                    menu._repondeur_messages_recuperes([message])
            jouer.assert_not_called()

    def test_l_installation_d_un_service_voip(self):
        todo = mock.Mock()
        for reponses in self.RETOURS:
            with self.subTest(reponses=reponses), self._repondre(
                reponses
            ), mock.patch.object(menu, "_installer_sipgo") as sipgo:
                menu._installer_voip(todo)
            sipgo.assert_not_called()
        todo._deploy_asterisk_server.assert_not_called()
        with self._repondre(["2"]):
            menu._installer_voip(todo)
        todo._deploy_asterisk_server.assert_called_once_with()

    def test_l_annonce_d_un_appel_et_d_une_sonde(self):
        # Le numero, puis l'annonce : [0] ou Ctrl+D a l'annonce ne posent
        # aucune autre question et n'appellent personne.
        for reponses in (["forged", "0"], ["forged", EOFError()]):
            with self.subTest(reponses=reponses), self._repondre(
                reponses
            ), mock.patch.object(
                menu.sipgo_mod, "installe", return_value=True
            ), mock.patch.object(
                menu.sipgo_mod, "sons_fournis", return_value=[]
            ), mock.patch.object(
                menu.sipgo_mod, "mode_pcm", return_value=2
            ), mock.patch.object(
                menu.calls_mod, "voix_disponible", return_value=(True, "")
            ), mock.patch.object(
                menu.calls_mod, "numero_valide", return_value="10000000000"
            ), mock.patch.object(
                menu.sipgo_mod, "appeler"
            ) as appeler, mock.patch.object(
                menu.sipgo_mod, "sonder"
            ) as sonder, mock.patch.object(
                menu, "_lancer_interruptible"
            ) as lancer, mock.patch(
                "click.confirm"
            ) as confirme:
                menu._appel_voip(todo=None)
            # La sonde demande son mode PCM entre le numero et l'annonce.
            with self.subTest(sonde=reponses), self._repondre(
                [reponses[0], "", reponses[1]]
            ), mock.patch.object(
                menu.sipgo_mod, "installe", return_value=True
            ), mock.patch.object(
                menu.sipgo_mod, "sons_fournis", return_value=[]
            ), mock.patch.object(
                menu.sipgo_mod, "mode_pcm", return_value=2
            ), mock.patch.object(
                menu.calls_mod, "numero_valide", return_value="10000000000"
            ), mock.patch.object(
                menu.sipgo_mod, "sonder"
            ) as sonde, mock.patch(
                "click.confirm"
            ) as confirme_sonde:
                menu._sonder_audio()
            for double in (
                appeler,
                sonder,
                lancer,
                confirme,
                sonde,
                confirme_sonde,
            ):
                double.assert_not_called()

    def test_l_annonce_choisie(self):
        # Une reponse vide garde le defaut marque, aucune annonce ; un son
        # livre rend son chemin ; « autre » demande le chemin d'un fichier.
        sons = ["/forged/sons/a.wav", "/forged/sons/b.wav"]
        cas = (
            ([""], ""),
            (["4"], ""),
            (["2"], sons[1]),
            (["3", ""], ""),
            (["3", "/forged/absent.wav"], ""),
            (["0"], None),
            ([EOFError()], None),
        )
        for reponses, attendu in cas:
            with self.subTest(reponses=reponses), self._repondre(
                reponses
            ), mock.patch.object(
                menu.sipgo_mod, "sons_fournis", return_value=sons
            ):
                self.assertEqual(menu._choisir_annonce(), attendu)

    def test_la_regle_udev(self):
        with ExitStack() as pile:
            for nom, valeur in (
                ("posee", False),
                ("port_reserve", None),
                ("cause_absence_lien", ""),
                ("port_libre", (True, "ok")),
            ):
                pile.enter_context(
                    mock.patch.object(menu.udev_mod, nom, return_value=valeur)
                )
            poser = pile.enter_context(
                mock.patch.object(
                    menu.udev_mod, "poser", return_value=(True, "")
                )
            )
            retirer = pile.enter_context(
                mock.patch.object(
                    menu.udev_mod, "retirer", return_value=(True, "")
                )
            )
            for reponses in self.RETOURS:
                with self.subTest(reponses=reponses), self._repondre(reponses):
                    menu._regle_udev()
            poser.assert_not_called()
            retirer.assert_not_called()
            with self._repondre(["2"]):
                menu._regle_udev()
            retirer.assert_called_once_with()
            poser.assert_not_called()


if __name__ == "__main__":
    unittest.main()
