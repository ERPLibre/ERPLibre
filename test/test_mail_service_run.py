#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La commande sans interface des règles, sur des doubles.

`HOME` et `XDG_CONFIG_HOME` pointent vers des dossiers temporaires : la
base `~/.erplibre/mail`, les comptes, les règles, l'état et le journal y
vivent. La configuration est un dict, le coffre un kdbx temporaire, le
mot de passe maître un fichier dans un `CREDENTIALS_DIRECTORY` temporaire.
`subprocess.run` est remplacé par une assertion : la commande n'appelle
aucun programme système.
"""

import contextlib
import io
import logging
import os
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
# Argon2 remplacé pour tout le module : voir argon2_rapide.py.
from argon2_rapide import setUpModule  # noqa: E402,F401
from test_mail_sync import FakeImapTransport  # noqa: E402

from script.todo.mail import accounts as mail_accounts  # noqa: E402
from script.todo.mail import credential, menu  # noqa: E402
from script.todo.mail import secrets as mail_secrets  # noqa: E402
from script.todo.mail.accounts import account_from_preset  # noqa: E402
from script.todo.mail.imap_sync import FolderInfo  # noqa: E402
from script.todo.mail.imap_transport import ImapAuthError  # noqa: E402
from script.todo.mail.rules import engine, run, storage  # noqa: E402
from script.todo.mail.rules.lock import file_lock  # noqa: E402
from script.todo.mail.rules.model import (  # noqa: E402
    Condition,
    Group,
    RuleError,
    new_rule,
)
from script.todo.mail.secrets import SecretStore  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
OWN = "boite.regles@example.org"
CAROLE = "carole.regle@example.org"
MAITRE = "maitre-essai"
SECRET_IMAP = "PASSWORD"


class FakeConfig(dict):
    """La configuration réduite à un dict ; une clé absente rend None."""

    def get_config_value(self, keys):
        valeur = self
        for cle in keys:
            valeur = valeur.get(cle) if isinstance(valeur, dict) else None
        return valeur


class Transport(FakeImapTransport):
    """Un serveur sans SPECIAL-USE : aucun dossier n'annonce de rôle."""

    def list_folders(self):
        return [FolderInfo(name=n) for n in sorted(self.folders)]


class ServiceCase(unittest.TestCase):
    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.home = Path(home.name)
        rustine = mock.patch.dict(
            os.environ,
            {
                "HOME": str(self.home),
                "XDG_CONFIG_HOME": str(self.home / ".config"),
            },
        )
        rustine.start()
        self.addCleanup(rustine.stop)
        self.addCleanup(os.chdir, os.getcwd())
        # Filets : un programme système lancé, ou la configuration réelle
        # du dépôt lue (elle désigne le vrai coffre), fait échouer le test.
        for cible, message in (
            ("subprocess.run", "programme système appelé"),
            ("script.todo.mail.rules.run.ConfigFile", "configuration lue"),
        ):
            filet = mock.patch(cible, side_effect=AssertionError(message))
            filet.start()
            self.addCleanup(filet.stop)
        # Les journaux du paquet restent hors de la sortie des tests.
        paquet = logging.getLogger("script.todo.mail")
        self.addCleanup(setattr, paquet, "propagate", paquet.propagate)
        paquet.propagate = False
        self.base = self.home / ".erplibre" / "mail"
        self.kdbx = self.home / "coffre.kdbx"
        self.creds = self.home / "creds"
        self.creds.mkdir()
        self.env = {"CREDENTIALS_DIRECTORY": str(self.creds)}
        self.connexions = []

    # -- mise en place -------------------------------------------------

    def comptes(self, *comptes):
        mail_accounts.save(list(comptes))

    def compte(self, nom, adresse=OWN, **champs):
        account = account_from_preset(nom, adresse, "generic")
        account.cache_mode = "clear"
        account.sent_folder = "INBOX.Sent"
        for cle, valeur in champs.items():
            setattr(account, cle, valeur)
        return account

    def regle(self, nom, enabled=True):
        rule = new_rule("reply", "Absence")
        rule.enabled = enabled
        rule.action.body = "Je suis absente."
        rule.filter = Group("all", [Condition("body", "bonjour")])
        storage.upsert_rule(nom, rule, base=self.base)
        return rule

    def coffre(self, secrets=None, maitre=MAITRE):
        from pykeepass import create_database

        kp = create_database(str(self.kdbx), password=MAITRE)
        magasin = SecretStore(
            kdbx_manager=SimpleNamespace(get_kdbx=lambda: kp),
            use_keyring=False,
        )
        for ref, valeur in (secrets or {}).items():
            magasin.set(ref, valeur)
        (self.creds / credential.CREDENTIAL_ID).write_text(maitre)

    def connect(self, transport=None):
        def ouvrir(account, secret):
            self.connexions.append(account.name)
            if transport is not None:
                return transport
            imap = Transport()
            imap.folders["INBOX"] = {
                "uidvalidity": 1,
                "messages": {},
                "bodies": {},
            }
            return imap

        return ouvrir

    def deps(self, **champs):
        valeurs = dict(
            config_file=FakeConfig({"kdbx": {"path": str(self.kdbx)}}),
            env=self.env,
            out=io.StringIO(),
            configure_logging=False,
            use_keyring=False,
            limit_core=lambda: None,
            connect_fn=self.connect(),
            lock_wait=0.2,
        )
        valeurs.update(champs)
        return run.ServiceDeps(**valeurs)

    def lancer(self, *argv, **champs):
        deps = self.deps(**champs)
        code = run.main(list(argv), deps=deps)
        return code, deps.out.getvalue()


