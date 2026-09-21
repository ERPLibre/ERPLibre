#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un script avec shebang doit être exécutable — dans ce que git STOCKE.

Le bit d'exécution n'accorde rien : qui peut lire le fichier peut déjà faire
« python3 fichier ». Il décide seulement si « ./script/... » fonctionne.

L'écriture par le groupe ne s'exige pas ici : git ne stocke QUE le bit
d'exécution — 100644 ou 100755 — et le reste vient de l'umask de celui qui
fait le checkout. Sous umask 0002, chaque checkout produit 775, et un test du
disque échoue pour une raison qui n'est pas dans le dépôt.

On vérifie donc l'index, seul mode que le dépôt porte et propage. Le mode du
disque reste l'affaire de la machine, pas d'un test.
"""

import ast
import glob
import os
import re
import subprocess
import tempfile
import unittest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

PATTERNS = (
    "script/analyse/*.py",
    "script/analyse/*/*.py",
    "script/odoo/migration/*.py",
)


def scripts():
    """(chemin, a un shebang) pour chaque script des dossiers visés."""
    found = []
    for pattern in PATTERNS:
        for path in sorted(glob.glob(os.path.join(REPO, pattern))):
            with open(path, "rb") as handle:
                found.append((path, handle.read(2) == b"#!"))
    return found


def index_mode(path):
    """Le mode que GIT porte pour ce fichier : 100644 ou 100755."""
    done = subprocess.run(
        ["git", "ls-files", "-s", "--", os.path.relpath(path, REPO)],
        capture_output=True,
        text=True,
        cwd=REPO,
    )
    if done.returncode or not done.stdout.strip():
        return None
    return done.stdout.split()[0]


class TestExecutableBit(unittest.TestCase):
    def test_the_inventory_is_not_empty(self):
        # Un test qui ne trouve rien passe toujours.
        self.assertGreater(len(scripts()), 10)

    def test_every_shebang_script_is_executable_in_git(self):
        # Dans l'index, pas sur le disque : c'est ce que reçoivent les
        # autres. Un fichier rendu exécutable localement sans être commité
        # marcherait ici et nulle part ailleurs.
        for path, has_shebang in scripts():
            if not has_shebang:
                continue
            relative = os.path.relpath(path, REPO)
            mode = index_mode(path)
            if mode is None:
                continue  # non suivi : rien à garantir pour personne
            with self.subTest(script=relative):
                self.assertEqual(mode, "100755", relative)

    def test_a_file_without_shebang_is_not_marked_executable(self):
        # Le symétrique : un bit d'exécution sur un fichier qu'aucun
        # interpréteur ne réclame dit une intention qui n'existe pas.
        for path, has_shebang in scripts():
            if has_shebang:
                continue
            mode = index_mode(path)
            if mode is None:
                continue
            with self.subTest(script=os.path.relpath(path, REPO)):
                self.assertEqual(mode, "100644")

    def test_the_check_reads_git_not_the_filesystem(self):
        # Le défaut corrigé : l'umask du poste décide de 755 contre 775, et
        # un test qui le lit échoue sur la machine des autres. On le vérifie
        # par les IMPORTS — chercher un nom de constante dans la source d'un
        # fichier qui contient ce test échouerait sur lui-même.
        import ast

        with open(__file__) as handle:
            tree = ast.parse(handle.read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module)
        self.assertIn("subprocess", imported)
        self.assertNotIn("stat", imported)


class TestAucuneGardeNeLitLeCodeDUneAffectation(unittest.TestCase):
    """« $? » ne survit pas à la commande suivante, et une AFFECTATION en
    est une.

    Lu après « ARGS=… », il valait le code de l'affectation — toujours zéro.
    La garde qui suivait ne pouvait donc jamais se déclencher, et un
    docker-compose non réécrit partait en construction sans un mot.

    Une commande préfixée d'une variable — « EL_PHASE=setup ./script.sh » —
    n'est PAS une affectation : son « $? » est bien celui de la commande, et
    le détecteur doit l'écarter. C'est le faux positif qui l'éprouve.
    """

    # Une affectation PURE : un nom, une valeur, et RIEN d'autre.
    PURE = re.compile(r"""^\s*\w+=(?:"[^"]*"|'[^']*'|[^\s;&|]*)\s*$""")
    CAPTURE = re.compile(r"^\s*\w+=\$\?\s*$")

    @classmethod
    def gardes_mortes(cls, racine):
        out = []
        for dossier, _sous, fichiers in os.walk(racine):
            for nom in sorted(fichiers):
                if not nom.endswith(".sh"):
                    continue
                chemin = os.path.join(dossier, nom)
                with open(chemin, encoding="utf-8", errors="replace") as fic:
                    lignes = fic.read().splitlines()
                for i, ligne in enumerate(lignes):
                    if not cls.CAPTURE.match(ligne):
                        continue
                    j = i - 1
                    while j >= 0 and (
                        not lignes[j].strip()
                        or lignes[j].strip().startswith("#")
                    ):
                        j -= 1
                    if j >= 0 and cls.PURE.match(lignes[j]):
                        out.append(f"{os.path.relpath(chemin, REPO)}:{i + 1}")
        return out

    def test_the_detector_tells_an_assignment_from_a_prefixed_command(self):
        """SANS CE CONTRÔLE, le détecteur peut être cassé dans un sens ou
        dans l'autre sans que rien ne le dise : trop large, il accuse les
        commandes préfixées ; trop étroit, il ne voit plus rien."""
        bac = tempfile.mkdtemp()
        mort = os.path.join(bac, "mort.sh")
        with open(mort, "w", encoding="utf-8") as fic:
            fic.write('faire_un_truc\nARGS="x"\nretVal=$?\n')
        vivant = os.path.join(bac, "vivant.sh")
        with open(vivant, "w", encoding="utf-8") as fic:
            fic.write("EL_PHASE=setup ./script.sh\nretVal=$?\n")
        vus = self.gardes_mortes(bac)
        self.assertEqual(["mort.sh:3"], [v.split("/")[-1] for v in vus])

    def test_no_shell_script_reads_the_status_of_an_assignment(self):
        self.assertEqual([], self.gardes_mortes(os.path.join(REPO, "script")))


