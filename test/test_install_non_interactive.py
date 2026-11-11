#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le mode d'installation non interactif dans les scripts shell.

EL_NON_INTERACTIVE=1 coupe toutes les questions de l'installation. Ces tests
gardent :

- le fragment script/install/lib_non_interactive.sh : apt-get sans question
  ni relance de service, les variables exportées, sudo vérifié d'avance et
  son ticket gardé vivant ;
- les questions des scripts : l'architecture non supportée s'arrête sans
  rien lire même sur un terminal, mise ne demande plus rien mais attend sa
  réponse dans EL_INSTALL_MISE, et install.sh installe le venv d'outillage
  sans demander ;
- le branchement des scripts, lu dans leur texte.

Hors de ce mode, rien ne change : chaque test du mode a son pendant qui le
vérifie. sudo, uname et apt-get sont remplacés par des scripts qui notent
leurs appels ; rien n'est installé.
"""

import os
import re
import select
import subprocess
import tempfile
import unittest
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
LIB = RACINE / "script/install/lib_non_interactive.sh"
# Le mode et ses réponses, retirés de l'environnement hérité du shell.
VARIABLES_DU_MODE = {
    "EL_NON_INTERACTIVE",
    "EL_INSTALL_TARGET",
    "EL_FREEZE",
    "EL_WITH_EXTRA",
    "EL_INSTALL_SYSTEM",
    "EL_INSTALL_MISE",
    "EL_GIT_NAME",
    "EL_GIT_EMAIL",
}


def environnement(**extra):
    """L'environnement du test, sans mode ni réponse hérités du shell."""
    env = {k: v for k, v in os.environ.items() if k not in VARIABLES_DU_MODE}
    env.update(extra)
    return env


def sur_terminal(script, env):
    """Lance `script` avec stdin, stdout et stderr sur un pseudo-terminal,
    sans rien y taper ; rend (code, ce qui a été affiché). Une lecture
    bloquerait jusqu'au délai et ferait échouer le test."""
    maitre, esclave = os.openpty()
    proc = subprocess.Popen(
        ["bash", "-c", script],
        cwd=RACINE,
        env=env,
        stdin=esclave,
        stdout=esclave,
        stderr=esclave,
    )
    os.close(esclave)
    code = proc.wait(timeout=10)
    lu = b""
    while select.select([maitre], [], [], 0.2)[0]:
        try:
            morceau = os.read(maitre, 4096)
        except OSError:
            break
        if not morceau:
            break
        lu += morceau
    os.close(maitre)
    return code, lu.decode(errors="replace")


