#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le pilote L2TP/IPsec écrit, et ce qu'il n'écrit JAMAIS.

Le test central de ce fichier est `test_no_secret_reaches_a_command_line` :
il rejoue tout le plan de montage à blanc et vérifie qu'aucun secret n'a
atterri dans une ligne de commande. `/proc/<pid>/cmdline` est lisible par
tout utilisateur de la machine ; un secret en argument est un secret public
pendant toute la durée de la commande.

Aucun root, aucun serveur en face : le `Runner` à blanc n'exécute rien, il
enregistre. Le serveur du profil est 127.0.0.1 pour qu'aucun test ne dépende
d'une résolution de nom.
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.vpn import profiles
from script.vpn.drivers import base
from script.vpn.drivers.l2tp_ipsec import (
    APPARMOR_PROFILE,
    L2tpIpsecDriver,
)
from script.vpn.runner import Runner, replace_block
from script.vpn.vault import redact

PSK = "cl3-Pr3-P4rt4g33!"
PPP_PASSWORD = "m0tD3P4ss3-PPP"
SECRETS = {"psk": PSK, "password": PPP_PASSWORD}

PROFILE = profiles.validate(
    {
        "name": "acme",
        "driver": "l2tp_ipsec",
        "server": "127.0.0.1",
        "ppp_user": "ACME\\user",
        "routes": ["10.20.0.0/16"],
        "probe": "10.20.0.1",
    }
)


def _driver(**overrides):
    profile = dict(PROFILE)
    profile.update(overrides)
    return L2tpIpsecDriver(profile, SECRETS)


def _dry_runner(driver):
    return Runner(
        dry_run=True,
        quiet=True,
        redactor=lambda text: redact(text, driver.secret_values()),
    )


