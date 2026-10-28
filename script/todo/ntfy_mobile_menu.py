#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le menu « Préparer ntfy pour ERPLibre mobile » : prépare, liste, révoque.

La frontière avec `ntfy_mobile.py` est nette : ici on DEMANDE (quelle
machine, quel téléphone, quelles adresses) et on affiche ; là-bas on décide
et on construit les scripts `sh`. Chaque script passe par `host.run`, que
l'hôte soit cette machine ou une cible ssh.

Le jeton du téléphone n'existe que dans le lien affiché : il n'est écrit dans
aucun fichier.
"""

import base64
import binascii
import socket
import time
import urllib.parse

import click

from script.todo import ntfy_mobile as nm
from script.todo.todo_i18n import t

# Redémarrages lents : l'état `activating` est relu ce nombre de fois, à
# cette cadence, avant de conclure à un échec.
RESTART_RECHECKS = 5
RESTART_RECHECK_SECONDS = 1
RECHECK_SCRIPT = "systemctl is-active ntfy\n"

RATE_LIMITING_PROBLEM = "ntfy_mobile_subscriber_rate_limiting"
LOCAL_URL_HOSTS = ("localhost", "127.0.0.1")
SKIP = "-"


def _yes(prompt):
    return input(prompt).strip().lower() in ("y", "yes", "o", "oui")


class NtfyMobileMenuMixin:
    def prompt_execute_ntfy_mobile(self):
        print(f"\n{t('Deploy - Prepare ntfy for ERPLibre mobile')}")
        choices = [
            {"prompt_description": t("Prepare a phone")},
            {"prompt_description": t("List the prepared phones")},
            {"prompt_description": t("Revoke a phone")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._ntfy_mobile_prepare()
            elif status == "2":
                self._ntfy_mobile_list()
            elif status == "3":
                self._ntfy_mobile_revoke()
            else:
                print(t("Command not found !"))

    def _ntfy_mobile_host(self):
        """LocalHost ou SshHost selon le choix ; None si l'on renonce."""
        print(t("Run on this machine or over ssh?"))
        print(f"[1] {t('This machine')}")
        print(f"[2] {t('Over ssh')}")
        choice = input(t("Your choice (1/2): ")).strip()
        if choice == "2":
            chosen = self._ask_ssh_target()
            return nm.SshHost(chosen[0]) if chosen else None
        return nm.LocalHost()

    def _ntfy_mobile_lan_address(self):
        """Adresse de cette machine sur le réseau local, sans émettre de
        paquet (connect UDP : le noyau choisit l'interface de sortie)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.connect(("192.0.2.1", 9))
            return sock.getsockname()[0]
        except OSError:
            return "127.0.0.1"
        finally:
            sock.close()

    def _ntfy_mobile_inspect(self, host):
        """(config, texte, clés, propriétaire) ou None, message affiché.

        Lit le `server.yml` en root : root lit tous les fichiers.
        """
        default = nm.DEFAULT_CONFIG
        config = input(f"{t('ntfy configuration file')} [{default}]: ")
        config = config.strip() or default
        _code, out = host.run(nm.inspect_script(config), sudo_user=None)
        markers = nm.parse_markers(out)
        try:
            text = base64.b64decode(markers.get("YML", ""), validate=True)
            text = text.decode("utf-8")
        except (binascii.Error, UnicodeDecodeError):
            text = ""
        if not text:
            print(f"✗ {t('The ntfy configuration could not be read.')}")
            return None
        keys = nm.read_yml_keys(text)
        owner = markers.get("OWNER", "?")
        return config, text, keys, owner

    def _ntfy_mobile_owner_known(self, owner):
        if owner and owner != "?":
            return True
        print(f"✗ {t('The owner of the ntfy auth file is unknown.')}")
        return False

    def _ntfy_mobile_wait_active(self, host, state):
        """Vrai quand ntfy est `active`, en relisant `activating`."""
        rechecks = 0
        while state == "activating" and rechecks < RESTART_RECHECKS:
            time.sleep(RESTART_RECHECK_SECONDS)
            _code, out = host.run(RECHECK_SCRIPT, sudo_user=None)
            state = out.strip().splitlines()[-1] if out.strip() else ""
            rechecks += 1
        if state == "active":
            print(f"✓ {t('ntfy restarted and active.')}")
            return True
        print(f"✗ {t('ntfy is not active after the restart:')} {state}")
        return False

    def _ntfy_mobile_prepare(self):
        print(f"\n{t('Deploy - Prepare ntfy for ERPLibre mobile')}")
        host = self._ntfy_mobile_host()
        if host is None:
            return
        inspected = self._ntfy_mobile_inspect(host)
        if inspected is None:
            return
        config, text, keys, owner = inspected

        problems = nm.config_problems(keys)
        blocking = [p for p in problems if p != RATE_LIMITING_PROBLEM]
        if blocking:
            for problem in blocking:
                print(f"✗ {t(problem)}")
            print(
                t(
                    "Fix this with: Deploy - Install NTFY notification"
                    " server."
                )
            )
            return
        if not self._ntfy_mobile_owner_known(owner):
            return

        if not self._ntfy_mobile_apply_config(
            host, config, text, problems, owner
        ):
            return

        label = input(t("Phone name (e.g. Alice's phone): ")).strip()
        try:
            user = nm.phone_user(label)
        except ValueError:
            print(f"✗ {t('This name has no usable character.')}")
            return
        prefix = nm.random_prefix()
        _code, out = host.run(
            nm.access_script(config, user, prefix), sudo_user=owner
        )
        token = nm.parse_token(out)
        if token is None:
            print(f"✗ {t('The phone access could not be created.')}")
            return

        phone_url, odoo_url = self._ntfy_mobile_ask_urls(host, keys)
        link = nm.build_link(
            phone_url, token, prefix, nm.cache_seconds(keys), odoo_url
        )
        qr = nm.render_qr(link)
        print(f"\n✓ {t('Phone access ready:')} {user}")
        if qr:
            print(f"\n{t('Scan this code with the ERPLibre mobile app:')}")
            print(qr)
        else:
            print(
                f"\n{t('QR code unavailable, install it with:')}"
                " pip install -r requirement/erplibre_require-ments.txt"
            )
        print(link)
        print(
            f"\n⚠ {t('This link gives access to the notifications of this phone: do not share it.')}"
        )

    def _ntfy_mobile_apply_config(self, host, config, text, problems, owner):
        """Propose les ajustements du `server.yml` ; Faux pour arrêter."""
        ssh = isinstance(host, nm.SshHost)
        default = "" if ssh else "127.0.0.1"
        shown = default or SKIP
        raw = input(
            f"{t('Odoo server source addresses to exempt from rate limits, comma separated')}"
            f" [{shown}]: "
        ).strip()
        raw = default if raw == "" else raw
        hosts = [] if raw == SKIP else [h.strip() for h in raw.split(",")]
        hosts = [h for h in hosts if h]
        if not hosts:
            print(
                f"⚠ {t('No address exempted: a busy Odoo server hits HTTP 429 and loses pushes.')}"
            )

        new = nm.with_exempt_hosts(text, hosts) if hosts else text
        if RATE_LIMITING_PROBLEM in problems:
            new = nm.with_subscriber_rate_limiting_off(new)
        if new == text:
            return True

        print(f"\n{t('Proposed changes to the ntfy configuration:')}")
        print(nm.unified_diff(text, new, config))
        if not _yes(
            t("Write this configuration (a backup copy is kept)? (y/N): ")
        ):
            stays = [
                key
                for key in (nm.EXEMPT_HOSTS_KEY, nm.RATE_LIMITING_KEY)
                if nm.read_yml_keys(new).get(key)
                != nm.read_yml_keys(text).get(key)
            ]
            print(
                f"⚠ {t('Configuration left unchanged, not applied:')}"
                f" {', '.join(stays)}"
            )
            return True
        stamp = time.strftime("%Y%m%d%H%M%S")
        code, _out = host.run(
            nm.write_yml_script(config, new, stamp), sudo_user=None
        )
        if code != 0:
            print(f"✗ {t('The configuration could not be written.')}")
            return False
        print(f"✓ {t('Configuration written.')}")
        if not _yes(t("Restart ntfy now to apply it? (y/N): ")):
            print(
                f"⚠ {t('Not restarted: the change applies at the next ntfy restart.')}"
            )
            return True
        _code, out = host.run(nm.restart_script(), sudo_user=None)
        state = nm.parse_markers(out).get("ACTIVE", "")
        return self._ntfy_mobile_wait_active(host, state)

    def _ntfy_mobile_ask_urls(self, host, keys):
        """(URL côté téléphone, URL côté Odoo)."""
        port = keys.get("listen-http", "").rsplit(":", 1)[-1] or "80"
        base = keys.get("base-url", "")
        base_host = urllib.parse.urlsplit(base).hostname or ""
        if base and base_host not in LOCAL_URL_HOSTS:
            default = base
        elif isinstance(host, nm.SshHost):
            default = f"http://{host.target.rsplit('@', 1)[-1]}:{port}"
        else:
            default = f"http://{self._ntfy_mobile_lan_address()}:{port}"
        phone_url = input(
            f"{t('URL the phone reaches ntfy at')} [{default}]: "
        ).strip()
        phone_url = phone_url or default
        odoo_url = input(
            f"{t('URL the Odoo server publishes to (Enter: same)')}"
            f" [{phone_url}]: "
        ).strip()
        return phone_url, odoo_url or phone_url

    def _ntfy_mobile_phones(self, host):
        """(config, owner, [utilisateurs]) ou None."""
        inspected = self._ntfy_mobile_inspect(host)
        if inspected is None:
            return None
        config, _text, _keys, owner = inspected
        if not self._ntfy_mobile_owner_known(owner):
            return None
        _code, out = host.run(nm.list_script(config), sudo_user=owner)
        return config, owner, nm.phone_users(out)

    def _ntfy_mobile_list(self):
        print(f"\n📱 {t('List the prepared phones')}")
        host = self._ntfy_mobile_host()
        if host is None:
            return
        found = self._ntfy_mobile_phones(host)
        if found is None:
            return
        users = found[2]
        if not users:
            print(t("No phone prepared."))
            return
        for user in users:
            print(f"  {user}")

    def _ntfy_mobile_revoke(self):
        print(f"\n📱 {t('Revoke a phone')}")
        host = self._ntfy_mobile_host()
        if host is None:
            return
        found = self._ntfy_mobile_phones(host)
        if found is None:
            return
        config, owner, users = found
        if not users:
            print(t("No phone prepared."))
            return
        for number, user in enumerate(users, 1):
            print(f"[{number}] {user}")
        raw = input(t("Phone to revoke (number): ")).strip()
        if not raw.isdigit() or not 1 <= int(raw) <= len(users):
            print(t("Invalid selection!"))
            return
        user = users[int(raw) - 1]
        print(user)
        if not _yes(t("Revoke the access of this phone? (y/N): ")):
            return
        code, _out = host.run(nm.revoke_script(config, user), sudo_user=owner)
        if code != 0:
            print(f"✗ {t('The revocation failed.')}")
            return
        print(f"✓ {t('Access revoked.')}")
