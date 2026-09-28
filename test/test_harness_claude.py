#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les cinq sous-commandes d'un agent détaché, et ce qu'elles coûtent.

Ces tests ne vérifient pas qu'une commande marche — c'est le CLI qui répond de
ça — mais que le menu ne peut pas en construire une qui détruise plus que ce
qu'il annonce. Trois choses, donc :

`--discard-unpushed` ne se construit JAMAIS. Le drapeau jette les commits non
poussés d'un arbre de travail, et le CLI n'accepte que la valeur qu'un `rm`
précédent rapporte lui-même — un menu qui la fabriquerait détruirait du
travail sur une valeur devinée.

Le niveau de confirmation suit le DOMMAGE et non l'habitude. `stop` garde la
conversation et se répare d'un `attach` ; `respawn` coupe le travail en
cours ; `rm` supprime la session et son arbre, et rien ne la récupère. Les
trois n'appellent donc pas la même question.

Et un agent d'arrière-plan se distingue d'un terminal : le premier se pilote
par ces cinq commandes, le second se reprend par `--resume` et se questionne
par une copie branchée. Confondre les deux ferait proposer `stop` sur le
terminal où l'on travaille.
"""

import unittest

from script.todo.assistant.harness import claude as C


class Session:
    """Ce que le registre rend, réduit au champ qui décide."""

    def __init__(self, kind):
        self.kind = kind


class TestLArgvDeListage(unittest.TestCase):
    def test_the_listing_asks_for_json(self):
        self.assertEqual(C.argv_lister(), ["claude", "agents", "--json"])

    def test_the_finished_ones_are_asked_for_explicitly(self):
        """Une session sortie laisse un arbre de travail que `rm` nettoie.

        La taire laisserait un répertoire que rien ne propose de retirer."""
        self.assertEqual(C.argv_lister(terminees=True)[-1], "--all")

    def test_the_listing_needs_no_terminal(self):
        """`--json` est ce qui rend la sortie lisible sans TTY."""
        self.assertIn("--json", C.argv_lister())


class TestLArgvDAction(unittest.TestCase):
    def test_each_subcommand_builds_three_words(self):
        for sous in (
            C.JOURNAL,
            C.ATTACHER,
            C.ARRETER,
            C.RELANCER,
            C.SUPPRIMER,
        ):
            argv = C.argv_action(sous, "11d6eefb-242a-44c8-bc4d-2757747eefed")
            self.assertEqual(len(argv), 3, sous)
            self.assertEqual(argv[0], "claude")
            self.assertEqual(argv[1], sous)

    def test_the_full_identifier_is_passed(self):
        """La forme courte affichée est un préfixe, jamais ce qui est passé."""
        argv = C.argv_action(C.JOURNAL, "11d6eefb-242a-44c8")
        self.assertEqual(argv[2], "11d6eefb-242a-44c8")

    def test_no_flag_is_ever_added(self):
        """Surtout pas `--discard-unpushed`, qui jette des commits."""
        for sous in (C.SUPPRIMER, C.RELANCER, C.ARRETER):
            argv = C.argv_action(sous, "un-identifiant")
            self.assertEqual([m for m in argv if m.startswith("--")], [])

    def test_an_unknown_subcommand_is_refused(self):
        """Une faute de frappe ne doit pas devenir une commande lancée."""
        with self.assertRaises(ValueError):
            C.argv_action("kill", "un-identifiant")
        with self.assertRaises(ValueError):
            C.argv_action("", "un-identifiant")

    def test_an_empty_identifier_is_refused(self):
        """Sans identifiant, `claude rm` prendrait autre chose pour cible."""
        with self.assertRaises(ValueError):
            C.argv_action(C.SUPPRIMER, "")
        with self.assertRaises(ValueError):
            C.argv_action(C.SUPPRIMER, None)


class TestLeNiveauDeConfirmation(unittest.TestCase):
    def test_reading_asks_nothing(self):
        self.assertEqual(C.confirmation_exigee(C.JOURNAL), "rien")
        self.assertEqual(C.confirmation_exigee(C.ATTACHER), "rien")

    def test_stopping_asks_nothing(self):
        """La conversation est gardée et un `attach` la rouvre."""
        self.assertEqual(C.confirmation_exigee(C.ARRETER), "rien")

    def test_restarting_asks_for_a_yes(self):
        """Le travail en cours est coupé : ça se demande, ça ne se retape pas."""
        self.assertEqual(C.confirmation_exigee(C.RELANCER), "oui")

    def test_deleting_asks_for_the_identifier(self):
        """Rien ne récupère une session supprimée, ni son arbre de travail.

        Une frappe sur « o » se donne par réflexe ; recopier un identifiant
        oblige à regarder ce qu'on détruit."""
        self.assertEqual(C.confirmation_exigee(C.SUPPRIMER), "id")

    def test_the_irreversible_one_is_the_deletion(self):
        self.assertEqual(C.IRREVERSIBLE, C.SUPPRIMER)
        self.assertIn(C.SUPPRIMER, C.DESTRUCTRICES)


class TestArrierePlanOuTerminal(unittest.TestCase):
    def test_an_interactive_session_is_not_a_background_agent(self):
        """Proposer `stop` sur le terminal où l'on travaille serait un piège."""
        self.assertFalse(C.est_arriere_plan(Session("interactive")))

    def test_every_other_kind_is_piloted_by_these_commands(self):
        """Le binaire connaît cinq genres ; quatre ne sont pas un terminal."""
        for genre in ("background", "detached", "remote", "cloud"):
            self.assertTrue(C.est_arriere_plan(Session(genre)), genre)

    def test_a_session_without_a_kind_is_not_interactive(self):
        """Un registre qui omet le champ ne doit pas faire passer une session
        pour le terminal courant."""

        class Sans:
            pass

        self.assertTrue(C.est_arriere_plan(Sans()))


if __name__ == "__main__":
    unittest.main()
