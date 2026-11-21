#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Compte de la VM au déploiement : un utilisateur et un mot de passe pour
tout le parc.

Ce que ces tests gardent, sans VM :

- le nom de compte se valide (forme POSIX courte, comptes déjà déclarés
  refusés) et le générateur tire 16 caractères lisibles, une lettre en tête ;
- la spec porte le compte, l'empreinte du mot de passe et deux drapeaux,
  jamais le clair ; la commande de création reçoit « --user » et
  « --password-hash », plus jamais « --password » ;
- le clair voyage de l'hôte à l'invité par l'environnement puis par
  l'entrée standard de ssh, sans paraître sur une ligne de commande, dans
  session.json ou dans un journal ;
- chaque ssh de l'hôte vers la VM porte son compte : le suivi, sa relance,
  l'accès, Proxmox. Une session écrite avant la clé « user » retombe sur
  « erplibre » ;
- le compte d'une VM existante se retrouve : suivi, puis ~/.ssh/config,
  puis le défaut.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE))

from script.proxmox import proxmox_deploy as pve  # noqa: E402
from script.todo import qemu_install_monitor as mon  # noqa: E402
from script.todo.deploy_form_lib import (  # noqa: E402
    VM_PASSWORD_ALPHABET,
    VM_PASSWORD_DEFAULT,
    VM_LOGIN_FILE,
    VM_USER_DEFAULT,
    VM_USER_RESERVED,
    VmSecret,
    build_spec,
    generate_vm_password,
    validate_vm_user,
)
from script.todo.todo import TODO  # noqa: E402

# Mot de passe inventé : il ne doit paraître dans aucune commande ni aucun
# fichier que ces tests produisent.
SECRET = "Kp4essaiWm"


def _todo():
    return TODO.__new__(TODO)


def _verifie(clair, empreinte):
    """Vrai si `empreinte` ($6$sel$…) est celle de `clair`, recalculée par
    openssl avec le même sel."""
    sel = empreinte.split("$")[2]
    res = subprocess.run(
        ["openssl", "passwd", "-6", "-salt", sel, "-stdin"],
        input=clair + "\n",
        capture_output=True,
        text=True,
        check=True,
    )
    return res.stdout.strip() == empreinte


def _vm(name="vm-a"):
    return {
        "name": name,
        "distro": "debian",
        "version": "13",
        "arch": "amd64",
        "ram": 2048,
        "vcpus": 2,
        "disk": "20G",
    }


class TestValidateVmUser(unittest.TestCase):
    def test_accepted_names(self):
        for nom in ("erplibre", "_svc", "a", "dev-1", "x" * 32):
            self.assertIsNone(validate_vm_user(nom), nom)

    def test_rejected_forms(self):
        for nom in ("", "Alice", "1abc", "-abc", "a b", "a.b", "x" * 33):
            self.assertIsNotNone(validate_vm_user(nom), nom)

    def test_accounts_the_images_already_declare(self):
        for nom in ("root", "nixos", "ubuntu", "gnome-remote-desktop", "gdm"):
            self.assertIn(nom, VM_USER_RESERVED)
            self.assertIsNotNone(validate_vm_user(nom), nom)

    def test_service_accounts_and_groups_are_taken(self):
        """« git » : Forgejo tournerait sous le compte de connexion. Un
        groupe existant : useradd refuse le compte, la VM n'en a aucun."""
        from script.qemu import deploy_qemu

        groupes = set(deploy_qemu.GPU_GROUPS)
        for distro in ("ubuntu", "debian", "fedora", "arch", "opensuse"):
            groupes |= {
                g.strip() for g in deploy_qemu.user_groups(distro).split(",")
            }
        for nom in sorted(groupes | {"git", "kvm", "adm"}):
            self.assertIsNotNone(validate_vm_user(nom), nom)

    def test_the_default_is_valid(self):
        self.assertIsNone(validate_vm_user(VM_USER_DEFAULT))


class TestGenerateVmPassword(unittest.TestCase):
    def test_shape(self):
        for _ in range(50):
            pw = generate_vm_password()
            self.assertEqual(16, len(pw))
            self.assertTrue(pw[0].isalpha(), pw)
            self.assertTrue(set(pw) <= set(VM_PASSWORD_ALPHABET), pw)
            self.assertFalse(set(pw) & set("0O1lI"), pw)

    def test_draws_differ(self):
        self.assertEqual(20, len({generate_vm_password() for _ in range(20)}))

    def test_length_is_a_parameter(self):
        self.assertEqual(24, len(generate_vm_password(24)))


