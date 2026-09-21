#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un NOM de base ne prouve rien, et deux endroits le croyaient.

L'écran de duplication proposait « <source>_neutralize » comme nom par
défaut AVANT de demander s'il fallait neutraliser. Qui accepte le défaut
puis décline obtient une base au nom rassurant qui garde ses tâches
planifiées actives, son repli sur le « smtp_server » de la configuration
et ses clés de paiement vivantes — exactement ce que la docstring de la
méthode décrit comme le danger.

ET LE CODE S'Y TROMPAIT AUSSI. Le test de fumée décidait sur le nom, puis
s'authentifiait — « --internal-required » — donc exerçait le back-office
contre une base qui n'avait jamais été neutralisée.

L'autorité existe : « database.is_neutralized » dans `ir_config_parameter`
est le drapeau qu'Odoo pose lui-même, et le dépôt le lit déjà. C'est la
doctrine du garde d'exercice, qui interroge la base et non son nom.

Ni PostgreSQL ni Odoo : les invites sont simulées, la sonde est injectée.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo.database_manager import DatabaseManager  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

SOURCE = "base_de_banc"


class Execute:
    """Retient la commande, n'en lance aucune."""

    def __init__(self):
        self.commandes = []

    def exec_command_live(self, commande, **_options):
        self.commandes.append(commande)
        return 0, ""


def dupliquer(reponses):
    """Joue l'écran de duplication. Rend (commande, écran, gestionnaire)."""
    executeur = Execute()
    gestionnaire = DatabaseManager(executeur, lambda *_a, **_k: None)
    gestionnaire.select_database = lambda: SOURCE
    gestionnaire._report_neutralize = staticmethod(lambda _d: None)
    tampon = io.StringIO()
    with mock.patch("builtins.input", side_effect=list(reponses)):
        with redirect_stdout(tampon):
            gestionnaire.duplicate_database()
    commande = executeur.commandes[0] if executeur.commandes else ""
    return commande, tampon.getvalue()


class TestLeNomProposeSuitLaReponse(unittest.TestCase):
    """Le défaut offert ne doit pas promettre ce qu'on vient de décliner.

    L'ordre décide : la neutralisation se demande AVANT le nom, parce que
    c'est elle qui dit ce que ce nom a le droit d'annoncer.
    """

    def test_declining_never_offers_a_name_that_claims_it(self):
        """Taper Entrée sur le défaut est le geste le plus courant : c'est
        lui qui doit être sûr."""
        commande, _ecran = dupliquer(["n", ""])
        self.assertNotIn("--neutralize", commande)
        self.assertNotIn("_neutralize", commande)

    def test_accepting_still_offers_the_name_that_says_so(self):
        """Contrôle positif : retirer le suffixe partout priverait d'un
        nom qui dit vrai."""
        commande, _ecran = dupliquer(["", ""])
        self.assertIn("--neutralize", commande)
        self.assertIn(f"{SOURCE}_neutralize", commande)

    def test_a_typed_name_is_kept_as_typed(self):
        commande, _ecran = dupliquer(["n", "ma_copie"])
        self.assertIn("-d ma_copie", commande)

    def test_a_typed_name_that_lies_is_said_out_loud(self):
        """On ne refuse pas un nom choisi à la main — mais le taire
        laisserait la base mentir à qui la relira dans six mois."""
        _commande, ecran = dupliquer(["n", f"{SOURCE}_neutralize"])
        self.assertIn(t("This name says neutralized, and it is not."), ecran)

    def test_an_honest_typed_name_gets_no_such_warning(self):
        _commande, ecran = dupliquer(["n", "ma_copie"])
        self.assertNotIn(
            t("This name says neutralized, and it is not."), ecran
        )


class TestLeVerdictDeFumeeInterrogeLaBase(unittest.TestCase):
    """Le test de fumée décidait sur le NOM, puis s'authentifiait.

    « --internal-required » fait entrer dans le back-office avec
    l'utilisateur que la neutralisation pose. Accordé sur la foi d'un
    suffixe, il exerçait une base aux tâches planifiées actives et aux
    clés de paiement vivantes.

    « database.is_neutralized » est le drapeau qu'Odoo pose lui-même —
    l'autorité, que le dépôt lit déjà ailleurs. Une sonde ILLISIBLE ne
    vaut pas « neutralisée » : on prend alors la voie prudente, qui ne
    coûte qu'une couverture moindre.
    """

    def lancer(self, nom, drapeau):
        from script.analyse import monitoring
        from script.todo.todo_upgrade import TodoUpgrade

        outil = TodoUpgrade.__new__(TodoUpgrade)
        outil.ask_gate = lambda *_a, **_k: "y"
        lancees = []
        outil.run_tool = lambda _nom, cmd: lancees.append(cmd)
        tampon = io.StringIO()
        with mock.patch.object(
            monitoring, "neutralize_state", lambda *_a, **_k: {"flag": drapeau}
        ):
            with redirect_stdout(tampon):
                outil.prompt_smoke_public_url(nom)
        return (lancees[0] if lancees else ""), tampon.getvalue()

    def test_a_name_that_claims_it_does_not_win_over_the_flag(self):
        """LE CAS QUI COÛTE : la copie porte le suffixe et n'a jamais été
        neutralisée. S'y authentifier exerce une base vivante."""
        commande, _ecran = self.lancer("base_neutralize", 0)
        self.assertNotIn("--internal-required", commande)

    def test_a_name_that_says_nothing_does_not_lose_against_the_flag(self):
        """L'inverse coûte aussi : une base neutralisée sous un autre nom
        n'était testée qu'en pages publiques, et on croyait le back-office
        couvert."""
        commande, _ecran = self.lancer("copie_du_jour", 1)
        self.assertIn("--internal-required", commande)

    def test_an_unreadable_probe_takes_the_cautious_path(self):
        """Ni vrai ni faux : PostgreSQL injoignable, base absente, table
        qui n'existe pas. Se tromper vers « pages publiques seulement » ne
        coûte qu'une couverture moindre."""
        commande, ecran = self.lancer("base_neutralize", None)
        self.assertNotIn("--internal-required", commande)
        self.assertIn(t("Could not read the neutralization flag."), ecran)

    def test_the_screen_says_which_path_it_takes(self):
        """Un saut annoncé nulle part fait croire le back-office testé."""
        _commande, ecran = self.lancer("copie_du_jour", 1)
        self.assertTrue(ecran.strip())


if __name__ == "__main__":
    unittest.main()
