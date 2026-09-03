#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un nœud de rendu présent ne prouve pas que la 3D marche.

QEMU refuse de démarrer le domaine quand EGL ne s'initialise pas sur le nœud,
et il le dit seulement à ce moment-là : « egl: eglInitialize failed:
EGL_NOT_INITIALIZED », puis « egl: render node init failed ». La détection ne
voit qu'un fichier dans /dev/dri, et aucun test préalable ne distingue un GPU
utilisable d'un nœud qui existe sans pile EGL.

Ce que ces tests gardent :

- une VM graphique naît quand même, en rendu logiciel, plutôt que d'échouer ;
- le domaine de l'essai raté est retiré avant la seconde tentative, sinon le
  nom est pris et la VM reste celle qui ne démarre pas ;
- « --gpu on » est une exigence : elle n'est pas trahie en silence ;
- un échec qui n'est PAS celui d'EGL n'est pas rattrapé.
"""

import importlib.util
import io
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.argv = ["todo.py"]
RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

SORTIE_EGL = (
    "ERROR    erreur interne : le processus s'est arrêté pendant la"
    " connexion au moniteur: qemu-system-x86_64: egl: eglInitialize failed:"
    " EGL_NOT_INITIALIZED\n"
    "qemu-system-x86_64: egl: render node init failed\n"
)
SORTIE_AUTRE = "ERROR    Unknown OS name 'ubuntu99.04'\n"


class Signature(unittest.TestCase):
    def test_it_recognises_the_egl_failure(self):
        self.assertTrue(DQ.egl_failed(SORTIE_EGL))

    def test_it_does_not_recognise_another_failure(self):
        self.assertFalse(DQ.egl_failed(SORTIE_AUTRE))
        self.assertFalse(DQ.egl_failed(""))


class Repli(unittest.TestCase):
    """virt_install avec un GPU détecté, dont EGL ne démarre pas."""

    def _args(self, gpu="auto"):
        return SimpleNamespace(
            name="vm-a",
            memory=4096,
            vcpus=2,
            arch="amd64",
            network="network=default,model=virtio",
            graphics="none",
            desktop=True,
            gpu=gpu,
            gpu_node="/dev/dri/renderD128",
            attach_console=False,
            bios=False,
        )

    def _lancer(self, gpu="auto", sortie=SORTIE_EGL, code=1):
        """Rend (commandes lancées, SystemExit ou None)."""
        lances = []

        class FauxRunner:
            dry_run = False
            use_sudo = False

            def run(self, cmd, *, privileged=False, check=True, capture=False):
                lances.append(list(cmd))
                if capture:
                    return (code, sortie)
                return None

        with mock.patch.object(
            DQ, "host_arch", return_value="amd64"
        ), mock.patch.object(
            DQ, "kvm_available", return_value=True
        ), mock.patch.object(
            DQ, "os"
        ) as faux_os:
            faux_os.getuid.return_value = 1000
            faux_os.makedirs.return_value = None
            buf = io.StringIO()
            with redirect_stdout(buf):
                try:
                    DQ.virt_install(
                        self._args(gpu),
                        Path("/tmp/d.qcow2"),
                        Path("/tmp/s.iso"),
                        "ubuntu26.04",
                        FauxRunner(),
                    )
                    sortie_exc = None
                except SystemExit as exc:
                    sortie_exc = exc
        return lances, sortie_exc, buf.getvalue()

    def test_the_first_attempt_carries_the_3d(self):
        lances, _, _ = self._lancer()
        self.assertIn("model.acceleration.accel3d=on", " ".join(lances[0]))

    def test_a_second_attempt_runs_without_the_3d(self):
        lances, exc, rendu = self._lancer()
        self.assertIsNone(exc, rendu)
        dernier = " ".join(lances[-1])
        self.assertNotIn("accel3d", dernier)
        self.assertNotIn("egl-headless", dernier)
        # L'écran doit revenir : une VM graphique sans --video n'en a plus.
        self.assertIn("--video virtio", dernier)

    def test_the_failed_domain_is_undefined_first(self):
        """Sans ce retrait, virt-install refuse le nom déjà pris et la VM
        reste celle qui ne démarre pas."""
        lances, _, _ = self._lancer()
        milieu = " ".join(lances[1])
        self.assertIn("undefine", milieu)
        self.assertIn("vm-a", milieu)
        self.assertLess(1, len(lances) - 1)

    def test_gpu_on_also_falls_back_but_says_so(self):
        """Une VM qu'on n'a pas est pire qu'une VM sans 3D. Le repli vaut donc
        aussi pour une 3D demandée — à condition de nommer ce qui manque, sans
        quoi l'utilisateur croirait avoir obtenu ce qu'il a coché."""
        lances, exc, rendu = self._lancer(gpu="on")
        self.assertIsNone(exc, rendu)
        self.assertIn("DEMANDÉE", rendu)
        self.assertNotIn("accel3d", " ".join(lances[-1]))

    def test_another_failure_is_not_retried(self):
        lances, exc, _ = self._lancer(sortie=SORTIE_AUTRE)
        self.assertIsInstance(exc, SystemExit)
        self.assertEqual(1, len(lances))

    def _sans_ecran(self, resultat):
        """virt_install sur une VM sans console dont la 3D est demandée.

        `resultat` est ce que rend le runner en mode capture. Rend les
        commandes lancées."""
        args = self._args(gpu="on")
        args.desktop = False
        lances = []

        class FauxRunner:
            dry_run = False
            use_sudo = False

            def run(self, cmd, *, privileged=False, check=True, capture=False):
                lances.append(list(cmd))
                return resultat if capture else None

        with mock.patch.object(
            DQ, "host_arch", return_value="amd64"
        ), mock.patch.object(
            DQ, "kvm_available", return_value=True
        ), mock.patch.object(
            DQ, "os"
        ) as faux_os:
            faux_os.getuid.return_value = 1000
            with redirect_stdout(io.StringIO()):
                DQ.virt_install(
                    args,
                    Path("/tmp/d.qcow2"),
                    Path("/tmp/s.iso"),
                    "ubuntu26.04",
                    FauxRunner(),
                )
        return lances

    def test_a_screenless_3d_vm_keeps_egl_as_its_only_display(self):
        """« --graphics none » dit « aucun affichage » : le poser à côté d'un
        egl-headless, qui EST un affichage, se contredit."""
        rendu = " ".join(self._sans_ecran((0, ""))[0])
        self.assertIn("egl-headless", rendu)
        self.assertNotIn("--graphics none", rendu)

    def test_dropping_the_3d_gives_the_display_back(self):
        """Le repli doit rendre le « --graphics none » écarté pour la 3D,
        sinon la VM repart sur le défaut de virt-install."""
        dernier = " ".join(self._sans_ecran((1, SORTIE_EGL))[-1])
        self.assertIn("--graphics none", dernier)
        self.assertNotIn("egl-headless", dernier)

    def test_a_success_never_retries(self):
        lances, exc, _ = self._lancer(sortie="", code=0)
        self.assertIsNone(exc)
        self.assertEqual(1, len(lances))


if __name__ == "__main__":
    unittest.main()
