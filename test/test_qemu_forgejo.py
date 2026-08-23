#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Option Forgejo : la case, son filtrage, et le script qui fait le travail.

Forgejo est un service, pas un outil de bureau : une VM serveur le prend comme
une VM graphique. Son binaire est statique, donc le même fichier sert apt, dnf,
pacman et zypper — c'est ce qui le rend portable sans une branche par
distribution. Les architectures, elles, sont bornées par l'amont : Forgejo
publie amd64, arm64 et arm-6, et rien pour s390x.

Le script est vérifié en l'EXÉCUTANT sur ses chemins de refus — architecture
inconnue, version introuvable — qui précèdent toute élévation de privilège et
ne touchent donc à rien.
"""

import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

sys.argv = ["todo.py"]
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

SCRIPT = (
    pathlib.Path(__file__).resolve().parent.parent
    / "script/forgejo/install_forgejo.sh"
)


class TestTheCheckbox(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)
        self.spec = TODO._QEMU_VM_TOOLS["forgejo"]

    def test_it_is_offered_in_the_form(self):
        keys = [k for k, _l, _h in TODO._qemu_vm_tool_choices()]
        self.assertIn("forgejo", keys)

    def test_a_plain_server_gets_it(self):
        """Une forge n'affiche rien : elle n'a pas besoin de bureau."""
        self.assertFalse(self.spec["needs_desktop"])
        got = self.todo._qemu_tools_for(("forgejo",), "amd64", "", "ubuntu")
        self.assertIn("forgejo", got)

    def test_every_package_family_gets_it(self):
        """Le binaire est statique : aucune famille n'est exclue, à la
        différence de la compilation mobile que son installateur borne à apt.
        """
        self.assertEqual(self.spec["families"], ())
        for distro in ("ubuntu", "debian", "almalinux", "opensuse", "arch"):
            self.assertIn(
                "forgejo",
                self.todo._qemu_tools_for(("forgejo",), "amd64", "", distro),
                distro,
            )

    def test_arm64_yes_s390x_no(self):
        """Forgejo publie amd64, arm64 et arm-6. Sur s390x il faudrait le bâtir
        en Go : la case se grise plutôt que de poser un binaire inexécutable.
        """
        for arch in ("amd64", "arm64"):
            self.assertIn(
                "forgejo",
                self.todo._qemu_tools_for(("forgejo",), arch, "", "ubuntu"),
                arch,
            )
        self.assertNotIn(
            "forgejo",
            self.todo._qemu_tools_for(("forgejo",), "s390x", "", "ubuntu"),
        )

    def test_its_disk_cost_is_counted_in_the_plan(self):
        self.assertGreater(
            self.todo._qemu_tools_disk_gb(("forgejo",), "amd64", "", "ubuntu"),
            0,
        )


class TestTheInstallBlock(unittest.TestCase):
    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_it_calls_the_dedicated_script(self):
        """Une seule autorité : la même commande sert le déploiement d'une VM et
        une installation à la main."""
        for prod, root in (
            (False, "$HOME/git/erplibre"),
            (True, "/opt/erplibre"),
        ):
            block = self.todo._qemu_forgejo_steps(
                self.todo._qemu_install_dir(prod)
            )
            self.assertIn(f"{root}/script/forgejo/install_forgejo.sh", block)

    def test_alone_it_does_not_drag_the_android_prologue(self):
        """Cocher Forgejo seul ne doit pas installer un SDK Android."""
        cmd = self.todo._qemu_after_remote_cmd(("forgejo",), False)
        self.assertIn("install_forgejo.sh", cmd)
        self.assertNotIn("sdkmanager", cmd)
        self.assertNotIn("mstep", cmd)

    def test_with_the_mobile_build_forgejo_comes_first(self):
        """Une minute contre une heure : un échec rapide se voit tôt."""
        cmd = self.todo._qemu_after_remote_cmd(("forgejo", "mobile"), False)
        self.assertLess(cmd.index("install_forgejo.sh"), cmd.index("gradlew"))

    def test_a_forgejo_failure_still_fails_the_vm(self):
        """Même contrat que la compilation mobile : une VM dont la forge
        demandée n'existe pas n'est pas la VM demandée. Les groupes sont donc
        liés par « && », jamais par « ; »."""
        cmd = self.todo._qemu_after_remote_cmd(("forgejo", "mobile"), False)
        between = cmd[
            cmd.index("install_forgejo.sh") : cmd.index("ERPLibre mobile")
        ]
        self.assertIn("&&", between)
        self.assertNotIn("|| true", between)

    def test_valid_shell_in_every_combination(self):
        for tools in (
            ("forgejo",),
            ("forgejo", "mobile"),
            ("forgejo", "avd"),
            ("forgejo", "mobile", "avd"),
        ):
            cmd = self.todo._qemu_after_remote_cmd(tools, False)
            res = subprocess.run(
                ["bash", "-n"],
                input="mstep() { :; }; mdiag() { :; };\n" + cmd,
                capture_output=True,
                text=True,
            )
            self.assertEqual(0, res.returncode, f"{tools}: {res.stderr}")


class TestDesktopOnlyVm(unittest.TestCase):
    """Une VM sans ERPLibre : le script Forgejo vit dans le dépôt, donc nulle
    part. L'écarter en silence laisserait croire qu'une case cochée a été
    honorée."""

    def setUp(self):
        self.todo = TODO.__new__(TODO)

    def test_it_says_what_it_skips(self):
        cmd = self.todo._qemu_erplibre_remote_cmd(
            None, None, False, "gnome", "", "deb", ("forgejo",)
        )
        self.assertIn("forgejo", cmd)
        self.assertIn(t("needs the ERPLibre install, skipped:"), cmd)
        self.assertNotIn("install_forgejo.sh", cmd)

    def test_it_stays_quiet_when_nothing_was_deferred(self):
        """Assertion visée sur LA note, et non sur tout « ⚠ » : la commande en
        porte d'autres, légitimes — dont celui du bureau qui ne démarre pas."""
        cmd = self.todo._qemu_erplibre_remote_cmd(
            None, None, False, "gnome", "", "deb", ("gnome_ext",)
        )
        self.assertNotIn(t("needs the ERPLibre install, skipped:"), cmd)

    def test_the_note_is_valid_shell(self):
        cmd = self.todo._qemu_erplibre_remote_cmd(
            None, None, False, "gnome", "", "deb", ("forgejo", "mobile")
        )
        res = subprocess.run(
            ["bash", "-n"], input=cmd, capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)


