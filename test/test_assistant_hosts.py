#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les sources de cibles qui viennent d'ailleurs : QEMU, SSH, et ses tunnels.

L'énumération des VM libvirt, la résolution d'un alias SSH et la lecture de
ses redirections sont des méthodes de la classe TODO, et le paquet
`assistant` n'a pas le droit d'importer `todo.py` — l'import coûte près d'une
seconde et imprime sur la sortie. Les trois sources arrivent donc INJECTÉES,
et ce que ces tests défendent est le contrat de cette injection : une source
non branchée rend une liste VIDE et non une erreur, et aucun de ces tests ne
touche `virsh`, `ssh -G` ni la configuration SSH réelle.

Le danger que la maison connaît est le test qui n'affirme rien. Cette
machine-ci n'a AUCUN domaine libvirt et AUCUNE configuration SSH : un test
qui boucle sur la sortie réelle ne s'exécute jamais et passe pour la mauvaise
raison. Chaque boucle est donc précédée d'une garde sur le jeu d'essai, et
tout ce qui est parcouru vient de constantes de ce fichier.

Trois régressions sont visées par leur nom.

**Le résolveur qui écrase.** Un mot-clé de ssh_config se répète
légitimement, et le résolveur qui ne garde qu'une valeur par mot-clé — celui
qui convient à `identityfile`, dont la première entrée est celle qui compte —
réduit trois redirections déclarées à une seule. Deux services sur trois
disparaissent alors sans que rien ne tombe en rouge, et le menu annonce une
découverte réussie.

**Le résolveur patient.** Les deux résolveurs d'adresse de VM qui attendent
patientent jusqu'à dix minutes PAR VM ; seul celui qui lit le bail une fois
convient à l'affichage d'une liste. Un test lit le TEXTE du module pour que
substituer l'un à l'autre casse, parce qu'aucune assertion de comportement ne
distingue « lent » de « rapide ».

**Les motifs pris pour des machines.** Un joker est une règle et un motif nié
retire un nom : ni l'un ni l'autre ne désigne une machine à sonder.
L'énumérateur du dépôt écarte le premier et laisse passer le second, donc
l'énumérateur d'essai d'ici rend les DEUX, et c'est la source testée qui doit
les refuser.

Les alias, les noms de VM et les adresses sont INVENTÉS :
`.claude/rules/04-code-conventions.md` l'exige pour la valeur qui illustre un
interdit, et demande d'en vérifier l'absence ailleurs. Le domaine de premier
niveau `.invalid` est réservé à cet usage, et « azurite », « obsidienne »,
« malachite » et « basalte » ne désignent rien de réel : hors de ces tests,
ils ne paraissent que dans d'autres jeux d'essai, jamais dans du code ni
dans une configuration.
"""

import os
import re
import subprocess
import sys
import unittest

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import discover  # noqa: E402

# Une configuration SSH d'essai. Deux noms sur une seule ligne « Host », un
# joker, un motif nié, et une entrée SANS `HostName` — les quatre formes que
# la source doit traiter différemment.
CONFIG = """
Host azurite.invalid obsidienne.invalid
    HostName 192.0.2.21
    Port 2222

Host *
    ServerAliveInterval 30

Host !malachite.invalid
    User personne

