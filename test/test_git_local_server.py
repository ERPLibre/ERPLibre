#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Le serveur git local, et les deux défauts qu'il avait à l'envers.

LE PROTOCOLE GIT N'AUTHENTIFIE PERSONNE. Ce n'est pas une lacune de
configuration : il n'y a pas de compte, pas de mot de passe, pas de trace
d'auteur. Tout ce qui atteint le port a les droits que le démon accorde.

D'où deux défauts qui, ensemble, faisaient une porte : « --listen » n'était
pas posé — donc écoute sur toutes les interfaces — et
« --enable=receive-pack » l'était d'office — donc écriture. N'importe qui
sur le réseau pouvait pousser dans n'importe quel dépôt servi, sans laisser
de nom.

La commande est RENDUE et non exécutée : c'est ce qui permet de l'éprouver
depuis une station, sans lancer de démon ni ouvrir de port.
"""

import ast
import contextlib
import importlib.util
import io
import os
import sys
import tempfile
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)


def _module():
    """git_local_server.py chargé comme module, comme le fait le menu."""
    chemin = os.path.join(RACINE, "script", "git", "git_local_server.py")
    spec = importlib.util.spec_from_file_location("git_local_server", chemin)
    module = importlib.util.module_from_spec(spec)
    sys.modules["git_local_server"] = module
    spec.loader.exec_module(module)
    return module


GLS = _module()
DEPOTS = "/depots-de-banc"
PORT = 9418


class TestLesDeuxDefautsRenverses(unittest.TestCase):
    def test_by_default_it_listens_on_the_loopback_only(self):
        """Sans « --listen », le démon écoute sur toutes les interfaces et
        le dépôt est offert à tout ce qui atteint la machine."""
        cmd = GLS.daemon_command(DEPOTS, PORT)
        self.assertIn("--listen=127.0.0.1", cmd)

    def test_by_default_nothing_can_be_pushed(self):
        """L'écriture est ANONYME par construction : rien ne dira qui a
        poussé."""
        self.assertNotIn("receive-pack", GLS.daemon_command(DEPOTS, PORT))

    def test_writing_is_possible_and_has_to_be_asked_for(self):
        """Contrôle positif : l'interdire toujours retirerait l'usage."""
        cmd = GLS.daemon_command(DEPOTS, PORT, writable=True)
        self.assertIn("--enable=receive-pack", cmd)

    def test_listening_further_is_possible_and_has_to_be_asked_for(self):
        cmd = GLS.daemon_command(DEPOTS, PORT, listen="0.0.0.0")
        self.assertIn("--listen=0.0.0.0", cmd)

    def test_reading_stays_open_to_whoever_is_let_in(self):
        """« --export-all » n'ouvre que la lecture, et seulement à qui
        « --listen » laisse entrer : c'est ce qui rend un miroir de
        manifeste utilisable sans marquer chaque dépôt un par un."""
        self.assertIn("--export-all", GLS.daemon_command(DEPOTS, PORT))

    def test_the_two_looseners_are_independent(self):
        """L'un ou l'autre seul est déjà large ; les deux ensemble sont une
        porte. Les lier ferait ouvrir le second en demandant le premier."""
        ouvert = GLS.daemon_command(DEPOTS, PORT, listen="0.0.0.0")
        ecrivable = GLS.daemon_command(DEPOTS, PORT, writable=True)
        self.assertNotIn("receive-pack", ouvert)
        self.assertIn("--listen=127.0.0.1", ecrivable)


def analyse_argv(argv=()):
    """La configuration qu'aurait `main` avec cette ligne de commande."""
    vrai = sys.argv
    sys.argv = ["git_local_server.py", *argv]
    try:
        return GLS.get_config()
    finally:
        sys.argv = vrai


class TestCeQueLaLigneDeCommandeOffre(unittest.TestCase):
    def analyse(self, argv=()):
        return analyse_argv(argv)

    def test_the_safe_defaults_are_the_defaults(self):
        config = self.analyse()
        self.assertEqual(GLS.DEFAULT_LISTEN, config.listen)
        self.assertFalse(config.allow_anonymous_push)

    def test_each_loosening_is_named_for_what_it_does(self):
        """« --allow-anonymous-push » dit ce qu'il autorise ; un
        « --enable-write » laisserait croire qu'il y a un auteur."""
        config = self.analyse(
            ["--allow-anonymous-push", "--listen", "0.0.0.0"]
        )
        self.assertTrue(config.allow_anonymous_push)
        self.assertEqual("0.0.0.0", config.listen)


