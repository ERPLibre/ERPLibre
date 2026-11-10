#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""erplibre_home_extension_to_repo.sh : un clone ordinaire de l'extension
GNOME, que repo sync refuse (« .git: unsupported checkout state »), perd son
.git avant la synchronisation, et garde ses fichiers : la session GNOME les
charge par un lien, et le répertoire ne se vide jamais.

Chaque test pose une racine temporaire : un dépôt d'extension local cloné
par git dans script/gnome-extension/erplibre_home/, et un faux repo dont
« list -p --all » nomme, ou non, ce chemin, comme le vrai selon les groupes
de l'init. repo lui-même n'est pas lancé : l'adoption qu'il fait d'un
répertoire sans .git est rejouée par git seul (un .git en lien vers le
dépôt, HEAD posé, « read-tree --reset -u »).

Ce que ces tests gardent :

- un clone sans travail local visible voit son .git, et lui seul, passer
  dans erplibre_home.plain-clone-git-<date>/ ; chaque fichier, suivi ou
  ignoré, reste en place, et l'adoption par repo laisse un arbre propre ;
- un clone avec une modification, un fichier non suivi, un commit sur
  aucun remote, une remise, un worktree lié, un .git en fichier hors de
  .repo/ ou un dépôt que git ne lit pas reste entier, et le script sort en
  1 en nommant la raison ;
- une extension extraite par repo que l'init n'extrait plus, et que repo
  sync supprimerait, arrête la mise à jour en nommant le groupe
  erplibre_home ; extraite et gardée par l'init, elle est laissée à repo ;
- sans le répertoire, sans repo prêt, ou quand repo n'extrait pas
  l'extension, rien ne change ;
- chaque script update_manifest_*.sh le lance après la passation des jeux
  et juste avant repo sync.
