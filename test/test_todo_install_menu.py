#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Installation de TODO : l'ordre des questions et ce qu'il lance.

Le choix se pose AVANT l'étape système. « First system installation? »
installe la pile de l'OS pour Odoo (update_env_version.py --install) ; posée
en premier, elle l'installait aussi pour qui ne voulait qu'une autre
technologie. Elle vient donc après le choix, pour les choix qui en ont
besoin — et pour une version d'Odoo, après les menus de l'environnement et
du type d'installation, qui offrent « 0: Back » : un retour ne doit rien
laisser d'installé.

Rien n'est installé ici : input() répond d'après une liste écrite d'avance,
subprocess.run et exec_command_live sont remplacés par des enregistreurs.
"""

import builtins
import contextlib
import io
import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.todo import install_non_interactif  # noqa: E402
from script.todo import todo as todo_module  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

QUESTION_SYSTEME = todo_module.t(
    "First system installation? Installs the system packages first (y/N): "
).strip()
QUESTION_SYSTEME_OUI = todo_module.t(
    "First system installation? Installs the system packages first (Y/n): "
).strip()
QUESTION_SUITE = todo_module.t("Rest of the installation:")


# La vraie sonde, gardée avant que setUpModule la remplace.
SONDE_REELLE = TODO.__dict__["_systeme_manquant"].__func__


def setUpModule():
    # La sonde du système lirait l'hôte : rien ne manque, sauf dans les
    # tests qui disent le contraire.
    patch = mock.patch.object(
        TODO, "_systeme_manquant", staticmethod(lambda: [])
    )
    patch.start()
    unittest.addModuleCleanup(patch.stop)


SANS_INTERACTION = "EL_NON_INTERACTIVE=1 EL_INSTALL_MISE=1 "


class ExecuteFactice:
    def __init__(self):
        self.commandes = []

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        return 0


class Banc(unittest.TestCase):
    def jouer(self, reponses, sudo=0, sudo_n=1):
        """Lance prompt_install ; rend (questions posées, commandes lancées).
        Le code rendu est dans self.code, chaque commande en liste dans
        self.listes. `sudo` est le code de « sudo -v », None pour un
        sudo absent ; `sudo_n`, celui de « sudo -n true » : 1 par défaut,
        un mot de passe serait demandé.

        Une question de plus que de réponses fait échouer le test en le
        disant, au lieu d'un StopIteration anonyme.
        """
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteFactice()
        questions = []
        suite = iter(reponses)

        def repondre(prompt=""):
            questions.append(prompt)
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question sans réponse prévue : {prompt!r}"
                ) from None

        lances = []

        def run(cmd, *args, **kwargs):
            lances.append(cmd)
            # « which pycharm » échoue : pas de question PyCharm ici.
            code = 1 if isinstance(cmd, list) and cmd[:1] == ["which"] else 0
            if cmd[:1] == ["sudo"] and sudo is None:
                raise FileNotFoundError("sudo")
            if cmd == ["sudo", "-v"]:
                code = sudo
            if cmd == ["sudo", "-n", "true"]:
                code = sudo_n
            return subprocess.CompletedProcess(cmd, code, "", "")

        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", run),
            mock.patch.object(todo_module.os, "geteuid", lambda: 1000),
            mock.patch.dict(os.environ, {}, clear=False),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            os.environ.pop("EL_NON_INTERACTIVE", None)
            self.code = todo.prompt_install()
            self.environ_apres = dict(os.environ)
        self.listes = [c for c in lances if isinstance(c, list)]
        commandes = todo.execute.commandes + [
            c for c in lances if isinstance(c, str)
        ]
        return questions, commandes


class TestOrdreDesQuestions(Banc):
    def test_the_choice_comes_before_the_system_question(self):
        questions, commandes = self.jouer(["0"])
        self.assertEqual(len(questions), 1)
        self.assertNotIn(QUESTION_SYSTEME, questions[0])
        self.assertEqual(commandes, [])

    def test_an_odoo_version_asks_system_then_the_rest(self):
        # La version, le développement, l'installation standard, la
        # question système, puis la suite, Entrée : interactive.
        questions, commandes = self.jouer(["1", "1", "1", "y", ""])
        self.assertEqual(len(questions), 5)
        for question in questions[:3]:
            self.assertNotIn(QUESTION_SYSTEME, question)
        self.assertIn(QUESTION_SYSTEME, questions[3])
        self.assertIn(QUESTION_SUITE, questions[4])
        self.assertFalse(any(SANS_INTERACTION in c for c in commandes))
        self.assertIn(
            "./script/version/update_env_version.py --install", commandes
        )
        self.assertTrue(
            any("--install_dev" in c for c in commandes), commandes
        )

    def test_enter_picks_production_then_standard(self):
        # La version, puis Entrée à l'environnement et au type.
        with mock.patch.object(
            todo_module, "gel_des_sources", lambda **_: (5, 5)
        ):
            questions, commandes = self.jouer(["1", "", "", "n", ""])
        self.assertIn("[2]", questions[1])
        self.assertIn("[1]", questions[2])
        principale = commandes[-1]
        self.assertTrue(principale.startswith("EL_FREEZE=1 "), principale)
        self.assertNotIn("--with_extra", principale)

    def test_enter_without_freeze_falls_back_to_development(self):
        with mock.patch.object(
            todo_module, "gel_des_sources", lambda **_: (0, 5)
        ):
            _, commandes = self.jouer(["1", "", "", "n", ""])
        self.assertTrue(commandes[-1].startswith("EL_FREEZE=0 "), commandes)

    def test_enter_installs_the_system_when_something_is_missing(self):
        with mock.patch.object(
            TODO, "_systeme_manquant", staticmethod(lambda: ["psql", "node"])
        ):
            questions, commandes = self.jouer(["1", "1", "1", "", ""])
        self.assertIn(QUESTION_SYSTEME_OUI, questions[3])
        self.assertIn(
            "./script/version/update_env_version.py --install", commandes
        )

    def test_enter_skips_the_system_when_nothing_is_missing(self):
        questions, commandes = self.jouer(["1", "1", "1", "", ""])
        self.assertIn(QUESTION_SYSTEME, questions[3])
        self.assertNotIn(
            "./script/version/update_env_version.py --install", commandes
        )

    def test_back_from_the_environment_menu_installs_nothing(self):
        """La version, puis « 0: Back » au choix de l'environnement."""
        questions, commandes = self.jouer(["1", "0"])
        self.assertEqual(len(questions), 2)
        for question in questions:
            self.assertNotIn(QUESTION_SYSTEME, question)
        self.assertEqual(commandes, [])

    def test_back_from_the_install_type_menu_installs_nothing(self):
        """La version, le développement, puis « 0: Back » au type."""
        questions, commandes = self.jouer(["1", "1", "0"])
        self.assertEqual(len(questions), 3)
        for question in questions:
            self.assertNotIn(QUESTION_SYSTEME, question)
        self.assertEqual(commandes, [])

    def test_erplibre_only_keeps_the_system_question(self):
        questions, commandes = self.jouer(["q", "n", ""])
        self.assertIn(QUESTION_SYSTEME, questions[1])
        self.assertIn(QUESTION_SUITE, questions[2])
        self.assertEqual(commandes, ["./script/install/install_erplibre.sh"])

    def test_mobile_offers_no_unattended_rest(self):
        # Sa dernière étape fait choisir un appareil Android au clavier.
        questions, commandes = self.jouer(["m", "n"])
        self.assertEqual(len(questions), 2)
        self.assertEqual(commandes, ["./mobile/install_and_run.sh"])


