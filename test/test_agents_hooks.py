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
