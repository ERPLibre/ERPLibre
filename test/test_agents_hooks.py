#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les hooks de télémétrie : ce qu'ils écrivent, et ce qu'ils ne cassent pas.

Le hook tourne à CHAQUE appel d'outil, et Claude Code lit son code de sortie :
un code non nul sur un `PreToolUse` BLOQUE l'appel. Une télémétrie qui lève
empêcherait donc le travail qu'elle prétend mesurer. Le premier groupe de
tests ne vérifie rien d'autre que ça, sur toutes les entrées qui peuvent
arriver — vide, tronquée, du JSON qui n'est pas un objet.

Le second groupe défend ce qui N'EST PAS écrit. L'événement porte
`tool_input` — la ligne bash, le contenu d'une édition — et `tool_response`.
Le journal compte des appels ; il ne recopie pas ce qu'ils disent. C'est un
choix de conception, et il tient même là où la frontière a été levée pour
l'AFFICHAGE : ce qui n'est pas écrit n'a pas à être protégé plus tard.

Le troisième défend la FUSION des réglages. Un fichier de réglages porte
volontiers d'autres hooks, et les remplacer retirerait le travail de quelqu'un
d'autre en silence.

Les valeurs sont inventées, et le marqueur qui joue le rôle d'un secret est un
témoin : sa présence dans l'entrée est ce qui prouve qu'il ne ressort pas.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

from script.todo.assistant.agents import journal, pose
from script.todo.assistant.agents.hooks import evenement

HOOK = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "script",
    "todo",
    "assistant",
    "agents",
    "hooks",
    "evenement.py",
)

# Un témoin planté dans les champs que le journal ne doit PAS recopier.
TEMOIN = "marqueur-de-commande-qui-ne-doit-pas-sortir"


def _pre(**extra):
    charge = {
        "hook_event_name": "PreToolUse",
        "session_id": "aaaa-bbbb-cccc",
        "cwd": "/un/chemin",
        "tool_name": "Bash",
        "tool_use_id": "toolu_01",
        "tool_input": {"command": f"echo {TEMOIN}"},
    }
    charge.update(extra)
    return charge


class TestLeHookNeCassePasLAppel(unittest.TestCase):
    """Zéro, quoi qu'il arrive. Un code non nul bloquerait l'appel d'outil."""

    def _lancer(self, charge, maison):
        return subprocess.run(
            [sys.executable, HOOK],
            input=charge,
            text=True,
            capture_output=True,
            env=dict(os.environ, HOME=maison),
        )

    def setUp(self):
        self.maison = tempfile.mkdtemp()

    def test_a_normal_event_exits_zero(self):
        fini = self._lancer(json.dumps(_pre()), self.maison)
        self.assertEqual(fini.returncode, 0, fini.stderr)

    def test_empty_input_exits_zero(self):
        self.assertEqual(self._lancer("", self.maison).returncode, 0)

    def test_broken_json_exits_zero(self):
        self.assertEqual(
            self._lancer("{ ceci n'est pas du json", self.maison).returncode, 0
        )

    def test_json_that_is_not_an_object_exits_zero(self):
        self.assertEqual(self._lancer("[1, 2, 3]", self.maison).returncode, 0)

    def test_an_unwritable_home_exits_zero(self):
        """Disque plein, répertoire interdit : le travail continue quand même."""
        fini = self._lancer(json.dumps(_pre()), "/proc/introuvable")
        self.assertEqual(fini.returncode, 0)

    def test_the_hook_prints_nothing_on_stdout(self):
        """Ce qu'un hook imprime peut être interprété : il se tait."""
        fini = self._lancer(json.dumps(_pre()), self.maison)
        self.assertEqual(fini.stdout, "")