class TestNothingToDo(ServiceCase):
    def test_no_account_exits_zero_without_touching_the_vault(self):
        config = mock.MagicMock()
        config.get_config_value.side_effect = AssertionError("coffre lu")
        code, sortie = self.lancer(config_file=config)
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(sortie, t("mail_service_no_account") + "\n")

    def test_no_active_rule_exits_zero_without_network_or_vault(self):
        self.comptes(self.compte("perso"))
        self.regle("perso", enabled=False)
        absent = self.home / "absent.kdbx"
        code, sortie = self.lancer(
            config_file=FakeConfig({"kdbx": {"path": str(absent)}}),
            connect_fn=mock.Mock(side_effect=AssertionError("réseau")),
        )
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(sortie, t("mail_service_no_active_rules") + "\n")

    def test_quiet_run_with_nothing_to_do_prints_nothing(self):
        self.assertEqual(self.lancer("--quiet"), (run.EXIT_OK, ""))
        self.comptes(self.compte("perso"))
        self.assertEqual(self.lancer("--quiet"), (run.EXIT_OK, ""))

    def test_a_disabled_account_is_skipped_and_named_only_without_quiet(self):
        self.comptes(self.compte("perso", enabled=False))
        self.regle("perso")
        ligne = f"perso : {t('mail_service_account_disabled')}"
        code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_OK)
        self.assertIn(ligne, sortie)
        self.assertEqual(self.lancer("--quiet"), (run.EXIT_OK, ""))
        code, sortie = self.lancer("--quiet", "--compte", "perso")
        self.assertEqual(sortie, ligne + "\n")
        self.assertEqual(self.connexions, [])

    def test_an_ephemeral_account_is_skipped_with_a_line_even_when_quiet(self):
        self.comptes(self.compte("perso", cache_mode="ephemeral"))
        self.regle("perso")
        code, sortie = self.lancer("--quiet")
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(
            sortie, f"perso : {t('mail_service_account_ephemeral')}\n"
        )
        self.assertEqual(self.connexions, [])

    def test_unreadable_rules_exit_with_the_rule_code_without_network(self):
        self.comptes(self.compte("perso"))
        storage.rules_path("perso", self.base).write_text("{ pas du json")
        code, sortie = self.lancer(
            connect_fn=mock.Mock(side_effect=AssertionError("réseau"))
        )
        self.assertEqual(code, run.EXIT_RULE)
        self.assertIn(f"perso : {t('mail_service_rules_unreadable')}", sortie)


