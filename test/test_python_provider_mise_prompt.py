#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Sans mise, l'installation le PROPOSE avant que pyenv ne compile.

La question ne se pose que devant un terminal : un déploiement de VM, un
build Docker ou une CI lancent la même installation sans personne pour
répondre, et doivent garder le comportement d'avant — l'avertissement, puis
la compilation. Devant un terminal, le défaut est oui, pour Entrée comme
au bout du délai : un CPython précompilé vaut mieux qu'une compilation. Un
refus est retenu dans .erplibre-mise-refus, pour que le délai écoulé au
venv suivant ne le renverse pas.

Tout est faux et local : curl dépose un installateur qui pose un faux mise
dans le HOME du test, ce mise « installe » un faux python, et pyenv est
remplacé par une fonction qui laisse une trace. Aucun réseau, aucune
compilation, rien hors du répertoire temporaire.
"""

import os
import pty
import select
import shutil
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
LIB = RACINE / "script" / "install" / "lib_python_provider.sh"
VERSION = "3.12.16"
QUESTION = "Installer mise maintenant"
PERMANENT = "Activer mise de facon permanente"

# Le faux mise : « install » crée un python qui rend la version demandée,
# « where » le retrouve, comme le vrai, sans réseau.
FAUX_MISE = """#!/bin/bash
racine="$(dirname "$0")/../share/faux_mise"
case "$1" in
  --version) echo "2026.1.0 faux" ;;
  where)
    v="${2#python@}"
    [ -x "$racine/$v/bin/python" ] || exit 1
    echo "$racine/$v" ;;
  install)
    v="${2#python@}"
    mkdir -p "$racine/$v/bin"
    printf '#!/bin/bash\\necho %s\\n' "$v" > "$racine/$v/bin/python"
    chmod +x "$racine/$v/bin/python" ;;
  *) exit 1 ;;