class TestBuildSpec(unittest.TestCase):
    FORM = {
        "res_label": "x1",
        "ssh_key": "/k.pub",
        "install": None,
        "add_ssh_config": False,
        "parallelism": 1,
    }

    def test_defaults(self):
        spec = build_spec([], set(), dict(self.FORM))
        self.assertEqual(VM_USER_DEFAULT, spec["user"])
        self.assertEqual("", spec["password_hash"])
        self.assertIs(True, spec["login_default"])
        self.assertIs(False, spec["keep_login_in_vm"])

    def test_values_pass_through(self):
        form = dict(
            self.FORM,
            user="essai",
            password_hash="$6$sel$abc",
            login_default=False,
            keep_login_in_vm=True,
        )
        spec = build_spec([], set(), form)
        self.assertEqual("essai", spec["user"])
        self.assertEqual("$6$sel$abc", spec["password_hash"])
        self.assertIs(False, spec["login_default"])
        self.assertIs(True, spec["keep_login_in_vm"])


class TestDeployParts(unittest.TestCase):
    def setUp(self):
        self.todo = _todo()
        self.todo._qemu_cache_active = lambda: False

    def _parts(self, spec):
        return self.todo._qemu_deploy_parts_for(_vm(), spec, dry_run=True)

    def _option(self, parts, nom):
        return parts[parts.index(nom) + 1]

    def test_default_account(self):
        parts = self._parts({"ssh_key": "/k.pub"})
        self.assertNotIn("--password", parts)
        self.assertEqual(VM_USER_DEFAULT, self._option(parts, "--user"))
        self.assertTrue(
            _verifie(
                VM_PASSWORD_DEFAULT, self._option(parts, "--password-hash")
            )
        )

    def test_chosen_account(self):
        self.todo._qemu_vm_secret = SECRET
        spec = {"user": "essai", "login_default": False}
        parts = self._parts(spec)
        self.assertEqual("essai", self._option(parts, "--user"))
        self.assertTrue(
            _verifie(SECRET, self._option(parts, "--password-hash"))
        )
        self.assertNotIn(SECRET, " ".join(parts))
        self.assertNotIn(SECRET, json.dumps(spec))
        self.assertNotIn("password", spec)

    def test_the_hash_is_computed_once(self):
        """L'aperçu et chaque VM d'un même déploiement : la même empreinte,
        sans relancer openssl."""
        premiere = self._option(self._parts({}), "--password-hash")
        mod = self.todo._qemu_import_module()
        with mock.patch.object(mod, "hash_password") as hacher:
            seconde = self._option(self._parts({}), "--password-hash")
        hacher.assert_not_called()
        self.assertEqual(premiere, seconde)

    def test_a_spec_hash_wins(self):
        parts = self._parts({"password_hash": "$6$sel$garde"})
        self.assertEqual(
            "$6$sel$garde", self._option(parts, "--password-hash")
        )

    def test_no_known_password_means_no_option(self):
        """Ni défaut ni clair en mémoire : aucune option, le compte n'ouvre
        que par la clé."""
        parts = self._parts({"login_default": False})
        self.assertNotIn("--password-hash", parts)
        self.assertNotIn("--password", parts)


