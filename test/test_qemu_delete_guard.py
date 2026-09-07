#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Effacer une VM depuis le menu, avec la preuve que c'est la bonne.

Le garde d'identité existait, il était éprouvé, et il n'était pas sur le
chemin qu'un opérateur emprunte : l'écran reconstruisait la commande à la
main — le même corps que le verbe, sans son garde — et le fichier n'importait
rien du paquet des backends.

UN NOM SE RÉEMPLOIE, UN UUID NON. Entre l'affichage de la liste et
l'exécution il y a trois questions : une fenêtre de durée humaine pendant
laquelle un nom peut cesser de désigner le même domaine. La preuve se lit
donc À L'AFFICHAGE : lue juste avant d'effacer, elle se comparerait à
elle-même.

UN MENU NE DÉSARME PAS. La bibliothèque tolère une preuve absente, et c'est
un choix écrit : sur un poste où l'on n'a pas pu la relever, mieux vaut la
prudence d'avant. Mais un domaine que l'inventaire vient d'énumérer porte
TOUJOURS son UUID : une preuve manquante ne décrit pas une station, elle
décrit une lecture cassée — typiquement l'URI implicite, qui rend une liste
vide sans erreur. Retomber sur le nom serait un échec OUVERT.

Rien ici ne touche à un hyperviseur : libvirt et l'exécution sont remplacés.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo.todo import TODO  # noqa: E402
from script.vm import backend as VM  # noqa: E402

# Deux domaines de banc, preuves inventées.
INVENTAIRE = (
    "aaaaaaaa-1111-2222-3333-444444444444 machine-a\n"
    "bbbbbbbb-1111-2222-3333-444444444444 machine-b\n"
)


class Bancal:
    """Une exécution de banc : elle retient, elle ne joue rien."""

    def __init__(self, code=0):
        self.vues = []
        self.code = code

    def exec_command_live(self, cmd, source_erplibre=True):
        self.vues.append(cmd)
        return self.code


def todo_avec(inventaire=INVENTAIRE, reponses=(), fichiers=()):
    """Une instance TODO dont l'inventaire, les invites et l'exécution sont
    remplacés par des faits."""
    todo = TODO.__new__(TODO)
    todo._qemu_list_vms = lambda: None
    todo._qemu_list_domains_proved = lambda: VM.parse_uuid_listing(inventaire)
    todo._qemu_list_domains = lambda: [
        d.name for d in VM.parse_uuid_listing(inventaire)
    ]
    todo._qemu_vm_own_files = lambda _nom: list(fichiers)
    todo.execute = Bancal()
    file = list(reponses)
    todo._file_de_reponses = file
    return todo


def jouer(todo, reponses):
    """Joue l'écran d'effacement avec une file de réponses, sans terminal."""
    import builtins
    import io
    from contextlib import redirect_stdout

    file = list(reponses)
    vrai_input = builtins.input
    builtins.input = lambda *_a, **_k: file.pop(0) if file else ""
    tampon = io.StringIO()
    try:
        with redirect_stdout(tampon):
            todo._qemu_delete_vm()
    finally:
        builtins.input = vrai_input
    return tampon.getvalue()


class TestLeGardeEstSurLeChemin(unittest.TestCase):
    def test_the_command_refuses_before_it_undefines(self):
        """L'ORDRE est la seule chose qui compte pour un préfixe de shell :
        après l'undefine, le garde ne garde plus rien."""
        todo = todo_avec()
        jouer(todo, ["1", "n", "y"])
        self.assertEqual(1, len(todo.execute.vues), todo.execute.vues)
        cmd = todo.execute.vues[0]
        self.assertLess(cmd.index("REFUS"), cmd.index("undefine"))

    def test_the_proof_that_travels_is_the_one_that_was_listed(self):
        """Une preuve relevée juste avant d'effacer serait comparée à
        elle-même et ne prouverait rien."""
        todo = todo_avec()
        jouer(todo, ["1", "n", "y"])
        self.assertIn(
            "aaaaaaaa-1111-2222-3333-444444444444", todo.execute.vues[0]
        )

    def test_it_addresses_by_name_and_proves_by_uuid(self):
        todo = todo_avec()
        jouer(todo, ["2", "n", "y"])
        cmd = todo.execute.vues[0]
        self.assertIn("undefine machine-b", cmd)
        self.assertIn("bbbbbbbb-1111-2222-3333-444444444444", cmd)
        self.assertNotIn("machine-a", cmd)

    def test_the_menu_no_longer_writes_the_command_itself(self):
        """Un corps recopié dérive de son original au premier correctif, et
        c'est le chemin recopié qui dérive en silence."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_manage.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_delete_vm"
        ][0]
        appels = [
            noeud.func.attr
            for noeud in ast.walk(corps)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
        ]
        self.assertIn("delete_command", appels)


class TestLaLectureDeLInventaire(unittest.TestCase):
    """Le banc d'à côté remplace la lecture entière : sans cette épreuve,
    rien ne dit que la commande demande bien la preuve."""

    def _lire(self, sortie="", casse=False):
        from unittest.mock import patch

        vues = []

        class Reponse:
            stdout = sortie

        def espion(argv, **_kwargs):
            vues.append(argv)
            if casse:
                raise OSError("virsh introuvable")
            return Reponse()

        todo = TODO.__new__(TODO)
        with patch("script.todo.qemu_manage.subprocess.run", espion):
            domaines = todo._qemu_list_domains_proved()
        return domaines, vues

    def test_it_asks_for_the_proof_and_the_name(self):
        _domaines, vues = self._lire(INVENTAIRE)
        self.assertTrue(vues, "aucun appel : rien n'est prouvé")
        self.assertIn("--uuid", vues[0])
        self.assertIn("--name", vues[0])

    def test_it_asks_once_and_not_once_per_machine(self):
        """Un appel par machine se verrait devant un menu."""
        _domaines, vues = self._lire(INVENTAIRE)
        self.assertEqual(1, len(vues))

    def test_the_uri_is_never_left_implicit(self):
        """Sans elle, libvirt choisit un hyperviseur séparé où « list
        --all » rend une liste vide, sans erreur et sans avertissement."""
        _domaines, vues = self._lire(INVENTAIRE)
        self.assertIn("--connect", vues[0])

    def test_it_yields_the_domains_with_their_proof(self):
        domaines, _vues = self._lire(INVENTAIRE)
        self.assertEqual(
            ["machine-a", "machine-b"], [d.name for d in domaines]
        )
        self.assertTrue(all(VM.is_armed(d) for d in domaines))

    def test_a_broken_read_yields_no_domain_and_does_not_raise(self):
        """Une liste vide ferme l'écran ; une exception le ferait tomber."""
        domaines, _vues = self._lire(casse=True)
        self.assertEqual((), domaines)


