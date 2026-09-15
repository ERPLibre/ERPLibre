#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un test long ne se lance pas sur une seule frappe.

Ces scripts créent de vraies machines et durent. Le menu affichait la
commande puis l'exécutait aussitôt : un chiffre tapé de travers partait donc
créer trois VM, et il n'y avait plus qu'à attendre pour les détruire.

La question n'est pas posée pour tout : un plan à blanc ou un rapport ne crée
rien, et une invite qu'on apprend à confirmer sans lire ne protège plus rien
le jour où elle compte. Le partage se fait sur les arguments, et ce test le
vérifie dans les deux sens.
"""

import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from script.todo import todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402


class FauxExecute:
    """Retient ce qu'on lui demande de lancer, sans rien lancer."""

    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **_kw):
        self.commandes.append(cmd)


def menu(reponse=True):
    todo = TODO.__new__(TODO)
    todo.execute = FauxExecute()
    return todo, mock.patch(
        "script.todo.longtest_menu.click.confirm", return_value=reponse
    )


class TestConfirmationDesTestsLongs(unittest.TestCase):
    def test_une_vraie_execution_demande(self):
        todo, patch = menu(reponse=True)
        with patch as confirm:
            todo._longtest_run("qemu_cache.py", "")
        self.assertTrue(confirm.called, "aucune confirmation demandée")
        self.assertEqual(len(todo.execute.commandes), 1)

    def test_un_refus_ne_lance_rien(self):
        todo, patch = menu(reponse=False)
        with patch:
            todo._longtest_run("qemu_cache.py", "")
        self.assertEqual(
            todo.execute.commandes, [], "le test a démarré malgré le refus"
        )

    def test_le_plan_a_blanc_ne_demande_pas(self):
        """Il ne crée rien : demander l'aurait rendue machinale."""
        todo, patch = menu()
        with patch as confirm:
            todo._longtest_run("qemu_cache.py", "--dry-run")
        self.assertFalse(confirm.called)
        self.assertEqual(len(todo.execute.commandes), 1)

    def test_le_rapport_ne_demande_pas(self):
        todo, patch = menu()
        with patch as confirm:
            todo._longtest_run("qemu_cache.py", "--rapport")
        self.assertFalse(confirm.called)
        self.assertEqual(len(todo.execute.commandes), 1)

    def test_un_appelant_peut_couper_la_question(self):
        """La destruction pose déjà la sienne : la doubler ferait répondre
        deux fois à la même chose."""
        todo, patch = menu()
        with patch as confirm:
            todo._longtest_run("qemu_cache.py", "--detruire", demander=False)
        self.assertFalse(confirm.called)
        self.assertEqual(len(todo.execute.commandes), 1)

    def test_la_question_dit_ce_qui_va_arriver(self):
        """Détruire n'est pas lancer.

        L'invite était la même pour les deux : « Cela crée de vraies VM…
        Lancer ce test long ? » s'affichait devant « --detruire », qui efface
        des machines et leurs disques. On répondait oui à autre chose que ce
        qui allait arriver, et c'est l'acte le moins rattrapable des deux.
        """
        todo, patch = menu()
        with patch as confirm:
            todo._longtest_run("qemu_cache.py", "--detruire")
        pose = confirm.call_args.args[0]
        self.assertIn("Détruire", pose, f"question posée : {pose}")
        self.assertNotIn("Lancer", pose)

    def test_une_creation_pose_toujours_la_sienne(self):
        todo, patch = menu()
        with patch as confirm:
            todo._longtest_run("qemu_cache.py", "--sans-cache")
        pose = confirm.call_args.args[0]
        self.assertIn("Lancer", pose, f"question posée : {pose}")

    def test_les_deux_avertissements_different(self):
        """L'un annonce une création, l'autre un effacement : les confondre
        est ce qui rend une confirmation machinale."""
        from script.todo.longtest_menu import LongTestMenuMixin as L

        creer = L._longtest_question("")
        defaire = L._longtest_question("--detruire")
        self.assertNotEqual(creer, defaire)
        for cle in creer + defaire:
            self.assertIn(
                cle,
                todo_i18n.TRANSLATIONS,
                f"« {cle} » n'est pas une clé de traduction",
            )

    def test_la_commande_reste_affichee(self):
        """Elle l'était déjà, et c'est ce qui rend la question répondable."""
        todo, patch = menu()
        with patch, mock.patch("builtins.print") as ecrit:
            todo._longtest_run("qemu_cache.py", "--dry-run")
        dit = " ".join(str(a) for c in ecrit.call_args_list for a in c.args)
        self.assertIn("qemu_cache.py --dry-run", dit)

    def test_la_destruction_ne_demande_pas_deux_fois(self):
        """Les deux appels de _longtest_defaire portent demander=False."""
        src = (RACINE / "script" / "todo" / "longtest_menu.py").read_text(
            encoding="utf-8"
        )
        bloc = src[
            src.index("def _longtest_defaire") : src.index(
                "def _longtest_depart"
            )
        ]
        for appel in ("--detruire --dry-run", '"--detruire"'):
            self.assertIn(
                "demander=False",
                bloc,
                f"l'appel {appel} de la destruction pose une seconde question",
            )


if __name__ == "__main__":
    unittest.main()
