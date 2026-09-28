#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Choisit les fichiers de tests concernés par un changement ou un échec.

Deux sélections, que `run_unit_test.py` combine par union :

 - `concernes()` : les fichiers de tests qui DÉPENDENT d'un fichier modifié.
   Le graphe se lit dans le code, sans rien importer : chaque fichier Python
   pointe vers les modules qu'il importe — absolus, relatifs ou nus, ces
   derniers étant ceux qu'un `sys.path.insert` rend visibles — et vers les
   fichiers que DÉSIGNE une de ses chaînes : une chaîne qui n'est qu'un
   chemin, ou un nom porteur d'un répertoire dans une commande. Cette
   seconde arête couvre ce qu'aucun import ne dit : le script shell qu'un
   test exécute, le module qu'un autre charge par son chemin, le fichier
   JSON qu'il lit. Dans un module du code, elle ne vaut que pour les
   fichiers Python : un script shell n'y tourne que si l'on appelle le menu
   qui le lance. Un fichier de tests est retenu dès qu'un fichier modifié
   est atteignable depuis lui.

   Le graphe penche vers l'inclusion : un nom qui désigne plusieurs
   fichiers les désigne tous. Un test de trop coûte une seconde, un test
   oublié laisse passer ce qu'il devait arrêter.

 - `echecs_retenus()` / `retenir_echecs()` : les fichiers en échec au
   passage précédent, gardés dans un fichier hors du dépôt. Un fichier
   quitte la liste en passant ; un fichier arrêté par Ctrl+C n'a rien
   prouvé et garde son état.
"""

import ast
import os
import re
import subprocess

# Un nom de fichier dans une chaîne : « install_proxmox.sh »,
# « script/qemu/deploy_qemu.py », « conf/x.json ».
NOM_DE_FICHIER = re.compile(
    r"[\w.-]+\.(?:py|sh|json|xml|conf|ya?ml|toml|cfg|ini|txt|md|j2|service)\b"
)


def fichiers_modifies(racine, reference="HEAD"):
    """Chemins relatifs des fichiers qui diffèrent de `reference` — indexés
    ou non — et des fichiers non suivis. Vide hors d'un dépôt git."""

    def git(*args):
        res = subprocess.run(
            ["git", *args],
            cwd=racine,
            capture_output=True,
            text=True,
            check=False,
        )
        if res.returncode != 0:
            raise ValueError(res.stderr.strip() or f"git {' '.join(args)}")
        return [ligne for ligne in res.stdout.splitlines() if ligne]

    return sorted(
        set(git("diff", "--name-only", reference))
        | set(git("ls-files", "--others", "--exclude-standard"))
    )


def fichiers_du_depot(racine):
    """Les fichiers suivis et non ignorés : ceux qu'un nom peut désigner."""
    res = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=racine,
        capture_output=True,
        text=True,
        check=False,
    )
    return [ligne for ligne in res.stdout.splitlines() if ligne]


