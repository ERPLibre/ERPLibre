#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""OpenVPN : on part du fichier `.ovpn` que le client a fourni.

Ce pilote ne fabrique PAS de configuration OpenVPN. Un `.ovpn` porte une
autorité de certification, un certificat, une clé privée, des directives de
compression et de chiffrement : le modéliser dans un profil JSON serait
recopier un format qui existe déjà, et le recopier moins bien. Le profil
pointe donc vers le fichier, et ce pilote y ajoute ce que le fichier ne peut
pas contenir sans devenir un secret de plus : les identifiants, lus dans le
coffre et posés dans un tmpfs.

Deux choses qu'on aurait tort de croire évidentes :

· **`--cd`.** Un `.ovpn` référence ses fichiers voisins en relatif (`ca.crt`,
  `client.key`). Lancé depuis la racine du dépôt, openvpn ne les trouve pas
  et se plaint d'un certificat manquant, pas d'un répertoire. On se place
  donc dans le répertoire du fichier.
· **L'ordre des options.** Ce qui suit `--config` sur la ligne de commande
  l'emporte sur le contenu du fichier. Notre `--auth-user-pass <fichier>`
  doit donc venir APRÈS, sinon un `auth-user-pass` nu dans le `.ovpn` fait
  attendre une saisie qui ne viendra jamais — le démon est détaché.

