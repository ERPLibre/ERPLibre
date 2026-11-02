#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Fonctions pures de `script/todo/ntfy_mobile.py` : contrôles du serveur
ntfy, script d'accès du téléphone, édition de `server.yml`, lien et QR."""

import ast
import base64
import contextlib
import io
import os
import re
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from script.todo import ntfy_mobile as nm

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Exemple inventé, partagé avec le côté application.
EXAMPLE_LINK = (
    "erplibre-ntfy:setup?v=1"
    "&url=http%3A%2F%2Fntfy.exemple.test%3A8080"
    "&token=tk_exempleexempleexempleexemple"
    "&prefix=upab12cd34&cache=43200"
    "&odoo=http%3A%2F%2Fodoo-ntfy.exemple.test%3A8080"
)

YML = (
    '# keepalive-interval: "45s"\n'
    'keepalive-interval: "45s"\n'
    'visitor-request-limit-exempt-hosts: "odoo.exemple.test"\n'
    'listen-http: ":8080"\n'
)


INSTALLER = os.path.join(REPO, "script", "install", "install_ntfy.sh")


def installer_server_yml(tls_block="# no tls"):
    """Le `server.yml` que `install_ntfy.sh` écrit, variables résolues."""
    with open(INSTALLER) as handle:
        text = handle.read()
    body = text.split("<<YAML\n", 1)[1].split("\nYAML\n", 1)[0]
    body = body.replace("${TLS_BLOCK}", tls_block)
    body = body.replace("${DEFAULT_ACCESS}", "deny-all")
    return re.sub(r"\$\{[A-Z_]+\}", "/x", body)


class TestIdentifiers(unittest.TestCase):
    def test_prefix_shape_and_randomness(self):
        seen = {nm.random_prefix() for _ in range(20)}
        self.assertGreater(len(seen), 1)
        for prefix in seen:
            self.assertRegex(prefix, r"^up[a-z0-9]{8}$")

    def test_phone_user_sanitized(self):
        self.assertEqual(
            nm.phone_user("Téléphone de Bruno"), "erm_telephonedebruno"
        )
        with self.assertRaises(ValueError):
            nm.phone_user("!!")


class TestServerConfig(unittest.TestCase):
    def test_config_problems(self):
        self.assertEqual(
            nm.config_problems({}),
            ["ntfy_mobile_no_auth_file", "ntfy_mobile_not_deny_all"],
        )
        keys = {
            "auth-file": "/x",
            "auth-default-access": "read-write",
            "visitor-subscriber-rate-limiting": "true",
        }
        self.assertEqual(
            nm.config_problems(keys),
            [
                "ntfy_mobile_not_deny_all",
                "ntfy_mobile_subscriber_rate_limiting",
            ],
        )
        installer = nm.read_yml_keys(installer_server_yml())
        self.assertEqual(nm.config_problems(installer), [])

    def test_installer_https_block_read_back(self):
        # Le bloc TLS s'insère dans le heredoc à la place de ${TLS_BLOCK} :
        # ses clés restent lisibles au premier niveau par read_yml_keys.
        block = (
            'listen-https: ":8443"\ncert-file: "/etc/ntfy/tls/ntfy.crt"\n'
            'key-file: "/etc/ntfy/tls/ntfy.key"'
        )
        keys = nm.read_yml_keys(installer_server_yml(block))
        self.assertEqual(keys["listen-https"], ":8443")
        self.assertEqual(keys["cert-file"], "/etc/ntfy/tls/ntfy.crt")
        self.assertEqual(keys["listen-http"], ":/x")
        self.assertEqual(nm.config_problems(keys), [])

    def test_read_yml_keys(self):
        keys = nm.read_yml_keys(YML + "other: plain # note\n  nested: 1\n")
        self.assertEqual(keys["keepalive-interval"], "45s")
        self.assertEqual(keys["other"], "plain")
        self.assertNotIn("nested", keys)

    def test_cache_seconds_units(self):
        for text, expected in (
            ("12h", 43200),
            ("30m", 1800),
            ("3600s", 3600),
            ("2d", 172800),
        ):
            self.assertEqual(
                nm.cache_seconds({"cache-duration": text}), expected
            )
        self.assertEqual(nm.cache_seconds({}), 43200)

    def test_exempt_hosts_merge_keeps_other_lines_byte_identical(self):
        new = nm.with_exempt_hosts(YML, ["127.0.0.1"])
        self.assertIn(
            'visitor-request-limit-exempt-hosts: "odoo.exemple.test,127.0.0.1"',
            new,
        )
        old_lines = YML.splitlines(keepends=True)
        new_lines = new.splitlines(keepends=True)
        self.assertEqual(len(old_lines), len(new_lines))
        changed = [
            i for i, (a, b) in enumerate(zip(old_lines, new_lines)) if a != b
        ]
        self.assertEqual(changed, [2])
        self.assertEqual(nm.with_exempt_hosts(new, ["odoo.exemple.test"]), new)
        appended = nm.with_exempt_hosts("a: 1", ["127.0.0.1"])
        self.assertEqual(
            appended, 'a: 1\nvisitor-request-limit-exempt-hosts: "127.0.0.1"\n'
        )

    def test_subscriber_rate_limiting_turned_off(self):
        src = "a: 1\nvisitor-subscriber-rate-limiting: true\nb: 2\n"
        self.assertEqual(
            nm.with_subscriber_rate_limiting_off(src),
            "a: 1\nvisitor-subscriber-rate-limiting: false\nb: 2\n",
        )
        off = "visitor-subscriber-rate-limiting: false\n"
        self.assertEqual(nm.with_subscriber_rate_limiting_off(off), off)
        self.assertEqual(
            nm.with_subscriber_rate_limiting_off("a: 1\n"),
            "a: 1\nvisitor-subscriber-rate-limiting: false\n",
        )

    def test_unified_diff(self):
        diff = nm.unified_diff("a\n", "b\n", "/etc/x.yml")
        self.assertIn("--- /etc/x.yml", diff)
        self.assertIn("+b", diff)