class TestArguments(ServiceCase):
    def test_an_unknown_account_name_exits_with_the_usage_code(self):
        self.comptes(self.compte("perso"))
        code, sortie = self.lancer("--compte", "inconnu")
        self.assertEqual(code, run.EXIT_USAGE)
        self.assertIn(t("mail_service_unknown_account"), sortie)
        with contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(self.lancer("--inconnu")[0], run.EXIT_USAGE)

    def test_a_named_account_restricts_the_pass_to_it(self):
        self.comptes(
            self.compte("perso"),
            self.compte("boite-regles", adresse="denis.tri@example.org"),
        )
        self.regle("perso")
        self.regle("boite-regles")
        self.coffre(
            {
                "kdbx:ERPLibre/Mail/perso": SECRET_IMAP,
                "kdbx:ERPLibre/Mail/boite-regles": SECRET_IMAP,
            }
        )
        code, _ = self.lancer("--account", "boite-regles")
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(self.connexions, ["boite-regles"])
        self.connexions.clear()
        self.lancer()
        self.assertEqual(self.connexions, ["perso", "boite-regles"])

    def test_a_named_account_still_knows_the_other_accounts(self):
        self.comptes(
            self.compte("perso"),
            self.compte(
                "boite-regles", adresse="denis.tri@example.org", enabled=False
            ),
        )
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})
        vus = []

        def passe(session, **kwargs):
            vus.append([a.name for a in kwargs["all_accounts"]])
            return engine.EngineReport(account=session.account.name)

        with mock.patch.object(engine, "run_pass", side_effect=passe):
            code, _ = self.lancer("--compte", "perso")
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(vus, [["perso", "boite-regles"]])

    def test_unreadable_accounts_file_exits_with_the_config_code(self):
        chemin = mail_accounts.accounts_path()
        chemin.parent.mkdir(parents=True)
        chemin.write_text("{ illisible")
        code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_CONFIG)
        self.assertTrue(
            sortie.startswith(t("mail_service_accounts_unreadable"))
        )
        self.assertNotIn(str(self.home), sortie)

    def test_help_exits_zero(self):
        with contextlib.redirect_stdout(io.StringIO()) as aide:
            self.assertEqual(run.main(["--help"], deps=self.deps()), 0)
        self.assertIn("--compte", aide.getvalue())
        self.assertIn("--quiet", aide.getvalue())

    def test_help_names_the_account_argument_in_the_interface_language(self):
        from script.todo import todo_i18n

        ancienne = todo_i18n._current_lang
        self.addCleanup(setattr, todo_i18n, "_current_lang", ancienne)
        for langue, nom in (("en", "NAME"), ("fr", "NOM")):
            todo_i18n._current_lang = langue
            with self.subTest(langue=langue):
                with contextlib.redirect_stdout(io.StringIO()) as aide:
                    run.main(["--help"], deps=self.deps())
                self.assertIn(f"--compte {nom}", aide.getvalue())


