#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La sonde est éprouvée par un SHELL, jamais relue comme une chaîne.

Relire une chaîne mesure ce qu'on a écrit, pas ce qui s'exécutera : une
protection qui semble absente parce qu'elle est citée, ou présente alors que
le découpage la défait, se lit pareil. Les quatre branches sont donc jouées
par bash, avec des faux outils sur le PATH — sans privilège, sans nftables,
et en millisecondes.

Rien ici ne touche à une machine : les faux outils vivent dans un répertoire
temporaire, et le PATH est réduit à lui.
"""

import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.append(RACINE)

from script.lib_valid import ValidationError  # noqa: E402
from script.posture import plan  # noqa: E402
from script.posture import rules  # noqa: E402

REGLES = "table inet erplibre {\n}\n"

# Le shell est nommé par son chemin ABSOLU : le PATH de l'enfant est
# réduit au répertoire de banc, si bien qu'un nom seul ne s'y
# résoudrait pas.
BASH = shutil.which("bash") or "/bin/bash"


def faux_outil(dossier, nom, corps):
    """Dépose un exécutable de banc et le rend jouable."""
    chemin = os.path.join(dossier, nom)
    with open(chemin, "w", encoding="utf-8") as handle:
        handle.write("#!/bin/sh\n" + corps + "\n")
    os.chmod(chemin, os.stat(chemin).st_mode | stat.S_IXUSR)
    return chemin


class TestLaSondeJoueeParUnShell(unittest.TestCase):
    """Le PATH est réduit au répertoire de banc : ce qui n'y est pas
    n'existe pas, y compris nftables."""

    def jouer(self, **outils):
        with tempfile.TemporaryDirectory() as dossier:
            for nom, corps in outils.items():
                faux_outil(dossier, nom, corps)
            res = subprocess.run(
                [BASH, "-c", plan.probe_command()],
                capture_output=True,
                text=True,
                env={"PATH": dossier},
            )
        return plan.parse_probe(res.stdout), res

    def test_no_tool_at_all_says_so(self):
        verdict, _res = self.jouer()
        self.assertEqual(plan.TOOL_ABSENT, verdict)

    def test_a_sudo_that_asks_for_a_password_is_not_a_missing_table(self):
        """Les deux se corrigent de deux côtés : l'un est un droit à
        obtenir, l'autre un chargement à refaire."""
        verdict, _res = self.jouer(nft="exit 0", sudo="exit 1")
        self.assertEqual(plan.NO_PRIVILEGE, verdict)

    def test_the_tool_without_the_table_says_the_table(self):
        verdict, _res = self.jouer(
            nft="exit 0",
            sudo='case "$*" in *true*) exit 0;; *) exit 1;; esac',
        )
        self.assertEqual(plan.TABLE_ABSENT, verdict)

    def test_the_table_present_is_the_only_way_to_read_loaded(self):
        verdict, _res = self.jouer(nft="exit 0", sudo="exit 0")
        self.assertEqual(plan.LOADED, verdict)

    def test_the_probe_always_exits_zero(self):
        """Selon la version, le code de sortie ne distingue pas « pas
        d'outil » de « pas de table » : c'est le TEXTE qui répond."""
        for outils in ({}, {"nft": "exit 0", "sudo": "exit 1"}):
            with self.subTest(outils=sorted(outils)):
                _verdict, res = self.jouer(**outils)
                self.assertEqual(0, res.returncode, res.stderr)

    def test_the_probe_asks_the_table_the_renderer_creates(self):
        """Un nom écrit deux fois divergerait, et la sonde chercherait une
        table que personne ne crée."""
        self.assertIn(f"inet {rules.TABLE}", plan.probe_command())


