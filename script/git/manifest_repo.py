#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les dépôts des manifestes d'Odoo : en ajouter un, le forker pour une
organisation, y créer une branche, poser son remote amont, lister et
ouvrir des pull requests.

Ce module fait le travail sans rien demander ; le menu Répertoire git de
TODO pose les questions et l'appelle, et la ligne de commande fait de même
sans menu :

    manifest_repo.py add URL --version 18.0 [--branch B] [--freeze|--no-freeze]
    manifest_repo.py fork CHEMIN --organisation ORG [--version 18.0]
                     [--upstream origine|fork] [--all-branches]
                     [--manifest 17.0,18.0 | --no-manifest]
    manifest_repo.py branch CHEMIN NOM [--from REF] [--push REMOTE]
    manifest_repo.py branches NOM CHEMIN... [--from REF] [--push]
    manifest_repo.py upstream CHEMIN [--version 18.0]
    manifest_repo.py remove CHEMIN [--version 18.0] [--apply]
    manifest_repo.py sync CHEMIN [--version 18.0]
    manifest_repo.py refreeze CHEMIN [--commit SHA] [--version 18.0]
    manifest_repo.py pulls --organisation ORG [--version 18.0]
    manifest_repo.py mine [--author LOGIN] [--all-repos]
    manifest_repo.py fork-sync [CHEMIN...] [--version 18.0]
    manifest_repo.py token [--organisation ORG]
    manifest_repo.py prune CHEMIN [--fetch] [--github] [--apply] [--remote]
    manifest_repo.py pr CHEMIN --title T [--body B] [--target amont|manifeste]
                     [--draft]

CHEMIN est le « path » du projet dans le manifeste, ou la fin de ce chemin
(« OCA_server-tools »). Le jeton GitHub du fork est EL_GITHUB_TOKEN.

Un dépôt ajouté reçoit le remote de son organisation (repris s'il existe
déjà vers la même URL), le chemin odoo<version>/addons/<organisation>_<dépôt>
et la branche demandée, la version d'Odoo par défaut ; il est gelé sur la
tête de cette branche quand le manifeste est gelé. Une branche absente de
l'hôte, ou un dépôt déjà dans le manifeste, est refusé avant d'écrire.
"""

import argparse
import os
import re
import subprocess
import sys
from xml.sax.saxutils import quoteattr

sys.path.append(
    os.path.normpath(os.path.join(os.path.dirname(__file__), "..", ".."))
)

from script.git import github_fork, manifest_fork  # noqa: E402
from script.git import manifest_freeze, repo_upgrade  # noqa: E402

MANIFESTE = re.compile(r"git_manifest_odoo(\d+\.\d+)\.xml$")
DELAI_GIT = 120


def dossier_manifestes(dossier=None):
    return dossier or repo_upgrade.DOSSIER


def versions_des_manifestes(dossier=None):
    """Les versions d'Odoo qui ont un manifeste, triées."""
    try:
        noms = os.listdir(dossier_manifestes(dossier))
    except OSError:
        return []
    trouvees = {m.group(1) for n in noms if (m := MANIFESTE.match(n))}
    return sorted(trouvees, key=lambda v: [int(x) for x in v.split(".")])


def url_du_projet(projet, remotes):
    """L'URL d'où le projet se clone : fetch de son remote + son nom."""
    return repo_upgrade.url_amont(
        remotes.get(projet.get("remote")), projet.get("name")
    )


def projets_github(version, dossier=None):
    """(remotes, [(projet, propriétaire, dépôt)]) des projets de `version`
    hébergés sur GitHub, triés par chemin."""
    remotes, projets = repo_upgrade.lire_manifestes(
        version, dossier_manifestes(dossier)
    )
    res = []
    for projet in projets.values():
        depot = github_fork.depot_github(url_du_projet(projet, remotes))
        if depot:
            res.append((projet, *depot))
    res.sort(key=lambda r: r[0].get("path", ""))
    return remotes, res


def versions_du_depot(proprietaire, depot, dossier=None):
    """{version: (remotes, projet)} des versions dont un manifeste clone
    proprietaire/depot. Le premier projet trouvé par version compte."""
    res = {}
    for version in versions_des_manifestes(dossier):
        remotes, liste = projets_github(version, dossier)
        for projet, p, d in liste:
            if (p.lower(), d.lower()) == (proprietaire.lower(), depot.lower()):
                res[version] = (remotes, projet)
                break
    return res


def fichier_du_projet(version, name, path, dossier=None):
    """Le fichier de manifeste de `version` qui déclare name+path, ou None."""
    for chemin in repo_upgrade.fichiers_manifeste(
        version, dossier_manifestes(dossier)
    ):
        with open(chemin, encoding="utf-8") as fh:
            texte = fh.read()
        for _d, _f, attrs in manifest_freeze.iter_projects(texte):
            if attrs.get("name") == name and attrs.get("path") == path:
                return chemin
    return None


def branche_du_projet(projet):
    return manifest_freeze.manifest_branch(
        projet.get("revision"),
        projet.get("upstream"),
        projet.get("dest-branch"),
    )


def trouver_projet(version, chemin, dossier=None):
    """(remotes, projet) dont le path est `chemin`, ou se termine par
    « /chemin » ; ValueError si aucun ou plusieurs."""
    remotes, projets = repo_upgrade.lire_manifestes(
        version, dossier_manifestes(dossier)
    )
    cible = chemin.strip("/")
    trouves = [
        p
        for p in projets.values()
        if p.get("path") == cible or p.get("path", "").endswith("/" + cible)
    ]
    if len(trouves) != 1:
        raise ValueError(
            f"{chemin} : {len(trouves)} projet(s) dans le manifeste {version}"
        )
    return remotes, trouves[0]


# ── Ajouter un dépôt ───────────────────────────────────────────────────


def tete(url, branche, delai=repo_upgrade.DELAI_RESEAU):
    """Le commit de tête de `branche` sur l'hôte, ou None."""
    try:
        res = subprocess.run(
            ["git", "ls-remote", "--heads", url, f"refs/heads/{branche}"],
            capture_output=True,
            text=True,
            timeout=delai,
            env=repo_upgrade.env_sans_invite(),
        )
    except (OSError, subprocess.SubprocessError):
        return None
    morceaux = res.stdout.split()
    return morceaux[0] if res.returncode == 0 and morceaux else None


def est_gele(texte):
    """Vrai si la plupart des projets du fichier portent un commit gelé."""
    attrs = [a for _d, _f, a in manifest_freeze.iter_projects(texte)]
    geles = sum(1 for a in attrs if a.get(manifest_freeze.FREEZE_ATTR))
    return bool(attrs) and geles * 2 > len(attrs)