class TestAucunDrapeauAccepteEnSilence(unittest.TestCase):
    """Un drapeau déclaré que rien ne lit est accepté et ne fait RIEN.

    C'est pire qu'un drapeau absent : celui-là rend « unrecognized
    arguments » et l'on sait tout de suite. Cinq l'étaient, dont un qui
    promettait trois choses — changer le répertoire de téléchargement, le
    vider au démarrage, servir au grid réseau — et dont la branche avait
    été retirée en rendant le répertoire temporaire inconditionnel. L'aide
    était restée.

    TROIS PIÈGES, tous payés en écrivant cette garde :
    - `firefox_options.add_argument("--no-sandbox")` porte le même nom de
      méthode et n'est pas argparse : le receveur doit être un parser ;
    - un fichier peut ne créer que des GROUPES, le parser lui étant passé
      en paramètre — chercher « ArgumentParser » dans la source l'écarte ;
    - `dest=` décide du nom d'attribut : « --nb_parent » se lit
      « args.parent_depth », et le chercher sous son nom le dirait mort.
    """

    # Le fichier porte déjà REPO ; en poser un second les ferait
    # diverger au premier déplacement.
    RACINE = REPO

    @classmethod
    def parsers_de(cls, arbre):
        noms = set()
        for n in ast.walk(arbre):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                f = n.value.func
                appel = getattr(f, "attr", getattr(f, "id", ""))
                if appel in (
                    "ArgumentParser",
                    "add_argument_group",
                    "add_parser",
                ):
                    noms |= {
                        t.id for t in n.targets if isinstance(t, ast.Name)
                    }
        return noms

    @classmethod
    def drapeaux_de(cls, chemin):
        """{(drapeau, attribut)} déclarés sur un parser de ce fichier."""
        src = open(chemin, encoding="utf-8").read()
        if "add_argument" not in src:
            return set()
        try:
            arbre = ast.parse(src)
        except SyntaxError:
            return set()
        parsers = cls.parsers_de(arbre)
        out = set()
        for n in ast.walk(arbre):
            if not (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_argument"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id in parsers
            ):
                continue
            dest = None
            for kw in n.keywords:
                if kw.arg == "dest" and isinstance(kw.value, ast.Constant):
                    dest = kw.value.value
            for a in n.args:
                if (
                    isinstance(a, ast.Constant)
                    and isinstance(a.value, str)
                    and a.value.startswith("--")
                ):
                    out.add((a.value, dest or a.value[2:].replace("-", "_")))
        return out

    @classmethod
    def tout_le_source(cls):
        morceaux = []
        for dossier in ("script", "test"):
            base = os.path.join(cls.RACINE, dossier)
            for r, _d, fichiers in os.walk(base):
                for nom in fichiers:
                    if nom.endswith(".py"):
                        with open(
                            os.path.join(r, nom), encoding="utf-8"
                        ) as fic:
                            morceaux.append(fic.read())
        return "\n".join(morceaux)

    @classmethod
    def setUpClass(cls):
        cls.source = cls.tout_le_source()
        cls.tous = []
        for r, _d, fichiers in os.walk(os.path.join(cls.RACINE, "script")):
            for nom in sorted(fichiers):
                if nom.endswith(".py"):
                    chemin = os.path.join(r, nom)
                    for paire in sorted(cls.drapeaux_de(chemin)):
                        cls.tous.append((chemin, paire))

    def est_lu(self, attribut):
        motif = re.compile(r"\.%s\b|[\"']%s[\"']" % (attribut, attribut))
        return bool(motif.search(self.source))

    def test_the_scan_actually_finds_flags(self):
        """Sur zéro drapeau trouvé, la garde passe et ne tient rien.

        Trois fois le détecteur s'est cassé en silence en l'écrivant ;
        c'est ici que ça doit tomber."""
        self.assertGreater(len(self.tous), 100)

    def test_no_flag_is_declared_and_never_read(self):
        morts = [
            f"{os.path.relpath(c, self.RACINE)} : {d}"
            for c, (d, attribut) in self.tous
            if not self.est_lu(attribut)
        ]
        self.assertEqual([], morts)


