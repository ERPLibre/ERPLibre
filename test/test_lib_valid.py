#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les contrôles que plusieurs formats partagent, éprouvés pour eux tous.

Ils étaient éprouvés À TRAVERS le format qui s'en servait d'abord, donc
seulement sur les usages de celui-là. Partagés, leur contrat se dit ici : ce
qu'ils refusent, ce qu'ils normalisent, et ce qu'ils laissent passer.

Ce qu'ils refusent n'est pas cosmétique — chaque valeur finit dans une ligne
de commande lancée par sudo — et « il refuse ce qu'il faut » ne se prouve
qu'avec un contrôle positif à côté : un module qui refuse TOUT passerait la
moitié de ces épreuves.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script import lib_valid as V  # noqa: E402


class TestCeQuilRefuseEtCeQuilLaissePasser(unittest.TestCase):
    def test_a_semicolon_never_reaches_a_shell(self):
        """LE défaut que ces contrôles existent pour empêcher."""
        for valeur in ("machine; rm -rf /", "machine && echo", "a b"):
            with self.subTest(valeur=valeur):
                with self.assertRaises(V.ValidationError):
                    V.text({"k": valeur}, "k", "Hôte", pattern=V.SERVER_RE)

    def test_a_plain_host_passes(self):
        """Contrôle positif : refuser tout passerait l'épreuve d'à côté."""
        self.assertEqual(
            "compte@machine.example",
            V.text(
                {"k": " compte@machine.example "},
                "k",
                "Hôte",
                pattern=V.SERVER_RE,
            ),
        )

    def test_a_user_is_refused_where_only_a_host_belongs(self):
        with self.assertRaises(V.ValidationError):
            V.text({"k": "a@b.example"}, "k", "Domaine", pattern=V.HOST_RE)
        self.assertEqual(
            "b.example",
            V.text({"k": "b.example"}, "k", "Domaine", pattern=V.HOST_RE),
        )

    def test_it_normalises_in_place(self):
        """L'appelant relit le dictionnaire, pas la valeur rendue."""
        fiche = {"k": "  machine  "}
        V.text(fiche, "k", "Hôte")
        self.assertEqual("machine", fiche["k"])

    def test_an_optional_field_left_empty_becomes_an_empty_string(self):
        """Un None survivrait jusqu'à « None » dans un fichier écrit."""
        fiche = {"k": None}
        self.assertEqual("", V.text(fiche, "k", "Hôte", required=False))
        self.assertEqual("", fiche["k"])

    def test_a_required_field_left_empty_is_refused(self):
        with self.assertRaises(V.ValidationError):
            V.text({}, "k", "Hôte")

    def test_a_second_line_is_refused(self):
        """Une valeur écrite dans un fichier de configuration en clé=valeur
        y ouvrirait une ligne que personne n'a voulue."""
        with self.assertRaises(V.ValidationError):
            V.text({"k": "machine\nautre=chose"}, "k", "Hôte")

    def test_a_port_out_of_range_is_refused_and_in_range_is_kept(self):
        self.assertEqual(2222, V.port({"k": "2222"}, "k", "Port"))
        for valeur in (0, 65536, "vingt-deux"):
            with self.subTest(valeur=valeur):
                with self.assertRaises(V.ValidationError):
                    V.port({"k": valeur}, "k", "Port")


class TestIlNeNommeAucunDomaine(unittest.TestCase):
    """Partagé par plusieurs formats, il n'appartient à aucun."""

    def test_it_names_no_domain(self):
        chemin = os.path.join(RACINE, "script", "lib_valid.py")
        with open(chemin, encoding="utf-8") as handle:
            source = handle.read().lower()
        for mot in ("vpn", "wireguard", "sshuttle", "tunnel", "profil"):
            self.assertNotIn(mot, source)