class TestTheScript(unittest.TestCase):
    """Le script lui-même, exécuté sur ses chemins de refus."""

    def test_it_is_executable_and_valid_shell(self):
        self.assertTrue(os.access(SCRIPT, os.X_OK), "pas exécutable")
        res = subprocess.run(
            ["bash", "-n", str(SCRIPT)], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)

    def test_help_explains_the_knobs_and_exits_clean(self):
        res = subprocess.run(
            ["bash", str(SCRIPT), "--help"], capture_output=True, text=True
        )
        self.assertEqual(0, res.returncode, res.stderr)
        for knob in (
            "FORGEJO_VERSION",
            "FORGEJO_HTTP_PORT",
            "FORGEJO_ADMIN_USER",
        ):
            self.assertIn(knob, res.stdout)

    def _run_with_stubs(self, stubs, env=None):
        """Lance le script avec un PATH bouchonné. Les chemins testés ici
        s'arrêtent AVANT tout sudo : rien n'est installé nulle part."""
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            for name, body in stubs.items():
                (bin_dir / name).write_text(f"#!/bin/bash\n{body}\n")
                (bin_dir / name).chmod(0o755)
            return subprocess.run(
                ["bash", str(SCRIPT)],
                capture_output=True,
                text=True,
                env=dict(
                    os.environ,
                    PATH=f"{bin_dir}:/usr/bin:/bin",
                    **(env or {}),
                ),
                timeout=120,
            )

    def test_an_unpublished_architecture_is_refused_by_name(self):
        """Sur s390x, Forgejo n'a pas de binaire. Le dire vaut mieux que
        télécharger un fichier qui ne s'exécutera pas."""
        res = self._run_with_stubs({"uname": "echo s390x"})
        self.assertNotEqual(0, res.returncode)
        self.assertIn("s390x", res.stdout + res.stderr)

    def test_an_unreachable_release_feed_is_named(self):
        res = self._run_with_stubs({"uname": "echo x86_64", "curl": "exit 7"})
        self.assertNotEqual(0, res.returncode)
        self.assertIn("Version", res.stdout + res.stderr)

    def test_a_pinned_version_needs_no_feed(self):
        """FORGEJO_VERSION évite l'appel réseau : utile hors ligne, et c'est ce
        qui rend ce test rapide."""
        res = self._run_with_stubs(
            {"uname": "echo x86_64", "curl": "exit 7", "sudo": "exit 0"},
            env={"FORGEJO_VERSION": "9.9.9"},
        )
        out = res.stdout + res.stderr
        self.assertIn("9.9.9", out)
        # Il échoue plus loin (le téléchargement est bouchonné), pas sur la
        # version : c'est bien le réseau du flux qui a été évité.
        self.assertNotIn("Version de Forgejo introuvable", out)


