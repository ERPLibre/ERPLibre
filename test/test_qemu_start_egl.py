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
import os
import re
import shlex
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_hardware as hw  # noqa: E402
from script.todo import qemu_manage as qm  # noqa: E402
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


class LeDiagnostic(unittest.TestCase):
    """Un relevé destiné à quelqu'un qui n'a pas accès à la machine.

    Il doit donc être complet, ne RIEN modifier, et dire à celui qui l'envoie
    ce qu'il contient — un rapport de machine porte son nom, ses chemins de
    compte et ses adresses.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_host_gpu_node = lambda: "/dev/dri/renderD128"
        self.todo._qemu_lib_present = lambda motif: ""
        # La proposition d'outils a ses propres tests : ici elle ne ferait
        # qu'attendre une réponse que personne ne donne.
        self.todo._qemu_diag_offer_tools = lambda: False
        self.lances = []

    def _lancer(self, tmp):
        def faux_run(cmd, **k):
            self.lances.append(cmd)

            class R:
                stdout = f"sortie de {cmd}\n"
                stderr = ""

            return R()

        with mock.patch.object(
            __import__("script.todo.qemu_manage", fromlist=["x"]).subprocess,
            "run",
            side_effect=faux_run,
        ), mock.patch.object(
            os.path, "expanduser", return_value=tmp
        ), mock.patch(
            "builtins.print"
        ):
            self.todo._qemu_diagnostics()
        return sorted(os.listdir(tmp))

    def test_it_writes_one_readable_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            fichiers = self._lancer(tmp)
            self.assertEqual(1, len(fichiers), fichiers)
            self.assertTrue(fichiers[0].startswith("qemu-diagnostic-"))
            contenu = Path(tmp, fichiers[0]).read_text(encoding="utf-8")
        # Les quatre familles qui décident d'un problème QEMU : la machine,
        # l'hyperviseur, le GPU, et l'interpréteur qui porte virt-xml.
        for attendu in ("uname", "virsh", "dri", "virt-xml", "3D"):
            self.assertIn(attendu, contenu)

    # Programmes qui ne peuvent que LIRE. « command -v » cherche un outil
    # sans le lancer : la présence du mot « virt-install » dans une sonde ne
    # dit donc rien, seul le programme en tête de commande compte.
    LECTURE_SEULE = {
        "uname",
        "cat",
        "systemd-detect-virt",
        "ls",
        "lspci",
        "eglinfo",
        "command",
        "head",
        "df",
        "id",
        "true",
        "grep",
        "ps",
        "sort",
        "echo",
    }
    VIRSH_LECTURE = {"version", "list", "net-list"}

    def test_every_probe_is_read_only(self):
        """Un rapport qui modifie l'hôte n'est plus un rapport."""
        with tempfile.TemporaryDirectory() as tmp:
            self._lancer(tmp)
        operateurs = {";", "|", "||", "&&"}
        for cmd in self.lances:
            # shlex plutôt qu'un découpage sur « | » : le motif de grep en
            # contient un, et le couper au milieu ferait juger « 3d » comme
            # s'il était un programme.
            morceau = []
            for jeton in shlex.split(cmd) + [";"]:
                if jeton not in operateurs:
                    morceau.append(jeton)
                    continue
                if morceau:
                    self._juger(morceau, cmd)
                morceau = []

    def _juger(self, jetons, cmd):
        """Un morceau de commande ne doit que lire.

        « sudo » n'est qu'un préfixe : l'admettre en tête ouvrirait la porte
        à tout. On le retire et on juge le programme qu'il porte.
        """
        while jetons and (
            os.path.basename(jetons[0]) == "sudo" or jetons[0].startswith("-")
        ):
            jetons = jetons[1:]
        if not jetons:
            return
        tete = os.path.basename(jetons[0])
        if tete == "python3":
            return
        if tete == "virsh":
            sous = [
                j
                for j in jetons[1:]
                if not j.startswith("-") and "://" not in j
            ]
            self.assertIn(sous[0], self.VIRSH_LECTURE, cmd)
            return
        self.assertIn(tete, self.LECTURE_SEULE, cmd)

    def test_a_hanging_probe_does_not_hold_the_report(self):
        """Une commande qui pend ne doit pas retenir le rapport : son absence
        de réponse est elle-même une information."""
        import subprocess as sp

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(
                __import__(
                    "script.todo.qemu_manage", fromlist=["x"]
                ).subprocess,
                "run",
                side_effect=sp.TimeoutExpired("x", 30),
            ), mock.patch.object(
                os.path, "expanduser", return_value=tmp
            ), mock.patch(
                "builtins.print"
            ):
                self.todo._qemu_diagnostics()
            contenu = Path(tmp, os.listdir(tmp)[0]).read_text(encoding="utf-8")
        self.assertIn("(timeout)", contenu)


class LesOutilsDuRapport(unittest.TestCase):
    """eglinfo est le seul qui ÉPROUVE EGL : sans lui le rapport dit ce qui
    est installé, jamais si ça démarre — et c'est la question posée."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.lances = []
        self.todo.execute = mock.MagicMock()
        self.todo.execute.exec_command_live.side_effect = (
            lambda cmd, **k: self.lances.append(cmd) or 0
        )

    def _proposer(self, presents, reponse="o"):
        """`presents` : les outils du rapport déjà installés.

        UN SEUL patch de shutil.which : « qm.shutil » et le shutil de
        qemu_privilege sont le MÊME objet, et deux patchs concurrents dessus
        se recouvrent — l'hôte est donc simulé en une fois, gestionnaire de
        paquets compris.
        """
        connus = set(presents) | {"pacman"}

        def faux_which(binaire):
            return "/usr/bin/x" if binaire in connus else None

        with mock.patch.object(
            qm.shutil, "which", side_effect=faux_which
        ), mock.patch("builtins.input", return_value=reponse), mock.patch(
            "builtins.print"
        ):
            return self.todo._qemu_diag_offer_tools()

    def test_nothing_is_offered_when_all_are_there(self):
        self.assertFalse(self._proposer({"eglinfo", "lspci"}))
        self.assertEqual([], self.lances)

    def test_the_package_follows_the_distribution(self):
        """« mesa-utils » n'existe pas sur Fedora, qui livre « mesa-demos »."""
        self._proposer(set())
        joint = " ".join(self.lances)
        self.assertIn("pacman", joint)
        self.assertIn("mesa-utils", joint)
        self.assertIn("pciutils", joint)

    def test_the_command_is_announced_before_the_question(self):
        """« Les installer ? » ne dit ni ce qui sera lancé ni avec quels
        droits : la commande entière, sudo compris, précède la question."""
        connus = {"pacman"}
        vus = []
        with mock.patch.object(
            qm.shutil,
            "which",
            side_effect=lambda b: "/usr/bin/x" if b in connus else None,
        ), mock.patch(
            "builtins.input",
            side_effect=lambda p="": (vus.append(("?", p)), "n")[1],
        ), mock.patch(
            "builtins.print",
            side_effect=lambda *a, **k: vus.append(
                ("!", " ".join(str(x) for x in a))
            ),
        ):
            self.todo._qemu_diag_offer_tools()
        avant = [txt for genre, txt in vus[: [g for g, _ in vus].index("?")]]
        joint = "\n".join(avant)
        self.assertIn("sudo pacman", joint)
        self.assertIn("mesa-utils", joint)

    def test_a_refusal_installs_nothing(self):
        self.assertFalse(self._proposer(set(), reponse="n"))
        self.assertEqual([], self.lances)

    def test_without_a_terminal_it_installs_nothing(self):
        """Un lancement scripté n'a personne pour répondre : l'invite y lève
        EOFError, et le rapport — déjà écrit — ne doit pas tomber avec."""
        connus = {"pacman"}
        with mock.patch.object(
            qm.shutil,
            "which",
            side_effect=lambda b: "/usr/bin/x" if b in connus else None,
        ), mock.patch("builtins.input", side_effect=EOFError), mock.patch(
            "builtins.print"
        ):
            self.assertFalse(self.todo._qemu_diag_offer_tools())
        self.assertEqual([], self.lances)

    def test_only_the_missing_ones_are_proposed(self):
        self._proposer({"lspci"})
        self.assertEqual(1, len(self.lances), self.lances)
        self.assertIn("mesa-utils", self.lances[0])


