#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que l'interface dit de la revendication des messages : la ligne du
mode du serveur (menu [6] › [1], menu du service), les lignes de l'essai,
les réponses retenues par le service, et la sortie du service.

`HOME` est un dossier temporaire : les états du moteur et du service s'y
écrivent, jamais sous le vrai dossier personnel.
"""

import contextlib
import io
import json
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Argon2 remplacé pour tout le module : voir argon2_rapide.py.
from argon2_rapide import setUpModule  # noqa: E402,F401
from test_mail_rules_menu import FauxTodo, RulesMenuCase  # noqa: E402
from test_mail_service_run import SECRET_IMAP, ServiceCase  # noqa: E402

from script.todo.mail import menu  # noqa: E402
from script.todo.mail.accounts import account_from_preset  # noqa: E402
from script.todo.mail.rules import engine, run, storage  # noqa: E402
from script.todo.mail.store import default_base  # noqa: E402
from script.todo.mail.tui import rule_trial_lines  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"

CLAIM_WARNINGS = (
    "mail_rules_claim_uncertain_warning",
    "mail_rules_send_uncertain_warning",
    "mail_rules_claim_none_warning",
    "mail_rules_claim_failed_final",
)


def simulation(**champs):
    valeurs = dict(
        rule_enabled=True,
        executable=True,
        filter_lines=[],
        matched=True,
        reason="send",
        reason_if_new="send",
        target=CAROLE,
        subject="",
        rendered=None,
        error="",
        headers_complete=True,
        auth_serv_id="",
        authenticated=None,
    )
    valeurs.update(champs)
    return engine.Simulation(**valeurs)


class TestClaimTexts(RulesMenuCase):
    def test_claim_mode_text_covers_every_mode_and_the_unknown(self):
        for mode in ("atomic", "plain", "none"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    engine.claim_mode_text(mode), t(f"mail_rules_claim_{mode}")
                )
        for inconnu in ("", "quantique", None):
            self.assertEqual(
                engine.claim_mode_text(inconnu), t("mail_rules_claim_unknown")
            )

    def test_trial_lines_say_claimed_elsewhere_uncertain_or_here(self):
        attendus = {
            "elsewhere": ("mail_rules_trial_claimed_elsewhere", "yellow"),
            "uncertain": ("mail_rules_trial_claim_uncertain", "yellow"),
            "here": ("mail_rules_trial_claimed_here", "dim"),
        }
        for etat, (cle, style) in attendus.items():
            with self.subTest(etat=etat):
                lignes = rule_trial_lines(simulation(claim=etat))
                self.assertIn((t(cle), style), lignes)
        textes = [texte for texte, _ in rule_trial_lines(simulation())]
        for cle, _style in attendus.values():
            self.assertNotIn(t(cle), textes)

    def test_trial_lines_of_an_old_simulation_without_claim_still_render(
        self,
    ):
        ancienne = SimpleNamespace(
            **{k: v for k, v in vars(simulation()).items() if k != "claim"}
        )
        self.assertFalse(hasattr(ancienne, "claim"))
        lignes = rule_trial_lines(ancienne)
        self.assertIn((f"{t('mail_rules_trial_target')} {CAROLE}", ""), lignes)

    def test_the_rules_list_entry_prints_the_claim_mode(self):
        self.regles("Absence")
        storage.save_state(
            "perso",
            storage.EngineState(claim_mode="plain"),
            base=self.base,
        )
        sortie = self.lancer("1", "0")
        self.assertIn(t("mail_rules_claim_plain"), sortie)
        sortie = self.lancer("9", "0")
        self.assertNotIn(t("mail_rules_claim_plain"), sortie)


class TestServiceMenuClaim(RulesMenuCase):
    def mode(self, nom, mode):
        storage.save_state(
            nom, storage.EngineState(claim_mode=mode), base=default_base()
        )

    def test_the_service_menu_lists_accounts_with_a_plain_or_none_claim(self):
        comptes = [
            account_from_preset(nom, OWN, "generic")
            for nom in ("simple", "aucune", "atomique", "inconnu")
        ]
        self.mode("simple", "plain")
        self.mode("aucune", "none")
        self.mode("atomique", "atomic")
        self.assertEqual(
            menu._claim_lines(comptes),
            [
                f"  simple : {t('mail_rules_claim_plain')}",
                f"  aucune : {t('mail_rules_claim_none')}",
            ],
        )

    def test_the_service_menu_shows_replies_held_by_the_service(self):
        base = default_base()
        base.mkdir(parents=True)
        (base / run.STATE_NAME).write_text(
            json.dumps(
                {"perso": {"held": 2, "fail": ""}, "autre": {"held": 0}}
            )
        )
        self.assertEqual(
            menu._held_lines(base),
            [f"  perso : {t('mail_service_menu_held')} 2"],
        )
        (base / run.STATE_NAME).write_text(json.dumps({"perso": {"held": 0}}))
        self.assertEqual(menu._held_lines(base), [])

    def test_the_service_menu_prints_the_claim_and_held_lines(self):
        from script.todo.mail import service

        self.mode("perso", "plain")
        base = default_base()
        (base / run.STATE_NAME).write_text(json.dumps({"perso": {"held": 3}}))
        sortie = io.StringIO()
        with (
            mock.patch.object(service, "status", return_value=None),
            mock.patch.object(service, "status_text", return_value="ÉTAT"),
            mock.patch.object(menu.click, "prompt", side_effect=["0"]),
            contextlib.redirect_stdout(sortie),
        ):
            menu._service_menu(FauxTodo())
        lignes = sortie.getvalue().splitlines()
        self.assertEqual(lignes[0], "ÉTAT")
        self.assertIn(f"  perso : {t('mail_rules_claim_plain')}", lignes)
        self.assertIn(f"  perso : {t('mail_service_menu_held')} 3", lignes)


class TestServiceOutput(ServiceCase):
    def test_the_service_output_carries_the_fixed_claim_warnings(self):
        textes = [t(cle) for cle in CLAIM_WARNINGS]
        bilan = engine.EngineReport(
            account="perso", active_rules=1, warnings=list(textes)
        )
        self.assertEqual(run._journal_safe(bilan, "perso").warnings, textes)

    def test_a_repeated_claim_failure_is_written_once_in_quiet_mode(self):
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})

        def passe(session, **kwargs):
            return engine.EngineReport(
                account=session.account.name,
                active_rules=1,
                warnings=[t("mail_rules_claim_failed")],
            )

        with mock.patch.object(engine, "run_pass", side_effect=passe):
            code, sortie = self.lancer("--quiet")
        self.assertEqual(code, run.EXIT_NETWORK)
        self.assertIn(t("mail_service_claim_failed"), sortie)
        self.assertNotIn(t("mail_rules_claim_failed"), sortie)
        with mock.patch.object(engine, "run_pass", side_effect=passe):
            code, sortie = self.lancer("--quiet")
        self.assertEqual(code, run.EXIT_NETWORK)
        self.assertEqual(sortie, "")


if __name__ == "__main__":
    unittest.main()
