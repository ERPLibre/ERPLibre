#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une désinstallation se MESURE, elle ne se suppose pas.

`odoo-bin --uninstall` ne cherche que l'état « installed ». Un module resté
en « to remove » d'une tentative précédente est ignoré en silence, et Odoo
sort en 0. Le pilote tenait ce 0 pour une réussite : c'est ainsi que
muk_web_theme a traversé quatre paliers de 12 → 18 en étant réputé retiré,
alors qu'il était « installed » de la 15 à la 18.
"""

import ast
import io
import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.todo_upgrade import TodoUpgrade  # noqa: E402

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
SOURCE = os.path.join(RACINE, "script", "todo", "todo_upgrade.py")


class FauxPilote(TodoUpgrade):
    """Un pilote qui n'exécute rien, mais respecte le contrat de retour."""

    def __init__(self, survivants=(), lisible=True):
        self.survivants = list(survivants)
        self.lisible = lisible
        self.commandes = []
        self.commentaires = []
        self.dct_progression = {}
        self.dct_module_per_version = {}

    def todo_upgrade_execute(self, cmd, **kwargs):
        self.commandes.append(cmd)
        if kwargs.get("get_output"):
            # Le vrai rend TROIS valeurs quand on demande la sortie, et un
            # statut NON nul veut dire « raté ».
            if not self.lisible:
                return 1, cmd, None
            return 0, cmd, list(self.survivants)
        return 0, cmd

    def write_config(self):
        pass

    def add_comment_progression(self, msg):
        self.commentaires.append(msg)

    def split_present_missing(self, lst):
        return list(lst), []


class TestStillInstalled(unittest.TestCase):
    def test_it_names_what_survived(self):
        pilote = FauxPilote(survivants=["muk_web_theme"])
        self.assertEqual(
            pilote.still_installed("db", ["muk_web_theme", "web_responsive"]),
            ["muk_web_theme"],
        )

    def test_an_unreadable_database_says_UNKNOWN_not_empty(self):
        # Rendre [] serait affirmer « tout est parti » sans l'avoir lu :
        # exactement le défaut qu'on corrige.
        pilote = FauxPilote(lisible=False)
        self.assertIsNone(pilote.still_installed("db", ["web_responsive"]))

    def test_nothing_to_check_asks_the_database_nothing(self):
        pilote = FauxPilote()
        self.assertEqual(pilote.still_installed("db", []), [])
        self.assertEqual(pilote.commandes, [])

    def test_it_counts_to_remove_as_still_there(self):
        # « to remove » n'est pas « uninstalled » : c'est justement l'état
        # que --uninstall refuse de traiter, donc celui qu'il faut voir.
        pilote = FauxPilote()
        pilote.still_installed("db", ["web_responsive"])
        self.assertIn("state <> 'uninstalled'", pilote.commandes[0])

    def test_the_module_names_are_quoted_for_sql(self):
        pilote = FauxPilote()
        pilote.still_installed("db", ["web_responsive"])
        self.assertIn("'web_responsive'", pilote.commandes[0])


class TestTheBookkeepingTellsTheTruth(unittest.TestCase):
    def pilote(self, survivants):
        pilote = FauxPilote(survivants=survivants)
        pilote.dct_module_per_version = {
            17: ["web_responsive", "muk_web_theme"]
        }
        return pilote

    def test_a_module_left_in_place_stays_counted_as_installed(self):
        pilote = self.pilote(["web_responsive"])
        pilote.uninstall_from_database(["web_responsive"], "db", 17)
        self.assertIn("web_responsive", pilote.dct_module_per_version[17])

    def test_a_module_really_gone_is_dropped(self):
        pilote = self.pilote([])
        pilote.uninstall_from_database(["web_responsive"], "db", 17)
        self.assertNotIn("web_responsive", pilote.dct_module_per_version[17])
        # …et sans emporter le voisin au passage.
        self.assertIn("muk_web_theme", pilote.dct_module_per_version[17])

    def test_the_survivor_is_recorded_where_someone_will_read_it(self):
        pilote = self.pilote(["web_responsive"])
        pilote.uninstall_from_database(["web_responsive"], "db", 17)
        trace = " ".join(pilote.commentaires)
        self.assertIn("still installed", trace)
        self.assertIn("web_responsive", trace)

    def test_an_unreadable_database_does_not_crash_the_migration(self):
        # « je ne sais pas » revient en None : le traiter comme une liste
        # ferait tomber la migration sur un TypeError, six heures après le
        # départ, pour un renseignement qui n'était que confortable.
        pilote = FauxPilote(lisible=False)
        pilote.dct_module_per_version = {17: ["web_responsive"]}
        pilote.uninstall_from_database(["web_responsive"], "db", 17)
        self.assertEqual(pilote.dct_module_per_version[17], [])

    def test_a_silent_success_leaves_no_alarm(self):
        pilote = self.pilote([])
        pilote.uninstall_from_database(["web_responsive"], "db", 17)
        self.assertEqual(
            [c for c in pilote.commentaires if "still installed" in c], []
        )