def plan_ajout(url, version, branche, remotes):
    """Le projet à déclarer pour `url` : {name, path, remote, fetch,
    nouveau_remote, revision, groups}. ValueError hors de GitHub.

    Le remote repris est un remote simple vers la même organisation — la
    casse du propriétaire ne compte pas chez GitHub —, celui qui porte son
    nom d'abord ; jamais un remote « _origin_ », qui ferait passer le dépôt
    pour le fork d'un autre. Le chemin prend la casse de ce remote."""
    depot = github_fork.depot_github(url)
    if not depot:
        raise ValueError(f"{url} : pas une URL GitHub")
    proprietaire, nom = depot
    fetch = manifest_fork.fetch_github(proprietaire)
    candidats = [
        n
        for n, f in remotes.items()
        if "_origin_" not in n
        and (f or "").rstrip("/").lower() == fetch.rstrip("/").lower()
    ]
    existant = next(
        (n for n in candidats if n.lower() == proprietaire.lower()),
        candidats[0] if candidats else None,
    )
    if existant:
        fetch = remotes[existant]
        proprietaire = fetch.rstrip("/").rsplit("/", 1)[-1] or proprietaire
    remote = existant or proprietaire
    homonyme = next((n for n in remotes if n.lower() == remote.lower()), None)
    if not existant and homonyme:
        raise ValueError(
            f"remote {homonyme} déjà déclaré vers {remotes[homonyme]}"
        )
    return {
        "name": f"{nom}.git",
        "path": f"odoo{version}/addons/{proprietaire}_{nom}",
        "remote": remote,
        "fetch": fetch,
        "nouveau_remote": existant is None,
        "revision": branche,
        "groups": f"addons,odoo{version}",
    }


def inserer_projet(texte, plan, gel=None):
    """Déclare le projet de `plan` (et son remote s'il est nouveau) dans
    `texte`, avant le premier projet dont le chemin vient après le sien,
    un attribut par ligne comme les autres."""
    # Déclaré dans CE fichier même s'il l'est dans le _dev ou l'extra de la
    # version, qui ne se fusionnent pas toujours ; sans effet s'il y est.
    texte = manifest_fork.ajouter_remote(texte, plan["remote"], plan["fetch"])
    attrs = [("name", plan["name"]), ("revision", plan["revision"])]
    if gel:
        attrs.append((manifest_freeze.FREEZE_ATTR, gel))
    attrs += [
        ("path", plan["path"]),
        ("remote", plan["remote"]),
        ("groups", plan["groups"]),
    ]
    # quoteattr échappe « & », « < » et le guillemet, qu'un nom de branche
    # peut porter : sans lui le manifeste ne se relirait plus.
    lignes = (
        ["    <project"]
        + [f"        {cle}={quoteattr(valeur)}" for cle, valeur in attrs]
        + ["    />"]
    )
    bloc = "\n".join(lignes) + "\n"
    position = None
    for debut, _fin, attrs in manifest_freeze.iter_projects(texte):
        if attrs.get("path", "").lower() > plan["path"].lower():
            position = texte.rfind("\n", 0, debut) + 1
            break
    if position is None:
        position = texte.rindex("</manifest>")
    return texte[:position] + bloc + texte[position:]


def depot_deja_present(depot, version, dossier=None):
    """Vrai si un projet de `version` clone proprietaire/dépôt, ou en est
    un fork : son amont déclaré ou deviné vise ce dépôt."""
    cible = (depot[0].lower(), depot[1].lower())
    remotes, projets = repo_upgrade.lire_manifestes(
        version, dossier_manifestes(dossier)
    )
    for projet in projets.values():
        urls = [url_du_projet(projet, remotes)]
        amont = repo_upgrade.resoudre_amont(projet, remotes)
        if amont:
            urls.append(amont.get("url"))
        for u in urls:
            trouve = github_fork.depot_github(u or "")
            if trouve and (trouve[0].lower(), trouve[1].lower()) == cible:
                return True
    return False


def ajouter_depot(url, version, branche=None, geler=None, dossier=None):
    """Ajoute `url` au manifeste principal de `version`. Rend (fichier,
    plan, gel). Refuse, sans rien écrire, un dépôt déjà présent, une
    branche absente de l'hôte ou un hôte injoignable."""
    dossier = dossier_manifestes(dossier)
    branche = branche or version
    fichier = os.path.join(dossier, f"git_manifest_odoo{version}.xml")
    if not os.path.isfile(fichier):
        raise ValueError(f"pas de manifeste pour Odoo {version}")
    remotes, liste = projets_github(version, dossier)
    depot = github_fork.depot_github(url)
    if depot and depot_deja_present(depot, version, dossier):
        raise ValueError(
            f"{depot[0]}/{depot[1]} est déjà dans le manifeste {version}"
        )
    plan = plan_ajout(url, version, branche, remotes)
    _r, projets = repo_upgrade.lire_manifestes(version, dossier)
    if any(p.get("path") == plan["path"] for p in projets.values()):
        raise ValueError(
            f"{plan['path']} est déjà dans le manifeste {version}"
        )
    disponibles = repo_upgrade.branches(url)
    if disponibles is None:
        raise ValueError(f"{url} injoignable")
    if branche not in disponibles:
        proches = ", ".join(sorted(disponibles)[:12]) or "-"
        raise ValueError(f"branche {branche} absente ; présentes : {proches}")
    with open(fichier, encoding="utf-8") as fh:
        texte = fh.read()
    if geler is None:
        geler = est_gele(texte)
    gel = tete(url, branche) if geler else None
    if geler and not gel:
        raise ValueError(f"tête de {branche} illisible sur {url}")
    neuf = inserer_projet(texte, plan, gel)
    with open(fichier, "w", encoding="utf-8") as fh:
        fh.write(neuf)
    return fichier, plan, gel


# ── Forker pour une organisation ───────────────────────────────────────


def creer_branche_active(client, nom_complet, proprietaire, depot, projet):
    """Pose dans le fork la branche que suit `projet`, sur son commit gelé,
    ou sur la tête de la source s'il n'est pas gelé. Rend (branche, sha)
    posés, ou None si rien n'était à faire."""
    branche = branche_du_projet(projet)
    if not branche or client.branche(nom_complet, branche):
        return None
    sha = projet.get(manifest_freeze.FREEZE_ATTR) or client.branche(
        f"{proprietaire}/{depot}", branche
    )
    if not sha:
        raise github_fork.ErreurGitHub(
            f"branche {branche} absente de la source"
        )
    client.creer_branche(nom_complet, branche, sha)
    return branche, sha


def forker(
    client, proprietaire, depot, organisation, toutes, projet, attendre=True
):
    """Fork proprietaire/depot dans `organisation` et, si seule la branche
    active est copiée, l'y pose. Rend (fork, créé, branche posée).
    Refuse l'organisation qui possède déjà le dépôt : GitHub rendrait le
    dépôt lui-même, et le manifeste le prendrait pour son propre fork."""
    if organisation.lower() == proprietaire.lower():
        raise ValueError(
            f"{proprietaire}/{depot} appartient déjà à {organisation}"
        )
    fork, cree = client.forker(proprietaire, depot, organisation, toutes)
    if cree and attendre and not client.attendre(fork["full_name"]):
        raise github_fork.ErreurGitHub(f"{fork['full_name']} : fork pas prêt")
    posee = None
    if not toutes:
        posee = creer_branche_active(
            client, fork["full_name"], proprietaire, depot, projet
        )
    return fork, cree, posee


