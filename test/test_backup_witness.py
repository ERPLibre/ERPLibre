#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le constat daté d'une sauvegarde, et ce qu'il refuse de croire.

Un vérificateur dit ce qu'il voit à l'instant où on le lance ; le témoin est
ce qui permet de répondre « la dernière fois qu'on a regardé, c'était il y a
trois semaines ». Ni le fichier ni le vérificateur ne portent cette réponse.

RIEN N'EST ÉCRIT CHEZ L'OPÉRATEUR pendant ces épreuves : le chemin du témoin
est déplacé dans un répertoire temporaire par la variable d'environnement
prévue pour cela, et l'horloge est injectée pour que rien ne dépende de
l'instant où l'épreuve tourne.
"""

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.database import backup_verify as V  # noqa: E402
from script.database import backup_witness as W  # noqa: E402

T0 = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


class BancDeTemoin(unittest.TestCase):
    def setUp(self):
        self.dossier = tempfile.TemporaryDirectory()
        self.addCleanup(self.dossier.cleanup)
        chemin = os.path.join(self.dossier.name, "etat", "temoin.json")
        ancien = os.environ.get(W.WITNESS_VAR)
        os.environ[W.WITNESS_VAR] = chemin
        self.addCleanup(self._restaurer, ancien)

    @staticmethod
    def _restaurer(ancien):
        if ancien is None:
            os.environ.pop(W.WITNESS_VAR, None)
        else:
            os.environ[W.WITNESS_VAR] = ancien

    def sauvegarde(self, nom="a.zip", verdict=V.SOUND, **extra):
        return V.Verification(
            verdict,
            path=os.path.join(self.dossier.name, nom),
            size=extra.pop("size", 42),
            checks=extra.pop("checks", ("present", "non-empty", "zip")),
            **extra,
        )


class TestCeQueLeTemoinPorte(BancDeTemoin):
    def test_nothing_looked_at_is_not_nothing_to_report(self):
        self.assertEqual({}, W.entries())

    def test_a_verification_becomes_a_dated_entry(self):
        entree = W.record(self.sauvegarde(), now=T0)
        self.assertEqual(V.SOUND, entree["verdict"])
        self.assertEqual("2026-01-01T12:00:00Z", entree["checked_at"])
        self.assertEqual(["present", "non-empty", "zip"], entree["checks"])

    def test_it_survives_a_new_read(self):
        W.record(self.sauvegarde(), now=T0)
        self.assertEqual(1, len(W.entries()))

    def test_it_is_indexed_by_absolute_path(self):
        """Deux façons d'écrire le même fichier ne doivent pas donner deux
        constats qui se contredisent."""
        W.record(self.sauvegarde(), now=T0)
        (chemin,) = W.entries()
        self.assertTrue(os.path.isabs(chemin))

    def test_a_relative_path_is_found_again_by_its_absolute_one(self):
        """Deux façons d'écrire le même fichier ne doivent pas donner deux
        constats qui se contredisent — ni un constat introuvable."""
        relatif = V.Verification(V.SOUND, path="sauvegardes/a.zip", size=1)
        W.record(relatif, now=T0)
        absolu = os.path.abspath("sauvegardes/a.zip")
        self.assertEqual([absolu], list(W.entries()))
        self.assertEqual(0, W.age_seconds("sauvegardes/a.zip", now=T0))
        self.assertEqual(0, W.age_seconds(absolu, now=T0))

    def test_a_second_look_replaces_the_first(self):
        W.record(self.sauvegarde(verdict=V.SOUND), now=T0)
        W.record(
            self.sauvegarde(verdict=V.CORRUPT),
            now=T0 + timedelta(days=1),
        )
        (entree,) = W.entries().values()
        self.assertEqual(V.CORRUPT, entree["verdict"])
        self.assertEqual(1, len(W.entries()))

    def test_two_backups_do_not_overwrite_each_other(self):
        W.record(self.sauvegarde("a.zip"), now=T0)
        W.record(self.sauvegarde("b.zip"), now=T0)
        self.assertEqual(2, len(W.entries()))

    def test_the_detail_travels_when_there_is_one(self):
        entree = W.record(
            self.sauvegarde(verdict=V.NOT_A_ZIP, detail="pas un index"),
            now=T0,
        )
        self.assertIn("pas un index", entree["detail"])


class TestLaFraicheur(BancDeTemoin):
    def test_never_looked_at_is_none_and_not_zero(self):
        """L'un dit que personne n'a jamais regardé, l'autre qu'on vient de
        le faire."""
        self.assertIsNone(W.age_seconds("/rien.zip"))

    def test_the_age_is_counted_from_the_recorded_instant(self):
        sauvegarde = self.sauvegarde()
        W.record(sauvegarde, now=T0)
        self.assertEqual(
            86400,
            W.age_seconds(sauvegarde.path, now=T0 + timedelta(days=1)),
        )

    def test_a_fresh_look_is_zero_seconds_old(self):
        sauvegarde = self.sauvegarde()
        W.record(sauvegarde, now=T0)
        self.assertEqual(0, W.age_seconds(sauvegarde.path, now=T0))


class TestCeQuIlRefuseDeCroire(BancDeTemoin):
    """Un témoin qu'on peut éditer pour se rassurer ne vaut rien."""

    def ecrire_brut(self, data):
        chemin = W.witness_path()
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fichier:
            json.dump(data, fichier)

    def test_a_verdict_outside_the_vocabulary_is_discarded(self):
        self.ecrire_brut(
            {
                "/x.zip": {
                    "verdict": "inventé",
                    "checked_at": "2026-01-01T00:00:00Z",
                }
            }
        )
        self.assertEqual({}, W.entries())

    def test_a_malformed_date_is_discarded(self):
        """Une tournure de langage n'est pas une date, et aucune
        soustraction ne sait la lire."""
        for date in ("hier", "2026-01-01", "", None):
            with self.subTest(date=date):
                self.ecrire_brut(
                    {"/x.zip": {"verdict": V.SOUND, "checked_at": date}}
                )
                self.assertEqual({}, W.entries())

    def test_a_sound_entry_written_by_hand_is_still_read(self):
        """Contrôle positif : tout refuser ne prouverait rien."""
        self.ecrire_brut(
            {
                "/x.zip": {
                    "verdict": V.SOUND,
                    "checked_at": "2026-01-01T00:00:00Z",
                }
            }
        )
        self.assertEqual(1, len(W.entries()))

    def test_a_corrupt_file_is_no_entry_at_all(self):
        chemin = W.witness_path()
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        with open(chemin, "w", encoding="utf-8") as fichier:
            fichier.write("{ ceci n'est pas du json")
        self.assertEqual({}, W.entries())

    def test_one_bad_entry_does_not_hide_the_good_ones(self):
        self.ecrire_brut(
            {
                "/bon.zip": {
                    "verdict": V.SOUND,
                    "checked_at": "2026-01-01T00:00:00Z",
                },
                "/retouche.zip": {"verdict": "inventé", "checked_at": "x"},
            }
        )
        self.assertEqual(["/bon.zip"], list(W.entries()))


