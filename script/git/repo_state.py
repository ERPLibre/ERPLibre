#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""L'état du code d'un checkout ERPLibre, en JSON stable, sans rien écrire.

Trois sous-commandes, toutes en lecture seule, toutes rendues sur la sortie
standard par un objet JSON qui porte « schema » (version du contrat) et
« command » :

- « snapshot » (par défaut) : la version d'ERPLibre et d'Odoo, le mode du
  checkout, et pour chaque dépôt du manifeste local son commit HEAD, son
  écart à ce que le manifeste demande et les modules Odoo qu'il porte, avec
  leur version lue dans « __manifest__.py ». « fingerprint » est un sha256
  des parties stables : deux instantanés du même état ont la même empreinte.
- « between DÉPÔT ANCIEN NOUVEAU » : les commits de « ANCIEN..NOUVEAU »
  dans un clone, bornés ; avec « --paths », les fichiers et les modules
  qui diffèrent entre les deux.
- « cross-version DÉPÔT » : le même chemin de dépôt sous les autres
  arbres « odoo<V>/ » du checkout — présence et version de chaque module,
  commits de notre fork dans l'autre version sans équivalent dans celle-ci,
  historique de chaque module des deux côtés, écart de code entre les deux.

Ce que le manifeste demande
---------------------------
Le manifeste local « .repo/local_manifests/erplibre_manifest.xml » est la
fusion que git-repo lit : sa « revision » est une branche quand le checkout
suit les branches, un commit quand il est gelé. La CIBLE d'un dépôt est le
commit que cette « revision » désigne dans son clone : le commit lui-même,
ou « refs/remotes/<remote>/<branche> », la branche de suivi que git-repo
avance à chaque synchronisation. Les fichiers de `manifest/` donnent en plus
ce que le manifeste local ne porte pas : « freeze-revision » et
« fork-upstream-freeze-revision ».

« state » d'un dépôt vaut :

  conforme        HEAD est la cible
  en_avance       la cible est un ancêtre de HEAD : HEAD porte des commits
                  de plus, et aucun de moins
  decale          tout autre cas : HEAD en retard, à côté, ou cible absente
                  du clone (« target » vaut alors None)
  sale            « --dirty » seulement : l'arbre du clone n'est pas son
                  commit — fichiers suivis modifiés, ou fichiers non suivis
                  que rien n'ignore ; « alignment » garde alors
                  conforme, en_avance ou decale. Un clone hors manifeste
                  reste « hors_manifeste », « dirty » le dit sale
  absent          le chemin du manifeste n'est pas cloné
  hors_manifeste  un clone sous « odoo<V>/ » ou « odoo<V>/addons/ » que le
                  manifeste local ne nomme pas
  erreur          git n'a pas pu lire le clone ; « error » dit pourquoi

Lecture seule, y compris pour un compte de service
--------------------------------------------------
Chaque appel à git passe « -c safe.directory=* » — le compte d'un service
Odoo n'est pas le propriétaire des clones —, « GIT_TERMINAL_PROMPT=0 » —
aucune invite d'identification ne bloque —, « GIT_OPTIONAL_LOCKS=0 » —
« git status » n'écrit pas l'index qu'il rafraîchit — et un délai. Aucune
commande ne touche au réseau : la comparaison entre versions se fait dans
chaque clone séparément, et le diff entre deux clones lit les objets de
l'autre par « GIT_ALTERNATE_OBJECT_DIRECTORIES », qui n'ajoute qu'une source
de lecture.

Une erreur sur un dépôt se rend dans son entrée (« error ») et n'arrête
jamais les autres.

