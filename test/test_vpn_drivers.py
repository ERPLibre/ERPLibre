#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les cinq pilotes VPN : contrat commun, et ce qui est propre à chacun.

Le test qui compte le plus est `NoSecretLeaksAnywhere` : il rejoue le plan de
montage de CHAQUE pilote avec de faux secrets et vérifie qu'aucun n'atteint
une ligne de commande. `/proc/<pid>/cmdline` est lisible par tout utilisateur
de la machine ; un secret en argument est un secret public. Ce test est
table-orientée exprès : un sixième pilote ajouté au registre y entre tout
seul, et échoue s'il se croit dispensé de la règle.

Ni root, ni réseau, ni serveur en face : le `Runner` à blanc n'exécute rien,
il enregistre. Tous les serveurs de test sont 127.0.0.1 pour qu'aucun test ne
dépende d'une résolution de nom.
"""

import base64
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
)

from script.vpn import profiles
from script.vpn.drivers import DRIVERS
from script.vpn.drivers.base import locate, which
from script.vpn.runner import Runner
from script.vpn.valid import ProfileError
from script.vpn.vault import redact

# Des secrets reconnaissables, assez longs pour qu'aucun ne se retrouve par
# hasard dans un chemin ou une option.
SECRET = "S3cr3t-Qu3-P3rs0nn3-N3-D0it-V0ir"
WG_PRIVATE = base64.b64encode(bytes(range(32))).decode()
WG_PUBLIC = base64.b64encode(bytes(range(32, 64))).decode()
WG_PRESHARED = base64.b64encode(bytes(range(64, 96))).decode()

# Un profil valide par pilote, et les secrets que ce pilote attend.
SAMPLES = {
    "l2tp_ipsec": (
        {
            "server": "127.0.0.1",
            "ppp_user": "ACME\\user",
            "routes": ["10.20.0.0/16"],
            "probe": "10.20.0.1",
        },
        {"psk": SECRET + "-psk", "password": SECRET + "-ppp"},
    ),
    "wireguard": (
        {
            "server": "127.0.0.1",
            "wg_address": "10.7.0.2/32",
            "wg_peer_key": WG_PUBLIC,
            "routes": ["10.7.0.0/24"],
        },
        {"wg_private_key": WG_PRIVATE, "wg_preshared_key": WG_PRESHARED},
    ),
    "openvpn": (
        {
            "server": "127.0.0.1",
            "ovpn_config": "/tmp/acme/client.ovpn",
            "ovpn_user": "user",
            "routes": ["10.30.0.0/16"],
        },
        {"password": SECRET + "-ovpn"},
    ),
    "openconnect": (
        {
            "server": "127.0.0.1",
            "oc_user": "user",
            "oc_protocol": "anyconnect",
            "default_route": True,
        },
        {"password": SECRET + "-oc"},
    ),
    "sshuttle": (
        {
            "server": "erplibre@127.0.0.1",
            "routes": ["10.40.0.0/16"],
            "probe": "10.40.0.1",
        },
        {},
    ),
}


def build(driver_name, **overrides):
    """(pilote instancié, exécuteur à blanc) pour `driver_name`."""
    fields, secrets = SAMPLES[driver_name]
    profile = dict(fields, name=f"t-{driver_name}"[:31], driver=driver_name)
    profile.update(overrides)
    profile = profiles.validate(profile)
    driver = DRIVERS[driver_name](profile, dict(secrets))
    runner = Runner(
        dry_run=True,
        quiet=True,
        redactor=lambda text: redact(text, driver.secret_values()),
    )
    return driver, runner


def commands(runner):
    return [op["cmd"] for op in runner.ops if op["kind"] == "cmd"]


class DriverContract(unittest.TestCase):
    """Ce que tout pilote doit déclarer pour que le menu et le CLI
    fonctionnent sans le connaître."""

    def test_every_driver_is_complete(self):
        for name, cls in DRIVERS.items():
            with self.subTest(driver=name):
                self.assertEqual(cls.name, name)
                self.assertTrue(cls.label, "libellé vide")
                self.assertLessEqual(len(cls.label), 34, "libellé trop long")
                self.assertTrue(cls.hint, "aucun conseil de choix")
                self.assertTrue(cls.binaries, "aucun binaire déclaré")
                self.assertTrue(cls.server_label)
                self.assertIsInstance(cls.proven, bool)

    def test_form_fields_are_well_formed(self):
        for name, cls in DRIVERS.items():
            for field in cls.form_fields:
                with self.subTest(driver=name, field=field):
                    key, label, kind, advanced = field
                    self.assertIn(kind, ("text", "int", "flag", "path"))
                    self.assertIn(
                        key,
                        cls.defaults,
                        "un champ demandé sans valeur par défaut",
                    )
                    self.assertTrue(label)
                    self.assertIsInstance(advanced, bool)

    def test_secret_fields_are_well_formed(self):
        for name, cls in DRIVERS.items():
            for key, label, required in cls.secret_fields:
                with self.subTest(driver=name, secret=key):
                    self.assertTrue(label)
                    self.assertIsInstance(required, bool)

    def test_every_sample_profile_validates(self):
        """Le jeu d'essai lui-même doit passer la validation : sinon les
        tests suivants mesureraient un profil que personne ne pourrait
        enregistrer."""
        for name in DRIVERS:
            with self.subTest(driver=name):
                driver, _ = build(name)
                self.assertEqual(driver.profile["driver"], name)


class BinariesRootRunsAreNotOursToRun(unittest.TestCase):
    """Un binaire lancé par root n'a pas à être exécutable par nous.

    `pppd` est installé en 4750 root:dip sur Debian et Ubuntu. Tout
    utilisateur hors du groupe dip se voyait annoncer « pppd absent » sur
    une machine où le paquet ppp était installé — et envoyé réinstaller ce
    qui était déjà là. C'est l'EXISTENCE qui compte : xl2tpd, qui tourne en
    root, l'exécute très bien.
    """

    def test_which_asks_about_us_and_locate_about_existence(self):
        with tempfile.TemporaryDirectory() as directory:
            faux = os.path.join(directory, "pppd")
            open(faux, "w").close()
            os.chmod(faux, 0o000)
            with patch.dict(os.environ, {"PATH": directory}):
                self.assertEqual(which("pppd"), "")
                self.assertEqual(locate("pppd"), faux)

    def test_a_driver_sees_such_a_binary_as_present(self):
        driver, _ = build("l2tp_ipsec")
        with tempfile.TemporaryDirectory() as directory:
            for binary in driver.binaries:
                chemin = os.path.join(directory, binary)
                open(chemin, "w").close()
                os.chmod(chemin, 0o000)
            with patch.dict(os.environ, {"PATH": directory}):
                self.assertEqual(driver.missing_binaries(), [])

    def test_a_truly_absent_binary_is_still_reported(self):
        driver, _ = build("l2tp_ipsec")
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"PATH": directory}):
                self.assertEqual(
                    sorted(driver.missing_binaries()),
                    sorted(driver.binaries),
                )


class NoSecretLeaksAnywhere(unittest.TestCase):
    """Le test central : aucun secret dans une ligne de commande, pour
    aucun pilote."""

    def test_no_secret_in_any_command(self):
        for name in DRIVERS:
            driver, runner = build(name)
            driver.up(runner)
            with self.subTest(driver=name):
                self.assertTrue(runner.ops, "plan vide")
                for op in runner.ops:
                    if op["kind"] != "cmd":
                        continue
                    for secret in driver.secret_values():
                        self.assertNotIn(
                            secret,
                            op["cmd"],
                            f"{name} : secret dans « {op['label']} »",
                        )

    def test_a_secret_in_a_payload_is_always_marked(self):
        """Un secret peut voyager par l'entrée standard ou dans un fichier
        — mais l'opération doit être MARQUÉE, sinon l'affichage le
        montrerait."""
        for name in DRIVERS:
            driver, runner = build(name)
            driver.up(runner)
            for op in runner.ops:
                payload = (
                    op.get("stdin")
                    if op["kind"] == "cmd"
                    else op.get("content")
                )
                if not payload:
                    continue
                leaked = [s for s in driver.secret_values() if s in payload]
                if leaked:
                    with self.subTest(driver=name, op=op.get("label")):
                        self.assertTrue(
                            op.get("secret_stdin") or op.get("secret"),
                            "secret non marqué",
                        )

    def test_secret_files_are_owner_only_and_in_tmpfs(self):
        for name in DRIVERS:
            driver, runner = build(name)
            driver.up(runner)
            for op in runner.ops:
                if op["kind"] == "write" and op["secret"]:
                    with self.subTest(driver=name, path=op["path"]):
                        self.assertEqual(op["mode"], "0600")
                        self.assertTrue(op["path"].startswith("/dev/shm/"))

    def test_down_erases_the_secret_directory(self):
        """Sauf pour ceux qui n'écrivent aucun secret : il n'y a rien à
        effacer, et prétendre le faire serait du théâtre."""
        writes_secrets = ("l2tp_ipsec", "wireguard", "openvpn")
        for name in DRIVERS:
            driver, runner = build(name)
            driver.down(runner)
            joined = " ".join(commands(runner))
            with self.subTest(driver=name):
                if name in writes_secrets:
                    self.assertIn(f"rm -rf -- {driver.secret_dir}", joined)


class Wireguard(unittest.TestCase):
    def test_config_holds_the_private_key_and_the_peer(self):
        driver, _ = build("wireguard")
        body = driver.config_body()
        self.assertIn(f"PrivateKey = {WG_PRIVATE}", body)
        self.assertIn(f"PublicKey = {WG_PUBLIC}", body)
        self.assertIn(f"PresharedKey = {WG_PRESHARED}", body)
        self.assertIn("Endpoint = 127.0.0.1:51820", body)

    def test_no_dns_line_in_the_configuration(self):
        """`DNS =` fait appeler `resolvconf` par wg-quick, absent de
        beaucoup d'installations systemd-resolved — et c'est la
        configuration ENTIÈRE qui échoue alors."""
        driver, _ = build("wireguard", wg_dns="10.7.0.1")
        self.assertNotIn("DNS =", driver.config_body())
        # …mais le DNS est bien appliqué, par resolvectl, après le montage.
        driver, runner = build("wireguard", wg_dns="10.7.0.1")
        driver.up(runner)

    def test_allowed_ips_carries_the_routing(self):
        driver, _ = build("wireguard")
        self.assertEqual(driver.allowed_ips, "10.7.0.0/24")
        driver, _ = build("wireguard", default_route=True, routes=[])
        self.assertEqual(driver.allowed_ips, "0.0.0.0/0")

    def test_the_config_file_is_named_after_the_interface(self):
        """`wg-quick` DÉDUIT le nom de l'interface du nom du fichier."""
        driver, _ = build("wireguard")
        self.assertTrue(
            driver.config_file.endswith(f"/{driver.iface}.conf"),
            driver.config_file,
        )
        self.assertLessEqual(len(driver.iface), 15)

    def test_no_manual_route_command(self):
        """Les routes appartiennent à wg-quick, via AllowedIPs : en
        ajouter ici entrerait en conflit avec les siennes."""
        driver, runner = build("wireguard")
        driver.up(runner)
        for command in commands(runner):
            self.assertNotIn("ip route replace 10.7.0.0/24", command)

    def test_it_waits_for_a_handshake(self):
        """L'interface monte même avec une clé fausse : sans cette attente,
        « monté » ne voudrait dire que « l'interface existe »."""
        driver, runner = build("wireguard")
        driver.up(runner)
        self.assertTrue(
            any("latest-handshakes" in c for c in commands(runner)),
            "aucune attente de poignée de main",
        )

    def test_a_malformed_peer_key_is_refused(self):
        """wg-quick refuse la configuration ENTIÈRE sur une clé mal formée,
        avec un message qui ne dit pas laquelle. On le dit avant."""
        for bad in ("pas-une-cle", WG_PUBLIC[:-1], WG_PUBLIC + "x", ""):
            with self.subTest(cle=bad):
                with self.assertRaises(ProfileError):
                    build("wireguard", wg_peer_key=bad)

    def test_an_address_without_prefix_becomes_a_32(self):
        driver, _ = build("wireguard", wg_address="10.7.0.9")
        self.assertEqual(driver.profile["wg_address"], "10.7.0.9/32")


