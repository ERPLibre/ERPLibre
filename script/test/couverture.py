#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Couverture de code d'un JEU de mesures : données, rapports, historique.

Deux jeux, chacun avec son interpréteur et sa configuration :

- « erplibre » : le code de l'outillage (script/, long_test/, docker/),
  mesuré par la suite unitaire, sous .venv.erplibre et
  conf/coverage.erplibre.toml ;
- « odoo » : les modules Odoo que testent les scénarios du générateur,
  sous le venv Odoo et conf/coverage.odoo.cfg.

Chaque processus mesuré écrit son propre fichier de données (« coverage
run -p ») dans `donnees(jeu)`, HORS du TMPDIR de l'élément, que le lanceur
supprime. En fin de passage : `combiner`, puis `produire_json` — rapide, la
source de la TUI et de l'historique —, puis `historiser`. Le HTML, plus
lent, se produit à la demande.

Tout vit sous $XDG_CACHE_HOME/erplibre/couverture/<jeu>/ :

    donnees/.coverage[.*]   les données, fusionnées par combiner
    coverage.json           le rapport JSON du dernier passage
    html/index.html         le rapport HTML, à la demande
    historique.jsonl        une ligne par passage (voir historiser)

L'import ne demande que la bibliothèque standard : coverage est appelé par
l'interpréteur du jeu, en sous-processus, ce qui sert aussi le jeu Odoo,
dont le Python n'est pas celui du lanceur.

    couverture.py combiner|json|html|texte|historique|effacer [--jeu NOM]
"""

import argparse
import datetime
import glob
import json
import os
import shutil
import subprocess
import sys

RACINE = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)
CACHE = os.path.join(
    os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache"),
    "erplibre",
    "couverture",
)


class Jeu:
    """Un jeu de mesures : son nom, sa configuration et l'interpréteur
    qui porte coverage."""

    def __init__(self, nom, rc, python, libelle):
        self.nom = nom
        self.rc = rc
        self.python = python
        self.libelle = libelle


def _python_odoo():
    """L'interpréteur du venv Odoo actif : .venv.<.erplibre-version>."""
    try:
        with open(os.path.join(RACINE, ".erplibre-version")) as fh:
            version = fh.read().strip()
    except OSError:
        version = ""
    candidat = os.path.join(RACINE, f".venv.{version}", "bin", "python")
    if version and os.path.exists(candidat):
        return candidat
    # Sans fichier de version : le seul venv Odoo présent, s'il est seul.
    trouves = glob.glob(os.path.join(RACINE, ".venv.odoo*", "bin", "python"))
    return trouves[0] if len(trouves) == 1 else candidat


def jeu(nom):
    """Le Jeu `nom` ; ValueError s'il n'existe pas."""
    if nom == "erplibre":
        return Jeu(
            "erplibre",
            os.path.join(RACINE, "conf", "coverage.erplibre.toml"),
            os.path.join(RACINE, ".venv.erplibre", "bin", "python"),
            "Code ERPLibre",
        )
    if nom == "odoo":
        return Jeu(
            "odoo",
            os.path.join(RACINE, "conf", "coverage.odoo.cfg"),
            _python_odoo(),
            "Modules Odoo",
        )
    raise ValueError(f"jeu de couverture inconnu : {nom}")


JEUX = ("erplibre", "odoo")


def dossier(nom):
    return os.path.join(CACHE, nom)


def donnees(nom):
    """Le répertoire des fichiers de données du jeu."""
    return os.path.join(dossier(nom), "donnees")


def fichier_donnees(nom):
    """Le fichier de données fusionné ; les processus écrivent à côté,
    suffixés par « -p »."""
    return os.path.join(donnees(nom), ".coverage")


def chemin_json(nom):
    return os.path.join(dossier(nom), "coverage.json")


def chemin_html(nom):
    return os.path.join(dossier(nom), "html", "index.html")


def chemin_historique(nom):
    return os.path.join(dossier(nom), "historique.jsonl")


# Version minimale de coverage par jeu : « patch = subprocess », dont le
# jeu erplibre a besoin, date de 7.10 ; le jeu odoo s'en passe, et le venv
# d'une ancienne version d'Odoo porte un coverage plus ancien.
VERSION_MINIMALE = {"erplibre": (7, 10), "odoo": (0,)}


