#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Retirer une version d'Odoo du checkout, ou toutes.

Ce que retire une version V
---------------------------
- l'arbre « odoo<V>/ » ;
- ses venvs « .venv.odoo<V>_python* » ;
- ses dépôts git-repo « .repo/projects/odoo<V>/ » ;
- sa ligne de « .repo/installed_odoo_version.txt » et son entrée de
  « .erplibre-state.json ». Le manifeste local est régénéré sans elle : il
  fusionne les manifestes de chaque version installée, et le prochain
  « repo sync » reclonerait l'arbre retiré ;
- les stockages d'objets « .repo/project-objects/* » qu'aucun dépôt restant
  n'utilise plus.

Le Python de pyenv d'une version retirée n'est que signalé, quand plus
aucune version installée ne le déclare : d'autres projets de la machine
peuvent s'en servir.

La version active (« .odoo-version ») n'est retirée que par --all, qui
retire toutes les versions ; « make install_odoo_<V> » reclone ensuite.

Nettoyage en place d'un stockage partagé
----------------------------------------
git-repo fait partager un même stockage d'objets aux dépôts d'un même projet
amont, toutes versions confondues (« objects » y est un lien). Retirer les
dépôts d'une version ne rend donc rien tant qu'un dépôt restant garde des
références vers son historique : le clone du cœur d'Odoo d'une version porte
souvent les branches de toutes les autres. Pour chaque stockage qu'un dépôt
retiré utilisait et qu'un dépôt restant utilise encore :

