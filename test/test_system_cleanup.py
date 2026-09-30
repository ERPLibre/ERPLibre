#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'espace à récupérer : ce qui est proposé, et surtout ce qui ne l'est pas.

Chaque cas bâtit un arbre jetable — un $HOME, un /tmp, un data_dir d'Odoo et
un dépôt, tous sous un répertoire temporaire : rien du poste n'est lu ni
effacé.
"""

import os
import tempfile
import time
import unittest

from script.todo import system_cleanup as sc

VIEUX = time.time() - 10 * 86400


def ecrire(chemin, octets=4096, date=None):
    os.makedirs(os.path.dirname(chemin), exist_ok=True)
    with open(chemin, "wb") as fh:
        fh.write(b"x" * octets)
    if date:
        os.utime(chemin, (date, date))


def vieillir(chemin, date=VIEUX):
    """Toute l'arborescence à `date` : ce qui la rend inactive."""
    for dossier, sous, fichiers in os.walk(chemin):
        for nom in sous + fichiers:
            os.utime(os.path.join(dossier, nom), (date, date))
    os.utime(chemin, (date, date))


class Arbre(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        base = tmp.name
        self.home = os.path.join(base, "home")
        self.tmp = os.path.join(base, "tmp")
        self.data = os.path.join(base, "data")
        self.depot = os.path.join(base, "depot")
        for d in (self.home, self.tmp, self.data, self.depot):
            os.makedirs(d)
        self.uid = os.getuid()

    def noms(self, candidats):
        return sorted((c.categorie, c.nom) for c in candidats)


class TestLesCaches(Arbre):
    def test_home_caches_and_repo_residue_are_checked(self):
        ecrire(os.path.join(self.home, ".cache/pip/http/a"))
        ecrire(os.path.join(self.depot, "script/__pycache__/m.pyc"))
        ecrire(os.path.join(self.depot, "htmlcov/index.html"))
        ecrire(os.path.join(self.depot, ".coverage.poste.1"))
        trouves = sc.caches(self.depot, self.home)
        self.assertEqual(
            self.noms(trouves),
            [
                ("cache", ".cache/pip"),
                ("cache", "__pycache__"),
                ("cache", "coverage"),
            ],
        )
        self.assertTrue(all(c.coche for c in trouves))

    def test_poetry_environments_are_not_a_cache(self):
        ecrire(os.path.join(self.home, ".cache/pypoetry/virtualenvs/e/bin/p"))
        self.assertEqual(sc.caches(self.depot, self.home), [])

    def test_venvs_private_and_tasks_are_not_walked(self):
        for rel in (
            ".venv.odoo18.0/lib/__pycache__/a.pyc",
            "private/x/__pycache__/a.pyc",
            "tasks/__pycache__/a.pyc",
        ):
            ecrire(os.path.join(self.depot, rel))
        self.assertEqual(sc.caches(self.depot, self.home), [])


class TestLesRestesDeTmp(Arbre):
    def test_old_leftovers_of_known_tools_only(self):
        ecrire(os.path.join(self.tmp, "run_unit_test.abc/x.log"))
        vieillir(os.path.join(self.tmp, "run_unit_test.abc"))
        ecrire(os.path.join(self.tmp, "tmprecent/x"))
        ecrire(os.path.join(self.tmp, "autre_outil/x"))
        vieillir(os.path.join(self.tmp, "autre_outil"))
        os.makedirs(os.path.join(self.tmp, "sshfs_vide"))
        vieillir(os.path.join(self.tmp, "sshfs_vide"))
        ecrire(os.path.join(self.tmp, "sshfs_plein/f"))
        vieillir(os.path.join(self.tmp, "sshfs_plein"))
        trouves = sc.restes_tmp(self.tmp, self.uid, jours=2)
        self.assertEqual(
            self.noms(trouves),
            [("tmp", "run_unit_test.abc"), ("tmp", "sshfs_vide")],
        )

    def test_another_users_leftover_is_ignored(self):
        ecrire(os.path.join(self.tmp, "run_unit_test.x/y"))
        vieillir(os.path.join(self.tmp, "run_unit_test.x"))
        self.assertEqual(sc.restes_tmp(self.tmp, self.uid + 1, jours=2), [])


class TestOdoo(Arbre):
    def setUp(self):
        super().setUp()
        ecrire(os.path.join(self.data, "filestore/vivante/ab/f"))
        ecrire(os.path.join(self.data, "filestore/orpheline/ab/f"))
        vieillir(os.path.join(self.data, "filestore/orpheline"))
        ecrire(os.path.join(self.data, "sessions/s1"), date=VIEUX)
        ecrire(os.path.join(self.data, "sessions/s2"))

    def test_only_filestores_without_a_database(self):
        trouves = sc.odoo(self.data, {"vivante"}, jours=2)
        self.assertEqual(
            self.noms(trouves),
            [("filestore", "orpheline"), ("sessions", "sessions")],
        )
        sessions = [c for c in trouves if c.categorie == "sessions"][0]
        self.assertEqual(
            [os.path.basename(p) for p in sessions.chemins], ["s1"]
        )

    def test_no_database_list_proposes_no_filestore(self):
        trouves = sc.odoo(self.data, None, jours=2)
        self.assertEqual(self.noms(trouves), [("sessions", "sessions")])

    def test_a_recent_orphan_is_flagged(self):
        ecrire(os.path.join(self.data, "filestore/neuve/f"))
        trouves = sc.odoo(self.data, {"vivante"}, jours=2)
        neuve = [c for c in trouves if c.nom == "neuve"][0]
        self.assertEqual(neuve.mise_en_garde, "recent")
        self.assertFalse(neuve.coche)


class TestLesVenvs(Arbre):
    def test_other_odoo_venvs_only(self):
        for nom in (
            ".venv.odoo18.0_python3.12.10",
            ".venv.odoo16.0_python3.10.0",
            ".venv.erplibre",
        ):
            ecrire(os.path.join(self.depot, nom, "bin/python"))
        trouves = sc.venvs(self.depot, ".venv.odoo18.0_python3.12.10")
        self.assertEqual(
            self.noms(trouves), [("venv", ".venv.odoo16.0_python3.10.0")]
        )
        self.assertEqual(trouves[0].mise_en_garde, "reinstall")


class TestLesGardeFous(Arbre):
    def racines(self):
        return sc.racines_permises(self.depot, self.home, self.tmp, self.data)

    def test_a_path_under_an_allowed_root_passes(self):
        chemin = os.path.join(self.depot, "a/__pycache__")
        os.makedirs(chemin)
        self.assertIsNone(
            sc.refus(chemin, self.depot, self.racines(), self.uid)
        )

    def test_private_and_tasks_are_refused(self):
        for rel in ("private/x", "tasks/y"):
            chemin = os.path.join(self.depot, rel)
            os.makedirs(chemin)
            self.assertEqual(
                sc.refus(chemin, self.depot, self.racines(), self.uid),
                "protected",
            )

    def test_a_link_anywhere_on_the_path_is_refused(self):
        ailleurs = os.path.join(self.home, "ailleurs")
        os.makedirs(os.path.join(ailleurs, "cible"))
        os.symlink(ailleurs, os.path.join(self.tmp, "tmplien"))
        chemin = os.path.join(self.tmp, "tmplien", "cible")
        self.assertEqual(
            sc.refus(chemin, self.depot, self.racines(), self.uid), "link"
        )

    def test_another_owner_is_refused(self):
        chemin = os.path.join(self.tmp, "tmpx")
        os.makedirs(chemin)
        self.assertEqual(
            sc.refus(chemin, self.depot, self.racines(), self.uid + 1),
            "owner",
        )

    def test_outside_the_allowed_roots_is_refused(self):
        chemin = os.path.join(self.home, "Documents")
        os.makedirs(chemin)
        self.assertEqual(
            sc.refus(chemin, self.depot, self.racines(), self.uid), "outside"
        )

    def test_a_root_itself_is_never_deleted(self):
        self.assertEqual(
            sc.refus(self.tmp, self.depot, self.racines(), self.uid),
            "outside",
        )


class TestLEffacement(Arbre):
    def racines(self):
        return sc.racines_permises(self.depot, self.home, self.tmp, self.data)

    def test_deletes_what_passes_and_reports_what_is_left(self):
        bon = os.path.join(self.depot, "a/__pycache__")
        ecrire(os.path.join(bon, "m.pyc"), octets=8192)
        garde = os.path.join(self.depot, "private/__pycache__")
        ecrire(os.path.join(garde, "m.pyc"))
        cand = sc.Candidat("cache", "__pycache__", [bon, garde])
        liberes, laisses = sc.effacer(
            [cand], self.depot, self.racines(), self.uid
        )
        self.assertFalse(os.path.exists(bon))
        self.assertTrue(os.path.exists(garde))
        self.assertGreaterEqual(liberes, 8192)
        self.assertEqual(laisses, [(garde, "protected")])

    def test_a_filestore_whose_database_reappeared_is_kept(self):
        chemin = os.path.join(self.data, "filestore", "revenue")
        ecrire(os.path.join(chemin, "f"))
        cand = sc.Candidat("filestore", "revenue", [chemin])
        _, laisses = sc.effacer(
            [cand], self.depot, self.racines(), self.uid, bases={"revenue"}
        )
        self.assertTrue(os.path.exists(chemin))
        self.assertEqual(laisses, [(chemin, "database")])

    def test_no_filestore_is_deleted_without_a_fresh_database_list(self):
        chemin = os.path.join(self.data, "filestore", "orpheline")
        ecrire(os.path.join(chemin, "f"))
        cand = sc.Candidat("filestore", "orpheline", [chemin])
        _, laisses = sc.effacer(
            [cand], self.depot, self.racines(), self.uid, bases=None
        )
        self.assertTrue(os.path.exists(chemin))
        self.assertEqual(laisses, [(chemin, "no-database-list")])

    def test_an_orphan_filestore_is_deleted_with_the_list(self):
        chemin = os.path.join(self.data, "filestore", "orpheline")
        ecrire(os.path.join(chemin, "f"))
        cand = sc.Candidat("filestore", "orpheline", [chemin])
        _, laisses = sc.effacer(
            [cand], self.depot, self.racines(), self.uid, bases={"autre"}
        )
        self.assertFalse(os.path.exists(chemin))
        self.assertEqual(laisses, [])


class TestLEnsemble(Arbre):
    def test_largest_first_and_nothing_empty(self):
        ecrire(os.path.join(self.home, ".cache/pip/a"), octets=1000)
        ecrire(os.path.join(self.home, ".npm/_cacache/b"), octets=90000)
        os.makedirs(os.path.join(self.home, ".cache/go-build"))
        trouves = sc.candidats(
            self.depot,
            home=self.home,
            tmp=self.tmp,
            data_dir=self.data,
            bases=set(),
            actif=None,
            uid=self.uid,
        )
        self.assertEqual(
            [c.nom for c in trouves], [".npm/_cacache", ".cache/pip"]
        )


AUCUN_USAGE = (set(), [])


class TestLesAutresCaches(Arbre):
    def test_downloaded_caches_are_unchecked_and_warned(self):
        ecrire(os.path.join(self.home, ".cache/huggingface/hub/m"))
        trouves = sc.caches_telecharges(self.home)
        self.assertEqual(self.noms(trouves), [("cache", ".cache/huggingface")])
        self.assertFalse(trouves[0].coche)
        self.assertEqual(trouves[0].mise_en_garde, "download")

    def test_an_unknown_heavy_cache_is_offered_unchecked(self):
        # Un répertoire et un petit fichier occupent déjà deux blocs : le
        # seuil est au-dessus, le gros fichier le dépasse seul.
        ecrire(os.path.join(self.home, ".cache/outil_x/gros"), octets=65536)
        ecrire(os.path.join(self.home, ".cache/outil_y/petit"), octets=10)
        ecrire(
            os.path.join(self.home, ".cache/pypoetry/virtualenvs/e/f"),
            octets=65536,
        )
        ecrire(os.path.join(self.home, ".cache/pip/a"), octets=65536)
        trouves = sc.caches_inconnus(self.home, AUCUN_USAGE, seuil=32768)
        self.assertEqual(self.noms(trouves), [("unknown", ".cache/outil_x")])
        self.assertFalse(trouves[0].coche)
        self.assertEqual(trouves[0].mise_en_garde, "unknown")

    def test_an_unknown_cache_in_use_is_not_offered(self):
        chemin = os.path.join(self.home, ".cache/outil_x")
        ecrire(os.path.join(chemin, "disque.img"), octets=8192)
        ouvert = ({os.path.join(chemin, "disque.img")}, [])
        nomme = (set(), [f"qemu -drive file={chemin}/disque.img"])
        for utilises in (ouvert, nomme):
            self.assertEqual(
                sc.caches_inconnus(self.home, utilises, seuil=4096), []
            )

    def test_the_trash_is_one_unchecked_entry(self):
        ecrire(os.path.join(self.home, sc.CORBEILLE_REL, "files/a.txt"))
        ecrire(os.path.join(self.home, sc.CORBEILLE_REL, "info/a.trashinfo"))
        trouves = sc.corbeille(self.home)
        self.assertEqual(self.noms(trouves), [("trash", "Trash")])
        self.assertEqual(len(trouves[0].chemins), 2)
        self.assertFalse(trouves[0].coche)

    def test_this_process_is_seen_using_its_cwd(self):
        self.assertTrue(sc.en_usage(os.getcwd(), sc.usages()))


class TestLesDepotsVoisins(Arbre):
    def setUp(self):
        super().setUp()
        self.voisin = os.path.join(os.path.dirname(self.depot), "voisin")
        ecrire(os.path.join(self.voisin, ".erplibre-version"), octets=5)
        for nom in (".venv.erplibre", ".venv.odoo18.0_python3.12.10"):
            ecrire(os.path.join(self.voisin, nom, "bin/python"))
        ecrire(os.path.join(os.path.dirname(self.depot), "autre/.venv.x/f"))
        ecrire(os.path.join(self.depot, ".venv.odoo16.0/bin/python"))

    def test_only_the_venvs_of_other_erplibre_checkouts(self):
        trouves = sc.venvs_voisins(self.depot, AUCUN_USAGE)
        self.assertEqual(
            self.noms(trouves),
            [
                ("venv-other", "voisin/.venv.erplibre"),
                ("venv-other", "voisin/.venv.odoo18.0_python3.12.10"),
            ],
        )
        self.assertFalse(any(c.coche for c in trouves))

    def test_a_venv_in_use_is_not_offered(self):
        venv = os.path.join(self.voisin, ".venv.erplibre")
        utilises = ({os.path.join(venv, "lib/x.so")}, [])
        noms = [c.nom for c in sc.venvs_voisins(self.depot, utilises)]
        self.assertNotIn("voisin/.venv.erplibre", noms)

    def test_a_neighbour_private_directory_is_protected(self):
        racines = sc.racines_permises(
            self.depot, self.home, self.tmp, self.data
        )
        chemin = os.path.join(self.voisin, "private", "x")
        os.makedirs(chemin)
        self.assertEqual(
            sc.refus(chemin, self.depot, racines, self.uid), "protected"
        )
        venv = os.path.join(self.voisin, ".venv.erplibre")
        self.assertIsNone(sc.refus(venv, self.depot, racines, self.uid))


class Reponse:
    def __init__(self, stdout, returncode=0):
        self.stdout = stdout
        self.returncode = returncode


class TestLeRapportDesDepots(unittest.TestCase):
    def test_repositories_heaviest_first_with_their_heavy_children(self):
        sortie = (
            "10\t/g/a/petit\n"
            "900\t/g/a/odoo\n"
            "1000\t/g/a\n"
            "3000\t/g/b/.venv.x\n"
            "3000\t/g/b\n"
            "4000\t/g\n"
        )

        def lanceur(args, **kw):
            return Reponse(sortie if args[0] == "du" else "")

        depots = sc.depots_lourds("/g", lanceur=lanceur, seuil=100)
        self.assertEqual([d["nom"] for d in depots], ["b", "a"])
        self.assertEqual(depots[1]["enfants"], [("odoo", 900)])
        self.assertIsNone(depots[0]["commit"])

    def test_a_failing_du_gives_none(self):
        def lanceur(args, **kw):
            raise OSError

        self.assertIsNone(sc.depots_lourds("/g", lanceur=lanceur))


class TestLesCachesDuSysteme(Arbre):
    def test_present_tools_only_and_the_journal_above_its_floor(self):
        pkg = os.path.join(self.tmp, "pkg")
        ecrire(os.path.join(pkg, "p.tar.zst"))
        journal = os.path.join(self.tmp, "journal")
        ecrire(os.path.join(journal, "j"))
        caches = (
            ("pacman", pkg, "pacman", ["sudo", "pacman", "-Sc"]),
            ("apt", pkg, "apt-get", ["sudo", "apt-get", "clean"]),
            ("journal", journal, "journalctl", ["sudo", "journalctl"]),
        )
        trouves = sc.caches_systeme(
            caches, which=lambda b: None if b == "apt-get" else b
        )
        self.assertEqual([c["nom"] for c in trouves], ["pacman"])
        self.assertEqual(trouves[0]["commande"][0], "sudo")


if __name__ == "__main__":
    unittest.main()
