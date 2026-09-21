#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Ce que la machine EST, décidé sans dépendre de la machine qui teste.

L'ordre des épreuves de détection est le contrat : un nœud Proxmox porte
« ID=debian » dans son os-release, et le sonder après Debian le classerait
Debian et lui proposerait un menu qui ne s'applique pas à lui.

Aucune de ces épreuves ne lance de sous-processus ni ne lit le vrai
« /etc/os-release » : les deux coutures d'environnement du module rendent la
détection décidable depuis n'importe quelle station.
"""

import io
import os
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from test.devstack_harness import PIEGE, ShimDir  # noqa: E402

from script.todo import devstack_report as R  # noqa: E402
from script.todo import host_os as H  # noqa: E402


class HoteCase(unittest.TestCase):
    """Chaque épreuve part d'un environnement sans couture ni override."""

    def setUp(self):
        for var in (H.HOST_OS_VAR, H.OS_RELEASE_VAR):
            self.addCleanup(os.environ.pop, var, None)
            os.environ.pop(var, None)
        self.addCleanup(
            setattr, H, "_override_fautif_dit", H._override_fautif_dit
        )
        H._override_fautif_dit = False
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def os_release(self, contenu):
        """Pose un os-release de banc et le déclare au module."""
        chemin = os.path.join(self.tmp.name, "os-release")
        with io.open(chemin, "w", encoding="utf-8") as handle:
            handle.write(contenu)
        os.environ[H.OS_RELEASE_VAR] = chemin
        return chemin

    def sans_proxmox(self):
        """Neutralise les deux indices de Proxmox, absents d'une station."""
        return patch.multiple(
            H, PROXMOX_INDICES=(), PROXMOX_BINAIRE="pveversion-absent"
        )


class TestLOrdreDeDetection(HoteCase):
    def test_darwin_is_macos_whatever_the_os_release_says(self):
        self.os_release("ID=debian\n")
        with patch.object(os, "uname") as uname:
            uname.return_value.sysname = "Darwin"
            self.assertEqual(H.MACOS, H.host_os())

    def test_proxmox_is_probed_before_debian(self):
        """Un nœud PVE porte « ID=debian » : l'ordre inverse le classerait
        Debian et lui proposerait un menu qui ne le concerne pas."""
        self.os_release("ID=debian\nVERSION_CODENAME=trixie\n")
        indice = os.path.join(self.tmp.name, "pve")
        os.mkdir(indice)
        with patch.object(H, "PROXMOX_INDICES", (indice,)):
            self.assertEqual(H.PROXMOX, H.host_os())
        # Contrôle positif : sans l'indice, le MÊME os-release rend Debian.
        with self.sans_proxmox():
            self.assertEqual(H.DEBIAN, H.host_os())

    def test_the_proxmox_binary_is_an_indice_too(self):
        self.os_release("ID=debian\n")
        with ShimDir(nu=True, pveversion="exit 0") as shim:
            with patch.dict(os.environ, {"PATH": shim.path()}):
                with patch.object(H, "PROXMOX_INDICES", ()):
                    self.assertEqual(H.PROXMOX, H.host_os())

    def test_the_known_ids(self):
        attendus = {
            "debian": H.DEBIAN,
            "ubuntu": H.DEBIAN,
            "raspbian": H.DEBIAN,
            "arch": H.ARCH,
            "manjaro": H.ARCH,
            "cachyos": H.ARCH,
        }
        self.assertTrue(attendus, "aucun cas : rien n'est prouvé")
        for identifiant, jeton in attendus.items():
            with self.subTest(id=identifiant):
                self.os_release("ID=%s\n" % identifiant)
                with self.sans_proxmox():
                    self.assertEqual(jeton, H.host_os())

    def test_id_like_catches_a_derivative(self):
        self.os_release('ID=pop\nID_LIKE="ubuntu debian"\n')
        with self.sans_proxmox():
            self.assertEqual(H.DEBIAN, H.host_os())

    def test_an_unnamed_system_is_unknown_and_not_a_failure(self):
        self.os_release("ID=plan9\n")
        with self.sans_proxmox():
            self.assertEqual(H.UNKNOWN, H.host_os())

    def test_a_missing_os_release_is_an_answer_not_a_crash(self):
        os.environ[H.OS_RELEASE_VAR] = os.path.join(self.tmp.name, "absent")
        with self.sans_proxmox():
            self.assertEqual(H.UNKNOWN, H.host_os())
        self.assertEqual({}, H.os_release())