esac
"""


class BancMise(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.home = self.dir / "home"
        self.home.mkdir()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        for outil in (
            "bash",
            "sh",
            "mktemp",
            "rm",
            "cat",
            "grep",
            "mkdir",
            "chmod",
            "dirname",
            "printf",
        ):
            os.symlink(shutil.which(outil), self.bin / outil)
        self.trace = self.dir / "trace"
        self.faux("uname", 'echo "x86_64"\n')
        # curl dépose, à l'emplacement de -o, un installateur qui pose le
        # faux mise là où mise.run le pose : ~/.local/bin.
        (self.dir / "faux_mise").write_text(FAUX_MISE, encoding="utf-8")
        self.faux(
            "curl",
            f'echo "curl $*" >> "{self.trace}"\n'
            'while [ $# -gt 0 ]; do [ "$1" = -o ] && sortie="$2"; shift; done\n'
            'cat > "$sortie" <<FIN\n'
            # Le vrai installateur parle sur stdout : ce qui en arriverait
            # sur le stdout d'el_python_exec deviendrait le chemin retenu.
            'echo "mise: installed successfully"\n'
            'mkdir -p "\\$HOME/.local/bin"\n'
            f'cp "{self.dir}/faux_mise" "\\$HOME/.local/bin/mise"\n'
            'chmod +x "\\$HOME/.local/bin/mise"\n'
            "FIN\n",
        )
        os.symlink(shutil.which("cp"), self.bin / "cp")

    def faux(self, nom, corps):
        chemin = self.bin / nom
        if chemin.exists():
            chemin.unlink()
        chemin.write_text("#!/bin/bash\n" + corps, encoding="utf-8")
        chemin.chmod(0o755)

    def lancer(self, entree="", terminal=True, env=None, appel=None):
        """Source la bibliothèque, remplace ce qui sortirait du banc, puis
        appelle el_python_exec. stdout est ce que lirait install_venv.sh."""
        garde = ""
        if terminal is not None:
            vrai = "true" if terminal else "false"
            garde = f"el_peut_demander() {{ {vrai}; }}\n"
        script = (
            f'source "{LIB}"\n'
            + garde
            # Le python du système ne doit pas court-circuiter la question.
            + "el_distro_python_exec() { return 1; }\n"
            "el_pyenv_install() {\n"
            f'  echo "pyenv $1" >> "{self.trace}"\n'
            '  echo "/faux/pyenv/python"\n'
            "}\n" + (appel or f"el_python_exec {VERSION}")
        )
        milieu = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "TMPDIR": str(self.dir),
            "PYENV_ROOT": str(self.dir / "pyenv"),
            "SHELL": "/bin/bash",
        }
        milieu.update(env or {})
        # Dans le dossier du banc : un refus y écrit .erplibre-mise-refus.
        return subprocess.run(
            [str(self.bin / "bash"), "-c", script],
            input=entree,
            cwd=self.dir,
            env=milieu,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def traces(self):
        return self.trace.read_text() if self.trace.exists() else ""

    @property
    def refus(self):
        return self.dir / ".erplibre-mise-refus"

    @property
    def mise_pose(self):
        return self.home / ".local" / "bin" / "mise"


class TestSansTerminal(BancMise):
    def test_rien_n_est_demande_et_pyenv_compile(self):
        fini = self.lancer(terminal=False)
        self.assertNotIn(QUESTION, fini.stderr)
        self.assertIn("make install_mise", fini.stderr)
        self.assertNotIn("curl", self.traces())
        self.assertIn(f"pyenv {VERSION}", self.traces())
        self.assertEqual("/faux/pyenv/python", fini.stdout.strip())


class TestLaQuestion(BancMise):
    def test_le_defaut_est_oui(self):
        # Entrée pose mise ; la seconde, à l'activation permanente, dont le
        # défaut reste non : elle modifie le .bashrc.
        fini = self.lancer("\n\n")
        self.assertIn(QUESTION, fini.stderr)
        self.assertIn("(O/n, defaut : O dans 60 s)", fini.stderr)
        self.assertIn("(o/N, defaut : N dans 60 s)", fini.stderr)
        self.assertTrue(self.mise_pose.exists(), fini.stderr)
        self.assertNotIn("pyenv", self.traces())
        self.assertFalse((self.home / ".bashrc").exists())

    def test_non_explicite_laisse_pyenv_compiler(self):
        for non in ("n", "non", "No"):
            with self.subTest(non=non):
                if self.trace.exists():
                    self.trace.unlink()
                self.refus.unlink(missing_ok=True)
                fini = self.lancer(f"{non}\n")
                self.assertNotIn("curl", self.traces())
                self.assertIn(f"pyenv {VERSION}", self.traces())
                self.assertFalse(self.mise_pose.exists())
                self.assertTrue(self.refus.exists(), fini.stderr)
                # Le refus a déjà dit pourquoi pyenv compile : pas de
                # conseil d'interrompre pour poser mise, juste après.
                self.assertNotIn("Ctrl+C", fini.stderr)

    def test_la_fin_de_l_entree_prend_le_defaut(self):
        fini = self.lancer("")
        self.assertTrue(self.mise_pose.exists(), fini.stderr)
        self.assertNotIn("pyenv", self.traces())
        self.assertEqual(0, fini.returncode, fini.stderr)

    def test_un_refus_est_retenu_au_venv_suivant(self):
        # Sans lui, le délai écoulé au venv suivant renverserait le « non ».
        self.lancer("n\n")
        self.trace.unlink()
        fini = self.lancer("")
        self.assertNotIn(QUESTION + " (", fini.stderr)
        self.assertIn("refuse pour ce depot", fini.stderr)
        self.assertIn(f"pyenv {VERSION}", self.traces())
        self.assertFalse(self.mise_pose.exists())

    def test_non_interactif_sudo_ne_demande_rien(self):
        # Sur un hôte à pacman, la pose passe par sudo : en mode non
        # interactif, « sudo -n », qui échoue sans ticket au lieu
        # d'attendre un mot de passe ; pyenv reprend la main.
        self.faux("pacman", "exit 0\n")
        self.faux("sudo", f'echo "sudo $*" >> "{self.trace}"\nexit 1\n')
        fini = self.lancer(
            env={"EL_NON_INTERACTIVE": "1", "EL_INSTALL_MISE": "1"}
        )
        self.assertIn("sudo -n pacman", self.traces(), fini.stderr)
        self.assertIn("sudo demanderait un mot de passe", fini.stderr)
        self.assertNotIn(QUESTION + " (", fini.stderr)

    def test_oui_pose_mise_et_continue_avec_lui(self):
        for oui in ("o", "oui", "y", "Yes"):
            with self.subTest(oui=oui):
                if self.mise_pose.exists():
                    shutil.rmtree(self.home / ".local")
                if self.trace.exists():
                    self.trace.unlink()
                fini = self.lancer(f"{oui}\nn\n")
                self.assertTrue(self.mise_pose.exists(), fini.stderr)
                self.assertNotIn("pyenv", self.traces(), fini.stderr)
                # stdout ne porte QUE le chemin : les questions et la
                # sortie de l'installateur sont sur stderr.
                lignes = fini.stdout.splitlines()
                self.assertEqual(1, len(lignes), fini.stdout)
                self.assertTrue(
                    lignes[0].endswith(f"/{VERSION}/bin/python"), lignes
                )

    def test_l_activation_permanente_est_demandee_apres_la_pose(self):
        fini = self.lancer("o\n\n")
        self.assertLess(
            fini.stderr.index(QUESTION), fini.stderr.index(PERMANENT)
        )
        self.assertIn(".bashrc", fini.stderr)
        self.assertFalse((self.home / ".bashrc").exists())


class TestActivationPermanente(BancMise):
    def test_oui_ecrit_l_activation_une_seule_fois(self):
        self.lancer("o\no\n")
        bashrc = (self.home / ".bashrc").read_text()
        ligne = f'eval "$({self.mise_pose} activate bash)"'
        self.assertIn(ligne, bashrc)
        self.lancer(appel="el_mise_rendre_permanent")
        self.assertEqual(
            1, (self.home / ".bashrc").read_text().count("mise activate")
        )

    def test_un_bashrc_existant_garde_son_contenu(self):
        (self.home / ".bashrc").write_text("alias ll='ls -l'\n")
        self.lancer("o\no\n")
        bashrc = (self.home / ".bashrc").read_text()
        self.assertTrue(bashrc.startswith("alias ll='ls -l'\n"), bashrc)
        self.assertIn("mise activate bash", bashrc)

    def test_zsh_ecrit_dans_zshrc(self):
        self.lancer("o\no\n", env={"SHELL": "/usr/bin/zsh"})
        self.assertIn("mise activate zsh", (self.home / ".zshrc").read_text())
        self.assertFalse((self.home / ".bashrc").exists())


class TestLeRepli(BancMise):
    def test_un_telechargement_rate_retombe_sur_pyenv(self):
        self.faux(
            "curl",
            f'echo "curl $*" >> "{self.trace}"\n'
            'echo "curl: (22) The requested URL returned error: 504" >&2\n'
            "exit 22\n",
        )
        fini = self.lancer("o\n")
        self.assertIn("installateur mise impossible", fini.stderr)
        self.assertIn(
            "mise n'a pas pu etre pose : pyenv va compiler", fini.stderr
        )
        self.assertNotIn(PERMANENT, fini.stderr)
        self.assertIn(f"pyenv {VERSION}", self.traces())
        self.assertEqual("/faux/pyenv/python", fini.stdout.strip())


class TestQuandRienNEstDemande(BancMise):
    def test_pyenv_porte_deja_la_version(self):
        (self.dir / "pyenv" / "versions" / VERSION).mkdir(parents=True)
        fini = self.lancer("o\n")
        self.assertNotIn(QUESTION, fini.stderr)
        self.assertNotIn("curl", self.traces())

    def test_s390x_n_a_aucun_binaire_mise(self):
        self.faux("uname", 'echo "s390x"\n')
        fini = self.lancer("o\n")
        self.assertNotIn(QUESTION, fini.stderr)
        self.assertNotIn("curl", self.traces())

    def test_pyenv_demande_explicitement(self):
        fini = self.lancer("o\n", env={"EL_PYTHON_PROVIDER": "pyenv"})
        self.assertNotIn(QUESTION, fini.stderr)
        self.assertNotIn("curl", self.traces())

    def test_un_mise_hors_du_path_est_retrouve(self):
        # Ce que laisse une première pose : ~/.local/bin hors du PATH. Le
        # venv suivant, dans un autre processus, doit s'en servir.
        self.lancer("o\nn\n")
        self.trace.unlink()
        fini = self.lancer("")
        self.assertNotIn(QUESTION, fini.stderr)
        self.assertNotIn("curl", self.traces())
        self.assertNotIn("pyenv", self.traces())
        self.assertTrue(fini.stdout.strip().endswith("/bin/python"))


class TestCeQueLaRevueAVu(BancMise):
    def test_un_tube_sur_stdin_ne_pose_aucune_question(self):
        # Le VRAI garde, non remplacé : stdin et stderr sont des tubes, comme
        # dans une VM, un build Docker ou une CI.
        fini = self.lancer("o\n", terminal=None)
        self.assertNotIn(QUESTION, fini.stderr)
        self.assertNotIn("curl", self.traces())
        self.assertIn(f"pyenv {VERSION}", self.traces())

    def test_sans_reponse_le_defaut_s_applique_au_bout_du_delai(self):
        # Un « non » n'est pas retenu d'un processus à l'autre : la question
        # revient au venv suivant, et une installation laissée seule doit
        # continuer plutôt que d'attendre. stdin reste ouvert, sans rien.
        script = (
            f'source "{LIB}"\n'
            "el_peut_demander() { true; }\n"
            "el_distro_python_exec() { return 1; }\n"
            "el_pyenv_install() { echo /faux/pyenv/python; }\n"
            f"el_python_exec {VERSION}\n"
        )
        milieu = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "TMPDIR": str(self.dir),
            "PYENV_ROOT": str(self.dir / "pyenv"),
            "EL_QUESTION_DELAI": "1",
        }
        # Un tube dont l'écriture reste ouverte : read n'y voit jamais de fin
        # d'entrée, seul le délai peut le débloquer.
        lecture, ecriture = os.pipe()
        try:
            proc = subprocess.Popen(
                [str(self.bin / "bash"), "-c", script],
                stdin=lecture,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                cwd=self.dir,
                env=milieu,
                text=True,
            )
            sortie, erreur = proc.communicate(timeout=20)
        finally:
            os.close(lecture)
            os.close(ecriture)
        # Le délai écoulé prend le défaut, oui : mise est posé.
        self.assertIn("defaut : O dans 1 s", erreur)
        self.assertTrue(
            sortie.strip().endswith(f"/{VERSION}/bin/python"), erreur
        )
        self.assertNotIn("pyenv", self.traces())

    def test_mise_explicite_ignore_le_refus_retenu(self):
        # EL_PYTHON_PROVIDER=mise exige mise : un refus retenu en mode auto
        # ne le bloque pas, et un refus ici n'est pas retenu.
        self.refus.touch()
        fini = self.lancer("n\n", env={"EL_PYTHON_PROVIDER": "mise"})
        self.assertIn(QUESTION + " (", fini.stderr)
        self.refus.unlink()
        self.lancer("n\n", env={"EL_PYTHON_PROVIDER": "mise"})
        self.assertFalse(self.refus.exists())

    def test_mise_explicite_ne_promet_pas_pyenv(self):
        for reponses in ("n\n", "o\n"):
            with self.subTest(reponses=reponses):
                # Chaque tour part sans refus retenu.
                self.refus.unlink(missing_ok=True)
                if reponses == "o\n":
                    self.faux("curl", "exit 22\n")
                fini = self.lancer(
                    reponses, env={"EL_PYTHON_PROVIDER": "mise"}
                )
                self.assertIn(QUESTION, fini.stderr)
                self.assertNotIn("pyenv va compiler", fini.stderr)
                self.assertIn("l'installation s'arrete", fini.stderr)
                self.assertNotEqual(0, fini.returncode)
                self.assertEqual("", fini.stdout.strip())
                self.assertNotIn("pyenv", self.traces())

    def test_le_conseil_de_repli_donne_le_chemin_de_mise(self):
        # mise posé hors du PATH, mais incapable de fournir la version : le
        # conseil doit nommer ce mise-là, qu'un « mise » nu ne trouverait pas.
        local_bin = self.home / ".local" / "bin"
        local_bin.mkdir(parents=True)
        faux = local_bin / "mise"
        faux.write_text("#!/bin/bash\nexit 1\n", encoding="utf-8")
        faux.chmod(0o755)
        fini = self.lancer("")
        self.assertIn(f"{faux} install python@{VERSION}", fini.stderr)

    def test_une_activation_en_commentaire_ne_compte_pas(self):
        (self.home / ".bashrc").write_text(
            '# eval "$(mise activate bash)"\n', encoding="utf-8"
        )
        fini = self.lancer("o\no\n")
        self.assertNotIn("deja active", fini.stderr)
        self.assertIn(
            f'\neval "$({self.mise_pose} activate bash)"',
            (self.home / ".bashrc").read_text(),
        )

    def test_une_activation_existante_n_est_pas_doublee(self):
        (self.home / ".bashrc").write_text(
            'eval "$(mise activate bash)"\n', encoding="utf-8"
        )
        fini = self.lancer("o\no\n")
        self.assertIn("deja active", fini.stderr)
        self.assertEqual(
            1, (self.home / ".bashrc").read_text().count("activate")
        )

    def test_un_autre_shell_ne_recoit_rien(self):
        fini = self.lancer("o\n", env={"SHELL": "/usr/bin/fish"})
        self.assertNotIn(PERMANENT, fini.stderr)
        self.assertIn("ni bash ni zsh", fini.stderr)
        self.assertFalse((self.home / ".bashrc").exists())
        # mise est posé et l'installation continue quand même avec lui.
        self.assertNotIn("pyenv", self.traces())


class TestMakeInstallMise(BancMise):
    """La cible elle-même, de bout en bout, dans le banc isolé."""

    def make(self):
        if not (self.bin / "make").exists():
            os.symlink(shutil.which("make"), self.bin / "make")
        # Le refus vit dans le banc, jamais à la racine du vrai dépôt.
        return subprocess.run(
            [str(self.bin / "make"), "-s", "install_mise"],
            cwd=RACINE,
            input="",
            env={
                "PATH": str(self.bin),
                "HOME": str(self.home),
                "TMPDIR": str(self.dir),
                "SHELL": "/bin/bash",
                "EL_MISE_REFUS": str(self.refus),
            },
            capture_output=True,
            text=True,
            timeout=60,
        )

    def test_pose_mise_et_dit_comment_l_activer(self):
        self.refus.touch()
        fini = self.make()
        # mise posé à la demande : le refus retenu est oublié.
        self.assertFalse(self.refus.exists(), fini.stderr)
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertTrue(self.mise_pose.exists(), fini.stderr)
        # Sans terminal, rien n'est demandé : la ligne est donnée à copier.
        self.assertIn("activate bash", fini.stderr)
        self.assertFalse((self.home / ".bashrc").exists())

    def test_un_echec_fait_echouer_make(self):
        # make rend 2 dès qu'une recette échoue, quel que soit son code.
        self.faux("curl", "exit 22\n")
        fini = self.make()
        self.assertNotEqual(0, fini.returncode)
        self.assertIn("installateur mise impossible", fini.stderr)

    def test_s390x_n_est_pas_une_erreur(self):
        self.faux("uname", 'echo "s390x"\n')
        self.refus.touch()
        fini = self.make()
        # Rien n'est posé : le refus reste.
        self.assertTrue(self.refus.exists(), fini.stderr)
        self.assertEqual(0, fini.returncode, fini.stderr)
        self.assertIn("s390x", fini.stderr)


class TestDerriereUnVraiTerminal(BancMise):
    """Le garde de terminal, sans le remplacer : install_venv.sh lit
    el_python_exec par « $( … ) », où stdout est un tube même devant un
    terminal. La question doit s'afficher quand même, et le chemin rendu
    rester propre."""

    def conduire(self, frappes):
        script = (
            f'source "{LIB}"\n'
            "el_distro_python_exec() { return 1; }\n"
            "el_pyenv_install() { echo /faux/pyenv/python; }\n"
            f'chemin="$(el_python_exec {VERSION})"\n'
            'echo "CHEMIN=$chemin"\n'
        )
        milieu = {
            "PATH": str(self.bin),
            "HOME": str(self.home),
            "TMPDIR": str(self.dir),
            "PYENV_ROOT": str(self.dir / "pyenv"),
            "SHELL": "/bin/bash",
        }
        maitre, esclave = pty.openpty()
        proc = subprocess.Popen(
            [str(self.bin / "bash"), "-c", script],
            stdin=esclave,
            stdout=esclave,
            stderr=esclave,
            cwd=self.dir,
            env=milieu,
            close_fds=True,
        )
        os.close(esclave)
        morceaux, restantes = [], list(frappes)
        limite = time.monotonic() + 30
        try:
            while time.monotonic() < limite:
                pret, _, _ = select.select([maitre], [], [], 0.5)
                if not pret:
                    if proc.poll() is not None:
                        break
                    continue
                try:
                    bloc = os.read(maitre, 4096)
                except OSError:
                    break
                if not bloc:
                    break
                morceaux.append(bloc)
                vu = b"".join(morceaux).decode(errors="replace")
                # Une frappe par question, une fois la question affichée.
                if restantes and vu.count("? ") > len(frappes) - len(
                    restantes
                ):
                    os.write(maitre, restantes.pop(0).encode())
        finally:
            if proc.poll() is None:
                proc.kill()
            proc.wait(timeout=30)
            os.close(maitre)
        return b"".join(morceaux).decode(errors="replace").replace("\r", "")

    def test_la_question_s_affiche_et_le_chemin_reste_propre(self):
        texte = self.conduire(["o\n", "n\n"])
        self.assertIn(QUESTION, texte)
        self.assertIn(PERMANENT, texte)
        ligne = [lg for lg in texte.splitlines() if lg.startswith("CHEMIN=")]
        self.assertEqual(1, len(ligne), texte)
        self.assertTrue(ligne[0].endswith(f"/{VERSION}/bin/python"), texte)


class TestUneSeulePose(unittest.TestCase):
    def test_make_install_mise_passe_par_la_bibliotheque(self):
        """Une seule façon de poser mise : la cible du Makefile appelle la
        fonction que l'installation propose, sans copie de l'installateur."""
        sortie = subprocess.run(
            ["make", "-n", "install_mise"],
            cwd=RACINE,
            capture_output=True,
            text=True,
            timeout=60,
        ).stdout
        self.assertIn("el_mise_poser", sortie)
        self.assertNotIn("mise.run", sortie)


if __name__ == "__main__":
    unittest.main()
