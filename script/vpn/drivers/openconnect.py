#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""OpenConnect : le seul pilote où aucun secret ne touche un fichier.

`--passwd-on-stdin` fait lire le mot de passe sur l'entrée standard. Il ne
passe donc ni par un argument (`/proc/<pid>/cmdline`, lisible par tous), ni
par un fichier, même en tmpfs. C'est le cas idéal, et il vaut la peine d'être
nommé : les autres pilotes composent avec des technologies qui EXIGENT un
fichier, celui-ci n'en a pas besoin.

Un client, plusieurs protocoles : AnyConnect (Cisco), Pulse/Juniper,
GlobalProtect (Palo Alto), Fortinet, F5, Array. `--protocol` décide.

`--non-inter` est passé volontairement. Sans lui, un certificat serveur
inconnu déclenche une question — et openconnect la lirait sur l'entrée
standard, celle par laquelle arrive justement le mot de passe. Le tunnel
échouerait sur un « certificate verify failed » incompréhensible. Avec
`--non-inter`, openconnect refuse tout de suite ET imprime la ligne
`--servercert sha256:…` à recopier dans le champ `oc_servercert` du profil.

Les routes appartiennent au serveur : c'est `vpnc-script` qui les pose, à
partir de ce que le concentrateur pousse. Le profil peut en AJOUTER, il ne
les remplace pas — d'où `needs_routes = False`.

SSO / SAML — le cas du « formulaire web »
-----------------------------------------
Quand le concentrateur authentifie par un fournisseur d'identité (Azure AD,
Okta, Duo…), il n'y a pas de mot de passe à envoyer : il faut une page web.
Le client de Cisco la rend dans un navigateur WebKit embarqué — donc un
écran, et sur bien des postes la variable `WEBKIT_DISABLE_DMABUF_RENDERER=1`
en prime pour qu'elle s'affiche. Son CLI, lui, ne sait pas le faire.

openconnect le fait sans écran sur la machine cliente. Mesuré dans sa
bibliothèque : il ÉCOUTE sur le port local 29786 et attend la redirection
(« Accepted incoming external-browser connection on port 29786 »), après
avoir lancé le programme donné à `--external-browser` avec l'URL de
connexion. Sur un serveur, ce « navigateur » est un simple `echo` : l'URL
s'affiche, on l'ouvre dans SON navigateur, et un

    ssh -L 29786:localhost:29786 <la machine cliente>

