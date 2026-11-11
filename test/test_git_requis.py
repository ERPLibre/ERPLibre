#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""git avant TODO : script/install/lib_git_requis.sh, et son branchement.

TODO importe GitPython, qui refuse de se charger sans exécutable git.
el_git_requis, lancé par install.sh avant tout Python, pose git par le
gestionnaire de paquets du système, ou dit comment le poser.

Le PATH du test ne porte que des outils choisis : git en est absent, et
sudo, apt-get, dnf et id sont de faux scripts qui notent leurs appels. Le
faux apt-get « installe » un faux git dans ce même PATH. Rien n'est
installé.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
LIB = RACINE / "script/install/lib_git_requis.sh"


class BancGit(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        self.trace = self.dir / "trace"
        for outil in ("bash", "env", "chmod", "cat"):
            os.symlink(shutil.which(outil), self.bin / outil)
        self.faux("id", 'echo "1000"\n')
        self.faux(
            "sudo",
            f'echo "sudo $*" >> "{self.trace}"\n'
            '[ "$1" = "-n" ] && shift\n'
            'exec env "$@"\n',
        )

    def faux(self, nom, corps):
        chemin = self.bin / nom
        chemin.write_text("#!/bin/bash\n" + corps, encoding="utf-8")
        chemin.chmod(0o755)

    def gestionnaire(self, nom="apt-get"):
        """Un faux gestionnaire qui pose un faux git sur « install »."""
        self.faux(
            nom,
            f'echo "{nom} $*" >> "{self.trace}"\n'
            'case " $* " in *" install "*)\n'
            f"  printf '#!/bin/bash\\necho git version 9.9\\n' > \"{self.bin}/git\"\n"
            f'  chmod +x "{self.bin}/git" ;;\n'
            "esac\n",
        )

    def lancer(self, entree="", terminal=True, env=None):
        vrai = "true" if terminal else "false"
        script = (
            f'source "{LIB}"\n'
            f"el_git_peut_demander() {{ {vrai}; }}\n"
            "el_git_requis\n"
        )
        milieu = {"PATH": str(self.bin), "HOME": str(self.dir)}
        milieu.update(env or {})
        return subprocess.run(
            [str(self.bin / "bash"), "-c", script],
            cwd=RACINE,
            input=entree,
            env=milieu,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def traces(self):
        return self.trace.read_text() if self.trace.exists() else ""


class TestGitRequis(BancGit):
    def test_git_present_rien_n_est_fait(self):
        self.faux("git", "echo git version 9.9\n")
        self.gestionnaire()
        fini = self.lancer()
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertEqual("", fini.stderr)
        self.assertEqual("", self.traces())

    def test_entree_pose_git(self):
        self.gestionnaire()
        fini = self.lancer("\n")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn("[O/n]", fini.stderr)
        self.assertIn("apt-get", self.traces())
        self.assertIn("install -y git", self.traces())
        self.assertIn("git est pose : git version 9.9", fini.stderr)

    def test_non_ne_pose_rien_et_donne_la_commande(self):
        self.gestionnaire()
        fini = self.lancer("n\n")
        self.assertEqual(1, fini.returncode)
        self.assertIn("Commande : sudo apt-get", fini.stderr)
        self.assertEqual("", self.traces())
        self.assertFalse((self.bin / "git").exists())

    def test_sans_terminal_la_commande_est_donnee(self):
        self.gestionnaire()
        fini = self.lancer(terminal=False)
        self.assertEqual(1, fini.returncode)
        self.assertIn("Commande :", fini.stderr)
        self.assertNotIn("[O/n]", fini.stderr)
        self.assertEqual("", self.traces())

    def test_non_interactif_pose_git_sans_demander(self):
        # sudo -n : un mot de passe que personne ne saisirait fait échouer.
        self.gestionnaire()
        fini = self.lancer(terminal=False, env={"EL_NON_INTERACTIVE": "1"})
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertNotIn("[O/n]", fini.stderr)
        self.assertIn("sudo -n DEBIAN_FRONTEND=noninteractive", self.traces())

    def test_root_se_passe_de_sudo(self):
        # Un conteneur minimal, lancé en root, n'a pas sudo.
        self.faux("id", 'echo "0"\n')
        self.gestionnaire()
        fini = self.lancer("\n")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertNotIn("sudo", self.traces())

    def test_dnf(self):
        self.gestionnaire("dnf")
        fini = self.lancer("\n")
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn("sudo dnf install -y git", self.traces())

    def test_aucun_gestionnaire(self):
        fini = self.lancer("\n")
        self.assertEqual(1, fini.returncode)
        self.assertIn("Aucun gestionnaire de paquets connu", fini.stderr)

    def test_echec_de_la_pose(self):
        # Le gestionnaire tourne sans poser git : TODO ne démarre pas.
        self.faux("apt-get", f'echo "apt-get $*" >> "{self.trace}"\n')
        fini = self.lancer("\n")
        self.assertEqual(1, fini.returncode)
        self.assertIn("git n'a pas pu etre pose", fini.stderr)


class TestBranchement(unittest.TestCase):
    def test_install_sh_demande_git_avant_tout_python(self):
        texte = (RACINE / "install.sh").read_text(encoding="utf-8")
        rang = texte.index("el_git_requis || exit 1")
        self.assertIn(". ./script/install/lib_git_requis.sh", texte[:rang])
        self.assertNotIn("exec ", texte[:rang])
        self.assertNotIn("python", texte[:rang].split("lib_git_requis")[-1])

    def test_todo_py_sans_git_le_dit_sans_traceback(self):
        with tempfile.TemporaryDirectory() as vide:
            fini = subprocess.run(
                [sys.executable, "script/todo/todo.py"],
                cwd=RACINE,
                env={"PATH": vide, "HOME": vide, "EL_LANG": "fr"},
                capture_output=True,
                text=True,
                timeout=60,
            )
        self.assertEqual(1, fini.returncode, fini.stderr)
        self.assertIn("./todo.sh", fini.stdout)
        self.assertNotIn("Traceback", fini.stderr)


if __name__ == "__main__":
    unittest.main()
