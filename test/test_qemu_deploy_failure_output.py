#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une création de VM ratée doit montrer le message de l'outil.

La sortie de virt-install est capturée en mémoire puis jetée après la boucle :
si elle ne s'affiche pas à ce moment-là, elle n'existe plus nulle part. Quatre
lignes ne suffisent pas — l'épilogue « Échec de la commande » et sa ligne de
commande les occupent entièrement, et le message de l'outil tombe juste
au-dessus de la fenêtre.

Ce que ces tests gardent :

- une VM qui réussit reste discrète, une qui échoue montre assez pour être
  diagnostiquée ;
- la sortie complète d'un échec atterrit dans un fichier, seule trace qui
  survit à l'écran ;
- un journal qu'on ne peut pas écrire ne fait pas échouer le déploiement.
"""

import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402

# Forme réelle d'un échec : le message de l'outil, puis l'épilogue qui occupe
# à lui seul les quatre dernières lignes.
SORTIE_ECHEC = "\n".join(
    [f"  bruit {i}" for i in range(20)]
    + [
        "ERROR    Le message de virt-install qui explique tout",
        "  virsh --connect qemu:///system start la-vm",
        "  sinon, recommencer l'installation.",
        "Échec de la commande (code 1) :",
        "  env XDG_CACHE_HOME=/var/tmp/x virt-install --connect …",
    ]
)


class FailureOutput(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def _lancer(self, rc, sortie):
        """Rend ce que le déploiement affiche pour un job au code `rc`."""
        jobs = [(1, "la-vm", ["/bin/true"])]

        class Res:
            returncode = rc
            stdout = sortie
            stderr = ""

        with mock.patch(
            "script.todo.qemu_deploy.subprocess.run", return_value=Res()
        ), mock.patch.object(
            self.todo, "_fmt_dur", return_value="1s"
        ), mock.patch.object(
            self.todo, "_qemu_save_failure_log", return_value="/tmp/x.log"
        ):
            buf = io.StringIO()
            with redirect_stdout(buf):
                self.todo._qemu_deploy_jobs_cli(jobs, 1)
        return buf.getvalue()

    def test_a_failure_shows_the_tool_message(self):
        """La régression même : avec quatre lignes, cette ligne manquait."""
        rendu = self._lancer(1, SORTIE_ECHEC)
        self.assertIn("Le message de virt-install qui explique tout", rendu)

    def test_a_failure_names_the_full_log(self):
        rendu = self._lancer(1, SORTIE_ECHEC)
        self.assertIn("/tmp/x.log", rendu)

    def test_a_success_stays_terse(self):
        """Sans quoi trente lignes par VM réussie noieraient un lot de dix."""
        rendu = self._lancer(0, SORTIE_ECHEC)
        self.assertNotIn("bruit 0", rendu)
        corps = [
            ln
            for ln in rendu.splitlines()
            if ln.startswith("    ") and ln.strip()
        ]
        self.assertLessEqual(len(corps), 4, corps)

    def test_a_3d_failure_names_the_way_out(self):
        """« --gpu off » n'est pas dans le menu : si le rapport ne le nomme
        pas, un hôte incompatible avec la 3D n'a aucune issue depuis TODO."""
        rendu = self._lancer(1, SORTIE_ECHEC + "\n  --video accel3d=on")
        self.assertIn("--gpu off", rendu)

    def test_a_failure_without_3d_stays_silent_about_it(self):
        rendu = self._lancer(1, SORTIE_ECHEC)
        self.assertNotIn("--gpu off", rendu)

    def test_an_unwritable_log_does_not_break_the_deploy(self):
        """Perdre le journal ne doit pas faire perdre le déploiement."""
        with mock.patch(
            "script.todo.qemu_install_monitor.session_dir",
            side_effect=OSError("disque plein"),
        ):
            chemin = self.todo._qemu_save_failure_log("la-vm", "peu importe")
        self.assertIsNone(chemin)

    def test_the_log_name_survives_a_hostile_vm_name(self):
        """Le nom de VM vient de l'utilisateur : il ne doit pas composer un
        chemin hors du répertoire de session."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch(
                "script.todo.qemu_install_monitor.session_dir",
                return_value=Path(tmp),
            ):
                chemin = self.todo._qemu_save_failure_log("../../evil vm", "x")
        self.assertIsNotNone(chemin)
        self.assertEqual(chemin.parent, Path(tmp))
        self.assertNotIn("/", chemin.name.replace("-create.log", ""))


if __name__ == "__main__":
    unittest.main()