class TestNoStepWritesAnotherStepsFlag(unittest.TestCase):
    """Chaque drapeau `state_4_*` ne doit porter QUE sa propre liste.

    Trois étapes rangeaient leurs drapeaux sous
    `state_4_module_migrate_odoo_lst`. Sans effet dans la course en cours —
    la locale est lue une fois, au début — mais à la REPRISE cette clé est
    relue comme « OpenUpgrade est passé », et la migration du palier est
    sautée. Un test structurel se justifie ici : conduire une reprise
    complète coûterait des heures, et la faute est visible dans l'écriture.
    """

    def assignations(self):
        with io.open(SOURCE, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        vues = {}
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Assign):
                continue
            for cible in noeud.targets:
                if not (
                    isinstance(cible, ast.Subscript)
                    and isinstance(cible.value, ast.Attribute)
                    and cible.value.attr == "dct_progression"
                    and isinstance(cible.slice, ast.Constant)
                    and str(cible.slice.value).startswith("state_4_")
                ):
                    continue
                if isinstance(noeud.value, ast.Name):
                    vues.setdefault(cible.slice.value, set()).add(
                        noeud.value.id
                    )
        return vues

    def test_the_scan_actually_finds_something(self):
        # Sans cette borne, le test suivant passerait sur un dictionnaire
        # vide le jour où la forme de l'écriture change.
        self.assertGreater(len(self.assignations()), 2)

    def test_each_flag_is_written_from_one_list_only(self):
        for cle, noms in sorted(self.assignations().items()):
            self.assertEqual(
                len(noms), 1, f"{cle} écrit depuis {sorted(noms)}"
            )

    def test_the_migrate_flag_comes_from_the_migrate_list(self):
        self.assertEqual(
            self.assignations().get("state_4_module_migrate_odoo_lst"),
            {"lst_module_migrate_odoo"},
        )