class TestLocksAndVault(ServiceCase):
    def test_a_held_service_lock_exits_busy_at_once(self):
        self.base.mkdir(parents=True)
        with file_lock(self.base / run.SERVICE_LOCK_NAME, wait=0) as tenu:
            self.assertTrue(tenu)
            debut = time.monotonic()
            code, sortie = self.lancer()
            duree = time.monotonic() - debut
        self.assertEqual(code, run.EXIT_BUSY)
        self.assertEqual(sortie, t("mail_service_already_running") + "\n")
        self.assertLess(duree, 1.0)

    def test_a_locked_vault_gives_one_line_and_stops(self):
        self.comptes(
            self.compte("perso"),
            self.compte("boite-regles", adresse="denis.tri@example.org"),
        )
        self.regle("perso")
        self.regle("boite-regles")
        connect = mock.Mock(side_effect=AssertionError("réseau"))
        code, sortie = self.lancer(env={}, connect_fn=connect)
        self.assertEqual(code, run.EXIT_VAULT)
        self.assertEqual(len(sortie.splitlines()), 1)
        self.assertTrue(sortie.startswith(t("mail_service_vault_locked")))
        connect.assert_not_called()

    def test_the_vault_reason_is_named(self):
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})
        vide = self.home / "creds-vide"
        vide.mkdir()
        cas = (
            ("no_password", {"CREDENTIALS_DIRECTORY": str(vide)}, None),
            ("wrong_password", None, "faux"),
            ("not_configured", None, None),
        )
        for raison, env, maitre in cas:
            with self.subTest(raison):
                deps = {}
                if env is not None:
                    deps["env"] = env
                if maitre is not None:
                    (self.creds / credential.CREDENTIAL_ID).write_text(maitre)
                if raison == "not_configured":
                    deps["config_file"] = FakeConfig()
                code, sortie = self.lancer(**deps)
                self.assertEqual(code, run.EXIT_VAULT)
                self.assertEqual(
                    sortie,
                    f"{t('mail_service_vault_locked')}"
                    f" {t('mail_service_vault_' + raison)}\n",
                )
                self.assertEqual(self.connexions, [])
                (self.creds / credential.CREDENTIAL_ID).write_text(MAITRE)

    def test_a_pass_by_hand_says_the_credential_is_not_read(self):
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})
        code, sortie = self.lancer(env={})
        self.assertEqual(code, run.EXIT_VAULT)
        self.assertEqual(
            sortie,
            f"{t('mail_service_vault_locked')}"
            f" {t('mail_service_vault_no_password_by_hand')}\n",
        )
        self.assertNotIn("[7] › [2]", sortie)
        # Hors du service, `kdbx.password` ouvre le coffre comme avant.
        config = FakeConfig(
            {"kdbx": {"path": str(self.kdbx), "password": MAITRE}}
        )
        code, sortie = self.lancer(env={}, config_file=config)
        self.assertNotIn(t("mail_service_vault_locked"), sortie)

    def test_a_refused_config_password_does_not_send_to_the_credential(self):
        """Sans credential lu, le mot de passe refusé vient de
        `kdbx.password` : le message le nomme et ne renvoie pas à
        [8] › [2], par la main comme dans l'unité sans credential."""
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})
        config = FakeConfig(
            {"kdbx": {"path": str(self.kdbx), "password": "perime"}}
        )
        vide = self.home / "creds-vide"
        vide.mkdir()
        for env in ({}, {"CREDENTIALS_DIRECTORY": str(vide)}):
            with self.subTest(env=bool(env)):
                code, sortie = self.lancer(env=env, config_file=config)
                self.assertEqual(code, run.EXIT_VAULT)
                self.assertEqual(
                    sortie,
                    f"{t('mail_service_vault_locked')}"
                    f" {t('mail_service_vault_wrong_password_config')}\n",
                )
                self.assertNotIn("[7] › [2]", sortie)
                self.assertEqual(self.connexions, [])

    def test_main_drops_core_dumps(self):
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})
        ordre = []
        config = FakeConfig({"kdbx": {"path": str(self.kdbx)}})
        lire = config.get_config_value
        config.get_config_value = lambda keys: (
            ordre.append("coffre") or lire(keys)
        )
        code, _ = self.lancer(
            config_file=config, limit_core=lambda: ordre.append("core")
        )
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(ordre.count("core"), 1)
        self.assertEqual(ordre[0], "core")
        self.assertIn("coffre", ordre)