class RenderedFiles(unittest.TestCase):
    def test_ipsec_conn_is_transport_mode(self):
        """Mode TRANSPORT, pas tunnel. En mode tunnel, la SA monte et
        aucune interface PPP n'apparaît jamais."""
        body = _driver().ipsec_conn_body()
        self.assertIn("type=transport", body)
        self.assertNotIn("type=tunnel", body)

    def test_ipsec_conn_accepts_any_local_port(self):
        """`leftprotoport=17/%any` : derrière du NAT, le port source est
        réécrit et une politique clouée sur 1701 ne s'applique plus."""
        self.assertIn("leftprotoport=17/%any", _driver().ipsec_conn_body())

    def test_ipsec_conn_names_the_server_and_the_connection(self):
        body = _driver().ipsec_conn_body()
        self.assertIn("conn erplibre-acme", body)
        self.assertIn("right=127.0.0.1", body)
        self.assertIn("rightprotoport=17/1701", body)

    def test_psk_is_written_in_hexadecimal(self):
        """Le PSK part en hexadécimal : mêmes octets pour strongSwan, et
        plus aucune question d'échappement de guillemets."""
        body = _driver().ipsec_secrets_body("127.0.0.1")
        self.assertIn(f"PSK 0x{PSK.encode('utf-8').hex()}", body)
        self.assertNotIn(PSK, body)
        self.assertIn("%any 127.0.0.1 :", body)

    def test_ppp_options_escape_the_domain_backslash(self):
        """`ACME\\user` est la forme courante sur un concentrateur L2TP.
        Sans échappement, pppd envoie `ACMEuser` et le serveur refuse
        sans dire pourquoi."""
        body = _driver().ppp_options_body()
        self.assertIn(r'name "ACME\\user"', body)

    def test_ppp_refuses_no_method_and_requires_nothing(self):
        """Aucun `refuse-*`, et `noauth`.

        Mesuré sur un vrai concentrateur : il demande « <auth pap> », et un
        `refuse-pap` y répond « ConfNak <auth chap MD5> » — le serveur coupe
        alors sur « peer refused to authenticate », où le « peer » est NOUS.
        `require-mschap-v2`, symétriquement, exigerait que le SERVEUR
        s'authentifie auprès de nous : aucun sens pour un client.

        PAP est en clair sur la liaison PPP, qui voyage dans l'ESP : c'est
        IPsec qui protège l'authentification, et ce pilote ne lance jamais
        L2TP sans SA établie."""
        body = _driver().ppp_options_body()
        self.assertIn("noauth", body)
        for refuse in (
            "refuse-pap",
            "refuse-eap",
            "refuse-chap",
            "refuse-mschap",
            "require-mschap-v2",
            "require-chap",
        ):
            self.assertNotIn(refuse, body)

    def test_an_interface_without_an_address_is_a_failure(self):
        """pppd crée l'interface AVANT qu'IPCP ait négocié l'adresse.

        Lire tout de suite annonçait « ppp0 : sans adresse » sur un tunnel
        sain, et faisait chercher les DNS du pair avant que pppd les ait
        écrits. On attend donc l'adresse — et son absence au bout du délai
        est un échec, pas un détail d'affichage.

        Le mode à blanc rend la main avant cette étape : on joue donc le
        chemin réel, avec l'exécuteur bouchonné. La sonde du noyau est
        bouchonnée elle aussi : sans cela le test mesurerait l'IPsec de la
        machine qui l'exécute, et un conteneur sans XFRM le ferait échouer
        sur un plan de montage pourtant correct.
        """
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        module = "script.vpn.drivers.l2tp_ipsec"
        with patch(
            f"{module}.netlink_family_available", return_value=True
        ), patch.object(
            runner, "cmd", return_value=(0, "established successfully")
        ), patch.object(
            runner, "write", return_value=0
        ), patch.object(
            runner, "block", return_value=False
        ), patch.object(
            runner, "mkdir", return_value=0
        ), patch(
            "script.vpn.drivers.base.locate", return_value="/usr/bin/x"
        ), patch(
            f"{module}.locate", return_value=""
        ), patch(
            f"{module}.resolve", return_value="203.0.113.9"
        ), patch(
            f"{module}.ppp_interfaces", return_value=set()
        ), patch(
            f"{module}.wait_for_new_interface", return_value="ppp0"
        ), patch(
            f"{module}.wait_for_interface_address", return_value=[]
        ) as attente:
            self.assertFalse(driver.up(runner))
        attente.assert_called_once()
        self.assertTrue(
            [motif for motif in runner.failures if "adresse" in motif],
            runner.failures,
        )

    def test_xl2tpd_requires_nothing_of_the_peer(self):
        """« require chap » et « require authentication » font passer
        « require-chap » et « auth » à pppd, c'est-à-dire « que le serveur
        me prouve qui il est ». Le serveur refuse, et la liaison tombe."""
        body = _driver().xl2tpd_conf_body()
        self.assertIn("require authentication = no", body)
        self.assertIn("require chap = no", body)

    def test_xl2tpd_comments_use_a_semicolon(self):
        """L'analyseur de xl2tpd ne connaît pas « # » : un dièse en tête
        fait refuser le fichier ENTIER — « data '#…' occurs with no
        context », puis « Unable to load config file »."""
        first = _driver().xl2tpd_conf_body().splitlines()[0]
        self.assertTrue(first.startswith(";"), first)
        self.assertNotIn("#", _driver().xl2tpd_conf_body())

    def test_the_peer_identity_is_accepted_as_presented(self):
        """Une passerelle s'annonce par son IP quand `right` est un nom :
        sans `rightid=%any`, strongSwan refuse — « IDir '203.0.113.5' does
        not match to 'vpn.exemple.com' »."""
        self.assertIn("rightid=%any", _driver().ipsec_conn_body())

    def test_split_tunnel_by_default(self):
        """Pas de `defaultroute` sans demande explicite : capter tout le
        trafic couperait la session SSH en cours."""
        self.assertNotIn("defaultroute", _driver().ppp_options_body())
        self.assertIn(
            "defaultroute",
            _driver(default_route=True).ppp_options_body(),
        )

    def test_mtu_and_user_come_from_the_profile(self):
        body = _driver(mtu=1400).ppp_options_body()
        self.assertIn("mtu 1400", body)
        self.assertIn("mru 1400", body)

    def test_xl2tpd_points_at_the_tmpfs_options(self):
        body = _driver().xl2tpd_conf_body()
        self.assertIn("[lac erplibre-acme]", body)
        self.assertIn("lns = 127.0.0.1", body)
        self.assertIn(
            "pppoptfile = /dev/shm/erplibre-vpn/acme/ppp.options", body
        )


