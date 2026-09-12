#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce que le câblage du menu assistant doit tenir.

Six sites de `todo.py` participent à un sous-menu — l'import, les bases de la
classe, l'étiquette du fil d'Ariane, les deux listes jumelles du menu parent,
et les clés de traduction. Aucun n'échoue bruyamment quand il manque : une
entrée mal branchée appelle simplement autre chose, une étiquette absente
retire une miette du fil, et `t()` rend une clé inconnue telle quelle, donc une
faute de frappe s'affiche en clair à l'utilisateur sans que rien ne lève.

Ce fichier est le SEUL de la famille assistant à importer `TODO` : cet import
coûte près d'une seconde et imprime sur la sortie, et le faire payer aux neuf
autres fichiers rendrait la boucle d'écriture inutilisable. La contrepartie est
vérifiée ici même — le paquet, lui, doit rester importable seul.

`_menu_header()` enregistre une télémétrie dans `~/.erplibre` : tout test qui
appelle une méthode de menu la neutralise, sinon il écrit pour de vrai.
"""
from __future__ import annotations

import ast
import collections
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

from script.todo.todo_i18n import t

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MENU = os.path.join(RACINE, "script", "todo", "assistant_menu.py")


def _litteral(noeud):
    """La chaîne d'un nœud constant, ou `None`."""
    if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
        return noeud.value
    return None


def cles_de_traduction(chemin):
    """Les clés littérales que le fichier confie à `t()`, directement ou non.

    Lit l'arbre syntaxique plutôt que le texte : une expression régulière
    attraperait aussi les appels commentés et raterait les appels sur
    plusieurs lignes.

    Deux formes comptent. `t("clé")` est la forme directe. `_llm_count(n,
    "singulier", "pluriel")` en est une INDIRECTE : ses deux derniers
    arguments sont des clés que l'accord choisit à l'exécution, et une faute
    de frappe y afficherait « hosts swept » en clair sans que rien ne lève —
    exactement ce que la forme directe protège déjà.
    """
    with open(chemin) as fichier:
        arbre = ast.parse(fichier.read())
    cles = set()
    for noeud in ast.walk(arbre):
        if not isinstance(noeud, ast.Call):
            continue
        cible = noeud.func
        nom = getattr(cible, "id", None) or getattr(cible, "attr", None)
        if nom == "t" and noeud.args:
            valeur = _litteral(noeud.args[0])
            if valeur is not None:
                cles.add(valeur)
        elif nom == "_llm_count" and len(noeud.args) >= 3:
            for argument in noeud.args[1:3]:
                valeur = _litteral(argument)
                if valeur is not None:
                    cles.add(valeur)
    return cles


class Cablage(unittest.TestCase):
    """Les six sites de `todo.py` que le sous-menu réclame."""

    def test_todo_expose_le_sous_menu_llm(self):
        from script.todo.todo import TODO

        self.assertTrue(hasattr(TODO, "prompt_assistant_llm"))

    def test_l_etiquette_de_fil_d_ariane_existe(self):
        """Le fil se dérive de la pile d'appels : une méthode absente de
        `_MENU_LABELS` ne contribue AUCUNE miette, en silence. Le sous-menu
        VPN a été livré ainsi et ne se situe donc nulle part."""
        from script.todo.todo import TODO

        self.assertEqual(TODO._MENU_LABELS.get("prompt_assistant_llm"), "LLM")
        self.assertEqual(TODO._MENU_LABELS.get("prompt_assistant_ia"), "IA")

    def test_un_dispatche_vers_l_ecran_des_agents_seulement(self):
        """Les deux listes du menu parent sont tenues à la main et rien ne
        les rapproche : `[1]` peut afficher une entrée et appeler l'autre."""
        from script.todo.todo import TODO

        todo = TODO()
        with patch.object(TODO, "prompt_assistant_ia") as mock_ia, patch(
            "script.todo.mail.menu.prompt_execute_mail"
        ) as mock_mail, patch("click.prompt", side_effect=["1", "0"]), patch(
            "script.todo.todo_telemetry.record"
        ):
            todo.prompt_assistant()
        mock_ia.assert_called_once_with()
        mock_mail.assert_not_called()

    def test_deux_dispatche_toujours_vers_le_courriel_seulement(self):
        from script.todo.todo import TODO

        todo = TODO()
        with patch.object(TODO, "prompt_assistant_ia") as mock_llm, patch(
            "script.todo.mail.menu.prompt_execute_mail"
        ) as mock_mail, patch("click.prompt", side_effect=["2", "0"]), patch(
            "script.todo.todo_telemetry.record"
        ):
            todo.prompt_assistant()
        mock_mail.assert_called_once()
        mock_llm.assert_not_called()

    def test_le_sous_menu_s_ouvre_sans_aucun_serveur_configure(self):
        """Une machine sans serveur est le cas de la PREMIÈRE utilisation.

        La sonde et le registre sont injectés : le menu ne doit ni ouvrir de
        socket, ni lire la configuration réelle du poste qui lance la suite.
        """
        from script.todo.todo import TODO

        todo = TODO()
        with patch(
            "script.todo.assistant.fingerprint.collect", return_value={}
        ), patch("script.todo.assistant.servers.load", return_value=[]), patch(
            "click.prompt", side_effect=["0"]
        ), patch(
            "script.todo.todo_telemetry.record"
        ):
            todo.prompt_assistant_llm()


