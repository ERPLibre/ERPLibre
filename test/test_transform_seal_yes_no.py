#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Transform data, Analyse module et le sceau PAdES : les questions oui/non,
sous les règles de `ui.confirm`.

Chaque question est non par défaut, sauf cinq qui sont oui : remplacer les
nombres, remplacer le texte, ouvrir l'écran de paramétrage, écrire la copie
après l'aperçu, inclure les dépôts hors du manifeste. Un refus — Entrée là
où le défaut est non, n, non, une faute puis Ctrl+D, Ctrl+D — n'efface,
n'écrit, ne lance ni ne retire rien ; o, oui, y et yes agissent.

Les questions du formulaire d'anonymisation, après la première, prennent
`back` : Ctrl+D y abandonne tout le formulaire, comme « 0 » à ses
questions texte.

Rien ne part : `execute`, `traiter`, `retirer_du_registre` et
`analyser` sont des doubles qui notent, et les copies à effacer vivent
dans un dossier temporaire. Un `ScriptedPort` répond aux questions du
port ; `input` ne lit que les valeurs tapées.
"""

import os
import shutil
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.git import git_module_diff  # noqa: E402
from script.todo import (  # noqa: E402
    module_menu,
    seal_menu,
    todo_i18n,
    transform_menu,
    ui,
)
from script.todo.todo_i18n import t  # noqa: E402
from script.todo.ui.port import ScriptedPort  # noqa: E402

SEAL_DIR = "forged_yesno_seal"
# Défaut non : une réponse vide, une faute puis Ctrl+D, Ctrl+D refusent.
REFUS = ([""], ["n"], ["peut-être", EOFError()], [EOFError()])
OUI = (["o"], ["oui"], ["y"], ["YES"])
# Défaut oui : n, non, une faute puis Ctrl+D, Ctrl+D refusent.
REFUS_OUI = (["n"], ["non"], ["peut-être", EOFError()], [EOFError()])
OUI_OUI = ([""], *OUI)


class _Execute:
    """Note chaque commande, sans rien lancer."""

    def __init__(self):
        self.cmds = []

    def exec_command_live(self, cmd, **_opts):
        self.cmds.append(cmd)
        return 0


class _Base(unittest.TestCase):
    def setUp(self):
        saved = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", saved)
        todo_i18n.use_lang("fr")

    def play(self, call, answers, typed=()):
        """Ce que rend `call()` quand `answers` répondent, dans l'ordre, par
        un `ScriptedPort` (`self.port`) ; `typed` répond aux valeurs lues
        par `input`, qu'aucune autre question ne lit."""
        with (
            mock.patch(
                "builtins.input",
                side_effect=list(typed) if typed else AssertionError,
            ),
            mock.patch("builtins.print"),
            ui.bind(ScriptedPort(list(answers))) as self.port,
        ):
            return call()

    def asked(self):
        """(texte sans indice, défaut « y » ou « n ») de chaque question
        oui/non posée, une fois de plus après chaque faute."""
        return [
            (event["prompt"], event["default"])
            for event in self.port.events
            if event.get("kind") == "confirm"
        ]

    def notices(self):
        return [e["text"] for e in self.port.events if e.get("t") == "notice"]

    def check(self, make, prompt, default=False, pre=(), typed=()):
        """`make()` rend (`call`, `acted`), neufs pour chaque cas ; la
        question oui/non `prompt`, de défaut `default`, suit les réponses
        `pre` du port et les valeurs tapées `typed` : chaque refus laisse
        `acted()` faux, chaque oui le rend vrai, chaque réponse est lue ;
        une faute est dite, puis la question revient."""
        refus, oui = (REFUS_OUI, OUI_OUI) if default else (REFUS, OUI)
        cases = [(r, False) for r in refus] + [(o, True) for o in oui]
        for answers, expected in cases:
            with self.subTest(answers=answers):
                call, acted = make()
                self.play(call, [*pre, *answers], typed)
                fois = 2 if "peut-être" in answers else 1
                posee = (prompt, "y" if default else "n")
                self.assertEqual(self.asked()[-fois:], [posee] * fois)
                self.assertEqual(self.port.answers, [])
                self.assertIs(acted(), expected)
                if "peut-être" in answers:
                    self.assertIn(
                        f"{t('Answer yes or no: ')}peut-être", self.notices()
                    )


