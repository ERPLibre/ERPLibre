#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'espace à récupérer : ce qui est proposé, et surtout ce qui ne l'est pas.

Chaque cas bâtit un arbre jetable — un $HOME, un /tmp, un data_dir d'Odoo et
un dépôt, tous sous un répertoire temporaire : rien du poste n'est lu ni
effacé. Les processus (usages) et les points de montage (montages) du poste
sont remplacés par des ensembles vides ; un test qui en a besoin les
fabrique.
"""

import os
import subprocess
import tempfile
import time
import unittest
from unittest import mock

from script.todo import system_cleanup as sc

VIEUX = time.time() - 10 * 86400

# La vraie lecture des processus, avant que Arbre ne la remplace : les tests
# qui fabriquent un /proc l'appellent sur lui.
USAGES = sc.usages


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
        vrai_montages = sc.montages
        for patch in (
            mock.patch.object(sc, "usages", return_value=(set(), [])),
            mock.patch.object(
                sc,
                "montages",
                side_effect=lambda chemin=None: (
                    set() if chemin is None else vrai_montages(chemin)
                ),
            ),
        ):
            patch.start()
            self.addCleanup(patch.stop)

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
        """Le seul cas qui lit le vrai /proc : ce processus s'y voit."""
        self.assertTrue(sc.en_usage(os.getcwd(), USAGES()))


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


class TestLesMontages(Arbre):
    """Un point de montage sur ou sous un candidat : rmtree effacerait le
    système de fichiers monté. Les points sont fabriqués."""

    def racines(self):
        return sc.racines_permises(self.depot, self.home, self.tmp, self.data)

    def test_mountinfo_points_are_unescaped(self):
        chemin = os.path.join(self.home, "mountinfo")
        with open(chemin, "w") as fh:
            fh.write(
                "36 35 98:0 / /mnt/a\\040b rw - ext4 /dev/x rw\n"
                "37 35 0:5 / /tmp/tmp.abc rw - fuse.sshfs h:/ rw\n"
            )
        self.assertEqual(sc.montages(chemin), {"/mnt/a b", "/tmp/tmp.abc"})

    def test_a_mount_on_or_under_a_path_is_refused(self):
        chemin = os.path.join(self.tmp, "tmp.abc")
        os.makedirs(os.path.join(chemin, "mnt"))
        for point in (chemin, os.path.join(chemin, "mnt")):
            self.assertEqual(
                sc.refus(
                    chemin, self.depot, self.racines(), self.uid, {point}
                ),
                "mount",
            )
        self.assertIsNone(
            sc.refus(
                chemin,
                self.depot,
                self.racines(),
                self.uid,
                {os.path.join(self.tmp, "tmp.abcd")},
            )
        )

    def test_a_mounted_tmp_entry_is_never_measured_nor_offered(self):
        chemin = os.path.join(self.tmp, "tmp.abc")
        ecrire(os.path.join(chemin, "distant"))
        vieillir(chemin)
        with mock.patch.object(sc, "mesurer") as mesure:
            trouves = sc.restes_tmp(self.tmp, self.uid, 2, points={chemin})
        self.assertEqual(trouves, [])
        mesure.assert_not_called()

    def test_deletion_rereads_the_mounts(self):
        chemin = os.path.join(self.tmp, "tmp.abc")
        ecrire(os.path.join(chemin, "distant"))
        cand = sc.Candidat("tmp", "tmp.abc", [chemin])
        with mock.patch.object(sc, "montages", return_value={chemin}):
            liberes, laisses = sc.effacer(
                [cand],
                self.depot,
                self.racines(),
                self.uid,
                utilises=(set(), []),
            )
        self.assertTrue(os.path.exists(os.path.join(chemin, "distant")))
        self.assertEqual((liberes, laisses), (0, [(chemin, "mount")]))

    def test_an_sshfs_file_is_a_leftover_and_an_unreadable_one_no_crash(self):
        journal = os.path.join(self.tmp, "sshfs_debug.log")
        ecrire(journal, date=VIEUX)
        illisible = os.path.join(self.tmp, "sshfs_ferme")
        os.makedirs(illisible)
        os.chmod(illisible, 0)
        self.addCleanup(os.chmod, illisible, 0o700)
        trouves = sc.restes_tmp(self.tmp, self.uid, 2, points=set())
        noms = [c.nom for c in trouves]
        self.assertIn("sshfs_debug.log", noms)
        if os.geteuid() != 0:
            self.assertNotIn("sshfs_ferme", noms)