class TestAFailedOpenUpgradeStaysUnrecorded(unittest.TestCase):
    """Un OpenUpgrade raté ne doit pas passer pour fait.

    `lst_upgrade_odoo` n'est pas une copie : `dct_progression.get()` rend
    l'objet stocké. L'affecter avant l'exécution le faisait persister au
    premier `write_config()` venu — celui du chemin d'échec compris, qui
    remet pourtant le drapeau de clonage à zéro pour forcer un nouvel
    essai. La reprise sautait alors OpenUpgrade et laissait une base 17
    tourner sous le code 18. Mesuré sur test_neutralize_upgrade_18 :
    base = 17.0.1.3, et sa commande de migration déjà consignée.

    Conduire `execute_odoo_upgrade` en vrai demanderait une migration
    complète ; la faute est un ORDRE dans le source, et c'est l'ordre
    qu'on mesure.
    """

    def arbre(self):
        with io.open(SOURCE, encoding="utf-8") as handle:
            return ast.parse(handle.read())

    def lignes_affectation(self):
        lignes = []
        for noeud in ast.walk(self.arbre()):
            if not isinstance(noeud, ast.Assign):
                continue
            for cible in noeud.targets:
                if (
                    isinstance(cible, ast.Subscript)
                    and isinstance(cible.value, ast.Name)
                    and cible.value.id == "lst_upgrade_odoo"
                ):
                    lignes.append(noeud.lineno)
        return lignes

    @staticmethod
    def _remet_le_clone_a_zero(noeud):
        """Ce bloc renonce-t-il en redemandant un clonage neuf ?

        Le repère est l'affectation `lst_clone_odoo[index] = False` : c'est
        elle qui distingue « je renonce, refais le clone » de l'étape de
        clonage elle-même, qui écrit `= True` et vit ailleurs. Chercher les
        seuls NOMS attrapait les deux, et l'ancre tombait 700 lignes trop
        haut — le test passait alors sur n'importe quel ordre.
        """
        for petit in ast.walk(noeud):
            if not isinstance(petit, ast.Assign):
                continue
            if not (
                isinstance(petit.value, ast.Constant)
                and petit.value.value is False
            ):
                continue
            for cible in petit.targets:
                if (
                    isinstance(cible, ast.Subscript)
                    and isinstance(cible.value, ast.Name)
                    and cible.value.id == "lst_clone_odoo"
                ):
                    return True
        return False

    def ligne_abandon(self):
        """Le `return` qui renonce après un OpenUpgrade raté."""
        lignes = [
            max(n.lineno for n in ast.walk(noeud) if isinstance(n, ast.Return))
            for noeud in ast.walk(self.arbre())
            if isinstance(noeud, ast.If)
            and self._remet_le_clone_a_zero(noeud)
            and any(isinstance(n, ast.Return) for n in ast.walk(noeud))
        ]
        return min(lignes) if lignes else None

    def test_both_anchors_are_found(self):
        # Sans cette borne, les tests suivants passeraient à vide le jour
        # où l'une des deux formes change.
        self.assertTrue(self.lignes_affectation())
        self.assertIsNotNone(self.ligne_abandon())

    def test_the_step_is_recorded_only_after_the_failure_path_gave_up(self):
        abandon = self.ligne_abandon()
        for ligne in self.lignes_affectation():
            self.assertGreater(
                ligne,
                abandon,
                "lst_upgrade_odoo est marqué fait avant que l'échec ait"
                " pu renoncer : la reprise sautera OpenUpgrade",
            )

    def test_it_is_recorded_exactly_once(self):
        # Deux affectations, et l'une repasserait devant l'échec.
        self.assertEqual(len(self.lignes_affectation()), 1)


class TestDiscardingTheCloneDiscardsItsPreparation(unittest.TestCase):
    """Rebâtir le clone annule tout ce qu'on lui avait fait.

    Quand OpenUpgrade échoue, le pilote remet le drapeau de clonage à zéro
    pour que la base intermédiaire soit refaite depuis la version
    précédente. Mais les drapeaux des étapes qui avaient préparé CE
    clone — le SQL de pré-migration, les désinstallations, les
    installations — restaient debout. La base neuve repartait donc sans
    sa préparation, et OpenUpgrade retombait sur le problème même que le
    SQL existe pour écarter.
    """

    PAR_CLONE = (
        "lst_fix_migration_odoo",
        "lst_module_uninstall_module",
        "lst_module_install_module",
    )

    def bloc_abandon(self):
        with io.open(SOURCE, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        for noeud in ast.walk(arbre):
            if isinstance(
                noeud, ast.If
            ) and TestAFailedOpenUpgradeStaysUnrecorded._remet_le_clone_a_zero(
                noeud
            ):
                return noeud
        return None

    def remis_a_zero(self):
        """Les listes que ce bloc remet à leur valeur vide."""
        noms = set()
        for petit in ast.walk(self.bloc_abandon()):
            if not isinstance(petit, ast.Assign):
                continue
            if not (
                isinstance(petit.value, ast.Constant)
                and petit.value.value is False
            ) and not (
                isinstance(petit.value, ast.List) and not petit.value.elts
            ):
                continue
            for cible in petit.targets:
                if isinstance(cible, ast.Subscript) and isinstance(
                    cible.value, ast.Name
                ):
                    noms.add(cible.value.id)
        return noms

    def test_the_failure_block_is_found(self):
        self.assertIsNotNone(self.bloc_abandon())

    def test_every_per_clone_flag_is_reset(self):
        remis = self.remis_a_zero()
        for nom in self.PAR_CLONE:
            self.assertIn(nom, remis, f"{nom} survit à son clone")

    def test_each_reset_is_persisted(self):
        # Remettre la liste à zéro sans l'écrire ne survit pas au
        # processus : c'est la reprise qui relit le fichier.
        corps = ast.dump(self.bloc_abandon())
        for cle in (
            "state_4_fix_migration_odoo_lst",
            "state_4_uninstall_module",
            "state_4_install_module",
        ):
            self.assertIn(cle, corps)
        self.assertIn("write_config", corps)


if __name__ == "__main__":
    unittest.main()