Host basalte.invalid
"""

# Ce que `ssh -G` rend pour les alias qui déclarent quelque chose. Les clés
# sont en minuscules, comme celles du résolveur du dépôt.
RESOLU = {
    "azurite.invalid": {"hostname": "192.0.2.21", "port": "2222"},
    "obsidienne.invalid": {"hostname": "192.0.2.21", "port": "2222"},
}

# Des noms de VM inventés. Le second n'a pas d'adresse, le troisième en fait
# lever la résolution.
VM_AVEC_IP = "vm-azurite"
VM_SANS_IP = "vm-obsidienne"
VM_QUI_LEVE = "vm-basalte"
IP_DE_VM = "192.0.2.31"


def alias_naifs(texte=CONFIG):
    """Un énumérateur d'alias qui rend TOUT ce qu'une ligne « Host » porte.

    Il découpe les noms multiples comme l'énumérateur du dépôt, mais ne
    filtre NI le joker NI le motif nié : le dépôt écarte le premier et laisse
    passer le second, et rendre les deux met la charge du filtrage sur la
    source testée, qui est ce qu'on veut vérifier.
    """

    def lister():
        noms = []
        for ligne in texte.splitlines():
            if not re.match(r"^[ \t]*Host[ \t]+", ligne):
                continue
            noms.extend(ligne.split()[1:])
        return noms

    return lister


def resolveur(table=None, appels=None):
    """Un `ssh -G` d'essai, y compris son comportement par défaut.

    Un alias absent de la table rend l'alias LUI-MÊME comme hôte et le port
    22, ce qui est ce que `ssh -G` annonce quand rien n'est déclaré : la
    branche sans `HostName` ne s'invente donc pas, elle se recopie.
    """
    table = RESOLU if table is None else table

    def resolve(alias):
        if appels is not None:
            appels.append(alias)
        return dict(table.get(alias, {"hostname": alias, "port": "22"}))

    return resolve


# Ce que `ssh -G` rend pour un mot-clé RÉPÉTÉ : une valeur par occurrence,
# dans l'ordre de la sortie. Toutes les formes que la source doit trancher —
# port nu, liaison explicite, les trois jokers, nom de liaison, liaison IPv6,
# destination IPv6, et socket Unix sans port. Le dernier couple redéclare un
# port local déjà pris.
#
# Les trois jokers ne se valent PAS, et c'est ce que la source doit savoir :
# « * » et « 0.0.0.0 » ouvrent un écouteur que la boucle locale v4 joint,
# « :: » un écouteur marqué `IPV6_V6ONLY` qu'elle ne joint pas.
FORWARDS = {
    "azurite.invalid": {
        "localforward": [
            "1234 [127.0.0.1]:1234",
            "[127.0.0.1]:2345 [obsidienne.invalid]:80",
            "[*]:3456 [192.0.2.31]:8000",
            "[localhost]:4567 [2001:db8::1]:9000",
            "[0.0.0.0]:6001 [192.0.2.31]:81",
            "[::1]:6002 [192.0.2.31]:82",
            "[::]:6003 [192.0.2.31]:83",
            "/run/essai.sock [192.0.2.31]:22",
            "1234 [192.0.2.31]:9999",
        ]
    },
    "basalte.invalid": {"localforward": ["5678 [127.0.0.1]:5678"]},
}


def resolveur_complet(table=None, appels=None):
    """Un `ssh -G` d'essai qui GARDE les répétitions, en {clé: [valeurs]}.

    C'est le contrat que la source des tunnels exige, et il diffère de celui
    de `resolveur` : un mot-clé répété y rend une LISTE. Un alias absent de
    la table rend un dictionnaire vide, ce qui est ce qu'annonce une entrée
    qui ne déclare aucun tunnel.
    """
    table = FORWARDS if table is None else table

    def resolve_all(alias):
        if appels is not None:
            appels.append(alias)
        return {cle: list(val) for cle, val in table.get(alias, {}).items()}

    return resolve_all


def domaines(noms, appels=None):
    """Un énumérateur de domaines libvirt, qui note qu'on l'a appelé."""

    def lister():
        if appels is not None:
            appels.append("list")
        return list(noms)

    return lister


def adresse_de_vm(appels=None):
    """Le résolveur d'adresse BON MARCHÉ : une lecture, aucune attente."""

    def vm_ip(name):
        if appels is not None:
            appels.append(name)
        if name == VM_AVEC_IP:
            return IP_DE_VM
        if name == VM_QUI_LEVE:
            raise OSError("bail illisible")
        return None

    return vm_ip


