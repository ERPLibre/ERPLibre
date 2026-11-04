#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le journal de session du TODO garde ce que le terminal a montré.

Il reçoit les messages des loggers et, pour chaque commande lancée par
exec_command_live, la commande, sa sortie et son code, caviardés comme à
l'écran. Il est privé (0600 dans un dossier 0700), borné en nombre, et son
absence n'empêche jamais le TODO de tourner. Les secrets sont inventés.
"""

import io
import logging
import os
import shutil
import stat
import sys
import tempfile
import unittest
from unittest import mock

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.execute import execute  # noqa: E402
from script.todo import todo_journal  # noqa: E402


class TestJournalSession(unittest.TestCase):
    def setUp(self):
        self.etat = tempfile.mkdtemp(prefix="test_todo_journal_")
        self.addCleanup(shutil.rmtree, self.etat, ignore_errors=True)
        self.addCleanup(todo_journal.fermer)
        self.environ = {"XDG_STATE_HOME": self.etat}

    def ouvrir(self, **kwargs):
        chemin = todo_journal.ouvrir(environ=self.environ, **kwargs)
        self.assertIsNotNone(chemin)
        return chemin

    def contenu(self, chemin):
        todo_journal.fermer()
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    def test_commande_sortie_et_code_sont_gardes(self):
        chemin = self.ouvrir()
        code = execute.Execute().exec_command_live(
            "echo bonjour; echo 'curl: (23) essai' >&2; exit 3",
            source_erplibre=False,
            quiet=True,
        )
        self.assertEqual(3, code)
        texte = self.contenu(chemin)
        self.assertIn("$ echo bonjour", texte)
        self.assertIn("bonjour\n", texte)
        self.assertIn("curl: (23) essai", texte)
        self.assertIn("[code 3,", texte)

    def test_les_secrets_sont_caviardes_comme_a_l_ecran(self):
        chemin = self.ouvrir()
        execute.Execute().exec_command_live(
            "echo --password mdp-invente-8812",
            source_erplibre=False,
            quiet=True,
        )
        self.assertNotIn("mdp-invente-8812", self.contenu(chemin))

    def test_les_messages_des_loggers_sont_gardes(self):
        chemin = self.ouvrir()
        logging.getLogger("essai.journal").error("zip incomplet, essai")
        self.assertIn("zip incomplet, essai", self.contenu(chemin))

    def test_les_messages_des_loggers_sont_caviardes(self):
        """Un logger écrit ce qu'on lui donne : le journal masque quand même."""
        chemin = self.ouvrir()
        logging.getLogger("essai.journal").error(
            "Run cmd: odoo-bin --db_password invente-log21"
        )
        texte = self.contenu(chemin)
        self.assertNotIn("invente-log21", texte)
        self.assertIn("Run cmd: odoo-bin --db_password", texte)

    def test_le_traceback_est_caviarde(self):
        chemin = self.ouvrir()
        try:
            raise RuntimeError("echec de curl -u admin:invente-tb22 http://x")
        except RuntimeError:
            todo_journal.noter_exception()
        texte = self.contenu(chemin)
        self.assertNotIn("invente-tb22", texte)
        self.assertIn("RuntimeError: echec de curl -u admin:", texte)

    def test_une_cle_privee_affichee_ligne_par_ligne(self):
        """La sortie arrive ligne par ligne : le corps de la clé, sans aucun
        mot qui le signale, est masqué jusqu'à la ligne de fin."""
        chemin = self.ouvrir()
        execute.Execute().exec_command_live(
            "printf '%s\\n' '-----BEGIN RSA PRIVATE KEY-----'"
            " 'MIIEinvente23' 'invente24==' '-----END RSA PRIVATE KEY-----'"
            " 'apres la cle'",
            source_erplibre=False,
            quiet=True,
        )
        texte = self.contenu(chemin)
        self.assertNotIn("invente23", texte)
        self.assertNotIn("invente24", texte)
        self.assertIn("-----END RSA PRIVATE KEY-----", texte)
        self.assertIn("apres la cle", texte)

    def test_le_journal_est_prive(self):
        chemin = self.ouvrir()
        self.assertEqual(0o600, stat.S_IMODE(os.stat(chemin).st_mode))
        dossier = todo_journal.dossier_journaux(self.environ)
        self.assertEqual(0o700, stat.S_IMODE(os.stat(dossier).st_mode))

    def test_l_en_tete_nomme_le_checkout(self):
        chemin = self.ouvrir()
        self.assertIn(os.getcwd(), self.contenu(chemin).splitlines()[0])

    def test_seuls_les_plus_recents_restent(self):
        dossier = todo_journal.dossier_journaux(self.environ)
        os.makedirs(dossier)
        for rang in range(5):
            ancien = os.path.join(dossier, f"todo_ancien_{rang}.log")
            with open(ancien, "w", encoding="utf-8"):
                pass
            os.utime(ancien, (1000 + rang, 1000 + rang))
        autre = os.path.join(dossier, "autre.txt")
        with open(autre, "w", encoding="utf-8"):
            pass
        chemin = self.ouvrir(garder=3)
        restants = sorted(os.listdir(dossier))
        self.assertIn(os.path.basename(chemin), restants)
        self.assertIn("autre.txt", restants)
        self.assertEqual(
            ["todo_ancien_3.log", "todo_ancien_4.log"],
            sorted(n for n in restants if n.startswith("todo_ancien_")),
        )

    def test_desactive_par_la_variable(self):
        self.environ["ERPLIBRE_TODO_LOG"] = "0"
        self.assertIsNone(todo_journal.ouvrir(environ=self.environ))
        self.assertFalse(os.path.exists(os.path.join(self.etat, "erplibre")))

    def test_un_dossier_inaccessible_n_empeche_pas_le_todo(self):
        bloque = os.path.join(self.etat, "fichier_et_non_dossier")
        with open(bloque, "w", encoding="utf-8"):
            pass
        self.environ["XDG_STATE_HOME"] = bloque
        with mock.patch("builtins.print"):
            self.assertIsNone(todo_journal.ouvrir(environ=self.environ))
        code = execute.Execute().exec_command_live(
            "true", source_erplibre=False, quiet=True
        )
        self.assertEqual(0, code)

    def test_apres_fermeture_plus_rien_n_est_ecrit(self):
        chemin = self.ouvrir()
        todo_journal.fermer()
        taille = os.path.getsize(chemin)
        execute.Execute().exec_command_live(
            "echo apres", source_erplibre=False, quiet=True
        )
        logging.getLogger("essai.journal").error("apres fermeture")
        self.assertEqual(taille, os.path.getsize(chemin))

    def test_un_plantage_laisse_son_traceback(self):
        chemin = self.ouvrir()
        try:
            raise RuntimeError("plantage inventé")
        except RuntimeError:
            todo_journal.noter_exception()
        self.assertIn("RuntimeError: plantage inventé", self.contenu(chemin))


