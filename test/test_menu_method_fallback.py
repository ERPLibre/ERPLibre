#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le repli des menus Proxmox et QEMU/KVM : le numéro tapé joue l'entrée.

Une entrée peut porter sa destination dans « method » plutôt que dans un
« elif » numéroté. execute_from_configuration ne lit pas cette clé : un repli
qui lui passe l'entrée n'appelle rien, et le menu se réaffiche sans un mot.
MenuCoherence apparie libellés et méthodes en lisant le source et croit
« method » sur parole ; ces épreuves tapent le numéro AFFICHÉ et regardent
ce qui est réellement appelé.

Tout est bouchonné en deçà du menu : aucun hôte, aucune VM, aucun
sous-processus. Les entrées greffées sont inventées et remplacent ce que
todo.json déclare, pour que le résultat ne dépende pas du poste.
"""

import io
import os
import re
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

sys.argv = ["todo.py"]

from script.todo import host_os  # noqa: E402
from script.todo import todo_i18n  # noqa: E402
from script.todo.devstack_report import DS_OK  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

GREFFE_COMMANDE = {
    "prompt_description": "Banc repli - greffe par commande",
    "makefile_cmd": "banc_repli_cible",
}
GREFFE_METHODE = {
    "prompt_description": "Banc repli - greffe par méthode",
    "method": "_banc_repli_greffe",
}


class RepliCase:
    """Socle : un menu dont le repli joue ce que son numéro désigne.

    À déclarer par la sous-classe : CLE (la greffe de todo.json que le menu
    lit) et ouvrir(), qui bouchonne ce que le menu interroge avant sa boucle
    et rend ce que le menu rend.
    """

    CLE = ""

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "fr"
        sys.argv = ["todo.py"]
        self.todo = TODO()
        # Méthodes appelées par leur nom, et entrées passées à
        # execute_from_configuration : les deux chemins du repli.
        self.appels = []
        self.executees = []
        self.todo.execute_from_configuration = (
            lambda entree, *_a, **_k: self.executees.append(entree)
        )
        self.greffe = [dict(GREFFE_COMMANDE), dict(GREFFE_METHODE)]
        # Les choix tels que le menu les numérote : fill_help_info les
        # reçoit, greffe comprise, juste avant la première question.
        self.choix = []
        vraie = self.todo.fill_help_info

        def capturer(choices):
            self.choix.append(choices)
            return vraie(choices)

        self.todo.fill_help_info = capturer

    def ouvrir(self):
        raise NotImplementedError

    def get_config(self, cle):
        return list(self.greffe) if cle == self.CLE else None

    @staticmethod
    def numero_affiche(aide, entree):
        """Le numéro que le menu affiche devant « entree », lu dans le texte
        de la question : c'est celui que l'utilisateur tape."""
        cle = entree.get("prompt_description_key")
        libelle = todo_i18n.t(cle) if cle else entree["prompt_description"]
        trouves = re.findall(
            r"^\[(\d+)\] " + re.escape(libelle) + r"$", aide, re.M
        )
        if len(trouves) != 1:
            raise AssertionError(f"« {libelle} » affiché {len(trouves)} fois")
        return trouves[0]

    def jouer(self, saisies):
        """Ouvre le menu et tape ce que « saisies(aide, choices) » rend,
        calculé sur le menu tel qu'il s'affiche, puis 0. Rend le texte vu."""
        file = None

        def repondre(aide, *_a, **_k):
            nonlocal file
            if file is None:
                file = iter(list(saisies(aide, self.choix[-1])) + ["0"])
            return next(file)

        vu = io.StringIO()
        with patch("click.prompt", side_effect=repondre), patch.object(
            self.todo.config_file, "get_config", side_effect=self.get_config
        ), redirect_stdout(vu):
            self.assertFalse(self.ouvrir())
        return vu.getvalue()

    def methodes_enregistrees(self, choices):
        """Les entrées « method » de choices, chacune remplacée sur
        l'instance par un enregistreur qui note son nom."""
        entrees = [c for c in choices if c.get("method")]
        for entree in entrees:
            nom = entree["method"]
            setattr(self.todo, nom, lambda nom=nom: self.appels.append(nom))
        return entrees

    def test_every_method_entry_calls_its_method(self):
        entrees = []

        def saisies(aide, choices):
            entrees.extend(self.methodes_enregistrees(choices))
            return [self.numero_affiche(aide, e) for e in entrees]

        self.jouer(saisies)
        self.assertTrue(
            entrees, "aucune entrée « method » : rien n'est prouvé"
        )
        self.assertEqual([e["method"] for e in entrees], self.appels)
        self.assertEqual([], self.executees)

    def test_a_grafted_command_still_reaches_its_execution(self):
        """L'entrée de todo.json sans « method » garde son chemin."""

        def saisies(aide, _choices):
            return [self.numero_affiche(aide, self.greffe[0])]

        self.jouer(saisies)
        self.assertEqual([GREFFE_COMMANDE], self.executees)
        self.assertEqual([], self.appels)

    def test_an_unknown_answer_says_so_and_plays_nothing(self):
        def saisies(aide, _choices):
            dernier = max(
                int(n) for n in re.findall(r"^\[(\d+)\]", aide, re.M)
            )
            return [str(dernier + 1), "banc"]

        vu = self.jouer(saisies)
        self.assertEqual(2, vu.count(todo_i18n.t("Command not found !")))
        self.assertEqual([], self.executees)
        self.assertEqual([], self.appels)


class TestLeRepliProxmox(RepliCase, unittest.TestCase):
    CLE = "proxmox_from_makefile"

    def ouvrir(self):
        # L'hôte retenu est la seule chose que le menu lit avant sa boucle.
        self.todo._pve_host = lambda ask=True: {"target": "banc-repli"}
        self.todo._pve_label = lambda host: "banc-repli"
        return self.todo.prompt_execute_proxmox()

    def test_its_own_method_entry_is_played_without_a_graft(self):
        """L'entrée native déclarée par « method » : seule, elle suffit."""
        self.greffe = []
        entrees = []

        def saisies(aide, choices):
            entrees.extend(self.methodes_enregistrees(choices))
            return [self.numero_affiche(aide, e) for e in entrees]

        self.jouer(saisies)
        self.assertTrue(entrees, "aucune entrée « method » native")
        self.assertEqual([e["method"] for e in entrees], self.appels)


class TestLeRepliQemu(RepliCase, unittest.TestCase):
    CLE = "qemu_from_makefile"

    def ouvrir(self):
        # Les trois gardes d'entrée : l'hôte, le script de déploiement, les
        # outils. Aucune n'est éprouvée ici.
        self.todo._qemu_script_path = lambda: os.path.abspath(__file__)
        self.todo._qemu_ensure_tools = lambda: True
        with patch.object(host_os, "refuse_host", return_value=DS_OK):
            return self.todo.prompt_execute_qemu()


if __name__ == "__main__":
    unittest.main()
