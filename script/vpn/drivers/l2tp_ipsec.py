#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""L2TP sur IPsec, clé pré-partagée : strongSwan + xl2tpd + pppd.

Trois étages, et il faut les trois pour avoir une interface :

    1. IPsec en mode TRANSPORT protège l'UDP 1701 entre nous et le serveur.
       Mode transport, pas tunnel : c'est L2TP qui encapsule, IPsec ne fait
       que chiffrer. Un `type=tunnel` ici ne monte jamais.
    2. L2TP (xl2tpd) ouvre une session dans ce canal protégé.
    3. PPP s'authentifie (MS-CHAPv2) et crée l'interface ppp*.

Trois pièges connus, réglés ici et pas ailleurs :

    · `charon { install_routes = no }` — sinon charon pose lui-même une
      route pour la SA, qui détourne le trafic L2TP et le tunnel n'aboutit
      jamais. C'est LE symptôme classique « la SA est établie, ppp0
      n'apparaît pas ».
    · Route de survie vers le serveur. En mode « tout le trafic », la route
      par défaut part dans ppp0 — y compris les paquets ESP à destination du
      serveur, qui se retrouvent à passer par le tunnel qu'ils portent. Une
      route /32 vers le serveur via la passerelle d'origine évite ce
      serpent qui se mord la queue.
    · systemd-resolved ignore /etc/ppp/resolv.conf. `usepeerdns` remplit ce
      fichier, personne ne le lit, et « le VPN marche mais aucun nom ne
      résout ». D'où l'appel `resolvectl` explicite.

Où vivent les fichiers, et pourquoi :

    /dev/shm/erplibre-vpn/<profil>/   0700 root — LES SECRETS. tmpfs : rien
                                     n'est écrit sur un disque persistant, et
                                     un redémarrage efface tout.
    /run/erplibre-vpn/<profil>.*     0755 — l'état non secret (interface
                                     retenue, pid, route ajoutée). Lisible
                                     sans sudo : `status` en a besoin.
    /etc/ipsec.conf, /etc/ipsec.secrets   un bloc marqué, retiré au « down ».
    /etc/strongswan.d/erplibre-vpn.conf   le réglage install_routes.
