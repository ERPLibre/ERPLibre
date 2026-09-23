#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La configuration d'une instance Lima, et la lecture de son inventaire.

CES ÉPREUVES TIENNENT CE QU'ON COMPOSE ET CE QU'ON ANALYSE — pas ce que
l'outil en fait. La distinction n'est pas théorique : une description
d'instance a passé ces épreuves, s'est relue en YAML, et a été refusée au
démarrage parce que le champ « arch » a son propre vocabulaire. C'est
`long_test/lima_confront.py` qui mesure cette moitié-là.

Le rendu est écrit ligne à ligne pour rester lisible ; il est donc relu ici
par un analyseur YAML, qui rattrape ce que l'écriture manuelle risque de
casser.
"""

import os
import sys
import unittest

import yaml

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from script import posture as P  # noqa: E402
from script.posture import plan as plan  # noqa: E402
from script.vm import lima as L  # noqa: E402

IMAGE = "https://exemple.invalid/ubuntu-24.04-arm64.img"


class TestLeRenduSeRelit(unittest.TestCase):
    """Écrit à la main pour rester commentable, relu par un analyseur."""

    def rendu(self, **kw):
        return yaml.safe_load(L.render_config(IMAGE, **kw))

    def test_it_is_valid_yaml_on_both_systems(self):
        for macos in (False, True):
            with self.subTest(macos=macos):
                self.assertIsInstance(self.rendu(macos=macos), dict)

    def test_the_image_and_the_size_are_what_was_asked(self):
        lu = self.rendu(cpus=8, memory="16GiB", disk="120GiB")
        self.assertEqual(IMAGE, lu["images"][0]["location"])
        self.assertEqual(8, lu["cpus"])
        self.assertEqual("16GiB", lu["memory"])
        self.assertEqual("120GiB", lu["disk"])

    def test_the_architecture_travels_where_it_matters(self):
        lu = self.rendu(arch="aarch64")
        self.assertEqual("aarch64", lu["arch"])
        self.assertEqual("aarch64", lu["images"][0]["arch"])

    def test_nothing_of_the_host_is_ever_mounted(self):
        """Lima monte le répertoire personnel par défaut : une VM censée
        être confinée y lirait tout ce que l'utilisateur possède, sans
        qu'une seule règle réseau soit en cause."""
        for macos in (False, True):
            with self.subTest(macos=macos):
                self.assertEqual([], self.rendu(macos=macos)["mounts"])

    def test_the_host_keys_stay_on_the_host_by_default(self):
        """Le canal d'exec passe par la clé que l'outil génère : l'invité
        n'a pas à connaître les identités de qui le lance."""
        self.assertFalse(self.rendu()["ssh"]["loadDotSSHPubKeys"])
        self.assertTrue(
            self.rendu(load_host_keys=True)["ssh"]["loadDotSSHPubKeys"]
        )


class TestLeJetonDArchitecture(unittest.TestCase):
    """Le champ « arch » d'une instance a son propre vocabulaire.

    Le dépôt dit « amd64 », comme les images Ubuntu. L'outil, lui, n'accepte
    que [x86_64 aarch64 armv7l ppc64le riscv64 s390x] et refuse le
    DÉMARRAGE sur tout autre jeton — une configuration qui se relit
    parfaitement en YAML ne démarre donc pas pour autant.

    Les deux mots voyagent dans le même appel : l'URL d'image porte l'un,
    le champ porte l'autre. C'est ce qui rend la traduction nécessaire au
    point de passage plutôt que chez chaque appelant.
    """

    # Ce que l'outil accepte. Il nomme lui-même cette liste en refusant
    # un jeton qui n'y est pas, ce qui la rend vérifiable sans documentation.
    ACCEPTES = ("x86_64", "aarch64", "armv7l", "ppc64le", "riscv64", "s390x")

    def test_the_repo_tokens_land_in_the_accepted_set(self):
        for jeton in ("amd64", "x86_64", "arm64", "aarch64"):
            with self.subTest(jeton=jeton):
                self.assertIn(L.config_arch(jeton), self.ACCEPTES)

    def test_the_rendered_field_never_says_amd64(self):
        """« amd64 » rendu tel quel fait échouer le démarrage."""
        rendu = L.render_config("http://host.invalid/i.img", arch="amd64")
        self.assertNotIn("amd64", rendu)
        self.assertIn("arch: x86_64", rendu)

    def test_both_arch_fields_agree(self):
        """Le champ du haut et celui de l'image sont le MÊME vocabulaire ;
        n'en traduire qu'un laisserait l'autre refusé."""
        rendu = L.render_config("http://host.invalid/i.img", arch="arm64")
        self.assertEqual(2, rendu.count("aarch64"))
        self.assertNotIn("arm64\n", rendu)

    def test_an_image_url_keeps_its_own_spelling(self):
        """L'image s'appelle « amd64 » chez son éditeur ; traduire l'URL
        pointerait vers un fichier qui n'existe pas."""
        url = "http://host.invalid/img-amd64.img"
        self.assertIn(url, L.render_config(url, arch="amd64"))

    def test_an_unknown_token_passes_through(self):
        """L'outil nomme sa liste en refusant ; une correspondance devinée
        ici ferait démarrer une VM d'une autre architecture, ou échouer
        plus loin sans dire pourquoi."""
        self.assertEqual("mips64", L.config_arch("mips64"))

    def test_no_arch_asked_writes_no_field(self):
        rendu = L.render_config("http://host.invalid/i.img")
        self.assertNotIn("arch:", rendu)