class ClesDeTraduction(unittest.TestCase):
    """Ce qu'une clé manquante coûte : du texte anglais brut à l'écran."""

    def test_chaque_cle_du_menu_est_declaree(self):
        from script.todo.todo_i18n import TRANSLATIONS

        cles = cles_de_traduction(MENU)
        self.assertTrue(cles, "aucune clé t() trouvée dans le menu")
        manquantes = sorted(c for c in cles if c not in TRANSLATIONS)
        self.assertEqual(manquantes, [])

    def test_chaque_commande_annoncee_est_traduite(self):
        """« /? » imprime l'aide de chaque commande servie : une aide non
        traduite s'y afficherait en anglais au milieu du français."""
        from script.todo.assistant.chat import COMMANDS
        from script.todo.assistant_menu import COMMANDES_PHASE_1
        from script.todo.todo_i18n import TRANSLATIONS

        self.assertTrue(COMMANDES_PHASE_1)
        for nom in COMMANDES_PHASE_1:
            self.assertIn(nom, COMMANDS)
            self.assertIn(COMMANDS[nom], TRANSLATIONS)


class JournalDuTransport(unittest.TestCase):
    """La conversation ne doit pas être coupée par des lignes de journal.

    `todo.py` pose un gestionnaire sur le logger racine à l'import, et le
    transport HTTP journalise chaque requête en INFO : sans réglage, une ligne
    « HTTP Request: POST … » paraît à chaque réponse du modèle.
    """

    def test_le_transport_du_client_openai_est_silencieux(self):
        """Le nom du transport n'est pas stable : le venv porte `httpx` ET
        `httpx2`, et c'est la version du client `openai` qui décide lequel
        émet. Ce test part du transport RÉELLEMENT importé, pour tomber en
        rouge le jour où le client en change plutôt que de laisser la ligne
        revenir en silence."""
        import logging

        from script.todo.assistant_menu import AssistantMenuMixin

        AssistantMenuMixin._llm_quiet_http()

        import types

        import openai._base_client as base

        # Le client importe son transport sous le nom du paquet, qui est
        # justement ce qui change : on cherche donc tout module dont le nom
        # de tête commence par « httpx », plutôt qu'un attribut fixe.
        noms = {
            valeur.__name__.split(".")[0]
            for valeur in vars(base).values()
            if isinstance(valeur, types.ModuleType)
            and valeur.__name__.split(".")[0].startswith("httpx")
        }
        self.assertTrue(noms, "aucun transport httpx dans le client openai")
        for nom in sorted(noms):
            self.assertGreaterEqual(
                logging.getLogger(nom).getEffectiveLevel(),
                logging.WARNING,
                f"le logger « {nom} » parlerait pendant la conversation",
            )

    def test_les_deux_transports_connus_sont_nommes(self):
        import logging

        from script.todo.assistant_menu import AssistantMenuMixin

        AssistantMenuMixin._llm_quiet_http()
        for nom in ("httpx", "httpx2"):
            self.assertGreaterEqual(
                logging.getLogger(nom).getEffectiveLevel(), logging.WARNING
            )


