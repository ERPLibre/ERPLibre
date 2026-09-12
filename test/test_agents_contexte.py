#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'une session porte, et les deux pièges qui mentent sans lever.

**Un delta lu comme un état.** Plusieurs enregistrements sont réémis en cours
de session et ne portent que ce qui a changé. Prendre la dernière occurrence
pour l'état donne « un fichier d'instructions » là où sept sont chargés et
« une skill » là où trente-neuf le sont, sur des sessions réelles. Les deux
formes ne se corrigent pas de la même façon : `instructions`
s'accumule par chemin, `skill_listing` retient son entrée initiale.

**Une absence lue comme un zéro.** Trois causes donnent le même vide et
appellent trois gestes opposés : la version du CLI n'écrit pas
l'enregistrement, le processus appartient à un autre compte, le processus est
mort. « 0 skill » sur une session qui en a trente-neuf est le message le plus
trompeur qu'un écran de diagnostic puisse produire.

Et une chose que ce module ne fait JAMAIS : rendre un champ dont la valeur est
du texte libre. La transcription porte le contenu intégral des fichiers
d'instructions, celui des skills, l'invite système et la sortie des hooks. On
en garde le chemin, le nom, le compte, la taille — jamais le texte.

Les chemins sont inventés.
"""

import json
import unittest

from script.todo.assistant.agents import contexte as ctx

TEMOIN = "contenu-de-fichier-qui-ne-doit-pas-sortir"


def _piece(sous_type, **champs):
    return {"type": "attachment", "attachment": {"type": sous_type, **champs}}


def _instructions(*fichiers):
    return _piece(
        "instructions",
        files=[{"path": c, "content": t} for c, t in fichiers],
    )


class TestLeModeleEtLaMachine(unittest.TestCase):
    def test_the_model_identity_is_read(self):
        c = ctx.replier(
            ctx.Contexte(),
            _piece(
                "model",
                identity={
                    "modelId": "un-modele[1m]",
                    "marketingName": "Un Modèle",
                    "knowledgeCutoff": "May 2026",
                },
            ),
        )
        self.assertEqual(c.modele, "Un Modèle")
        self.assertEqual(c.modele_id, "un-modele[1m]")
        self.assertEqual(c.coupure, "May 2026")

    def test_the_model_prose_is_not_read(self):
        """L'enregistrement porte aussi un paragraphe : seule l'identité sort."""
        c = ctx.replier(
            ctx.Contexte(),
            _piece("model", identity={"modelId": "m"}, text=TEMOIN),
        )
        self.assertNotIn(TEMOIN, f"{c.modele}{c.modele_id}{c.coupure}")

    def test_the_environment_snapshot_is_read(self):
        c = ctx.replier(
            ctx.Contexte(),
            _piece(
                "environment",
                snapshot={
                    "platform": "linux",
                    "osVersion": "Linux 1.2.3",
                    "shell": "bash",
                    "workingDirectory": "/un/chemin",
                    "isGitRepo": True,
                    "isWorktree": False,
                },
            ),
        )
        self.assertEqual(c.plateforme, "linux Linux 1.2.3")
        self.assertEqual(c.shell, "bash")
        self.assertTrue(c.depot_git)
        self.assertFalse(c.worktree)


class TestLeDeltaDesInstructions(unittest.TestCase):
    def test_a_later_record_does_not_replace_the_list(self):
        """Le cas réel : sept fichiers tombent à un seul."""
        c = ctx.Contexte()
        c = ctx.replier(
            c,
            _instructions(
                ("/a/CLAUDE.md", "aaa"),
                ("/a/.claude/rules/01.md", "bb"),
                ("/a/.claude/rules/02.md", "cccc"),
            ),
        )
        c = ctx.replier(c, _instructions(("/a/.claude/rules/02.md", "ccccc")))
        self.assertEqual(len(c.instructions), 3)

    def test_the_latest_size_wins_for_a_changed_file(self):
        c = ctx.replier(ctx.Contexte(), _instructions(("/a/x.md", "aa")))
        c = ctx.replier(c, _instructions(("/a/x.md", "aaaa")))
        self.assertEqual(c.instructions[0].octets, 4)

    def test_the_order_of_first_appearance_is_kept(self):
        c = ctx.replier(
            ctx.Contexte(), _instructions(("/a.md", "x"), ("/b.md", "y"))
        )
        c = ctx.replier(c, _instructions(("/a.md", "zz")))
        self.assertEqual(
            [f.chemin for f in c.instructions], ["/a.md", "/b.md"]
        )

    def test_only_the_size_survives_not_the_content(self):
        c = ctx.replier(ctx.Contexte(), _instructions(("/a.md", TEMOIN)))
        rendu = json.dumps(
            [(f.chemin, f.octets) for f in c.instructions], ensure_ascii=False
        )
        self.assertNotIn(TEMOIN, rendu)
        self.assertEqual(c.instructions[0].octets, len(TEMOIN))

    def test_a_file_without_a_path_is_dropped(self):
        c = ctx.replier(ctx.Contexte(), _instructions(("", "x")))
        self.assertEqual(c.instructions, ())


class TestLeDeltaDesSkills(unittest.TestCase):
    def test_the_initial_entry_wins(self):
        """Le cas réel : trente-neuf skills tombent à une seule."""
        c = ctx.replier(
            ctx.Contexte(),
            _piece("skill_listing", skillCount=39, isInitial=True),
        )
        c = ctx.replier(
            c, _piece("skill_listing", skillCount=1, isInitial=False)
        )
        self.assertEqual(c.skills, 39)

    def test_a_later_initial_replaces_the_previous_one(self):
        c = ctx.replier(
            ctx.Contexte(),
            _piece("skill_listing", skillCount=24, isInitial=True),
        )
        c = ctx.replier(
            c, _piece("skill_listing", skillCount=41, isInitial=True)
        )
        self.assertEqual(c.skills, 41)

    def test_a_delta_alone_is_still_read(self):
        """Sans initiale, un delta est tout ce qu'on a : mieux que rien, et
        l'écran ne prétend pas que c'est un état."""
        c = ctx.replier(
            ctx.Contexte(),
            _piece("skill_listing", skillCount=3, isInitial=False),
        )
        self.assertEqual(c.skills, 3)
        self.assertFalse(c.skills_initiales)

    def test_no_skill_record_is_minus_one_not_zero(self):
        """Zéro dirait « aucune skill » ; moins un dit « non porté »."""
        self.assertEqual(ctx.Contexte().skills, -1)


class TestLesPermissionsNeSeTotalisentPas(unittest.TestCase):
    def test_the_announcements_are_counted_not_summed(self):
        """Les tailles redescendent — 10, 0, 0, 6 — donc ce n'est pas un
        cumul, et l'enregistrement ne dit ni ajout ni retrait. Aucun total
        n'est donc affiché."""
        c = ctx.Contexte()
        for taille in (10, 0, 0, 6):
            c = ctx.replier(
                c,
                _piece("command_permissions", allowedTools=["x"] * taille),
            )
        self.assertEqual(c.annonces_permissions, 4)
        self.assertEqual(c.derniere_permission, 6)

    def test_a_malformed_record_counts_as_an_announcement(self):
        c = ctx.replier(ctx.Contexte(), _piece("command_permissions"))
        self.assertEqual(c.annonces_permissions, 1)
        self.assertEqual(c.derniere_permission, 0)