class TestHelpers(unittest.TestCase):
    def test_the_worst_exit_follows_the_priority(self):
        self.assertEqual(run.worst_exit([]), run.EXIT_OK)
        self.assertEqual(run.worst_exit([0, 0]), run.EXIT_OK)
        self.assertEqual(run.worst_exit([6, 4]), run.EXIT_NETWORK)
        self.assertEqual(run.worst_exit([4, 5]), run.EXIT_RULE)
        self.assertEqual(run.worst_exit([5, 7]), run.EXIT_AUTH)
        self.assertEqual(run.worst_exit([7, 3]), run.EXIT_VAULT)
        self.assertEqual(run.worst_exit([3, 8]), run.EXIT_CONFIG)
        self.assertEqual(run.worst_exit([8, 1, 6]), run.EXIT_FAILURE)
        self.assertEqual(run.worst_exit([6, 0]), run.EXIT_BUSY)

    def test_redact_masks_addresses_and_control_characters(self):
        ligne = run.redact(
            f"perso : refus pour {OWN} et <{CAROLE}>\x1b[2J\tfin"
        )
        self.assertNotIn("@", ligne)
        self.assertNotIn("\x1b", ligne)
        self.assertIn(run.ADDRESS_MASK, ligne)
        self.assertIn("perso : refus pour", ligne)
        longue = run.redact("x" * 1000)
        self.assertEqual(len(longue), run.LINE_MAX)
        self.assertTrue(longue.endswith("…"))

    def test_the_state_round_trips_and_an_unreadable_one_is_empty(self):
        with tempfile.TemporaryDirectory() as dossier:
            self.assertEqual(run.load_state(dossier), {})
            run.save_state(dossier, {"perso": {"held": 1, "fail": ""}})
            self.assertEqual(
                run.load_state(dossier), {"perso": {"held": 1, "fail": ""}}
            )
            (Path(dossier) / run.STATE_NAME).write_text("[1, 2]")
            self.assertEqual(run.load_state(dossier), {})
            (Path(dossier) / run.STATE_NAME).write_text("{ illisible")
            self.assertEqual(run.load_state(dossier), {})

    def test_the_service_folders_are_the_inbox_and_sent(self):
        compte = SimpleNamespace(sent_folder="INBOX.Sent")
        retenu = run.service_folder_for(compte)
        self.assertTrue(retenu(FolderInfo(name="INBOX")))
        self.assertTrue(retenu(FolderInfo(name="inbox")))
        self.assertTrue(retenu(FolderInfo(name="INBOX.Sent")))
        self.assertTrue(retenu(FolderInfo(name="Envoyés", role="sent")))
        self.assertFalse(retenu(FolderInfo(name="Archive")))
        self.assertFalse(retenu(FolderInfo(name="Sent")))
        sans = run.service_folder_for(SimpleNamespace(sent_folder=""))
        self.assertFalse(sans(FolderInfo(name="")))

    def test_kdbx_refs_include_the_cache_key_of_an_encrypted_cache(self):
        compte = account_from_preset("perso", OWN, "generic")
        compte.cache_mode = "clear"
        self.assertEqual(run.kdbx_refs(compte), ["kdbx:ERPLibre/Mail/perso"])
        compte.cache_mode = "encrypted"
        self.assertEqual(
            run.kdbx_refs(compte),
            ["kdbx:ERPLibre/Mail/perso", "kdbx:ERPLibre/Mail/perso/cache-key"],
        )
        anneau = account_from_preset("perso", OWN, "generic", vault="keyring")
        anneau.cache_mode = "clear"
        self.assertEqual(run.kdbx_refs(anneau), [])


