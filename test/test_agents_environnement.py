#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'environnement d'une session : ce qui s'affiche, et surtout ce qui non.

Ce module est le premier de la fonctionnalité qui peut montrer un SECRET à
l'écran, donc ces tests portent presque tous sur des absences.

**Le découpage fuit avant le masquage.** Une valeur peut porter des sauts de
ligne — une invite de shell en porte — donc découper le bloc sur les sauts de
ligne puis couper sur `=` rend des fragments de VALEUR au milieu d'une liste
de NOMS. Un test reproduit exactement ce cas : il compte les noms d'un bloc
dont une valeur est multiligne, et exige que le fragment n'en soit pas un.

**Le masquage est une LISTE BLANCHE.** Le filtre par motif du dépôt ne
reconnaît que `NOM=valeur` collé ; en deux colonnes il laisse passer presque
tout. Une valeur ne s'affiche donc que si son nom est déclaré ET que sa valeur
a la forme attendue — ce qui rattrape une valeur détournée dans un nom permis.

**None n'est pas une liste vide.** « Rien n'a pu être lu » et « ce processus
n'a aucune variable » se ressemblent à l'écran et disent le contraire.

Les valeurs sont inventées. Le témoin qui joue le secret est planté dans
l'entrée exprès : sa présence est ce qui prouve qu'il ne ressort pas.
"""

import unittest

from script.todo.assistant.agents import environnement as env

TEMOIN = "valeur-de-secret-qui-ne-doit-pas-sortir"


def _bloc(paires):
    """Un `/proc/<pid>/environ` : des « NOM=valeur » séparés par l'octet nul."""
    return b"\0".join(f"{n}={v}".encode("utf-8") for n, v in paires) + b"\0"


def _ouvrir(brut):
    class Faux:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self):
            return brut

    return lambda chemin: Faux()


class TestLeDecoupage(unittest.TestCase):
    def test_a_plain_block(self):
        self.assertEqual(
            env.decouper(_bloc([("LANG", "fr_CA.UTF-8"), ("SHLVL", "2")])),
            [("LANG", "fr_CA.UTF-8"), ("SHLVL", "2")],
        )

    def test_only_the_first_equals_splits(self):
        """Une valeur porte volontiers des « = » : les couper la tronquerait."""
        ((nom, valeur),) = env.decouper(_bloc([("A", "b=c=d")]))
        self.assertEqual((nom, valeur), ("A", "b=c=d"))

    def test_a_multiline_value_does_not_become_a_name(self):
        """Le cas réel : découper sur les sauts de ligne rend vingt-neuf
        « noms » pour vingt-sept variables, dont un de deux cent cinquante-neuf
        caractères — un morceau de la valeur d'une invite de shell."""
        invite = "\\u@\\h \\w\nsuite de l'invite\nencore\n"
        paires = env.decouper(_bloc([("PS1", invite), ("TERM", "xterm")]))
        self.assertEqual([n for n, _ in paires], ["PS1", "TERM"])

    def test_a_fragment_is_rejected_as_a_name(self):
        """Ce qui n'est pas un identifiant n'est pas un nom de variable."""
        brut = b"PATH=/bin\0un fragment de valeur=suite\0TERM=xterm\0"
        self.assertEqual([n for n, _ in env.decouper(brut)], ["PATH", "TERM"])

    def test_an_entry_without_an_equals_is_dropped(self):
        self.assertEqual(env.decouper(b"SANSEGAL\0TERM=xterm\0")[0][0], "TERM")

    def test_an_empty_block_yields_nothing(self):
        self.assertEqual(env.decouper(b""), [])
        self.assertEqual(env.decouper(None), [])


class TestLeJugement(unittest.TestCase):
    def test_a_declared_name_with_the_expected_shape_shows(self):
        variable = env.juger("TERM", "xterm-256color")
        self.assertTrue(variable.visible)
        self.assertEqual(variable.forme, "xterm-256color")

    def test_a_declared_name_with_a_wrong_shape_is_masked(self):
        """La forme rattrape une valeur détournée dans un nom permis."""
        variable = env.juger("SHELL", f"/bin/bash #{TEMOIN}")
        self.assertFalse(variable.visible)
        self.assertNotIn(TEMOIN, variable.forme)

    def test_an_undeclared_name_only_shows_its_shape(self):
        variable = env.juger("UNE_VARIABLE_INCONNUE", TEMOIN)
        self.assertFalse(variable.visible)
        self.assertNotIn(TEMOIN, variable.forme)
        self.assertIn(str(len(TEMOIN)), variable.forme)

    def test_a_secret_does_not_even_show_its_length(self):
        """La longueur d'un secret est déjà un renseignement."""
        for nom in (
            "ANTHROPIC_API_KEY",
            "GITHUB_TOKEN",
            "DB_PASSWORD",
            "AWS_SECRET_ACCESS_KEY",
            "SOME_AUTH_HEADER",
            "STARSHIP_SESSION_KEY",
            "SESSION_COOKIE",
        ):
            variable = env.juger(nom, TEMOIN)
            self.assertTrue(variable.secret, nom)
            self.assertEqual(variable.forme, env.MASQUE, nom)
            self.assertNotIn(str(len(TEMOIN)), variable.forme, nom)

    def test_a_path_says_it_is_a_path(self):
        """La forme diagnostique sans recopier : « c'est un chemin » suffit."""
        self.assertEqual(env.juger("HOME", "/home/compte").forme, "<chemin>")

    def test_an_empty_value_is_not_a_zero_length(self):
        self.assertEqual(env.juger("VIDE", "").forme, "<vide>")

    def test_the_language_of_this_machine_shows(self):
        """Le cas qui a échoué au premier essai : la valeur porte un chiffre."""
        self.assertTrue(env.juger("LANG", "fr_CA.UTF-8").visible)
        self.assertTrue(env.juger("LANG", "en_US.UTF-8").visible)