class LesHotesSsh(unittest.TestCase):
    def test_un_ssh_config_absent_est_une_liste_vide_pas_une_panne(self):
        """Le fichier n'existe pas sur beaucoup de machines : c'est un FAIT,
        et le menu doit s'ouvrir quand même."""
        vide = discover.ssh_hosts(list_aliases=lambda: [], resolve=resolveur())
        self.assertEqual([], vide)

        def leve():
            raise OSError("~/.ssh/config")

        self.assertEqual(
            [], discover.ssh_hosts(list_aliases=leve, resolve=resolveur())
        )

    def test_une_ligne_host_multi_noms_rend_chaque_nom(self):
        """Une ligne « Host a b » déclare DEUX machines : les rendre comme une
        seule clé portant un espace est la faute d'un analyseur du venv que
        le dépôt n'utilise pas."""
        cibles = discover.ssh_hosts(
            list_aliases=alias_naifs(), resolve=resolveur()
        )
        self.assertTrue(cibles, "aucune cible : le jeu d'essai ne colle plus")
        par_alias = {alias: (host, port) for alias, host, port in cibles}
        self.assertIn("azurite.invalid", par_alias)
        self.assertIn("obsidienne.invalid", par_alias)
        self.assertEqual(("192.0.2.21", 2222), par_alias["azurite.invalid"])
        self.assertEqual(("192.0.2.21", 2222), par_alias["obsidienne.invalid"])

    def test_un_joker_et_un_motif_nie_ne_sont_pas_des_machines(self):
        alias = alias_naifs()()
        self.assertIn("*", alias, "le jeu d'essai doit porter le joker")
        self.assertIn("!malachite.invalid", alias, "et le motif nié aussi")
        cibles = discover.ssh_hosts(
            list_aliases=alias_naifs(), resolve=resolveur()
        )
        self.assertTrue(cibles, "aucune cible")
        for nom, host, _port in cibles:
            self.assertNotIn("*", nom)
            self.assertNotIn("?", nom)
            self.assertFalse(nom.startswith("!"))
            self.assertNotIn("malachite", nom)
            self.assertNotIn("malachite", host)

    def test_une_entree_sans_hostname_garde_l_alias_pour_cible(self):
        """`ssh -G` remplit l'hôte avec l'alias quand aucun `HostName` n'est
        déclaré : l'alias EST une cible sondable, que le DNS ou le fichier
        des hôtes résout."""
        cibles = discover.ssh_hosts(
            list_aliases=alias_naifs(), resolve=resolveur()
        )
        par_alias = {alias: (host, port) for alias, host, port in cibles}
        self.assertIn("basalte.invalid", par_alias)
        self.assertEqual(("basalte.invalid", 22), par_alias["basalte.invalid"])

    def test_un_resolveur_muet_garde_l_alias_avec_le_port_de_ssh(self):
        """Un résolveur qui rend {} n'a rien appris ; le repli vaut ce que
        `ssh` lui-même annonce, donc il n'invente rien."""
        cibles = discover.ssh_hosts(
            list_aliases=lambda: ["basalte.invalid"],
            resolve=lambda alias: {},
        )
        self.assertEqual([("basalte.invalid", "basalte.invalid", 22)], cibles)

    def test_un_resolveur_qui_leve_ne_perd_pas_les_autres_alias(self):
        def resolve(alias):
            if alias == "azurite.invalid":
                raise OSError("ssh absent")
            return {"hostname": alias, "port": "22"}

        cibles = discover.ssh_hosts(
            list_aliases=lambda: ["azurite.invalid", "basalte.invalid"],
            resolve=resolve,
        )
        self.assertEqual(
            ["azurite.invalid", "basalte.invalid"],
            [alias for alias, _h, _p in cibles],
        )