class TestSecretsSuspects(unittest.TestCase):
    """Ce que l'analyse des journaux signale, et ce qu'elle laisse. Valeurs
    inventées."""

    def natures(self, *lignes):
        return todo_journal.secrets_suspects(lignes)

    def test_une_forme_connue_restee_en_clair(self):
        self.assertEqual(
            self.natures("ok", "odoo --db_password invente-31"),
            [(2, "unmasked known form")],
        )

    def test_une_ligne_deja_masquee_ne_compte_pas(self):
        self.assertEqual(self.natures("odoo --db_password '***'"), [])

    def test_les_jetons_que_le_masquage_ne_connait_pas(self):
        cle_aws = "AKIA" + "Q" * 16
        trouvees = self.natures(
            f"export ID={cle_aws}",
            "xoxb-" + "1" * 12,
            "eyJ" + "a" * 10 + ".eyJ" + "b" * 10 + "." + "c" * 10,
        )
        self.assertEqual(
            [n for _, n in trouvees], ["AWS access key", "Slack token", "JWT"]
        )

    def test_un_hash_git_n_est_pas_un_secret(self):
        self.assertEqual(self.natures("commit " + "a1b2c3d4" * 5), [])


class TestDuplicateur(unittest.TestCase):
    """La copie de sys.stdout, seule : l'écran inchangé, le journal propre."""

    def setUp(self):
        self.ecran = io.StringIO()
        self.journal = []
        self.d = todo_journal.Duplicateur(self.ecran, self.journal.append)

    def test_l_ecran_recoit_tout_tel_quel(self):
        texte = "\x1b[32m✅ ok\x1b[0m\n--password invente-41\n"
        self.d.write(texte)
        self.assertEqual(self.ecran.getvalue(), texte)

    def test_le_journal_recoit_des_lignes_caviardees_sans_ansi(self):
        self.d.write("\x1b[32m✅ ok\x1b[0m\n--password invente-42\n")
        self.assertEqual(self.journal, ["✅ ok\n", "--password '***'\n"])

    def test_flush_pousse_l_invite_en_cours(self):
        self.d.write("Commande :")
        self.assertEqual(self.journal, [])
        self.d.flush()
        self.assertEqual(self.journal, ["Commande :\n"])

    def test_rien_pendant_exec_command_live(self):
        with mock.patch.object(execute, "_commandes_en_cours", 1):
            self.d.write("deja journalise\n")
        self.assertEqual(self.journal, [])

    def test_un_menu_reaffiche_ne_s_ecrit_qu_une_fois(self):
        menu = "[1] Un\n[2] Deux\n[3] Trois\n[0] Retour\n"
        self.d.write(menu)
        self.d.write(menu)
        self.assertEqual(self.journal[:4], menu.splitlines(keepends=True))
        self.assertEqual(
            self.journal[4:], [f"({todo_journal.t('menu redisplayed')})\n"]
        )

    def test_l_ecran_alterne_est_suspendu(self):
        self.d.write("\x1b[?1049h")
        self.d.write("dessin de l'interface\n")
        self.d.write("\x1b[?1049l")
        self.d.write("apres\n")
        self.assertEqual(
            self.journal,
            [
                f"({todo_journal.t('full-screen display')})\n",
                "apres\n",
            ],
        )

    def test_une_barre_de_progression_garde_son_dernier_etat(self):
        self.d.write("10%\r50%\r100%\n")
        self.assertEqual(self.journal, ["100%\n"])

    def test_les_attributs_sont_ceux_du_vrai_flux(self):
        self.d.write("x")
        self.assertEqual(self.d.getvalue(), "x")
        self.assertEqual(self.d.encoding, self.ecran.encoding)
        self.assertFalse(self.d.closed)

    def test_un_journal_qui_echoue_ne_casse_pas_l_affichage(self):
        def echoue(_texte):
            raise OSError("disque plein")

        d = todo_journal.Duplicateur(self.ecran, echoue)
        d.write("toujours affiche\n")
        d.flush()
        self.assertIn("toujours affiche", self.ecran.getvalue())


