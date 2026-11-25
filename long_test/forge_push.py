#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Une forge Forgejo déployée dans une VM reçoit-elle le projet actuel ?

Le test crée une VM QEMU, y dépose le code de CE checkout (un bundle git :
la VM ne joint jamais GitHub pour le code), n'y installe d'ERPLibre que
.venv.erplibre — pas d'Odoo —, puis lance l'installateur Forgejo du dépôt
avec push-to-create, inscriptions fermées, dépôts privés par défaut et push
de clone superficiel accepté. Il amorce ensuite la forge par son API : un
jeton créé avec le mot de passe administrateur, la clé SSH publique déposée,
chaque organisation propriétaire créée privée. Enfin il pousse, en
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
import secrets
import shlex
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from descente import (  # noqa: E402
    Descente,
    cle_publique,
    detruire_etage1,
    dire,
    drapeaux_cache,
)

from script.git import forgejo_client as fc  # noqa: E402
from script.git import push_remote  # noqa: E402

OUTIL = "forge_push"
NOM_BASE = "forge-push"
UTILISATEUR = "erplibre"
DISTRO, VERSION = "ubuntu", "24.04"
VCPUS = 4
MEMOIRE_MO = 4096
DISQUE_GO = 60
PORT_HTTP = 3000
PORT_SSH = 2222
# Un compte dont le nom ne recouvre aucun propriétaire du manifeste : Forgejo
# compare les noms sans égard à la casse, et un compte « erplibre »
# empêcherait l'organisation « ERPLibre ».
ADMIN = "forge-longtest"
PORTEES = ("write:organization", "write:repository", "write:user")

DELAI_CREATION = 1800
DELAI_SSH = 900
DELAI_CODE = 900
DELAI_INSTALL = 3600
DELAI_PUSH = 1800

OPTIONS_SSH = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    "-o",
    "LogLevel=ERROR",
]
ETAPES = (
    "vm",
    "ssh",
    "code",
    "venv",
    "forgejo",
    "api",
    "push",
    "verification",
)


def chemins_de_course(horodatage):
    """(rapport, journal, dossier) de la course, sous ~/.erplibre/longtest."""
    base = os.path.expanduser(f"~/.erplibre/longtest/{NOM_BASE}-{horodatage}")
    os.makedirs(os.path.dirname(base), exist_ok=True)
    return base + ".json", base + ".log", base


def depot_de_l_url(url):
    """(propriétaire, dépôt sans « .git ») d'une URL de dépôt git, quelle
    qu'en soit la forme ; None sans au moins deux segments."""
    url = (url or "").strip().rstrip("/")
    if url.endswith(".git"):
        url = url[: -len(".git")]
    if "://" in url:
        chemin = url.split("://", 1)[1].partition("/")[2]
    elif ":" in url:
        chemin = url.split(":", 1)[1]
    else:
        chemin = url
    segments = [s for s in chemin.split("/") if s]
    if len(segments) < 2:
        return None
    return segments[-2], segments[-1]


def argv_creation(nom, cle_pub):
    """La ligne de deploy_qemu.py, sans « sudo »."""
    argv = [
        os.path.join(RACINE, ".venv.erplibre/bin/python"),
        os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
        "--distro",
        DISTRO,
        "--version",
        VERSION,
        "--name",
        nom,
        "--vcpus",
        str(VCPUS),
        "--memory",
        str(MEMOIRE_MO),
        "--disk-size",
        f"{DISQUE_GO}G",
        "--no-upgrade",
    ]
    if cle_pub:
        argv += ["--ssh-key", cle_pub]
    return argv + drapeaux_cache()


def commande_forgejo():
    """La commande distante qui installe Forgejo depuis le checkout de la
    VM. Le mot de passe administrateur arrive par l'entrée standard : il
    n'apparaît ni dans la ligne de commande ni dans le journal."""
    reglages = {
        "FORGEJO_ADMIN_USER": ADMIN,
        "FORGEJO_HTTP_PORT": str(PORT_HTTP),
        "FORGEJO_SSH_PORT": str(PORT_SSH),
        "FORGEJO_PUSH_CREATE": "1",
        "FORGEJO_DISABLE_REGISTRATION": "1",
        "FORGEJO_DEFAULT_PRIVATE": "1",
        "FORGEJO_SHALLOW_PUSH": "1",
    }
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in reglages.items())
    return (
        "IFS= read -r FORGEJO_ADMIN_PASSWORD && export FORGEJO_ADMIN_PASSWORD"
        f" && cd ~/git/erplibre && env {exports}"
        " ./script/forgejo/install_forgejo.sh"
    )


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


