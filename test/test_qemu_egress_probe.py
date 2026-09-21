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
from script.todo import deploy_verify as V  # noqa: E402
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
            couches = V.egress_layers(verdict)
            vert = all(c.code == R.DS_OK for c in couches)
            with self.subTest(verdict=verdict):
                self.assertEqual(verdict == plan.LOADED, vert)

    def test_a_missing_tool_is_about_the_guest_and_not_the_firewall(self):
        """Il se corrige en changeant d'image, pas en rechargeant."""
        couche = V.egress_layers(plan.TOOL_ABSENT)[0]
        self.assertEqual("guest", couche.layer)
        self.assertEqual(R.DS_ERR, couche.code)

    def test_an_unreadable_table_is_a_failure_and_not_a_clean_exit(self):
        """La machine a reçu une posture qui promet un confinement : une
        vérification qui n'aboutit pas ne doit pas se lire comme un
        succès."""
        couche = V.egress_layers(plan.NO_PRIVILEGE)[0]
        self.assertEqual(R.DS_ERR, couche.code)
        self.assertNotEqual(R.DS_SKIP, couche.code)

    def test_silence_is_the_only_clean_withdrawal(self):
        """Là, rien n'a été sondé du tout — et la couche nommée est celle
        qui a cédé, le transport, pas le pare-feu jamais mesuré."""
        couche = V.egress_layers(plan.UNREAD)[0]
        self.assertEqual(R.DS_SKIP, couche.code)
        self.assertEqual("transport", couche.layer)

    def test_every_failure_says_what_to_do(self):
        """Un verdict rouge sans remède envoie chercher au hasard."""
        for verdict in plan.VERDICTS:
            if verdict == plan.LOADED:
                continue
            for couche in V.egress_layers(verdict):
                with self.subTest(verdict=verdict):
                    self.assertTrue(couche.remedy)

    def test_every_layer_is_in_the_closed_vocabulary(self):
        """Le constructeur refuse déjà une couche inconnue ; l'appeler pour
        chaque verdict est ce qui fait tomber l'épreuve si l'un d'eux se
        met à en nommer une qui n'existe pas."""
        for verdict in plan.VERDICTS:
            for couche in V.egress_layers(verdict):
                with self.subTest(verdict=verdict):
                    self.assertIn(couche.layer, R.LAYERS)


class TestLaRelectureDuParc(unittest.TestCase):
    def _relire(self, reponse, ip_map):
        lire = lecteur(reponse)
        tampon = io.StringIO()
        with redirect_stdout(tampon):
            releve = menu()._qemu_probe_egress(["a", "b"], ip_map, lire=lire)
        return releve, tampon.getvalue(), lire

    def test_only_a_table_that_was_read_counts_as_confined(self):
        """Ce qui n'a pas été lu vaut « non » : l'inverse ferait passer un
        silence pour une garantie."""
        for verdict in plan.VERDICTS:
            releve, _sortie, _lire = self._relire(
                f"{plan.MARQUEUR}{verdict}", {"a": IP, "b": IP}
            )
            with self.subTest(verdict=verdict):
                confine = releve.unconfined == ()
                self.assertEqual(verdict == plan.LOADED, confine)

    def test_a_fleet_that_loaded_reports_green(self):
        releve, sortie, lire = self._relire(
            f"{plan.MARQUEUR}{plan.LOADED}", {"a": IP, "b": "198.51.100.6"}
        )
        self.assertEqual(R.DS_OK, releve.code)
        self.assertEqual((), releve.unconfined)
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
            releve = menu()._qemu_probe_egress(
                ["a", "b"], {"a": IP, "b": "198.51.100.6"}, lire=lire
            )
        self.assertEqual(R.DS_ERR, releve.code)
        self.assertEqual(("b",), releve.unconfined)

    def test_a_machine_without_an_address_counts_as_silence(self):
        """Elle n'est pas sondée, donc rien n'est prouvé pour elle — et
        surtout pas qu'elle va bien."""
        releve, _sortie, lire = self._relire(
            f"{plan.MARQUEUR}{plan.LOADED}", {"a": IP}
        )
        self.assertEqual(1, len(lire.vues))
        self.assertEqual(R.DS_SKIP, releve.code)
        self.assertEqual(("b",), releve.unconfined)

    def test_nothing_read_is_never_green(self):
        releve, _sortie, _lire = self._relire("", {"a": IP, "b": IP})
        self.assertNotEqual(R.DS_OK, releve.code)
        self.assertEqual(("a", "b"), releve.unconfined)

    def test_each_machine_is_named_in_what_is_written(self):
        _releve, sortie, _lire = self._relire(
            f"{plan.MARQUEUR}{plan.LOADED}", {"a": IP, "b": IP}
        )
        for nom in ("a", "b"):
            self.assertIn(nom, sortie)


