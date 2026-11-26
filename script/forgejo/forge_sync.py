#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)

"""Avance, sur l'hôte de la forge, chaque dépôt de travail jusqu'à son
miroir, en fast-forward seulement.

Chaque paire de la configuration lie un dépôt de travail
« <propriétaire>/<dépôt> », qui reçoit les pushes et les pull requests, à
son miroir natif Forgejo « <propriétaire>-mirror/<dépôt> », en lecture
seule, que la forge rafraîchit depuis l'origine. Pour chaque branche
suivie, une passe lit les deux pointes directement dans les dépôts nus de
la forge (`chemin_disque`), puis pousse la pointe du miroir vers le dépôt
de travail PAR LA FORGE, en HTTP local : ses hooks tournent et les bases
des pull requests se mettent à jour.

Le push n'est jamais forcé : ni « + » dans la refspec, ni « --force »,
ni « --force-with-lease ». git refuse alors, côté client, une pointe
annoncée par la forge qui n'est pas un ancêtre du commit poussé dans le
dépôt du miroir : une branche qui a divergé n'est jamais réécrite, elle
est notée « divergent », avec la date où la divergence a été vue la
première fois (« depuis »). Un dépôt de travail absent du disque ne reçoit
rien : le push-to-create de la forge le créerait.

Le module tourne sous le compte système de Forgejo, lancé par
« python3 -I » depuis une unité systemd ; il n'importe que la bibliothèque
standard. Le jeton arrive par `$CREDENTIALS_DIRECTORY/token` (systemd
`LoadCredential=`) et ne passe à git que par les variables
`GIT_CONFIG_COUNT/KEY/VALUE` : ni ligne de commande, ni URL, ni journal.
L'URL de la forge, la racine des dépôts et le compte viennent d'un fichier
d'environnement sans secret.

  forge_sync.py passe              # une passe (le service systemd)
  forge_sync.py configurer < json  # fusionne des paires (root)
  forge_sync.py retirer O/D...     # retire des paires (root)
  forge_sync.py etat               # configuration et dernière passe, en JSON
"""

import base64
import fcntl
import json
import os
import re
import subprocess
import sys
import time

CONF_DIR = "/etc/erplibre-forge-sync"
CONFIG = CONF_DIR + "/config.json"
JETON = CONF_DIR + "/token"
ENVIRONNEMENT = CONF_DIR + "/environment"
ETAT_DIR = "/var/lib/erplibre-forge-sync"
ETAT = ETAT_DIR + "/etat.json"
VERROU = ETAT_DIR + "/verrou"
SUFFIXE = "-mirror"
ETATS = (
    "a_jour",
    "avance",
    "creee",
    "en_avance",
    "divergent",
    "absente",
    "absente_miroir",
    "depot_absent",
    "refuse",
    "erreur",
)
# Les états qui font rendre 1 à une passe ; une divergence ou une absence
# est un constat, pas une panne.
ECHECS = ("refuse", "erreur")
DELAI_GIT = 600
DELAI_PUSH = 3600
PAIRES_MAX = 2000

_FORGE_LOCALE = re.compile(
    r"^http://(127\.0\.0\.1|localhost|\[::1\]):\d{1,5}$"
)
_FORGE = re.compile(r"^(?:https?|file)://\S+[^/\s]$")
_PROPRIETAIRE = re.compile(r"^[A-Za-z0-9][-.\w]{0,39}$", re.ASCII)
_DEPOT = re.compile(r"^[-.\w]{1,100}$", re.ASCII)
_BRANCHE_INTERDIT = re.compile(r"\.\.|//|@\{|[\x00-\x20\x7f~^:?*\[\\]")


# ── Validation ───────────────────────────────────────────────────────


def forge_valide(url, locale=True):
    """Vrai pour l'URL de la forge sans « / » final. `locale` n'admet que
    « http://127.0.0.1|localhost|[::1]:<port> » : le push ne sort jamais
    de l'hôte. Sans `locale` (les tests), http(s):// et file:// passent."""
    motif = _FORGE_LOCALE if locale else _FORGE
    return isinstance(url, str) and bool(motif.match(url))


