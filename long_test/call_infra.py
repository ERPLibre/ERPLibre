#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""coturn et ntfy s'installent-ils, se vérifient-ils et se désinstallent-ils
sur de vraies machines Debian et Arch ?

Une VM par système, l'une après l'autre : `long-call-infra-debian` (Debian
13) et `long-call-infra-arch` (Arch, image du jour). Il vit dans long_test/
et non dans test/ : il crée de vraies machines et y installe des paquets.

CE QU'IL ENVOIE : LES BRIQUES DU MENU

Chaque étape est celle du menu « Infrastructure d'appel » de todo.py, sans
ses questions : les `Answers` sont écrites ici, et la suite passe par
`script/todo/call_infra.py` — sonde, plan, script d'installation, pare-feu,
écriture de l'état, vérification, désinstallation. Un test qui installerait
par ses propres soins prouverait son chemin, pas celui du produit. Chaque
étape du produit part dans sa propre session ssh, comme le menu lance
chaque script par un appel à part.

LE VERDICT EST L'ÉTAT DE LA MACHINE

Les allocations TURN réelles et la santé de ntfy sont lues depuis cette
machine par `check_local`, comme le menu le fait ; la désinstallation est
jugée sur ce qui reste sur l'hôte (unité, dossier de l'outil, règles du
pare-feu, configuration remise) et sur les ports vus d'ici.

Debian couvre l'adoption et le pare-feu : ufw y est activé (ssh d'abord),
ntfy y est d'abord posé à l'ancienne par install_ntfy.sh avec un compte de
téléphone, puis l'outil installe les deux services avec un certificat d'une
autorité locale (local_cert) et ouvre ses ports. Arch couvre le chemin http
sans pare-feu, après la préparation pacman du menu.

  ./long_test/call_infra.py                  # Debian puis Arch
  ./long_test/call_infra.py --distro arch    # un seul système
  ./long_test/call_infra.py --dry-run        # le plan, rien de créé
  ./long_test/call_infra.py --garder         # garder les VM
  ./long_test/call_infra.py --detruire       # défaire la dernière course
"""

import argparse
import base64
import binascii
import datetime
import hashlib
import json
import os
import re
import secrets
import shlex
import socket
import subprocess
import sys
import time

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, RACINE)
sys.path.insert(0, os.path.join(RACINE, "long_test"))

from descente import (  # noqa: E402
    Descente,
    Famille,
    capacite_hote,
    cle_publique,
    detruire,
    detruire_etage1,
    dire,
    drapeaux_cache,
    retirer_alias,
)
from script.reverse_proxy import local_cert  # noqa: E402
from script.todo import call_infra as ci  # noqa: E402
from script.todo import call_infra_menu as cim  # noqa: E402
from script.todo import ntfy_mobile as nm  # noqa: E402
from script.todo import turn_client  # noqa: E402

OUTIL = "call_infra"
NOM_BASE = "long-call-infra"
# L'utilisateur que deploy_qemu.py crée, avec un sudo sans mot de passe.
UTILISATEUR = "erplibre"

# Le système et la version de deploy_qemu.py, dans l'ordre de la course.
DISTROS = {"debian": "13", "arch": "latest"}

# Le gabarit d'une VM : le minimum du catalogue pour ces deux images. Les
# deux services tiennent dans 2 Gio.
VCPUS = 2
MEMOIRE_MO = 2048
DISQUE_GO = 20
# Ce qu'une course écrit dans le disque creux de la VM, mise à jour
# complète d'Arch comprise : une estimation, comparée à l'espace libre de
# l'hôte, pas aux 20 Go virtuels.
DISQUE_ECRIT_GO = 6
MARGE_RAM_MO = 1024
MARGE_DISQUE_GO = 4

DELAI_CREATION = 1800
DELAI_SSH = 600
# Attente de cloud-init, préparation pacman (mise à jour complète), pose
# d'ufw : un index de paquets à rafraîchir et des téléchargements.
DELAI_PREPARATION = 1800
DELAI_INSTALL = 1800
DELAI_SCRIPT = 300
DELAI_PORT = 3

# Les lignes de sortie qui portent un secret : le mot de passe de
# l'administrateur de ntfy, la clé du compte de contrôle de coturn. Ce sont
# celles que le menu masque à l'écran ; ici elles sont masquées au journal.
SECRETS = (cim.ADMIN_PASSWORD_LINE, cim.CHECK_KEY_LINE)
# Un jeton d'accès de ntfy, que `ntfy token add` imprime au milieu d'une
# ligne : il ouvre les sujets du téléphone tant que la VM vit.
JETON = re.compile(r"tk_[A-Za-z0-9]+")

# Les lignes de `check_local` qui doivent être vertes, par système.
CONTROLES = {
    "debian": (
        "turn-udp",
        "turn-tcp",
        "turn-tls",
        "ntfy-health",
        "firewall",
        "service-coturn",
        "service-ntfy",
    ),
    "arch": (
        "turn-udp",
        "turn-tcp",
        "ntfy-health",
        "service-coturn",
        "service-ntfy",
    ),
}

# Les étapes, dans l'ordre, pour le plan et le rapport.
ETAPES = {
    "debian": (
        "vm",
        "ssh",
        "cloud-init",
        "ufw-actif",
        "ntfy-ancien",
        "telephone-ancien",
        "installation",
        "ntfy-adopte",
        "verification",
        "telephone-garde",
        "rien-a-changer",
        "melange (information)",
        "desinstallation",
        "etat-apres-desinstallation",
        "ports-fermes",
        "desinstallation-vide",
    ),
    "arch": (
        "vm",
        "ssh",
        "cloud-init",
        "pacman",
        "installation",
        "verification",
        "desinstallation",
        "ports-fermes",
        "desinstallation-vide",
    ),
}

# Le libellé du téléphone semé avant l'adoption, et le compte REST du
# rejeu de la base partagée (secret et comptes long terme).
LIBELLE_TELEPHONE = "longtest"
UTILISATEUR_REST = "longtest"

OPTIONS_SSH = [
    "-o",
    "StrictHostKeyChecking=no",
    "-o",
    "UserKnownHostsFile=/dev/null",
    "-o",
    "BatchMode=yes",
    "-o",
    "ConnectTimeout=10",
    # Une session morte (VM figée, réseau coupé) se détecte en deux
    # minutes au lieu d'attendre le délai entier de l'étape.
    "-o",
    "ServerAliveInterval=15",
    "-o",
    "ServerAliveCountMax=8",
]


def nom_vm(distro):
    """Le domaine libvirt, qui sert aussi d'alias ssh. Fixe : une VM
    gardée par `--garder` fait refuser la course suivante jusqu'au
    `--detruire`, plutôt que d'empiler une seconde VM."""
    return f"{NOM_BASE}-{distro}"


