# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Préparation de l'hôte Proxmox : rôle, utilisateur, jeton d'API, contenus.

Tout passe par un exécuteur injecté (`Executer`, une commande -> (code,
sortie)), donc sans réseau dans les tests. Le secret d'un jeton n'est montré
par Proxmox qu'à sa création : `preparer_hote` le range aussitôt dans le
coffre du parc (`coffre.ecrire`) et ne le met dans aucun message ni journal.
"""

import copy
import json

from script.opentofu import coffre
from script.opentofu.moteur import Resultat
from script.opentofu.spec import RACINE_PARCS
from script.proxmox import proxmox_deploy as pve
from script.todo.todo_i18n import t

ROLE = "ERPLibreTofu"
UTILISATEUR = "tofu@pve"
STOCKAGE_DEFAUT = "local"
CONTENUS_REQUIS = ("snippets", "import")
PRIVILEGES = (
    "Realm.AllocateUser",
    "VM.PowerMgmt",
    "VM.GuestAgent.Unrestricted",
    "Sys.Console",
    "Sys.Audit",
    "Sys.AccessNetwork",
    "VM.Config.Cloudinit",
    "VM.Replicate",
    "Pool.Allocate",
    "SDN.Audit",
    "Realm.Allocate",
    "SDN.Use",
    "Mapping.Modify",
    "VM.Config.Memory",
    "VM.GuestAgent.FileSystemMgmt",
    "VM.Allocate",
    "SDN.Allocate",
    "VM.Console",
    "VM.Clone",
    "VM.Backup",
    "Datastore.AllocateTemplate",
    "VM.Snapshot",
    "VM.Config.Network",
    "Sys.Incoming",
    "Sys.Modify",
    "VM.Snapshot.Rollback",
    "VM.Config.Disk",
    "Datastore.Allocate",
    "VM.Config.CPU",
    "VM.Config.CDROM",
    "Group.Allocate",
    "Datastore.Audit",
    "VM.Migrate",
    "VM.GuestAgent.FileWrite",
    "Mapping.Use",
    "Datastore.AllocateSpace",
    "Sys.Syslog",
    "VM.Config.Options",
    "Pool.Audit",
    "User.Modify",
    "VM.Config.HWType",
    "VM.Audit",
    "Sys.PowerMgmt",
    "VM.GuestAgent.Audit",
    "Mapping.Audit",
    "VM.GuestAgent.FileRead",
    "Permissions.Modify",
)


def contenus_requis(actuels):
    """Union triée des types de contenu `actuels` (séparés par des virgules)
    et de ceux que la préparation exige."""
    types = {c.strip() for c in actuels.split(",") if c.strip()}
    return ",".join(sorted(types | set(CONTENUS_REQUIS)))


def _cmd_role():
    privs = ",".join(PRIVILEGES)
    return (
        f'pveum role add {ROLE} -privs "{privs}"'
        f' || pveum role modify {ROLE} -privs "{privs}"'
    )


def _cmd_utilisateur():
    return f"pveum user add {UTILISATEUR}"


def _cmd_acl():
    return f"pveum aclmod / -user {UTILISATEUR} -role {ROLE}"


def _cmd_retrait(parc):
    return f"pveum user token remove {UTILISATEUR} {parc}"


def _cmd_ajout(parc):
    return (
        f"pveum user token add {UTILISATEUR} {parc} " "--privsep 0 --output-format json"
    )


def _cmd_contenus(stockage, contenus):
    return f"pvesm set {stockage} --content {contenus}"


def commandes_preparation(parc, stockage, contenus, recreer):
    """Commandes d'écriture, dans l'ordre : rôle, utilisateur, ACL, retrait
    du jeton si `recreer`, ajout du jeton, contenus du stockage. Pure."""
    cmds = [_cmd_role(), _cmd_utilisateur(), _cmd_acl()]
    if recreer:
        cmds.append(_cmd_retrait(parc))
    cmds.append(_cmd_ajout(parc))
    cmds.append(_cmd_contenus(stockage, contenus))
    return cmds


def extraire_jeton(sortie_json, parc):
    """`tofu@pve!<parc>=<secret>` depuis la sortie JSON de `token add`.

    ValueError (sans citer la sortie, qui porte le secret) si elle n'est pas
    du JSON ou n'a pas de champ `value`.
    """
    try:
        valeur = json.loads(sortie_json).get("value")
    except (ValueError, AttributeError):
        valeur = None
    if not valeur or not isinstance(valeur, str):
        raise ValueError(t("Token creation output has no secret value."))
    return f"{UTILISATEUR}!{parc}={valeur}"


def _json(executer, cmd):
    """Sortie JSON de `cmd`, ou ValueError nommant la commande."""
    code, sortie = executer(cmd)
    if code != 0:
        raise ValueError(
            t("Reading the host failed (exit {code}): {cmd}").format(code=code, cmd=cmd)
        )
    try:
        return json.loads(sortie)
    except ValueError:
        raise ValueError(t("Unreadable JSON from: {cmd}").format(cmd=cmd))


def _elevation(spec, executer_brut):
    """Valeur de `hote.sudo` ("" si root, "sudo " si NOPASSWD), ou None."""
    code, sortie = executer_brut("id -u")
    if code == 0 and sortie.strip() == "0":
        return ""
    code, _ = executer_brut("sudo -n true")
    return "sudo " if code == 0 else None


def _echec(cmd, code):
    return Resultat(
        False,
        t("Host command failed (exit {code}): {cmd}").format(code=code, cmd=cmd),
        code,
    )


def preparer_hote(spec, executer_brut, recreer=False, racine=RACINE_PARCS):
    """(Resultat, spec_neuve) : l'hôte prêt pour tofu et le jeton au coffre.

    `executer_brut` lance une commande sans sudo, pour que le test root voie
    le vrai compte ; l'élévation est posée ici dans `hote.sudo` de la spec
    rendue, que l'appelant sauve. Un jeton déjà connu des deux côtés ne
    change rien. Un jeton présent sur l'hôte mais sans secret local n'est
    recréé que si `recreer`, Proxmox ne montrant le secret qu'à la création.
    """
    neuve = copy.deepcopy(spec)
    parc = neuve["nom"]
    cible = neuve["cible"]
    sudo = _elevation(neuve, executer_brut)
    if sudo is None:
        return Resultat(False, t("root@ or sudo NOPASSWD required")), neuve
    cible["hote"]["sudo"] = sudo

    def executer(cmd):
        return executer_brut(pve.wrap_privilege(cmd, sudo))

    stockage = cible.get("stockage_snippets") or STOCKAGE_DEFAUT
    cible["stockage_snippets"] = stockage
    try:
        jetons = _json(
            executer, f"pveum user token list {UTILISATEUR} " "--output-format json"
        )
        utilisateurs = _json(executer, "pveum user list --output-format json")
        config = _json(executer, f"pvesh get /storage/{stockage} --output-format json")
    except ValueError as exc:
        return Resultat(False, str(exc)), neuve
    ids = {str(j.get("tokenid", "")).rsplit("!", 1)[-1] for j in jetons} | {
        str(j.get("full-tokenid", "")).rsplit("!", 1)[-1] for j in jetons
    }
    existe = parc in ids
    local = bool(coffre.lire(parc, racine).get("jeton"))
    if existe and local and not recreer:
        return Resultat(True, t("Host already prepared.")), neuve
    if existe and not local and not recreer:
        return (
            Resultat(
                False,
                t(
                    "Token {parc} exists on the host but its secret is not "
                    "stored here; Proxmox shows it only at creation. "
                    "Recreate the token."
                ).format(parc=parc),
            ),
            neuve,
        )
    contenus = contenus_requis(config.get("content", ""))
    deja = any(u.get("userid") == UTILISATEUR for u in utilisateurs)
    cmds = commandes_preparation(parc, stockage, contenus, existe)
    for cmd in cmds:
        if cmd == _cmd_utilisateur() and deja:
            continue
        code, sortie = executer(cmd)
        if code != 0:
            return _echec(cmd, code), neuve
        if cmd == _cmd_ajout(parc):
            try:
                jeton = extraire_jeton(sortie, parc)
            except ValueError as exc:
                return Resultat(False, str(exc)), neuve
            donnees = coffre.lire(parc, racine)
            donnees["jeton"] = jeton
            coffre.ecrire(parc, donnees, racine)
    return Resultat(True, t("Host prepared.")), neuve