class Openvpn(unittest.TestCase):
    def test_it_changes_directory_to_the_config(self):
        """Un .ovpn référence ses fichiers voisins en relatif."""
        driver, _ = build("openvpn")
        self.assertIn("--cd /tmp/acme", driver.command())

    def test_config_comes_before_the_credentials(self):
        """Ce qui suit `--config` l'emporte sur le contenu du fichier : un
        `auth-user-pass` nu dedans ferait attendre une saisie qui ne
        viendra jamais, le démon étant détaché."""
        command = build("openvpn")[0].command()
        self.assertLess(
            command.index("--config"), command.index("--auth-user-pass")
        )

    def test_credentials_are_two_lines_in_tmpfs(self):
        driver, _ = build("openvpn")
        self.assertEqual(driver.auth_body(), f"user\n{SECRET}-ovpn\n")
        self.assertTrue(driver.auth_file.startswith("/dev/shm/"))

    def test_split_tunnel_asks_for_route_nopull(self):
        self.assertIn("--route-nopull", build("openvpn")[0].command())

    def test_full_tunnel_lets_the_server_push(self):
        command = build("openvpn", default_route=True, routes=[])[0].command()
        self.assertNotIn("--route-nopull", command)

    def test_no_credentials_no_auth_option(self):
        """Un .ovpn qui s'authentifie par certificat ne doit pas se voir
        imposer un fichier d'identifiants vide."""
        command = build("openvpn", ovpn_user="")[0].command()
        self.assertNotIn("--auth-user-pass", command)

    def test_it_waits_for_the_initialisation_line(self):
        driver, runner = build("openvpn")
        driver.up(runner)
        self.assertTrue(
            any(
                "Initialization Sequence Completed" in c
                for c in commands(runner)
            )
        )

    def test_a_missing_config_path_is_refused(self):
        with self.assertRaises(ProfileError):
            build("openvpn", ovpn_config="")


