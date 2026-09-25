#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Docker / Podman lance-t-il ce qu'il annonce ?

Trois gestes de ce menu sont irréversibles ou coûteux, et chacun se décide
sur un détail que l'affichage seul ne garantit pas :

- l'installation de Docker demande un MODE. Le groupe « docker » équivaut à
  root sur l'hôte, le mode sans privilège n'y touche pas : le drapeau doit
  suivre la réponse, et jamais un défaut ;
- l'effacement porte sur les VOLUMES, donc sur la base de données. Il se
  refuse par un simple non, et rien ne part ;
- les scripts de script/docker/ appellent la commande docker par son nom.
  Sous Podman seul, le menu doit s'arrêter AVANT de lancer, sinon l'erreur
  accuse le script au lieu du moteur absent.
"""

import builtins
import contextlib
import io
import re
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import container_menu  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

SOURCE = (RACINE / "script/todo/container_menu.py").read_text(encoding="utf-8")


class ExecuteFactice:
    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)


class Banc(unittest.TestCase):
    def todo(self, fiche=None):
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        if fiche is not None:
            todo._container_fiche = lambda: fiche
        return todo

    @staticmethod
    @contextlib.contextmanager
    def reponses(entrees=(), prompts=()):
        """Joue des réponses écrites d'avance sur input() et click.prompt."""
        suite = iter(entrees)
        ancien = builtins.input
        builtins.input = lambda *a, **k: next(suite, "")
        sortie = io.StringIO()
        try:
            with mock.patch.object(
                container_menu.click, "prompt", side_effect=list(prompts)
            ):
                with contextlib.redirect_stdout(sortie):
                    yield sortie
        finally:
            builtins.input = ancien


class TestInstallation(Banc):
    def test_le_mode_groupe_est_celui_de_la_reponse(self):
        todo = self.todo()
        with self.reponses(entrees=["o"], prompts=["1"]):
            todo._container_install("docker")
        self.assertEqual(1, len(todo.execute.commandes))
        cmd = todo.execute.commandes[0]
        self.assertIn("--groupe", cmd)
        self.assertNotIn("--rootless", cmd)

    def test_le_mode_sans_privilege_peut_prendre_l_amont(self):
        todo = self.todo()
        with self.reponses(entrees=["o", "o"], prompts=["2"]):
            todo._container_install("docker")
        cmd = todo.execute.commandes[0]
        self.assertIn("--rootless", cmd)
        self.assertIn("--amont", cmd)

    def test_l_amont_se_refuse_sans_emporter_le_mode(self):
        todo = self.todo()
        with self.reponses(entrees=["n", "o"], prompts=["2"]):
            todo._container_install("docker")
        cmd = todo.execute.commandes[0]
        self.assertIn("--rootless", cmd)
        self.assertNotIn("--amont", cmd)

    def test_podman_ne_demande_aucun_mode(self):
        """Sans démon ni groupe, il n'y a rien à arbitrer."""
        todo = self.todo()
        with self.reponses(entrees=["o"], prompts=[]):
            todo._container_install("podman")
        cmd = todo.execute.commandes[0]
        self.assertIn("podman", cmd)
        self.assertNotIn("--groupe", cmd)

    def test_un_refus_ne_lance_rien(self):
        todo = self.todo()
        with self.reponses(entrees=["n"], prompts=["1"]):
            todo._container_install("docker")
        self.assertEqual([], todo.execute.commandes)


class TestEffacement(Banc):
    FICHE = {"moteur": "docker", "sans_sudo": True}

    def test_il_nomme_les_volumes_avant_de_demander(self):
        todo = self.todo(self.FICHE)
        with self.reponses(entrees=["o"]) as sortie:
            todo._container_nettoyage()
        self.assertIn("VOLUME", sortie.getvalue().upper())
        self.assertIn("--volumes", todo.execute.commandes[0])

    def test_un_refus_n_efface_rien(self):
        todo = self.todo(self.FICHE)
        with self.reponses(entrees=["n"]):
            todo._container_nettoyage()
        self.assertEqual([], todo.execute.commandes)


class TestLigneDeCommandeDocker(Banc):
    """Les scripts de script/docker/ appellent « docker » par son nom."""

    def test_sans_docker_le_sous_menu_ne_s_ouvre_pas(self):
        todo = self.todo()
        with mock.patch.object(
            container_menu.shutil, "which", return_value=None
        ):
            with self.reponses() as sortie:
                todo._container_erplibre()
        self.assertEqual([], todo.execute.commandes)
        self.assertIn("docker", sortie.getvalue())

    def test_avec_docker_chaque_entree_lance_son_script(self):
        todo = self.todo()
        with mock.patch.object(
            container_menu.shutil, "which", return_value="/usr/bin/docker"
        ):
            with self.reponses(prompts=["1", "5", "0"]):
                todo._container_erplibre()
        self.assertEqual(
            [
                "./script/docker/docker_exec.sh",
                "./script/docker/docker_repo_show_status.sh",
            ],
            todo.execute.commandes,
        )

    def test_une_source_absente_ne_lance_pas_la_copie(self):
        todo = self.todo()
        with self.reponses(prompts=["/n/existe/pas"]) as sortie:
            todo._container_copier_fichier()
        self.assertEqual([], todo.execute.commandes)
        self.assertIn("/n/existe/pas", sortie.getvalue())


class TestInventaire(Banc):
    def test_le_prefixe_sudo_suit_la_fiche(self):
        todo = self.todo({"moteur": "docker", "sans_sudo": False})
        with self.reponses():
            todo._container_inventaire(["images"])
        self.assertEqual("sudo docker images", todo.execute.commandes[0])

    def test_sans_moteur_rien_ne_part(self):
        todo = self.todo()
        todo._container_fiche = lambda: None
        with self.reponses():
            todo._container_inventaire(["images"])
        self.assertEqual([], todo.execute.commandes)


class TestVersionsOdoo(Banc):
    def test_elles_viennent_du_catalogue_la_plus_recente_en_tete(self):
        todo = self.todo()
        versions = todo._container_versions_odoo()
        self.assertTrue(versions)
        self.assertEqual(versions, sorted(versions, key=float, reverse=True))
        self.assertIn("18.0", versions)


class TestNumerotation(Banc):
    def test_chaque_entree_affichee_a_sa_branche(self):
        """Une entrée sans branche rend « Command not found » sur un numéro
        que le menu vient d'afficher."""
        corps = SOURCE[
            SOURCE.index("def prompt_execute_container") : SOURCE.index(
                "def _container_fiches"
            )
        ]
        entrees = len(re.findall(r'"prompt_description":', corps))
        branches = re.findall(r'status == "(\d+)"', corps)
        self.assertEqual(
            [str(n) for n in range(1, entrees + 1)],
            [b for b in branches if b != "0"],
        )


if __name__ == "__main__":
    unittest.main()