def prendre_le_fork(
    client,
    fork,
    proprietaire,
    depot,
    organisation,
    mode,
    versions,
    toutes,
    dossier=None,
):
    """Fait prendre le fork aux manifestes de `versions`. Rend [(version,
    fichier changé ou None, erreur ou None)]."""
    par_version = versions_du_depot(proprietaire, depot, dossier)
    res = []
    for version in versions:
        if version not in par_version:
            res.append((version, None, "absent du manifeste"))
            continue
        remotes, projet = par_version[version]
        try:
            if not toutes:
                creer_branche_active(
                    client, fork["full_name"], proprietaire, depot, projet
                )
            changement = manifest_fork.plan(
                projet, remotes, organisation, mode, fork.get("name")
            )
            chemin = fichier_du_projet(
                version, projet.get("name"), projet.get("path"), dossier
            )
            if not chemin:
                raise ValueError("projet introuvable dans les fichiers")
            with open(chemin, encoding="utf-8") as fh:
                texte = fh.read()
            neuf, trouve = manifest_fork.appliquer(
                texte, projet.get("name"), projet.get("path"), changement
            )
        except (github_fork.ErreurGitHub, ValueError) as exc:
            res.append((version, None, str(exc)))
            continue
        if trouve and neuf != texte:
            with open(chemin, "w", encoding="utf-8") as fh:
                fh.write(neuf)
            res.append((version, chemin, None))
        else:
            res.append((version, None, None))
    return res


# ── Branche et remote amont d'un clone ─────────────────────────────────