class TestRienNeSortEnClair(unittest.TestCase):
    """Le témoin planté dans chaque champ ne doit reparaître nulle part."""

    def _liste(self, paires):
        return env.variables(1, ouvrir=_ouvrir(_bloc(paires)))

    def test_no_witness_in_the_whole_listing(self):
        liste = self._liste(
            [
                ("ANTHROPIC_API_KEY", TEMOIN),
                ("PS1", f"invite {TEMOIN}"),
                ("UNE_INCONNUE", TEMOIN),
                ("TERM", "xterm"),
            ]
        )
        rendu = " ".join(f"{v.nom} {v.forme} {v.valeur}" for v in liste)
        self.assertNotIn(TEMOIN, rendu)

    def test_every_name_is_still_listed(self):
        """Masquer n'est pas taire : le nom reste, c'est la valeur qui part."""
        liste = self._liste([("ANTHROPIC_API_KEY", TEMOIN), ("TERM", "x")])
        self.assertEqual([v.nom for v in liste], ["ANTHROPIC_API_KEY", "TERM"])

    def test_the_summary_counts_what_it_says(self):
        """QUATRE nombres, et ils se réconcilient.

        Trois ne le faisaient pas : le dernier comptait les SECRÈTES sous
        l'étiquette « masquées », et le lecteur d'un écran de diagnostic en
        déduisait qu'un reste était dans un état que personne ne nommait. Une
        masquée montre sa forme, une secrète ne montre même pas sa longueur —
        deux états, donc deux nombres.
        """
        liste = self._liste(
            [("TERM", "xterm"), ("SECRET_TOKEN", TEMOIN), ("AUTRE", "x")]
        )
        self.assertEqual(env.resume(liste), "3 · 1 · 2 · 1")
        total, claires, masquees, secretes = [
            int(n) for n in env.resume(liste).split(" · ")
        ]
        self.assertEqual(claires + masquees, total, "les nombres se ferment")
        self.assertLessEqual(secretes, masquees, "un secret est masqué")


class TestLIllisible(unittest.TestCase):
    def test_an_unreadable_process_is_none_not_empty(self):
        """« Rien n'a pu être lu » et « il n'y a rien » disent le contraire."""

        def refuser(chemin):
            raise PermissionError(13, "réservé au propriétaire")

        self.assertIsNone(env.variables(1, ouvrir=refuser))

    def test_a_dead_process_is_none(self):
        def absent(chemin):
            raise FileNotFoundError(2, chemin)

        self.assertIsNone(env.variables(1, ouvrir=absent))

    def test_a_process_with_no_variable_is_an_empty_list(self):
        self.assertEqual(env.variables(1, ouvrir=_ouvrir(b"")), [])

    def test_a_pid_that_is_not_a_number_is_refused(self):
        self.assertIsNone(env.variables("; rm -rf /"))

    def test_the_summary_of_nothing_readable_is_empty(self):
        self.assertEqual(env.resume(None), "")


class TestLeDevoilement(unittest.TestCase):
    """La soupape : une variable à la fois, jamais le bloc."""

    def test_it_returns_the_real_value(self):
        valeur = env.devoile(
            1,
            "UNE_INCONNUE",
            ouvrir=_ouvrir(_bloc([("UNE_INCONNUE", "vraie")])),
        )
        self.assertEqual(valeur, "vraie")

    def test_an_absent_name_returns_none(self):
        self.assertIsNone(
            env.devoile(1, "ABSENTE", ouvrir=_ouvrir(_bloc([("A", "b")])))
        )

    def test_an_unreadable_process_returns_none(self):
        def refuser(chemin):
            raise PermissionError(13, "refusé")

        self.assertIsNone(env.devoile(1, "A", ouvrir=refuser))


class TestLesFamillesAbsentes(unittest.TestCase):
    def test_the_missing_families_are_named(self):
        """Un processus lancé avant un réglage ne le porte pas : le dire évite
        de chercher un écran cassé là où l'environnement est simplement figé.
        """
        liste = env.variables(1, ouvrir=_ouvrir(_bloc([("TERM", "xterm")])))
        self.assertEqual(env.familles_absentes(liste), env.FAMILLES)

    def test_a_present_family_is_not_reported(self):
        liste = env.variables(
            1, ouvrir=_ouvrir(_bloc([("CLAUDE_CODE_ENABLE_TELEMETRY", "1")]))
        )
        self.assertNotIn("CLAUDE_", env.familles_absentes(liste))

    def test_nothing_readable_reports_every_family(self):
        self.assertEqual(env.familles_absentes(None), env.FAMILLES)


if __name__ == "__main__":
    unittest.main()