class LeConseilAcl(unittest.TestCase):
    """La liste de périphériques n'est proposée que si elle explique le
    blocage : hôte à carte NVIDIA propriétaire, dont la liste ne nomme pas
    ses nœuds. libvirt y ajoute le nœud de rendu quand le domaine le
    déclare, jamais ceux de la carte, et la pile propriétaire ouvre les deux.
    """

    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.todo._qemu_host_gpu_node = lambda: "/dev/dri/renderD128"

    def _conseil(self, nodes, acl):
        vus = []
        with mock.patch.object(
            self.todo, "_qemu_nvidia_nodes", return_value=nodes
        ), mock.patch.object(
            self.todo, "_qemu_acl_active", return_value=acl
        ), mock.patch(
            "builtins.print",
            side_effect=lambda *a, **k: vus.append(
                " ".join(str(x) for x in a)
            ),
        ):
            parle = self.todo._qemu_nvidia_acl_advice()
        return parle, "\n".join(vus)

    def test_a_host_without_nvidia_hears_nothing(self):
        parle, rendu = self._conseil([], "")
        self.assertFalse(parle)
        self.assertEqual("", rendu)

    def test_a_list_that_already_names_them_is_left_alone(self):
        """Répéter un conseil déjà suivi le rend invisible quand il compte."""
        nodes = ["/dev/nvidia0", "/dev/nvidiactl"]
        parle, _ = self._conseil(
            nodes, 'cgroup_device_acl = ["/dev/nvidia0", "/dev/nvidiactl"]'
        )
        self.assertFalse(parle)

    def test_a_missing_node_brings_the_whole_list_back(self):
        """La clé REMPLACE le défaut au lieu de s'y ajouter : proposer
        seulement les nœuds manquants ferait perdre /dev/kvm."""
        parle, rendu = self._conseil(
            ["/dev/nvidia0", "/dev/nvidiactl"],
            'cgroup_device_acl = ["/dev/nvidia0"]',
        )
        self.assertTrue(parle)
        for attendu in ("/dev/kvm", "/dev/null", "/dev/dri/renderD128"):
            self.assertIn(attendu, rendu)
        self.assertIn("AJOUTER", rendu)

    def test_an_unreadable_file_says_so_instead_of_concluding(self):
        parle, rendu = self._conseil(["/dev/nvidia0"], None)
        self.assertTrue(parle)
        self.assertIn("grep -n cgroup_device_acl", rendu)

    def test_unreadable_and_absent_are_not_the_same_answer(self):
        """Ne pas pouvoir lire n'est pas savoir qu'il n'y a rien : le premier
        cas doit rendre None, pour que le conseil le DISE au lieu de conclure
        qu'aucune liste n'existe."""
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as tmp:
            vide = Path(tmp, "vide.conf")
            vide.write_text("# tout en commentaire\n", encoding="utf-8")
            with mock.patch.object(type(self.todo), "_QEMU_CONF", str(vide)):
                self.assertEqual("", self.todo._qemu_acl_active())
            with mock.patch.object(
                type(self.todo), "_QEMU_CONF", str(Path(tmp, "absent.conf"))
            ):
                self.assertIsNone(self.todo._qemu_acl_active())
            regle = Path(tmp, "regle.conf")
            regle.write_text(
                '#cgroup_device_acl = ["/dev/vieux"]\n'
                'cgroup_device_acl = ["/dev/nvidia0"]\n',
                encoding="utf-8",
            )
            with mock.patch.object(type(self.todo), "_QEMU_CONF", str(regle)):
                actif = self.todo._qemu_acl_active()
        # La ligne en COMMENTAIRE ne compte pas : la lire ferait croire à un
        # réglage que libvirt ignore.
        self.assertIn("/dev/nvidia0", actif)
        self.assertNotIn("/dev/vieux", actif)

    def test_it_names_the_restart_and_the_vm_recreation(self):
        """Un redémarrage de l'invité ne suffit pas : la liste s'applique au
        lancement de QEMU, donc il faut éteindre et rallumer."""
        _, rendu = self._conseil(["/dev/nvidia0"], "")
        self.assertIn("systemctl restart", rendu)
        self.assertIn("is-active", rendu)