class TheOrderOfTheMountingPlan(unittest.TestCase):
    """Trois étapes dont l'ordre a été payé cher sur une vraie machine."""

    def _plan(self, apparmor=False):
        """Le plan de montage à blanc : une entrée par opération, commande
        ou chemin de fichier.

        `apparmor` fait exister le profil de charon. Il n'y en a que sur
        Debian et Ubuntu ; sans ce bouchon, le test de l'ordre des étapes
        mesure la distribution qui l'exécute et ne trouve pas une étape que
        le pilote a raison de ne pas produire ailleurs.
        """
        driver = _driver()
        runner = _dry_runner(driver)
        existe = os.path.exists

        def presente(chemin):
            if apparmor and chemin == APPARMOR_PROFILE:
                return True
            return existe(chemin)

        with patch("os.path.exists", side_effect=presente):
            driver.up(runner)
        return [op.get("cmd", "") + op.get("path", "") for op in runner.ops]

    def test_apparmor_is_allowed_before_charon_reads_the_secrets(self):
        """AppArmor confine charon par CHEMIN et refuse /dev/shm. La règle
        doit être posée ET le profil rechargé avant que charon lise les
        secrets, sinon le refus arrive du noyau et ressort trois étages
        plus loin en « no shared key found »."""
        plan = self._plan(apparmor=True)
        regle = next(
            i for i, c in enumerate(plan) if "apparmor_parser -r" in c
        )
        # À blanc, charon est réputé déjà lancé : le plan recharge au lieu
        # de démarrer, et « rereadsecrets » est le moment où charon lit nos
        # secrets. C'est lui qui doit venir après la règle.
        secrets = next(i for i, c in enumerate(plan) if "rereadsecrets" in c)
        self.assertLess(regle, secrets)

    def test_it_waits_for_the_connection_before_bringing_it_up(self):
        """`ipsec start` rend la main avant que le starter ait poussé les
        connexions : un « up » immédiat échoue sur « no match », sur une
        configuration parfaitement valide."""
        plan = self._plan()
        attente = next(i for i, c in enumerate(plan) if "statusall" in c)
        montee = next(
            i for i, c in enumerate(plan) if "ipsec up erplibre-" in c
        )
        self.assertLess(attente, montee)

    def test_a_busy_l2tp_port_stops_the_plan(self):
        """Continuer produirait un tube de contrôle qui n'apparaît jamais,
        deux étapes plus loin. On regarde le PORT et non le nom du service :
        sur Ubuntu, xl2tpd est un script SysV enveloppé que
        « disable --now » n'arrête pas toujours."""
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        occupe = (
            "UNCONN 0 0 0.0.0.0:1701 0.0.0.0:*"
            ' users:(("xl2tpd",pid=1234,fd=5))'
        )
        with patch(
            "script.vpn.drivers.l2tp_ipsec.locate",
            return_value="/usr/bin/ss",
        ):
            with patch.object(runner, "cmd", return_value=(0, occupe)):
                self.assertFalse(driver._l2tp_port_is_free(runner))
        self.assertTrue(runner.failures)
        # Le verdict NOMME ce qui tient le port.
        self.assertIn("xl2tpd", runner.failures[0])

    def test_a_free_l2tp_port_lets_the_plan_through(self):
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        with patch(
            "script.vpn.drivers.l2tp_ipsec.locate",
            return_value="/usr/bin/ss",
        ):
            with patch.object(runner, "cmd", return_value=(0, "\n")):
                self.assertTrue(driver._l2tp_port_is_free(runner))
        self.assertFalse(runner.failures)

    def test_without_ss_the_plan_is_not_blocked(self):
        """Un faux blocage serait pire qu'un échec tardif : sans `ss`, on
        laisse passer et le tube de contrôle tranchera."""
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        with patch("script.vpn.drivers.l2tp_ipsec.locate", return_value=""):
            self.assertTrue(driver._l2tp_port_is_free(runner))


