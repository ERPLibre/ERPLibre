# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""La spec d'un parc : un fichier JSON par parc, source de vérité du moteur.

Le fichier vit dans `private/opentofu/<parc>/spec.json`. `valider` rend une
liste d'erreurs traduites et ne lève jamais : une spec éditée à la main doit
produire un message lisible, pas une trace. `charger` regroupe ces erreurs
dans `SpecInvalide`. `sauver` écrit par fichier temporaire puis renommage,
fichier en 0600 et dossier en 0700, car la spec porte alias d'hôte, noms de
VM et adresses.
"""

import ipaddress
import json
import os
import re
import tempfile
from pathlib import Path

from script.todo.todo_i18n import t

RACINE_PARCS = Path(__file__).resolve().parent.parent.parent / "private" / "opentofu"

SCHEMA = 1
_RE_PARC = re.compile(r"^[a-z][a-z0-9-]{0,30}$")
_RE_VM = re.compile(r"^[a-z][a-z0-9-]{0,62}$")
_RE_DISQUE = re.compile(r"^[1-9][0-9]*G$")
_RAM_MIN = 512
_CHAMPS_CIBLE = (
    "api_url",
    "noeud",
    "stockage",
    "stockage_snippets",
    "pont",
)


class SpecInvalide(Exception):
    """Spec illisible ou invalide ; `erreurs` porte les messages traduits."""

    def __init__(self, erreurs):
        self.erreurs = list(erreurs)
        super().__init__("\n".join(self.erreurs))


def dossier_parc(nom, racine=RACINE_PARCS):
    """Dossier d'un parc sous `racine`.

    Lève ValueError (message traduit) quand `nom` n'est pas un nom de parc :
    tout chemin de parc passe par ici, et un nom comme `../x` sortirait de
    `racine`. `fullmatch` refuse aussi un saut de ligne final que `$` laisse
    passer.
    """
    if not isinstance(nom, str) or not _RE_PARC.fullmatch(nom):
        raise ValueError(t("Invalid fleet name: {nom}").format(nom=nom))
    return Path(racine) / nom


def _cle_ssh_par_defaut():
    """Première clé publique usuelle de ~/.ssh, ou "" s'il n'y en a pas."""
    for nom in ("id_ed25519.pub", "id_rsa.pub"):
        chemin = Path.home() / ".ssh" / nom
        if chemin.is_file():
            return str(chemin)
    return ""


def nouvelle_spec(nom, hote):
    """Spec de schéma 1 avec une VM par défaut, cible proxmox à résoudre."""
    return {
        "schema": SCHEMA,
        "nom": nom,
        "moteur": "tofu",
        "cible": {
            "type": "proxmox",
            "hote": {"target": hote, "jump": "", "port": "", "sudo": "sudo "},
            "api_url": "",
            "insecure": True,
            "noeud": "",
            "stockage": "",
            "stockage_snippets": "",
            "pont": "",
        },
        "compte": {"user": "erplibre", "ssh_key": _cle_ssh_par_defaut()},
        "vms": [
            {
                "nom": f"{nom}-vm-1",
                "vmid": None,
                "distro": "debian",
                "version": "13",
                "arch": "amd64",
                "vcpus": 2,
                "ram": 4096,
                "disque": "20G",
                "ip": "auto",
                "passerelle": "",
                "dns": [],
                "demarrer": True,
                "installer_erplibre": False,
                "branche": "",
            }
        ],
    }


def _ip_valide(ip):
    if ip in ("auto", "dhcp"):
        return True
    try:
        ipaddress.ip_interface(ip)
    except ValueError:
        return False
    return "/" in ip


def _entier(valeur):
    return isinstance(valeur, int) and not isinstance(valeur, bool)


def _valider_vm(vm, distros, vus):
    """Erreurs d'une VM ; `vus` accumule les noms pour repérer les doublons."""
    if not isinstance(vm, dict):
        return [t("A VM entry must be an object.")]
    erreurs = []
    nom = vm.get("nom")
    if not isinstance(nom, str) or not _RE_VM.match(nom):
        erreurs.append(t("Invalid VM name: {nom}").format(nom=nom))
    elif nom in vus:
        erreurs.append(t("Duplicate VM name: {nom}").format(nom=nom))
    else:
        vus.add(nom)
    if not _entier(vm.get("vcpus")) or vm["vcpus"] < 1:
        erreurs.append(t("VM {nom}: vcpus must be an integer >= 1.").format(nom=nom))
    if not _entier(vm.get("ram")) or vm["ram"] < _RAM_MIN:
        erreurs.append(
            t("VM {nom}: ram must be an integer >= {min} (MiB).").format(
                nom=nom, min=_RAM_MIN
            )
        )
    disque = vm.get("disque")
    if not isinstance(disque, str) or not _RE_DISQUE.match(disque):
        erreurs.append(
            t("VM {nom}: disk must look like 20G, got {val}.").format(
                nom=nom, val=disque
            )
        )
    ip = vm.get("ip")
    if not isinstance(ip, str) or not _ip_valide(ip):
        erreurs.append(
            t("VM {nom}: ip must be auto, dhcp or a.b.c.d/nn, got {val}.").format(
                nom=nom, val=ip
            )
        )
    elif ip not in ("auto", "dhcp") and not vm.get("passerelle"):
        erreurs.append(t("VM {nom}: a fixed ip needs a gateway.").format(nom=nom))
    if not isinstance(vm.get("dns", []), list):
        erreurs.append(t("VM {nom}: dns must be a list.").format(nom=nom))
    vmid = vm.get("vmid")
    if vmid is not None and (not _entier(vmid) or vmid < 100):
        erreurs.append(
            t("VM {nom}: vmid must be empty or an integer >= 100.").format(nom=nom)
        )
    if distros is not None:
        distro, version = vm.get("distro"), vm.get("version")
        if distro not in distros:
            erreurs.append(
                t("VM {nom}: unknown distro {val}.").format(nom=nom, val=distro)
            )
        elif version not in distros[distro][0]:
            erreurs.append(
                t("VM {nom}: unknown version {val} for {distro}.").format(
                    nom=nom, val=version, distro=distro
                )
            )
    return erreurs