class TestCeQuiNEstPasEcrit(unittest.TestCase):
    def _ligne(self, charge, racine):
        self.assertTrue(evenement.ecrire(json.dumps(charge), racine=racine))
        chemin = journal.chemin_du_jour(racine=racine)
        with open(chemin, encoding="utf-8") as fh:
            return fh.read()

    def setUp(self):
        self.racine = tempfile.mkdtemp()

    def test_the_command_never_reaches_the_log(self):
        """`tool_input` porte la ligne bash. Elle n'est pas écrite."""
        texte = self._ligne(_pre(), self.racine)
        self.assertNotIn(TEMOIN, texte)

    def test_the_tool_response_never_reaches_the_log_either(self):
        texte = self._ligne(
            _pre(hook_event_name="PostToolUse", tool_response=TEMOIN),
            self.racine,
        )
        self.assertNotIn(TEMOIN, texte)

    def test_what_is_written_is_the_structure(self):
        texte = self._ligne(_pre(), self.racine)
        ligne = json.loads(texte.strip())
        self.assertEqual(ligne["hook_event_name"], "PreToolUse")
        self.assertEqual(ligne["tool_name"], "Bash")
        self.assertEqual(ligne["tool_use_id"], "toolu_01")
        self.assertIn("ts", ligne)

    def test_an_event_without_a_name_is_not_written(self):
        """Sans nom d'événement, la ligne ne s'apparie à rien."""
        self.assertFalse(
            evenement.ecrire(
                json.dumps({"tool_name": "Bash"}), racine=self.racine
            )
        )

    def test_the_fields_match_the_journal(self):
        """Le hook recopie ces constantes faute de pouvoir importer.

        Importer le paquet coûterait une seconde par appel d'outil ; le prix
        de la duplication est ce test."""
        self.assertEqual(evenement.CHAMPS, journal.CHAMPS)
        self.assertEqual(evenement.CHAMPS_NOMBRE, journal.CHAMPS_NOMBRE)
        self.assertEqual(evenement.CHAMPS_BOOLEEN, journal.CHAMPS_BOOLEEN)
        self.assertEqual(evenement.RACINE, journal.RACINE)


class TestLaFusionDesReglages(unittest.TestCase):
    ETRANGER = {
        "matcher": "*",
        "hooks": [{"type": "command", "command": "un-formateur-a-nous"}],
    }

    def test_a_foreign_hook_survives(self):
        avant = {"hooks": {"PreToolUse": [self.ETRANGER]}}
        apres = pose.fusionner(avant, pose.bloc())
        commandes = [
            h["command"]
            for e in apres["hooks"]["PreToolUse"]
            for h in e["hooks"]
        ]
        self.assertIn("un-formateur-a-nous", commandes)
        self.assertEqual(len(apres["hooks"]["PreToolUse"]), 2)

    def test_everything_else_in_the_file_survives(self):
        avant = {"env": {"UNE": "1"}, "theme": "dark"}
        apres = pose.fusionner(avant, pose.bloc())
        self.assertEqual(apres["env"], {"UNE": "1"})
        self.assertEqual(apres["theme"], "dark")

    def test_installing_twice_does_not_duplicate_us(self):
        """Le chemin de l'interpréteur change quand le venv est refait."""
        une = pose.fusionner({}, pose.bloc())
        deux = pose.fusionner(une, pose.bloc())
        self.assertEqual(len(deux["hooks"]["PreToolUse"]), 1)

    def test_removing_takes_only_ours(self):
        avant = {"hooks": {"PreToolUse": [self.ETRANGER]}}
        apres = pose.retirer_de(pose.fusionner(avant, pose.bloc()))
        self.assertEqual(apres["hooks"]["PreToolUse"], [self.ETRANGER])

    def test_removing_leaves_no_empty_shell(self):
        """Une clé `hooks` vide ferait croire à une pose partielle."""
        apres = pose.retirer_de(pose.fusionner({}, pose.bloc()))
        self.assertNotIn("hooks", apres)

    def test_every_journal_event_is_installed(self):
        installes = set(pose.bloc())
        self.assertEqual(installes, set(journal.EVENEMENTS))

    def test_the_tool_events_carry_a_matcher(self):
        """Sans matcher, l'entrée ne s'applique à aucun outil."""
        for evt in ("PreToolUse", "PostToolUse"):
            self.assertEqual(pose.bloc()[evt][0]["matcher"], "*")

    def test_the_interpreter_is_named_in_full(self):
        """« python3 » du PATH ferait dépendre la télémétrie du shell."""
        self.assertTrue(pose.commande().startswith("/"))


