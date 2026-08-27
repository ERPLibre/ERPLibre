#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Un dépôt absent d'un palier fait disparaître ses modules en chemin.

Une migration 12 → 18 traverse SIX paliers, et à chacun le checkout
bascule sur le manifeste de cette version. Un dépôt d'addons qui manque
au manifeste du 17 n'existe pas sur disque pendant l'étape 17 : Odoo
déclare ses modules introuvables, et le pilote propose alors de les
effacer de la base. La question « veux-tu supprimer le module manquant »
arrive au milieu de six paliers, on répond oui, et la fonctionnalité du
client part sans que rien n'ait échoué.

Ce qui distingue un trou d'une absence légitime
-----------------------------------------------
Beaucoup de dépôts n'ont tout simplement pas de branche pour une
version : les déclarer serait une erreur. Le seul signal qui vaille est
donc le TROU — présent avant, présent après, absent au milieu — CONFIRMÉ
par l'existence de la branche en amont.

Mesuré sur ce dépôt : 35 trous, dont 19 sont de vraies omissions. Les
seize autres n'ont pas la branche en amont et sont donc corrects. Un
outil qui aurait signalé les 35 aurait eu 46 % de bruit, et un rapport
qui fait peur pour rien finit ignoré en entier.

Quinze des dix-neuf partagent le même motif : déclarés en 16 et en 18,
absents du 17, la branche 17.0 existant en amont. Un lot ajouté pour la
18 sans rétro-portage — exactement le genre d'oubli qu'aucune relecture
ne voit et qu'un compte de trous rend évident.

Pourquoi le réseau est OPTIONNEL
--------------------------------
Confirmer demande un `git ls-remote` par dépôt. Sans `--upstream`,
l'outil liste les trous et dit qu'il ne les a pas départagés — c'est
honnête et instantané. Avec, il tranche.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

try:
    from script.todo.todo_i18n import t
except Exception:  # pragma: no cover - repli si i18n indisponible

    def t(key: str) -> str:
        return key


REPO_ROOT = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
DOSSIER = os.path.join(REPO_ROOT, "manifest")
MOTIF_FICHIER = re.compile(r"git_manifest_odoo(\d+\.\d+)\.xml$")
MOTIF_BRANCHE = re.compile(r"refs/heads/(\d+\.\d+)$")
DELAI_RESEAU = 60
PARALLELE = 8

COULEURS = {
    "broken": "\033[31m",
    "watch": "\033[33m",
    "ok": "\033[32m",
    "step": "\033[36m",
    "dim": "\033[90m",
}
RESET = "\033[0m"


def paint(texte, genre, colour):
    """Teinter, ou rendre le texte tel quel quand la couleur est coupée."""
    if not colour:
        return texte
    return f"{COULEURS.get(genre, '')}{texte}{RESET}"


def rang(version):
    """« 9.0 » avant « 10.0 » : trier des versions comme du texte ment."""
    return tuple(int(x) for x in version.split("."))


def versions(dossier=DOSSIER):
    """Les versions qui ont un manifeste, lues sur le disque.

    Les DÉDUIRE plutôt que les écrire : une version ajoutée au dépôt doit
    entrer dans l'analyse sans qu'on pense à toucher ici. Les manifestes
    `_dev` sont écartés — ils complètent le principal, et un dépôt qui
    n'est que dans le `_dev` n'est pas censé être partout.
    """
    trouves = {}
    for chemin in glob.glob(os.path.join(dossier, "git_manifest_odoo*.xml")):
        found = MOTIF_FICHIER.search(os.path.basename(chemin))
        if found:
            trouves[found.group(1)] = chemin
    return [(v, trouves[v]) for v in sorted(trouves, key=rang)]


def declarations(dossier=DOSSIER):
    """{dépôt: {version: url}} — qui est déclaré où, et d'où il vient.

    L'URL se recompose du `fetch` de son remote et du nom du projet ;
    c'est elle qui permettra d'aller demander à l'amont s'il a la branche.
    """
    par_depot = {}
    for version, chemin in versions(dossier):
        try:
            racine = ET.parse(chemin).getroot()
        except ET.ParseError:
            continue
        fetch = {
            r.get("name"): r.get("fetch") or "" for r in racine.iter("remote")
        }
        for projet in racine.iter("project"):
            nom = projet.get("name")
            if not nom:
                continue
            base = fetch.get(projet.get("remote"), "")
            url = base.rstrip("/") + "/" + nom if base else ""
            par_depot.setdefault(nom, {})[version] = url
    return par_depot


def gaps(par_depot, toutes_versions=None):
    """[(dépôt, présentes, manquantes, url)] — les trous, et eux seuls.

    Un trou est un manque ENTRE deux présences. Ce qui manque avant la
    première ou après la dernière n'en est pas un : un dépôt né en 16 n'a
    rien à faire en 12, et l'exiger crierait sur presque tout le fichier.
    """
    ordre = toutes_versions or [v for v, _ in versions()]
    lst = []
    for nom, par_version in sorted(par_depot.items()):
        presentes = sorted(par_version, key=rang)
        debut, fin = ordre.index(presentes[0]), ordre.index(presentes[-1])
        manquantes = [
            v for v in ordre[debut : fin + 1] if v not in par_version
        ]
        if manquantes:
            url = par_version[presentes[-1]] or par_version[presentes[0]]
            lst.append((nom, presentes, manquantes, url))
    return lst


