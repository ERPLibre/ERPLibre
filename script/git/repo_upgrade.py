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

from script.git import repo_stats

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


# ── Le diagnostic d'une mise à niveau ──────────────────────────────────
#
# Tout ce qui suit LIT. « git fetch » range des objets dans le magasin, ce
# qui est une écriture sur le disque, mais il ne déplace aucune référence,
# n'ajoute aucun remote, ne crée aucune branche et ne touche pas l'arbre de
# travail : rien de ce que git ou git-repo tient pour l'état du dépôt ne
# change. C'est ce qui permet de constater avant de décider.

DELAI_GIT = 300


def git(args, cwd, delai=DELAI_GIT):
    """(sortie, erreur, code) — git ne lève jamais depuis ici.

    Un code de retour non nul est un RÉSULTAT et non un accident : un dépôt
    sans amont joignable doit produire un constat, pas interrompre la passe
    des quinze autres.
    """
    try:
        done = subprocess.run(
            ["git"] + list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc), 1
    return done.stdout, done.stderr, done.returncode


def est_superficiel(chemin):
    """Un clone tronqué n'a pas de base de fusion avec son amont."""
    out, _err, code = git(["rev-parse", "--is-shallow-repository"], chemin)
    return code == 0 and out.strip() == "true"


def recuperer_amont(chemin, url, branche, delai=DELAI_GIT):
    """Amène la branche amont dans FETCH_HEAD. True si elle y est.

    FETCH_HEAD et non un remote ajouté : un second remote survivrait mal à
    « repo sync --force-sync », qui réécrit le répertoire git, et le poser
    ferait sortir la passe du domaine de la lecture.
    """
    _out, _err, code = git(["fetch", "--quiet", url, branche], chemin, delai)
    return code == 0


def divergence(chemin):
    """(nos commits, commits amont) depuis la base de fusion, ou None."""
    out, _err, code = git(
        ["rev-list", "--left-right", "--count", "HEAD...FETCH_HEAD"], chemin
    )
    if code:
        return None
    champs = out.split()
    if len(champs) != 2:
        return None
    return int(champs[0]), int(champs[1])


def base_fusion(chemin):
    """Le commit d'où les deux branches partent, ou None si elles n'en ont
    aucun — un fork reconstruit de zéro n'est pas rebasable."""
    out, _err, code = git(["merge-base", "HEAD", "FETCH_HEAD"], chemin)
    return out.strip() if code == 0 else None


def predire_conflits(chemin):
    """Les chemins qui entrent en conflit, sans toucher à rien.

    « git merge-tree » calcule la fusion en mémoire : ni index, ni arbre de
    travail, ni branche. Le constat coûte quelques millisecondes et se
    rejoue autant de fois qu'on veut.
    """
    out, _err, code = git(
        [
            "merge-tree",
            "--write-tree",
            "--name-only",
            "--messages",
            "HEAD",
            "FETCH_HEAD",
        ],
        chemin,
    )
    if code == 0:
        return []
    lignes = out.splitlines()[1:]
    return [x.strip() for x in lignes if x.strip() and "/" in x]


def nos_commits(chemin):
    """[(court, sujet)] des commits que l'amont n'a pas."""
    out, _err, code = git(
        ["log", "--format=%h\t%s", "FETCH_HEAD..HEAD"], chemin
    )
    if code:
        return []
    lst = []
    for ligne in out.splitlines():
        if "\t" in ligne:
            court, sujet = ligne.split("\t", 1)
            lst.append((court.strip(), sujet.strip()))
    return lst


def ecart_amont(chemin):
    """Le « --numstat » de ce que l'AMONT apporte.

    C'est la question qu'un relecteur se pose vraiment : non pas ce que le
    fork porte, mais ce qui ARRIVE. Les deux se calculent depuis la même
    base de fusion et ne se confondent pas — l'un pèse quelques commits,
    l'autre plusieurs centaines.
    """
    out, _err, code = git(["diff", "--numstat", "HEAD...FETCH_HEAD"], chemin)
    return repo_stats.lire_numstat(out) if code == 0 else []


def notre_ecart(chemin):
    """Le « --numstat » de NOS seuls changements.

    Trois points et non deux : la comparaison part de la base de fusion, et
    ce qui revient est ce que le fork ajoute, sans les centaines de commits
    que l'amont a pris de son côté.
    """
    out, _err, code = git(["diff", "--numstat", "FETCH_HEAD...HEAD"], chemin)
    return repo_stats.lire_numstat(out) if code == 0 else []


def modules_presents(chemin, ref, modules, prefixes):
    """Ceux de ces modules qui EXISTENT à cette référence.

    Un module se reconnaît à son « __manifest__.py » et non à son
    répertoire : le répertoire d'empaquetage que certains dépôts posent à
    leur racine rejoue l'arborescence des modules sans en être un, et le
    compter gonflerait la liste des modules touchés.

    Un seul « ls-tree » pour tous les candidats : un appel par module
    coûterait une vingtaine de processus là où un seul répond.
    """
    if not modules:
        return set()
    cibles = {}
    for module in modules:
        for prefixe in prefixes:
            cibles[f"{prefixe}{module}/__manifest__.py"] = module
    out, _err, code = git(
        ["ls-tree", "--name-only", "-r", ref, "--"] + list(cibles), chemin
    )
    if code:
        return set()
    return {
        cibles[ligne.strip()]
        for ligne in out.splitlines()
        if ligne.strip() in cibles
    }


