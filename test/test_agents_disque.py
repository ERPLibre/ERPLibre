#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que Claude Code occupe, et ce que l'écran a le droit de proposer.

Un total par répertoire n'est pas une information sur laquelle agir :
« historique des fichiers : 10 Go » ne dit pas quoi faire. Ces tests fixent le
cran en dessous — l'historique par session, et le plus gros fichier capturé
d'une session — parce que c'est là que la réponse se trouve. Sur la machine où
ce module a été écrit, une seule session portait presque tout le volume, et
dans un seul fichier : une image disque de machine virtuelle, entrée dans
l'historique parce qu'une session l'avait touchée.

Deux garde-fous, et les deux sont des ABSENCES que rien ne signalerait :

**Une session vivante n'est jamais retirable.** Elle écrit encore, et retirer
son historique sous elle laisserait une session qui croit pouvoir restaurer ce
qui n'existe plus.

**Un identifiant ne compose pas un chemin sans contrôle.** Un « .. » y
désignerait autre chose que ce que l'écran a montré, et la suppression est
récursive.

Le système de fichiers est INJECTÉ partout : aucun test ne lit ni n'écrit sur
le disque réel.
"""

import unittest

from script.todo.assistant.agents import disque as dq


def _arbre(contenu):
    """Un faux `os.walk` sur `{chemin: {nom: octets}}`."""

    def marcher(base):
        for chemin, fichiers in contenu.items():
            if chemin == base or chemin.startswith(base.rstrip("/") + "/"):
                yield chemin, [], list(fichiers)

    return marcher


def _tailles(contenu):
    plat = {}
    for chemin, fichiers in contenu.items():
        for nom, octets in fichiers.items():
            plat[f"{chemin}/{nom}"] = octets

    def taille(chemin):
        if chemin not in plat:
            raise OSError(chemin)
        return plat[chemin]

    return taille


class TestLaMesure(unittest.TestCase):
    CONTENU = {
        "/m/file-history": {"gros": 10 << 30},
        "/m/projects": {"a": 1 << 20, "b": 2 << 20},
        "/m/cache": {},
    }

    def _postes(self, present=None):
        return dq.mesurer(
            maison="/m",
            marcher=_arbre(self.CONTENU),
            taille=_tailles(self.CONTENU),
            existe=present
            or (
                lambda c: c.rsplit("/", 1)[-1]
                in {"file-history", "projects", "cache"}
            ),
        )

    def test_the_biggest_comes_first(self):
        noms = [p.nom for p in self._postes()]
        self.assertEqual(noms[0], "file-history")
        self.assertEqual(noms[1], "projects")

    def test_the_bytes_are_summed(self):
        projets = next(p for p in self._postes() if p.nom == "projects")
        self.assertEqual(projets.octets, 3 << 20)
        self.assertEqual(projets.fichiers, 2)

    def test_an_empty_directory_is_present_and_zero(self):
        """Vide et absent pèsent tous deux zéro, et ce n'est pas la même
        chose : le premier a été vidé, le second n'a jamais servi."""
        cache = next(p for p in self._postes() if p.nom == "cache")
        self.assertTrue(cache.present)
        self.assertEqual(cache.octets, 0)

    def test_an_absent_directory_says_so(self):
        greffons = next(p for p in self._postes() if p.nom == "plugins")
        self.assertFalse(greffons.present)

    def test_every_known_directory_is_reported(self):
        """La liste est FERMÉE : un tableau qui change de lignes tout seul ne
        se compare pas d'une fois sur l'autre."""
        self.assertEqual({p.nom for p in self._postes()}, set(dq.REPERTOIRES))

    def test_an_unreadable_file_does_not_raise(self):
        contenu = {"/m/cache": {"absent": 1}}
        postes = dq.mesurer(
            maison="/m",
            marcher=_arbre(contenu),
            taille=lambda c: (_ for _ in ()).throw(OSError(c)),
            existe=lambda c: True,
        )
        self.assertTrue(postes)