def disponible(nom):
    """Vrai si l'interpréteur du jeu porte coverage, dans la version
    minimale du jeu."""
    python = jeu(nom).python
    if not os.path.exists(python):
        return False
    minimum = VERSION_MINIMALE.get(nom, (0,))
    res = subprocess.run(
        [
            python,
            "-c",
            "import coverage, sys;"
            f"sys.exit(0 if coverage.version_info >= {minimum!r} else 1)",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return res.returncode == 0


def effacer(nom):
    """Retire les données du passage précédent ; le JSON, le HTML et
    l'historique restent."""
    shutil.rmtree(donnees(nom), ignore_errors=True)
    os.makedirs(donnees(nom), exist_ok=True)


def env(nom):
    """Variables qui envoient les données de tout processus mesuré — les
    sous-processus compris — vers le répertoire du jeu."""
    return {
        "COVERAGE_FILE": fichier_donnees(nom),
        "COVERAGE_RCFILE": jeu(nom).rc,
    }


def envelopper(nom, cmd):
    """`cmd` — `[python, options…, cible, arguments…]` — lancé sous
    « coverage run -p » avec la configuration du jeu. Les options de
    l'interpréteur (« -u ») restent avant « -m coverage »."""
    python, reste = cmd[0], list(cmd[1:])
    options = []
    while reste and reste[0].startswith("-") and reste[0] != "-m":
        options.append(reste.pop(0))
    return [
        python,
        *options,
        "-m",
        "coverage",
        "run",
        "-p",
        f"--rcfile={jeu(nom).rc}",
        *reste,
    ]


def _coverage(nom, *arguments):
    """Lance « coverage <arguments> » par l'interpréteur du jeu, depuis la
    racine : les chemins relatifs des données s'y résolvent.
    RuntimeError si cet interpréteur n'existe pas : un venv absent se dit
    en une ligne, pas par le FileNotFoundError de subprocess."""
    j = jeu(nom)
    if not os.path.exists(j.python):
        raise RuntimeError(
            f"pas d'interpréteur pour le jeu {nom} : {j.python}"
        )
    return subprocess.run(
        [j.python, "-m", "coverage", *arguments, f"--rcfile={j.rc}"],
        cwd=RACINE,
        env=dict(os.environ, **env(nom)),
        capture_output=True,
        text=True,
    )


def combiner(nom):
    """Fusionne les fichiers de données des processus. Rend le nombre de
    fichiers fusionnés ; 0 si aucun processus n'a rien écrit."""
    morceaux = glob.glob(fichier_donnees(nom) + ".*")
    if not morceaux:
        return 0
    res = _coverage(nom, "combine", "--keep")
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    for chemin in morceaux:
        try:
            os.remove(chemin)
        except OSError:
            pass
    return len(morceaux)


def produire_json(nom):
    """coverage.json du dernier passage ; rend son chemin."""
    os.makedirs(dossier(nom), exist_ok=True)
    sortie = chemin_json(nom)
    res = _coverage(nom, "json", "-o", sortie, "--pretty-print")
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return sortie


def produire_html(nom):
    """Le rapport HTML ; rend le chemin de son index."""
    res = _coverage(
        nom, "html", "-d", os.path.dirname(chemin_html(nom)), "--quiet"
    )
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return chemin_html(nom)


def rapport_texte(nom):
    """Le rapport texte de coverage, trié par couverture."""
    res = _coverage(nom, "report", "--sort=cover")
    if res.returncode != 0:
        raise RuntimeError(res.stderr.strip() or res.stdout.strip())
    return res.stdout


def lire_json(nom):
    """Le dict de coverage.json, ou None s'il n'y en a pas encore."""
    try:
        with open(chemin_json(nom), encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _pourcentage(couvertes, total):
    return round(100.0 * couvertes / total, 2) if total else 100.0


def dossier_de(chemin, profondeur=2):
    """Le dossier de regroupement d'un fichier : ses `profondeur` premiers
    composants (« script/todo » pour script/todo/todo.py)."""
    parties = chemin.replace(os.sep, "/").split("/")
    return "/".join(parties[: min(profondeur, len(parties) - 1)]) or "."


def resume(rapport, profondeur=2):
    """{total, dossiers} tirés d'un coverage.json : instructions et
    branches, couvertes et totales, par dossier de `profondeur`
    composants."""
    dossiers = {}
    for chemin, f in rapport.get("files", {}).items():
        s = f.get("summary", {})
        d = dossiers.setdefault(
            dossier_de(chemin, profondeur),
            {
                "lignes": 0,
                "couvertes": 0,
                "branches": 0,
                "branches_couvertes": 0,
            },
        )
        d["lignes"] += s.get("num_statements", 0)
        d["couvertes"] += s.get("covered_lines", 0)
        d["branches"] += s.get("num_branches", 0)
        d["branches_couvertes"] += s.get("covered_branches", 0)
    for d in dossiers.values():
        d["pourcentage"] = _pourcentage(
            d["couvertes"] + d["branches_couvertes"],
            d["lignes"] + d["branches"],
        )
    t = rapport.get("totals", {})
    total = {
        "pourcentage": round(t.get("percent_covered", 0.0), 2),
        "lignes": t.get("num_statements", 0),
        "couvertes": t.get("covered_lines", 0),
        "branches": t.get("num_branches", 0),
        "branches_couvertes": t.get("covered_branches", 0),
        "fichiers": len(rapport.get("files", {})),
    }
    return {"total": total, "dossiers": dict(sorted(dossiers.items()))}


def _git(*arguments):
    res = subprocess.run(
        ["git", *arguments],
        cwd=RACINE,
        capture_output=True,
        text=True,
    )
    return res.stdout.strip() if res.returncode == 0 else ""


def historiser(nom, complet, incomplets=(), duree=0.0, maintenant=None):
    """Ajoute le passage à l'historique et rend la ligne écrite.

    `complet` : faux pour un passage partiel (--changed, --failed,
    fichiers nommés), qui ne se compare pas à un passage complet.
    `incomplets` : les éléments tués (délai, Ctrl+C), dont une partie des
    données a pu se perdre. La ligne :

        {date, commit, branche, jeu, complet, incomplets, duree_s,
         total: {pourcentage, lignes, couvertes, branches,
                 branches_couvertes, fichiers},
         dossiers: {dossier: {pourcentage, lignes, couvertes, branches,
                              branches_couvertes}}}
    """
    rapport = lire_json(nom)
    if rapport is None:
        raise RuntimeError(f"pas de coverage.json pour le jeu {nom}")
    ligne = {
        "date": (maintenant or datetime.datetime.now(datetime.UTC))
        .replace(microsecond=0)
        .isoformat(),
        "commit": _git("rev-parse", "--short=12", "HEAD"),
        "branche": _git("rev-parse", "--abbrev-ref", "HEAD"),
        "jeu": nom,
        "complet": bool(complet),
        "incomplets": sorted(incomplets),
        "duree_s": round(duree, 1),
        **resume(rapport),
    }
    os.makedirs(dossier(nom), exist_ok=True)
    with open(chemin_historique(nom), "a", encoding="utf-8") as fh:
        fh.write(json.dumps(ligne, ensure_ascii=False) + "\n")
    return ligne


def lire_historique(nom):
    """Les lignes de l'historique, de la plus ancienne à la plus récente.
    Une ligne illisible est sautée."""
    lignes = []
    try:
        with open(chemin_historique(nom), encoding="utf-8") as fh:
            for texte in fh:
                try:
                    lignes.append(json.loads(texte))
                except ValueError:
                    continue
    except OSError:
        pass
    return lignes


def precedent_comparable(historique):
    """Le dernier passage COMPLET avant le dernier passage, ou None : un
    passage partiel ne mesure qu'une partie du code."""
    if len(historique) < 2:
        return None
    for ligne in reversed(historique[:-1]):
        if ligne.get("complet"):
            return ligne
    return None


def ecart(nom):
    """(dernier, écart en points avec le précédent comparable), ou
    (dernier, None) sans précédent comparable, ou (None, None)."""
    historique = lire_historique(nom)
    if not historique:
        return None, None
    dernier = historique[-1]
    avant = precedent_comparable(historique)
    if avant is None or not dernier.get("complet"):
        return dernier, None
    return dernier, round(
        dernier["total"]["pourcentage"] - avant["total"]["pourcentage"], 2
    )


def ligne_de_bilan(nom):
    """« Couverture : 67.12 % (+0.40) » pour le bilan d'un passage."""
    dernier, delta = ecart(nom)
    if dernier is None:
        return "Couverture : aucune donnée"
    texte = f"Couverture : {dernier['total']['pourcentage']:.2f} %"
    if delta is not None:
        texte += f" ({delta:+.2f})"
    if not dernier.get("complet"):
        texte += " — passage partiel"
    if dernier.get("incomplets"):
        texte += f", {len(dernier['incomplets'])} élément(s) tué(s)"
    return texte


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "action",
        choices=("combiner", "json", "html", "texte", "historique", "effacer"),
    )
    parser.add_argument("--jeu", default="erplibre", choices=JEUX)
    args = parser.parse_args(argv)
    try:
        return _executer(args)
    except RuntimeError as e:
        # Le message de coverage (« No data to report. ») suffit ; une
        # trace Python le noierait.
        print(f"couverture.py {args.action} : {e}", file=sys.stderr)
        return 1


def _executer(args):
    if args.action == "effacer":
        effacer(args.jeu)
    elif args.action == "combiner":
        print(f"{combiner(args.jeu)} fichier(s) fusionné(s)")
    elif args.action == "json":
        print(produire_json(args.jeu))
    elif args.action == "html":
        print(produire_html(args.jeu))
    elif args.action == "texte":
        print(rapport_texte(args.jeu))
    elif args.action == "historique":
        for ligne in lire_historique(args.jeu):
            print(
                f"{ligne['date']}  {ligne.get('commit', ''):12}"
                f"  {ligne['total']['pourcentage']:6.2f} %"
                f"  {'complet' if ligne.get('complet') else 'partiel'}"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