def valider(spec, distros=None):
    """Erreurs traduites de `spec`, liste vide si elle est valide.

    `distros` a la forme de `deploy_qemu.DISTROS` (`{distro: (versions, ...)}`) ;
    à None, distro et version ne sont pas contrôlées.
    """
    if not isinstance(spec, dict):
        return [t("The spec must be a JSON object.")]
    erreurs = []
    if spec.get("schema") != SCHEMA:
        erreurs.append(
            t("Unsupported spec schema: {val}.").format(val=spec.get("schema"))
        )
    nom = spec.get("nom")
    if not isinstance(nom, str) or not _RE_PARC.match(nom):
        erreurs.append(t("Invalid fleet name: {nom}").format(nom=nom))
    if spec.get("moteur") != "tofu":
        erreurs.append(t("Unsupported engine: {val}.").format(val=spec.get("moteur")))
    cible = spec.get("cible")
    if not isinstance(cible, dict) or cible.get("type") != "proxmox":
        erreurs.append(t("The target must be of type proxmox."))
    else:
        hote = cible.get("hote")
        if not isinstance(hote, dict) or not hote.get("target"):
            erreurs.append(t("The target host needs a ssh target."))
        else:
            if hote.get("jump"):
                erreurs.append(t("A jump host is not supported yet."))
            if hote.get("sudo", "sudo ") not in ("sudo ", ""):
                erreurs.append(t("The host sudo field must be 'sudo ' or empty."))
        for champ in _CHAMPS_CIBLE:
            if not isinstance(cible.get(champ, ""), str):
                erreurs.append(
                    t("Target field {champ} must be a string.").format(champ=champ)
                )
    compte = spec.get("compte")
    if not isinstance(compte, dict) or not compte.get("user"):
        erreurs.append(t("The account needs a user."))
    vms = spec.get("vms")
    if not isinstance(vms, list) or not vms:
        erreurs.append(t("The spec needs at least one VM."))
    else:
        vus = set()
        for vm in vms:
            erreurs.extend(_valider_vm(vm, distros, vus))
    return erreurs


def charger(nom, racine=RACINE_PARCS):
    """Lit et valide la spec d'un parc ; lève `SpecInvalide` sinon."""
    try:
        chemin = dossier_parc(nom, racine) / "spec.json"
    except ValueError as exc:
        raise SpecInvalide([str(exc)])
    try:
        spec = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SpecInvalide(
            [t("Cannot read {chemin}: {err}").format(chemin=chemin, err=exc)]
        )
    erreurs = valider(spec)
    if erreurs:
        raise SpecInvalide(erreurs)
    return spec


def sauver(spec, racine=RACINE_PARCS):
    """Écrit la spec de façon atomique et rend son chemin."""
    dossier = dossier_parc(spec["nom"], racine)
    dossier.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(dossier, 0o700)
    cible = dossier / "spec.json"
    fd, tmp = tempfile.mkstemp(dir=dossier, prefix=".spec.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(spec, f, indent=2, ensure_ascii=False)
            f.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, cible)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return cible


def lister(racine=RACINE_PARCS):
    """Noms triés des parcs qui ont un `spec.json`."""
    racine = Path(racine)
    if not racine.is_dir():
        return []
    return sorted(d.name for d in racine.iterdir() if (d / "spec.json").is_file())
