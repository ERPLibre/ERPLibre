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


class TestLeBancDansLeMenuDesEpreuvesLongues(unittest.TestCase):
    """Le banc n'est pas une descente : ni profondeur, ni hôte de départ. Il
    prend un TERRAIN, qui est une grappe déjà là."""

    def test_its_real_run_asks(self):
        """Il crée de vraies VM sur une grappe : une frappe ne doit pas
        suffire."""
        todo, patch = menu(reponse=True)
        with patch as confirm:
            todo._longtest_run("setops_banc.py", "")
        self.assertTrue(confirm.called)
        self.assertEqual(1, len(todo.execute.commandes))

    def test_its_plan_does_not_ask(self):
        """Il ne crée rien : demander l'aurait rendue machinale."""
        todo, patch = menu()
        with patch as confirm:
            todo._longtest_run("setops_banc.py", "--dry-run")
        self.assertFalse(confirm.called)

    def test_a_refusal_launches_nothing(self):
        todo, patch = menu(reponse=False)
        with patch:
            todo._longtest_run("setops_banc.py", "")
        self.assertEqual([], todo.execute.commandes)

    def test_the_bench_is_in_the_undoable_scripts(self):
        """Sans quoi l'écran de défaite ne l'appellerait pas, et ce qu'il a posé
        ne se défairait que depuis la ligne de commande."""
        from script.todo.longtest_menu import SCRIPTS_DEFAISABLES

        self.assertIn("setops_banc.py", SCRIPTS_DEFAISABLES)

    def test_a_named_terrain_reaches_the_command(self):
        """NOMMÉ PLUTÔT QUE DEVINÉ, quand on veut : une grappe qu'on possède se
        désigne, là où le banc déduit le dernier étage du labo."""
        todo, patch = menu()
        with (
            patch,
            mock.patch("builtins.input", return_value="  une-grappe-a-moi  "),
        ):
            args = todo._longtest_terrain_banc()
        self.assertEqual(" --terrain une-grappe-a-moi", args)

    def test_an_empty_answer_lets_the_bench_deduce(self):
        """Le contrôle positif : sans lui, un argument toujours ajouté
        passerait l'épreuve ci-dessus."""
        todo, patch = menu()
        with patch, mock.patch("builtins.input", return_value="   "):
            self.assertEqual("", todo._longtest_terrain_banc())

    def test_a_terrain_with_a_space_is_quoted(self):
        """Il finit dans une ligne de commande : non cité, un nom à espace la
        couperait en deux arguments."""
        todo, patch = menu()
        with patch, mock.patch("builtins.input", return_value="deux mots"):
            args = todo._longtest_terrain_banc()
        self.assertIn("'deux mots'", args)


class TestChaqueNumeroDuMenuMeneQuelquePart(unittest.TestCase):
    """Un numéro aiguillé mais non listé est INATTEIGNABLE ; un numéro listé mais
    non aiguillé répond « commande introuvable ». Ce fichier porte déjà la trace
    d'une fois où deux entrées sont devenues inatteignables parce qu'un autre
    groupe occupait leurs numéros et était interrogé avant elles."""

    def combien(self):
        """Le nombre d'entrées que l'écran propose, lu dans son code."""
        import inspect

        from script.todo import longtest_menu

        source = inspect.getsource(longtest_menu.LongTestMenuMixin)
        debut = source.find("choices = [")
        fin = source.find("# Le cache n", debut)
        return source[debut:fin].count("prompt_description")

    def mene(self, numero):
        """Ce que ce numéro déclenche : la commande lancée, ou « defaire »."""
        todo = TODO.__new__(TODO)
        todo.execute = FauxExecute()
        vus = []
        with (
            mock.patch.object(
                TODO, "fill_help_info", return_value="?", create=True
            ),
            mock.patch(
                "script.todo.longtest_menu.click.prompt",
                side_effect=[numero, "0"],
            ),
            # CONFIRMÉ, et c'est ce qui rend l'épreuve possible : refusée, une
            # vraie exécution ne lance rien — et « rien lancé » se confondrait
            # alors avec « le numéro ne mène nulle part ». L'exécuteur est un
            # faux, donc aucune machine n'est créée.
            mock.patch(
                "script.todo.longtest_menu.click.confirm", return_value=True
            ),
            mock.patch("builtins.input", return_value=""),
            mock.patch.object(
                TODO,
                "_longtest_defaire",
                lambda _self: vus.append("defaire"),
                create=True,
            ),
            mock.patch.object(
                TODO, "_longtest_depth", lambda _self: 1, create=True
            ),
            mock.patch.object(
                TODO, "_longtest_depart", lambda _self, _s: "", create=True
            ),
            mock.patch.object(
                TODO, "_longtest_depart_nixos", lambda _self: "", create=True
            ),
        ):
            todo.prompt_execute_longtest()
        return vus + [c for c in todo.execute.commandes]

    def test_every_listed_number_leads_somewhere(self):
        """LA PROPRIÉTÉ : aucune entrée listée ne répond « introuvable ». Le
        refus de confirmation ne lance rien, donc un plan à blanc ou la défaite
        sont les traces qu'on attend ; ce qui compte est qu'un numéro ne tombe
        jamais dans la branche finale."""
        muet = []
        for numero in range(1, self.combien() + 1):
            with self.subTest(numero=numero):
                mene = self.mene(str(numero))
                if not mene:
                    muet.append(numero)
        self.assertEqual(
            [],
            muet,
            f"ces numéros sont listés mais ne mènent nulle part : {muet}",
        )

    def test_a_number_beyond_the_list_leads_nowhere(self):
        """Le contrôle positif : sans lui, un écran qui lance toujours quelque
        chose passerait l'épreuve ci-dessus."""
        self.assertEqual([], self.mene(str(self.combien() + 1)))

    def test_the_bench_is_reachable(self):
        """Nommément, et non par le seul compte : c'est lui qu'on vient d'y
        brancher."""
        lances = [
            c
            for numero in range(1, self.combien() + 1)
            for c in self.mene(str(numero))
            if isinstance(c, str) and "setops_banc.py" in c
        ]
        self.assertNotEqual([], lances)


if __name__ == "__main__":
    unittest.main()
