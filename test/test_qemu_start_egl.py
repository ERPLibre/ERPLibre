#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une 3D écrite dans la définition d'une VM se met à l'épreuve au démarrage.

Le nœud de rendu peut exister sans qu'EGL y démarre : QEMU refuse alors le
domaine, et la VM reste inutilisable tant que quelqu'un ne défait pas le
réglage. Rien ne permet de le savoir avant l'essai — la création a déjà son
repli, le réglage d'une VM existante avait besoin du sien.

Ce que ces tests gardent :

- l'échec EGL est reconnu au démarrage et le retrait est proposé ;
- le retrait ne touche QUE la 3D : passer « autostart » à None l'éteindrait,
  et « heads » ferait naître une étape sans rapport ;
- un échec de démarrage qui n'est pas celui d'EGL n'est pas rattrapé.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_hardware as hw  # noqa: E402
from script.todo.todo import TODO  # noqa: E402

SORTIE_EGL = (
    "error: erreur interne : le processus s'est arrêté pendant la connexion"
    " au moniteur: qemu-system-x86_64: egl: eglInitialize failed:"
    " EGL_NOT_INITIALIZED\n"
    "qemu-system-x86_64: egl: render node init failed"
)
SORTIE_AUTRE = (
    "error: Failed to start domain: internal error:"
    " qemu unexpectedly closed"
)

ETAT = {
    "name": "vm-a",
    "vcpus": 16,
    "mem_mib": 32768,
    "video": "virtio",
    "accel3d": True,
    "egl": True,
    "render": "/dev/dri/renderD128",
    "screen": True,
    "heads": 1,
    "cpu": "",
    "net": "default",
    "autostart": True,
}


class LaSignature(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_it_recognises_the_egl_failure(self):
        self.assertTrue(self.todo._qemu_egl_failed(SORTIE_EGL))

    def test_it_ignores_another_failure(self):
        self.assertFalse(self.todo._qemu_egl_failed(SORTIE_AUTRE))

    def test_an_unloadable_module_does_not_raise(self):
        """Le menu ne doit pas tomber parce que la source de vérité manque."""
        self.todo._qemu_import_module = mock.Mock(side_effect=OSError("x"))
        self.assertFalse(self.todo._qemu_egl_failed(SORTIE_EGL))


class LeRetrait(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.lances = []
        self.todo.execute = mock.MagicMock()
        self.todo.execute.exec_command_live.side_effect = (
            lambda cmd, **k: self.lances.append(cmd) or 0
        )
        self.todo._qemu_dumpxml = lambda n, **k: "<domain/>"
        self.todo._qemu_autostart = lambda n: True
        self.todo._qemu_import_module = lambda: _FauxModule()

    def _lancer(self, sortie, reponse="o"):
        with mock.patch.object(hw, "hw_state", return_value=dict(ETAT)):
            with mock.patch("builtins.input", return_value=reponse):
                with mock.patch("builtins.print"):
                    self.todo._qemu_start_failed(
                        "vm-a", "virsh start vm-a", sortie
                    )
        return self.lances

    def test_another_failure_is_left_alone(self):
        self.assertEqual([], self._lancer(SORTIE_AUTRE))

    def test_a_refusal_changes_nothing(self):
        self.assertEqual([], self._lancer(SORTIE_EGL, reponse="n"))

    def test_it_removes_the_3d_then_starts_again(self):
        lances = self._lancer(SORTIE_EGL)
        joint = " ".join(lances)
        self.assertIn("accel3d=off", joint)
        self.assertIn("--remove-device --graphics type=egl-headless", joint)
        # Le démarrage revient EN DERNIER : le retrait doit être écrit avant.
        self.assertEqual("virsh start vm-a", lances[-1])

    def test_it_touches_only_the_3d(self):
        """Le test précédent passerait même si le retrait éteignait aussi le
        démarrage automatique : c'est ce que fait « autostart » à None, et
        seul un contrôle sur les commandes RÉELLEMENT lancées l'attrape."""
        lances = self._lancer(SORTIE_EGL)
        # TOUT ce qui précède le démarrage, sans filtrer sur l'outil : la
        # commande d'autostart passe par virsh et non par virt-xml, donc un
        # filtre sur « virt-xml » laisserait justement passer la fautive.
        retraits = lances[:-1]
        self.assertEqual(2, len(retraits), retraits)
        joint = " ".join(retraits)
        self.assertNotIn("--disable", joint)
        self.assertNotIn("autostart", joint)
        self.assertNotIn("model.heads", joint)


class LeRapport3D(unittest.TestCase):
    """Ce que l'hôte doit fournir pour qu'une 3D de VM démarre.

    Deux briques distinctes : « egl-headless » ouvre le nœud et crée le
    contexte EGL par GBM — c'est Mesa qui répond — et virglrenderer ne sert
    qu'ENSUITE. Les chercher par fichier plutôt que par paquet : les noms de
    paquets changent d'une distribution à l'autre, pas les emplacements.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_host_gpu_node = lambda: "/dev/dri/renderD128"

    def _rendu(self, presents):
        self.todo._qemu_lib_present = lambda motif: (
            f"/usr/lib/{motif}.0" if motif in presents else ""
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.todo._qemu_gpu_3d_report()
        return buf.getvalue()

    def test_it_names_the_two_bricks(self):
        """virglrenderer sans EGL ne sert à rien : les deux se lisent."""
        rendu = self._rendu(set())
        self.assertIn("virglrenderer", rendu)
        self.assertIn("libEGL.so", rendu)
        self.assertIn("ui-egl-headless.so", rendu)

    def test_a_missing_piece_is_marked(self):
        rendu = self._rendu({"libgbm.so"})
        lignes = [l for l in rendu.splitlines() if "libgbm" in l]
        self.assertTrue(lignes and lignes[0].strip().startswith("✅"))
        manquant = [l for l in rendu.splitlines() if "virglrenderer" in l]
        self.assertTrue(manquant[0].strip().startswith("❌"))

    def test_it_says_the_node_alone_proves_nothing(self):
        """Le nœud existe dans le cas qui échoue : le rapport doit donc
        proposer d'éprouver EGL, pas se contenter de le lister."""
        rendu = self._rendu(set())
        self.assertIn("/dev/dri/renderD128", rendu)
        self.assertIn("eglinfo", rendu)

    def test_it_changes_nothing(self):
        """Un rapport qui installerait quoi que ce soit ne serait plus un
        rapport."""
        self.todo.execute = mock.MagicMock()
        self._rendu(set())
        self.todo.execute.exec_command_live.assert_not_called()


class _FauxModule:
    """deploy_qemu réduit à ce que le menu lui demande."""

    @staticmethod
    def egl_failed(sortie):
        return "eglInitialize failed" in (sortie or "")


if __name__ == "__main__":
    unittest.main()
