#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""La polarité : le même chiffre, deux lectures opposées.

Zéro cron actif est le succès attendu d'une copie de développement et une
panne totale sur une production. C'est la propriété centrale de cet outil,
et c'est aussi celle qu'une refonte casserait sans bruit : il suffirait
qu'un contrôle perde une de ses deux politiques pour qu'il se taise —
sans erreur, sans rouge, en donnant l'impression d'avoir été vérifié.

Le second sujet de ce fichier est le secret. Une base de test porte des
clés de paiement encore VIVANTES. Un rapport finit dans un billet ou
devant un agent : aucune requête ne doit lire la valeur d'un secret, et
c'est vérifié sur le texte des requêtes, pas sur l'intention.
"""

import os
import sys
import unittest

sys.path.insert(
    0, os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.analyse import check_instance_state as etat  # noqa: E402


class TestEveryCheckDeclaresBothReadings(unittest.TestCase):
    """Un contrôle sans politique se tairait — sans erreur ni rouge."""

    def test_each_check_has_a_policy_for_each_expectation(self):
        for controle in etat.CONTROLES:
            for attente in etat.ATTENTES:
                self.assertIn(attente, controle, controle["key"])
                self.assertTrue(controle[attente], controle["key"])

    def test_each_policy_is_one_we_know_how_to_read(self):
        connus = ("zero", "nonzero", "info", "skip")
        for controle in etat.CONTROLES:
            for attente in etat.ATTENTES:
                self.assertIn(controle[attente][0], connus, controle["key"])

    def test_a_judging_policy_carries_a_gravity_we_understand(self):
        for controle in etat.CONTROLES:
            for attente in etat.ATTENTES:
                politique = controle[attente]
                if politique[0] in ("zero", "nonzero"):
                    self.assertIn(politique[1], ("broken", "watch"))

    def test_a_judging_policy_explains_itself(self):
        """Un rouge sans raison n'apprend rien à qui le lit."""
        for controle in etat.CONTROLES:
            for attente in etat.ATTENTES:
                if controle[attente][0] in ("zero", "nonzero"):
                    self.assertTrue(
                        controle.get(f"why_{attente}", "").strip(),
                        f"{controle['key']}/{attente}",
                    )

    def test_a_skipped_check_says_why(self):
        for controle in etat.CONTROLES:
            for attente in etat.ATTENTES:
                politique = controle[attente]
                if politique[0] == "skip":
                    self.assertGreater(len(politique), 1, controle["key"])
                    self.assertTrue(politique[1].strip())

    def test_every_section_declared_is_actually_used(self):
        utilisees = {c["section"] for c in etat.CONTROLES}
        self.assertEqual(set(etat.SECTIONS), utilisees)

    def test_keys_are_unique(self):
        cles = [c["key"] for c in etat.CONTROLES]
        self.assertEqual(len(cles), len(set(cles)))


class TestChaqueTexteDeControleEstTraduit(unittest.TestCase):
    """Un texte de contrôle absent de la table s'affiche EN ANGLAIS.

    Les vingt-neuf de cet écran l'étaient : le rapport entier sortait en
    anglais au milieu d'une interface française, et rien ne le disait —
    `t()` rend la clé quand elle ne la connaît pas.

    LA GARDE DES CLÉS LITTÉRALES NE LES VOIT PAS. Ces textes arrivent
    par `t(controle["title"])` : le nom ne se lit pas dans le source, il
    se lit dans la TABLE. C'est donc ici qu'ils se tiennent, au plus près
    de la table qui les porte.

    Le piège qui va avec : ces chaînes sont concaténées sur plusieurs
    lignes. Une expression régulière n'en attrape que le premier
    fragment, et traduire ce fragment ne servirait à rien. La table se
    LIT, elle ne se grepe pas.
    """

    CHAMPS = ("section", "title", "why_copy", "why_live")

    @staticmethod
    def table():
        from script.todo.todo_i18n import TRANSLATIONS

        return TRANSLATIONS

    def test_every_control_text_is_in_the_table(self):
        table = self.table()
        absentes = sorted(
            {
                f"{controle['key']}.{champ} : {texte[:60]}"
                for controle in etat.CONTROLES
                for champ in self.CHAMPS
                if (texte := controle.get(champ)) and texte not in table
            }
        )
        self.assertEqual([], absentes)

    def test_the_scan_actually_reads_texts(self):
        """Sur zéro texte lu, la garde passe et ne tient rien."""
        textes = [
            controle.get(champ)
            for controle in etat.CONTROLES
            for champ in self.CHAMPS
            if controle.get(champ)
        ]
        self.assertGreater(len(textes), 20)

    def test_a_text_written_on_several_lines_is_read_whole(self):
        """La concaténation implicite est l'idiome de cette table : la
        clé est la chaîne ENTIÈRE, pas son premier morceau."""
        longs = [
            t
            for controle in etat.CONTROLES
            for champ in self.CHAMPS
            if (t := controle.get(champ)) and len(t) > 80
        ]
        self.assertTrue(longs)
        for texte in longs:
            with self.subTest(texte=texte[:40]):
                self.assertIn(texte, self.table())