1. les dépôts restants sous « .repo/projects/odoo* » perdent leurs
   références de versions non installées (voir `version_de_ref`) ; la
   branche extraite et « refs/remotes/m/* » restent ; leur reflog expire
   aux délais par défaut de git ;
2. l'ensemble à garder est l'union, dépôt par dépôt, de « rev-list
   --objects --all --reflog --indexed-objects » : chaque dépôt garde sa
   propre frontière de clone superficiel. Un « git gc » lancé depuis un
   seul dépôt effacerait les objets dont un autre a encore besoin ;
3. « pack-objects » écrit ces objets dans un pack neuf ; les anciens packs
   sont mis de côté, chaque objet gardé est relu, puis les anciens packs
   sont effacés — remis en place si un objet manque. Un objet isolé
   (« loose ») que le pack neuf contient part ; les autres restent, comme
   un « git gc » les laisse avant leur délai.

Un stockage à clone partiel (« .promisor »), à « alternates », dont un
dépôt porte un verrou git, dont le pack neuf ne tient pas dans l'espace
libre, ou dont le gain reste sous SEUIL_GAIN, est laissé tel quel. Aucune
autre commande git ne doit tourner sur le checkout pendant le nettoyage.

Travail non sauvegardé
----------------------
Avant d'effacer, chaque dépôt de la version est lu : arbre modifié (fichiers
non suivis compris), commits qu'aucun remote ne contient — lus dans le dépôt
git-repo, même quand l'arbre n'existe plus —, stash ; puis tout fichier de
« odoo<V>/ » hors d'un dépôt. Cette liste s'affiche, et seul le mot
MOT_CONFIRMATION tapé dans un terminal laisse effacer ; --yes ne la saute
pas.

Codes de sortie : 0 fait, ou rien à faire ; 1 erreur pendant l'effacement ;
2 usage ; 3 refusé (version active, confirmation absente).
"""

import argparse
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

RACINE = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..")
)
sys.path.append(RACINE)

FICHIER_INSTALLEES = os.path.join(".repo", "installed_odoo_version.txt")
FICHIER_ETAT = ".erplibre-state.json"
FICHIER_VERSION = ".odoo-version"
FICHIER_SUPPORT = os.path.join("conf", "supported_version_erplibre.json")
MANIFESTE_LOCAL = os.path.join(
    ".repo", "local_manifests", "erplibre_manifest.xml"
)
PROJETS = os.path.join(".repo", "projects")
STOCKAGES = os.path.join(".repo", "project-objects")

# Sous ce gain, réécrire les packs d'un stockage coûte plus qu'il ne rend.
SEUIL_GAIN = 10 * 1024 * 1024
# Le pack neuf s'écrit avant que les anciens partent : l'espace libre doit
# couvrir sa taille estimée, avec cette marge.
MARGE_ESPACE = 1.2
MOT_CONFIRMATION = "effacer"
# Les stockages au plus grand gain que le plan détaille, les autres comptés.
AFFICHES = 10
VERROUS = (
    "index.lock",
    "HEAD.lock",
    "packed-refs.lock",
    "shallow.lock",
    "config.lock",
)
# La plus ancienne série d'Odoo : une branche « 2.0 » d'un dépôt tiers n'est
# pas une version d'Odoo.
VERSION_MIN = 5

EXIT_OK, EXIT_ERREUR, EXIT_USAGE, EXIT_REFUS = 0, 1, 2, 3

RE_VERSION = re.compile(r"^\d+\.\d+$")
# Le dernier segment d'une référence : « 16.0 », « 16.0_foo », « 16.0-mig »,
# « saas-16.3 », « tmp.16.0 », « staging.saas-16.2 ».
RE_VERSION_REF = re.compile(
    r"(?:^|/)(?:(?:staging|tmp)\.)?(?:saas-)?(\d+)\.\d+[^/]*$"
)


# ── lecture ───────────────────────────────────────────────────────────────


def version_de_ref(nom):
    """La série d'Odoo (entier) que nomme la référence `nom`, ou None."""
    m = RE_VERSION_REF.search(nom)
    if not m:
        return None
    serie = int(m.group(1))
    return serie if serie >= VERSION_MIN else None


def serie(version):
    """« 16.0 » -> 16."""
    return int(version.split(".")[0])


def lire_lignes(chemin):
    try:
        with open(chemin, encoding="utf-8") as fh:
            return [ligne.strip() for ligne in fh if ligne.strip()]
    except OSError:
        return []


def lire_installees(racine):
    """Les versions de « installed_odoo_version.txt » : ["18.0", …]."""
    return [
        ligne[len("odoo") :]
        for ligne in lire_lignes(os.path.join(racine, FICHIER_INSTALLEES))
        if ligne.startswith("odoo")
    ]


def lire_active(racine):
    lignes = lire_lignes(os.path.join(racine, FICHIER_VERSION))
    return lignes[0] if lignes else None


def pythons_par_version(racine):
    """{"16.0": "3.10.18", …} d'après conf/supported_version_erplibre.json."""
    try:
        with open(os.path.join(racine, FICHIER_SUPPORT)) as fh:
            donnees = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return {}
    return {
        v["odoo_version"]: v["python_version"]
        for v in donnees.values()
        if v.get("odoo_version") and v.get("python_version")
    }


def versions_connues(racine):
    """Toute version dont il reste une trace : arbre, venv, dépôts, liste."""
    connues = set(lire_installees(racine))
    for chemin in glob.glob(os.path.join(racine, "odoo*")):
        nom = os.path.basename(chemin)[len("odoo") :]
        if os.path.isdir(chemin) and RE_VERSION.match(nom):
            connues.add(nom)
    for chemin in glob.glob(os.path.join(racine, PROJETS, "odoo*")):
        nom = os.path.basename(chemin)[len("odoo") :]
        if RE_VERSION.match(nom):
            connues.add(nom)
    for chemin in glob.glob(os.path.join(racine, ".venv.odoo*_python*")):
        m = re.match(
            r"\.venv\.odoo(\d+\.\d+)_python", os.path.basename(chemin)
        )
        if m:
            connues.add(m.group(1))
    return sorted(connues, key=serie)


def taille(chemin):
    """Octets occupés sur le disque sous `chemin`, liens non suivis."""
    try:
        st = os.lstat(chemin)
    except OSError:
        return 0
    if not os.path.isdir(chemin) or os.path.islink(chemin):
        return st.st_blocks * 512
    total = 0
    for dossier, dossiers, fichiers in os.walk(chemin):
        for nom in dossiers + fichiers:
            try:
                total += os.lstat(os.path.join(dossier, nom)).st_blocks * 512
            except OSError:
                pass
    return total


def versions_choisies(reponse, choix):
    """Les versions de `choix` que désignent les numéros de `reponse`,
    séparés par des espaces, comptés à partir de 1, sans doublon et dans
    l'ordre de `choix`. Rend [] pour une réponse vide ou « 0 » (retour),
    None quand un numéro ne désigne rien."""
    mots = reponse.split()
    if not mots or mots == ["0"]:
        return []
    if not all(m.isdigit() and 0 < int(m) <= len(choix) for m in mots):
        return None
    retenus = {int(m) - 1 for m in mots}
    return [v for i, v in enumerate(choix) if i in retenus]


def humain(octets):
    for unite in ("o", "Kio", "Mio", "Gio"):
        if abs(octets) < 1024 or unite == "Gio":
            return f"{octets:.1f} {unite}" if unite != "o" else f"{octets} o"
        octets /= 1024
    return f"{octets:.1f} Gio"


def git(args, gitdir=None, cwd=None, entree=None):
    """(stdout, stderr, code) de git."""
    cmd = ["git"]
    if gitdir:
        cmd += ["--git-dir", gitdir]
    r = subprocess.run(
        cmd + args, cwd=cwd, input=entree, capture_output=True, text=True
    )
    return r.stdout, r.stderr, r.returncode


def depots_git(base):
    """Les dossiers git de git-repo sous `base` (« …/x.git » avec HEAD)."""
    trouves = []
    for dossier, dossiers, _fichiers in os.walk(base):
        if dossier.endswith(".git") and os.path.isfile(
            os.path.join(dossier, "HEAD")
        ):
            trouves.append(dossier)
            dossiers[:] = []
    return sorted(trouves)


def arbre_du_depot(racine, gitdir):
    """L'arbre de travail du dépôt git-repo `gitdir`."""
    relatif = os.path.relpath(gitdir, os.path.join(racine, PROJETS))
    return os.path.join(racine, relatif[: -len(".git")])


def stockage_du_depot(gitdir):
    """Le dossier « objects » réel du dépôt, ou None."""
    objets = os.path.join(gitdir, "objects")
    return os.path.realpath(objets) if os.path.isdir(objets) else None


def carte_des_stockages(racine):
    """{stockage: [dossiers git qui l'utilisent]} pour tout « .repo/projects »."""
    carte = {}
    for gitdir in depots_git(os.path.join(racine, PROJETS)):
        stockage = stockage_du_depot(gitdir)
        if stockage:
            carte.setdefault(stockage, []).append(gitdir)
    return carte


# ── travail non sauvegardé ────────────────────────────────────────────────


def non_sauve_du_depot(racine, gitdir):
    """Ce qui serait perdu avec ce dépôt : liste de textes courts."""
    pertes = []
    out, _err, code = git(
        ["rev-list", "--count", "HEAD", "--branches", "--not", "--remotes"],
        gitdir,
    )
    if code:
        out, _err, code = git(
            ["rev-list", "--count", "--branches", "--not", "--remotes"],
            gitdir,
        )
    if not code and out.strip() not in ("", "0"):
        pertes.append(f"{out.strip()} commit(s) absent(s) de tout remote")
    _out, _err, code = git(
        ["rev-parse", "-q", "--verify", "refs/stash"], gitdir
    )
    if not code:
        pertes.append("un stash")
    arbre = arbre_du_depot(racine, gitdir)
    if os.path.lexists(os.path.join(arbre, ".git")):
        # Sans --no-optional-locks, « status » réécrit l'index : un essai à
        # sec toucherait le dépôt qu'il ne fait que lire.
        out, _err, code = git(
            [
                "--no-optional-locks",
                "status",
                "--porcelain",
                "--untracked-files=normal",
            ],
            cwd=arbre,
        )
        if not code and out.strip():
            pertes.append(f"{len(out.splitlines())} fichier(s) modifié(s)")
    return pertes


def hors_depot(racine, version, arbres):
    """Les fichiers de « odoo<V>/ » qu'aucun dépôt ne contient.

    Rend [(chemin relatif, nombre de fichiers)] ; un dossier vide ne
    compte pas."""
    base = os.path.join(racine, f"odoo{version}")
    if not os.path.isdir(base):
        return []
    arbres = {os.path.normpath(a) for a in arbres}
    ancetres = set()
    for a in arbres:
        parent = os.path.dirname(a)
        while len(parent) >= len(base):
            ancetres.add(parent)
            parent = os.path.dirname(parent)
    trouves = []
    for dossier, dossiers, fichiers in os.walk(base):
        for nom in fichiers:
            trouves.append(
                (os.path.relpath(os.path.join(dossier, nom), racine), 1)
            )
        garder = []
        for nom in dossiers:
            chemin = os.path.join(dossier, nom)
            if chemin in arbres:
                continue
            if chemin in ancetres and not os.path.islink(chemin):
                garder.append(nom)
                continue
            n = sum(len(f) for _d, _s, f in os.walk(chemin))
            if os.path.islink(chemin) or n:
                trouves.append(
                    (os.path.relpath(chemin, racine) + "/", max(n, 1))
                )
        dossiers[:] = garder
    return trouves


# ── plan ──────────────────────────────────────────────────────────────────


def refs_a_retirer(gitdir, gardees):
    """Les références de `gitdir` d'une série d'Odoo absente de `gardees`.

    La branche extraite et « refs/remotes/m/* » (la révision du manifeste)
    restent toujours. Une référence symbolique dont la cible part, telle
    « refs/remotes/<remote>/HEAD » qui désigne la branche par défaut du
    remote, part avec elle : laissée, elle ne désignerait plus rien et git
    la signalerait à chaque commande."""
    out, _err, code = git(
        ["for-each-ref", "--format=%(refname) %(symref)"], gitdir
    )
    if code:
        return []
    extraite, _err, _code = git(["symbolic-ref", "-q", "HEAD"], gitdir)
    extraite = extraite.strip()
    retirer, symboliques = [], []
    for ligne in out.splitlines():
        ref, _, cible = ligne.partition(" ")
        if ref == extraite or ref.startswith("refs/remotes/m/"):
            continue
        if cible:
            symboliques.append((ref, cible))
            continue
        s = version_de_ref(ref)
        if s is not None and s not in gardees:
            retirer.append(ref)
    partantes = set(retirer)
    retirer += [ref for ref, cible in symboliques if cible in partantes]
    return retirer


def lister_objets(gitdirs, sortie, refs_exclues=None):
    """Écrit dans `sortie` les objets à garder, dépôt par dépôt (doublons
    compris : « pack-objects » les ignore). Rend None, ou le motif d'un
    échec.

    `refs_exclues` : {gitdir: [refs]} à ne pas compter, pour une estimation
    faite avant leur retrait."""
    refs_exclues = refs_exclues or {}
    with open(sortie, "w") as fh:
        for gitdir in gitdirs:
            exclues = set(refs_exclues.get(gitdir, ()))
            args = ["git", "--git-dir", gitdir, "rev-list", "--objects"]
            if exclues:
                out, _err, _code = git(
                    ["for-each-ref", "--format=%(refname)"], gitdir
                )
                tetes = [r for r in out.split() if r not in exclues] + ["HEAD"]
                entree = "\n".join(tetes) + "\n"
                args += ["--stdin"]
            else:
                entree = None
                args += ["--all"]
            args += ["--reflog"]
            if os.path.isfile(os.path.join(gitdir, "index")):
                args += ["--indexed-objects"]
            fh.flush()
            r = subprocess.run(
                args,
                input=entree,
                stdout=fh,
                stderr=subprocess.PIPE,
                text=True,
            )
            if r.returncode:
                return f"{gitdir}: {r.stderr.strip().splitlines()[-1:]}"
    return None


def ecrire_uniques(liste):
    """Écrit à côté de `liste` ses identifiants d'objets sans doublon ;
    rend le chemin écrit."""
    vus = set()
    uniques = liste + ".uniques"
    with open(liste) as entree, open(uniques, "w") as sortie:
        for ligne in entree:
            sha = ligne[:40]
            cle = bytes.fromhex(sha)
            if cle not in vus:
                vus.add(cle)
                sortie.write(sha + "\n")
    return uniques


def cat_file(gitdir, uniques, format_):
    """Les lignes de « cat-file --batch-check » pour chaque identifiant."""
    with open(uniques) as entree:
        r = subprocess.Popen(
            [
                "git",
                "--git-dir",
                gitdir,
                "cat-file",
                f"--batch-check={format_}",
            ],
            stdin=entree,
            stdout=subprocess.PIPE,
            text=True,
        )
        yield from r.stdout
        r.wait()


def taille_des_objets(gitdir, uniques):
    """Octets sur disque des objets de `uniques`."""
    total = 0
    for ligne in cat_file(gitdir, uniques, "%(objectsize:disk)"):
        mot = ligne.split()[0] if ligne.split() else ""
        if mot.isdigit():
            total += int(mot)
    return total


def manquants(gitdir, uniques):
    """Le nombre d'objets de `uniques` que le stockage n'a pas."""
    return sum(
        1
        for ligne in cat_file(gitdir, uniques, "%(objectname)")
        if ligne.rstrip().endswith(" missing")
    )


def motif_de_saut(stockage, gitdirs):
    """Pourquoi ne pas toucher à ce stockage, ou None."""
    pack = os.path.join(stockage, "pack")
    if glob.glob(os.path.join(pack, "*.promisor")):
        return "clone partiel"
    if os.path.isfile(os.path.join(stockage, "info", "alternates")):
        return "alternates"
    for gitdir in gitdirs:
        for verrou in VERROUS:
            if os.path.exists(os.path.join(gitdir, verrou)):
                return f"verrou {os.path.join(gitdir, verrou)}"
    return None


def planifier(racine, versions, tout, estimer=True):
    """Ce que retirerait la commande, sans rien toucher."""
    installees = lire_installees(racine)
    active = lire_active(racine)
    cibles = versions_connues(racine) if tout else sorted(versions, key=serie)
    restantes = [v for v in installees if v not in cibles]
    if active and active not in cibles and active not in restantes:
        restantes.append(active)
    gardees = {serie(v) for v in restantes}

    plan = {
        "versions": [],
        "restantes": restantes,
        "orphelins": [],
        "partages": [],
        "pyenv": [],
    }
    retires = set()
    for v in cibles:
        dossier_projets = os.path.join(racine, PROJETS, f"odoo{v}")
        gitdirs = depots_git(dossier_projets)
        retires.update(gitdirs)
        arbre = os.path.join(racine, f"odoo{v}")
        entree = {
            "version": v,
            "arbre": arbre if os.path.isdir(arbre) else None,
            "venvs": sorted(
                glob.glob(os.path.join(racine, f".venv.odoo{v}_python*"))
            ),
            "projets": (
                dossier_projets if os.path.isdir(dossier_projets) else None
            ),
            "installee": v in installees,
            "non_sauve": [],
        }
        for gitdir in gitdirs:
            for perte in non_sauve_du_depot(racine, gitdir):
                relatif = os.path.relpath(
                    arbre_du_depot(racine, gitdir), racine
                )
                entree["non_sauve"].append(f"{relatif} : {perte}")
        arbres = [arbre_du_depot(racine, g) for g in gitdirs]
        for chemin, n in hors_depot(racine, v, arbres):
            entree["non_sauve"].append(
                f"{chemin} : {n} fichier(s) hors de tout dépôt"
            )
        entree["taille"] = sum(
            taille(c)
            for c in [entree["arbre"], entree["projets"], *entree["venvs"]]
            if c
        )
        plan["versions"].append(entree)

    dossier_stockages = os.path.realpath(os.path.join(racine, STOCKAGES))
    for stockage, gitdirs in sorted(carte_des_stockages(racine).items()):
        # Un dépôt à « objects » propre part avec son dossier.
        if os.path.dirname(os.path.dirname(stockage)) != dossier_stockages:
            continue
        if not set(gitdirs) & retires:
            continue
        restants = [g for g in gitdirs if g not in retires]
        dossier = os.path.dirname(stockage)
        if not restants:
            plan["orphelins"].append(
                {"stockage": dossier, "taille": taille(dossier)}
            )
            continue
        projets_odoo = os.path.join(racine, PROJETS, "odoo")
        refs = {
            g: refs_a_retirer(g, gardees)
            for g in restants
            if g.startswith(projets_odoo)
        }
        partage = {
            "stockage": dossier,
            "objets": stockage,
            "restants": restants,
            "refs": {g: r for g, r in refs.items() if r},
            "avant": taille(stockage),
            "apres": None,
            "saut": motif_de_saut(stockage, restants),
        }
        if estimer and not partage["saut"]:
            with tempfile.TemporaryDirectory() as tmp:
                liste = os.path.join(tmp, "objets")
                echec = lister_objets(restants, liste, partage["refs"])
                if echec:
                    partage["saut"] = f"lecture impossible ({echec})"
                else:
                    partage["apres"] = taille_des_objets(
                        restants[0], ecrire_uniques(liste)
                    )
        plan["partages"].append(partage)

    pythons = pythons_par_version(racine)
    encore = {pythons.get(v) for v in restantes}
    pyenv = os.path.expanduser(os.path.join("~", ".pyenv", "versions"))
    for v in cibles:
        py = pythons.get(v)
        if py and py not in encore and os.path.isdir(os.path.join(pyenv, py)):
            if py not in plan["pyenv"]:
                plan["pyenv"].append(py)
    return plan


def afficher(racine, plan):
    print("Versions à retirer :")
    for e in plan["versions"]:
        morceaux = [
            os.path.relpath(c, racine) + "/"
            for c in [e["arbre"], e["projets"], *e["venvs"]]
            if c
        ]
        quoi = ", ".join(morceaux) or "aucun fichier, état seulement"
        print(f"  {e['version']:>5}  {humain(e['taille']):>10}  {quoi}")
    print(f"Versions qui restent : {', '.join(plan['restantes']) or 'aucune'}")
    if plan["orphelins"]:
        total = sum(o["taille"] for o in plan["orphelins"])
        print(
            f"Stockages d'objets sans dépôt restant : {len(plan['orphelins'])},"
            f" {humain(total)}"
        )
    sautes = [p for p in plan["partages"] if p["saut"]]
    for p in sautes:
        nom = os.path.relpath(p["stockage"], racine)
        print(f"Stockage partagé {nom} : laissé tel quel ({p['saut']})")
    utiles = sorted(
        (
            p
            for p in plan["partages"]
            if not p["saut"]
            and p["apres"] is not None
            and p["avant"] - p["apres"] >= SEUIL_GAIN
        ),
        key=lambda p: p["apres"] - p["avant"],
    )
    if utiles:
        avant = sum(p["avant"] for p in utiles)
        apres = sum(p["apres"] for p in utiles)
        nrefs = sum(len(r) for p in utiles for r in p["refs"].values())
        print(
            f"Stockages partagés à compacter : {len(utiles)},"
            f" {humain(avant)} -> ~{humain(apres)} ; {nrefs} référence(s)"
            " de versions non installées retirée(s)"
        )
        for p in utiles[:AFFICHES]:
            nom = os.path.relpath(p["stockage"], racine)
            print(
                f"  {humain(p['avant']):>10} -> ~{humain(p['apres']):<10} {nom}"
            )
        if len(utiles) > AFFICHES:
            print(f"  … et {len(utiles) - AFFICHES} autre(s)")
    for py in plan["pyenv"]:
        print(
            f"Python {py} : plus aucune version installée ne le déclare"
            f" (« pyenv uninstall {py} » s'il ne sert à rien d'autre)"
        )


# ── effacement ────────────────────────────────────────────────────────────


def effacer(chemin, erreurs):
    """Efface un fichier, un lien ou un dossier ; note l'échec."""

    def rendre_inscriptible(fonction, cible, _exc):
        try:
            os.chmod(os.path.dirname(cible), 0o700)
            os.chmod(cible, 0o700)
            fonction(cible)
        except OSError as exc:
            erreurs.append(f"{cible}: {exc}")

    if os.path.islink(chemin) or os.path.isfile(chemin):
        try:
            os.remove(chemin)
        except OSError as exc:
            erreurs.append(f"{chemin}: {exc}")
    elif os.path.isdir(chemin):
        shutil.rmtree(chemin, onexc=rendre_inscriptible)


def mettre_a_jour_etat(racine, retirees):
    """Retire les versions de la liste des installées et de l'état."""
    chemin = os.path.join(racine, FICHIER_INSTALLEES)
    if os.path.isfile(chemin):
        lignes = [
            ligne
            for ligne in lire_lignes(chemin)
            if ligne[len("odoo") :] not in retirees
        ]
        with open(chemin, "w", encoding="utf-8") as fh:
            fh.write("".join(f"{ligne}\n" for ligne in lignes))
    chemin = os.path.join(racine, FICHIER_ETAT)
    try:
        with open(chemin, encoding="utf-8") as fh:
            etat = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return
    versions = etat.get("odoo_versions") or {}
    for v in retirees:
        versions.pop(v, None)
    if etat.get("current_odoo_version") in retirees:
        active = lire_active(racine)
        etat["current_odoo_version"] = active if active in versions else None
    with open(chemin, "w", encoding="utf-8") as fh:
        json.dump(etat, fh, indent=4, ensure_ascii=False)
        fh.write("\n")


def regenerer_defaut(racine, sortie):
    """La fusion des manifestes, gelée ou non comme le checkout l'est."""
    from script.git import repo_pull, repo_state

    geler = repo_state.mode_du_checkout(racine)[0] == "frozen"
    return repo_pull.regenerer_defaut(racine, racine, sortie, geler)


def regenerer_manifeste(racine, regenerer):
    """Réécrit le manifeste local d'un coup. Rend None, ou le motif."""
    local = os.path.join(racine, MANIFESTE_LOCAL)
    if not os.path.isfile(local):
        return None
    temporaire = os.path.join(os.path.dirname(local), ".erplibre_manifest.tmp")
    code, texte = regenerer(racine, temporaire)
    if code or not os.path.isfile(temporaire):
        ligne = (texte or "").strip().splitlines()[-1:] or [str(code)]
        return ligne[0]
    os.replace(temporaire, local)
    return None


def compacter(partage, erreurs):
    """Nettoie en place un stockage partagé (voir la docstring du module).

    Rend les octets rendus."""
    objets = partage["objets"]
    restants = partage["restants"]
    for gitdir, refs in partage["refs"].items():
        # no-deref : une référence symbolique part elle-même, pas sa cible.
        entree = "".join(f"option no-deref\ndelete {r}\n" for r in refs)
        _out, err, code = git(["update-ref", "--stdin"], gitdir, entree=entree)
        if code:
            erreurs.append(f"{gitdir}: update-ref: {err.strip()}")
            return 0
    for gitdir in restants:
        git(["reflog", "expire", "--all"], gitdir)

    avant = taille(objets)
    pack = os.path.join(objets, "pack")
    with tempfile.TemporaryDirectory() as tmp:
        liste = os.path.join(tmp, "objets")
        echec = lister_objets(restants, liste)
        if echec:
            erreurs.append(f"{objets}: {echec}")
            return 0
        uniques = ecrire_uniques(liste)
        estime = taille_des_objets(restants[0], uniques)
        if avant - estime < SEUIL_GAIN:
            return 0
        if shutil.disk_usage(pack).free < estime * MARGE_ESPACE:
            erreurs.append(
                f"{objets}: {humain(estime)} à écrire, espace libre"
                " insuffisant ; laissé tel quel"
            )
            return 0
        with open(liste) as entree:
            r = subprocess.run(
                [
                    "git",
                    "--git-dir",
                    restants[0],
                    "pack-objects",
                    "--threads=0",
                    "--delta-base-offset",
                    "-q",
                    os.path.join(pack, "pack"),
                ],
                stdin=entree,
                capture_output=True,
                text=True,
            )
        if r.returncode:
            erreurs.append(f"{objets}: pack-objects: {r.stderr.strip()}")
            return 0
        neuf = f"pack-{r.stdout.strip()}"

        cote = os.path.join(pack, f"ancien-{int(time.time())}")
        os.makedirs(cote)
        gardes = {
            os.path.splitext(n)[0]
            for n in os.listdir(pack)
            if n.endswith(".keep")
        }
        deplaces = []
        for nom in sorted(os.listdir(pack)):
            base = os.path.splitext(nom)[0]
            if (
                base == neuf
                or base in gardes
                or os.path.isdir(os.path.join(pack, nom))
            ):
                continue
            os.rename(os.path.join(pack, nom), os.path.join(cote, nom))
            deplaces.append(nom)
        info = os.path.join(objets, "info")
        for nom in ("commit-graph", "commit-graphs"):
            if os.path.exists(os.path.join(info, nom)):
                os.rename(os.path.join(info, nom), os.path.join(cote, nom))
                deplaces.append(os.path.join("info", nom))

        absents = manquants(restants[0], uniques)
        if absents:
            for nom in deplaces:
                destination = (
                    os.path.join(objets, nom)
                    if nom.startswith("info")
                    else os.path.join(pack, nom)
                )
                os.rename(
                    os.path.join(cote, os.path.basename(nom)), destination
                )
            os.rmdir(cote)
            erreurs.append(
                f"{objets}: {absents} objet(s) absent(s) du pack neuf ;"
                " anciens packs remis en place"
            )
            return 0
        shutil.rmtree(cote)
        git(["prune-packed"], restants[0])
    return max(avant - taille(objets), 0)


def executer(racine, plan, regenerer=None):
    """Efface selon `plan`. Rend (octets rendus, erreurs)."""
    erreurs = []
    rendu = 0
    for e in plan["versions"]:
        echecs = len(erreurs)
        chemins = [c for c in [e["arbre"], e["projets"], *e["venvs"]] if c]
        for chemin in chemins:
            effacer(chemin, erreurs)
        reste = sum(taille(c) for c in chemins) if len(erreurs) > echecs else 0
        rendu += e["taille"] - reste
    retirees = [e["version"] for e in plan["versions"]]
    mettre_a_jour_etat(racine, retirees)
    motif = regenerer_manifeste(racine, regenerer or regenerer_defaut)
    if motif:
        erreurs.append(
            f"manifeste local non régénéré ({motif}) : « make"
            " repo_configure_all » avant tout « repo sync », qui reclonerait"
            " les versions retirées"
        )
    for o in plan["orphelins"]:
        effacer(o["stockage"], erreurs)
        rendu += o["taille"] - taille(o["stockage"])
    for p in plan["partages"]:
        if p["saut"] or (
            p["apres"] is not None and p["avant"] - p["apres"] < SEUIL_GAIN
        ):
            continue
        rendu += compacter(p, erreurs)
    return rendu, erreurs


# ── interface ─────────────────────────────────────────────────────────────


def confirmer(plan, oui):
    """Vrai si l'effacement est consenti."""
    pertes = [
        (e["version"], p) for e in plan["versions"] for p in e["non_sauve"]
    ]
    if pertes:
        print("\nTravail non sauvegardé, perdu à l'effacement :")
        for version, perte in pertes:
            print(f"  [{version}] {perte}")
        if not sys.stdin.isatty():
            print("Pas de terminal pour confirmer : rien n'est effacé.")
            return False
        reponse = input(
            f"Tapez « {MOT_CONFIRMATION} » pour tout effacer quand même : "
        )
        return reponse.strip() == MOT_CONFIRMATION
    if oui:
        return True
    if not sys.stdin.isatty():
        print("Pas de terminal pour confirmer : relancer avec --yes.")
        return False
    return input("\nEffacer ? [o/N] ").strip().lower() in ("o", "oui", "y")


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Retirer une version d'Odoo du checkout, ou toutes."
    )
    groupe = parser.add_mutually_exclusive_group(required=True)
    groupe.add_argument(
        "--version",
        action="append",
        metavar="V",
        help="version à retirer, ex. 16.0 ; se répète",
    )
    groupe.add_argument(
        "--all", action="store_true", help="retirer toutes les versions"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="afficher sans rien effacer"
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="sans question, sauf travail non sauvegardé",
    )
    parser.add_argument("--root", default=RACINE, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    racine = os.path.abspath(args.root)

    versions = []
    for v in args.version or []:
        v = v.removeprefix("odoo")
        if not RE_VERSION.match(v):
            parser.error(f"version « {v} » : attendu la forme 16.0")
        versions.append(v)
    active = lire_active(racine)
    if not args.all and active in versions:
        print(
            f"{active} est la version active : passer d'abord à une autre"
            " (make switch_odoo_<V>), ou tout retirer par --all."
        )
        return EXIT_REFUS
    if not args.all:
        connues = versions_connues(racine)
        absentes = [v for v in versions if v not in connues]
        if absentes:
            print(f"Rien d'installé pour {', '.join(absentes)}.")
            versions = [v for v in versions if v in connues]
            if not versions:
                return EXIT_OK

    print("Lecture des dépôts…")
    plan = planifier(racine, versions, args.all)
    if not plan["versions"]:
        print("Rien à retirer.")
        return EXIT_OK
    afficher(racine, plan)
    if args.dry_run:
        return EXIT_OK
    if not confirmer(plan, args.yes):
        return EXIT_REFUS
    rendu, erreurs = executer(racine, plan)
    for erreur in erreurs:
        print(f"Erreur : {erreur}", file=sys.stderr)
    print(f"Espace rendu : {humain(rendu)}")
    if args.all:
        print("Toutes les versions sont retirées : make install_odoo_<V>.")
    return EXIT_ERREUR if erreurs else EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
