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

Le remote amont NOMMÉ
---------------------
Un amont déclaré se range dans le clone sous un remote qui porte le nom de
« fork-upstream-remote », à l'URL que `resoudre_amont` compose : la branche
amont se lit alors « <remote>/<branche> », dans tig comme dans le reflog
du rebase. `preparer_remote` le pose, `ajouter_remotes` le pose et le
récupère sur tous les forks, et la passe à sec fait de même avant de
comparer. Un remote homonyme qui vise une autre URL n'est jamais modifié :
il est signalé, avec la commande qui le corrige.
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

from script.git import manifest_freeze, repo_stats  # noqa: E402

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


def env_sans_invite():
    """L'environnement d'un git qui ne demande jamais d'identifiant.

    Un dépôt HTTPS absent ou privé fait répondre 401 à l'hébergeur, et git
    réclame alors un nom d'utilisateur sur le terminal : la passe, lancée
    sur tous les forks en parallèle, resterait suspendue à une invite.
    « GIT_TERMINAL_PROMPT=0 » fait échouer la commande à la place ; un
    assistant d'identification configuré, et la clé SSH, servent toujours.
    """
    return dict(os.environ, GIT_TERMINAL_PROMPT="0")


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


def versions_installees(racine=REPO_ROOT, dossier=DOSSIER):
    """Les versions d'Odoo du checkout, croissantes : celles qui ont un arbre
    « odoo<V>/ » à la racine ET un manifeste.

    Un arbre sans manifeste n'a aucun fork à lire, et un manifeste sans
    arbre n'a aucun clone où poser un remote.
    """
    try:
        noms = os.listdir(racine)
    except OSError:
        return []
    versions = []
    for nom in noms:
        m = re.match(r"^odoo(\d+\.\d+)$", nom)
        if (
            m
            and os.path.isdir(os.path.join(racine, nom))
            and fichiers_manifeste(m.group(1), dossier)
        ):
            versions.append(m.group(1))
    return sorted(versions, key=lambda v: tuple(int(x) for x in v.split(".")))


