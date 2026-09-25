#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu Set-OPS : ce que chaque numéro tapé déclenche vraiment.

`MenuCoherence` apparie les libellés et les « method » en LISANT le source ;
elle croit « method » sur parole. Ces épreuves tapent le numéro, par
`click.prompt` bouchonné, et regardent quelle méthode part.

L'écran d'état est éprouvé sur un relevé POSÉ : il ne lit ni le poste ni le
moteur, et tout sous-processus fait échouer l'épreuve. Les noms de moteur,
d'écosystème, de site et d'entrées greffées sont inventés et n'existent
nulle part ailleurs dans le dépôt.
"""

import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

RACINE_DEPOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE_DEPOT)

sys.argv = ["todo.py"]

from script.setops import engine, state  # noqa: E402
from script.todo import state_screen, todo_i18n  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

TODO_PY = Path(RACINE_DEPOT) / "script" / "todo" / "todo.py"

CHEMIN = "private/repo/Moteur-Fictif-Schiste"
SHA = "0123456789abcdef0123456789abcdef01234567"

# Un poste à moitié réglé : un clone manuel, aucun venv Ansible, un
# écosystème et un site montés. Les trois états y figurent.
RELEVE = state.Releve(
    systeme="Linux",
    chemin=CHEMIN,
    revision=SHA,
    parent_ignore=True,
    outil_repo=True,
    repo_initialise=False,
    chemin_occupe=True,
    moteur_present=True,
    gere_par_repo=None,
    arbre_repo=False,
    relation=engine.EGAL,
    ecart=0,
    modifies=0,
    ansible_playbook=False,
    version_ansible=None,
    plage_ansible=None,
    mineur_path=None,
    biblios_ecarts=(),
    collections_ecarts=(),
    biblios_epinglees=None,
    collections_epinglees=None,
    instance_reelle=False,
    ecosysteme="Ecosysteme-Fictif-Gneiss",
    plan_present=True,
    site="Site-Fictif-Pegmatite",
    site_brise=False,
    code_cle=0,
    outils_absents=(),
)

# Deux entrées que todo.json grefferait au menu Deploy.
GREFFES = [
    {"prompt_description": "greffe-fictive-serpentine"},
    {"prompt_description": "greffe-fictive-micaschiste"},
]

ENTREE_SETOPS = "Set-OPS - Sovereign ecosystem (plan, Ansible, Proxmox)"


def _interdit(*_a, **_k):
    raise AssertionError("l'écran d'état ne lance aucun processus")


class CasDeMenu(unittest.TestCase):
    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "fr"
        sys.argv = ["todo.py"]
        self.todo = TODO()
        self.joues = []


class TestLeSousMenuSetops(CasDeMenu):
    def setUp(self):
        super().setUp()
        self.todo._setops_state = lambda: self.joues.append("etat")

    def _menu(self, saisies):
        """Joue `saisies` au menu ; garde le texte de chaque invite et les
        saisies que le menu n'a pas lues."""
        self.invites = []
        self.restantes = list(saisies)

        def invite(texte, *_a, **_k):
            self.invites.append(texte)
            return self.restantes.pop(0)

        vu = io.StringIO()
        with patch("click.prompt", side_effect=invite), redirect_stdout(vu):
            rendu = self.todo.prompt_execute_setops()
        return rendu, vu.getvalue()

    def test_the_gesture_the_state_screen_names_is_reachable_here(self):
        """L'écran d'état dit « « X » le pose ». Si aucune entrée ne porte
        ce libellé, il envoie chercher une commande qui n'existe pas.

        Le numéro n'est PAS écrit ici : il se LIT dans le menu, pour qu'une
        entrée posée plus haut ne fasse pas rougir l'épreuve.
        """
        self.todo._setops_ansible_env = lambda: self.joues.append("ansible")
        libelle = todo_i18n.t(state.GESTE_ANSIBLE)
        tapes = []

        def saisie(texte, *_a, **_k):
            if tapes:
                return "0"
            vus = [
                num
                for num, reste in re.findall(r"^\[(\d+)\] (.*)$", texte, re.M)
                if reste == libelle
            ]
            self.assertEqual(1, len(vus), f"« {libelle} » : {vus}")
            tapes.append(vus[0])
            return vus[0]

        with (
            patch("click.prompt", side_effect=saisie),
            redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(self.todo.prompt_execute_setops())
        self.assertEqual(["ansible"], self.joues)

    def test_the_state_line_names_that_same_gesture(self):
        """Les deux bouts de la couture : l'écran nomme, le menu porte."""
        vu = RELEVE._replace(ansible_playbook=False)
        # Le segment affiché est traduit : la ligne se désigne par son
        # RANG dans la liste des clés, comme l'écran la construit.
        rendu = state.lignes(vu)
        ligne = rendu[state.SEGMENTS.index(state.ANSIBLE)]
        self.assertIn(todo_i18n.t(state.GESTE_ANSIBLE), ligne.detail)

    def test_typing_1_runs_the_state_screen(self):
        """L'écran joué, le menu reste ouvert : c'est le « 0 » qui le
        ferme, et non la fin de l'écran."""
        rendu, _ = self._menu(["1", "0"])
        self.assertEqual(["etat"], self.joues)
        self.assertFalse(rendu)
        self.assertEqual([], self.restantes, "sorti sans lire le « 0 »")
        self.assertEqual(2, len(self.invites))

    def test_the_state_screen_sits_under_the_integration_section(self):
        """Le titre de la section s'affiche avant l'entrée [1], sur une
        ligne qui n'est pas une entrée."""
        # Seul le texte de l'invite compte ici : le retour s'éprouve plus bas.
        self._menu(["0"])
        rangs = self.invites[0].splitlines()
        entree = next(
            i for i, rang in enumerate(rangs) if rang.startswith("[1] ")
        )
        self.assertTrue(
            any(
                todo_i18n.t("Integration") in rang
                for rang in rangs[:entree]
                if not rang.startswith("[")
            ),
            self.invites[0],
        )

    def test_an_unknown_number_says_so_instead_of_acting(self):
        _, vu = self._menu(["99", "0"])
        self.assertEqual([], self.joues)
        self.assertIn(todo_i18n.t("Command not found !"), vu)

    def test_zero_goes_back_to_the_calling_menu(self):
        rendu, _ = self._menu(["0"])
        self.assertIs(False, rendu)
        self.assertEqual([], self.joues)


class TestDepuisDeploy(CasDeMenu):
    """Le numéro AFFICHÉ d'une entrée du menu Deploy, lu dans le texte du
    menu, mène à cette entrée — avec ou sans entrées greffées par
    todo.json."""

    def setUp(self):
        super().setUp()
        self.todo.prompt_execute_setops = lambda: self.joues.append("setops")
        self.todo.execute_from_configuration = lambda entree: (
            self.joues.append(entree["prompt_description"])
        )

    def _deploy(self, greffes, saisie):
        """Ouvre le menu Deploy, todo.json greffant `greffes` ; `saisie`
        reçoit le texte du menu et rend le numéro tapé, puis « 0 »."""
        with (
            patch.object(
                self.todo.config_file, "get_config", return_value=greffes
            ),
            patch("click.prompt", side_effect=saisie),
            redirect_stdout(io.StringIO()),
        ):
            self.assertFalse(self.todo.prompt_execute_deploy())

    def _numero(self, texte, libelle):
        """Le numéro que le menu affiche devant `libelle`, une seule fois."""
        trouves = [
            n
            for n, reste in re.findall(r"^\[(\d+)\] (.*)$", texte, re.M)
            if reste == libelle
        ]
        self.assertEqual(1, len(trouves), f"« {libelle} » : {trouves}")
        return trouves[0]

    def _rang_affiche(self, greffes, libelle):
        """Le numéro affiché de `libelle`, lu sans rien lancer."""
        vus = []

        def saisie(texte, *_a, **_k):
            vus.append(self._numero(texte, libelle))
            return "0"

        self._deploy(greffes, saisie)
        return vus[0]

    def _taper(self, greffes, libelle):
        """Tape le numéro affiché de `libelle`, puis revient."""
        tapes = []

        def saisie(texte, *_a, **_k):
            if tapes:
                return "0"
            tapes.append(self._numero(texte, libelle))
            return tapes[0]

        self._deploy(greffes, saisie)

    def test_the_displayed_number_opens_the_setops_menu(self):
        self._taper([], todo_i18n.t(ENTREE_SETOPS))
        self.assertEqual(["setops"], self.joues)

    def test_a_graft_from_todo_json_does_not_move_it(self):
        """La greffe s'affiche APRÈS Set-OPS : son numéro ne dépend pas du
        nombre d'entrées que todo.json ajoute, et il mène au sous-menu."""
        libelle = todo_i18n.t(ENTREE_SETOPS)
        self.assertEqual(
            self._rang_affiche([], libelle),
            self._rang_affiche(list(GREFFES), libelle),
        )
        self._taper(list(GREFFES), libelle)
        self.assertEqual(["setops"], self.joues)

    # Chaque entrée déclarée par « method », et la méthode qu'elle atteint.
    # Le numéro n'est PAS écrit ici : il se lit dans le menu, sans quoi une
    # entrée posée plus haut par l'amont ferait rougir ce contrôle alors que
    # rien n'est cassé — et c'est justement ce qu'il doit prouver.
    ENTREES = {
        "Deploy - VM backends (which one this machine uses)": (
            "_deploy_vm_backends"
        ),
        "Deploy - Site address book (what a confined VM reaches)": (
            "prompt_execute_egress_book"
        ),
        "Lima - instances (macOS, Linux)": "prompt_execute_lima",
        "Deploy - verify this station, layer by layer": (
            "_qemu_verify_station"
        ),
        "Deploy - verify a deployed VM, layer by layer": "_qemu_verify_vm",
        ENTREE_SETOPS: "prompt_execute_setops",
    }

    def test_each_entry_reaches_its_own_method(self):
        for greffes in ([], GREFFES):
            for cle, methode in self.ENTREES.items():
                with self.subTest(greffes=len(greffes), entree=cle):
                    joues = []
                    for nom in self.ENTREES.values():
                        setattr(self.todo, nom, lambda n=nom: joues.append(n))
                    self._taper(list(greffes), todo_i18n.t(cle))
                    self.assertEqual([methode], joues)

    def test_setops_comes_last_so_no_entry_moves(self):
        """Ce qui garantit qu'aucune entrée n'a changé de numéro : la neuve
        est posée APRÈS toutes les autres. Seules les greffes de todo.json
        la suivent, ce que `test_a_graft_from_todo_json_does_not_move_it`
        tient de son côté."""
        vus = []

        def saisie(texte, *_a, **_k):
            vus.extend(re.findall(r"^\[(\d+)\] ", texte, re.M))
            return "0"

        self._deploy([], saisie)
        dernier = max(int(n) for n in vus if n != "0")
        self.assertEqual(
            str(dernier),
            self._rang_affiche([], todo_i18n.t(ENTREE_SETOPS)),
        )

    def test_the_grafted_entries_still_run_under_their_number(self):
        for entree in GREFFES:
            with self.subTest(entree=entree["prompt_description"]):
                self.joues.clear()
                self._taper(list(GREFFES), entree["prompt_description"])
                self.assertEqual([entree["prompt_description"]], self.joues)


class TestLEcranDEtat(CasDeMenu):
    def _ecran(self):
        vu = io.StringIO()
        with (
            patch.object(state, "releve", return_value=RELEVE),
            patch("subprocess.run", side_effect=_interdit),
            patch("subprocess.Popen", side_effect=_interdit),
            redirect_stdout(vu),
        ):
            rendu = self.todo._setops_state()
        self.assertIsNone(rendu)
        return vu.getvalue()

    def test_it_prints_ten_marked_lines(self):
        marques = tuple(state_screen.MARQUES.values())
        lignes = [
            l for l in self._ecran().splitlines() if l.lstrip()[:1] in marques
        ]
        self.assertEqual(10, len(lignes), "\n".join(lignes))

    def test_it_prints_the_shared_render_of_the_survey_in_order(self):
        """Ce que l'écran imprime EST le rendu commun des lignes décidées
        sur le relevé, dans l'ordre : ni copie, ni tri."""
        attendu = state_screen.render(state.lignes(RELEVE))
        vu = self._ecran()
        position = 0
        for ligne in attendu:
            trouvee = vu.find(ligne, position)
            self.assertGreaterEqual(trouvee, 0, f"absente : « {ligne} »")
            position = trouvee + len(ligne)

    def test_it_frames_the_lines_with_a_title_and_a_footer(self):
        vu = self._ecran()
        titre = vu.find(todo_i18n.t("Set-OPS integration, line by line"))
        pied = vu.find(
            todo_i18n.t(
                "Each « to set up here » line names the gesture that"
                " settles it; this screen launches nothing."
            )
        )
        premiere = vu.find(state.lignes(RELEVE)[0].segment)
        self.assertGreaterEqual(titre, 0)
        self.assertLess(titre, premiere)
        self.assertLess(premiere, pied)

    def test_the_survey_is_taken_at_the_repository_root(self):
        """La racine se dérive du code, et non du dossier courant : todo
        lancé d'ailleurs relève le même dépôt."""
        recues = []

        def releve(racine):
            recues.append(racine)
            return RELEVE

        ailleurs = tempfile.mkdtemp(prefix="setops-menu-")
        self.addCleanup(os.rmdir, ailleurs)
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(ailleurs)
        with (
            patch.object(state, "releve", side_effect=releve),
            patch("subprocess.run", side_effect=_interdit),
            redirect_stdout(io.StringIO()),
        ):
            self.todo._setops_state()
        self.assertEqual(1, len(recues))
        self.assertTrue(os.path.samefile(RACINE_DEPOT, recues[0]))


class TestLaComposition(CasDeMenu):
    def test_the_mixin_is_composed_into_todo(self):
        from script.todo.setops_menu import SetopsMenuMixin

        self.assertIsInstance(self.todo, SetopsMenuMixin)

    def test_the_breadcrumb_names_the_path_the_documentation_gives(self):
        self.assertEqual(
            "TODO › Execute › Deploy › Set-OPS",
            TODO.menu_path(
                "run",
                "prompt_execute",
                "prompt_execute_deploy",
                "prompt_execute_setops",
            ),
        )

    def test_the_telemetry_tree_reads_the_setops_menu(self):
        """L'arbre des menus suit les imports de mixins de todo.py : une
        autre forme d'import laisserait le sous-menu hors de l'arbre."""
        from script.todo.todo_telemetry import _mixin_files

        noms = {f.name for f in _mixin_files(TODO_PY)}
        self.assertIn("setops_menu.py", noms)


if __name__ == "__main__":
    unittest.main()
