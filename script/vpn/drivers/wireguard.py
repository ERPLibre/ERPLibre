#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""WireGuard : une configuration, une commande, et c'est monté.

Le plus simple des pilotes — et c'est justement là qu'il faut se méfier.
WireGuard n'a pas de session : `wg-quick up` réussit et l'interface apparaît
même si la clé du pair est fausse, même si l'endpoint est injoignable. Rien
ne dit non, parce qu'il n'y a personne à qui dire non.

Ce pilote attend donc une POIGNÉE DE MAIN avant de déclarer le tunnel monté.
Sans cette attente, « ✓ Tunnel monté » voudrait dire « l'interface existe »,
ce qui n'est pas la même chose et ne se découvre qu'au premier paquet perdu.

Les routes viennent d'`AllowedIPs` et c'est `wg-quick` qui les pose — y
compris, en « tout le trafic », l'astuce de marquage (fwmark) qui garde
l'endpoint joignable. On ne double donc PAS son travail : un `ip route` de
plus ici entrerait en conflit avec le sien.
"""
from __future__ import annotations

import shlex

from script.vpn import valid
from script.vpn.drivers.base import VpnDriver, interface_addresses


class WireguardDriver(VpnDriver):
    name = "wireguard"
    label = "WireGuard"
    binaries = ("wg", "wg-quick", "ip")
    secret_fields = (
        ("wg_private_key", "WireGuard private key of this machine", True),
        ("wg_preshared_key", "WireGuard pre-shared key (optional)", False),
    )
    iface_kind = "wireguard"
    hint = "When you control both ends: the fastest and the simplest"
    defaults = {
        "port": 51820,
        "wg_address": "",
        "wg_peer_key": "",
        "wg_dns": "",
        "wg_keepalive": 25,
    }
    form_fields = (
        (
            "wg_address",
            "Address of this machine inside the tunnel (10.7.0.2/32)",
            "text",
            False,
        ),
        ("wg_peer_key", "Public key of the peer", "text", False),
        ("port", "WireGuard endpoint port", "int", True),
        ("wg_dns", "DNS server inside the tunnel (optional)", "text", True),
        ("wg_keepalive", "PersistentKeepalive, in seconds", "int", True),
    )

    # ------------------------------------------------------------------
    @property
    def iface(self):
        """Nom de l'interface, et donc du fichier de configuration.

        `wg-quick` DÉDUIT le nom de l'interface du nom du fichier : le
        fichier doit s'appeler `<interface>.conf`. Tronqué à 15 caractères,
        limite du noyau pour un nom d'interface.
        """
        return f"wg-{self.name_tag}"[:15]

    @property
    def config_file(self):
        return f"{self.secret_dir}/{self.iface}.conf"

    @property
    def allowed_ips(self):
        """`AllowedIPs` : ce qui entre dans le tunnel.

        C'est le champ le plus mal compris de WireGuard — il sert à LA FOIS
        de filtre de trafic et de table de routage. `0.0.0.0/0` veut donc
        dire « tout le trafic », et rien d'autre n'est nécessaire pour cela.
        """
        if self.profile.get("default_route"):
            return "0.0.0.0/0"
        return ", ".join(self.profile.get("routes", []))

    # ------------------------------------------------------------------
    @classmethod
    def validate_profile(cls, profile):
        valid.ip_interface(
            profile, "wg_address", "Adresse de cette machine dans le tunnel"
        )
        valid.wg_key(profile, "wg_peer_key", "Clé publique du pair")
        valid.port(profile, "port", "Port de l'endpoint WireGuard")
        valid.ip_address(
            profile, "wg_dns", "Serveur DNS dans le tunnel", required=False
        )
        valid.integer(profile, "wg_keepalive", "PersistentKeepalive", 0, 65535)

    def config_body(self):
        p = self.profile
        lines = [
            "# Généré par ERPLibre (script/vpn). tmpfs, 0600, effacé au down.",
            "[Interface]",
            f"PrivateKey = {self.secrets.get('wg_private_key', '')}",
            f"Address = {p['wg_address']}",
            f"MTU = {p['mtu']}",
            "",
            "[Peer]",
            f"PublicKey = {p['wg_peer_key']}",
        ]
        preshared = self.secrets.get("wg_preshared_key")
        if preshared:
            lines.append(f"PresharedKey = {preshared}")
        lines += [
            f"Endpoint = {p['server']}:{p['port']}",
            f"AllowedIPs = {self.allowed_ips}",
        ]
        if p.get("wg_keepalive"):
            # Indispensable derrière du NAT : sans trafic, la traduction
            # expire et le pair ne sait plus où nous joindre.
            lines.append(f"PersistentKeepalive = {p['wg_keepalive']}")
        # Pas de « DNS = » : wg-quick le confie à `resolvconf`, absent de
        # beaucoup d'installations systemd-resolved, et la configuration
        # ENTIÈRE échoue alors. On appelle resolvectl nous-mêmes.
        return "\n".join(lines)

    # ------------------------------------------------------------------
    def up(self, runner):
        p = self.profile
        if not self.ensure_ready(runner):
            return False
        if not self.allowed_ips:
            runner.fail(
                "Aucun réseau à router : AllowedIPs serait vide et le"
                " tunnel ne porterait rien."
            )
            return False

        self.prepare_dirs(runner)
        runner.write(
            self.config_file,
            self.config_body() + "\n",
            mode="0600",
            secret=True,
        )
        code, _ = runner.cmd(
            f"monter {self.iface}",
            f"wg-quick up {shlex.quote(self.config_file)}",
            timeout=60,
        )
        if code != 0 and not runner.dry_run:
            runner.fail(
                "wg-quick a refusé. Causes usuelles : clé mal formée,"
                " adresse déjà prise, module wireguard absent du noyau."
            )
            return False
        self.write_state(runner, "iface", self.iface)

        if not self._wait_for_handshake(runner):
            return False
        if runner.dry_run:
            return True

        addresses = (
            ", ".join(interface_addresses(self.iface)) or "sans adresse"
        )
        runner.ok(f"interface {self.iface} : {addresses}")
        # Les routes appartiennent à wg-quick, via AllowedIPs. Rien à
        # ajouter ici — voir l'en-tête du fichier.
        if p.get("wg_dns"):
            self.set_resolved_dns(runner, self.iface, [p["wg_dns"]])
        return True

    def _wait_for_handshake(self, runner):
        """Attend une poignée de main avec le pair.

        `wg show … latest-handshakes` rend un horodatage par pair, à zéro
        tant que rien n'a abouti. C'est le SEUL signe que la clé et
        l'endpoint sont bons : l'interface, elle, monte de toute façon.
        """
        script = (
            "for i in $(seq 1 20); do"
            f" wg show {shlex.quote(self.iface)} latest-handshakes"
            " | awk '$2 > 0 { found = 1 } END { exit !found }'"
            " && exit 0; sleep 0.5; done; exit 1"
        )
        code, _ = runner.cmd(
            "attendre la poignée de main du pair",
            f"sh -c {shlex.quote(script)}",
            check=False,
            timeout=30,
        )
        if code == 0 or runner.dry_run:
            return True
        runner.fail(
            "Aucune poignée de main en 10 s. L'interface est montée — c'est"
            " toujours le cas avec WireGuard — mais le pair n'a pas"
            " répondu : clé publique du pair, PSK, endpoint ou UDP"
            f" {self.profile['port']} filtré."
        )
        return False

    # ------------------------------------------------------------------
    def down(self, runner):
        runner.cmd(
            f"démonter {self.iface}",
            f"wg-quick down {shlex.quote(self.config_file)}",
            check=False,
            timeout=60,
        )
        # Filet : après un redémarrage du CLI, le fichier de configuration
        # peut avoir disparu du tmpfs alors que l'interface tient toujours.
        # `wg-quick down` échoue alors, et l'interface resterait là.
        runner.cmd(
            f"filet : retirer {self.iface} si elle est restée",
            "sh -c {}".format(
                shlex.quote(
                    f"ip link show {shlex.quote(self.iface)} >/dev/null 2>&1"
                    f" && ip link del {shlex.quote(self.iface)} || true"
                )
            ),
            check=False,
        )
        runner.remove(self.secret_dir)
        self.clear_state(runner, "iface")
        runner.ok("Tunnel démonté, secrets effacés.")
        return True

    # ------------------------------------------------------------------
    def status(self, runner):
        iface = self.recorded_iface() or self.iface
        code, out = runner.cmd(
            "poignée de main WireGuard",
            f"wg show {shlex.quote(iface)} latest-handshakes",
            check=False,
            capture=True,
        )
        stamps = [
            int(part)
            for line in out.splitlines()
            for part in line.split()[1:2]
            if part.isdigit()
        ]
        latest = max(stamps) if stamps else 0
        extra = [
            (
                "poignée de main",
                bool(latest) if code == 0 else None,
                (
                    f"horodatage {latest}"
                    if latest
                    else (out.strip().splitlines() or ["wg muet (sudo ?)"])[
                        -1
                    ][:120]
                ),
            )
        ]
        return self.standard_status(runner, extra=extra)

    def log_commands(self):
        return [
            (
                f"état complet de {self.iface}",
                f"wg show {shlex.quote(self.iface)}",
            ),
            (
                "journal du noyau (module wireguard)",
                "journalctl -n 30 --no-pager -k -g wireguard",
            ),
        ]
