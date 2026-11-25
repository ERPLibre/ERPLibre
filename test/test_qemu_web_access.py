#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L'accès web d'une VM de production : nginx devant Odoo, ou :8069.

Le mode se choisit dans les deux formulaires et dans l'invite en ligne ; il
décide de la commande distante (nginx, certificat, certbot), des refus avant
F5, de l'URL que le suivi ouvre et de la ligne du guide de connexion. Une
spec de production écrite avant ce choix vaut « direct » et se rejoue à
l'identique. Rien ici ne crée de VM : les commandes sont lues, et leur
syntaxe vérifiée par « bash -n ».
"""

import asyncio
import base64
import contextlib
import importlib.util
import io
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.argv = ["todo.py"]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_qemu_deploy_form_dolibarr import (  # noqa: E402
    CTX,
    FORMES,
    commun,
    scenario,
    spec_rendue,
)
from test_todo_deploy_form_parity import TEXTUAL  # noqa: E402

from script.nginx import deploy_nginx_and_certbot as ngx  # noqa: E402
from script.todo import qemu_erp as erp  # noqa: E402
from script.todo import qemu_install_monitor as mon  # noqa: E402
from script.todo.qemu_erp import access  # noqa: E402
from script.todo.qemu_erp import dolibarr as qd  # noqa: E402
from script.todo.todo import TODO  # noqa: E402
from script.todo.todo_i18n import t  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "deploy_qemu", REPO / "script" / "qemu" / "deploy_qemu.py"
)
dq = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dq)

ODOO_18 = "make install_os && make install_odoo_18"
NON_ERP = "make install_os && ./script/install/install_erplibre.sh"
# Valeurs inventées, dans les noms réservés à la documentation.
DOMAINE = "erp.example.org"
COURRIEL = "admin@example.org"
LE = {"access": access.LETSENCRYPT, "domain": DOMAINE, "email": COURRIEL}
PVE = {"target": "root@pve.example", "addr": "198.51.100.5"}


def todo():
    return TODO.__new__(TODO)


def remote(mode, prod=True, cmd=ODOO_18, **extra):
    web = {"access": mode, **extra} if mode is not None else None
    return todo()._qemu_erplibre_remote_cmd(
        "develop", cmd, prod, web_access=web
    )


NGX_PY = "script/nginx/deploy_nginx_and_certbot.py"


def deballe_kit(cmd, dossier):
    """Dépaquette dans `dossier` l'archive que la commande `cmd` transporte,
    par la même ligne que l'invité (printf | base64 -d | tar)."""
    debut = cmd.index("printf %s ") + len("printf %s ")
    b64 = shlex.split(cmd[debut : cmd.index(" | base64 -d", debut)])[0]
    subprocess.run(
        ["tar", "-xzf", "-", "-C", dossier],
        input=base64.b64decode(b64),
        check=True,
    )


def bash_ok(cmd):
    r = subprocess.run(
        ["bash", "-n", "-c", cmd], capture_output=True, text=True
    )
    return r.returncode == 0, r.stderr


def spec(mode=None, distros=("ubuntu",), cmd=ODOO_18, prod=True, **extra):
    install = {"branch": "develop", "prod": prod, "cmd": cmd, **extra}
    if mode is not None:
        install["access"] = mode
    return {
        "install": install,
        "vms": [
            {"name": f"vm-{i}", "distro": d} for i, d in enumerate(distros)
        ],
    }