def git(chemin, *args):
    """(code, sortie) de « git -C chemin args »."""
    try:
        res = subprocess.run(
            ["git", "-C", chemin, *args],
            capture_output=True,
            text=True,
            timeout=DELAI_GIT,
            env=repo_upgrade.env_sans_invite(),
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    return res.returncode, (res.stdout + res.stderr).strip()


def remotes_du_clone(chemin):
    code, sortie = git(chemin, "remote")
    return sortie.split() if code == 0 else []


def brancher(chemin, nom, depart=None, pousser=None):
    """Crée la branche `nom` dans le clone `chemin`, depuis `depart` (HEAD
    par défaut), et s'y place ; la pousse vers le remote `pousser` en la
    faisant suivre, si donné. Rend [(étape, code, sortie)] ; s'arrête à la
    première étape en échec. Un nom que git refuse l'est avant tout."""
    code, sortie = git(chemin, "check-ref-format", "--branch", nom)
    if code:
        return [("nom", code, sortie or f"nom de branche invalide : {nom}")]
    args = ["switch", "-c", nom] + ([depart] if depart else [])
    etapes = [("branche", *git(chemin, *args))]
    if etapes[-1][1] == 0 and pousser:
        etapes.append(("push", *git(chemin, "push", "-u", pousser, nom)))
    return etapes


def brancher_plusieurs(depots, nom, depart=None, pousser=False, jobs=None):
    """Crée la branche `nom` dans chaque clone de `depots` ([(chemin,
    remote)]), en parallèle ; la pousse vers ce remote — celui que git-repo
    donne au projet — si `pousser`. Rend, dans l'ordre de `depots`,
    [(chemin, étapes de brancher())]. Un échec dans un clone n'arrête pas
    les autres."""
    from concurrent.futures import ThreadPoolExecutor

    def un(depot):
        chemin, remote = depot
        return chemin, brancher(
            chemin, nom, depart, remote if pousser else None
        )

    with ThreadPoolExecutor(max_workers=jobs or os.cpu_count() or 4) as ex:
        return list(ex.map(un, depots))


def ajouter_amont(chemin, projet, remotes):
    """Pose dans le clone le remote amont que le manifeste déclare pour
    `projet`, puis récupère sa branche. Rend (état, détail) : état vaut
    « ajoute » ou « present » quand le remote est en place et récupéré,
    sinon la raison (voir repo_upgrade.preparer_remote)."""
    amont = repo_upgrade.resoudre_amont(projet, remotes)
    remote = repo_upgrade.remote_amont(amont)
    if not remote:
        return None, repo_upgrade.motif_sans_remote(amont)
    etat, url = repo_upgrade.preparer_remote(chemin, amont)
    if etat == "autre_url":
        return etat, (
            f"{repo_upgrade.LIBELLES_APPROFONDIR['autre_url']} ({url}) :"
            f" {repo_upgrade.commande_set_url(chemin, remote, amont['url'])}"
        )
    if etat not in ("ajoute", "present"):
        return etat, repo_upgrade.LIBELLES_APPROFONDIR.get(etat, etat)
    # Un clone superficiel ne reçoit de l'amont que la même profondeur :
    # sans borne, le fetch rapatrierait tout l'historique amont.
    profondeur = None
    if repo_upgrade.est_superficiel(chemin):
        profondeur = (
            projet.get("clone-depth") or repo_upgrade.PROFONDEUR_MANUELLE
        )
    ok = repo_upgrade.recuperer_amont(
        chemin,
        amont["url"],
        amont["branche"],
        profondeur=profondeur,
        remote=remote,
    )
    return (
        (etat, f"{remote}/{amont['branche']}")
        if ok
        else ("fetch", amont["url"])
    )


# ── Branches fusionnées ────────────────────────────────────────────────

# Les branches de version et les branches principales ne sont jamais
# proposées au nettoyage, fusionnées ou non.
PROTEGEES = re.compile(r"^(\d+\.\d+|master|main|develop|HEAD)$")


def bases_du_clone(chemin, projet, remotes):
    """Les références distantes où une branche du clone est fusionnée :
    la branche du manifeste sur le remote du projet, et la branche amont
    d'un fork quand son remote est posé. Seules celles que le clone
    connaît sont rendues."""
    refs = []
    branche = branche_du_projet(projet)
    if branche and projet.get("remote"):
        refs.append(f"{projet['remote']}/{branche}")
    amont = repo_upgrade.resoudre_amont(projet, remotes)
    remote = repo_upgrade.remote_amont(amont)
    if remote and amont.get("branche"):
        refs.append(f"{remote}/{amont['branche']}")
    return [
        r
        for r in dict.fromkeys(refs)
        if git(chemin, "rev-parse", "--verify", "-q", f"refs/remotes/{r}")[0]
        == 0
    ]


def remotes_de_fork(chemin, projet, remotes):
    """Les remotes du clone où l'on pousse ses branches : tous, sauf le
    remote d'un projet qui n'est pas un fork et l'amont déclaré d'un fork,
    dont les branches appartiennent à d'autres."""
    exclus = set()
    if not repo_upgrade.est_fork(projet):
        exclus.add(projet.get("remote"))
    amont = repo_upgrade.remote_amont(
        repo_upgrade.resoudre_amont(projet, remotes)
    )
    if amont:
        exclus.add(amont)
    return [r for r in remotes_du_clone(chemin) if r not in exclus]


def _fusionnees(chemin, bases, *args):
    """Les noms courts des références que `git branch <args> --merged`
    rend pour au moins une des `bases`."""
    noms = set()
    for base in bases:
        code, sortie = git(
            chemin,
            "branch",
            *args,
            "--merged",
            base,
            "--format=%(refname:short)",
        )
        if code:
            raise ValueError(sortie)
        noms.update(sortie.split())
    return noms


def branches_du_clone(chemin, forks):
    """({branche locale}, {remote: {branche}}) du clone, hors branches
    protégées et branche courante ; les remotes sont ceux de `forks`."""
    _code, courante = git(chemin, "branch", "--show-current")

    def garder(nom):
        return nom != courante and not PROTEGEES.match(nom)

    _code, sortie = git(chemin, "branch", "--format=%(refname:short)")
    locales = {b for b in sortie.split() if garder(b)}
    distantes = {}
    for remote in forks:
        _code, sortie = git(
            chemin,
            "branch",
            "-r",
            "--list",
            f"{remote}/*",
            "--format=%(refname:short)",
        )
        distantes[remote] = {
            b.split("/", 1)[1]
            for b in sortie.split()
            if "/" in b and garder(b.split("/", 1)[1])
        }
    return locales, distantes


def branches_a_nettoyer(chemin, bases, forks, fusion_github=None):
    """Les branches à proposer au nettoyage : {"locales": {nom: motif},
    "distantes": {remote: {nom: motif}}}. Le motif vaut « fusion » quand
    la branche est contenue dans une des `bases`, ou celui que rend
    `fusion_github(nom)` (une PR fusionnée par squash, que git ne voit
    pas) ; une branche sans motif n'est pas proposée."""
    locales, distantes = branches_du_clone(chemin, forks)
    fusion_locale = _fusionnees(chemin, bases)
    fusion_distante = _fusionnees(chemin, bases, "-r")
    motifs = {}

    def motif(nom, fusionnee):
        if fusionnee:
            return "fusion"
        if fusion_github is None:
            return None
        if nom not in motifs:
            motifs[nom] = fusion_github(nom)
        return motifs[nom]

    res = {"locales": {}, "distantes": {}}
    for nom in sorted(locales):
        m = motif(nom, nom in fusion_locale)
        if m:
            res["locales"][nom] = m
    for remote, noms in distantes.items():
        trouves = {}
        for nom in sorted(noms):
            m = motif(nom, f"{remote}/{nom}" in fusion_distante)
            if m:
                trouves[nom] = m
        if trouves:
            res["distantes"][remote] = trouves
    return res


def fusion_par_github(client, tetes, cibles):
    """La fonction `fusion_github` de branches_a_nettoyer() : pour une
    branche, « PR #n » si une pull request fermée de l'un des
    propriétaires `tetes` vers l'un des dépôts `cibles` a été fusionnée,
    sinon None. Un dépôt invisible ne compte pas."""

    def chercher(nom):
        for cible in cibles:
            for proprietaire in tetes:
                for pr in client.pull_requests_de(
                    cible, f"{proprietaire}:{nom}"
                ):
                    if pr.get("merged_at"):
                        return f"PR #{pr.get('number')}"
        return None

    return chercher


def supprimer_branches(chemin, locales=(), distantes=None):
    """Supprime les branches locales `locales` et, pour chaque remote de
    `distantes`, ses branches sur le serveur. La suppression locale est
    forcée (-D) : `git branch -d` juge la fusion contre HEAD ou la branche
    suivie, pas contre la base du manifeste que branches_a_nettoyer() a
    vérifiée, ni contre une PR fusionnée par squash.
    Rend [(remote ou None, nom, code, sortie)]."""
    res = []
    for nom in locales:
        res.append((None, nom, *git(chemin, "branch", "-D", nom)))
    for remote, noms in (distantes or {}).items():
        for nom in noms:
            res.append(
                (remote, nom, *git(chemin, "push", remote, "--delete", nom))
            )
    return res


def plan_nettoyage(chemin, projet, remotes, client=None, fetch=False):
    """(bases, forks, candidats) du clone `chemin` : voir bases_du_clone,
    remotes_de_fork et branches_a_nettoyer. `fetch` rafraîchit d'abord
    les remotes en jeu ; `client` ajoute la recherche des pull requests
    fusionnées par squash, des propriétaires des forks vers le dépôt du
    manifeste, l'amont déclaré et les forks eux-mêmes."""
    forks = remotes_de_fork(chemin, projet, remotes)
    if fetch:
        amont = repo_upgrade.remote_amont(
            repo_upgrade.resoudre_amont(projet, remotes)
        )
        presents = remotes_du_clone(chemin)
        rafraichir(
            chemin,
            [
                r
                for r in dict.fromkeys([projet.get("remote"), amont, *forks])
                if r in presents
            ],
        )
    bases = bases_du_clone(chemin, projet, remotes)
    if not bases:
        return bases, forks, {"locales": {}, "distantes": {}}
    fusion_github = None
    if client is not None:
        tetes, cibles = [], [
            n for n, _b in cibles_pull_request(projet, remotes).values()
        ]
        for remote in forks:
            code, url = git(chemin, "remote", "get-url", remote)
            depot = github_fork.depot_github(url) if not code else None
            if depot:
                tetes.append(depot[0])
                cibles.append("/".join(depot))
        fusion_github = fusion_par_github(
            client, list(dict.fromkeys(tetes)), list(dict.fromkeys(cibles))
        )
    return (
        bases,
        forks,
        branches_a_nettoyer(chemin, bases, forks, fusion_github),
    )


def rafraichir(chemin, remotes):
    """`git fetch --prune` de chaque remote : une branche supprimée sur le
    serveur ne reste pas proposée. Rend [(remote, code, sortie)]."""
    return [(r, *git(chemin, "fetch", "--prune", r)) for r in remotes]


# ── Mettre un fork à jour depuis son amont ─────────────────────────────


def forks_du_manifeste(version, dossier=None):
    """Les forks GitHub que les manifestes de `version` clonent :
    [(chemin, fork « propriétaire/dépôt », branche, amont « propriétaire/
    dépôt » ou None, branche amont ou None)], triés par chemin."""
    remotes, liste = projets_github(version, dossier)
    res = []
    for projet, proprietaire, depot in liste:
        if not repo_upgrade.est_fork(projet):
            continue
        amont = repo_upgrade.resoudre_amont(projet, remotes) or {}
        depot_amont = github_fork.depot_github(amont.get("url"))
        res.append(
            (
                projet.get("path"),
                f"{proprietaire}/{depot}",
                branche_du_projet(projet),
                "/".join(depot_amont) if depot_amont else None,
                amont.get("branche"),
            )
        )
    return res


ETATS_SYNCHRO = {
    "fast-forward": "avance",
    "merge": "fusion",
    "none": "a_jour",
}


def synchroniser_un_fork(client, fork, branche, amont, branche_amont):
    """Met la `branche` du `fork` à jour depuis son parent GitHub. GitHub
    fusionne la branche du MÊME nom chez le PARENT du fork : l'appel n'est
    fait que si ce parent est l'amont déclaré et sa branche la même, sans
    quoi le fork recevrait un autre code que celui que le manifeste dit
    suivre. Rend (état, détail) ; état parmi « avance », « fusion »,
    « a_jour », « conflit », « refus », « ignore »."""
    if not branche:
        return "ignore", "pas de branche dans le manifeste"
    if not amont or not branche_amont:
        return "ignore", "pas d'amont déclaré pour cette version"
    if branche_amont != branche:
        return "ignore", f"branche amont {branche_amont} ≠ {branche}"
    infos = client.depot(*fork.split("/", 1))
    if infos is None:
        return "ignore", "fork introuvable sur GitHub"
    parent = (infos.get("parent") or {}).get("full_name", "")
    if parent.lower() != amont.lower():
        return "ignore", f"parent GitHub {parent or '-'} ≠ amont {amont}"
    code, corps = client.synchroniser_fork(fork, branche)
    message = corps.get("message", "")
    if code == 409:
        return "conflit", message
    if code == 422:
        return "refus", message
    return ETATS_SYNCHRO.get(corps.get("merge_type"), "avance"), message


def synchroniser_forks(client, forks, jobs=8):
    """synchroniser_un_fork() sur chaque entrée de forks_du_manifeste(), en
    parallèle. Une erreur d'API sur un fork devient son état « erreur » et
    n'arrête pas les autres. Rend [(entrée, état, détail)] dans l'ordre."""
    from concurrent.futures import ThreadPoolExecutor

    def un(entree):
        try:
            return (entree, *synchroniser_un_fork(client, *entree[1:]))
        except github_fork.ErreurGitHub as exc:
            return entree, "erreur", str(exc)

    with ThreadPoolExecutor(max_workers=jobs) as ex:
        return list(ex.map(un, forks))


# ── Pull requests ──────────────────────────────────────────────────────


def lister_pull_requests(client, organisation, version, dossier=None, jobs=8):
    """Les pull requests ouvertes de chaque dépôt des manifestes de
    `version` dans `organisation` : [(chemin, nom complet, [pr] ou None)],
    None quand l'organisation n'a pas ce dépôt. Les dépôts se lisent en
    parallèle : l'API répond à chacun en une requête."""
    from concurrent.futures import ThreadPoolExecutor

    _remotes, liste = projets_github(version, dossier)
    vus, cibles = set(), []
    for projet, _proprietaire, depot in liste:
        nom = f"{organisation}/{depot}"
        if nom.lower() not in vus:
            vus.add(nom.lower())
            cibles.append((projet.get("path"), nom))
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        prs = list(ex.map(lambda c: client.pull_requests(c[1]), cibles))
    return [(chemin, nom, lot) for (chemin, nom), lot in zip(cibles, prs)]


ECHECS_CI = {
    "failure",
    "error",
    "cancelled",
    "timed_out",
    "action_required",
    "startup_failure",
}


def etat_ci(statut, checks):
    """« echec », « en_cours », « succes » ou None (aucune CI) à partir du
    statut combiné et des check-runs d'un commit. Un seul échec l'emporte,
    puis une vérification non terminée ; un statut combiné sans aucun
    statut déclaré ne compte pas."""
    etats = []
    if statut and statut.get("total_count"):
        etats.append(statut.get("state"))
    for check in checks or []:
        if check.get("status") != "completed":
            etats.append("pending")
        else:
            etats.append(check.get("conclusion"))
    if any(e in ECHECS_CI for e in etats):
        return "echec"
    if "pending" in etats:
        return "en_cours"
    return "succes" if etats else None


def etat_revue(avis):
    """« changements », « approuvee » ou None d'après la DERNIÈRE revue
    décisive de chaque relecteur : un commentaire ne retire pas une
    approbation, une approbation retire une demande de changements."""
    dernier = {}
    for revue in avis or []:
        etat = revue.get("state")
        if etat in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            dernier[(revue.get("user") or {}).get("login")] = etat
    if "CHANGES_REQUESTED" in dernier.values():
        return "changements"
    if "APPROVED" in dernier.values():
        return "approuvee"
    return None


def depots_des_manifestes(version, dossier=None):
    """Les « propriétaire/dépôt », en minuscules, que les manifestes de
    `version` clonent, avec l'amont déclaré de chaque fork : c'est là
    qu'une pull request sur ces dépôts est ouverte."""
    remotes, liste = projets_github(version, dossier)
    res = set()
    for projet, proprietaire, depot in liste:
        res.add(f"{proprietaire}/{depot}".lower())
        for nom, _base in cibles_pull_request(projet, remotes).values():
            res.add(nom.lower())
    return res


def statut_pull_requests(client, auteur, depots=None, jobs=8):
    """L'état des pull requests de `auteur`, restreintes aux dépôts de
    l'ensemble `depots` (minuscules) s'il est donné. Rend une liste de
    dicts {depot, numero, titre, url, etat, revue, ci} ; `etat` vaut
    « fusionnee », « fermee », « brouillon » ou « ouverte ». Revue et CI
    ne sont lues que pour une pull request ouverte, en parallèle."""
    from concurrent.futures import ThreadPoolExecutor

    res = []
    for item in client.mes_pull_requests(auteur):
        depot = item.get("repository_url", "").split("/repos/", 1)[-1]
        if depots is not None and depot.lower() not in depots:
            continue
        if (item.get("pull_request") or {}).get("merged_at"):
            etat = "fusionnee"
        elif item.get("state") == "closed":
            etat = "fermee"
        else:
            etat = "brouillon" if item.get("draft") else "ouverte"
        res.append(
            {
                "depot": depot,
                "numero": item.get("number"),
                "titre": item.get("title", ""),
                "url": item.get("html_url", ""),
                "etat": etat,
                "revue": None,
                "ci": None,
            }
        )

    def detail(pr):
        numero = pr["numero"]
        sha = (client.pull_request(pr["depot"], numero).get("head") or {}).get(
            "sha"
        )
        pr["revue"] = etat_revue(client.avis(pr["depot"], numero))
        if sha:
            pr["ci"] = etat_ci(*client.verifications(pr["depot"], sha))

    ouvertes = [p for p in res if p["etat"] in ("ouverte", "brouillon")]
    with ThreadPoolExecutor(max_workers=jobs) as ex:
        list(ex.map(detail, ouvertes))
    return res


def branche_poussee(chemin):
    """(branche courante, remote suivi, branche distante) du clone, ou
    None hors branche ou sans branche suivie."""
    code, branche = git(chemin, "branch", "--show-current")
    if code or not branche:
        return None
    code, suivie = git(chemin, "rev-parse", "--abbrev-ref", "@{u}")
    if code or "/" not in suivie:
        return None
    remote, distante = suivie.split("/", 1)
    return branche, remote, distante


def cibles_pull_request(projet, remotes):
    """Les dépôts où ouvrir la pull request : {clé: (propriétaire/dépôt,
    branche de base)}. « manifeste » est le dépôt que le manifeste clone,
    vers sa branche ; « amont » l'amont déclaré d'un fork, vers sa branche
    amont, quand il y en a un."""
    res = {}
    depot = github_fork.depot_github(url_du_projet(projet, remotes))
    branche = branche_du_projet(projet)
    if depot and branche:
        res["manifeste"] = ("/".join(depot), branche)
    amont = repo_upgrade.resoudre_amont(projet, remotes)
    if amont and amont.get("branche"):
        depot_amont = github_fork.depot_github(amont.get("url"))
        if depot_amont:
            res["amont"] = ("/".join(depot_amont), amont["branche"])
    return res


def ouvrir_pull_request(
    client, chemin, cible, base, titre, corps="", brouillon=False
):
    """Ouvre, sur le dépôt `cible` vers `base`, la pull request de la
    branche courante du clone `chemin`, telle que poussée vers son remote
    suivi. Refuse une branche non suivie, un remote hors de GitHub, ou une
    branche identique à la base sur le même dépôt."""
    poussee = branche_poussee(chemin)
    if not poussee:
        raise ValueError(
            "branche courante non poussée (pas de branche suivie)"
        )
    _branche, remote, distante = poussee
    code, url = git(chemin, "remote", "get-url", remote)
    tete = github_fork.depot_github(url) if not code else None
    if not tete:
        raise ValueError(f"remote {remote} hors de GitHub")
    if "/".join(tete).lower() == cible.lower() and distante == base:
        raise ValueError(f"{distante} est déjà la branche de base")
    return client.creer_pull_request(
        cible, f"{tete[0]}:{distante}", base, titre, corps, brouillon
    )


def resume_commits(chemin, base_ref, limite=20):
    """(sujet du dernier commit, liste « - sujet » des commits depuis
    `base_ref`) : le titre et le corps proposés pour une pull request."""
    _c, sujet = git(chemin, "log", "-1", "--format=%s")
    code, sujets = git(
        chemin,
        "log",
        f"--max-count={limite}",
        "--format=- %s",
        f"{base_ref}..HEAD",
    )
    return sujet, (sujets if not code else "")


# ── Retirer, synchroniser, regeler ─────────────────────────────────────


MANIFESTE_LOCAL = os.path.join(
    ".repo", "local_manifests", "erplibre_manifest.xml"
)


def _bloc(texte, debut, fin):
    """Les bornes de la ligne entière d'une balise : de son retrait au saut
    de ligne qui la suit."""
    a = texte.rfind("\n", 0, debut) + 1
    b = texte.find("\n", fin)
    return a, (len(texte) if b < 0 else b + 1)


def remote_utilise(texte, nom):
    """Vrai si un projet du fichier clone par `nom`, le nomme comme amont,
    ou si le <default> le désigne."""
    for _d, _f, attrs in manifest_freeze.iter_projects(texte):
        if nom in (attrs.get("remote"), attrs.get("fork-upstream-remote")):
            return True
    defaut = re.search(r"<default\b[^>]*\bremote=\"([^\"]*)\"", texte)
    return bool(defaut and defaut.group(1) == nom)


def retirer_remote(texte, nom):
    """Le texte sans la déclaration du remote `nom` (ligne entière)."""
    for m in manifest_fork._hors_commentaires(texte, manifest_fork._REMOTE):
        if dict(manifest_fork._ATTRS.findall(m.group(0))).get("name") == nom:
            a, b = _bloc(texte, m.start(), m.end())
            return texte[:a] + texte[b:]
    return texte


def retirer_projet(texte, name, path):
    """(texte sans le <project> name+path, remote retiré ou None). Le
    remote part avec lui quand plus rien du fichier ne l'emploie."""
    for debut, fin, attrs in manifest_freeze.iter_projects(texte):
        if attrs.get("name") != name or attrs.get("path") != path:
            continue
        a, b = _bloc(texte, debut, fin)
        texte = texte[:a] + texte[b:]
        remote = attrs.get("remote")
        if remote and not remote_utilise(texte, remote):
            return retirer_remote(texte, remote), remote
        return texte, None
    raise ValueError(f"{path} absent du fichier")


def retirer_depot(version, chemin, dossier=None):
    """Retire le projet `chemin` du manifeste de `version` qui le déclare.
    Rend (fichier, projet, remote retiré ou None)."""
    _remotes, projet = trouver_projet(version, chemin, dossier)
    fichier = fichier_du_projet(
        version, projet.get("name"), projet.get("path"), dossier
    )
    if not fichier:
        raise ValueError(f"{chemin} : projet introuvable dans les fichiers")
    with open(fichier, encoding="utf-8") as fh:
        texte = fh.read()
    neuf, remote = retirer_projet(texte, projet["name"], projet["path"])
    with open(fichier, "w", encoding="utf-8") as fh:
        fh.write(neuf)
    return fichier, projet, remote


def mode_gele(racine):
    """Vrai si la dernière reconfiguration a posé les commits gelés : le
    manifeste local porte alors des commits dans « revision »."""
    try:
        with open(
            os.path.join(racine, MANIFESTE_LOCAL), encoding="utf-8"
        ) as fh:
            texte = fh.read()
    except OSError:
        return False
    return any(
        manifest_freeze.is_sha(a.get("revision"))
        for _d, _f, a in manifest_freeze.iter_projects(texte)
    )


def commandes_synchro(racine, chemin=None, gel=None, local=False):
    """Les commandes qui régénèrent le manifeste local, dans le mode du
    checkout (gelé ou non, sauf `gel` donné), puis synchronisent `chemin`
    seul, ou tout le checkout sans `chemin`. `local` synchronise sans
    réseau : c'est ce qui suffit à retirer le clone d'un projet ôté du
    manifeste, repo effaçant lui-même un clone obsolète resté propre."""
    gel = mode_gele(racine) if gel is None else gel
    fusion = [
        ".venv.erplibre/bin/python",
        "script/git/git_merge_repo_manifest.py",
        "--output",
        MANIFESTE_LOCAL,
        "--with_OCA",
    ] + (["--freeze"] if gel else [])
    synchro = [".venv.erplibre/bin/repo", "sync", "-c"]
    if local:
        synchro.append("-l")
    synchro += [chemin] if chemin else [f"-j{os.cpu_count() or 4}"]
    return [fusion, synchro]


def executer(commandes, racine):
    """Lance `commandes` dans `racine`, sortie au terminal ; s'arrête au
    premier échec. Rend le code de sortie."""
    for args in commandes:
        code = subprocess.call(args, cwd=racine)
        if code:
            return code
    return 0


def regeler(version, chemin, racine, sha=None, dossier=None):
    """Pose le commit gelé du projet `chemin` sur `sha` (HEAD de son clone
    par défaut) et, pour un fork à l'amont déclaré, recalcule sa base
    amont. Rend {fichier, sha, base, motif, pousse} : `pousse` faux quand
    aucun remote du clone ne porte ce commit — un gel que personne d'autre
    ne pourrait récupérer."""
    from script.git import git_freeze_manifest

    remotes, projet = trouver_projet(version, chemin, dossier)
    clone = os.path.join(racine, projet["path"])
    code, sortie = git(
        clone, "rev-parse", "--verify", f"{sha or 'HEAD'}^{{commit}}"
    )
    if code:
        raise ValueError(
            f"{sha or 'HEAD'} : commit introuvable dans {projet['path']}"
        )
    sha = sortie.split()[-1]
    _c, distantes = git(clone, "branch", "-r", "--contains", sha)
    amont = repo_upgrade.resoudre_amont(projet, remotes)
    base, motif = None, None
    if amont:
        constat = git_freeze_manifest.base_amont(clone, sha, amont)
        base, motif = constat.get("base"), constat.get("motif")
    fichier = fichier_du_projet(
        version, projet["name"], projet["path"], dossier
    )
    with open(fichier, encoding="utf-8") as fh:
        texte = fh.read()
    cle = manifest_freeze.project_key(projet["name"], projet["path"])
    neuf, _changees = manifest_freeze.rewrite(
        texte, freeze={cle: sha}, upstream={cle: base}
    )
    with open(fichier, "w", encoding="utf-8") as fh:
        fh.write(neuf)
    return {
        "fichier": fichier,
        "sha": sha,
        "base": base,
        "motif": motif,
        "pousse": bool(distantes.strip()),
    }


# ── Ligne de commande ──────────────────────────────────────────────────


def _racine():
    return os.path.normpath(
        os.path.join(os.path.dirname(__file__), "..", "..")
    )


def _client(racine):
    """Le client GitHub du jeton EL_GITHUB_TOKEN, ou None (dit pourquoi)."""
    jeton = github_fork.jeton(racine)
    if not jeton:
        print("EL_GITHUB_TOKEN missing", file=sys.stderr)
        return None
    return github_fork.ClientGitHub(jeton)


def main(argv=None):
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    sous = parser.add_subparsers(dest="commande", required=True)
    p = sous.add_parser("add", help="add a GitHub repository to a manifest")
    p.add_argument("url")
    p.add_argument("--version")
    p.add_argument("--branch")
    gel = p.add_mutually_exclusive_group()
    gel.add_argument(
        "--freeze", dest="geler", action="store_true", default=None
    )
    gel.add_argument("--no-freeze", dest="geler", action="store_false")
    p = sous.add_parser("fork", help="fork a manifest repository")
    p.add_argument("chemin")
    p.add_argument("--organisation", required=True)
    p.add_argument("--version")
    p.add_argument(
        "--upstream",
        choices=(manifest_fork.AMONT_ORIGINE, manifest_fork.AMONT_FORK),
        default=manifest_fork.AMONT_ORIGINE,
    )
    p.add_argument("--all-branches", action="store_true")
    man = p.add_mutually_exclusive_group()
    man.add_argument("--manifest", help="versions, separated by commas")
    man.add_argument("--no-manifest", action="store_true")
    p = sous.add_parser(
        "branch", help="create a branch in a cloned repository"
    )
    p.add_argument("chemin")
    p.add_argument("nom")
    p.add_argument("--from", dest="depart")
    p.add_argument("--push", metavar="REMOTE")
    p.add_argument("--version")
    p = sous.add_parser(
        "branches", help="create one branch in several cloned repositories"
    )
    p.add_argument("nom")
    p.add_argument("chemins", nargs="+")
    p.add_argument("--from", dest="depart")
    p.add_argument(
        "--push", action="store_true", help="push to the project's remote"
    )
    p.add_argument("--version")
    p = sous.add_parser("upstream", help="add and fetch the upstream remote")
    p.add_argument("chemin")
    p.add_argument("--version")
    p = sous.add_parser("remove", help="remove a repository from a manifest")
    p.add_argument("chemin")
    p.add_argument("--version")
    p.add_argument(
        "--apply",
        action="store_true",
        help="regenerate the local manifest; repo then deletes a clean clone",
    )
    p = sous.add_parser(
        "sync", help="regenerate the local manifest, sync one repo"
    )
    p.add_argument("chemin")
    p.add_argument("--version")
    p = sous.add_parser("refreeze", help="freeze one repository on a commit")
    p.add_argument("chemin")
    p.add_argument("--commit", help="default: HEAD of the clone")
    p.add_argument("--version")
    p = sous.add_parser("pulls", help="list the open pull requests")
    p.add_argument("--organisation", required=True)
    p.add_argument("--version")
    p = sous.add_parser(
        "mine", help="status of my pull requests: review, CI, merged"
    )
    p.add_argument("--author", help="default: the account of the token")
    p.add_argument(
        "--all-repos",
        action="store_true",
        help="do not restrict to the repositories of the manifests",
    )
    p.add_argument("--version")
    p = sous.add_parser("token", help="check the scopes of the GitHub token")
    p.add_argument("--organisation", help="also check the membership")
    p.add_argument("--version")
    p = sous.add_parser(
        "fork-sync",
        help="update forks from their upstream on GitHub (merge-upstream)",
    )
    p.add_argument("chemins", nargs="*", help="default: every fork")
    p.add_argument("--version")
    p = sous.add_parser(
        "prune", help="list, then delete, the merged branches of a clone"
    )
    p.add_argument("chemin")
    p.add_argument("--fetch", action="store_true", help="fetch --prune first")
    p.add_argument(
        "--github",
        action="store_true",
        help="also ask GitHub for pull requests merged by squash",
    )
    p.add_argument(
        "--apply", action="store_true", help="delete the local branches"
    )
    p.add_argument(
        "--remote",
        action="store_true",
        help="with --apply, also delete them on the fork remotes",
    )
    p.add_argument("--version")
    p = sous.add_parser(
        "pr", help="open a pull request from the current branch"
    )
    p.add_argument("chemin")
    p.add_argument("--title", required=True)
    p.add_argument("--body", default="")
    p.add_argument("--target", choices=("manifeste", "amont"), default="amont")
    p.add_argument("--draft", action="store_true")
    p.add_argument("--version")
    args = parser.parse_args(argv)
    racine = _racine()
    version = args.version or repo_upgrade.version_active(racine)
    if not version:
        print("no Odoo version", file=sys.stderr)
        return 2
    try:
        if args.commande == "add":
            fichier, plan, gel = ajouter_depot(
                args.url, version, args.branch, args.geler
            )
            print(
                f"{os.path.relpath(fichier, racine)} : {plan['path']}"
                f" ({plan['remote']}, {plan['revision']}"
                f"{', ' + gel[:12] if gel else ''})"
            )
            return 0
        if args.commande == "pulls":
            client = _client(racine)
            if not client:
                return 2
            total = absents = 0
            for chemin_p, nom, lot in lister_pull_requests(
                client, args.organisation, version
            ):
                if lot is None:
                    absents += 1
                    continue
                for pr in lot:
                    total += 1
                    print(
                        f"{nom}#{pr.get('number')} {pr.get('title')} — {pr.get('html_url')}"
                    )
            print(f"{total} pull request(s); {absents} repositories not found")
            return 0
        if args.commande == "token":
            client = _client(racine)
            if not client:
                return 2
            rapport = github_fork.verifier_jeton(client, args.organisation)
            portees = rapport["portees"]
            print(
                f"account: {rapport['login'] or '-'} · scopes:"
                f" {', '.join(portees) if portees is not None else '-'}"
                f" · role: {rapport['role'] or '-'}"
            )
            for code in rapport["codes"]:
                grave = code in github_fork.PROBLEMES_JETON
                print(
                    f"{'error' if grave else 'warning'}:"
                    f" {github_fork.TEXTES_JETON[code]}"
                )
            return int(
                bool(set(rapport["codes"]) & github_fork.PROBLEMES_JETON)
            )
        if args.commande == "fork-sync":
            client = _client(racine)
            if not client:
                return 2
            forks = forks_du_manifeste(version)
            if args.chemins:
                voulus = {
                    trouver_projet(version, c)[1]["path"] for c in args.chemins
                }
                forks = [f for f in forks if f[0] in voulus]
            code_final = 0
            for entree, etat, detail in synchroniser_forks(client, forks):
                print(f"{etat:<8} {entree[1]} {entree[2]} {detail}")
                if etat in ("conflit", "refus", "erreur"):
                    code_final = 1
            return code_final
        if args.commande == "prune":
            remotes, projet = trouver_projet(version, args.chemin)
            chemin = os.path.join(racine, projet["path"])
            client = _client(racine) if args.github else None
            if args.github and not client:
                return 2
            bases, _forks, plan = plan_nettoyage(
                chemin, projet, remotes, client, args.fetch
            )
            if not bases:
                print(f"{projet['path']}: no base branch known to the clone")
                return 1
            print(f"base: {', '.join(bases)}")
            for nom, motif in plan["locales"].items():
                print(f"local  {nom} ({motif})")
            for remote, noms in plan["distantes"].items():
                for nom, motif in noms.items():
                    print(f"{remote}  {nom} ({motif})")
            if not args.apply:
                return 0
            code_final = 0
            for remote, nom, code, sortie in supprimer_branches(
                chemin,
                plan["locales"],
                plan["distantes"] if args.remote else None,
            ):
                print(
                    f"{'✓' if code == 0 else '❌'} {remote or 'local'} {nom}"
                )
                if code:
                    print(f"  {sortie}")
                    code_final = 1
            return code_final
        if args.commande == "mine":
            client = _client(racine)
            if not client:
                return 2
            depots = None if args.all_repos else depots_des_manifestes(version)
            for pr in statut_pull_requests(
                client, args.author or client.utilisateur(), depots
            ):
                details = " ".join(
                    f"{cle}={pr[cle]}" for cle in ("revue", "ci") if pr[cle]
                )
                print(
                    f"{pr['etat']:<10} {pr['depot']}#{pr['numero']}"
                    f" {pr['titre']} {details} — {pr['url']}"
                )
            return 0
        if args.commande == "branches":
            depots = []
            for c in args.chemins:
                _r, p = trouver_projet(version, c)
                depots.append(
                    (os.path.join(racine, p["path"]), p.get("remote"))
                )
            code = 0
            for chemin_c, etapes in brancher_plusieurs(
                depots, args.nom, args.depart, args.push
            ):
                for etape, c, sortie in etapes:
                    code = code or c
                    print(
                        f"{os.path.relpath(chemin_c, racine)} · {etape} : {'ok' if not c else sortie}"
                    )
            return 1 if code else 0
        if args.commande == "remove":
            fichier, projet, remote = retirer_depot(version, args.chemin)
            print(
                f"{os.path.relpath(fichier, racine)} : {projet['path']}"
                f"{' + remote ' + remote if remote else ''}"
            )
            if args.apply:
                return executer(commandes_synchro(racine, local=True), racine)
            return 0
        remotes, projet = trouver_projet(version, args.chemin)
        chemin = os.path.join(racine, projet["path"])
        if args.commande == "sync":
            return executer(commandes_synchro(racine, projet["path"]), racine)
        if args.commande == "refreeze":
            res = regeler(version, args.chemin, racine, args.commit)
            print(
                f"{os.path.relpath(res['fichier'], racine)} : {res['sha'][:12]}"
                f" · base {res['base'][:12] if res['base'] else res['motif'] or '-'}"
            )
            if not res["pousse"]:
                print("warning: no remote of the clone holds this commit")
            return 0
        if args.commande == "pr":
            cibles = cibles_pull_request(projet, remotes)
            if args.target not in cibles:
                raise ValueError(
                    f"no {args.target} target for {projet['path']}"
                )
            client = _client(racine)
            if not client:
                return 2
            pr = ouvrir_pull_request(
                client,
                chemin,
                *cibles[args.target],
                args.title,
                args.body,
                args.draft,
            )
            print(pr.get("html_url"))
            return 0
        if args.commande == "branch":
            etapes = brancher(chemin, args.nom, args.depart, args.push)
            for etape, code, sortie in etapes:
                print(f"{etape} : {'ok' if not code else sortie}")
            return 1 if any(code for _e, code, _s in etapes) else 0
        if args.commande == "upstream":
            etat, detail = ajouter_amont(chemin, projet, remotes)
            print(f"{etat} : {detail}")
            return 0 if etat in ("ajoute", "present") else 1
        depot = github_fork.depot_github(url_du_projet(projet, remotes))
        if not depot:
            raise ValueError(f"{projet['path']} n'est pas sur GitHub")
        client = _client(racine)
        if not client:
            return 2
        fork, cree, posee = forker(
            client, *depot, args.organisation, args.all_branches, projet
        )
        print(f"{'created' if cree else 'present'} : {fork.get('html_url')}")
        if posee:
            print(f"branch {posee[0]} @ {posee[1][:12]}")
        if args.no_manifest:
            return 0
        versions = [v for v in (args.manifest or version).split(",") if v]
        code = 0
        for v, fichier, erreur in prendre_le_fork(
            client,
            fork,
            *depot,
            args.organisation,
            args.upstream,
            versions,
            args.all_branches,
        ):
            if erreur:
                code = 1
            print(
                f"{v} : {erreur or (os.path.relpath(fichier, racine) if fichier else 'unchanged')}"
            )
        return code
    except (ValueError, github_fork.ErreurGitHub) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