class TestSuiteSansInteraction(Banc):
    """« Sans interaction », choisi au menu après la question système :
    chaque question suivante prend sa réponse par défaut."""

    def test_unattended_prefixes_every_command(self):
        questions, commandes = self.jouer(["1", "1", "1", "y", "2"])
        self.assertEqual(len(questions), 5)
        self.assertEqual(
            commandes[0],
            SANS_INTERACTION
            + "./script/version/update_env_version.py --install",
        )
        self.assertTrue(commandes[-1].startswith(SANS_INTERACTION))
        self.assertIn("--install_dev", commandes[-1])
        self.assertEqual(self.code, 0)

    def test_unattended_leaves_todo_environment_alone(self):
        # Relancé après un échec, TODO refuserait son menu sous
        # EL_NON_INTERACTIVE=1.
        self.jouer(["1", "1", "1", "y", "2"])
        self.assertNotIn("EL_NON_INTERACTIVE", self.environ_apres)

    def test_sudo_password_asked_once_before_leaving(self):
        _, commandes = self.jouer(["1", "1", "1", "y", "2"])
        self.assertEqual(self.listes.count(["sudo", "-v"]), 1)
        # Avant l'étape système : elle passe par exec_command_live, que
        # ExecuteFactice note ; sudo -v est demandé, puis elle part.
        self.assertTrue(
            commandes[0].endswith("update_env_version.py --install")
        )

    def test_passwordless_sudo_asks_nothing(self):
        # NOPASSWD, ou un ticket valide : « sudo -v » n'est pas lancé, sudo-rs
        # le ferait authentifier quand même.
        _, commandes = self.jouer(["1", "1", "1", "y", "2"], sudo=1, sudo_n=0)
        self.assertNotIn(["sudo", "-v"], self.listes)
        self.assertEqual(self.code, 0)
        self.assertTrue(commandes[-1].startswith(SANS_INTERACTION))

    def test_missing_sudo_is_a_refusal_not_a_crash(self):
        _, commandes = self.jouer(["1", "1", "1", "y", "2"], sudo=None)
        self.assertEqual((self.code, commandes), (1, []))

    def test_an_exported_no_to_mise_is_kept(self):
        with mock.patch.dict(os.environ, {"EL_INSTALL_MISE": "0"}):
            _, commandes = self.jouer(["1", "1", "1", "n", "2"])
        self.assertTrue(
            commandes[-1].startswith(
                "EL_NON_INTERACTIVE=1 EL_INSTALL_MISE=0 "
            ),
            commandes,
        )

    def test_without_system_step_sudo_is_not_asked(self):
        self.jouer(["1", "1", "1", "n", "2"])
        self.assertNotIn(["sudo", "-v"], self.listes)

    def test_sudo_refused_installs_nothing(self):
        _, commandes = self.jouer(["1", "1", "1", "y", "2"], sudo=1)
        self.assertEqual((self.code, commandes), (1, []))

    def test_unknown_value_asks_again(self):
        questions, commandes = self.jouer(["1", "1", "1", "n", "x", "1"])
        self.assertEqual(len(questions), 6)
        self.assertIn(QUESTION_SUITE, questions[5])
        self.assertFalse(any(SANS_INTERACTION in c for c in commandes))