class TestLesHooks(unittest.TestCase):
    def test_a_hook_is_named_with_its_code_and_duration(self):
        c = ctx.replier(
            ctx.Contexte(),
            _piece(
                "hook_success",
                hookName="SessionStart:startup",
                exitCode="0",
                durationMs="26",
                stdout=TEMOIN,
                command=TEMOIN,
            ),
        )
        self.assertEqual(c.hooks, (("SessionStart:startup", "0", "26"),))

    def test_neither_the_output_nor_the_command_is_kept(self):
        """La sortie brute d'un programme arbitraire est le champ le plus
        exposé du lot."""
        c = ctx.replier(
            ctx.Contexte(),
            _piece(
                "hook_success", hookName="h", stdout=TEMOIN, command=TEMOIN
            ),
        )
        self.assertNotIn(TEMOIN, json.dumps(c.hooks))

    def test_the_same_hook_is_not_listed_twice(self):
        piece = _piece(
            "hook_success", hookName="h", exitCode="0", durationMs="1"
        )
        c = ctx.replier(ctx.replier(ctx.Contexte(), piece), piece)
        self.assertEqual(len(c.hooks), 1)


class TestCeQuiEstIgnore(unittest.TestCase):
    def test_an_unknown_attachment_changes_nothing(self):
        c = ctx.replier(
            ctx.Contexte(), _piece("prompt_snapshot", systemPrompt=[TEMOIN])
        )
        self.assertEqual(c, ctx.Contexte())

    def test_a_line_that_is_not_an_attachment(self):
        for objet in ({"type": "assistant"}, [], "texte", None, 12):
            self.assertEqual(
                ctx.replier(ctx.Contexte(), objet), ctx.Contexte()
            )

    def test_the_carried_records_are_remembered(self):
        """« Non porté » et « porté mais vide » ne disent pas la même chose."""
        c = ctx.replier(ctx.Contexte(), _piece("skill_listing", skillCount=0))
        self.assertTrue(c.a("skill_listing"))
        self.assertFalse(ctx.Contexte().a("skill_listing"))