class TestCeQuiNExistePasPartout(unittest.TestCase):
    """Deux réglages font ÉCHOUER le démarrage là où ils n'existent pas."""

    def rendu(self, **kw):
        return yaml.safe_load(L.render_config(IMAGE, **kw))

    def test_the_apple_engine_is_named_only_on_macos(self):
        self.assertEqual(L.VM_TYPE_MACOS, self.rendu(macos=True)["vmType"])
        self.assertNotIn("vmType", self.rendu(macos=False))

    def test_a_reachable_address_is_asked_for_only_on_macos(self):
        """Elle passe par socket_vmnet, qui n'existe pas ailleurs."""
        self.assertIn("networks", self.rendu(macos=True, reachable=True))
        self.assertNotIn("networks", self.rendu(macos=False, reachable=True))

    def test_without_asking_there_is_no_network_block(self):
        """Contrôle positif : le bloc n'est pas systématique."""
        self.assertNotIn("networks", self.rendu(macos=True))


class TestCeQueLaConfigurationNeTientPas(unittest.TestCase):
    """Une configuration muette sur ce qu'elle n'applique pas fait croire à
    un confinement qui n'existe pas."""

    def test_no_posture_promises_nothing(self):
        """`unenforceable` répond « que promet cette POSTURE que la
        configuration ne tient pas ». Sans posture, pas de promesse."""
        self.assertEqual((), L.unenforceable(None))

    def test_what_the_rendered_config_offers_is_read_in_its_text(self):
        """TROIS QUESTIONS VOISINES, et un écran de création a besoin de
        celle-ci. Sur macOS l'adresse joignable est POSSIBLE — donc
        `host_limits` dit « rien ne manque » — et pourtant elle n'est pas
        là si personne ne l'a demandée. L'écran annoncerait « joignable »
        sur une instance qui ne l'est pas."""
        sans = L.render_config("https://exemple.invalid/i.img", macos=True)
        self.assertEqual(("reachable-address",), L.config_limits(sans))
        self.assertEqual((), L.host_limits(macos=True))

    def test_asking_for_it_on_macos_makes_it_offered(self):
        """Contrôle positif : toujours répondre « manquant » retirerait
        l'information."""
        avec = L.render_config(
            "https://exemple.invalid/i.img", macos=True, reachable=True
        )
        self.assertEqual((), L.config_limits(avec))

    def test_asking_for_it_elsewhere_does_not_make_it_offered(self):
        """La demande est IGNORÉE hors macOS plutôt que d'écrire un bloc
        qui ferait échouer le démarrage — donc elle reste manquante, et le
        dire est tout l'intérêt de lire le texte."""
        ailleurs = L.render_config(
            "https://exemple.invalid/i.img", macos=False, reachable=True
        )
        self.assertEqual(("reachable-address",), L.config_limits(ailleurs))

    def test_reading_the_text_cannot_drift_from_writing_it(self):
        """Le bloc est UNE constante : deux littéraux voisins cesseraient
        de correspondre au premier ajustement."""
        avec = L.render_config(
            "https://exemple.invalid/i.img", macos=True, reachable=True
        )
        self.assertIn(L.NETWORK_SHARED, avec)

    def test_nothing_rendered_is_not_taken_for_reachable(self):
        self.assertEqual(("reachable-address",), L.config_limits(""))
        self.assertEqual(("reachable-address",), L.config_limits(None))

    def test_the_host_limit_is_a_separate_question(self):
        """Un écran qui montre une configuration AVANT de la jouer n'a pas
        encore de posture, et `unenforceable` ne lui dirait donc RIEN — ce
        qui laisserait croire une instance joignable."""
        self.assertEqual(("reachable-address",), L.host_limits(macos=False))
        self.assertEqual((), L.host_limits(macos=True))

    def test_the_posture_answer_takes_its_host_limit_from_there(self):
        """Une seule source : deux copies du même constat divergeraient au
        premier changement de l'hôte."""
        for nom in P.posture_names():
            with self.subTest(posture=nom):
                repondu = L.unenforceable(P.get_posture(nom), macos=False)
                for borne in L.host_limits(macos=False):
                    self.assertIn(borne, repondu)

    def test_cutting_egress_is_beyond_an_instance_file(self):
        """Le réseau en mode utilisateur donne TOUJOURS la sortie, et aucun
        réglage d'instance ne la retire."""
        self.assertIn(
            "egress-none",
            L.unenforceable(P.get_posture("local-only"), macos=True),
        )

    def test_an_allowlist_is_beyond_it_too(self):
        """Elle se pose dans l'invité, pas dans la description."""
        self.assertIn(
            "destinations-bounded",
            L.unenforceable(P.get_posture("paranoid"), macos=True),
        )

    def test_a_reachable_address_is_missing_off_macos(self):
        self.assertIn(
            "reachable-address", L.unenforceable(P.get_posture("open"))
        )
        self.assertNotIn(
            "reachable-address",
            L.unenforceable(P.get_posture("open"), macos=True),
        )

    def test_the_freest_posture_is_fully_holdable_on_macos(self):
        """Contrôle positif : tout déclarer manquant ne prouverait rien."""
        self.assertEqual(
            (), L.unenforceable(P.get_posture("open"), macos=True)
        )

    def test_every_posture_gets_an_answer(self):
        for nom in P.posture_names():
            with self.subTest(posture=nom):
                self.assertIsInstance(
                    L.unenforceable(P.get_posture(nom), macos=True), tuple
                )