class TestPass(ServiceCase):
    def setUp(self):
        super().setUp()
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})

    def test_the_preset_sent_folder_is_synced_without_special_use(self):
        imap = Transport()
        imap.add("INBOX", 1)
        imap.add("INBOX.Sent", 1)
        imap.add("Archive", 1)
        choisis = []
        select = imap.select
        imap.select = lambda dossier: (
            choisis.append(dossier) or select(dossier)
        )
        code, sortie = self.lancer(connect_fn=self.connect(imap))
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(sorted(set(choisis)), ["INBOX", "INBOX.Sent"])
        self.assertIn(f"perso : 2 {t('mail_new_messages')}", sortie)
        from script.todo.mail.store import Store

        store = Store(self.compte("perso"), mode="clear", base=self.base)
        store.open()
        self.addCleanup(store.close)
        self.assertEqual(
            {f["name"] for f in store.folders()}, {"INBOX", "INBOX.Sent"}
        )

    def test_a_rule_error_text_never_reaches_the_output(self):
        motif = "zorglub-motif"
        with mock.patch.object(
            storage, "load", side_effect=RuleError(f"motif {motif} refusé")
        ):
            code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_RULE)
        self.assertNotIn(motif, sortie)
        bilan = engine.EngineReport(
            account="perso", status="error", active_rules=1, errors=[motif]
        )
        with mock.patch.object(engine, "run_pass", return_value=bilan):
            code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_RULE)
        self.assertIn(t("mail_service_rule_error"), sortie)
        self.assertNotIn(t("mail_rules_error"), sortie)
        self.assertNotIn(motif, sortie)
        with journalisation():
            with mock.patch.object(engine, "run_pass", return_value=bilan):
                code, sortie = self.lancer(configure_logging=True)
        self.assertNotIn(motif, sortie)
        journal = (self.home / ".erplibre" / "mail.log").read_text()
        self.assertIn(motif, journal)

    def test_a_server_error_shows_its_class_and_response_code_only(self):
        refus = ImapAuthError(f"[AUTHENTICATIONFAILED] refus pour {OWN}")
        code, sortie = self.lancer(connect_fn=mock.Mock(side_effect=refus))
        self.assertEqual(code, run.EXIT_AUTH)
        self.assertEqual(
            sortie,
            f"perso : {t('mail_service_kind_auth')}"
            " ImapAuthError [AUTHENTICATIONFAILED]\n",
        )
        self.assertNotIn("@", sortie)
        self.assertNotIn("refus pour", sortie)

    def test_two_identical_offline_quiet_passes_print_one_line(self):
        hors = mock.Mock(side_effect=ConnectionRefusedError(111, "refusé"))
        premier = self.lancer("--quiet", connect_fn=hors)
        second = self.lancer("--quiet", connect_fn=hors)
        self.assertEqual(premier[0], run.EXIT_NETWORK)
        self.assertEqual(second[0], run.EXIT_NETWORK)
        self.assertEqual(
            premier[1],
            f"perso : {t('mail_service_kind_network')}"
            " ConnectionRefusedError\n",
        )
        self.assertEqual(second[1], "")
        # Sans `--quiet`, la panne s'écrit à chaque passe.
        self.assertEqual(len(self.lancer(connect_fn=hors)[1].splitlines()), 1)

    def test_a_held_send_is_printed_once_while_its_count_holds(self):
        muet = engine.EngineReport(account="perso", active_rules=1)
        sorties = []
        with mock.patch.object(engine, "run_pass", return_value=muet):
            for nombre in (1, 1, 2):
                with mock.patch(
                    "script.todo.mail.tui.held_auto_counts",
                    return_value=[("perso", nombre)],
                ):
                    sorties.append(self.lancer("--quiet"))
        self.assertEqual([code for code, _ in sorties], [0, 0, 0])
        self.assertIn("(o)", sorties[0][1])
        self.assertEqual(sorties[1][1], "")
        self.assertIn("(o)", sorties[2][1])
        self.assertEqual(len(sorties[2][1].splitlines()), 1)

    def test_a_held_account_lock_is_busy_and_repeats_silently(self):
        with file_lock(storage.lock_path("perso", self.base), wait=0) as tenu:
            self.assertTrue(tenu)
            premier = self.lancer("--quiet")
            second = self.lancer("--quiet")
        self.assertEqual((premier[0], second[0]), (6, 6))
        self.assertIn(t("mail_service_busy"), premier[1])
        self.assertNotIn(t("mail_rules_locked"), premier[1])
        self.assertEqual(second[1], "")

    def test_the_state_file_is_private(self):
        code, _ = self.lancer()
        self.assertEqual(code, run.EXIT_OK)
        mode = stat.S_IMODE(os.stat(self.base / run.STATE_NAME).st_mode)
        self.assertEqual(mode, 0o600)
        self.assertEqual(run.load_state(self.base)["perso"]["fail"], "")

    def test_a_missing_secret_stops_only_its_account(self):
        self.comptes(
            self.compte("perso"),
            self.compte("boite-regles", adresse="denis.tri@example.org"),
        )
        self.regle("boite-regles")
        code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_VAULT)
        self.assertIn(
            f"boite-regles : {t('mail_service_kind_vault')} MissingSecret",
            sortie,
        )
        self.assertEqual(self.connexions, ["perso"])

    def test_the_root_logger_stays_at_warning_after_config_file(self):
        self.assertIn("script.config.config_file", sys.modules)
        racine = logging.getLogger()
        avant = racine.level
        self.addCleanup(racine.setLevel, avant)
        racine.setLevel(logging.INFO)
        with journalisation():
            code, _ = self.lancer(configure_logging=True)
            self.assertEqual(racine.level, logging.WARNING)
        self.assertEqual(code, run.EXIT_OK)
        self.assertTrue((self.home / ".erplibre" / "mail.log").is_file())

    def test_an_unexpected_exception_exits_one_with_the_type_name_only(self):
        panne = RuntimeError(f"secret pour {OWN}")
        with (
            mock.patch.object(mail_accounts, "load", side_effect=panne),
            self.assertLogs("script.todo.mail.rules.run", "ERROR") as vus,
        ):
            code, sortie = self.lancer()
        self.assertIn("RuntimeError", "\n".join(vus.output))
        self.assertEqual(code, run.EXIT_FAILURE)
        self.assertEqual(
            sortie, f"{t('mail_service_unexpected')} RuntimeError\n"
        )