class TestLeRegistre(unittest.TestCase):
    def test_odoo_serves_the_four_modes_dolibarr_none(self):
        self.assertEqual(
            {access.SELF_SIGNED, access.HTTP, access.LETSENCRYPT, "direct"},
            set(erp.get(erp.APP_ODOO).access_modes),
        )
        self.assertEqual((), erp.get(erp.APP_DOLIBARR).access_modes)

    def test_self_signed_is_the_default_and_first(self):
        self.assertEqual(access.SELF_SIGNED, access.DEFAULT)
        self.assertEqual(access.DEFAULT, access.MODES[0].key)

    def test_an_old_prod_spec_is_direct(self):
        self.assertEqual(
            access.DIRECT, access.fields({"prod": True})["access"]
        )
        self.assertEqual(
            access.DIRECT, erp.vm_access({}, {"prod": True, "cmd": ODOO_18})
        )

    def test_only_odoo_in_production_gets_a_mode(self):
        self.assertEqual(
            access.SELF_SIGNED,
            erp.effective_access(True, ODOO_18, access.SELF_SIGNED),
        )
        for prod, cmd in (
            (False, ODOO_18),
            (True, qd.INSTALL_CMD),
            (True, NON_ERP),
        ):
            with self.subTest(prod=prod, cmd=cmd):
                self.assertEqual(
                    access.DIRECT,
                    erp.effective_access(prod, cmd, access.SELF_SIGNED),
                )

    def test_domain_and_email_only_for_lets_encrypt(self):
        champs = access.fields(
            {"prod": True, "access": access.HTTP, "domain": DOMAINE}
        )
        self.assertEqual("", champs["domain"])
        champs = access.fields({"prod": True, **LE})
        self.assertEqual(
            (DOMAINE, COURRIEL), (champs["domain"], champs["email"])
        )


class TestLesRefus(unittest.TestCase):
    def test_nixos_refuses_nginx_but_not_direct(self):
        refus = erp.install_refusals(spec(access.SELF_SIGNED, ("nixos",)))
        self.assertEqual([f"vm-0: {t(access.NIXOS_REFUSAL)}"], refus)
        self.assertEqual(
            [], erp.install_refusals(spec(access.DIRECT, ("nixos",)))
        )

    def test_a_supported_plan_is_not_refused(self):
        for mode in (access.SELF_SIGNED, access.HTTP):
            with self.subTest(mode):
                self.assertEqual([], erp.install_refusals(spec(mode)))
        self.assertEqual([], erp.install_refusals(spec(**LE)))

    def test_lets_encrypt_needs_a_domain_and_an_email(self):
        refus = erp.install_refusals(spec(access.LETSENCRYPT))
        self.assertIn(t("Let's Encrypt needs a domain."), refus)
        self.assertIn(t("Let's Encrypt needs an admin email."), refus)

    def test_lets_encrypt_refuses_malformed_values(self):
        refus = erp.install_refusals(
            spec(access.LETSENCRYPT, domain="erp", email="admin")
        )
        self.assertIn(t("Let's Encrypt: invalid domain: %s") % "erp", refus)
        self.assertIn(
            t("Let's Encrypt: invalid admin email: %s") % "admin", refus
        )

    def test_an_email_with_shell_metacharacters_is_refused(self):
        # Le courriel finit sur la ligne de commande de certbot, en root.
        for email in (
            "a$(id)@example.org",
            "a;reboot;@example.org",
            "`id`@example.org",
            "o'brien@example.org",
            "admin@exa mple.org",
            "admin@example.org;id",
        ):
            with self.subTest(email):
                self.assertNotEqual("", access.email_error(email))
        for email in (COURRIEL, "first.last+tag@sub.example.org"):
            with self.subTest(email):
                self.assertEqual("", access.email_error(email))

    def test_one_domain_cannot_name_two_vms(self):
        refus = erp.install_refusals(spec(distros=("ubuntu", "debian"), **LE))
        self.assertEqual(1, len(refus))
        self.assertIn("vm-0, vm-1", refus[0])

    def test_dolibarr_and_development_are_never_refused(self):
        self.assertEqual(
            [],
            erp.install_refusals(
                spec(access.SELF_SIGNED, ("ubuntu",), cmd=qd.INSTALL_CMD)
            ),
        )
        self.assertEqual(
            [],
            erp.install_refusals(
                spec(access.LETSENCRYPT, ("nixos",), prod=False)
            ),
        )

    def test_an_unknown_mode_is_refused(self):
        refus = erp.install_refusals(spec("ftp"))
        self.assertEqual(
            [f"vm-0: {t('Unknown web access: %s') % 'ftp'}"], refus
        )