class Openconnect(unittest.TestCase):
    def test_the_password_never_touches_the_disk(self):
        """Le seul pilote sans aucun fichier de secret."""
        driver, runner = build("openconnect")
        driver.up(runner)
        secret_writes = [
            op
            for op in runner.ops
            if op["kind"] == "write" and op.get("secret")
        ]
        self.assertEqual(secret_writes, [])

    def test_the_password_travels_on_marked_standard_input(self):
        driver, runner = build("openconnect")
        driver.up(runner)
        launches = [
            op for op in runner.ops if op["kind"] == "cmd" and op.get("stdin")
        ]
        self.assertEqual(len(launches), 1)
        self.assertTrue(launches[0]["secret_stdin"])
        self.assertIn(f"{SECRET}-oc", launches[0]["stdin"])
        self.assertIn("--passwd-on-stdin", launches[0]["cmd"])

    def test_non_interactive_so_a_cert_prompt_cannot_eat_the_password(self):
        self.assertIn("--non-inter", build("openconnect")[0].command())

    def test_the_interface_is_named_not_discovered(self):
        driver, _ = build("openconnect")
        self.assertIn(f"--interface={driver.iface}", driver.command())
        self.assertLessEqual(len(driver.iface), 15)

    def test_an_unknown_protocol_is_refused(self):
        with self.assertRaises(ProfileError):
            build("openconnect", oc_protocol="carrier-pigeon")

    def test_routes_are_not_required(self):
        """C'est le serveur qui les pousse : exiger une route déclarée
        serait une fausse exigence."""
        driver, _ = build("openconnect", default_route=False, routes=[])
        self.assertEqual(driver.profile["routes"], [])