class TestThePolarityActuallyInverts(unittest.TestCase):
    """La propriété centrale, épinglée sur un cas réel mesuré."""

    def _controle(self, cle):
        for controle in etat.CONTROLES:
            if controle["key"] == cle:
                return controle
        raise AssertionError(cle)

    def test_active_crons_are_a_fault_on_a_copy_and_normal_when_live(self):
        controle = self._controle("cron_active")
        copie = etat.verdict(controle, 35, etat.COPY)
        vivante = etat.verdict(controle, 35, etat.LIVE)
        self.assertEqual(copie[0], "bad")
        self.assertEqual(vivante[0], "ok")

    def test_no_cron_at_all_is_the_opposite(self):
        controle = self._controle("cron_active")
        self.assertEqual(etat.verdict(controle, 0, etat.COPY)[0], "ok")
        self.assertEqual(etat.verdict(controle, 0, etat.LIVE)[0], "bad")

    def test_late_jobs_are_not_judged_on_a_copy(self):
        """Une copie jamais démarrée hérite des retards de l'ORIGINE."""
        controle = self._controle("cron_late")
        genre, _, raison = etat.verdict(controle, 11, etat.COPY)
        self.assertEqual(genre, "skip")
        self.assertTrue(raison)
        self.assertEqual(etat.verdict(controle, 11, etat.LIVE)[0], "bad")

    def test_missing_backups_are_not_judged_on_a_copy(self):
        """update_prod_to_dev les efface : leur absence ne prouve rien."""
        controle = self._controle("backup_rows")
        self.assertEqual(etat.verdict(controle, 0, etat.COPY)[0], "skip")
        self.assertEqual(etat.verdict(controle, 0, etat.LIVE)[0], "bad")

    def test_having_no_mail_server_warns_under_both_readings(self):
        """Zéro serveur NE prouve PAS la sûreté : Odoo retombe sur la conf.

        C'est pourquoi le `neutralize.sql` d'Odoo INSÈRE un serveur bouchon
        `invalid:1025` au lieu de tout supprimer, avec le commentaire
        « prevent using fallback servers ». Notre `disable_mail_server`, lui,
        fait `unlink()` — il rouvre la porte qu'Odoo ferme.
        """
        controle = self._controle("mail_server_total")
        for attente in etat.ATTENTES:
            self.assertEqual(etat.verdict(controle, 0, attente)[0], "bad")

    def test_a_check_without_a_policy_is_skipped_never_approved(self):
        """L'oubli doit se voir comme un trou, pas comme un feu vert."""
        orphelin = {"key": "x", "section": "Users", "title": "x", "sql": ""}
        for attente in etat.ATTENTES:
            self.assertEqual(etat.verdict(orphelin, 99, attente)[0], "skip")

    def test_an_unreadable_check_is_not_a_zero(self):
        controle = self._controle("cron_active")
        genre, _, raison = etat.verdict(
            controle, {"error": "relation absente"}, etat.COPY
        )
        self.assertEqual(genre, "unreadable")
        self.assertIn("relation", raison)


class TestWhatTheReportSaysAndCounts(unittest.TestCase):
    def _tout(self, valeur=0):
        return {c["key"]: valeur for c in etat.CONTROLES}

    def test_the_header_names_the_reading(self):
        for attente, mot in (
            (etat.COPY, "a development copy"),
            (etat.LIVE, "a live instance"),
        ):
            texte = etat.render("b", self._tout(), attente, colour=False)
            self.assertIn(etat.t(mot), texte)

    def test_only_faults_reach_the_exit_code(self):
        resultats = self._tout()
        resultats["cron_active"] = 35  # faute sous copy, normal sous live
        self.assertTrue(etat.findings(resultats, etat.COPY))
        self.assertFalse(
            [
                f
                for f in etat.findings(resultats, etat.LIVE)
                if f[0]["key"] == "cron_active"
            ]
        )

    def test_a_skipped_check_shows_its_number_and_its_reason(self):
        resultats = self._tout()
        resultats["cron_late"] = 11
        texte = etat.render("b", resultats, etat.COPY, colour=False)
        self.assertIn("11", texte)
        self.assertIn(
            etat.t(
                "Nobody runs the scheduler on a restored copy:"
                " measured 11 late on an untouched source"
                " database."
            ),
            texte,
        )

    def test_an_unreadable_check_is_shown_as_unknown(self):
        resultats = self._tout()
        resultats["mail_stuck"] = {"error": "relation absente"}
        texte = etat.render("b", resultats, etat.LIVE, colour=False)
        self.assertIn("❔", texte)

    def test_sections_come_out_in_the_declared_order(self):
        texte = etat.render("b", self._tout(), etat.COPY, colour=False)
        positions = [texte.find(etat.t(s)) for s in etat.SECTIONS]
        self.assertEqual(positions, sorted(positions))
        self.assertNotIn(-1, positions)


class TestNoQueryEverReadsASecret(unittest.TestCase):
    """Une base de test porte des clés de paiement encore VIVANTES."""

    SECRETS = (
        "secret_key",
        "publishable_key",
        "smtp_pass",
        "password",
        "sftp_password",
        "database.secret",
        "api_key",
    )

    def test_no_secret_column_is_selected(self):
        for controle in etat.CONTROLES:
            minuscule = controle["sql"].lower()
            for secret in self.SECRETS:
                self.assertNotIn(secret, minuscule, controle["key"])

    def test_every_query_reads_and_returns_one_number(self):
        for controle in etat.CONTROLES:
            sql = " ".join(controle["sql"].split())
            self.assertTrue(sql.upper().startswith("SELECT"), controle["key"])
            majuscule = f" {sql.upper()} "
            for interdit in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER"):
                self.assertNotIn(f" {interdit} ", majuscule, controle["key"])


if __name__ == "__main__":
    unittest.main()
