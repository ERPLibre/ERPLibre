#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""streamdeck_games_to_repo.sh : un clone ordinaire des jeux Stream Deck,
que repo sync refuse (« .git: unsupported checkout state »), est mis de
côté avant la synchronisation.

Chaque test pose une racine temporaire : un dépôt de jeux local, étiqueté,
cloné par git dans script/stream_deck/games/, et un faux repo dont
« list -p --all » nomme, ou non, ce chemin, comme le vrai selon les
groupes de l'init. repo lui-même n'est pas lancé.

Ce que ces tests gardent :

- un clone sans travail local visible est déplacé, entier, vers
  games.plain-clone-<date>/, et games/ ne garde qu'une copie de save/ ;
  rien n'est supprimé, pas même ce que les vérifications ne voient pas ;
- un clone avec une modification, un fichier non suivi (même sous
  status.showUntrackedFiles=no), un commit sur aucun remote, une remise ou
  un worktree lié reste en place, et le script sort en 1 en nommant la
  raison ;
- un .git en fichier qui ne pointe pas dans .repo/ (worktree lié,
  --separate-git-dir) retient le clone ;
- un games/ extrait par repo (.git en lien, ancienne disposition, ou
  fichier vers .repo/) que l'init n'extrait plus, et que repo sync va donc
  supprimer, voit ses sauvegardes copiées dans games.save-<date>/ ;
- sans games/, sans repo prêt, ou quand repo n'extrait pas les jeux, rien
  ne change ;
- chaque script update_manifest_*.sh le lance après repo init et juste
  avant repo sync, et l'init de code_generator garde le groupe streamdeck.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/manifest/streamdeck_games_to_repo.sh"
JEUX = "script/stream_deck/games"
IDENTITE = ["-c", "user.name=Test", "-c", "user.email=test@example.invalid"]


def git(depot, *args, env=None):
    return subprocess.run(
        ["git", "-C", str(depot), *IDENTITE, *args],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    ).stdout