def _ssh(cible, commande, journal, delai, entree=None):
    """Lance `commande` dans la VM, sortie au journal. Rend le code, ou
    None si elle n'a pas abouti dans son délai."""
    try:
        with open(journal, "a", encoding="utf-8") as fh:
            fh.write(f"── ssh {cible} {commande}\n")
            fh.flush()
            fini = subprocess.run(
                ["ssh", *OPTIONS_SSH, cible, commande],
                input=entree,
                text=True,
                stdout=fh,
                stderr=subprocess.STDOUT,
                timeout=delai,
            )
    except (OSError, subprocess.SubprocessError) as souci:
        dire(f"  ✗ ssh interrompu : {souci}", journal)
        return None
    return fini.returncode


def attendre_ssh(cible, delai=DELAI_SSH):
    """Vrai dès qu'une commande aboutit en ssh : le port s'ouvre avant que
    cloud-init ait posé le compte."""
    fin = time.time() + delai
    while time.time() < fin:
        try:
            fini = subprocess.run(
                ["ssh", *OPTIONS_SSH, cible, "true"],
                capture_output=True,
                timeout=30,
            )
            if fini.returncode == 0:
                return True
        except (OSError, subprocess.SubprocessError):
            pass
        time.sleep(5)
    return False


def adresse_de(nom):
    """L'IPv4 de la VM d'après son bail DHCP, ou ""."""
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)._qemu_vm_ip(nom, timeout=DELAI_SSH) or ""


def git_hote(*args, delai=600):
    """(code, sortie) de git sur le checkout de l'hôte."""
    fini = subprocess.run(
        ["git", "-C", RACINE, *args],
        capture_output=True,
        text=True,
        timeout=delai,
    )
    return fini.returncode, fini.stdout.strip()


# Les fichiers que le test exerce, copiés tels qu'ils sont dans l'arbre de
# travail par-dessus le clone du bundle : c'est notre code qu'on veut voir
# tourner, commité ou non.
EXERCES = ("script/forgejo/install_forgejo.sh",)


def deposer_code(course, cible, dossier):
    """Le bundle de HEAD copié dans la VM et cloné dans ~/git/erplibre,
    puis les fichiers d'EXERCES de l'arbre de travail par-dessus."""
    code, head = git_hote("rev-parse", "HEAD")
    bundle = os.path.join(dossier, "erplibre.bundle")
    os.makedirs(dossier, exist_ok=True)
    if code or git_hote("bundle", "create", bundle, "HEAD")[0]:
        return False
    for argv in (
        [
            "ssh",
            *OPTIONS_SSH,
            cible,
            "command -v git >/dev/null || sudo DEBIAN_FRONTEND=noninteractive apt-get -o DPkg::Lock::Timeout=600 install -y git",
        ],
        ["scp", *OPTIONS_SSH, bundle, f"{cible}:erplibre.bundle"],
        [
            "ssh",
            *OPTIONS_SSH,
            cible,
            "test -e ~/git/erplibre || { mkdir -p ~/git && git -c"
            " advice.detachedHead=false clone -q ~/erplibre.bundle ~/git/erplibre"
            f" && git -C ~/git/erplibre checkout -q {head}; }}",
        ],
        *(
            [
                "scp",
                *OPTIONS_SSH,
                os.path.join(RACINE, f),
                f"{cible}:git/erplibre/{f}",
            ]
            for f in EXERCES
        ),
    ):
        try:
            with open(course.journal, "a", encoding="utf-8") as fh:
                fini = subprocess.run(
                    argv,
                    stdout=fh,
                    stderr=subprocess.STDOUT,
                    timeout=DELAI_CODE,
                )
        except (OSError, subprocess.SubprocessError):
            return False
        if fini.returncode:
            return False
    return True