def branche_valide(nom):
    """Vrai pour un nom de branche que la passe accepte de passer à git :
    ni vide, ni « - » ou « / » en tête (une option, un chemin absolu), ni
    « .. », « // », « @{ », blanc, caractère de contrôle ou l'un de
    « ~^:?*[\\ », ni « / », « . » ou « .lock » final."""
    return (
        isinstance(nom, str)
        and bool(nom)
        and nom[0] not in "-/"
        and not _BRANCHE_INTERDIT.search(nom)
        and not nom.endswith(("/", ".", ".lock"))
    )


def _depot_valide(texte):
    """(propriétaire, dépôt) de « propriétaire/dépôt », ou None. Les deux
    motifs ferment aussi la traversée de chemin sous la racine des
    dépôts : ni « / » de plus, ni « . » ou « .. » seul."""
    if not isinstance(texte, str) or texte.count("/") != 1:
        return None
    proprietaire, depot = texte.split("/")
    if (
        not _PROPRIETAIRE.match(proprietaire)
        or not _DEPOT.match(depot)
        or depot in (".", "..")
        or depot.lower().endswith(".git")
    ):
        return None
    return proprietaire, depot


def valider(config):
    """Les erreurs de `config`, [] quand elle est valide : version 1, au
    plus `PAIRES_MAX` paires, chaque « depot » et « miroir » de la forme
    « propriétaire/dépôt », propriétaires distincts sans égard à la casse,
    celui du miroir seul à finir par `SUFFIXE`, et des « branches »
    {travail, miroir, creer} non vides, sans « travail » doublé."""
    if not isinstance(config, dict) or config.get("version") != 1:
        return ["version: 1 expected"]
    paires = config.get("paires")
    if not isinstance(paires, list):
        return ["paires: a list expected"]
    if len(paires) > PAIRES_MAX:
        return [f"paires: {PAIRES_MAX} at most"]
    erreurs = []
    for i, paire in enumerate(paires):
        ou = f"paires[{i}]"
        if not isinstance(paire, dict):
            erreurs.append(f"{ou}: an object expected")
            continue
        depot = _depot_valide(paire.get("depot"))
        miroir = _depot_valide(paire.get("miroir"))
        if depot is None:
            erreurs.append(f"{ou}: invalid depot {paire.get('depot')!r}")
        if miroir is None:
            erreurs.append(f"{ou}: invalid miroir {paire.get('miroir')!r}")
        if depot and miroir:
            proprio_t, proprio_m = depot[0].lower(), miroir[0].lower()
            if proprio_t == proprio_m:
                erreurs.append(f"{ou}: depot and miroir share their owner")
            if not proprio_m.endswith(SUFFIXE):
                erreurs.append(f"{ou}: the miroir owner must end in {SUFFIXE}")
            if proprio_t.endswith(SUFFIXE):
                erreurs.append(f"{ou}: the depot owner ends in {SUFFIXE}")
        branches = paire.get("branches")
        if not isinstance(branches, list) or not branches:
            erreurs.append(f"{ou}: branches must be a non-empty list")
            continue
        vues = set()
        for j, b in enumerate(branches):
            ici = f"{ou}.branches[{j}]"
            if not isinstance(b, dict):
                erreurs.append(f"{ici}: an object expected")
                continue
            for cle in ("travail", "miroir"):
                if not branche_valide(b.get(cle)):
                    erreurs.append(f"{ici}: invalid {cle} {b.get(cle)!r}")
            if not isinstance(b.get("creer"), bool):
                erreurs.append(f"{ici}: creer must be a boolean")
            if b.get("travail") in vues:
                erreurs.append(f"{ici}: travail {b.get('travail')!r} twice")
            vues.add(b.get("travail"))
    return erreurs


def fusionner(ancienne, nouvelle):
    """La configuration `ancienne` où chaque paire de `nouvelle` remplace
    celle du même « depot » (sans égard à la casse) ; les autres restent,
    dans leur ordre, les nouvelles s'ajoutent à la fin."""
    paires = {
        p["depot"].lower(): p
        for p in (ancienne or {}).get("paires", [])
        if isinstance(p, dict) and isinstance(p.get("depot"), str)
    }
    for p in nouvelle.get("paires", []):
        paires[p["depot"].lower()] = p
    return {"version": 1, "paires": list(paires.values())}