class TestLaCommandeDistante(unittest.TestCase):
    def test_every_mode_is_valid_shell(self):
        for mode, extra in (
            (access.SELF_SIGNED, {}),
            (access.HTTP, {}),
            (access.LETSENCRYPT, {"domain": DOMAINE, "email": COURRIEL}),
            (access.DIRECT, {}),
        ):
            with self.subTest(mode):
                ok, err = bash_ok(remote(mode, **extra))
                self.assertTrue(ok, err)

    def test_self_signed_makes_a_private_certificate(self):
        cmd = remote(access.SELF_SIGNED)
        self.assertIn("umask 077 && sudo openssl req -x509", cmd)
        self.assertIn('-subj "/CN=$EL_HOST"', cmd)
        self.assertIn("subjectAltName=DNS:$EL_HOST", cmd)
        self.assertIn("sudo chmod 0600 /etc/ssl/erplibre/privkey.pem", cmd)
        self.assertIn(
            "--ssl_exist --force_ssl_dir /etc/ssl/erplibre "
            "--no_certbot_options",
            cmd,
        )
        self.assertNotIn("--run_certbot", cmd)
        self.assertIn('EL_URL="https://${EL_IP:-<ip>}/"', cmd)

    def test_http_uses_the_plain_template(self):
        cmd = remote(access.HTTP)
        self.assertIn("script/nginx/deploy_nginx_and_certbot.py", cmd)
        self.assertIn("--generate_nginx --default_server", cmd)
        self.assertNotIn("--ssl_exist", cmd)
        self.assertNotIn("openssl req", cmd)
        self.assertIn('EL_URL="http://${EL_IP:-<ip>}/"', cmd)

    def test_lets_encrypt_runs_certbot_for_the_domain(self):
        cmd = remote(access.LETSENCRYPT, domain=DOMAINE, email=COURRIEL)
        self.assertIn(
            f"--run_certbot --domain {DOMAINE} --admin_email {COURRIEL}", cmd
        )
        self.assertIn(f"/etc/letsencrypt/live/{DOMAINE}", cmd)
        self.assertIn(f"EL_HOST={DOMAINE}", cmd)
        self.assertNotIn("--ssl_exist", cmd)

    def test_nginx_comes_after_the_odoo_service_in_its_block(self):
        cmd = remote(access.SELF_SIGNED)
        self.assertLess(cmd.index("erplibre.service"), cmd.index("== nginx ("))
        self.assertIn("proxy_mode = True", cmd)
        self.assertIn("sudo systemctl restart erplibre.service", cmd)

    def test_nothing_for_direct_development_dolibarr_or_old_specs(self):
        for nom, cmd in (
            ("direct", remote(access.DIRECT)),
            ("dev", remote(access.SELF_SIGNED, prod=False)),
            ("dolibarr", remote(access.SELF_SIGNED, cmd=qd.INSTALL_CMD)),
            ("ancienne spec", remote(None)),
        ):
            with self.subTest(nom):
                self.assertNotIn("nginx", cmd)

    def test_an_old_spec_replays_the_same_command(self):
        # Le bloc d'installation d'avant le choix : prod, sans « access ».
        avant = {"branch": "develop", "prod": True, "cmd": ODOO_18}
        t_ = todo()
        self.assertEqual(
            t_._qemu_erplibre_remote_cmd("develop", ODOO_18, True),
            t_._qemu_erplibre_remote_cmd(
                "develop", ODOO_18, True, web_access=avant
            ),
        )

    def test_nixos_is_refused_inside_the_vm_too(self):
        cmd = todo()._qemu_nginx_cmd(access.HTTP)
        self.assertIn("grep -q '^ID=nixos' /etc/os-release", cmd)
        self.assertLess(cmd.index("ID=nixos"), cmd.index("install -y nginx"))

    def test_firewalld_and_selinux_are_handled(self):
        cmd = todo()._qemu_nginx_cmd(access.SELF_SIGNED)
        self.assertIn("--add-service=http --add-service=https", cmd)
        self.assertIn("setsebool -P httpd_can_network_connect 1", cmd)

    def test_the_vm_runs_the_host_script_not_its_clone(self):
        # La branche clonée peut ne pas connaître les options du bloc.
        cmd = todo()._qemu_nginx_cmd(access.SELF_SIGNED)
        self.assertNotIn('cd "$SVC_DIR" && sudo python3', cmd)
        self.assertIn(
            'cd "$EL_NGX_DIR" && sudo python3 '
            "script/nginx/deploy_nginx_and_certbot.py",
            cmd,
        )
        with tempfile.TemporaryDirectory() as kit:
            deballe_kit(cmd, kit)
            for nom in os.listdir(REPO / "script" / "nginx"):
                if nom.startswith("template_nginx") or nom == NGX_PY:
                    with self.subTest(nom):
                        self.assertEqual(
                            (REPO / "script" / "nginx" / nom).read_bytes(),
                            (
                                Path(kit) / "script" / "nginx" / nom
                            ).read_bytes(),
                        )
        self.assertLess(
            cmd.index("EL_NGX_DIR=$(mktemp -d)"), cmd.index(NGX_PY)
        )
        self.assertIn('rm -rf "$EL_NGX_DIR"', cmd)

    def test_the_kit_is_reproducible(self):
        self.assertEqual(
            todo()._qemu_nginx_cmd(access.HTTP),
            todo()._qemu_nginx_cmd(access.HTTP),
        )

    def test_the_generated_site_line_runs_against_the_kit(self):
        for mode, attendu in (
            (access.SELF_SIGNED, "listen 443 ssl default_server;"),
            (access.HTTP, "listen 80 default_server;"),
            (access.LETSENCRYPT, "listen 80 default_server;"),
        ):
            with self.subTest(mode), tempfile.TemporaryDirectory() as kit:
                cmd = todo()._qemu_nginx_cmd(mode, DOMAINE, COURRIEL)
                deballe_kit(cmd, kit)
                conf = os.path.join(kit, "erplibre.conf")
                debut = cmd.index(f"sudo python3 {NGX_PY} --generate_nginx")
                ligne = cmd[debut : cmd.index(" ); then", debut)]
                valeurs = {
                    "$EL_NGX_CONF": conf,
                    "$EL_HOST": "vm-test",
                    "$EL_V": "18.0",
                    "$EL_WS": "8069",
                }
                argv = [valeurs.get(a, a) for a in shlex.split(ligne)[2:]]
                r = subprocess.run(
                    [sys.executable, *argv],
                    cwd=kit,
                    capture_output=True,
                    text=True,
                )
                self.assertEqual(0, r.returncode, r.stderr)
                self.assertIn(attendu, Path(conf).read_text())

    def test_websocket_follows_the_workers(self):
        cmd = todo()._qemu_nginx_cmd(access.HTTP)
        self.assertIn("EL_WS=8072", cmd)
        self.assertIn("|| EL_WS=8069", cmd)
        self.assertIn('--default_port_websocket "$EL_WS"', cmd)