class TestLesReglesPoseesDansLInvite(unittest.TestCase):
    """La liste blanche se pose DANS L'INVITÉ, pas dans la description.

    `unenforceable` le dit depuis toujours — « destinations-bounded » — et
    sa docstring nomme la sortie : « l'appelant décide : renoncer, ou poser
    le verrou ailleurs — dans l'invité, où il attrape ce que la
    configuration ne peut pas ». Le provisionnement d'instance EST cet
    ailleurs, et il manquait.

    Les chemins, les modes et la commande d'amorçage viennent du paquet
    posture. Ce module-ci PEUT l'importer, là où le moteur qemu ne le peut
    pas — il se charge sans le dépôt sur son chemin d'import — et c'est
    pourquoi la recopie est assumée là-bas et interdite ici.
    """

    REGLES = "table inet erplibre { chain output { policy drop; } }\n"

    def rendu(self, **kw):
        return L.render_config(
            "img", provision_script=plan.provision_script(self.REGLES), **kw
        )

    def test_no_rules_means_no_provisioning_at_all(self):
        """Un bloc vide se lirait comme un provisionnement qui a tourné."""
        self.assertNotIn("provision:", L.render_config("img"))

    def test_the_block_is_valid_yaml_like_the_rest(self):
        charge = yaml.safe_load(self.rendu())
        self.assertEqual(1, len(charge["provision"]))
        self.assertEqual("system", charge["provision"][0]["mode"])

    def test_the_rules_reach_the_guest_verbatim(self):
        charge = yaml.safe_load(self.rendu())
        self.assertIn(self.REGLES.strip(), charge["provision"][0]["script"])

    def test_the_paths_come_from_the_posture_package(self):
        """Recopiés ici, ils divergeraient du jour où le paquet les change,
        et l'invité chargerait un fichier que personne n'écrit."""
        script = yaml.safe_load(self.rendu())["provision"][0]["script"]
        self.assertIn(plan.RULES_PATH, script)
        self.assertIn(plan.UNIT_PATH, script)

    def test_the_unit_text_comes_from_there_too(self):
        script = yaml.safe_load(self.rendu())["provision"][0]["script"]
        self.assertIn(plan.unit_text().strip(), script)

    def test_it_arms_and_loads_in_that_order(self):
        """Armer sans charger laisse sortir jusqu'au premier redémarrage ;
        charger sans armer laisse sortir à partir du deuxième."""
        script = yaml.safe_load(self.rendu())["provision"][0]["script"]
        self.assertIn(plan.first_boot_command(), script)

    def test_the_rules_file_is_born_owner_only(self):
        """Il porte les adresses du site. Une redirection shell ne prend
        pas de mode : c'est le masque qui décide, et un chmod APRÈS
        laisserait le fichier lisible le temps de son écriture."""
        script = yaml.safe_load(self.rendu())["provision"][0]["script"]
        attendu = f"{0o666 ^ int(plan.RULES_MODE, 8):04o}"
        self.assertIn(f"umask {attendu}", script)
        self.assertEqual("0600", plan.RULES_MODE)

    def test_blank_rules_pose_nothing(self):
        """Un fichier vide se chargerait sans rien appliquer, et l'instance
        se lirait comme confinée. Le refus vit dans le composeur, et ce
        module ne voit qu'un script vide — ce qui suffit à ne rien écrire."""
        self.assertEqual("", plan.provision_script("  \n "))
        self.assertNotIn(
            "provision:", L.render_config("img", provision_script="  \n ")
        )