def modules_repris(chemin, modules, prefixes, base):
    """Les modules que le fork a ajoutés et que l'amont porte désormais.

    C'est la seule forme d'absorption qui rende un commit caduc. Un module
    seulement MODIFIÉ par le fork existe des deux côtés depuis toujours :
    sa présence en amont ne dit rien, et la confondre avec une reprise ferait
    proposer l'abandon d'un correctif encore utile.

    La reprise se lit donc à la base de fusion : absent là-bas, présent chez
    l'amont aujourd'hui, le module est bien arrivé par nous puis par eux.
    """
    if not modules or not base:
        return []
    a_la_base = modules_presents(chemin, base, modules, prefixes)
    chez_amont = modules_presents(chemin, "FETCH_HEAD", modules, prefixes)
    return sorted(chez_amont - a_la_base)


def marquer_modules_amont(constat, chemin, prefixes):
    """Range les modules que l'amont apporte en « doc seulement » ou non.

    Le tri se fait sur l'arbre de L'AMONT : ce sont SES modules, et les
    passer au crible des nôtres en perdrait la plupart. Un module dont
    aucun fichier changé n'est du code se saute en relecture, et c'est le
    seul chiffre que cette passe existe pour produire.
    """
    stats = constat.get("stats_amont")
    if not stats:
        return
    reels = modules_presents(chemin, "FETCH_HEAD", stats["modules"], prefixes)
    constat["modules_amont_doc"] = [
        m for m in stats["modules_doc"] if m in reels
    ]
    constat["modules_amont_code"] = [
        m for m in stats["modules_code"] if m in reels
    ]


def prefixes_module(constat):
    """Où logent les modules de ce dépôt.

    Le fork du cœur d'Odoo est le seul à les ranger sous deux répertoires
    au lieu de les poser à sa racine.
    """
    if (constat.get("chemin") or "").rstrip("/").endswith("/odoo"):
        return repo_stats.PREFIXES_ODOO_CORE
    return repo_stats.PREFIXES_DEFAUT


def diagnostiquer(constat, racine=REPO_ROOT, delai=DELAI_GIT):
    """Le verdict d'un fork, enrichi sur place. Ne modifie aucun dépôt."""
    chemin = os.path.join(racine, constat["chemin"] or "")
    amont = constat["amont"]
    constat.update(
        {
            "verdict": "non_comparable",
            "motif": None,
            "nos": 0,
            "amont_avance": 0,
            "base": None,
            "conflits": [],
            "commits": [],
            "stats": None,
            "stats_amont": None,
            "modules_amont_doc": [],
            "modules_amont_code": [],
            "modules": [],
            "modules_repris": [],
        }
    )

    if not os.path.isdir(chemin):
        constat["motif"] = t("missing from disk")
        return constat
    if not amont or not amont.get("branche"):
        constat["motif"] = t("no upstream branch declared")
        return constat
    if est_superficiel(chemin):
        constat["motif"] = t("shallow repository")
        return constat
    if not recuperer_amont(chemin, amont["url"], amont["branche"], delai):
        constat["motif"] = t("upstream unreachable")
        return constat

    ecart = divergence(chemin)
    if ecart is None:
        constat["motif"] = t("divergence unreadable")
        return constat
    constat["nos"], constat["amont_avance"] = ecart
    constat["base"] = base_fusion(chemin)
    if constat["base"] is None:
        constat["motif"] = t("no merge base")
        return constat

    if constat["nos"] == 0:
        constat["verdict"] = (
            "a_jour" if constat["amont_avance"] == 0 else "en_retard"
        )
        if constat["amont_avance"]:
            prefixes = prefixes_module(constat)
            constat["stats_amont"] = repo_stats.agreger(
                ecart_amont(chemin), prefixes
            )
            marquer_modules_amont(constat, chemin, prefixes)
        return constat

    prefixes = prefixes_module(constat)
    constat["commits"] = nos_commits(chemin)
    lignes = notre_ecart(chemin)
    constat["stats"] = repo_stats.agreger(lignes, prefixes)
    constat["stats_amont"] = repo_stats.agreger(ecart_amont(chemin), prefixes)
    constat["conflits"] = predire_conflits(chemin)
    marquer_modules_amont(constat, chemin, prefixes)
    constat["modules"] = sorted(
        modules_presents(chemin, "HEAD", constat["stats"]["modules"], prefixes)
    )
    constat["modules_repris"] = modules_repris(
        chemin, constat["modules"], prefixes, constat["base"]
    )

    if not constat["conflits"]:
        constat["verdict"] = "a_rebaser"
    elif constat["modules_repris"] and set(constat["modules_repris"]) == set(
        constat["modules"]
    ):
        constat["verdict"] = "absorbe"
    else:
        constat["verdict"] = "en_conflit"
    return constat