class LesTunnelsSsh(unittest.TestCase):
    """La source qui sonde ICI ce qui répond LÀ-BAS.

    Un service derrière un pare-feu qui ne laisse passer que le port de ssh
    n'ouvre aucun port vu du dehors : sonder le nom d'hôte de son alias
    annonce vide un hôte qui sert des modèles. C'est l'extrémité locale de sa
    redirection qui répond, et elle ne se devine pas — aucune liste de ports
    ne contient un numéro que l'utilisateur a choisi.

    La régression visée porte un nom : le résolveur qui ÉCRASE. Le résolveur
    d'une valeur par mot-clé convient à `identityfile`, dont la première
    entrée est celle qui compte, et il réduit trois tunnels à un seul. Rien
    ne tombe en rouge quand cela arrive — deux services sur trois
    disparaissent, en silence, et le menu annonce une découverte réussie.
    """

    def test_chaque_occurrence_d_un_mot_cle_repete_rend_un_tunnel(self):
        """Le cœur de la source : `localforward` paraît une fois par tunnel,
        et les quatre sondables sont rendus, pas seulement le premier."""
        tunnels = discover.ssh_forwards(
            list_aliases=alias_naifs(),
            resolve_all=resolveur_complet(),
        )
        self.assertEqual(
            [
                ("azurite.invalid", 1234),
                ("azurite.invalid", 2345),
                ("azurite.invalid", 3456),
                ("azurite.invalid", 4567),
                ("azurite.invalid", 6001),
                ("azurite.invalid", 6002),
                ("azurite.invalid", 6003),
                ("basalte.invalid", 5678),
            ],
            [(one.alias, one.local_port) for one in tunnels],
        )

    def test_une_liaison_sans_adresse_se_sonde_par_sa_boucle_locale(self):
        """Un port nu, les jokers v4 et le nom « localhost » désignent cette
        machine sans nommer une de ses adresses : les rendre tels quels
        donnerait des cibles que rien ne résout.

        La FAMILLE décide laquelle des deux boucles locales, et c'est le
        point. Le joker v6 « :: » n'est pas le pendant de « * » : ssh pose
        `IPV6_V6ONLY` sur l'écouteur qu'il ouvre, donc le port existe sur
        « ::1 » et pas sur « 127.0.0.1 ». Replier l'un sur l'autre lit un
        tunnel MONTÉ comme absent, propose de le remonter, et ce montage
        échoue sur « Address already in use » — l'utilisateur n'a alors aucune
        issue.
        """
        tunnels = discover.ssh_forwards(
            list_aliases=alias_naifs(),
            resolve_all=resolveur_complet(),
        )
        par_port = {one.local_port: one.bind for one in tunnels}
        self.assertTrue(
            par_port, "aucun tunnel : le jeu d'essai ne colle plus"
        )
        for port in (1234, 3456, 4567, 6001, 5678):
            self.assertEqual("127.0.0.1", par_port[port], f"port {port}")
        for port in (6002, 6003):
            self.assertEqual("::1", par_port[port], f"port {port}")

    def test_une_liaison_qui_nomme_une_adresse_est_rendue_telle_quelle(self):
        """ssh écoute là et nulle part ailleurs : la ramener à la boucle
        locale sonderait une adresse où rien n'est lié."""
        table = {
            "basalte.invalid": {
                "localforward": ["[192.0.2.21]:7001 [192.0.2.31]:80"]
            }
        }
        tunnels = discover.ssh_forwards(
            list_aliases=alias_naifs(),
            resolve_all=resolveur_complet(table=table),
        )
        self.assertEqual(["192.0.2.21"], [one.bind for one in tunnels])

    def test_un_tunnel_sur_socket_unix_n_a_aucun_port_a_frapper(self):
        """Il lie un chemin, pas un port. Le retenir rendrait une cible dont
        le port est le nom d'un fichier."""
        tunnels = discover.ssh_forwards(
            list_aliases=alias_naifs(),
            resolve_all=resolveur_complet(),
        )
        # La ligne du socket est la SEULE du jeu d'essai à viser le port 22
        # de la destination : son absence prouve qu'elle n'a rien produit,
        # là où une assertion sur un port local nul porterait sur une valeur
        # que `_port` ne peut de toute façon pas rendre.
        self.assertNotIn(
            ("192.0.2.31", 22), [(one.host, one.port) for one in tunnels]
        )
        self.assertNotIn(
            "/run/essai.sock",
            [one.host for one in tunnels] + [one.bind for one in tunnels],
        )

    def test_un_port_local_declare_deux_fois_ne_rend_qu_une_cible(self):
        """Un seul écouteur peut lier un port : le second `ssh` échouerait.
        Deux cibles identiques feraient compter deux fois le même service."""
        tunnels = discover.ssh_forwards(
            list_aliases=alias_naifs(),
            resolve_all=resolveur_complet(),
        )
        couples = [(one.bind, one.local_port) for one in tunnels]
        self.assertEqual(len(couples), len(set(couples)))

    def test_la_destination_ipv6_garde_ses_deux_points(self):
        """La coupe se fait au DERNIER deux-points. Couper au premier
        rendrait une adresse tronquée à son premier groupe."""
        tunnels = discover.ssh_forwards(
            list_aliases=alias_naifs(),
            resolve_all=resolveur_complet(),
        )
        lointain = [one for one in tunnels if one.local_port == 4567]
        self.assertEqual(1, len(lointain))
        self.assertEqual("2001:db8::1", lointain[0].host)
        self.assertEqual(9000, lointain[0].port)

    def test_un_joker_et_un_motif_nie_ne_declarent_aucun_tunnel(self):
        """Un joker est une règle et un motif nié retire un nom : ni l'un ni
        l'autre ne désigne une machine dont on monterait les tunnels."""
        appels = []
        discover.ssh_forwards(
            list_aliases=alias_naifs(),
            resolve_all=resolveur_complet(appels=appels),
        )
        self.assertNotIn("*", appels)
        self.assertNotIn("!malachite.invalid", appels)

    def test_un_resolveur_qui_leve_ne_perd_pas_les_autres_alias(self):
        """Une entrée illisible ne fait pas disparaître celles d'après."""

        def resolve_all(alias):
            if alias == "azurite.invalid":
                raise OSError("ssh absent")
            return {
                cle: list(val) for cle, val in FORWARDS.get(alias, {}).items()
            }

        tunnels = discover.ssh_forwards(
            list_aliases=alias_naifs(), resolve_all=resolve_all
        )
        self.assertEqual(["basalte.invalid"], [one.alias for one in tunnels])

    def test_un_resolveur_qui_rend_autre_chose_qu_un_dict_ne_leve_pas(self):
        """Un résolveur injecté rend ce qu'il veut ; aucun type inattendu
        n'est une raison d'empêcher le menu de s'ouvrir."""
        for retour in (None, [], "localforward 22 [x]:22", 7):
            with self.subTest(retour=retour):
                self.assertEqual(
                    [],
                    discover.ssh_forwards(
                        list_aliases=alias_naifs(),
                        resolve_all=lambda _a, r=retour: r,
                    ),
                )

    def test_une_valeur_mal_formee_est_ecartee_seule(self):
        """Une ligne abîmée ne fait pas tomber les voisines de son alias."""
        table = {
            "basalte.invalid": {
                "localforward": [
                    "pas-un-port [192.0.2.31]:80",
                    "99999 [192.0.2.31]:80",
                    "0 [192.0.2.31]:80",
                    "",
                    "1 2 3",
                    "7000 [192.0.2.31]:80",
                ]
            }
        }
        tunnels = discover.ssh_forwards(
            list_aliases=alias_naifs(),
            resolve_all=resolveur_complet(table=table),
        )
        self.assertEqual([7000], [one.local_port for one in tunnels])

    def test_sans_injection_la_source_est_vide_et_ne_leve_pas(self):
        """Une source qu'on n'a pas branchée n'a rien à dire. Et une demi-
        injection n'appelle pas même le connecteur qu'elle a reçu."""
        appels = []
        self.assertEqual([], discover.ssh_forwards())
        self.assertEqual([], discover.ssh_forwards(list_aliases=alias_naifs()))
        self.assertEqual(
            [],
            discover.ssh_forwards(
                resolve_all=resolveur_complet(appels=appels)
            ),
        )
        self.assertEqual([], appels)

    def test_un_enumerateur_qui_leve_est_une_source_vide(self):
        """Un fichier absent rend déjà [] chez l'énumérateur du dépôt ; un
        énumérateur injecté lève ce qu'il veut, et c'est la même chose."""

        def lister():
            raise OSError("~/.ssh/config illisible")

        self.assertEqual(
            [],
            discover.ssh_forwards(
                list_aliases=lister, resolve_all=resolveur_complet()
            ),
        )


