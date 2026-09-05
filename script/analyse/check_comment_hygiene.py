#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Les commentaires d'un fichier disent-ils le fonctionnement, ou son contexte ?

La convention est dans `.claude/rules/04-code-conventions.md` : un commentaire
dit COMMENT le code marche, il ne porte aucune donnée identifiante et il ne
raconte pas l'enquête. Cet outil en vérifie la part mécanique.

Deux familles, de sûreté très différente :

- `identifiant` — adresse IP, courriel, chemin de compte. Une
  correspondance est une trouvaille : ces formes n'ont aucune raison d'être
  dans un commentaire.
- `récit` — marqueur de témoignage (« vécu sur », « mesuré le »), date
  absolue, première personne. Une correspondance est un SIGNAL À RELIRE : la
  même phrase peut énoncer un fait durable. L'outil ne trie pas à la place
  du lecteur.

Il lit les commentaires `#` et, en Python, les docstrings de module, de classe
et de fonction. Le reste du code ne l'intéresse pas.

Il se signale lui-même : ce fichier CITE les marqueurs qu'il cherche, et ses
citations sont des correspondances comme les autres. Ces trouvailles-là sont
la définition de l'outil, pas un défaut à corriger.

Codes de sortie, convention partagée des outils du dépôt : 0 rien à signaler,
1 des trouvailles, 2 l'outil a échoué.
"""

from __future__ import annotations

import argparse
import ast
import io
import json
import os
import re
import subprocess
import sys
import tokenize

RACINE = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))

sys.path.append(RACINE)
sys.path.append(os.path.join(RACINE, "script"))

# Réexportés pour que ce module reste le seul point d'entrée de l'outil.
from lib_identifiant import exemples_declares  # noqa: E402,F401
from lib_identifiant import (
    NOMS_INTERDITS,
    adresse_de_machine,
    identifiants,
    termes_interdits,
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


# Le code porte ses phrases dans des commentaires ; la prose et les gabarits
# les portent partout. Les deux familles se lisent donc différemment, mais
# la même règle s'y applique : un nom de machine se dépose aussi bien dans un
# runbook ou un vhost que dans une docstring.
SUFFIXES_CODE = (".py", ".sh", ".bash")
SUFFIXES_TEXTE = (
    ".md",
    ".txt",
    ".json",
    ".yaml",
    ".yml",
    ".html",
    ".hcl",
    ".tsv",
)
SUFFIXES = SUFFIXES_CODE + SUFFIXES_TEXTE

# Ce qui vient d'ailleurs ou n'est pas du source : le dépôt ne le réécrit pas.
# « /private/ » et « /tasks/ » ne sont pas versionnés et portent EXPRÈS ce que
# ni le code ni un commit ne doivent porter — l'un la donnée de client, l'autre
# l'enquête et ses relevés. L'y signaler ferait une faute de ce qui est rangé
# là pour cette raison même.
EXCLUS = (
    "/OCA_",
    "/addons/",
    "/.venv",
    "/node_modules/",
    "/.git/",
    "/private/",
    "/tasks/",
)


def est_genere(chemin):
    """Ce Markdown est-il produit par mmg depuis un « .base.md » ?

    La règle 07 interdit d'éditer un fichier produit : la modification part
    au prochain rendu. Signaler la copie en plus de sa source ferait pointer
    la même phrase jusqu'à trois fois, dont deux à une ligne qu'on ne peut
    pas corriger.
    """
    if not chemin.endswith(".md"):
        return False
    base = re.sub(r"(\.fr)?\.md$", ".base.md", chemin)
    return base != chemin and os.path.exists(base)


def a_balayer(chemin):
    """Un chemin du dépôt, et non du code tiers, un environnement ou du rendu."""
    normalise = chemin.replace(os.sep, "/")
    while normalise.startswith("./"):
        normalise = normalise[2:]
    if any(exclu in "/" + normalise for exclu in EXCLUS):
        return False
    return not est_genere(normalise)


# Le témoignage : la phrase prend un événement pour sujet au lieu du code.
# L'accent porte la distinction : « mesuré sur » témoigne, « mesure le »
# décrit ce que le code fait. Sans lui, le motif prend le présent pour du passé.
# « le relevé » est un NOM et prend les mêmes prépositions : un déterminant
# devant le participe désigne la chose relevée, pas l'acte de relever.
RECIT = re.compile(
    r"(?<!\w)(?<!(?:le|du|au|un|ce)\s)(?<!(?:son|des|les|aux|mon|ton)\s)"
    r"(?:vécu|mesuré|relevé|rapporté|constaté|observé|signalé)e?s?"
    r"(?:[,]?\s+(?:sur|le|la|les|dans|chez|par|au|aux|en|à|ce|deux|trois)\b"
    r"|\s*[:—])",
    re.IGNORECASE,
)

# Une date absolue date le commentaire : le fonctionnement, lui, n'a pas de date.
DATE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}\b"
    r"|\b\d{1,2}\s+(?:janvier|février|mars|avril|mai|juin|juillet|août"
    r"|septembre|octobre|novembre|décembre)\s+\d{4}\b",
    re.IGNORECASE,
)

# Le rédacteur pris pour sujet : « ma conclusion était fausse », « mes essais ».
PERSONNE = re.compile(
    r"(?<![\w'])(?:j'|je|ma|mon|mes|nous\s+avons"
    r"|ce\s+matin|la\s+veille|ce\s+jour-là|hier)\b",
    re.IGNORECASE,
)

MOTIFS_RECIT = (
    ("témoignage", RECIT),
    ("date", DATE),
    ("personne", PERSONNE),
)


def _bloc(sous_lignes):
    """Un bloc : son texte recollé, et les lignes physiques qui le portent.

    Le texte recollé sert à CHERCHER — une phrase coupée en trois lignes reste
    une phrase. Chaque sous-ligne garde en plus son OFFSET dans ce texte : une
    occurrence trouvée à la position n se convertit alors en numéro de ligne
    sans jamais rechercher l'extrait, qui se retrouverait dans un autre mot.
    """
    debuts, position = [], 0
    for numero, texte in sous_lignes:
        debuts.append((position, numero))
        position += len(texte) + 1
    return {
        "line": sous_lignes[0][0],
        "text": " ".join(texte for _, texte in sous_lignes),
        "lines": sous_lignes,
        "offsets": debuts,
    }


def _regroupe(lignes_commentees):
    """Les lignes consécutives forment un bloc ; un trou en ouvre un autre."""
    blocs, courant = [], []
    for numero, texte in lignes_commentees:
        if courant and numero == courant[-1][0] + 1:
            courant.append((numero, texte))
        else:
            if courant:
                blocs.append(_bloc(courant))
            courant = [(numero, texte)]
    if courant:
        blocs.append(_bloc(courant))
    return blocs


def blocs_python(source):
    """Les commentaires et docstrings d'un source Python.

    Une docstring garde ses lignes PHYSIQUES, relues dans le source : le
    littéral de l'AST a perdu son indentation et ses numéros.
    """
    lignes_source = source.split("\n")

    commentaires = []
    lisible = True
    try:
        for jeton in tokenize.generate_tokens(io.StringIO(source).readline):
            if jeton.type == tokenize.COMMENT:
                commentaires.append(
                    (jeton.start[0], jeton.string.lstrip("#").strip())
                )
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # Un source que Python refuse reste du texte : le balayage ligne à
        # ligne voit encore les « # », là où rendre un rapport vide dirait
        # « propre » d'un fichier qu'on n'a pas lu.
        lisible = False
    trouves = _regroupe(commentaires) if lisible else blocs_shell(source)

    try:
        arbre = ast.parse(source)
    except SyntaxError:
        return sorted(trouves, key=lambda b: b["line"])

    portees = [arbre] + [
        noeud
        for noeud in ast.walk(arbre)
        if isinstance(
            noeud, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
        )
    ]
    for noeud in portees:
        corps = getattr(noeud, "body", None)
        if not corps or not isinstance(corps[0], ast.Expr):
            continue
        valeur = corps[0].value
        if not (
            isinstance(valeur, ast.Constant) and isinstance(valeur.value, str)
        ):
            continue
        debut = corps[0].lineno
        fin = getattr(corps[0], "end_lineno", debut) or debut
        sous_lignes = [
            (numero, lignes_source[numero - 1].strip())
            for numero in range(debut, min(fin, len(lignes_source)) + 1)
        ]
        if sous_lignes:
            trouves.append(_bloc(sous_lignes))

    return sorted(trouves, key=lambda b: b["line"])


def commentaire_shell(ligne):
    """Ce que dit le commentaire de cette ligne shell, ou None.

    Le « # » qui ouvre un commentaire est celui qui n'est ni protégé par des
    guillemets, ni échappé, ni collé à un mot — `${VAR#préfixe}` et une URL
    `…/#ancre` n'ouvrent rien. Le shebang n'est pas un commentaire.
    """
    if ligne.lstrip().startswith("#!"):
        return None
    quote = None
    precedent = ""
    for index, caractere in enumerate(ligne):
        if precedent == "\\":
            precedent = ""
            continue
        if quote:
            if caractere == quote:
                quote = None
        elif caractere in "\"'":
            quote = caractere
        elif caractere == "#" and (index == 0 or ligne[index - 1].isspace()):
            return ligne[index:].lstrip("#").strip()
        precedent = caractere
    return None


def blocs_shell(source):
    """Les commentaires d'un script shell, les consécutifs regroupés."""
    commentaires = []
    for numero, ligne in enumerate(source.split("\n"), start=1):
        texte = commentaire_shell(ligne)
        if texte is not None:
            commentaires.append((numero, texte))
    return _regroupe(commentaires)