class NotSawingOffTheBranchYouSitOn(unittest.TestCase):
    """En mode « tout le trafic », le retour de la session SSH qui donne
    l'ordre part dans le tunnel. On perd la machine, le menu, et le moyen de
    démonter ce qu'on vient de monter."""

    def _routes(self, ssh_connection=None):
        driver = _driver(default_route=True, routes=[])
        runner = _dry_runner(driver)
        env = {"SSH_CONNECTION": ssh_connection} if ssh_connection else {}
        with patch.dict(os.environ, env, clear=not ssh_connection):
            driver.up(runner)
        return [
            op["cmd"]
            for op in runner.ops
            if op["kind"] == "cmd" and "ip route replace" in op["cmd"]
        ]

    def test_the_ssh_client_keeps_a_direct_route(self):
        routes = self._routes("192.0.2.50 54321 198.51.100.7 22")
        self.assertTrue(
            any("192.0.2.50/32" in c for c in routes),
            routes,
        )
        # Celle du serveur reste, évidemment.
        self.assertTrue(any("127.0.0.1/32" in c for c in routes), routes)

    def test_nothing_extra_outside_an_ssh_session(self):
        routes = self._routes(None)
        self.assertTrue(any("127.0.0.1/32" in c for c in routes), routes)
        self.assertEqual(len(routes), 1, routes)

    def test_a_bogus_ssh_connection_is_ignored(self):
        """`SSH_CONNECTION` mal formée ne doit pas produire une route
        absurde ni faire échouer le montage."""
        routes = self._routes("pas-une-adresse 1 2 3")
        self.assertEqual(len(routes), 1, routes)

    def test_the_teardown_removes_every_survival_route(self):
        """Elles sont plusieurs : l'état en garde une par ligne."""
        driver = _driver(default_route=True, routes=[])
        runner = _dry_runner(driver)
        with patch.object(
            driver, "read_state", return_value="1.2.3.4/32\n5.6.7.8/32"
        ):
            driver.down(runner)
        joined = " ".join(
            op.get("cmd", "") for op in runner.ops if op["kind"] == "cmd"
        )
        self.assertIn("ip route del 1.2.3.4/32", joined)
        self.assertIn("ip route del 5.6.7.8/32", joined)