class TestLesFamilles(unittest.TestCase):
    """Un aiguillage par gestionnaire de paquets, avec ses noms."""

    def test_each_family_installs_nginx(self):
        cmd = todo()._qemu_nginx_cmd(access.SELF_SIGNED)
        for mgr, (base, _certbot) in TODO._QEMU_NGINX_PKGS.items():
            with self.subTest(mgr):
                self.assertIn(
                    f"command -v {mgr} >/dev/null 2>&1; then "
                    f"{TODO._QEMU_NGINX_INSTALL[mgr]} {base}; ",
                    cmd,
                )
        # certbot n'est posé que pour Let's Encrypt.
        for _base, certbot in TODO._QEMU_NGINX_PKGS.values():
            self.assertNotIn(certbot, cmd)

    def test_lets_encrypt_adds_certbot_per_family(self):
        cmd = todo()._qemu_nginx_cmd(access.LETSENCRYPT, DOMAINE, COURRIEL)
        for mgr, (base, certbot) in TODO._QEMU_NGINX_PKGS.items():
            with self.subTest(mgr):
                self.assertIn(
                    f"{TODO._QEMU_NGINX_INSTALL[mgr]} {base} {certbot}; ", cmd
                )
        self.assertIn("certbot-nginx", TODO._QEMU_NGINX_PKGS["pacman"][1])
        # certbot vient d'EPEL sur la famille RHEL.
        dnf = cmd[cmd.index("command -v dnf") :]
        self.assertLess(dnf.index("epel-release"), dnf.index("certbot"))

    def test_the_site_goes_where_the_family_reads_it(self):
        cmd = todo()._qemu_nginx_cmd(access.HTTP)
        self.assertIn("EL_NGX_CONF=/etc/nginx/sites-available/erplibre", cmd)
        self.assertIn("sudo rm -f /etc/nginx/sites-enabled/default", cmd)
        self.assertIn("EL_NGX_CONF=/etc/nginx/conf.d/erplibre.conf", cmd)
        self.assertIn("include /etc/nginx/conf.d/*.conf;", cmd)


