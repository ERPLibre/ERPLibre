#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le rapport de diagnostic montre la cause d'un déploiement raté.

Ce que ces tests gardent :

- les sondes du journal de libvirt sont bornées, ne taisent pas l'avis
  d'accès de journalctl, n'écrivent rien et ne dépendent pas de dmesg ;
- les journaux de déploiement : les trois plus récents, des extraits bornés
  dont les secrets sont masqués, et aucun dossier créé ;
- les descripteurs de firmware sont fusionnés comme libvirt les fusionne,
  et un firmware en mémoire trié avant le firmware en flash est signalé ;
- qemu.conf se lit sans jamais recopier un refus de permission ;
- la sonde shell extraite garde le format du rapport ;
- le rapport s'affiche à l'écran sur un oui, vide compris, et rien ne
  s'affiche sur un non ou une entrée fermée.
"""

import importlib.util
import io
import json
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
from script.todo import qemu_manage as qm  # noqa: E402
from script.todo.qemu_manage import QemuManageMixin  # noqa: E402
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


def _todo():
    todo = TODO.__new__(TODO)
    todo._qemu_mod_cache = DQ
    return todo


def _sortie(fn, *args, **kwargs):
    tampon = io.StringIO()
    with redirect_stdout(tampon):
        fn(*args, **kwargs)
    return tampon.getvalue()


class _Res:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class LesSondesDuJournal(unittest.TestCase):
    SONDES = dict(QemuManageMixin._DIAG_FAILURE_PROBES)

    def test_each_journal_probe_is_bounded(self):
        for titre, cmd in self.SONDES.items():
            self.assertIn("tail -n", cmd, titre)

    def test_the_access_notice_is_not_silenced(self):
        """« -q » tait l'avis « not seeing messages from other users » : sans
        lui, un journal illisible passerait pour un journal vide."""
        for titre, cmd in self.SONDES.items():
            jetons = shlex.split(cmd)
            self.assertNotIn("-q", jetons, titre)
            self.assertNotIn("--quiet", jetons, titre)
        for titre in (
            "journal libvirt (AppArmor, firmware)",
            "AppArmor refusé (noyau)",
        ):
            self.assertIn("Hint|Users in groups", self.SONDES[titre])

    def test_journalctl_never_writes(self):
        for cmd in self.SONDES.values():
            for option in (
                "--vacuum-size",
                "--vacuum-time",
                "--vacuum-files",
                "--rotate",
                "--flush",
                "--sync",
                "--setup-keys",
                "--relinquish-var",
            ):
                self.assertNotIn(option, cmd)

    def test_guest_agent_noise_is_dropped_before_the_bound(self):
        """Le « guest agent not responding » est journalisé au niveau err :
        « -p err » ne l'écarte pas, le filtre de la sonde le doit, quelle
        que soit la langue de l'hôte, et AVANT la borne."""
        cmd = self.SONDES["journal libvirt"]
        filtre = cmd.split("2>&1 |", 1)[1]
        bruit = [
            "libvirtd[1]: Guest agent is not responding: QEMU guest agent"
            " is not connected",
            "libvirtd[1]: L’agent d’accueil ne répond pas :"
            " L'agent invité QEMU n'est pas connecté",
        ] * 200
        cause = "virtqemud[2]: error: cause-inventée-du-refus"
        indice = "Hint: You are currently not seeing messages from other users"
        entree = "\n".join([indice, cause] + bruit) + "\n"
        res = subprocess.run(
            filtre,
            shell=True,
            input=entree.encode(),
            capture_output=True,
            timeout=10,
            env={**os.environ, "LC_ALL": "C"},
        )
        sortie = res.stdout.decode()
        self.assertIn(cause, sortie)
        self.assertIn(indice, sortie)
        self.assertNotIn("agent", sortie.lower())

    def test_kernel_denials_do_not_depend_on_dmesg(self):
        cmd = self.SONDES["AppArmor refusé (noyau)"]
        self.assertIn("_TRANSPORT=kernel", cmd)
        self.assertFalse(cmd.lstrip().startswith("dmesg"))