def retirer(config, depots):
    """`config` sans les paires dont le « depot » est l'un de `depots`,
    sans égard à la casse."""
    otes = {d.lower() for d in depots}
    return {
        "version": 1,
        "paires": [
            p
            for p in (config or {}).get("paires", [])
            if p.get("depot", "").lower() not in otes
        ],
    }


def lire_environnement(chemin=ENVIRONNEMENT, environ=None):
    """{forge, depots, compte} de `environ` (l'`EnvironmentFile` que
    systemd a chargé), complété par le fichier `chemin` (« CLE=valeur »
    par ligne) pour ce qui manque."""
    environ = os.environ if environ is None else environ
    cles = {
        "forge": "FORGE_SYNC_URL",
        "depots": "FORGE_SYNC_REPOS",
        "compte": "FORGE_SYNC_ACCOUNT",
    }
    fichier = {}
    try:
        with open(chemin, encoding="utf-8") as fh:
            for ligne in fh:
                cle, egal, valeur = ligne.strip().partition("=")
                if egal and not cle.startswith("#"):
                    fichier[cle.strip()] = valeur.strip().strip("\"'")
    except OSError:
        pass
    return {n: environ.get(v) or fichier.get(v, "") for n, v in cles.items()}


def chemin_disque(depots, nom):
    """Le dépôt nu de « propriétaire/dépôt » sous la racine `depots`, tel
    que Forgejo le range : propriétaire et dépôt en minuscules, « .git »
    ajouté."""
    proprietaire, depot = nom.split("/")
    return os.path.join(depots, proprietaire.lower(), depot.lower() + ".git")


# ── git, le jeton hors de la ligne de commande ───────────────────────


def _entete(compte, jeton):
    return "Authorization: Basic " + base64.b64encode(
        f"{compte}:{jeton}".encode()
    ).decode("ascii")


def environnement(forge, compte, jeton, home):
    """L'environnement de chaque commande git. Le jeton n'y est qu'en
    en-tête HTTP, limité aux URL qui commencent par `forge` ; ni la
    configuration système ni celle du compte ne s'appliquent, aucune
    invite n'est possible et aucun gestionnaire d'identifiants n'est
    consulté. `GIT_CONFIG_COUNT` demande git 2.31 au moins."""
    return {
        "PATH": os.environ.get("PATH") or "/usr/bin:/bin",
        "LC_ALL": "C",
        "HOME": home,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_COUNT": "2",
        "GIT_CONFIG_KEY_0": f"http.{forge}/.extraHeader",
        "GIT_CONFIG_VALUE_0": _entete(compte, jeton),
        "GIT_CONFIG_KEY_1": "credential.helper",
        "GIT_CONFIG_VALUE_1": "",
    }