class TestJournalComplet(unittest.TestCase):
    """Le journal ouvert pour de vrai : stdout, DEBUG, sous-processus."""

    def setUp(self):
        self.etat = tempfile.mkdtemp(prefix="test_todo_journal_stdout_")
        self.addCleanup(shutil.rmtree, self.etat, ignore_errors=True)
        self.addCleanup(todo_journal.fermer)
        self.chemin = todo_journal.ouvrir(
            environ={"XDG_STATE_HOME": self.etat}
        )
        self.assertIsNotNone(self.chemin)

    def contenu(self):
        todo_journal.fermer()
        with open(self.chemin, encoding="utf-8") as fichier:
            return fichier.read()

    def test_un_print_va_au_journal_et_stdout_revient(self):
        avant = todo_journal._ouvert["stdout"]
        print("message du TODO, essai 51")
        texte = self.contenu()
        self.assertIn("message du TODO, essai 51\n", texte)
        self.assertIs(sys.stdout, avant)

    def test_une_commande_n_est_pas_recopiee_deux_fois(self):
        execute.Execute().exec_command_live(
            "echo unique-52", source_erplibre=False
        )
        texte = self.contenu()
        # « $ echo unique-52 » puis « unique-52 » : la commande et sa sortie,
        # une fois chacune, et non leur affichage en plus.
        self.assertEqual(texte.count("unique-52"), 2)

    def test_ce_qui_est_tape_n_est_pas_ecrit(self):
        with mock.patch.object(sys, "stdin", io.StringIO("tape-invente-53\n")):
            reponse = input("Invite essai : ")
        self.assertEqual(reponse, "tape-invente-53")
        texte = self.contenu()
        self.assertIn("Invite essai :", texte)
        self.assertNotIn("tape-invente-53", texte)

    def test_le_debug_du_depot_va_au_journal_seulement(self):
        logging.getLogger("script.essai").debug("detail-debug-54")
        logging.getLogger("bibliotheque.essai").debug("bruit-debug-55")
        texte = self.contenu()
        self.assertIn("detail-debug-54", texte)
        self.assertNotIn("bruit-debug-55", texte)

    def test_lancer_journalise_garde_sortie_et_code(self):
        code = todo_journal.lancer_journalise(
            ["sh", "-c", "echo sortie-56; echo --password invente-57; exit 4"]
        )
        self.assertEqual(code, 4)
        texte = self.contenu()
        self.assertIn("sortie-56\n", texte)
        self.assertNotIn("invente-57", texte)
        self.assertIn("[code 4]", texte)

    def test_un_libelle_remplace_la_commande_au_journal(self):
        todo_journal.lancer_journalise(
            ["sh", "-c", "echo script-long-61"], libelle="libelle-lisible-62"
        )
        texte = self.contenu()
        self.assertIn("$ libelle-lisible-62", texte)
        self.assertNotIn("echo script-long-61", texte)
        self.assertIn("script-long-61\n", texte)

    def test_lancer_au_terminal_garde_commande_et_code(self):
        fini = todo_journal.lancer_au_terminal(
            ["sh", "-c", "exit 3"], check=False
        )
        self.assertEqual(fini.returncode, 3)
        texte = self.contenu()
        self.assertIn("$ sh -c exit 3", texte)
        self.assertIn(todo_journal.t("output on the terminal"), texte)
        self.assertIn("[code 3]", texte)

    def test_lancer_au_terminal_note_le_code_avant_de_relever(self):
        import subprocess

        with self.assertRaises(subprocess.CalledProcessError):
            todo_journal.lancer_au_terminal(["sh", "-c", "exit 5"], check=True)
        self.assertIn("[code 5]", self.contenu())

    def test_la_commande_au_terminal_est_caviardee(self):
        todo_journal.lancer_au_terminal(
            "true --password invente-60", shell=True
        )
        self.assertNotIn("invente-60", self.contenu())

    def test_la_session_en_cours_se_nomme(self):
        courant = todo_journal.session_en_cours()
        self.assertEqual(courant["nom"], os.path.basename(self.chemin))
        self.assertTrue(courant["affichage"])
        todo_journal.fermer()
        self.assertIsNone(todo_journal.session_en_cours())


class TestConsoleALInfo(unittest.TestCase):
    """Le DEBUG ouvert pour le journal ne doit pas atteindre la console."""

    def test_la_console_reste_a_info(self):
        etat = tempfile.mkdtemp(prefix="test_todo_journal_console_")
        self.addCleanup(shutil.rmtree, etat, ignore_errors=True)
        console = io.StringIO()
        handler = logging.StreamHandler(console)
        racine = logging.getLogger()
        racine.addHandler(handler)
        self.addCleanup(racine.removeHandler, handler)
        todo_journal.ouvrir(environ={"XDG_STATE_HOME": etat})
        try:
            logging.getLogger("script.essai").debug("detail-console-58")
            logging.getLogger("script.essai").info("info-console-59")
        finally:
            todo_journal.fermer()
        self.assertNotIn("detail-console-58", console.getvalue())
        self.assertIn("info-console-59", console.getvalue())
        self.assertEqual(handler.level, logging.NOTSET)


if __name__ == "__main__":
    unittest.main()
