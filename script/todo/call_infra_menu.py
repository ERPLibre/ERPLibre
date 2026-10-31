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
import ipaddress
import os
import socket
import ssl
import sys
import time

import click

from script.todo import call_infra as ci
from script.todo import ntfy_mobile as nm
from script.todo.todo_i18n import t

# Code de sortie de ssh quand la connexion, ou le dépôt du script, échoue.
SSH_FAILED = 255
CHECK_KEY_LINE = "@@CHECK_KEY"
PROBE_HIDDEN = ("@@FILE", "@@PENDING", "@@STATE")
ADMIN_PASSWORD_LINE = "@@ADMIN_PASSWORD"
SERVICE_CHOICES = {
    "1": frozenset({"coturn", "ntfy"}),
    "2": frozenset({"coturn"}),
    "3": frozenset({"ntfy"}),
}
SYMBOLS = {True: "✓", False: "✗", None: "?"}
MODE_CHOICES = {"1": "development", "2": "production"}
YES_WORDS = ("y", "yes", "o", "oui")
# Greffons DNS de certbot qu'une distribution empaquette : Debian 13 n'en
# fournit que trois, Ubuntu 24.04 tous sauf luadns et nsone, Arch les neuf.
# install_certbot.sh refuse un greffon sans paquet ; le menu ne propose que
# ceux-là, plus ceux que la sonde trouve déjà installés. Un dérivé de
# Debian autre qu'Ubuntu reçoit la liste de Debian, la plus courte.
DNS_PLUGINS_PACKAGED = {
    "debian": ("cloudflare", "google", "rfc2136"),
    "ubuntu": tuple(p for p in ci.DNS_PLUGINS if p not in ("luadns", "nsone")),
    "arch": ci.DNS_PLUGINS,
}


def _yes(prompt):
    return input(prompt).strip().lower() in YES_WORDS