class TestCeQuOnRefuseDePoser(unittest.TestCase):
    """Une machine qui devait être confinée et ne l'est pas ne reçoit
    rien. Elle existe et elle est jointe : c'est justement pourquoi
    continuer l'installerait derrière une promesse qu'elle ne tient pas."""

    def test_the_ones_that_held_are_kept(self):
        """Contrôle positif : les autres ont chargé leurs règles et n'ont
        pas à payer pour celle qui a échoué."""
        self.assertEqual(
            ["a", "c"], menu()._egress_keep(["a", "b", "c"], ("b",))
        )

    def test_nothing_refused_changes_nothing(self):
        self.assertEqual(["a", "b"], menu()._egress_keep(["a", "b"], ()))

    def test_a_fleet_that_all_failed_installs_nowhere(self):
        self.assertEqual([], menu()._egress_keep(["a", "b"], ("a", "b")))

    def test_the_deployed_list_is_not_the_one_that_shrinks(self):
        """Le sommaire final compte ce qui a été DÉPLOYÉ : amputer cette
        liste ferait disparaître du décompte des machines bien réelles."""
        deployees = ["a", "b"]
        menu()._egress_keep(deployees, ("b",))
        self.assertEqual(["a", "b"], deployees)


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
        """Les « if » du déploiement QEMU dont la condition lit `nom`.

        La PRÉSENCE d'un appel ne prouve rien : posé sous une condition
        toujours fausse, il reste dans l'arbre et ne s'exécute jamais. Ce
        qui compte est donc la garde, pas la ligne.

        CHERCHÉ DANS TOUT LE FICHIER, et non dans une fonction nommée : le
        corps du déploiement a été scindé en enveloppe et corps, et la
        garde ne tenait plus rien — elle lisait une fonction devenue
        longue de dix lignes, et rendait zéro « if » sans rien dire. La
        variable, elle, est locale à ce corps où qu'il vive.
        """
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        return [
            noeud
            for noeud in ast.walk(arbre)
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

    def test_the_withholding_is_wired_to_the_read_back(self):
        """Sans cet appel, la relecture rougit et l'installation se pose
        quand même : le rapport serait une décoration."""
        gardes = self._si_gardes_par("egress_pose")
        filtrages = [g for g in gardes if self._appelle(g, "_egress_keep")]
        self.assertEqual(1, len(filtrages))

    def test_both_install_paths_target_the_filtered_list(self):
        """Poser sur la liste non filtrée annulerait le retrait sans que
        rien ne le dise. Les deux voies se lisent différemment : le suivi
        reçoit la LISTE, l'installation synchrone BOUCLE dessus."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "qemu_deploy.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        # LE FICHIER ENTIER, et non une fonction nommée : le corps du
        # déploiement a été scindé, et viser son ancien nom rendait zéro
        # appel — donc vert sur « l'installation ne touche plus la liste
        # non filtrée » alors que plus rien n'était regardé.
        suivi = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "_qemu_install_erplibre_monitored"
        ]
        self.assertEqual(1, len(suivi))
        passes = [n.id for n in suivi[0].args if isinstance(n, ast.Name)]
        self.assertIn("a_installer", passes)
        self.assertNotIn("deployed", passes)

        boucles = [
            n
            for n in ast.walk(arbre)
            if isinstance(n, ast.For)
            and isinstance(n.iter, ast.Name)
            and any(
                isinstance(a, ast.Call)
                and isinstance(a.func, ast.Attribute)
                and a.func.attr == "_qemu_install_erplibre_vm"
                for a in ast.walk(n)
            )
        ]
        self.assertEqual(1, len(boucles))
        self.assertEqual("a_installer", boucles[0].iter.id)

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
