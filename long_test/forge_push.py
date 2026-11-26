#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une forge Forgejo déployée dans une VM reçoit-elle le projet actuel ?

Le test crée la forge par `script.forgejo.forge_vm.deployer`, celle que le
menu TODO crée aussi : une VM QEMU, le code de CE checkout (un bundle git)
avec l'installateur de l'arbre de travail, .venv.erplibre seul — pas
d'Odoo —, Forgejo en push-to-create, inscriptions fermées, dépôts privés
par défaut et push de clone superficiel accepté, puis un jeton créé avec le
mot de passe administrateur et la clé SSH publique déposée. Il crée
ensuite, privée, chaque organisation propriétaire. Enfin il pousse, en
parallèle et sans force, le dépôt ERPLibre lui-même et chaque clone de la
version d'Odoo active (la branche du manifeste, `push_remote.MODE_MANIFESTE`),
chacun vers « ssh://git@<vm>:2222/<propriétaire>/<dépôt>.git », et vérifie
sur la forge que chaque branche porte le commit poussé.

Le retour suit (`retour`) : dans un clone temporaire du dossier de course,
une branche d'un commit vide part vers le dépôt ERPLibre de la forge, une
pull request l'y fusionne dans la branche poussée, puis
`forge_pull_requests` doit la lire fusionnée et la rapatrier en
fast-forward dans la branche locale du clone temporaire.

Avec `--miroirs K`, les miroirs suivent (`miroirs`, `synchro`) : le
minuteur posé sur la forge, un miroir natif pour le dépôt ERPLibre (une
branche de refs/remotes/origin) et K clones, puis trois branches de cas
poussées sans force dans le dépôt ERPLibre de la forge — en retard, en
avance et divergente par rapport au miroir —, et une passe qui doit
avancer la première, laisser les deux autres et ne rien forcer. La VM doit
joindre GitHub en https pour cette étape.