class _OpenconnectNoHelper(DRIVERS["openconnect"]):
    """Le pilote openconnect, mais sans greffon SSO.

    L'attribut de classe masque la propriété du parent, qui irait chercher
    dans le PATH. Sans cela, « SSO sans greffon » serait vrai ou faux selon
    la machine qui exécute la suite.
    """

    sso_helper = ""


class OpenconnectSingleSignOn(unittest.TestCase):
    """Le cas du « formulaire web » : le concentrateur délègue à un
    fournisseur d'identité, et il n'y a aucun mot de passe à envoyer.

    Deux chemins existent, et cette classe couvre le premier. Sans greffon,
    openconnect s'en charge seul : il écoute sur son port local 29786 et
    attend la redirection d'un navigateur, lequel peut être celui de
    l'utilisateur, ailleurs, à travers un `ssh -L`. Cela ne fonctionne que
    si le serveur annonce la méthode « navigateur externe ».

    Le second chemin — le concentrateur exige un navigateur intégré, et un
    greffon fait l'étape web — vit dans `test_vpn_presets.py`, classe
    `DelegatedSso`.
    """

    def _sso(self, helper="", **overrides):
        """Un pilote en SSO, sur le chemin CHOISI par le test.

        `helper` décide : vide, c'est `--external-browser` et openconnect se
        débrouille ; renseigné, le pilote délègue l'étape web au greffon.
        Il est TOUJOURS explicite, jamais découvert — sinon le test dépend
        de ce qui est installé sur la machine qui l'exécute, et le même code
        passe ici et échoue ailleurs.
        """
        profile = dict(
            SAMPLES["openconnect"][0],
            name="t-sso",
            driver="openconnect",
            oc_sso=True,
            oc_user="",
            oc_sso_helper=helper,
        )
        profile.update(overrides)
        clean = profiles.validate(profile)
        which = DRIVERS["openconnect"] if helper else _OpenconnectNoHelper
        return which(clean, {})

    def test_a_profile_without_user_or_password_is_valid(self):
        """En SSO, c'est le fournisseur d'identité qui décide de qui on est :
        exiger un utilisateur refuserait un profil parfaitement valide."""
        driver = self._sso()
        self.assertEqual(driver.profile["oc_user"], "")
        self.assertEqual(driver.missing_secrets(), [])

    def test_the_command_asks_for_an_external_browser(self):
        command = self._sso().command()
        self.assertIn("--external-browser=echo", command)
        self.assertNotIn("--passwd-on-stdin", command)
        self.assertNotIn("--user=", command)

    def test_no_non_inter_in_sso(self):
        """L'échange avec le navigateur EST l'interaction : l'interdire
        ferait échouer la seule étape qui compte."""
        self.assertNotIn("--non-inter", self._sso().command())

    def test_a_chosen_browser_is_honoured(self):
        driver = self._sso(oc_external_browser="/usr/bin/xdg-open")
        self.assertIn("--external-browser=/usr/bin/xdg-open", driver.command())

    def test_it_explains_the_round_trip_before_waiting(self):
        """openconnect attend en silence : sans explication, l'attente
        ressemble à un blocage, et la redirection ne revient jamais si
        personne n'a monté le tunnel ssh."""
        driver = self._sso()
        runner = Runner(dry_run=True)
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            driver.up(runner)
        printed = buffer.getvalue()
        self.assertIn("29786", printed)
        self.assertIn("ssh -L", printed)

    def test_sso_writes_no_secret_and_sends_nothing_on_stdin(self):
        driver = self._sso()
        runner = Runner(dry_run=True, quiet=True)
        driver.up(runner)
        for op in runner.ops:
            self.assertFalse(op.get("secret"))
            self.assertFalse(op.get("stdin"))

    def test_classic_mode_still_needs_a_password(self):
        """Sans SSO et sans mot de passe, on le dit au lieu de lancer une
        commande qui échouera.

        Le binaire est réputé présent : sans ce bouchon, le test mesure les
        paquets de la machine qui l'exécute et c'est « openconnect absent »
        qui remonte, sur un pilote qui a pourtant raison de le dire.
        """
        profile = profiles.validate(
            dict(
                SAMPLES["openconnect"][0],
                name="t-clas",
                driver="openconnect",
            )
        )
        driver = DRIVERS["openconnect"](profile, {})
        runner = Runner(dry_run=False, quiet=True)
        runner.cmd = lambda *a, **k: (0, "")
        runner.mkdir = lambda *a, **k: 0
        with patch(
            "script.vpn.drivers.base.locate", return_value="/usr/bin/x"
        ):
            self.assertFalse(driver.up(runner))
        self.assertTrue(
            [m for m in runner.failures if "coffre" in m], runner.failures
        )