class TestLeScriptNginx(unittest.TestCase):
    """Les trois options ajoutées à deploy_nginx_and_certbot.py."""

    def test_enabled_link_only_for_sites_available(self):
        self.assertEqual(
            "/etc/nginx/sites-enabled/erplibre",
            ngx.enabled_link("/etc/nginx/sites-available/erplibre"),
        )
        self.assertIsNone(ngx.enabled_link("/etc/nginx/conf.d/erplibre.conf"))

    def test_adapt_template(self):
        brut = (
            "    listen 443 ssl; # managed by Certbot\n"
            "    include /etc/letsencrypt/options-ssl-nginx.conf;\n"
            "    ssl_dhparam /etc/letsencrypt/ssl-dhparams.pem;\n"
            "    listen 80;\n"
        )
        self.assertEqual(brut, ngx.adapt_template(brut))
        fait = ngx.adapt_template(brut, True, True)
        self.assertIn("listen 443 ssl default_server;", fait)
        self.assertIn("listen 80 default_server;", fait)
        self.assertNotIn("letsencrypt", fait)

    def test_certbot_gets_an_argv_never_a_shell_line(self):
        self.assertEqual(
            [
                "sudo",
                "certbot",
                "--email",
                "a$(id)@example.org",
                "--non-interactive",
                "--agree-tos",
                "--nginx",
                "-d",
                DOMAINE,
                "-d",
                "www.example.org",
            ],
            ngx.certbot_argv(
                [DOMAINE, "www.example.org"], "a$(id)@example.org"
            ),
        )
        self.assertEqual(
            ["sudo", "certbot", "--nginx", "-d", DOMAINE],
            ngx.certbot_argv([DOMAINE]),
        )

    def test_the_self_signed_site_is_written(self):
        with tempfile.TemporaryDirectory() as tmp:
            conf = os.path.join(tmp, "erplibre.conf")
            subprocess.run(
                [
                    sys.executable,
                    "script/nginx/deploy_nginx_and_certbot.py",
                    "--generate_nginx",
                    "--default_server",
                    "--nginx_conf",
                    conf,
                    "--domain",
                    "vm-test",
                    "--odoo_version",
                    "18.0",
                    "--default_port_websocket",
                    "8069",
                    "--ssl_exist",
                    "--force_ssl_dir",
                    "/etc/ssl/erplibre",
                    "--no_certbot_options",
                ],
                cwd=REPO,
                check=True,
                capture_output=True,
            )
            texte = Path(conf).read_text()
        self.assertIn("ssl_certificate /etc/ssl/erplibre/fullchain.pem", texte)
        self.assertIn("listen 443 ssl default_server;", texte)
        self.assertNotIn("letsencrypt", texte)
        self.assertNotIn("8072", texte)