class TestLireLInventaire(unittest.TestCase):
    """Deux formes acceptées, et ce n'est pas de l'indécision : selon la
    version, l'inventaire rend un objet par ligne ou un tableau unique.
    Parier sur l'une rendrait une liste vide sur l'autre — et une liste vide
    se lit comme « aucune instance », ce qui est un mensonge tranquille."""

    LIGNES = (
        '{"name":"a","status":"Running","arch":"aarch64",'
        '"sshLocalPort":60022}\n'
        '{"name":"b","status":"Stopped"}'
    )
    TABLEAU = (
        '[{"name":"a","status":"Running"},{"name":"b","status":"Stopped"}]'
    )

    def test_one_object_per_line_is_read(self):
        vues = L.parse_instances(self.LIGNES)
        self.assertEqual(["a", "b"], [i.name for i in vues])
        self.assertEqual("60022", vues[0].ssh_port)

    def test_a_single_array_is_read_too(self):
        self.assertEqual(
            ["a", "b"], [i.name for i in L.parse_instances(self.TABLEAU)]
        )

    def test_both_forms_agree_on_what_runs(self):
        for nom, texte in (("lignes", self.LIGNES), ("tableau", self.TABLEAU)):
            with self.subTest(forme=nom):
                vues = L.parse_instances(texte)
                self.assertEqual(
                    [True, False], [L.is_running(i) for i in vues]
                )

    def test_a_truncated_line_does_not_lose_the_others(self):
        """Une instance en cours de création peut produire une ligne
        partielle ; perdre les autres pour elle serait pire."""
        vues = L.parse_instances(self.LIGNES + "\n{ tronqué")
        self.assertEqual(["a", "b"], [i.name for i in vues])

    # Ce que l'outil écrit quand il n'a AUCUNE instance : un avertissement
    # au format logfmt, sur la sortie STANDARD, et un code de retour 0.
    # L'horodatage est neutralisé — c'est la forme qui porte le fait.
    VIDE_BAVARD = (
        'time="0000-00-00T00:00:00-00:00" level=warning'
        ' msg="No instance found. Run `limactl create` to create an'
        ' instance."'
    )

    def test_an_empty_inventory_is_not_an_empty_output(self):
        """Un inventaire vide ARRIVE bavard, et par la bonne sortie.

        Juger « aucune instance » sur une sortie vide ne tient donc pas :
        la ligne n'est pas du JSON, et un analyseur qui la laisserait
        remonter ferait lever là où le menu attend un tuple.
        """
        self.assertEqual((), L.parse_instances(self.VIDE_BAVARD))

    def test_a_warning_line_never_becomes_an_instance(self):
        """Une ligne de journal n'a pas de champ « name » ; la prendre pour
        une instance ferait proposer d'en démarrer une qui n'existe pas."""
        vues = L.parse_instances(self.VIDE_BAVARD + "\n" + self.LIGNES)
        self.assertEqual(["a", "b"], [i.name for i in vues])

    def test_an_entry_without_a_name_is_dropped(self):
        self.assertEqual((), L.parse_instances('{"status":"Running"}'))

    def test_nothing_reads_as_nothing(self):
        for texte in ("", "   ", None, "pas du json du tout"):
            with self.subTest(texte=texte):
                self.assertEqual((), L.parse_instances(texte))

    def test_the_running_state_is_read_without_case(self):
        """La valeur est un mot capitalisé ; un jour minuscule ferait
        passer une instance vivante pour éteinte."""
        for mot in ("Running", "running", "RUNNING"):
            with self.subTest(mot=mot):
                vues = L.parse_instances('{"name":"a","status":"%s"}' % mot)
                self.assertTrue(L.is_running(vues[0]))

    def test_anything_else_is_not_running(self):
        for mot in ("Stopped", "Broken", ""):
            with self.subTest(mot=mot):
                vues = L.parse_instances('{"name":"a","status":"%s"}' % mot)
                self.assertFalse(L.is_running(vues[0]))

    def test_finding_by_name(self):
        vues = L.parse_instances(self.LIGNES)
        self.assertEqual("b", L.find(vues, "b").name)
        self.assertIsNone(L.find(vues, "jamais-vue"))
        self.assertIsNone(L.find((), "a"))