class TestCeQuiEntreDansUnFichierSuivi(unittest.TestCase):
    """Le `.claude/settings.json` du dépôt est SUIVI par git.

    Deux règles s'y appliquent que le fichier du compte ignore : rien
    d'identifiant n'entre dans un fichier que le dépôt emporte, et ce qui y
    est écrit doit valoir pour TOUT clone. Un chemin absolu manque les deux à
    la fois — il porte le nom du compte qui a posé les hooks, et il désigne un
    répertoire qu'aucun autre clone n'a.
    """

    def _ligne(self, endroit):
        (entree,) = pose.bloc(endroit)["SessionEnd"]
        return entree["hooks"][0]["command"]

    def test_the_repository_command_carries_no_absolute_path(self):
        ligne = self._ligne(pose.DEPOT)
        for mot in ligne.split():
            self.assertFalse(mot.startswith("/"), ligne)

    def test_the_repository_command_carries_no_home(self):
        """Un chemin de compte est exactement ce que les conventions
        refusent."""
        self.assertNotIn(os.path.expanduser("~"), self._ligne(pose.DEPOT))

    def test_the_global_command_stays_absolute(self):
        """Le fichier du compte ne suit pas le dépôt et ne vaut que pour cette
        machine : l'interpréteur y reste nommé en entier."""
        for mot in self._ligne(pose.GLOBAL).split():
            self.assertTrue(mot.startswith("/"))

    def test_both_places_stay_recognisable(self):
        """La signature reconnaît NOS entrées : sans elle, le retrait ne
        saurait plus lesquelles enlever, aux deux endroits."""
        for endroit in (pose.GLOBAL, pose.DEPOT):
            pose_faite = pose.fusionner({}, pose.bloc(endroit))
            self.assertEqual(
                set(pose.actifs(pose_faite)), set(journal.EVENEMENTS)
            )

    def test_the_repository_hook_really_runs(self):
        """Le chemin relatif désigne bien le hook, depuis la racine."""
        racine = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self.assertTrue(os.path.isfile(os.path.join(racine, pose.RELATIF)))


class TestUnFichierQuOnNaPasSuRelire(unittest.TestCase):
    """Écrire par-dessus des réglages illisibles les remplacerait tous.

    Une virgule en trop dans un `settings.json` suffit à le rendre illisible,
    et le fichier porte volontiers des permissions, des variables et les hooks
    de quelqu'un d'autre. « Absent » et « illisible » se ressemblent à la
    lecture et disent le contraire : le premier se complète, le second se
    refuse.
    """

    @staticmethod
    def _illisible(chemin):
        return None

    def test_installing_over_unreadable_settings_writes_nothing(self):
        ecrits = {}
        with self.assertRaises(OSError):
            pose.poser(
                pose.GLOBAL,
                charger=self._illisible,
                ecrire=lambda c, d: ecrits.__setitem__(c, d),
            )
        self.assertEqual(ecrits, {})

    def test_removing_from_unreadable_settings_writes_nothing(self):
        ecrits = {}
        with self.assertRaises(OSError):
            pose.retirer(
                pose.GLOBAL,
                charger=self._illisible,
                ecrire=lambda c, d: ecrits.__setitem__(c, d),
            )
        self.assertEqual(ecrits, {})

    def test_the_screen_is_told_rather_than_shown_zero(self):
        """None et « aucun hook posé » ne se confondent pas à l'écran."""
        etat = pose.etat(racine_depot="/un/depot", charger=self._illisible)
        for _, (_, actifs) in etat.items():
            self.assertIsNone(actifs)

    def test_a_missing_file_is_still_installable(self):
        """Refuser l'illisible ne doit pas refuser l'absent : la première pose
        se fait sur un fichier qui n'existe pas."""
        ecrits = {}
        chemin = pose.poser(
            pose.GLOBAL,
            charger=lambda c: {},
            ecrire=lambda c, d: ecrits.__setitem__(c, d),
        )
        self.assertIn("hooks", ecrits[chemin])

    def test_a_real_broken_file_reads_as_unreadable(self):
        """Le vrai lecteur, sur un vrai fichier : c'est lui qui tranche."""
        with tempfile.TemporaryDirectory() as dossier:
            casse = os.path.join(dossier, "settings.json")
            with open(casse, "w", encoding="utf-8") as fh:
                fh.write('{"hooks": {},}\n')
            self.assertIsNone(pose._charger(casse))
            absent = os.path.join(dossier, "rien.json")
            self.assertEqual(pose._charger(absent), {})

    def test_a_symlink_keeps_being_a_symlink(self):
        """Un `settings.json` est volontiers un lien vers un dépôt de
        configuration : `os.replace` sur le lien l'en détacherait en
        silence."""
        with tempfile.TemporaryDirectory() as dossier:
            vrai = os.path.join(dossier, "vrai.json")
            with open(vrai, "w", encoding="utf-8") as fh:
                fh.write("{}\n")
            lien = os.path.join(dossier, "settings.json")
            os.symlink(vrai, lien)
            pose._ecrire(lien, {"hooks": {}})
            self.assertTrue(os.path.islink(lien))

    def test_the_active_events_are_reported(self):
        pose_faite = pose.fusionner({}, pose.bloc())
        self.assertEqual(set(pose.actifs(pose_faite)), set(journal.EVENEMENTS))
        self.assertEqual(pose.actifs({}), ())


