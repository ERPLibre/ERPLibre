#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Le retour des pull requests d'une forge vers les clones du checkout.

Trois gestes, du plus sûr au plus engageant.

La LECTURE prend, pour un clone, les pull requests du dépôt de la forge qui
le concernent : celles dont la tête est l'une de ses branches locales (et
vient du même dépôt, pas d'un fork homonyme), et celles qui visent sa
branche du manifeste. Les ouvertes sont toutes lues, avec leur revue et la
CI du commit de tête ; les fermées, les plus récentes seulement. Tout texte
venu de la forge passe par `affichable` avant d'atteindre le terminal.

Le RAPATRIEMENT amène la branche de base d'une pull request fusionnée dans
le clone, sans jamais forcer une branche locale : la ref de suivi
« <remote>/<base> » avance, puis la branche locale est créée si elle
manque, avancée en fast-forward si c'est possible, et laissée telle quelle
sinon. Aucune branche n'est supprimée, aucune branche extraite ne change
hors d'un fast-forward sur un arbre propre.

Le GEL ne suit que les projets déjà gelés, vers l'avant seulement :
`candidats_gel` choisit ceux dont le commit gelé est un ancêtre du commit
rapatrié, et la publication puis l'écriture restent à l'appelant
(`freeze_resolution`).

`repo_pull` (masquage des secrets) s'importe dans les fonctions : il
importe `repo_state`, qui importe le menu, qui importe ce module.
"""

import os
import re

from script.git import manifest_freeze, manifest_repo, repo_upgrade

# Le nombre de pull requests fermées montrées par dépôt, les plus récentes.
FERMEES_MONTREES = 5
# Les préfixes de titre qui font d'une pull request un brouillon, ceux de
# Forgejo par défaut ; la casse ne compte pas.
PREFIXES_BROUILLON = ("WIP:", "[WIP]")
ETATS_RAPATRIEMENT = (
    "creee",
    "a_jour",
    "avance",
    "en_avance",
    "diverge",
    "indetermine",
    "sale",
    "operation_en_cours",
    "refus",
    "echec_fetch",
)
# Les états après lesquels la branche locale porte le commit fusionné.
ETATS_GELABLES = ("creee", "a_jour", "avance")
# Le détail d'un refus pour un nom de branche que git n'accepte pas : une
# clé de traduction, contrairement au texte de git des autres refus.
NOM_INVALIDE = "invalid branch name"
# Les fichiers que laisse une opération git interrompue, lus par
# « git rev-parse --git-path » : un worktree secondaire a les siens.
OPERATIONS = (
    "rebase-merge",
    "rebase-apply",
    "MERGE_HEAD",
    "CHERRY_PICK_HEAD",
    "REVERT_HEAD",
    "BISECT_LOG",
)
_CONTROLE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_SHA = re.compile(r"[0-9a-fA-F]{40}(?:[0-9a-fA-F]{24})?")


def affichable(texte):
    """`texte` venu de la forge (titre, login, URL) dont chaque caractère
    de contrôle devient « ? » : une séquence d'échappement dans un titre
    agirait sinon sur le terminal. None rend ""."""
    return _CONTROLE.sub("?", "" if texte is None else str(texte))


def etat_pr(pr):
    """« fusionnee », « fermee », « brouillon » ou « ouverte ». Un titre
    préfixé par l'un de `PREFIXES_BROUILLON`, sans égard à la casse, fait
    un brouillon comme le champ « draft »."""
    if pr.get("merged"):
        return "fusionnee"
    if pr.get("state") == "closed":
        return "fermee"
    titre = (pr.get("title") or "").upper()
    if pr.get("draft") or titre.startswith(
        tuple(p.upper() for p in PREFIXES_BROUILLON)
    ):
        return "brouillon"
    return "ouverte"


def revues_github(revues):
    """Les revues de Forgejo dans le vocabulaire de `manifest_repo.etat_revue`
    : « REQUEST_CHANGES » devient « CHANGES_REQUESTED », une revue écartée
    (« dismissed ») devient « DISMISSED » quel que soit son état. L'ordre
    est conservé ; un élément qui n'est pas un dict est ignoré."""
    res = []
    for revue in revues or []:
        if not isinstance(revue, dict):
            continue
        etat = revue.get("state")
        if revue.get("dismissed"):
            etat = "DISMISSED"
        elif etat == "REQUEST_CHANGES":
            etat = "CHANGES_REQUESTED"
        res.append(dict(revue, state=etat))
    return res