class TestTransformCopies(_Base):
    """Effacer les copies produites : un oui tapé, jamais un réflexe."""

    def test_the_copies_are_deleted_on_a_yes_only(self):
        def make():
            base = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, base, True)
            copie = os.path.join(base, "forged_yesno.anon.csv")
            with open(copie, "w", encoding="utf-8") as flux:
                flux.write("x")
            menu = transform_menu.TransformMenuMixin()

            def call():
                with mock.patch.object(
                    transform_menu, "SORTIE_PAR_DEFAUT", base
                ):
                    menu._transform_copies()

            return call, lambda: not os.path.exists(copie)

        self.check(make, t("Delete all copies in private/transform/?"))


class TestTransformApercu(_Base):
    def test_the_preview_writes_by_default(self):
        def make():
            got = []
            menu = transform_menu.TransformMenuMixin()

            def call():
                got.append(menu._transform_preview({"remplacees": 3}))

            return call, lambda: got[0]

        self.check(make, t("Write?"), default=True)


class TestTransformEcran(_Base):
    RAPPORT = {"feuilles": [{"nom": "F", "colonnes": []}]}

    def test_no_asks_the_prompts_and_ctrl_d_cancels(self):
        """« non » rend {}, les invites ; Ctrl+D, seul ou après une faute,
        rend None et abandonne le formulaire."""
        menu = transform_menu.TransformMenuMixin()
        for answers, wanted in (
            (["n"], {}),
            (["non"], {}),
            (["0", "n"], {}),
            ([EOFError()], None),
            (["peut-être", EOFError()], None),
        ):
            with self.subTest(answers=answers):
                rendu = self.play(
                    lambda: menu._transform_ecran(self.RAPPORT), answers
                )
                self.assertEqual(rendu, wanted)
                self.assertEqual(self.port.answers, [])
                self.assertEqual(
                    self.asked()[0], (t("Open the TUI for setup?"), "y")
                )
                confirm = [
                    e for e in self.port.events if e.get("kind") == "confirm"
                ]
                self.assertTrue(confirm[0]["back"])

    def test_yes_opens_the_screen(self):
        from script.todo import transform_form

        menu = transform_menu.TransformMenuMixin()
        for answers in OUI_OUI:
            with (
                self.subTest(answers=answers),
                mock.patch.object(
                    transform_form,
                    "run_transform_form",
                    return_value={"forged": True},
                ),
                mock.patch.object(
                    transform_form, "contexte_depuis_rapport", return_value={}
                ),
            ):
                rendu = self.play(
                    lambda: menu._transform_ecran(self.RAPPORT), answers
                )
                self.assertEqual(rendu, {"forged": True})