def argv_creation(distro, nom, cle_pub="", drapeaux=()):
    """La ligne de deploy_qemu.py, sans sudo : la CLI écrit disque et seed
    par l'API des volumes de libvirt."""
    argv = [
        os.path.join(RACINE, ".venv.erplibre/bin/python"),
        os.path.join(RACINE, "script/qemu/deploy_qemu.py"),
        "--distro",
        distro,
        "--version",
        DISTROS[distro],
        "--name",
        nom,
        "--vcpus",
        str(VCPUS),
        "--memory",
        str(MEMOIRE_MO),
        "--disk-size",
        f"{DISQUE_GO}G",
    ]
    if cle_pub:
        argv += ["--ssh-key", cle_pub]
    return argv + list(drapeaux)


def masquer(texte):
    """`texte` où chaque ligne qui commence par un des SECRETS devient
    « <préfixe> *** », et chaque jeton de ntfy (JETON) « tk_*** ». Le reste
    passe tel quel."""
    lignes = []
    for ligne in texte.splitlines(keepends=True):
        nu = ligne.rstrip("\r\n")
        prefixe = next((p for p in SECRETS if nu.startswith(p)), None)
        if prefixe is None:
            lignes.append(JETON.sub("tk_***", ligne))
        else:
            fin = ligne[len(nu) :]
            lignes.append(f"{prefixe} ***{fin}")
    return "".join(lignes)


def commande_distante(root=True, utilisateur=None, env=None, shell="sh"):
    """La commande que ssh fait lancer à l'hôte.

    Le script arrive par l'entrée standard : « "$(cat)" » le lit en entier
    AVANT que la redirection « </dev/null » ne s'applique, si bien que les
    commandes du script (apt, pacman) ne lisent jamais la suite du script.
    Le corps ne passe donc ni par l'argv local de ssh ni par le journal.
    `root` : sous « sudo -n », qui échoue au lieu d'attendre un mot de
    passe ; `utilisateur` : sous ce compte. `env` : variables posées par
    « env », sans secret (elles se lisent dans la liste des processus).
    """
    parties = []
    if root or utilisateur:
        parties += ["sudo", "-n"]
        if utilisateur:
            parties += ["-u", shlex.quote(utilisateur)]
    if env:
        parties.append("env")
        parties += [f"{k}={shlex.quote(str(v))}" for k, v in env.items()]
    parties += [shell, "-c", '"$(cat)"', "</dev/null"]
    return " ".join(parties)


def ssh_base(cible):
    return ["ssh"] + OPTIONS_SSH + [cible]


def _ajouter(log, texte):
    with open(log, "a", encoding="utf-8") as fh:
        fh.write(texte if texte.endswith("\n") else texte + "\n")


def distant(cible, script, log, delai, **options):
    """Lance `script` sur `cible` (options de `commande_distante`). Rend
    (code, sortie), ou (None, "") quand ssh n'a pas abouti dans `delai`.

    La sortie rendue est entière, pour que les lignes `@@` se relisent ;
    celle du journal passe par `masquer`."""
    argv = ssh_base(cible) + [commande_distante(**options)]
    try:
        fini = subprocess.run(
            argv,
            input=script,
            capture_output=True,
            text=True,
            timeout=delai,
        )
    except (OSError, subprocess.SubprocessError) as souci:
        _ajouter(log, f"✗ ssh {cible} interrompu : {souci}")
        return None, ""
    sortie = (fini.stdout or "") + (fini.stderr or "")
    _ajouter(log, masquer(sortie))
    _ajouter(log, f"── code {fini.returncode}")
    return fini.returncode, sortie


