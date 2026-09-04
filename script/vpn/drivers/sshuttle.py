#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""sshuttle : un VPN sur une simple session SSH, sans rien à installer en face.

Le pilote le plus utile quand il n'y a PAS de concentrateur : si on a un accès
SSH sur une machine du réseau visé, on a déjà tout. Rien à installer côté
serveur, aucune clé à échanger, aucun secret à ranger — l'authentification est
celle de SSH, donc `secret_fields` est vide et le coffre n'est même pas
ouvert. C'est le seul pilote qui n'en a pas besoin.

Deux différences qui changent le code, et pas seulement les commandes :

· **Pas d'interface.** sshuttle détourne le trafic par le pare-feu
  (iptables/nftables), il ne crée pas de `tun`. Toutes les vérifications
  d'interface et de table de routage sont donc muettes ici : c'est l'adresse
  TÉMOIN qui dit si ça marche, et rien d'autre. Ce pilote est la raison d'être
  du champ `probe`.
· **Il s'élève tout seul.** sshuttle veut être lancé par l'UTILISATEUR : il
  n'appelle sudo que pour la partie pare-feu. Le lancer sous sudo ferait
  ouvrir la session SSH par root, avec les clés de root — c'est-à-dire aucune.
  D'où `sudo=False`, et un fichier de pid dans le home plutôt que dans /run.
"""
from __future__ import annotations

import os
import shlex

from script.vpn import valid
from script.vpn.drivers.base import VpnDriver


class SshuttleDriver(VpnDriver):
    name = "sshuttle"
    label = "sshuttle"
    binaries = ("sshuttle", "ssh")
    # Aucun. L'authentification est celle de SSH.
    secret_fields = ()
    iface_kind = ""
    hint = (
        "When all you have is SSH access: nothing to install on the far side"
    )
    server_label = "SSH target (user@host, or a ~/.ssh/config alias)"
    uses_mtu = False
    defaults = {"port": 22, "ssh_dns": True}
    form_fields = (
        ("port", "SSH port", "int", True),
        ("ssh_dns", "Also send DNS queries through the tunnel?", "flag", True),
    )

    # ------------------------------------------------------------------
    @property
    def pid_file(self):
        """Dans le home, pas dans /run.

        sshuttle tourne sous l'utilisateur et écrit ce fichier lui-même :
        /run/erplibre-vpn appartient à root, il ne pourrait pas."""
        return os.path.expanduser(f"~/.erplibre/vpn-{self.name_tag}.pid")

    @property
    def subnets(self):
        """Ce qui entre dans le tunnel. `0.0.0.0/0` pour « tout »."""
        if self.profile.get("default_route"):
            return ["0.0.0.0/0"]
        return list(self.profile.get("routes", []))

    @classmethod
    def validate_profile(cls, profile):
        valid.port(profile, "port", "Port SSH")
        valid.flag(profile, "ssh_dns")

    def command(self):
        p = self.profile
        remote = p["server"]
        if int(p.get("port", 22)) != 22:
            remote = f"{remote}:{p['port']}"
        parts = [
            "sshuttle",
            f"--remote {shlex.quote(remote)}",
            "--daemon",
            f"--pidfile {shlex.quote(self.pid_file)}",
        ]
        if p.get("ssh_dns"):
            parts.append("--dns")
        parts.extend(shlex.quote(subnet) for subnet in self.subnets)
        return " ".join(parts)

    # ------------------------------------------------------------------
    def up(self, runner):
        if not self.ensure_ready(runner):
            return False
        if not self.subnets:
            runner.fail("Aucun réseau à détourner : rien à faire.")
            return False

        runner.call(
            f"préparer {os.path.dirname(self.pid_file)}",
            lambda: os.makedirs(os.path.dirname(self.pid_file), exist_ok=True),
        )
        # SANS sudo : sudo est demandé par sshuttle lui-même, et seulement
        # pour le pare-feu. Voir l'en-tête du fichier.
        code, _ = runner.cmd(
            f"détourner {', '.join(self.subnets)} par {self.profile['server']}",
            self.command(),
            sudo=False,
            check=False,
            timeout=90,
        )
        if code != 0 and not runner.dry_run:
            runner.fail(
                "sshuttle n'a pas démarré. Les causes usuelles : SSH qui ne"
                f" passe pas vers {self.profile['server']} (l'essayer à la"
                " main), python absent sur la machine distante, ou sudo"
                " local refusé."
            )
            return False
        if runner.dry_run:
            return True
        if self.pid_alive() is not True:
            runner.fail(
                "sshuttle s'est lancé puis a rendu la main sans laisser de"
                " processus vivant. Le relancer sans --daemon montre ce"
                " qu'il refuse."
            )
            return False
        runner.ok(
            "Détournement actif. Pas d'interface à montrer : sshuttle passe"
            " par le pare-feu."
        )
        return True

    def down(self, runner):
        # Sans sudo, comme au montage : c'est notre processus.
        self.kill_pidfile(runner, "arrêter sshuttle", sudo=False)
        runner.ok("Détournement arrêté.")
        return True

    def status(self, runner):
        """Ni interface, ni route à vérifier : le témoin est le seul juge.

        On ne réutilise donc PAS `standard_status` — ses vérifications
        d'interface et de routes rendraient des « ✗ » qui n'ont aucun sens
        pour un détournement par le pare-feu."""
        checks = self.check_kernel()
        checks += [
            self.check_binaries(),
            self.check_daemon("processus sshuttle"),
            (
                "réseaux détournés",
                bool(self.subnets),
                ", ".join(self.subnets) or "aucun",
            ),
        ]
        probe = self.check_probe(runner)
        if not probe:
            checks.append(
                (
                    "témoin",
                    None,
                    "aucune adresse témoin : renseigner « probe » dans le"
                    " profil, c'est la seule preuve possible ici",
                )
            )
        checks.extend(probe)
        return checks

    def log_commands(self):
        return [
            (
                "règles de détournement",
                # Le nom de la chaîne porte le port choisi par sshuttle
                # (12300 par défaut, mais pas toujours) : on cherche le
                # motif plutôt que de parier sur le nom.
                'sh -c "iptables -t nat -S 2>/dev/null | grep -i sshuttle'
                " || nft list ruleset 2>/dev/null | grep -i sshuttle"
                " || echo 'aucune règle sshuttle visible'\"",
            )
        ]