class TestVmPassword(unittest.TestCase):
    def test_default(self):
        self.assertEqual(VM_PASSWORD_DEFAULT, _todo()._qemu_vm_password({}))

    def test_secret_in_memory(self):
        todo = _todo()
        todo._qemu_vm_secret = SECRET
        self.assertEqual(
            SECRET, todo._qemu_vm_password({"login_default": False})
        )

    def test_absent_secret(self):
        self.assertIsNone(_todo()._qemu_vm_password({"login_default": False}))

    def test_a_secret_for_another_hash_is_not_given(self):
        """La spec d'une VM recréée porte l'empreinte de SON mot de passe :
        un autre clair en mémoire ne lui est pas remis."""
        todo = _todo()
        todo._qemu_vm_secret = SECRET
        spec = {"login_default": False}
        empreinte = todo._qemu_vm_password_hash(spec)
        self.assertEqual(
            SECRET,
            todo._qemu_vm_password(dict(spec, password_hash=empreinte)),
        )
        self.assertIsNone(
            todo._qemu_vm_password(dict(spec, password_hash="$6$x$autre"))
        )

    def test_needed_for_grd_or_keep(self):
        todo = _todo()
        self.assertTrue(todo._qemu_vm_login_file_needed("gnome", False))
        self.assertFalse(todo._qemu_vm_login_file_needed("cinnamon", False))
        self.assertFalse(todo._qemu_vm_login_file_needed("", False))
        self.assertTrue(todo._qemu_vm_login_file_needed("", True))

    def test_an_unknown_flavour_needs_nothing(self):
        """Aucune saveur inconnue n'est installée comme GNOME : le clair
        n'a pas à partir vers elle."""
        todo = _todo()
        self.assertFalse(todo._qemu_vm_login_file_needed("inventee", False))
        self.assertTrue(todo._qemu_vm_login_file_needed("inventee", True))

    def test_needed_only_by_gnome_today(self):
        """Valeurs écrites en dur : seul GNOME Remote Desktop relit le mot de
        passe dans l'invité, et seul son bloc retire le fichier ensuite. Une
        saveur ajoutée ici doit aussi retirer le fichier sur toutes ses
        voies."""
        todo = _todo()
        attendu = {
            "gnome": True,
            "cinnamon": False,
            "plasma": False,
            "xfce": False,
            "cosmic": False,
            "hyprland": False,
            "i3": False,
        }
        self.assertEqual(set(attendu), set(TODO._QEMU_DESKTOP))
        for key, besoin in attendu.items():
            with self.subTest(saveur=key):
                self.assertEqual(
                    besoin, todo._qemu_vm_login_file_needed(key, False)
                )

    def test_summary_line(self):
        ligne = _todo()._qemu_login_line(
            {"user": "essai", "login_default": False}
        )
        self.assertIn("essai", ligne)
        self.assertNotIn(VM_PASSWORD_DEFAULT, ligne.replace("essai", ""))
        self.assertIn(
            f"{VM_USER_DEFAULT} / {VM_PASSWORD_DEFAULT}",
            _todo()._qemu_login_line({}),
        )


def _trace_avec_locales(exc):
    """La trace que Textual affiche quand une exception lui échappe :
    rich.traceback, variables locales comprises, rendue en texte."""
    import io

    from rich.console import Console
    from rich.traceback import Traceback

    sortie = io.StringIO()
    Console(file=sortie, width=200, color_system=None).print(
        Traceback.from_exception(
            type(exc), exc, exc.__traceback__, show_locals=True
        )
    )
    return sortie.getvalue()


class TestSecretMasking(unittest.TestCase):
    def test_the_value_works_as_a_str(self):
        secret = VmSecret(SECRET)
        self.assertEqual(SECRET, secret)
        self.assertEqual(f"{SECRET}\n", f"{secret}\n")
        self.assertEqual(SECRET.encode(), secret.encode())
        self.assertNotIn(SECRET, repr(secret))
        self.assertNotIn(SECRET[:4], repr(secret[:4]))

    def test_memory_holds_a_masked_value(self):
        todo = _todo()
        todo._qemu_set_vm_secret(SECRET)
        self.assertIsInstance(todo._qemu_vm_secret, VmSecret)
        todo._qemu_set_vm_secret("")
        self.assertIsNone(todo._qemu_vm_secret)

    def test_a_traceback_with_locals_shows_no_password(self):
        """Une valeur plus longue que ce que la trace affiche passe par une
        tranche : elle reste masquée aussi."""
        for valeur in (VmSecret(SECRET), VmSecret(SECRET * 12)):

            def echoue(secret, garde):
                raise ValueError("échec")

            try:
                echoue(valeur, (valeur, "$6$x"))
            except ValueError as exc:
                texte = _trace_avec_locales(exc)
            self.assertIn("échec", texte)
            self.assertNotIn(SECRET, texte)