class WhenTheToolKnowsTheFixItOffersIt(unittest.TestCase):
    """L'outil sait souvent quoi faire. Renvoyer l'utilisateur taper la
    commande puis tout relancer, c'est lui faire porter un travail déjà
    identifié — mais le faire d'office serait arrêter un service du système
    sans le demander. Donc : proposer, appliquer, revérifier."""

    def setUp(self):
        """La question posée s'affiche même sur un exécuteur silencieux —
        c'est voulu, on s'apprête à bloquer dessus. Elle n'a rien à faire
        dans la sortie du lanceur de tests pour autant."""
        silence = redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)

    def _runner(self, sortie_port):
        """Exécuteur bouchonné dont `ss` rend `sortie_port` — une réponse par
        interrogation du port, dans l'ordre : avant le correctif, puis après.

        Seules les commandes `ss` consomment la liste : l'application du
        correctif est une commande comme une autre, et si elle en prenait
        une, le test mesurerait autre chose que ce qu'il croit.
        """
        runner = Runner(dry_run=False, quiet=True)
        reponses = list(sortie_port)

        def cmd(label, command, *a, **k):
            if "ss -lunp" in command:
                return 0, reponses.pop(0) if reponses else ""
            return 0, ""

        runner.cmd = cmd
        return runner

    TENU = (
        "UNCONN 0 0 0.0.0.0:1701 0.0.0.0:*"
        ' users:(("xl2tpd",pid=12314,fd=3))'
    )

    def test_it_offers_to_stop_xl2tpd_then_carries_on(self):
        driver = _driver()
        # `ss` dit « tenu », puis « libre » après le correctif.
        runner = self._runner([self.TENU, ""])
        with patch(
            "script.vpn.drivers.l2tp_ipsec.locate", return_value="/usr/bin/ss"
        ), patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="o"
        ):
            self.assertTrue(driver._l2tp_port_is_free(runner))
        self.assertFalse(runner.failures)

    def test_a_refused_fix_leaves_the_failure_standing(self):
        driver = _driver()
        runner = self._runner([self.TENU])
        with patch(
            "script.vpn.drivers.l2tp_ipsec.locate", return_value="/usr/bin/ss"
        ), patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="n"
        ):
            self.assertFalse(driver._l2tp_port_is_free(runner))
        self.assertTrue(runner.failures)

    def test_a_fix_that_does_not_free_the_port_still_fails(self):
        """Accepté, appliqué, et le port reste tenu : on ne prétend pas que
        c'est réglé."""
        driver = _driver()
        runner = self._runner([self.TENU, self.TENU])
        with patch(
            "script.vpn.drivers.l2tp_ipsec.locate", return_value="/usr/bin/ss"
        ), patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="o"
        ):
            self.assertFalse(driver._l2tp_port_is_free(runner))
        self.assertTrue(runner.failures)

    def test_a_leftover_of_the_same_profile_offers_our_own_down(self):
        """Un montage précédent du MÊME profil n'a rien à faire décider :
        le remède est notre propre « down », et on le propose."""
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        args = (
            "12314 xl2tpd -c /dev/shm/erplibre-vpn/acme/xl2tpd.conf"
            " -C /run/erplibre-vpn/acme.control"
        )
        appels = {"ss": 0}

        def cmd(label, command, *a, **k):
            if "ss -lunp" in command:
                appels["ss"] += 1
                # Tenu au premier regard, libre après le « down ».
                return 0, self.TENU if appels["ss"] == 1 else ""
            if "ps -o pid=" in command:
                return 0, args
            return 0, ""

        runner.cmd = cmd
        with patch(
            "script.vpn.drivers.l2tp_ipsec.locate", return_value="/usr/bin/ss"
        ), patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="o"
        ):
            self.assertTrue(driver._l2tp_port_is_free(runner))
        self.assertFalse(runner.failures)

    def test_a_sibling_tunnel_is_named_not_killed(self):
        """Le port peut être tenu par un de NOS tunnels, sur un autre
        profil. Le tuer couperait le sien : on le nomme et on s'arrête."""
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        args = (
            "12314 xl2tpd -c"
            " /dev/shm/erplibre-vpn/autre-client/xl2tpd.conf"
            " -C /run/erplibre-vpn/autre-client.control"
        )

        def cmd(label, command, *a, **k):
            if "ss -lunp" in command:
                return 0, self.TENU
            if "ps -o pid=" in command:
                return 0, args
            return 0, ""

        runner.cmd = cmd
        with patch(
            "script.vpn.drivers.l2tp_ipsec.locate", return_value="/usr/bin/ss"
        ), patch("builtins.input") as demande:
            self.assertFalse(driver._l2tp_port_is_free(runner))
        demande.assert_not_called()
        self.assertTrue(
            [m for m in runner.failures if "autre-client" in m],
            runner.failures,
        )

    def test_another_daemon_is_named_not_stopped(self):
        """Arrêter à l'aveugle un service qu'on ne connaît pas serait pire
        que le blocage : on le nomme, et on s'arrête là."""
        driver = _driver()
        autre = (
            "UNCONN 0 0 0.0.0.0:1701 0.0.0.0:*"
            ' users:(("un-autre-truc",pid=999,fd=3))'
        )
        runner = self._runner([autre])
        with patch(
            "script.vpn.drivers.l2tp_ipsec.locate", return_value="/usr/bin/ss"
        ), patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="o"
        ) as demande:
            self.assertFalse(driver._l2tp_port_is_free(runner))
        demande.assert_not_called()
        self.assertTrue(runner.failures)

    def test_the_question_is_a_whole_line_not_an_input_prompt(self):
        """Un lanceur qui relaie notre sortie en la lisant ligne par ligne
        garde une ligne partielle dans son tampon. Une question passée en
        prompt d'`input` reste donc invisible jusqu'à ce que la réponse ait
        déjà été donnée, puis ressort collée au texte suivant — et on
        répond à une question qu'on n'a pas lue."""
        runner = Runner(dry_run=False, quiet=True)
        runner.cmd = lambda *a, **k: (0, "")
        sortie = io.StringIO()
        with patch("sys.stdin.isatty", return_value=True), patch(
            "builtins.input", return_value="o"
        ) as demande, redirect_stdout(sortie):
            runner.propose("essai", "systemctl stop x", question="Arrêter ?")
        # Rien ne doit être confié au prompt d'`input` : c'est lui qui ne
        # porte pas de fin de ligne.
        demande.assert_called_once_with()
        self.assertIn("Arrêter ? [o/N]\n", sortie.getvalue())

    def test_without_a_terminal_nothing_is_applied(self):
        """Un outil qui arrête un service parce que PERSONNE n'a répondu
        serait pire que le problème qu'il résout."""
        runner = Runner(dry_run=False, quiet=True)
        applique = []
        runner.cmd = lambda *a, **k: (applique.append(a) or (0, ""))
        with patch("sys.stdin.isatty", return_value=False):
            self.assertFalse(
                runner.propose("essai", "systemctl stop quelque-chose")
            )
        self.assertEqual(applique, [])

    def test_dry_run_only_announces_the_fix(self):
        runner = Runner(dry_run=True, quiet=True)
        with patch("builtins.input") as demande:
            self.assertFalse(runner.propose("essai", "systemctl stop x"))
        demande.assert_not_called()