class TestIdentiteGit(Banc):
    """Sans identité git, le menu propose de la saisir après la question
    système et le choix d'une suite interactive.

    _fragment_repo_init est remplacé : repo_identity_ready rend
    `self.prete`, et chaque repo_identity_set est noté dans `self.ecrits`.
    """

    def setUp(self):
        self.prete = False
        self.ecrits = []

        def fragment(fonction, *args):
            if fonction == "repo_identity_ready":
                code = 0 if self.prete else 1
            else:
                self.ecrits.append((fonction, *args))
                code = 0
            return subprocess.CompletedProcess(fonction, code, "", "")

        patch = mock.patch.object(
            TODO, "_fragment_repo_init", staticmethod(fragment)
        )
        patch.start()
        self.addCleanup(patch.stop)

    def test_identite_presente_aucune_question(self):
        self.prete = True
        questions, _ = self.jouer(["1", "1", "1", "n", ""])
        self.assertEqual(len(questions), 5)
        self.assertIn(QUESTION_SYSTEME, questions[3])

    def test_refus_rien_n_est_ecrit(self):
        questions, commandes = self.jouer(["1", "1", "1", "n", "", "n"])
        self.assertIn(QUESTION_SYSTEME, questions[3])
        self.assertIn(QUESTION_SUITE, questions[4])
        self.assertIn(todo_module.t("Configure it now? (Y/n): "), questions[5])
        self.assertEqual(self.ecrits, [])
        self.assertTrue(any("--install_dev" in c for c in commandes))

    def test_saisie_confirmee_puis_ecrite(self):
        questions, _ = self.jouer(
            [
                "1",
                "1",
                "1",
                "n",
                "",
                "y",
                "Nom Fictif",
                "fictif@example.invalid",
                "y",
            ]
        )
        self.assertIn(QUESTION_SYSTEME, questions[3])
        self.assertEqual(
            self.ecrits,
            [("repo_identity_set", "Nom Fictif", "fictif@example.invalid")],
        )

    def test_courriel_invalide_redemande(self):
        self.jouer(
            [
                "1",
                "1",
                "1",
                "n",
                "",
                "y",
                "Nom Fictif",
                "sans-arobase",
                "fictif@example.invalid",
                "y",
            ]
        )
        self.assertEqual(
            self.ecrits,
            [("repo_identity_set", "Nom Fictif", "fictif@example.invalid")],
        )

    def test_non_a_la_confirmation_reprend_avec_defauts(self):
        questions, _ = self.jouer(
            [
                "1",
                "1",
                "1",
                "n",
                "",
                "y",
                "Nom Fictif",
                "fictif@example.invalid",
                "n",
                "",
                "autre@example.invalid",
                "y",
            ]
        )
        self.assertIn("[Nom Fictif]", questions[9])
        self.assertEqual(
            self.ecrits,
            [("repo_identity_set", "Nom Fictif", "autre@example.invalid")],
        )

    def test_entree_ouvre_la_saisie(self):
        questions, _ = self.jouer(
            [
                "1",
                "1",
                "1",
                "n",
                "",
                "",
                "Nom Fictif",
                "fictif@example.invalid",
                "y",
            ]
        )
        self.assertEqual(
            self.ecrits,
            [("repo_identity_set", "Nom Fictif", "fictif@example.invalid")],
        )

    def test_erplibre_seul_ne_propose_rien(self):
        questions, _ = self.jouer(["q", "n", ""])
        self.assertEqual(len(questions), 3)
        self.assertIn(QUESTION_SYSTEME, questions[1])

    def test_sans_interaction_rien_n_est_demande_ni_ecrit(self):
        questions, _ = self.jouer(["1", "1", "1", "n", "2"])
        self.assertEqual(len(questions), 5)
        self.assertEqual(self.ecrits, [])

    def test_retour_ne_propose_rien(self):
        questions, _ = self.jouer(["1", "1", "0"])
        self.assertEqual(len(questions), 3)


class ExecuteNote(ExecuteFactice):
    """Note aussi les options de chaque appel ; `echec` donne le code rendu
    par la commande qui le contient."""

    def __init__(self, echec=None):
        super().__init__()
        self.options = []
        self.echec = echec or {}

    def exec_command_live(self, cmd, **kwargs):
        self.commandes.append(cmd)
        self.options.append(kwargs)
        for motif, code in self.echec.items():
            if motif in cmd:
                return code
        return 0