class TestLeSuivi(unittest.TestCase):
    VM = {"name": "vm-o", "ip": "192.0.2.8"}

    def test_the_url_follows_the_mode(self):
        for mode, url in (
            (None, "http://192.0.2.8:8069"),
            (access.DIRECT, "http://192.0.2.8:8069"),
            (access.SELF_SIGNED, "https://192.0.2.8/"),
            (access.HTTP, "http://192.0.2.8/"),
        ):
            with self.subTest(mode):
                vm = dict(self.VM, access=mode) if mode else self.VM
                self.assertEqual((None, url), mon.web_target(vm))
        vm = dict(self.VM, access=access.LETSENCRYPT, domain=DOMAINE)
        self.assertEqual((None, f"https://{DOMAINE}/"), mon.web_target(vm))

    def test_behind_proxmox_the_tunnel_reaches_nginx(self):
        for mode, cible in ((access.SELF_SIGNED, 443), (access.HTTP, 80)):
            with self.subTest(mode):
                m = access.get(mode)
                argv, url = mon.web_target(dict(self.VM, access=mode, pve=PVE))
                self.assertIn(f"{m.tunnel_port}:198.51.100.5:{cible}", argv)
                self.assertEqual(
                    f"{m.scheme}://127.0.0.1:{m.tunnel_port}/", url
                )
        # Let's Encrypt : le domaine, jamais un tunnel vers l'adresse.
        vm = dict(self.VM, access=access.LETSENCRYPT, domain=DOMAINE, pve=PVE)
        self.assertEqual((None, f"https://{DOMAINE}/"), mon.web_target(vm))
        # Direct : le tunnel de toujours, vers 8069.
        argv, _url = mon.web_target(dict(self.VM, pve=PVE))
        self.assertIn("18069:198.51.100.5:8069", argv)

    def _entrees(self, web, cmd=ODOO_18, prod=True):
        vu = {}
        t_ = todo()
        t_._qemu_import_module = lambda: object()
        t_._qemu_vm_meta = lambda nom, mod: ("ubuntu", "24.04", "amd64")

        def capture(vms, branche, remote):
            vu["vms"] = vms
            raise SystemExit

        with mock.patch.object(mon, "launch_installs", capture):
            with contextlib.suppress(SystemExit):
                t_._qemu_install_erplibre_monitored(
                    ["vm-o"],
                    "develop",
                    {"vm-o": "192.0.2.8"},
                    cmd,
                    prod,
                    web_access=web,
                )
        return vu["vms"]

    def test_the_manifest_entry_carries_the_mode(self):
        entree = self._entrees({"prod": True, **LE})[0]
        self.assertEqual(access.LETSENCRYPT, entree["access"])
        self.assertEqual(DOMAINE, entree["domain"])

    def test_direct_old_and_dev_entries_carry_nothing(self):
        for nom, web, prod in (
            ("direct", {"access": access.DIRECT}, True),
            ("ancienne", {"prod": True}, True),
            ("dev", {"access": access.SELF_SIGNED}, False),
        ):
            with self.subTest(nom):
                entree = self._entrees(web, prod=prod)[0]
                self.assertNotIn("access", entree)


