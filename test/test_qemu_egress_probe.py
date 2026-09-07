#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Relire les règles posées, parce que l'invité ne le dit à personne.

Le chargement échoue DANS la machine sans que l'hôte l'apprenne : l'attente
de cloud-init lit son état pour cesser d'attendre, jamais pour le dire, et
l'autre voie d'amorce recopie ses fichiers avec une commande qui tolère son
propre échec. Sans relecture, une machine dont l'image n'a pas l'analyseur
se déploie en annonçant un confinement que rien ne tient.

CHAQUE VERDICT SE CORRIGE D'UN CÔTÉ DIFFÉRENT, et c'est pourquoi ils ne
s'agrègent pas en un seul code : une table absente se recharge, un
analyseur absent se choisit avec l'image, un droit manquant s'accorde, un
silence est un problème de transport.

Rien ici ne touche à une machine : la lecture est un paramètre.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.posture import plan  # noqa: E402
from script.todo import devstack_report as R  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

# Une adresse de documentation (RFC 5737).
IP = "198.51.100.5"


def menu():
    return TODO.__new__(TODO)


def lecteur(reponse):
    """Une lecture de banc : une réponse, et un journal des commandes."""
    vues = []

    def lire(commande):
        vues.append(commande)
        return reponse

    lire.vues = vues
    return lire


class TestLaCommandeDeSonde(unittest.TestCase):
    def test_it_carries_the_probe_the_posture_package_names(self):
        """Une sonde recopiée divergerait de son original au premier
        correctif ; celle-ci vient du module qui la définit."""
        commande = menu()._egress_probe_command(IP)
        self.assertIn(plan.MARQUEUR, commande)
        self.assertIn(IP, commande)

    def test_the_probe_travels_as_one_argument(self):
        """Découpée, ssh en recollerait les morceaux à sa façon, et le
        « ; » du milieu s'exécuterait du mauvais côté."""
        import shlex

        morceaux = shlex.split(menu()._egress_probe_command(IP))
        self.assertEqual(plan.probe_command(), morceaux[-1])

    def test_it_never_waits_for_an_answer_from_a_human(self):
        """Une invite bloquerait le déploiement sur une question que
        personne ne voit."""
        self.assertIn("BatchMode=yes", menu()._egress_probe_command(IP))

    def test_a_reused_address_does_not_refuse_a_fresh_machine(self):
        commande = menu()._egress_probe_command(IP)
        self.assertIn("StrictHostKeyChecking=no", commande)


class TestChaqueVerdictSaCouche(unittest.TestCase):
    def test_loaded_is_the_only_green_one(self):
        for verdict in plan.VERDICTS:
            couches = menu()._egress_layers(verdict)
            vert = all(c.code == R.DS_OK for c in couches)
            with self.subTest(verdict=verdict):
                self.assertEqual(verdict == plan.LOADED, vert)

    def test_a_missing_tool_is_about_the_guest_and_not_the_firewall(self):
        """Il se corrige en changeant d'image, pas en rechargeant."""
        couche = menu()._egress_layers(plan.TOOL_ABSENT)[0]
        self.assertEqual("guest", couche.layer)
        self.assertEqual(R.DS_ERR, couche.code)

    def test_an_unreadable_table_is_a_failure_and_not_a_clean_exit(self):
        """La machine a reçu une posture qui promet un confinement : une
        vérification qui n'aboutit pas ne doit pas se lire comme un
        succès."""
        couche = menu()._egress_layers(plan.NO_PRIVILEGE)[0]
        self.assertEqual(R.DS_ERR, couche.code)
        self.assertNotEqual(R.DS_SKIP, couche.code)

    def test_silence_is_the_only_clean_withdrawal(self):
        """Là, rien n'a été sondé du tout — et la couche nommée est celle
        qui a cédé, le transport, pas le pare-feu jamais mesuré."""
        couche = menu()._egress_layers(plan.UNREAD)[0]
        self.assertEqual(R.DS_SKIP, couche.code)
        self.assertEqual("transport", couche.layer)

    def test_every_failure_says_what_to_do(self):
        """Un verdict rouge sans remède envoie chercher au hasard."""
        for verdict in plan.VERDICTS:
            if verdict == plan.LOADED:
                continue
            for couche in menu()._egress_layers(verdict):
                with self.subTest(verdict=verdict):
                    self.assertTrue(couche.remedy)

    def test_every_layer_is_in_the_closed_vocabulary(self):
        """Le constructeur refuse déjà une couche inconnue ; l'appeler pour
        chaque verdict est ce qui fait tomber l'épreuve si l'un d'eux se
        met à en nommer une qui n'existe pas."""
        for verdict in plan.VERDICTS:
            for couche in menu()._egress_layers(verdict):
                with self.subTest(verdict=verdict):
                    self.assertIn(couche.layer, R.LAYERS)