class TheInstallerShipsWhatTheNegotiationNeeds(unittest.TestCase):
    def test_debian_gets_the_plugin_that_provides_3des(self):
        """Sans le greffon openssl, charon ANNONCE 3DES, le concentrateur le
        choisit — c'est souvent le seul qu'il connaisse — et la négociation
        meurt sur « ENCRYPTION_ALGORITHM 3DES_CBC not supported! »."""
        with open("script/install/install_vpn.sh") as fh:
            script = fh.read()
        ligne = [
            line
            for line in script.splitlines()
            if "l2tp_ipsec:debian" in line or "strongswan-starter" in line
        ]
        self.assertTrue(
            any("libstrongswan-standard-plugins" in line for line in ligne),
            ligne,
        )


class SecretsStayOffTheCommandLine(unittest.TestCase):
    def test_no_secret_reaches_a_command_line(self):
        driver = _driver()
        runner = _dry_runner(driver)
        driver.up(runner)
        self.assertTrue(runner.ops, "le plan est vide")
        for op in runner.ops:
            if op["kind"] != "cmd":
                continue
            for secret in (PSK, PPP_PASSWORD):
                self.assertNotIn(
                    secret,
                    op["cmd"],
                    f"secret dans une commande : {op['label']}",
                )

    def test_secrets_travel_only_on_marked_standard_input(self):
        """Un secret peut passer par l'entrée standard — mais alors
        l'opération DOIT être marquée, sinon l'affichage le montrerait."""
        driver = _driver()
        runner = _dry_runner(driver)
        driver.up(runner)
        for op in runner.ops:
            content = (
                op.get("stdin") if op["kind"] == "cmd" else op.get("content")
            )
            if not content:
                continue
            leaks = [s for s in (PSK, PPP_PASSWORD) if s in content]
            if leaks:
                marked = op.get("secret_stdin") or op.get("secret")
                self.assertTrue(
                    marked,
                    f"secret non marqué dans {op.get('label') or op.get('path')}",
                )

    def test_the_files_that_hold_secrets_are_owner_only(self):
        driver = _driver()
        runner = _dry_runner(driver)
        driver.up(runner)
        writes = [op for op in runner.ops if op["kind"] == "write"]
        secret_writes = [op for op in writes if op["secret"]]
        self.assertEqual(len(secret_writes), 2, [w["path"] for w in writes])
        for op in secret_writes:
            self.assertEqual(op["mode"], "0600", op["path"])
            self.assertTrue(
                op["path"].startswith("/dev/shm/"),
                f"{op['path']} n'est pas dans un tmpfs",
            )

    def test_dry_run_output_shows_no_secret(self):
        """Ce que « Afficher la configuration rendue » imprime doit être
        montrable à l'écran de quelqu'un d'autre."""
        driver = _driver()
        runner = Runner(
            dry_run=True,
            redactor=lambda text: redact(text, driver.secret_values()),
        )
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            driver.up(runner)
        printed = buffer.getvalue()
        self.assertTrue(printed.strip())
        for secret in (PSK, PPP_PASSWORD):
            self.assertNotIn(secret, printed)
        self.assertIn("********", printed)

    def test_redact_masks_the_longest_first(self):
        """Masquer « ab » avant « abcdef » laisserait « cdef » en clair."""
        masked = redact("abcdef et ab", {"a": "ab", "b": "abcdef"})
        self.assertNotIn("abcdef", masked)
        self.assertEqual(masked, "******** et ********")


class DownOrder(unittest.TestCase):
    def test_secrets_include_is_removed_before_the_file(self):
        """L'ordre compte : un `include` qui pointe vers un fichier
        disparu fait échouer TOUT rechargement de charon, y compris celui
        d'une autre connexion."""
        driver = _driver()
        runner = _dry_runner(driver)
        driver.down(runner)
        commands = [
            op.get("cmd", "") + op.get("path", "") for op in runner.ops
        ]
        read_secrets = next(
            i for i, c in enumerate(commands) if "cat /etc/ipsec.secrets" in c
        )
        remove_dir = next(
            i
            for i, c in enumerate(commands)
            if "rm -rf -- /dev/shm/erplibre-vpn/acme" in c
        )
        self.assertLess(read_secrets, remove_dir)

    def test_down_erases_the_secret_directory(self):
        driver = _driver()
        runner = _dry_runner(driver)
        driver.down(runner)
        joined = " ".join(op.get("cmd", "") for op in runner.ops)
        self.assertIn("rm -rf -- /dev/shm/erplibre-vpn/acme", joined)