class TestOsReleaseSeLitSansSExecuter(HoteCase):
    def test_it_reads_the_fields_it_is_given(self):
        self.os_release('ID=debian\nPRETTY_NAME="Debian GNU/Linux"\n')
        champs = H.os_release()
        self.assertEqual("debian", champs["ID"])
        self.assertEqual("Debian GNU/Linux", champs["PRETTY_NAME"])

    def test_it_never_executes_the_file(self):
        """C'est un fichier de configuration, pas un script."""
        temoin = os.path.join(self.tmp.name, "temoin")
        self.os_release("ID=debian\nX=$(touch %s)\n" % temoin)
        H.os_release()
        self.assertFalse(os.path.exists(temoin))


class TestLaCoutureDOverride(HoteCase):
    def test_a_known_token_is_imposed(self):
        for jeton in H.HOSTS:
            with self.subTest(jeton=jeton):
                os.environ[H.HOST_OS_VAR] = jeton
                self.assertEqual(jeton, H.host_os())

    def test_an_unknown_token_is_said_once_then_ignored(self):
        """Le propager ferait échouer tout sur une faute de frappe."""
        self.os_release("ID=debian\n")
        os.environ[H.HOST_OS_VAR] = "debain"
        erreur = io.StringIO()
        with self.sans_proxmox():
            with patch.object(sys, "stderr", erreur):
                premier = H.host_os()
                H.host_os()
        self.assertEqual(H.DEBIAN, premier)
        self.assertEqual(1, erreur.getvalue().count("debain"))


class TestLeJetonDArchitecture(HoteCase):
    def test_the_generic_tokens(self):
        attendus = {
            "x86_64": "amd64",
            "amd64": "amd64",
            "aarch64": "arm64",
            "arm64": "arm64",
            "s390x": "s390x",
        }
        for machine, jeton in attendus.items():
            with self.subTest(machine=machine):
                with patch.object(os, "uname") as uname:
                    uname.return_value.machine = machine
                    self.assertEqual(jeton, H.arch_token())

    def test_an_unknown_machine_falls_back(self):
        with patch.object(os, "uname") as uname:
            uname.return_value.machine = "riscv64"
            self.assertEqual(H.ARCH_DEFAUT, H.arch_token())

    def test_the_standalone_copy_still_agrees(self):
        """`deploy_qemu.py` ne peut PAS importer ce module : il voyage seul,
        poussé tel quel sur une machine distante. Sa copie reste donc, et
        cette épreuve est ce qui l'empêche de diverger."""
        import importlib.util

        chemin = os.path.join(RACINE, "script", "qemu", "deploy_qemu.py")
        spec = importlib.util.spec_from_file_location("deploy_qemu", chemin)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        machines = ("x86_64", "amd64", "aarch64", "arm64", "s390x", "riscv64")
        for machine in machines:
            with self.subTest(machine=machine):
                with patch.object(os, "uname") as uname:
                    uname.return_value.machine = machine
                    self.assertEqual(H.arch_token(), module.host_arch())