class TestOuIlVitEtCommentIlSEcrit(BancDeTemoin):
    def test_it_is_written_readable_by_its_owner_alone(self):
        W.record(self.sauvegarde(), now=T0)
        self.assertEqual(0o600, os.stat(W.witness_path()).st_mode & 0o777)

    def test_its_parent_is_closed_too(self):
        """Un fichier en 0600 dans un répertoire ouvert se remplace."""
        W.record(self.sauvegarde(), now=T0)
        parent = os.path.dirname(W.witness_path())
        self.assertEqual(0o700, os.stat(parent).st_mode & 0o777)

    def test_no_half_written_file_is_ever_left(self):
        """L'écriture passe par un temporaire puis un remplacement."""
        W.record(self.sauvegarde(), now=T0)
        restes = [
            nom
            for nom in os.listdir(os.path.dirname(W.witness_path()))
            if nom.endswith(".tmp")
        ]
        self.assertEqual([], restes)

    def test_it_lives_outside_the_repository_by_default(self):
        """Une sauvegarde survit à une copie de travail, donc son constat
        aussi — et un fichier posé dans le dépôt se fait emporter par un
        ratissage d'indexation."""
        os.environ.pop(W.WITNESS_VAR, None)
        self.assertNotIn(RACINE, W.witness_path())
        self.assertTrue(W.witness_path().startswith(os.path.expanduser("~")))


if __name__ == "__main__":
    unittest.main()
