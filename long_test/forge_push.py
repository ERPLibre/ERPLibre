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

Aucun clone de l'hôte n'est modifié : le push vise une URL, aucun remote
n'est ajouté. Le mot de passe administrateur est tiré au hasard, passé par
l'entrée standard et jamais écrit ; le jeton ne vit que dans le processus.

Le rapport (~/.erplibre/longtest/forge-push-<horodatage>.json) nomme la VM
et son UUID ; `--detruire` défait la VM du dernier rapport, et elle seule.

  ./long_test/forge_push.py                  # toute la course
  ./long_test/forge_push.py --projets 5      # le dépôt ERPLibre et 5 clones
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
ETAPES = forge_vm.ETAPES + ("organisations", "push", "verification")


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
EXERCES = ("script/forgejo/install_forgejo.sh",)


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
    if args.dry_run:
        argv = forge_vm.argv_creation(nom, cle_pub, drapeaux_cache())
        course.dire("  " + " ".join(shlex.quote(a) for a in ["sudo"] + argv))
        course.ecrire()
        return 0

    # 1 à 6. La VM, SSH, le code, .venv.erplibre seul, Forgejo, l'amorçage
    # de l'API (jeton, clé SSH). Le rapport nomme la VM dès qu'elle existe,
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
    )
    if forge is None:
        return 1
    client, web = forge["client"], forge["web"]

    # 7. Les organisations propriétaires, créées privées.
    try:
        cibles, ecartes = cibles_du_projet(
            projets, forge["base_ssh"], head, origine, branche
        )
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
    course.rapport["fin"] = time.strftime("%Y-%m-%d %H:%M:%S")
    course.ecrire()
    course.dire(f"rapport : {chemin}")
    course.dire(f"forge : {web} (VM gardée : --detruire la défait)")
    return 0 if ok else 1


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
    args = parseur.parse_args(argv)
    if args.detruire:
        return detruire(args.dry_run)
    return mener(args)


if __name__ == "__main__":
    sys.exit(main())