"""

import os
import re
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
SCRIPT = RACINE / "script/manifest/erplibre_home_extension_to_repo.sh"
EXT = "script/gnome-extension/erplibre_home"
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
        self.source = self.tmp / "ext.git"
        self.source.mkdir()
        git(self.source, "init", "-q", "-b", "main")
        (self.source / ".gitignore").write_text(
            "schemas/gschemas.compiled\nlocale/\n__pycache__/\n"
        )
        (self.source / "schemas").mkdir()
        (self.source / "schemas/x.gschema.xml").write_text("<schemalist/>\n")
        (self.source / "metadata.json").write_text("{}\n")
        git(self.source, "add", "-A")
        git(self.source, "commit", "-q", "-m", "un")
        self.racine = self.tmp / "erplibre"
        self.ext = self.racine / EXT
        self.ext.parent.mkdir(parents=True)
        git(self.tmp, "clone", "-q", str(self.source), str(self.ext))
        # Les sorties de compilation que la session lit, ignorées.
        (self.ext / "schemas/gschemas.compiled").write_text("compilé")
        (self.ext / "locale/fr/LC_MESSAGES").mkdir(parents=True)
        (self.ext / "locale/fr/LC_MESSAGES/erplibre-home.mo").write_text("")
        self.faux_repo([EXT])

    def faux_repo(self, chemins):
        """Un repo dont « list -p --all » rend `chemins`, comme après un
        init dont les groupes décident des projets extraits."""
        repo = self.racine / ".venv.erplibre/bin/repo"
        repo.parent.mkdir(parents=True, exist_ok=True)
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

    def contenu(self):
        return sorted(
            (str(p.relative_to(self.ext)), p.read_bytes())
            for p in self.ext.rglob("*")
            if p.is_file() and ".git" not in p.relative_to(self.ext).parts
        )

    def mis_de_cote(self):
        return sorted(self.ext.parent.glob("erplibre_home.plain-clone-git-*"))

    def test_only_the_git_dir_of_a_clean_clone_moves_aside(self):
        avant = self.contenu()
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual(avant, self.contenu())
        self.assertFalse(os.path.lexists(self.ext / ".git"))
        (git_dir,) = self.mis_de_cote()
        self.assertTrue((git_dir / "HEAD").is_file())
        self.assertIn("moved to %s" % (EXT + ".plain-clone-git-"), fini.stdout)
        self.assertIn("files kept", fini.stdout)

    def test_repo_adopting_the_files_leaves_a_clean_tree(self):
        """Ce que fait repo sync d'un répertoire sans .git : un .git en lien
        vers le dépôt du projet, HEAD détaché sur la révision, puis
        « read-tree --reset -u ». Les fichiers suivis, identiques, ne
        changent pas, les ignorés restent, et git status est vide."""
        self.assertEqual(0, self.lancer().returncode)
        avant = self.contenu()
        projet = self.tmp / "projet"
        git(
            self.tmp,
            "clone",
            "-q",
            "--no-checkout",
            str(self.source),
            str(projet),
        )
        os.symlink(projet / ".git", self.ext / ".git")
        sha = git(self.source, "rev-parse", "main").strip()
        git(self.ext, "update-ref", "--no-deref", "HEAD", sha)
        git(self.ext, "read-tree", "--reset", "-u", "-v", "HEAD")
        self.assertEqual(avant, self.contenu())
        self.assertEqual(
            "",
            git(self.ext, "status", "--porcelain", "--untracked-files=normal"),
        )

    def test_local_work_keeps_the_whole_clone_and_exits_1(self):
        def worktree_lie():
            git(
                self.ext,
                "worktree",
                "add",
                "-q",
                "--detach",
                str(self.tmp / "lie"),
                "HEAD",
            )

        cas = {
            "changes or untracked": lambda: (
                self.ext / "metadata.json"
            ).write_text('{"x": 1}\n'),
            "untracked": lambda: (self.ext / "notes.txt").write_text("x"),
            "commits on no remote": lambda: (
                (self.ext / "neuf.js").write_text(""),
                git(self.ext, "add", "neuf.js"),
                git(self.ext, "commit", "-q", "-m", "local"),
            ),
            "a stash": lambda: (
                (self.ext / "metadata.json").write_text("{}\n\n"),
                git(self.ext, "stash", "-q"),
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
                self.assertIn(raison.split(" or ")[0], fini.stderr)
                self.assertIn("repo sync cannot take it over", fini.stderr)
                self.assertEqual(avant, self.contenu())
                self.assertTrue((self.ext / ".git").is_dir())
                self.assertEqual([], self.mis_de_cote())

    def test_an_unreadable_clone_is_kept_with_its_changes(self):
        """git status échoue sur un index corrompu : une sortie vide n'y
        vaut pas « rien de local », sans quoi repo écraserait la
        modification par read-tree."""
        (self.ext / "metadata.json").write_text('{"x": 1}\n')
        (self.ext / ".git/index").write_bytes(b"illisible")
        avant = self.contenu()
        fini = self.lancer()
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("git status failed", fini.stderr)
        self.assertIn("repo sync cannot take it over", fini.stderr)
        self.assertEqual(avant, self.contenu())
        self.assertTrue((self.ext / ".git").is_dir())
        self.assertEqual([], self.mis_de_cote())

    def test_a_git_file_outside_repo_holds_the_clone_back(self):
        ailleurs = self.tmp / "git_ailleurs"
        shutil.move(self.ext / ".git", ailleurs)
        (self.ext / ".git").write_text("gitdir: %s\n" % ailleurs)
        fini = self.lancer()
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("its .git is a file", fini.stderr)
        self.assertTrue((self.ext / ".git").is_file())

    def extrait_par_repo(self):
        """Donne à l'extension la forme d'une extraction de repo."""
        projet = self.racine / ".repo/projects" / (EXT + ".git")
        projet.parent.mkdir(parents=True)
        shutil.move(self.ext / ".git", projet)
        os.symlink(projet, self.ext / ".git")

    def test_an_extension_repo_keeps_extracting_is_left_to_it(self):
        self.extrait_par_repo()
        avant = self.contenu()
        fini = self.lancer()
        self.assertEqual((0, ""), (fini.returncode, fini.stdout))
        self.assertEqual(avant, self.contenu())

    def test_an_init_without_its_group_stops_before_repo_removes_it(self):
        """repo sync supprimerait le répertoire que la session charge."""
        self.extrait_par_repo()
        self.faux_repo(["mobile/erplibre_home_mobile"])
        avant = self.contenu()
        fini = self.lancer()
        self.assertEqual(1, fini.returncode, fini.stdout)
        self.assertIn("repo sync would remove it", fini.stderr)
        self.assertIn("erplibre_home group", fini.stderr)
        self.assertEqual(avant, self.contenu())

    def test_a_clone_repo_will_not_extract_stays(self):
        self.faux_repo(["mobile/erplibre_home_mobile"])
        avant = self.contenu()
        self.assertEqual(0, self.lancer().returncode)
        self.assertEqual(avant, self.contenu())
        self.assertTrue((self.ext / ".git").is_dir())

    def test_without_repo_ready_or_extension_nothing_changes(self):
        shutil.rmtree(self.racine / ".repo/manifests")
        fini = self.lancer()
        self.assertEqual((0, ""), (fini.returncode, fini.stdout))
        self.assertTrue((self.ext / ".git").is_dir())
        self.faux_repo([EXT])
        shutil.rmtree(self.ext)
        fini = self.lancer()
        self.assertEqual((0, ""), (fini.returncode, fini.stdout))
        self.assertEqual([], self.mis_de_cote())

    def test_what_is_set_aside_is_ignored_by_erplibre(self):
        fini = subprocess.run(
            ["git", "check-ignore", "-q", EXT + ".plain-clone-git-2026/HEAD"],
            cwd=RACINE,
        )
        self.assertEqual(0, fini.returncode)

    def test_it_is_an_executable_valid_shell_script(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK))
        fini = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, fini.returncode, fini.stderr)


class LesScriptsDeMiseAJour(unittest.TestCase):
    SCRIPTS = (
        "update_manifest_dev.sh",
        "update_manifest_prod.sh",
        "update_manifest_local_dev.sh",
        "update_manifest_local_prod.sh",
        "update_manifest_local_mobile.sh",
        "update_manifest_local_dev_code_generator.sh",
    )

    def test_each_update_runs_it_after_the_games_and_before_repo_sync(self):
        for nom in self.SCRIPTS:
            with self.subTest(script=nom):
                lignes = [
                    ligne
                    for ligne in (RACINE / "script/manifest" / nom)
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if not ligne.lstrip().startswith("#")
                ]

                def rang(motif):
                    (i,) = [
                        n
                        for n, ligne in enumerate(lignes)
                        if re.search(motif, ligne)
                    ]
                    return i

                appel = rang(r"erplibre_home_extension_to_repo\.sh")
                self.assertEqual(
                    rang(r"streamdeck_games_to_repo\.sh") + 1, appel
                )
                self.assertEqual(appel + 1, rang(r"bin/repo sync"))
                self.assertIn("exit 1", lignes[appel])


if __name__ == "__main__":
    unittest.main()