fait revenir la redirection à openconnect. Aucun écran là-bas, et le mot de
passe ne quitte jamais le poste de l'utilisateur.
"""
from __future__ import annotations

import shlex

from script.vpn import valid
from script.vpn.drivers.base import (
    VpnDriver,
    interface_addresses,
    interface_exists,
)

# Ce que ce client sait parler. La liste vient de `openconnect --protocol`.
PROTOCOLS = ("anyconnect", "nc", "pulse", "gp", "f5", "fortinet", "array")


class OpenconnectDriver(VpnDriver):
    name = "openconnect"
    label = "OpenConnect"
    binaries = ("openconnect", "ip")
    # Non obligatoire : en SSO il n'y a AUCUN mot de passe à déposer, et le
    # menu ne doit pas réclamer un secret que la méthode n'utilise pas. La
    # vraie exigence dépend du mode, elle est donc dans `up`.
    secret_fields = (("password", "VPN password", False),)
    iface_kind = "tun"
    hint = "Cisco AnyConnect, Pulse, GlobalProtect, Fortinet appliances"
    user_field = "oc_user"
    # Le MTU vient du serveur (ou du .ovpn), pas du profil.
    uses_mtu = False
    # Le serveur pousse les routes : exiger une route déclarée serait une
    # fausse exigence.
    needs_routes = False
    defaults = {
        "port": 443,
        "oc_user": "",
        "oc_protocol": "anyconnect",
        "oc_authgroup": "",
        "oc_servercert": "",
        # SSO : le concentrateur authentifie par un fournisseur d'identité,
        # dans un navigateur. Voir l'en-tête du fichier.
        "oc_sso": False,
        # Programme lancé avec l'URL de connexion. Vide = `echo`, qui
        # l'affiche : c'est ce qu'on veut sur une machine sans écran.
        "oc_external_browser": "",
    }
    form_fields = (
        ("oc_user", "VPN user", "text", False),
        (
            "oc_protocol",
            "Protocol (anyconnect, nc, pulse, gp, f5, fortinet, array)",
            "text",
            False,
        ),
        (
            "oc_authgroup",
            "Authentication group / realm (optional)",
            "text",
            True,
        ),
        (
            "oc_servercert",
            "Pinned server certificate (sha256:... , printed on first refusal)",
            "text",
            True,
        ),
        (
            "oc_sso",
            "Authentication through a web form (SAML / SSO)?",
            "flag",
            False,
        ),
        (
            "oc_external_browser",
            "Browser command for SSO (empty: show the URL to open yourself)",
            "path",
            True,
        ),
        ("port", "HTTPS port", "int", True),
    )

    # ------------------------------------------------------------------
    @property
    def iface(self):
        """Interface NOMMÉE, et non découverte : openconnect sait le faire
        (`--interface`), et un nom connu d'avance rend `status` fiable même
        après un redémarrage du CLI. Tronqué à 15 caractères."""
        return f"vpn-{self.name_tag}"[:15]

    @classmethod
    def validate_profile(cls, profile):
        # Le mode d'abord : en SSO, c'est le fournisseur d'identité qui
        # décide de qui on est, et exiger un utilisateur ici refuserait un
        # profil parfaitement valide.
        valid.flag(profile, "oc_sso")
        valid.text(
            profile,
            "oc_user",
            "Utilisateur VPN",
            required=not profile["oc_sso"],
        )
        protocol = valid.text(profile, "oc_protocol", "Protocole")
        if protocol not in PROTOCOLS:
            raise valid.ProfileError(
                f"Protocole inconnu : « {protocol} »."
                f" Connus : {', '.join(PROTOCOLS)}."
            )
        valid.text(
            profile,
            "oc_authgroup",
            "Groupe d'authentification",
            required=False,
        )
        valid.text(
            profile,
            "oc_servercert",
            "Empreinte du certificat serveur",
            required=False,
        )
        valid.port(profile, "port", "Port HTTPS")
        valid.path(
            profile,
            "oc_external_browser",
            "Programme navigateur",
            required=False,
        )

    @property
    def browser(self):
        """Programme lancé avec l'URL de connexion SSO.

        `echo` par défaut : sur une machine sans écran, afficher l'URL est
        exactement ce qu'on veut — openconnect attend ensuite la redirection
        sur son port 29786."""
        return self.profile.get("oc_external_browser") or "echo"

    def command(self):
        """La ligne de commande, dans l'une de ses deux formes.

        Classique : le mot de passe arrive par l'entrée standard, grâce à
        `--passwd-on-stdin` — il n'est jamais dans la ligne de commande.

        SSO : il n'y a pas de mot de passe. Pas de `--non-inter` non plus,
        car l'échange avec le navigateur EST l'interaction ; l'interdire
        ferait échouer la seule étape qui compte.
        """
        p = self.profile
        parts = [
            "openconnect",
            f"--protocol={shlex.quote(p['oc_protocol'])}",
        ]
        if p["oc_user"]:
            parts.append(f"--user={shlex.quote(p['oc_user'])}")
        if p["oc_sso"]:
            parts.append(f"--external-browser={shlex.quote(self.browser)}")
        else:
            parts += ["--passwd-on-stdin", "--non-inter"]
        parts += [
            "--background",
            f"--pid-file={shlex.quote(self.pid_file)}",
            f"--interface={shlex.quote(self.iface)}",
        ]
        if p.get("oc_authgroup"):
            parts.append(f"--authgroup={shlex.quote(p['oc_authgroup'])}")
        if p.get("oc_servercert"):
            parts.append(f"--servercert={shlex.quote(p['oc_servercert'])}")
        parts.append(shlex.quote(f"{p['server']}:{p['port']}"))
        return " ".join(parts)

    # ------------------------------------------------------------------
    def up(self, runner):
        p = self.profile
        if not self.ensure_ready(runner):
            return False
        # `secrets=False` : ce pilote n'écrit AUCUN fichier de secret, et
        # créer un répertoire pour rien serait laisser croire qu'il en a un.
        self.prepare_dirs(runner, secrets=False)

        if p["oc_sso"]:
            self._explain_the_sso_round_trip(runner)
            mot_de_passe, delai = None, 300
        else:
            if not self.secrets.get("password"):
                report = runner.warn if runner.dry_run else runner.fail
                report(
                    "Aucun mot de passe dans le coffre, et le profil n'est"
                    " pas en SSO : les déposer, ou cocher « formulaire web »."
                )
                if not runner.dry_run:
                    return False
            mot_de_passe = self.secrets.get("password", "") + "\n"
            delai = 120

        code, _ = runner.cmd(
            f"ouvrir la session {p['oc_protocol']} sur {p['server']}",
            self.command(),
            stdin=mot_de_passe,
            secret_stdin=bool(mot_de_passe),
            check=False,
            timeout=delai,
        )
        if code != 0 and not runner.dry_run:
            runner.fail("openconnect a refusé.")
            if p["oc_sso"]:
                runner.info(
                    "      → En SSO, les deux causes sont : la redirection"
                    " n'est jamais revenue sur le port 29786 (redirection"
                    " ssh en place ?), ou le délai de 5 minutes a expiré"
                    " avant la fin de l'authentification."
                )
            else:
                runner.info(
                    "      → Causes usuelles : identifiants, certificat"
                    " serveur non épinglé (recopier la ligne"
                    " « --servercert sha256:… » ci-dessus dans le champ"
                    " oc_servercert), groupe d'authentification absent."
                )
            return False
        if runner.dry_run:
            runner.info(f"      (à blanc : l'interface serait {self.iface})")
            return True

        if not interface_exists(self.iface):
            runner.fail(
                f"openconnect s'est lancé mais {self.iface} n'existe pas."
                " vpnc-script est-il installé ? (paquet vpnc-scripts)"
            )
            return False
        addresses = (
            ", ".join(interface_addresses(self.iface)) or "sans adresse"
        )
        runner.ok(f"interface {self.iface} : {addresses}")
        self.write_state(runner, "iface", self.iface)
        # Les routes du serveur sont déjà posées par vpnc-script. Celles du
        # profil s'AJOUTENT : un réseau que le concentrateur ne pousse pas
        # mais qu'on sait joignable.
        self.add_routes(runner, self.iface)
        return True

    def _explain_the_sso_round_trip(self, runner):
        """Dit à l'humain ce qu'il va devoir faire, AVANT de le bloquer.

        openconnect va afficher une URL puis attendre, silencieusement, sur
        son port 29786. Sans cette explication, l'attente ressemble à un
        blocage — et la redirection ne revient jamais si personne n'a monté
        le tunnel ssh."""
        runner.info(
            "      Authentification par formulaire web. openconnect va"
            " afficher une URL, puis attendre la redirection sur son port"
            " local 29786."
        )
        runner.info(
            "      Depuis VOTRE poste, avant d'ouvrir l'URL :"
            " ssh -L 29786:localhost:29786 <cette machine>"
        )
        if self.browser == "echo":
            runner.info(
                "      L'URL s'affichera ici : l'ouvrir dans votre propre"
                " navigateur. Le mot de passe ne quitte pas votre poste."
            )
        else:
            runner.info(f"      Navigateur lancé sur place : {self.browser}")

    def down(self, runner):
        # SIGTERM : openconnect rappelle vpnc-script, qui défait les routes
        # et le DNS qu'il avait posés. Un « kill -9 » les laisserait en
        # place, et la machine resterait à moitié dans le tunnel.
        self.kill_pidfile(runner, "arrêter openconnect (SIGTERM)")
        self.clear_state(runner, "iface", "pid")
        runner.ok(
            "Session fermée. Aucun secret à effacer : il n'a jamais"
            " touché le disque."
        )
        return True

    def status(self, runner):
        return self.standard_status(
            runner, extra=[self.check_daemon("processus openconnect")]
        )

    def log_commands(self):
        return [
            (
                "journal openconnect",
                "journalctl -n 40 --no-pager -t openconnect",
            )
        ]