def fichiers_manifeste(version, dossier=DOSSIER):
    """Les manifestes d'une version, dans l'ordre où ils se fusionnent.

    Les trois se lisent ENSEMBLE et jamais séparément : un remote amont
    peut n'être déclaré que dans le fichier « extra » ou « dev » alors
    que le fork qui s'y réfère vit dans le principal. Une résolution
    fichier par fichier rate cet amont et le déclare inconnu à tort.
    """
    gabarits = (
        f"git_manifest_odoo{version}.xml",
        f"git_manifest_odoo{version}_dev.xml",
        f"git_manifest_extra_odoo{version}.xml",
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
            env=env_sans_invite(),
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

    « base_gelee » est la base amont que le gel a écrite dans
    « fork-upstream-freeze-revision », ou None, et « gel » le commit gelé
    de « freeze-revision ». Les deux se lisent sur la définition qui
    l'emporte dans la fusion, comme « revision » et « remote », le remote
    du fork, sous le nom que git-repo donne aussi au remote du clone, et
    « clone_depth », la profondeur de clonage du manifeste, ou None.

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
                "remote": projet.get("remote"),
                "clone_depth": projet.get("clone-depth"),
                "gel": projet.get(manifest_freeze.FREEZE_ATTR),
                "base_gelee": projet.get(
                    manifest_freeze.FORK_UPSTREAM_FREEZE_ATTR
                ),
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
# Tout ce qui suit LIT, à trois écritures près, toutes hors de ce que
# git-repo suit : les objets que « git fetch » range dans le magasin, le
# remote amont nommé quand il manque (`preparer_remote`), et sa branche de
# suivi « refs/remotes/<remote>/<branche> », que le fetch avance. Aucune
# branche locale n'est créée ni déplacée, HEAD et l'arbre de travail ne
# bougent pas. C'est ce qui permet de constater avant de décider.

DELAI_GIT = 300

# La profondeur proposée pour récupérer à la main l'amont d'un clone
# superficiel dont le manifeste ne donne pas « clone-depth ».
PROFONDEUR_MANUELLE = 50


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
            env=env_sans_invite(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc), 1
    return done.stdout, done.stderr, done.returncode


def commit_de(chemin, ref):
    """Le commit complet que `ref` désigne dans ce clone, ou None."""
    out, _err, code = git(
        ["rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"], chemin
    )
    sha = out.strip()
    return sha if code == 0 and sha else None


def est_superficiel(chemin):
    """Un clone tronqué n'a pas de base de fusion avec son amont."""
    out, _err, code = git(["rev-parse", "--is-shallow-repository"], chemin)
    return code == 0 and out.strip() == "true"


def recuperer_amont(
    chemin, url, branche, delai=DELAI_GIT, profondeur=None, remote=None
):
    """Amène la branche amont dans FETCH_HEAD. True si elle y est.

    Sans `remote`, le fetch se fait par l'URL : seul FETCH_HEAD change.
    Avec, il passe par ce remote, que `preparer_remote` a posé, et sa
    refspec explicite « +refs/heads/<branche>:refs/remotes/<remote>/<branche> »
    avance aussi la branche de suivi, quelle que soit la refspec que le
    remote porte dans sa configuration. « --no-tags » garde les tags de
    l'amont hors de ceux du clone, même sur un remote posé à la main.

    `profondeur` borne l'historique amont rapatrié (« --depth »). Elle ne
    sert qu'à un clone déjà superficiel : sur un clone complet, « --depth »
    le rendrait superficiel.
    """
    args = ["fetch", "--quiet"]
    if profondeur:
        args.append(f"--depth={profondeur}")
    if remote:
        suivi = f"+refs/heads/{branche}:refs/remotes/{remote}/{branche}"
        args += ["--no-tags", remote, suivi]
    else:
        args += [url, branche]
    _out, _err, code = git(args, chemin, delai)
    return code == 0


def remote_amont(amont):
    """Le nom du remote amont à poser dans le clone, ou None.

    Seul un amont DÉCLARÉ en a un : « fork-upstream-remote », une URL que
    les manifestes résolvent et une branche « fork-upstream ». Un amont
    deviné par la convention peut viser un autre dépôt, et un remote posé
    sur lui resterait dans le clone après correction du manifeste.
    """
    if not amont or amont.get("source") != "declare":
        return None
    if not (amont.get("remote") and amont.get("url") and amont.get("branche")):
        return None
    return amont["remote"]


def motif_sans_remote(amont):
    """Pourquoi `remote_amont` ne rend rien pour cet amont."""
    if not amont or amont.get("source") != "declare":
        return t("no fork-upstream-remote attribute")
    if not amont.get("url"):
        return t("upstream remote absent from the manifests")
    return t("no fork-upstream branch for this version")


def url_du_remote(chemin, remote):
    """L'URL que la configuration du clone donne à `remote`, ou None.

    Lue brute par « git config » et non par « git remote get-url », qui
    applique les réécritures « url.<base>.insteadOf » : la comparaison
    porte sur ce qui est écrit, que `remote set-url` corrige.
    """
    out, _err, code = git(["config", "--get", f"remote.{remote}.url"], chemin)
    return out.strip() if code == 0 else None


def cle_url(url):
    """La clé qui identifie le dépôt que vise `url`, quelle qu'en soit
    l'écriture.

    « https://hôte/chemin », « ssh://[user@]hôte[:port]/chemin » et
    « user@hôte:chemin » rendent le même tuple (hôte en minuscules, chemin
    sans « / » ni « .git » final). Toute autre forme — chemin local,
    « file:// » — se rend telle quelle, sans « / » final : elle ne se
    compare qu'à elle-même.
    """
    url = (url or "").strip()
    m = re.match(
        r"^(?:https?|ssh|git)://(?:[^@/]+@)?([^/:]+)(?::\d+)?/(.*)$", url
    ) or re.match(r"^[^@/:]+@([^/:]+):(?!/)(.*)$", url)
    if not m:
        return url.rstrip("/")
    depot = m.group(2).strip("/")
    if depot.endswith(".git"):
        depot = depot[: -len(".git")]
    return m.group(1).lower(), depot


def preparer_remote(chemin, amont, delai=DELAI_GIT):
    """(etat, url en place) du remote amont nommé de ce clone.

    `etat` vaut :
      None        l'amont n'a pas de remote nommé (voir `remote_amont`)
      non_clone   `chemin` n'est pas la racine d'un clone : rien n'est posé
      ajoute      le remote manquait, « git remote add » l'a posé
      present     le remote existe déjà à la même URL, et sert tel quel
      autre_url   le remote existe à une autre URL : il n'est pas touché
      refuse      git a refusé de l'ajouter ou de le configurer

    « --no-tags » écrit « tagOpt = --no-tags » dans la configuration du
    remote : les tags de l'amont ne se mêlent pas à ceux du clone, où un
    tag homonyme du fork serait sinon remplacé ou refusé. « -t <branche> »
    restreint sa refspec à « +refs/heads/<branche>:refs/remotes/<remote>/
    <branche> » : un « git fetch <remote> » sans argument n'amène que la
    branche amont déclarée, et non chaque branche de l'amont. Sur un clone
    superficiel, « skipFetchAll » exclut en plus le remote de
    « git fetch --all », qui y rapatrierait tout l'historique amont.

    La même URL s'entend au sens de `cle_url` : l'écriture https et
    l'écriture ssh d'un même dépôt se valent, puisque la conversion des
    remotes du dépôt en ssh réécrit aussi celui-ci. Un remote déjà présent
    garde sa refspec. L'URL en place n'est rendue que pour « present » et
    « autre_url ».
    """
    remote = remote_amont(amont)
    if not remote:
        return None, None
    if not est_clone(chemin):
        return "non_clone", None
    en_place = url_du_remote(chemin, remote)
    if en_place is None:
        branche = amont["branche"]
        _out, _err, code = git(
            [
                "remote",
                "add",
                "--no-tags",
                "-t",
                branche,
                remote,
                amont["url"],
            ],
            chemin,
            delai,
        )
        if not code and est_superficiel(chemin):
            _out, _err, code = git(
                ["config", f"remote.{remote}.skipFetchAll", "true"], chemin
            )
        return ("refuse" if code else "ajoute"), None
    if cle_url(en_place) == cle_url(amont["url"]):
        return "present", en_place
    return "autre_url", en_place


def commande_set_url(chemin, remote, url):
    """La commande qui rend à `remote` l'URL déclarée, depuis la racine."""
    return f"git -C {chemin} remote set-url {remote} {url}"


def commande_fetch_superficiel(chemin, remote, branche, profondeur=None):
    """La commande qui récupère à la main l'amont d'un clone superficiel."""
    profondeur = profondeur or PROFONDEUR_MANUELLE
    return f"git -C {chemin} fetch --depth={profondeur} {remote} {branche}"


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


def depuis_le_gel(chemin, base):
    """(commits amont depuis `base`, amont réécrit) face à FETCH_HEAD.

    `base` est la base amont gelée. Elle est ancêtre de FETCH_HEAD tant que
    l'amont n'a fait qu'avancer : le compte est alors celui de
    « base..FETCH_HEAD ». Une base qui n'en est plus ancêtre dit un amont
    réécrit (force-push), et aucun compte n'a de sens. Le clone est
    complet (un clone superficiel s'arrête avant) et le fetch a amené tout
    l'historique de FETCH_HEAD : une base absente du clone n'en fait donc
    pas partie, et compte aussi comme un amont réécrit. (None, None) quand
    git échoue.
    """
    _out, _err, code = git(["cat-file", "-e", f"{base}^{{commit}}"], chemin)
    if code:
        return None, True
    _out, _err, code = git(
        ["merge-base", "--is-ancestor", base, "FETCH_HEAD"], chemin
    )
    if code == 1:
        return None, True
    if code:
        return None, None
    out, _err, code = git(
        ["rev-list", "--count", f"{base}..FETCH_HEAD"], chemin
    )
    if code or not out.strip().isdigit():
        return None, False
    return int(out), False


def est_clone(chemin):
    """Vrai si `chemin` est la RACINE d'un dépôt git.

    Un dossier non cloné sous le checkout ERPLibre, lui-même un dépôt git,
    ferait sinon répondre git pour ERPLibre.
    """
    if not os.path.isdir(chemin):
        return False
    out, _err, code = git(["rev-parse", "--show-toplevel"], chemin)
    return code == 0 and os.path.realpath(out.strip()) == os.path.realpath(
        chemin
    )


def nos_commits_geles(forks, racine=REPO_ROOT):
    """[dict] — les commits que chaque fork porte entre sa base amont gelée
    et son commit gelé, lus dans son clone, sans réseau.

    Seuls entrent les constats d'`etat_forks` qui portent à la fois « gel »
    et « base_gelee », dans leur ordre. Chaque ligne donne « chemin »
    (relatif à `racine`), « dossier » (absolu), « base », « gel », « nos »,
    le compte de « base..gel » ou None, et « motif », None quand la plage
    s'ouvre, sinon ce qui l'en empêche : un clone absent, un commit gelé ou
    une base absent du magasin d'objets, une base qui n'est plus ancêtre du
    commit gelé dans l'historique du clone, un compte que git refuse. Un
    objet absent n'est jamais récupéré.
    """
    lignes = []
    for constat in forks:
        base, gel = constat.get("base_gelee"), constat.get("gel")
        if not base or not gel:
            continue
        dossier = os.path.join(racine, constat.get("chemin") or "")
        ligne = {
            "chemin": constat.get("chemin"),
            "dossier": dossier,
            "base": base,
            "gel": gel,
            "nos": None,
            "motif": None,
        }
        lignes.append(ligne)
        if not est_clone(dossier):
            ligne["motif"] = t("not cloned")
            continue
        # Le commit gelé d'abord : la base en est un ancêtre, donc un clone
        # en retard sur le gel manque des deux, et c'est la synchronisation
        # qui les ramène.
        _out, _err, code = git(
            ["cat-file", "-e", f"{gel}^{{commit}}"], dossier
        )
        if code:
            ligne["motif"] = t(
                "frozen commit absent from the clone: synchronize the repositories"
            )
            continue
        _out, _err, code = git(
            ["cat-file", "-e", f"{base}^{{commit}}"], dossier
        )
        if code:
            ligne["motif"] = t(
                "base absent from the clone: run the freeze with the upstream base"
            )
            continue
        # Un objet présent ne suffit pas : une frontière superficielle posée
        # entre les deux coupe l'historique, et « base..gel » compterait alors
        # une plage tronquée sans erreur.
        _out, _err, code = git(
            ["merge-base", "--is-ancestor", base, gel], dossier
        )
        if code:
            ligne["motif"] = t(
                "history cut between the base and the frozen commit"
                " (shallow clone)"
                if est_superficiel(dossier)
                else "the base is not an ancestor of the frozen commit"
            )
            continue
        out, _err, code = git(
            ["rev-list", "--count", f"{base}..{gel}"], dossier
        )
        if code or not out.strip().isdigit():
            ligne["motif"] = t("git could not count the commits")
            continue
        ligne["nos"] = int(out)
    return lignes


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
    """Le verdict d'un fork, enrichi sur place.

    Un amont déclaré passe par son remote nommé : `preparer_remote` le pose
    s'il manque, puis le fetch avance « refs/remotes/<remote>/<branche> »
    et FETCH_HEAD. C'est tout ce qui s'écrit, et seulement après les refus
    qui précèdent (absent du disque, sans branche amont, superficiel) : un
    clone superficiel ne reçoit ni remote ni fetch. Un amont deviné se
    récupère par l'URL, sans remote.

    « cible » est la référence de l'amont récupéré, « <remote>/<branche> »
    ou FETCH_HEAD, celle que `repo_apply.appliquer` rebase ; « cible_sha »
    est le commit qu'elle désigne après le fetch et « head » celui de HEAD :
    les deux épinglent l'état montré, qu'une passe sans menu revérifie
    avant d'écrire. « remote_amont »
    est l'état que `preparer_remote` rend. Un remote homonyme à une autre
    URL rend le fork non comparable : « url_en_place » porte cette URL et
    « correction » la commande qui la remplace.
    """
    chemin = os.path.join(racine, constat["chemin"] or "")
    amont = constat["amont"]
    constat.update(
        {
            "verdict": "non_comparable",
            "motif": None,
            "cible": None,
            "cible_sha": None,
            "head": None,
            "remote_amont": None,
            "url_en_place": None,
            "correction": None,
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
            "amont_depuis_gel": None,
            "amont_reecrit": None,
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
    remote = remote_amont(amont)
    if remote:
        etat, en_place = preparer_remote(chemin, amont, delai)
        constat["remote_amont"] = etat
        if etat == "autre_url":
            constat["motif"] = t("upstream remote points to another URL")
            constat["url_en_place"] = en_place
            constat["correction"] = commande_set_url(
                constat["chemin"], remote, amont["url"]
            )
            return constat
        if etat == "non_clone":
            constat["motif"] = t("not cloned")
            return constat
        if etat == "refuse":
            constat["motif"] = t("the upstream remote could not be added")
            return constat
        cible = f"{remote}/{amont['branche']}"
    else:
        cible = "FETCH_HEAD"
    if not recuperer_amont(
        chemin, amont["url"], amont["branche"], delai, remote=remote
    ):
        constat["motif"] = t("upstream unreachable")
        return constat
    constat["cible"] = cible
    constat["cible_sha"] = commit_de(chemin, cible)
    constat["head"] = commit_de(chemin, "HEAD")
    if constat.get("base_gelee"):
        constat["amont_depuis_gel"], constat["amont_reecrit"] = depuis_le_gel(
            chemin, constat["base_gelee"]
        )

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


def ajouter_remote(constat, racine=REPO_ROOT, delai=DELAI_GIT):
    """Pose et récupère le remote amont nommé d'un fork. Rend un dict.

    « issue » vaut :
      non_declare   l'amont n'a pas de remote nommé ; « motif » dit pourquoi
      absent        aucun clone à ce chemin (« non_clone »)
      autre_url     le remote vise une autre URL (« url_en_place ») : rien
                    n'est touché, « commande » la corrige
      refuse        git a refusé d'ajouter le remote
      superficiel   le remote est posé mais le fetch est SAUTÉ : récupérer
                    l'amont complet dans un clone superficiel rapatrierait
                    tout son historique. « commande » le fait à la profondeur
                    du manifeste, ou PROFONDEUR_MANUELLE ; c'est le seul
                    fetch de ce remote qui garde le clone superficiel
      fetch_echoue  le remote est posé, l'amont n'a pas répondu
      ajoute        remote posé, amont récupéré dans « cible »
      present       remote déjà là à la même URL, amont récupéré

    « remote_ajoute » dit si le remote vient d'être posé, quelle que soit
    l'issue du fetch.
    """
    amont = constat.get("amont") or {}
    remote = remote_amont(amont)
    chemin = os.path.join(racine, constat.get("chemin") or "")
    res = {
        "chemin": constat.get("chemin"),
        "remote": amont.get("remote"),
        "url": amont.get("url"),
        "branche": amont.get("branche"),
        "issue": "non_declare",
        "motif": None,
        "remote_ajoute": False,
        "url_en_place": None,
        "cible": None,
        "commande": None,
    }
    if not remote:
        res["motif"] = motif_sans_remote(amont)
        return res
    etat, en_place = preparer_remote(chemin, amont, delai)
    res["remote_ajoute"] = etat == "ajoute"
    if etat in ("autre_url", "refuse", "non_clone"):
        res["issue"] = "absent" if etat == "non_clone" else etat
        res["url_en_place"] = en_place
        if etat == "autre_url":
            res["commande"] = commande_set_url(
                res["chemin"], remote, amont["url"]
            )
        return res
    if est_superficiel(chemin):
        res["issue"] = "superficiel"
        res["commande"] = commande_fetch_superficiel(
            res["chemin"], remote, amont["branche"], constat.get("clone_depth")
        )
        return res
    if not recuperer_amont(
        chemin, amont["url"], amont["branche"], delai, remote=remote
    ):
        res["issue"] = "fetch_echoue"
        return res
    res["issue"] = etat
    res["cible"] = f"{remote}/{amont['branche']}"
    return res


def ajouter_remotes(
    version,
    dossier=DOSSIER,
    racine=REPO_ROOT,
    parallele=PARALLELE,
    delai=DELAI_GIT,
):
    """`ajouter_remote` sur chaque fork d'une version, en parallèle.

    Les forks sont ceux de la passe à sec, dans le même ordre, et aucun
    n'est diagnostiqué : seuls le remote et sa branche de suivi s'écrivent.
    """
    lst = etat_forks(version, dossier, verifier=False)
    with ThreadPoolExecutor(max_workers=parallele) as pool:
        return list(pool.map(lambda c: ajouter_remote(c, racine, delai), lst))


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
            if x.get("base_gelee"):
                cible += f" · {t('frozen base')} {x['base_gelee'][:12]}"
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


def ligne_gel(constat):
    """(texte, genre) de l'écart à la base amont gelée, ou None sans base.

    Un amont réécrit se signale en rouge : la base gelée n'est plus dans
    son historique, et un rebase depuis elle ne vaut plus rien.
    """
    base = constat.get("base_gelee")
    if not base:
        return None
    if constat.get("amont_reecrit"):
        return (
            f"{t('upstream rewritten since the freeze')} ({base[:12]})",
            "broken",
        )
    if constat.get("amont_depuis_gel") is None:
        return None
    return (
        f"{constat['amont_depuis_gel']}"
        f" {t('upstream commits since the freeze')} ({base[:12]})",
        "dim",
    )


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
            gel = ligne_gel(x)
            if gel:
                out.append(paint(f"        ↳ {gel[0]}", gel[1], colour))
            if x.get("correction"):
                out.append(
                    paint(
                        f"        ↳ {x.get('url_en_place')}", "watch", colour
                    )
                )
                out.append(
                    paint(f"        $ {x['correction']}", "dim", colour)
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
    ajoutes = len([x for x in lst if x.get("remote_amont") == "ajoute"])
    out.append(
        paint(
            f"  {t('Upstream remotes added:')} {ajoutes} · "
            f"{t('no local branch moved, no work tree touched')}",
            "ok",
            colour,
        )
    )
    return "\n".join(out)


# L'ordre du rapport des remotes : ce qui demande un geste d'abord, ce qui
# est fait ensuite, les forks sautés en dernier.
ISSUES_REMOTE = (
    "autre_url",
    "refuse",
    "fetch_echoue",
    "superficiel",
    "absent",
    "ajoute",
    "present",
    "non_declare",
)
_ISSUES_TITRE = {
    "autre_url": t("Remote with another URL, left untouched"),
    "refuse": t("Remote refused by git"),
    "fetch_echoue": t("Remote set, upstream unreachable"),
    "superficiel": t("Shallow clone: remote set, fetch skipped"),
    "absent": t("Not cloned"),
    "ajoute": t("Remote added and fetched"),
    "present": t("Remote already present, fetched"),
    "non_declare": t("Skipped: upstream not declared"),
}
_ISSUES_GENRE = {
    "autre_url": "broken",
    "refuse": "broken",
    "fetch_echoue": "broken",
    "superficiel": "watch",
    "absent": "dim",
    "ajoute": "ok",
    "present": "ok",
    "non_declare": "dim",
}


def render_remotes(lst, version, colour=True):
    """Le rapport d'`ajouter_remotes`, groupé par issue.

    Chaque fork est NOMMÉ, les sautés compris, avec ce qui l'a fait
    sauter : un fork absent de la liste ne dirait pas s'il a été oublié.
    """
    out = [
        paint(
            f"🌐 {t('Upstream remotes')} — Odoo {version} — "
            f"{len(lst)} {t('forks')}",
            "step",
            colour,
        ),
        "─" * 62,
    ]
    for issue in ISSUES_REMOTE:
        groupe = [x for x in lst if x["issue"] == issue]
        if not groupe:
            continue
        titre = f"  {_ISSUES_TITRE[issue]} ({len(groupe)})"
        out.append(paint(titre, _ISSUES_GENRE[issue], colour))
        for x in groupe:
            out.append(f"    {x['chemin']}")
            if issue == "non_declare":
                out.append(paint(f"        → {x['motif']}", "dim", colour))
                continue
            vise = f"{x['remote']} {x['url']} @ {x['branche']}"
            out.append(paint(f"        → {vise}", "dim", colour))
            if x.get("url_en_place"):
                out.append(
                    paint(f"        ↳ {x['url_en_place']}", "watch", colour)
                )
            if x.get("commande"):
                out.append(paint(f"        $ {x['commande']}", "dim", colour))
            if issue == "superficiel":
                note = t("only this command keeps the clone shallow")
                out.append(paint(f"          {note}", "dim", colour))
    out.append("─" * 62)
    prets = len([x for x in lst if x["cible"]])
    out.append(
        f"  {t('Upstream fetched')} {prets} · "
        f"{t('Upstream remotes added:')} "
        f"{len([x for x in lst if x['remote_ajoute']])}"
    )
    return "\n".join(out)


def _main_remotes_toutes_versions(args):
    """`--add-remotes --all-versions` : chaque version installée, croissante.

    Sort 2 sans aucune version, 1 dès qu'un fork d'une version a échoué.
    """
    import json

    versions = versions_installees(dossier=args.manifest_dir)
    if not versions:
        print(f"❌ {t('No Odoo version found')}", file=sys.stderr)
        return 2
    par_version = [
        (version, ajouter_remotes(version, args.manifest_dir))
        for version in versions
    ]
    if args.json:
        print(
            json.dumps(
                {
                    "versions": [
                        {"version": version, "remotes": lst}
                        for version, lst in par_version
                    ]
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        colour = sys.stdout.isatty() and not args.no_color
        print(
            "\n\n".join(
                render_remotes(lst, version, colour)
                for version, lst in par_version
            )
        )
    echecs = ("autre_url", "refuse", "fetch_echoue")
    return (
        1
        if any(
            x["issue"] in echecs for _version, lst in par_version for x in lst
        )
        else 0
    )


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
    parser.add_argument(
        "--add-remotes",
        action="store_true",
        help=t(
            "add and fetch the named upstream remote of each fork (network)"
        ),
    )
    parser.add_argument(
        "--all-versions",
        action="store_true",
        help=t(
            "with --add-remotes: every Odoo version of the checkout, not only"
            " the active one"
        ),
    )
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--no-color", action="store_true")
    args = parser.parse_args(argv)

    if args.add_remotes and args.all_versions:
        return _main_remotes_toutes_versions(args)

    version = args.version or version_active()
    if not version:
        print(f"❌ {t('No Odoo version found')}", file=sys.stderr)
        return 2
    if not fichiers_manifeste(version, args.manifest_dir):
        print(f"❌ {args.manifest_dir} : {version}", file=sys.stderr)
        return 2

    if args.add_remotes:
        lst = ajouter_remotes(version, args.manifest_dir)
        if args.json:
            print(
                json.dumps(
                    {"version": version, "remotes": lst},
                    indent=2,
                    ensure_ascii=False,
                )
            )
        else:
            colour = sys.stdout.isatty() and not args.no_color
            print(render_remotes(lst, version, colour))
        echecs = ("autre_url", "refuse", "fetch_echoue")
        return 1 if any(x["issue"] in echecs for x in lst) else 0

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