class LesVmQemu(unittest.TestCase):
    def test_zero_domaine_libvirt_est_une_source_vide(self):
        """« libvirt répond, aucune VM définie » est un FAIT : le résolveur
        n'est pas même appelé."""
        appels = []
        self.assertEqual(
            [],
            discover.qemu_hosts(
                list_domains=domaines([]), vm_ip=adresse_de_vm(appels)
            ),
        )
        self.assertEqual([], appels)

    def test_une_vm_sans_ip_est_listee_inconnue_pas_ecartee(self):
        """Elle est définie et peut être démarrée : la faire disparaître de
        la liste ne le dirait pas."""
        appels = []
        trouves = discover.qemu_hosts(
            list_domains=domaines([VM_AVEC_IP, VM_SANS_IP]),
            vm_ip=adresse_de_vm(appels),
        )
        self.assertEqual([(VM_AVEC_IP, IP_DE_VM), (VM_SANS_IP, None)], trouves)
        self.assertEqual([VM_AVEC_IP, VM_SANS_IP], appels)

    def test_une_resolution_qui_leve_garde_la_vm_dans_la_liste(self):
        trouves = discover.qemu_hosts(
            list_domains=domaines([VM_QUI_LEVE, VM_AVEC_IP]),
            vm_ip=adresse_de_vm(),
        )
        self.assertEqual(
            [(VM_QUI_LEVE, None), (VM_AVEC_IP, IP_DE_VM)], trouves
        )

    def test_un_virsh_qui_leve_est_une_source_vide(self):
        def leve():
            raise OSError("virsh absent")

        self.assertEqual(
            [], discover.qemu_hosts(list_domains=leve, vm_ip=adresse_de_vm())
        )

    def test_sans_resolveur_les_domaines_sortent_sans_adresse(self):
        trouves = discover.qemu_hosts(list_domains=domaines([VM_AVEC_IP]))
        self.assertEqual([(VM_AVEC_IP, None)], trouves)


