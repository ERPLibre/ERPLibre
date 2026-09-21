#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que la posture nomme se DÉDUIT de ses champs, il ne se recopie pas.

Une liste écrite à la main peut nommer une forge sous une posture qui
annonce ne pas en vouloir. Les épreuves qui suivent modifient un champ et
vérifient que la liste suit : c'est ce qui distingue une déduction d'une
coïncidence, et une table recopiée les confondrait toutes les deux.

L'autre moitié — OÙ ces rôles se trouvent — est un carnet du site, passé en
paramètre. Aucune adresse du dépôt n'y entre, et celles qu'on lit ici sont
des plages de documentation (RFC 5737).
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.lib_valid import ValidationError  # noqa: E402
from script.posture import allowlist as A  # noqa: E402
from script.posture import destinations as D  # noqa: E402
from script.posture import registry as R  # noqa: E402
from script.posture import rules  # noqa: E402

PARANOID = R.get_posture("paranoid")

# Un carnet de banc : un réseau de documentation par rôle connu.
CARNET = {
    nom: [f"198.51.100.{index + 10}/32"]
    for index, nom in enumerate(A.symbol_names())
}


class TestQuiADroitAUneListe(unittest.TestCase):
    def test_it_matches_the_two_fields_that_decide_it(self):
        for nom in R.posture_names():
            posture = R.get_posture(nom)
            attendu = (
                posture.destinations_bounded and posture.egress == "allowlist"
            )
            with self.subTest(posture=nom):
                self.assertEqual(attendu, D.has_bounded_list(posture))

    def test_exactly_one_posture_has_one_today(self):
        """Le compteur du travail : trois postures sur quatre n'ont pas de
        liste bornée, et cette épreuve le dira en tombant le jour où une
        quatrième en gagne une."""
        avec = [
            nom
            for nom in R.posture_names()
            if D.has_bounded_list(R.get_posture(nom))
        ]
        self.assertEqual(["paranoid"], avec)

    def test_no_posture_at_all_has_no_list(self):
        self.assertFalse(D.has_bounded_list(None))
        self.assertEqual((), D.symbols_for(None))

    def test_an_empty_list_means_exactly_that(self):
        """Vide n'est pas un échec : c'est la réponse, et le rendu des
        règles nomme laquelle des deux raisons s'applique."""
        for nom in R.posture_names():
            posture = R.get_posture(nom)
            with self.subTest(posture=nom):
                self.assertEqual(
                    D.has_bounded_list(posture),
                    bool(D.symbols_for(posture)),
                )


class TestLaDeductionSuitLesChamps(unittest.TestCase):
    """Un champ bouge, la liste suit — sinon c'est une table recopiée."""

    def test_the_resolver_follows_the_dns_field(self):
        self.assertIn("dns-resolver", D.symbols_for(PARANOID))
        self.assertNotIn(
            "dns-resolver", D.symbols_for(PARANOID._replace(dns="host"))
        )

    def test_the_forge_follows_the_field_that_asks_for_it(self):
        self.assertIn("forge", D.symbols_for(PARANOID))
        self.assertNotIn(
            "forge", D.symbols_for(PARANOID._replace(needs_forge=False))
        )

    def test_the_ai_gateway_follows_reachable_remote_providers(self):
        """Aucune posture bornée ne les joint aujourd'hui : sans ce
        contrôle, la déduction passerait pour juste en ne rendant jamais
        le rôle."""
        self.assertFalse(PARANOID.cloud)
        self.assertNotIn("ai-gateway", D.symbols_for(PARANOID))
        self.assertIn(
            "ai-gateway", D.symbols_for(PARANOID._replace(cloud=True))
        )

    def test_the_resolver_comes_first(self):
        """Son absence fait lire tous les autres échecs comme des pannes
        de réseau : il se voit en tête de fichier."""
        self.assertEqual("dns-resolver", D.symbols_for(PARANOID)[0])

    def test_no_role_is_named_twice(self):
        noms = D.symbols_for(PARANOID._replace(cloud=True))
        self.assertEqual(len(set(noms)), len(noms), noms)

    def test_every_role_named_exists_in_the_table(self):
        """Un rôle nommé hors table ferait échouer le rendu au bout,
        sur un message qui parlerait de vocabulaire plutôt que de posture."""
        for nom in R.posture_names():
            for symbole in D.symbols_for(R.get_posture(nom)):
                with self.subTest(posture=nom, symbole=symbole):
                    self.assertIn(symbole, A.SYMBOLS)

    def test_the_floor_is_part_of_the_table_too(self):
        self.assertTrue(D.SOCLE, "socle vidé : rien n'est prouvé")
        for symbole in D.SOCLE:
            with self.subTest(symbole=symbole):
                self.assertIn(symbole, A.SYMBOLS)