class TestLesOptionsArriventJusquAuDemon(unittest.TestCase):
    """Une option analysée puis jetée est pire que pas d'option.

    `get_config` peut lire « --allow-anonymous-push » parfaitement et
    `daemon_command` savoir le rendre : si `main` ne les relie pas, le drapeau
    ne fait rien. Le démon démarre en lecture seule, la poussée est refusée,
    et on cherche la cause du côté du client. Ces épreuves mesurent le FIL
    entre les deux, que rien d'autre ici ne touche.
    """

    @staticmethod
    def _main():
        chemin = os.path.join(RACINE, "script", "git", "git_local_server.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef) and noeud.name == "main"
        ]
        assert len(corps) == 1, "ancre introuvable ou dédoublée"
        return corps[0]

    def _appel(self):
        appels = [
            noeud
            for noeud in ast.walk(self._main())
            if isinstance(noeud, ast.Call)
            and isinstance(noeud.func, ast.Name)
            and noeud.func.id == "serve_git_daemon"
        ]
        self.assertEqual(1, len(appels), "l'ancre doit être unique")
        return appels[0]

    def _passe(self, appel, nom):
        """La valeur du mot-clé `nom`, ou None s'il n'est pas passé."""
        for mot in appel.keywords:
            if mot.arg == nom:
                return mot.value
        return None

    def test_the_listen_option_is_the_one_handed_over(self):
        """« listen=DEFAULT_LISTEN » recompilerait sans un mot et rendrait
        « --listen » muet."""
        valeur = self._passe(self._appel(), "listen")
        self.assertIsInstance(valeur, ast.Attribute)
        self.assertEqual("listen", valeur.attr)
        self.assertEqual("config", valeur.value.id)

    def test_the_push_option_is_the_one_handed_over(self):
        valeur = self._passe(self._appel(), "writable")
        self.assertIsInstance(valeur, ast.Attribute)
        self.assertEqual("allow_anonymous_push", valeur.attr)
        self.assertEqual("config", valeur.value.id)

    def test_the_call_is_not_parked_under_a_dead_condition(self):
        """La PRÉSENCE d'un appel ne prouve rien : posé sous une condition
        toujours fausse, il reste dans l'arbre et ne s'exécute jamais."""
        appel = self._appel()
        for noeud in ast.walk(self._main()):
            if not isinstance(noeud, ast.If):
                continue
            if any(appel is fils for fils in ast.walk(noeud)):
                self.assertNotIsInstance(noeud.test, ast.Constant)

    def test_the_fields_the_call_reads_are_fields_config_has(self):
        """L'arbre seul ne voit pas un champ renommé d'un côté : le démon
        lèverait un AttributeError après toute la lecture du manifeste, donc
        au bout de plusieurs secondes et non au démarrage."""
        appel = self._appel()
        config = analyse_argv()
        lus = [
            mot.value.attr
            for mot in appel.keywords
            if isinstance(mot.value, ast.Attribute)
        ]
        self.assertTrue(lus, "aucun champ lu : rien n'est prouvé")
        for champ in lus:
            with self.subTest(champ=champ):
                self.assertTrue(hasattr(config, champ))


class TestLUrlNommeLAdresseLiee(unittest.TestCase):
    """Le démon se lie à UNE adresse ; un nom d'hôte en désigne une autre.

    Tant que le démon écoutait partout, « localhost » atteignait forcément
    quelque chose. Lié à la seule boucle IPv4, il donne un refus de connexion
    là où le résolveur rend « ::1 » en premier — et l'URL affichée dément le
    refus, ce qui envoie chercher du côté du pare-feu.
    """

    def test_an_ipv6_address_is_bracketed(self):
        """Sans crochets, ses deux-points passent pour un séparateur de
        port et l'URL n'est plus analysable."""
        self.assertEqual("[::1]", GLS.url_host("::1"))

    def test_an_ipv4_address_is_left_alone(self):
        self.assertEqual("127.0.0.1", GLS.url_host("127.0.0.1"))

    def test_the_clone_commands_name_the_bound_address(self):
        """La liste n'imprime que les dépôts qui existent sur disque : sans
        répertoire nu, elle est vide et ne prouverait rien."""
        with tempfile.TemporaryDirectory() as depots:
            os.mkdir(os.path.join(depots, "essai.git"))
            projets = [{"name": "essai", "path": "essai"}]
            sortie = io.StringIO()
            with contextlib.redirect_stdout(sortie):
                GLS.print_clone_commands(depots, projets, PORT, listen="::1")
        texte = sortie.getvalue()
        self.assertIn("git://[::1]", texte)
        self.assertNotIn("localhost", texte)