class TestLaRelectureDuParc(unittest.TestCase):
    def _relire(self, reponse, ip_map):
        lire = lecteur(reponse)
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = menu()._qemu_probe_egress(["a", "b"], ip_map, lire=lire)
        return code, tampon.getvalue(), lire

    def test_a_fleet_that_loaded_reports_green(self):
        code, sortie, lire = self._relire(
            f"{plan.MARQUEUR}{plan.LOADED}", {"a": IP, "b": "198.51.100.6"}
        )
        self.assertEqual(R.DS_OK, code)
        self.assertEqual(2, len(lire.vues))
        self.assertIn("firewall", sortie)

    def test_one_machine_short_of_the_tool_reddens_the_whole_fleet(self):
        """Le pire code, et non le premier : une seule machine qui n'a pas
        chargé ses règles est une machine de trop."""

        def lire(commande):
            if "198.51.100.6" in commande:
                return f"{plan.MARQUEUR}{plan.TOOL_ABSENT}"
            return f"{plan.MARQUEUR}{plan.LOADED}"

        tampon = io.StringIO()
        with redirect_stdout(tampon):
            code = menu()._qemu_probe_egress(
                ["a", "b"], {"a": IP, "b": "198.51.100.6"}, lire=lire
            )
        self.assertEqual(R.DS_ERR, code)

    def test_a_machine_without_an_address_counts_as_silence(self):
        """Elle n'est pas sondée, donc rien n'est prouvé pour elle — et
        surtout pas qu'elle va bien."""
        code, _sortie, lire = self._relire(
            f"{plan.MARQUEUR}{plan.LOADED}", {"a": IP}
        )
        self.assertEqual(1, len(lire.vues))
        self.assertEqual(R.DS_SKIP, code)

    def test_nothing_read_is_never_green(self):
        code, _sortie, _lire = self._relire("", {"a": IP, "b": IP})
        self.assertNotEqual(R.DS_OK, code)

    def test_each_machine_is_named_in_what_is_written(self):
        _code, sortie, _lire = self._relire(
            f"{plan.MARQUEUR}{plan.LOADED}", {"a": IP, "b": IP}
        )
        for nom in ("a", "b"):
            self.assertIn(nom, sortie)


class TestLeChainageDansLeDeploiement(unittest.TestCase):
    """Le maillon qu'aucune épreuve ne peut jouer : le déploiement réel
    crée des machines. L'arbre dit s'il est branché."""

    @staticmethod
    def _appels(nom_fonction, nom_appel):
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == nom_fonction
        ]
        assert len(corps) == 1, nom_fonction
        return [
            noeud
            for noeud in ast.walk(corps[0])
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
            and noeud.func.attr == nom_appel
        ]

    @staticmethod
    def _si_gardes_par(nom_variable):
        """Les « if » de `_qemu_run_spec` dont la condition lit `nom`.

        La PRÉSENCE d'un appel ne prouve rien : posé sous une condition
        toujours fausse, il reste dans l'arbre et ne s'exécute jamais. Ce
        qui compte est donc la garde, pas la ligne.
        """
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_qemu_run_spec"
        ]
        assert len(corps) == 1, "_qemu_run_spec introuvable"
        return [
            noeud
            for noeud in ast.walk(corps[0])
            if isinstance(noeud, ast.If)
            and any(
                isinstance(n, ast.Name) and n.id == nom_variable
                for n in ast.walk(noeud.test)
            )
        ]

    @staticmethod
    def _appelle(noeud, nom_appel):
        import ast

        return any(
            isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == nom_appel
            for n in ast.walk(noeud)
        )

    def test_the_run_path_reads_the_rules_back_when_it_posed_some(self):
        """Sans cet appel, le fichier est posé et personne ne vérifie
        jamais qu'il a pris."""
        gardes = self._si_gardes_par("egress_pose")
        relectures = [
            g for g in gardes if self._appelle(g, "_qemu_probe_egress")
        ]
        self.assertEqual(1, len(relectures), "la relecture n'est pas gardée")

    def test_the_address_is_resolved_because_the_probe_needs_it(self):
        """Sans elle, la relecture ne joindrait aucune VM et rendrait un
        silence pour tout le parc — vert nulle part, prouvé nulle part."""
        gardes = self._si_gardes_par("egress_pose")
        resolutions = [
            g for g in gardes if self._appelle(g, "_qemu_resolve_ips")
        ]
        self.assertEqual(1, len(resolutions))

    def test_exactly_two_places_depend_on_having_posed_a_file(self):
        """Un troisième serait une porte de plus à tenir, et personne ne
        saurait laquelle."""
        self.assertEqual(2, len(self._si_gardes_par("egress_pose")))

    def test_the_probe_reaches_only_the_guest_layer_it_names(self):
        """La sonde est la seule chose qui parle à la machine ici : elle
        n'exécute rien d'autre."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        lecture = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "_egress_read"
        ]
        self.assertEqual(1, len(lecture))
        noms = [
            noeud.func.attr
            for noeud in ast.walk(lecture[0])
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Attribute)
        ]
        self.assertEqual(["run"], noms)


if __name__ == "__main__":
    unittest.main()
