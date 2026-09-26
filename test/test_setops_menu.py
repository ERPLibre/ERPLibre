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

import builtins
import io
import os
import re
import stat
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

RACINE_DEPOT = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE_DEPOT)

sys.argv = ["todo.py"]

from script.setops import console, engine, runner, state, vaults  # noqa: E402
from script.setops import runbooks as registre  # noqa: E402
from script.todo import state_screen, todo_i18n  # noqa: E402
from script.todo.setops_menu import SetopsMenuMixin as M  # noqa: E402
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

# Un registre de banc, de la forme exacte que rend « lister --json ». Les
# identifiants sont inventés et n'existent nulle part ailleurs dans le dépôt.
REGISTRE_BANC = """[
  {"id": "banc-fictif-sequence", "titre": "Une sequence de banc",
   "portee": "tenant", "but": "Eprouver l ecran.", "etapes": [
    {"cible": "banc-mesurer", "libelle": "Mesure", "portee": "toute",
     "nature": "mesure", "pourquoi": "Parce que.", "variables": [],
     "fixes": {}},
    {"cible": "banc-ecrire", "libelle": "Ecrit", "portee": "tenant",
     "nature": "ecriture", "pourquoi": "Parce que.", "variables": [{"nom": "NOM", "invite": "Le nom", "facultatif": false}],
     "fixes": {}},
    {"cible": "banc-raser", "libelle": "Detruit", "portee": "toute",
     "nature": "destructif", "pourquoi": "Parce que.", "variables": [],
     "fixes": {"CONFIRMER": "true"}},
    {"cible": "banc-tenant", "libelle": "Locataire", "portee": "tenant",
     "nature": "mesure", "pourquoi": "Parce que.", "variables": [],
     "fixes": {}}]}
]
"""


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

    # Chaque geste que l'écran d'état NOMME, l'entrée qui doit le porter, et
    # le relevé qui rend cette ligne « à régler ». Un geste nommé par l'écran
    # s'ajoute ici, et les deux bouts de la couture sont tenus d'un coup.
    COUTURES = (
        (
            state.GESTE_ANSIBLE,
            "_setops_ansible_env",
            state.ANSIBLE,
            {"ansible_playbook": False},
        ),
        (state.GESTE_VOUTES, "_setops_vaults", state.CLE, {"code_cle": 1}),
    )

    def test_the_gesture_the_state_screen_names_is_reachable_here(self):
        """L'écran d'état dit « « X » le pose ». Si aucune entrée ne porte
        ce libellé, il envoie chercher une commande qui n'existe pas.

        Le numéro n'est PAS écrit ici : il se LIT dans le menu, pour qu'une
        entrée posée plus haut ne fasse pas rougir l'épreuve.
        """
        for geste, methode, _segment, _releve in self.COUTURES:
            with self.subTest(geste=geste):
                self.joues = []
                setattr(
                    self.todo, methode, lambda: self.joues.append("atteint")
                )
                libelle = todo_i18n.t(geste)
                tapes = []

                def saisie(texte, *_a, **_k):
                    if tapes:
                        return "0"
                    vus = [
                        num
                        for num, reste in re.findall(
                            r"^\[(\d+)\] (.*)$", texte, re.M
                        )
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
                self.assertEqual(["atteint"], self.joues)

    def test_the_state_line_names_that_same_gesture(self):
        """Les deux bouts de la couture : l'écran nomme, le menu porte."""
        for geste, _methode, segment, champs in self.COUTURES:
            with self.subTest(geste=geste):
                # Le segment affiché est traduit : la ligne se désigne par son
                # RANG dans la liste des clés, comme l'écran la construit.
                rendu = state.lignes(RELEVE._replace(**champs))
                ligne = rendu[state.SEGMENTS.index(segment)]
                self.assertIn(todo_i18n.t(geste), ligne.detail)

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


class CasDEcosysteme(CasDeMenu):
    """Les écrans d'écosystème, le moteur remplacé à la couture.

    `_setops_lancer` est LE point où le menu parle au moteur : le bouchonner
    isole la logique de l'écran sans rien lancer, et garde la trace de ce qui
    serait parti — cible, variables, confirmation.
    """

    TABLEAU = (
        "  INSTANCE               INDEX  VLAN        FEDERE  PROD \n"
        "  OPS-Fictif-Dolomie         7  1071-1079   oui     ?    \n"
        "* OPS-Fictif-Ankerite       12  —           LOCAL   non  \n"
        "\n* = instance active (symlink 'instance').\n"
    )
    MODELES = (
        "  socle\n  integral\n\n"
        "Index fédérés déjà pris : [7] (choisir un index libre).\n"
    )

    def setUp(self):
        super().setUp()
        self.lances = []
        self.reponses = {}
        self.todo._setops_moteur = lambda: "/moteur-fictif"
        self.todo._setops_lancer = self._lancer
        # Le rapport des voûtes ne passe pas par `_setops_lancer` : le moteur
        # y est appelé directement. Bouchonné ici, aucun écran ne lance de
        # sous-processus.
        self.todo._setops_voutes = lambda _m: ()

    def _lancer(
        self, moteur, cible, variables=(), confirmer=False, capture=True
    ):
        self.lances.append((cible, tuple(variables), confirmer))
        return self.reponses.get(cible, runner.Verdict(0, ""))

    def _ecran(self, methode, saisies=()):
        """Joue `methode`, les questions recevant `saisies` dans l'ordre."""
        file = list(saisies)
        vrai = builtins.input
        builtins.input = lambda *_a, **_k: file.pop(0) if file else ""
        vu = io.StringIO()
        try:
            with redirect_stdout(vu):
                getattr(self.todo, methode)()
        finally:
            builtins.input = vrai
        return vu.getvalue()

    def cibles(self):
        return [cible for cible, _v, _c in self.lances]


class TestLeBandeau(CasDEcosysteme):
    """Tous les gestes du moteur portent sur l'écosystème monté : l'écran
    qui agit doit dire lequel, sans qu'on ait à le demander."""

    ECRANS = (
        "_setops_ecosystems",
        "_setops_ecosystem_use",
        "_setops_ecosystem_create",
        "_setops_vaults",
    )

    def test_every_acting_screen_says_which_ecosystem_is_mounted(self):
        for methode in self.ECRANS:
            with self.subTest(ecran=methode):
                self.todo._setops_bandeau = lambda _m: print("BANDEAU-BANC")
                self.assertIn("BANDEAU-BANC", self._ecran(methode))

    def test_the_banner_names_the_mounted_one(self):
        with patch.object(
            state.ecosystems, "monte", lambda _m: "OPS-Fictif-Dolomie"
        ):
            vu = self._ecran("_setops_ecosystems")
        self.assertIn("OPS-Fictif-Dolomie", vu)

    def test_the_banner_says_so_when_nothing_is_mounted(self):
        with patch.object(state.ecosystems, "monte", lambda _m: ""):
            vu = self._ecran("_setops_ecosystems")
        self.assertIn(todo_i18n.t("none mounted"), vu)


class TestLaListeDesEcosystemes(CasDEcosysteme):
    def test_the_rows_are_numbered_and_the_mounted_one_marked(self):
        self.reponses["instances"] = runner.Verdict(0, self.TABLEAU)
        vu = self._ecran("_setops_ecosystems")
        self.assertIn("[1] OPS-Fictif-Dolomie", vu)
        self.assertIn("* [2] OPS-Fictif-Ankerite", vu)

    def test_no_ecosystem_says_so_rather_than_showing_an_empty_list(self):
        self.reponses["instances"] = runner.Verdict(
            0, "Aucune instance decouverte (depots freres).\n"
        )
        vu = self._ecran("_setops_ecosystems")
        self.assertIn(todo_i18n.t("no ecosystem beside the engine yet"), vu)

    def test_an_unreadable_answer_is_said_and_shown_raw(self):
        """Refuser sans montrer laisserait l'opérateur sans rien : la ligne
        est déjà affichée, la réponse du moteur doit l'être aussi."""
        self.reponses["instances"] = runner.Verdict(
            0, "quelque chose d'autre\n"
        )
        vu = self._ecran("_setops_ecosystems")
        self.assertIn(
            todo_i18n.t("unreadable answer; replay the line above by hand"), vu
        )
        self.assertIn("quelque chose d'autre", vu)

    def test_a_refusal_shows_the_table_and_the_engine_s_words(self):
        """Le moteur rend 2 sur une collision d'index : cacher la liste
        priverait de ce qui explique le refus."""
        self.reponses["instances"] = runner.Verdict(
            2, self.TABLEAU + "\n⚠  COLLISION d'index entre instances\n"
        )
        vu = self._ecran("_setops_ecosystems")
        self.assertIn("COLLISION", vu)
        self.assertIn("[1] OPS-Fictif-Dolomie", vu)


class TestLaBascule(CasDEcosysteme):
    def setUp(self):
        super().setUp()
        self.reponses["instances"] = runner.Verdict(0, self.TABLEAU)

    def test_the_number_typed_decides_which_name_is_sent(self):
        """Le nom n'est jamais retapé : retapé de travers, il désigne un
        dossier absent et le moteur refuse sans qu'on sache pourquoi."""
        self._ecran("_setops_ecosystem_use", ["2"])
        self.assertEqual(
            ("instance-utiliser", (("NOM", "OPS-Fictif-Ankerite"),), True),
            self.lances[-1],
        )

    def test_an_empty_answer_switches_nothing(self):
        self._ecran("_setops_ecosystem_use", [""])
        self.assertEqual(["instances"], self.cibles())

    def test_a_number_past_the_list_switches_nothing(self):
        self._ecran("_setops_ecosystem_use", ["9"])
        self.assertEqual(["instances"], self.cibles())

    def test_the_switch_is_confirmed_and_the_listing_is_not(self):
        """La confirmation distingue le geste qui ÉCRIT de celui qui lit."""
        self._ecran("_setops_ecosystem_use", ["1"])
        confirme = {cible: c for cible, _v, c in self.lances}
        self.assertEqual(
            {"instances": False, "instance-utiliser": True}, confirme
        )

    def test_a_refusal_is_reported_and_not_swallowed(self):
        self.reponses["instance-utiliser"] = runner.Verdict(2, "Refus: …\n")
        vu = self._ecran("_setops_ecosystem_use", ["1"])
        self.assertIn("Refus", vu)
        self.assertNotIn(todo_i18n.t("Done."), vu)

    def test_a_gesture_that_could_not_run_is_not_a_success(self):
        self.reponses["instance-utiliser"] = runner.Verdict(None, "")
        vu = self._ecran("_setops_ecosystem_use", ["1"])
        self.assertIn(todo_i18n.t("the gesture could not run at all"), vu)


class TestLaCreation(CasDEcosysteme):
    def setUp(self):
        super().setUp()
        self.reponses["instance-modeles"] = runner.Verdict(0, self.MODELES)

    def test_the_three_values_reach_the_line(self):
        self._ecran(
            "_setops_ecosystem_create", ["OPS-Fictif-Siderite", "2", "5"]
        )
        self.assertEqual(
            (
                "instance-creer",
                (
                    ("NOM", "OPS-Fictif-Siderite"),
                    ("MODELE", "integral"),
                    ("INDEX", "5"),
                ),
                True,
            ),
            self.lances[-1],
        )

    def test_an_empty_index_takes_the_free_one_proposed(self):
        """Proposer épargne de chercher un trou ; le moteur valide quand
        même ce qu'il reçoit."""
        self._ecran(
            "_setops_ecosystem_create", ["OPS-Fictif-Siderite", "1", ""]
        )
        variables = dict(self.lances[-1][1])
        self.assertEqual("0", variables["INDEX"])

    def test_an_empty_name_creates_nothing(self):
        self._ecran("_setops_ecosystem_create", [""])
        self.assertEqual(["instance-modeles"], self.cibles())

    def test_a_template_number_past_the_list_creates_nothing(self):
        self._ecran("_setops_ecosystem_create", ["OPS-Fictif-Siderite", "9"])
        self.assertEqual(["instance-modeles"], self.cibles())

    def test_an_unreadable_template_list_creates_nothing(self):
        self.reponses["instance-modeles"] = runner.Verdict(0, "autre chose\n")
        vu = self._ecran("_setops_ecosystem_create", ["x", "1", ""])
        self.assertEqual(["instance-modeles"], self.cibles())
        self.assertIn(
            todo_i18n.t("unreadable answer; replay the line above by hand"), vu
        )


class TestLesRunbooks(CasDEcosysteme):
    """Le navigateur de séquences : RIEN N'EST MASQUÉ.

    Une séquence dont on retirerait ce que todo ne lance pas mentirait par
    omission — et le pire cas n'est pas théorique : huit des dix-sept
    séquences réelles ont des trous, et l'une commencerait à son étape 2.
    """

    def setUp(self):
        super().setUp()
        self.todo._setops_registre = lambda _m: registre.lit_registre(
            REGISTRE_BANC
        )
        self.todo._pve_show = None

    def ecran(self, saisies=()):
        return self._ecran("_setops_runbooks", saisies)

    def test_every_sequence_is_listed_with_what_it_offers(self):
        vu = self.ecran()
        self.assertIn("banc-fictif-sequence", vu)
        self.assertIn("1/4", vu)

    def test_a_barred_step_stays_shown_with_its_reason(self):
        """C'est tout le parti : l'étape reste là, et dit pourquoi elle ne
        part pas d'ici."""
        vu = self.ecran(["1"])
        self.assertIn("banc-raser", vu)
        self.assertIn(
            todo_i18n.t("destructive: the engine keeps this one"), vu
        )
        self.assertIn(todo_i18n.t("no ecosystem mounted"), vu)

    def test_typing_a_barred_step_names_its_barrier(self):
        """Répondre « choix invalide » ferait croire à une faute de frappe,
        alors que le numéro est exactement celui qu'on lit."""
        vu = self.ecran(["1", "3"])
        self.assertIn(
            todo_i18n.t("destructive: the engine keeps this one"), vu
        )
        self.assertEqual([], self.cibles())

    def test_a_measure_runs_without_asking(self):
        self.ecran(["1", "1"])
        self.assertEqual(["banc-mesurer"], self.cibles())

    def test_a_write_asks_todo_s_own_confirmation(self):
        """La ligne affichée porte CONFIRMER=false, et pour ces cibles-là le
        drapeau ne veut rien dire : sans cette question, la ligne
        enseignerait qu'un « false » protège."""
        with patch.object(
            state.ecosystems, "monte", lambda _m: "OPS-Fictif-Dolomie"
        ):
            vu = self.ecran(["1", "2", "un-nom-fictif", "n"])
        self.assertIn(todo_i18n.t("This step WRITES."), vu)
        self.assertEqual([], self.cibles())

    def test_a_confirmed_write_carries_its_variables(self):
        with patch.object(
            state.ecosystems, "monte", lambda _m: "OPS-Fictif-Dolomie"
        ):
            self.ecran(["1", "2", "un-nom-fictif", "o"])
        self.assertEqual(
            ("banc-ecrire", (("NOM", "un-nom-fictif"),), False),
            self.lances[-1],
        )

    def test_a_missing_variable_runs_nothing(self):
        with patch.object(
            state.ecosystems, "monte", lambda _m: "OPS-Fictif-Dolomie"
        ):
            vu = self.ecran(["1", "2", ""])
        self.assertIn("NOM", vu)
        self.assertEqual([], self.cibles())

    def test_an_unreadable_registry_lists_nothing(self):
        self.todo._setops_registre = lambda _m: None
        self.ecran(["1"])
        self.assertEqual([], self.cibles())


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


class CasDeVoute(CasDEcosysteme):
    """L'écran des clés, le rapport du moteur POSÉ.

    Les noms de dépôt et les chemins sont inventés ; le chemin de clé pointe
    dans un dossier temporaire, parce que la pose écrit vraiment.
    """

    def setUp(self):
        super().setUp()
        self.dossier = tempfile.mkdtemp(prefix="setops-voutes-ecran-")
        self.addCleanup(self._menage)
        self.chemin = os.path.join(self.dossier, "setops-vault-fabrique-nord")
        self.todo._setops_voutes = lambda _m: self.voutes

    def _menage(self):
        for nom in os.listdir(self.dossier):
            os.unlink(os.path.join(self.dossier, nom))
        os.rmdir(self.dossier)

    def voute(self, role, nom, etat, chemin=None):
        return vaults.Voute(
            role=role,
            nom=nom,
            etat=etat,
            chemin=chemin if chemin is not None else self.chemin,
        )

    @property
    def reglee(self):
        """Une machine en ordre : sa clé présente, celle du site absente
        parce qu'elle DOIT l'être."""
        return (
            self.voute(vaults.INSTANCE, "Fabrique-Nord", vaults.PRESENTE),
            self.voute(
                vaults.HEBERGEUR,
                "Terrain-Nord",
                vaults.SANS_CLE,
                "/chemin-fictif/setops-vault-terrain-nord",
            ),
        )

    @property
    def bloquee(self):
        """La seule absence qui empêche cette machine de travailler."""
        return (
            self.voute(
                vaults.INSTANCE, "Fabrique-Nord", vaults.ABSENTE_BLOQUANTE
            ),
            self.voute(
                vaults.HEBERGEUR,
                "Terrain-Nord",
                vaults.SANS_CLE,
                "/chemin-fictif/setops-vault-terrain-nord",
            ),
        )

    def ecran(self, saisies=()):
        return self._ecran("_setops_vaults", saisies)


class TestLeTableauDesVoutes(CasDeVoute):
    def test_each_vault_is_named_with_its_repo_and_its_path(self):
        """Le contrôle positif : sans lui, un écran qui n'imprime rien
        passerait les épreuves d'absence ci-dessous."""
        self.voutes = self.reglee
        vu = self.ecran()
        self.assertIn("Fabrique-Nord", vu)
        self.assertIn("Terrain-Nord", vu)
        self.assertIn(self.chemin, vu)

    def test_the_three_states_do_not_read_alike(self):
        self.voutes = self.bloquee
        vu = self.ecran()
        for etat in (vaults.ABSENTE_BLOQUANTE, vaults.SANS_CLE):
            with self.subTest(etat=etat):
                marque, dit = self.todo.VOUTES[etat]
                self.assertIn(marque, vu)
                self.assertIn(todo_i18n.t(dit), vu)

    def test_nothing_to_name_says_so_instead_of_an_empty_table(self):
        self.voutes = ()
        vu = self.ecran()
        self.assertIn(
            todo_i18n.t(
                "nothing to name: no ecosystem mounted, and no underlay"
            ),
            vu,
        )

    def test_an_unreadable_report_offers_nothing(self):
        self.voutes = None
        self.ecran(["1"])
        self.assertEqual([], self.cibles())


class TestUneAbsenceVoulueNestPasUnePanne(CasDeVoute):
    """Sur le runner d'un locataire, la clé du site manque EXPRÈS. La
    présenter comme un défaut enverrait réparer une séparation qui tient — en
    donnant à ce poste des clés qu'il ne doit pas détenir."""

    SEPARATION = (
        "A key missing above is not a fault: it is a separation that"
        " holds. Posing one here would open nothing — the secret of"
        " that vault already exists elsewhere."
    )

    def test_the_separation_is_stated_as_a_fact(self):
        """Le garde porte sur la PHRASE, pas sur le cadenas : celui-ci marque
        aussi la ligne du tableau, et un garde posé sur lui reste vert le jour
        où la phrase disparaît."""
        self.voutes = self.reglee
        self.assertIn(todo_i18n.t(self.SEPARATION), self.ecran())

    def test_a_machine_with_nothing_shut_does_not_get_the_sentence(self):
        """Elle ne se dit que là où il y a une séparation à dire."""
        self.voutes = (
            self.voute(vaults.INSTANCE, "Fabrique-Nord", vaults.PRESENTE),
        )
        self.assertNotIn(todo_i18n.t(self.SEPARATION), self.ecran())

    def test_no_key_is_ever_offered_for_what_must_stay_shut(self):
        """Le seul geste offert est la lecture : rien ne propose de poser la
        clé de l'hébergeur."""
        self.voutes = self.reglee
        vu = self.ecran()
        # Apparié sur le libellé FORMÉ avec le nom de l'hébergeur : tronquer le
        # gabarit couperait dans « {nom} », et le garde ne rougirait jamais.
        offre = todo_i18n.t("Pose a NEW key for {nom}")
        self.assertNotIn(offre.format(nom="Terrain-Nord"), vu)
        self.assertNotIn(offre.format(nom="Fabrique-Nord"), vu)
        self.assertIn(vaults.CIBLE_RECENSER, vu)

    def test_the_pose_is_offered_only_for_the_blocking_one(self):
        self.voutes = self.bloquee
        vu = self.ecran()
        attendu = todo_i18n.t("Pose a NEW key for {nom}").format(
            nom="Fabrique-Nord"
        )
        self.assertIn(attendu, vu)
        self.assertNotIn("Terrain-Nord", vu.split(attendu)[1])


class TestLaPoseDepuisLEcran(CasDeVoute):
    def setUp(self):
        super().setUp()
        self.voutes = self.bloquee

    def test_the_key_is_posed_and_never_printed(self):
        """UNE CLÉ AFFICHÉE EST UNE CLÉ PERDUE : l'écran se garde, se copie,
        se colle dans un rapport."""
        vu = self.ecran(["1", "o"])
        self.assertTrue(os.path.isfile(self.chemin))
        with open(self.chemin, encoding="ascii") as tenu:
            contenu = tenu.read()
        self.assertNotIn(contenu, vu)
        self.assertNotIn(contenu[:8], vu)
        self.assertIn(todo_i18n.t("key posed, readable by you alone"), vu)

    def test_the_posed_file_is_readable_by_nobody_else(self):
        self.ecran(["1", "o"])
        mode = stat.S_IMODE(os.stat(self.chemin).st_mode)
        self.assertEqual(0, mode & (stat.S_IRWXG | stat.S_IRWXO))

    def test_an_existing_key_is_never_replaced(self):
        """Une clé remplacée rend sa voûte définitivement illisible."""
        with open(self.chemin, "w", encoding="ascii") as tenu:
            tenu.write("la-cle-qui-ouvre-deja-cette-voute")
        vu = self.ecran(["1", "o"])
        with open(self.chemin, encoding="ascii") as tenu:
            self.assertEqual("la-cle-qui-ouvre-deja-cette-voute", tenu.read())
        self.assertIn(todo_i18n.t(self.todo.POSES[vaults.DEJA_LA]), vu)

    def test_saying_no_poses_nothing(self):
        vu = self.ecran(["1", "n"])
        self.assertFalse(os.path.exists(self.chemin))
        self.assertIn(todo_i18n.t("Cancelled."), vu)

    def test_leaving_the_screen_poses_nothing(self):
        self.ecran([""])
        self.assertFalse(os.path.exists(self.chemin))

    def test_the_two_cases_are_said_before_the_question(self):
        """Une clé neuve n'ouvre qu'une voûte qui ne porte encore rien : sur
        une voûte déjà chiffrée, le secret revient de son archive."""
        vu = self.ecran(["1", "n"])
        self.assertIn(
            todo_i18n.t(
                "A new key only opens a vault that holds nothing yet. If this"
                " ecosystem already has encrypted files, bring its key back"
                " from its archive instead."
            ),
            vu,
        )


class TestCeQueLEcranNeLancePas(CasDeVoute):
    """`gpg` demande une phrase de passe : elle va de la main au terminal sans
    traverser un outil qui pourrait la retenir."""

    def setUp(self):
        super().setUp()
        self.voutes = self.reglee

    def test_the_passphrase_gestures_are_shown_and_never_run(self):
        vu = self.ecran(["1"])
        for cible in vaults.CIBLES_GPG:
            with self.subTest(cible=cible):
                self.assertIn(cible, vu)
                self.assertNotIn(cible, self.cibles())

    def test_each_handed_over_line_carries_the_variable_it_demands(self):
        """Une ligne remise sans sa variable se fait refuser par le moteur, et
        la remise n'aurait rien donné."""
        vu = self.ecran()
        for cible, variable in vaults.CIBLES_GPG.items():
            with self.subTest(cible=cible):
                self.assertIn(f"{cible} {variable}=", vu)

    def test_the_census_is_a_read_and_goes_through_the_engine(self):
        self.ecran(["1"])
        self.assertEqual([(vaults.CIBLE_RECENSER, (), False)], self.lances)


class TestLeRapportEstLuMemeSurUnRefus(CasDeVoute):
    """LE CODE 1 EST LE CAS QUE CET ÉCRAN EXISTE POUR MONTRER : le moteur rend
    1 quand la clé de l'instance montée manque. Gater la lecture sur un 0
    cacherait le rapport au moment où il sert."""

    def lire(self, verdict):
        self.todo.__dict__.pop("_setops_voutes", None)
        vu = io.StringIO()
        with patch.object(runner, "jouer", lambda *_a, **_k: verdict):
            with redirect_stdout(vu):
                return self.todo._setops_voutes("/moteur-fictif")

    def test_a_blocking_report_is_read_although_the_code_is_one(self):
        lues = self.lire(
            runner.Verdict(
                1,
                "instance    Fabrique-Nord        CLE ABSENTE   "
                "/chemin-fictif/setops-vault-fabrique-nord\n",
            )
        )
        self.assertEqual(1, len(lues))
        self.assertEqual(vaults.ABSENTE_BLOQUANTE, lues[0].etat)

    def test_a_gesture_that_could_not_run_at_all_reads_nothing(self):
        self.assertIsNone(self.lire(runner.Verdict(None, "")))


class TestLEcranSaitNommerToutCeQueLaCoucheRend(unittest.TestCase):
    """Les vocabulaires sont CLOS dans les couches, et l'écran les traduit.

    Un mot ajouté à une couche sans son entrée ici lève un `KeyError` au
    moment précis où l'écran devait le nommer — c'est-à-dire sur le cas rare
    que ce mot a été ajouté pour décrire.
    """

    TABLES = (
        (registre.BARRIERES, M.BARRIERES, "barrières de runbook"),
        (vaults.ETATS, M.VOUTES, "états de voûte"),
        (vaults.POSES, M.POSES, "verdicts de pose"),
        (console.ETATS, M.CONSOLES, "états de console"),
        (console.ARRETS, M.ARRETS, "verdicts d'arrêt"),
    )

    def test_every_word_of_every_closed_vocabulary_is_named(self):
        for vocabulaire, table, quoi in self.TABLES:
            for mot in vocabulaire:
                with self.subTest(quoi=quoi, mot=mot):
                    self.assertIn(mot, table)

    def test_no_table_names_a_word_the_layer_cannot_produce(self):
        """Une entrée orpheline est un mot retiré de la couche : la table
        garde alors une phrase que rien n'affiche plus."""
        for vocabulaire, table, quoi in self.TABLES:
            with self.subTest(quoi=quoi):
                self.assertEqual(set(), set(table) - set(vocabulaire))


class CasDeConsole(CasDEcosysteme):
    """L'écran de la console web, les trois faits POSÉS.

    Rien n'est lancé, rien n'est signalé, rien ne dort : le lancement détaché,
    la sonde du port et le signal sont tous bouchonnés.
    """

    SUIVI = console.Suivi(pid=4242, port=console.PORT)

    def setUp(self):
        super().setUp()
        self.mesure = (console.ARRETEE, 0, None)
        self.detaches = []
        self.signales = []
        self.pid_rendu = 4242
        self.todo._setops_console_etat = lambda env=None: self.mesure
        self.todo._qemu_self_address = lambda: ("poste-fictif.invalid", True)

    def _detacher(self, argv, env=None, cwd=None, journal=None):
        self.detaches.append(tuple(argv))
        return self.pid_rendu

    def ecran(self, saisies=(), ports=(True,)):
        """Joue l'écran ; `ports` est ce que la sonde du port répond."""
        vus = list(ports)
        with (
            patch.object(runner, "detacher", self._detacher),
            patch.object(
                console,
                "port_occupe",
                lambda *_a, **_k: vus.pop(0) if len(vus) > 1 else vus[0],
            ),
            patch.object(console, "ecrit_suivi", lambda *_a: True),
            patch.object(console, "oublie", lambda *_a: None),
            patch("os.killpg", lambda pid, sig: self.signales.append(pid)),
            patch("time.sleep", lambda _s: None),
        ):
            return self._ecran("_setops_console", saisies)


class TestLaPorteSansSerrureEstAnnoncee(CasDeConsole):
    """Une console sans authentification se juge AVANT de la lancer."""

    AVERTISSEMENT = (
        "This console has NO authentication: whatever reaches its port"
        " reads the whole inventory and triggers its gestures."
    )

    def test_the_warning_is_said(self):
        self.assertIn(todo_i18n.t(self.AVERTISSEMENT), self.ecran())

    def test_the_warning_comes_before_the_state(self):
        """En note de bas d'écran, il se lit après la décision."""
        vu = self.ecran()
        self.assertLess(
            vu.index(todo_i18n.t(self.AVERTISSEMENT)),
            vu.index(console.url()),
        )

    def test_the_way_in_from_elsewhere_is_an_ssh_forward(self):
        """Elle REMET l'authentification à SSH, là où lier largement la
        supprimerait."""
        vu = self.ecran()
        self.assertIn(
            console.redirection(
                "poste-fictif.invalid", os.environ.get("USER", "")
            ),
            vu,
        )

    def test_a_station_outside_an_ssh_session_is_told_so(self):
        self.todo._qemu_self_address = lambda: ("nom-fictif", False)
        self.assertIn(
            todo_i18n.t("Not in an SSH session: check the host address."),
            self.ecran(),
        )


class TestRienNePublieLaConsole(CasDeConsole):
    """Lier largement publierait sur le réseau une console sans serrure qui
    peut déployer sur la flotte."""

    def test_the_launched_command_never_names_an_address(self):
        """Le moteur lie 127.0.0.1 par défaut ; todo laisse faire ce défaut et
        ne passe aucun hôte. Éprouvé sur ce qui PART, pas sur le source."""
        self.mesure = (console.ARRETEE, 0, None)
        self.ecran(["1"])
        self.assertEqual(1, len(self.detaches))
        argv = self.detaches[0]
        self.assertIn(console.CIBLE, argv)
        for morceau in argv:
            with self.subTest(morceau=morceau):
                self.assertNotIn("--hote", morceau)
                self.assertNotIn("0.0.0.0", morceau)

    def test_the_address_shown_is_the_loopback(self):
        self.assertIn(f"http://{console.ADRESSE}:", self.ecran())


class TestCeQueLEcranOffre(CasDeConsole):
    def test_a_stopped_console_can_be_started(self):
        self.mesure = (console.ARRETEE, 0, None)
        self.ecran(["1"])
        self.assertEqual(1, len(self.detaches))

    def test_a_running_console_can_be_stopped(self):
        self.mesure = (console.VIVANTE, 4242, self.SUIVI)
        with patch.object(console, "tenue", lambda *_a, **_k: True):
            self.ecran(["1"], ports=(False,))
        self.assertEqual([4242], self.signales)

    def test_a_port_held_by_someone_else_offers_nothing(self):
        """Arrêter ce que todo n'a pas lancé porterait sur le travail de
        quelqu'un d'autre.

        Éprouvé sur ce que l'écran OFFRE, et non sur ce qui est parti : la
        couche refuse déjà un arrêt sans preuve, donc un geste offert à tort
        ne signalerait rien et passerait pour sage.
        """
        self.mesure = (console.TENU, 0, None)
        vu = self.ecran(["1"])
        self.assertEqual([], self.detaches)
        self.assertEqual([], self.signales)
        self.assertNotIn(todo_i18n.t("Stop it"), vu)
        self.assertNotIn(todo_i18n.t("Start it"), vu)
        self.assertIn(todo_i18n.t(self.todo.CONSOLES[console.TENU][1]), vu)

    def test_a_doubt_offers_nothing(self):
        """Lancer une seconde console lui disputerait le port."""
        self.mesure = (console.INCONNU, 0, None)
        vu = self.ecran(["1"])
        self.assertEqual([], self.detaches)
        self.assertEqual([], self.signales)
        self.assertNotIn(todo_i18n.t("Stop it"), vu)
        self.assertNotIn(todo_i18n.t("Start it"), vu)

    def test_leaving_the_screen_does_nothing(self):
        self.mesure = (console.ARRETEE, 0, None)
        self.ecran([""])
        self.assertEqual([], self.detaches)


class TestUnDetacheEchoueEnSilence(CasDeConsole):
    """Le PID rendu ne prouve pas que le serveur écoute."""

    def test_a_console_that_never_answers_is_not_announced_as_up(self):
        self.mesure = (console.ARRETEE, 0, None)
        vu = self.ecran(["1"], ports=(False,))
        self.assertNotIn("✅", vu)
        self.assertIn(console.JOURNAL, vu)

    def test_a_console_that_answers_is_announced_with_its_group(self):
        self.mesure = (console.ARRETEE, 0, None)
        vu = self.ecran(["1"], ports=(False, True))
        self.assertIn("✅", vu)
        self.assertIn("4242", vu)

    def test_a_launch_that_could_not_run_says_so(self):
        self.mesure = (console.ARRETEE, 0, None)
        self.pid_rendu = None
        vu = self.ecran(["1"])
        self.assertIn(todo_i18n.t("the gesture could not run at all"), vu)


class TestRienNestSignaleSansPreuve(CasDeConsole):
    """Un PID se recycle : le groupe visé serait celui d'un autre travail."""

    def test_a_recycled_pid_is_refused_and_nothing_is_signalled(self):
        self.mesure = (console.VIVANTE, 4242, self.SUIVI)
        with patch.object(console, "ligne_de_commande", lambda *_a: "autre"):
            vu = self.ecran(["1"])
        self.assertEqual([], self.signales)
        self.assertIn(todo_i18n.t(self.todo.ARRETS[console.ARRET_REFUSE]), vu)

    def test_an_unreadable_command_line_is_refused_too(self):
        self.mesure = (console.VIVANTE, 4242, self.SUIVI)
        with patch.object(console, "ligne_de_commande", lambda *_a: None):
            self.ecran(["1"])
        self.assertEqual([], self.signales)

    def test_a_port_still_held_after_the_signal_is_said(self):
        self.mesure = (console.VIVANTE, 4242, self.SUIVI)
        with patch.object(console, "tenue", lambda *_a, **_k: True):
            vu = self.ecran(["1"], ports=(True,))
        self.assertEqual([4242], self.signales)
        self.assertIn(todo_i18n.t(self.todo.ARRETS[console.ARRET_TENACE]), vu)


class TestLeReleveDeLaConsole(CasDEcosysteme):
    """La mesure elle-même, le suivi POSÉ sur le disque.

    Elle n'est pas bouchonnée ici : c'est elle qui décide de tout l'écran, et
    c'est elle qui laissait un PID mort rendre l'écran indécidable.
    """

    def setUp(self):
        super().setUp()
        self.dossier = tempfile.mkdtemp(prefix="setops-console-releve-")
        self.addCleanup(self._menage)
        self.env = {"XDG_RUNTIME_DIR": self.dossier}
        self.todo.__dict__.pop("_setops_console_etat", None)

    def _menage(self):
        for nom in os.listdir(self.dossier):
            os.unlink(os.path.join(self.dossier, nom))
        os.rmdir(self.dossier)

    def poser_suivi(self, pid):
        console.ecrit_suivi(console.chemin_suivi(self.env), pid, console.PORT)

    def relever(self, ligne, occupe):
        with (
            patch.object(console, "ligne_de_commande", lambda *_a: ligne),
            patch.object(console, "port_occupe", lambda *_a, **_k: occupe),
        ):
            return self.todo._setops_console_etat(self.env)

    def test_our_own_console_is_seen_alive(self):
        self.poser_suivi(4242)
        mot, pid, suivi = self.relever("make inventaire-ui", True)
        self.assertEqual((console.VIVANTE, 4242), (mot, pid))
        self.assertIsNotNone(suivi)

    def test_a_dead_pid_does_not_freeze_the_screen(self):
        """LE DÉFAUT QUE LA VRAIE EXÉCUTION A MONTRÉ : un lancement raté
        laisse un PID mort dans le suivi. Rendu « indécidable », l'écran
        n'offrait plus jamais de lancer la console."""
        self.poser_suivi(4242)
        mot, _pid, suivi = self.relever(console.ABSENT, False)
        self.assertEqual(console.ARRETEE, mot)
        self.assertIsNone(suivi)

    def test_a_stale_record_is_forgotten_rather_than_reread(self):
        """Un PID se réattribue : le relire à chaque visite finit par
        désigner le travail d'un autre."""
        self.poser_suivi(4242)
        self.relever(console.ABSENT, False)
        self.assertFalse(os.path.exists(console.chemin_suivi(self.env)))

    def test_a_record_that_still_holds_is_kept(self):
        self.poser_suivi(4242)
        self.relever("make inventaire-ui", True)
        self.assertTrue(os.path.exists(console.chemin_suivi(self.env)))

    def test_no_record_at_all_reads_as_stopped(self):
        mot, pid, suivi = self.relever(None, False)
        self.assertEqual((console.ARRETEE, 0, None), (mot, pid, suivi))

    def test_an_unreadable_command_line_is_never_guessed(self):
        self.poser_suivi(4242)
        mot, _pid, _suivi = self.relever(None, True)
        self.assertEqual(console.INCONNU, mot)


# Un registre de banc qui déclare quatre des cibles réelles. Les libellés, les
# « pourquoi » et les invites sont inventés ; seuls les noms de cible sont ceux
# du moteur, puisque ce sont eux que les portes nomment.
REGISTRE_PORTES = """[
  {"id": "banc-fictif-portes", "titre": "Banc des portes", "portee": "tenant",
   "but": "Eprouver les portes.", "etapes": [
    {"cible": "deployer", "libelle": "Deploie un hote de banc",
     "portee": "tenant", "nature": "ecriture", "pourquoi": "Parce que.",
     "duree": "~2 min", "fixes": {},
     "variables": [{"nom": "HOTE", "invite": "Le nom de l hote",
                    "facultatif": false}]},
    {"cible": "instancier-appliquer", "libelle": "Prend l inventaire",
     "portee": "tenant", "nature": "ecriture", "pourquoi": "Parce que.",
     "duree": "", "variables": [], "fixes": {}},
    {"cible": "config", "libelle": "Affiche la configuration",
     "portee": "tenant", "nature": "mesure", "pourquoi": "Parce que.",
     "duree": "", "variables": [], "fixes": {}},
    {"cible": "flotte-creer", "libelle": "Cree les VM manquantes",
     "portee": "poste", "nature": "ecriture", "pourquoi": "Parce que.",
     "duree": "", "variables": [], "fixes": {"CONFIRMER": "true"}}
   ]}
]
"""


class CasDePorte(CasDEcosysteme):
    """Les portes dédiées, le registre POSÉ.

    Le registre est bouchonné au même endroit que pour le navigateur : les
    deux doivent lire la MÊME source, et une porte qui décrirait le geste
    autrement que la séquence serait le défaut qu'on cherche à éviter.
    """

    def setUp(self):
        super().setUp()
        self.todo._setops_registre = lambda _m: registre.lit_registre(
            REGISTRE_PORTES
        )
        self.todo._pve_show = None
        self.captures = []
        # Un écosystème et un site MONTÉS : sans eux, toute étape de portée
        # « tenant » ou « site » est barrée, et les épreuves ci-dessous
        # mesureraient la barrière au lieu du geste.
        for nom, valeur in (
            ("monte", lambda _m: "Ecosysteme-Fictif-Gneiss"),
            ("site_monte", lambda _m: "Site-Fictif-Pegmatite"),
        ):
            correctif = patch.object(state.ecosystems, nom, valeur)
            correctif.start()
            self.addCleanup(correctif.stop)

    def _lancer(
        self, moteur, cible, variables=(), confirmer=False, capture=True
    ):
        """Comme celui de la classe mère, en gardant AUSSI la capture : c'est
        elle qui dit si le terminal a été rendu au moteur."""
        self.lances.append((cible, tuple(variables), confirmer))
        self.captures.append(capture)
        return self.reponses.get(cible, runner.Verdict(0, ""))

    def porte(self, cible, saisies=()):
        """Joue la porte de `cible`, les invites ÉCRITES comme un terminal les
        écrit.

        Le bouchon de la classe mère avale l'invite passée à `input`, si bien
        qu'un écran pourrait poser une question sans texte sans qu'une épreuve
        le voie. Ici l'invite est imprimée, donc éprouvable.
        """
        file = list(saisies)
        vrai = builtins.input

        def repondre(invite="", *_a, **_k):
            print(invite, end="")
            return file.pop(0) if file else ""

        builtins.input = repondre
        vu = io.StringIO()
        try:
            with redirect_stdout(vu):
                getattr(self.todo, registre.methode(cible))()
        finally:
            builtins.input = vrai
        return vu.getvalue()


class TestChaquePorteMeneAuGesteQuElleNomme(unittest.TestCase):
    """Onze portes, un seul écran : chaque méthode ne fait que nommer sa
    cible. Le nom de la méthode est DÉRIVÉ de la cible, donc aucune table
    n'est à tenir à jour ici."""

    def setUp(self):
        sys.argv = ["todo.py"]
        self.todo = TODO()
        self.vus = []
        self.todo._setops_geste = lambda cible: self.vus.append(cible)

    def test_every_declared_door_has_its_method(self):
        for cible in registre.PORTES:
            with self.subTest(cible=cible):
                self.assertTrue(
                    hasattr(self.todo, registre.methode(cible)),
                    registre.methode(cible),
                )

    def test_every_door_passes_its_own_target(self):
        """Une porte qui passerait la cible d'une autre lancerait le mauvais
        geste sous le bon libellé — le pire des deux mondes."""
        for cible in registre.PORTES:
            with self.subTest(cible=cible):
                self.vus = []
                getattr(self.todo, registre.methode(cible))()
                self.assertEqual([cible], self.vus)

    def test_no_method_opens_a_door_that_is_not_declared(self):
        """Une méthode orpheline offrirait un geste que le menu ne montre
        pas, et dont le libellé n'existe pas."""
        ouvertes = {
            nom for nom in dir(self.todo) if nom.startswith("_setops_geste_")
        }
        self.assertEqual(
            {registre.methode(c) for c in registre.PORTES}, ouvertes
        )


class TestLaPorteDecritCeQueLeRegistreDit(CasDePorte):
    def test_the_screen_carries_the_registry_s_own_words(self):
        """Le contrôle positif : sans lui, un écran muet passerait les
        épreuves de refus plus bas."""
        vu = self.porte("deployer", ["banc-hote-fictif", "o"])
        self.assertIn("Deploie un hote de banc", vu)
        self.assertIn("[tenant]", vu)
        self.assertIn("~2 min", vu)

    def test_the_prompt_is_the_one_the_engine_wrote(self):
        vu = self.porte("deployer", ["banc-hote-fictif", "o"])
        self.assertIn("Le nom de l hote", vu)
        self.assertEqual(
            [("deployer", (("HOTE", "banc-hote-fictif"),), False)], self.lances
        )

    def test_a_target_the_registry_does_not_declare_runs_nothing(self):
        self.todo._setops_registre = lambda _m: registre.lit_registre(
            REGISTRE_BANC
        )
        self.porte("deployer", ["banc-hote-fictif", "o"])
        self.assertEqual([], self.cibles())

    def test_an_unreadable_registry_runs_nothing(self):
        self.todo._setops_registre = lambda _m: None
        self.porte("deployer", ["banc-hote-fictif", "o"])
        self.assertEqual([], self.cibles())


class TestLaPorteEtLeNavigateurJugentPareil(CasDePorte):
    """La barrière est celle du navigateur, et non une seconde règle : une
    porte qui jugerait elle-même finirait par conduire ce que le navigateur
    refuse, ou l'inverse."""

    def test_what_the_engine_gates_stays_gated_behind_its_door(self):
        vu = self.porte("flotte-creer", ["o"])
        self.assertEqual([], self.cibles())
        self.assertIn(
            todo_i18n.t(self.todo.BARRIERES[registre.CONFIRMATION_MOTEUR]), vu
        )

    def test_a_tenant_gesture_without_an_ecosystem_is_refused(self):
        with patch.object(state.ecosystems, "monte", lambda _m: ""):
            vu = self.porte("deployer", ["banc-hote-fictif", "o"])
        self.assertEqual([], self.cibles())
        self.assertIn(
            todo_i18n.t(self.todo.BARRIERES[registre.SANS_ECOSYSTEME]), vu
        )


class TestUnInterrupteurNeSeDemandePasParSaValeur(CasDePorte):
    """La recette lit FORCE par « $(if $(FORCE),…) », et GNU make tient toute
    chaîne non vide pour vraie : celui qui tape « 0 » pour dire non force tout
    autant. C'est pourquoi la question est fermée."""

    def test_saying_yes_turns_it_on_with_one(self):
        self.porte("instancier-appliquer", ["o", "o"])
        self.assertEqual(
            [("instancier-appliquer", (("FORCE", "1"),), False)], self.lances
        )

    def test_saying_no_passes_nothing_at_all(self):
        """Pas même un « FORCE= » vide, qui se lirait comme une valeur
        choisie — et pas « FORCE=0 », qui forcerait."""
        self.porte("instancier-appliquer", ["n", "o"])
        self.assertEqual([("instancier-appliquer", (), False)], self.lances)

    def test_the_screen_says_it_is_a_switch(self):
        vu = self.porte("instancier-appliquer", ["n", "o"])
        self.assertIn(
            todo_i18n.t("any value at all turns it on, « 0 » included."), vu
        )

    def test_a_gesture_without_a_switch_is_never_asked_about(self):
        vu = self.porte("deployer", ["banc-hote-fictif", "o"])
        self.assertNotIn(
            todo_i18n.t("any value at all turns it on, « 0 » included."), vu
        )


class TestUneCibleQuiParleGardeLeTerminal(CasDePorte):
    """Capturée, une cible qui pose des questions lit une entrée fermée, rend
    « EOF » et n'a rien fait : le verdict est un refus que rien n'explique."""

    def test_the_terminal_is_handed_over(self):
        self.porte("config", ["o"])
        self.assertEqual([False], self.captures)

    def test_a_gesture_that_does_not_speak_is_captured(self):
        self.porte("deployer", ["banc-hote-fictif", "o"])
        self.assertEqual([True], self.captures)

    def test_an_assistant_that_writes_is_confirmed_although_declared_a_read(
        self,
    ):
        """Le registre le déclare « mesure » ; il écrit la configuration et
        sème la voûte. Sans la question, todo le lancerait comme une lecture
        anodine."""
        self.porte("config", ["n"])
        self.assertEqual([], self.cibles())
        self.assertTrue(
            registre.ecrit(
                registre.trouve(
                    registre.lit_registre(REGISTRE_PORTES), "config"
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
