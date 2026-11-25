#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le menu Production : sous-menus, commandes tirées du profil, secrets.

La mise à jour arrête un service ; la sauvegarde, la restauration et la
minuterie écrivent. Le menu doit donc toujours passer par la simulation
(`--dry-run`, annoncée une seule fois), ne rien lancer quand elle refuse,
demander avant l'exécution réelle en nommant le service, la base et les
valeurs à risque du profil, et ne lancer celle-ci que sous sudo par
`todo_journal.lancer_au_terminal`, avec l'empreinte du profil simulé.

Chaque commande porte `--profile <chemin absolu>` quand le profil existe,
et `--service` seulement quand l'outil vise une unité. Un secret du
profil n'atteint l'outil que par le chemin d'un fichier 0600 d'un tmpfs,
retiré dans tous les cas ; sa valeur ne paraît ni dans les commandes, ni
dans le journal de session, ni à l'écran.

Rien n'est réellement exécuté : `execute`, `lancer_au_terminal` et le
`subprocess.run` du journal sont des doublures. Les profils, les
préférences, le dossier des unités et les tmpfs sont des dossiers
temporaires ; les valeurs sont inventées.
"""

import collections
import contextlib
import io
import os
import stat
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
# Importé par son dossier et non par `test.` : sous le python3 du système,
# `test` est le paquet des tests de la bibliothèque standard.
sys.path.insert(0, str(RACINE / "test"))
sys.argv = ["todo.py"]

from profil_isole import profil_isole  # noqa: E402

from script.execute import execute as execution  # noqa: E402
from script.lib_ops import profil, systemd  # noqa: E402
from script.todo import (  # noqa: E402
    ops_menu,
    ops_settings,
    todo_i18n,
    todo_prefs,
)
from script.todo.todo import TODO  # noqa: E402

SERVICE = "odoo-exemple.service"
SECRET = "valeur-secrete-inventee-41f9"
REFERENCE = f"ERPLibre/Production/{SERVICE}/warmup.api_key"
DOSSIER_PROFILS = None
_LANGUE = []


def setUpModule():
    global DOSSIER_PROFILS
    # Les outils que le menu construit ne lisent jamais le vrai dossier des
    # profils : la couture vise un dossier temporaire, une garde refuse le
    # vrai.
    DOSSIER_PROFILS = profil_isole()
    preferences = tempfile.TemporaryDirectory(prefix="erplibre-prefs-")
    unittest.addModuleCleanup(preferences.cleanup)
    patch = mock.patch.object(
        todo_prefs,
        "_path",
        lambda: Path(preferences.name) / "todo_prefs.json",
    )
    patch.start()
    unittest.addModuleCleanup(patch.stop)
    _LANGUE.append(todo_i18n._current_lang)
    todo_i18n._current_lang = "en"
    unittest.addModuleCleanup(
        setattr, todo_i18n, "_current_lang", _LANGUE.pop()
    )


class FauxExecute:
    """Retient les commandes et rend le code demandé. Comme le vrai, il
    écrit la commande au journal de session."""

    def __init__(self, code=0):
        self.code = code
        self.commandes = []
        self.options = []

    def exec_command_live(self, cmd, **kw):
        execution._journaliser(f"$ {cmd}\n")
        self.commandes.append(cmd)
        self.options.append(kw)
        return self.code


def chemin_profil():
    return os.path.join(DOSSIER_PROFILS, SERVICE + ".json")


def ecrire_profil(**groupes):
    doc = {"version": profil.VERSION, "service": SERVICE}
    doc.update(groupes)
    profil.ecrire(chemin_profil(), doc)
    return doc


def nouveau_todo(code=0):
    todo = TODO.__new__(TODO)
    todo.execute = FauxExecute(code)
    todo.config_file = None
    todo._ops_service_devine = None
    return todo


Jeu = collections.namedtuple("Jeu", "todo terminal confirm sortie")


class Base(unittest.TestCase):
    """Préférences vides, instance retenue, aucun profil, unités et
    WorkingDirectory simulés."""

    WORKING_DIRECTORY = str(RACINE)

    def setUp(self):
        todo_prefs._save({})
        ops_settings.OpsSettingsMixin._ops_retenir_service(SERVICE)
        if os.path.lexists(chemin_profil()):
            os.unlink(chemin_profil())
        unites = tempfile.TemporaryDirectory(prefix="erplibre-unites-")
        self.addCleanup(unites.cleanup)
        self.unites = unites.name
        # Entrer dans le menu purge les restes de secrets : la purge vise
        # un tmpfs temporaire, jamais celui d'une session réelle.
        tmpfs = tempfile.TemporaryDirectory(prefix="erplibre-tmpfs-")
        self.addCleanup(tmpfs.cleanup)
        self.tmpfs = tmpfs.name
        for patch in (
            mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": tmpfs.name}),
            mock.patch.object(ops_settings, "DEV_SHM", "/nulle/part"),
            mock.patch.object(profil, "DOSSIER_UNITES", unites.name),
            mock.patch.object(
                systemd,
                "lire_proprietes",
                lambda nom, cles, lanceur: {
                    "WorkingDirectory": self.WORKING_DIRECTORY
                },
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)

    def jouer(
        self,
        methode,
        saisies=(),
        code=0,
        confirme=True,
        code_reel=0,
        todo=None,
        args=(),
    ):
        """Joue `methode` ; rend un `Jeu`. `confirme` est la réponse à
        toutes les questions oui/non, ou une liste de réponses."""
        todo = todo or nouveau_todo(code)
        sortie = io.StringIO()
        if isinstance(confirme, (list, tuple)):
            reponses = {"side_effect": list(confirme)}
        else:
            reponses = {"return_value": confirme}
        with (
            mock.patch("builtins.input", side_effect=list(saisies)),
            mock.patch(
                "script.todo.ops_menu.click.confirm", **reponses
            ) as confirm,
            mock.patch(
                "script.todo.ops_menu.todo_journal.lancer_au_terminal",
                return_value=mock.Mock(returncode=code_reel),
            ) as terminal,
            mock.patch(
                "script.todo.ops_menu.subprocess.run",
                side_effect=AssertionError("subprocess.run direct"),
            ),
            contextlib.redirect_stdout(sortie),
        ):
            getattr(todo, methode)(*args)
        return Jeu(todo, terminal, confirm, sortie.getvalue())

    def reelle(self, jeu):
        """L'argv de l'exécution réelle (la dernière)."""
        return jeu.terminal.call_args.args[0]


class TestMiseAJour(Base):
    def test_simulation_puis_sudo_avec_profil(self):
        ecrire_profil(
            instance={"db": "exemple_db"},
            update_module={"ignore_error": ["^odoo\\.addons\\.exemple_a"]},
        )
        empreinte = profil.empreinte_fichier(chemin_profil())
        jeu = self.jouer("_ops_update_modules", ["my_module_a", "", ""])
        (simulation,) = jeu.todo.execute.commandes
        self.assertIn("update_module.py", simulation)
        self.assertIn(f"--service {SERVICE}", simulation)
        self.assertIn(f"--profile {chemin_profil()}", simulation)
        self.assertTrue(simulation.endswith("--dry-run"))
        self.assertEqual(
            jeu.todo.execute.options[0],
            {"source_erplibre": False, "announce": False},
        )
        # La commande s'annonce une seule fois.
        self.assertEqual(jeu.sortie.count(simulation), 1)
        question = jeu.confirm.call_args.args[0]
        self.assertIn(SERVICE, question)
        self.assertIn("exemple_db", question)
        self.assertIn("--ignore-error ^odoo\\.addons\\.exemple_a", question)
        argv = self.reelle(jeu)
        self.assertEqual(argv[0], "sudo")
        self.assertNotIn("--dry-run", argv)
        self.assertIn("my_module_a", argv)
        self.assertEqual(argv[-2:], ["--profile-sha256", empreinte])
        self.assertEqual(argv[argv.index("--profile") + 1], chemin_profil())

    def test_la_question_rappelle_la_purge_des_journaux(self):
        ecrire_profil(update_module={"log_keep_days": 30})
        jeu = self.jouer("_ops_update_modules", ["base", "", ""])
        self.assertIn("--log-keep-days 30", jeu.confirm.call_args.args[0])

    def test_sans_profil_ni_empreinte(self):
        jeu = self.jouer("_ops_update_modules", ["base", "", ""])
        argv = self.reelle(jeu)
        self.assertNotIn("--profile", argv)
        self.assertNotIn("--profile-sha256", argv)
        self.assertIn("--service", argv)
        self.assertIn(t_("(detected)"), jeu.confirm.call_args.args[0])

    def test_base_tapee_et_sans_sauvegarde(self):
        jeu = self.jouer("_ops_update_modules", ["base", "demo_db", "n"])
        argv = self.reelle(jeu)
        self.assertEqual(argv[argv.index("--db") + 1], "demo_db")
        self.assertIn("--no-backup", argv)
        self.assertIn("demo_db", jeu.confirm.call_args.args[0])

    def test_la_base_du_profil_sert_de_defaut(self):
        ecrire_profil(instance={"db": "exemple_db"})
        jeu = self.jouer("_ops_update_modules", ["base", "", ""])
        self.assertNotIn("--db", self.reelle(jeu))
        self.assertIn("exemple_db", jeu.sortie)

    def test_refus_de_la_confirmation(self):
        jeu = self.jouer("_ops_update_modules", ["base", "", ""], confirme=0)
        self.assertEqual(len(jeu.todo.execute.commandes), 1)
        self.assertFalse(jeu.terminal.called)

    def test_simulation_qui_refuse_n_execute_rien(self):
        jeu = self.jouer("_ops_update_modules", ["base", "", ""], code=2)
        self.assertFalse(jeu.confirm.called)
        self.assertFalse(jeu.terminal.called)

    def test_simulation_seule(self):
        jeu = self.jouer("_ops_simulate_modules", ["base", "", ""])
        self.assertEqual(len(jeu.todo.execute.commandes), 1)
        self.assertFalse(jeu.confirm.called)
        self.assertFalse(jeu.terminal.called)

    def test_sans_module_rien_n_est_lance(self):
        jeu = self.jouer("_ops_update_modules", [""])
        self.assertEqual(jeu.todo.execute.commandes, [])
        self.assertFalse(jeu.terminal.called)

    def test_valeurs_citees_pour_le_shell(self):
        jeu = self.jouer(
            "_ops_update_modules", ["base; id", "", ""], confirme=False
        )
        self.assertIn("'base; id'", jeu.todo.execute.commandes[0])

    def test_code_de_l_execution_reelle_affiche(self):
        jeu = self.jouer("_ops_update_modules", ["base", "", ""], code_reel=3)
        self.assertIn(f"{t_('The command ended with code')} 3", jeu.sortie)

    def test_autre_checkout_annonce_dans_la_question(self):
        self.WORKING_DIRECTORY = "/srv/autre-checkout-invente"
        jeu = self.jouer("_ops_update_modules", ["base", "", ""])
        question = jeu.confirm.call_args.args[0]
        self.assertIn("[ATTN]", question)
        self.assertIn("/srv/autre-checkout-invente", question)


def t_(texte):
    return ops_menu.t(texte)


class TestSauvegardes(Base):
    """Sauvegarde, restaurations et minuterie : simulation, accord, sudo
    par lancer_au_terminal, `--service` et `--profile`."""

    CAS = (
        ("_ops_backup_now", [""], "odoo_backup.py", []),
        ("_ops_test_restore", [""], "odoo_backup.py", ["--test-restore"]),
        (
            "_ops_restore_new_database",
            ["/srv/sauvegardes/exemple_db/x.zip", "copie_db"],
            "odoo_backup.py",
            [
                "--restore",
                "--file",
                "/srv/sauvegardes/exemple_db/x.zip",
                "--into",
                "copie_db",
            ],
        ),
        (
            "_ops_backup_timer_install",
            [""],
            "install_backup_timer.py",
            [],
        ),
        (
            "_ops_backup_timer_remove",
            [""],
            "install_backup_timer.py",
            ["--uninstall"],
        ),
    )

    def setUp(self):
        super().setUp()
        ecrire_profil(
            backup={
                "keep_daily": 10,
                "copy_to": "sauvegarde@backup.example.org:/srv/hors-site",
            },
            backup_timer={"on_calendar": "*-*-* 02:30:00"},
        )

    def test_simulation_accord_puis_sudo(self):
        for methode, saisies, script, attendus in self.CAS:
            with self.subTest(methode=methode):
                jeu = self.jouer(methode, saisies)
                (simulation,) = jeu.todo.execute.commandes
                self.assertIn(script, simulation)
                self.assertIn(f"--service {SERVICE}", simulation)
                self.assertIn(f"--profile {chemin_profil()}", simulation)
                self.assertTrue(simulation.endswith("--dry-run"))
                self.assertIs(jeu.todo.execute.options[0]["announce"], False)
                self.assertTrue(jeu.confirm.called)
                argv = self.reelle(jeu)
                self.assertEqual(argv[0], "sudo")
                self.assertTrue(argv[2].endswith(script))
                self.assertNotIn("--dry-run", argv)
                self.assertIn("--profile-sha256", argv)
                for valeur in attendus:
                    self.assertIn(valeur, argv)

    def test_la_question_rappelle_les_valeurs_a_risque(self):
        jeu = self.jouer("_ops_backup_now", [""])
        question = jeu.confirm.call_args.args[0]
        self.assertIn(SERVICE, question)
        self.assertIn("--keep-daily 10", question)
        self.assertIn("--copy-to sauvegarde@backup.example.org", question)

    def test_valeur_tapee_pas_rappelee_comme_du_profil(self):
        jeu = self.jouer("_ops_backup_timer_remove", ["demo_db"])
        question = jeu.confirm.call_args.args[0]
        self.assertIn("demo_db", question)

    def test_la_minuterie_annonce_le_calendrier_du_profil(self):
        jeu = self.jouer("_ops_backup_timer_install", [""])
        self.assertIn("*-*-* 02:30:00", jeu.confirm.call_args.args[0])
        self.assertNotIn("03:00", jeu.confirm.call_args.args[0])

    def test_sans_profil_le_calendrier_de_l_outil(self):
        os.unlink(chemin_profil())
        defaut = ops_settings.construire_parseurs(("backup_timer",))[
            "backup_timer"
        ].get_default("on_calendar")
        jeu = self.jouer("_ops_backup_timer_install", [""])
        self.assertIn(str(defaut), jeu.confirm.call_args.args[0])

    def test_base_transmise_ou_laissee_au_profil(self):
        jeu = self.jouer("_ops_backup_now", ["demo_db"])
        argv = self.reelle(jeu)
        self.assertEqual(argv[argv.index("--db") + 1], "demo_db")
        jeu = self.jouer("_ops_backup_now", [""])
        self.assertNotIn("--db", self.reelle(jeu))

    def test_refus_de_l_accord(self):
        for methode, saisies, _script, _attendus in self.CAS:
            with self.subTest(methode=methode):
                jeu = self.jouer(methode, saisies, confirme=False)
                self.assertEqual(len(jeu.todo.execute.commandes), 1)
                self.assertFalse(jeu.terminal.called)

    def test_simulation_qui_refuse_n_execute_rien(self):
        for methode, saisies, _script, _attendus in self.CAS:
            with self.subTest(methode=methode):
                jeu = self.jouer(methode, saisies, code=2)
                self.assertFalse(jeu.confirm.called)
                self.assertFalse(jeu.terminal.called)

    def test_restauration_sans_fichier_ni_base(self):
        for saisies in ([""], ["x.zip", ""]):
            with self.subTest(saisies=saisies):
                jeu = self.jouer("_ops_restore_new_database", saisies)
                self.assertEqual(jeu.todo.execute.commandes, [])
                self.assertFalse(jeu.terminal.called)

    def test_valeurs_citees_pour_le_shell(self):
        jeu = self.jouer(
            "_ops_restore_new_database", ["a b.zip", "x; id"], confirme=False
        )
        self.assertIn("'a b.zip'", jeu.todo.execute.commandes[0])
        self.assertIn("'x; id'", jeu.todo.execute.commandes[0])

    def test_etat_sans_sudo_ni_service(self):
        ecrire_profil()
        for code in (0, 1, 2):
            with self.subTest(code=code):
                jeu = self.jouer("_ops_backup_status", code=code)
                (commande,) = jeu.todo.execute.commandes
                self.assertIn("--status", commande)
                self.assertIn("--profile", commande)
                # --status liste toutes les bases : il ne vise aucune unité.
                self.assertNotIn("--service", commande)
                self.assertNotIn("sudo", commande)
                self.assertEqual(jeu.confirm.called, code == 2)
                self.assertEqual(jeu.terminal.called, code == 2)

    def test_etat_illisible_propose_sudo(self):
        ecrire_profil()
        jeu = self.jouer("_ops_backup_status", code=2)
        (commande,) = jeu.todo.execute.commandes
        reelle = self.reelle(jeu)
        self.assertEqual(reelle[0], "sudo")
        self.assertEqual(ops_menu.joindre(reelle[1:]), commande)
        jeu = self.jouer("_ops_backup_status", code=2, confirme=False)
        self.assertFalse(jeu.terminal.called)
        self.assertIn("sudo", jeu.sortie)


class TestMinuteries(Base):
    def test_etat_et_credentials(self):
        Path(self.unites, "erplibre-backup-exemple.service").write_text(
            f"ExecStart=/x --profile {chemin_profil()}\n"
            "LoadCredentialEncrypted=warmup.api_key:/etc/credstore.encrypted"
            "/erplibre-backup-exemple.service.warmup.api_key\n"
        )
        Path(self.unites, "erplibre-sante-exemple.service").write_text(
            "LoadCredential=warmup.api_key:/etc/credstore"
            "/erplibre-sante-exemple.service.warmup.api_key\n"
        )
        Path(self.unites, "autre.service").write_text(
            "LoadCredential=x:/etc/credstore/autre.service.x\n"
        )
        ecrire_profil()
        jeu = self.jouer("_ops_timers_status")
        (commande,) = jeu.todo.execute.commandes
        self.assertEqual(commande, "systemctl list-timers --all 'erplibre-*'")
        self.assertNotIn("sudo", commande)
        self.assertIn("erplibre-backup-exemple.service", jeu.sortie)
        self.assertIn(t_("uses this profile"), jeu.sortie)
        self.assertIn(t_("encrypted"), jeu.sortie)
        ligne = next(
            ligne
            for ligne in jeu.sortie.splitlines()
            if t_("stored in clear, readable by root only") in ligne
        )
        self.assertIn("[ATTN]", ligne)
        self.assertNotIn("autre.service", jeu.sortie)

    def lanceur(self, version, creds):
        def lancer(argv, timeout):
            if argv[0] == "systemctl":
                return 0, f"systemd {version} (+PAM)\n"
            return (0, "systemd 255\n") if creds else (127, "")

        return lancer

    def controle(self, version, creds, confirme=True):
        todo = nouveau_todo()
        doc = {"backup_timer": {"cle_inventee": {"kdbx": REFERENCE}}}
        with (
            mock.patch.dict(
                profil.SECRETS, {("backup_timer", "cle_inventee"): "x.cle"}
            ),
            mock.patch.object(
                todo,
                "_ops_document",
                return_value=profil.Lu(doc, "0" * 64, chemin_profil()),
            ),
            mock.patch(
                "script.todo.ops_menu.click.confirm", return_value=confirme
            ) as confirm,
            contextlib.redirect_stdout(io.StringIO()) as sortie,
        ):
            resultat = todo._ops_controle_credentials(
                "backup_timer", lanceur=self.lanceur(version, creds)
            )
        return resultat, confirm, sortie.getvalue()

    def test_controle_des_credentials_avant_le_secret(self):
        resultat, confirm, _ = self.controle(255, True)
        self.assertTrue(resultat)
        self.assertFalse(confirm.called)
        resultat, confirm, _ = self.controle(249, False, confirme=False)
        self.assertFalse(resultat)
        self.assertIs(confirm.call_args.kwargs["default"], False)
        self.assertIn("x.cle", confirm.call_args.args[0])
        resultat, confirm, sortie = self.controle(246, False)
        self.assertFalse(resultat)
        self.assertFalse(confirm.called)
        self.assertIn("247", sortie)

    def test_sans_secret_aucun_controle(self):
        todo = nouveau_todo()
        lanceur = mock.Mock(side_effect=AssertionError("lancé"))
        self.assertTrue(
            todo._ops_controle_credentials("backup_timer", lanceur=lanceur)
        )


class TestJournalEtCourriels(Base):
    """Le journal et la liste des courriels se lisent sans sudo ; un refus
    de lecture (code 2) propose la même commande sous sudo. Le renvoi des
    courriels passe par sudo, sans capture, après accord."""

    def jouer_lecture(self, methode, saisies=(), ecrit=True, **kw):
        with mock.patch(
            "script.todo.ops_menu._inscriptible", return_value=ecrit
        ) as inscriptible:
            jeu = self.jouer(methode, saisies, **kw)
        return jeu, inscriptible

    def test_lectures_sans_sudo(self):
        for methode, saisies, attendus in (
            ("_ops_log_since_last", [], ["log_check.py", "--since-last"]),
            ("_ops_log_last_hours", [""], ["log_check.py", "--last 24"]),
            ("_ops_log_last_hours", ["6"], ["--last 6"]),
            ("_ops_log_hourly", [""], ["--by-hour --days 7"]),
            ("_ops_log_hourly", ["3"], ["--by-hour --days 3"]),
            ("_ops_mail_list", [""], ["mail_retry.py", "--list"]),
            ("_ops_mail_list", ["base_essai"], ["--list --db base_essai"]),
        ):
            with self.subTest(methode=methode, saisies=saisies):
                jeu, _ = self.jouer_lecture(methode, saisies)
                (commande,) = jeu.todo.execute.commandes
                for attendu in attendus:
                    self.assertIn(attendu, commande)
                self.assertIn(f"--service {SERVICE}", commande)
                self.assertNotIn("sudo", commande)
                self.assertEqual(
                    jeu.todo.execute.options[0],
                    {"source_erplibre": False, "announce": False},
                )
                self.assertFalse(jeu.confirm.called)
                self.assertFalse(jeu.terminal.called)

    def test_refus_de_lecture_propose_sudo(self):
        for methode, saisies in (
            ("_ops_log_last_hours", [""]),
            ("_ops_mail_list", [""]),
        ):
            with self.subTest(methode=methode):
                jeu, _ = self.jouer_lecture(methode, saisies, code=2)
                self.assertTrue(jeu.confirm.called)
                argv = self.reelle(jeu)
                self.assertEqual(argv[0], "sudo")
                jeu, _ = self.jouer_lecture(
                    methode, saisies, code=2, confirme=False
                )
                self.assertFalse(jeu.terminal.called)

    def test_nombres_refuses(self):
        """`entier` : « ² » et « ٣ » passent `isdigit()` mais pas int()."""
        for saisie in ("x", "²", "٣", "-1", "1.5", "0"):
            with self.subTest(saisie=saisie):
                jeu, _ = self.jouer_lecture("_ops_log_last_hours", [saisie])
                self.assertEqual(jeu.todo.execute.commandes, [])
                self.assertFalse(jeu.terminal.called)
                self.assertIn(
                    t_("Cancelled: expected a whole number >= 1."), jeu.sortie
                )

    def test_ops_nombre(self):
        todo = nouveau_todo()
        for saisie, attendu in (
            ("", 24),
            ("12", 12),
            ("²", None),
            ("٣", None),
            ("-1", None),
            ("1.5", None),
        ):
            with self.subTest(saisie=saisie):
                with (
                    mock.patch("builtins.input", return_value=saisie),
                    contextlib.redirect_stdout(io.StringIO()),
                ):
                    self.assertEqual(todo._ops_nombre("? ", 24), attendu)

    def test_jours_du_profil(self):
        ecrire_profil(log_check={"days": 14})
        jeu, _ = self.jouer_lecture("_ops_log_hourly", [""])
        (commande,) = jeu.todo.execute.commandes
        # Réponse vide : l'outil lit lui-même les jours du profil.
        self.assertTrue(commande.endswith("--by-hour"), commande)
        jeu, _ = self.jouer_lecture("_ops_log_hourly", ["3"])
        self.assertTrue(jeu.todo.execute.commandes[0].endswith("--days 3"))

    def test_invite_des_jours_montre_le_profil(self):
        ecrire_profil(log_check={"days": 14})
        with mock.patch("builtins.input", return_value="") as saisie:
            todo = nouveau_todo()
            with (
                mock.patch("script.todo.ops_menu._inscriptible"),
                contextlib.redirect_stdout(io.StringIO()),
            ):
                todo._ops_log_hourly()
        self.assertIn("[14]", saisie.call_args.args[0])

    def test_since_last_lit_le_dossier_d_etat_du_profil(self):
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        ecrire_profil(log_check={"state_dir": "/srv/etat-invente"})
        jeu, inscriptible = self.jouer_lecture(
            "_ops_log_since_last", ecrit=False
        )
        inscriptible.assert_called_once_with("/srv/etat-invente")
        self.assertIn("/srv/etat-invente", jeu.confirm.call_args.args[0])
        self.assertEqual(jeu.todo.execute.commandes, [])
        argv = self.reelle(jeu)
        self.assertEqual(argv[0], "sudo")
        self.assertIn("--since-last", argv)

    def test_since_last_sans_profil(self):
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        _jeu, inscriptible = self.jouer_lecture("_ops_log_since_last")
        inscriptible.assert_called_once_with(ops_menu.ETAT_LOG_CHECK)
        jeu, _ = self.jouer_lecture(
            "_ops_log_since_last", ecrit=False, confirme=False
        )
        self.assertFalse(jeu.terminal.called)
        self.assertEqual(len(jeu.todo.execute.commandes), 1)

    def test_renvoi_sous_sudo_apres_accord(self):
        jeu = self.jouer("_ops_mail_retry", ["base_essai"])
        self.assertTrue(jeu.confirm.called)
        argv = self.reelle(jeu)
        self.assertEqual(argv[0], "sudo")
        self.assertTrue(argv[2].endswith("mail_retry.py"))
        self.assertEqual(argv[-2:], ["--db", "base_essai"])
        self.assertNotIn("--yes", argv)
        jeu = self.jouer("_ops_mail_retry", [""], confirme=False)
        self.assertFalse(jeu.terminal.called)
        self.assertEqual(jeu.todo.execute.commandes, [])

    def test_code_sous_sudo_affiche(self):
        for code, montre in ((0, False), (1, False), (2, True)):
            with self.subTest(code=code):
                jeu = self.jouer("_ops_mail_retry", [""], code_reel=code)
                attendu = f"{t_('The command ended with code')} {code}"
                self.assertEqual(attendu in jeu.sortie, montre)


class TestSante(Base):
    def test_sante_locale_sans_les_url_du_profil(self):
        jeu = self.jouer("_ops_health_local")
        (commande,) = jeu.todo.execute.commandes
        self.assertTrue(
            commande.endswith("--local --profile-unset url"), commande
        )
        self.assertIn(f"--service {SERVICE}", commande)
        self.assertFalse(jeu.confirm.called)
        jeu = self.jouer("_ops_health_local", code=2)
        self.assertTrue(jeu.confirm.called)
        self.assertEqual(self.reelle(jeu)[0], "sudo")
        self.assertEqual(self.reelle(jeu)[-1], "url")

    def test_prechauffage(self):
        jeu = self.jouer("_ops_warmup_deep")
        (commande,) = jeu.todo.execute.commandes
        self.assertTrue(commande.endswith("--deep --local"), commande)
        self.assertIn(f"--service {SERVICE}", commande)

    def test_validation_d_odoo_conf_de_l_instance(self):
        jeu = self.jouer("_ops_odoo_conf_check", [""])
        (commande,) = jeu.todo.execute.commandes
        self.assertIn("odoo_conf_check.py", commande)
        self.assertIn(f"--service {SERVICE}", commande)
        self.assertNotIn("--file", commande)
        self.assertFalse(jeu.confirm.called)
        jeu = self.jouer("_ops_odoo_conf_check", [""], code=2)
        self.assertTrue(jeu.confirm.called)
        self.assertEqual(self.reelle(jeu)[0], "sudo")

    def test_validation_d_un_fichier_tape(self):
        with tempfile.TemporaryDirectory() as dossier:
            chemin = os.path.join(dossier, "exemple.conf")
            with open(chemin, "w") as f:
                f.write("[options]\n")
            jeu = self.jouer("_ops_odoo_conf_check", [chemin])
            (commande,) = jeu.todo.execute.commandes
            self.assertTrue(commande.endswith(f"--file {chemin}"), commande)
            self.assertNotIn("--service", commande)
            jeu = self.jouer(
                "_ops_odoo_conf_check", [os.path.join(dossier, "absent")]
            )
        self.assertEqual(jeu.todo.execute.commandes, [])
        self.assertFalse(jeu.terminal.called)
        self.assertIn(
            t_("Cancelled: file not found: {path}").split("{")[0], jeu.sortie
        )

    def test_sante_d_une_url_tapee(self):
        for saisies, attendu in (
            (["example.org", ""], "--url https://example.org"),
            (
                ["https://www.example.org/web", "example.org"],
                "--url https://www.example.org --mail-domain example.org",
            ),
        ):
            with self.subTest(saisies=saisies):
                jeu = self.jouer("_ops_health_url", saisies)
                (commande,) = jeu.todo.execute.commandes
                self.assertIn("health_check.py", commande)
                self.assertNotIn("--service", commande)
                self.assertTrue(commande.endswith(attendu), commande)
                self.assertFalse(jeu.terminal.called)
        jeu = self.jouer("_ops_health_url", ["example.org", ""], code=2)
        self.assertFalse(jeu.terminal.called)

    def test_sante_des_url_du_profil(self):
        ecrire_profil(health_check={"url": ["https://erp.example.org"]})
        jeu = self.jouer("_ops_health_url")
        (commande,) = jeu.todo.execute.commandes
        self.assertNotIn("--url", commande)
        self.assertNotIn("--service", commande)
        self.assertTrue(commande.endswith(chemin_profil()), commande)
        self.assertIn("https://erp.example.org", jeu.confirm.call_args.args[0])
        jeu = self.jouer(
            "_ops_health_url", ["www.example.org", ""], confirme=False
        )
        (commande,) = jeu.todo.execute.commandes
        self.assertTrue(
            commande.endswith("--url https://www.example.org"), commande
        )

    def test_url_ou_domaine_invalide_ne_lance_rien(self):
        for saisies in (
            ["ftp://example.org"],
            ["https://u:p@example.org"],
            [""],
            ["example.org", "-f/etc/passwd"],
            ["example.org", "a;b"],
        ):
            with self.subTest(saisies=saisies):
                jeu = self.jouer("_ops_health_url", saisies)
                self.assertEqual(jeu.todo.execute.commandes, [])


class FauxCoffre:
    def __init__(self, valeurs=None):
        self.valeurs = dict(valeurs or {})
        self.lus = []

    def get(self, ref):
        self.lus.append(ref)
        return self.valeurs.get(ref)


class TestSecretsDuPrechauffage(Base):
    """La clé d'API du profil (référence KeePass) arrive au préchauffage
    par un fichier 0600 du tmpfs, retiré après succès, exception, Ctrl-C
    et reprise sous sudo ; sa valeur ne paraît nulle part."""

    def setUp(self):
        super().setUp()
        ecrire_profil(
            warmup={"login": "warmup-bot", "api_key_file": {"kdbx": REFERENCE}}
        )
        tmpfs = tempfile.TemporaryDirectory(prefix="erplibre-tmpfs-")
        self.addCleanup(tmpfs.cleanup)
        self.tmpfs = tmpfs.name
        self.journal = io.StringIO()
        execution.set_session_journal(self.journal)
        self.addCleanup(execution.set_session_journal, None)
        for patch in (
            mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": self.tmpfs}),
            mock.patch.object(ops_settings, "DEV_SHM", "/nulle/part"),
        ):
            patch.start()
            self.addCleanup(patch.stop)
        self.vus = []

    def todo(self, code=0, coffre=True):
        todo = nouveau_todo(code)
        todo._ops_coffre = lambda: (
            FauxCoffre({"kdbx:" + REFERENCE: SECRET}) if coffre else None
        )
        return todo

    def terminal_reel(self, effet=None):
        """`lancer_au_terminal` réel (il journalise), son subprocess.run
        remplacé : il retient l'état du fichier de secret au lancement."""

        def run(argv, **kw):
            chemin = argv[argv.index("--api-key-file") + 1]
            info = os.stat(chemin)
            self.vus.append(
                (
                    chemin,
                    stat.S_IMODE(info.st_mode),
                    Path(chemin).read_text(),
                )
            )
            if effet is not None:
                raise effet
            return mock.Mock(returncode=0)

        return mock.patch(
            "script.todo.todo_journal.subprocess.run", side_effect=run
        )

    def jouer_secret(self, todo, confirme=True, effet=None):
        sortie = io.StringIO()
        with (
            mock.patch(
                "script.todo.ops_menu.click.confirm", return_value=confirme
            ) as confirm,
            self.terminal_reel(effet),
            contextlib.redirect_stdout(sortie),
            contextlib.redirect_stderr(sortie),
        ):
            todo._ops_warmup_deep()
        return sortie.getvalue(), confirm

    def assertJamaisExpose(self, todo, sortie):
        self.assertNotIn(SECRET, sortie)
        self.assertNotIn(SECRET, " ".join(todo.execute.commandes))
        self.assertNotIn(SECRET, self.journal.getvalue())
        self.assertEqual(os.listdir(self.tmpfs), [])

    def test_fichier_0600_puis_retire(self):
        vus = []

        class Execute(FauxExecute):
            def exec_command_live(self, cmd, **kw):
                chemin = cmd.split("--api-key-file ")[1].split()[0]
                vus.append((Path(chemin).read_text(), os.stat(chemin)))
                return super().exec_command_live(cmd, **kw)

        todo = self.todo()
        todo.execute = Execute()
        sortie, _ = self.jouer_secret(todo)
        (commande,) = todo.execute.commandes
        self.assertIn(f"--api-key-file {self.tmpfs}{os.sep}", commande)
        self.assertNotIn("--profile-unset login", commande)
        ((contenu, info),) = vus
        self.assertEqual(contenu, SECRET)
        self.assertEqual(stat.S_IMODE(info.st_mode), 0o600)
        self.assertJamaisExpose(todo, sortie)

    def test_reprise_sous_sudo_dans_le_meme_bloc(self):
        todo = self.todo(code=2)
        sortie, confirm = self.jouer_secret(todo)
        self.assertTrue(confirm.called)
        ((chemin, mode, contenu),) = self.vus
        self.assertEqual((mode, contenu), (0o600, SECRET))
        self.assertIn(chemin, todo.execute.commandes[0])
        self.assertIn(f"--api-key-file {chemin}", self.journal.getvalue())
        self.assertJamaisExpose(todo, sortie)

    def test_retire_apres_exception_et_ctrl_c(self):
        for erreur in (RuntimeError("panne"), KeyboardInterrupt()):
            with self.subTest(erreur=type(erreur).__name__):
                todo = self.todo(code=2)
                with self.assertRaises(type(erreur)):
                    self.jouer_secret(todo, effet=erreur)
                self.assertEqual(os.listdir(self.tmpfs), [])

    def test_coffre_absent_option_omise(self):
        todo = self.todo(coffre=False)
        sortie, confirm = self.jouer_secret(todo)
        self.assertIn(
            t_("Continue without the authenticated warm-up?"),
            confirm.call_args.args[0],
        )
        (commande,) = todo.execute.commandes
        self.assertNotIn("--api-key-file", commande)
        self.assertNotIn("--profile-unset", commande)
        todo = self.todo(coffre=False)
        self.jouer_secret(todo, confirme=False)
        self.assertEqual(todo.execute.commandes, [])

    def test_refus_sans_tmpfs(self):
        todo = self.todo()
        with mock.patch.dict(os.environ, {"XDG_RUNTIME_DIR": ""}):
            sortie, _ = self.jouer_secret(todo)
        self.assertIn("tmpfs", sortie)
        self.assertNotIn("--api-key-file", todo.execute.commandes[0])
        self.assertNotIn(SECRET, sortie)

    def test_purge_a_l_entree_du_menu(self):
        reste = os.path.join(self.tmpfs, "erplibre-secret-abc123")
        os.mkdir(reste)
        Path(reste, "warmup.api_key").write_text(SECRET)
        # Le dossier d'un todo vivant (un autre onglet) reste.
        vivant = f"erplibre-secret-{os.getpid()}-xyz789"
        os.mkdir(os.path.join(self.tmpfs, vivant))
        self.addCleanup(os.rmdir, os.path.join(self.tmpfs, vivant))
        todo = self.todo()
        with (
            mock.patch("script.todo.ops_menu.click.prompt", return_value="0"),
            mock.patch.object(TODO, "fill_help_info", return_value=""),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            self.assertIs(todo.prompt_execute_production(), False)
        self.assertEqual(os.listdir(self.tmpfs), [vivant])


class TestDossierInscriptible(unittest.TestCase):
    """`_inscriptible` sur de vrais dossiers : celui qui existe, sinon son
    parent existant le plus proche."""

    def test_dossiers(self):
        d = tempfile.TemporaryDirectory()
        self.addCleanup(d.cleanup)
        racine = d.name
        self.assertTrue(ops_menu._inscriptible(racine))
        self.assertTrue(ops_menu._inscriptible(os.path.join(racine, "a", "b")))
        if os.geteuid() == 0:
            self.skipTest("root écrit partout")
        fermee = os.path.join(racine, "fermee")
        os.makedirs(fermee)
        os.chmod(fermee, 0o555)
        self.addCleanup(os.chmod, fermee, 0o755)
        self.assertFalse(ops_menu._inscriptible(fermee))
        self.assertFalse(ops_menu._inscriptible(os.path.join(fermee, "etat")))


class TestLesMenusSontBranches(Base):
    """Chaque entrée de la racine et de chaque sous-menu, jouée au
    clavier, atteint sa méthode."""

    CHEMINS = (
        (["1"], "_ops_choisir_instance"),
        (["2", "1"], "_ops_update_modules"),
        (["2", "2"], "_ops_simulate_modules"),
        (["3", "1"], "_ops_backup_now"),
        (["3", "2"], "_ops_backup_status"),
        (["3", "3"], "_ops_test_restore"),
        (["3", "4"], "_ops_restore_new_database"),
        (["4", "1"], "_ops_log_since_last"),
        (["4", "2"], "_ops_log_last_hours"),
        (["4", "3"], "_ops_log_hourly"),
        (["4", "4"], "_ops_mail_list"),
        (["4", "5"], "_ops_mail_retry"),
        (["5", "1"], "_ops_health_local"),
        (["5", "2"], "_ops_health_url"),
        (["5", "3"], "_ops_warmup_deep"),
        (["5", "4"], "_ops_odoo_conf_check"),
        (["6", "1"], "_ops_perf_audit"),
        (["6", "2"], "_ops_settings_host_local"),
        (["7", "1"], "_ops_timers_status"),
        (["7", "2"], "_ops_backup_timer_install"),
        (["7", "3"], "_ops_backup_timer_remove"),
        (["8", "1"], "_ops_settings_edit"),
        (["8", "2"], "_ops_settings_show"),
        (["8", "3"], "_ops_settings_check"),
        (["8", "4"], "_ops_settings_secrets"),
        (["8", "5"], "_ops_settings_delete"),
        (["8", "6"], "_ops_settings_host"),
    )

    def naviguer(self, touches, methode):
        todo = nouveau_todo()
        retours = touches + ["0"] * len(touches)
        sortie = io.StringIO()
        with (
            mock.patch(
                "script.todo.ops_menu.click.prompt", side_effect=retours
            ),
            mock.patch.object(TODO, "fill_help_info", return_value=""),
            mock.patch.object(TODO, methode) as feuille,
            contextlib.redirect_stdout(sortie),
        ):
            self.assertIs(todo.prompt_execute_production(), False)
        return feuille, sortie.getvalue()

    def test_chaque_entree_atteint_sa_methode(self):
        for touches, methode in self.CHEMINS:
            with self.subTest(touches=touches, methode=methode):
                feuille, _ = self.naviguer(list(touches), methode)
                feuille.assert_called_once_with()

    def test_l_en_tete_nomme_l_instance_et_le_profil(self):
        ecrire_profil(backup={"keep_daily": 10})
        _feuille, sortie = self.naviguer(["8", "2"], "_ops_settings_show")
        self.assertIn(f"🏭 {t_('Instance:')} {SERVICE}", sortie)
        self.assertIn("(1 value(s))", sortie)

    def test_choix_inconnu(self):
        _feuille, sortie = self.naviguer(["9"], "_ops_menu_update")
        self.assertIn(t_("Command not found !"), sortie)

    def test_entree_24_du_menu_execute(self):
        source = (RACINE / "script" / "todo" / "todo.py").read_text()
        self.assertIn(
            '[24] {t("Production - Update, back up, restore and watch a'
            ' systemd instance")}',
            source,
        )
        self.assertIn("status = self.prompt_execute_production()", source)
        self.assertEqual(
            TODO._MENU_LABELS["prompt_execute_production"], "Production"
        )


if __name__ == "__main__":
    unittest.main()
