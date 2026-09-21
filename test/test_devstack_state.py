#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'écran d'avancement doit se DÉRIVER, sinon c'est un tableau de plus.

Un tableau écrit à la main vieillit sans un mot : il reste lisible, personne
ne le relit, et il dit « fait » longtemps après qu'on a défait. Ces épreuves
tiennent la seule propriété qui l'en distingue — chaque ligne bouge quand ce
qu'elle décrit bouge.

Le relevé est POSÉ et jamais lu sur la machine : c'est ce qui permet
d'éprouver l'état d'un site qu'on n'a pas sous la main, et de vérifier les
verdicts qu'on ne peut pas provoquer ici.
"""

import os
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo import devstack_state as D  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


def releve(**remplace):
    """Un relevé de banc : tout est réglé, sauf ce qu'on retire."""
    base = {
        "backends_eprouves": ("libvirt", "pve", "lima"),
        "postures_armees": ("connected", "paranoid", "local-only"),
        "profils_servant_le_web": ("local-webui",),
        "profils_forge": ("forge-du-site",),
        "cibles_sauvegarde": ("nas-hors-site",),
        "forge_canonique": "amont",
        "miroirs_sortants": ("interne",),
    }
    base.update(remplace)
    return D.Releve(**base)


class CasDeLangue(unittest.TestCase):
    """La langue est ÉPINGLÉE : les clés SONT les chaînes anglaises."""

    def setUp(self):
        self.addCleanup(
            setattr, todo_i18n, "_current_lang", todo_i18n._current_lang
        )
        todo_i18n._current_lang = "en"


class TestChaqueSegmentDeDevstackAUneLigne(CasDeLangue):
    """Le socle en compte treize. Un segment sans ligne se lirait comme un
    segment qui n'existe pas, et une liste amputée se lit comme une liste."""

    SEGMENTS = (
        "host-base",
        "sandbox-vm",
        "ai-tools",
        "local-ai",
        "connected-vm",
        "local-forge",
        "canonical-forge",
        "github-mirror",
        "openbao-master",
        "openbao-follower",
        "sauvegarde-hors-instance",
        "restore-test",
        "local-webui",
    )

    def test_the_thirteen_segments_each_have_one_line(self):
        vus = [l.segment for l in D.lignes(releve())]
        self.assertEqual(list(self.SEGMENTS), vus)

    def test_every_state_is_one_of_the_three(self):
        for ligne in D.lignes(releve()):
            with self.subTest(segment=ligne.segment):
                self.assertIn(ligne.etat, D.ETATS)

    def test_every_line_says_where_it_comes_from(self):
        """Sans origine, la ligne est une affirmation de plus : personne ne
        peut la contredire sans lire le module qui la rend."""
        for ligne in D.lignes(releve()):
            with self.subTest(segment=ligne.segment):
                self.assertTrue(ligne.source.strip())

    def test_every_line_says_something(self):
        for ligne in D.lignes(releve()):
            with self.subTest(segment=ligne.segment):
                self.assertTrue(ligne.detail.strip())


class TestLEtatSuitCeQuiDecide(CasDeLangue):
    """La seule propriété qui distingue cet écran d'un tableau écrit à la
    main : chaque ligne BOUGE quand ce qu'elle décrit bouge."""

    @staticmethod
    def etat_de(rendu, segment):
        return next(l.etat for l in rendu if l.segment == segment)

    def test_losing_every_proven_backend_shows_on_the_host_line(self):
        self.assertEqual(
            D.PORTE, self.etat_de(D.lignes(releve()), "host-base")
        )
        self.assertEqual(
            D.ABSENT,
            self.etat_de(D.lignes(releve(backends_eprouves=())), "host-base"),
        )

    def test_postures_that_stop_arming_show_on_the_connected_line(self):
        self.assertEqual(
            D.PORTE, self.etat_de(D.lignes(releve()), "connected-vm")
        )
        self.assertEqual(
            D.ABSENT,
            self.etat_de(
                D.lignes(releve(postures_armees=("open",))), "connected-vm"
            ),
        )

    def test_a_forge_the_code_drives_but_the_site_has_not_declared(self):
        """L'ÉTAT DU MILIEU existe pour ce cas exactement : dire « fait »
        enverrait chercher une panne là où il n'y a qu'un réglage absent,
        et dire « absent » accuserait le code de ce qu'il sait faire."""
        self.assertEqual(
            D.PORTE, self.etat_de(D.lignes(releve()), "local-forge")
        )
        self.assertEqual(
            D.A_REGLER,
            self.etat_de(D.lignes(releve(profils_forge=())), "local-forge"),
        )

    def test_a_backup_target_the_site_has_not_declared(self):
        self.assertEqual(
            D.A_REGLER,
            self.etat_de(
                D.lignes(releve(cibles_sauvegarde=())),
                "sauvegarde-hors-instance",
            ),
        )

    def test_the_web_half_needs_both_the_posture_and_the_profile(self):
        """DEUX CONDITIONS, et aucune ne se déduit de l'autre : une sortie
        coupée sans profil qui promette une interface ne sert rien, et un
        profil qui promet sans règles promet ce qu'il ne tient pas."""
        self.assertEqual(
            D.PORTE, self.etat_de(D.lignes(releve()), "local-webui")
        )
        for manque in (
            {"postures_armees": ("connected",)},
            {"profils_servant_le_web": ()},
        ):
            with self.subTest(**manque):
                self.assertEqual(
                    D.A_REGLER,
                    self.etat_de(D.lignes(releve(**manque)), "local-webui"),
                )