"""
from __future__ import annotations

import os
import re
import shlex
import sys

from script.vpn import valid
from script.vpn.drivers.base import (
    NETLINK_XFRM,
    SECRET_DIR,
    STATE_DIR,
    VpnDriver,
    interface_addresses,
    locate,
    netlink_family_available,
    ppp_interfaces,
    pppd_dns,
    resolve,
    wait_for_interface_address,
    wait_for_new_interface,
    which,
)

IPSEC_CONF = "/etc/ipsec.conf"
IPSEC_SECRETS = "/etc/ipsec.secrets"
STRONGSWAN_DROPIN = "/etc/strongswan.d/erplibre-vpn.conf"
# AppArmor confine charon par CHEMIN sur Debian et Ubuntu. Le profil se
# termine par `#include <local/…>` : c'est le point d'extension prévu, et le
# fichier local existe déjà, vide.
APPARMOR_PROFILE = "/etc/apparmor.d/usr.lib.ipsec.charon"
APPARMOR_LOCAL = "/etc/apparmor.d/local/usr.lib.ipsec.charon"

# Le drop-in est PARTAGÉ par tous les profils : c'est un réglage de charon,
# pas d'une connexion. Il vaut pour toute SA de la machine, et c'est assumé —
# sur un poste client, aucune SA ne veut que charon pose ses routes.
DROPIN_BODY = """# Généré par ERPLibre (script/vpn) — ne pas éditer.
#
# charon poserait sinon une route pour chaque SA. En L2TP/IPsec, cette route
# détourne le trafic UDP 1701 et le tunnel ne monte jamais : la SA s'établit,
# ppp0 n'apparaît pas. xl2tpd et pppd posent les routes dont on a besoin.
charon {
    install_routes = no
}
"""


# Ce que charon dit, et ce que ça veut dire. Ces cinq messages sont ceux
# qu'on rencontre en montant un tunnel L2TP/IPsec, et aucun ne se comprend
# seul : le premier a coûté une heure de recherche du côté du PSK, alors que
# le PSK était juste et le refus venait d'AppArmor.
IPSEC_HINTS = (
    (
        "no shared key found",
        "charon n'a pas trouvé le PSK. Le fichier est là, mais un refus"
        " AppArmor sur /dev/shm l'empêche de le LIRE :"
        " journalctl -k | grep DENIED.",
    ),
    (
        "not supported!",
        "charon a retenu un algorithme qu'il ne sait pas exécuter — le"
        " greffon manque. Sur Debian et Ubuntu, 3DES vient du greffon"
        " openssl : paquet libstrongswan-standard-plugins.",
    ),
    (
        "does not match to",
        "l'identité annoncée par la passerelle diffère de celle attendue."
        " `rightid=%any` l'accepte : le bloc de /etc/ipsec.conf est-il à"
        " jour ? Un « down » puis un « up » le réécrit.",
    ),
    (
        "AUTHENTICATION_FAILED",
        "la passerelle a refusé la clé pré-partagée.",
    ),
    (
        "NO_PROPOSAL_CHOSEN",
        "la passerelle refuse toutes nos propositions de chiffrement.",
    ),
)


class L2tpIpsecDriver(VpnDriver):
    name = "l2tp_ipsec"
    label = "L2TP/IPsec PSK"
    binaries = ("ipsec", "xl2tpd", "pppd", "ip")
    # L'IPsec du noyau est la première condition de tout : sans la famille
    # netlink XFRM, charon s'arrête à l'initialisation sur « kernel-ipsec »
    # manquant, et l'échec se lit ensuite comme une connexion jamais
    # chargée. La sonde ne rend « absent » que si le noyau refuse la
    # famille, ce qu'aucun droit ni aucun réglage ne provoque.
    kernel_features = (
        (
            "XFRM (IPsec du noyau)",
            lambda: netlink_family_available(NETLINK_XFRM),
        ),
    )
    secret_fields = (
        ("psk", "IPsec pre-shared key (PSK)", True),
        ("password", "PPP password", True),
    )
    iface_kind = "ppp"
    # Faux : un profil sans route reste utilisable — il joint l'hôte
    # distant, et l'adresse qu'on y obtient dit quel réseau ajouter. Le
    # site ne donne souvent qu'une passerelle et des identifiants.
    needs_routes = False
    hint = "When the far side imposes it: a router, a firewall, Windows RRAS"
    proven = True
    user_field = "ppp_user"
    defaults = {
        "ppp_user": "",
        "use_peer_dns": True,
        "dns_search": "",
        # Le port L2TP LOCAL. 1701 est la valeur attendue ; le déplacer est
        # le remède quand un xl2tpd du système tient déjà le port.
        "l2tp_local_port": 1701,
    }
    form_fields = (
        (
            "ppp_user",
            "PPP user (the one the server authenticates)",
            "text",
            False,
        ),
        ("l2tp_local_port", "Local L2TP port", "int", True),
        ("use_peer_dns", "Use the DNS pushed by the peer?", "flag", True),
        ("dns_search", "DNS search domain (optional)", "text", True),
    )

    # ------------------------------------------------------------------
    # Chemins et noms dérivés du profil
    # ------------------------------------------------------------------
    @property
    def conn(self):
        """Nom de la connexion IPsec ET du LAC xl2tpd. Préfixé pour ne
        jamais entrer en collision avec une connexion de l'utilisateur."""
        return f"erplibre-{self.name_tag}"

    @property
    def secrets_file(self):
        return f"{self.secret_dir}/ipsec.secrets"

    @property
    def xl2tpd_conf(self):
        return f"{self.secret_dir}/xl2tpd.conf"

    @property
    def ppp_options(self):
        return f"{self.secret_dir}/ppp.options"

    @property
    def control_file(self):
        return f"{STATE_DIR}/{self.name_tag}.control"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------
    @classmethod
    def validate_profile(cls, profile):
        valid.text(
            profile,
            "ppp_user",
            "Utilisateur PPP (c'est lui que le serveur authentifie)",
        )
        valid.port(profile, "l2tp_local_port", "Port L2TP local")
        valid.flag(profile, "use_peer_dns")
        valid.text(
            profile,
            "dns_search",
            "Domaine de recherche DNS",
            required=False,
            pattern=valid.HOST_RE,
        )

    # ------------------------------------------------------------------
    # Rendu des fichiers
    # ------------------------------------------------------------------
    def ipsec_conn_body(self):
        """Le bloc `conn` pour /etc/ipsec.conf.

        `leftprotoport=17/%any` et non `17/1701` : derrière du NAT, le port
        source local est réécrit, et une politique clouée sur 1701 ne
        s'applique alors plus aux paquets qui sortent. `%any` couvre les
        deux cas — dont 1701.

        Les propositions incluent 3DES et modp1024 : c'est vieux, et c'est
        exactement ce que servent les concentrateurs L2TP qu'on rencontre.
        Les listes sont ordonnées, le meilleur d'abord.
        """
        p = self.profile
        return "\n".join(
            [
                f"conn {self.conn}",
                "    keyexchange=ikev1",
                "    authby=secret",
                "    type=transport",
                "    left=%defaultroute",
                "    leftprotoport=17/%any",
                f"    right={p['server']}",
                # La passerelle s'annonce comme elle veut : par son IP, par
                # un FQDN, parfois par autre chose. Sans `rightid=%any`,
                # strongSwan déduit l'identité attendue de `right` et refuse
                # tout ce qui en diffère — « IDir '203.0.113.5' does not
                # match to 'vpn.exemple.com' », sur une configuration par
                # ailleurs juste. En PSK, c'est la CLÉ qui protège, pas
                # l'identité annoncée par le pair.
                "    rightid=%any",
                "    rightprotoport=17/1701",
                "    ike=aes256-sha1-modp1024,aes128-sha1-modp1024,"
                "3des-sha1-modp1024!",
                "    esp=aes256-sha1,aes128-sha1,3des-sha1!",
                "    dpdaction=clear",
                "    dpddelay=30s",
                "    auto=add",
            ]
        )

    def ipsec_secrets_body(self, server_ip):
        """Le PSK, en HEXADÉCIMAL.

        strongSwan accepte `PSK "texte"` ou `PSK 0x<hex>`, et les deux
        donnent les mêmes octets. L'hexadécimal évite toute question
        d'échappement : un PSK contenant `"` ou `\\` casse la forme citée,
        et un PSK est justement ce qu'on ne veut pas voir se faire tronquer
        en silence.
        """
        psk = self.secrets.get("psk", "")
        as_hex = psk.encode("utf-8").hex()
        return "\n".join(
            [
                "# Généré par ERPLibre (script/vpn). tmpfs : jamais sur",
                "# disque, effacé au « down » et à l'extinction.",
                f"%any {server_ip} : PSK 0x{as_hex}",
            ]
        )

    def xl2tpd_conf_body(self):
        p = self.profile
        # « ; » et non « # » : l'analyseur de xl2tpd ne connaît que le
        # point-virgule, et refuse le fichier ENTIER sur un « # » en tête —
        # « data '#…' occurs with no context », suivi de « Unable to load
        # config file ». Un commentaire mal marqué cassait tout.
        return "\n".join(
            [
                "; Généré par ERPLibre (script/vpn).",
                "[global]",
                f"port = {p['l2tp_local_port']}",
                "access control = no",
                "",
                f"[lac {self.conn}]",
                f"lns = {p['server']}",
                # Rien à EXIGER du pair : « require chap » et « require
                # authentication » font passer « require-chap » et « auth »
                # à pppd, c'est-à-dire « que le serveur s'authentifie
                # auprès de moi ». Le serveur refuse, à juste titre, et pppd
                # coupe : « LCP terminated by peer (peer refused to
                # authenticate) ». La politique d'authentification est celle
                # de ppp.options, et elle ne parle que de NOUS.
                "require chap = no",
                "refuse pap = no",
                "require authentication = no",
                "ppp debug = no",
                f"pppoptfile = {self.ppp_options}",
                "length bit = yes",
                "redial = no",
            ]
        )

    def ppp_options_body(self):
        """Les options pppd, mot de passe compris.

        C'est le seul secret que la technologie oblige à poser dans un
        fichier : pppd ne lit un mot de passe ni d'une variable
        d'environnement, ni d'un argument. Le fichier est donc en 0600
        dans un tmpfs 0700 appartenant à root, et il est effacé au « down ».
        Résiduel assumé : tant que le tunnel est monté, root peut le lire.
        """
        p = self.profile
        lines = [
            "# Généré par ERPLibre (script/vpn). tmpfs, 0600, effacé au down.",
            "ipcp-accept-local",
            "ipcp-accept-remote",
            # AUCUN `refuse-*`. La méthode est celle que le concentrateur
            # demande, et mesuré sur un vrai : « rcvd [LCP ConfReq …
            # <auth pap> …] », auquel un `refuse-pap` répond
            # « ConfNak <auth chap MD5> » — le serveur coupe alors la
            # liaison sur « peer refused to authenticate », et le « peer »
            # de ce message, c'est NOUS.
            #
            # PAP envoie le mot de passe en clair SUR LA LIAISON PPP, qui
            # voyage dans la session L2TP, elle-même dans l'ESP. C'est le
            # dispositif même de L2TP/IPsec : c'est IPsec qui protège
            # l'authentification PPP. Ce pilote ne lance jamais L2TP sans SA
            # IPsec établie — il abandonne avant —, donc le mot de passe ne
            # sort jamais en clair du poste.
            "noccp",
            # Ne rien exiger du pair. Un client n'authentifie pas son
            # concentrateur en PPP : c'est IPsec qui l'a fait, avant.
            "noauth",
            "noipdefault",
            f"mtu {p['mtu']}",
            f"mru {p['mtu']}",
            "connect-delay 5000",
            "lcp-echo-interval 30",
            "lcp-echo-failure 4",
            f"name {_pppd_quote(p['ppp_user'])}",
            f"password {_pppd_quote(self.secrets.get('password', ''))}",
        ]
        if p.get("use_peer_dns"):
            lines.append("usepeerdns")
        if p.get("default_route"):
            # `replacedefaultroute` remet l'ancienne route en descendant :
            # sans lui, une déconnexion brutale laisse la machine sans
            # route par défaut du tout.
            lines.append("defaultroute")
            lines.append("replacedefaultroute")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Montée
    # ------------------------------------------------------------------
    def up(self, runner):
        p = self.profile
        if not self.ensure_ready(runner):
            return False

        server_ip = runner.call(
            f"résoudre {p['server']}",
            lambda: resolve(p["server"]),
            dry_safe=True,
        )
        if not server_ip:
            runner.fail(
                f"« {p['server']} » ne résout pas : sans son adresse, ni le"
                " PSK ni la route de survie ne peuvent être posés."
            )
            return False
        runner.ok(f"{p['server']} → {server_ip}")

        before = (
            runner.call(
                "relever les interfaces PPP existantes",
                ppp_interfaces,
                dry_safe=True,
            )
            or set()
        )

        if not self._l2tp_port_is_free(runner):
            return False

        self.prepare_dirs(runner)
        runner.write(
            self.secrets_file,
            self.ipsec_secrets_body(server_ip) + "\n",
            mode="0600",
            secret=True,
        )
        runner.write(
            self.xl2tpd_conf, self.xl2tpd_conf_body() + "\n", mode="0600"
        )
        runner.write(
            self.ppp_options,
            self.ppp_options_body() + "\n",
            mode="0600",
            secret=True,
        )
        runner.write(STRONGSWAN_DROPIN, DROPIN_BODY, mode="0644")
        self._allow_apparmor_to_read_secrets(runner)
        runner.block(IPSEC_CONF, self.name_tag, self.ipsec_conn_body(), "0644")
        runner.block(
            IPSEC_SECRETS,
            self.name_tag,
            f"include {self.secrets_file}",
            "0600",
        )

        self._reload_charon(runner)
        if not self._wait_for_conn(runner):
            return False

        if p.get("default_route"):
            self.add_host_route(runner, server_ip)
            self.protect_the_ssh_session(runner)

        # Capturé, et non affiché en direct : cette sortie EST le
        # diagnostic. Une négociation IKE tient en une vingtaine de lignes,
        # et c'est la dernière qui dit pourquoi ça a échoué.
        code, out = runner.cmd(
            f"monter la SA IPsec ({self.conn})",
            f"ipsec up {shlex.quote(self.conn)}",
            timeout=120,
            check=False,
            capture=True,
        )
        if runner.dry_run:
            pass
        elif code != 0 or "established successfully" not in out:
            for line in out.strip().splitlines()[-6:]:
                runner.info(f"      │ {line}")
            runner.fail("La SA IPsec n'est pas montée.")
            for motif, explication in IPSEC_HINTS:
                if motif in out:
                    runner.info(f"      → {explication}")
            if not any(motif in out for motif, _ in IPSEC_HINTS):
                runner.info(
                    "      → Causes usuelles restantes : UDP 500/4500"
                    " filtré, ou passerelle injoignable. Voir"
                    " « diagnostic »."
                )
            return False
        else:
            runner.ok("SA IPsec établie.")

        runner.cmd(
            "lancer xl2tpd (instance dédiée à ce profil)",
            "xl2tpd -c {} -C {} -p {}".format(
                shlex.quote(self.xl2tpd_conf),
                shlex.quote(self.control_file),
                shlex.quote(self.pid_file),
            ),
        )
        if not self._wait_for_control(runner):
            return False
        runner.cmd(
            "demander la session L2TP",
            "sh -c {}".format(
                shlex.quote(
                    f'echo "c {self.conn}" > {shlex.quote(self.control_file)}'
                )
            ),
            timeout=30,
        )

        iface = runner.call(
            "attendre l'interface PPP",
            lambda: wait_for_new_interface(before, "ppp"),
        )
        if runner.dry_run:
            runner.info("      (à blanc : l'interface serait nommée ici)")
            return True
        if not iface:
            runner.fail(
                "Aucune interface PPP n'est apparue. La SA IPsec est"
                " montée : le refus vient de L2TP ou de PPP"
                " (identifiants, MS-CHAPv2). Voir « diagnostic »."
            )
            return False
        # L'interface EXISTE dès que pppd la crée, bien avant qu'IPCP ait
        # négocié l'adresse. La lire tout de suite annonçait « ppp0 : sans
        # adresse » sur un tunnel qui allait très bien — et faisait chercher
        # les DNS du pair avant que pppd les ait écrits.
        addresses = runner.call(
            f"attendre l'adresse de {iface}",
            lambda: wait_for_interface_address(iface),
        )
        if not addresses:
            runner.fail(
                f"{iface} est apparue sans obtenir d'adresse : IPCP n'a pas"
                " abouti. L'authentification PPP a-t-elle réussi ? Le"
                " journal de pppd le dit — voir « diagnostic »."
            )
            return False
        runner.ok(f"interface {iface} : {', '.join(addresses)}")
        self.write_state(runner, "iface", iface)
        self.add_routes(runner, iface)
        self.suggest_routes(runner, iface)
        if p.get("use_peer_dns"):
            servers = runner.call(
                "lire les DNS poussés par le pair", pppd_dns, dry_safe=True
            )
            if servers:
                self.set_resolved_dns(
                    runner, iface, servers, p.get("dns_search", "")
                )
            else:
                runner.warn("Le pair n'a poussé aucun DNS.")
        return True

    # ------------------------------------------------------------------
    # Descente
    # ------------------------------------------------------------------
    def down(self, runner):
        """Défait tout, dans l'ordre inverse, sans s'arrêter au premier
        échec : une descente doit nettoyer ce qu'elle PEUT nettoyer, même
        si un étage est déjà tombé de lui-même."""
        runner.cmd(
            "fermer la session L2TP",
            "sh -c {}".format(
                shlex.quote(
                    f"[ -p {shlex.quote(self.control_file)} ] &&"
                    f' echo "d {self.conn}" >'
                    f" {shlex.quote(self.control_file)} || true"
                )
            ),
            check=False,
            timeout=20,
        )
        self.kill_pidfile(runner, "arrêter xl2tpd")
        runner.cmd(
            f"descendre la SA IPsec ({self.conn})",
            f"ipsec down {shlex.quote(self.conn)}",
            check=False,
        )
        self.del_host_route(runner)
        # Les blocs AVANT les fichiers : un `include` qui pointe vers un
        # fichier disparu fait échouer tout rechargement de charon, y
        # compris ceux d'une autre connexion.
        runner.block(IPSEC_SECRETS, self.name_tag, "", "0600")
        runner.block(IPSEC_CONF, self.name_tag, "", "0644")
        runner.remove(self.secret_dir)
        self.clear_state(runner, "iface", "hostroute", "pid", "control")
        self._reload_charon(runner, check=False)
        runner.ok("Tunnel démonté, secrets effacés.")
        return True

    # ------------------------------------------------------------------
    # État
    # ------------------------------------------------------------------
    def status(self, runner):
        # `statusall` et non `status` : `status` ne montre que les SA, et son
        # « no match » est la réponse NORMALE d'un tunnel démonté. Il ne dit
        # rien de la connexion elle-même — confondre les deux envoyait
        # chercher une configuration absente alors qu'elle était chargée.
        code, out = runner.cmd(
            "état de charon",
            f"ipsec statusall {shlex.quote(self.conn)}",
            check=False,
            capture=True,
        )
        if code != 0:
            unreachable = "charon injoignable (arrêté ? sudo refusé ?)"
            return self.standard_status(
                runner,
                extra=[
                    ("connexion chargée", None, unreachable),
                    ("SA IPsec", None, unreachable),
                ],
            )
        loaded = f"{self.conn}:" in out
        established = "ESTABLISHED" in out
        extra = [
            (
                "connexion chargée",
                loaded,
                self.conn if loaded else "absente de charon",
            ),
            (
                "SA IPsec",
                established,
                "établie" if established else "aucune SA (tunnel démonté)",
            ),
        ]
        return self.standard_status(runner, extra=extra)

    def log_commands(self):
        """L'unité strongSwan n'a pas le même nom partout : on essaie les
        deux plutôt que de deviner la distribution."""
        return [
            (
                "journal strongSwan / xl2tpd",
                "journalctl -n 40 --no-pager -u strongswan-starter"
                " -u strongswan -u xl2tpd",
            ),
            ("journal pppd", "journalctl -n 20 --no-pager -t pppd"),
            # Le seul endroit où un refus AppArmor apparaît. Sans cette
            # ligne, un « no shared key found » reste inexplicable.
            (
                "refus AppArmor (noyau)",
                'sh -c "journalctl -k --no-pager -n 200'
                " | grep -i 'apparmor=\\\"DENIED\\\"' | tail -5"
                " || echo 'aucun refus AppArmor récent'\"",
            ),
        ]

    # ------------------------------------------------------------------
    # Détails propres à L2TP/IPsec
    # ------------------------------------------------------------------
    def _wait_for_control(self, runner):
        """Attend que xl2tpd crée son tube de contrôle.

        xl2tpd se détache immédiatement et crée le FIFO ensuite. Écrire
        dedans sans attendre échoue sur « No such file or directory », une
        erreur qui ne dit rien du vrai problème — lequel est presque
        toujours un xl2tpd qui n'a pas pu s'attacher au port.
        """
        control = shlex.quote(self.control_file)
        script = (
            f"for i in $(seq 1 40); do [ -p {control} ] && exit 0;"
            " sleep 0.25; done; exit 1"
        )
        code, _ = runner.cmd(
            "attendre le tube de contrôle de xl2tpd",
            f"sh -c {shlex.quote(script)}",
            check=False,
            timeout=25,
        )
        if code == 0 or runner.dry_run:
            return True
        runner.fail(
            "xl2tpd n'a pas créé son tube de contrôle : il n'a pas"
            " démarré. Cause la plus fréquente, UDP"
            f" {self.profile['l2tp_local_port']} déjà pris — voir"
            " « diagnostic »."
        )
        return False

    def _l2tp_port_is_free(self, runner):
        """Faux si le port L2TP local est encore tenu après remèdes.

        La question n'est PAS « le service xl2tpd est-il actif ? » mais « le
        port est-il libre ? » : un xl2tpd orphelin tient UDP 1701 alors que
        `systemctl is-active xl2tpd` répond « inactive », et le service en
        relance un second par-dessus. Le nom du service ne dit rien ; le
        port, tout.

        On classe donc pid par pid, parce que les détenteurs peuvent être de
        natures différentes en même temps :

        · un reste d'un montage précédent de CE profil → on propose notre
          propre « down » ;
        · un xl2tpd qui n'est pas à nous (service, orphelin) → on propose de
          l'arrêter et de le terminer ;
        · le tunnel d'un AUTRE de nos profils → on le nomme et on s'arrête :
          couper le sien est une décision qui revient à son propriétaire ;
        · autre chose → on le nomme, on n'y touche pas.

        Sans `ss`, on ne bloque pas : l'absence du tube de contrôle de
        xl2tpd le dira deux étapes plus loin, et un faux blocage serait pire
        qu'un échec tardif.
        """
        port = self.profile["l2tp_local_port"]
        if not locate("ss"):
            return True
        report = runner.warn if runner.dry_run else runner.fail

        holders, tenu = self._port_holders(runner, port)
        if not tenu:
            return True

        voisin = self._sibling_profile(holders)
        if voisin:
            report(f"UDP {port} est tenu par notre tunnel « {voisin} ».")
            runner.info(
                "      → Le démonter d'abord :"
                f" ./script/vpn/vpn.py down --profile {voisin}"
                "  (deux profils L2TP ne partagent pas le même port, et"
                " couper le sien est votre décision, pas la nôtre)."
            )
            return runner.dry_run

        # Remède 1 : un reste de CE profil.
        if self._mine(holders):
            runner.info(
                f"      Un montage précédent de « {self.name_tag} » n'a pas"
                " été démonté."
            )
            if runner.propose(
                f"reste du montage précédent de {self.name_tag}",
                f"{sys.executable} -u ./script/vpn/vpn.py down --profile"
                f" {shlex.quote(self.name_tag)}",
                sudo=False,
                question="Démonter ce reste et réessayer ?",
            ):
                holders, tenu = self._port_holders(runner, port)
                if not tenu:
                    runner.ok(f"Reste démonté, UDP {port} libre.")
                    return True

        # Remède 2 : des xl2tpd qui ne sont pas à nous.
        etrangers = self._foreign_xl2tpd(holders)
        if etrangers:
            if runner.propose(
                f"UDP {port} tenu par xl2tpd",
                "sh -c {}".format(
                    shlex.quote(
                        "systemctl stop xl2tpd 2>/dev/null;"
                        f" kill {' '.join(etrangers)} 2>/dev/null; true"
                    )
                ),
                question=(
                    "Arrêter le service xl2tpd et terminer les processus"
                    f" restants ({', '.join(etrangers)}), puis réessayer ?"
                ),
            ):
                holders, tenu = self._port_holders(runner, port)
                if not tenu:
                    runner.ok(f"UDP {port} libéré.")
                    runner.info(
                        "      (le service reviendra au prochain démarrage :"
                        " sudo systemctl disable xl2tpd)"
                    )
                    return True

        report(f"UDP {port} est encore tenu : {tenu.splitlines()[0][:110]}")
        inconnus = [
            args for _pid, args in holders if "xl2tpd" not in args and args
        ]
        if inconnus:
            runner.info(
                f"      → « {inconnus[0][:60]} » n'est pas à nous :"
                " l'arrêter demande votre décision, ou changer"
                " « l2tp_local_port » dans le profil."
            )
        return runner.dry_run

    def _who_holds_the_port(self, runner, port):
        """Ligne(s) de `ss` décrivant qui tient UDP `port`, "" si personne."""
        script = f"ss -lunp 2>/dev/null | grep ':{port} ' || true"
        _, out = runner.cmd(
            f"UDP {port} est-il déjà tenu ?",
            f"sh -c {shlex.quote(script)}",
            check=False,
            capture=True,
        )
        return out.strip()

    def _port_holders(self, runner, port):
        """([(pid, ligne de commande)], sortie brute de `ss`).

        La ligne de commande est ce qui distingue nos instances des autres :
        les nôtres portent leur configuration dans SECRET_DIR/<profil>/.
        """
        tenu = self._who_holds_the_port(runner, port)
        pids = re.findall(r"pid=(\d+)", tenu)
        if not pids:
            return [], tenu
        _, out = runner.cmd(
            "à qui appartiennent ces processus ?",
            f"ps -o pid=,args= -p {' '.join(pids)}",
            sudo=False,
            check=False,
            capture=True,
        )
        vu = {}
        for line in (out or "").splitlines():
            morceaux = line.strip().split(None, 1)
            if len(morceaux) == 2:
                vu[morceaux[0]] = morceaux[1]
        # `ss` nomme déjà le processus : c'est le repli quand `ps` ne dit
        # rien (hidepid, processus disparu entre les deux appels). Sans ce
        # repli on perdrait la classification, donc le remède, sur une
        # information qu'on avait pourtant déjà.
        noms = dict(
            (pid, nom)
            for nom, pid in re.findall(r'\("([^"]+)",pid=(\d+)', tenu)
        )
        return [(pid, vu.get(pid) or noms.get(pid, "")) for pid in pids], tenu

    def _mine(self, holders):
        """Pids qui sont des instances de CE profil."""
        marque = f"{SECRET_DIR}/{self.name_tag}/"
        return [pid for pid, args in holders if marque in args]

    def _sibling_profile(self, holders):
        """Nom d'un AUTRE de nos profils tenant le port, "" sinon."""
        for _pid, args in holders:
            trouve = re.search(
                rf"{re.escape(SECRET_DIR)}/([^/\s]+)/", args or ""
            )
            if trouve and trouve.group(1) != self.name_tag:
                return trouve.group(1)
        return ""

    def _foreign_xl2tpd(self, holders):
        """Pids xl2tpd qui ne sont pas des instances à nous."""
        return [
            pid
            for pid, args in holders
            if "xl2tpd" in args and SECRET_DIR not in args
        ]

    def _allow_apparmor_to_read_secrets(self, runner):
        """Autorise charon à lire nos secrets en tmpfs.

        AppArmor confine charon par CHEMIN, et `/dev/shm` ne figure pas dans
        son profil. Sans cette règle, charon lit /etc/ipsec.secrets, suit
        notre `include`, et se fait refuser le fichier par le noyau — pour
        échouer trois étages plus loin sur « no shared key found », alors
        que le PSK est là et bien formé. Seul `journalctl -k` le dit, en
        clair : `apparmor="DENIED" … denied_mask="r"`.

        Le fichier `local/` est le point d'extension prévu par Debian et
        Ubuntu ; il ne contient aucun secret, seulement un chemin. Il n'est
        PAS retiré au démontage : c'est une permission de chemin, valable
        pour tous les profils, et inoffensive quand le répertoire est vide.
        """
        if not os.path.exists(APPARMOR_PROFILE):
            # Ni Debian ni Ubuntu : pas de profil charon à étendre.
            return
        changed = runner.block(
            APPARMOR_LOCAL,
            "secrets",
            f"{SECRET_DIR}/** r,",
            "0644",
        )
        if not changed:
            return
        # Le rechargement s'applique aussi au charon DÉJÀ lancé : sans lui,
        # la règle n'entrerait en vigueur qu'au prochain démarrage.
        runner.cmd(
            "recharger le profil AppArmor de charon",
            f"apparmor_parser -r {shlex.quote(APPARMOR_PROFILE)}",
            check=False,
        )

    def _wait_for_conn(self, runner):
        """Attend que la connexion soit chargée dans charon.

        `ipsec start` rend la main tout de suite : charon met une fraction
        de seconde à démarrer, et le starter lui pousse les connexions
        ENSUITE. Un `ipsec up` lancé dans l'instant échoue sur « no match »
        — la connexion étant parfaitement valide, c'est l'erreur la plus
        trompeuse de toute la séquence.
        """
        conn = shlex.quote(self.conn)
        script = (
            f"for i in $(seq 1 40); do ipsec statusall {conn} 2>/dev/null"
            f" | grep -q {shlex.quote(self.conn + ':')} && exit 0;"
            " sleep 0.25; done; exit 1"
        )
        code, _ = runner.cmd(
            "attendre que charon ait chargé la connexion",
            f"sh -c {shlex.quote(script)}",
            check=False,
            timeout=20,
        )
        if code == 0 or runner.dry_run:
            return True
        runner.fail(
            f"charon n'a pas chargé « {self.conn} » en 10 s. Le bloc de"
            " /etc/ipsec.conf est-il bien formé ? Voir le journal de"
            " strongSwan."
        )
        return False

    def _reload_charon(self, runner, check=True):
        code, _ = runner.cmd(
            "charon tourne-t-il ?",
            "ipsec status",
            check=False,
            capture=True,
        )
        if code != 0:
            runner.cmd("démarrer charon", "ipsec start", check=check)
            return
        runner.cmd("recharger ipsec.conf", "ipsec reload", check=check)
        runner.cmd("relire les secrets", "ipsec rereadsecrets", check=check)


def _pppd_quote(value: str) -> str:
    """`value` cité pour un fichier d'options pppd.

    pppd lit des chaînes entre guillemets doubles et y traite `\\` comme
    échappement. Un utilisateur de la forme `DOMAINE\\prenom` est courant sur
    les concentrateurs L2TP : sans cet échappement, pppd envoie
    `DOMAINEprenom` et le serveur refuse sans dire pourquoi.
    """
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'