class TestLesDeuxEndroits(unittest.TestCase):
    def test_both_places_are_always_reported(self):
        """Taire celui qui manque empêcherait de dire « posé ici, pas là »."""
        etat = pose.etat(racine_depot="/un/depot", charger=lambda c: {})
        self.assertEqual(set(etat), {pose.GLOBAL, pose.DEPOT})
        for _, (chemin, actifs) in etat.items():
            self.assertTrue(chemin)
            self.assertEqual(actifs, ())

    def test_the_repository_path_follows_the_repository(self):
        chemin, _ = pose.etat(racine_depot="/un/depot", charger=lambda c: {})[
            pose.DEPOT
        ]
        self.assertEqual(chemin, "/un/depot/.claude/settings.json")

    def test_the_global_path_is_expanded(self):
        chemin, _ = pose.etat(charger=lambda c: {})[pose.GLOBAL]
        self.assertNotIn("~", chemin)

    def test_installing_writes_where_it_says(self):
        ecrits = {}
        chemin = pose.poser(
            pose.DEPOT,
            racine_depot="/un/depot",
            charger=lambda c: {},
            ecrire=lambda c, d: ecrits.__setitem__(c, d),
        )
        self.assertEqual(chemin, "/un/depot/.claude/settings.json")
        self.assertIn(chemin, ecrits)
        self.assertIn("hooks", ecrits[chemin])


class TestLeMenage(unittest.TestCase):
    def test_an_old_log_goes_and_a_recent_one_stays(self):
        """La date est dans le NOM : pas besoin de lire, ni de croire l'mtime,
        qu'une copie ou une restauration remet à l'heure de la copie."""
        retires = []
        journaux = [
            "/j/2020-01-01.jsonl",
            "/j/2099-01-01.jsonl",
        ]
        journal.nettoyer(
            racine="/j",
            jours=14,
            lister=lambda motif: journaux,
            retirer=retires.append,
        )
        self.assertEqual(retires, ["/j/2020-01-01.jsonl"])

    def test_a_refused_removal_does_not_raise(self):
        def refuser(chemin):
            raise OSError("interdit")

        journal.nettoyer(
            racine="/j",
            lister=lambda motif: ["/j/2020-01-01.jsonl"],
            retirer=refuser,
        )


if __name__ == "__main__":
    unittest.main()


