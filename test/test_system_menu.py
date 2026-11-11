#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu Système : le diagnostic et son rapport, le choix de l'espace à
récupérer, au formulaire comme en ligne.

Les faits du poste sont fabriqués : un test ne dépend ni du matériel ni des
commandes installées là où il tourne.
"""

import asyncio
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import system_cleanup as sc  # noqa: E402
from script.todo import system_diagnostic as sd  # noqa: E402
from script.todo import system_menu as sm  # noqa: E402
from script.todo import todo_i18n  # noqa: E402


def setUpModule():
    ancienne = todo_i18n._current_lang
    todo_i18n._current_lang = "fr"
    unittest.addModuleCleanup(setattr, todo_i18n, "_current_lang", ancienne)


class TestLesSourcesAbsentes(unittest.TestCase):
    def test_a_missing_command_gives_none(self):
        with mock.patch.object(sd.shutil, "which", return_value=None):
            self.assertIsNone(sd.commande(["hostnamectl"]))
            self.assertIsNone(sd.cartes_graphiques())

    def test_identity_falls_back_without_hostnamectl(self):
        with (
            mock.patch.object(sd, "commande", return_value=None),
            mock.patch.object(sd, "lire", return_value=None),
        ):
            ident = sd.identite()
        self.assertTrue(ident["kernel"])
        self.assertIsNone(ident["vendor"])

    def test_every_missing_fact_reads_unavailable(self):
        texte = "\n".join(sm.lignes_diagnostic(faits_absents()))
        self.assertIn("indisponible", texte)
        self.assertIn("lspci non installé", texte)
        self.assertNotIn("None", texte)

    def test_physical_machine_reads_none_not_unavailable(self):
        """systemd-detect-virt répond « none » avec le code 1."""

        def commande(args, timeout=5, codes_ok=(0,)):
            if args[0] == "systemd-detect-virt" and 1 in codes_ok:
                return "none\n"
            return None

        with (
            mock.patch.object(sd, "commande", side_effect=commande),
            mock.patch.object(sd, "lire", return_value=None),
        ):
            self.assertEqual(sd.identite()["virtualization"], "none")


def faits_absents():
    """Un diagnostic où chaque source manque."""
    return {
        "identity": dict.fromkeys(
            (
                "hostname",
                "os",
                "kernel",
                "architecture",
                "chassis",
                "virtualization",
                "vendor",
                "model",
            )
        ),
        "cpu": {"model": None, "logical": None, "physical": None},
        "memory": dict.fromkeys(
            ("total", "available", "swap_total", "swap_free")
        ),
        "gpu": None,
        "partitions": [],
        "load": {"load": None, "uptime": None},
        "erplibre": {
            "erplibre": None,
            "odoo": None,
            "python": None,
            "active_venv": None,
            "venvs": [],
        },
    }


class TestLesFichiersDuSysteme(unittest.TestCase):
    def fichier(self, contenu):
        with tempfile.NamedTemporaryFile(
            "w", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(contenu)
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_meminfo_in_bytes(self):
        chemin = self.fichier(
            "MemTotal:       2048 kB\nMemAvailable:   1024 kB\n"
            "SwapTotal:         0 kB\nSwapFree:          0 kB\n"
        )
        mem = sd.memoire(chemin)
        self.assertEqual(mem["total"], 2048 * 1024)
        self.assertEqual(mem["available"], 1024 * 1024)

    def test_only_data_filesystems_and_the_repo_marked(self):
        racine = tempfile.mkdtemp()
        self.addCleanup(os.rmdir, racine)
        mounts = self.fichier(
            "proc /proc proc rw 0 0\n"
            "tmpfs /run tmpfs rw 0 0\n"
            "/dev/sda1 / ext4 rw 0 0\n"
        )
        parts = sd.partitions(racine, mounts)
        self.assertEqual([p["mountpoint"] for p in parts], ["/"])
        self.assertTrue(parts[0]["repo"])

    def repertoires(self, *noms):
        base = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, base)
        chemins = []
        for nom in noms:
            chemin = os.path.join(base, nom)
            os.makedirs(chemin)
            chemins.append(chemin)
        return base, chemins

    def test_one_line_per_device_and_escapes_decoded(self):
        base, (racine, home, espace) = self.repertoires(
            "racine", "home", "a b"
        )
        mounts = self.fichier(
            f"/dev/sda1 {racine} btrfs rw 0 0\n"
            f"/dev/sda1 {home} btrfs rw 0 0\n"
            f"/dev/sdb1 {base}/a\\040b ext4 rw 0 0\n"
        )
        parts = sd.partitions(home, mounts)
        par_appareil = {p["device"]: p for p in parts}
        self.assertEqual(len(parts), 2)
        self.assertEqual(par_appareil["/dev/sda1"]["mountpoint"], home)
        self.assertEqual(par_appareil["/dev/sda1"]["others"], [racine])
        self.assertTrue(par_appareil["/dev/sda1"]["repo"])
        self.assertEqual(par_appareil["/dev/sdb1"]["mountpoint"], espace)

    def test_a_mounted_file_is_not_a_disk(self):
        base, (racine,) = self.repertoires("racine")
        fichier = os.path.join(base, "hosts")
        open(fichier, "w").close()
        mounts = self.fichier(
            f"/dev/sda1 {racine} ext4 rw 0 0\n/dev/sda1 {fichier} ext4 rw 0 0\n"
        )
        parts = sd.partitions(racine, mounts)
        self.assertEqual(parts[0]["others"], [])

    def test_a_repo_on_a_network_share_marks_the_share_not_its_parent(self):
        base, (parent,) = self.repertoires("srv")
        partage = os.path.join(parent, "nfs")
        os.makedirs(os.path.join(partage, "repo"))
        mounts = self.fichier(
            f"/dev/sda1 {parent} ext4 rw 0 0\n"
            f"hote:/x {partage} nfs4 rw 0 0\n"
        )
        parts = sd.partitions(os.path.join(partage, "repo"), mounts)
        marquee = [p for p in parts if p["repo"]]
        self.assertEqual([p["mountpoint"] for p in marquee], [partage])
        self.assertEqual(marquee[0]["fstype"], "nfs4")

    def test_the_last_line_of_a_mount_point_wins(self):
        base, (racine,) = self.repertoires("racine")
        mounts = self.fichier(
            f"/dev/sda1 {racine} ext4 rw 0 0\n/dev/sdc1 {racine} xfs rw 0 0\n"
        )
        parts = sd.partitions(racine, mounts)
        self.assertEqual([p["device"] for p in parts], ["/dev/sdc1"])


class TestLeChoixEnLigne(unittest.TestCase):
    def candidats(self):
        return [
            sc.Candidat("cache", ".cache/pip", ["/a"], 3000, coche=True),
            sc.Candidat("filestore", "orpheline", ["/b"], 2000),
            sc.Candidat(
                "venv", ".venv.odoo16", ["/c"], 1000, mise_en_garde="reinstall"
            ),
        ]

    def choisir(self, reponse):
        with (
            mock.patch("builtins.input", return_value=reponse),
            mock.patch("builtins.print"),
        ):
            return sm.choisir_en_ligne(self.candidats())

    def test_enter_takes_the_checked_ones(self):
        self.assertEqual(self.choisir(""), [0])

    def test_numbers_pick_those_ones(self):
        self.assertEqual(self.choisir("2, 3"), [1, 2])

    def test_out_of_range_numbers_are_ignored(self):
        self.assertEqual(self.choisir("0,4,2"), [1])

    def test_c_cancels(self):
        self.assertIsNone(self.choisir("c"))

    def test_the_label_says_size_category_and_warning(self):
        ligne = sm.libelle(self.candidats()[2])
        self.assertIn("1000 o", ligne)
        self.assertIn("Venv d'une autre version d'Odoo", ligne)
        self.assertIn("réinstaller", ligne)


class TestLeFormulaire(unittest.TestCase):
    def test_the_checked_boxes_are_returned(self):
        candidats = [
            sc.Candidat("cache", ".cache/pip", ["/a"], 3000, coche=True),
            sc.Candidat("filestore", "orpheline", ["/b"], 2000),
        ]
        app = sm.formulaire(candidats)
        if app is None:
            self.skipTest("Textual absent")
        vu = {}

        async def scenario():
            from textual.widgets import SelectionList

            async with app.run_test(size=(120, 20)) as pilote:
                await pilote.pause()
                liste = app.query_one(SelectionList)
                vu["avant"] = list(liste.selected)
                liste.select(1)
                await pilote.click("#effacer")
                await pilote.pause()
            vu["rendu"] = app.return_value

        asyncio.run(scenario())
        self.assertEqual(vu["avant"], [0])
        self.assertEqual(sorted(vu["rendu"]), [0, 1])

    def test_cancel_returns_none(self):
        app = sm.formulaire(
            [sc.Candidat("cache", ".cache/pip", ["/a"], 3000, coche=True)]
        )
        if app is None:
            self.skipTest("Textual absent")

        async def scenario():
            async with app.run_test(size=(120, 20)) as pilote:
                await pilote.pause()
                await pilote.click("#annuler")
                await pilote.pause()

        asyncio.run(scenario())
        self.assertIsNone(app.return_value)


class TestLeRapport(unittest.TestCase):
    def test_the_report_lands_in_private_diagnostic(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        ancien = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with (
                    mock.patch.object(
                        sd, "collecter", return_value=faits_absents()
                    ),
                    mock.patch("builtins.input", return_value="o"),
                    mock.patch("builtins.print"),
                ):
                    todo._system_diagnostic()
                fichiers = os.listdir(
                    os.path.join(tmp, "private", "diagnostic")
                )
                with open(
                    os.path.join(tmp, "private", "diagnostic", fichiers[0]),
                    encoding="utf-8",
                ) as fh:
                    contenu = fh.read()
            finally:
                os.chdir(ancien)
        self.assertEqual(len(fichiers), 1)
        self.assertTrue(fichiers[0].endswith(".txt"))
        self.assertIn("Identité", contenu)

    def test_no_report_without_a_yes(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        ancien = os.getcwd()
        with tempfile.TemporaryDirectory() as tmp:
            os.chdir(tmp)
            try:
                with (
                    mock.patch.object(
                        sd, "collecter", return_value=faits_absents()
                    ),
                    mock.patch("builtins.input", return_value=""),
                    mock.patch("builtins.print"),
                ):
                    todo._system_diagnostic()
                existe = os.path.exists(os.path.join(tmp, "private"))
            finally:
                os.chdir(ancien)
        self.assertFalse(existe)


class TestLesLibelles(unittest.TestCase):
    def test_every_category_warning_and_reason_is_translated(self):
        for cle in (
            list(sm.LIBELLES_CATEGORIE.values())
            + list(sm.MISES_EN_GARDE.values())
            + list(sm.RAISONS.values())
        ):
            self.assertIn(cle, todo_i18n.TRANSLATIONS, cle)


class TestLesCachesSudo(unittest.TestCase):
    def lancer(self, reponses):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        todo.execute = mock.Mock()
        caches = [
            {
                "nom": "pacman",
                "chemin": "/nulle/part",
                "taille": 2048,
                "commande": ["sudo", "pacman", "-Sc", "--noconfirm"],
            }
        ]
        with (
            mock.patch.object(sc, "caches_systeme", return_value=caches),
            mock.patch("builtins.input", side_effect=reponses),
            mock.patch("builtins.print"),
        ):
            todo._system_caches_sudo()
        return todo.execute.exec_command_live.call_args_list

    def test_nothing_runs_without_a_yes(self):
        self.assertEqual(self.lancer(["1", "n"]), [])
        self.assertEqual(self.lancer([""]), [])

    def test_the_chosen_command_runs_after_a_yes(self):
        appels = self.lancer(["1", "o"])
        self.assertEqual(len(appels), 1)
        self.assertEqual(appels[0].args[0], "sudo pacman -Sc --noconfirm")


class TestLEspaceARecuperer(unittest.TestCase):
    """Le menu autour d'effacer() : rien sans oui, et la liste des bases
    RELUE au moment d'effacer, non celle de la recherche."""

    def lancer(self, reponse, bases=({"a"}, {"a", "orpheline"})):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        cand = sc.Candidat("filestore", "orpheline", ["/x/orpheline"], 10)
        lectures = list(bases)
        with (
            mock.patch.object(TODO, "_system_data_dir", return_value="/x"),
            mock.patch.object(
                TODO,
                "_system_bases_partagees",
                side_effect=lambda d: lectures.pop(0),
            ),
            mock.patch.object(sc, "candidats", return_value=[cand]),
            mock.patch.object(sm, "choisir_en_ligne", return_value=[0]),
            mock.patch.object(sm.sys.stdin, "isatty", return_value=False),
            mock.patch.object(sc, "effacer", return_value=(0, [])) as effacer,
            mock.patch("builtins.input", return_value=reponse),
            mock.patch("builtins.print"),
            mock.patch.dict(sm.os.environ, {}, clear=False),
        ):
            sm.os.environ.pop("PGHOST", None)
            sm.os.environ.pop("PGPORT", None)
            todo._system_espace()
        return effacer

    def test_nothing_is_deleted_without_a_yes(self):
        self.lancer("").assert_not_called()
        self.lancer("n").assert_not_called()

    def test_an_empty_version_file_offers_no_current_venv(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        tmp = tempfile.mkdtemp()
        self.addCleanup(__import__("shutil").rmtree, tmp)
        open(os.path.join(tmp, ".erplibre-version"), "w").close()
        ancien = os.getcwd()
        os.chdir(tmp)
        try:
            with (
                mock.patch.object(TODO, "_system_data_dir", return_value=None),
                mock.patch.object(sc, "candidats", return_value=[]) as cands,
                mock.patch("builtins.print"),
            ):
                todo._system_espace()
        finally:
            os.chdir(ancien)
        self.assertIsNone(cands.call_args.kwargs["actif"])

    def messages(self, data_dir, environ, bases={"a"}):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        vus = []
        with (
            mock.patch.object(TODO, "_system_data_dir", return_value=data_dir),
            mock.patch.object(
                TODO, "_system_bases_partagees", return_value=bases
            ) as lu,
            mock.patch.dict(sm.os.environ, environ, clear=False),
            mock.patch.object(sc, "candidats", return_value=[]) as cands,
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: vus.append(" ".join(map(str, a))),
            ),
        ):
            for v in ("PGHOST", "PGPORT"):
                if v not in environ:
                    sm.os.environ.pop(v, None)
            todo._system_espace()
        return "\n".join(vus), lu.called, cands.call_args.kwargs["bases"]

    def test_no_data_dir_is_not_called_unreachable(self):
        texte, lu, bases = self.messages(None, {})
        self.assertIn("Aucun data_dir", texte)
        self.assertNotIn("injoignable", texte)
        self.assertFalse(lu)
        self.assertIsNone(bases)

    def test_an_exported_pgport_proposes_no_filestore(self):
        texte, lu, bases = self.messages("/d", {"PGPORT": "5499"})
        self.assertIn("PGPORT", texte)
        self.assertFalse(lu)
        self.assertIsNone(bases)

    def test_the_database_list_is_read_again_before_deleting(self):
        effacer = self.lancer("o")
        effacer.assert_called_once()
        self.assertEqual(effacer.call_args.kwargs["bases"], {"a", "orpheline"})