def verdict_controle(lignes, requis):
    """(vert, problèmes) des `CheckLine` de `check_local`.

    Vert quand chaque nom de `requis` est présent et vaut True, et
    qu'aucune autre ligne ne vaut False ; une ligne non requise à None
    (« rien à vérifier ») ne compte pas. `problèmes` : les noms en défaut,
    requis manquants compris, dans l'ordre de `requis` puis des lignes."""
    vues = {ligne.name: ligne.ok for ligne in lignes}
    problemes = [nom for nom in requis if vues.get(nom) is not True]
    problemes += [
        ligne.name
        for ligne in lignes
        if ligne.name not in requis and ligne.ok is False
    ]
    return not problemes, problemes


def resultat_melange(rest_ok, controle_ok):
    """Le rejeu d'un secret REST ajouté à la base de coturn, où vit déjà le
    compte de contrôle : « melange-ok » quand l'allocation REST et celle du
    compte de contrôle réussissent toutes deux, « melange-refuse » sinon.
    C'est une information sur le paquet, pas un échec de la course."""
    return "melange-ok" if rest_ok and controle_ok else "melange-refuse"


def reponses(ip, cert_pem=None, key_pem=None):
    """Les `Answers` de la course : les deux services, l'adresse de la VM
    comme nom public, et le certificat fourni quand il y en a un."""
    return ci.Answers(
        services=frozenset(ci.SERVICES),
        tls="supplied" if cert_pem else "none",
        cert_pem=cert_pem,
        key_pem=key_pem,
        public_name=ip,
    )


def _sonde(cible, log, executer):
    """`HostFacts` de l'hôte, ou None (sortie illisible, ssh perdu)."""
    code, sortie = executer(cible, ci.probe_script(), log, DELAI_SCRIPT)
    if code is None:
        return None
    try:
        return ci.parse_probe(sortie)
    except ci.Refusal as refus:
        _ajouter(log, f"✗ sonde : {refus.key} {refus.values}")
        return None


def installer(cible, answers, log, executer=distant, maintenant=None):
    """Le chemin du menu, de la sonde à l'état écrit.

    Rend {"ok", "etape", "rien_a_faire", "adoptes", "etat"} : `etape` nomme
    ce qui a échoué (sonde, plan, install, pare-feu, etat), `adoptes` les
    services dont la configuration étrangère a été sauvée, `etat` l'état
    écrit sur l'hôte. Le pare-feu reçoit ses règles quand il en montre
    (le « oui » du menu) ; sans aperçu, la consignation reste celle de
    l'état précédent."""
    res = {
        "ok": False,
        "etape": "sonde",
        "rien_a_faire": False,
        "adoptes": (),
        "etat": None,
    }
    facts = _sonde(cible, log, executer)
    if facts is None:
        return res
    res["etape"] = "plan"
    try:
        plan = ci.plan_install(
            facts,
            answers,
            maintenant or datetime.datetime.now(datetime.timezone.utc),
        )
    except ci.Refusal as refus:
        _ajouter(log, f"✗ plan : {refus.key} {refus.values}")
        return res
    res["adoptes"] = plan.adopt
    if plan.nothing_to_do:
        _ajouter(log, "✓ rien à changer")
        res.update(ok=True, etape="", rien_a_faire=True)
        return res
    res["etape"] = "install"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    code, sortie = executer(
        cible, ci.install_script(plan, stamp), log, DELAI_INSTALL
    )
    sauve = [v.strip() for n, v in ci.marker_lines(sortie) if n == "SAVED"]
    if code != 0 or sauve[-1:] != ["yes"]:
        return res
    etat = ci.written_state(plan, stamp)
    kind = facts.firewall
    regles = ci.firewall_rules(answers)
    chaine = facts.nft_chains[0] if len(facts.nft_chains) == 1 else None
    precedent = etat.get("firewall")
    record = ci.firewall_record(kind, "", precedent)
    if ci.firewall_preview(kind, regles, chaine):
        res["etape"] = "pare-feu"
        code, sortie = executer(
            cible,
            ci.firewall_script(kind, regles, "allow"),
            log,
            DELAI_SCRIPT,
        )
        if code != 0:
            return res
        record = ci.firewall_record(kind, sortie, precedent)
    etat = ci.with_firewall(etat, record)
    res["etape"] = "etat"
    code, sortie = executer(
        cible, ci.state_write_script(etat), log, DELAI_SCRIPT
    )
    sauve = [v.strip() for n, v in ci.marker_lines(sortie) if n == "SAVED"]
    if code != 0 or sauve[-1:] != ["yes"]:
        return res
    res.update(ok=True, etape="", etat=etat)
    return res