def etat_ci(statut):
    """« echec », « en_cours », « succes » ou None (aucune CI) d'un statut
    combiné : `manifest_repo.etat_ci` sans check-run. None ou {} rend
    None."""
    if not statut:
        return None
    return manifest_repo.etat_ci(statut, [])


def branches_locales(chemin):
    """Les noms des branches locales du clone ; set() quand git échoue."""
    out, _err, code = repo_upgrade.git(
        ["for-each-ref", "--format=%(refname)", "refs/heads"], chemin
    )
    if code:
        return set()
    return {
        ligne[len("refs/heads/") :]
        for ligne in out.splitlines()
        if ligne.startswith("refs/heads/")
    }


def pertinentes(prs, locales, reference, depot_forge=None):
    """Les pull requests de `prs` qui concernent un clone : la tête est
    l'une de ses branches `locales` et vient du dépôt `depot_forge`
    (« propriétaire/dépôt », casse ignorée ; une tête sans dépôt connu
    compte), ou la base est sa branche `reference`. Dédoublonnées par
    numéro, ordre conservé."""
    res, vus = [], set()
    for pr in prs or []:
        if not isinstance(pr, dict):
            continue
        tete = pr.get("head") or {}
        base = pr.get("base") or {}
        origine = ((tete.get("repo") or {}).get("full_name") or "").lower()
        du_depot = (
            not origine
            or depot_forge is None
            or origine == depot_forge.lower()
        )
        if not (
            (tete.get("ref") in locales and du_depot)
            or (reference and base.get("ref") == reference)
        ):
            continue
        if pr.get("number") in vus:
            continue
        vus.add(pr.get("number"))
        res.append(pr)
    return res


def _entier(valeur):
    try:
        return int(valeur or 0)
    except (TypeError, ValueError):
        return 0


def lire(
    client,
    proprietaire,
    depot,
    locales,
    reference,
    fermees=FERMEES_MONTREES,
):
    """Les pull requests du dépôt de la forge qui concernent un clone (voir
    `pertinentes`) : toutes les ouvertes, puis au plus `fermees` fermées,
    les plus récemment modifiées, choisies parmi les `fermees * 4` que la
    forge rend en premier. La revue et la CI ne se lisent que pour une
    ouverte ou un brouillon. Un refus de l'API (`ErreurForgejo`) remonte.

    Chaque élément : numero, titre et url (`affichable`), etat (`etat_pr`),
    tete, base, sha_tete, sha_fusion, fusionnee_le (AAAA-MM-JJ ou ""),
    commentaires, revue (`manifest_repo.etat_revue`) et ci (`etat_ci`)."""
    forge = f"{proprietaire}/{depot}"
    ouvertes = pertinentes(
        client.pull_requests(proprietaire, depot, etat="open"),
        locales,
        reference,
        forge,
    )
    fermees_lues = client.pull_requests(
        proprietaire,
        depot,
        etat="closed",
        tri="recentupdate",
        limite=fermees * 4,
    )
    retenues = (
        ouvertes
        + pertinentes(fermees_lues, locales, reference, forge)[:fermees]
    )
    res, vus = [], set()
    for pr in retenues:
        numero = pr.get("number")
        if numero is None or numero in vus:
            continue
        vus.add(numero)
        etat = etat_pr(pr)
        tete = pr.get("head") or {}
        base = pr.get("base") or {}
        revue = ci = None
        if etat in ("ouverte", "brouillon"):
            revue = manifest_repo.etat_revue(
                revues_github(
                    client.revues_pull_request(proprietaire, depot, numero)
                )
            )
            sha = tete.get("sha") or ""
            if _SHA.fullmatch(sha):
                ci = etat_ci(client.statut_combine(proprietaire, depot, sha))
        res.append(
            {
                "numero": numero,
                "titre": affichable(pr.get("title")),
                "url": affichable(pr.get("html_url")),
                "etat": etat,
                "tete": tete.get("ref") or "",
                "base": base.get("ref") or "",
                "sha_tete": tete.get("sha") or "",
                "sha_fusion": pr.get("merge_commit_sha") or "",
                "fusionnee_le": (pr.get("merged_at") or "")[:10],
                "commentaires": _entier(pr.get("comments")),
                "revue": revue,
                "ci": ci,
            }
        )
    return res