class TestElleNeLanceRien(unittest.TestCase):
    def test_the_module_runs_nothing_and_prints_nothing(self):
        import ast

        chemin = os.path.join(RACINE, "script", "vm", "lima.py")
        with open(chemin, encoding="utf-8") as handle:
            arbre = ast.parse(handle.read())
        noms = [
            n.func.id
            for n in ast.walk(arbre)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        ]
        self.assertTrue(noms, "aucun appel lu : rien n'est prouvé")
        for interdit in ("print", "input", "run", "system", "Popen"):
            self.assertNotIn(interdit, noms)


class TestLesCommandesDeLOutil(unittest.TestCase):
    """Rendues et non exécutées : c'est ce qui les rend éprouvables sans
    « limactl », et ce qui permet de les MONTRER avant de les jouer.

    Un ARGV et non une chaîne : sans shell, la question du guillemet ne se
    pose pas. La mise en forme pour l'écran est une fonction à part, et une
    seule.
    """

    def test_the_inventory_asks_for_json(self):
        """La sortie tabulée change de colonnes selon la version :
        l'analyser reviendrait à parier sur une mise en page."""
        self.assertIn("--json", L.list_argv())

    def test_starting_refuses_any_prompt(self):
        """Sans cela, l'outil ouvre une conversation — un éditeur, une
        question — et un menu se fige sur une invite que nul ne voit."""
        self.assertIn(L.SANS_INVITE, L.start_argv("essai"))

    def test_starting_with_a_config_puts_it_last(self):
        argv = L.start_argv("essai", "/tmp/essai.yaml")
        self.assertEqual("/tmp/essai.yaml", argv[-1])
        self.assertIn("essai", argv)

    def test_starting_without_a_config_carries_no_path(self):
        """Contrôle positif : un chemin vide ne doit pas devenir un
        argument vide, que l'outil lirait comme un fichier introuvable."""
        argv = L.start_argv("essai")
        self.assertNotIn("", argv)
        self.assertEqual(L.SANS_INVITE, argv[-1])

    def test_stopping_and_deleting_ask_nothing(self):
        """Leur question se poserait là où la sortie n'est plus lue, ce qui
        revient à ne rien demander."""
        self.assertIn(L.SANS_QUESTION, L.stop_argv("essai"))
        self.assertIn(L.SANS_QUESTION, L.delete_argv("essai"))

    def test_a_shell_without_a_command_is_a_session(self):
        """« bash -c » y attendrait une commande qui ne vient pas."""
        argv = L.shell_argv("essai")
        self.assertNotIn("bash", argv)
        self.assertEqual(["essai"], argv[-1:])

    def test_a_shell_with_a_suite_wraps_it(self):
        """L'outil exécute des ARGUMENTS : « a && b » lui arriverait comme
        une liste de mots."""
        argv = L.shell_argv("essai", "a && b")
        self.assertEqual(["--", "bash", "-c", "a && b"], argv[-4:])

    def test_every_command_names_the_same_binary(self):
        """Un jour où il s'appellerait autrement, il n'y a qu'un endroit à
        toucher — et cette épreuve le tient."""
        for argv in (
            L.list_argv(),
            L.start_argv("essai"),
            L.stop_argv("essai"),
            L.delete_argv("essai"),
            L.shell_argv("essai"),
        ):
            with self.subTest(argv=argv[:2]):
                self.assertEqual(L.LIMACTL, argv[0])

    def test_the_instance_name_travels_whole(self):
        """Découper sur l'espace viserait une autre instance, ou aucune."""
        for rendu in (L.start_argv, L.stop_argv, L.delete_argv, L.shell_argv):
            with self.subTest(rendu=rendu.__name__):
                self.assertIn("un nom", rendu("un nom"))

    def test_the_lifecycle_vocabulary_excludes_suspend(self):
        """Un arrêt n'est PAS une pause : confondre les deux perd l'état
        d'une VM qu'on croyait seulement mettre de côté. C'est pourquoi
        `verbs.power_command` refuse ce backend."""
        self.assertEqual(("start", "stop", "delete"), L.LIFECYCLE)
        self.assertNotIn("suspend", L.LIFECYCLE)
        self.assertNotIn("resume", L.LIFECYCLE)