CONFIG_CALL = re.compile(
    r"\bntfy\s+(?:(?:user|token|access)\s+)?--config\s+\S+"
)


def ntfy_calls(script):
    return [
        line
        for line in script.splitlines()
        if re.search(r"(^|[\s;(\"])ntfy\s", line)
    ]


class TestAccessScript(unittest.TestCase):
    def script(self, **kw):
        args = dict(
            config="/etc/ntfy/server.yml",
            user="erm_alice",
            prefix="upab12cd34",
        )
        args.update(kw)
        return nm.access_script(**args)

    def test_access_script_every_ntfy_call_has_config(self):
        script = self.script()
        calls = ntfy_calls(script)
        self.assertEqual(len(calls), 4)
        for line in calls:
            self.assertRegex(line, CONFIG_CALL)
        # Le garde-fou échoue bien sur un appel sans --config.
        self.assertIsNone(CONFIG_CALL.search("ntfy user add --config X u"))
        self.assertIsNone(CONFIG_CALL.search("ntfy token add u"))
        self.assertIn("ntfy user --config", script)
        self.assertIn("ntfy token --config", script)
        self.assertTrue(script.startswith("set -e\n"))

    def test_installer_user_calls_have_config(self):
        # L'installateur crée le compte administrateur avec la même CLI :
        # sans --config, elle viserait /etc/ntfy/server.yml et ses NTFY_*.
        with open(INSTALLER) as handle:
            text = handle.read()
        pattern = r"\bntfy\s+(?:--config\s+\S+\s+)?(user|token|access)\b"
        calls = [
            line
            for line in text.splitlines()
            if not line.lstrip().startswith("#") and re.search(pattern, line)
        ]
        self.assertGreaterEqual(len(calls), 2, calls)
        for line in calls:
            self.assertRegex(line, CONFIG_CALL)

    def test_access_script_never_sets_expiry_or_keepalive(self):
        script = self.script()
        self.assertNotIn("--expires", script)
        self.assertNotIn("keepalive", script)
        self.assertIn("write-only", script)
        self.assertIn("'upab12cd34*' read-only", script)

    def test_access_script_never_reuses_an_existing_user(self):
        # Une recréation silencieuse fusionnerait deux téléphones : l'ajout
        # d'un nom déjà pris échoue, et `set -e` arrête le script.
        self.assertNotIn("--ignore-exists", self.script())

    def test_access_script_quotes_values(self):
        script = self.script(label="x'; touch /tmp/pwned; '")
        lines = [ln for ln in script.splitlines() if "--label" in ln]
        self.assertEqual(len(lines), 1)
        words = shlex.split(lines[0])
        self.assertIn("--label=x'; touch /tmp/pwned; '", words)
        self.assertEqual(words[-1], "erm_alice")

    def test_other_scripts_carry_config(self):
        for script in (
            nm.revoke_script("/c.yml", "erm_alice"),
            nm.list_script("/c.yml"),
        ):
            calls = ntfy_calls(script)
            self.assertTrue(calls)
            for line in calls:
                self.assertRegex(line, CONFIG_CALL)
        self.assertIn("del erm_alice", nm.revoke_script("/c.yml", "erm_alice"))

    def test_inspect_and_write_scripts(self):
        inspect = nm.inspect_script("/c.yml")
        for marker in ("@@VERSION", "@@OWNER", "@@YML", "@@HEALTH", "@@UNIT"):
            self.assertIn(marker, inspect)
        write = nm.write_yml_script("/c.yml", "a: 1\n", "20260101")
        self.assertIn("/c.yml.bak-20260101", write)
        self.assertIn("base64 -d", write)
        lines = write.splitlines()
        self.assertLess(
            lines.index("umask 077"),
            min(i for i, ln in enumerate(lines) if "base64 -d" in ln),
        )
        self.assertIn("systemctl restart ntfy", nm.restart_script())

    def test_phone_users(self):
        out = (
            "user erm_alice (role: user, tier: none)\n- read-only access to "
            "topic upab12cd34*\nuser bob (role: admin, tier: none)\n"
            "user erm_bruno (role: user, tier: none)\n"
        )
        self.assertEqual(nm.phone_users(out), ["erm_alice", "erm_bruno"])