class TestLesBasesPartagees(unittest.TestCase):
    def lancer(self, configs, reponses):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        options = {
            None: {"db_port": "5432"},
            "/v/a/config.conf": {"db_port": "5433"},
            "/v/b/config.conf": {"db_port": "5432"},
        }
        from script.analyse import lib_analyse

        with (
            mock.patch.object(sc, "configs_partageant", return_value=configs),
            mock.patch.object(
                lib_analyse, "read_config", side_effect=lambda c: options[c]
            ),
            mock.patch.object(
                TODO, "_system_bases", side_effect=lambda c: reponses[c]
            ) as lu,
        ):
            return todo._system_bases_partagees("/d"), lu.call_count

    def test_union_over_clusters_each_asked_once(self):
        bases, appels = self.lancer(
            [None, "/v/a/config.conf", "/v/b/config.conf"],
            {None: {"x"}, "/v/a/config.conf": {"y"}},
        )
        self.assertEqual(bases, {"x", "y"})
        self.assertEqual(appels, 2)

    def test_one_unreachable_cluster_proposes_no_filestore(self):
        bases, _ = self.lancer(
            [None, "/v/a/config.conf"], {None: {"x"}, "/v/a/config.conf": None}
        )
        self.assertIsNone(bases)


class TestLesCachesSudoEchouent(unittest.TestCase):
    def test_a_failed_command_is_not_reported_as_done(self):
        from script.todo.todo import TODO

        todo = TODO.__new__(TODO)
        todo.execute = mock.Mock()
        todo.execute.exec_command_live.return_value = 1
        caches = [
            {
                "nom": "pacman",
                "chemin": "/nulle/part",
                "taille": 2048,
                "commande": ["sudo", "pacman", "-Sc", "--noconfirm"],
            }
        ]
        vus = []
        with (
            mock.patch.object(sc, "caches_systeme", return_value=caches),
            mock.patch("builtins.input", side_effect=["1", "o"]),
            mock.patch(
                "builtins.print",
                side_effect=lambda *a, **k: vus.append(" ".join(map(str, a))),
            ),
        ):
            todo._system_caches_sudo()
        self.assertTrue(any("⚠ pacman" in v for v in vus))
        self.assertFalse(any("✓ pacman" in v for v in vus))


if __name__ == "__main__":
    unittest.main()