class TestLHistoriqueParSession(unittest.TestCase):
    CONTENU = {
        "/m/file-history/aaaa": {"image@v1": 10 << 30, "petit@v2": 1 << 10},
        "/m/file-history/bbbb": {"un@v1": 2 << 20},
        "/m/file-history/cccc": {},
    }

    def _histoires(self, vivantes=()):
        return dq.historiques(
            maison="/m",
            lister=lambda motif: list(self.CONTENU),
            marcher=_arbre(self.CONTENU),
            taille=_tailles(self.CONTENU),
            vivantes=vivantes,
        )

    def test_the_biggest_session_comes_first(self):
        self.assertEqual([h.session for h in self._histoires()][0], "aaaa")

    def test_the_largest_single_capture_is_reported(self):
        """« 10 Go dont 10 Go en un fichier » dit que quelque chose d'énorme
        est entré par accident. « 10 Go » seul ne dit rien."""
        aaaa = self._histoires()[0]
        self.assertEqual(aaaa.plus_gros, 10 << 30)
        self.assertEqual(aaaa.fichiers, 2)

    def test_a_live_session_is_never_removable(self):
        aaaa = self._histoires(vivantes={"aaaa"})[0]
        self.assertTrue(aaaa.vivante)
        self.assertFalse(aaaa.retirable)

    def test_a_dormant_session_is_removable(self):
        aaaa = self._histoires()[0]
        self.assertFalse(aaaa.vivante)
        self.assertTrue(aaaa.retirable)

    def test_an_empty_history_is_not_removable(self):
        """Il n'y a rien à retirer : le proposer serait un geste sans effet."""
        cccc = next(h for h in self._histoires() if h.session == "cccc")
        self.assertFalse(cccc.retirable)

    def test_an_unanswerable_question_offers_nothing(self):
        """None n'est pas l'ensemble vide.

        Le listage des sessions rend une liste VIDE quand l'outil n'est pas
        joignable depuis le processus qui lance le menu — installé par un
        gestionnaire de versions, ou hors du PATH. Confondre « aucune session
        vivante » avec « la question est restée sans réponse » fait tomber la
        garde en OUVERT sur un geste destructeur : toute session devient
        retirable, y compris celle qui écrit en ce moment.
        """
        histoires = self._histoires(vivantes=None)
        self.assertTrue(histoires)
        for histoire in histoires:
            self.assertTrue(histoire.vivante, histoire.session)
            self.assertFalse(histoire.retirable, histoire.session)


class TestLeCheminEstControle(unittest.TestCase):
    def test_a_plain_identifier_composes(self):
        self.assertEqual(
            dq.chemin_historique("aaaa", maison="/m"),
            "/m/file-history/aaaa",
        )

    def test_a_traversal_is_refused(self):
        """La suppression est récursive : un « .. » désignerait autre chose
        que ce que l'écran a montré."""
        for mauvais in ("../..", "a/b", "..", ".ssh", "/etc"):
            with self.assertRaises(ValueError, msg=mauvais):
                dq.chemin_historique(mauvais, maison="/m")

    def test_an_empty_identifier_is_refused(self):
        with self.assertRaises(ValueError):
            dq.chemin_historique("", maison="/m")


class TestLesOctetsLisibles(unittest.TestCase):
    def test_each_scale(self):
        self.assertEqual(dq.octets_lisibles(0), "0")
        self.assertEqual(dq.octets_lisibles(512), "512")
        self.assertEqual(dq.octets_lisibles(45 << 10), "45.0 ko")
        self.assertEqual(dq.octets_lisibles(3 << 20), "3.0 Mo")
        self.assertEqual(dq.octets_lisibles(10 << 30), "10.0 Go")

    def test_none_is_zero(self):
        self.assertEqual(dq.octets_lisibles(None), "0")


if __name__ == "__main__":
    unittest.main()
