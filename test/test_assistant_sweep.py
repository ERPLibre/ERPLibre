#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le balayage : ce qu'on planifie, ce qu'on frappe, et rien d'autre.

Trois décisions sont défendues ici, et chacune casse en silence.

**Le préfixe se lit, il ne se devine pas.** Une machine porte volontiers deux
/24 — un sur son interface physique, un sur un pont de virtualisation où elle
est la passerelle — et « le /24 local » n'a alors pas de sens. Une régression
qui choisirait pour l'utilisateur balaierait le mauvais réseau sans rien
lever, et un réseau plus large qu'un /24 doit être REFUSÉ plutôt que
rétréci : rétrécir présenterait une hypothèse comme une lecture.

**Le balayage ne touche que ce qu'on lui a désigné.** Les adresses de la
machine elle-même sont écartées du plan, sans quoi le balayage se reconnaît
lui-même et offre la passerelle d'un pont comme un serveur découvert. Et la
table de voisinage ne rend que ce qui a RÉPONDU : une entrée sans adresse
matérielle dit qu'on a demandé sans obtenir.

**Le battement de cœur est testable, et c'est le point.** L'idiome de
progression du dépôt code son intervalle en dur, et c'est exactement pourquoi
cette branche-là n'a aucun test. Ici l'intervalle et l'horloge sont injectés.

Aucun paquet n'est émis : le connecteur est injecté partout, `ip` est
remplacé par du texte, et le cas du /24 complet remplace en plus
`socket.create_connection` par une levée, pour qu'un chemin oublié tombe en
rouge au lieu de parler au réseau.