class TestHashFailure(unittest.TestCase):
    """openssl absent, introuvable ou en échec : RuntimeError, sans le clair
    ni dans le message ni dans la trace, et sans l'exception d'origine,
    dont le cadre de subprocess.run tient le clair en « input »."""

    def _echoue(self, erreur):
        todo = _todo()
        todo._qemu_set_vm_secret(SECRET)
        mod = todo._qemu_import_module()
        with mock.patch.object(mod, "hash_password", side_effect=erreur):
            with self.assertRaises(RuntimeError) as pris:
                todo._qemu_vm_password_hash({"login_default": False})
        return pris.exception

    def test_every_failure_becomes_a_runtime_error(self):
        for erreur in (
            SystemExit("outil requis introuvable : 'openssl'"),
            FileNotFoundError(2, "openssl"),
            subprocess.CalledProcessError(1, ["openssl", "passwd"]),
        ):
            with self.subTest(erreur=type(erreur).__name__):
                exc = self._echoue(erreur)
                self.assertIsNone(exc.__cause__)
                self.assertIsNone(exc.__context__)
                self.assertNotIn(SECRET, str(exc))
                self.assertNotIn(SECRET, _trace_avec_locales(exc))

    def test_a_real_openssl_failure_shows_no_password(self):
        """Le vrai chemin d'openssl, PATH réduit à une doublure qui échoue :
        le cadre de subprocess.run n'entre pas dans la trace."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        faux = Path(tmp) / "openssl"
        faux.write_text("#!/bin/sh\nexit 3\n")
        faux.chmod(0o755)
        todo = _todo()
        todo._qemu_set_vm_secret(SECRET)
        mod = todo._qemu_import_module()
        with mock.patch.dict(os.environ, {"PATH": tmp}), mock.patch.dict(
            sys.modules, {"crypt": None}
        ):
            with self.assertRaises(RuntimeError) as pris:
                mod_hash = todo._qemu_vm_password_hash
                mod_hash({"login_default": False})
        self.assertIn("CalledProcessError", str(pris.exception))
        self.assertNotIn(SECRET, _trace_avec_locales(pris.exception))
        self.assertTrue(callable(mod.hash_password))


class TestPushCommand(unittest.TestCase):
    """Le dépôt du clair, exécuté avec un ssh bouchonné qui recopie son
    entrée standard et sa ligne de commande."""

    def _joue(self, env_secret):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        recu = Path(tmp) / "recu"
        argv = Path(tmp) / "argv"
        shell = (
            f'ssh() {{ echo "$*" > {argv}; cat > {recu}; }}; '
            "u=essai; ip=192.0.2.7; "
            + mon.vm_login_push_cmd('"$u@$ip"')
            + 'echo "reste=${EL_VM_PW-}"'
        )
        env = dict(os.environ)
        env.pop(mon.VM_LOGIN_ENV, None)
        if env_secret:
            env[mon.VM_LOGIN_ENV] = env_secret
        res = subprocess.run(
            ["bash", "-c", shell],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return shell, res.stdout, recu, argv

    def test_the_secret_goes_through_stdin(self):
        shell, out, recu, argv = self._joue(SECRET)
        self.assertEqual(SECRET + "\n", recu.read_text())
        self.assertNotIn(SECRET, shell)
        self.assertNotIn(SECRET, argv.read_text())
        self.assertIn("essai@192.0.2.7", argv.read_text())
        self.assertIn(VM_LOGIN_FILE, argv.read_text())
        # SSH_OPTS_BATCH porte « -n », qui avalerait l'entrée.
        options = argv.read_text().split(" essai@")[0].split()
        self.assertNotIn("-n", options)
        self.assertIn("reste=\n", out)

    def test_nothing_without_a_secret(self):
        _shell, _out, recu, _argv = self._joue("")
        self.assertFalse(recu.exists())

    def _joue_garde(self, garde):
        """Le dépôt joué jusque dans l'« invité » : ssh exécute sa commande
        distante, sudo note ce qu'il lancerait. Rend (sudo appelé ?,
        sortie)."""
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        trace = Path(tmp) / "sudo"
        shell = (
            'ssh() { for a; do d="$a"; done; bash -c "$d"; }; '
            f'sudo() {{ echo "$*" >> {trace}; cat > /dev/null; }}; '
            "export -f sudo; "
            + mon.vm_login_push_cmd('"essai@192.0.2.7"', guard=garde)
        )
        env = dict(os.environ, **{mon.VM_LOGIN_ENV: SECRET})
        res = subprocess.run(
            ["bash", "-c", shell],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return trace.exists(), res.stdout

    def test_a_refusing_guard_writes_nothing(self):
        """Une installation qui tourne encore a pu relire et retirer le
        fichier : la garde empêche de le réécrire derrière elle."""
        ecrit, _out = self._joue_garde("")
        self.assertTrue(ecrit)
        ecrit, out = self._joue_garde("echo occupee; exit 75; ")
        self.assertFalse(ecrit)
        self.assertIn("occupee", out)


class TestLaunchWrapper(unittest.TestCase):
    def _lance(self, **kw):
        vus = {}

        def faux_popen(argv, *a, **k):
            vus["argv"] = argv
            vus["env"] = k.get("env")

        with mock.patch.object(mon.subprocess, "Popen", faux_popen):
            mon._launch_one("192.0.2.7", "true", "/dev/null", "vm-a", **kw)
        return vus["argv"][-1], vus["env"]

    def test_every_ssh_uses_the_account(self):
        script, _env = self._lance(user="essai", reboot="-pve")
        self.assertIn("u=essai; ", script)
        self.assertNotIn("erplibre@", script)
        self.assertGreaterEqual(script.count('"$u@$ip"'), 4)

    def test_default_account(self):
        script, _env = self._lance()
        self.assertIn(f"u={VM_USER_DEFAULT}; ", script)

    def test_the_secret_only_travels_in_the_environment(self):
        script, env = self._lance(user="essai", secret=SECRET)
        self.assertNotIn(SECRET, script)
        self.assertEqual(SECRET, env[mon.VM_LOGIN_ENV])
        self.assertLess(
            script.index(mon.VM_LOGIN_ENV), script.index(mon.INSTALL_TAG)
        )

    def test_no_secret_no_push(self):
        script, env = self._lance(user="essai")
        self.assertIsNone(env)
        self.assertNotIn(mon.VM_LOGIN_ENV, script)

    def test_the_wrapper_unexports_the_secret_first(self):
        """Recopié dans une variable de shell puis retiré de
        l'environnement avant toute commande : ni la sonde de cloud-init
        ni virsh n'en héritent. Le dépôt passe RELAUNCH_GUARD."""
        script, _env = self._lance(user="essai", secret=SECRET)
        self.assertTrue(
            script.startswith(
                f'{mon.VM_LOGIN_SHELL_VAR}="${mon.VM_LOGIN_ENV}"; '
                f"unset {mon.VM_LOGIN_ENV}; "
            ),
            script[:80],
        )
        depot = script[script.index("cat > ") - 600 : script.index("cat > ")]
        self.assertIn(mon.INSTALL_TAG, depot)
        self.assertIn("exit 75", depot)