Codes de sortie : 0 rendu complet, les erreurs par dépôt comprises ;
1 erreur interne (le JSON porte « error », la trace va sur la sortie
d'erreur) ; 2 usage ; 3 la cible n'existe pas — un chemin hors du
checkout ou non cloné, un NOUVEAU inconnu du clone, un « --repo » que ni
le manifeste ni le disque ne connaît.
"""

from __future__ import annotations

import argparse
import ast
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import traceback
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.git import manifest_freeze, repo_stats, repo_upgrade  # noqa: E402
from script.todo import git_repo_menu  # noqa: E402

SCHEMA = 1
COMMANDES = ("snapshot", "between", "cross-version")

EXIT_OK = 0
EXIT_INTERNE = 1
EXIT_USAGE = 2
EXIT_CIBLE = 3

# Le délai d'UN appel à git, en secondes.
DELAI = 30
# Le nombre de commits rendus au plus par « between » et par la liste des
# commits candidats au portage.
MAX_COMMITS = 200
# Le nombre de commits de l'historique d'un module rendus de chaque côté.
MAX_HISTOIRE = 20
# Le nombre de modules dont « cross-version » rend l'historique quand aucun
# module n'est nommé : un dépôt comme le cœur d'Odoo en porte des centaines.
MAX_HISTOIRE_MODULES = 100
# Le nombre de commits d'un module, dans la version de référence, contre
# lesquels un candidat au portage se compare. Un commit porté plus loin dans
# le passé se compte à porter.
FENETRE_REFERENCE = 1000
# La taille au plus du diff complet de « cross-version --full », en octets.
MAX_OCTETS = 1_000_000
# Les fichiers que l'écart de code de « cross-version » détaille au plus,
# par module puis en tout ; les comptes, eux, portent sur tous. Sans borne,
# le cœur d'Odoo détaille des dizaines de milliers de fichiers.
MAX_CHEMINS = 100
MAX_CHEMINS_TOTAL = 1000
# Les fichiers modifiés que « between --paths » nomme au plus ; les modules
# touchés, eux, se déduisent de tous.
MAX_CHEMINS_ENTRE = 1000

MANIFESTE_LOCAL = git_repo_menu.MANIFESTE_LOCAL
FICHIERS_MODULE = ("__manifest__.py", "__openerp__.py")
RE_VERSION_ODOO = re.compile(r"^odoo(\d+\.\d+)$")
RE_CHEMIN_VERSION = re.compile(r"^odoo(\d+\.\d+)/(.+)$")
# Les séparateurs de champs et d'enregistrements d'un « git log --format » :
# ni un sujet ni un nom ne les contient.
CHAMP = "\x1f"
ENREG = "\x1e"
FORMAT_COMMIT = f"{ENREG}%H{CHAMP}%an{CHAMP}%aI{CHAMP}%s"
# Les options qui gardent git muet et déterministe quelle que soit la
# configuration du compte : ni couleur, ni signature vérifiée par gpg, ni
# démon fsmonitor lancé, ni chemin échappé en octal.
OPTIONS_GIT = (
    "-c",
    "safe.directory=*",
    "-c",
    "color.ui=never",
    "-c",
    "log.showSignature=false",
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.quotepath=off",
)


# ── git ─────────────────────────────────────────────────────────────────


def git(args, cwd, delai=DELAI, entree=None, env=None):
    """(sortie, erreur, code) — ne lève jamais.

    `entree` est passée sur l'entrée standard, `env` complète
    l'environnement sans invite de `repo_upgrade.env_sans_invite`. Un délai
    dépassé rend le code 124 et « timeout » en erreur.
    """
    environ = repo_upgrade.env_sans_invite()
    environ["GIT_OPTIONAL_LOCKS"] = "0"
    if env:
        environ.update(env)
    try:
        done = subprocess.run(
            ["git", *OPTIONS_GIT, *args],
            cwd=cwd,
            input=entree,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=delai,
            env=environ,
        )
    except subprocess.TimeoutExpired:
        return "", f"timeout after {delai}s", 124
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc), 1
    return done.stdout, done.stderr, done.returncode


def erreur_git(err, code):
    """La première ligne d'erreur de git, ou son code à défaut."""
    ligne = (err or "").strip().splitlines()
    return ligne[0] if ligne else f"git exited with {code}"


def a_un_git(chemin):
    """Vrai si `chemin` porte un « .git » : dossier, fichier ou lien.

    Un test de système de fichiers et non un appel à git : il trie en une
    fraction de milliseconde les deux cents chemins d'un manifeste, et
    seuls les candidats passent par `lire_tete`.
    """
    return os.path.lexists(os.path.join(chemin, ".git"))


def lire_tete(chemin, delai=DELAI):
    """(head, branche, erreur) d'un clone, en un appel.

    « branche » vaut None sur une HEAD détachée, l'état où git-repo pose
    ses clones. La racine que git rend doit être `chemin` : un dossier sans
    dépôt propre sous un autre dépôt ferait sinon répondre son parent.
    """
    out, err, code = git(
        ["rev-parse", "--show-toplevel", "HEAD", "--abbrev-ref", "HEAD"],
        chemin,
        delai,
    )
    if code:
        return None, None, erreur_git(err, code)
    lignes = out.splitlines()
    if len(lignes) < 3:
        return None, None, "unexpected rev-parse output"
    if os.path.realpath(lignes[0]) != os.path.realpath(chemin):
        return None, None, "not the root of a git repository"
    head = lignes[1].strip()
    branche = lignes[2].strip()
    if not manifest_freeze.is_sha(head):
        return None, None, "HEAD is not a commit"
    return head, (None if branche == "HEAD" else branche), None


def resoudre(chemin, ref, delai=DELAI):
    """Le commit complet que `ref` désigne dans ce clone, ou None."""
    if not ref or ref.startswith("-"):
        return None
    out, _err, code = git(
        ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
        chemin,
        delai,
    )
    sha = out.strip()
    return sha if code == 0 and manifest_freeze.is_sha(sha) else None


def avance_retard(chemin, cible, head, delai=DELAI):
    """(commits de HEAD absents de la cible, commits de la cible absents de
    HEAD), ou (None, None) si git refuse."""
    out, _err, code = git(
        ["rev-list", "--left-right", "--count", f"{head}...{cible}"],
        chemin,
        delai,
    )
    champs = out.split()
    if code or len(champs) != 2:
        return None, None
    return int(champs[0]), int(champs[1])


def est_superficiel(chemin, delai=DELAI):
    """True pour un clone tronqué, False pour un clone complet, None si git
    refuse de le lire.

    Passe par `git`, comme tout appel du module : un clone dont le compte
    n'est pas le propriétaire se lit quand même, et un refus ne se confond
    pas avec un clone complet.
    """
    out, _err, code = git(
        ["rev-parse", "--is-shallow-repository"], chemin, delai
    )
    if code:
        return None
    return out.strip() == "true"


def est_sale(chemin, delai=DELAI):
    """True si l'arbre de travail n'est pas le commit HEAD, None si git
    refuse.

    Comptent les fichiers suivis modifiés et les fichiers non suivis que
    rien n'ignore : un module ou un fichier copié dans le clone est du code
    qu'Odoo charge. Les fichiers ignorés (« .pyc », « __pycache__ ») ne
    comptent pas, « git status » ne les liste pas.
    """
    out, _err, code = git(
        ["status", "--porcelain", "--untracked-files=normal"], chemin, delai
    )
    if code:
        return None
    return bool(out.strip())


def lire_commits(texte):
    """[{sha, author, date, subject}] d'une sortie au `FORMAT_COMMIT`."""
    lst = []
    for bloc in texte.split(ENREG):
        tete = bloc.split("\n", 1)[0]
        champs = tete.split(CHAMP)
        if len(champs) != 4 or not manifest_freeze.is_sha(champs[0]):
            continue
        lst.append(
            {
                "sha": champs[0],
                "author": champs[1],
                "date": champs[2],
                "subject": champs[3].strip(),
            }
        )
    return lst


def sans_identifiants(url):
    """L'URL sans ce qui peut porter un secret.

    En http(s), tout le « userinfo » part : un jeton d'accès s'y écrit
    souvent comme nom d'utilisateur. Ailleurs, seul le mot de passe part ;
    l'utilisateur d'une URL ssh (« git@ ») n'est pas un secret.
    """
    if not url:
        return url
    m = re.match(r"^(https?|ftps?)://[^/@]*@(.*)$", url, re.I)
    if m:
        return f"{m.group(1)}://{m.group(2)}"
    return re.sub(r"^([a-z][a-z0-9+.-]*://[^/:@]+):[^/@]*@", r"\1@", url)


# ── Lecture des fichiers du checkout ────────────────────────────────────


def lire_fichier(racine, nom):
    """Le contenu d'un fichier de la racine, sans blanc, ou None."""
    try:
        with open(os.path.join(racine, nom)) as fh:
            return fh.read().strip() or None
    except OSError:
        return None


def lire_manifeste_local(racine):
    """(remotes, défaut, projets) du manifeste local, ou None s'il manque.

    `projets` est une liste d'attributs dans l'ordre du fichier, `défaut`
    les attributs de « <default> ». Lu par un parseur XML : une entrée en
    commentaire n'est pas un projet. Lève ET.ParseError sur un fichier
    illisible.
    """
    chemin = os.path.join(racine, MANIFESTE_LOCAL)
    if not os.path.isfile(chemin):
        return None
    arbre = ET.parse(chemin).getroot()
    remotes = {e.get("name"): e.get("fetch") for e in arbre.findall("remote")}
    defaut = arbre.find("default")
    projets = [dict(p.attrib) for p in arbre.findall("project")]
    return (
        remotes,
        (dict(defaut.attrib) if defaut is not None else {}),
        projets,
    )


def chemin_projet(attrs):
    """Le chemin d'un projet ; son nom à défaut, comme dans git-repo."""
    return attrs.get("path") or attrs.get("name")


def lire_sources(racine, versions):
    """(remotes, {chemin: attributs}) des fichiers de `manifest/` de ces
    versions, fusionnés par `repo_upgrade.lire_manifestes`.

    Une version dont les fichiers sont illisibles est sautée : le manifeste
    local suffit à décrire ses dépôts, il n'y manquera que les gels.
    """
    dossier = os.path.join(racine, "manifest")
    remotes, par_chemin = {}, {}
    for version in sorted(versions):
        try:
            rem, projets = repo_upgrade.lire_manifestes(version, dossier)
        except (OSError, ET.ParseError):
            continue
        for nom, fetch in rem.items():
            remotes.setdefault(nom, fetch)
        for attrs in projets.values():
            attrs = dict(attrs)
            attrs.pop("_fichier", None)
            par_chemin[chemin_projet(attrs)] = attrs
    return remotes, par_chemin


def versions_des_chemins(chemins):
    """Les versions d'Odoo que nomment les chemins « odoo<V>/… »."""
    versions = set()
    for chemin in chemins:
        m = RE_CHEMIN_VERSION.match(chemin or "")
        if m:
            versions.add(m.group(1))
    return versions


def definitions(racine):
    """(projets, remotes, présent) — ce que le checkout déclare.

    `projets` est {chemin: attributs} : les attributs du manifeste local,
    complétés par ceux des fichiers de `manifest/` qu'il ne porte pas
    (« freeze-revision », « fork-upstream-freeze-revision »). Le manifeste
    local l'emporte sur le reste : c'est lui que git-repo a appliqué.
    `présent` est False quand le manifeste local manque ; les projets sont
    alors ceux des fichiers de `manifest/` de la version active.
    """
    local = lire_manifeste_local(racine)
    if local is None:
        version = repo_upgrade.version_active(racine)
        remotes, sources = lire_sources(racine, {version} if version else ())
        return sources, remotes, False
    remotes_local, defaut, projets = local
    versions = versions_des_chemins(chemin_projet(p) for p in projets)
    version = repo_upgrade.version_active(racine)
    if version:
        versions.add(version)
    remotes_src, sources = lire_sources(racine, versions)
    remotes = dict(remotes_src)
    remotes.update(remotes_local)
    fusion = {}
    for attrs in projets:
        chemin = chemin_projet(attrs)
        complet = dict(sources.get(chemin, {}))
        complet.update(attrs)
        for cle, valeur in defaut.items():
            if cle in ("remote", "revision"):
                complet.setdefault(cle, valeur)
        fusion[chemin] = complet
    return fusion, remotes, True


def amont_de(attrs, remotes):
    """L'amont d'un fork au format du contrat, ou None hors d'un fork."""
    amont = repo_upgrade.resoudre_amont(attrs, remotes)
    if amont is None:
        return None
    return {
        "remote": amont["remote"],
        "name": amont["nom"],
        "branch": amont["branche"],
        "freeze_revision": attrs.get(
            manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR
        ),
        "declared": amont["source"] == "declare",
        "url": sans_identifiants(amont["url"]) or None,
    }


def ref_cible(attrs):
    """La ref qui désigne, dans le clone, le commit que le manifeste
    demande : le commit lui-même, un tag, ou la branche de suivi
    « refs/remotes/<remote>/<branche> » que git-repo synchronise."""
    revision = attrs.get("revision")
    if not revision:
        return None
    if manifest_freeze.is_sha(revision) or revision.startswith("refs/tags/"):
        return revision
    branche = (
        revision[len("refs/heads/") :]
        if revision.startswith("refs/heads/")
        else revision
    )
    remote = attrs.get("remote")
    if not remote:
        return None
    return f"refs/remotes/{remote}/{branche}"


# ── Modules ─────────────────────────────────────────────────────────────


def lire_manifeste_module(fichier):
    """(données, erreur) d'un « __manifest__.py ».

    Lu par `ast.literal_eval` sur le premier dictionnaire du fichier, jamais
    importé : un module ne s'exécute pas pour qu'on lise sa version, et un
    commentaire ou une docstring avant le dictionnaire ne le gênent pas.
    """
    try:
        with open(fichier, encoding="utf-8") as fh:
            arbre = ast.parse(fh.read(), filename=fichier)
        for noeud in arbre.body:
            if isinstance(noeud, ast.Expr) and isinstance(
                noeud.value, ast.Dict
            ):
                donnees = ast.literal_eval(noeud.value)
                return donnees, None
    except (OSError, SyntaxError, ValueError, UnicodeDecodeError) as exc:
        return None, f"{type(exc).__name__}: {exc}"
    return None, "no dictionary in the manifest"


def prefixes_de(chemin):
    """Où logent les modules du dépôt à ce chemin (voir
    `repo_upgrade.prefixes_module`)."""
    return repo_upgrade.prefixes_module({"chemin": chemin})


def modules_du_depot(racine, chemin):
    """[{name, version, installable, path}] des modules du clone, triés.

    Un module est un dossier qui porte « __manifest__.py » (ou
    « __openerp__.py » des versions anciennes) sous un préfixe de
    `prefixes_de`. « path » est relatif à `racine`. Un manifeste illisible
    garde le module, sans version, avec « error ».
    """
    clone = os.path.join(racine, chemin)
    modules = {}
    for prefixe in prefixes_de(chemin):
        dossier = os.path.join(clone, prefixe)
        try:
            entrees = sorted(os.scandir(dossier), key=lambda e: e.name)
        except OSError:
            continue
        for entree in entrees:
            if entree.name.startswith(".") or not entree.is_dir():
                continue
            fichier = next(
                (
                    os.path.join(entree.path, f)
                    for f in FICHIERS_MODULE
                    if os.path.isfile(os.path.join(entree.path, f))
                ),
                None,
            )
            if not fichier or entree.name in modules:
                continue
            donnees, erreur = lire_manifeste_module(fichier)
            module = {
                "name": entree.name,
                "version": None,
                "installable": None,
                "path": os.path.join(chemin, prefixe, entree.name),
            }
            if donnees is not None:
                version = donnees.get("version")
                module["version"] = None if version is None else str(version)
                module["installable"] = bool(donnees.get("installable", True))
            if erreur:
                module["error"] = erreur
            modules[entree.name] = module
    return [modules[n] for n in sorted(modules)]


# ── snapshot ────────────────────────────────────────────────────────────


def clones_hors_manifeste(racine, connus):
    """Les clones sous « odoo<V>/ » et « odoo<V>/addons/ » que le manifeste
    ne nomme pas, triés. Un simple test de « .git » : `lire_tete` confirme
    ensuite que le dossier est bien la racine d'un dépôt."""
    trouves = []
    for version in versions_presentes(racine):
        for sous in ("", "addons"):
            base = (
                os.path.join(f"odoo{version}", sous)
                if sous
                else (f"odoo{version}")
            )
            try:
                noms = sorted(os.listdir(os.path.join(racine, base)))
            except OSError:
                continue
            for nom in noms:
                chemin = os.path.join(base, nom)
                if chemin in connus:
                    continue
                if a_un_git(os.path.join(racine, chemin)):
                    trouves.append(chemin)
    return trouves


def versions_presentes(racine):
    """Les versions des arbres « odoo<V>/ » de la racine, croissantes."""
    try:
        noms = os.listdir(racine)
    except OSError:
        return []
    versions = [
        m.group(1)
        for m in (RE_VERSION_ODOO.match(n) for n in noms)
        if m and os.path.isdir(os.path.join(racine, m.group(0)))
    ]
    return sorted(versions, key=cle_version)


def cle_version(version):
    """« 9.0 » avant « 12.0 » : un tri numérique, pas alphabétique."""
    try:
        return tuple(int(x) for x in version.split("."))
    except ValueError:
        return (float("inf"),)


def url_du_clone(chemin, delai=DELAI):
    """L'URL du premier remote du clone, en ordre alphabétique, ou None."""
    out, _err, code = git(
        ["config", "--get-regexp", r"^remote\..*\.url$"], chemin, delai
    )
    if code:
        return None, None
    lignes = sorted(out.splitlines())
    if not lignes:
        return None, None
    cle, _, url = lignes[0].partition(" ")
    return cle[len("remote.") : -len(".url")], sans_identifiants(url.strip())


def entree_depot(racine, chemin, attrs, remotes, sale, delai):
    """L'entrée du contrat pour un dépôt. `attrs` vaut None hors manifeste.

    Ne lève pas : une erreur inattendue se rend dans « error » avec l'état
    « erreur ».
    """
    entree = {
        "path": chemin,
        "name": None,
        "remote": None,
        "url": None,
        "revision": None,
        "manifest_branch": None,
        "freeze_revision": None,
        "upstream": None,
        "head": None,
        "branch": None,
        "target": None,
        "ahead": None,
        "behind": None,
        "alignment": None,
        "state": None,
        "dirty": None,
        "modules": [],
        "error": None,
    }
    try:
        remplir_depot(entree, racine, chemin, attrs, remotes, sale, delai)
    except Exception as exc:  # une entrée par dépôt, jamais une trace
        entree["state"] = "erreur"
        entree["error"] = f"{type(exc).__name__}: {exc}"
    return entree


def remplir_depot(entree, racine, chemin, attrs, remotes, sale, delai):
    """Remplit `entree` (voir `entree_depot`)."""
    clone = os.path.join(racine, chemin)
    if attrs is not None:
        entree["name"] = attrs.get("name")
        entree["remote"] = attrs.get("remote")
        entree["url"] = (
            sans_identifiants(
                repo_upgrade.url_amont(
                    remotes.get(attrs.get("remote")), attrs.get("name")
                )
            )
            or None
        )
        entree["revision"] = attrs.get("revision")
        entree["manifest_branch"] = manifest_freeze.manifest_branch(
            attrs.get("revision"),
            attrs.get("upstream"),
            attrs.get("dest-branch"),
        )
        entree["freeze_revision"] = attrs.get(manifest_freeze.FREEZE_ATTR)
        entree["upstream"] = amont_de(attrs, remotes)

    if not a_un_git(clone):
        entree["state"] = "absent" if attrs is not None else "erreur"
        if attrs is None:
            entree["error"] = "not a git repository"
        return

    head, branche, erreur = lire_tete(clone, delai)
    if erreur:
        entree["state"] = "erreur"
        entree["error"] = erreur
        return
    entree["head"], entree["branch"] = head, branche
    entree["modules"] = modules_du_depot(racine, chemin)

    if attrs is None:
        entree["state"] = "hors_manifeste"
        entree["name"] = os.path.basename(chemin)
        entree["remote"], entree["url"] = url_du_clone(clone, delai)
    else:
        ref = ref_cible(attrs)
        if ref == head:
            cible = head
        else:
            cible = resoudre(clone, ref, delai)
        entree["target"] = cible
        if cible == head:
            entree["ahead"] = entree["behind"] = 0
            entree["alignment"] = "conforme"
        elif cible:
            avance, retard = avance_retard(clone, cible, head, delai)
            entree["ahead"], entree["behind"] = avance, retard
            entree["alignment"] = (
                "en_avance" if retard == 0 and avance else "decale"
            )
        else:
            entree["alignment"] = "decale"
        entree["state"] = entree["alignment"]

    if sale:
        entree["dirty"] = est_sale(clone, delai)
        if entree["dirty"] and entree["state"] != "hors_manifeste":
            entree["state"] = "sale"


def empreinte(donnees):
    """sha256 des parties stables : tout sauf « generated_at », l'empreinte
    elle-même et la durée. Les clés sont triées : l'ordre d'écriture du
    dictionnaire ne compte pas."""
    stable = {
        k: v
        for k, v in donnees.items()
        if k not in ("generated_at", "fingerprint", "duration_ms")
    }
    brut = json.dumps(
        stable, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    return hashlib.sha256(brut.encode("utf-8")).hexdigest()


def etat_erplibre(racine, sale, delai):
    """La version, le commit et la branche du checkout ERPLibre."""
    info = {
        "version": lire_fichier(racine, ".erplibre-version"),
        "commit": None,
        "head": None,
        "branch": None,
        "dirty": None,
    }
    if not a_un_git(racine):
        return info
    head, branche, erreur = lire_tete(racine, delai)
    if erreur:
        info["error"] = erreur
        return info
    info["head"], info["branch"] = head, branche
    out, _err, code = git(
        ["describe", "--tags", "--always", "HEAD"], racine, delai
    )
    info["commit"] = out.strip() if code == 0 else head
    if sale:
        info["dirty"] = est_sale(racine, delai)
    return info


def mode_du_checkout(racine):
    """(mode, détail) tel que l'en-tête du menu le déduit.

    « frozen » dès qu'un projet du manifeste local est épinglé sur un
    commit, « branches » sinon, None sans manifeste local.
    """
    etat = git_repo_menu.etat_manifeste_local(racine)
    if etat is None:
        return None, None
    epingles, total = etat
    return ("frozen" if epingles else "branches"), {
        "pinned": epingles,
        "total": total,
    }


def normaliser(racine, chemin):
    """Le chemin relatif à la racine, ou None s'il en sort."""
    if os.path.isabs(chemin):
        chemin = os.path.relpath(chemin, racine)
    chemin = os.path.normpath(chemin)
    if chemin == ".." or chemin.startswith("../") or os.path.isabs(chemin):
        return None
    return chemin


def snapshot(racine, sale=False, depots=None, delai=DELAI, jobs=None):
    """(données, code de sortie) de l'instantané (voir la docstring du
    module). `depots` limite aux chemins nommés."""
    debut = datetime.datetime.now(datetime.timezone.utc)
    erreurs = []
    try:
        projets, remotes, local = definitions(racine)
    except (OSError, ET.ParseError) as exc:
        projets, remotes, local = {}, {}, False
        erreurs.append(f"manifest: {type(exc).__name__}: {exc}")
    mode, detail = mode_du_checkout(racine) if local else (None, None)

    cibles = [(c, projets[c]) for c in sorted(projets)]
    cibles += [(c, None) for c in clones_hors_manifeste(racine, set(projets))]
    cibles.sort(key=lambda x: x[0])
    code = EXIT_OK
    if depots:
        voulus = []
        for brut in depots:
            chemin = normaliser(racine, brut)
            if chemin is None:
                erreurs.append(f"--repo {brut}: outside the checkout")
                code = EXIT_CIBLE
                continue
            voulus.append(chemin)
        par_chemin = dict(cibles)
        cibles = []
        for chemin in dict.fromkeys(voulus):
            if chemin in par_chemin:
                cibles.append((chemin, par_chemin[chemin]))
            elif a_un_git(os.path.join(racine, chemin)):
                cibles.append((chemin, None))
            else:
                erreurs.append(f"--repo {chemin}: unknown repository")
                code = EXIT_CIBLE
        cibles.sort(key=lambda x: x[0])

    with ThreadPoolExecutor(max_workers=max(1, jobs or defaut_jobs())) as p:
        repos = list(
            p.map(
                lambda c: entree_depot(
                    racine, c[0], c[1], remotes, sale, delai
                ),
                cibles,
            )
        )

    donnees = {
        "schema": SCHEMA,
        "command": "snapshot",
        "generated_at": debut.isoformat(timespec="seconds"),
        "root": racine,
        "erplibre": etat_erplibre(racine, sale, delai),
        "odoo": {
            "version": lire_fichier(racine, ".odoo-version"),
            "python": lire_fichier(racine, ".python-odoo-version"),
        },
        "mode": mode,
        "mode_detail": detail,
        "local_manifest": local,
        "dirty_checked": bool(sale),
        "repos": repos,
        "counts": compter(repos),
        "errors": erreurs,
    }
    donnees["fingerprint"] = empreinte(donnees)
    fin = datetime.datetime.now(datetime.timezone.utc)
    donnees["duration_ms"] = int((fin - debut).total_seconds() * 1000)
    return donnees, code


def compter(repos):
    """{état: nombre} des dépôts, et le nombre de modules."""
    etats = {}
    for r in repos:
        etats[r["state"]] = etats.get(r["state"], 0) + 1
    return {
        "repos": len(repos),
        "modules": sum(len(r["modules"]) for r in repos),
        "states": dict(sorted(etats.items())),
    }


def defaut_jobs():
    """Le parallélisme par défaut : un fil par cœur, huit au moins.

    Les fils attendent git bien plus qu'ils ne calculent.
    """
    return max(repo_upgrade.PARALLELE, os.cpu_count() or 1)


# ── between ─────────────────────────────────────────────────────────────


def ouvrir_clone(racine, brut, delai):
    """(chemin relatif, dossier, head, branche, erreur) d'un argument DÉPÔT.

    `erreur` est non nulle quand le chemin sort du checkout ou n'est pas la
    racine d'un clone.
    """
    chemin = normaliser(racine, brut)
    if chemin is None:
        return None, None, None, None, "outside the checkout"
    dossier = os.path.join(racine, chemin)
    if not a_un_git(dossier):
        return chemin, dossier, None, None, "not a git repository"
    head, branche, erreur = lire_tete(dossier, delai)
    return chemin, dossier, head, branche, erreur


def between(
    racine,
    depot,
    ancien,
    neuf,
    maximum=MAX_COMMITS,
    delai=DELAI,
    chemins=False,
    max_chemins=MAX_CHEMINS_ENTRE,
):
    """(données, code de sortie) des commits de « ANCIEN..NOUVEAU ».

    « count » est le nombre total de commits de la plage, « commits » les
    `maximum` plus récents, « truncated » dit qu'il en manque. « removed »
    compte « NOUVEAU..ANCIEN » : non nul, l'historique a été réécrit entre
    les deux (« ancestor » vaut alors False). Un ANCIEN inconnu du clone
    — un commit qu'un historique réécrit a laissé derrière lui — ne fait
    pas une erreur : « old_known » vaut False et la plage reste vide.

    Avec `chemins`, « changed_modules » nomme les modules dont un fichier
    diffère entre les arbres des deux commits — ce qu'un passage de l'un à
    l'autre change sur le disque, réécriture comprise —, « paths_count »
    compte ces fichiers et « paths » en nomme `max_chemins` au plus
    (« paths_truncated »). Sans `chemins`, ces clés valent None.
    """
    donnees = {
        "schema": SCHEMA,
        "command": "between",
        "generated_at": maintenant(),
        "root": racine,
        "path": None,
        "old": ancien,
        "new": neuf,
        "old_sha": None,
        "new_sha": None,
        "old_known": False,
        "new_known": False,
        "ancestor": None,
        "shallow": None,
        "count": None,
        "removed": None,
        "truncated": False,
        "max": maximum,
        "commits": [],
        "changed_modules": None,
        "paths_count": None,
        "paths": None,
        "paths_truncated": None,
        "error": None,
    }
    chemin, dossier, _head, _branche, erreur = ouvrir_clone(
        racine, depot, delai
    )
    donnees["path"] = chemin
    if erreur:
        donnees["error"] = erreur
        return donnees, EXIT_CIBLE
    donnees["shallow"] = est_superficiel(dossier, delai)
    donnees["new_sha"] = resoudre(dossier, neuf, delai)
    donnees["new_known"] = bool(donnees["new_sha"])
    donnees["old_sha"] = resoudre(dossier, ancien, delai)
    donnees["old_known"] = bool(donnees["old_sha"])
    if not donnees["new_known"]:
        donnees["error"] = "new revision unknown in the clone"
        return donnees, EXIT_CIBLE
    if not donnees["old_known"]:
        return donnees, EXIT_OK
    vieux, nouveau = donnees["old_sha"], donnees["new_sha"]
    avance, retard = avance_retard(dossier, nouveau, vieux, delai)
    donnees["count"], donnees["removed"] = retard, avance
    donnees["ancestor"] = None if avance is None else avance == 0
    out, err, code = git(
        [
            "log",
            f"--format={FORMAT_COMMIT}",
            f"--max-count={max(0, maximum)}",
            f"{vieux}..{nouveau}",
        ],
        dossier,
        delai,
    )
    if code:
        donnees["error"] = erreur_git(err, code)
        return donnees, EXIT_OK
    donnees["commits"] = lire_commits(out)
    total = donnees["count"]
    donnees["truncated"] = total is not None and total > len(
        donnees["commits"]
    )
    if chemins:
        out, err, code = git(
            ["diff", "--name-only", "--no-renames", vieux, nouveau],
            dossier,
            delai,
        )
        if code:
            donnees["error"] = erreur_git(err, code)
            return donnees, EXIT_OK
        fichiers = [f for f in out.splitlines() if f.strip()]
        prefixes = prefixes_de(chemin)
        donnees["changed_modules"] = sorted(
            {
                m
                for m in (repo_stats.module_de(f, prefixes) for f in fichiers)
                if m
            }
        )
        donnees["paths_count"] = len(fichiers)
        donnees["paths"] = fichiers[: max(0, max_chemins)]
        donnees["paths_truncated"] = len(fichiers) > len(donnees["paths"])
    return donnees, EXIT_OK


def maintenant():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )


# ── cross-version ───────────────────────────────────────────────────────


def normaliser_sujet(sujet):
    """Le sujet comparé entre deux versions : blancs réduits, et sans le
    « [17.0] » de tête qu'un portage ajoute parfois."""
    sujet = re.sub(r"\s+", " ", sujet or "").strip()
    return re.sub(r"^\[\d+\.\d+\]\s*", "", sujet)


def patch_ids(dossier, args_log, delai=DELAI):
    """{sha: patch-id} des commits que `args_log` sélectionne, ou None si
    git échoue (un délai dépassé sur un long historique).

    « git log -p » limité au chemin du module, puis « git patch-id
    --stable » : l'identifiant ne dépend que du diff de ce module, ni du
    commit parent ni de l'ordre des fichiers, et se retrouve d'un clone à
    l'autre. Un commit de fusion n'a pas de diff et n'en reçoit pas.
    """
    out, _err, code = git(
        ["log", "-p", "--no-merges", "--format=commit %H", *args_log],
        dossier,
        delai,
    )
    if code:
        return None
    if not out.strip():
        return {}
    ids, _err, code = git(["patch-id", "--stable"], dossier, delai, out)
    if code:
        return None
    table = {}
    for ligne in ids.splitlines():
        champs = ligne.split()
        if len(champs) == 2:
            table[champs[1]] = champs[0]
    return table


def base_de_nos_commits(dossier, attrs, remotes, version, head, delai):
    """({sha, source}, motif) — d'où partent les commits de notre fork.

    Deux bases candidates : la base de fusion de HEAD et de la branche de
    suivi amont « refs/remotes/<remote amont>/<branche> » (la branche
    déclarée, ou le nom de la version faute de déclaration), source
    « upstream_ref » ; la base amont gelée, quand elle est un ancêtre de
    HEAD, source « upstream_freeze ». La plus récente des deux l'emporte :
    la branche de suivi, que seul le diagnostic de mise à niveau avance,
    peut rester en arrière d'un fork amené par la synchronisation, et une
    base trop ancienne compterait comme nôtres les commits amont posés
    entre elle et la vraie base. Le gel ne l'emporte que s'il descend de la
    base de fusion ; plus ancien ou à côté, la base de fusion reste. Un
    dépôt qui n'est pas un fork ne porte pas de commits à nous : motif
    « not_a_fork ».
    """
    if not attrs or not repo_upgrade.est_fork(attrs):
        return None, "not_a_fork"
    amont = repo_upgrade.resoudre_amont(attrs, remotes) or {}
    remote = amont.get("remote")
    branche = amont.get("branche") or version
    fusion = None
    if remote and branche:
        suivi = resoudre(dossier, f"refs/remotes/{remote}/{branche}", delai)
        if suivi:
            out, _err, code = git(["merge-base", head, suivi], dossier, delai)
            if code == 0 and manifest_freeze.is_sha(out.strip()):
                fusion = out.strip()
    gelee = resoudre(
        dossier, attrs.get(manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR), delai
    )
    if gelee and not est_ancetre(dossier, gelee, head, delai):
        gelee = None
    if fusion and gelee and fusion != gelee:
        if est_ancetre(dossier, fusion, gelee, delai):
            return {"sha": gelee, "source": "upstream_freeze"}, None
    if fusion:
        return {"sha": fusion, "source": "upstream_ref"}, None
    if gelee:
        return {"sha": gelee, "source": "upstream_freeze"}, None
    return None, "upstream_base_unknown"


def est_ancetre(dossier, ancetre, descendant, delai=DELAI):
    """True si `ancetre` est `descendant` ou l'un de ses ancêtres."""
    _out, _err, code = git(
        ["merge-base", "--is-ancestor", ancetre, descendant], dossier, delai
    )
    return code == 0


def commits_candidats(dossier, base, head, prefixes, modules, maximum, delai):
    """([commit], tronqué, hors_modules) — nos commits de « base..HEAD ».

    Chaque commit porte « modules », ceux de `modules` qu'il touche. Un
    commit qui n'en touche aucun est compté dans `hors_modules` et écarté :
    la comparaison se fait module par module.
    """
    out, _err, code = git(
        [
            "log",
            "--no-merges",
            "--name-only",
            f"--format={FORMAT_COMMIT}",
            f"--max-count={maximum + 1}",
            f"{base}..{head}",
        ],
        dossier,
        delai,
    )
    if code:
        return [], False, 0
    blocs = [b for b in out.split(ENREG) if b.strip()]
    tronque = len(blocs) > maximum
    commits, hors = [], 0
    for bloc in blocs[:maximum]:
        tete, _, fichiers = bloc.partition("\n")
        commit = lire_commits(ENREG + tete)
        if not commit:
            continue
        commit = commit[0]
        touches = {
            repo_stats.module_de(f.strip(), prefixes)
            for f in fichiers.splitlines()
            if f.strip()
        }
        commit["modules"] = sorted(m for m in touches if m in modules)
        if commit["modules"]:
            commits.append(commit)
        else:
            hors += 1
    return commits, tronque, hors


def dossier_module(prefixes, module, presents):
    """Le chemin du module dans le dépôt, sous le préfixe où il existe."""
    for prefixe in prefixes:
        if (prefixe, module) in presents:
            return f"{prefixe}{module}"
    return f"{prefixes[0]}{module}"


def prefixe_de(module_info, chemin_depot):
    """Le préfixe d'un module, lu dans son « path »."""
    rel = os.path.relpath(module_info["path"], chemin_depot)
    return rel[: len(rel) - len(module_info["name"])]


def historique(dossier, chemin_module, maximum, delai):
    """[commit] des `maximum` derniers commits qui touchent ce module."""
    out, _err, code = git(
        [
            "log",
            f"--format={FORMAT_COMMIT}",
            f"--max-count={maximum}",
            "HEAD",
            "--",
            chemin_module,
        ],
        dossier,
        delai,
    )
    return lire_commits(out) if code == 0 else []


def objets_de(dossier, delai):
    """Le magasin d'objets absolu d'un clone, ou None."""
    out, _err, code = git(
        ["rev-parse", "--path-format=absolute", "--git-path", "objects"],
        dossier,
        delai,
    )
    chemin = out.strip()
    return chemin if code == 0 and os.path.isdir(chemin) else None


def ecart_de_code(
    dossier,
    objets_autre,
    head_autre,
    head,
    chemins,
    prefixes,
    complet,
    max_octets,
    delai,
    max_chemins=None,
    max_total=None,
):
    """{modules: {nom: {files, added, removed, paths, paths_truncated}},
    paths_truncated, …} de l'autre version vers celle-ci, sur les commits
    HEAD des deux clones.

    Le diff se calcule dans ce clone, qui lit les objets de l'autre par
    « GIT_ALTERNATE_OBJECT_DIRECTORIES » : rien ne s'y copie. « files »,
    « added » et « removed » comptent tous les fichiers ; « paths » n'en
    détaille que `max_chemins` par module et `max_total` en tout, et
    « paths_truncated » dit qu'il en manque — celui du module pour sa liste,
    celui de la racine pour l'ensemble. Avec `complet`, « patch » porte le
    diff entier, coupé à `max_octets`.
    """
    max_chemins = MAX_CHEMINS if max_chemins is None else max_chemins
    max_total = MAX_CHEMINS_TOTAL if max_total is None else max_total
    resultat = {
        "from": head_autre,
        "to": head,
        "modules": {},
        "paths_truncated": False,
        "error": None,
    }
    if not chemins:
        return resultat
    env = {"GIT_ALTERNATE_OBJECT_DIRECTORIES": objets_autre or ""}
    base = ["diff", "-M", "--no-ext-diff", head_autre, head, "--", *chemins]
    out, err, code = git(
        base[:1] + ["--numstat"] + base[1:], dossier, delai, env=env
    )
    if code:
        resultat["error"] = erreur_git(err, code)
        return resultat
    detailles = 0
    for ajouts, retraits, fichier in repo_stats.lire_numstat(out):
        module = repo_stats.module_de(fichier, prefixes)
        if not module:
            continue
        stat = resultat["modules"].setdefault(
            module,
            {
                "files": 0,
                "added": 0,
                "removed": 0,
                "paths": [],
                "paths_truncated": False,
            },
        )
        stat["files"] += 1
        stat["added"] += ajouts
        stat["removed"] += retraits
        if len(stat["paths"]) >= max_chemins or detailles >= max_total:
            stat["paths_truncated"] = True
            resultat["paths_truncated"] = True
            continue
        stat["paths"].append(
            {"path": fichier, "added": ajouts, "removed": retraits}
        )
        detailles += 1
    if complet:
        out, err, code = git(base, dossier, delai, env=env)
        if code:
            resultat["error"] = erreur_git(err, code)
        else:
            brut = out.encode("utf-8")
            resultat["patch_truncated"] = len(brut) > max_octets
            resultat["patch"] = brut[:max_octets].decode(
                "utf-8", errors="ignore"
            )
    return resultat


def comparer_version(
    racine, ici, autre_version, reste, projets, remotes, filtre, options
):
    """L'entrée de l'autre version W pour « cross-version » (voir
    `cross_version`). Ne lève pas."""
    chemin = f"odoo{autre_version}/{reste}"
    entree = {
        "version": autre_version,
        "path": chemin,
        "present": False,
        "head": None,
        "branch": None,
        "fork": None,
        "base": None,
        "modules": [],
        "to_port": None,
        "ported": [],
        "to_port_reason": None,
        "outside_modules": 0,
        "incomplete_modules": [],
        "truncated": False,
        "history": {},
        "history_truncated": False,
        "diff": None,
        "error": None,
    }
    try:
        remplir_version(
            entree,
            racine,
            ici,
            autre_version,
            chemin,
            projets,
            remotes,
            filtre,
            options,
        )
    except Exception as exc:  # une entrée par version, jamais une trace
        entree["error"] = f"{type(exc).__name__}: {exc}"
    return entree


def remplir_version(
    entree, racine, ici, version, chemin, projets, remotes, filtre, options
):
    """Remplit `entree` (voir `comparer_version`)."""
    delai = options["timeout"]
    dossier = os.path.join(racine, chemin)
    if not a_un_git(dossier):
        return
    head, branche, erreur = lire_tete(dossier, delai)
    if erreur:
        entree["error"] = erreur
        return
    entree.update(present=True, head=head, branch=branche)
    attrs = projets.get(chemin)
    entree["fork"] = bool(attrs and repo_upgrade.est_fork(attrs))

    mods_la = {m["name"]: m for m in modules_du_depot(racine, chemin)}
    mods_ici = ici["modules_par_nom"]
    noms = sorted(set(mods_la) | set(mods_ici))
    if filtre:
        noms = [n for n in noms if n == filtre]

    def resume(m):
        return (
            None if m is None else {"version": m["version"], "path": m["path"]}
        )

    entree["modules"] = [
        {
            "name": n,
            "here": resume(mods_ici.get(n)),
            "there": resume(mods_la.get(n)),
        }
        for n in noms
    ]

    prefixes = prefixes_de(chemin)
    presents_la = {(prefixe_de(m, chemin), n) for n, m in mods_la.items()}
    presents_ici = {
        (prefixe_de(m, ici["path"]), n) for n, m in mods_ici.items()
    }

    # Nos commits dans l'autre version, et leur équivalent dans celle-ci.
    base, motif = base_de_nos_commits(
        dossier, attrs, remotes, version, head, delai
    )
    entree["base"] = base
    entree["to_port_reason"] = motif
    if base:
        candidats, tronque, hors = commits_candidats(
            dossier,
            base["sha"],
            head,
            prefixes,
            set(noms) & set(mods_la),
            options["max"],
            delai,
        )
        entree["truncated"] = tronque
        entree["outside_modules"] = hors
        (
            entree["to_port"],
            entree["ported"],
            entree["incomplete_modules"],
        ) = apparier(
            ici,
            dossier,
            [f"--max-count={options['max']}", f"{base['sha']}..{head}"],
            candidats,
            prefixes,
            presents_la,
            presents_ici,
            delai,
        )

    # L'écart de code des modules communs.
    communs = [n for n in noms if n in mods_la and n in mods_ici]
    entree["diff"] = ecart_de_code(
        ici["dossier"],
        objets_de(dossier, delai),
        head,
        ici["head"],
        [dossier_module(prefixes, n, presents_ici) for n in communs],
        prefixes,
        options["full"],
        options["max_bytes"],
        delai,
        options["max_paths"],
        options["max_paths_total"],
    )

    # L'historique de chaque module, des deux côtés : d'abord ceux qui
    # diffèrent (code, ou présents d'un seul côté), puis les autres, au plus
    # `history_modules` sans module nommé.
    differents = set(entree["diff"]["modules"]) | {
        n for n in noms if (n in mods_la) != (n in mods_ici)
    }
    avec_histoire = sorted(
        (n for n in noms if n in mods_la or n in mods_ici),
        key=lambda n: (n not in differents, n),
    )
    if not filtre and len(avec_histoire) > options["history_modules"]:
        avec_histoire = avec_histoire[: options["history_modules"]]
        entree["history_truncated"] = True

    def deux_cotes(nom):
        cote = {}
        for cle, dos, presents, mods in (
            ("here", ici["dossier"], presents_ici, mods_ici),
            ("there", dossier, presents_la, mods_la),
        ):
            cote[cle] = (
                historique(
                    dos,
                    dossier_module(prefixes, nom, presents),
                    options["history"],
                    delai,
                )
                if nom in mods
                else []
            )
        return nom, cote

    with ThreadPoolExecutor(max_workers=options["jobs"]) as pool:
        entree["history"] = dict(sorted(pool.map(deux_cotes, avec_histoire)))


def apparier(
    ici,
    dossier,
    plage,
    candidats,
    prefixes,
    presents_la,
    presents_ici,
    delai,
):
    """(à porter, portés, incomplets) — chaque candidat, module par module.

    Un candidat est porté quand un commit de ce module, dans les
    `FENETRE_REFERENCE` derniers de cette version, a le même patch-id
    (limité au dossier du module) ou le même sujet normalisé. Les deux se
    calculent dans chaque clone séparément ; l'appariement se fait ici.
    `incomplets` nomme les modules dont un patch-id n'a pas pu se calculer :
    leurs candidats ne s'y apparient que par le sujet.
    """
    a_porter, portes, incomplets = [], [], []
    modules = sorted({m for c in candidats for m in c["modules"]})
    for module in modules:
        chemin_la = dossier_module(prefixes, module, presents_la)
        ids_la = patch_ids(dossier, [*plage, "--", chemin_la], delai)
        ids_ici, sujets_ici = {}, {}
        if any(n == module for _p, n in presents_ici):
            chemin_ici = dossier_module(prefixes, module, presents_ici)
            par_sha = patch_ids(
                ici["dossier"],
                [f"--max-count={FENETRE_REFERENCE}", "HEAD", "--", chemin_ici],
                delai,
            )
            if par_sha is None:
                incomplets.append(module)
            ids_ici = {pid: sha for sha, pid in (par_sha or {}).items()}
            for commit in historique(
                ici["dossier"], chemin_ici, FENETRE_REFERENCE, delai
            ):
                sujets_ici.setdefault(
                    normaliser_sujet(commit["subject"]), commit["sha"]
                )
        for commit in candidats:
            if module not in commit["modules"]:
                continue
            pid = (ids_la or {}).get(commit["sha"])
            ligne = {
                "module": module,
                "sha": commit["sha"],
                "subject": commit["subject"],
                "author": commit["author"],
                "date": commit["date"],
                "patch_id": pid,
                "match": None,
            }
            if pid and pid in ids_ici:
                ligne["match"] = {"by": "patch-id", "sha": ids_ici[pid]}
            elif normaliser_sujet(commit["subject"]) in sujets_ici:
                ligne["match"] = {
                    "by": "subject",
                    "sha": sujets_ici[normaliser_sujet(commit["subject"])],
                }
            (portes if ligne["match"] else a_porter).append(ligne)
        if ids_la is None and module not in incomplets:
            incomplets.append(module)
    return a_porter, portes, incomplets


def cross_version(racine, depot, module=None, options=None):
    """(données, code de sortie) de la comparaison entre versions.

    DÉPÔT est un chemin « odoo<V>/<reste> ». Pour chaque autre arbre
    « odoo<W>/ » de la racine, l'entrée de « others » compare
    « odoo<W>/<reste> » à ce dépôt :

    - « modules » : chaque module des deux côtés, « here » et « there »
      valant {version, path} ou None ;
    - « to_port » : nos commits de l'autre version (« base..HEAD », voir
      `base_de_nos_commits`) qui touchent un module et n'ont pas
      d'équivalent ici, « ported » ceux qui en ont un (« match ») ;
      None avec « to_port_reason » quand la base est introuvable ou que le
      dépôt n'est pas un fork ;
    - « history » : les derniers commits de chaque module, des deux côtés ;
      sans module nommé, ceux de « history_modules » modules au plus, ceux
      qui diffèrent d'abord (« history_truncated ») ;
    - « diff » : l'écart de code des modules communs, de l'autre version
      vers celle-ci, sa liste de fichiers bornée (voir `ecart_de_code`).
    """
    options = dict(
        {
            "timeout": DELAI,
            "max": MAX_COMMITS,
            "history": MAX_HISTOIRE,
            "history_modules": MAX_HISTOIRE_MODULES,
            "full": False,
            "max_bytes": MAX_OCTETS,
            "max_paths": MAX_CHEMINS,
            "max_paths_total": MAX_CHEMINS_TOTAL,
            "jobs": defaut_jobs(),
        },
        **(options or {}),
    )
    delai = options["timeout"]
    donnees = {
        "schema": SCHEMA,
        "command": "cross-version",
        "generated_at": maintenant(),
        "root": racine,
        "path": None,
        "version": None,
        "module": module,
        "repo": None,
        "others": [],
        "error": None,
    }
    chemin, dossier, head, branche, erreur = ouvrir_clone(racine, depot, delai)
    donnees["path"] = chemin
    m = RE_CHEMIN_VERSION.match(chemin or "")
    if not erreur and not m:
        erreur = "not under an odoo<V>/ tree"
    if erreur:
        donnees["error"] = erreur
        return donnees, EXIT_CIBLE
    version, reste = m.group(1), m.group(2)
    donnees["version"] = version
    try:
        projets, remotes, _local = definitions(racine)
    except (OSError, ET.ParseError) as exc:
        projets, remotes = {}, {}
        donnees["error"] = f"manifest: {type(exc).__name__}: {exc}"
    modules = modules_du_depot(racine, chemin)
    attrs = projets.get(chemin)
    donnees["repo"] = {
        "path": chemin,
        "head": head,
        "branch": branche,
        "fork": bool(attrs and repo_upgrade.est_fork(attrs)),
        "modules": [m for m in modules if not module or m["name"] == module],
    }
    ici = {
        "path": chemin,
        "dossier": dossier,
        "head": head,
        "modules_par_nom": {m["name"]: m for m in modules},
    }
    for autre in versions_presentes(racine):
        if autre == version:
            continue
        donnees["others"].append(
            comparer_version(
                racine, ici, autre, reste, projets, remotes, module, options
            )
        )
    return donnees, EXIT_OK


# ── CLI ─────────────────────────────────────────────────────────────────


def analyser(argv):
    """Les arguments ; « snapshot » quand aucune sous-commande n'est
    nommée en tête."""
    argv = list(argv)
    if not argv or (
        argv[0] not in COMMANDES and argv[0] not in ("-h", "--help")
    ):
        argv = ["snapshot"] + argv

    commun = argparse.ArgumentParser(add_help=False)
    commun.add_argument(
        "--root",
        default=repo_upgrade.REPO_ROOT,
        help="ERPLibre checkout to read (default: this one)",
    )
    commun.add_argument(
        "--timeout",
        type=float,
        default=DELAI,
        help=f"seconds allowed to each git call (default {DELAI})",
    )
    commun.add_argument(
        "--jobs", type=int, default=0, help="parallel git calls"
    )
    commun.add_argument(
        "--json",
        action="store_true",
        help="accepted for compatibility: the output is always JSON",
    )
    commun.add_argument(
        "--pretty", action="store_true", help="indent the JSON"
    )

    parser = argparse.ArgumentParser(
        description="Read-only state of the code of an ERPLibre checkout, "
        "as JSON."
    )
    sous = parser.add_subparsers(dest="commande")

    snap = sous.add_parser(
        "snapshot", parents=[commun], help="state of every repository"
    )
    snap.add_argument(
        "--dirty",
        action="store_true",
        help="also run git status in every clone (slower)",
    )
    snap.add_argument(
        "--repo",
        action="append",
        default=[],
        metavar="PATH",
        help="limit to this repository path (repeatable)",
    )

    entre = sous.add_parser(
        "between", parents=[commun], help="commits between two revisions"
    )
    entre.add_argument("repo", metavar="REPO_PATH")
    entre.add_argument("old", metavar="OLD")
    entre.add_argument("new", metavar="NEW")
    entre.add_argument("--max", type=int, default=MAX_COMMITS)
    entre.add_argument(
        "--paths",
        action="store_true",
        help="also name the changed files and the modules they belong to",
    )
    entre.add_argument(
        "--max-paths",
        type=int,
        default=MAX_CHEMINS_ENTRE,
        help=f"changed files named at most (default {MAX_CHEMINS_ENTRE})",
    )

    croise = sous.add_parser(
        "cross-version",
        parents=[commun],
        help="the same repository under the other odoo<V>/ trees",
    )
    croise.add_argument("repo", metavar="MODULE_REPO_PATH")
    croise.add_argument("--module", default=None, metavar="NAME")
    croise.add_argument(
        "--max",
        type=int,
        default=MAX_COMMITS,
        help="our commits read at most in the other version",
    )
    croise.add_argument(
        "--history",
        type=int,
        default=MAX_HISTOIRE,
        help="commits of each module history, per side",
    )
    croise.add_argument(
        "--history-modules",
        type=int,
        default=MAX_HISTOIRE_MODULES,
        help="modules given a history without --module, those that differ "
        f"first (default {MAX_HISTOIRE_MODULES})",
    )
    croise.add_argument(
        "--full", action="store_true", help="include the full diff"
    )
    croise.add_argument("--max-bytes", type=int, default=MAX_OCTETS)
    croise.add_argument(
        "--max-paths",
        type=int,
        default=MAX_CHEMINS,
        help=f"files of the code difference listed per module "
        f"(default {MAX_CHEMINS})",
    )
    croise.add_argument(
        "--max-paths-total",
        type=int,
        default=MAX_CHEMINS_TOTAL,
        help=f"files of the code difference listed in all "
        f"(default {MAX_CHEMINS_TOTAL})",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = analyser(sys.argv[1:] if argv is None else argv)
    racine = os.path.realpath(args.root)
    jobs = args.jobs or defaut_jobs()
    try:
        if args.commande == "between":
            donnees, code = between(
                racine,
                args.repo,
                args.old,
                args.new,
                args.max,
                args.timeout,
                args.paths,
                args.max_paths,
            )
        elif args.commande == "cross-version":
            donnees, code = cross_version(
                racine,
                args.repo,
                args.module,
                {
                    "timeout": args.timeout,
                    "max": max(0, args.max),
                    "history": max(0, args.history),
                    "history_modules": max(0, args.history_modules),
                    "full": args.full,
                    "max_bytes": max(0, args.max_bytes),
                    "max_paths": max(0, args.max_paths),
                    "max_paths_total": max(0, args.max_paths_total),
                    "jobs": jobs,
                },
            )
        else:
            donnees, code = snapshot(
                racine, args.dirty, args.repo, args.timeout, jobs
            )
    except Exception as exc:
        traceback.print_exc(file=sys.stderr)
        donnees = {
            "schema": SCHEMA,
            "command": args.commande,
            "error": f"internal: {type(exc).__name__}: {exc}",
        }
        code = EXIT_INTERNE
    json.dump(
        donnees,
        sys.stdout,
        ensure_ascii=False,
        indent=2 if args.pretty else None,
    )
    sys.stdout.write("\n")
    return code


if __name__ == "__main__":
    sys.exit(main())