class TestInstallCli(unittest.TestCase):
    """« ./todo.sh install » : réponses données d'avance, et en mode non
    interactif, aucune question, jamais.

    input() échoue s'il est appelé : une question en mode non interactif
    est un défaut. _fragment_repo_init et gel_des_sources sont remplacés :
    l'identité git est absente, chaque version a des commits gelés.
    """

    def setUp(self):
        self.ecrits = []
        self.pret = False
        self.mise_absente = False

        def fragment(fonction, *args):
            if fonction == "repo_identity_ready":
                code = 0 if self.pret else 1
            else:
                self.ecrits.append((fonction, *args))
                code = 0
            return subprocess.CompletedProcess(fonction, code, "", "")

        for patch in (
            mock.patch.object(
                TODO, "_fragment_repo_init", staticmethod(fragment)
            ),
            mock.patch.object(
                todo_module, "gel_des_sources", lambda **_: (5, 5)
            ),
            mock.patch.object(
                install_non_interactif,
                "mise_requis",
                lambda environ: self.mise_absente,
            ),
            mock.patch.dict(os.environ, {}, clear=False),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        for variable in (
            "EL_NON_INTERACTIVE",
            "EL_INSTALL_TARGET",
            "EL_FREEZE",
            "EL_WITH_EXTRA",
            "EL_INSTALL_SYSTEM",
            "EL_GIT_NAME",
            "EL_GIT_EMAIL",
            "EL_INSTALL_MISE",
        ):
            os.environ.pop(variable, None)

    def lancer(
        self, argv, echec=None, echec_principal=None, reponses=(), sudo=0
    ):
        """Lance install_cli ; rend (code, commandes, questions, sortie).

        `echec` : {motif: code} pour exec_command_live ; `echec_principal` :
        code de la commande d'installation, lancée par subprocess.run ;
        `sudo` : code du contrôle el_sudo_preflight."""
        todo = TODO.__new__(TODO)
        todo.execute = ExecuteNote(echec)
        self.todo = todo
        self.preflights = 0
        questions, suite = [], iter(reponses)

        def repondre(prompt=""):
            questions.append(prompt)
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(f"question posée : {prompt!r}") from None

        lances = []

        def run(cmd, *args, **kwargs):
            lances.append(cmd)
            if isinstance(cmd, list) and cmd[:1] == ["which"]:
                return subprocess.CompletedProcess(cmd, 1, "", "")
            if isinstance(cmd, list) and "el_sudo_preflight" in " ".join(cmd):
                self.preflights += 1
                return subprocess.CompletedProcess(cmd, sudo, "", "")
            if isinstance(cmd, str) and echec_principal:
                raise subprocess.CalledProcessError(echec_principal, cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        sortie = io.StringIO()
        relance = mock.Mock()
        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", run),
            mock.patch.object(TODO, "restart_script", relance),
            contextlib.redirect_stdout(sortie),
        ):
            code = todo.install_cli(argv)
        self.relance = relance
        commandes = todo.execute.commandes + [
            c for c in lances if isinstance(c, str)
        ]
        return code, commandes, questions, sortie.getvalue()

    TOUT = [
        "--non-interactive",
        "--target",
        "18.0",
        "--env",
        "dev",
        "--type",
        "standard",
        "--system",
        "yes",
    ]

    def test_aucune_question_et_tout_est_lance(self):
        code, commandes, questions, _ = self.lancer(self.TOUT)
        self.assertEqual(code, 0)
        self.assertEqual(questions, [])
        self.assertEqual(self.preflights, 1)
        self.assertEqual(
            commandes[0], "./script/version/update_env_version.py --install"
        )
        principale = commandes[-1]
        self.assertTrue(principale.startswith("EL_FREEZE=0 "), principale)
        self.assertIn("--install_dev", principale)
        self.assertNotIn("--with_extra", principale)
        self.assertEqual(os.environ.get("EL_NON_INTERACTIVE"), "1")

    def test_l_etape_systeme_tourne_ici_et_attend(self):
        self.lancer(self.TOUT)
        options = self.todo.execute.options[0]
        self.assertIs(options.get("source_erplibre"), False)
        self.assertIs(options.get("single_source_erplibre"), True)

    def test_production_et_extras(self):
        argv = [a for a in self.TOUT]
        argv[argv.index("dev")] = "prod"
        argv[argv.index("standard")] = "extra"
        _, commandes, _, _ = self.lancer(argv)
        self.assertTrue(commandes[-1].startswith("EL_FREEZE=1 "))
        self.assertTrue(commandes[-1].endswith(" --with_extra"))

    def test_sudo_qui_demanderait_un_mot_de_passe(self):
        code, commandes, questions, _ = self.lancer(self.TOUT, sudo=1)
        self.assertEqual((code, commandes, questions), (1, [], []))

    def test_sans_etape_systeme_sudo_n_est_pas_controle(self):
        argv = [a for a in self.TOUT]
        argv[argv.index("yes")] = "no"
        self.lancer(argv)
        self.assertEqual(self.preflights, 0)

    def test_cible_m_refusee(self):
        code, commandes, _, _ = self.lancer(
            ["--non-interactive", "--target", "m", "--system", "no"]
        )
        self.assertEqual((code, commandes), (2, []))

    def test_mise_absente_sans_reponse(self):
        self.mise_absente = True
        code, commandes, _, sortie = self.lancer(self.TOUT)
        self.assertEqual((code, commandes), (2, []))
        self.assertIn("--mise", sortie)

    def test_reponse_mise_transmise_aux_scripts(self):
        self.mise_absente = True
        code, _, _, _ = self.lancer(self.TOUT + ["--mise", "yes"])
        self.assertEqual(code, 0)
        self.assertEqual(os.environ.get("EL_INSTALL_MISE"), "1")

    def test_reponse_manquante_rien_n_est_lance(self):
        code, commandes, questions, sortie = self.lancer(
            ["--non-interactive", "--target", "18.0"]
        )
        self.assertEqual(code, 2)
        self.assertEqual((commandes, questions), ([], []))
        for attendu in ("--env", "--type", "--system"):
            self.assertIn(attendu, sortie)

    def test_mode_par_la_variable(self):
        os.environ["EL_NON_INTERACTIVE"] = "1"
        code, commandes, _, _ = self.lancer([])
        self.assertEqual((code, commandes), (2, []))

    def test_cible_inconnue(self):
        argv = [a for a in self.TOUT]
        argv[argv.index("18.0")] = "99.0"
        code, commandes, _, sortie = self.lancer(argv)
        self.assertEqual((code, commandes), (2, []))
        self.assertIn("99.0", sortie)

    def test_echec_systeme_arrete_avant_l_installation(self):
        code, commandes, _, _ = self.lancer(self.TOUT, echec={"--install": 7})
        self.assertEqual(code, 7)
        self.assertFalse(any("--install_dev" in c for c in commandes))

    def test_echec_de_l_installation_rend_son_code(self):
        code, _, _, _ = self.lancer(self.TOUT, echec_principal=3)
        self.assertEqual(code, 3)
        self.relance.assert_not_called()

    def test_sans_identite_rien_n_est_ecrit(self):
        self.lancer(self.TOUT)
        self.assertEqual(self.ecrits, [])

    def test_identite_donnee_est_ecrite(self):
        self.pret = True
        self.lancer(
            self.TOUT
            + ["--git-name", "Nom Fictif", "--git-email", "f@example.invalid"]
        )
        self.assertEqual(
            self.ecrits,
            [("repo_identity_set", "Nom Fictif", "f@example.invalid")],
        )

    def test_q_sans_environnement_ni_type(self):
        code, commandes, questions, _ = self.lancer(
            ["--non-interactive", "--target", "q", "--system", "no"]
        )
        self.assertEqual((code, questions), (0, []))
        self.assertEqual(commandes, ["./script/install/install_erplibre.sh"])

    def test_mise_no_survit_a_la_suite_sans_interaction(self):
        # Une affectation en préfixe écraserait --mise no.
        code, commandes, _, _ = self.lancer(
            ["--target", "18.0", "--env", "dev", "--type", "standard"]
            + ["--system", "no", "--mise", "no"],
            reponses=["2"],
        )
        self.assertEqual(code, 0)
        self.assertTrue(
            commandes[-1].startswith(
                "EL_NON_INTERACTIVE=1 EL_INSTALL_MISE=0 "
            ),
            commandes,
        )

    def test_sans_mode_les_reponses_absentes_sont_demandees(self):
        # La cible est donnée, l'environnement et le reste sont demandés.
        code, _, questions, _ = self.lancer(
            ["--target", "18.0"], reponses=["1", "1", "n", "", "n"]
        )
        self.assertEqual(code, 0)
        self.assertEqual(len(questions), 5)
        version = todo_module.t("Choose a version:")
        self.assertFalse(any(version in q for q in questions))


class TestPycharmFerme(unittest.TestCase):
    """PyCharm s'ouvre sans bloquer : l'installation attend qu'il soit
    refermé, faute de quoi son analyse du projet, reprise à chaque fichier
    ajouté, ralentit l'installation."""

    def _attendre(self, reponses, pgrep):
        """Lance _wait_pycharm_closed ; rend (questions, appels pgrep, sortie).

        `pgrep` donne le code de chaque appel à pgrep, dans l'ordre : 0, un
        PyCharm tourne encore ; 1, plus aucun."""
        todo = TODO.__new__(TODO)
        questions, appels = [], []
        suite, codes = iter(reponses), iter(pgrep)

        def repondre(prompt=""):
            questions.append(prompt)
            return next(suite)

        def run(cmd, *args, **kwargs):
            appels.append(cmd)
            return subprocess.CompletedProcess(cmd, next(codes), "", "")

        sortie = io.StringIO()
        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", run),
            contextlib.redirect_stdout(sortie),
        ):
            todo._wait_pycharm_closed()
        return questions, appels, sortie.getvalue()

    def test_continues_once_pycharm_is_closed(self):
        questions, appels, _ = self._attendre([""], [1])
        self.assertEqual(len(questions), 1)
        self.assertEqual(appels, [["pgrep", "-f", "-i", "pycharm"]])

    def test_asks_again_while_pycharm_runs(self):
        questions, appels, sortie = self._attendre(["", ""], [0, 1])
        self.assertEqual(len(questions), 2)
        self.assertEqual(len(appels), 2)
        self.assertIn(
            todo_module.t(
                "PyCharm is still running: close it before continuing."
            ),
            sortie,
        )

    def test_c_continues_without_checking(self):
        questions, appels, _ = self._attendre(["c"], [])
        self.assertEqual(len(questions), 1)
        self.assertEqual(appels, [])

    def test_the_install_waits_for_pycharm_closed(self):
        """Le parcours entier : PyCharm ouvert, puis l'attente, puis
        seulement la commande d'installation."""
        todo = TODO.__new__(TODO)
        evenements = []

        class Execute:
            def exec_command_live(self, cmd, **kwargs):
                evenements.append(("lance", cmd))
                return 0

        todo.execute = Execute()
        # Version, environnement, type, système non, suite interactive,
        # PyCharm oui, Entrée.
        suite = iter(["1", "1", "1", "n", "", "y", ""])

        def repondre(prompt=""):
            evenements.append(("question", prompt))
            return next(suite)

        def run(cmd, *args, **kwargs):
            if isinstance(cmd, str):
                # La commande d'installation passe par subprocess.run.
                evenements.append(("lance", cmd))
                return subprocess.CompletedProcess(cmd, 0, "", "")
            if cmd[:1] == ["which"]:
                return subprocess.CompletedProcess(cmd, 0, "", "")
            return subprocess.CompletedProcess(cmd, 1, "", "")  # pgrep

        exists = os.path.exists
        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", run),
            # L'identité git a ses tests : TestIdentiteGit.
            mock.patch.object(
                TODO, "_proposer_identite_git", lambda self, **_: None
            ),
            mock.patch.object(
                todo_module.os.path,
                "exists",
                lambda p: False if p == ".idea" else exists(p),
            ),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            todo.prompt_install()
        rangs = {
            "pycharm": next(
                i
                for i, (k, v) in enumerate(evenements)
                if k == "lance" and "pycharm" in v
            ),
            "attente": next(
                i
                for i, (k, v) in enumerate(evenements)
                if k == "question" and "PyCharm" in v and "(c " in v
            ),
            "installation": next(
                i
                for i, (k, v) in enumerate(evenements)
                if k == "lance" and "--install_dev" in v
            ),
        }
        self.assertLess(rangs["pycharm"], rangs["attente"])
        self.assertLess(rangs["attente"], rangs["installation"])