class Balayage(unittest.TestCase):
    """Ce que le balayage doit atteindre, et ce qu'il ne doit pas taire.

    Un serveur vit souvent sur un réseau que la machine ne PORTE pas,
    joignable par la passerelle. Les deux mécanismes qui semblaient couvrir ce
    cas ne le couvrent pas : la saisie d'une adresse ne prend qu'un hôte, et
    la table de voisinage est link-local, donc elle ne connaît jamais un hôte
    routé. Sans réseau saisi à la main, un tel serveur est hors d'atteinte.
    """

    def _todo(self):
        from script.todo.todo import TODO

        todo = TODO()
        todo._llm_session = {
            "serveur": None,
            "sonde": [],
            "confirmes": set(),
        }
        return todo

    def test_un_reseau_non_porte_est_balayable(self):
        """Aucune interface ne porte ce préfixe, et il doit être planifiable
        quand même : c'est le cas d'un CLI qui tourne dans une VM, dont le
        « réseau local » est celui de l'hyperviseur."""
        from script.todo.assistant import discover as llm_disc

        todo = self._todo()
        vus = {}
        with patch.object(
            llm_disc, "local_networks", return_value=[]
        ), patch.object(llm_disc, "run_ip", return_value=""), patch.object(
            todo, "_qemu_host_addresses", staticmethod(lambda: set())
        ), patch.object(
            todo,
            "_llm_probe_and_keep",
            lambda adresses, **kw: vus.update({"n": len(adresses), "kw": kw}),
        ), patch(
            "click.prompt", side_effect=["198.51.100.0/24", "o"]
        ):
            todo._llm_search_cidr()
        self.assertEqual(vus.get("n"), 254)
        self.assertEqual(vus["kw"]["cible"], "198.51.100.0/24")
        self.assertFalse(vus["kw"]["restreint"])

    def test_le_defaut_est_le_reseau_entier_pas_les_hotes_deja_vus(self):
        """Rétrécir par défaut se retourne : la table de voisinage ne porte
        souvent que la passerelle, le balayage tombe à une adresse, et le
        résumé annonce un réseau vide là où une seule adresse a été vue."""
        from script.todo.assistant import discover as llm_disc

        todo = self._todo()
        vus = {}
        voisinage = "198.51.100.1 dev lien0 lladdr aa:bb:cc:dd:ee:01 REACHABLE"
        with patch.object(
            llm_disc, "run_ip", return_value=voisinage
        ), patch.object(
            todo, "_qemu_host_addresses", staticmethod(lambda: set())
        ), patch.object(
            todo,
            "_llm_probe_and_keep",
            lambda adresses, **kw: vus.update({"n": len(adresses), "kw": kw}),
        ), patch(
            "click.prompt", side_effect=["o"]
        ):
            todo._llm_sweep_cidr("198.51.100.0/24")
        self.assertEqual(vus.get("n"), 254)
        self.assertFalse(vus["kw"]["restreint"])

    def test_la_lettre_v_restreint_et_le_dit(self):
        from script.todo.assistant import discover as llm_disc

        todo = self._todo()
        vus = {}
        voisinage = "198.51.100.1 dev lien0 lladdr aa:bb:cc:dd:ee:01 REACHABLE"
        with patch.object(
            llm_disc, "run_ip", return_value=voisinage
        ), patch.object(
            todo, "_qemu_host_addresses", staticmethod(lambda: set())
        ), patch.object(
            todo,
            "_llm_probe_and_keep",
            lambda adresses, **kw: vus.update({"n": len(adresses), "kw": kw}),
        ), patch(
            "click.prompt", side_effect=["v"]
        ):
            todo._llm_sweep_cidr("198.51.100.0/24")
        self.assertEqual(vus.get("n"), 1)
        self.assertTrue(vus["kw"]["restreint"])

    def test_un_balayage_restreint_sans_trouvaille_le_dit(self):
        """« Aucun serveur sur ce /24 » après une adresse regardée est un
        faux négatif présenté comme un fait."""
        import io
        from contextlib import redirect_stdout

        from script.todo.assistant import discover as llm_disc

        todo = self._todo()
        sortie = io.StringIO()
        with patch.object(llm_disc, "sweep", return_value=[]), redirect_stdout(
            sortie
        ):
            todo._llm_probe_and_keep(
                ["198.51.100.1"], cible="198.51.100.0/24", restreint=True
            )
        texte = sortie.getvalue()
        self.assertIn(t("Only part of that network was swept."), texte)

    def test_un_balayage_complet_sans_trouvaille_ne_le_dit_pas(self):
        import io
        from contextlib import redirect_stdout

        from script.todo.assistant import discover as llm_disc

        todo = self._todo()
        sortie = io.StringIO()
        with patch.object(llm_disc, "sweep", return_value=[]), redirect_stdout(
            sortie
        ):
            todo._llm_probe_and_keep(["198.51.100.1"], cible="198.51.100.0/24")
        self.assertNotIn(
            t("Only part of that network was swept."), sortie.getvalue()
        )

    def test_plus_large_qu_un_slash24_est_refuse(self):
        from script.todo.assistant import discover as llm_disc

        todo = self._todo()
        appels = []
        with patch.object(
            todo, "_qemu_host_addresses", staticmethod(lambda: set())
        ), patch.object(llm_disc, "run_ip", return_value=""), patch.object(
            todo, "_llm_probe_and_keep", lambda *a, **k: appels.append(a)
        ), patch(
            "click.prompt", side_effect=[]
        ):
            todo._llm_sweep_cidr("10.0.0.0/8")
        self.assertEqual(appels, [])