class TestCeQuOnMontreAvantDeJouer(unittest.TestCase):
    def test_a_value_with_a_space_is_shown_quoted(self):
        """Sans guillemet, la ligne affichée se relirait comme deux
        arguments : elle ne serait plus celle qui s'exécute, ce qui est
        pire que ne rien montrer."""
        montre = L.display(L.stop_argv("un nom"))
        self.assertIn("'un nom'", montre)

    def test_a_plain_command_is_shown_plainly(self):
        self.assertEqual("limactl list --json", L.display(L.list_argv()))

    def test_nothing_is_an_empty_line_and_not_a_crash(self):
        self.assertEqual("", L.display(()))
        self.assertEqual("", L.display(None))

    def test_what_is_shown_reassembles_into_what_runs(self):
        """Le contrôle qui compte : la ligne montrée doit se redécouper en
        l'argv exact, sinon on montre autre chose que ce qu'on joue."""
        import shlex

        for argv in (
            L.start_argv("un nom", "/tmp/un chemin.yaml"),
            L.shell_argv("essai", "a && b"),
            L.delete_argv("essai"),
        ):
            with self.subTest(argv=argv[:2]):
                self.assertEqual(argv, shlex.split(L.display(argv)))


class TestLaConfrontationNecritAucuneCommande(unittest.TestCase):
    """Une copie dans `long_test/` ferait confronter le script à lui-même.

    Il passerait pendant que le code livré porte une autre forme — et
    « non éprouvé » veut dire précisément qu'on ne sait pas laquelle est la
    bonne. Toute commande doit donc venir de `script.vm.lima`.
    """

    @staticmethod
    def source():
        chemin = os.path.join(RACINE, "long_test", "lima_confront.py")
        with open(chemin, encoding="utf-8") as fichier:
            return fichier.read()

    def test_the_confrontation_exists_and_was_read(self):
        self.assertIn("lima", self.source())

    @staticmethod
    def _litteraux_de_code(source):
        """Les chaînes du CODE qui nomment l'outil, docstrings
        exclues. La mécanique vit dans `test/code_literals.py` : ce
        contrôle a été recopié trois fois, et la troisième copie
        levait un TypeError sur une expression conditionnelle.
        """
        from code_literals import literals_matching

        return literals_matching(source, "limactl")

    def test_the_ast_filter_sees_the_docstrings_it_must_ignore(self):
        """Contrôle du banc : un filtre qui exclurait TOUT passerait
        l'épreuve suivante sans avoir rien lu."""
        exemple = 'x = "limactl list"\n\n\ndef f():\n    "limactl doc"\n'
        self.assertEqual(["limactl list"], self._litteraux_de_code(exemple))

    def test_it_writes_no_limactl_literal_of_its_own(self):
        litteraux = self._litteraux_de_code(self.source())
        self.assertEqual([], litteraux, litteraux)

    def test_it_calls_the_renderers(self):
        source = self.source()
        for rendu in ("list_argv", "start_argv", "stop_argv", "delete_argv"):
            with self.subTest(rendu=rendu):
                self.assertIn(f"lima.{rendu}(", source)


if __name__ == "__main__":
    unittest.main()