class BancShell(unittest.TestCase):
    """sudo remplacé par un script qui note ses arguments et rend
    `self.code_sudo`."""

    code_sudo = 0

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.trace = self.dir / "trace"
        faux = self.dir / "sudo"
        faux.write_text(
            f'#!/bin/sh\necho "sudo $*" >> "{self.trace}"\n'
            f"exit {self.code_sudo}\n",
            encoding="utf-8",
        )
        faux.chmod(0o755)

    def lancer(self, appel, **env):
        milieu = environnement(**env)
        milieu["PATH"] = f"{self.dir}:{milieu['PATH']}"
        return subprocess.run(
            ["bash", "-c", f'. "{LIB}"; {appel}'],
            cwd=RACINE,
            env=milieu,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def appels_sudo(self):
        if not self.trace.exists():
            return []
        return self.trace.read_text().splitlines()


class TestFragment(BancShell):
    def test_apt_get_hors_mode(self):
        sortie = self.lancer("el_apt_get").stdout
        self.assertEqual(sortie, "sudo apt-get -o DPkg::Lock::Timeout=600")

    def test_apt_get_en_mode(self):
        sortie = self.lancer("el_apt_get", EL_NON_INTERACTIVE="1").stdout
        for attendu in (
            "sudo DEBIAN_FRONTEND=noninteractive NEEDRESTART_MODE=l apt-get",
            "DPkg::Lock::Timeout=600",
            "--force-confdef",
            "--force-confold",
        ):
            self.assertIn(attendu, sortie)

    def test_variables_exportees_en_mode_seulement(self):
        lire = (
            "el_non_interactive_env; echo"
            ' "$DEBIAN_FRONTEND|$NEEDRESTART_MODE|$GIT_TERMINAL_PROMPT|$PIP_NO_INPUT"'
        )
        sans = {
            "DEBIAN_FRONTEND": "",
            "NEEDRESTART_MODE": "",
            "GIT_TERMINAL_PROMPT": "",
            "PIP_NO_INPUT": "",
        }
        self.assertEqual(self.lancer(lire, **sans).stdout.strip(), "|||")
        self.assertEqual(
            self.lancer(lire, EL_NON_INTERACTIVE="1", **sans).stdout.strip(),
            "noninteractive|l|0|1",
        )

    def test_preflight_hors_mode_ne_touche_pas_sudo(self):
        self.assertEqual(self.lancer("el_sudo_preflight").returncode, 0)
        self.assertEqual(self.appels_sudo(), [])

    @unittest.skipIf(os.geteuid() == 0, "root passe sans sudo")
    def test_preflight_en_mode_sudo_sans_mot_de_passe(self):
        fait = self.lancer("el_sudo_preflight", EL_NON_INTERACTIVE="1")
        self.assertEqual(fait.returncode, 0)
        self.assertEqual(self.appels_sudo(), ["sudo -n true"])


@unittest.skipIf(os.geteuid() == 0, "root passe sans sudo")
class TestPreflightRefuse(BancShell):
    code_sudo = 1

    def test_sudo_qui_demanderait_un_mot_de_passe_arrete(self):
        fait = self.lancer("el_sudo_preflight", EL_NON_INTERACTIVE="1")
        self.assertEqual(fait.returncode, 1)
        self.assertIn("sudo -v", fait.stdout)
        self.assertIn("NOPASSWD", fait.stdout)


class TestKeepalive(BancShell):
    """Le faux sudo note ses appels et refuse : la boucle s'arrête au
    premier refus, sans attendre."""

    code_sudo = 1

    def test_hors_mode_rien_ne_tourne(self):
        self.lancer("el_sudo_keepalive; sleep 0.3")
        self.assertEqual(self.appels_sudo(), [])

    @unittest.skipIf(os.geteuid() == 0, "root passe sans sudo")
    def test_en_mode_le_ticket_est_rafraichi(self):
        self.lancer("el_sudo_keepalive; sleep 0.5", EL_NON_INTERACTIVE="1")
        self.assertEqual(self.appels_sudo(), ["sudo -n -v"])


class TestQuestionMise(unittest.TestCase):
    """el_mise_proposer quand mise est absent, l'architecture x86_64 et
    pyenv sans la version : la question serait posée."""

    def proposer(self, **env):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        bin_ = Path(tmp.name, "bin")
        bin_.mkdir()
        faux = bin_ / "uname"
        faux.write_text("#!/bin/sh\necho x86_64\n", encoding="utf-8")
        faux.chmod(0o755)
        # Un sudo qui refuse : le PATH système ne mène pas au vrai.
        sudo = bin_ / "sudo"
        sudo.write_text("#!/bin/sh\nexit 1\n", encoding="utf-8")
        sudo.chmod(0o755)
        milieu = environnement(**env)
        for variable in ("MISE_INSTALL_PATH", "EL_PYTHON_PROVIDER"):
            milieu.pop(variable, None)
        milieu.update(
            HOME=tmp.name,
            PYENV_ROOT=str(Path(tmp.name, "pyenv")),
            PATH=f"{bin_}:/usr/bin:/bin",
        )
        script = (
            ". ./script/install/lib_python_provider.sh\n"
            "el_mise_cmd() { return 1; }\n"
            "el_mise_poser() { echo POSE; }\n"
            "el_mise_proposer_permanent() { :; }\n"
            'el_mise_proposer 3.15.2; echo "rc=$?"'
        )
        return subprocess.run(
            ["bash", "-c", script],
            cwd=RACINE,
            env=milieu,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_reponse_manquante_arrete(self):
        fait = self.proposer(EL_NON_INTERACTIVE="1")
        self.assertIn("rc=3", fait.stdout)
        self.assertIn("EL_INSTALL_MISE", fait.stderr)

    def test_oui_pose_mise_sans_demander(self):
        fait = self.proposer(EL_NON_INTERACTIVE="1", EL_INSTALL_MISE="1")
        self.assertIn("POSE", fait.stdout)
        self.assertIn("rc=0", fait.stdout)

    def test_non_laisse_pyenv(self):
        fait = self.proposer(EL_NON_INTERACTIVE="1", EL_INSTALL_MISE="0")
        self.assertIn("rc=2", fait.stdout)
        self.assertNotIn("POSE", fait.stdout)

    def test_hors_mode_sans_terminal_rien_n_est_demande(self):
        fait = self.proposer()
        self.assertIn("rc=1", fait.stdout)


class TestQuestionsDesScripts(unittest.TestCase):
    def env_arch(self, arch, **extra):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        faux = Path(tmp.name, "uname")
        faux.write_text(f"#!/bin/sh\necho {arch}\n", encoding="utf-8")
        faux.chmod(0o755)
        env = environnement()
        env.pop("EL_ALLOW_UNSUPPORTED_ARCH", None)
        env.update(extra)
        env["PATH"] = f"{tmp.name}:{env['PATH']}"
        return env

    def test_architecture_non_supportee_sur_un_terminal(self):
        script = ". ./script/install/lib_arch_check.sh; el_arch_check"
        code, sortie = sur_terminal(
            script, self.env_arch("riscv64", EL_NON_INTERACTIVE="1")
        )
        self.assertEqual(code, 1)
        self.assertNotIn("[o/N]", sortie)
        self.assertIn("EL_ALLOW_UNSUPPORTED_ARCH=1", sortie)

    def test_architecture_non_supportee_autorisee(self):
        script = ". ./script/install/lib_arch_check.sh; el_arch_check"
        code, _ = sur_terminal(
            script,
            self.env_arch(
                "riscv64",
                EL_NON_INTERACTIVE="1",
                EL_ALLOW_UNSUPPORTED_ARCH="1",
            ),
        )
        self.assertEqual(code, 0)

    def test_mise_ne_demande_rien_en_mode(self):
        script = (
            ". ./script/install/lib_python_provider.sh; "
            "el_peut_demander && echo DEMANDE || echo MUET"
        )
        _, hors_mode = sur_terminal(script, environnement())
        _, en_mode = sur_terminal(
            script, environnement(EL_NON_INTERACTIVE="1")
        )
        self.assertIn("DEMANDE", hors_mode)
        self.assertIn("MUET", en_mode)

    def test_install_sh_installe_sans_demander(self):
        script = (
            "source <(sed -n '/^el_confirmer()/,/^}/p' install.sh); "
            'el_confirmer "Lancer ?"'
        )
        fait = subprocess.run(
            ["bash", "-c", script],
            cwd=RACINE,
            env=environnement(EL_NON_INTERACTIVE="1"),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        self.assertEqual(fait.returncode, 0)
        self.assertIn("EL_NON_INTERACTIVE=1", fait.stdout)
        sans_mode = subprocess.run(
            ["bash", "-c", script],
            cwd=RACINE,
            env=environnement(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
        )
        self.assertEqual(sans_mode.returncode, 1)


class TestBranchement(unittest.TestCase):
    """Le mode atteint chaque script, lu dans leur texte."""

    def lire(self, chemin):
        return (RACINE / chemin).read_text(encoding="utf-8")

    def test_install_dev_verifie_sudo_avant_tout(self):
        texte = self.lire("script/install/install_dev.sh")
        self.assertLess(
            texte.index("el_sudo_preflight || exit 1"),
            texte.index("el_arch_check || exit 1"),
        )
        self.assertLess(
            texte.index("el_non_interactive_env"),
            texte.index("install_debian_dependency.sh"),
        )

    def test_apt_passe_par_el_apt_get(self):
        texte = self.lire("script/install/install_debian_dependency.sh")
        self.assertIn('APT_GET="$(el_apt_get)"', texte)
        code = [
            ligne
            for ligne in texte.splitlines()
            if not ligne.lstrip().startswith("#")
        ]
        nues = [
            ligne for ligne in code if re.search(r"sudo apt(-get)? ", ligne)
        ]
        self.assertEqual(nues, [])

    def test_le_deb_local_passe_par_apt_get(self):
        texte = self.lire("script/install/install_debian_dependency.sh")
        self.assertIn('${APT_GET} install -y "./$(basename "${_url}")"', texte)
        code = [
            ligne
            for ligne in texte.splitlines()
            if not ligne.lstrip().startswith("#")
        ]
        # Ni appel ni paquet gdebi-core dans la liste apt.
        self.assertFalse(any("gdebi" in ligne for ligne in code))

    def test_ticket_sudo_garde_vivant(self):
        for chemin in (
            "script/install/install_dev.sh",
            "script/install/install_production.sh",
        ):
            texte = self.lire(chemin)
            with self.subTest(script=chemin):
                self.assertLess(
                    texte.index("el_sudo_preflight || exit 1"),
                    texte.index("el_sudo_keepalive"),
                )

    def test_poetry_sans_interaction(self):
        texte = self.lire("script/install/install_locally.sh")
        appels = re.findall(r'"\$\{POETRY_ODOO_PATH\}" install [^\n]*', texte)
        self.assertEqual(len(appels), 2)
        for appel in appels:
            self.assertIn("${POETRY_INTERACTION}", appel)

    def test_production_verifie_sudo_avant_le_premier(self):
        texte = self.lire("script/install/install_production.sh")
        premier_sudo = re.search(r"^sudo ", texte, re.M).start()
        self.assertLess(texte.index("el_sudo_preflight"), premier_sudo)
        lignes = re.findall(
            r'^[ \t]*sudo su \$\{EL_USER\} -c "[^\n]*', texte, re.M
        )
        self.assertEqual(len(lignes), 3)
        for ligne in lignes:
            self.assertIn("${EL_SU_ENV}", ligne)


if __name__ == "__main__":
    unittest.main()