class ReglagesDuBalayage(unittest.TestCase):
    """Les réglages viennent des préférences, et une valeur abîmée n'y passe
    pas.

    Le délai est le seul réglage du balayage qui fabrique des faux négatifs :
    sous mille connexions simultanées, un hôte joignable en une milliseconde
    se manque à cinq centièmes de délai. Une valeur illisible ou négative doit
    donc retomber sur le défaut du module, jamais s'appliquer.
    """

    def test_les_prefs_sont_passees_au_balayage(self):
        from script.todo import todo_prefs
        from script.todo.assistant_menu import AssistantMenuMixin

        with patch.object(
            todo_prefs,
            "get",
            lambda cle, defaut=None: {
                "assistant_sweep_workers": 64,
                "assistant_sweep_timeout": 0.75,
            }[cle],
        ):
            reglages = AssistantMenuMixin._llm_sweep_tuning()
        self.assertEqual(reglages, {"workers": 64, "timeout": 0.75})

    def test_une_valeur_illisible_retombe_sur_le_defaut_du_module(self):
        from script.todo import todo_prefs
        from script.todo.assistant_menu import AssistantMenuMixin

        for mauvais in ("beaucoup", None, -1, 0):
            with patch.object(
                todo_prefs, "get", lambda cle, defaut=None: mauvais
            ):
                reglages = AssistantMenuMixin._llm_sweep_tuning()
            self.assertNotIn("workers", reglages, f"accepté : {mauvais!r}")
            self.assertNotIn("timeout", reglages, f"accepté : {mauvais!r}")

    def test_le_defaut_du_module_ne_suit_pas_le_nombre_de_coeurs(self):
        """Dimensionner par cœurs est l'erreur que ce module refuse : ces
        fils attendent le réseau. Le plafond réel est le nombre de sondes,
        que le balayage applique lui-même."""
        import os

        from script.todo.assistant import discover as llm_disc

        self.assertNotEqual(llm_disc.MAX_WORKERS, os.cpu_count())
        self.assertGreaterEqual(llm_disc.MAX_WORKERS, 1024)
        self.assertNotIn("cpu_count", _source_de_la_decouverte())

    def test_les_prefs_declarent_les_deux_reglages(self):
        from script.todo import todo_prefs

        for cle in ("assistant_sweep_workers", "assistant_sweep_timeout"):
            self.assertIn(cle, todo_prefs.DEFAULTS)