class MarkedBlocks(unittest.TestCase):
    """`replace_block` décide de ce qu'on écrit dans /etc/ipsec.conf.
    Elle est pure : elle se juge sans /etc."""

    def test_appends_when_absent(self):
        result = replace_block("config setup\n", "acme", "conn acme\n    x=1")
        self.assertIn("config setup", result)
        self.assertIn(">>> erplibre-vpn acme", result)
        self.assertIn("conn acme", result)
        self.assertIn("<<< erplibre-vpn acme", result)

    def test_replaces_in_place_and_keeps_the_rest(self):
        first = replace_block("avant\n", "acme", "un")
        second = replace_block(first, "acme", "deux")
        self.assertIn("avant", second)
        self.assertIn("deux", second)
        self.assertNotIn("un\n", second)
        self.assertEqual(second.count(">>> erplibre-vpn acme"), 1)

    def test_removes_when_body_is_empty(self):
        with_block = replace_block("avant\nautre\n", "acme", "un")
        without = replace_block(with_block, "acme", "")
        self.assertNotIn("erplibre-vpn acme", without)
        self.assertIn("avant", without)
        self.assertIn("autre", without)

    def test_two_profiles_coexist(self):
        text = replace_block("", "acme", "un")
        text = replace_block(text, "beta", "deux")
        self.assertIn("erplibre-vpn acme", text)
        self.assertIn("erplibre-vpn beta", text)
        text = replace_block(text, "acme", "")
        self.assertNotIn("erplibre-vpn acme", text)
        self.assertIn("erplibre-vpn beta", text)