def branches(url, delai=DELAI_RESEAU):
    """Les branches de version publiées en amont, ou None si injoignable.

    None et l'ensemble vide ne disent PAS la même chose : « je n'ai pas
    pu demander » n'est pas « il n'y en a pas », et confondre les deux
    transformerait une coupure réseau en absolution générale.
    """
    if not url:
        return None
    try:
        done = subprocess.run(
            ["git", "ls-remote", "--heads", url],
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if done.returncode:
        return None
    trouvees = set()
    for ligne in done.stdout.splitlines():
        found = MOTIF_BRANCHE.search(ligne.strip())
        if found:
            trouvees.add(found.group(1))
    return trouvees


def judge(lst_gaps, verifier=False, lecteur=branches, parallele=PARALLELE):
    """[(dépôt, manquantes, omissions, etat)] — trancher, ou avouer.

    `etat` vaut "omission" quand l'amont a la branche, "legitime" quand
    il ne l'a pas, "inconnu" quand on n'a pas demandé ou pas pu.
    """
    if not verifier:
        return [(n, m, [], "inconnu") for n, _p, m, _u in lst_gaps]

    with ThreadPoolExecutor(max_workers=parallele) as pool:
        amonts = list(pool.map(lambda g: lecteur(g[3]), lst_gaps))

    resultat = []
    for (nom, _presentes, manquantes, _url), amont in zip(lst_gaps, amonts):
        if amont is None:
            resultat.append((nom, manquantes, [], "inconnu"))
            continue
        omissions = [v for v in manquantes if v in amont]
        resultat.append(
            (
                nom,
                manquantes,
                omissions,
                "omission" if omissions else "legitime",
            )
        )
    return resultat


def render(juges, verifie, colour=True):
    """Le rapport lisible. Les omissions d'abord, le reste en sourdine."""
    lignes = [f"🗺 {t('Repositories missing from a step')}", ""]
    omissions = [j for j in juges if j[3] == "omission"]
    inconnus = [j for j in juges if j[3] == "inconnu"]
    legitimes = [j for j in juges if j[3] == "legitime"]

    if not juges:
        lignes.append(
            paint(
                f"✅ {t('Every repository is declared without a hole.')}",
                "ok",
                colour,
            )
        )
        return "\n".join(lignes)

    for nom, _manq, omis, _etat in omissions:
        lignes.append(paint(f"❌ {nom}", "broken", colour))
        lignes.append(
            paint(
                f"      {t('missing from')} {', '.join(omis)}"
                f" — {t('upstream has the branch')}",
                "dim",
                colour,
            )
        )

    if omissions:
        lignes.append("")
        lignes.append(
            paint(
                f"   {t('Add the <project> entry to')}"
                f" manifest/git_manifest_odoo<version>.xml",
                "dim",
                colour,
            )
        )

    if inconnus:
        lignes.append("")
        mot = (
            t("not asked: run with --upstream")
            if not verifie
            else t("upstream unreachable")
        )
        lignes.append(
            paint(
                f"❔ {len(inconnus)} {t('holes not settled')} — {mot}",
                "watch",
                colour,
            )
        )
        for nom, manq, _o, _e in inconnus:
            lignes.append(
                paint(f"      {nom} — {', '.join(manq)}", "dim", colour)
            )

    if legitimes:
        lignes.append("")
        lignes.append(
            paint(
                f"✅ {len(legitimes)} {t('holes are legitimate: no such branch upstream')}",
                "ok",
                colour,
            )
        )
    return "\n".join(lignes)


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=t("Repositories declared for some steps but not others."),
    )
    parser.add_argument(
        "--upstream",
        action="store_true",
        help=t("ask each remote whether the branch exists (network)"),
    )
    parser.add_argument("--manifest-dir", default=DOSSIER)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    if not os.path.isdir(args.manifest_dir):
        print(f"❌ {args.manifest_dir}", file=sys.stderr)
        return 2

    lst = gaps(
        declarations(args.manifest_dir),
        [v for v, _ in versions(args.manifest_dir)],
    )
    juges = judge(lst, verifier=args.upstream)

    if args.json:
        print(
            json.dumps(
                {
                    "checked_upstream": args.upstream,
                    "gaps": [
                        {
                            "repository": n,
                            "missing": m,
                            "omissions": o,
                            "state": e,
                        }
                        for n, m, o, e in juges
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        colour = sys.stdout.isatty() and not args.no_color
        print(render(juges, args.upstream, colour))
    return 1 if any(j[3] == "omission" for j in juges) else 0


if __name__ == "__main__":
    sys.exit(main())