class TestLesCapacites(HoteCase):
    """Une sonde regarde ; elle ne lance rien et ne lève rien."""

    def test_no_probe_runs_a_subprocess(self):
        """Le piège rend le binaire TROUVABLE mais fait échouer son appel."""
        with ShimDir(
            nu=True, git=PIEGE, virsh=PIEGE, pacman=PIEGE, limactl=PIEGE
        ) as shim:
            with patch.dict(os.environ, {"PATH": shim.path()}):
                caps = H.capabilities()
            self.assertTrue(caps, "aucune capacité : rien n'est prouvé")
            self.assertEqual([], shim.appels)

    def test_a_present_binary_is_reported_present(self):
        with ShimDir(nu=True, git="exit 0") as shim:
            with patch.dict(os.environ, {"PATH": shim.path()}):
                caps = {c.name: c for c in H.capabilities()}
        self.assertTrue(caps["git"].present)
        self.assertIn(str(shim.chemin), caps["git"].why)

    def test_an_absent_binary_is_reported_absent(self):
        with ShimDir(nu=True) as shim:
            with patch.dict(os.environ, {"PATH": shim.path()}):
                caps = {c.name: c for c in H.capabilities()}
        self.assertFalse(caps["git"].present)

    def test_the_package_manager_follows_the_host(self):
        for jeton, outil in (
            (H.MACOS, "brew"),
            (H.DEBIAN, "apt-get"),
            (H.ARCH, "pacman"),
            (H.PROXMOX, "apt-get"),
        ):
            with self.subTest(jeton=jeton):
                os.environ[H.HOST_OS_VAR] = jeton
                noms = [c.name for c in H.capabilities()]
                self.assertIn(outil, noms)

    def test_an_unnamed_host_claims_no_package_manager(self):
        os.environ[H.HOST_OS_VAR] = H.UNKNOWN
        noms = [c.name for c in H.capabilities()]
        for outil in ("brew", "apt-get", "pacman"):
            self.assertNotIn(outil, noms)

    def test_the_vault_is_absent_without_a_path(self):
        caps = {c.name: c for c in H.capabilities()}
        self.assertFalse(caps["kdbx"].present)

    def test_the_vault_is_present_when_the_file_is(self):
        chemin = os.path.join(self.tmp.name, "coffre.kdbx")
        open(chemin, "w").close()
        caps = {c.name: c for c in H.capabilities(kdbx_path=chemin)}
        self.assertTrue(caps["kdbx"].present)

    def test_every_capability_is_the_shared_record(self):
        for cap in H.capabilities():
            with self.subTest(nom=cap.name):
                self.assertIsInstance(cap, R.Capability)


class TestLeRetraitEstUnSaut(HoteCase):
    def test_an_allowed_host_passes(self):
        os.environ[H.HOST_OS_VAR] = H.DEBIAN
        self.assertEqual(R.DS_OK, H.require_host(H.DEBIAN, H.ARCH))

    def test_another_host_skips_and_says_so(self):
        os.environ[H.HOST_OS_VAR] = H.MACOS
        erreur = io.StringIO()
        with patch.object(sys, "stderr", erreur):
            code = H.require_host(H.DEBIAN)
        self.assertEqual(R.DS_SKIP, code)
        self.assertIn(H.MACOS, erreur.getvalue())

    def test_the_refusal_is_a_skip_and_never_a_failure(self):
        os.environ[H.HOST_OS_VAR] = H.MACOS
        with patch.object(sys, "stderr", io.StringIO()):
            self.assertNotEqual(R.DS_ERR, H.require_host(H.DEBIAN))


class TestLeModuleNeLanceRien(unittest.TestCase):
    def test_it_never_calls_subprocess(self):
        """Une sonde qui lance un binaire coûte des secondes sur un menu."""
        import ast

        chemin = os.path.join(RACINE, "script", "todo", "host_os.py")
        with io.open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        racines = set()
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                racines.update(a.name.split(".")[0] for a in noeud.names)
            elif isinstance(noeud, ast.ImportFrom) and noeud.module:
                racines.add(noeud.module.split(".")[0])
        self.assertTrue(racines, "aucun import lu : rien n'est prouvé")
        self.assertNotIn("subprocess", racines)
        self.assertIn("shutil", racines)
        self.assertEqual({"script"}, racines - set(sys.stdlib_module_names))


if __name__ == "__main__":
    unittest.main()