def deja_local(chemin, pr):
    """Vrai si le commit de fusion de `pr` est dans la branche locale de sa
    base. Faux sans commit de fusion, sans cette branche, ou quand le
    commit manque au clone. Aucun réseau."""
    sha, base = pr.get("sha_fusion") or "", pr.get("base") or ""
    if not _SHA.fullmatch(sha) or not base:
        return False
    _out, _err, code = repo_upgrade.git(
        ["cat-file", "-e", f"{sha}^{{commit}}"], chemin
    )
    if code:
        return False
    _out, _err, code = repo_upgrade.git(
        ["merge-base", "--is-ancestor", sha, f"refs/heads/{base}"], chemin
    )
    return code == 0


def nom_de_branche_sur(base, chemin=None):
    """Vrai si `base`, venu de l'API, est un nom de branche que git accepte
    tel quel : non vide, sans « - » initial (il deviendrait une option), et
    validé par « git check-ref-format --branch » sans expansion (« @{-1} »
    rendrait un autre nom). `chemin` : le clone où git tourne."""
    if not base or base.startswith("-"):
        return False
    out, _err, code = repo_upgrade.git(
        ["check-ref-format", "--branch", base], chemin or os.getcwd()
    )
    return code == 0 and out.strip() == base


def _resultat(etat, detail="", sha=None, ancien=None):
    return {"etat": etat, "detail": detail, "sha": sha, "ancien": ancien}


def rapatrier(chemin, remote, base):
    """Amène la branche `base` du remote `remote` dans le clone, sans
    jamais forcer une branche locale. Rend {etat, detail, sha, ancien} ;
    `etat` est l'un de `ETATS_RAPATRIEMENT`, `sha` le commit de la forge
    quand il est connu, `ancien` celui de la branche locale ou None.

    Le fetch force la seule ref de suivi « refs/remotes/<remote>/<base> ».
    La branche locale absente est créée sans configuration de suivi
    (« creee ») : `repo sync` et `repo prune` ignorent une branche qui n'en
    a pas. Égale, elle est « a_jour » ; en avance sur la forge,
    « en_avance » ; divergée, « diverge » (« indetermine » dans un clone
    superficiel, où l'ascendance ne se prouve pas). Une opération git
    interrompue (rebase, merge…) bloque tout. Extraite, elle n'avance qu'en
    fast-forward sur un arbre sans modification suivie (« sale » sinon) ;
    non extraite, par « git fetch . » sans « + », que git refuse pour un
    non-fast-forward ou une branche extraite dans un autre worktree."""
    from script.git import repo_pull

    if not nom_de_branche_sur(base, chemin):
        return _resultat("refus", NOM_INVALIDE)
    suivi = f"refs/remotes/{remote}/{base}"
    locale = f"refs/heads/{base}"
    _out, err, code = repo_upgrade.git(
        ["fetch", "--no-tags", remote, f"+refs/heads/{base}:{suivi}"],
        chemin,
        repo_upgrade.DELAI_GIT,
    )
    if code:
        return _resultat(
            "echec_fetch", repo_pull.sans_secrets(err.strip())[-300:]
        )
    neuf = repo_upgrade.commit_de(chemin, suivi)
    if neuf is None:
        return _resultat("echec_fetch", suivi)
    ancien = repo_upgrade.commit_de(chemin, locale)
    if ancien is None:
        _out, err, code = repo_upgrade.git(
            [
                "update-ref",
                "-m",
                f"erplibre: fetch merged {remote}/{base}",
                locale,
                neuf,
                "",
            ],
            chemin,
        )
        if code:
            return _resultat(
                "refus", repo_pull.sans_secrets(err.strip()), neuf
            )
        return _resultat("creee", "", neuf)
    if ancien == neuf:
        return _resultat("a_jour", "", neuf, ancien)

    def ancetre(a, b):
        return (
            repo_upgrade.git(["merge-base", "--is-ancestor", a, b], chemin)[2]
            == 0
        )

    if ancetre(neuf, ancien):
        return _resultat("en_avance", "", neuf, ancien)
    if not ancetre(ancien, neuf):
        etat = (
            "indetermine"
            if repo_upgrade.est_superficiel(chemin)
            else "diverge"
        )
        return _resultat(etat, "", neuf, ancien)
    for nom in OPERATIONS:
        out, _err, code = repo_upgrade.git(
            ["rev-parse", "--git-path", nom], chemin
        )
        if code == 0 and os.path.exists(os.path.join(chemin, out.strip())):
            return _resultat("operation_en_cours", nom, neuf, ancien)
    out, _err, code = repo_upgrade.git(
        ["symbolic-ref", "--quiet", "HEAD"], chemin
    )
    if code == 0 and out.strip() == locale:
        out, _err, code = repo_upgrade.git(
            ["status", "--porcelain", "--untracked-files=no"], chemin
        )
        if code or out.strip():
            return _resultat("sale", "", neuf, ancien)
        _out, err, code = repo_upgrade.git(
            ["merge", "--ff-only", "--quiet", neuf], chemin
        )
    else:
        _out, err, code = repo_upgrade.git(
            ["fetch", "--quiet", "--no-tags", ".", f"{suivi}:{locale}"],
            chemin,
        )
    if code:
        return _resultat(
            "refus", repo_pull.sans_secrets(err.strip())[-300:], neuf, ancien
        )
    return _resultat("avance", "", neuf, ancien)