class TestLeTempsPasseEtLeTempsEcoule(unittest.TestCase):
    """Deux durées qui se ressemblent et ne disent pas la même chose.

    L'horloge d'une session compte tout ce qui s'est écoulé, y compris les
    heures où personne ne regardait : elle annonce des centaines d'heures dès
    qu'une session reste ouverte plusieurs jours. Le temps d'ATTENTION borne
    chaque écart
    par un seuil d'inactivité, et c'est lui qui répond à « combien de temps
    ce travail a-t-il pris ».

    Le journal des hooks porte déjà l'instant de chaque événement : rien n'est
    à collecter, seulement à replier.
    """

    def test_the_gaps_are_summed(self):
        lignes = [
            {"session_id": "a", "ts": 0},
            {"session_id": "a", "ts": 1_000},
            {"session_id": "a", "ts": 3_000},
        ]
        self.assertEqual(journal.temps_actif(lignes), {"a": 3_000})

    def test_a_long_silence_is_capped(self):
        """Sans coupure, une session ouverte trois jours compte trois jours."""
        lignes = [
            {"session_id": "a", "ts": 0},
            {"session_id": "a", "ts": 3 * 86_400_000},
        ]
        self.assertEqual(
            journal.temps_actif(lignes), {"a": journal.INACTIVITE_MS}
        )

    def test_the_order_of_the_log_does_not_decide(self):
        """Deux sessions écrivent dans le même fichier, entrelacées."""
        lignes = [
            {"session_id": "a", "ts": 2_000},
            {"session_id": "b", "ts": 500},
            {"session_id": "a", "ts": 0},
            {"session_id": "b", "ts": 1_500},
        ]
        self.assertEqual(journal.temps_actif(lignes), {"a": 2_000, "b": 1_000})

    def test_a_single_event_is_zero_and_that_is_a_measure(self):
        """On sait que la session a existé, pas combien elle a duré : il n'y
        a aucun intervalle à mesurer, donc zéro est juste."""
        self.assertEqual(
            journal.temps_actif([{"session_id": "a", "ts": 42}]), {"a": 0}
        )

    def test_a_line_without_a_session_or_an_instant_is_dropped(self):
        lignes = [
            {"ts": 1_000},
            {"session_id": "a"},
            {"session_id": "a", "ts": "hier"},
            "pas un objet",
            {"session_id": "a", "ts": 0},
            {"session_id": "a", "ts": 1_000},
        ]
        self.assertEqual(journal.temps_actif(lignes), {"a": 1_000})

    def test_nothing_read_is_nothing_said(self):
        self.assertEqual(journal.temps_actif([]), {})

    def test_the_decoding_half_is_reusable(self):
        """Tous les événements portent un instant, seuls deux se recousent en
        appels : lire le temps sur les appels l'amputerait."""
        texte = "\n".join(
            json.dumps(l)
            for l in (
                {"session_id": "a", "ts": 0, "hook_event_name": "SessionEnd"},
                {"session_id": "a", "ts": 1_000},
            )
        )
        lignes = journal.lire_lignes(
            lister=lambda motif: ["/j/2026-01-01.jsonl"],
            lire_texte=lambda chemin: texte,
        )
        self.assertEqual(len(lignes), 2)
        self.assertEqual(journal.temps_actif(lignes), {"a": 1_000})
        self.assertEqual(journal.apparier(lignes), [])


class TestLesQuatreFinsDUnAppel(unittest.TestCase):
    """« Inachevé » recouvrait trois situations sans rapport.

    Un outil en échec se corrige, un outil interrompu se relance, un appel
    dont aucune clôture n'est venue ne dit rien du tout. Les compter ensemble
    donne un écran dont le chiffre n'appelle aucun geste.

    Les noms de champ sont ceux des charges réelles du binaire :
    `PostToolUseFailure` porte `error`, `is_interrupt` et `duration_ms`.
    """

    def _pre(self, cle, outil="Bash"):
        return {
            "hook_event_name": "PreToolUse",
            "tool_use_id": cle,
            "tool_name": outil,
            "session_id": "s",
            "ts": 0,
        }

    def test_a_finished_call_says_so(self):
        appels = journal.apparier(
            [
                self._pre("1"),
                {
                    "hook_event_name": "PostToolUse",
                    "tool_use_id": "1",
                    "ts": 40,
                },
            ]
        )
        self.assertEqual([a.issue for a in appels], [journal.FINI])

    def test_a_failure_is_told_from_an_interruption(self):
        appels = journal.apparier(
            [
                self._pre("1"),
                {
                    "hook_event_name": "PostToolUseFailure",
                    "tool_use_id": "1",
                    "ts": 40,
                    "is_interrupt": False,
                },
                self._pre("2"),
                {
                    "hook_event_name": "PostToolUseFailure",
                    "tool_use_id": "2",
                    "ts": 40,
                    "is_interrupt": True,
                },
            ]
        )
        self.assertEqual(
            sorted(a.issue for a in appels),
            sorted([journal.ECHOUE, journal.INTERROMPU]),
        )

    def test_a_call_nothing_closed_is_unfinished_and_has_no_duration(self):
        (appel,) = journal.apparier([self._pre("1")])
        self.assertEqual(appel.issue, journal.INACHEVE)
        self.assertIsNone(appel.duree_ms)

    def test_the_three_are_counted_apart(self):
        appels = journal.apparier(
            [
                self._pre("1"),
                {
                    "hook_event_name": "PostToolUse",
                    "tool_use_id": "1",
                    "ts": 1,
                },
                self._pre("2"),
                {
                    "hook_event_name": "PostToolUseFailure",
                    "tool_use_id": "2",
                    "ts": 1,
                },
                self._pre("3"),
                {
                    "hook_event_name": "PostToolUseFailure",
                    "tool_use_id": "3",
                    "ts": 1,
                    "is_interrupt": True,
                },
                self._pre("4"),
            ]
        )
        (groupe,) = journal.par_outil(appels)
        self.assertEqual(groupe.appels, 4)
        self.assertEqual(groupe.echoues, 1)
        self.assertEqual(groupe.interrompus, 1)
        self.assertEqual(groupe.inacheves, 1)

    def test_the_failure_event_is_installed(self):
        """Sans lui, aucun échec n'atteint jamais le journal."""
        self.assertIn("PostToolUseFailure", journal.EVENEMENTS)
        self.assertEqual(pose.bloc()["PostToolUseFailure"][0]["matcher"], "*")