class TestParsers(unittest.TestCase):
    def test_parse_token(self):
        line = (
            "token tk_abcdEFGH1234 created for user erm_alice, never expires\n"
        )
        self.assertEqual(nm.parse_token("x\n" + line), "tk_abcdEFGH1234")
        self.assertIsNone(nm.parse_token("Error: user does not exist"))

    def test_parse_markers(self):
        out = "noise\n@@VERSION ntfy 2.34.0\n@@OWNER ntfy\n@@HEALTH ?\n"
        self.assertEqual(
            nm.parse_markers(out),
            {"VERSION": "ntfy 2.34.0", "OWNER": "ntfy", "HEALTH": "?"},
        )


class TestLinkAndQr(unittest.TestCase):
    def test_link_round_trip(self):
        link = nm.build_link(
            "http://ntfy.exemple.test:8080",
            "tk_exempleexempleexempleexemple",
            "upab12cd34",
            43200,
            "http://odoo-ntfy.exemple.test:8080",
        )
        self.assertEqual(link, EXAMPLE_LINK)
        self.assertNotIn("&odoo", nm.build_link("http://h", "tk_a", "upx", 1))

    def test_render_qr_none_without_segno(self):
        with mock.patch.dict(sys.modules, {"segno": None}):
            self.assertIsNone(nm.render_qr(EXAMPLE_LINK))

    def test_render_qr_draws_with_segno(self):
        try:
            import segno  # noqa: F401
        except ImportError:
            self.skipTest("segno absent")
        drawing = nm.render_qr(EXAMPLE_LINK)
        self.assertIsInstance(drawing, str)
        self.assertGreater(len(drawing.splitlines()), 10)


