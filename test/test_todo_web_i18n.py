#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les mots de la page web de TODO.

Chaque chaîne d'interface de `static/src` passe par la table de traduction
de TODO : la clé littérale d'un appel `t("…")` (`env.t`, `this.env.t`,
`_t`) ou une valeur d'un objet `*_LABELS` existe dans TRANSLATIONS, en
français et en anglais. Un gabarit OWL n'écrit aucun mot à lui, ni entre
ses balises, ni dans un attribut que l'utilisateur lit (aria-label,
placeholder, title, alt), ni dans une expression qu'il affiche (`t-esc`,
`t-out`, `t-att-` de ces attributs) hors d'un appel `t('…')` ; un signe
seul, « … » ou « › », y reste permis. Et le code de la page ne nomme
aucune méthode de TODO ni aucun identifiant de menu : ce qu'elle montre
vient des messages et de /api/telemetry.
"""

import ast
import re
import unittest
from pathlib import Path

from script.todo import todo_i18n, todo_telemetry

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "script" / "todo" / "web" / "static" / "src"
# Un gabarit OWL : `xml` suivi d'un littéral de gabarit.
TEMPLATE = re.compile(r"\bxml`(.*?)`", re.S)
# Une balise, guillemets respectés : `() => …` y reste.
TAG = re.compile(r"""<(?:"[^"]*"|'[^']*'|[^'">])*>""")
# Une lettre, de toute écriture.
LETTER = re.compile(r"[^\W\d_]")
# Un attribut lu par l'utilisateur, écrit en dur.
READ_ATTRIBUTE = re.compile(
    r"""(?<![-\w])(aria-label|placeholder|title|alt)="""
)
# Une expression qu'un gabarit affiche : son texte, ou un attribut lu.
SHOWN = re.compile(
    r'\s(?:t-esc|t-out|t-att-(?:aria-label|placeholder|title|alt))="([^"]*)"'
)
# Un appel de traduction à clé littérale, `env.t('…')`.
CALL = re.compile(r"""\b_?t\((['"])(?:(?!\1).)*\1\)""")
# Un littéral entre guillemets simples ou doubles.
QUOTED = re.compile(r"""(['"])((?:(?!\1).)*)\1""")
# Le bandeau d'une connexion expirée : il nomme l'entrée du menu principal
# de TODO qui ouvre l'interface par son libellé, jamais par son numéro.
EXPIRED = (
    "Connection expired: reopen the interface from TODO › "
    "Navigation telemetry."
)


def _todo_class():
    """La classe TODO de todo.py, lue sans l'importer."""
    source = (REPO / "script" / "todo" / "todo.py").read_text(encoding="utf-8")
    return next(
        n for n in ast.walk(ast.parse(source)) if isinstance(n, ast.ClassDef)
    )


def _command_names() -> set:
    """Méthodes que l'arbre de TODO rattache à un menu ou à une feuille,
    et toutes celles que nomme un menu du registre : état, suffixe,
    garde.

    Seuls les noms qui contiennent « _ » sont gardés : « run » ou « quit »
    sont aussi des mots courants, un nom composé ne l'est jamais.
    """
    names = set()

    def walk(node):
        if node.get("method"):
            names.add(node["method"])
        for child in node["children"]:
            walk(child)

    walk(todo_telemetry.build_code_tree())
    names |= set(todo_telemetry._menu_labels(_todo_class()))
    todo_dir = REPO / "script" / "todo"
    for menu in todo_telemetry._declared_menus(todo_dir).values():
        names |= {menu.get("name"), menu.get("state")}
        for item in menu.get("entries") or []:
            names |= {item.get(k) for k in ("action", "suffix", "when")}
    return {name for name in names if name and "_" in name}


def _written(tag) -> list:
    """Les littéraux à lettres des expressions que `tag` affiche, hors des
    appels `t('…')` : des mots écrits en dur, que la traduction ne voit
    pas."""
    words = []
    for value in SHOWN.findall(tag):
        for _, literal in QUOTED.findall(CALL.sub("", value)):
            if LETTER.search(literal):
                words.append(literal)
    return words


def page_keys() -> set:
    """Clés de traduction que la page emploie : les littéraux de `t(…)` et
    les valeurs des objets `*_LABELS`, écrits sur une ou plusieurs
    lignes."""
    keys = set()
    labels = re.compile(r"^const \w+_LABELS = \{.*?\};$", re.M | re.S)
    for path in SRC.glob("*.js"):
        text = path.read_text(encoding="utf-8")
        keys |= {m[1] for m in re.findall(r"\b_?t\((['\"])(.+?)\1\)", text)}
        for block in labels.findall(text):
            keys |= set(re.findall(r'"([^"]+)"', block))
    return keys


class TestWords(unittest.TestCase):
    def test_every_key_of_the_page_is_translated_in_both_languages(self):
        # t() rend une clé inconnue telle quelle : une faute de frappe
        # s'afficherait en anglais dans une page française.
        keys = page_keys()
        # Les clés d'un objet sur plusieurs lignes sont lues aussi.
        self.assertIn("Connection lost.", keys)
        self.assertIn("Other answer", keys)
        self.assertGreater(len(keys), 10)
        missing = sorted(keys - set(todo_i18n.TRANSLATIONS))
        self.assertEqual(missing, [])
        for key in sorted(keys):
            entry = todo_i18n.TRANSLATIONS[key]
            self.assertTrue(entry.get("fr") and entry.get("en"), key)

    def test_templates_write_no_words_of_their_own(self):
        templates = 0
        for path in sorted(SRC.glob("*.js")):
            text = path.read_text(encoding="utf-8")
            for template in TEMPLATE.findall(text):
                templates += 1
                between = TAG.sub("", template)
                self.assertIsNone(LETTER.search(between), path.name)
                for tag in TAG.findall(template):
                    self.assertIsNone(READ_ATTRIBUTE.search(tag), tag)
                    self.assertEqual(_written(tag), [], tag)
        self.assertGreater(templates, 5)
        # Un mot en dur dans une expression affichée se voit.
        shown = """<b t-esc="n + ' s'" t-att-aria-label="env.t('Close')"/>"""
        self.assertEqual(_written(shown), [" s"])

    def test_the_expired_banner_names_the_menu_by_its_current_label(self):
        # Le libellé de l'entrée, emoji ôté, tel que TODO l'affiche dans
        # chaque langue : un libellé renommé fait échouer ce test.
        self.assertIn(EXPIRED, page_keys())
        label = todo_telemetry._menu_labels(_todo_class())["prompt_telemetry"]
        for lang in todo_i18n.LANGUAGES:
            shown = todo_i18n.translate(label, lang).split(" ", 1)[1]
            self.assertTrue(
                todo_i18n.TRANSLATIONS[EXPIRED][lang].endswith(
                    f" TODO › {shown}."
                ),
                lang,
            )

    def test_the_page_code_names_no_command(self):
        names = _command_names()
        self.assertGreater(len(names), 50)
        # Le registre compte : une ligne d'état, un suffixe.
        self.assertLessEqual({"_web_state", "_pref_label"}, names)
        for path in sorted(SRC.glob("*.js")):
            words = set(re.findall(r"\w+", path.read_text(encoding="utf-8")))
            self.assertFalse(words & names, path.name)


if __name__ == "__main__":
    unittest.main()