VERDICTS = (
    "en_conflit",
    "absorbe",
    "a_rebaser",
    "en_retard",
    "non_comparable",
    "a_jour",
)


def passe_diagnostic(
    version,
    dossier=DOSSIER,
    racine=REPO_ROOT,
    parallele=PARALLELE,
    delai=DELAI_GIT,
):
    """Le diagnostic de tous les forks d'une version, en parallèle.

    Chaque dépôt est un répertoire git indépendant : un amont lent n'en
    retarde aucun autre, et un amont muet n'en fait échouer aucun.
    """
    lst = etat_forks(version, dossier, verifier=False)
    with ThreadPoolExecutor(max_workers=parallele) as pool:
        return list(pool.map(lambda c: diagnostiquer(c, racine, delai), lst))


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


_VERDICTS_TITRE = {
    "en_conflit": t("Conflicting"),
    "absorbe": t("Absorbed upstream"),
    "a_rebaser": t("To rebase"),
    "en_retard": t("Behind upstream"),
    "non_comparable": t("Cannot be compared"),
    "a_jour": t("Up to date"),
}
_VERDICTS_GENRE = {
    "en_conflit": "broken",
    "absorbe": "watch",
    "a_rebaser": "ok",
    "en_retard": "ok",
    "non_comparable": "dim",
    "a_jour": "dim",
}


def cumuler(lst):
    """Les chiffres de toute la passe : langages et modules apportés.

    Un module se compte par (dépôt, nom) : deux dépôts peuvent porter un
    module homonyme, et les fondre en ferait disparaître un.
    """
    langages = {}
    doc, code = set(), set()
    for constat in lst:
        stats = constat.get("stats_amont")
        if stats:
            for nom, valeur in stats["langages"].items():
                entree = langages.setdefault(nom, {"ajouts": 0, "retraits": 0})
                entree["ajouts"] += valeur["ajouts"]
                entree["retraits"] += valeur["retraits"]
        for module in constat.get("modules_amont_doc") or []:
            doc.add((constat["chemin"], module))
        for module in constat.get("modules_amont_code") or []:
            code.add((constat["chemin"], module))
    return {
        "langages": langages,
        "modules_doc": sorted(doc),
        "modules_code": sorted(code),
    }


def render_diagnostic(lst, version, colour=True):
    """Le rapport d'une passe à sec, groupé par verdict.

    Les dépôts que rien n'a touchés sont NOMMÉS et non tus : « rien à
    faire » et « comparaison impossible » sont deux réponses, et un
    silence ne dit ni l'une ni l'autre.
    """
    out = [
        paint(
            f"🔍 {t('Upgrade dry run')} — Odoo {version} — "
            f"{len(lst)} {t('forks')}",
            "step",
            colour,
        ),
        "─" * 62,
    ]
    for verdict in VERDICTS:
        groupe = [x for x in lst if x["verdict"] == verdict]
        if not groupe:
            continue
        titre = f"  {_VERDICTS_TITRE.get(verdict, verdict)} ({len(groupe)})"
        out.append(paint(titre, _VERDICTS_GENRE.get(verdict, ""), colour))
        for x in groupe:
            nom = (x["chemin"] or "").split("/")[-1]
            chiffres = f"+{x['nos']} −{x['amont_avance']}"
            detail = x.get("motif") or ""
            if x["conflits"]:
                detail = f"{len(x['conflits'])} {t('conflicting files')}"
            out.append(f"    {nom:38s} {chiffres:12s} {detail}")
            if x.get("modules_repris"):
                out.append(
                    paint(
                        "        ↳ "
                        + t("upstream now carries")
                        + " "
                        + ", ".join(x["modules_repris"]),
                        "watch",
                        colour,
                    )
                )
    total = cumuler(lst)
    out.append("─" * 62)
    out.append(
        f"  {t('Modules touched')} "
        f"{len(total['modules_doc']) + len(total['modules_code'])} · "
        f"{t('Documentation and translation only')} "
        f"{len(total['modules_doc'])} · "
        f"{t('Contains code')} {len(total['modules_code'])}"
    )
    langues = " · ".join(
        f"{nom} +{v['ajouts']} −{v['retraits']}"
        for nom, v in sorted(
            total["langages"].items(), key=lambda kv: -kv[1]["ajouts"]
        )
        if v["ajouts"] or v["retraits"]
    )
    if langues:
        out.append(f"  {langues}")
    out.append(paint(f"  {t('No state was written')}", "ok", colour))
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
    parser.add_argument(
        "--diagnostic",
        action="store_true",
        help=t("dry run: diverge, conflicts and statistics (network)"),
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

    if args.diagnostic:
        lst = passe_diagnostic(version, args.manifest_dir)
        if args.json:
            print(
                json.dumps(
                    {"version": version, "forks": lst},
                    indent=2,
                    ensure_ascii=False,
                    default=sorted,
                )
            )
        else:
            colour = sys.stdout.isatty() and not args.no_color
            print(render_diagnostic(lst, version, colour))
        return 0

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
