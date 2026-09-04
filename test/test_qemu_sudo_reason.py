#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Pourquoi le déploiement demande un mot de passe, dit AVANT de le demander.

sudo n'explique jamais ce qu'il sert à faire : son invite tombe entre deux
lignes de journal, et on la subit sans savoir si elle porte sur libvirt, sur
un paquet ou sur un fichier. Appartenir au groupe libvirt ne suffit pas à
s'en passer, et la raison n'est pas libvirt : le déploiement écrit le disque
et le seed dans le pool de libvirt, un répertoire de root où le groupe ne
donne aucun droit d'écriture.

Ce que ces tests gardent :

- la raison est CONSTATÉE, jamais supposée : l'écriture d'un répertoire se
  teste, elle ne se déduit pas de son mode — une ACL peut l'accorder là où
  « drwxr-xr-x root root » semble la refuser ;
- l'explication précède la commande, et ne se répète pas ;
- root ne s'entend rien annoncer : aucune invite ne viendra ;
- les faits ont UNE source, deploy_qemu, et deux rendus — le français du
  script et les deux langues du menu.
"""

import importlib.util
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

RACINE = Path(__file__).resolve().parents[1]


def _deploy_qemu():
    path = RACINE / "script/qemu/deploy_qemu.py"
    spec = importlib.util.spec_from_file_location("deploy_qemu", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


DQ = _deploy_qemu()

PAS_ROOT = os.geteuid() != 0


class LeConstat(unittest.TestCase):
    def test_a_writable_directory_needs_nothing(self):
        with tempfile.TemporaryDirectory() as chemin:
            self.assertIsNone(DQ.repertoire_a_root(Path(chemin)))

    @unittest.skipUnless(PAS_ROOT, "root écrit partout")
    def test_a_directory_closed_to_writing_is_reported_with_its_mode(self):
        """Le mode et le propriétaire ne sont lus qu'APRÈS le test d'écriture,
        et servent à dire au lecteur ce qui bloque."""
        with tempfile.TemporaryDirectory() as chemin:
            os.chmod(chemin, 0o500)
            try:
                vu = DQ.repertoire_a_root(Path(chemin))
            finally:
                os.chmod(chemin, 0o700)
        self.assertIsNotNone(vu)
        self.assertEqual(chemin, vu[0])
        self.assertIn(":", vu[1])
        self.assertTrue(vu[2].startswith("d"), vu[2])

    def test_a_missing_directory_says_nothing(self):
        """Le déploiement le créera, et c'est son parent qui décide alors."""
        self.assertIsNone(DQ.repertoire_a_root(Path("/nexiste/pas/ici")))

    def test_the_default_pool_is_named_once(self):
        """Deux écritures du même chemin divergent dès qu'on en change une :
        argparse et le constat doivent lire la même constante."""
        parser = DQ.build_parser()
        args = parser.parse_args(["--distro", "ubuntu", "--hostname", "vm"])
        self.assertEqual(DQ.DEFAULT_DISK_DIR, args.disk_dir)
        self.assertEqual(DQ.DEFAULT_IMAGE_DIR, args.image_dir)
        self.assertEqual(DQ.DEFAULT_IMAGE_DIR, args.seed_dir)


class LesFaits(unittest.TestCase):
    def test_the_socket_is_always_probed(self):
        """Ce que le groupe libvirt couvre RÉELLEMENT se teste en essayant :
        y figurer et en disposer dans la session courante sont deux choses."""
        with mock.patch.object(DQ, "libvirt_ready", return_value=True):
            faits = DQ.sudo_facts()
        self.assertIn(("socket", ("ok",)), faits)

    @unittest.skipUnless(PAS_ROOT, "root écrit partout")
    def test_a_closed_directory_becomes_a_fact(self):
        with tempfile.TemporaryDirectory() as chemin:
            os.chmod(chemin, 0o500)
            try:
                with mock.patch.object(DQ, "libvirt_ready", return_value=True):
                    faits = DQ.sudo_facts(Path(chemin), Path(chemin))
            finally:
                os.chmod(chemin, 0o700)
        ecritures = [v for cle, v in faits if cle == "ecriture"]
        # Le même répertoire deux fois ne se dit qu'une.
        self.assertEqual(1, len(ecritures))
        self.assertEqual(chemin, ecritures[0][0])

    def test_a_missing_virsh_does_not_accuse_the_group(self):
        """Sans virsh il n'y a rien à joindre : dire « la socket ne répond
        pas » ferait chercher un droit là où il manque un paquet."""
        with mock.patch.object(DQ.shutil, "which", return_value=None):
            faits = DQ.sudo_facts()
        self.assertIn(("socket", ("absent",)), faits)
        self.assertNotIn("ne répond pas", " ".join(DQ.sudo_lignes(faits)))


