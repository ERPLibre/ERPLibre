#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le sous-menu « Infrastructure d'appel » : installer coturn et ntfy sur un
hôte, préparer ntfy pour ERPLibre mobile, vérifier, désinstaller.

Même frontière que `ntfy_mobile_menu.py` : ici on DEMANDE et on affiche ;
`call_infra.py` décide et construit les scripts `sh`, que `host.run` lance
en root sur cette machine ou par ssh. Un refus (`call_infra.Refusal`) et une
ligne du verdict (`CheckLine`) portent une clé i18n et ses valeurs, rendues
ici par `t(clé).format(**valeurs)`.

Secrets : le mot de passe du compte de contrôle de coturn naît sur l'hôte,
dans son installateur ; la ligne `@@CHECK_KEY` de la vérification est
masquée à l'écran ; le mot de passe administrateur de ntfy n'est affiché
qu'une fois, après l'installation.
"""

import codecs
import contextlib
import dataclasses
import datetime
import os
import sys
import time

import click

from script.todo import call_infra as ci
from script.todo import ntfy_mobile as nm
from script.todo.todo_i18n import t

# Ce que sudo écrit quand il refuse : trois essais manqués, ou un mot de
# passe exigé sans terminal pour le demander.
SUDO_REFUSED = ("incorrect password", "a password is required")
CHECK_KEY_LINE = "@@CHECK_KEY"
ADMIN_PASSWORD_LINE = "@@ADMIN_PASSWORD"
SERVICE_CHOICES = {
    "1": frozenset({"coturn", "ntfy"}),
    "2": frozenset({"coturn"}),
    "3": frozenset({"ntfy"}),
}
SYMBOLS = {True: "✓", False: "✗", None: "?"}


def _yes(prompt):
    return input(prompt).strip().lower() in ("y", "yes", "o", "oui")


class _HiddenLines:
    """Sortie standard de remplacement pendant `host.run`.

    `ntfy_mobile._tee_run` écrit chaque octet dans `sys.stdout.buffer` :
    ici, ces octets passent à `target`, sauf les lignes qui commencent par
    un des `prefixes`, remplacées par « <préfixe> *** ». Une ligne est
    décidée dès que son début ne peut plus être un préfixe, si bien que
    l'invite de sudo, sans fin de ligne, s'affiche aussitôt. Le texte écrit
    par `print` passe tel quel. `finish()` rend ce qui reste en attente.
    """

    def __init__(self, target, prefixes):
        self._target = target
        self._raw = getattr(target, "buffer", None)
        self._decoder = codecs.getincrementaldecoder("utf-8")("replace")
        self._prefixes = tuple(p.encode("utf-8") for p in prefixes)
        self._line = bytearray()
        self._hidden = None
        self._passing = not self._prefixes
        self.buffer = self

    def write(self, data):
        if isinstance(data, str):
            self._target.write(data)
            return len(data)
        for value in data:
            self._feed(bytes([value]))
        return len(data)

    def flush(self):
        if self._raw is not None:
            self._raw.flush()
        self._target.flush()

    def finish(self):
        if self._line:
            self._emit(bytes(self._line))
            self._line.clear()
        self.flush()

    def _emit(self, data):
        if self._raw is not None:
            self._raw.write(data)
        else:
            self._target.write(self._decoder.decode(data))

    def _feed(self, byte):
        if byte == b"\n":
            if self._hidden is not None:
                self._emit(self._hidden + b" ***\n")
            else:
                self._emit(bytes(self._line) + byte)
            self._line.clear()
            self._hidden = None
            self._passing = not self._prefixes
            return
        if self._passing:
            self._emit(byte)
            return
        if self._hidden is not None:
            return
        self._line += byte
        for prefix in self._prefixes:
            if self._line.startswith(prefix):
                self._hidden = prefix
                self._line.clear()
                return
        if not any(p.startswith(self._line) for p in self._prefixes):
            self._emit(bytes(self._line))
            self._line.clear()
            self._passing = True


class CallInfraMenuMixin:
    def prompt_execute_call_infra(self):
        print(f"\n{t('Deploy - Call infrastructure')}")
        choices = [
            {
                "prompt_description": t(
                    "Call infra - Install on a host (coturn, ntfy)"
                )
            },
            {
                "prompt_description": t(
                    "Call infra - Prepare ntfy for ERPLibre mobile"
                )
            },
            {"prompt_description": t("Call infra - Check")},
            {"prompt_description": t("Call infra - Uninstall")},
        ]
        help_info = self.fill_help_info(choices)
        while True:
            status = click.prompt(help_info)
            print()
            if status == "0":
                return False
            elif status == "1":
                self._call_infra_install()
            elif status == "2":
                self.prompt_execute_ntfy_mobile()
            elif status == "3":
                self._call_infra_check()
            elif status == "4":
                self._call_infra_uninstall()
            else:
                print(t("Command not found !"))

    def _call_infra_host(self):
        """LocalHost ou SshHost, le choix de `_ntfy_mobile_host` ; None si
        l'on renonce. Sur cette machine, un ntfy déjà installé est annoncé
        comme ADOPTÉ : sa configuration est montrée en diff et sauvée, ses
        comptes et jetons restent."""
        host = self._ntfy_mobile_host()
        if isinstance(host, nm.LocalHost) and self._call_infra_local_ntfy():
            print(f"⚠ {t('call_infra_local_ntfy_adopted')}")
        return host

    def _call_infra_local_ntfy(self):
        """Vrai quand la configuration de ntfy existe sur cette machine. Un
        `stat`, rien de lancé : la sonde, en root, lira le reste."""
        return os.path.exists(ci.NTFY_CONFIG)

    # --- Exécution et rendu -------------------------------------------------

    def _call_infra_run(self, host, script, hide=()):
        """(code, sortie) de `script` lancé en root par `host`, ou None
        quand sudo a refusé (ligne `call_infra_sudo_refused` affichée).

        Les lignes qui commencent par un des préfixes `hide` sont masquées
        à l'écran et gardées dans la sortie rendue.
        """
        writer = _HiddenLines(sys.stdout, hide)
        with contextlib.redirect_stdout(writer):
            try:
                code, out = host.run(script, sudo_user=None)
            finally:
                writer.finish()
        if code != 0 and any(s in out.lower() for s in SUDO_REFUSED):
            print(f"✗ {t('call_infra_sudo_refused')}")
            return None
        return code, out

    @staticmethod
    def _call_infra_text(key, values):
        """`t(key)` rempli de `values` ; le texte brut suivi des valeurs
        quand un champ manque, plutôt qu'une trace."""
        text = t(key)
        try:
            return text.format(**values)
        except (KeyError, IndexError, ValueError):
            return f"{text} {values}"

    def _call_infra_refuse(self, refusal):
        print(f"✗ {self._call_infra_text(refusal.key, refusal.values)}")

    def _call_infra_probe(self, host):
        """`HostFacts` de l'hôte, ou None, la raison affichée."""
        result = self._call_infra_run(host, ci.probe_script())
        if result is None:
            return None
        try:
            return ci.parse_probe(result[1])
        except ci.Refusal as refusal:
            self._call_infra_refuse(refusal)
            return None

    @staticmethod
    def _call_infra_ask(label, default):
        raw = input(f"{label} [{default}]: ").strip()
        return raw or str(default)

    def _call_infra_ask_int(self, label, default):
        raw = self._call_infra_ask(label, default)
        if raw.isdigit():
            return int(raw)
        print(f"✗ {t('Not a number:')} {raw}")
        return None

    def _call_infra_ask_range(self, label, low, high):
        raw = self._call_infra_ask(label, f"{low}-{high}")
        parts = raw.split("-")
        if len(parts) == 2 and all(p.strip().isdigit() for p in parts):
            return int(parts[0]), int(parts[1])
        print(f"✗ {t('Not a port range:')} {raw}")
        return None

    @staticmethod
    def _call_infra_read_file(label):
        """Contenu d'un fichier de CETTE machine, ou None, la raison
        affichée."""
        path = os.path.expanduser(input(f"{label}: ").strip())
        if not path:
            print(f"✗ {t('A file is required.')}")
            return None
        try:
            with open(path, encoding="utf-8") as handle:
                return handle.read()
        except (OSError, UnicodeDecodeError) as error:
            print(f"✗ {t('The file could not be read:')} {path} ({error})")
            return None

    @staticmethod
    def _call_infra_default_name(host, facts):
        """Nom public proposé : l'hôte réel joint par ssh, sinon la
        première adresse globale de l'hôte, sinon son nom."""
        if isinstance(host, nm.SshHost):
            return host.hostname or host.target.rsplit("@", 1)[-1]
        if facts.addresses:
            return facts.addresses[0]
        return facts.hostname

    # --- Installer ----------------------------------------------------------

    def _call_infra_install(self):
        print(f"\n{t('Call infra - Install on a host (coturn, ntfy)')}")
        host = self._call_infra_host()
        if host is None:
            return
        facts = self._call_infra_probe(host)
        if facts is None:
            return
        # Les refus de système passent avant les questions : `plan_install`
        # les ferait aussi, mais seulement une fois tout demandé.
        if facts.family is None:
            self._call_infra_refuse(
                ci.Refusal(
                    "call_infra_unsupported_os",
                    os=facts.os_id or "?",
                    supported=ci.SUPPORTED,
                )
            )
            return
        if not facts.systemd:
            self._call_infra_refuse(ci.Refusal("call_infra_no_systemd"))
            return
        print(
            f"{t('Host:')} {facts.hostname} — {facts.os_id}"
            f" {facts.os_version} — {', '.join(facts.addresses)}"
        )
        answers = self._call_infra_ask_answers(host, facts)
        if answers is None:
            return
        try:
            plan = ci.plan_install(
                facts, answers, datetime.datetime.now(datetime.timezone.utc)
            )
        except ci.Refusal as refusal:
            self._call_infra_refuse(refusal)
            return
        if plan.nothing_to_do:
            print(f"✓ {t('call_infra_nothing_to_change')}")
            return
        self._call_infra_show_plan(plan)
        if not _yes(t("Install now? (y/N): ")):
            print(t("Nothing installed."))
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        result = self._call_infra_run(
            host,
            ci.install_script(plan, stamp),
            hide=(ADMIN_PASSWORD_LINE,),
        )
        if result is None or not self._call_infra_installed(*result):
            return
        state = ci.written_state(plan, stamp)
        record = self._call_infra_firewall(
            host, facts, answers, state.get("firewall")
        )
        self._call_infra_save_state(host, ci.with_firewall(state, record))
        self._call_infra_report(host)

    def _call_infra_ask_answers(self, host, facts):
        """`Answers` des questions, préremplies par l'état d'un passage
        précédent ; None si une réponse ne se lit pas (raison affichée)."""
        prior = ci.state_answers(facts.state)
        default_name = self._call_infra_default_name(host, facts)
        if prior is None:
            prior = ci.Answers(
                services=frozenset(ci.SERVICES),
                tls="none",
                cert_pem=None,
                key_pem=None,
                public_name=default_name,
            )
        print(f"\n{t('Services to install:')}")
        print(f"[1] {t('coturn and ntfy')}")
        print(f"[2] {t('coturn only')}")
        print(f"[3] {t('ntfy only')}")
        default = next(
            k for k, v in SERVICE_CHOICES.items() if v == prior.services
        )
        choice = self._call_infra_ask(t("Your choice (1/2/3)"), default)
        services = SERVICE_CHOICES.get(choice)
        if services is None:
            print(t("Invalid selection!"))
            return None

        print(f"\n{t('Certificate:')}")
        print(f"[1] {t('call_infra_tls_none')}")
        print(
            f"[2] {t('Supplied: certificate and key files of this machine')}"
        )
        choice = self._call_infra_ask(
            t("Your choice (1/2)"), "2" if prior.tls == "supplied" else "1"
        )
        if choice not in ("1", "2"):
            print(t("Invalid selection!"))
            return None
        tls = "supplied" if choice == "2" else "none"
        cert_pem = key_pem = None
        if tls == "supplied":
            cert_pem = self._call_infra_read_file(t("Certificate file (PEM)"))
            if cert_pem is None:
                return None
            key_pem = self._call_infra_read_file(t("Private key file (PEM)"))
            if key_pem is None:
                return None

        name = self._call_infra_ask(
            t("Public name of the host (name or address)"),
            prior.public_name or default_name,
        )
        ports = {}
        if "coturn" in services:
            ports["turn_port"] = self._call_infra_ask_int(
                t("TURN port (udp and tcp)"), prior.turn_port
            )
            if ports["turn_port"] is None:
                return None
            if tls == "supplied":
                ports["turns_port"] = self._call_infra_ask_int(
                    t("TURNS port (tcp, TLS)"), prior.turns_port
                )
                if ports["turns_port"] is None:
                    return None
            relays = self._call_infra_ask_range(
                t("Media relay port range (udp)"),
                prior.min_port,
                prior.max_port,
            )
            if relays is None:
                return None
            ports["min_port"], ports["max_port"] = relays
        if "ntfy" in services:
            # Le port de ntfy suit le mode : celui de l'état ne vaut que si
            # le mode est le même (8080 en http, 8443 avec un certificat).
            same_mode = prior.tls == tls
            default_port = ci.ntfy_port(
                dataclasses.replace(
                    prior,
                    tls=tls,
                    ntfy_port=prior.ntfy_port if same_mode else None,
                )
            )
            ports["ntfy_port"] = self._call_infra_ask_int(
                t("ntfy port (tcp)"), default_port
            )
            if ports["ntfy_port"] is None:
                return None
        return ci.Answers(
            services=services,
            tls=tls,
            cert_pem=cert_pem,
            key_pem=key_pem,
            public_name=name,
            external_ip=prior.external_ip,
            **ports,
        )

    def _call_infra_show_plan(self, plan):
        answers = plan.answers
        chosen = [s for s in ci.SERVICES if s in answers.services]
        print(f"\n{t('Summary')}")
        print(f"  {t('Services:')} {', '.join(chosen)}")
        print(f"  {t('Mode:')} {t('development')}")
        if answers.tls == "none":
            print(f"  {t('TLS:')} {t('call_infra_tls_none')}")
        else:
            print(f"  {t('TLS:')} {t('supplied certificate')}")
        print(f"  {t('Public name:')} {answers.public_name}")
        opened = ", ".join(
            f"{r.port}/{r.proto} {r.service}"
            for r in ci.firewall_rules(answers)
        )
        print(f"  {t('Ports:')} {opened}")
        if "coturn" in answers.services:
            print(f"  ⚠ {t('call_infra_private_ranges_allowed')}")
        for svc in plan.adopt:
            record = plan.new_state["services"][svc]
            print(
                "  ⚠ "
                + self._call_infra_text(
                    "call_infra_adopted",
                    {"service": svc, "config": record["config"]},
                )
            )
        for path, diff in plan.diffs:
            print(f"\n{t('Changes to')} {path} :")
            print(diff)

    def _call_infra_installed(self, code, out):
        """Vrai quand le script a écrit l'état (`@@SAVED yes`). La dernière
        ligne `@@ACTIVE` d'un service fait foi : son installateur en
        imprime une, le script la sienne après lui."""
        saved, active, failed, password = "", {}, [], ""
        for name, value in ci.marker_lines(out):
            if name == "SAVED":
                saved = value.strip()
            elif name == "ACTIVE":
                svc, _, current = value.partition(" ")
                active[svc] = current.strip()
            elif name == "FAILED":
                failed.append(value.strip())
            elif name == "ADMIN_PASSWORD" and value.strip():
                password = value.strip()
        for svc, current in active.items():
            print(f"{SYMBOLS[current == 'active']} {svc} : {current}")
        # Le compte de ntfy existe dès que son installateur l'a créé, même
        # si coturn échoue ensuite : son mot de passe n'est affiché qu'ici.
        if password:
            print(f"\n⚠ {t('call_infra_admin_password')}")
            print(f"  {password}\n")
        if code != 0 or saved != "yes":
            for step in failed:
                print(f"✗ {t('Step failed:')} {step}")
            print(f"✗ {t('call_infra_install_failed')}")
            return False
        print(f"✓ {t('call_infra_installed')}")
        return True

    def _call_infra_firewall(self, host, facts, answers, previous):
        """`state["firewall"]` après l'aperçu des règles et, sur un oui,
        leur ajout. Sans oui, les règles déjà consignées restent : elles
        sont encore sur l'hôte et la désinstallation doit les retirer."""
        kind = facts.firewall
        rules = ci.firewall_rules(answers)
        chain = facts.nft_chains[0] if len(facts.nft_chains) == 1 else None
        preview = ci.firewall_preview(kind, rules, chain)
        record = ci.firewall_record(kind, "", previous)
        if preview:
            print(
                f"\n{t('Firewall')} ({kind}) : {t('call_infra_firewall_preview')}"
            )
            for line in preview:
                print(f"  {line}")
            if _yes(t("Add these rules? (y/N): ")):
                result = self._call_infra_run(
                    host, ci.firewall_script(kind, rules, "allow")
                )
                if result is not None:
                    code, out = result
                    record = ci.firewall_record(kind, out, previous)
                    names = {name for name, _ in ci.marker_lines(out)}
                    if "FIREWALL_MANUAL" in names:
                        print(f"⚠ {t('call_infra_firewall_manual')}")
                    if code != 0:
                        print(f"✗ {t('call_infra_firewall_failed')}")
            else:
                print(t("No firewall rule added."))
        elif kind == "nftables":
            print(f"⚠ {t('call_infra_firewall_manual')}")
        for note in ci.firewall_notes(kind):
            print(f"⚠ {t(note)}")
        return record

    def _call_infra_save_state(self, host, state):
        result = self._call_infra_run(host, ci.state_write_script(state))
        if result is None:
            return False
        saved = [v for n, v in ci.marker_lines(result[1]) if n == "SAVED"]
        if result[0] != 0 or saved[-1:] != ["yes"]:
            print(f"✗ {t('call_infra_state_not_saved')}")
            return False
        return True

    # --- Vérifier -----------------------------------------------------------

    def _call_infra_check(self):
        print(f"\n{t('Call infra - Check')}")
        host = self._call_infra_host()
        if host is None:
            return
        self._call_infra_report(host)

    def _call_infra_report(self, host):
        """Lit l'hôte (`check_remote_script`, la clé masquée à l'écran) et
        affiche une ligne par `CheckLine` de `check_local`."""
        result = self._call_infra_run(
            host, ci.check_remote_script(), hide=(CHECK_KEY_LINE,)
        )
        if result is None:
            return
        try:
            remote = ci.parse_check_remote(result[1])
        except ci.Refusal as refusal:
            self._call_infra_refuse(refusal)
            return
        state = remote["state"] if isinstance(remote["state"], dict) else {}
        services = state.get("services")
        settings = [
            record["settings"]
            for record in (
                services.values() if isinstance(services, dict) else []
            )
            if isinstance(record, dict)
            and isinstance(record.get("settings"), dict)
        ]
        address, cafile = "", None
        if settings:
            names = [
                s["public_name"] for s in settings if s.get("public_name")
            ]
            address = self._call_infra_ask(
                t("Address that reaches the host from this machine"),
                names[0] if names else "",
            )
            if any(s.get("tls") == "supplied" for s in settings):
                raw = input(f"{t('call_infra_ask_cafile')}: ").strip()
                cafile = os.path.expanduser(raw) if raw else None
        print(f"\n{t('Call infra - Check')}")
        for line in ci.check_local(remote, address, cafile):
            print(self._call_infra_line(line))

    def _call_infra_line(self, line):
        labels = {
            "turn-udp": t("TURN over UDP"),
            "turn-tcp": t("TURN over TCP"),
            "turn-tls": t("TURN over TLS"),
            "ntfy-health": t("ntfy health"),
            "cert-expiry": t("Certificate expiry"),
            "firewall": t("Firewall rules"),
            "state": t("Host state"),
        }
        if line.name.startswith("service-"):
            label = f"{t('Service')} {line.name[len('service-'):]}"
        else:
            label = labels.get(line.name, line.name)
        detail = self._call_infra_text(line.detail, line.values)
        return f"{SYMBOLS.get(line.ok, '?')} {label} : {detail}"

    # --- Désinstaller -------------------------------------------------------

    def _call_infra_uninstall(self):
        print(f"\n{t('Call infra - Uninstall')}")
        host = self._call_infra_host()
        if host is None:
            return
        facts = self._call_infra_probe(host)
        if facts is None:
            return
        stamp = time.strftime("%Y%m%d-%H%M%S")
        if not isinstance(facts.state, dict):
            result = self._call_infra_run(
                host, ci.uninstall_script(None, False, stamp)
            )
            if result is None:
                return
            for name, value in ci.marker_lines(result[1]):
                if name == "PENDING":
                    print(
                        "⚠ "
                        + self._call_infra_text(
                            "call_infra_pending_left",
                            {"service": value.strip()},
                        )
                    )
            print(t("Nothing to uninstall."))
            return
        # L'état vient de l'hôte : il est validé avant toute question.
        try:
            ci.uninstall_script(facts.state, False, stamp)
        except ci.Refusal as refusal:
            self._call_infra_refuse(refusal)
            return
        self._call_infra_show_uninstall(facts.state)
        remove_data = _yes(t("call_infra_ask_remove_data"))
        if not _yes(t("Uninstall now? (y/N): ")):
            print(t("Nothing uninstalled."))
            return
        result = self._call_infra_run(
            host, ci.uninstall_script(facts.state, remove_data, stamp)
        )
        if result is not None:
            self._call_infra_uninstalled(*result)

    def _call_infra_show_uninstall(self, state):
        services = state.get("services")
        services = services if isinstance(services, dict) else {}
        print(f"\n{t('Recorded on the host:')}")
        for svc in ci.SERVICES:
            record = services.get(svc)
            if not isinstance(record, dict):
                continue
            if record.get("adopted"):
                what = self._call_infra_text(
                    "call_infra_uninstall_restores",
                    {
                        "config": record.get("config"),
                        "backup": record.get("backup"),
                    },
                )
            elif record.get("installed_by_tool"):
                what = t("call_infra_uninstall_purges")
            else:
                what = t("call_infra_uninstall_keeps_package")
            print(f"  {svc} : {what}")
        rules = ci.rules_from_state(state)
        if rules:
            listed = ", ".join(f"{r.port}/{r.proto}" for r in rules)
            print(f"  {t('Firewall rules removed:')} {listed}")

    def _call_infra_uninstalled(self, code, out):
        done, failed, missing, left = "", [], [], []
        for name, value in ci.marker_lines(out):
            if name == "DONE":
                done = value.strip()
            elif name == "FAILED":
                failed.append(value.strip())
            elif name == "BACKUP_MISSING":
                missing.append(value.strip())
            elif name == "PENDING_LEFT":
                left.append(value.strip())
            elif name == "BACKUP_LOST":
                svc, _, backup = value.strip().partition(" ")
                print(
                    "⚠ "
                    + self._call_infra_text(
                        "call_infra_backup_lost",
                        {"service": svc, "backup": backup},
                    )
                )
        for svc in left:
            print(
                "⚠ "
                + self._call_infra_text(
                    "call_infra_pending_left", {"service": svc}
                )
            )
        if code == 0 and done == "yes":
            print(f"✓ {t('call_infra_uninstalled')}")
            return True
        if done == "partial":
            for value in missing:
                svc, _, backup = value.partition(" ")
                print(
                    "⚠ "
                    + self._call_infra_text(
                        "call_infra_backup_missing",
                        {"service": svc, "backup": backup},
                    )
                )
            return False
        for step in failed:
            print(f"✗ {t('Step failed:')} {step}")
        print(f"✗ {t('call_infra_uninstall_failed')}")
        return False