class TestHostAddress(unittest.TestCase):
    """L'adresse qui va dans ROOT_URL et SSH_DOMAIN, sur trois terrains.

    « hostname -I » vient de net-tools : l'inetutils d'Arch ne connaît pas ce
    drapeau et peut rendre le NOM de la machine. Une ROOT_URL bâtie sur un nom
    non résolvable est pire qu'un repli, d'où la validation de la forme.
    """

    def _host_address(self, stubs):
        """Extrait la fonction du script et l'exécute avec un PATH bouchonné."""
        body = SCRIPT.read_text()
        start = body.index("host_address() {")
        end = body.index("\n}", start) + 2
        fn = body[start:end]
        with tempfile.TemporaryDirectory() as tmp:
            bin_dir = pathlib.Path(tmp) / "bin"
            bin_dir.mkdir()
            for name, script in stubs.items():
                (bin_dir / name).write_text(f"#!/bin/bash\n{script}\n")
                (bin_dir / name).chmod(0o755)
            res = subprocess.run(
                ["bash", "-c", fn + "\nhost_address"],
                capture_output=True,
                text=True,
                env=dict(os.environ, PATH=f"{bin_dir}:/usr/bin:/bin"),
                timeout=30,
            )
        return res.stdout.strip()

    def test_it_takes_the_address_hostname_gives(self):
        got = self._host_address({"hostname": "echo 10.1.2.3"})
        self.assertEqual("10.1.2.3", got)

    def test_a_hostname_that_returns_a_name_is_rejected(self):
        """Le cas Arch : on tombe alors sur « ip », et non sur un nom."""
        got = self._host_address(
            {
                "hostname": "echo erplibre-arch",
                "ip": "echo '1.0.0.1 via 10.0.0.1 dev eth0 src 10.9.9.9 uid 0'",
            }
        )
        self.assertEqual("10.9.9.9", got)

    def test_without_hostname_nor_ip_it_falls_back_to_localhost(self):
        """Une forge joignable en local vaut mieux qu'un script qui s'arrête."""
        got = self._host_address({"hostname": "exit 1", "ip": "exit 1"})
        self.assertEqual("localhost", got)

    def test_it_never_returns_an_empty_string(self):
        """Une ROOT_URL « http://:3000/ » ne mène nulle part."""
        for stubs in (
            {"hostname": "echo", "ip": "echo"},
            {"hostname": "exit 2", "ip": "exit 2"},
        ):
            self.assertTrue(self._host_address(stubs), stubs)