class TestSondeSysteme(unittest.TestCase):
    """_systeme_manquant : ce que l'étape système poserait et qui manque."""

    def sonder(self, absentes=(), role=0):
        """`role` : code de psql, ou une exception qu'il lève."""
        self.appels = []

        def run(cmd, *a, **k):
            self.appels.append((cmd, k))
            if isinstance(role, BaseException):
                raise role
            return subprocess.CompletedProcess(cmd, role, "", "")

        with (
            mock.patch.object(
                todo_module.shutil,
                "which",
                lambda c, path=None: (
                    None if c in absentes else f"/usr/bin/{c}"
                ),
            ),
            mock.patch.object(todo_module.subprocess, "run", run),
        ):
            return SONDE_REELLE()

    def test_psql_ne_demande_jamais_de_mot_de_passe(self):
        # Une invite sur le terminal, tuée au délai, laisserait l'écho coupé.
        self.sonder()
        cmd, options = self.appels[0]
        self.assertIn("-w", cmd)
        self.assertEqual(options["env"].get("PGCONNECT_TIMEOUT"), "5")

    def test_delai_ou_erreur_valent_role_manquant(self):
        for erreur in (subprocess.TimeoutExpired("psql", 10), OSError()):
            with self.subTest(erreur=type(erreur).__name__):
                self.assertEqual(len(self.sonder(role=erreur)), 1)

    def test_tout_est_la(self):
        self.assertEqual(self.sonder(), [])

    def test_commandes_et_role_absents(self):
        manque = self.sonder(absentes=("node", "npm"), role=2)
        self.assertEqual(
            manque[:2] + [len(manque)], ["node", "npm", 3], manque
        )

    def test_sans_psql_le_role_n_est_pas_sonde(self):
        self.assertEqual(self.sonder(absentes=("psql",), role=2), ["psql"])