def git(args, cwd, env, delai=DELAI_GIT):
    """(sortie, erreur, code) de « git <args> » dans `cwd` ; ne lève
    jamais : une commande qui n'aboutit pas rend le code 1."""
    try:
        fini = subprocess.run(
            ["git", *args],
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return "", str(exc), 1
    return fini.stdout, fini.stderr, fini.returncode


def masquer(texte, secrets):
    """`texte` où chaque secret non vide, et l'en-tête qui le porte en
    base64, devient « *** »."""
    for s in secrets:
        if s:
            texte = texte.replace(s, "***")
    return texte


# ── Une paire ────────────────────────────────────────────────────────


def _derniere_ligne(texte):
    lignes = [ligne for ligne in (texte or "").splitlines() if ligne.strip()]
    return lignes[-1].strip() if lignes else ""


def motif_refus(sortie, erreur):
    """Le motif d'un « git push --porcelain » refusé. git écrit l'état de
    chaque référence sur la sortie standard, et un refus y commence par
    « ! » : « !<tab>src:dst<tab>[rejected] (fetch first) ». Ce résumé, sans
    le « ! » ni les références, l'emporte ; à défaut, la dernière ligne
    « remote: » de l'erreur (le message d'un hook), puis sa dernière ligne.
    L'erreur seule se termine sur un conseil générique de git."""
    for ligne in (sortie or "").splitlines():
        if ligne.startswith("!"):
            champs = [c.strip() for c in ligne[1:].split("\t") if c.strip()]
            return " ".join(champs[1:] or champs)
    distantes = [
        ligne.strip()
        for ligne in (erreur or "").splitlines()
        if ligne.startswith("remote:") and ligne[len("remote:") :].strip()
    ]
    if distantes:
        return distantes[-1]
    return _derniere_ligne(erreur)


def passe_paire(paire, forge, depots, env, git=git, secrets=()):
    """Les résultats de chaque branche de `paire`, un dict par branche :
    « depot », « miroir », « branche » (de travail), « branche_miroir »,
    « etat » (l'un d'`ETATS`), « travail » et « miroir_sha » (les pointes
    lues, "" si absentes) et « detail ».

    Les pointes et les ancêtres se lisent dans les dépôts nus, en lecture
    seule ; le seul geste d'écriture est le push, lancé DEPUIS le dépôt du
    miroir vers « <forge>/<depot>.git », sans force."""
    rep_m = chemin_disque(depots, paire["miroir"])
    rep_t = chemin_disque(depots, paire["depot"])
    url_t = f"{forge}/{paire['depot']}.git"
    resultats = []

    def res(b, etat, t="", m="", detail=""):
        resultats.append(
            {
                "depot": paire["depot"],
                "miroir": paire["miroir"],
                "branche": b["travail"],
                "branche_miroir": b["miroir"],
                "etat": etat,
                "travail": t,
                "miroir_sha": m,
                "detail": masquer(detail, secrets),
            }
        )

    if not os.path.isdir(rep_t):
        for b in paire["branches"]:
            res(b, "depot_absent")
        return resultats
    if not os.path.isdir(rep_m):
        for b in paire["branches"]:
            res(b, "erreur", detail="mirror repository absent")
        return resultats

    def pointe(rep, branche):
        out, _err, code = git(
            [
                "rev-parse",
                "--verify",
                "-q",
                f"refs/heads/{branche}^{{commit}}",
            ],
            rep,
            env,
        )
        return out.strip() if code == 0 else ""

    def contient(rep, sha):
        return git(["cat-file", "-e", f"{sha}^{{commit}}"], rep, env)[2] == 0

    def ancetre(rep, a, b):
        return git(["merge-base", "--is-ancestor", a, b], rep, env)[2] == 0

    def pousser(m, branche):
        # Ni « + » ni option de force : git compare, côté client, la pointe
        # que la forge annonce au commit poussé dans le dépôt du miroir, et
        # refuse ce qui n'est pas un fast-forward. Une pointe qui a bougé
        # depuis sa lecture est ainsi refusée aussi.
        out, err, code = git(
            [
                "push",
                "--porcelain",
                "--no-verify",
                url_t,
                f"{m}:refs/heads/{branche}",
            ],
            rep_m,
            env,
            DELAI_PUSH,
        )
        return code, motif_refus(out, err) if code else ""

    for b in paire["branches"]:
        m = pointe(rep_m, b["miroir"])
        if not m:
            res(b, "absente_miroir")
            continue
        t = pointe(rep_t, b["travail"])
        if not t:
            if not b.get("creer"):
                res(b, "absente", m=m)
                continue
            code, err = pousser(m, b["travail"])
            res(
                b,
                "refuse" if code else "creee",
                m=m,
                detail=err if code else "",
            )
            continue
        if t == m:
            res(b, "a_jour", t, m)
        elif contient(rep_m, t) and ancetre(rep_m, t, m):
            code, err = pousser(m, b["travail"])
            if code:
                res(b, "refuse", t, m, err)
            else:
                res(b, "avance", t, m, f"{t[:12]}..{m[:12]}")
        elif contient(rep_t, m) and ancetre(rep_t, m, t):
            out, _e, _c = git(["rev-list", "--count", f"{m}..{t}"], rep_t, env)
            res(b, "en_avance", t, m, f"+{out.strip() or '?'}")
        elif contient(rep_m, t) or contient(rep_t, m):
            # Une histoire contient les deux pointes : l'origine réécrite
            # (la pointe de travail dans le miroir) ou un travail qui a
            # rapatrié l'origine avant d'avancer encore.
            rep = rep_m if contient(rep_m, t) else rep_t
            out, _e, code = git(
                ["rev-list", "--left-right", "--count", f"{t}...{m}"],
                rep,
                env,
            )
            nombres = out.split()
            detail = (
                f"+{nombres[0]}/-{nombres[1]}"
                if code == 0 and len(nombres) == 2
                else ""
            )
            res(b, "divergent", t, m, detail)
        else:
            detail = "working commits absent from the mirror"
            if os.path.exists(os.path.join(rep_t, "shallow")):
                detail += " (shallow working repository)"
            res(b, "divergent", t, m, detail)
    return resultats


# ── La passe ─────────────────────────────────────────────────────────


def _iso(instant):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(instant))