class TestTransformFormulaire(_Base):
    """Le formulaire d'anonymisation : chaque question oui/non, son
    défaut, et une sortie à chacune."""

    RAPPORT = {
        "format": "xlsx",
        "feuilles": [{"nom": "Ventes"}, {"nom": "Achats"}],
        "hors_cellules": {"macros": 1, "graphiques": 1},
    }
    # Le chemin avancé, dans l'ordre : (question, défaut, réponse).
    QUESTIONS = (
        ("Anonymise this file?", "n", "o"),
        ("Advanced options?", "n", "o"),
        ("Replace numbers?", "y", ""),
        ("Keep the digit count?", "n", ""),
        ("Replace text?", "y", ""),
        ("Anonymise the header row too?", "n", ""),
        ("Keep the VBA macros in the copy?", "n", ""),
        ("Keep the charts in the copy?", "n", ""),
    )
    # Convertir, table du lot, feuilles, colonnes intactes, graine.
    TAPEES = ["", "", "", "", ""]

    def form(self, answers, typed=()):
        menu = transform_menu.TransformMenuMixin()
        menu._transform_ecran = lambda *args: {}
        return self.play(
            lambda: menu._transform_ask_options(self.RAPPORT),
            answers,
            typed or self.TAPEES,
        )

    def test_each_question_states_its_default(self):
        options = self.form([q[2] for q in self.QUESTIONS])
        self.assertEqual(
            self.asked(), [(t(q[0]), q[1]) for q in self.QUESTIONS]
        )
        self.assertTrue(options["nombres"])
        self.assertTrue(options["texte"])
        for cle in (
            "calibre_chiffres",
            "entetes",
            "garder_macros",
            "garder_graphiques",
        ):
            self.assertFalse(options[cle], cle)

    def test_a_refusal_to_anonymise_asks_nothing_else(self):
        for answers in REFUS:
            with self.subTest(answers=answers):
                self.assertIsNone(self.form(answers))
                self.assertEqual(self.port.answers, [])
                self.assertEqual(
                    set(self.asked()), {(t("Anonymise this file?"), "n")}
                )

    def test_ctrl_d_cancels_at_each_later_question(self):
        """Après la première, Ctrl+D (ou l'Annuler de la page) abandonne
        le formulaire : aucune question ne suit, rien n'est rendu."""
        valides = [q[2] for q in self.QUESTIONS]
        for rang in range(1, len(valides)):
            for fin in ([EOFError()], ["peut-être", EOFError()]):
                with self.subTest(rang=rang, fin=fin):
                    self.assertIsNone(self.form([*valides[:rang], *fin]))
                    self.assertEqual(self.port.answers, [])
                    asked = self.asked()
                    self.assertEqual(
                        asked[-1],
                        (t(self.QUESTIONS[rang][0]), self.QUESTIONS[rang][1]),
                    )
                    self.assertEqual(len(asked), rang + len(fin))
                    confirm = [
                        e
                        for e in self.port.events
                        if e.get("kind") == "confirm"
                    ]
                    self.assertTrue(confirm[-1]["back"])

    def test_a_typo_is_named_and_asked_again(self):
        """Une faute valait non à « Remplacer les nombres ? » : elle est
        dite, et la question revient."""
        valides = [q[2] for q in self.QUESTIONS]
        options = self.form([*valides[:2], "0", "peut-être", *valides[2:]])
        self.assertTrue(options["nombres"])
        self.assertEqual(
            self.notices(),
            [
                f"{t('Answer yes or no: ')}0",
                f"{t('Answer yes or no: ')}peut-être",
            ],
        )

    def test_the_short_path_takes_the_defaults(self):
        options = self.form(["oui", "non", "", ""], ["", ""])
        for cle, valeur in transform_menu.DEFAUTS_RAPIDES.items():
            self.assertEqual(options[cle], valeur, cle)
        self.assertEqual(len(self.asked()), 4)


class TestLeSceau(_Base):
    def menu(self):
        return seal_menu.SealMenuMixin()

    def test_the_registry_loses_its_empty_folders_on_a_yes_only(self):
        def make():
            menu = self.menu()
            retirer = mock.Mock()

            def call():
                with (
                    mock.patch.object(
                        seal_menu, "sceaux_connus", return_value=[SEAL_DIR]
                    ),
                    mock.patch.object(
                        seal_menu, "retirer_du_registre", retirer
                    ),
                    mock.patch.object(
                        menu, "_seal_status_folder", return_value=False
                    ),
                    mock.patch.object(menu, "_seal_status_keys_in_git"),
                ):
                    menu.execute_seal_status()

            return call, lambda: retirer.called

        self.check(
            make,
            t("Remove the %s folders without a seal from the registry?") % 1,
        )

    def test_the_guide_points_outside_on_a_yes_only(self):
        question = t(
            "Are the sealed PDFs opened outside the organisation, in a"
            " reader nobody configures?"
        )

        def make():
            menu = self.menu()
            menu._seal_guide_external = mock.Mock()
            menu._seal_guide_internal = mock.Mock()
            return (
                menu.execute_seal_guide,
                lambda: (
                    menu._seal_guide_external.called
                    and not menu._seal_guide_internal.called
                ),
            )

        self.check(make, question)

    def test_an_existing_seal_is_replaced_on_a_yes_only(self):
        def make():
            racine = tempfile.mkdtemp()
            self.addCleanup(shutil.rmtree, racine, True)
            dossier = os.path.join(racine, SEAL_DIR)
            os.makedirs(dossier)
            with open(os.path.join(dossier, seal_menu.NOM_P12), "w") as f:
                f.write("forged")
            got = []
            menu = self.menu()

            def call():
                with (
                    mock.patch.object(seal_menu, "RACINE", racine),
                    mock.patch.object(
                        seal_menu, "chemin_commitable", return_value=False
                    ),
                ):
                    got.append(menu._seal_ask_folder())

            return call, lambda: got[0] == dossier

        self.check(make, t("Replace it?"), typed=[SEAL_DIR])