class TestLireLaReponse(unittest.TestCase):
    def test_nothing_read_is_never_loaded(self):
        """Une sonde muette annoncée comme un succès est le mensonge que
        cette relecture existe pour empêcher."""
        for sortie in ("", None, "   ", "connexion refusée"):
            with self.subTest(sortie=repr(sortie)):
                self.assertEqual(plan.UNREAD, plan.parse_probe(sortie))

    def test_transport_noise_does_not_hide_the_answer(self):
        sortie = (
            "Warning: Permanently added 'x' (ED25519) to known hosts.\n"
            f"{plan.MARQUEUR}{plan.LOADED}\n"
        )
        self.assertEqual(plan.LOADED, plan.parse_probe(sortie))

    def test_a_word_outside_the_vocabulary_is_not_believed(self):
        self.assertEqual(
            plan.UNREAD, plan.parse_probe(f"{plan.MARQUEUR}tout-va-bien")
        )

    def test_a_bare_word_without_the_marker_is_not_an_answer(self):
        """Sans marqueur, n'importe quelle ligne de transport répondrait."""
        self.assertEqual(plan.UNREAD, plan.parse_probe("loaded"))

    def test_the_last_answer_wins(self):
        """Un invité bavard peut écrire avant la sonde."""
        sortie = (
            f"{plan.MARQUEUR}{plan.TOOL_ABSENT}\n{plan.MARQUEUR}{plan.LOADED}"
        )
        self.assertEqual(plan.LOADED, plan.parse_probe(sortie))

    def test_every_verdict_the_guest_can_say_is_read_back(self):
        self.assertTrue(plan.SAID_BY_GUEST, "vocabulaire vidé")
        for jeton in plan.SAID_BY_GUEST:
            with self.subTest(jeton=jeton):
                self.assertEqual(
                    jeton, plan.parse_probe(f"{plan.MARQUEUR}{jeton}")
                )

    def test_the_guest_cannot_take_back_an_answer_with_silence(self):
        """« non lu » décrit le silence : prononcé par un invité qui vient
        de répondre, il effacerait sa réponse."""
        self.assertNotIn(plan.UNREAD, plan.SAID_BY_GUEST)
        sortie = f"{plan.MARQUEUR}{plan.LOADED}\n{plan.MARQUEUR}{plan.UNREAD}"
        self.assertEqual(plan.LOADED, plan.parse_probe(sortie))

    def test_the_wording_of_the_verdicts_is_pinned(self):
        """Un écran les affichera : un jeton renommé casse un consommateur
        sans qu'aucune constante bouge."""
        self.assertEqual(
            (
                "loaded",
                "table-absent",
                "tool-absent",
                "no-privilege",
                "unread",
            ),
            plan.VERDICTS,
        )


class TestOuLeFichierSePose(unittest.TestCase):
    def test_the_path_is_flat_under_a_directory_that_always_exists(self):
        """L'une des deux voies recopie avec une commande qui ne crée pas
        les parents et tolère son propre échec : un chemin à deux niveaux
        se poserait sur une voie et manquerait en silence sur l'autre."""
        self.assertTrue(plan.RULES_PATH.startswith("/etc/"))
        self.assertEqual(2, plan.RULES_PATH.count("/"), plan.RULES_PATH)

    def test_the_mode_is_a_string_and_not_a_number(self):
        """Non quoté dans le YAML, « 644 » est lu en DÉCIMAL et appliqué
        tel quel, sans le moindre avertissement."""
        self.assertIsInstance(plan.RULES_MODE, str)
        self.assertTrue(plan.RULES_MODE.startswith("0"))

    def test_the_owner_stays_empty_so_the_write_is_not_deferred(self):
        """Un propriétaire nommé reporterait la pose à l'étape finale,
        alors que ce fichier doit être là avant tout le reste."""
        self.assertEqual("", plan.RULES_OWNER)

    def test_the_entry_has_the_four_fields_the_pose_expects(self):
        entree = plan.file_entry(REGLES)
        self.assertEqual(4, len(entree))
        self.assertEqual(
            (plan.RULES_PATH, plan.RULES_MODE, REGLES, plan.RULES_OWNER),
            entree,
        )

    def test_an_empty_file_is_refused_rather_than_posed(self):
        """Chargé, il s'accepterait sans rien appliquer, et la machine se
        lirait comme confinée."""
        for vide in ("", None, "   \n  "):
            with self.subTest(vide=repr(vide)):
                with self.assertRaises(ValidationError):
                    plan.file_entry(vide)

    def test_a_real_rendering_goes_through(self):
        """Contrôle positif : le refus ne doit pas manger ce qui est bon."""
        from script.posture import destinations as D
        from script.posture import registry as R

        carnet = {
            nom: [f"198.51.100.{index + 10}/32"]
            for index, nom in enumerate(
                __import__(
                    "script.posture.allowlist", fromlist=["x"]
                ).symbol_names()
            )
        }
        posture = R.get_posture("paranoid")
        texte = rules.render_egress(
            posture, D.destinations_for(posture, carnet)
        )
        self.assertEqual(texte, plan.file_entry(texte)[2])