def _source_de_la_decouverte():
    chemin = os.path.join(RACINE, "script", "todo", "assistant", "discover.py")
    with open(chemin) as fichier:
        return fichier.read()


class SessionsClaudeCode(unittest.TestCase):
    """Le câblage de la phase 4, sous « GPT code » et non sous le LLM.

    Une session est un processus adressé par identifiant ; un serveur est un
    hôte adressé par port. Les mêler dans une liste numérotée ferait partager
    des numéros à deux modèles mentaux, et toutes les entrées Claude vivent
    déjà sous ce menu-là.
    """

    def test_todo_expose_le_sous_menu_des_sessions(self):
        from script.todo.todo import TODO

        self.assertTrue(hasattr(TODO, "prompt_claude_sessions"))

    def test_l_etiquette_de_fil_d_ariane_existe(self):
        from script.todo.todo import TODO

        self.assertEqual(
            TODO._MENU_LABELS.get("prompt_claude_sessions"), "Claude Code"
        )

    def _entrees(self):
        """Les entrées affichées par « Assistant › IA », dans l'ordre.

        Le rang d'une entrée n'est PAS écrit dans le test : une section de
        plus le décale, et trois passes de cette fonctionnalité l'ont décalé
        trois fois. Il est donc DÉRIVÉ de l'écran, et le test affirme ce qui
        compte — l'entrée qui montre telle chose appelle telle méthode.
        """
        from script.todo.todo import TODO

        capture = []

        def fausse_aide(self, choices):
            capture.extend(choices)
            return ""

        todo = TODO()
        with patch.object(TODO, "fill_help_info", fausse_aide), patch(
            "click.prompt", side_effect=["0"]
        ), patch("script.todo.todo_telemetry.record"):
            todo.prompt_assistant_ia()
        return [c["prompt_description"] for c in capture if "section" not in c]

    def _rang(self, morceau):
        """Le numéro de l'entrée qui porte ce morceau de libellé."""
        for rang, libelle in enumerate(self._entrees(), start=1):
            if morceau in libelle:
                return rang
        raise AssertionError(f"aucune entrée ne porte « {morceau} »")

    def _dispatche(self, morceau, cible, *, temoin=None):
        """L'entrée qui porte `morceau` appelle-t-elle `cible` ?

        `temoin` nomme une méthode qui ne doit PAS partir, sans quoi un test
        vert ne dirait rien d'un dispatch qui appelle tout.
        """
        from script.todo.todo import TODO

        chiffre = str(self._rang(morceau))
        todo = TODO()
        with patch.object(TODO, cible) as mock_cible, patch.object(
            TODO, temoin or "prompt_execute_rtk"
        ) as mock_temoin, patch(
            "click.prompt", side_effect=[chiffre, "0"]
        ), patch(
            "script.todo.todo_telemetry.record"
        ):
            todo.prompt_assistant_ia()
        mock_cible.assert_called_once_with()
        mock_temoin.assert_not_called()

    def test_le_harnais_claude_ouvre_ses_sessions(self):
        self._dispatche("Claude Code", "prompt_claude_sessions")

    def test_la_telemetrie_ouvre_la_tui(self):
        self._dispatche(t("Agent telemetry (TUI)"), "_agents_telemetrie")

    def test_les_hooks_ouvrent_leur_ecran(self):
        self._dispatche(t("Telemetry hooks"), "_agents_hooks")

    def test_le_disque_ouvre_son_ecran(self):
        self._dispatche(t("Disk and cleanup"), "_agents_disque")

    def test_les_greffons_au_milieu_de_la_chaine(self):
        """Le milieu de la chaîne : c'est là qu'un décalage se cache."""
        self._dispatche(
            t("Claude Code plugins - marketplaces and ERPLibre list"),
            "prompt_execute_claude_plugins",
        )

    def test_la_derniere_entree_reste_joignable(self):
        """Un décalage d'un cran la rendrait injoignable."""
        self._dispatche(
            t("Add an automation with Claude in todo.py"),
            "_claude_add_automation",
        )

    def test_un_numero_au_dela_de_la_liste_ne_lance_rien(self):
        """Les deux listes se construisent ensemble ; rien ne doit dépasser."""
        from script.todo.todo import TODO

        todo = TODO()
        au_dela = str(len(self._entrees()) + 1)
        with patch.object(TODO, "_agents_telemetrie") as mock, patch(
            "click.prompt", side_effect=[au_dela, "0"]
        ), patch("script.todo.todo_telemetry.record"):
            todo.prompt_assistant_ia()
        mock.assert_not_called()

    def test_le_sous_menu_s_ouvre_sans_aucune_session(self):
        """Une machine sans Claude Code n'est pas une panne du menu."""
        from script.todo.todo import TODO

        todo = TODO()
        with patch(
            "script.todo.assistant.claude_sessions.fleet", return_value=[]
        ), patch("click.prompt", side_effect=["0"]), patch(
            "script.todo.todo_telemetry.record"
        ):
            todo.prompt_claude_sessions()

    def test_un_claude_absent_est_un_message_pas_un_plantage(self):
        import io
        from contextlib import redirect_stdout

        from script.todo.todo import TODO

        todo = TODO()
        sortie = io.StringIO()
        with patch("shutil.which", return_value=None), redirect_stdout(sortie):
            todo._claude_questionner([])
            todo._claude_reprendre([])
        self.assertIn(t("claude is not on the PATH."), sortie.getvalue())

    def test_aucune_session_a_reprendre_le_dit(self):
        import io
        from contextlib import redirect_stdout

        from script.todo.todo import TODO

        todo = TODO()
        sortie = io.StringIO()
        with patch("shutil.which", return_value="/usr/bin/claude"), patch(
            "click.prompt", side_effect=["0"]
        ), redirect_stdout(sortie):
            todo._claude_reprendre([])
        self.assertIn(t("No session on this machine."), sortie.getvalue())