class TestCeQuiEstDitQuandOnElargit(unittest.TestCase):
    """Un élargissement demandé se voit ; obtenu en silence, il s'oublie."""

    def servir(self, projets=(), depots=DEPOTS, **options):
        """Ce que le démon IMPRIME, sans qu'aucun démon ne démarre."""
        sortie = io.StringIO()
        vrai = GLS.Execute
        GLS.Execute = lambda *a, **k: type(
            "Muet", (), {"exec_command_live": lambda *a, **k: None}
        )()
        try:
            with contextlib.redirect_stdout(sortie):
                GLS.serve_git_daemon(depots, list(projets), PORT, **options)
        finally:
            GLS.Execute = vrai
        return sortie.getvalue()

    def test_the_safe_default_warns_about_nothing(self):
        """Un avertissement permanent ne s'avertit plus de rien."""
        sortie = self.servir()
        self.assertNotIn("⚠", sortie)

    def test_anonymous_writing_is_announced(self):
        self.assertIn("⚠", self.servir(writable=True))

    def test_listening_further_is_announced(self):
        self.assertIn("⚠", self.servir(listen="0.0.0.0"))

    def test_a_hostname_is_not_taken_for_the_loopback(self):
        """« localhost » se résout où le résolveur le dit ; le traiter
        comme local tairait un élargissement réel."""
        self.assertIn("⚠", self.servir(listen="localhost"))

    def test_every_printed_url_names_the_bound_address(self):
        """Le démon imprime l'URL À SUIVRE, deux fois : en tête pour chaque
        dépôt, puis en résumé. Les deux doivent nommer ce qui est lié — une
        seule laissée sur « localhost » suffit à envoyer au mauvais endroit.
        """
        with tempfile.TemporaryDirectory() as depots:
            os.mkdir(os.path.join(depots, "essai.git"))
            sortie = self.servir(
                projets=[{"name": "essai", "path": "essai"}],
                depots=depots,
                listen="::1",
            )
        self.assertNotIn("localhost", sortie)
        self.assertIn("URL: git://[::1]", sortie)
        self.assertIn("git://[::1]/essai.git", sortie)

    def test_the_daemon_is_never_started_by_these_tests(self):
        """Contrôle du banc : un Execute non remplacé lancerait un vrai
        démon et cette épreuve ne rendrait jamais la main."""
        self.assertTrue(hasattr(GLS, "Execute"))


class TestLaCommandeNExecuteRien(unittest.TestCase):
    def test_it_renders_a_string(self):
        """C'est ce qui permet de l'éprouver sans lancer de démon."""
        self.assertIsInstance(GLS.daemon_command(DEPOTS, PORT), str)

    def test_the_path_and_the_port_travel_whole(self):
        cmd = GLS.daemon_command(DEPOTS, 4242)
        self.assertIn(f"--base-path={DEPOTS}", cmd)
        self.assertIn("--port=4242", cmd)
        self.assertTrue(cmd.endswith(DEPOTS))

    def test_the_builder_touches_nothing(self):
        chemin = os.path.join(RACINE, "script", "git", "git_local_server.py")
        with open(chemin, encoding="utf-8") as fichier:
            arbre = ast.parse(fichier.read())
        corps = [
            noeud
            for noeud in ast.walk(arbre)
            if isinstance(noeud, ast.FunctionDef)
            and noeud.name == "daemon_command"
        ]
        self.assertEqual(1, len(corps))
        noms = [
            noeud.func.id
            for noeud in ast.walk(corps[0])
            if isinstance(noeud, ast.Call) and isinstance(noeud.func, ast.Name)
        ]
        for interdit in ("print", "exec", "eval", "open"):
            self.assertNotIn(interdit, noms)


if __name__ == "__main__":
    unittest.main()