class Sshuttle(unittest.TestCase):
    def test_it_is_not_launched_under_sudo(self):
        """sshuttle n'élève que la partie pare-feu. Sous sudo, la session
        SSH serait ouverte par root — avec les clés de root."""
        driver, runner = build("sshuttle")
        driver.up(runner)
        launches = [c for c in commands(runner) if "sshuttle --remote" in c]
        self.assertEqual(len(launches), 1)
        self.assertFalse(launches[0].startswith("sudo "), launches[0])

    def test_the_pidfile_lives_in_the_home(self):
        """/run/erplibre-vpn appartient à root : sshuttle tourne sous
        l'utilisateur et ne pourrait pas y écrire."""
        driver, _ = build("sshuttle")
        self.assertTrue(driver.pid_file.startswith(os.path.expanduser("~")))

    def test_it_has_no_secret_at_all(self):
        driver, _ = build("sshuttle")
        self.assertEqual(driver.secret_fields, ())
        self.assertEqual(driver.missing_secrets(), [])

    def test_subnets_come_from_the_routes(self):
        driver, _ = build("sshuttle")
        self.assertEqual(driver.subnets, ["10.40.0.0/16"])
        driver, _ = build("sshuttle", default_route=True, routes=[])
        self.assertEqual(driver.subnets, ["0.0.0.0/0"])

    def test_status_judges_on_the_witness_only(self):
        """Sans interface ni route à vérifier, une vérification
        d'interface rendrait un « ✗ » qui ne veut rien dire."""
        driver, runner = build("sshuttle")
        runner.quiet = True
        labels = [label for label, _, _ in driver.status(runner)]
        self.assertFalse([label for label in labels if "interface" in label])
        self.assertTrue([label for label in labels if "témoin" in label])

    def test_an_ssh_target_with_a_user_is_accepted(self):
        driver, _ = build("sshuttle")
        self.assertEqual(driver.profile["server"], "erplibre@127.0.0.1")


if __name__ == "__main__":
    unittest.main()