Avec `--ci`, la forge reçoit aussi le runner de CI (`runner`, un
forgejo-runner en mode hôte et le venv de CI bâti d'avance), et le dépôt
ERPLibre deux branches de plus : `HEAD~1` en `ci-longtest-base` et `HEAD`
en `ci-longtest`. Après le retour, Actions s'active sur ce dépôt, une pull
request s'ouvre entre elles, et son workflow — celui de HEAD, COMMITÉ :
la course refuse de partir sans lui — doit finir en succès (`ci`). Avec
`--miroirs` en plus, les commits que la synchro pousse ne doivent porter
aucun statut (`ci_push`) : le workflow ne réagit qu'aux pull requests.

Aucun clone de l'hôte n'est modifié : le push vise une URL, aucun remote
n'est ajouté. Le mot de passe administrateur est tiré au hasard, passé par
l'entrée standard et jamais écrit ; le jeton ne vit que dans le processus.

Le rapport (~/.erplibre/longtest/forge-push-<horodatage>.json) nomme la VM
et son UUID ; `--detruire` défait la VM du dernier rapport, et elle seule.

  ./long_test/forge_push.py                  # toute la course
  ./long_test/forge_push.py --projets 5      # le dépôt ERPLibre et 5 clones
  ./long_test/forge_push.py --miroirs 2      # plus les miroirs d'ERPLibre et de 2 clones
  ./long_test/forge_push.py --ci             # plus la CI des pull requests d'ERPLibre
  ./long_test/forge_push.py --dry-run        # le plan, rien de créé
  ./long_test/forge_push.py --detruire       # défaire la dernière course
"""

import argparse
import json
import os
import shlex
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from descente import (  # noqa: E402
    autre_descente,
    detruire_etage1,
    dire,
    drapeaux_cache,
)

from script.forgejo import forge_vm  # noqa: E402
from script.git import forgejo_client as fc  # noqa: E402
from script.git import manifest_repo, push_remote  # noqa: E402

OUTIL = "forge_push"
NOM_BASE = "forge-push"
# Un compte dont le nom ne recouvre aucun propriétaire du manifeste : Forgejo
# compare les noms sans égard à la casse, et un compte « erplibre »
# empêcherait l'organisation « ERPLibre ».
ADMIN = "forge-longtest"
DELAI_PUSH = 1800

OPTIONS_SSH = forge_vm.OPTIONS_SSH


def etapes(ci=False):
    """Les étapes de la course, dans l'ordre : celles de
    `forge_vm.etapes`, puis celles du test. `ci` ajoute « runner », « ci »
    après le retour et « ci_push » après la synchro."""
    return (
        forge_vm.etapes(runner=ci)
        + ("organisations", "push", "verification", "retour")
        + (("ci",) if ci else ())
        + ("miroirs", "synchro")
        + (("ci_push",) if ci else ())
    )


ETAPES = etapes()
# La branche que l'étape « retour » pousse puis fait fusionner.
BRANCHE_RETOUR = "longtest-retour"
# La fusion d'une pull request juste ouverte répond 405 tant que la forge
# n'a pas fini de vérifier qu'elle est fusionnable, ce qu'elle fait en
# arrière-plan : la demande se répète, `ESSAIS_FUSION` fois au plus.
ESSAIS_FUSION = 10
PAUSE_FUSION = 3
# Un miroir neuf reste vide le temps de son clone initial, que la forge
# mène en arrière-plan : il se relit toutes les `PAUSE_MIROIR` secondes,
# `ATTENTE_MIROIRS` secondes au plus pour l'ensemble.
ATTENTE_MIROIRS = 1800
PAUSE_MIROIR = 10
# Le temps entre les deux essais du push des branches de la synchro.
PAUSE_PUSH = 10
# Les branches de cas de l'étape « synchro », poussées dans le dépôt
# ERPLibre de la forge : en retard d'un commit sur le miroir, en avance
# d'un commit, et divergente (un commit propre sur l'avant-dernier).
CAS_SYNCHRO = {
    "longtest-ff": "avance",
    "longtest-ahead": "en_avance",
    "longtest-div": "divergent",
}
# Les branches de l'étape « ci » dans le dépôt ERPLibre de la forge : la
# pull request va de `BRANCHE_CI` (HEAD) vers `BRANCHE_CI_BASE` (HEAD~1).
BRANCHE_CI = "ci-longtest"
BRANCHE_CI_BASE = "ci-longtest-base"
# Le workflow a 60 minutes, plus l'attente d'un runner libre : son statut
# se relit toutes les `PAUSE_CI` secondes, `ATTENTE_CI` secondes au plus.
ATTENTE_CI = 75 * 60
PAUSE_CI = 30
# Le délai laissé à la forge pour créer un run après un push, avant de
# constater qu'elle n'en a créé aucun (« ci_push »).
ATTENTE_CI_PUSH = 60
# Les fichiers que la pull request de CI doit trouver COMMITÉS dans HEAD :
# le run lit le workflow et le script du venv dans le commit de tête.
FICHIERS_CI_COMMITES = (
    ".forgejo/workflows/unit_test.yml",
    "script/forgejo/ci_venv.sh",
)


def chemins_de_course(horodatage):
    """(rapport, journal, dossier) de la course, sous ~/.erplibre/longtest."""
    base = os.path.expanduser(f"~/.erplibre/longtest/{NOM_BASE}-{horodatage}")
    os.makedirs(os.path.dirname(base), exist_ok=True)
    return base + ".json", base + ".log", base


def cibles_du_projet(projets, base_ssh, head_erplibre, origine, branche):
    """(cibles, écartés) du push. Une cible : « nom » affiché, « chemin »
    du clone, « remote » (l'URL sur la forge), « specs », « proprietaire »,
    « depot », « branche » visée et « sha » attendu (rempli plus tard pour
    les clones). Le dépôt ERPLibre vient en premier."""
    cibles, ecartes = [], []
    if origine:
        prop, depot = origine
        cibles.append(
            {
                "nom": "ERPLibre",
                "chemin": RACINE,
                "remote": push_remote.url_cible(base_ssh, prop, depot),
                "specs": [f"HEAD:refs/heads/{branche}"],
                "proprietaire": prop,
                "depot": depot,
                "branche": branche,
                "sha": head_erplibre,
            }
        )
    for p in projets:
        if not p["proprietaire"] or not p["branche"]:
            ecartes.append((p["chemin"], "no owner or branch in the manifest"))
            continue
        specs, motif = push_remote.refspecs(
            os.path.join(RACINE, p["chemin"]),
            push_remote.MODE_MANIFESTE,
            p["remote"],
            p["branche"],
        )
        if motif:
            ecartes.append((p["chemin"], motif))
            continue
        nom = (
            p["nom"][: -len(".git")] if p["nom"].endswith(".git") else p["nom"]
        )
        cibles.append(
            {
                "nom": p["chemin"],
                "chemin": os.path.join(RACINE, p["chemin"]),
                "remote": push_remote.url_cible(
                    base_ssh, p["proprietaire"], nom
                ),
                "specs": specs,
                "proprietaire": p["proprietaire"],
                "depot": nom,
                "branche": p["branche"],
                "sha": None,
            }
        )
    return cibles, ecartes


class Course:
    """Le rapport d'une course, écrit après chaque étape."""

    def __init__(self, chemin, journal, args):
        self.chemin = chemin
        self.journal = journal
        self.rapport = {
            "outil": OUTIL,
            "dry_run": bool(args.dry_run),
            "debut": time.strftime("%Y-%m-%d %H:%M:%S"),
            "vm": None,
            "etapes": {},
            "pushes": [],
        }

    def dire(self, texte):
        dire(texte, self.journal)

    def etape(self, nom, ok, detail=""):
        self.rapport["etapes"][nom] = {"ok": bool(ok), "detail": detail}
        self.dire(
            f"{'✓' if ok else '✗'} {nom}{' : ' + detail if detail else ''}"
        )
        self.ecrire()
        return ok

    def ecrire(self):
        with open(self.chemin, "w", encoding="utf-8") as fh:
            json.dump(self.rapport, fh, indent=1, ensure_ascii=False)


def adresse_de(nom):
    """L'IPv4 de la VM d'après son bail DHCP, ou ""."""
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return (
        TODO.__new__(TODO)._qemu_vm_ip(nom, timeout=forge_vm.DELAI_SSH) or ""
    )


# Les fichiers que le test exerce, copiés tels qu'ils sont dans l'arbre de
# travail par-dessus le clone du bundle : c'est notre code qu'on veut voir
# tourner, commité ou non.
EXERCES = (
    "script/forgejo/install_forgejo.sh",
    "script/forgejo/install_forgejo_runner.sh",
    "script/forgejo/lib_app_ini.sh",
    "script/forgejo/ci_venv.sh",
)


def specs_ci(branche):
    """Les refspecs du dépôt ERPLibre avec `--ci` : HEAD sous `branche`,
    puis les deux branches de la pull request de CI. Aucun objet n'est
    écrit dans le dépôt de l'hôte."""
    return [
        f"HEAD:refs/heads/{branche}",
        f"HEAD~1:refs/heads/{BRANCHE_CI_BASE}",
        f"HEAD:refs/heads/{BRANCHE_CI}",
    ]


def refus_ci(git_hote=None):
    """Le motif qui empêche `--ci` de partir, ou "" : un fichier de
    `FICHIERS_CI_COMMITES` absent de HEAD, ou HEAD sans parent. `git_hote`
    (`forge_vm.git_hote` par défaut) rend (code, sortie)."""
    git_hote = git_hote or forge_vm.git_hote
    for f in FICHIERS_CI_COMMITES:
        if git_hote("cat-file", "-e", f"HEAD:{f}")[0]:
            return (
                f"{f} is not committed in HEAD: the pull request runs the"
                " COMMITTED workflow"
            )
    if git_hote("rev-parse", "--verify", "-q", "HEAD~1")[0]:
        return "HEAD has no parent: the CI pull request needs HEAD~1"
    return ""


def mener(args):
    horodatage = time.strftime("%Y%m%d-%H%M%S")
    chemin, journal, dossier = chemins_de_course(horodatage)
    course = Course(chemin, journal, args)
    nom = f"{NOM_BASE}-{horodatage[2:8]}-{horodatage[9:13]}"
    cle_pub = forge_vm.cle_publique()
    if not cle_pub:
        course.dire("✗ aucune clé publique dans ~/.ssh")
        return 1

    os.chdir(RACINE)
    projets = push_remote.projets_actifs()
    if args.projets is not None:
        projets = projets[: args.projets]
    _, origine_url = forge_vm.git_hote("remote", "get-url", "origin")
    depot = manifest_repo.depot_de_l_url(origine_url)
    origine = depot[:2] if depot else None
    _, branche = forge_vm.git_hote("rev-parse", "--abbrev-ref", "HEAD")
    branche = branche if branche and branche != "HEAD" else "main"
    _, head = forge_vm.git_hote("rev-parse", "HEAD")
    course.dire(
        f"plan : VM {nom} ({forge_vm.DISTRO} {forge_vm.VERSION},"
        f" {forge_vm.VCPUS} vCPU, {forge_vm.MEMOIRE_MO} Mo,"
        f" {forge_vm.DISQUE_GO} Go) ; ERPLibre ({branche}) et"
        f" {len(projets)} clones"
    )
    if args.ci:
        motif = refus_ci()
        if motif:
            course.dire(f"✗ --ci : {motif}")
            return 1
        if forge_vm.git_hote(
            "diff",
            "--quiet",
            "HEAD",
            "--",
            ".forgejo",
            "script/forgejo/ci_venv.sh",
            "script/test",
        )[0]:
            course.dire(
                "⚠ --ci : .forgejo, ci_venv.sh ou script/test diffèrent de"
                " HEAD ; la pull request exerce HEAD, pas l'arbre de travail"
            )
        course.dire(
            f"  runner : {forge_vm.LABEL_CI} ; pull request"
            f" {BRANCHE_CI} → {BRANCHE_CI_BASE} (HEAD → HEAD~1)"
        )
    if args.dry_run:
        argv = forge_vm.argv_creation(nom, cle_pub, drapeaux_cache())
        course.dire("  " + " ".join(shlex.quote(a) for a in ["sudo"] + argv))
        course.ecrire()
        return 0

    # 1 à 6. La VM, SSH, le code, .venv.erplibre seul, Forgejo, l'amorçage
    # de l'API (jeton, clé SSH), puis, avec --ci, le runner : son échec
    # arrête la course, la forge restant en place. Le rapport nomme la VM dès qu'elle existe,
    # pour que --detruire la retrouve même si une étape suivante échoue.
    # Une VM qui portait déjà ce nom avant la course n'est jamais notée :
    # --detruire la déferait. Une création échouée qui a laissé un domaine
    # l'est, pour que --detruire la retrouve.
    preexistante = bool(forge_vm.uuid_libvirt(nom))

    def etape(n, ok, detail=""):
        if n == "vm" and not preexistante:
            uuid = forge_vm.uuid_libvirt(nom)
            if uuid or ok:
                course.rapport["vm"] = {"nom": nom, "uuid": uuid}
        if n == "ssh" and ok:
            course.rapport["vm"]["ip"] = detail
        return course.etape(n, ok, detail)

    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    forge = forge_vm.deployer(
        nom,
        ADMIN,
        journal,
        dossier,
        adresse_de,
        TODO._QEMU_ERPLIBRE_VENV_CMD,
        etape,
        cache=drapeaux_cache(),
        exerces=EXERCES,
        cle_pub=cle_pub,
        preambule=TODO._qemu_cloud_init_wait(),
        runner=args.ci,
    )
    if forge is None or (args.ci and not forge.get("runner")):
        return 1
    client, web = forge["client"], forge["web"]

    # 7. Les organisations propriétaires, créées privées.
    try:
        cibles, ecartes = cibles_du_projet(
            projets, forge["base_ssh"], head, origine, branche
        )
        if args.ci and cibles and cibles[0]["nom"] == "ERPLibre":
            cibles[0]["specs"] = specs_ci(branche)
        natures = fc.plan_proprietaires(
            client,
            fc.organisations_requises(c["proprietaire"] for c in cibles),
        )
        absentes = [n for n, v in natures.items() if v == "absent"]
        orgs = fc.assurer_organisations(client, absentes)
        erreurs = {n: m for n, (e, m) in orgs.items() if e == "erreur"}
        erreurs.update(
            {n: v for n, v in natures.items() if v.startswith("erreur")}
        )
    except (fc.ErreurForgejo, OSError) as exc:
        course.etape("organisations", False, str(exc))
        return 1
    if not course.etape(
        "organisations",
        not erreurs,
        f"{len(natures)} propriétaires, {len(absentes)} créés"
        + (f", erreurs {erreurs}" if erreurs else ""),
    ):
        return 1
    for chemin_clone, motif in ecartes:
        course.dire(f"  écarté : {chemin_clone} : {motif}")

    # 8. Le push, en parallèle, sans force, par SSH avec la clé déposée.
    prive = cle_pub[: -len(".pub")]
    os.environ["GIT_SSH_COMMAND"] = " ".join(
        [
            "ssh",
            "-i",
            shlex.quote(prive),
            "-o",
            "IdentitiesOnly=yes",
            *OPTIONS_SSH,
        ]
    )
    for c in cibles:
        if c["sha"] is None:
            c["sha"] = git_hote_dans(c["chemin"], "rev-parse", "HEAD")
    debut = time.time()

    def suivi(r):
        essais = f" ({r['essais']} essais)" if r.get("essais", 1) > 1 else ""
        course.dire(
            f"  {'ok' if not r['code'] else 'ÉCHEC'} {r['nom']}{essais}"
        )

    resultats = push_remote.pousser_en_parallele(
        cibles, args.jobs, suivi, delai=DELAI_PUSH
    )
    echecs = [r for r in resultats if r["code"]]
    for r in echecs:
        course.dire(f"  ✗ {r['nom']} : {r['erreur'][-400:]}")
    course.rapport["pushes"] = [
        {"nom": r["nom"], "code": r["code"], "erreur": r["erreur"][-400:]}
        for r in resultats
    ]
    course.etape(
        "push",
        not echecs,
        f"{len(resultats) - len(echecs)}/{len(resultats)} en"
        f" {int(time.time() - debut)} s, {len(ecartes)} écartés",
    )

    # 9. La forge porte-t-elle chaque commit poussé ? Lu par « git
    # ls-remote », ce que le dépôt de la forge contient vraiment : l'API
    # enregistre les branches de façon asynchrone et peut répondre 404 juste
    # après le push.
    faux = []
    for r in resultats:
        if r["code"]:
            continue
        sur_forge = branche_distante(r["chemin"], r["remote"], r["branche"])
        if sur_forge != r["sha"]:
            faux.append(f"{r['nom']} : {sur_forge} ≠ {r['sha']}")
    for ligne in faux:
        course.dire(f"  ✗ {ligne}")
    ok = course.etape(
        "verification",
        not faux and not echecs,
        f"{len(resultats) - len(echecs) - len(faux)} branches vérifiées",
    )

    # 10. Le retour d'une pull request fusionnée sur la forge.
    if ok:
        erplibre = next(
            (r for r in resultats if r["nom"] == "ERPLibre" and not r["code"]),
            None,
        )
        ok = retour(course, client, erplibre, dossier)

    # 11. La CI d'une pull request d'ERPLibre, par le runner de la forge.
    if ok and args.ci:
        erplibre = next(
            (r for r in resultats if r["nom"] == "ERPLibre" and not r["code"]),
            None,
        )
        ok = ci(course, client, erplibre, head)

    # 12. Les miroirs et le minuteur qui en avance les dépôts de travail.
    if ok and args.miroirs:
        erplibre = next(
            (r for r in resultats if r["nom"] == "ERPLibre" and not r["code"]),
            None,
        )
        ok = miroirs(
            course,
            client,
            forge,
            erplibre,
            [r for r in resultats if r["nom"] != "ERPLibre" and not r["code"]][
                : args.miroirs
            ],
            journal,
            dossier,
        )

    # 13. Les pushes de la synchro ne lancent aucune CI.
    if ok and args.ci and args.miroirs:
        poses = (course.rapport.get("synchro") or {}).get("pousses") or []
        ok = ci_push(course, client, erplibre, [p for p in poses if p != head])
    course.rapport["fin"] = time.strftime("%Y-%m-%d %H:%M:%S")
    course.ecrire()
    course.dire(f"rapport : {chemin}")
    course.dire(f"forge : {web} (VM gardée : --detruire la défait)")
    return 0 if ok else 1


def retour(course, client, cible, dossier, pause=PAUSE_FUSION):
    """L'étape « retour » sur `cible`, la cible ERPLibre poussée ; None
    fait échouer l'étape.

    Le clone temporaire vit dans `dossier` : aucun clone de l'hôte n'est
    touché. Il rapatrie la branche poussée (profondeur 2), y pose une
    branche locale du même nom, et pousse sans force `BRANCHE_RETOUR`, un
    commit vide par-dessus. La pull request de `BRANCHE_RETOUR` vers la
    branche est ouverte, puis fusionnée par l'API (« Do: merge »). Réussie
    quand `forge_pull_requests.lire` la rend fusionnée, que `rapatrier`
    avance la branche locale non extraite, et que `deja_local` le
    constate. Rend le verdict, noté dans le rapport."""
    from script.git import forge_pull_requests as fpr

    if cible is None:
        return course.etape("retour", False, "ERPLibre was not pushed")
    clone = os.path.join(dossier, "retour")
    proprietaire, depot, base = (
        cible["proprietaire"],
        cible["depot"],
        cible["branche"],
    )
    suivi = f"refs/remotes/forge/{base}"
    identite = [
        "-c",
        "user.name=forge-longtest",
        "-c",
        "user.email=forge-longtest@example.invalid",
        "-c",
        "commit.gpgsign=false",
    ]
    for args in (
        ["init", "-q", clone],
        ["-C", clone, "remote", "add", "forge", cible["remote"]],
        ["-C", clone, "fetch", "-q", "--depth", "2", "forge"]
        + [f"refs/heads/{base}:{suivi}"],
        ["-C", clone, "branch", base, suivi],
        ["-C", clone, "checkout", "-q", "-b", BRANCHE_RETOUR, suivi],
        ["-C", clone, *identite, "commit", "-q", "--allow-empty"]
        + ["-m", "Long test: merge back"],
        ["-C", clone, "push", "-q", "forge"]
        + [f"refs/heads/{BRANCHE_RETOUR}:refs/heads/{BRANCHE_RETOUR}"],
    ):
        fini = subprocess.run(
            ["git", *args], capture_output=True, text=True, timeout=600
        )
        if fini.returncode:
            return course.etape(
                "retour",
                False,
                f"git {next(a for a in args if a[0] != '-' and a != clone)}:"
                f" {fini.stderr.strip()[-300:]}",
            )
    try:
        _etat, pr = client.assurer_pull_request(
            proprietaire, depot, BRANCHE_RETOUR, base, "Long test: merge back"
        )
        numero = int(pr["number"])
        chemin = (
            f"/repos/{client._q(proprietaire)}/{client._q(depot)}"
            f"/pulls/{numero}/merge"
        )
        for essai in range(ESSAIS_FUSION):
            try:
                client._appel(
                    "POST",
                    chemin,
                    ok=(200,),
                    attendu=object,
                    json={"Do": "merge"},
                )
                break
            except fc.ErreurForgejo as exc:
                if exc.statut != 405 or essai == ESSAIS_FUSION - 1:
                    raise
                time.sleep(pause)
        prs = fpr.lire(
            client, proprietaire, depot, fpr.branches_locales(clone), base
        )
    except (fc.ErreurForgejo, KeyError, TypeError, ValueError) as exc:
        return course.etape("retour", False, str(exc))
    lue = next((p for p in prs if p["numero"] == numero), {})
    resultat = fpr.rapatrier(clone, "forge", base)
    local = bool(lue) and fpr.deja_local(clone, lue)
    course.rapport["retour"] = {
        "pr": numero,
        "etat": lue.get("etat"),
        "rapatriement": resultat["etat"],
        "local": local,
    }
    return course.etape(
        "retour",
        lue.get("etat") == "fusionnee"
        and resultat["etat"] == "avance"
        and local,
        f"#{numero} {lue.get('etat')}, {resultat['etat']}"
        f" {resultat['detail']}".rstrip(),
    )


def ci(course, client, cible, head, attente=ATTENTE_CI, pause=PAUSE_CI):
    """L'étape « ci » sur `cible`, la cible ERPLibre poussée avec
    `specs_ci` ; None fait échouer l'étape.

    Actions s'active sur le dépôt, puis la pull request de `BRANCHE_CI`
    vers `BRANCHE_CI_BASE` s'ouvre (ou se reprend). Le statut combiné de
    `head` se relit toutes les `pause` secondes jusqu'à « succes » ou
    « echec », `attente` secondes au plus. Réussie sur « succes » ; le
    rapport garde la pull request, l'état et chaque statut."""
    from script.git import forge_pull_requests as fpr

    if cible is None:
        return course.etape("ci", False, "ERPLibre was not pushed")
    proprietaire, depot = cible["proprietaire"], cible["depot"]
    try:
        client.assurer_actions(proprietaire, depot)
        _etat, pr = client.assurer_pull_request(
            proprietaire, depot, BRANCHE_CI, BRANCHE_CI_BASE, "CI long test"
        )
        numero = int(pr["number"])
        fin = time.time() + attente
        while True:
            statut = client.statut_combine(proprietaire, depot, head)
            etat = fpr.etat_ci(statut)
            if etat in ("succes", "echec") or time.time() >= fin:
                break
            time.sleep(pause)
    except (fc.ErreurForgejo, KeyError, TypeError, ValueError) as exc:
        return course.etape("ci", False, str(exc))
    resume, url = fc.detail_statut(statut)
    course.rapport["ci"] = {
        "pr": numero,
        "etat": etat,
        "statuts": [
            {k: s.get(k) for k in ("context", "state", "target_url")}
            for s in (statut or {}).get("statuses") or []
            if isinstance(s, dict)
        ],
    }
    return course.etape(
        "ci", etat == "succes", f"#{numero} {etat} {resume} {url}".strip()
    )


def ci_push(course, client, cible, shas, attente=ATTENTE_CI_PUSH):
    """L'étape « ci_push » : après `attente` secondes, aucun des commits
    `shas`, poussés dans le dépôt ERPLibre de la forge hors de toute pull
    request, ne porte de statut. Un statut prouverait qu'un push lance le
    workflow."""
    if cible is None or not shas:
        return course.etape("ci_push", False, "no pushed commit to check")
    time.sleep(attente)
    porteurs = []
    try:
        for sha in shas:
            statut = client.statut_combine(
                cible["proprietaire"], cible["depot"], sha
            )
            if (statut or {}).get("statuses"):
                porteurs.append(sha[:12])
    except (fc.ErreurForgejo, ValueError) as exc:
        return course.etape("ci_push", False, str(exc))
    return course.etape(
        "ci_push",
        not porteurs,
        f"{len(shas)} commits"
        + (f", statuts sur {porteurs}" if porteurs else ", aucun statut"),
    )


def branche_de_suivi(existe, poussee):
    """La branche d'ERPLibre que le miroir suit : develop ou master, la
    première dont `existe(branche)` est vrai (refs/remotes/origin/…), et
    jamais la branche `poussee`. Celle-ci est la base que l'étape
    « retour » fait avancer d'un commit de fusion absent de l'origine :
    suivie, elle serait « divergent » dès que l'origine bouge, et la
    synchro échouerait sur un minuteur correct. Rend None sans autre
    branche."""
    for b in ("develop", "master"):
        if b != poussee and existe(b):
            return b
    return None


def miroirs(course, client, forge, erplibre, clones, journal, dossier):
    """Les étapes « miroirs » et « synchro » ; rend le verdict.

    « miroirs » : le minuteur installé sur la forge, puis un miroir natif
    pour ERPLibre et pour chaque cible `clones` (les résultats du push),
    leurs organisations créées, et l'attente de leur clone initial.
    « synchro » : trois branches de cas (`CAS_SYNCHRO`) bâties dans un
    clone superficiel du miroir d'ERPLibre et poussées sans force dans
    son dépôt de travail, la configuration écrite, une passe lancée, puis
    chaque résultat comparé à l'attendu par l'API de la forge."""
    from script.git import forge_mirror

    cible = f"{forge_vm.UTILISATEUR}@{forge['ip']}"
    if erplibre is None:
        return course.etape("miroirs", False, "ERPLibre was not pushed")
    if not forge_vm.installer_synchro(cible, journal, ADMIN):
        return course.etape(
            "miroirs", False, f"timer not installed: {journal}"
        )
    origine = forge_mirror.url_origine(
        git_hote_dans(RACINE, "remote", "get-url", "origin")
    )
    branche = branche_de_suivi(
        lambda b: git_hote_dans(
            RACINE, "rev-parse", "--verify", "-q", f"refs/remotes/origin/{b}"
        ),
        erplibre["branche"],
    )
    if not branche:
        return course.etape("miroirs", False, "no branch of origin to follow")
    racine = {
        "nom": erplibre["depot"],
        "proprietaire": erplibre["proprietaire"],
        "affiche": "ERPLibre",
        "origine": origine,
        "branches": [{"travail": branche, "miroir": branche, "creer": True}],
    }
    # L'origine d'un clone est le remote de son manifeste, lu dans les
    # fichiers sans surcouche de forge, comme le menu la lit.
    os.chdir(RACINE)
    remotes = forge_mirror.remotes_d_origine()
    actifs = {
        os.path.join(RACINE, q["chemin"]): q
        for q in push_remote.projets_actifs()
    }
    projets = [
        dict(actifs[c["chemin"]], affiche=c["nom"])
        for c in clones
        if c["chemin"] in actifs
    ]
    interdits = (
        forge_mirror.proprietaires_connus(remotes)
        | {erplibre["proprietaire"], ADMIN}
        | {c["proprietaire"] for c in clones}
    )
    paires, ecartes = forge_mirror.plan_miroirs(
        [racine] + projets, remotes, interdits
    )
    for p, motif in ecartes:
        course.dire(f"  écarté : {p.get('affiche')} : {motif}")
    paires = [p for p in paires if forge_mirror.origine_publique(p["origine"])]
    if not paires or paires[0]["projet"] is not racine:
        return course.etape(
            "miroirs", False, "the ERPLibre origin is not readable anonymously"
        )
    try:
        orgs = fc.organisations_requises(
            p["miroir"].split("/")[0] for p in paires
        )
        natures = fc.plan_proprietaires(client, orgs)
        fc.assurer_organisations(
            client, [o for o, n in natures.items() if n == "absent"]
        )
        for p in paires:
            org, nom = p["miroir"].split("/")
            etat, _ = client.assurer_miroir(org, nom, p["origine"])
            course.dire(f"  miroir {p['miroir']} : {etat}")
        fin = time.time() + ATTENTE_MIROIRS
        vides = list(paires)
        while vides and time.time() < fin:
            vides = [
                p
                for p in vides
                if (client.depot(*p["miroir"].split("/")) or {}).get(
                    "empty", True
                )
            ]
            if vides:
                time.sleep(PAUSE_MIROIR)
    except fc.ErreurForgejo as exc:
        return course.etape("miroirs", False, str(exc))
    course.rapport["miroirs"] = {
        "organisations": orgs,
        "paires": [p["depot"] for p in paires],
    }
    if not course.etape(
        "miroirs",
        not vides,
        f"{len(paires)} miroirs"
        + (f", vides : {[p['miroir'] for p in vides]}" if vides else ""),
    ):
        return False
    return synchro(course, client, cible, paires, branche, journal, dossier)


def synchro(course, client, cible, paires, branche, journal, dossier):
    """L'étape « synchro » sur `paires` (la première est ERPLibre, suivie
    sur `branche`) ; voir `miroirs`."""
    from script.git import forge_mirror

    racine = paires[0]
    proprio, depot = racine["depot"].split("/")
    org, nom = racine["miroir"].split("/")
    url_miroir = push_remote.url_cible(forge_base_ssh(cible), org, nom)
    url_travail = push_remote.url_cible(forge_base_ssh(cible), proprio, depot)
    clone = os.path.join(dossier, "miroir")
    identite = [
        "-c",
        "user.name=forge-longtest",
        "-c",
        "user.email=forge-longtest@example.invalid",
    ]

    def git(*args):
        fini = subprocess.run(
            ["git", *identite, *args],
            capture_output=True,
            text=True,
            timeout=600,
        )
        if fini.returncode:
            commande = next(a for a in args if a[0] != "-" and a != clone)
            raise RuntimeError(f"git {commande}: {fini.stderr.strip()[-300:]}")
        return fini.stdout.strip()

    try:
        git(
            "clone",
            "-q",
            "--depth",
            "3",
            "--no-tags",
            "--branch",
            branche,
            url_miroir,
            clone,
        )
        tete = git("-C", clone, "rev-parse", "HEAD")
        avant = git("-C", clone, "rev-parse", "HEAD~1")
        arbre = git("-C", clone, "rev-parse", "HEAD^{tree}")
        en_avance = git(
            "-C",
            clone,
            "commit-tree",
            arbre,
            "-p",
            tete,
            "-m",
            "Long test: ahead of the mirror",
        )
        divergent = git(
            "-C",
            clone,
            "commit-tree",
            arbre,
            "-p",
            avant,
            "-m",
            "Long test: diverged from the mirror",
        )
        poses = {
            "longtest-ff": avant,
            "longtest-ahead": en_avance,
            "longtest-div": divergent,
        }
        # Un second essai, comme le push parallèle : sous charge, le serveur
        # SSH de Forgejo coupe parfois la session avant d'avoir rendu le
        # statut des références (« remote failed to report status »).
        # Répéter le push est sans effet de bord : une référence déjà posée
        # est à jour, les autres le deviennent.
        for essai in (1, 2):
            try:
                git(
                    "-C",
                    clone,
                    "push",
                    "-q",
                    url_travail,
                    *(f"{sha}:refs/heads/{b}" for b, sha in poses.items()),
                )
                break
            except RuntimeError:
                if essai == 2:
                    raise
                time.sleep(PAUSE_PUSH)
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        return course.etape("synchro", False, str(exc))
    racine["branches"] += [
        {"travail": b, "miroir": branche, "creer": False} for b in CAS_SYNCHRO
    ]
    if not forge_vm.ecrire_config_synchro(
        cible, forge_mirror.config_synchro(paires), journal
    ):
        return course.etape("synchro", False, f"config refused: {journal}")
    precedent = (forge_vm.lire_etat_synchro(cible) or {}).get("etat") or {}
    code = forge_vm.lancer_passe(cible, journal)
    etat = (forge_vm.lire_etat_synchro(cible) or {}).get("etat") or {}
    faux = verifier_synchro(
        etat, precedent, racine["depot"], tete, poses, client, proprio, depot
    )
    course.rapport["synchro"] = {
        "code": code,
        "pousses": [tete, *poses.values()],
        "resultats": [
            {k: r.get(k) for k in ("depot", "branche", "etat", "detail")}
            for r in etat.get("resultats", [])
        ],
    }
    for ligne in faux:
        course.dire(f"  ✗ {ligne}")
    return course.etape(
        "synchro",
        not faux,
        f"{len(etat.get('resultats', []))} branches, code {code}",
    )


def verifier_synchro(etat, precedent, depot, tete, poses, client, o, r):
    """Les écarts d'une passe à l'attendu, [] si aucun : une passe neuve,
    chaque cas de `CAS_SYNCHRO` dans son état, « longtest-ff » avancé
    jusqu'à `tete` et « longtest-div » laissé sur son commit (lus par
    l'API), toute autre branche à jour, avancée, en avance ou divergente.

    Une branche de clone porte ce que le checkout de l'hôte a poussé : des
    commits locaux absents de l'origine la rendent divergente, et c'est
    alors l'état juste. Qu'une divergente ne soit jamais écrasée se vérifie
    sur « longtest-div », dont le commit est connu."""
    faux = []
    if not etat.get("debut") or etat.get("debut") == precedent.get("debut"):
        faux.append("no new pass")
    for res in etat.get("resultats", []):
        attendu = (
            CAS_SYNCHRO.get(res.get("branche"))
            if res.get("depot") == depot
            else None
        )
        permis = (
            {attendu}
            if attendu
            else {"a_jour", "avance", "en_avance", "creee", "divergent"}
        )
        if res.get("etat") not in permis:
            faux.append(
                f"{res.get('depot')} {res.get('branche')}: {res.get('etat')}"
                f" {res.get('detail', '')}".rstrip()
            )
    vus = {
        res.get("branche")
        for res in etat.get("resultats", [])
        if res.get("depot") == depot
    }
    faux += [f"{b}: no result" for b in CAS_SYNCHRO if b not in vus]
    for b, attendu in (
        ("longtest-ff", tete),
        ("longtest-div", poses["longtest-div"]),
    ):
        lu = client.commit_de_branche(o, r, b)
        if lu != attendu:
            faux.append(f"{b}: {lu} ≠ {attendu}")
    return faux


def forge_base_ssh(cible):
    """La base SSH des dépôts de la forge de `cible` (« user@ip »)."""
    return forge_vm.urls(cible.split("@", 1)[1])[1]


def branche_distante(chemin, remote, branche):
    """Le commit de refs/heads/`branche` sur `remote`, lu par « git
    ls-remote » depuis le clone `chemin`, ou None."""
    try:
        fini = subprocess.run(
            [
                "git",
                "-C",
                chemin,
                "ls-remote",
                remote,
                f"refs/heads/{branche}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    ligne = fini.stdout.split()
    return ligne[0] if fini.returncode == 0 and ligne else None


def git_hote_dans(chemin, *args):
    fini = subprocess.run(
        ["git", "-C", chemin, *args],
        capture_output=True,
        text=True,
        timeout=120,
    )
    return fini.stdout.strip() if fini.returncode == 0 else None


def dernier_rapport():
    """(chemin, rapport) du rapport le plus récent qui nomme une VM, ou
    (None, {})."""
    dossier = os.path.expanduser("~/.erplibre/longtest")
    try:
        noms = sorted(
            f
            for f in os.listdir(dossier)
            if f.startswith(NOM_BASE + "-") and f.endswith(".json")
        )
    except OSError:
        return None, {}
    for nom in reversed(noms):
        chemin = os.path.join(dossier, nom)
        try:
            with open(chemin, encoding="utf-8") as fh:
                rapport = json.load(fh)
        except (OSError, ValueError):
            continue
        if rapport.get("vm") and not rapport.get("detruite"):
            return chemin, rapport
    return None, {}


def detruire(dry_run=False):
    """Défait la VM du dernier rapport, par son UUID. Refuse tant qu'un
    test long tourne : sa course peut être celle du dernier rapport."""
    autres = autre_descente()
    if autres:
        dire(
            f"⛔ un test long tourne ({', '.join(map(str, autres))}) :"
            " rien ne sera défait."
        )
        return 1
    chemin, rapport = dernier_rapport()
    if not rapport:
        dire("rien à défaire")
        return 0
    vm = rapport["vm"]
    dire(f"défaire {vm['nom']} ({vm.get('uuid', '?')})")
    detruire_etage1(None, vm["nom"], dry_run=dry_run, attendu=vm.get("uuid"))
    if not dry_run:
        rapport["detruite"] = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(chemin, "w", encoding="utf-8") as fh:
            json.dump(rapport, fh, indent=1, ensure_ascii=False)
    return 0


def main(argv=None):
    parseur = argparse.ArgumentParser(
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument("--detruire", action="store_true")
    parseur.add_argument(
        "--projets",
        type=int,
        help="Push only the first N clones (default: all of them).",
    )
    parseur.add_argument("--jobs", type=int, default=push_remote.PARALLELE)
    parseur.add_argument(
        "--miroirs",
        type=int,
        default=0,
        metavar="K",
        help=(
            "After the push, mirror ERPLibre and K clones on the forge and"
            " check the fast-forward timer (default: 0, off)."
        ),
    )
    parseur.add_argument(
        "--ci",
        action="store_true",
        help=(
            "Also install the CI runner, open a pull request between HEAD~1"
            " and HEAD on the ERPLibre repository and wait for its unit"
            " tests; the workflow must be committed."
        ),
    )
    args = parseur.parse_args(argv)
    if args.detruire:
        return detruire(args.dry_run)
    return mener(args)


if __name__ == "__main__":
    sys.exit(main())
