#!/usr/bin/env python3
# © 2021-2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""D'où descend un fork, et l'amont porte-t-il encore quelque chose.

Un dépôt forké n'enregistre nulle part le dépôt dont il descend. git-repo
ne connaît que le remote qui sert à CLONER, et pour un fork ce remote est
celui du fork. L'amont n'existe donc que dans la tête de qui a forké, et
une mise à niveau ne peut pas commencer sans lui.

Ce que le nom du remote ne suffit pas à dire
--------------------------------------------
La convention « <propriétaire>_origin_<amont> » nomme l'amont dans le
suffixe, et suffit tant que trois choses se vérifient : que le remote
amont soit déclaré, que le dépôt porte le même nom des deux côtés, et
que l'amont ait une branche pour cette version d'Odoo. Aucune des trois
n'est acquise. Un fork peut être RENOMMÉ en y collant le nom de son
organisation d'origine, auquel cas l'URL déduite ne pointe sur rien. Un
amont peut être FIGÉ sur une version ancienne pendant que le fork en
traverse cinq de plus, auquel cas il n'y a rien sur quoi rebaser.

Les trois attributs lus ici portent donc ce que la convention devine :

- « fork-upstream-remote » nomme le <remote> amont ; son « fetch » donne
  l'URL, ce qui fait qu'un changement d'hébergeur ne touche qu'une ligne.
- « fork-upstream-name » ne paraît que sur un fork renommé.
- « fork-upstream » nomme la branche amont. Son ABSENCE, alors que le
  remote est déclaré, dit que l'amont ne porte rien pour cette version —
  ce qui n'est pas la même chose qu'un amont inconnu, et le rapport
  refuse de confondre les deux.

La convention reste lue en repli, et ce qu'elle produit est marqué comme
tel : un amont deviné et un amont déclaré ne se valent pas.

Pourquoi le réseau est OPTIONNEL
--------------------------------
Sans « --upstream », la lecture est instantanée et ne dit que ce que les
manifestes déclarent. Avec, chaque amont est interrogé et l'outil
tranche. Un amont injoignable et un amont sans la branche attendue sont
deux constats distincts, jamais fondus en un seul.
"""

from __future__ import annotations

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


def version_active(racine=REPO_ROOT):
    """La version d'Odoo du checkout, telle que « .odoo-version » la dit."""
    chemin = os.path.join(racine, ".odoo-version")
    try:
        with open(chemin) as fh:
            return fh.read().strip()
    except OSError:
        return ""


def fichiers_manifeste(version, dossier=DOSSIER):
    """Les manifestes d'une version, dans l'ordre où ils se fusionnent.

    Les trois se lisent ENSEMBLE et jamais séparément : un remote amont
    peut n'être déclaré que dans le fichier « extra » ou « dev » alors
    que le fork qui s'y réfère vit dans le principal. Une résolution
    fichier par fichier rate cet amont et le déclare inconnu à tort.
    """
    gabarits = (
        f"git_manifest_odoo{version}.xml",
        f"git_manifest_extra_odoo{version}.xml",
        f"git_manifest_odoo{version}_dev.xml",
    )
    return [
        os.path.join(dossier, g)
        for g in gabarits
        if os.path.isfile(os.path.join(dossier, g))
    ]


def cle(projet):
    """« nom+chemin » : le même dépôt sert plusieurs versions d'Odoo.

    Le nom seul les confond, et deux versions du même dépôt se
    recouvriraient en silence.
    """
    return f"{projet.get('name')}+{projet.get('path')}"


def lire_manifestes(version, dossier=DOSSIER):
    """(remotes, projets) des manifestes FUSIONNÉS d'une version.

    Lu par un parseur XML et non par un motif : des entrées <project>
    sont mises en commentaire dans les manifestes, et un grep les
    compterait comme vivantes.
    """
    remotes, projets = {}, {}
    for chemin in fichiers_manifeste(version, dossier):
        racine = ET.parse(chemin).getroot()
        for e in racine.findall("remote"):
            remotes.setdefault(e.get("name"), e.get("fetch"))
        for p in racine.findall("project"):
            projets[cle(p)] = dict(p.attrib, _fichier=os.path.basename(chemin))
    return remotes, projets


def url_amont(fetch, nom):
    """L'URL d'un dépôt chez son hébergeur, barre oblique comprise.

    Le « fetch » d'un remote se termine par une barre, sauf quand il ne
    s'y termine pas : la recoller sans la dédoubler évite une URL à
    double barre qui ne résout nulle part.
    """
    if not fetch or not nom:
        return ""
    return f"{fetch.rstrip('/')}/{nom}"


def est_fork(projet):
    """Un projet cloné depuis un fork, reconnu à son remote."""
    return "_origin_" in (projet.get("remote") or "")


def resoudre_amont(projet, remotes):
    """L'amont d'un fork : les attributs d'abord, la convention en repli.

    Rend None quand le projet n'est pas un fork. Rend un dictionnaire dont
    « branche » vaut None lorsque l'amont ne porte rien pour cette version,
    et dont « source » dit si la réponse a été DÉCLARÉE ou DEVINÉE — un
    amont deviné ne vaut pas un amont déclaré, et le rapport le montre.
    """
    if not est_fork(projet):
        return None

    remote = projet.get("fork-upstream-remote")
    source = "declare"
    if not remote:
        # Le suffixe du remote de clonage, faute de mieux. Le PRÉFIXE nomme
        # le propriétaire du fork et non l'hébergeur : seul le suffixe parle
        # de l'amont.
        remote = (projet.get("remote") or "").split("_origin_")[-1]
        source = "convention"

    nom = projet.get("fork-upstream-name") or projet.get("name")
    fetch = remotes.get(remote)
    return {
        "remote": remote,
        "nom": nom,
        "url": url_amont(fetch, nom),
        "branche": projet.get("fork-upstream"),
        "source": source,
        "remote_declare": fetch is not None,
    }