class TestUnMenuNeDesarmePas(unittest.TestCase):
    def test_a_domain_without_proof_is_refused_and_named(self):
        """Elle ne DISPARAÎT pas de la liste : la cacher laisserait croire
        qu'elle n'existe pas."""
        todo = todo_avec("machine-sans-preuve\n")
        vu = jouer(todo, ["1", "n", "y"])
        self.assertEqual([], todo.execute.vues)
        self.assertIn("machine-sans-preuve", vu)

    def test_the_library_still_disarms_and_that_is_not_touched(self):
        """Deux régimes : la bibliothèque tolère, le menu refuse. Toucher
        au premier bloquerait la suppression là où le désarmement a été
        écrit pour servir."""
        from script.vm import verbs as V

        nu = VM.libvirt_handle("machine-a")
        self.assertEqual("", V.identity_guard(nu))
        self.assertNotIn("REFUS", V.delete_command(nu, sudo="", uri="x"))

    def test_the_others_are_still_deleted(self):
        """Contrôle positif : une machine sans preuve ne doit pas fermer
        celles qui en ont une."""
        todo = todo_avec(
            "machine-sans-preuve\n"
            "bbbbbbbb-1111-2222-3333-444444444444 machine-b\n"
        )
        jouer(todo, ["all", "n", "y"])
        self.assertEqual(1, len(todo.execute.vues))
        self.assertIn("machine-b", todo.execute.vues[0])


class TestLesDisquesRestentLus(unittest.TestCase):
    """Le verbe DÉDUIRAIT les chemins du nom. Une VM renommée garde le nom
    de fichier d'avant, et un fichier partagé avec une voisine ne s'efface
    pas : la liste vient du XML, comme avant."""

    def test_the_files_come_from_the_inspection_not_from_the_name(self):
        todo = todo_avec(fichiers=["/var/lib/libvirt/images/autre-nom.qcow2"])
        jouer(todo, ["1", "y", "y"])
        cmd = todo.execute.vues[0]
        self.assertIn("autre-nom.qcow2", cmd)
        self.assertNotIn("machine-a.qcow2", cmd)

    def test_no_disk_asked_means_no_removal(self):
        todo = todo_avec(fichiers=["/var/lib/libvirt/images/autre-nom.qcow2"])
        jouer(todo, ["1", "n", "y"])
        self.assertNotIn("rm -f", todo.execute.vues[0])

    def test_the_verb_is_asked_not_to_guess(self):
        """« with_disks=True » ferait poser un « rm » sur un chemin déduit,
        en plus de celui qu'on a lu."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_manage.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_delete_vm"
        ][0]
        appels = [
            noeud
            for noeud in ast.walk(corps)
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr == "delete_command"
        ]
        self.assertEqual(1, len(appels))
        mots = {mot.arg: mot.value for mot in appels[0].keywords}
        self.assertIn("with_disks", mots)
        self.assertIs(False, getattr(mots["with_disks"], "value", None))


class TestRienNestFaitSansConfirmation(unittest.TestCase):
    def test_a_refused_confirmation_runs_nothing(self):
        todo = todo_avec()
        jouer(todo, ["1", "n", "n"])
        self.assertEqual([], todo.execute.vues)

    def test_an_empty_selection_runs_nothing(self):
        todo = todo_avec()
        jouer(todo, [""])
        self.assertEqual([], todo.execute.vues)


if __name__ == "__main__":
    unittest.main()