class TestAnalyseModule(_Base):
    def test_the_statistic_runs_on_a_yes_only(self):
        def make():
            menu = module_menu.ModuleMenuMixin()
            menu.execute = _Execute()
            return menu._module_statistique, lambda: bool(menu.execute.cmds)

        self.check(make, t("Continue?"))

    def auto_install(self, answers):
        """Le double de `traiter` après `answers`, le choix des dépôts
        compris."""
        menu = module_menu.ModuleMenuMixin()
        depots = ["odoo18.0/addons/OCA_a", "odoo18.0/addons/OCA_b"]
        with (
            mock.patch.object(
                module_menu.repo_upgrade, "version_active", return_value="18.0"
            ),
            mock.patch.object(
                module_menu, "depots_d_addons", return_value=depots
            ),
            mock.patch.object(
                module_menu.repo_remove_auto_install,
                "traiter",
                return_value=[],
            ) as traiter,
        ):
            self.play(menu._module_auto_install, answers)
        return traiter

    def test_commit_and_push_wait_for_a_yes_each(self):
        commit = (
            t(
                "Commit the changed manifests in each repository (current"
                " branch)?"
            ),
            "n",
        )
        push = (t("Push each commit to its tracked branch?"), "n")
        for answers, wanted, questions in (
            *[(["1", *r], (False, False), [commit] * len(r)) for r in REFUS],
            (["1", "o", ""], (True, False), [commit, push]),
            (["1", "oui", EOFError()], (True, False), [commit, push]),
            (["1", "y", "non"], (True, False), [commit, push]),
            (["1", "YES", "o"], (True, True), [commit, push]),
        ):
            with self.subTest(answers=answers):
                traiter = self.auto_install(answers)
                self.assertEqual(
                    traiter.call_args.kwargs,
                    {"commit": wanted[0], "push": wanted[1]},
                )
                self.assertEqual(self.port.answers, [])
                self.assertEqual(self.asked(), questions)

    def test_the_repositories_outside_the_manifest_are_included_by_default(
        self,
    ):
        def make():
            menu = module_menu.ModuleMenuMixin()
            analyser = mock.Mock(return_value={})

            def call():
                with (
                    mock.patch.object(
                        module_menu.repo_upgrade,
                        "version_active",
                        return_value="18.0",
                    ),
                    mock.patch.object(
                        menu,
                        "_module_analysis_choisir",
                        return_value=("a", "b"),
                    ),
                    mock.patch.object(
                        git_module_diff, "depots_du_choix", return_value=[]
                    ),
                    mock.patch.object(
                        git_module_diff,
                        "depots_addons_addons",
                        return_value=["forged_yesno_repo"],
                    ),
                    mock.patch.object(
                        git_module_diff,
                        "dossier_addons_addons",
                        return_value=module_menu.RACINE,
                    ),
                    mock.patch.object(
                        git_module_diff,
                        "depot_hors_manifeste",
                        side_effect=lambda racine, d: d,
                    ),
                    mock.patch.object(git_module_diff, "analyser", analyser),
                    mock.patch.object(module_menu, "rendre", return_value=[]),
                ):
                    menu._module_analysis_diff(git_module_diff.MODE_BRANCHE)

            return (
                call,
                lambda: analyser.call_args.args[2] == ["forged_yesno_repo"],
            )

        self.check(make, t("Include them?"), default=True)


if __name__ == "__main__":
    unittest.main()