def blocs_texte(source):
    """Toutes les lignes non vides, les consécutives regroupées.

    Un fichier de prose ou de gabarit n'a pas de syntaxe de commentaire à
    isoler : sa phrase EST son contenu. Ne lire que les lignes ouvertes par
    « # » n'y rendrait que les titres d'un Markdown, et rien du corps.
    """
    lignes = [
        (numero, ligne.strip())
        for numero, ligne in enumerate(source.split("\n"), start=1)
        if ligne.strip()
    ]
    return _regroupe(lignes)


def blocs(chemin, source):
    """Les phrases d'un fichier, selon son suffixe."""
    if chemin.endswith(".py"):
        return blocs_python(source)
    if chemin.endswith(SUFFIXES_TEXTE):
        return blocs_texte(source)
    return blocs_shell(source)


def recits(texte):
    """Les marqueurs de récit d'un texte : (motif, extrait, position).

    Toutes les occurrences, et non la première : un bloc de vingt lignes en
    porte souvent plusieurs, et n'en montrer qu'une cache le reste du travail.
    """
    trouves = []
    for nom, motif in MOTIFS_RECIT:
        for trouve in motif.finditer(texte):
            trouves.append((nom, trouve.group(0).strip(), trouve.start()))
    return sorted(trouves, key=lambda t: t[2])