Les adresses sont celles des blocs réservés à la documentation, et les noms
d'interface sont inventés — `.claude/rules/04-code-conventions.md` exige que
la valeur illustrant un interdit s'invente, et « lien0 » comme « pont0 » ne
paraissent nulle part ailleurs dans le dépôt.
"""

import os
import re
import sys
import time
import unittest
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.todo.assistant import discover  # noqa: E402
from script.todo.assistant import fingerprint  # noqa: E402

# Deux réseaux des blocs réservés à la documentation : ils ne peuvent
# désigner aucune machine réelle.
LAN = "192.0.2.0/24"
PONT = "198.51.100.0/24"

# Ce que « ip -o -4 addr show » annonce : la boucle locale, une interface
# ordinaire, un pont. La forme « -o » met l'interface et son préfixe sur la
# même ligne, ce qui est ce qui les rend rattachables.
ADDR = (
    "1: lo    inet 127.0.0.1/8 scope host lo\\       valid_lft forever\n"
    "2: lien0    inet 192.0.2.10/24 metric 1024 brd 192.0.2.255 scope"
    " global dynamic lien0\\       valid_lft 2968sec\n"
    "3: pont0    inet 198.51.100.1/24 brd 198.51.100.255 scope global"
    " pont0\\       valid_lft forever\n"
)

# Les mêmes interfaces, annoncées dans l'ordre inverse : l'ordre des rangs ne
# doit pas décider laquelle ouvre la liste.
ADDR_INVERSE = "\n".join(
    [ADDR.splitlines()[0], ADDR.splitlines()[2], ADDR.splitlines()[1]]
)

# Ce que « ip -d -o link show » annonce. « bridge » nu est le TYPE, et lui
# seul nomme un pont ; « bridge_slave » est l'attribut que porte un PORT de
# pont, et « bridge_id » un attribut du pont lui-même. Les trois paraissent
# ici pour que la frontière de mot du motif soit ce qui les sépare.
LINK = (
    "1: lo: <LOOPBACK,UP,LOWER_UP> mtu 65536 state UNKNOWN"
    "\\    link/loopback 00:00:00:00:00:00 addrgenmode eui64\n"
    "2: lien0: <BROADCAST,MULTICAST,UP,LOWER_UP> mtu 1500 state UP"
    "\\    link/ether aa:bb:cc:dd:ee:01 promiscuity 0"
    " bridge_slave state forwarding\n"
    "3: pont0: <NO-CARRIER,BROADCAST,MULTICAST,UP> mtu 1500 state DOWN"
    "\\    link/ether aa:bb:cc:dd:ee:02 promiscuity 0"
    "\\    bridge forward_delay 200 bridge_id 8000.aa:bb:cc:dd:ee:02\n"
)

# La route par défaut désigne l'interface qui sort de la machine. Le noyau a
# déjà tranché, et c'est cette réponse-là qui ouvre la liste.
ROUTE = (
    "default via 192.0.2.1 dev lien0 proto dhcp src 192.0.2.10 metric 1024\n"
)

# Une table de voisinage. Les deux premières ont répondu — elles portent une
# adresse matérielle ; les deux suivantes ont été sollicitées sans répondre ;
# la dernière répète la première sur une autre interface.
NEIGH = (
    "192.0.2.11 dev lien0 lladdr aa:bb:cc:dd:ee:11 REACHABLE\n"
    "192.0.2.12 dev lien0 lladdr aa:bb:cc:dd:ee:12 STALE\n"
    "192.0.2.13 dev lien0  FAILED\n"
    "192.0.2.14 dev lien0  INCOMPLETE\n"
    "192.0.2.11 dev pont0 lladdr aa:bb:cc:dd:ee:11 STALE\n"
)


def faux_ip(addr=ADDR, link=LINK, route=ROUTE):
    """Un exécuteur de « ip » qui rend du texte choisi, sans sous-processus.

    Se branche sur `local_networks(run=…)` et distingue les trois questions
    par leur verbe, comme la commande elle-même.
    """

    def run(argv):
        if "addr" in argv:
            return addr
        if "link" in argv:
            return link
        if "route" in argv:
            return route
        return ""

    return run


class Horloge:
    """Une horloge injectée qui avance d'une seconde par lecture.

    Une durée rendue par elle vaut au moins une seconde, là où le balayage
    d'un test dure quelques centièmes : une durée supérieure à la seconde
    PROUVE donc que c'est bien elle qui a été lue, et non l'horloge du
    système.
    """

    def __init__(self):
        self.lectures = 0

    def __call__(self):
        self.lectures += 1
        return 1000.0 + self.lectures


class Compteur:
    """Un connecteur injecté : rend vrai sur les couples ouverts, et compte
    ses appels."""

    def __init__(self, ouverts):
        self.ouverts = set(ouverts)
        self.appels = 0

    def __call__(self, host, port, timeout):
        self.appels += 1
        return (host, port) in self.ouverts


class LesReseauxLocaux(unittest.TestCase):
    def test_les_deux_slash24_locaux_sont_offerts(self):
        reseaux = discover.local_networks(run=faux_ip())
        self.assertTrue(reseaux, "aucun réseau lu : le motif ne colle plus")
        self.assertEqual([LAN, PONT], [item.cidr for item in reseaux])
        self.assertEqual(["lien0", "pont0"], [i.name for i in reseaux])

    def test_la_boucle_locale_n_est_pas_un_reseau_a_balayer(self):
        """Elle se sonde en quelques millisecondes, sans balayage : l'offrir
        ferait payer 254 adresses pour une seule."""
        reseaux = discover.local_networks(run=faux_ip())
        self.assertTrue(reseaux, "aucun réseau lu")
        for item in reseaux:
            self.assertNotIn("127.", item.cidr)
            self.assertNotEqual("lo", item.name)

    def test_le_pont_libvirt_est_signale_comme_tel(self):
        """Le type « bridge » nomme un pont ; les attributs « bridge_slave »
        et « bridge_id » n'en nomment pas un, et la ligne de l'interface
        ordinaire porte le premier pour le prouver."""
        par_nom = {i.name: i for i in discover.local_networks(run=faux_ip())}
        self.assertTrue(par_nom, "aucune interface lue")
        self.assertTrue(par_nom["pont0"].is_bridge)
        self.assertFalse(par_nom["lien0"].is_bridge)

    def test_l_interface_de_la_route_par_defaut_ouvre_la_liste(self):
        reseaux = discover.local_networks(
            run=faux_ip(addr=ADDR_INVERSE, route=ROUTE)
        )
        self.assertTrue(reseaux, "aucun réseau lu")
        self.assertEqual("lien0", reseaux[0].name)
        self.assertEqual({"lien0", "pont0"}, {i.name for i in reseaux})

    def test_un_prefixe_plus_large_est_rendu_tel_quel_pas_retreci(self):
        """Rétrécir en silence présenterait une hypothèse comme une lecture :
        le refus appartient au planificateur, qui peut le DIRE."""
        large = "2: lien0    inet 192.0.2.10/16 scope global lien0\n"
        reseaux = discover.local_networks(run=faux_ip(addr=large))
        self.assertEqual(["192.0.0.0/16"], [i.cidr for i in reseaux])
        self.assertEqual([], discover.plan_sweep(reseaux[0].cidr))

    def test_un_ip_absent_est_une_liste_vide_pas_une_panne(self):
        def leve(argv):
            raise FileNotFoundError(argv[0])

        self.assertEqual([], discover.local_networks(run=leve))
        self.assertEqual([], discover.local_networks(run=lambda argv: ""))


class LePlanDeBalayage(unittest.TestCase):
    def test_plus_large_qu_un_slash24_est_refuse(self):
        for cidr in ("192.0.2.0/23", "192.0.2.0/16", "10.0.0.0/8", "::/64"):
            self.assertEqual([], discover.plan_sweep(cidr), cidr)
        self.assertEqual(254, discover.MAX_HOSTS)

    def test_un_slash24_donne_tous_ses_hotes_fois_tous_les_ports(self):
        jobs = discover.plan_sweep(LAN)
        attendu = discover.MAX_HOSTS * len(fingerprint.PORTS)
        self.assertEqual(attendu, len(jobs))
        self.assertEqual(("192.0.2.1", fingerprint.PORTS[0]), jobs[0])

    def test_les_ports_par_defaut_sont_ceux_de_l_echelle(self):
        jobs = discover.plan_sweep("192.0.2.7/32")
        self.assertEqual(
            [(str("192.0.2.7"), port) for port in fingerprint.PORTS], jobs
        )

    def test_les_adresses_de_l_hote_sont_ecartees(self):
        """Sans ce retrait, un balayage se reconnaît lui-même et offre la
        passerelle d'un pont comme un serveur découvert."""
        siennes = ("192.0.2.10", "192.0.2.1")
        jobs = discover.plan_sweep(LAN, (11434,), skip=siennes)
        self.assertTrue(jobs, "plan vide : le retrait a tout emporté")
        self.assertEqual(discover.MAX_HOSTS - 2, len(jobs))
        for adresse in siennes:
            self.assertNotIn((adresse, 11434), jobs)

    def test_un_cidr_illisible_est_une_liste_vide(self):
        for cidre in ("", "   ", "pas-un-cidr", "192.0.2.0/33", None, 42):
            self.assertEqual([], discover.plan_sweep(cidre), repr(cidre))

    def test_un_ensemble_de_ports_vide_ne_planifie_rien(self):
        self.assertEqual([], discover.plan_sweep(LAN, ()))


