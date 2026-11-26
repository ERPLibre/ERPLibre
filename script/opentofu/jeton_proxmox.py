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

from script.opentofu import coffre, resolution
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


def _echec(cmd, code):
    return Resultat(
        False,
        t("Host command failed (exit {code}): {cmd}").format(code=code, cmd=cmd),
        code,
    )


def _ids_jetons(jetons):
    """Noms courts des jetons d'une liste `pveum user token list`."""
    ids = set()
    for j in jetons:
        for cle in ("tokenid", "full-tokenid"):
            ids.add(str(j.get(cle, "")).rsplit("!", 1)[-1])
    return ids


def preparer_hote(spec, executer_brut, recreer=False, racine=RACINE_PARCS):
    """(Resultat, spec_neuve) : l'hôte prêt pour tofu et le jeton au coffre.

    `executer_brut` lance une commande sans sudo, pour que le test root voie
    le vrai compte ; l'élévation est posée ici dans `hote.sudo` de la spec
    rendue, que l'appelant sauve. Idempotente : le rôle (privilèges à jour)
    et l'ACL sont toujours appliqués, l'utilisateur n'est créé que s'il
    manque, les contenus du stockage ne sont modifiés que s'il en manque.
    Seule l'étape du jeton est sautée quand il existe sur l'hôte et au
    coffre. Un jeton présent sur l'hôte mais sans secret local n'est recréé
    que si `recreer`, Proxmox ne montrant le secret qu'à la création.
    """
    neuve = copy.deepcopy(spec)
    parc = neuve["nom"]
    cible = neuve["cible"]
    sudo, raison = resolution.elevation(executer_brut)
    if sudo is None:
        return Resultat(False, raison), neuve
    cible["hote"]["sudo"] = sudo

    def executer(cmd):
        return executer_brut(pve.wrap_privilege(cmd, sudo))

    stockage = cible.get("stockage_snippets") or STOCKAGE_DEFAUT
    cible["stockage_snippets"] = stockage
    try:
        utilisateurs = _json(executer, "pveum user list --output-format json")
        deja = any(u.get("userid") == UTILISATEUR for u in utilisateurs)
        jetons = []
        if deja:
            jetons = _json(
                executer,
                f"pveum user token list {UTILISATEUR} --output-format json",
            )
        config = _json(executer, f"pvesh get /storage/{stockage} --output-format json")
    except ValueError as exc:
        return Resultat(False, str(exc)), neuve
    existe = parc in _ids_jetons(jetons)
    local = bool(coffre.lire(parc, racine).get("jeton"))
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
    actuels = config.get("content", "")
    contenus = contenus_requis(actuels)
    faire_jeton = recreer or not existe
    ecritures = 0
    for cmd in commandes_preparation(parc, stockage, contenus, existe):
        if cmd == _cmd_utilisateur():
            if deja:
                continue
            ecritures += 1
        elif cmd in (_cmd_retrait(parc), _cmd_ajout(parc)):
            if not faire_jeton:
                continue
            ecritures += 1
        elif cmd == _cmd_contenus(stockage, contenus):
            if contenus == ",".join(sorted(c for c in actuels.split(",") if c)):
                continue
            ecritures += 1
        code, sortie = executer(cmd)
        if code != 0:
            return _echec(cmd, code), neuve
        if cmd == _cmd_ajout(parc):
            try:
                jeton = extraire_jeton(sortie, parc)
            except ValueError as exc:
                return Resultat(False, str(exc)), neuve
            try:
                donnees = coffre.lire(parc, racine)
                donnees["jeton"] = jeton
                coffre.ecrire(parc, donnees, racine)
            except OSError:
                return (
                    Resultat(
                        False,
                        t(
                            "Token {parc} was created but could not be "
                            "stored; run again with token recreation."
                        ).format(parc=parc),
                    ),
                    neuve,
                )
    if not ecritures:
        return Resultat(True, t("Host already prepared.")), neuve
    return Resultat(True, t("Host prepared.")), neuve