class LeRenduDuScript(unittest.TestCase):
    def test_it_names_the_directory_and_what_the_group_does_not_cover(self):
        faits = [
            (
                "ecriture",
                ("/var/lib/libvirt/images", "root:root", "drwxr-xr-x"),
            ),
            ("socket", ("ok",)),
        ]
        texte = " ".join(DQ.sudo_lignes(faits))
        self.assertIn("/var/lib/libvirt/images", texte)
        self.assertIn("root:root", texte)
        self.assertIn("groupe libvirt", texte)

    def test_without_a_directory_it_names_the_system_steps(self):
        """Sans répertoire fermé, le mot de passe reste dû aux gestes système
        — dire « écrire dans » serait faux."""
        texte = " ".join(DQ.sudo_lignes([("socket", ("ok",))]))
        self.assertIn("gestes système", texte)
        self.assertNotIn("écrire dans", texte)

    def test_a_silent_socket_is_said_too(self):
        """Le cas du groupe déclaré mais absent de la session : la table dit
        ce qui est DÉCLARÉ, l'essai dit ce dont la session DISPOSE."""
        texte = " ".join(DQ.sudo_lignes([("socket", ("non",))]))
        self.assertIn("ne répond pas non plus sans sudo", texte)


class LAnnonceAvantLInvite(unittest.TestCase):
    def _lancer(self, appels=2):
        runner = DQ.Runner(use_sudo=True, dry_run=True)
        with mock.patch.object(
            DQ,
            "sudo_facts",
            return_value=[
                ("ecriture", ("/var/lib/libvirt/images", "root:root", "drwx")),
                ("socket", ("ok",)),
            ],
        ):
            with redirect_stdout(io.StringIO()) as sortie:
                for _ in range(appels):
                    runner.run(["qemu-img", "resize", "x"], privileged=True)
        return sortie.getvalue()

    def test_the_reason_comes_before_the_command(self):
        """Après l'invite, l'explication n'explique plus rien : le mot de
        passe est déjà tapé."""
        texte = self._lancer(appels=1)
        self.assertLess(
            texte.index("sudo va demander"), texte.index("qemu-img")
        )

    def test_it_is_said_once_for_the_whole_run(self):
        """sudo garde sa réponse quelques minutes ; répéter l'explication à
        chaque étape noierait le journal."""
        self.assertEqual(1, self._lancer(appels=3).count("sudo va demander"))

    def test_nothing_is_said_where_nothing_is_prefixed(self):
        runner = DQ.Runner(use_sudo=False, dry_run=True)
        with redirect_stdout(io.StringIO()) as sortie:
            runner.run(["qemu-img", "resize", "x"], privileged=True)
        self.assertNotIn("sudo", sortie.getvalue())


class LeRenduDuMenu(unittest.TestCase):
    """Le récapitulatif parle deux langues, le script une seule."""

    def _lignes(self, faits, euid=1000):
        todo = TODO.__new__(TODO)
        module = mock.MagicMock()
        module.sudo_facts.return_value = faits
        with mock.patch.object(
            TODO, "_qemu_import_module", return_value=module
        ), mock.patch.object(os, "geteuid", return_value=euid):
            return todo._qemu_sudo_lines()

    def test_root_is_told_nothing(self):
        """Aucune invite ne viendra : annoncer une question qui ne se posera
        pas est pire que se taire."""
        self.assertEqual([], self._lignes([("socket", ("ok",))], euid=0))

    def test_the_directory_and_its_rights_are_shown(self):
        lignes = self._lignes(
            [
                ("ecriture", ("/var/lib/libvirt/images", "root:root", "drwx")),
                ("socket", ("ok",)),
            ]
        )
        texte = " ".join(lignes)
        self.assertIn("/var/lib/libvirt/images", texte)
        self.assertIn("root:root", texte)
        self.assertIn("drwx", texte)

    def test_a_silent_socket_is_reported(self):
        lignes = self._lignes([("socket", ("non",))])
        self.assertTrue(
            any(
                t(
                    "the libvirt socket does not answer without sudo either:"
                    " group absent from this session, or libvirt not started"
                )
                == ligne
                for ligne in lignes
            ),
            lignes,
        )

    def test_an_unreadable_module_says_nothing(self):
        """Le récapitulatif ne doit pas tomber parce qu'un module ne se charge
        pas : c'est la page qu'on relit avant de créer des disques."""
        todo = TODO.__new__(TODO)
        with mock.patch.object(
            TODO, "_qemu_import_module", side_effect=OSError("absent")
        ), mock.patch.object(os, "geteuid", return_value=1000):
            self.assertEqual([], todo._qemu_sudo_lines())

    def test_every_sentence_is_translated(self):
        """Une clé absente du dictionnaire ressortirait en anglais au milieu
        d'un récapitulatif français."""
        for cle in (
            "sudo password: asked when the deployment starts",
            "write into %s — checked: %s %s, writing refused here",
            "the libvirt group opens the qemu:///system socket, not this"
            " directory",
            "the system steps of the script (service, group)",
        ):
            with self.subTest(cle=cle[:40]):
                self.assertNotEqual(cle, t(cle))


if __name__ == "__main__":
    unittest.main()
