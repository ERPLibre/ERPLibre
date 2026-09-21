#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Détruire une VM Proxmox par son VMID, avec la preuve que c'est la bonne.

Un VMID libéré est RÉATTRIBUÉ. Détruire « le 101 » d'un écran vieux de trois
questions, c'est détruire ce qui porte le 101 maintenant — et ici avec ses
disques ET ses entrées de sauvegarde, puisque « --purge » les emporte.

LE NOM ÉTAIT EN MAIN ET JETÉ. L'écran l'affiche à la ligne d'avant, dans
« 101 (nom) », puis n'appelait la destruction qu'avec le VMID.

UNE SEULE COMMANDE. La suite était rendue en deux morceaux, joués par deux
appels : deux shells distants, où le « exit 1 » du garde ne fermait que le
premier — la destruction partait quand même.

Ce chemin n'avait AUCUNE épreuve. Rien ne touche à un hôte : la sélection,
les questions et l'exécution sont remplacées.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402


def menu_avec(vms, oui=True):
    """Une instance TODO dont la sélection et l'exécution sont des faits."""
    todo = TODO.__new__(TODO)
    todo._pve_pick_vm = lambda titre="", multiple=False: list(vms)
    todo._is_yes = lambda _rep: oui
    todo.jouees = []
    todo._pve_show = lambda cmd, timeout=120, quiet=False: (
        todo.jouees.append(cmd) or (0, "")
    )
    return todo


def jouer(todo):
    import builtins
    import io
    from contextlib import redirect_stdout

    vrai = builtins.input
    builtins.input = lambda *_a, **_k: ""
    tampon = io.StringIO()
    try:
        with redirect_stdout(tampon):
            todo._pve_delete()
    finally:
        builtins.input = vrai
    return tampon.getvalue()


class TestLeGardeEstSurLeChemin(unittest.TestCase):
    def test_the_command_refuses_before_it_destroys(self):
        todo = menu_avec([{"vmid": 101, "name": "vm-essai"}])
        jouer(todo)
        self.assertEqual(1, len(todo.jouees), todo.jouees)
        cmd = todo.jouees[0]
        self.assertLess(cmd.index("REFUS"), cmd.index("qm destroy"))

    def test_the_name_that_was_displayed_is_the_one_that_proves(self):
        """Il est en main depuis la liste ; le jeter laissait détruire ce
        qui porte ce VMID maintenant."""
        todo = menu_avec([{"vmid": 101, "name": "vm-essai"}])
        jouer(todo)
        self.assertIn("vm-essai", todo.jouees[0])

    def test_one_call_per_vm_and_not_two(self):
        """Deux appels sont deux shells distants : le « exit 1 » du garde
        ne ferme que le premier."""
        todo = menu_avec(
            [
                {"vmid": 101, "name": "vm-a"},
                {"vmid": 102, "name": "vm-b"},
            ]
        )
        jouer(todo)
        self.assertEqual(2, len(todo.jouees))
        for cmd in todo.jouees:
            self.assertIn("qm stop", cmd)
            self.assertIn("qm destroy", cmd)

    def test_each_vm_gets_its_own_proof(self):
        todo = menu_avec(
            [
                {"vmid": 101, "name": "vm-a"},
                {"vmid": 102, "name": "vm-b"},
            ]
        )
        jouer(todo)
        self.assertIn("vm-a", todo.jouees[0])
        self.assertNotIn("vm-b", todo.jouees[0])
        self.assertIn("vm-b", todo.jouees[1])


class TestSansPreuveRienNePart(unittest.TestCase):
    def test_a_vm_without_a_name_is_refused_and_named(self):
        """Un écran qui vient de lister a le nom : son absence décrit une
        lecture cassée, et retomber sur le VMID seul serait un échec
        OUVERT."""
        todo = menu_avec([{"vmid": 101, "name": ""}])
        vu = jouer(todo)
        self.assertEqual([], todo.jouees)
        self.assertIn("101", vu)

    def test_a_vm_whose_name_is_only_spaces_is_refused_too(self):
        todo = menu_avec([{"vmid": 101, "name": "   "}])
        jouer(todo)
        self.assertEqual([], todo.jouees)

    def test_the_others_are_still_destroyed(self):
        """Contrôle positif : une VM sans nom ne doit pas fermer celles qui
        en ont un."""
        todo = menu_avec(
            [
                {"vmid": 101, "name": ""},
                {"vmid": 102, "name": "vm-b"},
            ]
        )
        jouer(todo)
        self.assertEqual(1, len(todo.jouees))
        self.assertIn("vm-b", todo.jouees[0])


class TestRienNestFaitSansConfirmation(unittest.TestCase):
    def test_a_refused_confirmation_destroys_nothing(self):
        todo = menu_avec([{"vmid": 101, "name": "vm-essai"}], oui=False)
        jouer(todo)
        self.assertEqual([], todo.jouees)

    def test_nothing_selected_destroys_nothing(self):
        todo = menu_avec([])
        jouer(todo)
        self.assertEqual([], todo.jouees)


if __name__ == "__main__":
    unittest.main()