MOTIF_BRANCHE = re.compile(r"refs/heads/(\S+)$")


def branches(url, delai=DELAI_RESEAU):
    """Les branches publiées en amont, ou None si injoignable.

    None dit que la question n'a pas pu être posée ; l'ensemble vide dit
    qu'elle a reçu une réponse, et que cette réponse est vide. Les
    confondre fait passer une coupure réseau, ou un dépôt devenu privé,
    pour un amont légitimement dépourvu de la branche attendue.
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


def etat_forks(
    version,
    dossier=DOSSIER,
    verifier=False,
    lecteur=branches,
    parallele=PARALLELE,
):
    """[dict] — un constat par fork, trié par chemin.

    « etat » vaut :
      declare        l'amont et sa branche sont inscrits
      sans_branche   l'amont est inscrit, il ne porte rien pour la version
      devine         rien n'est inscrit, la convention a répondu
      non_declare    rien n'est inscrit et la convention ne répond pas
      confirme       la branche existe bel et bien en amont  (--upstream)
      branche_absente  la branche inscrite n'existe pas      (--upstream)
      injoignable    l'amont n'a pas répondu                 (--upstream)
    """
    remotes, projets = lire_manifestes(version, dossier)
    lst = []
    for projet in projets.values():
        amont = resoudre_amont(projet, remotes)
        if amont is None:
            continue
        if not amont["remote_declare"]:
            etat = "non_declare"
        elif amont["source"] == "convention":
            etat = "devine"
        elif amont["branche"]:
            etat = "declare"
        else:
            etat = "sans_branche"
        lst.append(
            {
                "chemin": projet.get("path"),
                "nom": projet.get("name"),
                "revision": projet.get("revision"),
                "amont": amont,
                "etat": etat,
                "branches_amont": None,
            }
        )
    lst.sort(key=lambda x: x["chemin"] or "")

    if not verifier:
        return lst

    with ThreadPoolExecutor(max_workers=parallele) as pool:
        vues = list(pool.map(lambda x: lecteur(x["amont"]["url"]), lst))
    for constat, vu in zip(lst, vues):
        constat["branches_amont"] = None if vu is None else sorted(vu)
        if vu is None:
            constat["etat"] = "injoignable"
        elif constat["amont"]["branche"]:
            constat["etat"] = (
                "confirme"
                if constat["amont"]["branche"] in vu
                else "branche_absente"
            )
    return lst


# Un constat qui demande une correction du manifeste. Les autres sont des
# faits, pas des reproches : un amont figé n'est pas une erreur, c'est un
# projet qui a cessé de suivre.
ETATS_A_CORRIGER = ("non_declare", "devine", "branche_absente")

_TITRES = {
    "non_declare": t("No upstream declared for this fork"),
    "devine": t("Upstream guessed from the remote name"),
    "branche_absente": t("The declared upstream branch does not exist"),
    "injoignable": t("Upstream did not answer"),
    "sans_branche": t("Upstream carries no branch for this version"),
    "declare": t("Upstream declared"),
    "confirme": t("Upstream confirmed"),
}


def render(lst, verifie, colour=True):
    """Le rapport lisible. Ce qui est à corriger d'abord, le sain ensuite."""
    out = []
    ordre = (
        "non_declare",
        "devine",
        "branche_absente",
        "injoignable",
        "sans_branche",
        "confirme",
        "declare",
    )
    for etat in ordre:
        groupe = [x for x in lst if x["etat"] == etat]
        if not groupe:
            continue
        genre = (
            "broken"
            if etat in ETATS_A_CORRIGER
            else "watch" if etat in ("injoignable", "sans_branche") else "ok"
        )
        titre = f"{_TITRES.get(etat, etat)} ({len(groupe)})"
        out.append(paint(titre, genre, colour))
        for x in groupe:
            amont = x["amont"]
            cible = amont["url"] or f"?{amont['remote']}"
            if amont["branche"]:
                cible = f"{cible} @ {amont['branche']}"
            out.append(f"    {x['chemin']}")
            out.append(paint(f"        → {cible}", "dim", colour))
        out.append("")
    if not verifie:
        out.append(
            paint(
                t("Upstreams were not queried; use --upstream."), "dim", colour
            )
        )
    return "\n".join(out)


def main(argv=None):
    import argparse
    import json

    parser = argparse.ArgumentParser(
        description=t("Where each forked repository comes from."),
    )
    parser.add_argument("--version", default="")
    parser.add_argument("--manifest-dir", default=DOSSIER)
    parser.add_argument(
        "--upstream",
        action="store_true",
        help=t("ask each remote whether the branch exists (network)"),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    version = args.version or version_active()
    if not version:
        print(f"❌ {t('No Odoo version found')}", file=sys.stderr)
        return 2
    if not fichiers_manifeste(version, args.manifest_dir):
        print(f"❌ {args.manifest_dir} : {version}", file=sys.stderr)
        return 2

    lst = etat_forks(version, args.manifest_dir, verifier=args.upstream)

    if args.json:
        print(
            json.dumps(
                {
                    "version": version,
                    "checked_upstream": args.upstream,
                    "forks": lst,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        colour = sys.stdout.isatty() and not args.no_color
        print(render(lst, args.upstream, colour))
    return 1 if any(x["etat"] in ETATS_A_CORRIGER for x in lst) else 0


if __name__ == "__main__":
    sys.exit(main())
