#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le guide de migration du README mène-t-il à la migration ?

La section « Migrate a database between Odoo versions » de `README.base.md`
donne une suite de touches à taper dans TODO. Les numéros des menus bougent
dès qu'on insère une entrée, et rien d'autre ne relie le guide au code : il
pourrait envoyer le lecteur dans le mauvais écran sans que rien ne proteste.

Ce test lit les touches DANS le README — jamais une copie — et les rejoue
contre le vrai `TODO().run()`. Une seule file alimente `click.prompt` et
`input` : le guide ne dit pas lequel des deux lit la touche, le test non plus.
Les installations et la migration sont remplacées par des sondes ; la
configuration est celle d'un clone neuf, `todo.json` seul, sans les
surcharges privées du poste qui lance le test.
"""

import contextlib
import io
import json
import os
import re
import unittest
from unittest.mock import MagicMock, patch

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README = os.path.join(RACINE, "README.base.md")
TODO_JSON = os.path.join(RACINE, "script", "todo", "todo.json")

TITRES = {
    "en": "# Migrate a database between Odoo versions",
    "fr": "# Migrer une base de données entre versions d'Odoo",
}
# « > 7   Update » : la touche est le premier mot après le chevron.
RE_TOUCHE = re.compile(r"^> (\S+)", re.M)


def touches_du_guide(titre):
    """Les touches du premier bloc ```text qui suit `titre` dans le README."""
    with open(README, encoding="utf-8") as fichier:
        texte = fichier.read()
    debut = texte.index(titre + "\n")
    bloc = texte.index("```text\n", debut) + len("```text\n")
    fin = texte.index("```", bloc)
    return RE_TOUCHE.findall(texte[bloc:fin])


class MigrationAtteinte(Exception):
    """Levée par la sonde de migration : la séquence est arrivée au but."""


class TestGuideMigration(unittest.TestCase):
    def test_the_guide_was_actually_parsed(self):
        # Si le bloc change de forme, tomber ici plutôt que rejouer une
        # séquence vide et conclure que tout va bien.
        self.assertGreaterEqual(len(touches_du_guide(TITRES["en"])), 5)

    def test_both_languages_type_the_same_keys(self):
        self.assertEqual(
            touches_du_guide(TITRES["en"]), touches_du_guide(TITRES["fr"])
        )

    def test_the_keys_reach_the_database_migration(self):
        from script.todo import todo as module_todo
        from script.todo.todo import TODO

        touches = list(touches_du_guide(TITRES["en"]))
        restantes = iter(touches)

        def taper(*_args, **_kwargs):
            # Une touche de trop demandée : le guide s'arrête avant le but.
            try:
                return next(restantes)
            except StopIteration:
                self.fail(
                    "le guide est épuisé avant la migration :"
                    f" {' '.join(touches)}"
                )

        def todo_json_seul(_self, cle):
            with open(TODO_JSON, encoding="utf-8") as fichier:
                return json.load(fichier).get(cle)

        todo = TODO()
        todo.execute = MagicMock()
        # `which pycharm` échoue : pas de question sur l'IDE à intercaler.
        commande = MagicMock(returncode=1, stdout="", stderr="")
        # `todo_upgrade` n'est lié au module que si `script/todo` est sur
        # sys.path, ce qui n'est pas le cas sous le lanceur de tests.
        migration = MagicMock(
            MigrationRewind=type("Rembobine", (Exception,), {})
        )
        migration.TodoUpgrade.return_value.execute_odoo_upgrade.side_effect = (
            MigrationAtteinte
        )
        with (
            patch("click.prompt", side_effect=taper),
            patch("builtins.input", side_effect=taper),
            patch.object(TODO, "_ask_language"),
            patch.object(type(todo.config_file), "get_config", todo_json_seul),
            patch.object(
                module_todo.subprocess, "run", return_value=commande
            ) as lancer,
            patch.object(module_todo, "todo_upgrade", migration, create=True),
            patch("script.todo.todo_telemetry.record"),
            # Les menus s'affichent à chaque touche : les taire, sauf échec.
            contextlib.redirect_stdout(io.StringIO()),
        ):
            with self.assertRaises(
                MigrationAtteinte,
                msg="la séquence du guide n'ouvre pas la migration",
            ):
                todo.run()

        self.assertEqual(
            list(restantes), [], "le guide tape des touches en trop"
        )
        commandes = [appel.args[0] for appel in lancer.call_args_list]
        self.assertIn("make install_odoo_all_version", commandes)
        todo.execute.exec_command_live.assert_any_call(
            "./script/version/update_env_version.py --install",
            source_erplibre=True,
        )


if __name__ == "__main__":
    unittest.main()