PLUSIEURS = t(
    "Several numbers separated by spaces install those"
    " versions one after the other, in the order typed."
)
SANS_GEL = (
    "No frozen commit for this Odoo version: installing the development,"
    " on the branches."
)
GEL = "Production: each repository on its frozen commit."
LETTRES = "Letters and 0 are single choices, to type alone:"
INCOMPRIS = "Error, cannot understand value"
ECHEC = "The Bash script failed with return code"

# Un catalogue inventé, dans l'ordre que rend get_odoo_version : le menu le
# renverse, d'où « 1 » pour 21.0, « 2 » pour 17.0 et « 3 » pour 12.0.
CATALOGUE = [
    {"odoo_version": "12.0", "erplibre_version": "odoo12.0_python3.7.17"},
    {"odoo_version": "17.0", "erplibre_version": "odoo17.0_python3.10.18"},
    {
        "odoo_version": "21.0",
        "erplibre_version": "odoo21.0_python3.14.7",
        "postgresql_version": "18",
    },
]


class Poste:
    """Le checkout simulé : la version active et les Odoo installés.

    Une commande « --install_dev » rend sa version active, puis l'inscrit
    parmi les installées si elle réussit ; « --switch » ne fait que la
    rendre active. `echecs` donne le code de retour d'une version d'ERPLibre
    dont l'installation échoue.
    """

    def __init__(self, active="", installees=(), echecs=None):
        self.active = active
        self.installees = list(installees)
        self.echecs = echecs or {}
        self.lancees = []  # (commande, kwargs) dans l'ordre
        self.marquees = []

    def version_de(self, cmd):
        return cmd.split("--erplibre_version ", 1)[1].split()[0]

    def exec_command_live(self, cmd, **kwargs):
        self.lancees.append((cmd, kwargs))
        if "--switch" in cmd:
            self.active = self.version_de(cmd)
        return 0

    def run(self, cmd, *args, **kwargs):
        if isinstance(cmd, list):
            # « which pycharm » échoue : pas de question PyCharm ici.
            return subprocess.CompletedProcess(cmd, 1, "", "")
        self.lancees.append((cmd, kwargs))
        cible = self.version_de(cmd)
        self.active = cible
        code = self.echecs.get(cible, 0)
        if not code:
            self.installees.append(cible.split("_python", 1)[0])
        if code and kwargs.get("check"):
            raise subprocess.CalledProcessError(code, cmd)
        return subprocess.CompletedProcess(cmd, code, "", "")

    def get_odoo_version(self):
        odoo_active = self.active.split("_python", 1)[0] or None
        return [dict(e) for e in CATALOGUE], list(self.installees), odoo_active

    def commandes(self):
        return [cmd for cmd, _ in self.lancees]