class Graphe:
    """Les dépendances des fichiers Python du dépôt, lues sans import."""

    def __init__(self, racine, fichiers):
        self.racine = racine
        self.fichiers = set(fichiers)
        # « script.todo.todo » -> « script/todo/todo.py »
        self.par_module = {}
        # « todo.py » -> {chemins} ; « todo » -> {chemins .py}
        self.par_nom = {}
        self.par_nom_module = {}
        for chemin in self.fichiers:
            nom = os.path.basename(chemin)
            self.par_nom.setdefault(nom, set()).add(chemin)
            if chemin.endswith(".py"):
                module = chemin[:-3].replace("/", ".")
                if module.endswith(".__init__"):
                    module = module[: -len(".__init__")]
                self.par_module[module] = chemin
                court = module.rsplit(".", 1)[-1]
                self.par_nom_module.setdefault(court, set()).add(chemin)
        self._aretes = {}

    def _modules(self, dotted):
        """Le fichier d'un module absolu, ou celui de son paquet."""
        trouves = set()
        if dotted in self.par_module:
            trouves.add(self.par_module[dotted])
        elif "." not in dotted:
            # Un nom nu : visible par un sys.path.insert, où qu'il soit.
            trouves |= self.par_nom_module.get(dotted, set())
        return trouves

    def _fichiers_cites(self, texte):
        """Les fichiers qu'une chaîne DÉSIGNE, et non ceux qu'elle nomme.

        Une chaîne qui n'est qu'un chemin — « deploy_qemu.py »,
        « script/x.sh » — désigne son fichier. Dans une phrase, seul un nom
        porteur d'un répertoire compte, celui d'une commande shell :
        « Relancer todo.py » est un message, et en faire une dépendance
        relie aux traductions tout ce que todo.py atteint."""
        seul = not any(c.isspace() for c in texte)
        trouves = set()
        for nom in NOM_DE_FICHIER.findall(texte):
            debut = texte.find(nom)
            avec_repertoire = debut > 0 and texte[debut - 1] == "/"
            if seul or avec_repertoire:
                trouves |= self.par_nom.get(os.path.basename(nom), set())
        return trouves

    def aretes(self, chemin):
        """Ce dont `chemin` dépend directement."""
        if chemin in self._aretes:
            return self._aretes[chemin]
        deps = set()
        try:
            with open(
                os.path.join(self.racine, chemin), encoding="utf-8"
            ) as fh:
                arbre = ast.parse(fh.read())
        except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
            self._aretes[chemin] = deps
            return deps
        paquet = os.path.dirname(chemin).replace("/", ".")
        # Un module cité par un TEST, quel que soit son type, est ce que le
        # test lit ou exécute. Cité par un module du code, un script shell
        # ne tourne que si l'on appelle le menu qui le lance : les tests qui
        # l'exécutent le nomment eux-mêmes. N'en garder que les fichiers
        # Python, qu'un module charge par leur chemin.
        est_un_test = os.path.basename(chemin).startswith("test_")
        for noeud in ast.walk(arbre):
            if isinstance(noeud, ast.Import):
                for alias in noeud.names:
                    deps |= self._modules(alias.name)
            elif isinstance(noeud, ast.ImportFrom):
                if noeud.level:
                    base = paquet.split(".")
                    base = base[: len(base) - noeud.level + 1]
                    module = ".".join(
                        [p for p in base if p] + [noeud.module or ""]
                    ).strip(".")
                else:
                    module = noeud.module or ""
                deps |= self._modules(module)
                # « from paquet import sous_module » : le nom importé peut
                # être un module à part entière.
                for alias in noeud.names:
                    deps |= self._modules(f"{module}.{alias.name}")
            elif isinstance(noeud, ast.Constant) and isinstance(
                noeud.value, str
            ):
                cites = self._fichiers_cites(noeud.value)
                if not est_un_test:
                    cites = {c for c in cites if c.endswith(".py")}
                deps |= cites
        deps.discard(chemin)
        self._aretes[chemin] = deps
        return deps

    def atteignables(self, depart):
        """Tout ce dont `depart` dépend, de proche en proche."""
        vus = set()
        pile = [depart]
        while pile:
            chemin = pile.pop()
            for dep in self.aretes(chemin) if chemin.endswith(".py") else ():
                if dep not in vus:
                    vus.add(dep)
                    pile.append(dep)
        return vus


def concernes(racine, tests, modifies):
    """Les fichiers de `tests` (chemins relatifs à `racine`) qu'un fichier
    de `modifies` touche : modifié lui-même, ou atteignable depuis lui."""
    modifies = set(modifies)
    if not modifies:
        return []
    graphe = Graphe(racine, fichiers_du_depot(racine) + list(modifies))
    retenus = []
    for test in tests:
        test = os.path.normpath(test)
        if test in modifies or graphe.atteignables(test) & modifies:
            retenus.append(test)
    return retenus


def echecs_retenus(chemin):
    """Les noms de fichiers en échec au passage précédent."""
    try:
        with open(chemin, encoding="utf-8") as fh:
            return {ligne.strip() for ligne in fh if ligne.strip()}
    except OSError:
        return set()


def retenir_echecs(chemin, passes, echoues):
    """Met à jour la liste : `echoues` y entrent, `passes` en sortent, les
    autres gardent leur état."""
    retenus = (echecs_retenus(chemin) - set(passes)) | set(echoues)
    try:
        os.makedirs(os.path.dirname(chemin), exist_ok=True)
        provisoire = chemin + ".tmp"
        with open(provisoire, "w", encoding="utf-8") as fh:
            for nom in sorted(retenus):
                fh.write(nom + "\n")
        os.replace(provisoire, chemin)
    except OSError:
        pass
    return retenus