def verifier(cible, adresse, cafile, log, executer=distant):
    """(lignes `CheckLine`, faits lus) de la vérification du menu, depuis
    cette machine ; ([], None) quand l'hôte n'a pas répondu. La clé du
    compte de contrôle reste dans les faits, jamais au journal."""
    code, sortie = executer(cible, ci.check_remote_script(), log, DELAI_SCRIPT)
    if code is None:
        return [], None
    try:
        lus = ci.parse_check_remote(sortie)
    except ci.Refusal as refus:
        _ajouter(log, f"✗ vérification : {refus.key}")
        return [], None
    lignes = ci.check_local(lus, adresse, cafile)
    for ligne in lignes:
        _ajouter(
            log,
            f"{cim.SYMBOLS.get(ligne.ok, '?')} {ligne.name} : {ligne.detail}"
            f" {ligne.values}",
        )
    return lignes, lus


def desinstaller(cible, remove_data, log, executer=distant):
    """La désinstallation du menu. Rend « fait » (`@@DONE yes`), « rien »
    (pas d'état, `@@NOTHING`) ou « echec »."""
    facts = _sonde(cible, log, executer)
    if facts is None:
        return "echec"
    stamp = time.strftime("%Y%m%d-%H%M%S")
    etat = facts.state if isinstance(facts.state, dict) else None
    try:
        script = ci.uninstall_script(etat, remove_data, stamp)
    except ci.Refusal as refus:
        _ajouter(log, f"✗ désinstallation : {refus.key} {refus.values}")
        return "echec"
    code, sortie = executer(cible, script, log, DELAI_INSTALL)
    noms = dict(ci.marker_lines(sortie))
    if etat is None:
        return "rien" if code == 0 and "NOTHING" in noms else "echec"
    fait = [v.strip() for n, v in ci.marker_lines(sortie) if n == "DONE"]
    return "fait" if code == 0 and fait[-1:] == ["yes"] else "echec"


def port_tcp_ouvert(adresse, port, delai=DELAI_PORT):
    """Vrai quand une connexion TCP aboutit ; un refus ou un silence (un
    pare-feu qui jette) valent fermé."""
    try:
        with socket.create_connection((adresse, port), timeout=delai):
            return True
    except OSError:
        return False


def ports_fermes(adresse, tcp, udp):
    """{« <port>/<proto> »: fermé} vus d'ici. En udp, une requête STUN
    Binding sans réponse vaut fermé : un port udp ne refuse rien."""
    vus = {f"{p}/tcp": not port_tcp_ouvert(adresse, p) for p in tcp}
    for port in udp:
        reponse = turn_client.binding(adresse, port, "udp", timeout=DELAI_PORT)
        vus[f"{port}/udp"] = reponse is None
    return vus


# --- Machines -----------------------------------------------------------


def _todo():
    sys.argv = ["todo.py"]
    from script.todo.todo import TODO

    return TODO.__new__(TODO)


def creer_vm(nom, distro, journal, dry_run):
    """La VM, par la CLI du dépôt. Rend (nom, uuid, ok).

    Un nom que libvirt définit déjà n'est pas à cette course : refus, et
    (None, "", False). Une création qui échoue après avoir défini le
    domaine rend son nom et son UUID avec ok faux, pour qu'elle entre au
    rapport et reste défaisable."""
    argv = argv_creation(distro, nom, cle_publique(), drapeaux_cache())
    if dry_run:
        dire("      " + " ".join(shlex.quote(a) for a in argv), journal)
        return nom, "", True
    if Descente.uuid_libvirt(nom):
        dire(
            f"      ✗ {nom} existe déjà, elle n'est pas à cette course :"
            " --detruire d'abord",
            journal,
        )
        return None, "", False
    ok = False
    try:
        fini = subprocess.run(argv, timeout=DELAI_CREATION)
        ok = fini.returncode == 0
    except (OSError, subprocess.SubprocessError) as souci:
        dire(f"      ✗ la création de {nom} s'est arrêtée : {souci}", journal)
    if not ok:
        dire(f"      ✗ la création de {nom} a échoué", journal)
    uuid = Descente.uuid_libvirt(nom)
    if not ok and not uuid:
        return None, "", False
    return nom, uuid, ok


def adresse_de(nom, journal):
    """L'adresse de la VM, et l'entrée ~/.ssh/config qui la nomme : la CLI
    n'écrit pas cette entrée, sans laquelle « ssh <nom> » ne résout rien."""
    todo = _todo()
    ip = todo._qemu_vm_ip(nom, timeout=DELAI_SSH)
    if not ip:
        dire(f"      ✗ {nom} créée mais sans adresse", journal)
        return ""
    pub = cle_publique()
    prive = pub[:-4] if pub else None
    todo._write_ssh_config_entry([nom], UTILISATEUR, ip, identity_file=prive)
    dire(f"      {nom} : {ip}", journal)
    return ip