def ligne_a(bloc, position):
    """La ligne physique qui porte cette position du texte recollé."""
    numero = bloc["line"]
    for debut, ligne in bloc["offsets"]:
        if debut > position:
            break
        numero = ligne
    return numero


def inspect(chemin, source=None, termes=None):
    """Les trouvailles d'un fichier, dans l'ordre des lignes."""
    if termes is None:
        termes = termes_interdits()
    if source is None:
        with io.open(chemin, encoding="utf-8", errors="replace") as fh:
            source = fh.read()

    # Les déclarations se lisent sur le fichier ENTIER : un test déclare en
    # tête la valeur qu'il porte plus bas, là où elle sert.
    exemples = exemples_declares(source)

    trouvailles = []
    for bloc in blocs(chemin, source):
        familles = (
            ("identifiant", identifiants(bloc["text"], termes, exemples)),
            ("récit", recits(bloc["text"])),
        )
        for genre, trouves in familles:
            for motif, extrait, position in trouves:
                trouvailles.append(
                    {
                        "file": chemin,
                        "line": ligne_a(bloc, position),
                        "kind": genre,
                        "pattern": motif,
                        "excerpt": extrait,
                    }
                )
    return sorted(trouvailles, key=lambda f: (f["line"], f["kind"]))


def fichiers_indexes():
    """Les fichiers ajoutés à l'index git, filtrés sur les suffixes lisibles."""
    sortie = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACMR"],
        capture_output=True,
        text=True,
        cwd=RACINE,
    )
    chemins = []
    for nom in sortie.stdout.split("\n"):
        nom = nom.strip()
        if (
            nom.endswith(SUFFIXES)
            and a_balayer(nom)
            and os.path.isfile(os.path.join(RACINE, nom))
        ):
            chemins.append(nom)
    return chemins