class TestLOrigineEtLAffichage(unittest.TestCase):
    def test_a_user_file_is_named_as_such(self):
        import os

        maison = os.path.expanduser("~/.claude")
        fichier = ctx.Fichier(chemin=f"{maison}/CLAUDE.md")
        self.assertEqual(fichier.origine, "utilisateur")

    def test_a_repository_file_is_named_as_such(self):
        self.assertEqual(
            ctx.Fichier(chemin="/un/depot/CLAUDE.md").origine, "dépôt"
        )

    def test_the_home_is_abbreviated_but_not_the_repository(self):
        """Le nom du dépôt est celui du travail en cours : il sert à se situer."""
        import os

        maison = os.path.expanduser("~")
        c = ctx.replier(
            ctx.Contexte(),
            _instructions(
                (f"{maison}/.claude/CLAUDE.md", "x"),
                (f"{maison}/git/un-depot/CLAUDE.md", "y"),
            ),
        )
        chemins = [c0 for c0, _, _ in ctx.instructions_affichables(c)]
        self.assertTrue(all(ch.startswith("~") for ch in chemins))
        self.assertIn("un-depot", chemins[1])

    def test_the_listing_is_bounded(self):
        c = ctx.replier(
            ctx.Contexte(),
            _instructions(*[(f"/a/{i}.md", "x") for i in range(40)]),
        )
        self.assertEqual(
            len(ctx.instructions_affichables(c)), ctx.INSTRUCTIONS_MAX
        )


class TestLaLecture(unittest.TestCase):
    def _fichier(self, lignes):
        texte = "\n".join(json.dumps(o, ensure_ascii=False) for o in lignes)

        class Faux:
            def __enter__(self):
                return iter(texte.splitlines())

            def __exit__(self, *args):
                return False

        return lambda chemin: Faux()

    def test_a_transcript_is_folded(self):
        c = ctx.lire(
            "/x.jsonl",
            ouvrir=self._fichier(
                [
                    {"type": "assistant"},
                    _piece("model", identity={"marketingName": "Un Modèle"}),
                    _instructions(("/a.md", "xx")),
                ]
            ),
        )
        self.assertEqual(c.modele, "Un Modèle")
        self.assertEqual(len(c.instructions), 1)

    def test_a_broken_line_is_skipped(self):
        class Faux:
            def __enter__(self):
                return iter(
                    [
                        json.dumps(_piece("skill_listing", skillCount=7)),
                        '{"type": "attachment", ceci est cassé',
                    ]
                )

            def __exit__(self, *args):
                return False

        c = ctx.lire("/x.jsonl", ouvrir=lambda chemin: Faux())
        self.assertEqual(c.skills, 7)

    def test_a_missing_file_is_an_empty_context(self):
        def absent(chemin):
            raise FileNotFoundError(2, chemin)

        self.assertEqual(ctx.lire("/x.jsonl", ouvrir=absent), ctx.Contexte())


if __name__ == "__main__":
    unittest.main()