class TestTheScriptGuards(unittest.TestCase):
    """Quatre pièges rencontrés en le mettant au point, tous mesurés."""

    def setUp(self):
        self.body = SCRIPT.read_text()

    @property
    def code_lines(self):
        """Les lignes de CODE : le piège est expliqué en commentaire, et un
        test qui cherche dans les commentaires trébuche sur sa propre
        documentation — vécu à l'écriture de ce fichier."""
        return [
            ln
            for ln in self.body.splitlines()
            if ln.strip() and not ln.lstrip().startswith("#")
        ]

    def test_it_never_probes_with_exec_on_dev_tcp(self):
        """« exec » est un builtin spécial : une redirection qui échoue termine
        le shell. Le script mourait au premier tour de la boucle d'attente,
        code 1 et pas un mot."""
        guilty = [ln for ln in self.code_lines if "exec 3<>" in ln]
        self.assertEqual([], guilty)
        self.assertIn("/api/v1/version", self.body)

    def test_the_config_test_goes_through_sudo(self):
        """/etc/forgejo est en 770 root:git : « [ -f ] » échouait toujours, et
        chaque passage réécrivait la configuration avec des secrets neufs."""
        self.assertIn("sudo test -f", self.body)

    def test_all_four_secrets_are_written(self):
        """Sans oauth2.JWT_SECRET, Forgejo tente de l'écrire dans app.ini,
        n'y arrive pas, et boucle sur « [F] save oauth2.JWT_SECRET failed »."""
        for key in (
            "SECRET_KEY",
            "INTERNAL_TOKEN",
            "JWT_SECRET",
            "LFS_JWT_SECRET",
        ):
            self.assertIn(key, self.body, key)

    def test_the_default_admin_name_is_not_reserved(self):
        """Forgejo refuse « admin » : « CreateUser: name is reserved »."""
        self.assertIn("FORGEJO_ADMIN_USER:-erplibre", self.body)
        self.assertNotIn("FORGEJO_ADMIN_USER:-admin}", self.body)

    def test_it_restarts_when_something_changed(self):
        """« enable --now » ne touche PAS un service déjà actif : il garde alors
        sa configuration en mémoire. Vécu, et le symptôme ne désignait pas la
        cause — le serveur comparait son ancien INTERNAL_TOKEN à celui que le
        hook venait de lire, répondait 403 à son propre hook, et tout push
        finissait sur « Internal Server Error Decoding Failed »."""
        self.assertIn("systemctl restart forgejo.service", self.body)
        self.assertNotIn("enable --now forgejo", self.body)

    def test_the_restart_is_conditional(self):
        """Rejouer le script sur une forge saine ne doit pas l'interrompre,
        même deux secondes."""
        self.assertIn("CHANGED=0", self.body)
        self.assertIn('[ "$CHANGED" = 1 ]', self.body)
        # Trois évènements le lèvent : binaire posé, config écrite, unité
        # modifiée.
        self.assertEqual(3, self.body.count("CHANGED=1"))

    def test_the_unit_is_compared_before_being_written(self):
        """Sans comparaison, l'unité serait réécrite à l'identique et le
        service redémarrerait pour rien à chaque passage."""
        self.assertIn("cmp -s", self.body)

    def test_the_readiness_loop_stays_quiet_while_retrying(self):
        """« Failed to connect » au premier tour est normal — le service vient
        de redémarrer. C'est le die final qui parle."""
        # La commande est coupée sur deux lignes : on regarde le BLOC de la
        # boucle, pas la ligne qui porte l'URL.
        start = self.body.index("ready=0")
        block = self.body[start : self.body.index('[ "$ready" = 1 ]', start)]
        self.assertIn("curl -fs -o /dev/null", block)
        self.assertNotIn("-fsS", block)

    def test_it_touches_no_package_manager(self):
        """C'est ce qui le rend portable : le binaire est statique."""
        for pm in ("apt-get install", "dnf install", "pacman -S", "zypper"):
            self.assertNotIn(pm, self.body, pm)


if __name__ == "__main__":
    unittest.main()