def _resolve(name, port):
    """Adresses de `name`, sous la forme de `socket.getaddrinfo` qu'attend
    `call_infra.external_ip_for`. Le nom se résout depuis cette machine,
    par le DNS public, celui que les clients et Let's Encrypt
    interrogent."""
    return socket.getaddrinfo(name, port)


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
        l'on renonce."""
        return self._ntfy_mobile_host()

    # --- Exécution et rendu -------------------------------------------------

    def _call_infra_run(self, host, script, hide=()):
        """(code, sortie) de `script` lancé en root par `host`, ou None
        quand sudo a refusé (ligne `call_infra_sudo_refused` affichée).

        Le refus se lit à la forme de la sortie, jamais à son texte, que
        sudo écrit dans la langue de l'utilisateur : chaque script imprime
        au moins une ligne `@@`, un code non nul sans aucune ne vient que
        d'un script qui n'a pas démarré. Le code de ssh (255) n'en est pas
        un : la connexion a échoué, et le message de ssh est déjà à
        l'écran.

        Les lignes qui commencent par un des préfixes `hide` sont masquées
        à l'écran et gardées dans la sortie rendue.
        """
        writer = _HiddenLines(sys.stdout, hide)
        with contextlib.redirect_stdout(writer):
            try:
                code, out = host.run(script, sudo_user=None)
            finally:
                writer.finish()
        if code not in (0, SSH_FAILED) and not ci.marker_lines(out):
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
        # Les configurations lues (@@FILE) peuvent porter des secrets : en
        # base64, elles restent lisibles à qui voit l'écran.
        result = self._call_infra_run(
            host, ci.probe_script(), hide=PROBE_HIDDEN
        )
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
        # Sur cette machine, un ntfy d'une autre main (configuration sans la
        # marque de l'outil) est annoncé avant les questions : il sera
        # ADOPTÉ, sa configuration montrée en diff et sauvée, ses comptes
        # et jetons gardés. Celui que l'outil a écrit n'est que mis à jour.
        if (
            isinstance(host, nm.LocalHost)
            and facts.ntfy
            and ci.is_foreign(facts.ntfy["config_text"])
        ):
            print(f"⚠ {t('call_infra_local_ntfy_adopted')}")
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
            # Les services sont à jour, pas forcément le pare-feu : une règle
            # refusée, ou posée sans que l'état ait pu s'écrire, se propose
            # encore.
            if ci.firewall_missing(facts, answers):
                record = self._call_infra_firewall(
                    host, facts, answers, facts.state.get("firewall")
                )
                self._call_infra_save_state(
                    host, ci.with_firewall(facts.state, record)
                )
            return
        self._call_infra_show_plan(plan, facts)
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
        # L'état que le passage root vient d'écrire, que le pare-feu complète.
        state = ci.installed_state(plan, stamp, result[1])
        record = self._call_infra_firewall(
            host, facts, answers, state.get("firewall")
        )
        self._call_infra_save_state(host, ci.with_firewall(state, record))
        self._call_infra_report(host)

    def _call_infra_ask_answers(self, host, facts):
        """`Answers` des questions, préremplies par l'état d'un passage
        précédent ; None si une réponse ne se lit pas (raison affichée).
        Après les services vient le mode : le développement demande le
        certificat (aucun ou fourni), le nom public et les ports ; la
        production pose les questions de `_call_infra_ask_production`."""
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

        print(f"\n{t('Mode:')}")
        print(f"[1] {t('call_infra_mode_development')}")
        print(f"[2] {t('call_infra_mode_production')}")
        choice = self._call_infra_ask(
            t("Your choice (1/2)"),
            "2" if ci.is_production(prior) else "1",
        )
        mode = MODE_CHOICES.get(choice)
        if mode is None:
            print(t("Invalid selection!"))
            return None
        if mode == "production":
            return self._call_infra_ask_production(
                facts, prior, services, default_name
            )
        # Un état de production ne prête au développement que ce qui y a
        # le même sens : la plage des relais et le port de ntfy y changent
        # de valeur par défaut.
        same_mode = not ci.is_production(prior)

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
            cert_pem, key_pem = self._call_infra_read_pair()
            if cert_pem is None:
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
            low, high = (
                (prior.min_port, prior.max_port)
                if same_mode
                else (ci.DEV_MIN_PORT, ci.DEV_MAX_PORT)
            )
            relays = self._call_infra_ask_range(
                t("Media relay port range (udp)"), low, high
            )
            if relays is None:
                return None
            ports["min_port"], ports["max_port"] = relays
        if "ntfy" in services:
            # Le port de ntfy suit le mode : celui de l'état ne vaut que si
            # le mode est le même (8080 en http, 8443 avec un certificat).
            same_mode = same_mode and prior.tls == tls
            default_port = ci.ntfy_port(
                dataclasses.replace(
                    prior,
                    mode="development",
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

    def _call_infra_read_pair(self):
        """(certificat, clé) PEM lus sur cette machine, ou (None, None), la
        raison affichée."""
        cert_pem = self._call_infra_read_file(t("Certificate file (PEM)"))
        if cert_pem is None:
            return None, None
        key_pem = self._call_infra_read_file(t("Private key file (PEM)"))
        if key_pem is None:
            return None, None
        return cert_pem, key_pem

    @staticmethod
    def _call_infra_ask_yes(label, default):
        """Oui ou non ; une réponse vide rend `default`, montré en
        majuscule dans l'indice."""
        hint = t("call_infra_hint_yes") if default else t("call_infra_hint_no")
        raw = input(f"{label} {hint}: ").strip().lower()
        if not raw:
            return default
        return raw in YES_WORDS

    @staticmethod
    def _call_infra_ask_email(default):
        """Courriel pour Let's Encrypt : vide garde `default`, « - »
        n'en donne aucun."""
        shown = f" [{default}]" if default else ""
        raw = input(f"{t('call_infra_ask_email')}{shown}: ").strip()
        if raw == "-":
            return ""
        return raw or default

    @staticmethod
    def _call_infra_nginx_facts(facts):
        """(nginx installé, nginx écoute 80) d'après la sonde."""
        found = facts.nginx or {}
        present = bool(found) and found.get("state") != "absent"
        on_80 = ("tcp", ci.HTTP_PORT, ci.PROCESSES["nginx"]) in (
            facts.busy_ports
        )
        return present, on_80

    @staticmethod
    def _call_infra_443_free(facts):
        """Vrai quand aucun processus autre que coturn ne tient 443/tcp."""
        return not any(
            (proto, port) == ("tcp", ci.TURNS_ALT_PORT)
            and process != ci.PROCESSES["coturn"]
            for proto, port, process in facts.busy_ports
        )

    @staticmethod
    def _call_infra_dns_offered(facts):
        """Greffons DNS proposés, dans l'ordre de `DNS_PLUGINS` : ceux que
        la distribution de l'hôte empaquette, plus ceux déjà installés."""
        if facts.family == "arch":
            packaged = DNS_PLUGINS_PACKAGED["arch"]
        else:
            packaged = DNS_PLUGINS_PACKAGED.get(
                facts.os_id, DNS_PLUGINS_PACKAGED["debian"]
            )
        installed = set((facts.certbot or {}).get("plugins") or ())
        return [p for p in ci.DNS_PLUGINS if p in packaged or p in installed]

    def _call_infra_ask_plugin(self, facts, prior):
        """Greffon DNS choisi dans la liste de `_call_infra_dns_offered`,
        ou None, la raison affichée."""
        offered = self._call_infra_dns_offered(facts)
        print(f"\n{t('call_infra_ask_dns_plugin')}")
        for number, plugin in enumerate(offered, 1):
            print(f"[{number}] {plugin}")
        if len(offered) < len(ci.DNS_PLUGINS):
            print(
                self._call_infra_text(
                    "call_infra_dns_plugins_packaged", {"os": facts.os_id}
                )
            )
        default = (
            offered.index(prior.dns_plugin) + 1
            if prior.dns_plugin in offered
            else 1
        )
        choice = self._call_infra_ask(
            self._call_infra_text(
                "call_infra_choice_range", {"count": len(offered)}
            ),
            default,
        )
        if not choice.isdigit() or not 1 <= int(choice) <= len(offered):
            print(t("Invalid selection!"))
            return None
        return offered[int(choice) - 1]

    def _call_infra_ask_external_ip(self, facts, turn_name):
        """(ok, adresse) pour `external-ip` de coturn, d'après
        `external_ip_for` : rien à demander quand le nom de TURN résout
        vers une adresse de l'hôte (adresse None) ; derrière un NAT,
        l'adresse résolue est proposée, confirmée par Entrée ou remplacée ;
        un nom qui ne résout pas exige une adresse tapée (ok False, raison
        affichée, quand elle manque)."""
        address, reason = ci.external_ip_for(
            turn_name, facts.addresses, resolve=_resolve
        )
        if reason == "local":
            return True, None
        if reason == "nat":
            print(
                "⚠ "
                + self._call_infra_text(
                    "call_infra_turn_name_nat",
                    {"name": turn_name, "address": address},
                )
            )
            label = self._call_infra_text(
                "call_infra_ask_public_ip", {"address": address}
            )
            return True, input(f"{label} ").strip() or address
        print(
            "⚠ "
            + self._call_infra_text(
                "call_infra_turn_name_unresolved", {"name": turn_name}
            )
        )
        typed = input(f"{t('call_infra_ask_typed_ip')}: ").strip()
        if not typed:
            print(f"✗ {t('call_infra_public_ip_required')}")
            return False, None
        return True, typed

    @staticmethod
    def _call_infra_is_domain(name):
        """Vrai pour un nom à points qui n'est pas une adresse IP : la
        forme d'où `default_names` tire `ntfy.<d>` et `turn.<d>`."""
        name = (name or "").strip().rstrip(".")
        if "." not in name:
            return False
        try:
            ipaddress.ip_address(name)
        except ValueError:
            return True
        return False

    def _call_infra_ask_production(self, facts, prior, services, default):
        """Questions de production, après les services : domaine et noms
        proposés (`ntfy.<d>`, `turn.<d>`), source du certificat, défi de
        Let's Encrypt, courriel, nginx détecté, interface web de ntfy,
        ports, 443 pour coturn sur un hôte sans nginx où 443 est libre,
        IP publique. `Answers` de production, ou None (raison affichée).
        `default` : le nom proposé pour le domaine sans état de
        production."""
        again = ci.is_production(prior)
        if again and prior.public_name:
            proposed = prior.public_name
        else:
            proposed = next(
                (
                    name
                    for name in (default, facts.hostname)
                    if self._call_infra_is_domain(name)
                ),
                "",
            )
        if proposed:
            domain = self._call_infra_ask(t("call_infra_ask_domain"), proposed)
        else:
            domain = input(f"{t('call_infra_ask_domain')}: ")
        domain = domain.strip().rstrip(".")
        if not self._call_infra_is_domain(domain):
            print(f"✗ {t('call_infra_domain_needed')}")
            return None
        # Les noms d'un état de production ne valent que pour son domaine.
        same_domain = again and prior.public_name == domain
        proposed_ntfy, proposed_turn = ci.default_names(domain)
        names = {}
        if "ntfy" in services:
            names["ntfy_name"] = self._call_infra_ask(
                t("call_infra_ask_ntfy_name"),
                (same_domain and prior.ntfy_name) or proposed_ntfy,
            )
        if "coturn" in services:
            names["turn_name"] = self._call_infra_ask(
                t("call_infra_ask_turn_name"),
                (same_domain and prior.turn_name) or proposed_turn,
            )

        print(f"\n{t('Certificate:')}")
        print(f"[1] {t('call_infra_tls_letsencrypt')}")
        print(
            f"[2] {t('Supplied: certificate and key files of this machine')}"
        )
        choice = self._call_infra_ask(
            t("Your choice (1/2)"), "2" if prior.tls == "supplied" else "1"
        )
        if choice not in ("1", "2"):
            print(t("Invalid selection!"))
            return None
        tls = "supplied" if choice == "2" else "letsencrypt"
        cert_pem = key_pem = None
        if tls == "supplied":
            cert_pem, key_pem = self._call_infra_read_pair()
            if cert_pem is None:
                return None

        nginx_present, nginx_on_80 = self._call_infra_nginx_facts(facts)
        # ntfy passe toujours par nginx ; coturn seul ne s'en sert que pour
        # le défi HTTP.
        use_nginx = "ntfy" in services
        acme = dns_plugin = dns_credentials = None
        email = ""
        if tls == "letsencrypt":
            print(f"\n{t('call_infra_ask_challenge')}")
            print(f"[1] {t('call_infra_challenge_http')}")
            print(f"[2] {t('call_infra_challenge_dns')}")
            choice = self._call_infra_ask(
                t("Your choice (1/2)"), "2" if prior.acme == "dns" else "1"
            )
            if choice not in ("1", "2"):
                print(t("Invalid selection!"))
                return None
            if choice == "2":
                acme = "dns"
                dns_plugin = self._call_infra_ask_plugin(facts, prior)
                if dns_plugin is None:
                    return None
                # Lu ici, envoyé dans le corps du script : jamais affiché.
                dns_credentials = self._call_infra_read_file(
                    t("call_infra_ask_dns_credentials")
                )
                if dns_credentials is None:
                    return None
            elif use_nginx:
                acme = "http-nginx"
            elif nginx_present or nginx_on_80:
                # certbot seul ne peut pas prendre 80 à un nginx.
                print(f"  {t('call_infra_nginx_serves_challenge')}")
                acme, use_nginx = "http-nginx", True
            else:
                print(f"\n{t('call_infra_ask_http_way')}")
                print(f"[1] {t('call_infra_http_standalone')}")
                print(f"[2] {t('call_infra_http_nginx')}")
                choice = self._call_infra_ask(
                    t("Your choice (1/2)"),
                    "2" if prior.acme == "http-nginx" else "1",
                )
                if choice not in ("1", "2"):
                    print(t("Invalid selection!"))
                    return None
                acme = "http-nginx" if choice == "2" else "http-standalone"
                use_nginx = acme == "http-nginx"
            email = self._call_infra_ask_email(prior.email if again else "")
            if not email:
                print(f"⚠ {t('call_infra_email_none')}")

        nginx = None
        if use_nginx:
            if nginx_present:
                nginx = "existing"
                layout = (facts.nginx or {}).get("layout") or "?"
                print(
                    "  "
                    + self._call_infra_text(
                        "call_infra_nginx_existing", {"layout": layout}
                    )
                )
            else:
                nginx = "install"
                print(f"  {t('call_infra_nginx_install')}")
        ntfy_web = False
        if "ntfy" in services:
            ntfy_web = self._call_infra_ask_yes(
                t("call_infra_ask_ntfy_web"), again and prior.ntfy_web
            )

        ports, turns_443 = {}, False
        if "coturn" in services:
            ports["turn_port"] = self._call_infra_ask_int(
                t("TURN port (udp and tcp)"), prior.turn_port
            )
            if ports["turn_port"] is None:
                return None
            if (
                nginx is None
                and not nginx_present
                and self._call_infra_443_free(facts)
            ):
                turns_443 = self._call_infra_ask_yes(
                    self._call_infra_text(
                        "call_infra_ask_turns_443", {"port": prior.turns_port}
                    ),
                    again and prior.turns_443,
                )
            if turns_443:
                ports["turns_port"] = prior.turns_port
            else:
                ports["turns_port"] = self._call_infra_ask_int(
                    t("TURNS port (tcp, TLS)"), prior.turns_port
                )
                if ports["turns_port"] is None:
                    return None
            low, high = (
                (prior.min_port, prior.max_port)
                if again
                else (ci.PROD_MIN_PORT, ci.PROD_MAX_PORT)
            )
            relays = self._call_infra_ask_range(
                t("Media relay port range (udp)"), low, high
            )
            if relays is None:
                return None
            ports["min_port"], ports["max_port"] = relays
        if "ntfy" in services:
            ports["ntfy_port"] = self._call_infra_ask_int(
                t("call_infra_ask_ntfy_local_port"),
                (again and prior.ntfy_port) or ci.NTFY_HTTP_PORT,
            )
            if ports["ntfy_port"] is None:
                return None

        external_ip = None
        if "coturn" in services:
            ok, external_ip = self._call_infra_ask_external_ip(
                facts, names["turn_name"]
            )
            if not ok:
                return None
        return ci.Answers(
            services=services,
            tls=tls,
            cert_pem=cert_pem,
            key_pem=key_pem,
            public_name=domain,
            external_ip=external_ip,
            mode="production",
            acme=acme,
            dns_plugin=dns_plugin,
            dns_credentials=dns_credentials,
            email=email,
            ntfy_web=ntfy_web,
            turns_443=turns_443,
            nginx=nginx,
            **names,
            **ports,
        )

    def _call_infra_show_plan(self, plan, facts):
        answers = plan.answers
        production = ci.is_production(answers)
        chosen = [s for s in ci.SERVICES if s in answers.services]
        print(f"\n{t('Summary')}")
        print(f"  {t('Services:')} {', '.join(chosen)}")
        if production:
            print(f"  {t('Mode:')} {t('production')}")
            self._call_infra_show_production(answers)
        else:
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
            if production:
                print(f"  ✓ {t('call_infra_private_ranges_denied')}")
            else:
                print(f"  ⚠ {t('call_infra_private_ranges_allowed')}")
        if production:
            self._call_infra_dns_warnings(answers, facts)
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

    def _call_infra_show_production(self, answers):
        """Lignes du résumé propres à la production : noms, source du
        certificat, défi, courriel, nginx, interface web, IP publique."""
        names = []
        if "ntfy" in answers.services:
            names.append(f"ntfy {ci.ntfy_host(answers)}")
        if "coturn" in answers.services:
            names.append(f"TURN {ci.turn_host(answers)}")
        print(f"  {t('Names:')} {', '.join(names)}")
        if answers.tls == "letsencrypt":
            print(f"  {t('Certificate:')} {t('call_infra_cert_letsencrypt')}")
            if answers.acme == "dns":
                challenge = self._call_infra_text(
                    "call_infra_challenge_dns_plugin",
                    {"plugin": answers.dns_plugin},
                )
            elif answers.acme == "http-standalone":
                challenge = t("call_infra_challenge_http_standalone")
            else:
                challenge = t("call_infra_challenge_http_nginx")
            print(f"  {t('Challenge:')} {challenge}")
            print(
                f"  {t('Email:')} "
                f"{answers.email or t('call_infra_email_absent')}"
            )
        else:
            print(f"  {t('Certificate:')} {t('supplied certificate')}")
        if answers.nginx == "install":
            print(f"  nginx : {t('call_infra_nginx_to_install')}")
        elif answers.nginx == "existing":
            print(f"  nginx : {t('call_infra_nginx_kept')}")
        if "ntfy" in answers.services:
            web = (
                "call_infra_web_on"
                if answers.ntfy_web
                else "call_infra_web_off"
            )
            print(f"  {t('ntfy web interface:')} {t(web)}")
        if answers.external_ip:
            print(f"  {t('External IP:')} {answers.external_ip}")

    def _call_infra_dns_warnings(self, answers, facts):
        """Un avertissement par nom du certificat qui ne résout vers aucune
        adresse de l'hôte ni vers l'IP publique confirmée, ou ne résout
        pas : les clients n'y joindraient pas l'hôte, et le défi HTTP de
        Let's Encrypt échouerait (le défi DNS, lui, ne lit pas l'adresse)."""
        known = list(facts.addresses)
        if answers.external_ip:
            known.append(answers.external_ip.split("/", 1)[0])
        http_challenge = answers.tls == "letsencrypt" and answers.acme != "dns"
        for name in ci.certificate_names(answers):
            found, reason = ci.external_ip_for(name, known, resolve=_resolve)
            if reason == "local":
                continue
            if reason == "nat":
                text = self._call_infra_text(
                    "call_infra_dns_elsewhere", {"name": name, "found": found}
                )
            else:
                text = self._call_infra_text(
                    "call_infra_dns_unresolved", {"name": name}
                )
            if http_challenge:
                text += " " + t("call_infra_dns_le_fails")
            print(f"  ⚠ {text}")

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
        leur ajout. Sans oui, les règles déjà consignées restent, avec
        celles qu'un passage a posées sans pouvoir les consigner
        (`facts.firewall_pending`) : elles sont encore sur l'hôte et la
        désinstallation doit les retirer."""
        kind = facts.firewall
        rules = ci.firewall_rules(answers)
        chain = facts.nft_chains[0] if len(facts.nft_chains) == 1 else None
        preview = ci.firewall_preview(kind, rules, chain)
        pending = facts.firewall_pending
        record = ci.firewall_record(kind, "", previous, pending)
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
                    record = ci.firewall_record(kind, out, previous, pending)
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
            print(f"✗ {t('call_infra_state_not_saved')}")
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
            # En production, le nom public est le domaine, qui peut ne pas
            # joindre l'hôte : le nom de TURN, puis celui de ntfy, passent
            # avant lui.
            keys = ("public_name",)
            if state.get("mode") == "production":
                keys = ("turn_name", "ntfy_name", "public_name")
            names = [
                s[key]
                for key in keys
                for s in settings
                if isinstance(s.get(key), str) and s.get(key)
            ]
            address = self._call_infra_ask(
                t("Address that reaches the host from this machine"),
                names[0] if names else "",
            )
            if any(s.get("tls") == "supplied" for s in settings):
                raw = input(f"{t('call_infra_ask_cafile')}: ").strip()
                cafile = os.path.expanduser(raw) if raw else None
                # Une autorité qui ne se charge pas (chemin mal tapé, fichier
                # qui n'est pas un PEM) ferait dire « injoignable » au relais.
                if cafile is not None:
                    try:
                        ssl.create_default_context(cafile=cafile)
                    except (OSError, ValueError) as error:
                        print(
                            f"✗ {t('The file could not be read:')} {cafile}"
                            f" ({error})"
                        )
                        return
        print(f"\n{t('Call infra - Check')}")
        for line in ci.check_local(remote, address, cafile):
            print(self._call_infra_line(line))

    def _call_infra_line(self, line):
        labels = {
            "turn-udp": t("TURN over UDP"),
            "turn-tcp": t("TURN over TCP"),
            "turn-tls": t("TURN over TLS"),
            "private-denied": t("Private ranges denied"),
            "ntfy-health": t("ntfy health"),
            "cert-expiry": t("Certificate expiry"),
            "cert-issuer": t("Certificate issuer"),
            "renewal": t("Certificate renewal"),
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
        # Les règles qu'un passage a posées sans pouvoir les consigner
        # partent avec les autres.
        state = ci.merge_pending_firewall(facts.state, facts.firewall_pending)
        if not isinstance(state, dict):
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
            ci.uninstall_script(state, False, stamp)
        except ci.Refusal as refusal:
            self._call_infra_refuse(refusal)
            return
        self._call_infra_show_uninstall(state)
        remove_data = _yes(t("call_infra_ask_remove_data"))
        if not _yes(t("Uninstall now? (y/N): ")):
            print(t("Nothing uninstalled."))
            return
        result = self._call_infra_run(
            host, ci.uninstall_script(state, remove_data, stamp)
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
        nginx = state.get("nginx")
        if isinstance(nginx, dict):
            what = (
                "call_infra_uninstall_nginx_purges"
                if nginx.get("installed_by_tool")
                else "call_infra_uninstall_nginx_keeps"
            )
            print(f"  nginx : {t(what)}")
        if isinstance(state.get("certbot"), dict):
            print(f"  {t('call_infra_uninstall_certificate')}")
        if isinstance(state.get("certbot"), dict) or isinstance(
            state.get("hook"), dict
        ):
            print(f"  {t('call_infra_uninstall_hook')}")
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
