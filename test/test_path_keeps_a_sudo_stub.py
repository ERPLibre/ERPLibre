#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Un test qui remplace le PATH par celui du système double aussi sudo.

Le lanceur unitaire met en tête du PATH un sudo qui refuse. Un test qui
REMPLACE le PATH — « {bin_dir}:/usr/bin:/bin » — le perd, et le script qu'il
lance atteint alors le vrai sudo : sur un hôte qui exige un mot de passe, il
l'attend ; sur un hôte en NOPASSWD, il s'exécute en root sans rien dire.

La règle porte sur la FONCTION qui bâtit ce PATH, et non sur le fichier :
une doublure passée par un seul des tests qui l'appellent laisse les autres
atteindre le vrai sudo dès que le script avance d'une étape. La fonction la
garantit en citant « sudo », ou en se servant d'un dictionnaire de
doublures du module qui le contient.

Un PATH qui garde celui de l'appelant ($PATH, os.environ) garde aussi la
doublure du lanceur, et un PATH sans répertoire système n'atteint aucun
sudo : ni l'un ni l'autre n'est visé.
"""

import ast
import glob
import os
import re
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Fichiers dont le PATH système ne mène à aucun sudo, et pourquoi. Chaque
# entrée est une décision relue : la raison dit ce qui la rend sûre.
EXEMPTES = {
    "test_anonymize.py": (
        "le PATH est rendu par un pg_env simulé, et subprocess.run est"
        " remplacé par un espion : rien n'est exécuté"
    ),
    "test_qemu_privilege.py": (
        "le dictionnaire est l'entrée de system_env(), la fonction testée :"
        " rien n'est exécuté"
    ),
    "test_qemu_cache_guest.py": (
        "les commandes jouées sont celles qui tournent en root dans"
        " l'invité, et n'appellent pas sudo"
    ),
}

# Un répertoire système dans un PATH : « /usr/bin », « /bin », entre deux
# « : » ou en bout de chaîne.
SYSTEME = re.compile(r"(?:^|:)/(?:usr/)?s?bin(?::|$)")


def _texte(noeud):
    """Les parties constantes d'une chaîne, f-string comprise."""
    if isinstance(noeud, ast.Constant) and isinstance(noeud.value, str):
        return noeud.value
    if isinstance(noeud, ast.JoinedStr):
        return "".join(
            v.value
            for v in noeud.values
            if isinstance(v, ast.Constant) and isinstance(v.value, str)
        )
    return None


def _garde_l_appelant(noeud):
    """Le PATH construit reprend-il celui de l'appelant ?"""
    texte = _texte(noeud) or ""
    if "$PATH" in texte:
        return True
    for n in ast.walk(noeud):
        if isinstance(n, ast.Attribute) and n.attr == "environ":
            return True
        if isinstance(n, ast.Constant) and n.value == "PATH":
            return True
    return False


def paths_systeme(fonction):
    """Les valeurs de PATH qui remplacent celui de l'appelant par des
    répertoires système, dans le corps de `fonction`."""
    trouves = []
    for n in ast.walk(fonction):
        valeurs = []
        if isinstance(n, ast.keyword) and n.arg == "PATH":
            valeurs.append(n.value)
        elif isinstance(n, ast.Dict):
            valeurs += [
                v
                for k, v in zip(n.keys, n.values)
                if isinstance(k, ast.Constant) and k.value == "PATH"
            ]
        for v in valeurs:
            texte = _texte(v)
            if texte and SYSTEME.search(texte) and not _garde_l_appelant(v):
                trouves.append(v)
    return trouves


def _cite_sudo(noeud, doublures):
    for n in ast.walk(noeud):
        if isinstance(n, ast.Constant) and n.value == "sudo":
            return True
        if isinstance(n, ast.Name) and n.id in doublures:
            return True
    return False