class LaTableDeVoisinage(unittest.TestCase):
    def test_la_table_de_voisinage_ne_rend_que_ce_qui_a_parle(self):
        adresses = discover.neigh_hosts(NEIGH)
        self.assertEqual(["192.0.2.11", "192.0.2.12"], adresses)

    def test_une_table_vide_ou_abimee_ne_leve_pas(self):
        for texte in ("", None, "n'importe quoi\nlladdr sans adresse\n"):
            self.assertEqual([], discover.neigh_hosts(texte), repr(texte))


class LaFrappe(unittest.TestCase):
    def test_un_slash24_complet_n_emet_aucun_paquet(self):
        """Le connecteur injecté est le seul chemin : une socket ouverte par
        un chemin oublié tombe en rouge au lieu de parler au réseau."""
        jobs = discover.plan_sweep(LAN)
        ouverts = {("192.0.2.7", 11434), ("192.0.2.42", 8080)}
        connect = Compteur(ouverts)
        with patch(
            "script.todo.assistant.discover.socket.create_connection",
            side_effect=AssertionError("aucun paquet ne doit sortir"),
        ):
            trouves = discover.sweep(jobs, connect=connect)
        self.assertEqual(len(jobs), connect.appels)
        self.assertEqual(ouverts, set(trouves))

    def test_le_battement_part_sur_l_horloge_injectee(self):
        horloge = Horloge()
        evenements = []

        def lent(host, port, timeout):
            time.sleep(0.06)
            return False

        discover.sweep(
            [("192.0.2.7", 11434)],
            connect=lent,
            heartbeat_sec=0.01,
            now=horloge,
            on_event=evenements.append,
        )
        battements = [e for e in evenements if e[0] == "heartbeat"]
        self.assertTrue(battements, "aucun battement : la branche est muette")
        for _nom, faits, total, secondes in battements:
            self.assertLessEqual(faits, total)
            self.assertGreaterEqual(secondes, 1.0)

    def test_un_hote_bloque_n_arrete_pas_les_autres(self):
        bloque = ("192.0.2.99", 11434)
        ouverts = {("192.0.2.7", 11434), ("192.0.2.8", 1234)}

        def connect(host, port, timeout):
            if (host, port) == bloque:
                time.sleep(0.05)
                return False
            return (host, port) in ouverts

        jobs = sorted(ouverts | {bloque, ("192.0.2.9", 5001)})
        trouves = discover.sweep(
            jobs, connect=connect, heartbeat_sec=0.01, timeout=0.01
        )
        self.assertEqual(ouverts, set(trouves))

    def test_un_connecteur_qui_leve_compte_pour_un_port_ferme(self):
        def connect(host, port, timeout):
            if host == "192.0.2.99":
                raise OSError("pile réseau à bout")
            return port == 11434

        jobs = [("192.0.2.99", 11434), ("192.0.2.7", 11434)]
        self.assertEqual(
            [("192.0.2.7", 11434)], discover.sweep(jobs, connect=connect)
        )

    def test_les_evenements_rendent_les_memes_couples_que_le_retour(self):
        """L'appelant peut affirmer sur des DONNÉES et non sur du texte
        capté : c'est ce qui rend l'affichage remplaçable."""
        jobs = discover.plan_sweep("192.0.2.0/24", (11434, 1234))
        ouverts = {("192.0.2.7", 11434), ("192.0.2.9", 1234)}
        evenements = []
        trouves = discover.sweep(
            jobs,
            connect=Compteur(ouverts),
            on_event=evenements.append,
        )
        dits = [(e[1], e[2]) for e in evenements if e[0] == "hit"]
        self.assertTrue(dits, "aucune trouvaille annoncée")
        self.assertEqual(sorted(trouves), sorted(dits))
        self.assertEqual(
            [("done", len(trouves), len(jobs))],
            [e[:3] for e in evenements if e[0] == "done"],
        )

    def test_un_plan_vide_se_termine_sans_piscine(self):
        evenements = []
        self.assertEqual([], discover.sweep([], on_event=evenements.append))
        self.assertEqual(["done"], [e[0] for e in evenements])