def etend(chemins):
    """Les fichiers lisibles d'une liste de chemins, répertoires parcourus."""
    trouves = []
    for chemin in chemins:
        if os.path.isdir(chemin):
            for base, _, noms in os.walk(chemin):
                if not a_balayer(base + "/"):
                    continue
                for nom in sorted(noms):
                    complet = os.path.join(base, nom)
                    if nom.endswith(SUFFIXES) and a_balayer(complet):
                        trouves.append(complet)
        elif chemin.endswith(SUFFIXES) and a_balayer(chemin):
            trouves.append(chemin)
    return trouves


def render(trouvailles, colour=True):
    """Le rapport, groupé par fichier."""
    if not trouvailles:
        return ""

    def peindre(texte, code):
        return f"\033[{code}m{texte}\033[0m" if colour else texte

    lignes = []
    fichier = None
    for f in trouvailles:
        if f["file"] != fichier:
            fichier = f["file"]
            lignes.append(peindre(fichier, "1"))
        icone = "🔴" if f["kind"] == "identifiant" else "🟡"
        lignes.append(
            f"  {icone} {f['line']:>5}  {f['pattern']:<11} {f['excerpt']}"
        )

    durs = sum(1 for f in trouvailles if f["kind"] == "identifiant")
    mous = len(trouvailles) - durs
    lignes.append("")
    lignes.append(
        t(
            "%s identifying, %s to re-read — see .claude/rules/04-code-conventions.md"
        )
        % (peindre(durs, "31"), peindre(mous, "33"))
    )
    return "\n".join(lignes)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description=t(
            "do the comments say how the code works, or where it came from"
        )
    )
    parser.add_argument("paths", nargs="*", default=[])
    parser.add_argument(
        "--staged",
        action="store_true",
        help=t("only the files added to the git index"),
    )
    parser.add_argument(
        "--identifying-only",
        action="store_true",
        help=t("drop the narrative signals, keep the certain findings"),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    if args.staged:
        chemins = fichiers_indexes()
    elif args.paths:
        chemins = etend(args.paths)
    else:
        parser.error(t("give a path, or --staged"))
        return 2

    termes = termes_interdits()
    trouvailles = []
    for chemin in chemins:
        try:
            trouvailles.extend(inspect(chemin, termes=termes))
        except OSError as exc:
            print(f"❌ {chemin} : {exc}", file=sys.stderr)
            return 2

    if args.identifying_only:
        trouvailles = [f for f in trouvailles if f["kind"] == "identifiant"]

    if args.json:
        print(
            json.dumps(
                {"scanned": len(chemins), "findings": trouvailles},
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        colour = sys.stdout.isatty() and not args.no_color
        rapport = render(trouvailles, colour)
        if rapport:
            print(rapport)

    return 1 if trouvailles else 0


if __name__ == "__main__":
    sys.exit(main())