class TestLUsage(Arbre):
    def faux_proc(self, cwd, cmdline, environ=b""):
        proc = os.path.join(self.home, "proc")
        base = os.path.join(proc, "4242")
        os.makedirs(base)
        os.symlink(cwd, os.path.join(base, "cwd"))
        with open(os.path.join(base, "cmdline"), "wb") as fh:
            fh.write(b"\0".join(a.encode() for a in cmdline) + b"\0")
        with open(os.path.join(base, "environ"), "wb") as fh:
            fh.write(environ)
        return proc

    def test_a_venv_run_by_a_relative_path_is_in_use(self):
        venv = os.path.join(self.depot, ".venv.erplibre")
        os.makedirs(venv)
        proc = self.faux_proc(
            self.depot, ["./.venv.erplibre/bin/python", "script/todo/todo.py"]
        )
        utilises = USAGES(self.uid, proc)
        self.assertTrue(sc.en_usage(venv, utilises))
        self.assertFalse(
            sc.en_usage(os.path.join(self.depot, ".venv.odoo18"), utilises)
        )

    def test_virtual_env_marks_the_venv_in_use(self):
        venv = os.path.join(self.depot, ".venv.odoo18")
        os.makedirs(venv)
        proc = self.faux_proc(
            self.home, ["python"], environ=f"VIRTUAL_ENV={venv}\0".encode()
        )
        self.assertTrue(sc.en_usage(venv, USAGES(self.uid, proc)))

    def test_tmp_leftovers_and_venvs_in_use_are_not_offered(self):
        reste = os.path.join(self.tmp, "tmpold")
        ecrire(os.path.join(reste, "f"))
        vieillir(reste)
        venv = os.path.join(self.depot, ".venv.odoo16.0_python3.10.0")
        ecrire(os.path.join(venv, "f"))
        utilises = ({reste, os.path.join(venv, "bin/python")}, [])
        self.assertEqual(
            sc.restes_tmp(self.tmp, self.uid, 2, utilises, points=set()), []
        )
        self.assertEqual(
            sc.venvs(self.depot, ".venv.odoo18.0_python3.12.0", utilises), []
        )

    def test_no_venv_offered_without_the_active_one(self):
        ecrire(os.path.join(self.depot, ".venv.odoo16.0_python3.10.0", "f"))
        self.assertEqual(sc.venvs(self.depot, None), [])

    def test_deletion_rereads_who_uses_it(self):
        reste = os.path.join(self.tmp, "tmpold")
        ecrire(os.path.join(reste, "f"))
        cand = sc.Candidat("tmp", "tmpold", [reste])
        racines = sc.racines_permises(
            self.depot, self.home, self.tmp, self.data
        )
        _, laisses = sc.effacer(
            [cand], self.depot, racines, self.uid, utilises=({reste}, [])
        )
        self.assertTrue(os.path.exists(reste))
        self.assertEqual(laisses, [(reste, "in-use")])


class TestLesLiens(Arbre):
    def test_a_linked_cache_dir_is_offered_by_its_real_path(self):
        ailleurs = os.path.join(self.data, "cache-reel")
        ecrire(os.path.join(ailleurs, "pip", "a"))
        os.symlink(ailleurs, os.path.join(self.home, ".cache"))
        trouves = sc.caches(self.depot, self.home)
        pip = next(c for c in trouves if c.nom == ".cache/pip")
        self.assertEqual(
            pip.chemins, [os.path.join(os.path.realpath(ailleurs), "pip")]
        )
        racines = sc.racines_permises(
            self.depot, self.home, self.tmp, self.data
        )
        self.assertIsNone(
            sc.refus(pip.chemins[0], self.depot, racines, self.uid, set())
        )

    def test_a_trashed_link_goes_as_a_link_with_its_trashinfo(self):
        cible = os.path.join(self.data, "cible")
        ecrire(os.path.join(cible, "garde"))
        corbeille = os.path.join(self.home, sc.CORBEILLE_REL)
        os.makedirs(os.path.join(corbeille, "files"))
        os.symlink(cible, os.path.join(corbeille, "files", "lien"))
        ecrire(os.path.join(corbeille, "info", "lien.trashinfo"), octets=10)
        trouves = sc.corbeille(self.home)
        racines = sc.racines_permises(
            self.depot, self.home, self.tmp, self.data
        )
        _, laisses = sc.effacer(trouves, self.depot, racines, self.uid)
        self.assertEqual(laisses, [])
        self.assertFalse(
            os.path.lexists(os.path.join(corbeille, "files", "lien"))
        )
        self.assertTrue(os.path.exists(os.path.join(cible, "garde")))

    def test_a_link_leaf_outside_the_trash_stays_refused(self):
        os.makedirs(os.path.join(self.data, "cible"))
        lien = os.path.join(self.tmp, "tmplien")
        os.symlink(os.path.join(self.data, "cible"), lien)
        racines = sc.racines_permises(
            self.depot, self.home, self.tmp, self.data
        )
        self.assertEqual(
            sc.refus(lien, self.depot, racines, self.uid, set()), "link"
        )