def manquements(chemin):
    """[(ligne, fonction)] des PATH système sans doublure sudo."""
    with open(chemin, encoding="utf-8") as fh:
        arbre = ast.parse(fh.read())
    # Les dictionnaires de doublures du module qui contiennent sudo.
    doublures = set()
    for n in arbre.body:
        if isinstance(n, ast.Assign) and _cite_sudo(n.value, set()):
            doublures |= {t.id for t in n.targets if isinstance(t, ast.Name)}
    trouves = []
    fonctions = [
        n
        for n in ast.walk(arbre)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    for fonction in fonctions:
        # La fonction la plus intérieure répond de son PATH : une fonction
        # imbriquée est examinée pour elle-même.
        internes = {
            id(v)
            for f in ast.walk(fonction)
            if f is not fonction
            and isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
            for v in paths_systeme(f)
        }
        for valeur in paths_systeme(fonction):
            if id(valeur) in internes:
                continue
            if not _cite_sudo(fonction, doublures):
                trouves.append((valeur.lineno, fonction.name))
    return trouves


class TestLePathSystemeDoubleSudo(unittest.TestCase):
    def test_every_system_path_comes_with_a_sudo_stub(self):
        fautes = []
        for chemin in sorted(
            glob.glob(os.path.join(RACINE, "test/test_*.py"))
        ):
            nom = os.path.basename(chemin)
            if nom in EXEMPTES:
                continue
            fautes += [
                f"{nom}:{ligne} dans {fonction}()"
                for ligne, fonction in manquements(chemin)
            ]
        self.assertEqual(
            fautes,
            [],
            "PATH système sans doublure sudo : la fonction doit fournir un"
            ' « sudo » (par ex. {"sudo": \'exec "$@"\'}), ou le fichier'
            " entrer dans EXEMPTES avec sa raison",
        )

    def test_every_exemption_still_builds_a_system_path(self):
        """Une exemption qui ne vise plus rien exempterait en silence le
        prochain PATH système de ce fichier."""
        for nom in EXEMPTES:
            chemin = os.path.join(RACINE, "test", nom)
            with open(chemin, encoding="utf-8") as fh:
                arbre = ast.parse(fh.read())
            fonctions = [
                n
                for n in ast.walk(arbre)
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            ]
            self.assertTrue(
                any(paths_systeme(f) for f in fonctions),
                f"{nom} n'a plus de PATH système : retirer l'exemption",
            )


class TestLaRegle(unittest.TestCase):
    """La règle sur des cas écrits pour elle."""

    def _fautes(self, source):
        import tempfile

        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, encoding="utf-8"
        ) as fh:
            fh.write(source)
        self.addCleanup(os.unlink, fh.name)
        return manquements(fh.name)

    def test_a_helper_without_sudo_is_caught(self):
        source = (
            "def lance(d, stubs):\n"
            "    return run(env=dict(PATH=f'{d}:/usr/bin:/bin'))\n"
            "def test_x():\n"
            "    lance('d', {'sudo': 'exit 0'})\n"
        )
        self.assertEqual(self._fautes(source), [(2, "lance")])

    def test_a_helper_with_its_own_sudo_passes(self):
        source = (
            "def lance(d, stubs):\n"
            "    stubs = {'sudo': 'exit 1', **stubs}\n"
            "    return run(env={'PATH': f'{d}:/usr/bin:/bin'})\n"
        )
        self.assertEqual(self._fautes(source), [])

    def test_a_module_level_stub_table_counts(self):
        source = (
            "DOUBLURES = {'sudo': 'exec \"$@\"'}\n"
            "def lance(d):\n"
            "    stubs = dict(DOUBLURES)\n"
            "    return run(env={'PATH': f'{d}:/usr/bin'})\n"
        )
        self.assertEqual(self._fautes(source), [])

    def test_keeping_the_caller_path_is_not_a_replacement(self):
        source = (
            "def lance(d):\n"
            "    return run(env={'PATH': f'{d}:' + os.environ['PATH']})\n"
            "def lance2(d):\n"
            "    return run(env={'PATH': f'{d}:$PATH:/usr/bin'})\n"
        )
        self.assertEqual(self._fautes(source), [])

    def test_a_path_without_system_directories_reaches_no_sudo(self):
        source = "def lance(d):\n    return run(env={'PATH': str(d)})\n"
        self.assertEqual(self._fautes(source), [])


if __name__ == "__main__":
    unittest.main()