class WhatTheKernelGivesAndWhatOnlyARebootGivesBack(unittest.TestCase):
    """Un module inaccessible se manifeste trois étages plus haut : charon
    démarre, abandonne à l'initialisation, et l'attente de la connexion
    accuse un bloc de configuration parfaitement formé. La vérification la
    plus basse est donc celle qui doit parler la première."""

    PRESENT = ("XFRM d'essai", lambda: True)
    ABSENT = ("XFRM d'essai", lambda: False)

    def setUp(self):
        """La question posée s'affiche même sur un exécuteur silencieux —
        c'est voulu, on s'apprête à bloquer dessus. Elle n'a rien à faire
        dans la sortie du lanceur de tests pour autant."""
        silence = redirect_stdout(io.StringIO())
        silence.__enter__()
        self.addCleanup(silence.__exit__, None, None, None)

    def _kernel(self, driver, features, stale):
        driver.kernel_features = features
        return patch(
            "script.vpn.drivers.base.stale_kernel", return_value=stale
        )

    def test_netlink_route_answers_on_any_linux(self):
        """La sonde n'exige aucun droit : elle ouvre et referme."""
        self.assertTrue(base.netlink_family_available(0))

    def test_a_refused_family_is_absent_not_an_exception(self):
        with patch("socket.socket", side_effect=OSError(93, "nope")):
            self.assertFalse(base.netlink_family_available(base.NETLINK_XFRM))

    def test_a_kernel_without_any_module_tree_is_not_stale(self):
        """Un noyau compilé sans modules n'a rien à redémarrer : le
        déclarer périmé enverrait redémarrer pour rien."""
        with patch("os.path.isdir", return_value=False), patch(
            "os.listdir", return_value=[]
        ):
            self.assertEqual(base.stale_kernel(), "")

    def test_the_running_tree_gone_while_another_stands_is_stale(self):
        with patch("os.path.isdir", return_value=False), patch(
            "os.listdir", return_value=["1.2.3-neuf"]
        ), patch("platform.release", return_value="1.2.2-vieux"):
            self.assertEqual(base.stale_kernel(), "1.2.2-vieux")

    def test_a_present_tree_is_never_stale(self):
        with patch("os.path.isdir", return_value=True):
            self.assertEqual(base.stale_kernel(), "")

    def test_missing_and_stale_names_the_reboot(self):
        driver = _driver()
        with self._kernel(driver, (self.ABSENT,), "1.2.2-vieux"):
            (label, ok, detail) = driver.check_kernel()[0]
            self.assertTrue(driver.needs_reboot())
        self.assertEqual((label, ok), ("noyau", False))
        self.assertIn("1.2.2-vieux", detail)
        self.assertIn("redémarrer", detail)

    def test_missing_on_a_current_kernel_offers_no_reboot(self):
        """Redémarrer ne fait pas apparaître ce que le noyau n'a pas."""
        driver = _driver()
        with self._kernel(driver, (self.ABSENT,), ""):
            (_, ok, detail) = driver.check_kernel()[0]
            self.assertFalse(driver.needs_reboot())
        self.assertFalse(ok)
        self.assertNotIn("redémarrer", detail)

    def test_a_stale_tree_alone_is_a_warning_not_a_failure(self):
        """La capacité répond : un tunnel déjà monté fonctionne, et un
        « ✗ » ferait mentir le diagnostic."""
        driver = _driver()
        with self._kernel(driver, (self.PRESENT,), "1.2.2-vieux"):
            (_, ok, detail) = driver.check_kernel()[0]
            self.assertFalse(driver.needs_reboot())
        self.assertIs(ok, True)
        self.assertIn("1.2.2-vieux", detail)

    def test_a_healthy_kernel_says_so_once(self):
        driver = _driver()
        with self._kernel(driver, (self.PRESENT,), ""):
            checks = driver.check_kernel()
        self.assertEqual(len(checks), 1)
        self.assertIs(checks[0][1], True)

    def test_a_driver_that_asks_nothing_of_the_kernel_stays_silent(self):
        driver = _driver()
        with self._kernel(driver, (), ""):
            self.assertEqual(driver.check_kernel(), [])

    def test_the_reboot_is_offered_and_applied_when_accepted(self):
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        lancees = []
        runner.cmd = lambda label, command, **k: (
            lancees.append(command) or (0, "")
        )
        with self._kernel(driver, (self.ABSENT,), "1.2.2-vieux"), patch(
            "sys.stdin.isatty", return_value=True
        ), patch("builtins.input", return_value="o"):
            self.assertTrue(driver.propose_reboot(runner))
        self.assertEqual(lancees, ["systemctl reboot"])

    def test_nothing_reboots_without_a_terminal_to_answer(self):
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        lancees = []
        runner.cmd = lambda label, command, **k: (
            lancees.append(command) or (0, "")
        )
        with self._kernel(driver, (self.ABSENT,), "1.2.2-vieux"), patch(
            "sys.stdin.isatty", return_value=False
        ):
            self.assertFalse(driver.propose_reboot(runner))
        self.assertEqual(lancees, [])

    def test_nothing_reboots_on_a_dry_run(self):
        driver = _driver()
        runner = _dry_runner(driver)
        with self._kernel(driver, (self.ABSENT,), "1.2.2-vieux"), patch(
            "builtins.input"
        ) as demande:
            self.assertFalse(driver.propose_reboot(runner))
        demande.assert_not_called()

    def test_an_accepted_reboot_still_stops_the_mount(self):
        """La machine met quelques secondes à s'arrêter. Monter un tunnel
        dans l'intervalle serait le monter sur le noyau qu'on quitte."""
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        runner.cmd = lambda label, command, **k: (0, "")
        with self._kernel(driver, (self.ABSENT,), "1.2.2-vieux"), patch(
            "sys.stdin.isatty", return_value=True
        ), patch("builtins.input", return_value="o"):
            self.assertFalse(driver.ensure_ready(runner))
        self.assertTrue(runner.failures)

    def test_a_faulty_kernel_stops_the_mount_before_it_writes(self):
        """Rien ne doit atterrir dans /etc quand l'étage du dessous est à
        terre : les blocs posés là survivent au redémarrage et la
        configuration de quelqu'un a été touchée pour rien."""
        driver = _driver()
        runner = Runner(dry_run=False, quiet=True)
        with self._kernel(driver, (self.ABSENT,), "1.2.2-vieux"), patch(
            "sys.stdin.isatty", return_value=False
        ):
            self.assertFalse(driver.up(runner))
        touches = [
            op
            for op in runner.ops
            if "/etc" in op.get("cmd", "") + op.get("path", "")
        ]
        self.assertEqual(touches, [])
        self.assertTrue(runner.failures)

    def test_the_kernel_is_judged_before_the_packages(self):
        """Du plus bas au plus haut : la première ligne fausse doit être la
        CAUSE, pas une conséquence."""
        driver = _driver()
        runner = Runner(dry_run=True, quiet=True)
        with self._kernel(driver, (self.ABSENT,), "1.2.2-vieux"):
            labels = [label for label, _, _ in driver.standard_status(runner)]
        self.assertEqual(labels[0], "noyau")


if __name__ == "__main__":
    unittest.main()
