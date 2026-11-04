#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le journal de session du TODO garde ce que le terminal a montré.

Il reçoit les messages des loggers et, pour chaque commande lancée par
exec_command_live, la commande, sa sortie et son code, caviardés comme à
l'écran. Il est privé (0600 dans un dossier 0700), borné en nombre, et son
absence n'empêche jamais le TODO de tourner. Les secrets sont inventés.
"""

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


if __name__ == "__main__":
    unittest.main()