class TestLesDeuxLignesDesForges(CasDeLangue):
    """Elles disaient « absent du dépôt », et le dépôt sait désormais.

    Le rôle d'autorité existe et refuse deux canoniques ; le sens du miroir
    se dérive du manifeste et la surcharge le corrige ; la forge pousse
    d'elle-même. Ce qui manque est un RÉGLAGE de site, pas du code — et les
    deux ne s'adressent pas à la même personne.
    """

    @staticmethod
    def etat_de(rendu, segment):
        return next(l.etat for l in rendu if l.segment == segment)

    def test_an_authority_the_site_has_declared(self):
        self.assertEqual(
            D.PORTE, self.etat_de(D.lignes(releve()), "canonical-forge")
        )

    def test_a_site_without_one_has_something_to_set_not_to_write(self):
        """L'ÉTAT DU MILIEU : dire « absent » accuserait le code de ce
        qu'il sait faire, et « fait » enverrait chercher une panne là où il
        n'y a qu'un réglage."""
        self.assertEqual(
            D.A_REGLER,
            self.etat_de(
                D.lignes(releve(forge_canonique="")), "canonical-forge"
            ),
        )

    def test_the_authority_is_named_and_not_just_counted(self):
        """Un « oui » ne dirait pas laquelle, et c'est justement ce qu'on
        vient voir."""
        ligne = next(
            l for l in D.lignes(releve()) if l.segment == "canonical-forge"
        )
        self.assertIn("amont", ligne.detail)

    def test_an_outbound_mirror_the_site_has_declared(self):
        self.assertEqual(
            D.PORTE, self.etat_de(D.lignes(releve()), "github-mirror")
        )

    def test_no_outbound_mirror_is_a_setting_too(self):
        self.assertEqual(
            D.A_REGLER,
            self.etat_de(
                D.lignes(releve(miroirs_sortants=())), "github-mirror"
            ),
        )


class TestLeCompte(CasDeLangue):
    def test_the_count_covers_every_line(self):
        rendu = D.lignes(releve())
        self.assertEqual(len(rendu), sum(D.compte(rendu).values()))

    def test_every_state_appears_even_at_zero(self):
        """Un état absent de la table se lirait « aucun segment dans cet
        état » aussi bien que « cet état n'existe pas »."""
        self.assertEqual(set(D.ETATS), set(D.compte(D.lignes(releve()))))


class TestCeQueLEcranMontre(CasDeLangue):
    def test_each_segment_is_printed_with_its_source(self):
        texte = "\n".join(D.render(D.lignes(releve())))
        for ligne in D.lignes(releve()):
            with self.subTest(segment=ligne.segment):
                self.assertIn(ligne.segment, texte)
                self.assertIn(ligne.source, texte)

    def test_each_state_has_a_mark_of_its_own(self):
        """Deux états sous la même marque ne se distinguent pas à l'œil,
        et c'est le seul usage de cet écran."""
        self.assertEqual(len(D.ETATS), len(set(D.MARQUES.values())))
        self.assertEqual(set(D.ETATS), set(D.MARQUES))


class TestLeReleveTouchELaConfigurationEtLaDecisionNon(CasDeLangue):
    """Le partage qui rend l'écran éprouvable.

    `lignes` ne doit lire NI fichier NI machine : c'est ce qui permet de
    vérifier l'état d'un site qu'on n'a pas sous la main.
    """

    def test_the_decision_reads_nothing_of_the_machine(self):
        import inspect

        corps = inspect.getsource(D.lignes)
        for interdit in ("open(", "config", "subprocess", "os.path"):
            with self.subTest(interdit=interdit):
                self.assertNotIn(interdit, corps)

    def test_the_survey_gathers_everything_the_decision_needs(self):
        """Un champ du relevé que personne ne lit est un relevé qui coûte
        sans servir ; un champ manquant ferait lire la machine plus bas."""
        import inspect

        corps = inspect.getsource(D.lignes)
        lus = {c for c in D.Releve._fields if f"vu.{c}" in corps}
        self.assertEqual(set(D.Releve._fields), lus)


if __name__ == "__main__":
    unittest.main()