class LesSourcesInjectees(unittest.TestCase):
    def test_la_piscine_est_dimensionnee_par_vagues_pas_par_coeurs(self):
        """Ces fils attendent le réseau : un compte de cœurs à deux chiffres
        multiplierait par quinze la durée d'un /24."""
        source = _source()
        self.assertIn("min(len(jobs), workers)", source)
        self.assertNotIn("cpu_count", source)

    def test_la_sonde_est_une_connexion_jamais_un_sous_processus_ping(self):
        """Un `ping` par adresse coûterait un millier de fork+exec sur un
        /24, là où une socket n'en coûte aucun."""
        source = _source()
        self.assertIn("socket.create_connection", source)
        self.assertNotIn('"ping"', source)


class LaFrontiere(unittest.TestCase):
    def test_aucun_asyncio_du_depot_n_est_utilise(self):
        """`AsyncioPool` enveloppe des sous-processus et non des sockets, et
        passe à `asyncio.wait` un argument retiré de Python 3.10."""
        self.assertNotIn("lib_asyncio", _source())


def _source():
    """Le texte du module de découverte, non vide."""
    with open(discover.__file__, encoding="utf-8") as fh:
        texte = fh.read()
    if not re.search(r"def sweep\(", texte):
        raise AssertionError("source illisible : le module a changé de forme")
    return texte


if __name__ == "__main__":
    unittest.main()