class LesJournauxDeDeploiement(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = self.tmp.name
        patch = mock.patch.object(QemuManageMixin, "_DIAG_LOG_DIR", self.base)
        patch.start()
        self.addCleanup(patch.stop)
        self.todo = _todo()

    def _journal(self, nom, lignes, mtime=None):
        chemin = os.path.join(self.base, nom)
        Path(chemin).write_text("\n".join(lignes) + "\n", encoding="utf-8")
        if mtime is not None:
            os.utime(chemin, (mtime, mtime))
        return chemin

    def test_newest_three_logs_newest_first(self):
        chemins = [
            self._journal(f"vm-essai-{i}-create.log", ["ok"], 1_000_000 + i)
            for i in range(5)
        ]
        sortie = _sortie(self.todo._qemu_diag_deploy_logs)
        recents = list(reversed(chemins[2:]))
        positions = [sortie.index(c) for c in recents]
        self.assertEqual(sorted(positions), positions)
        for ancien in chemins[:2]:
            self.assertNotIn(ancien, sortie)

    def test_error_lines_and_tail_are_bounded(self):
        erreur = (
            "ERROR    erreur interne : ne peut pas charger le profil AppArmor"
        )
        lignes = []
        for i in range(10_000):
            if i % 200 == 0:
                lignes.append(f"{erreur} n°{i}")
            else:
                lignes.append(f"ligne ordinaire {i}")
        lignes[5_001] = "x" * 2_000
        chemin = self._journal("vm-essai-long-create.log", lignes)
        erreurs, fin = QemuManageMixin._diag_log_excerpt(chemin)
        self.assertEqual(QemuManageMixin._DIAG_LOG_ERRORS, len(erreurs))
        self.assertTrue(erreurs[-1].endswith("n°9800"))
        self.assertTrue(erreurs[0].endswith(f"n°{9800 - 14 * 200}"))
        self.assertEqual(QemuManageMixin._DIAG_LOG_TAIL, len(fin))
        self.assertEqual("ligne ordinaire 9999", fin[-1])
        plafond = QemuManageMixin._DIAG_LINE_MAX + 2
        long = QemuManageMixin._diag_redact("x" * 2_000)
        self.assertEqual(plafond, len(long))
        for ligne in erreurs + fin:
            self.assertLessEqual(len(ligne), plafond)

    def test_package_names_are_not_errors(self):
        chemin = self._journal(
            "vm-essai-paquets-create.log",
            [
                "Packages (2) perl-error-0.17031-1 vim-9",
                "virt-aa-helper: error: skipped restricted file",
                "Échec de la commande (code 1) :",
            ],
        )
        erreurs, _ = QemuManageMixin._diag_log_excerpt(chemin)
        self.assertEqual(
            [
                "virt-aa-helper: error: skipped restricted file",
                "Échec de la commande (code 1) :",
            ],
            erreurs,
        )

    def test_secrets_are_masked(self):
        secret = "s3cr3t-inventé"
        masque = QemuManageMixin._diag_redact(
            f"deploy_qemu.py --password {secret} --name vm-essai-1"
        )
        self.assertNotIn(secret, masque)
        self.assertIn("****", masque)
        self.assertIn("--name vm-essai-1", masque)
        self.assertNotIn(
            "abc$def", QemuManageMixin._diag_redact("hash $6$abc$def fin")
        )
        for ligne, fuite in (
            ("deploy_qemu.py --password 'mot-un mot-deux' --name b", "deux"),
            ('deploy_qemu.py --token "jeton-un jeton-deux" --x', "deux"),
            ('{"password": "json-inventé", "user": "u"}', "inventé"),
            ("ADMIN_PASSWORD='val-un val-deux val-trois'", "trois"),
        ):
            masque = QemuManageMixin._diag_redact(ligne)
            self.assertNotIn(fuite, masque, ligne)
            self.assertIn("****", masque, ligne)
        self.assertIn(
            '"user": "u"',
            QemuManageMixin._diag_redact('{"password": "x y", "user": "u"}'),
        )
        ordinaire = "== 5/5 virt-install (--osinfo ubuntu24.04) =="
        self.assertEqual(ordinaire, QemuManageMixin._diag_redact(ordinaire))

    def test_missing_dir_is_said_not_created(self):
        absent = os.path.join(self.base, "absent")
        with mock.patch.object(QemuManageMixin, "_DIAG_LOG_DIR", absent):
            sortie = _sortie(self.todo._qemu_diag_deploy_logs)
        attendu = t("No failed-deploy log: {path} does not exist.")
        self.assertIn(attendu.format(path=absent), sortie)
        self.assertFalse(os.path.exists(absent))

    def test_latest_session_is_named(self):
        for nom, avec in (("20990101-a", True), ("20990102-b", True)):
            os.makedirs(os.path.join(self.base, nom))
            if avec:
                Path(self.base, nom, "session.json").write_text("{}")
        os.makedirs(os.path.join(self.base, "20990103-sans"))
        sortie = _sortie(self.todo._qemu_diag_deploy_logs)
        attendu = t("Latest install session: {path}").format(
            path=os.path.join(self.base, "20990102-b")
        )
        self.assertIn(attendu, sortie)
        self.assertIn(
            t("No failed-deploy log in {path}.").format(path=self.base), sortie
        )


# Descripteurs inventés, calqués sur la disposition d'edk2 : deux firmwares
# Secure Boot, deux firmwares chargés en mémoire, un firmware en flash.
_SB_ENROLLED = "41-fw-essai-sb-enrolled.json"
_SB = "51-fw-essai-sb.json"
_SEV = "61-fw-essai-x86-sev.json"
_TDX = "61-fw-essai-x86-tdx.json"
_PLAIN = "61-fw-essai-x86.json"


def _flash(code, features=(), arch="x86_64", mode=None):
    mapping = {"device": "flash", "executable": {"filename": code}}
    if mode:
        mapping["mode"] = mode
    return {
        "interface-types": ["uefi"],
        "mapping": mapping,
        "targets": [{"architecture": arch, "machines": ["pc-q35-*"]}],
        "features": list(features),
    }


def _memoire(code, features=()):
    return {
        "interface-types": ["uefi"],
        "mapping": {"device": "memory", "filename": code},
        "targets": [{"architecture": "x86_64", "machines": ["pc-q35-*"]}],
        "features": list(features),
    }


class LesFirmwares(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.etc = os.path.join(self.tmp.name, "etc")
        self.share = os.path.join(self.tmp.name, "share")
        os.makedirs(self.etc)
        os.makedirs(self.share)
        self.todo = _todo()

    def _ecrire(self, dossier, nom, contenu):
        texte = contenu if isinstance(contenu, str) else json.dumps(contenu)
        Path(dossier, nom).write_text(texte, encoding="utf-8")

    def _jeu(self, avec_memoire=True):
        self._ecrire(
            self.share,
            _SB_ENROLLED,
            _flash("/opt/fw-essai/SB_CODE.fd", ["secure-boot"]),
        )
        self._ecrire(
            self.share,
            _SB,
            _flash("/opt/fw-essai/SB_CODE.fd", ["secure-boot"]),
        )
        if avec_memoire:
            self._ecrire(
                self.share, _SEV, _memoire("/opt/fw-essai/SEV.fd", ["amd-sev"])
            )
            self._ecrire(
                self.share,
                _TDX,
                _memoire("/opt/fw-essai/TDX.fd", ["intel-tdx", "secure-boot"]),
            )
        self._ecrire(self.share, _PLAIN, _flash("/opt/fw-essai/CODE.fd"))

    def _rapport(self, run):
        with (
            mock.patch.object(DQ, "FIRMWARE_DIRS", (self.etc, self.share)),
            mock.patch.object(qm.platform, "machine", return_value="x86_64"),
            mock.patch.object(qm.subprocess, "run", side_effect=run),
        ):
            return _sortie(self.todo._qemu_diag_firmware)

    def test_memory_firmware_sorting_first_is_flagged(self):
        self._jeu()
        descs = DQ.descripteurs_firmware((self.etc, self.share))
        self.assertEqual(
            [_SB_ENROLLED, _SB, _SEV, _TDX, _PLAIN],
            [d["fichier"] for d in descs],
        )
        self.assertEqual(
            _SEV, DQ.firmware_probable(descs, "x86_64")["fichier"]
        )
        self.assertEqual(
            _PLAIN,
            DQ.firmware_probable(descs, "x86_64", pflash_only=True)["fichier"],
        )
        sortie = self._rapport(lambda cmd, **k: _Res(1, "", "hors ligne"))
        alertes = [ln for ln in sortie.splitlines() if "⚠" in ln]
        self.assertEqual(1, len(alertes), sortie)
        self.assertIn(_SEV, alertes[0])
        self.assertIn(_PLAIN, alertes[0])
        self.assertIn("/opt/fw-essai/SEV.fd", alertes[0])

    def test_no_warning_when_flash_comes_first(self):
        self._jeu(avec_memoire=False)
        descs = DQ.descripteurs_firmware((self.etc, self.share))
        libre = DQ.firmware_probable(descs, "x86_64")
        self.assertIs(libre, DQ.firmware_probable(descs, "x86_64", True))
        self.assertEqual(_PLAIN, libre["fichier"])
        sortie = self._rapport(lambda cmd, **k: _Res(1, "", "hors ligne"))
        self.assertNotIn("⚠", sortie)

    def test_etc_overrides_and_empty_file_masks(self):
        self._jeu()
        self._ecrire(self.etc, _PLAIN, _flash("/opt/fw-essai/LOCAL.fd"))
        self._ecrire(self.etc, _SEV, "")
        descs = {
            d["fichier"]: d
            for d in DQ.descripteurs_firmware((self.etc, self.share))
        }
        self.assertEqual(
            os.path.join(self.etc, _PLAIN), descs[_PLAIN]["chemin"]
        )
        self.assertEqual("/opt/fw-essai/LOCAL.fd", descs[_PLAIN]["executable"])
        self.assertTrue(descs[_SEV]["masque"])
        self.assertFalse(descs[_PLAIN]["masque"])
        # Masqué, il ne compte plus : le firmware en flash redevient le choix.
        liste = DQ.descripteurs_firmware((self.etc, self.share))
        self.assertEqual(
            _PLAIN, DQ.firmware_probable(liste, "x86_64")["fichier"]
        )

    def test_flash_mode_defaults_to_split_and_bad_json_is_a_row(self):
        self._ecrire(self.share, _PLAIN, _flash("/opt/fw-essai/CODE.fd"))
        self._ecrire(
            self.share,
            "10-fw-essai-casse.json",
            "{pas du json",
        )
        self._ecrire(
            self.share,
            "20-fw-essai-combine.json",
            _flash("/opt/fw-essai/COMBINE.fd", mode="combined"),
        )
        descs = DQ.descripteurs_firmware((self.etc, self.share))
        par_nom = {d["fichier"]: d for d in descs}
        self.assertEqual("split", par_nom[_PLAIN]["mode"])
        self.assertEqual(
            "combined", par_nom["20-fw-essai-combine.json"]["mode"]
        )
        self.assertTrue(par_nom["10-fw-essai-casse.json"]["erreur"])
        self.assertEqual(
            "20-fw-essai-combine.json",
            DQ.firmware_probable(descs, "x86_64")["fichier"],
        )
        sortie = self._rapport(lambda cmd, **k: _Res(1, "", ""))
        illisible = t("unreadable: {error}").split("{")[0]
        ligne = [ln for ln in sortie.splitlines() if "casse" in ln]
        self.assertEqual(1, len(ligne), sortie)
        self.assertIn(illisible, ligne[0])

    def test_deeply_nested_json_is_a_row_not_a_raise(self):
        """json.load lève RecursionError, et non ValueError, sur un JSON
        imbriqué au-delà de la limite de récursion."""
        profond = "[" * 100_000 + "]" * 100_000
        self._ecrire(self.share, "10-fw-essai-profond.json", profond)
        descs = DQ.descripteurs_firmware((self.etc, self.share))
        self.assertEqual(1, len(descs))
        self.assertTrue(descs[0]["erreur"])

    def test_missing_dirs_give_nothing(self):
        absent = os.path.join(self.tmp.name, "absent")
        self.assertEqual([], DQ.descripteurs_firmware((absent,)))

    def test_arch_filter(self):
        self._ecrire(
            self.share,
            "30-fw-essai-arm.json",
            _flash("/opt/fw-essai/ARM.fd", arch="aarch64"),
        )
        descs = DQ.descripteurs_firmware((self.etc, self.share))
        self.assertIsNone(DQ.firmware_probable(descs, "x86_64"))
        self.assertEqual(
            "30-fw-essai-arm.json",
            DQ.firmware_probable(descs, "aarch64")["fichier"],
        )
        with mock.patch.object(qm.platform, "machine", return_value="amd64"):
            self.assertEqual("x86_64", QemuManageMixin._qemu_host_fw_arch())
        with mock.patch.object(qm.platform, "machine", return_value="arm64"):
            self.assertEqual("aarch64", QemuManageMixin._qemu_host_fw_arch())

    def test_domcapabilities_loader_values_are_listed(self):
        xml = (
            "<domainCapabilities><os supported='yes'>"
            "<enum name='firmware'><value>efi</value></enum>"
            "<loader supported='yes'>"
            "<value>/opt/fw-essai/CODE.fd</value>"
            "<value>/opt/fw-essai/SB_CODE.fd</value>"
            "<enum name='type'><value>rom</value><value>pflash</value></enum>"
            "</loader></os></domainCapabilities>"
        )
        lances = []

        def run(cmd, **k):
            lances.append(cmd)
            return _Res(0, xml, "")

        sortie = self._rapport(run)
        self.assertIn("domcapabilities", lances[0])
        self.assertIn("    /opt/fw-essai/CODE.fd", sortie)
        self.assertIn("    /opt/fw-essai/SB_CODE.fd", sortie)
        self.assertNotIn("    efi", sortie)
        self.assertNotIn("    rom", sortie)

        sortie = self._rapport(
            lambda cmd, **k: _Res(1, "", "error: connexion refusée")
        )
        self.assertIn("error: connexion refusée", sortie)

        def pend(cmd, **k):
            raise subprocess.TimeoutExpired(cmd, 30)

        self.assertIn("(timeout)", self._rapport(pend))

    def test_unloadable_deploy_script_still_lists_loaders(self):
        todo = TODO.__new__(TODO)
        todo._qemu_import_module = mock.Mock(side_effect=OSError("absent"))
        with (
            mock.patch.object(qm.platform, "machine", return_value="x86_64"),
            mock.patch.object(
                qm.subprocess, "run", return_value=_Res(1, "", "hors ligne")
            ),
        ):
            sortie = _sortie(todo._qemu_diag_firmware)
        self.assertIn("deploy_qemu.py", sortie)
        self.assertIn("hors ligne", sortie)


class LeQemuConf(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.conf = os.path.join(self.tmp.name, "qemu-essai.conf")
        patch = mock.patch.object(QemuManageMixin, "_QEMU_CONF", self.conf)
        patch.start()
        self.addCleanup(patch.stop)
        self.todo = _todo()

    def _lire(self, run=None):
        run = run or mock.Mock(side_effect=AssertionError("pas de sudo"))
        with mock.patch.object(qm.subprocess, "run", run):
            return _sortie(self.todo._qemu_diag_qemu_conf), run

    def test_readable_file_shows_active_keys_only(self):
        Path(self.conf).write_text(
            '#user = "root"\nuser = "essai-qemu"\ncgroup_device_acl = [\n',
            encoding="utf-8",
        )
        sortie, run = self._lire()
        self.assertIn('2:user = "essai-qemu"', sortie)
        self.assertIn("3:cgroup_device_acl", sortie)
        self.assertNotIn("1:#user", sortie)
        run.assert_not_called()

    def test_no_active_key_is_said(self):
        Path(self.conf).write_text('#user = "root"\n', encoding="utf-8")
        sortie, _ = self._lire()
        self.assertIn(t("No active key: libvirt defaults apply."), sortie)

    def test_unreadable_uses_sudo_n_then_says_root_only(self):
        Path(self.conf).write_text("", encoding="utf-8")
        vrai_open = open

        def faux_open(chemin, *a, **k):
            if chemin == self.conf:
                raise PermissionError(13, "Permission denied", chemin)
            return vrai_open(chemin, *a, **k)

        with mock.patch("builtins.open", side_effect=faux_open):
            run = mock.Mock(return_value=_Res(0, 'user = "essai-qemu"\n'))
            sortie, _ = self._lire(run)
            self.assertIn(t("(read through sudo -n)"), sortie)
            self.assertIn('1:user = "essai-qemu"', sortie)
            self.assertEqual(
                ["sudo", "-n", "cat", self.conf], run.call_args.args[0]
            )

            run = mock.Mock(
                return_value=_Res(
                    1, "", "sudo: interactive authentication is required"
                )
            )
            sortie, _ = self._lire(run)
        self.assertIn("sudo grep -nE", sortie)
        self.assertNotIn("Permission denied", sortie)
        self.assertNotIn("interactive authentication", sortie)

    def test_absent_file(self):
        sortie, run = self._lire()
        self.assertIn(t("File absent: libvirt defaults apply."), sortie)
        run.assert_not_called()


class LaSonde(unittest.TestCase):
    def test_diag_probe_keeps_the_report_format(self):
        todo = _todo()
        tampon = io.StringIO()
        with (
            mock.patch.object(
                qm.subprocess, "run", return_value=_Res(0, "hi\n", "")
            ) as run,
            redirect_stdout(tampon),
        ):
            section = todo._diag_probe("x", "echo hi")
        self.assertIn("… x", tampon.getvalue())
        self.assertEqual("\n===== x =====\n$ echo hi\nhi\n", section)
        self.assertEqual(30, run.call_args.kwargs["timeout"])
        self.assertTrue(run.call_args.kwargs["shell"])
        self.assertEqual("C", run.call_args.kwargs["env"]["LC_ALL"])
        with (
            mock.patch.object(
                qm.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired("echo hi", 30),
            ),
            mock.patch("builtins.print"),
        ):
            section = todo._diag_probe("x", "echo hi")
        self.assertEqual("\n===== x =====\n$ echo hi\n(timeout)\n", section)


class LAffichage(unittest.TestCase):
    TEXTE = "# rapport d'essai\nligne-temoin\n"
    CHEMIN = "/chemin/inexistant/qemu-diagnostic-essai.log"

    def _afficher(self, **input_kw):
        todo = _todo()
        with mock.patch("builtins.input", **input_kw) as faux:
            sortie = _sortie(todo._qemu_diag_show, self.CHEMIN, self.TEXTE)
        return sortie, faux

    def test_empty_answer_shows_the_report_then_its_path(self):
        sortie, faux = self._afficher(return_value="")
        self.assertEqual(
            t("Show the report on screen? (Y/n): "), faux.call_args.args[0]
        )
        self.assertIn("ligne-temoin", sortie)
        self.assertLess(
            sortie.index("ligne-temoin"), sortie.index(self.CHEMIN)
        )

    def test_yes_in_both_languages_shows_it(self):
        for reponse in ("o", "oui", "y", "YES"):
            with self.subTest(reponse=reponse):
                sortie, _ = self._afficher(return_value=reponse)
                self.assertIn("ligne-temoin", sortie)

    def test_no_shows_nothing(self):
        sortie, _ = self._afficher(return_value="n")
        self.assertEqual("", sortie)

    def test_closed_input_shows_nothing(self):
        sortie, _ = self._afficher(side_effect=EOFError)
        self.assertEqual("", sortie)

    def test_diagnostics_asks_after_writing_the_file(self):
        todo = _todo()
        with tempfile.TemporaryDirectory() as maison:
            vus = []

            def montrer(chemin, texte):
                vus.append((chemin, texte, Path(chemin).read_text("utf-8")))

            with (
                mock.patch.dict(os.environ, {"HOME": maison}),
                mock.patch.object(QemuManageMixin, "_DIAG_FAILURE_PROBES", ()),
                mock.patch.object(QemuManageMixin, "_DIAG_PROBES", ()),
                mock.patch.object(
                    QemuManageMixin, "_diag_section", return_value="section\n"
                ),
                mock.patch.object(
                    QemuManageMixin, "_qemu_diag_show", side_effect=montrer
                ),
                mock.patch.object(
                    QemuManageMixin,
                    "_qemu_diag_offer_tools",
                    return_value=False,
                ),
            ):
                _sortie(todo._qemu_diagnostics)
        self.assertEqual(1, len(vus))
        chemin, texte, sur_disque = vus[0]
        self.assertTrue(chemin.startswith(maison))
        self.assertEqual(texte, sur_disque)


if __name__ == "__main__":
    unittest.main()