class TestLesLiensDurs(Arbre):
    def test_a_file_shared_with_outside_frees_nothing(self):
        cache = os.path.join(self.home, ".cache/uv")
        ecrire(os.path.join(cache, "lib.so"), octets=65536)
        os.makedirs(os.path.join(self.depot, ".venv"))
        os.link(
            os.path.join(cache, "lib.so"),
            os.path.join(self.depot, ".venv", "lib.so"),
        )
        seul, _ = sc.mesurer(os.path.join(self.home, ".cache"))
        ensemble, _ = sc.mesurer(os.path.dirname(self.home))
        self.assertLess(seul, 65536)
        self.assertGreaterEqual(ensemble, 65536)


class TestLesFilestoresPartages(Arbre):
    def voisin(self, nom, data_dir):
        depot = os.path.join(os.path.dirname(self.depot), nom)
        ecrire(os.path.join(depot, ".erplibre-version"), octets=4)
        with open(os.path.join(depot, "config.conf"), "w") as fh:
            fh.write("[options]\n")
            if data_dir is not None:
                fh.write(f"data_dir = {data_dir}\n")
        return os.path.join(depot, "config.conf")

    def lire(self, chemin):
        import configparser

        p = configparser.RawConfigParser()
        p.read(chemin)
        return dict(p.items("options"))

    def test_every_checkout_writing_the_same_data_dir_counts(self):
        meme = self.voisin("meme", self.data)
        self.voisin("autre", os.path.join(self.home, "ailleurs"))
        defaut = self.voisin("defaut", None)
        self.assertEqual(
            sc.configs_partageant(self.depot, self.data, self.lire),
            [None, meme],
        )
        with mock.patch.object(sc, "DATA_DIR_ODOO", self.data):
            self.assertEqual(
                sc.configs_partageant(self.depot, self.data, self.lire),
                [None, defaut, meme],
            )


class TestLesRapports(Arbre):
    def test_heavy_dirs_when_the_checkout_sits_at_the_root(self):
        sortie = "4096\t/ERPLibre/addons\n8192\t/ERPLibre\n9999\t/\n"

        def lanceur(args, **kw):
            return subprocess.CompletedProcess(args, 0, sortie, "")

        depots = sc.depots_lourds("/", lanceur=lanceur, seuil=1)
        self.assertEqual([d["nom"] for d in depots], ["ERPLibre"])
        self.assertEqual(depots[0]["enfants"], [("addons", 4096)])

    def test_dnf5_cleans_its_own_cache(self):
        dnf5 = os.path.join(self.home, "dnf5")
        ecrire(dnf5, octets=4)
        lien = os.path.join(self.home, "dnf")
        os.symlink(dnf5, lien)
        self.assertEqual(sc.cache_dnf(lien, "/var/cache/dnf"), sc.CACHE_DNF5)
        ecrire(os.path.join(self.home, "dnf-3"), octets=4)
        self.assertEqual(
            sc.cache_dnf(os.path.join(self.home, "dnf-3"), "/var/cache/dnf"),
            "/var/cache/dnf",
        )