def passe(
    config,
    forge,
    depots,
    compte,
    jeton,
    home,
    precedent=None,
    git=git,
    maintenant=time.time,
):
    """{« debut », « fin » (ISO UTC), « compte », « resultats »} : les
    paires de `config`, l'une après l'autre. Un « divergent » porte
    « depuis » : celui de la passe `precedent` quand la même branche du
    même dépôt y divergeait déjà, sinon le « debut » de cette passe."""
    debut = _iso(maintenant())
    env = environnement(forge, compte, jeton, home)
    secrets = (jeton, env["GIT_CONFIG_VALUE_0"].split(" ", 2)[-1])
    anciens = {
        (r.get("depot", "").lower(), r.get("branche")): r.get("depuis")
        for r in (precedent or {}).get("resultats", [])
        if r.get("etat") == "divergent" and r.get("depuis")
    }
    resultats = []
    for paire in config.get("paires", []):
        try:
            lot = passe_paire(paire, forge, depots, env, git, secrets)
        except Exception as exc:  # une paire ne coupe pas les suivantes
            lot = [
                {
                    "depot": paire.get("depot"),
                    "miroir": paire.get("miroir"),
                    "branche": b.get("travail"),
                    "branche_miroir": b.get("miroir"),
                    "etat": "erreur",
                    "travail": "",
                    "miroir_sha": "",
                    "detail": masquer(str(exc), secrets),
                }
                for b in paire.get("branches", [])
            ]
        for r in lot:
            if r["etat"] == "divergent":
                r["depuis"] = anciens.get(
                    (r["depot"].lower(), r["branche"]), debut
                )
        resultats.extend(lot)
    return {
        "debut": debut,
        "fin": _iso(maintenant()),
        "compte": compte,
        "resultats": resultats,
    }


def _ecrire_json(chemin, donnees):
    """Écrit `donnees` dans `chemin` par un fichier temporaire renommé :
    un lecteur voit l'ancien contenu ou le nouveau, jamais un mélange.
    Mode 0644."""
    tmp = f"{chemin}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(donnees, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.chmod(tmp, 0o644)
    os.replace(tmp, chemin)


def ecrire_etat(chemin, etat):
    """L'état d'une passe, écrit d'un coup (voir `_ecrire_json`)."""
    _ecrire_json(chemin, etat)