def _avance_sur(chemin, ancien, neuf):
    """Vrai si le commit `ancien` est un ancêtre de `neuf` dans le clone,
    None quand `ancien` y manque."""
    if not manifest_freeze.is_sha(ancien) or (
        repo_upgrade.commit_de(chemin, ancien) is None
    ):
        return None
    _out, _err, code = repo_upgrade.git(
        ["merge-base", "--is-ancestor", ancien, neuf], chemin
    )
    return code == 0


def candidats_gel(projets, rapatries, definitions, fetch, avance_sur=None):
    """(dépôts, écartés) du gel à avancer après un rapatriement.

    `rapatries` : {chemin absolu: (base, résultat de `rapatrier`)} ;
    `definitions` : {clé: [(fichier, attributs)]} des fichiers du gel ;
    `fetch` : {remote: fetch} sans surcouche de forge ; `avance_sur(chemin,
    ancien, neuf)` rend True, False ou None (par défaut : « merge-base
    --is-ancestor », None quand l'ancien commit manque au clone).

    Un projet n'entre que s'il est un clone (jamais la racine ERPLibre),
    rapatrié dans un état de `ETATS_GELABLES`, sur sa branche du
    manifeste, déclaré avec un « path », déjà gelé (le dernier
    « freeze-revision » de ses définitions, comme dans la fusion), et si son
    gel est un ancêtre du commit rapatrié : le gel n'avance que vers
    l'avant. Un dépôt rendu porte ce que `freeze_resolution.publication` et
    `mettre_a_jour_gel` lisent : path (relatif), name, head, freeze_revision,
    url (celle du manifeste, sans surcouche), manifest_branch et branch, la
    base ; avec une branche, la publication rend la commande de push à
    lancer. Un écarté est (projet, motif), le motif étant une clé de
    traduction ; un état non gelable est écarté sans motif, déjà rapporté."""
    avance_sur = avance_sur or _avance_sur
    depots, ignores = [], []
    for p in projets:
        if p.get("racine") or p["chemin"] not in rapatries:
            continue
        base, resultat = rapatries[p["chemin"]]
        if resultat.get("etat") not in ETATS_GELABLES:
            continue
        sha = resultat.get("sha")
        if base != p.get("branche"):
            ignores.append((p, "merged into another branch"))
            continue
        if manifest_freeze.project_key(p["nom"], p["affiche"]) != p["cle"]:
            ignores.append((p, "no path in the manifest"))
            continue
        ancien_gel = None
        for _fichier, attrs in definitions.get(p["cle"], []):
            ancien_gel = attrs.get(manifest_freeze.FREEZE_ATTR) or ancien_gel
        if not ancien_gel:
            ignores.append((p, "not frozen"))
            continue
        if ancien_gel == sha:
            ignores.append((p, "freeze already on this commit"))
            continue
        avance = avance_sur(p["chemin"], ancien_gel, sha)
        if avance is None:
            ignores.append((p, "freeze commit not in the clone"))
            continue
        if not avance:
            ignores.append(
                (p, "the freeze is not an ancestor of the merged commit")
            )
            continue
        depots.append(
            {
                "path": p["affiche"],
                "name": p["nom"],
                "head": sha,
                "freeze_revision": ancien_gel,
                "url": repo_upgrade.url_amont(
                    fetch.get(p["remote"]), p["nom"]
                ),
                "manifest_branch": base,
                "branch": base,
            }
        )
    return depots, ignores