@contextlib.contextmanager
def journalisation():
    """Laisse `main` brancher `mail.log` dans le `HOME` temporaire, puis
    retire le gestionnaire et rend au logger du paquet son état."""
    paquet = logging.getLogger("script.todo.mail")
    racine = logging.getLogger()
    etat = (
        list(paquet.handlers),
        paquet.level,
        paquet.propagate,
        racine.level,
        menu._LOG_CONFIGURED,
    )
    menu._LOG_CONFIGURED = False
    try:
        yield
    finally:
        for handler in paquet.handlers:
            if handler not in etat[0]:
                paquet.removeHandler(handler)
                handler.close()
        paquet.setLevel(etat[1])
        paquet.propagate = etat[2]
        racine.setLevel(etat[3])
        menu._LOG_CONFIGURED = etat[4]


class TestRuleWarnings(ServiceCase):
    def test_a_rule_warning_text_goes_to_the_log_not_the_journal(self):
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})
        libre = f"{t('mail_rules_err_image_missing')} vacances-inventees.png"
        rapport = f"{t('mail_stats_report_invalid')} valeur-inventee"

        def passe(session, **kwargs):
            return engine.EngineReport(
                account=session.account.name,
                active_rules=1,
                failed=1,
                warnings=[libre, t("mail_rules_cap_warning"), rapport],
            )

        with (
            mock.patch.object(engine, "run_pass", side_effect=passe),
            self.assertLogs("script.todo.mail.rules.run", "INFO") as journal,
        ):
            code, sortie = self.lancer("--quiet")
        self.assertNotIn("vacances-inventees", sortie)
        self.assertNotIn("valeur-inventee", sortie)
        self.assertIn(t("mail_rules_cap_warning"), sortie)
        self.assertIn(f"{t('mail_service_rule_warnings')} 2", sortie)
        self.assertIn("vacances-inventees", "\n".join(journal.output))
        self.assertIn("valeur-inventee", "\n".join(journal.output))

    def test_a_failed_catch_up_is_told_without_the_tui_key(self):
        """Le rattrapage en échec : le journal dit le sien, sans renvoyer
        à la touche « l » du TUI, et le code est celui d'une panne de
        lien, comme un dossier en erreur."""
        self.comptes(self.compte("perso"))
        self.regle("perso")
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})

        def passe(session, **kwargs):
            return engine.EngineReport(
                account=session.account.name,
                active_rules=1,
                warnings=[t("mail_rules_error")],
            )

        with mock.patch.object(engine, "run_pass", side_effect=passe):
            code, sortie = self.lancer()
        self.assertEqual(code, run.EXIT_NETWORK)
        self.assertIn(t("mail_service_catchup_failed"), sortie)
        self.assertNotIn(t("mail_rules_error"), sortie)
        # Répété à l'identique avec --quiet : tu, comme un dossier en
        # erreur qui dure.
        with mock.patch.object(engine, "run_pass", side_effect=passe):
            code, sortie = self.lancer("--quiet")
            code, sortie = self.lancer("--quiet")
        self.assertEqual(code, run.EXIT_NETWORK)
        self.assertEqual(sortie, "")