class LeResolveurPatient(unittest.TestCase):
    def test_aucune_source_n_utilise_le_resolveur_patient(self):
        """Le nom du résolveur bon marché a celui du patient pour PRÉFIXE :
        c'est la frontière de mot qui les sépare, et une recherche de
        sous-chaîne interdirait aussi de nommer le bon."""
        source = _source()
        self.assertIsNone(
            re.search(r"\b_qemu_vm_ip\b", source),
            "le résolveur patient est nommé : il gèle le menu par VM",
        )
        self.assertNotIn("_qemu_resolve_ips", source)
        self.assertIn(
            "_qemu_vm_ip_now",
            source,
            "le résolveur bon marché doit être nommé, pas seulement décrit",
        )

    def test_le_resolveur_injecte_est_celui_qui_est_appele(self):
        appels = []
        discover.qemu_hosts(
            list_domains=domaines([VM_AVEC_IP, VM_SANS_IP]),
            vm_ip=adresse_de_vm(appels),
        )
        self.assertEqual([VM_AVEC_IP, VM_SANS_IP], appels)


class SansInjection(unittest.TestCase):
    def test_une_source_sans_injection_rend_une_liste_vide(self):
        """Une source qu'on n'a pas branchée n'a rien à dire ; ce n'est pas
        une panne du menu, et ce n'est pas une raison de lever."""
        self.assertEqual([], discover.qemu_hosts())
        self.assertEqual([], discover.ssh_hosts())

    def test_une_moitie_d_injection_ne_suffit_pas_a_ssh(self):
        """Sans résolveur, l'hôte et le port ne se sauraient pas, et les
        inventer serait une devinette là où `ssh -G` a la réponse."""
        appels = []
        self.assertEqual([], discover.ssh_hosts(list_aliases=alias_naifs()))
        self.assertEqual(
            [], discover.ssh_hosts(resolve=resolveur(appels=appels))
        )
        self.assertEqual([], appels)


class LaFrontiere(unittest.TestCase):
    def test_aucun_analyseur_de_config_ssh_n_est_reecrit_ici(self):
        """`ssh -G` a raison sur les `Include`, les `Match`, l'héritage des
        jokers et ses propres défauts ; recopier son travail est ce que
        l'injection évite.

        L'affirmation porte sur ce que le module NE FAIT PAS lui-même : il ne
        lit pas le fichier de configuration et n'appelle pas `ssh -G`. La
        présence du mot « ssh » ne dit rien à ce sujet — `ssh_runner` lance
        `ip` À TRAVERS ssh, ce qui délègue la configuration à ssh au lieu de
        la relire, donc respecte la règle en la nommant.
        """
        source = _source()
        self.assertNotIn("sshconf", source, "sshconf importé ici")
        # Le drapeau comme ARGUMENT, et non le nom de la commande dans une
        # docstring : les docstrings nomment `ssh -G` exprès, pour dire à qui
        # le travail est délégué.
        self.assertTrue(
            '"-G"' not in source and "'-G'" not in source,
            "« -G » passé en argument : la résolution est réécrite ici",
        )