Le tunnel scindé se demande à OpenVPN par `--route-nopull` : ignorer les
routes poussées, puis poser les nôtres. C'est un gros marteau — il ignore
aussi le DNS poussé — et le pilote le dit quand il le prend.
"""
from __future__ import annotations

import os
import shlex

from script.vpn import valid
from script.vpn.drivers.base import (
    STATE_DIR,
    VpnDriver,
    interface_addresses,
    interfaces,
    wait_for_new_interface,
)


class OpenvpnDriver(VpnDriver):
    name = "openvpn"
    label = "OpenVPN"
    binaries = ("openvpn", "ip")
    # Pas obligatoire : beaucoup de `.ovpn` s'authentifient par certificat
    # seul. `up` exige le mot de passe seulement si un utilisateur est
    # déclaré.
    secret_fields = (("password", "OpenVPN password", False),)
    iface_kind = "tun"
    # Faux : un profil sans route reste utilisable — il joint l'hôte
    # distant, et l'adresse qu'on y obtient dit quel réseau ajouter. Le
    # site ne donne souvent qu'une passerelle et des identifiants.
    needs_routes = False
    hint = "When the site handed you a .ovpn file"
    user_field = "ovpn_user"
    # Le MTU vient du serveur (ou du .ovpn), pas du profil.
    uses_mtu = False
    defaults = {"ovpn_config": "", "ovpn_user": ""}
    form_fields = (
        (
            "ovpn_config",
            "Path to the .ovpn file provided by the site",
            "path",
            False,
        ),
        (
            "ovpn_user",
            "OpenVPN user (empty if the file authenticates by certificate)",
            "text",
            False,
        ),
    )

    # ------------------------------------------------------------------
    @property
    def auth_file(self):
        return f"{self.secret_dir}/auth.txt"

    @property
    def log_file(self):
        """Journal en tmpfs, lisible sans sudo : c'est lui qui dit pourquoi
        une connexion a échoué, et `diagnose` doit pouvoir le montrer."""
        return f"{STATE_DIR}/{self.name_tag}.log"

    @classmethod
    def validate_profile(cls, profile):
        valid.path(profile, "ovpn_config", "Fichier .ovpn")
        valid.text(profile, "ovpn_user", "Utilisateur OpenVPN", required=False)

    def auth_body(self):
        """Le format attendu par `--auth-user-pass` : deux lignes."""
        return "{}\n{}\n".format(
            self.profile.get("ovpn_user", ""),
            self.secrets.get("password", ""),
        )

    def command(self):
        """La ligne de commande, sans aucun secret : le mot de passe est
        dans le fichier d'authentification, pas ici."""
        p = self.profile
        config = p["ovpn_config"]
        parts = [
            "openvpn",
            f"--config {shlex.quote(config)}",
            f"--cd {shlex.quote(os.path.dirname(config) or '.')}",
            f"--daemon erplibre-{self.name_tag}",
            f"--writepid {shlex.quote(self.pid_file)}",
            f"--log {shlex.quote(self.log_file)}",
        ]
        if p.get("ovpn_user"):
            parts.append(f"--auth-user-pass {shlex.quote(self.auth_file)}")
            # Le fichier est relu à chaque renégociation : rien à garder en
            # mémoire, et un secret de moins qui traîne dans le processus.
            parts.append("--auth-nocache")
        if not p.get("default_route") and p.get("routes"):
            parts.append("--route-nopull")
        return " ".join(parts)

    # ------------------------------------------------------------------
    def up(self, runner):
        p = self.profile
        if not self.ensure_ready(runner):
            return False
        if p.get("ovpn_user") and not self.secrets.get("password"):
            report = runner.warn if runner.dry_run else runner.fail
            report(
                f"Le profil déclare l'utilisateur « {p['ovpn_user']} » mais"
                " aucun mot de passe n'est dans le coffre."
            )
            if not runner.dry_run:
                return False
        self._warn_about_config_file(runner)

        before = (
            runner.call(
                "relever les interfaces tun/tap existantes",
                lambda: interfaces("tun"),
                dry_safe=True,
            )
            or set()
        )

        self.prepare_dirs(runner)
        if p.get("ovpn_user"):
            runner.write(
                self.auth_file, self.auth_body(), mode="0600", secret=True
            )
        if not p.get("default_route") and p.get("routes"):
            runner.warn(
                "Tunnel scindé par --route-nopull : les routes ET le DNS"
                " poussés par le serveur sont ignorés. Seules les routes du"
                " profil sont posées."
            )

        code, _ = runner.cmd("lancer openvpn", self.command(), timeout=60)
        if code != 0 and not runner.dry_run:
            runner.fail(
                "openvpn n'a pas démarré. Le journal dit pourquoi :"
                f" {self.log_file}"
            )
            return False

        if not self._wait_for_init(runner):
            return False
        if runner.dry_run:
            runner.info("      (à blanc : l'interface serait nommée ici)")
            return True

        iface = wait_for_new_interface(before, "tun", timeout=10)
        if not iface:
            runner.fail(
                "OpenVPN dit s'être initialisé, mais aucune interface"
                " tun/tap n'est apparue. Cas rare : configuration en mode"
                " pont (tap) sans interface propre."
            )
            return False
        addresses = ", ".join(interface_addresses(iface)) or "sans adresse"
        runner.ok(f"interface {iface} : {addresses}")
        self.write_state(runner, "iface", iface)
        if not p.get("default_route"):
            self.add_routes(runner, iface)
        self.suggest_routes(runner, iface)
        return True

    def _wait_for_init(self, runner):
        """Attend « Initialization Sequence Completed » dans le journal.

        C'est LE signal de succès d'OpenVPN. Le processus détaché existe
        bien avant : se contenter de son pid ferait dire « monté » à un
        client encore en train de se faire refuser ses certificats.
        """
        log = shlex.quote(self.log_file)
        script = (
            "for i in $(seq 1 120); do"
            f" grep -q 'Initialization Sequence Completed' {log}"
            " 2>/dev/null && exit 0; sleep 0.5; done; exit 1"
        )
        code, _ = runner.cmd(
            "attendre l'initialisation d'OpenVPN",
            f"sh -c {shlex.quote(script)}",
            check=False,
            timeout=75,
        )
        if code == 0 or runner.dry_run:
            return True
        runner.fail(
            "OpenVPN ne s'est pas initialisé en 60 s. Les dernières lignes"
            f" de {self.log_file} disent laquelle des trois étapes a"
            " échoué : TLS, authentification, ou pose des routes."
        )
        return False

    def _warn_about_config_file(self, runner):
        """Un `.ovpn` embarque souvent la clé privée du client.

        Le fichier appartient à l'utilisateur, pas à nous : on ne le
        déplace pas, on ne le réécrit pas. Mais lisible par tout le monde,
        il vaut la peine d'être signalé — c'est une clé privée.
        """
        config = self.profile.get("ovpn_config", "")
        try:
            mode = os.stat(config).st_mode
        except OSError:
            runner.warn(
                f"Fichier de configuration introuvable : {config}."
                " Le montage échouera."
            )
            return
        if mode & 0o077:
            runner.warn(
                f"{config} est lisible au-delà de son propriétaire"
                f" (mode {oct(mode & 0o777)}). Un .ovpn embarque souvent la"
                " clé privée du client : chmod 600 est de rigueur."
            )

    # ------------------------------------------------------------------
    def down(self, runner):
        self.kill_pidfile(runner, "arrêter openvpn")
        runner.remove(self.secret_dir)
        # Le journal SURVIT au démontage, volontairement : c'est juste
        # après un « down » qu'on cherche pourquoi ça n'allait pas. Il est
        # en tmpfs, donc il part au redémarrage de la machine.
        self.clear_state(runner, "iface", "pid")
        runner.ok(
            f"Tunnel démonté, secrets effacés. Journal gardé : {self.log_file}"
        )
        return True

    # ------------------------------------------------------------------
    def status(self, runner):
        extra = [self.check_daemon("processus openvpn")]
        try:
            with open(self.log_file) as fh:
                lines = [line.strip() for line in fh if line.strip()]
        except OSError:
            lines = []
        initialised = any(
            "Initialization Sequence Completed" in line for line in lines
        )
        extra.append(
            (
                "initialisation OpenVPN",
                initialised if lines else None,
                lines[-1][:120] if lines else "aucun journal",
            )
        )
        return self.standard_status(runner, extra=extra)

    def log_commands(self):
        return [
            (
                f"journal OpenVPN ({self.log_file})",
                f"tail -n 40 {shlex.quote(self.log_file)}",
            )
        ]