class TestLesRetoursDeVerification(Arbre):
    def test_a_non_utf8_mount_point_still_matches_the_candidate(self):
        chemin = os.path.join(self.home, "mountinfo")
        with open(chemin, "wb") as fh:
            fh.write(b"37 35 0:5 / /tmp/tmp\xff/mnt rw - fuse.sshfs h:/ rw\n")
        points = sc.montages(chemin)
        candidat = os.fsdecode(b"/tmp/tmp\xff")
        self.assertTrue(sc.porte_un_montage(candidat, points))

    def test_a_mounted_tmp_entry_is_never_stat_ed(self):
        chemin = os.path.join(self.tmp, "sshfs_mort")
        os.makedirs(chemin)
        vrai = os.lstat

        def lstat(c, *a, **k):
            if c == chemin:
                raise AssertionError("stat sur un montage")
            return vrai(c, *a, **k)

        with mock.patch.object(sc.os, "lstat", side_effect=lstat):
            self.assertEqual(
                sc.restes_tmp(self.tmp, self.uid, 0, points={chemin}), []
            )

    def faux_proc(self, cwd, cmdline, environ):
        proc = os.path.join(self.home, "proc")
        base = os.path.join(proc, "4242")
        os.makedirs(base)
        os.symlink(cwd, os.path.join(base, "cwd"))
        with open(os.path.join(base, "cmdline"), "wb") as fh:
            fh.write(b"\0".join(a.encode() for a in cmdline) + b"\0")
        with open(os.path.join(base, "environ"), "wb") as fh:
            fh.write(environ)
        return proc

    def test_a_relative_venv_is_in_use_after_the_process_changed_dir(self):
        venv = os.path.join(self.depot, ".venv.erplibre")
        os.makedirs(venv)
        proc = self.faux_proc(
            "/",
            ["./.venv.erplibre/bin/python", "-c", "pass"],
            f"PWD={self.depot}\0".encode(),
        )
        self.assertTrue(sc.en_usage(venv, USAGES(self.uid, proc)))

    def test_a_venv_on_the_path_is_in_use(self):
        venv = os.path.join(self.depot, ".venv.odoo18")
        ecrire(os.path.join(venv, "pyvenv.cfg"), octets=10)
        proc = self.faux_proc(
            self.home,
            ["python", "-c", "pass"],
            f"PATH={venv}/bin:/usr/bin\0".encode(),
        )
        self.assertTrue(sc.en_usage(venv, USAGES(self.uid, proc)))

    def test_unknown_caches_under_a_linked_cache_dir_are_offered(self):
        ailleurs = os.path.join(self.data, "cache-reel")
        ecrire(os.path.join(ailleurs, "inconnu", "gros"), octets=8192)
        os.symlink(ailleurs, os.path.join(self.home, ".cache"))
        trouves = sc.caches_inconnus(self.home, (set(), []), seuil=1)
        self.assertEqual(
            [c.chemins for c in trouves],
            [[os.path.join(os.path.realpath(ailleurs), "inconnu")]],
        )

    @unittest.skipIf(os.geteuid() == 0, "root liste tout")
    def test_an_unreadable_neighbour_or_filestore_does_not_crash(self):
        voisin = os.path.join(os.path.dirname(self.depot), "voisin")
        ecrire(os.path.join(voisin, ".erplibre-version"), octets=4)
        os.chmod(voisin, 0o311)
        self.addCleanup(os.chmod, voisin, 0o755)
        filestore = os.path.join(self.data, "filestore")
        os.makedirs(filestore)
        os.chmod(filestore, 0)
        self.addCleanup(os.chmod, filestore, 0o755)
        self.assertEqual(sc.venvs_voisins(self.depot, (set(), [])), [])
        self.assertEqual(sc.odoo(self.data, {"a"}, 2), [])

    def test_system_caches_without_sudo_or_as_root(self):
        os.makedirs(os.path.join(self.tmp, "pkg"))
        caches = (
            (
                "pacman",
                os.path.join(self.tmp, "pkg"),
                "pacman",
                ["sudo", "pacman", "-Sc"],
            ),
        )
        sans_sudo = lambda b: None if b == "sudo" else f"/usr/bin/{b}"
        self.assertEqual(
            sc.caches_systeme(caches, which=sans_sudo, euid=lambda: 1000), []
        )
        en_root = sc.caches_systeme(caches, which=sans_sudo, euid=lambda: 0)
        self.assertEqual(en_root[0]["commande"], ["pacman", "-Sc"])


if __name__ == "__main__":
    unittest.main()