class _FauxModule:
    """deploy_qemu réduit à ce que le menu lui demande."""

    @staticmethod
    def egl_failed(sortie):
        return "eglInitialize failed" in (sortie or "")


if __name__ == "__main__":
    unittest.main()


class LaSondeVideo(unittest.TestCase):
    """La 3D d'une VM se lit sur la ligne de commande de son QEMU.

    La définition dit ce qui est DEMANDÉ ; la ligne de commande dit ce qui
    a été REÇU. Entre les deux, libvirt peut retirer l'accélération sans le
    signaler, et « egl-headless » s'affiche dans les deux cas — chercher ce
    seul mot fait conclure à tort que la 3D est en place. Le suffixe
    « -gl » du device est la pièce qui tranche.
    """

    ARGV = (
        "/usr/bin/qemu-system-x86_64",
        "-name",
        "guest=une-vm,debug-threads=on",
        "-device",
        "%s,id=video0,max_outputs=1,bus=pcie.0",
        "-display",
        "egl-headless,rendernode=/dev/dri/renderD128",
        "-audiodev",
        '{"id":"audio1","driver":"none"}',
    )

    def _sonder(self, device, argv0=None, extra=()):
        """Sortie de la sonde devant un /proc bâti pour l'occasion."""
        from script.todo.qemu_manage import _DIAG_VIDEO_PY

        import subprocess

        with tempfile.TemporaryDirectory() as tmp:
            proc = Path(tmp) / "proc" / "4242"
            proc.mkdir(parents=True)
            argv = list(self.ARGV)
            argv[0] = argv0 or argv[0]
            argv[4] = argv[4] % device
            argv.extend(extra)
            (proc / "cmdline").write_bytes("\0".join(argv).encode() + b"\0")
            programme = _DIAG_VIDEO_PY.replace(
                "/proc/", str(Path(tmp) / "proc") + "/"
            ).replace('chemin.split("/")[2]', "chemin")
            fini = subprocess.run(
                [sys.executable, "-c", programme],
                capture_output=True,
                text=True,
            )
            self.assertEqual(fini.returncode, 0, fini.stderr)
            return fini.stdout

    def test_the_accelerated_device_is_reported(self):
        sortie = self._sonder("virtio-vga-gl")
        self.assertIn("une-vm", sortie)
        self.assertIn("virtio-vga-gl", sortie)

    def test_software_rendering_is_told_apart(self):
        """L'épreuve du rapport : les deux cas ne doivent PAS se lire pareil.

        « egl-headless » est présent des deux côtés ; un rapport qui ne
        montrerait que lui laisserait croire la 3D acquise.
        """
        accelere = self._sonder("virtio-vga-gl")
        logiciel = self._sonder("virtio-vga")
        self.assertIn("egl-headless", accelere)
        self.assertIn("egl-headless", logiciel)
        self.assertNotEqual(accelere, logiciel)
        self.assertNotIn("virtio-vga-gl", logiciel)

    def test_a_process_merely_naming_qemu_is_ignored(self):
        """Le tri se fait sur argv[0], et non sur la ligne entière.

        Un processus quelconque peut porter « qemu-system » dans ses
        arguments — un pager ouvert sur un journal, et la sonde elle-même,
        dont le programme contient le mot. Les compter ferait naître des
        VM qui n'existent pas. Le contre-exemple porte donc le motif
        AILLEURS qu'en tête, sans quoi il ne départage rien.
        """
        argv = ["/var/log/qemu-system-x86_64.log"]
        self.assertTrue(any("qemu-system" in a for a in argv))
        self.assertEqual(
            self._sonder("virtio-vga-gl", argv0="/usr/bin/less", extra=argv),
            "",
        )

    def test_the_diagnostic_carries_the_probe(self):
        from script.todo.qemu_manage import QemuManageMixin

        sondes = dict(QemuManageMixin._DIAG_PROBES)
        self.assertIn("video du qemu en cours", sondes)