class TestKeyring(ServiceCase):
    """Un compte au trousseau système : sondé avant tout réseau, puis
    avant chaque lecture ; jamais déverrouillé."""

    def setUp(self):
        super().setUp()
        compte = account_from_preset("perso", OWN, "generic", vault="keyring")
        compte.cache_mode = "clear"
        compte.sent_folder = "INBOX.Sent"
        self.comptes(compte)
        self.regle("perso")
        # Le vrai trousseau n'est jamais atteint.
        for nom in ("get_password", "set_password", "get_keyring"):
            filet = mock.patch(
                f"keyring.{nom}", side_effect=AssertionError("trousseau lu")
            )
            filet.start()
            self.addCleanup(filet.stop)

    def test_a_keyring_account_without_bus_exits_vault(self):
        connect = mock.Mock(side_effect=AssertionError("réseau"))
        with mock.patch.object(
            mail_secrets,
            "_user_bus_socket",
            return_value=self.home / "pas-de-bus",
        ):
            code, sortie = self.lancer(
                env={}, use_keyring=True, connect_fn=connect
            )
        self.assertEqual(code, run.EXIT_VAULT)
        self.assertEqual(
            sortie,
            f"{t('mail_service_vault_locked')}"
            f" {t('mail_service_keyring_no_bus')}\n",
        )
        connect.assert_not_called()

    def test_a_kdbx_only_run_never_probes_the_keyring(self):
        self.comptes(self.compte("perso"))
        self.coffre({"kdbx:ERPLibre/Mail/perso": SECRET_IMAP})
        with mock.patch.object(
            mail_secrets,
            "keyring_headless_problem",
            side_effect=AssertionError("trousseau sondé"),
        ):
            code, _ = self.lancer(use_keyring=True)
        self.assertEqual(code, run.EXIT_OK)
        self.assertEqual(self.connexions, ["perso"])

    def test_a_keyring_run_installs_the_guard(self):
        reponses = iter(["", "mail_service_keyring_locked"])
        sonde = mock.Mock(side_effect=lambda env: next(reponses))
        with mock.patch.object(
            mail_secrets, "keyring_headless_problem", sonde
        ):
            code, sortie = self.lancer(use_keyring=True)
        self.assertEqual(code, run.EXIT_VAULT)
        self.assertEqual(sonde.call_count, 2)
        self.assertEqual(
            sortie,
            f"perso : {t('mail_service_kind_vault')} SecretError\n",
        )
        self.assertEqual(self.connexions, [])


class TestSubprocess(unittest.TestCase):
    """La commande lancée comme le service la lance : un autre processus,
    depuis la racine du dépôt, `HOME` temporaire sans compte."""

    def setUp(self):
        home = tempfile.TemporaryDirectory()
        self.addCleanup(home.cleanup)
        self.env = dict(
            os.environ,
            HOME=home.name,
            XDG_CONFIG_HOME=os.path.join(home.name, ".config"),
            PYTHONPATH=str(REPO),
        )
        self.env.pop("CREDENTIALS_DIRECTORY", None)

    def lancer(self, *argv):
        return subprocess.run(
            [sys.executable, *argv],
            cwd=REPO,
            env=self.env,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_the_module_runs_without_textual(self):
        fini = self.lancer(
            "-c",
            "import sys; from script.todo.mail.rules import run;"
            " rc = run.main(['--quiet']);"
            " print('textual' in sys.modules, rc)",
        )
        self.assertEqual(fini.returncode, 0, fini.stderr)
        self.assertEqual(fini.stdout.strip(), "False 0")

    def test_python_dash_m_reaches_main(self):
        fini = self.lancer("-m", "script.todo.mail.rules.run", "--help")
        self.assertEqual(fini.returncode, 0, fini.stderr)
        self.assertIn("--compte", fini.stdout)
        sans = self.lancer("-m", "script.todo.mail.rules.run")
        self.assertEqual(sans.returncode, 0, sans.stderr)
        self.assertEqual(sans.stdout, t("mail_service_no_account") + "\n")


if __name__ == "__main__":
    unittest.main()