def mener(args):
    horodatage = time.strftime("%Y%m%d-%H%M%S")
    chemin, journal, dossier = chemins_de_course(horodatage)
    course = Course(chemin, journal, args)
    nom = f"{NOM_BASE}-{horodatage[2:8]}-{horodatage[9:13]}"
    cle_pub = cle_publique()
    if not cle_pub:
        course.dire("✗ aucune clé publique dans ~/.ssh")
        return 1

    os.chdir(RACINE)
    projets = push_remote.projets_actifs()
    if args.projets is not None:
        projets = projets[: args.projets]
    _, origine_url = git_hote("remote", "get-url", "origin")
    origine = depot_de_l_url(origine_url)
    _, branche = git_hote("rev-parse", "--abbrev-ref", "HEAD")
    branche = branche if branche and branche != "HEAD" else "main"
    _, head = git_hote("rev-parse", "HEAD")
    course.dire(
        f"plan : VM {nom} ({DISTRO} {VERSION}, {VCPUS} vCPU, {MEMOIRE_MO} Mo,"
        f" {DISQUE_GO} Go) ; ERPLibre ({branche}) et {len(projets)} clones"
    )
    if args.dry_run:
        course.dire(
            "  "
            + " ".join(
                shlex.quote(a) for a in ["sudo"] + argv_creation(nom, cle_pub)
            )
        )
        course.ecrire()
        return 0

    # 1. La VM.
    if Descente.uuid_libvirt(nom):
        course.etape("vm", False, f"{nom} existe déjà")
        return 1
    try:
        fini = subprocess.run(
            ["sudo"] + argv_creation(nom, cle_pub),
            timeout=DELAI_CREATION,
            stdin=subprocess.DEVNULL,
        )
        cree = fini.returncode == 0
    except (OSError, subprocess.SubprocessError) as souci:
        cree = False
        course.dire(f"  création interrompue : {souci}")
    uuid = Descente.uuid_libvirt(nom)
    if uuid:
        course.rapport["vm"] = {"nom": nom, "uuid": uuid}
    if not course.etape("vm", cree and uuid, nom):
        return 1

    # 2. SSH.
    ip = adresse_de(nom)
    cible = f"{UTILISATEUR}@{ip}"
    if not course.etape("ssh", ip and attendre_ssh(cible), ip):
        return 1
    course.rapport["vm"]["ip"] = ip

    # 3. Le code, puis 4. .venv.erplibre seul, puis 5. Forgejo.
    if not course.etape("code", deposer_code(course, cible, dossier)):
        return 1
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    venv = "cd ~/git/erplibre && " + TODO._QEMU_ERPLIBRE_VENV_CMD
    if not course.etape(
        "venv", _ssh(cible, venv, journal, DELAI_INSTALL, entree="") == 0
    ):
        return 1
    mot_de_passe = secrets.token_urlsafe(24)
    code = _ssh(
        cible,
        commande_forgejo(),
        journal,
        DELAI_INSTALL,
        entree=mot_de_passe + "\n",
    )
    if not course.etape("forgejo", code == 0):
        return 1

    # 6. L'API : jeton, clé SSH, organisations.
    web = f"http://{ip}:{PORT_HTTP}"
    try:
        amorce = fc.ClientForgejo(web, identifiants=(ADMIN, mot_de_passe))
        jeton = amorce.creer_jeton(f"{NOM_BASE}-{horodatage}", PORTEES)
        client = fc.ClientForgejo(web, jeton_api=jeton)
        version = client.version()
        with open(cle_pub, encoding="utf-8") as fh:
            client.ajouter_cle_ssh(f"{NOM_BASE}-{horodatage}", fh.read())
        base_ssh = f"ssh://git@{ip}:{PORT_SSH}"
        cibles, ecartes = cibles_du_projet(
            projets, base_ssh, head, origine, branche
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
        course.etape("api", False, str(exc))
        return 1
    if not course.etape(
        "api",
        not erreurs,
        f"Forgejo {version}, {len(natures)} propriétaires, {len(absentes)} créés"
        + (f", erreurs {erreurs}" if erreurs else ""),
    ):
        return 1
    for chemin_clone, motif in ecartes:
        course.dire(f"  écarté : {chemin_clone} : {motif}")

    # 7. Le push, en parallèle, sans force, par SSH avec la clé déposée.
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

    # 8. La forge porte-t-elle chaque commit poussé ? Lu par « git
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
    """Défait la VM du dernier rapport, par son UUID."""
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