def attendre_ssh(cible, journal, delai=DELAI_SSH):
    """Vrai dès qu'une commande aboutit en ssh : le port s'ouvre avant que
    cloud-init n'ait posé le compte."""
    fin = time.time() + delai
    while time.time() < fin:
        try:
            fini = subprocess.run(
                ssh_base(cible) + ["true"],
                capture_output=True,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            time.sleep(5)
            continue
        if fini.returncode == 0:
            return True
        time.sleep(5)
    dire(f"      ✗ {cible} jamais joignable en {delai} s", journal)
    return False


def plan_tient(journal, nombre=1):
    """L'hôte peut-il porter `nombre` VM debout ensemble ? Le dire avant
    d'en créer une. Chaque VM compte sa mémoire et son disque écrit ; les
    marges ne comptent qu'une fois, pour l'hôte."""
    coeurs, ram, disque = capacite_hote()
    dire(
        f"  machine locale : {coeurs} cœurs, {ram} Mo disponibles,"
        f" {disque} Go de disque",
        journal,
    )
    ram_voulue = nombre * MEMOIRE_MO + MARGE_RAM_MO
    disque_voulu = nombre * DISQUE_ECRIT_GO + MARGE_DISQUE_GO
    manque = []
    if ram < ram_voulue:
        manque.append(f"RAM (il en faut {ram_voulue} Mo pour {nombre} VM)")
    if disque < disque_voulu:
        manque.append(
            f"disque (il en faut {disque_voulu} Go libres pour {nombre} VM ;"
            f" chaque disque virtuel fait {DISQUE_GO} Go, creux)"
        )
    if manque:
        dire(f"  ✗ pas assez de {' ni de '.join(manque)}", journal)
        return False
    return True


# --- Scénarios ----------------------------------------------------------

# Pose ufw, autorise ssh AVANT d'activer, puis active : le pare-feu actif
# est ce que l'outil doit compléter sans jamais l'activer lui-même.
SCRIPT_UFW = "\n".join(
    [
        "set -e",
        "export DEBIAN_FRONTEND=noninteractive",
        "apt-get -o DPkg::Lock::Timeout=600 update -qq",
        "apt-get -o DPkg::Lock::Timeout=600 install -y -qq ufw",
        "ufw allow 22/tcp",
        "ufw --force enable",
        "ufw status | grep -q '^Status: active' && echo '@@UFW active'",
        "",
    ]
)

# Ce qui doit rester, ou non, après la désinstallation sur Debian : unité
# coturn, dossier de l'outil, règles ufw de l'outil, empreinte du
# server.yml remis, état de ntfy (adopté, donc gardé).
SCRIPT_APRES = "\n".join(
    [
        "for u in " + " ".join(ci.COTURN_UNITS.values()) + "; do",
        '  if systemctl cat "$u" >/dev/null 2>&1; then echo "@@UNIT $u"; fi',
        "done",
        f"if [ -e {ci.CALL_DIR} ]; then echo '@@CALL_DIR present'; fi",
        f"N=$(ufw show added 2>/dev/null | grep -c {ci.FIREWALL_COMMENT})",
        'echo "@@UFW_RULES ${N:-0}"',
        f'echo "@@YML_SHA $(sha256sum < {ci.NTFY_CONFIG} | cut -d" " -f1)"',
        f'echo "@@NTFY $(systemctl is-active {ci.NTFY_UNIT} 2>/dev/null)"',
        "echo @@END",
        "",
    ]
)


def script_secret(realm, secret):
    """Ajoute `secret` à la base de coturn par « turnadmin -s », sous le
    compte du service (la base lui appartient). Le secret passe en argument
    de turnadmin, lisible le temps de la commande : il naît pour ce rejeu,
    sur une VM jetable, et ne sert nulle part ailleurs."""
    return "\n".join(
        [
            "U=",
            "for u in " + " ".join(ci.COTURN_UNITS.values()) + "; do",
            '  if systemctl cat "$u" >/dev/null 2>&1; then',
            '    U=$(systemctl show -p User --value "$u"); break',
            "  fi",
            "done",
            f'runuser -u "${{U:-turnserver}}" -- turnadmin -s'
            f" {shlex.quote(secret)} -r {shlex.quote(realm)}"
            f" -b {ci.COTURN_DB} >/dev/null 2>&1",
            'echo "@@SECRET_RC $?"',
            "",
        ]
    )


class Scenario:
    """Les étapes d'un système et leur journal. `etapes` : {nom: bool},
    dans l'ordre où elles ont tourné ; `details` : ce qui éclaire un
    verdict (lignes de vérification, ports, rejeu du mélange)."""

    def __init__(self, distro, log, journal):
        self.distro = distro
        self.log = log
        self.journal = journal
        self.etapes = {}
        self.details = {}

    def noter(self, nom, ok, detail=None):
        self.etapes[nom] = bool(ok)
        if detail is not None:
            self.details[nom] = detail
        marque = "✓" if ok else "✗"
        dire(f"      {marque} {nom}", self.journal)
        _ajouter(self.log, f"══ {marque} {nom} {detail if detail else ''}")
        return bool(ok)

    def ligne(self):
        echecs = [n for n, ok in self.etapes.items() if not ok]
        return {
            "distro": self.distro,
            "version": DISTROS[self.distro],
            "verdict": f"ECHEC({echecs[0]})" if echecs else "OK",
            "etapes": self.etapes,
            "details": self.details,
            "journal": os.path.basename(self.log),
        }


def _texte_b64(valeur):
    """Le texte d'une valeur base64 de `inspect_script`, "" si illisible."""
    try:
        return base64.b64decode(valeur.strip(), validate=True).decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return ""


def _lignes_en_dict(lignes):
    return [
        {
            "name": li.name,
            "ok": li.ok,
            "detail": li.detail,
            "values": li.values,
        }
        for li in lignes
    ]


def _verification(sc, cible, ip, cafile):
    lignes, lus = verifier(cible, ip, cafile, sc.log)
    vert, problemes = verdict_controle(lignes, CONTROLES[sc.distro])
    sc.noter(
        "verification",
        vert,
        {"problemes": problemes, "lignes": _lignes_en_dict(lignes)},
    )
    return lignes, lus


def _telephones(cible, log, proprietaire):
    code, sortie = distant(
        cible,
        nm.list_script(ci.NTFY_CONFIG),
        log,
        DELAI_SCRIPT,
        utilisateur=proprietaire,
    )
    return nm.phone_users(sortie) if code == 0 else []


def _preparer(sc, cible, distro):
    """Attente de cloud-init, puis la préparation propre au système : la
    préparation pacman du menu sur Arch, ufw actif sur Debian."""
    todo = _todo()
    code, _s = distant(
        cible,
        todo._qemu_cloud_init_wait(),
        sc.log,
        DELAI_PREPARATION,
        root=False,
        shell="bash",
    )
    if not sc.noter("cloud-init", code == 0):
        return False
    if distro == "arch":
        code, _s = distant(
            cible,
            todo._qemu_pacman_prepare_cmd(),
            sc.log,
            DELAI_PREPARATION,
            root=False,
            shell="bash",
        )
        return sc.noter("pacman", code == 0)
    code, sortie = distant(cible, SCRIPT_UFW, sc.log, DELAI_PREPARATION)
    return sc.noter("ufw-actif", code == 0 and "@@UFW active" in sortie)


def _semer_ntfy(sc, cible, ip):
    """ntfy posé à l'ancienne : install_ntfy.sh lancé seul, sans l'outil,
    donc une configuration sans marque, puis un compte de téléphone par
    `access_script`. Rend (empreinte du server.yml, propriétaire de la
    base, téléphone) ou None."""
    with open(ci.INSTALLERS["ntfy"], encoding="utf-8") as fh:
        installateur = fh.read()
    code, sortie = distant(
        cible,
        installateur,
        sc.log,
        DELAI_INSTALL,
        shell="bash",
        env={
            "NTFY_PORT": ci.NTFY_HTTP_PORT,
            "NTFY_BASE_URL": f"http://{ip}:{ci.NTFY_HTTP_PORT}",
            "NTFY_NON_INTERACTIVE": 1,
        },
    )
    actif = dict(ci.marker_lines(sortie)).get("ACTIVE", "")
    code, sortie = distant(
        cible, nm.inspect_script(ci.NTFY_CONFIG), sc.log, DELAI_SCRIPT
    )
    faits = nm.parse_markers(sortie)
    texte = _texte_b64(faits.get("YML", ""))
    if not sc.noter(
        "ntfy-ancien",
        code == 0 and actif.strip() == "ntfy active" and ci.is_foreign(texte),
    ):
        return None
    # Le compte qui possède la base des comptes, sous lequel le menu lance
    # la CLI de ntfy ; « ? » quand `stat` n'a rien lu.
    proprietaire = faits.get("OWNER", "").strip()
    if proprietaire in ("", "?"):
        proprietaire = "ntfy"
    telephone = nm.phone_user(LIBELLE_TELEPHONE)
    code, sortie = distant(
        cible,
        nm.access_script(ci.NTFY_CONFIG, telephone, nm.random_prefix()),
        sc.log,
        DELAI_SCRIPT,
        utilisateur=proprietaire,
    )
    if not sc.noter(
        "telephone-ancien", code == 0 and bool(nm.parse_token(sortie))
    ):
        return None
    empreinte = hashlib.sha256(texte.encode("utf-8")).hexdigest()
    return empreinte, proprietaire, telephone


def _melange(sc, cible, ip, cafile, answers):
    """Le rejeu de la base partagée sur le vrai paquet : un secret REST
    ajouté par turnadmin à côté du compte de contrôle, puis une allocation
    de chaque sorte. Noté en information : il ne pèse pas sur le
    verdict."""
    secret = secrets.token_hex(16)
    code, sortie = distant(cible, script_secret(ip, secret), sc.log, 120)
    ajoute = dict(ci.marker_lines(sortie)).get("SECRET_RC", "").strip()
    user, password = turn_client.rest_credentials(
        secret, UTILISATEUR_REST, int(time.time()) + 3600
    )
    rest = turn_client.allocate(
        ip,
        answers.turn_port,
        "udp",
        user,
        turn_client.long_term_key(user, ip, password),
        timeout=5,
    )
    lignes, _lus = verifier(cible, ip, cafile, sc.log)
    controle = any(li.name == "turn-udp" and li.ok for li in lignes)
    detail = {
        "resultat": resultat_melange(rest.ok, controle),
        "turnadmin": ajoute or "?",
        "rest": "ok" if rest.ok else rest.error,
        "compte_controle": controle,
    }
    sc.details["melange"] = detail
    dire(f"      ℹ {detail['resultat']} {detail}", sc.journal)
    _ajouter(sc.log, f"══ ℹ melange {detail}")


def scenario_debian(sc, cible, ip, dossier):
    if not _preparer(sc, cible, "debian"):
        return
    seme = _semer_ntfy(sc, cible, ip)
    if seme is None:
        return
    empreinte, proprietaire, telephone = seme
    tls = local_cert.issue(os.path.join(dossier, "tls"), [ip])
    with open(tls["server_crt"], encoding="utf-8") as fh:
        cert = fh.read()
    with open(tls["server_key"], encoding="utf-8") as fh:
        cle = fh.read()
    answers = reponses(ip, cert, cle)
    res = installer(cible, answers, sc.log)
    if not sc.noter("installation", res["ok"], res["etape"] or None):
        return
    sc.noter("ntfy-adopte", "ntfy" in res["adoptes"])
    cafile = tls["ca_crt"]
    _verification(sc, cible, ip, cafile)
    sc.noter(
        "telephone-garde",
        telephone in _telephones(cible, sc.log, proprietaire),
    )
    again = installer(cible, answers, sc.log)
    sc.noter("rien-a-changer", again["ok"] and again["rien_a_faire"])
    _melange(sc, cible, ip, cafile, answers)
    sc.noter("desinstallation", desinstaller(cible, True, sc.log) == "fait")
    code, sortie = distant(cible, SCRIPT_APRES, sc.log, DELAI_SCRIPT)
    lus = dict(ci.marker_lines(sortie))
    unites = [v for n, v in ci.marker_lines(sortie) if n == "UNIT"]
    apres = {
        "sans-unite-coturn": not any(
            u.strip() in ci.COTURN_UNITS.values() for u in unites
        ),
        "sans-dossier-outil": "CALL_DIR" not in lus,
        "sans-regle-ufw": lus.get("UFW_RULES", "").strip() == "0",
        "server-yml-remis": lus.get("YML_SHA", "").strip() == empreinte,
        "ntfy-adopte-actif": lus.get("NTFY", "").strip() == "active",
        "telephone-toujours-la": telephone
        in _telephones(cible, sc.log, proprietaire),
    }
    sc.noter(
        "etat-apres-desinstallation",
        code == 0 and "END" in lus and all(apres.values()),
        apres,
    )
    ports = ports_fermes(
        ip,
        tcp=(answers.turn_port, answers.turns_port, ci.ntfy_port(answers)),
        udp=(answers.turn_port,),
    )
    sc.noter("ports-fermes", all(ports.values()), ports)
    sc.noter(
        "desinstallation-vide", desinstaller(cible, True, sc.log) == "rien"
    )


def scenario_arch(sc, cible, ip, dossier):
    if not _preparer(sc, cible, "arch"):
        return
    answers = reponses(ip)
    res = installer(cible, answers, sc.log)
    if not sc.noter("installation", res["ok"], res["etape"] or None):
        return
    _verification(sc, cible, ip, None)
    sc.noter("desinstallation", desinstaller(cible, True, sc.log) == "fait")
    ports = ports_fermes(
        ip,
        tcp=(answers.turn_port, ci.ntfy_port(answers)),
        udp=(answers.turn_port,),
    )
    sc.noter("ports-fermes", all(ports.values()), ports)
    sc.noter(
        "desinstallation-vide", desinstaller(cible, True, sc.log) == "rien"
    )


SCENARIOS = {"debian": scenario_debian, "arch": scenario_arch}


# --- Course -------------------------------------------------------------


class Course:
    """Le rapport, réécrit à chaque changement. Sa forme est le CONTRAT du
    défaire partagé (descente.py) : « outil » filtre les rapports, « pid »
    empêche de détruire sous une course vivante, « etages » porte une
    entrée de niveau 1 par VM encore debout. « systemes » est à ce test."""

    def __init__(self, dry_run, journal):
        self.journal = journal
        self.dossier = journal[:-4]
        self.chemin = self.dossier + ("-dryrun.json" if dry_run else ".json")
        self.rapport = {
            "outil": OUTIL,
            "dry_run": dry_run,
            "pid": os.getpid(),
            "etages": [],
            "systemes": [],
        }

    def ecrire(self):
        with open(self.chemin, "w", encoding="utf-8") as fh:
            json.dump(self.rapport, fh, indent=2)

    def inscrire(self, etage):
        """Écrit l'étage AVANT la suite : une course qui meurt laisse de
        quoi défaire sa VM."""
        self.rapport["etages"].append(etage)
        self.ecrire()

    def retirer(self, etage):
        self.rapport["etages"].remove(etage)
        self.ecrire()

    def noter(self, ligne):
        self.rapport["systemes"].append(ligne)
        self.ecrire()


def mener_un(course, distro):
    """Un système, de sa VM à son verdict ; la VM reste au rapport."""
    log = os.path.join(course.dossier, f"{distro}.log")
    sc = Scenario(distro, log, course.journal)
    nom = nom_vm(distro)
    dire(f"  ── {distro} {DISTROS[distro]} : {nom}", course.journal)
    nom, uuid, ok = creer_vm(nom, distro, course.journal, False)
    if nom:
        course.inscrire(
            {"niveau": 1, "nom": nom, "uuid": uuid, "alias": nom, "cree": True}
        )
    if not sc.noter("vm", ok):
        return sc.ligne()
    ip = adresse_de(nom, course.journal)
    if not sc.noter("ssh", bool(ip) and attendre_ssh(nom, course.journal)):
        return sc.ligne()
    try:
        SCENARIOS[distro](sc, nom, ip, course.dossier)
    except Exception as souci:  # noqa: BLE001 - un système, pas la course
        sc.noter("exception", False, repr(souci))
    return sc.ligne()


def defaire_vm(course):
    """Détruit les VM encore au rapport ; rend vrai quand il n'en reste
    aucune. Jamais detruire() en cours de course : il demande « OUI »."""
    for etage in list(course.rapport["etages"]):
        if detruire_etage1(
            course.journal, etage["nom"], attendu=etage["uuid"] or None
        ):
            retirer_alias({"etages": [etage]}, course.journal, NOM_BASE)
            course.retirer(etage)
    return not course.rapport["etages"]


def mener(argv):
    parseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parseur.add_argument(
        "--distro", choices=(*DISTROS, "tous"), default="tous"
    )
    parseur.add_argument("--dry-run", action="store_true")
    parseur.add_argument(
        "--garder", action="store_true", help="garder chaque VM"
    )
    parseur.add_argument("--detruire", action="store_true")
    args = parseur.parse_args(argv)

    journal = os.path.expanduser(
        f"~/.erplibre/longtest/{NOM_BASE}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    )
    os.makedirs(os.path.dirname(journal), exist_ok=True)

    # `detruire_une` défait une VM IMBRIQUÉE chez son parent ; ce test n'en
    # crée aucune, le défaire partagé ne l'appelle donc jamais. Elle le dit
    # plutôt que d'être None.
    def pas_d_imbrique(parent_alias, identite, nom, log=None):
        dire(f"      ✗ {nom} : ce test ne crée pas de VM imbriquée", log)
        return False

    if args.detruire:
        famille = Famille(OUTIL, NOM_BASE, pas_d_imbrique)
        return detruire(famille, journal, dry_run=args.dry_run)

    systemes = list(DISTROS) if args.distro == "tous" else [args.distro]
    course = Course(args.dry_run, journal)
    dire(f"  journal : {journal}", journal)
    if args.dry_run:
        dire("  --dry-run : rien ne sera créé.", journal)
        for distro in systemes:
            dire(f"  ── {distro} {DISTROS[distro]}", journal)
            creer_vm(nom_vm(distro), distro, journal, True)
            dire("      étapes : " + ", ".join(ETAPES[distro]), journal)
        course.ecrire()
        dire(f"  rapport : {course.chemin}", journal)
        return 0

    # `--garder` laisse chaque VM debout jusqu'à la fin de la course : la
    # place se compte pour toutes. Sans lui, une VM est défaite avant la
    # suivante, et une survivante arrête la course plus bas.
    if not plan_tient(journal, len(systemes) if args.garder else 1):
        return 1
    os.makedirs(course.dossier, exist_ok=True)
    course.ecrire()
    dire(f"  rapport : {course.chemin}", journal)
    for distro in systemes:
        ligne = mener_un(course, distro)
        course.noter(ligne)
        marque = "✅" if ligne["verdict"] == "OK" else "❌"
        dire(f"  {marque} {distro} : {ligne['verdict']}", journal)
        if args.garder:
            continue
        # Une VM encore en vie arrête la course : sans `--garder`,
        # plan_tient n'a compté la place que d'une seule.
        if not defaire_vm(course):
            dire(
                "  ✗ VM toujours en vie : la course s'arrête,"
                " --detruire la défait",
                journal,
            )
            break
    if course.rapport["etages"]:
        dire(
            f"  {len(course.rapport['etages'])} VM gardée(s) :"
            " --detruire les défait",
            journal,
        )
    vus = course.rapport["systemes"]
    tout = len(vus) == len(systemes) and all(
        ligne["verdict"] == "OK" for ligne in vus
    )
    dire(f"  {'✅' if tout else '❌'} infrastructure d'appel", journal)
    return 0 if tout else 1


if __name__ == "__main__":
    sys.exit(mener(sys.argv[1:]))