class TestLeGuide(unittest.TestCase):
    def test_the_guide_tables_match_the_registry(self):
        # deploy_qemu.py reste autonome : sa table locale suit access.py.
        nginx = {m.key: m for m in access.MODES if m.nginx}
        self.assertEqual(set(nginx), set(dq.WEB_ACCESS_GUIDE))
        self.assertEqual(access.DIRECT, dq.WEB_ACCESS_DIRECT)
        for cle, (url, _fr, _en) in dq.WEB_ACCESS_GUIDE.items():
            with self.subTest(cle):
                m = nginx[cle]
                self.assertTrue(url.startswith(f"{m.scheme}://"), url)
                self.assertEqual(m.needs_domain, "{domain}" in url)

    def test_the_cli_accepts_every_mode(self):
        action = next(
            a for a in dq.build_parser()._actions if a.dest == "web_access"
        )
        self.assertEqual(set(access.ALL_KEYS), set(action.choices))
        self.assertEqual(access.DIRECT, action.default)

    def _motd(self, **kw):
        return dq.build_motd(
            "ubuntu", "24.04", "amd64", "en", "/opt/erplibre", "", "", **kw
        )

    def test_the_motd_gives_the_nginx_url(self):
        self.assertIn("https://<ip>/", self._motd(access=access.SELF_SIGNED))
        self.assertIn("http://<ip>/", self._motd(access=access.HTTP))
        txt = self._motd(access=access.LETSENCRYPT, domain=DOMAINE)
        self.assertIn(f"https://{DOMAINE}/", txt)
        self.assertIn("sudo systemctl reload nginx", txt)
        self.assertNotIn(":8069", txt)

    def test_direct_keeps_the_8069_line(self):
        self.assertEqual(self._motd(), self._motd(access=access.DIRECT))
        self.assertIn("http://<ip>:8069", self._motd())
        self.assertNotIn("nginx", self._motd())

    def test_the_motd_stays_within_80_columns(self):
        txt = self._motd(access=access.LETSENCRYPT, domain=DOMAINE)
        self.assertLessEqual(max(len(lg) for lg in txt.splitlines()), 80)

    def _parts(self, **kw):
        return todo()._qemu_build_deploy_parts(
            "ubuntu",
            "24.04",
            "amd64",
            "vm",
            4096,
            2,
            "40G",
            None,
            "develop",
            dry_run=True,
            prod=True,
            install_cmd=ODOO_18,
            **kw,
        )

    def test_the_deploy_command_names_the_mode(self):
        p = self._parts(web_access=access.LETSENCRYPT, web_domain=DOMAINE)
        self.assertEqual(access.LETSENCRYPT, p[p.index("--web-access") + 1])
        self.assertEqual(DOMAINE, p[p.index("--web-domain") + 1])
        self.assertNotIn("--web-access", self._parts())
        self.assertNotIn("--web-access", self._parts(web_access=access.DIRECT))


class TestLInvite(unittest.TestCase):
    def _ask(self, cmd, reponses):
        with mock.patch("builtins.input", side_effect=list(reponses)):
            with contextlib.redirect_stdout(io.StringIO()):
                return todo()._qemu_ask_access(cmd)

    def test_blank_is_self_signed(self):
        self.assertEqual(
            {"access": access.SELF_SIGNED, "domain": "", "email": ""},
            self._ask(ODOO_18, [""]),
        )

    def test_lets_encrypt_asks_again_until_valid(self):
        rang = str(1 + [m.key for m in access.MODES].index(access.LETSENCRYPT))
        self.assertEqual(
            {
                "access": access.LETSENCRYPT,
                "domain": DOMAINE,
                "email": COURRIEL,
            },
            self._ask(ODOO_18, [rang, "", "erp", DOMAINE, "admin", COURRIEL]),
        )

    def test_nothing_is_asked_without_modes(self):
        for cmd in (NON_ERP, qd.INSTALL_CMD):
            with self.subTest(cmd):
                self.assertEqual(access.DIRECT, self._ask(cmd, [])["access"])