@unittest.skipUnless(shutil.which("git"), "git absent")
class LeScript(unittest.TestCase):
    def setUp(self):
        dossier = tempfile.TemporaryDirectory()
        self.addCleanup(dossier.cleanup)
        self.tmp = Path(dossier.name)
        source = self.tmp / "jeux.git"
        source.mkdir()
        git(source, "init", "-q")
        (source / ".gitignore").write_text(
            "__pycache__/\n*.log\nsave/*\n!save/.gitkeep\n"
        )
        (source / "save").mkdir()
        (source / "save/.gitkeep").write_text("")
        (source / "games_cli.py").write_text("import argparse\n")
        git(source, "add", "-A")
        git(source, "commit", "-q", "-m", "un")
        git(source, "tag", "v9.9.9")
        self.racine = self.tmp / "erplibre"
        self.jeux = self.racine / JEUX
        self.jeux.parent.mkdir(parents=True)
        git(self.tmp, "clone", "-q", str(source), str(self.jeux))
        git(
            self.jeux,
            "-c",
            "advice.detachedHead=false",
            "checkout",
            "-q",
            "v9.9.9",
        )
        (self.jeux / "save/partie.json").write_text("{}")
        (self.jeux / "__pycache__").mkdir()
        (self.jeux / "__pycache__/games_cli.pyc").write_text("")
        self.faux_repo([JEUX])

    def faux_repo(self, chemins):
        """Un repo dont « list -p --all » rend `chemins`, comme après un
        init dont les groupes décident des projets extraits."""
        repo = self.racine / ".venv.erplibre/bin/repo"
        repo.parent.mkdir(parents=True, exist_ok=True)
        # Comme le vrai, sans --all il ne nomme que les projets extraits :
        # aucun ici.
        repo.write_text(
            "#!/bin/sh\ncase \"$*\" in *--all*) printf '%s\\n' "
            + " ".join(chemins or ["''"])
            + " ;; esac\n"
        )
        repo.chmod(0o755)
        (self.racine / ".repo/manifests").mkdir(parents=True, exist_ok=True)

    def lancer(self, env=None):
        return subprocess.run(
            [str(SCRIPT), str(self.racine)],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )

    def contenu(self, dossier=None):
        dossier = dossier or self.jeux
        return sorted(
            str(p.relative_to(dossier))
            for p in dossier.rglob("*")
            if ".git" not in p.relative_to(dossier).parts
        )

    def mis_de_cote(self):
        return sorted(self.jeux.parent.glob("games.plain-clone-*"))

    def test_a_clean_clone_is_moved_aside_and_its_saves_copied_back(self):
        (self.jeux / "trace.log").write_text("ignoré")
        avant = self.contenu()
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(
            ["save", "save/.gitkeep", "save/partie.json"], self.contenu()
        )
        self.assertEqual("{}", (self.jeux / "save/partie.json").read_text())
        (ailleurs,) = self.mis_de_cote()
        self.assertEqual(avant, self.contenu(ailleurs))
        self.assertTrue((ailleurs / ".git").is_dir())
        self.assertIn("moved to %s" % (JEUX + ".plain-clone-"), fini.stdout)

    def test_work_the_checks_miss_survives_in_the_moved_clone(self):
        """skip-worktree cache une modification à git status : elle part
        avec le clone, sans être supprimée."""
        (self.jeux / "games_cli.py").write_text("travail\n")
        git(self.jeux, "update-index", "--skip-worktree", "games_cli.py")
        self.assertEqual(0, self.lancer().returncode)
        (ailleurs,) = self.mis_de_cote()
        self.assertEqual("travail\n", (ailleurs / "games_cli.py").read_text())

    def test_local_work_keeps_the_clone_and_exits_1(self):
        def worktree_lie():
            git(
                self.jeux,
                "worktree",
                "add",
                "-q",
                "--detach",
                str(self.tmp / "lie"),
                "v9.9.9",
            )

        cas = {
            "changes or untracked": lambda: (
                self.jeux / "games_cli.py"
            ).write_text("modifié\n"),
            "untracked": lambda: (self.jeux / "notes.txt").write_text("x"),
            "commits on no remote": lambda: (
                git(self.jeux, "switch", "-q", "-c", "travail"),
                (self.jeux / "neuf.py").write_text(""),
                git(self.jeux, "add", "neuf.py"),
                git(self.jeux, "commit", "-q", "-m", "local"),
            ),
            "a stash": lambda: (
                (self.jeux / "games_cli.py").write_text("remisé\n"),
                git(self.jeux, "stash", "-q"),
            ),
            "linked worktrees": worktree_lie,
        }
        for raison, poser in cas.items():
            with self.subTest(raison=raison):
                self.setUp()
                poser()
                avant = self.contenu()
                fini = self.lancer()
                self.assertEqual(1, fini.returncode, fini.stdout)
                self.assertIn("kept", fini.stderr)
                self.assertIn(raison.split(" or ")[0], fini.stderr)
                self.assertIn("repo sync cannot take it over", fini.stderr)
                self.assertEqual(avant, self.contenu())
                self.assertEqual([], self.mis_de_cote())

    def test_the_installed_commit_is_not_local_work(self):
        """main réécrit en amont : le commit extrait n'est plus sur un
        remote, mais refs/erplibre/installed, posé par l'installateur, le
        dit installé ; sans cette marque, il retient le clone."""
        git(self.jeux, "update-ref", "-d", "refs/remotes/origin/HEAD")
        for ref in git(
            self.jeux,
            "for-each-ref",
            "--format=%(refname)",
            "refs/remotes/",
            "refs/heads/",
            "refs/tags/",
        ).split():
            git(self.jeux, "update-ref", "-d", ref)
        self.assertEqual(1, self.lancer().returncode)
        git(self.jeux, "update-ref", "refs/erplibre/installed", "HEAD")
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(1, len(self.mis_de_cote()))

    def test_untracked_files_hidden_by_the_user_config_still_count(self):
        reglage = self.tmp / "gitconfig"
        reglage.write_text("[status]\n\tshowUntrackedFiles = no\n")
        (self.jeux / "notes.txt").write_text("x")
        fini = self.lancer(
            env=dict(os.environ, GIT_CONFIG_GLOBAL=str(reglage))
        )
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("notes.txt", fini.stderr)

    def test_a_clone_repo_will_not_extract_stays(self):
        """Les groupes de l'init excluent les jeux : repo ne touchera pas
        au clone, qui reste."""
        self.faux_repo(["mobile/erplibre_home_mobile"])
        avant = self.contenu()
        self.assertEqual(0, self.lancer().returncode)
        self.assertEqual(avant, self.contenu())
        self.assertEqual([], self.mis_de_cote())

    def test_without_repo_ready_nothing_changes(self):
        """Un init raté laisse .repo/manifests absent : rien à préparer,
        et rien ne se devine d'un manifeste local."""
        shutil.rmtree(self.racine / ".repo/manifests")
        avant = self.contenu()
        fini = self.lancer()
        self.assertEqual((0, ""), (fini.returncode, fini.stdout))
        self.assertEqual(avant, self.contenu())

    def test_a_git_file_outside_repo_holds_the_clone_back(self):
        ailleurs = self.tmp / "git_ailleurs"
        shutil.move(self.jeux / ".git", ailleurs)
        (self.jeux / ".git").write_text("gitdir: %s\n" % ailleurs)
        avant = self.contenu()
        fini = self.lancer()
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("its .git is a file", fini.stderr)
        self.assertEqual(avant, self.contenu())

    def extrait_par_repo(self, forme):
        """Donne à games/ la forme d'une extraction de repo."""
        projet = self.racine / ".repo/projects" / (JEUX + ".git")
        projet.parent.mkdir(parents=True)
        shutil.move(self.jeux / ".git", projet)
        if forme == "lien":
            os.symlink(projet, self.jeux / ".git")
        elif forme == "fichier":
            (self.jeux / ".git").write_text("gitdir: %s\n" % projet)
        else:
            (self.jeux / ".git").mkdir()
            os.symlink(projet / "objects", self.jeux / ".git/objects")

    def test_games_extracted_by_repo_are_left_to_it(self):
        for forme in ("lien", "fichier", "ancienne"):
            with self.subTest(forme=forme):
                self.setUp()
                self.extrait_par_repo(forme)
                avant = self.contenu()
                fini = self.lancer()
                self.assertEqual((0, ""), (fini.returncode, fini.stdout))
                self.assertEqual(avant, self.contenu())
                self.assertEqual([], self.mis_de_cote())

    def test_saves_are_copied_before_repo_removes_its_games(self):
        """L'init n'extrait plus les jeux : repo sync va supprimer games/,
        save/ compris, que les jeux ignorent."""
        self.extrait_par_repo("lien")
        self.faux_repo([])
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        (copie,) = sorted(self.jeux.parent.glob("games.save-*"))
        self.assertEqual("{}", (copie / "partie.json").read_text())
        self.assertIn("repo sync will remove it", fini.stdout)
        self.assertTrue((self.jeux / "save/partie.json").exists())
        # Sans autre sauvegarde que .gitkeep, rien à copier.
        shutil.rmtree(copie)
        (self.jeux / "save/partie.json").unlink()
        fini = self.lancer()
        self.assertEqual((0, ""), (fini.returncode, fini.stdout))
        self.assertEqual([], sorted(self.jeux.parent.glob("games.save-*")))

    def test_nothing_without_games(self):
        shutil.rmtree(self.jeux)
        fini = self.lancer()
        self.assertEqual((0, ""), (fini.returncode, fini.stdout))
        self.assertEqual([], self.mis_de_cote())

    def test_the_moved_clone_is_ignored_by_erplibre(self):
        for chemin in (".plain-clone-20260101/x", ".save-20260101/x"):
            with self.subTest(chemin=chemin):
                fini = subprocess.run(
                    ["git", "check-ignore", "-q", JEUX + chemin], cwd=RACINE
                )
                self.assertEqual(0, fini.returncode)