def _lire_json(chemin):
    try:
        with open(chemin, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


# ── Ligne de commande ────────────────────────────────────────────────


def _jeton_systemd():
    dossier = os.environ.get("CREDENTIALS_DIRECTORY", "")
    if not dossier:
        return ""
    try:
        with open(os.path.join(dossier, "token"), encoding="utf-8") as fh:
            return fh.read().strip()
    except OSError:
        return ""


def _passe_cli():
    if os.geteuid() == 0:
        print(
            "run it through: systemctl start erplibre-forge-sync.service",
            file=sys.stderr,
        )
        return 2
    try:
        verrou = os.open(VERROU, os.O_RDWR | os.O_CREAT, 0o644)
    except OSError as exc:
        print(f"lock: {exc}", file=sys.stderr)
        return 2
    try:
        try:
            fcntl.flock(verrou, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            print("a pass is already running")
            return 0
        env = lire_environnement(ENVIRONNEMENT)
        if not forge_valide(env["forge"]) or not os.path.isabs(
            env["depots"] or ""
        ):
            print("invalid environment: FORGE_SYNC_URL, FORGE_SYNC_REPOS")
            return 2
        if not env["compte"]:
            print("invalid environment: FORGE_SYNC_ACCOUNT")
            return 2
        config = _lire_json(CONFIG)
        erreurs = valider(config) if config is not None else ["no config"]
        if erreurs:
            for e in erreurs:
                print(f"config: {e}")
            return 2
        jeton = _jeton_systemd()
        if not jeton:
            print("no token in $CREDENTIALS_DIRECTORY")
            return 2
        etat = passe(
            config,
            env["forge"],
            env["depots"],
            env["compte"],
            jeton,
            os.path.dirname(ETAT),
            precedent=_lire_json(ETAT),
        )
        ecrire_etat(ETAT, etat)
        for r in etat["resultats"]:
            if r["etat"] != "a_jour":
                print(
                    f"{r['depot']} {r['branche']}: {r['etat']}"
                    f" {r['detail']}".rstrip()
                )
        return 1 if any(r["etat"] in ECHECS for r in etat["resultats"]) else 0
    finally:
        os.close(verrou)


def _configurer_cli(entree):
    try:
        nouvelle = json.loads(entree.read())
    except ValueError as exc:
        print(f"invalid JSON: {exc}")
        return 2
    erreurs = valider(nouvelle)
    if erreurs:
        for e in erreurs:
            print(e)
        return 2
    ancienne = _lire_json(CONFIG)
    if ancienne is not None and valider(ancienne):
        print("the existing configuration is invalid: replaced")
        ancienne = None
    avant = {p["depot"].lower() for p in (ancienne or {}).get("paires", [])}
    config = fusionner(ancienne, nouvelle)
    try:
        _ecrire_json(CONFIG, config)
    except OSError as exc:
        print(f"{CONFIG}: {exc}")
        return 2
    neuves = sum(p["depot"].lower() not in avant for p in nouvelle["paires"])
    print(f"{len(config['paires'])} pairs ({neuves} new)")
    return 0


def _retirer_cli(depots):
    config = _lire_json(CONFIG)
    if config is None:
        # Sans configuration, aucune paire ne reste à retirer.
        print("no config: nothing to remove")
        return 0
    reste = retirer(config, depots)
    try:
        _ecrire_json(CONFIG, reste)
    except OSError as exc:
        print(f"{CONFIG}: {exc}")
        return 2
    print(
        f"{len(reste['paires'])} pairs ({len(config['paires']) - len(reste['paires'])} removed)"
    )
    return 0


def _etat_cli():
    config = _lire_json(CONFIG)
    env = lire_environnement(ENVIRONNEMENT)
    try:
        jeton = os.path.getsize(JETON) > 0
    except OSError:
        jeton = False
    print(
        json.dumps(
            {
                "config": config,
                "erreurs_config": (
                    valider(config) if config is not None else []
                ),
                "jeton": jeton,
                "compte": env["compte"],
                "forge": env["forge"],
                "etat": _lire_json(ETAT),
            },
            ensure_ascii=False,
        )
    )
    return 0


def main(argv=None, entree=None):
    """Le code de sortie de la sous-commande `argv[0]` (voir l'en-tête)."""
    argv = sys.argv[1:] if argv is None else list(argv)
    commande = argv[0] if argv else ""
    if commande == "passe":
        return _passe_cli()
    if commande == "configurer":
        return _configurer_cli(entree or sys.stdin)
    if commande == "retirer" and len(argv) > 1:
        return _retirer_cli(argv[1:])
    if commande == "etat":
        return _etat_cli()
    print("\n".join(__doc__.strip().splitlines()[-4:]))
    return 2


if __name__ == "__main__":
    sys.exit(main())