@unittest.skipUnless(TEXTUAL, "Textual absent")
class TestLesFormulaires(unittest.TestCase):
    """Le champ « Accès web » sur les deux écrans, et ce qu'il produit."""

    def test_production_reveals_the_field_with_its_default(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Checkbox

                    vu["avant"] = app.query_one("#f_access").display
                    vu["dev"] = app._form_values()["install"]["access"]
                    app.query_one("#f_prod", Checkbox).value = True
                    await pilote.pause()
                    await pilote.pause()
                    vu["apres"] = app.query_one("#f_access").display
                    vu["domaine"] = app.query_one("#f_access_domain").display
                    vu["install"] = app._form_values()["install"]

                vu = scenario(nom, ["ubuntu"], gestes)
                self.assertFalse(vu["avant"])
                self.assertEqual(access.DIRECT, vu["dev"])
                self.assertTrue(vu["apres"])
                self.assertFalse(vu["domaine"])
                self.assertEqual(access.SELF_SIGNED, vu["install"]["access"])

    def test_lets_encrypt_asks_for_the_domain_and_refuses_f5(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Checkbox, Input, Select

                    app.query_one("#f_prod", Checkbox).value = True
                    await pilote.pause()
                    app.query_one("#f_access", Select).value = (
                        access.LETSENCRYPT
                    )
                    await pilote.pause()
                    await pilote.pause()
                    vu["champs"] = (
                        app.query_one("#f_access_domain").display,
                        app.query_one("#f_access_email").display,
                    )
                    with mock.patch.object(type(app), "notify") as dit:
                        app.action_deploy()
                        await pilote.pause()
                    vu["dit"] = " ".join(
                        str(c.args[0]) for c in dit.call_args_list
                    )
                    vu["refus"] = spec_rendue(nom, app)
                    app.query_one("#f_access_domain", Input).value = DOMAINE
                    app.query_one("#f_access_email", Input).value = COURRIEL
                    await pilote.pause()
                    vu["install"] = app._form_values()["install"]

                vu = scenario(nom, ["ubuntu"], gestes)
                self.assertEqual((True, True), vu["champs"])
                self.assertIsNone(vu["refus"])
                self.assertIn(t("Let's Encrypt needs a domain."), vu["dit"])
                self.assertEqual(
                    (access.LETSENCRYPT, DOMAINE, COURRIEL),
                    tuple(
                        vu["install"][k] for k in ("access", "domain", "email")
                    ),
                )

    def test_dolibarr_hides_the_field(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Checkbox

                    app.query_one("#f_prod", Checkbox).value = True
                    await pilote.pause()
                    await commun(app, pilote, qd.APP_DOLIBARR)
                    vu["vu"] = app.query_one("#f_access").display
                    vu["access"] = app._form_values()["install"]["access"]

                vu = scenario(nom, ["ubuntu"], gestes)
                self.assertFalse(vu["vu"])
                self.assertEqual(access.DIRECT, vu["access"])

    def test_an_old_prod_snapshot_replays_as_direct(self):
        # Un instantané d'historique de production pris avant le champ.
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Checkbox

                    app.query_one("#f_prod", Checkbox).value = True
                    await pilote.pause()
                    app._hist_prepare({"widgets": {"f_prod": True}})
                    app._sync_access()
                    vu["install"] = app._form_values()["install"]

                vu = scenario(nom, ["ubuntu"], gestes)
                self.assertTrue(vu["install"]["prod"])
                self.assertEqual(access.DIRECT, vu["install"]["access"])

    def test_a_nixos_row_says_why_until_direct(self):
        for nom in FORMES:
            with self.subTest(nom):

                async def gestes(app, pilote, vu):
                    from textual.widgets import Checkbox, Select

                    app.query_one("#f_prod", Checkbox).value = True
                    await pilote.pause()
                    await pilote.pause()
                    i = next(
                        k
                        for k, r in enumerate(app.rows)
                        if r["vm"]["distro"] == "nixos"
                    )
                    vu["avant"] = app._row_head(i, app.rows[i])
                    app.query_one("#f_access", Select).value = access.DIRECT
                    await pilote.pause()
                    await pilote.pause()
                    vu["apres"] = app._row_head(i, app.rows[i])

                vu = scenario(nom, ["ubuntu", "nixos"], gestes)
                self.assertIn(f"✗ {t(access.NIXOS_REFUSAL)}", vu["avant"])
                self.assertNotIn("✗", vu["apres"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