class TestTheTuiSaysWhyItRefuses(unittest.TestCase):
    """Rendre un script lançable ouvre un chemin sans le venv.

    Le shebang est « #!/usr/bin/env python3 » : lancé directement depuis un
    shell où le venv n'est pas actif, c'est le python du système qui répond,
    et Textual n'y est pas. La TUI retombait alors sur le rapport texte sans
    rien dire — le même défaut muet que le tube de sortie.
    """

    def run_tui(self):
        import sys

        sys.path.insert(0, os.path.join(REPO, "script", "odoo", "migration"))
        self.addCleanup(sys.path.remove, sys.path[0])
        from cow_drift_tui import run_tui

        return run_tui

    def finding(self):
        return {
            "id": 1,
            "key": "k",
            "website_id": 1,
            "reason": "r",
            "module_id": 2,
            "module_arch": "a",
            "copy_arch": "b",
            "decl_current": None,
            "decl_target": None,
            "current_version": "odoo12.0",
            "target_version": "odoo13.0",
        }

    def test_a_pipe_is_explained_not_swallowed(self):
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            result = self.run_tui()([self.finding()])
        self.assertFalse(result)
        self.assertTrue(out.getvalue().strip(), "refus muet")

    def test_nothing_to_show_stays_silent(self):
        # Une liste vide n'est pas un refus : il n'y a rien à annoncer.
        import io
        from contextlib import redirect_stdout

        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(self.run_tui()([]))
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