class TestLaDureeMesureeEtLaDureeSupposee(unittest.TestCase):
    """L'écart entre les deux instants INCLUT l'attente d'une autorisation.

    Un appel approuvé au bout de quatre minutes se lisait donc comme un appel
    de quatre minutes, et la médiane par outil s'en trouvait majorée dès que
    l'utilisateur approuve au lieu de laisser faire. Le binaire porte la durée
    qu'il rapporte lui-même, et c'est elle qui vaut.
    """

    PRE = {
        "hook_event_name": "PreToolUse",
        "tool_use_id": "1",
        "tool_name": "Bash",
        "session_id": "s",
        "ts": 0,
    }

    def test_the_measured_duration_wins_over_the_gap(self):
        (appel,) = journal.apparier(
            [
                self.PRE,
                {
                    "hook_event_name": "PostToolUse",
                    "tool_use_id": "1",
                    "ts": 4 * 60 * 1000,
                    "duration_ms": 40,
                },
            ]
        )
        self.assertEqual(appel.duree_ms, 40)

    def test_without_it_the_gap_is_the_fallback(self):
        """Une version antérieure du binaire ne la porte pas : mieux vaut un
        écart majoré que rien du tout."""
        (appel,) = journal.apparier(
            [
                self.PRE,
                {
                    "hook_event_name": "PostToolUse",
                    "tool_use_id": "1",
                    "ts": 250,
                },
            ]
        )
        self.assertEqual(appel.duree_ms, 250)

    def test_a_duration_that_is_a_boolean_is_not_a_duration(self):
        """`isinstance(True, int)` est vrai en Python."""
        (appel,) = journal.apparier(
            [
                self.PRE,
                {
                    "hook_event_name": "PostToolUse",
                    "tool_use_id": "1",
                    "ts": 250,
                    "duration_ms": True,
                },
            ]
        )
        self.assertEqual(appel.duree_ms, 250)

    def test_the_hook_keeps_the_number_and_the_flag(self):
        """Un filtre à chaînes les écartait tous les deux en silence."""
        charge = json.dumps(
            {
                "hook_event_name": "PostToolUseFailure",
                "tool_use_id": "x",
                "duration_ms": 42,
                "is_interrupt": True,
            }
        )
        with tempfile.TemporaryDirectory() as dossier:
            self.assertTrue(evenement.ecrire(charge, racine=dossier))
            fichiers = os.listdir(dossier)
            texte = open(os.path.join(dossier, fichiers[0])).read()
        ligne = json.loads(texte)
        self.assertEqual(ligne["duration_ms"], 42)
        self.assertIs(ligne["is_interrupt"], True)

    def test_the_hook_still_refuses_the_free_text(self):
        """`error` et `tool_input` portent une commande et un message : ils
        n'entrent pas plus qu'avant."""
        charge = json.dumps(
            {
                "hook_event_name": "PostToolUseFailure",
                "tool_use_id": "x",
                "error": TEMOIN,
                "tool_input": {"command": TEMOIN},
                "duration_ms": 42,
            }
        )
        with tempfile.TemporaryDirectory() as dossier:
            evenement.ecrire(charge, racine=dossier)
            fichiers = os.listdir(dossier)
            texte = open(os.path.join(dossier, fichiers[0])).read()
        self.assertNotIn(TEMOIN, texte)
        self.assertIn("42", texte)