class TestUnBooleenEcrit(unittest.TestCase):
    """« false » est une CHAÎNE, et `bool("false")` vaut vrai.

    Une configuration se tape à la main et se recopie d'un exemple : la
    chaîne y arrive naturellement là où le JSON attendait un littéral. Un
    drapeau qui protège quelque chose se retrouve alors levé par celui qui
    croyait l'abaisser, et rien ne le dit.

    Ce que ça coûte, en clair : « default_route » d'un profil VPN capte tout
    le trafic et coupe la session SSH en cours ; « allow_plaintext » d'un
    profil de forge envoie un jeton d'API en clair sur le réseau. Les deux
    sont faux par défaut, et les deux se lisent par ici.
    """

    def test_a_real_boolean_passes_through(self):
        self.assertTrue(V.flag({"k": True}, "k"))
        self.assertFalse(V.flag({"k": False}, "k"))

    def test_the_written_falses_are_false(self):
        for ecrit in ("false", "0", "no", "off", "non", "faux", ""):
            with self.subTest(ecrit=ecrit):
                self.assertFalse(V.flag({"k": ecrit}, "k"))

    def test_the_written_trues_are_true(self):
        """Contrôle positif : tout rendre faux retirerait l'usage."""
        for ecrit in ("true", "1", "yes", "on", "oui", "vrai"):
            with self.subTest(ecrit=ecrit):
                self.assertTrue(V.flag({"k": ecrit}, "k"))

    def test_case_and_padding_do_not_decide(self):
        """« FALSE » et « Off » viennent d'un fichier écrit par un humain."""
        for ecrit in ("FALSE", " false ", "Off", "\tNON\n"):
            with self.subTest(ecrit=ecrit):
                self.assertFalse(V.flag({"k": ecrit}, "k"))

    def test_a_word_that_is_neither_is_refused_and_not_guessed(self):
        """Deviner ferait dépendre une posture d'une faute de frappe."""
        for ecrit in ("nope", "vrai?", "2", "-1", "y"):
            with self.subTest(ecrit=ecrit):
                with self.assertRaises(V.ValidationError):
                    V.flag({"k": ecrit}, "k")

    def test_a_missing_key_is_false_and_does_not_raise(self):
        """Un drapeau absent d'un profil est un drapeau baissé."""
        self.assertFalse(V.flag({}, "k"))
        self.assertFalse(V.flag({"k": None}, "k"))

    def test_non_text_values_keep_python_truth(self):
        """Un 0, une liste vide, un None disent tous « non » ; un 1 dit
        « oui ». Rien à réinventer pour ces cas-là."""
        for valeur, attendu in (
            (0, False),
            (1, True),
            ([], False),
            ([0], True),
            (0.0, False),
        ):
            with self.subTest(valeur=valeur):
                self.assertEqual(attendu, V.flag({"k": valeur}, "k"))

    def test_it_normalises_in_place_like_its_neighbours(self):
        """Les appelants relisent `record[key]`, pas la valeur rendue."""
        record = {"k": "false"}
        V.flag(record, "k")
        self.assertIs(False, record["k"])

    def test_the_two_lists_never_overlap(self):
        """Un mot dans les deux rendrait la première liste consultée
        gagnante, ce qui est un ordre et non une règle."""
        self.assertEqual(set(), set(V.ECRITS_VRAIS) & set(V.ECRITS_FAUX))


class TestLAncienNomAttrapeToujours(unittest.TestCase):
    """Neuf appelants écrivent `except ProfileError` depuis avant le
    partage : ils doivent attraper ce que le générique lève."""

    def test_the_old_name_is_the_very_same_object(self):
        from script.vpn.valid import ProfileError

        self.assertIs(V.ValidationError, ProfileError)

    def test_what_the_generic_raises_is_caught_by_the_old_name(self):
        from script.vpn.valid import ProfileError

        with self.assertRaises(ProfileError):
            V.text({}, "k", "Hôte")


if __name__ == "__main__":
    unittest.main()
