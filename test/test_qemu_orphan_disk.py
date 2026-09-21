#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un disque resté seul bloque la création : le proposer à l'effacement.

Une création interrompue laisse son qcow2 sans VM définie. deploy_qemu refuse
alors d'écraser, et la création échoue APRÈS avoir fait attendre. Le
formulaire plein écran, lui, signale le disque mais ne peut pas l'effacer :
cela demande root, et une invite de mot de passe n'a nulle part où s'afficher
dans une application Textual.

Ce que ces tests gardent :

- l'effacement est PROPOSÉ, jamais fait d'office — le même nom peut désigner
  le disque d'une VM retirée à la main, dont on voulait garder les données ;
- un refus n'enchaîne pas en silence vers l'échec : il redemande ;
- le chemin plein écran passe par la même proposition que le chemin en ligne.
"""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402


class PropositionEffacement(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.efface = []
        self.todo._cleanup_delete_files = self._faux_effacement
        # Les deux SEULES feuilles impures du contrôle de propriété sont
        # bouchonnées ; le contrôle lui-même tourne pour de vrai. Sans
        # cela, l'épreuve interrogerait le libvirt de la station qui la
        # lance, et mesurerait son parc au lieu du code.
        self.todo._qemu_referenced_files = lambda noms=None: {}
        self.todo._qemu_files_in_use = lambda: set()

    def _faux_effacement(self, title, items, prompt):
        self.efface.append([p for _s, p in items])

    def _avec_disques(self, presents, reponses=()):
        """Simule des orphelins et rend (accepté, effacements demandés)."""
        it = iter(reponses)
        restants = {"v": list(presents)}

        def faux_orphans(names):
            return [
                (n, f"/var/lib/libvirt/images/{n}.qcow2")
                for n in names
                if n in restants["v"]
            ]

        def effacer(title, items, prompt):
            self.efface.append([p for _s, p in items])
            restants["v"] = []

        self.todo._qemu_orphan_disks = faux_orphans
        self.todo._cleanup_delete_files = effacer
        with (
            mock.patch("builtins.input", lambda *a: next(it, "")),
            mock.patch("builtins.print"),
        ):
            ok = self.todo._qemu_offer_orphan_removal(["vm-a", "vm-b"])
        return ok, self.efface

    def test_a_disk_owned_by_another_domain_is_never_offered(self):
        """LE défaut : le chemin est DÉDUIT du nom, et une VM renommée
        garde le nom de fichier d'avant. Déployer une machine qui reprend
        l'ancien nom proposait d'effacer le disque vivant de la voisine."""
        chemin = "/var/lib/libvirt/images/vm-a.qcow2"
        self.todo._qemu_orphan_disks = lambda names: [
            (n, f"/var/lib/libvirt/images/{n}.qcow2")
            for n in names
            if n == "vm-a"
        ]
        self.todo._qemu_referenced_files = lambda noms=None: {
            chemin: "vm-renommee"
        }
        with mock.patch("builtins.input", return_value="y"), mock.patch(
            "builtins.print"
        ):
            self.todo._qemu_offer_orphan_removal(["vm-a"])
        self.assertEqual([[]], self.efface)

    def test_and_the_screen_names_what_holds_it(self):
        """« Gardé » sans dire par quoi envoie chercher au hasard."""
        chemin = "/var/lib/libvirt/images/vm-a.qcow2"
        self.todo._qemu_orphan_disks = lambda names: [("vm-a", chemin)]
        self.todo._qemu_referenced_files = lambda noms=None: {
            chemin: "vm-renommee"
        }
        vues = []
        with mock.patch("builtins.input", return_value="n"), mock.patch(
            "builtins.print",
            lambda *a, **k: vues.append(" ".join(map(str, a))),
        ):
            self.todo._qemu_offer_orphan_removal(["vm-a"])
        ecrit = "\n".join(vues)
        self.assertIn("vm-renommee", ecrit)
        self.assertIn(chemin, ecrit)

    def test_a_disk_held_open_by_a_process_is_kept_too(self):
        """Un domaine peut avoir été retiré alors que qemu tourne encore."""
        chemin = "/var/lib/libvirt/images/vm-a.qcow2"
        self.todo._qemu_orphan_disks = lambda names: [("vm-a", chemin)]
        self.todo._qemu_files_in_use = lambda: {chemin}
        with mock.patch("builtins.input", return_value="y"), mock.patch(
            "builtins.print"
        ):
            self.todo._qemu_offer_orphan_removal(["vm-a"])
        self.assertEqual([[]], self.efface)

    def test_a_truly_orphan_disk_is_still_offered(self):
        """Contrôle positif : tout protéger rendrait la proposition
        inutile, et la création échouerait comme avant."""
        chemin = "/var/lib/libvirt/images/vm-a.qcow2"
        self.todo._qemu_orphan_disks = lambda names: [("vm-a", chemin)]
        with mock.patch("builtins.input", return_value="y"), mock.patch(
            "builtins.print"
        ):
            self.todo._qemu_offer_orphan_removal(["vm-a"])
        self.assertEqual([[chemin]], self.efface)

    def test_the_check_lives_where_one_deletes_not_where_one_detects(self):
        """La détection est PURE exprès : le formulaire la rappelle à
        chaque frappe, et un contrôle de propriété y demanderait root —
        donc une invite qui n'a nulle part où s'afficher."""
        import ast

        chemin = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "script",
            "todo",
            "qemu_deploy.py",
        )
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        par_nom = {
            noeud.name: noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
        }

        def appels(nom):
            return [
                n.func.attr
                for n in ast.walk(par_nom[nom])
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
            ]

        self.assertIn(
            "_qemu_split_orphans", appels("_qemu_offer_orphan_removal")
        )
        self.assertNotIn("_qemu_split_orphans", appels("_qemu_orphan_disks"))

    def test_without_orphans_nothing_is_asked(self):
        self.todo._qemu_orphan_disks = lambda names: []
        with mock.patch("builtins.print"):
            self.assertTrue(self.todo._qemu_offer_orphan_removal(["vm-a"]))
        self.assertEqual([], self.efface)

    def test_an_orphan_is_offered_for_deletion(self):
        ok, efface = self._avec_disques(["vm-a"])
        self.assertTrue(ok)
        self.assertEqual([["/var/lib/libvirt/images/vm-a.qcow2"]], efface)

    def test_a_kept_disk_asks_again_instead_of_failing(self):
        """Refuser l'effacement mène à un échec certain : le dire et
        redemander, plutôt qu'enchaîner en silence."""
        self.todo._qemu_orphan_disks = lambda names: [
            (n, f"/var/lib/libvirt/images/{n}.qcow2")
            for n in names
            if n == "vm-a"
        ]
        with (
            mock.patch("builtins.input", return_value="n"),
            mock.patch("builtins.print"),
        ):
            self.assertFalse(
                self.todo._qemu_offer_orphan_removal(["vm-a", "vm-b"])
            )

    def test_a_kept_disk_can_still_be_forced_through(self):
        self.todo._qemu_orphan_disks = lambda names: [
            (n, f"/var/lib/libvirt/images/{n}.qcow2")
            for n in names
            if n == "vm-a"
        ]
        with (
            mock.patch("builtins.input", return_value="o"),
            mock.patch("builtins.print"),
        ):
            self.assertTrue(self.todo._qemu_offer_orphan_removal(["vm-a"]))

    def test_the_size_is_read_from_the_real_file(self):
        """La taille annoncée est celle du fichier : un chiffre inventé
        empêcherait de juger ce qu'on efface."""
        with tempfile.TemporaryDirectory() as tmp:
            chemin = os.path.join(tmp, "vm-a.qcow2")
            with open(chemin, "wb") as fh:
                fh.write(b"x" * 4096)
            self.todo._qemu_orphan_disks = lambda names: [("vm-a", chemin)]
            vus = []
            self.todo._cleanup_delete_files = lambda t_, items, p: vus.extend(
                items
            )
            with (
                mock.patch("builtins.input", return_value="n"),
                mock.patch("builtins.print"),
            ):
                self.todo._qemu_offer_orphan_removal(["vm-a"])
            self.assertEqual([(4096, chemin)], vus)

    def test_an_unreadable_file_does_not_break_the_offer(self):
        self.todo._qemu_orphan_disks = lambda names: [("vm-a", "/nulle/part")]
        vus = []
        self.todo._cleanup_delete_files = lambda t_, items, p: vus.extend(
            items
        )
        with (
            mock.patch("builtins.input", return_value="n"),
            mock.patch("builtins.print"),
        ):
            self.todo._qemu_offer_orphan_removal(["vm-a"])
        self.assertEqual([(0, "/nulle/part")], vus)


class LeFormulaireYPasseAussi(unittest.TestCase):
    def test_the_tui_path_calls_the_offer(self):
        """Le formulaire avertit mais ne peut pas effacer : sans cet appel,
        un F5 de plus mène droit à l'échec."""
        source = Path("script/todo/qemu_deploy.py").read_text(encoding="utf-8")
        debut = source.index('if self._qemu_ask_ui() == "tui":')
        fin = source.index("got = self._qemu_collect_vms_cli(mod)", debut)
        self.assertIn("_qemu_offer_orphan_removal", source[debut:fin])


if __name__ == "__main__":
    unittest.main()