class LesScriptsDeMiseAJour(unittest.TestCase):
    """repo init fait, le script passe, puis repo sync ; un refus arrête la
    mise à jour avant repo sync."""

    SCRIPTS = (
        "update_manifest_dev.sh",
        "update_manifest_prod.sh",
        "update_manifest_local_dev.sh",
        "update_manifest_local_prod.sh",
        "update_manifest_local_mobile.sh",
        "update_manifest_local_dev_code_generator.sh",
    )

    @staticmethod
    def lignes(nom):
        return [
            ligne
            for ligne in (RACINE / "script/manifest" / nom)
            .read_text(encoding="utf-8")
            .splitlines()
            if not ligne.lstrip().startswith("#")
        ]

    def test_each_update_runs_it_between_repo_init_and_repo_sync(self):
        for nom in self.SCRIPTS:
            with self.subTest(script=nom):
                lignes = self.lignes(nom)

                def rang(motif):
                    (i,) = [
                        n
                        for n, ligne in enumerate(lignes)
                        if re.search(motif, ligne)
                    ]
                    return i

                appel = rang(r"streamdeck_games_to_repo\.sh")
                self.assertEqual(rang(r"bin/repo init") + 1, appel)
                self.assertEqual(appel + 1, rang(r"bin/repo sync"))
                self.assertIn("exit 1", lignes[appel])

    def test_the_code_generator_init_keeps_the_streamdeck_group(self):
        """Un groupe absent de l'init fait supprimer par repo le répertoire
        du projet, sauvegardes comprises."""
        (init,) = [
            ligne
            for ligne in self.lignes(
                "update_manifest_local_dev_code_generator.sh"
            )
            if "bin/repo init" in ligne
        ]
        groupes = re.search(r"-g (\S+)", init).group(1).split(",")
        self.assertIn("streamdeck", groupes)

    def test_it_is_an_executable_valid_shell_script(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        fini = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)


if __name__ == "__main__":
    unittest.main()