class TestLeCarnetDuSite(unittest.TestCase):
    def test_it_resolves_every_role_the_posture_names(self):
        prets = D.destinations_for(PARANOID, CARNET)
        self.assertEqual(
            list(D.symbols_for(PARANOID)), [d.symbol for d in prets]
        )

    def test_a_role_without_an_address_is_refused_and_named(self):
        """Rendu quand même, il produirait une machine qui ne joint pas sa
        forge, et le manque se découvrirait sur la machine."""
        ampute = {k: v for k, v in CARNET.items() if k != "forge"}
        with self.assertRaises(ValidationError) as leve:
            D.destinations_for(PARANOID, ampute)
        self.assertIn("forge", str(leve.exception))

    def test_a_role_the_posture_does_not_name_is_not_an_error(self):
        """Le carnet est partagé par toutes les postures : refuser le
        surplus le rendrait inutilisable dès la deuxième."""
        self.assertNotIn("ai-gateway", D.symbols_for(PARANOID))
        prets = D.destinations_for(PARANOID, CARNET)
        self.assertNotIn("ai-gateway", [d.symbol for d in prets])

    def test_a_site_may_serve_a_role_on_another_port(self):
        carnet = dict(CARNET)
        carnet["forge"] = {"networks": ["198.51.100.84/32"], "ports": [8443]}
        prets = D.destinations_for(PARANOID, carnet)
        forge = [d for d in prets if d.symbol == "forge"][0]
        self.assertEqual((8443,), forge.ports)

    def test_a_plain_string_of_networks_is_accepted(self):
        """Une valeur relue d'un fichier de configuration arrive ainsi."""
        carnet = dict(CARNET)
        carnet["forge"] = "198.51.100.84/32, 198.51.100.85/32"
        prets = D.destinations_for(PARANOID, carnet)
        forge = [d for d in prets if d.symbol == "forge"][0]
        self.assertEqual(2, len(forge.networks))

    def test_an_unreadable_entry_is_refused_rather_than_guessed(self):
        """Devinée, elle deviendrait une liste vide, que le contrôle des
        réseaux refuserait aussi. Ce que l'épreuve tient est le MESSAGE :
        « entrée illisible » envoie corriger la forme, « aucun réseau »
        envoie chercher une adresse qui est déjà là."""
        carnet = dict(CARNET)
        carnet["forge"] = 42
        with self.assertRaises(ValidationError) as leve:
            D.destinations_for(PARANOID, carnet)
        self.assertIn("illisible", str(leve.exception))

    def test_the_address_book_still_goes_through_the_door(self):
        """Le carnet est une donnée de site, donc une entrée non contrôlée
        si personne ne la contrôle."""
        carnet = dict(CARNET)
        carnet["forge"] = ["0.0.0.0/0"]
        with self.assertRaises(ValidationError):
            D.destinations_for(PARANOID, carnet)

    def test_a_posture_without_a_list_asks_the_book_for_nothing(self):
        for nom in ("open", "connected", "local-only"):
            with self.subTest(posture=nom):
                self.assertEqual(
                    (), D.destinations_for(R.get_posture(nom), CARNET)
                )

    def test_no_book_at_all_is_refused_where_a_list_is_expected(self):
        with self.assertRaises(ValidationError):
            D.destinations_for(PARANOID, None)
        self.assertEqual((), D.destinations_for(R.get_posture("open"), None))


class TestLesDeuxMoitiesSeRejoignent(unittest.TestCase):
    def test_the_book_and_the_posture_render_a_whole_file(self):
        """Le contrôle de bout en bout : ce que la posture nomme, ce que le
        site adresse, et le fichier qui en sort."""
        texte = rules.render_egress(
            PARANOID, D.destinations_for(PARANOID, CARNET)
        )
        for symbole in D.symbols_for(PARANOID):
            with self.subTest(symbole=symbole):
                self.assertIn(f"# {symbole} :", texte)

    def test_a_posture_without_a_list_is_refused_by_the_renderer(self):
        """Les deux moitiés se répondent : la liste vide n'explique pas
        pourquoi, le rendu si."""
        for nom in ("open", "connected"):
            posture = R.get_posture(nom)
            with self.subTest(posture=nom):
                with self.assertRaises(ValidationError):
                    rules.render_egress(
                        posture, D.destinations_for(posture, CARNET)
                    )


if __name__ == "__main__":
    unittest.main()