class Frontiere(unittest.TestCase):
    """Le paquet doit vivre sans le CLI qui l'appelle."""

    def test_le_paquet_assistant_n_importe_pas_todo(self):
        """Vérifié dans un processus NEUF : ce fichier-ci importe `TODO`, donc
        `sys.modules` le porte déjà et l'assertion passerait ici pour de
        mauvaises raisons.

        Ce que la frontière achète est mesurable : importer `todo.py` coûte
        près d'une seconde et imprime sur la sortie, et neuf fichiers de test
        le paieraient à chaque exécution.
        """
        code = (
            "import sys;"
            "import script.todo.assistant.backends;"
            "import script.todo.assistant.capabilities;"
            "import script.todo.assistant.chat;"
            "import script.todo.assistant.fingerprint;"
            "import script.todo.assistant.servers;"
            "print('script.todo.todo' in sys.modules)"
        )
        res = subprocess.run(
            [sys.executable, "-c", code],
            cwd=RACINE,
            capture_output=True,
            text=True,
            env={**os.environ, "PYTHONPATH": RACINE},
            timeout=60,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(res.stdout.strip(), "False", res.stdout)


class LesAgentsDetaches(unittest.TestCase):
    """Ce que « un agent d'arrière-plan » veut dire, et ce que ça exclut.

    La flotte réunit deux sources qui ne disent pas la même chose : le
    registre annonce ce qui TOURNE, un balayage des transcriptions annonce ce
    qui se REPREND. Une session dormante n'a donc ni genre ni processus, et
    la compter comme un agent détaché affichait « 1 agent » sur une machine
    qui n'en portait aucun — ce que seul le pilotage de l'écran a montré.
    """

    def _detaches(self, *sessions):
        from script.todo.assistant_menu import AssistantMenuMixin

        return AssistantMenuMixin._claude_detaches(list(sessions))

    def _session(self, cle, kind, live):
        from script.todo.assistant.claude_sessions import Session

        return Session(session_id=cle, kind=kind, live=live)

    def test_a_live_background_agent_counts(self):
        detaches = self._detaches(self._session("a", "background", True))
        self.assertEqual([s.session_id for s in detaches], ["a"])

    def test_a_terminal_never_counts(self):
        """Proposer « arrêter » sur la fenêtre où l'on travaille serait un
        piège, et c'est le genre qui l'écarte."""
        self.assertEqual(
            self._detaches(self._session("a", "interactive", True)), []
        )

    def test_a_dormant_session_is_not_an_agent(self):
        """Ni genre ni processus : c'est un fichier, pas un agent."""
        self.assertEqual(self._detaches(self._session("a", "", False)), [])

    def test_an_exited_background_agent_is_not_listed_either(self):
        """Il existe — `rm` sait encore nettoyer son arbre — mais il faut
        `claude agents --all` pour le voir, et la flotte ne le demande pas."""
        self.assertEqual(
            self._detaches(self._session("a", "background", False)), []
        )

    def test_the_order_of_the_fleet_is_kept(self):
        detaches = self._detaches(
            self._session("a", "interactive", True),
            self._session("b", "background", True),
            self._session("c", "detached", True),
        )
        self.assertEqual([s.session_id for s in detaches], ["b", "c"])


class LeCablageDesAgents(unittest.TestCase):
    """Les trois entrées d'arrière-plan mènent-elles où elles disent ?"""

    def _dispatche(self, chiffre, cible):
        from script.todo.todo import TODO

        todo = TODO()
        with patch.object(TODO, cible) as mock_cible, patch.object(
            TODO, "_claude_questionner"
        ) as mock_temoin, patch(
            "script.todo.assistant.claude_sessions.fleet", return_value=[]
        ), patch(
            "click.prompt", side_effect=[chiffre, "0"]
        ), patch(
            "script.todo.todo_telemetry.record"
        ):
            todo.prompt_claude_sessions()
        mock_cible.assert_called_once_with()
        mock_temoin.assert_not_called()

    def test_quatre_attache(self):
        self._dispatche("4", "_claude_attacher")

    def test_cinq_lit_le_journal(self):
        self._dispatche("5", "_claude_journal")

    def test_six_gere(self):
        self._dispatche("6", "_claude_gerer")


class LaVueDUneSession(unittest.TestCase):
    """`displayable()` fixe ce qu'une session a le droit de montrer.

    L'écran ne lit donc pas la session, il lit cette vue — et une clé qui n'y
    est pas lève un `KeyError` qui remonte jusqu'au CLI. Rien ne le signale à
    l'écriture : les deux vocabulaires se ressemblent, `cwd` du côté de la
    session et `dir` du côté de la vue, et seul le chemin de menu qui touche
    la ligne fautive le découvre. Le test lit donc la SOURCE plutôt que
    d'espérer qu'un test passe par chaque écran.
    """

    def _cles_lues(self):
        """Les clés que la source indexe sur un nom commençant par « vue »."""
        with open(MENU, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read())
        cles = set()
        for noeud in ast.walk(arbre):
            if not isinstance(noeud, ast.Subscript):
                continue
            cible = noeud.value
            if not isinstance(cible, ast.Name) or cible.id != "vue":
                continue
            litteral = _litteral(noeud.slice)
            if litteral is not None:
                cles.add(litteral)
        return cles

    def test_every_key_the_screen_reads_is_one_the_view_produces(self):
        from script.todo.assistant import claude_sessions as cs

        vue = cs.displayable(
            cs.Session(session_id="a" * 32, pid=1, cwd="/un/depot")
        )
        lues = self._cles_lues()
        self.assertTrue(lues, "aucune lecture de vue trouvée dans la source")
        self.assertEqual(lues - set(vue), set())


class LeDemasquageNeLevePasUnSecret(unittest.TestCase):
    """Le paquet tient DEUX paliers, et ils ne disent pas la même chose.

    « Masqué » veut dire « ce nom n'est pas déclaré », et se lève à la
    demande — c'est la soupape d'une liste blanche, qui masque par
    construction toute variable neuve et utile. « Secret » veut dire « la
    longueur même est un renseignement », et ne se lève pas. Les confondre
    laisse taper le nom d'une clé d'API pour la voir en clair, ce qui rend
    inutile tout le reste du module.

    Le témoin est inventé, et sa présence dans l'entrée est ce qui prouve
    qu'il ne ressort pas.
    """

    TEMOIN = "valeur-de-secret-qui-ne-doit-pas-sortir"

    def _demander(self, nom):
        """Taper `nom` à l'invite de démasquage. Rend (sorti, dévoilés)."""
        from script.todo.assistant.agents import environnement as env
        from script.todo.todo import TODO

        liste = [
            env.juger("ANTHROPIC_API_KEY", self.TEMOIN),
            env.juger("UNE_INCONNUE", self.TEMOIN),
        ]
        session = collections.namedtuple("S", "pid")(1234)
        demandes = []

        def faux_devoile(pid, quoi):
            demandes.append(quoi)
            return self.TEMOIN

        sorti = []
        with patch("click.prompt", return_value=nom), patch(
            "builtins.print",
            side_effect=lambda *a, **k: sorti.append(
                " ".join(str(x) for x in a)
            ),
        ), patch.object(env, "devoile", faux_devoile):
            TODO._claude_devoiler(TODO(), session, liste, env)
        return "\n".join(sorti), demandes

    def test_a_secret_is_refused_and_never_read(self):
        sorti, demandes = self._demander("ANTHROPIC_API_KEY")
        self.assertEqual(demandes, [])
        self.assertNotIn(self.TEMOIN, sorti)

    def test_the_refusal_says_why(self):
        """« Aucune variable de ce nom » serait faux : elle existe."""
        sorti, _ = self._demander("ANTHROPIC_API_KEY")
        self.assertIn(t("A secret is never unmasked here."), sorti)

    def test_an_ordinary_masked_variable_still_lifts(self):
        """Refuser trop retirerait la soupape, qui a sa raison d'être."""
        sorti, demandes = self._demander("UNE_INCONNUE")
        self.assertEqual(demandes, ["UNE_INCONNUE"])
        self.assertIn(self.TEMOIN, sorti)

    def test_nothing_but_secrets_opens_no_prompt(self):
        """Un secret n'est pas un candidat au démasquage.

        Proposer « démasquer une variable » sur une liste qui n'en compte que
        d'inaccessibles invite à taper un nom pour se faire refuser : la
        soupape ne s'ouvre que s'il y a quelque chose à lever.
        """
        from script.todo.assistant.agents import environnement as env
        from script.todo.todo import TODO

        liste = [env.juger("ANTHROPIC_API_KEY", self.TEMOIN)]
        session = collections.namedtuple("S", "pid")(1234)
        with patch("click.prompt") as invite, patch("builtins.print"):
            TODO._claude_devoiler(TODO(), session, liste, env)
        invite.assert_not_called()


class LEnvironnementNEstLuQueDUnProcessusVivant(unittest.TestCase):
    """Un pid se réemploie, et une session reprenable garde le sien.

    `/proc/<pid>/environ` lu sur une session éteinte montre l'environnement
    d'un AUTRE processus, sous le nom de celle-ci. L'écran demande donc la
    vivacité, que la flotte établit déjà en comparant le moment de démarrage
    du processus, et non la simple présence d'un pid.
    """

    def _contexte(self, *, live):
        from script.todo.assistant import claude_sessions as cs
        from script.todo.assistant.agents import environnement as env
        from script.todo.todo import TODO

        session = cs.Session(session_id="a" * 32, pid=4321, live=live)
        vus = []

        def fausses_variables(pid, **kw):
            vus.append(pid)
            return []

        todo = TODO()
        with patch.object(
            TODO, "_claude_choisir", return_value=session
        ), patch.object(
            TODO, "_claude_transcription", return_value=""
        ), patch.object(
            TODO, "_claude_environ_bloc"
        ), patch.object(
            env, "variables", fausses_variables
        ), patch(
            "builtins.print"
        ):
            todo._claude_contexte([session])
        return vus

    def test_a_dormant_session_is_not_read(self):
        self.assertEqual(self._contexte(live=False), [])

    def test_a_live_session_is_read(self):
        self.assertEqual(self._contexte(live=True), [4321])


if __name__ == "__main__":
    unittest.main()