class TestSession(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        self.appels = []
        for nom, val in (
            ("_launch_one", lambda *a, **k: self.appels.append((a, k))),
            ("local_uuid", lambda nom: "uuid-x"),
            ("session_dir", lambda: self.base),
        ):
            patch = mock.patch.object(mon, nom, val)
            patch.start()
            self.addCleanup(patch.stop)

    def _session(self):
        return mon.launch_installs(
            [
                {
                    "name": "vm-a",
                    "ip": "192.0.2.7",
                    "user": "essai",
                    "push_login": True,
                },
                {"name": "vm-b", "ip": "192.0.2.8"},
            ],
            "develop",
            "true",
            secret=SECRET,
        )

    def test_entries_carry_the_account_not_the_secret(self):
        chemin = self._session()
        texte = Path(chemin).read_text()
        self.assertNotIn(SECRET, texte)
        vms = json.loads(texte)["vms"]
        self.assertEqual("essai", vms[0]["user"])
        self.assertEqual("ssh essai@192.0.2.7", vms[0]["ssh"])
        self.assertIs(True, vms[0]["push_login"])
        self.assertEqual(VM_USER_DEFAULT, vms[1]["user"])
        self.assertNotIn("push_login", vms[1])
        self.assertEqual(SECRET, self.appels[0][1]["secret"])
        self.assertEqual("essai", self.appels[0][1]["user"])
        self.assertIsNone(self.appels[1][1]["secret"])

    def _echoue(self, chemin, nom):
        vm = next(
            v
            for v in json.loads(Path(chemin).read_text())["vms"]
            if v["name"] == nom
        )
        with open(vm["log"], "a") as fh:
            fh.write(f"{mon.EXIT_MARKER} 1\n")

    def test_relaunch_forwards_the_secret_only_where_needed(self):
        chemin = self._session()
        self._echoue(chemin, "vm-a")
        self._echoue(chemin, "vm-b")
        self.appels.clear()
        entree = mon.relaunch_install(chemin, "vm-a", "192.0.2.9", SECRET)
        mon.relaunch_install(chemin, "vm-b", "", SECRET)
        self.assertEqual("ssh essai@192.0.2.9", entree["ssh"])
        self.assertEqual(SECRET, self.appels[0][1]["secret"])
        self.assertEqual("essai", self.appels[0][1]["user"])
        self.assertIsNone(self.appels[1][1]["secret"])
        self.assertNotIn(SECRET, Path(chemin).read_text())

    def test_relaunch_works_without_the_secret(self):
        chemin = self._session()
        self._echoue(chemin, "vm-a")
        self.appels.clear()
        mon.relaunch_install(chemin, "vm-a")
        self.assertIsNone(self.appels[0][1]["secret"])

    def test_an_old_entry_without_user(self):
        vm = {"name": "vm-a", "ip": "192.0.2.7"}
        self.assertEqual(VM_USER_DEFAULT, mon.vm_user(vm))
        self.assertTrue(mon.vm_ssh_prefix(vm).endswith("erplibre@192.0.2.7"))

    def test_ssh_prefix_uses_the_account(self):
        self.assertTrue(
            mon.vm_ssh_prefix({"ip": "192.0.2.7", "user": "essai"}).endswith(
                " essai@192.0.2.7"
            )
        )
        pve_vm = {
            "user": "essai",
            "pve": {"target": "root@hote", "addr": "192.0.2.50"},
        }
        self.assertTrue(
            mon.vm_ssh_prefix(pve_vm).endswith(" essai@192.0.2.50")
        )


class TestRelaunchSecret(unittest.TestCase):
    def _vm(self, spec, push=True):
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        chemin = Path(tmp) / "vm.spec.json"
        chemin.write_text(json.dumps(spec))
        vm = {"spec_file": str(chemin)}
        if push:
            vm["push_login"] = True
        return vm

    def test_default_password(self):
        self.assertEqual(
            VM_PASSWORD_DEFAULT,
            mon.relaunch_secret(_todo(), self._vm({"login_default": True})),
        )

    def test_matching_secret(self):
        todo = _todo()
        todo._qemu_vm_secret = SECRET
        spec = {"login_default": False}
        spec["password_hash"] = todo._qemu_vm_password_hash(spec)
        self.assertEqual(SECRET, mon.relaunch_secret(todo, self._vm(spec)))

    def test_nothing_to_give(self):
        spec = {"login_default": True}
        self.assertIsNone(mon.relaunch_secret(None, self._vm(spec)))
        self.assertIsNone(
            mon.relaunch_secret(_todo(), self._vm(spec, push=False))
        )
        self.assertIsNone(mon.relaunch_secret(_todo(), {"push_login": True}))


class TestSynchronousInstall(unittest.TestCase):
    def _joue(self, desktop, vm_password):
        todo = _todo()
        appels = []
        todo.execute = mock.Mock()
        todo.execute.exec_command_live = lambda cmd, **k: appels.append(
            (cmd, k)
        )
        todo._qemu_wait_ssh = mock.Mock(return_value=True)
        todo._qemu_import_module = mock.Mock(side_effect=RuntimeError)
        todo._qemu_vm_arch = lambda nom: "amd64"
        todo._qemu_erplibre_remote_cmd = lambda *a, **k: "true"
        with mock.patch("builtins.print"):
            todo._qemu_install_erplibre_vm(
                "vm-a",
                "/k.pub",
                None,
                "192.0.2.7",
                desktop=desktop,
                user="essai",
                vm_password=vm_password,
            )
        todo._qemu_wait_ssh.assert_called_once_with("192.0.2.7", user="essai")
        return appels

    def test_push_then_install_as_the_account(self):
        appels = self._joue("gnome", SECRET)
        self.assertEqual(2, len(appels))
        (pousse, kw), (installe, _kw) = appels
        self.assertEqual({mon.VM_LOGIN_ENV: SECRET}, kw["new_env"])
        self.assertNotIn(SECRET, pousse)
        self.assertIn("essai@192.0.2.7", pousse)
        self.assertIn("essai@192.0.2.7", installe)

    def test_no_push_without_need(self):
        appels = self._joue("cinnamon", SECRET)
        self.assertEqual(1, len(appels))
        self.assertNotIn("new_env", appels[0][1])


class TestProxmox(unittest.TestCase):
    def test_user_data_carries_the_account(self):
        todo = _todo()
        mod = todo._qemu_import_module()
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        cle = Path(tmp) / "k.pub"
        cle.write_text("ssh-ed25519 AAAAessai essai\n")
        ud = todo._pve_user_data(
            mod, "debian", "vm-a", str(cle), "essai", "$6$sel$empreinte"
        )
        self.assertIn("name: essai", ud)
        self.assertIn("$6$sel$empreinte", ud)
        self.assertIn("lock_passwd: false", ud)

    def test_cipassword_takes_the_hash(self):
        spec = {
            "name": "essai",
            "storage": "local",
            "bridge": "vmbr0",
            "memory": 2048,
            "vcpus": 2,
            "disk": "20G",
            "image": "image.qcow2",
            "user": "essai",
            "password_hash": "$6$sel$empreinte",
            "start": True,
            "ipconfig": "ip=dhcp",
        }
        joint = " ".join(pve.create_cmds(100, spec))
        self.assertIn("--ciuser essai", joint)
        self.assertIn("--cipassword '$6$sel$empreinte'", joint)


class TestVmUserLookup(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.home = Path(tmp.name)
        patch = mock.patch.dict(os.environ, {"HOME": str(self.home)})
        patch.start()
        self.addCleanup(patch.stop)
        (self.home / ".ssh").mkdir()

    def _session(self, run, vms):
        d = self.home / ".erplibre/qemu-install" / run
        d.mkdir(parents=True)
        (d / "session.json").write_text(json.dumps({"vms": vms}))
        return d / "session.json"

    def _config(self, texte):
        (self.home / ".ssh/config").write_text(texte)

    def test_default(self):
        self.assertEqual(VM_USER_DEFAULT, _todo()._qemu_vm_user("vm-a"))

    def test_ssh_config_exact_host(self):
        self._config(
            "Host *\n  User partout\n\nHost vm-a\n  HostName 192.0.2.7\n"
            "  User essai\n"
        )
        self.assertEqual("essai", _todo()._qemu_vm_user("vm-a"))
        self.assertEqual(VM_USER_DEFAULT, _todo()._qemu_vm_user("vm-b"))

    def test_session_first_most_recent_wins(self):
        self._config("Host vm-a\n  User config\n")
        vieux = self._session("1", [{"name": "vm-a", "user": "ancien"}])
        os.utime(vieux, (1, 1))
        self._session("2", [{"name": "vm-a", "user": "recent"}])
        self.assertEqual("recent", _todo()._qemu_vm_user("vm-a"))

    def test_the_latest_started_entry_wins_not_the_latest_file(self):
        """Un nom repris par un déploiement plus récent : la session de
        l'ancienne VM, réécrite après coup (relance, ajout), ne reprend pas
        la main."""
        vieux = self._session(
            "1", [{"name": "vm-a", "user": "ancien", "started": 100.0}]
        )
        recent = self._session(
            "2", [{"name": "vm-a", "user": "recent", "started": 200.0}]
        )
        os.utime(recent, (1, 1))
        os.utime(vieux, (9e9, 9e9))
        self.assertEqual("recent", _todo()._qemu_vm_user("vm-a"))

    def test_an_entry_of_an_erased_domain_does_not_count(self):
        self._session(
            "1",
            [
                {
                    "name": "vm-a",
                    "user": "efface",
                    "uuid": "u-1",
                    "started": 300.0,
                },
                {
                    "name": "vm-b",
                    "user": "vivant",
                    "uuid": "u-2",
                    "started": 100.0,
                },
            ],
        )
        self._session(
            "2",
            [
                {
                    "name": "vm-a",
                    "user": "actuel",
                    "uuid": "u-2",
                    "started": 200.0,
                }
            ],
        )
        with mock.patch.object(mon, "local_uuid", return_value="u-2"):
            self.assertEqual("actuel", _todo()._qemu_vm_user("vm-a"))
        # UUID illisible : le garde est désarmé, la plus récente l'emporte.
        with mock.patch.object(mon, "local_uuid", return_value=""):
            self.assertEqual("efface", _todo()._qemu_vm_user("vm-a"))

    def test_local_and_proxmox_entries_stay_apart(self):
        pve_a = {"target": "root@hyperviseur", "vmid": 101}
        self._session(
            "1",
            [{"name": "vm-a", "user": "local", "started": 100.0}],
        )
        self._session(
            "2",
            [
                {
                    "name": "vm-a",
                    "user": "distant",
                    "pve": pve_a,
                    "started": 200.0,
                }
            ],
        )
        todo = _todo()
        self.assertEqual("local", todo._qemu_vm_user("vm-a"))
        self.assertEqual(
            "distant",
            todo._qemu_vm_user(
                "vm-a", {"target": "root@hyperviseur", "vmid": "101"}
            ),
        )
        # Un autre hôte ou un autre VMID : une autre machine.
        for autre in (
            {"target": "root@ailleurs", "vmid": 101},
            {"target": "root@hyperviseur", "vmid": 102},
        ):
            self.assertEqual(
                VM_USER_DEFAULT, todo._qemu_vm_user("vm-a", autre)
            )

    def test_an_old_session_without_user_falls_through(self):
        self._session("1", [{"name": "vm-a", "ip": "192.0.2.7"}])
        self._config("Host vm-a\n  User config\n")
        self.assertEqual("config", _todo()._qemu_vm_user("vm-a"))

    def test_ssh_target_uses_it(self):
        self._config("Host vm-a\n  User essai\n")
        todo = _todo()
        todo._qemu_resolve_ips = lambda noms, **k: {"vm-a": "192.0.2.7"}
        self.assertEqual(
            "essai@192.0.2.7", todo._qemu_ssh_target("vm-a", "libvirt")
        )


class TestRecreatePasswordLost(unittest.TestCase):
    """La recréation d'une VM après un redémarrage de todo : la spec gardée
    n'a que l'empreinte, et la confirmation doit dire ce qui manquera."""

    def _spec(self, desktop="gnome", keep=False, defaut=False):
        return {
            "login_default": defaut,
            "password_hash": "$6$sel$garde",
            "keep_login_in_vm": keep,
            "vms": [{"name": "vm-a", "desktop": desktop}],
        }

    def test_a_gnome_vm_without_the_password_in_memory(self):
        self.assertTrue(mon.recreate_login_lost(_todo(), self._spec()))

    def test_a_kept_password_without_it(self):
        self.assertTrue(
            mon.recreate_login_lost(_todo(), self._spec("", keep=True))
        )

    def test_nothing_is_lost(self):
        todo = _todo()
        self.assertFalse(mon.recreate_login_lost(None, self._spec()))
        self.assertFalse(
            mon.recreate_login_lost(todo, self._spec(defaut=True))
        )
        self.assertFalse(mon.recreate_login_lost(todo, self._spec("")))
        # Le clair encore en mémoire, pour CETTE empreinte.
        todo._qemu_set_vm_secret(SECRET)
        spec = self._spec()
        spec["password_hash"] = todo._qemu_vm_password_hash(
            {"login_default": False}
        )
        self.assertFalse(mon.recreate_login_lost(todo, spec))

    def test_any_vm_of_a_mixed_spec_counts(self):
        """Le besoin se lit sur CHAQUE VM de la spec, pas sur la première :
        un serveur en tête ne masque pas un bureau GNOME derrière lui."""
        spec = self._spec("")
        spec["vms"].append({"name": "vm-b", "desktop": "gnome"})
        self.assertTrue(mon.recreate_login_lost(_todo(), spec))

    def test_the_fleet_desktop_fills_a_vm_without_its_own(self):
        spec = self._spec("")
        spec["vms"] = [{"name": "vm-a"}]
        spec["desktop"] = "gnome"
        self.assertTrue(mon.recreate_login_lost(_todo(), spec))
        spec["vms"] = [{"name": "vm-a", "desktop": ""}]
        self.assertFalse(mon.recreate_login_lost(_todo(), spec))


class TestSecretRestore(unittest.TestCase):
    """Le clair d'une spec gardée remis en mémoire, pour la recréation :
    seulement s'il reproduit l'empreinte, recalculée avec son sel."""

    def setUp(self):
        sys.path.insert(0, str(RACINE / "script" / "qemu"))
        import deploy_qemu

        self.mod = deploy_qemu

    def test_the_hash_check(self):
        empreinte = self.mod.hash_password(SECRET)
        self.assertTrue(self.mod.password_matches_hash(SECRET, empreinte))
        self.assertFalse(self.mod.password_matches_hash("Autre1", empreinte))
        self.assertFalse(self.mod.password_matches_hash("", empreinte))
        self.assertFalse(
            self.mod.password_matches_hash(SECRET, "$1$sel$ancien")
        )

    def test_only_the_right_password_comes_back(self):
        todo = _todo()
        todo._qemu_import_module = lambda: self.mod
        spec = {
            "login_default": False,
            "password_hash": self.mod.hash_password(SECRET),
        }
        self.assertIsNone(todo._qemu_vm_password(spec))
        self.assertFalse(todo._qemu_vm_secret_restore(spec, "Autre1"))
        self.assertIsNone(todo._qemu_vm_secret)
        self.assertFalse(todo._qemu_vm_secret_restore(spec, ""))
        self.assertTrue(todo._qemu_vm_secret_restore(spec, SECRET))
        self.assertEqual(SECRET, todo._qemu_vm_password(spec))
        self.assertIsInstance(todo._qemu_vm_secret, VmSecret)
        self.assertFalse(mon.recreate_login_lost(todo, spec))

    def test_without_a_hash_nothing_is_restored(self):
        todo = _todo()
        todo._qemu_import_module = lambda: self.mod
        self.assertFalse(
            todo._qemu_vm_secret_restore({"login_default": False}, SECRET)
        )
        self.assertIsNone(todo._qemu_vm_secret)


class TestConsoleLogin(unittest.TestCase):
    def test_the_line_names_the_vm_account(self):
        todo = _todo()
        todo._qemu_vm_user = lambda nom: "essai"
        ligne = todo._qemu_console_login("vm-a")
        self.assertIn("essai", ligne)
        self.assertNotIn(f"{VM_USER_DEFAULT} /", ligne)


if __name__ == "__main__":
    unittest.main()