class TestLUniteDeRechargement(unittest.TestCase):
    """Sans elle, seul le PREMIER amorçage charge les règles : une machine
    redémarrée repart sans, et la voie de l'installateur — qui n'a aucune
    première commande — ne les chargeait jamais."""

    def test_it_runs_before_any_interface_is_configured(self):
        """Sinon il existe une fenêtre où la machine sort librement à
        chaque démarrage."""
        texte = plan.unit_text()
        self.assertIn("Before=network-pre.target", texte)
        self.assertIn("Wants=network-pre.target", texte)

    def test_it_loads_the_file_that_the_entry_poses(self):
        self.assertIn(plan.RULES_PATH, plan.unit_text())

    def test_it_finds_the_tool_through_a_shell(self):
        """systemd exige un chemin absolu pour son premier mot, et le
        répertoire de l'analyseur diffère selon la distribution ; le shell
        est au même endroit partout."""
        ligne = [
            l
            for l in plan.unit_text().splitlines()
            if l.startswith("ExecStart=")
        ]
        self.assertEqual(1, len(ligne))
        self.assertTrue(ligne[0].startswith("ExecStart=/bin/sh -c "))

    def test_it_runs_once_and_is_armed_for_every_boot(self):
        texte = plan.unit_text()
        self.assertIn("Type=oneshot", texte)
        self.assertIn("WantedBy=multi-user.target", texte)

    def test_its_entry_is_readable_and_not_secret(self):
        """Un fichier d'unité se lit ; il ne porte aucune adresse."""
        chemin, mode, contenu, proprietaire = plan.unit_entry()
        self.assertEqual(plan.UNIT_PATH, chemin)
        self.assertEqual("0644", mode)
        self.assertEqual("", proprietaire)
        self.assertEqual(plan.unit_text(), contenu)

    def test_the_unit_lives_where_the_installer_can_copy_it(self):
        """Le répertoire d'unités locales existe sur tout système systemd ;
        la voie qui recopie ne créerait pas un parent manquant."""
        self.assertTrue(plan.UNIT_PATH.startswith("/etc/systemd/system/"))
        self.assertTrue(plan.UNIT_PATH.endswith(plan.UNIT_NAME))

    def test_the_first_boot_arms_and_loads_in_that_order(self):
        """Armer sans charger laisse la machine sortir jusqu'au premier
        redémarrage ; charger sans armer la laisse sortir à partir du
        deuxième."""
        commande = plan.first_boot_command()
        self.assertLess(
            commande.index(plan.UNIT_NAME), commande.index(plan.RULES_PATH)
        )
        self.assertIn("&&", commande)
        self.assertNotIn("|| true", commande)

    def test_both_halves_must_succeed(self):
        """Joué par un shell : « && » lie les deux, un premier échec
        arrête tout, et le code de sortie est non nul."""
        with tempfile.TemporaryDirectory() as dossier:
            faux_outil(dossier, "systemctl", "exit 1")
            faux_outil(dossier, "nft", "echo NE-DEVRAIT-PAS-TOURNER; exit 0")
            res = subprocess.run(
                [BASH, "-c", plan.first_boot_command()],
                capture_output=True,
                text=True,
                env={"PATH": dossier},
            )
        self.assertNotEqual(0, res.returncode)
        self.assertNotIn("NE-DEVRAIT-PAS-TOURNER", res.stdout)


class TestLaLigneDeChargement(unittest.TestCase):
    def test_it_tolerates_no_failure(self):
        """Un « || true » masquerait la panne, et le déploiement
        continuerait en annonçant un confinement que rien ne tient."""
        self.assertNotIn("|| true", plan.load_command())
        self.assertNotIn("||", plan.load_command())

    def test_it_is_one_command_so_its_status_is_the_scripts(self):
        """Le code de sortie d'un script est celui de sa DERNIÈRE commande :
        placée en dernier, une commande unique porte son propre échec
        jusqu'au bout."""
        self.assertNotIn(";", plan.load_command())
        self.assertNotIn("&&", plan.load_command())

    def test_it_loads_the_file_that_the_entry_poses(self):
        self.assertIn(plan.RULES_PATH, plan.load_command())
        self.assertEqual(plan.RULES_PATH, plan.file_entry(REGLES)[0])

    def test_a_missing_tool_makes_it_fail_and_say_why(self):
        """Joué par un shell, sans nftables sur le PATH."""
        with tempfile.TemporaryDirectory() as dossier:
            res = subprocess.run(
                [BASH, "-c", plan.load_command()],
                capture_output=True,
                text=True,
                env={"PATH": dossier},
            )
        self.assertNotEqual(0, res.returncode)
        self.assertIn("nft", res.stderr)


if __name__ == "__main__":
    unittest.main()