class TestRunners(unittest.TestCase):
    def test_local_runner_tees_and_captures(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code, text = nm.LocalHost(sudo=()).run(
                "printf 'a'; printf '@@TOKEN x\\n'", None
            )
        self.assertEqual(code, 0)
        self.assertEqual(text, "a@@TOKEN x\n")
        self.assertEqual(out.getvalue(), "a@@TOKEN x\n")

    def test_local_runner_exit_code(self):
        with contextlib.redirect_stdout(io.StringIO()):
            code, _ = nm.LocalHost(sudo=()).run("exit 3", None)
        self.assertEqual(code, 3)

    def test_argv_shapes(self):
        host = nm.LocalHost()
        self.assertEqual(
            host.argv("true", "ntfy"),
            ["sudo", "-u", "ntfy", "sh", "-c", "true"],
        )
        self.assertEqual(host.argv("true", None), ["sudo", "sh", "-c", "true"])
        ssh = nm.SshHost("alice@ntfy.exemple.test").argv("echo 'a b'", "ntfy")
        self.assertEqual(ssh[:3], ["ssh", "-t", "alice@ntfy.exemple.test"])
        self.assertEqual(ssh[3], "sudo -u ntfy sh -c 'echo '\"'\"'a b'\"'\"''")

    def test_local_runner_drops_ntfy_variables(self):
        # NTFY_* passe avant --config dans la CLI : un shell qui exporte
        # NTFY_AUTH_FILE viserait un autre fichier d'accès.
        env = {
            "PATH": "/opt/inexistant/bin",
            "NTFY_AUTH_FILE": "/tmp/autre.db",
        }
        with mock.patch.dict(os.environ, env, clear=True), mock.patch.object(
            nm, "_tee_run", return_value=(0, "")
        ) as run:
            nm.LocalHost(sudo=()).run("true", None)
        passed = run.call_args.kwargs["env"]
        self.assertEqual(passed.get("PATH"), "/opt/inexistant/bin")
        self.assertFalse([k for k in passed if k.startswith("NTFY_")])

    SECRET_SCRIPT = "printf %s 'Q2xlZkludmVudGVlQUJD' > /dev/null\necho fini\n"

    def test_root_script_runs_from_a_private_file_not_argv(self):
        # `ps` montre l'argv à tout compte local : le script lancé en root
        # n'y passe pas, seul le chemin d'un fichier 0600 y figure.
        seen = {}

        def tee(argv, env=None):
            path = argv[-1]
            seen["argv"] = argv
            seen["mode"] = os.stat(path).st_mode & 0o777
            with open(path) as handle:
                seen["text"] = handle.read()
            return 0, ""

        with mock.patch.object(nm, "_tee_run", side_effect=tee):
            nm.LocalHost().run(self.SECRET_SCRIPT, None)
        self.assertEqual(seen["argv"][:2], ["sudo", "sh"])
        self.assertEqual(len(seen["argv"]), 3)
        self.assertEqual(seen["mode"], 0o600)
        self.assertEqual(seen["text"], self.SECRET_SCRIPT)
        self.assertFalse(os.path.exists(seen["argv"][-1]))
        for arg in seen["argv"]:
            self.assertNotIn("Q2xlZkludmVudGVlQUJD", arg)

    def test_root_script_over_ssh_is_staged_on_stdin(self):
        staged = {}

        def stage(argv, **kwargs):
            staged["argv"] = argv
            staged["input"] = kwargs.get("input")
            return mock.Mock(returncode=0, stdout=b"/tmp/tmp.Ab12Cd\n")

        with mock.patch.object(
            nm.subprocess, "run", side_effect=stage
        ), mock.patch.object(nm, "_tee_run", return_value=(0, "ok")) as tee:
            result = nm.SshHost("alice@ntfy.exemple.test").run(
                self.SECRET_SCRIPT, None
            )
        self.assertEqual(result, (0, "ok"))
        self.assertEqual(staged["input"], self.SECRET_SCRIPT.encode())
        self.assertEqual(
            staged["argv"][:3], ["ssh", "-T", "alice@ntfy.exemple.test"]
        )
        run = tee.call_args.args[0]
        self.assertEqual(run[:3], ["ssh", "-t", "alice@ntfy.exemple.test"])
        self.assertIn("sudo sh", run[3])
        self.assertIn("/tmp/tmp.Ab12Cd", run[3])
        for arg in staged["argv"] + run:
            self.assertNotIn("Q2xlZkludmVudGVlQUJD", arg)

    def test_ssh_staging_failure_runs_nothing(self):
        for done in (
            mock.Mock(returncode=255, stdout=b""),
            mock.Mock(returncode=0, stdout=b"/tmp/x y; rm -rf /\n"),
        ):
            with mock.patch.object(
                nm.subprocess, "run", return_value=done
            ), mock.patch.object(
                nm, "_tee_run"
            ) as tee, contextlib.redirect_stdout(
                io.StringIO()
            ):
                code, _out = nm.SshHost("alice@ntfy.exemple.test").run(
                    "true", None
                )
            self.assertEqual(code, 255)
            tee.assert_not_called()

    def test_ssh_staged_run_removes_its_directory(self):
        # Le dossier est retiré par le compte de connexion, après sudo, que
        # sudo ait réussi ou non ; le code rendu reste celui de sudo.
        remote = nm.SshHost("h").staged_argv("/tmp/tmp.Ab12Cd")[3]
        with tempfile.TemporaryDirectory() as tmp:
            stubs = os.path.join(tmp, "stubs")
            os.makedirs(stubs)
            staged = os.path.join(tmp, "staged")
            os.makedirs(staged)
            with open(os.path.join(staged, "s"), "w") as handle:
                handle.write("echo dans-le-script; exit 4\n")
            with open(os.path.join(stubs, "sudo"), "w") as handle:
                handle.write('#!/bin/sh\nexec "$@"\n')
            os.chmod(os.path.join(stubs, "sudo"), 0o755)
            done = subprocess.run(
                ["sh", "-c", remote.replace("/tmp/tmp.Ab12Cd", staged)],
                capture_output=True,
                text=True,
                env=dict(os.environ, PATH=stubs + ":" + os.environ["PATH"]),
            )
            self.assertEqual(done.returncode, 4)
            self.assertIn("dans-le-script", done.stdout)
            self.assertFalse(os.path.exists(staged))

    def test_restore_command_names_the_backup(self):
        command = nm.restore_command("/etc/ntfy/server.yml", "20260101")
        self.assertEqual(
            shlex.split(command),
            [
                "cp",
                "-p",
                "/etc/ntfy/server.yml.bak-20260101",
                "/etc/ntfy/server.yml",
                "&&",
                "systemctl",
                "restart",
                "ntfy",
            ],
        )


# Préfixe de la CLI d'un ntfy en conteneur, tel que `call_infra.ntfy_cli`
# le donne : la commande `ntfy` lancée dans le conteneur par le moteur.
CONTAINER_CLI = (
    "docker exec -e NTFY_PASSWORD -u 997:997 erplibre-call-ntfy ntfy"
)
COMPOSE_RESTART = (
    "docker compose -f /etc/erplibre-call/compose.yml -p erplibre-call"
    " restart ntfy"
)


class TestCliPrefix(unittest.TestCase):
    """Les scripts du téléphone par la CLI d'un état : le binaire de l'hôte
    par défaut, à l'octet près comme avant, ou la CLI dans son conteneur."""

    def test_default_scripts_unchanged(self):
        self.assertEqual(
            nm.access_script("/c.yml", "erm_alice", "upab12cd34"),
            "set -e\n"
            "ntfy access --config /c.yml everyone 'up*' write-only\n"
            'NTFY_PASSWORD="$(head -c 32 /dev/urandom | base64)"'
            " ntfy user --config /c.yml add erm_alice\n"
            "ntfy access --config /c.yml erm_alice 'upab12cd34*' read-only\n"
            "ntfy token --config /c.yml add --label=erplibre-mobile"
            " erm_alice\n",
        )
        self.assertEqual(
            nm.revoke_script("/c.yml", "erm_alice"),
            "set -e\nntfy user --config /c.yml del erm_alice\n",
        )
        self.assertEqual(
            nm.list_script("/c.yml"), "ntfy access --config /c.yml\n"
        )
        self.assertEqual(
            nm.restart_script(),
            "systemctl restart ntfy\nsleep 2\n"
            'echo "@@ACTIVE $(systemctl is-active ntfy)"\n',
        )
        self.assertEqual(
            nm.restore_command("/c.yml", "20260101"),
            "cp -p /c.yml.bak-20260101 /c.yml && systemctl restart ntfy",
        )
        inspect = nm.inspect_script("/c.yml")
        self.assertEqual(inspect, nm.inspect_script("/c.yml", None))
        self.assertNotIn("@@STATE", inspect)
        self.assertTrue(
            inspect.endswith(
                'echo "@@UNIT $(systemctl show -p LoadState --value ntfy'
                ' 2>/dev/null || echo ?)"\n'
            )
        )

    def test_version_script_through_the_cli(self):
        """`version_script` imprime la version par la CLI donnée ; par
        défaut, c'est la ligne VERSION de l'inspection, à l'octet près."""
        host = nm.version_script()
        self.assertEqual(
            host, 'echo "@@VERSION $(ntfy --version 2>&1 | head -n 1)"\n'
        )
        self.assertIn(host, nm.inspect_script("/c.yml"))
        self.assertEqual(
            nm.version_script(CONTAINER_CLI),
            f'echo "@@VERSION $({CONTAINER_CLI} --version 2>&1'
            ' | head -n 1)"\n',
        )

    def test_container_cli_keeps_every_call_on_its_config(self):
        script = nm.access_script(
            "/c.yml", "erm_alice", "upab12cd34", cli=CONTAINER_CLI
        )
        self.assertIn(
            'NTFY_PASSWORD="$(head -c 32 /dev/urandom | base64)" '
            + CONTAINER_CLI
            + " user --config /c.yml add erm_alice",
            script.splitlines(),
        )
        calls = ntfy_calls(script)
        self.assertEqual(len(calls), 4)
        for line in calls:
            self.assertTrue(
                line.split(" ntfy ")[0].endswith("erplibre-call-ntfy")
            )
            self.assertRegex(line, CONFIG_CALL)
        for other in (
            nm.revoke_script("/c.yml", "erm_alice", cli=CONTAINER_CLI),
            nm.list_script("/c.yml", cli=CONTAINER_CLI),
        ):
            self.assertIn(CONTAINER_CLI + " ", other)
            for line in ntfy_calls(other):
                self.assertRegex(line, CONFIG_CALL)

    def test_container_password_reaches_the_engine_only_by_environment(self):
        script = nm.access_script(
            "/c.yml", "erm_alice", "upab12cd34", cli=CONTAINER_CLI
        )
        with tempfile.TemporaryDirectory() as tmp:
            stubs = os.path.join(tmp, "stubs")
            os.makedirs(stubs)
            log = os.path.join(tmp, "argv")
            seen = os.path.join(tmp, "password")
            with open(os.path.join(stubs, "docker"), "w") as handle:
                handle.write(
                    "#!/bin/sh\n"
                    'echo "docker $*" >> "$LOG"\n'
                    'if [ -n "${NTFY_PASSWORD:-}" ]; then'
                    ' printf %s "$NTFY_PASSWORD" > "$SEEN"; fi\n'
                    'case "$*" in *" token "*)'
                    ' echo "token tk_exemple created for user erm_alice" ;;'
                    " esac\n"
                )
            os.chmod(os.path.join(stubs, "docker"), 0o755)
            done = subprocess.run(
                ["sh", "-c", script],
                capture_output=True,
                text=True,
                env=dict(
                    os.environ,
                    PATH=stubs + ":" + os.environ["PATH"],
                    LOG=log,
                    SEEN=seen,
                ),
                timeout=30,
            )
            self.assertEqual(done.returncode, 0, done.stderr)
            with open(log) as handle:
                argv = handle.read()
            with open(seen) as handle:
                password = handle.read()
        self.assertEqual(nm.parse_token(done.stdout), "tk_exemple")
        self.assertGreater(len(password), 20)
        self.assertNotIn(password, argv)
        self.assertNotIn(password, script)
        self.assertIn(
            "docker exec -e NTFY_PASSWORD -u 997:997 erplibre-call-ntfy ntfy"
            " user --config /c.yml add erm_alice",
            argv.splitlines(),
        )

    def test_restart_and_restore_through_the_given_commands(self):
        active = "echo active"
        script = nm.restart_script(COMPOSE_RESTART, active)
        self.assertEqual(
            script,
            f'{COMPOSE_RESTART}\nsleep 2\necho "@@ACTIVE $({active})"\n',
        )
        self.assertEqual(
            nm.restore_command("/c.yml", "20260101", COMPOSE_RESTART),
            f"cp -p /c.yml.bak-20260101 /c.yml && {COMPOSE_RESTART}",
        )

    def test_inspect_prints_the_state_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            stubs = os.path.join(tmp, "stubs")
            os.makedirs(stubs)
            for name in ("ntfy", "systemctl", "curl", "wget"):
                with open(os.path.join(stubs, name), "w") as handle:
                    handle.write("#!/bin/sh\nexit 1\n")
                os.chmod(os.path.join(stubs, name), 0o755)
            config = os.path.join(tmp, "server.yml")
            state = os.path.join(tmp, "state.json")
            with open(config, "w") as handle:
                handle.write('auth-file: "/x/user.db"\n')

            def run():
                return subprocess.run(
                    ["sh", "-c", nm.inspect_script(config, state)],
                    capture_output=True,
                    text=True,
                    env=dict(
                        os.environ, PATH=stubs + ":" + os.environ["PATH"]
                    ),
                    timeout=30,
                ).stdout

            self.assertNotIn("STATE", nm.parse_markers(run()))
            with open(state, "w") as handle:
                handle.write('{"method": "container"}')
            markers = nm.parse_markers(run())
        self.assertEqual(
            base64.b64decode(markers["STATE"]).decode(),
            '{"method": "container"}',
        )
        self.assertIn("YML", markers)


class TestStdlibOnly(unittest.TestCase):
    def test_module_imports_only_stdlib(self):
        with open(os.path.join(REPO, "script", "todo", "ntfy_mobile.py")) as f:
            tree = ast.parse(f.read())
        for node in tree.body:
            names = []
            if isinstance(node, ast.Import):
                names = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            for name in names:
                self.assertIn(name, sys.stdlib_module_names)


if __name__ == "__main__":
    unittest.main()