class TestPlusieursVersions(unittest.TestCase):
    """Plusieurs numéros séparés par des espaces installent ces versions
    l'une après l'autre, dans l'ordre tapé ; l'environnement, le type et
    l'étape système ne sont demandés qu'une fois pour le lot."""

    def jouer(self, reponses, poste, gels=None):
        """Lance prompt_install ; rend (questions, sortie, restart_script).

        `gels` donne, par version d'Odoo, ce que rend gel_des_sources."""
        todo = TODO.__new__(TODO)
        todo.execute = poste
        todo._poetry_drift_version = lambda: poste.active
        todo._python_versions_marquer_courante = poste.marquees.append
        todo.restart_script = mock.Mock()
        # La suite interactive et l'identité git ont leurs propres tests :
        # ici, rien ne s'intercale entre l'étape système et le lot.
        todo._choisir_suite = lambda: False
        todo._proposer_identite_git = lambda **_kwargs: None
        questions = []
        suite = iter(reponses)
        gels = gels or {}

        def repondre(prompt=""):
            questions.append(prompt)
            try:
                return next(suite)
            except StopIteration:
                raise AssertionError(
                    f"question sans réponse prévue : {prompt!r}"
                ) from None

        sortie = io.StringIO()
        with (
            mock.patch.object(builtins, "input", repondre),
            mock.patch.object(todo_module.subprocess, "run", poste.run),
            mock.patch.object(
                todo_module, "get_odoo_version", poste.get_odoo_version
            ),
            mock.patch.object(
                todo_module,
                "gel_des_sources",
                lambda odoo_version: gels.get(odoo_version, (0, 9)),
            ),
            contextlib.redirect_stdout(sortie),
        ):
            todo.prompt_install()
        return questions, sortie.getvalue(), todo.restart_script

    def installations(self, poste):
        return [c for c in poste.commandes() if "--install_dev" in c]

    def test_the_prompt_says_several_numbers_may_be_given(self):
        poste = Poste()
        questions, _, _ = self.jouer(["0"], poste)
        self.assertIn(t("Choose one or more versions:"), questions[0])
        self.assertIn(PLUSIEURS, questions[0])

    def test_versions_install_in_the_order_typed(self):
        poste = Poste()
        # Les versions, le développement, le standard, système non.
        questions, _, _ = self.jouer(["3 1", "1", "1", "n"], poste)
        self.assertEqual(len(questions), 4)
        self.assertIn(QUESTION_SYSTEME, questions[3])
        self.assertEqual(
            self.installations(poste),
            [
                "EL_FREEZE=0 ./script/version/update_env_version.py"
                " --erplibre_version odoo12.0_python3.7.17 --install_dev",
                "EL_FREEZE=0 ./script/version/update_env_version.py"
                " --erplibre_version odoo21.0_python3.14.7 --install_dev",
            ],
        )

    def test_mode_and_extra_are_asked_once_for_the_batch(self):
        """La production, demandée une fois, se rabat sur le développement
        pour la seule version sans gel, et le dit en la nommant."""
        poste = Poste()
        _, sortie, _ = self.jouer(
            ["2 1", "2", "2", "n"],
            poste,
            gels={"21.0": (5, 9), "17.0": (0, 9)},
        )
        self.assertEqual(
            self.installations(poste),
            [
                "EL_FREEZE=0 ./script/version/update_env_version.py"
                " --erplibre_version odoo17.0_python3.10.18 --install_dev"
                " --with_extra",
                "EL_FREEZE=1 ./script/version/update_env_version.py"
                " --erplibre_version odoo21.0_python3.14.7 --install_dev"
                " --with_extra",
            ],
        )
        self.assertIn(f"Odoo 17.0: {t(SANS_GEL)}", sortie)
        self.assertIn(f"Odoo 21.0: {t(GEL)}", sortie)

    def test_invalid_selections_are_refused_and_asked_again(self):
        poste = Poste()
        questions, sortie, _ = self.jouer(
            ["q 3", "3 0", "3 3", "3 9", "3 x", "7", "0"], poste
        )
        self.assertEqual(len(questions), 7)
        self.assertEqual(poste.lancees, [])
        self.assertEqual(sortie.count(t(LETTRES)), 2)
        self.assertIn(f"{t('Version number given twice:')} '3'", sortie)
        self.assertIn(f"{t('Unknown version number:')} '9'", sortie)
        self.assertIn(f"{t(INCOMPRIS)} 'x'", sortie)
        self.assertIn(f"{t(INCOMPRIS)} '7'", sortie)

    def test_a_failure_does_not_stop_the_batch(self):
        poste = Poste(echecs={"odoo17.0_python3.10.18": 4})
        _, sortie, restart = self.jouer(["3 2 1", "1", "1", "n"], poste)
        self.assertEqual(len(self.installations(poste)), 3)
        resume = sortie.split(t("Installation summary:"), 1)[1]
        self.assertIn("✅ Odoo 12.0", resume)
        self.assertIn("❌ Odoo 17.0", resume)
        self.assertIn(f"{t(ECHEC)} 4.", resume)
        self.assertIn("✅ Odoo 21.0", resume)
        restart.assert_not_called()

    def test_the_version_active_before_becomes_active_again(self):
        poste = Poste(active="odoo17.0_python3.10.18", installees=["odoo17.0"])
        self.jouer(["1 3", "1", "1", "n"], poste)
        self.assertEqual(
            poste.commandes()[-1],
            "./script/version/update_env_version.py --erplibre_version"
            " odoo17.0_python3.10.18 --switch",
        )
        self.assertEqual(poste.active, "odoo17.0_python3.10.18")
        self.assertEqual(poste.marquees, ["odoo17.0_python3.10.18"])

    def test_without_the_previous_version_the_last_installed_stays(self):
        poste = Poste(active="odoo17.0_python3.10.18")
        self.jouer(["3 1", "1", "1", "n"], poste)
        self.assertFalse(any("--switch" in c for c in poste.commandes()))
        self.assertEqual(poste.active, "odoo21.0_python3.14.7")

    def test_a_failed_last_version_leaves_the_last_success_active(self):
        poste = Poste(echecs={"odoo12.0_python3.7.17": 2})
        self.jouer(["1 3", "1", "1", "n"], poste)
        self.assertEqual(poste.active, "odoo21.0_python3.14.7")
        self.assertIn("--switch", poste.commandes()[-1])

    def test_the_system_step_runs_once_with_the_highest_postgresql(self):
        poste = Poste()
        self.jouer(["3 1", "1", "1", "y"], poste)
        systeme = [
            kwargs
            for cmd, kwargs in poste.lancees
            if cmd == "./script/version/update_env_version.py --install"
        ]
        self.assertEqual(len(systeme), 1)
        self.assertEqual(systeme[0].get("new_env"), {"PG_VERSION": "18"})

    def test_without_postgresql_requirement_the_system_step_is_unchanged(
        self,
    ):
        poste = Poste()
        self.jouer(["3 2", "1", "1", "y"], poste)
        systeme = [
            kwargs
            for cmd, kwargs in poste.lancees
            if cmd == "./script/version/update_env_version.py --install"
        ]
        self.assertEqual(systeme, [{"source_erplibre": True}])

    def test_a_single_version_passes_its_postgresql_requirement(self):
        poste = Poste()
        self.jouer(["1", "1", "1", "y"], poste)
        systeme = [
            kwargs
            for cmd, kwargs in poste.lancees
            if cmd == "./script/version/update_env_version.py --install"
        ]
        self.assertEqual(systeme[0].get("new_env"), {"PG_VERSION": "18"})

    def test_a_single_version_keeps_its_behaviour(self):
        """Une version seule : pas de bilan, pas de retour, et un échec
        relance TODO comme avant."""
        poste = Poste(
            active="odoo17.0_python3.10.18",
            installees=["odoo17.0"],
            echecs={"odoo12.0_python3.7.17": 3},
        )
        _, sortie, restart = self.jouer(["3", "1", "1", "n"], poste)
        self.assertEqual(len(self.installations(poste)), 1)
        self.assertFalse(any("--switch" in c for c in poste.commandes()))
        self.assertNotIn(t("Installation summary:"), sortie)
        self.assertIn(f"{t(ECHEC)} 3.", sortie)
        restart.assert_called_once()


if __name__ == "__main__":
    unittest.main()