def _source():
    """Le texte du module de découverte, non vide."""
    with open(discover.__file__, encoding="utf-8") as fh:
        texte = fh.read()
    if not re.search(r"def ssh_hosts\(", texte):
        raise AssertionError("source illisible : le module a changé de forme")
    return texte


class ReseauxDistants(unittest.TestCase):
    """Les réseaux lus sur une AUTRE machine, par le même analyseur.

    Quand le CLI tourne dans une machine virtuelle, les réseaux qu'il porte
    sont ceux de l'hyperviseur et le parc réel est hors-lien. La machine du
    dessus porte les bons préfixes ; `remote_networks` les lit chez elle en
    passant un exécuteur SSH à `local_networks`, ce qui réutilise la lecture
    des adresses, la détection des ponts et l'ordre par route par défaut sans
    en dupliquer une ligne.
    """

    ADRESSES = (
        "1: lo    inet 127.0.0.1/8 scope host lo\n"
        "2: lien0 inet 198.51.100.9/24 scope global lien0\n"
        "3: pont0 inet 192.0.2.1/24 scope global pont0\n"
    )
    LIENS = (
        "1: lo: <LOOPBACK> mtu 65536 qdisc noqueue state UNKNOWN\n"
        "2: lien0: <BROADCAST> mtu 1500 qdisc fq_codel state UP\n"
        "3: pont0: <BROADCAST> mtu 1500 qdisc noqueue state UP "
        "link/ether aa:bb:cc:dd:ee:07 bridge_id 8000.0 bridge\n"
    )
    DEFAUT = "default via 198.51.100.1 dev lien0 proto dhcp\n"

    def _executeur(self, journal):
        """Un exécuteur qui rend ce qu'annoncerait l'hôte distant."""

        def executer(argv):
            journal.append(tuple(argv))
            if "addr" in argv:
                return self.ADRESSES
            if "link" in argv:
                return self.LIENS
            if "route" in argv:
                return self.DEFAUT
            return ""

        return executer

    def test_les_reseaux_du_distant_sont_lus_et_le_pont_marque(self):
        journal = []
        reseaux = discover.remote_networks(
            "machine.invalid", run=self._executeur(journal)
        )
        self.assertTrue(journal, "aucune commande lancée sur l'hôte")
        self.assertEqual(
            [(r.cidr, r.name, r.is_bridge) for r in reseaux],
            [
                ("198.51.100.0/24", "lien0", False),
                ("192.0.2.0/24", "pont0", True),
            ],
        )

    def test_la_boucle_locale_du_distant_est_ecartee(self):
        reseaux = discover.remote_networks(
            "machine.invalid", run=self._executeur([])
        )
        self.assertTrue(reseaux)
        for reseau in reseaux:
            self.assertNotIn("127.0.0", reseau.cidr)

    def test_un_hote_muet_rend_une_liste_vide(self):
        reseaux = discover.remote_networks(
            "machine.invalid", run=lambda argv: ""
        )
        self.assertEqual(reseaux, [])

    def test_un_executeur_qui_leve_rend_une_liste_vide(self):
        def executer(argv):
            raise OSError("hôte injoignable")

        self.assertEqual(
            discover.remote_networks("machine.invalid", run=executer), []
        )

    def test_l_executeur_ssh_refuse_toute_invite_et_cite_ses_arguments(self):
        """`BatchMode=yes` empêche une demande de mot de passe de tenir le
        menu sur une question que personne ne voit venir, et la commande
        distante est relue par un interpréteur là-bas."""
        source = _source()
        self.assertIn("BatchMode=yes", source, "une invite pourrait bloquer")
        self.assertIn("shlex.quote", source, "arguments non cités")


if __name__ == "__main__":
    unittest.main()
