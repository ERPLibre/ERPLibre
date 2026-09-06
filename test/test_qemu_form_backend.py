#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le backend traverse le formulaire, et le déploiement refuse l'inconnu.

Trois pièces qui n'ont de sens qu'ensemble : l'écran DIT quel backend est
employé — il ne le choisit pas, ce chemin n'en pilote qu'un —, la spec le
porte, et le point de passage du déploiement s'arrête sur ce qu'il ne sait
pas piloter.

Ce refus est INATTEIGNABLE par l'écran d'aujourd'hui, et c'est voulu : il
attend celui de demain. Il s'éprouve donc directement, sinon rien ne le
tiendrait jusque-là.
"""

import os
import sys
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.todo.deploy_form_lib import build_spec  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.vm import backend as VM  # noqa: E402

# Le dict minimal que `build_spec` exige en accès direct.
FORM = {
    "res_label": "x1",
    "ssh_key": "",
    "install": None,
    "add_ssh_config": False,
    "parallelism": 1,
}

VM_UNE = {
    "distro": "ubuntu",
    "version": "24.04",
    "arch": "amd64",
    "name": "essai",
    "ram": 4096,
    "vcpus": 2,
    "disk": "30G",
}


class TestLaSpecLeTransporte(unittest.TestCase):
    def test_a_spec_without_a_backend_means_the_local_one(self):
        """Les invites en ligne n'en posent pas : leur spec doit rester
        valide, et valoir ce qu'elle a toujours valu."""
        self.assertEqual(VM.LIBVIRT, build_spec([], [], FORM)["backend"])

    def test_what_the_form_says_reaches_the_spec(self):
        """Une clé que `build_spec` ne recopie pas n'atteint jamais la
        spec — c'est déjà arrivé au choix de suivi."""
        spec = build_spec([], [], dict(FORM, backend=VM.LIMA))
        self.assertEqual(VM.LIMA, spec["backend"])

    def test_it_sits_at_deployment_level_and_not_inside_install(self):
        """Dans « install », il disparaîtrait dès qu'on décoche la case,
        emportant le choix de machine avec ce qu'on installe dedans."""
        spec = build_spec([], [], dict(FORM, backend=VM.LIBVIRT))
        self.assertIn("backend", spec)
        self.assertIsNone(spec["install"])


class TestLeDeploiementRefuseCeQuIlNePiloteRas(unittest.TestCase):
    """Laisser passer produirait un déploiement local sous un faux nom, ou
    une exception au milieu du travail."""

    def parts(self, backend):
        menu = TODO.__new__(TODO)
        spec = build_spec([VM_UNE], [], dict(FORM, backend=backend))
        return menu._qemu_deploy_parts_for(VM_UNE, spec, dry_run=True)

    def test_the_local_backend_goes_through(self):
        """Contrôle positif : refuser tout n'empêcherait rien d'utile."""
        parts = self.parts(VM.LIBVIRT)
        self.assertTrue(parts)
        self.assertIn("essai", " ".join(str(p) for p in parts))

    def test_a_spec_with_no_backend_at_all_goes_through(self):
        menu = TODO.__new__(TODO)
        spec = build_spec([VM_UNE], [], FORM)
        del spec["backend"]
        self.assertTrue(menu._qemu_deploy_parts_for(VM_UNE, spec, True))

    def test_any_other_backend_is_refused_by_name(self):
        for backend in (VM.PVE, VM.LIMA, "jamais-un-backend"):
            with self.subTest(backend=backend):
                with self.assertRaises(VM.VerbNotImplemented) as pris:
                    self.parts(backend)
                self.assertIn(backend, str(pris.exception))

    def test_the_refusal_names_what_this_path_does_drive(self):
        """Un refus qui ne dit pas ce qui marcherait est un cul-de-sac."""
        with self.assertRaises(VM.VerbNotImplemented) as pris:
            self.parts(VM.LIMA)
        self.assertIn(VM.LIBVIRT, str(pris.exception))


class TestLEcranDitSansChoisir(unittest.TestCase):
    def test_the_form_reads_the_backend_from_the_context(self):
        """D'aucun widget : offrir une main qu'on ne peut pas jouer vaut
        moins qu'un choix absent."""
        source = open(
            os.path.join(RACINE, "script", "todo", "qemu_deploy_form.py"),
            encoding="utf-8",
        ).read()
        self.assertIn('"backend": ctx.get("backend"', source)
        self.assertNotIn('"#f_backend"', source)

    def test_the_context_resolves_it_before_the_screen_opens(self):
        """Une sonde du PATH pendant que l'écran affiche n'a pas sa place."""
        source = open(
            os.path.join(RACINE, "script", "todo", "qemu_deploy.py"),
            encoding="utf-8",
        ).read()
        debut = source.index("    def _qemu_form_context(self, mod):")
        fin = source.index("\n    def ", debut + 1)
        self.assertIn(
            '"backend": vm_backend_choice.effective(', source[debut:fin]
        )


if __name__ == "__main__":
    unittest.main()
