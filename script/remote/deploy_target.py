#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Une machine où l'on déploie, nommée une fois et retrouvée ensuite.

Déployer demandait cinq réponses, à chaque verbe, sans jamais en retenir
aucune : onze commandes retapaient la même adresse, le même port et le même
chemin. Une cible NOMMÉE remplace la saisie par un choix, et rend possible ce
qu'une saisie interdit — dire quelle machine on vise, la sonder, et garder ce
qu'on y a trouvé.

DEUX MAGASINS, ET C'EST VOULU. L'inventaire est une DONNÉE de site : il vit
dans le fichier de configuration privé, seul des trois fusionnés par
`ConfigFile` à être gitignored, écrit en 0600 atomique. La cible RETENUE est
une préférence d'écran, et vit avec les autres préférences. Les confondre
ferait disparaître un inventaire entier le jour où quelqu'un remet ses
préférences à zéro.

PAS DE BOOLÉEN « prod ». Le mot recouvre deux questions distinctes : « ce
service est-il exposé ? », qui décide des workers et du proxy, et « quelle
posture a la machine ? », qui décide du chemin d'installation. Une cible
répond à la seconde par `path`, et à la première par `domain` : non vide, le
service est servi derrière nginx. Un champ, une vérité.

Toute valeur est VALIDÉE avant d'être écrite : elle finira dans une ligne de
commande. Un chemin distant portant un point-virgule n'y arrivera pas.
"""
from __future__ import annotations

import json
import os
import re

from script import lib_valid as valid

# Le MODULE, pas la constante : `CONFIG_OVERRIDE_PRIVATE_FILE` importée par
# valeur figerait le chemin à l'import, et les tests — qui le déplacent dans
# un répertoire temporaire — écriraient dans le vrai fichier de l'utilisateur.
from script.config import config_file as config_module
from script.config.config_file import ConfigFile
from script.lib_valid import (  # noqa: F401
    HOST_RE,
    NAME_RE,
    SERVER_RE,
    ValidationError,
)
from script.remote import host_probe

# La clé de section, dans les trois fichiers de configuration.
CONFIG_KEY = "deploy_targets"

# Ce que la cible désigne. Un seul genre aujourd'hui, et le champ existe
# quand même : une cible sans genre ne se distinguerait pas d'une autre le
# jour où un second transport arrive, et il faudrait alors deviner d'après
# les champs présents.
KIND_SSH = "erplibre-ssh"
KINDS = (KIND_SSH,)

# Ce que le Makefile de déploiement pose déjà comme défaut. Le répéter ici
# n'est pas une duplication mais un CONTRAT : une cible qui omet le chemin se
# comporte exactement comme la saisie qu'elle remplace.
DEFAULT_PATH = "~/erplibre_deploy_2"

DEFAULTS = {
    "name": "",
    "kind": KIND_SSH,
    "target": "",
    "jump": "",
    # Le port est une CHAÎNE, et vide par défaut. « 22 » écrit en dur
    # imposerait le port à un alias de ~/.ssh/config qui en déclare un autre ;
    # vide, ssh et le Makefile gardent chacun le leur.
    "port": "",
    "identity": "",
    "path": DEFAULT_PATH,
    # Non vide ≡ le service est servi derrière nginx, avec un certificat.
    "domain": "",
    "admin_email": "",
    # Ce que la sonde a constaté, et non ce que quelqu'un a saisi. Vide tant
    # que personne n'a sondé — ce qui n'est pas « en panne », et l'écran doit
    # pouvoir dire la différence.
    "verdict": "",
    "version": "",
    "sudo": "",
    "last_probe": "",
}

# Horodatage UTC à la seconde. Assez précis pour dire « sondée il y a
# longtemps », assez grossier pour rester lisible dans un fichier relu.
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
# Un courriel finit dans une ligne de commande passée à certbot : ce qui
# n'est ni lettre, ni chiffre, ni `.+_%-` autour d'un « @ » est refusé.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9][A-Za-z0-9.-]*$")


def with_defaults(target: dict) -> dict:
    """Copie de la cible où chaque clé connue a une valeur."""
    full = dict(DEFAULTS)
    full.update({k: v for k, v in target.items() if v is not None})
    return full


def load_all(config=None) -> list[dict]:
    """Toutes les cibles, dans l'ordre de fusion. Jamais None.

    Une entrée sans nom est écartée : elle serait impossible à choisir, à
    modifier et à supprimer, et resterait là sans que rien ne la nomme.
    """
    cfg = config or ConfigFile()
    data = cfg.get_config(CONFIG_KEY)
    if not isinstance(data, list):
        return []
    return [t for t in data if isinstance(t, dict) and t.get("name")]


def load(name: str, config=None) -> dict | None:
    """La cible `name`, complétée par les défauts, ou None."""
    for target in load_all(config):
        if target.get("name") == name:
            return with_defaults(target)
    return None


def names(config=None) -> list[str]:
    return [t["name"] for t in load_all(config)]


def _load_private() -> dict:
    """Contenu brut du fichier privé, {} s'il est absent ou illisible."""
    path = config_module.CONFIG_OVERRIDE_PRIVATE_FILE
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def private_targets() -> list[dict]:
    """Les cibles du fichier privé SEULES.

    L'écriture doit repartir de cette liste et non de la fusion : réécrire la
    fusion recopierait dans le fichier privé les cibles venues du fichier
    partagé, qui se retrouveraient alors en double à la lecture suivante (la
    fusion étend les listes, elle ne les déduplique pas).
    """
    data = _load_private().get(CONFIG_KEY)
    return (
        [t for t in data if isinstance(t, dict)]
        if isinstance(data, list)
        else []
    )


def save(target: dict, config=None) -> dict:
    """Valide puis écrit la cible dans le fichier privé.

    Rend la cible normalisée. Lève ValidationError si quelque chose ne va
    pas — AVANT d'écrire quoi que ce soit, pour qu'un refus laisse
    l'inventaire tel qu'il était.
    """
    clean = validate(target)
    cfg = config or ConfigFile()
    targets = [t for t in private_targets() if t.get("name") != clean["name"]]
    targets.append(clean)
    cfg.set_config_value([CONFIG_KEY], targets)
    return clean


def delete(name: str, config=None) -> bool:
    """Retire la cible du fichier privé.

    Rend False si elle n'y était pas — une cible venue du fichier partagé
    n'est pas supprimable d'ici, et le dire vaut mieux que de faire semblant.
    """
    targets = private_targets()
    kept = [t for t in targets if t.get("name") != name]
    if len(kept) == len(targets):
        return False
    cfg = config or ConfigFile()
    cfg.set_config_value([CONFIG_KEY], kept)
    return True


def validate(target: dict) -> dict:
    """Cible normalisée, ou ValidationError."""
    full = with_defaults(target)

    valid.text(full, "name", "Nom de cible", pattern=NAME_RE)

    kind = str(full.get("kind") or "").strip()
    if kind not in KINDS:
        raise ValidationError(
            f"Genre de cible inconnu : « {kind} »."
            f" Connus : {', '.join(KINDS)}."
        )
    full["kind"] = kind

    valid.text(full, "target", "Adresse de la cible", pattern=SERVER_RE)
    valid.text(full, "jump", "Rebond SSH", required=False, pattern=SERVER_RE)
    _port(full)
    valid.path(full, "identity", "Clé privée", required=False)
    valid.path(full, "path", "Chemin distant")
    # Le domaine est un nom d'hôte SEUL : « compte@domaine » finirait dans la
    # requête de certificat et dans la configuration nginx.
    valid.text(full, "domain", "Domaine", required=False, pattern=HOST_RE)
    valid.text(
        full,
        "admin_email",
        "Courriel d'administration",
        required=False,
        pattern=_EMAIL_RE,
    )

    _constate(full)
    return full


def _port(full: dict) -> None:
    """Le port reste une CHAÎNE, et le vide reste vide.

    Le valider comme un entier puis le rendre tel quel ferait écrire « 22 »
    là où l'utilisateur n'avait rien mis, et imposerait ce port à un alias
    qui en déclare un autre.
    """
    brut = str(full.get("port") or "").strip()
    if not brut:
        full["port"] = ""
        return
    valid.port({"port": brut}, "port", "Port SSH")
    full["port"] = brut


def _constate(full: dict) -> None:
    """Ce que la sonde a déposé : contrôlé, mais jamais exigé.

    Une cible qu'on vient d'écrire n'a pas encore été sondée, et une valeur
    hors vocabulaire trahit un fichier modifié à la main — la refuser vaut
    mieux que de l'afficher comme un verdict.
    """
    verdict = str(full.get("verdict") or "").strip()
    if verdict and verdict not in host_probe.VERDICTS:
        raise ValidationError(
            f"Verdict inconnu : « {verdict} »."
            f" Connus : {', '.join(host_probe.VERDICTS)}."
        )
    full["verdict"] = verdict

    valid.text(full, "version", "Version constatée", required=False)

    sudo = str(full.get("sudo") or "").strip()
    if sudo and sudo != "sudo":
        raise ValidationError(f"Préfixe d'élévation inattendu : « {sudo} ».")
    full["sudo"] = "sudo " if sudo else ""

    date = str(full.get("last_probe") or "").strip()
    if date and not _ISO_RE.match(date):
        raise ValidationError(
            f"Date de sonde refusée : « {date} »."
            " Attendu 2026-01-31T14:05:00Z."
        )
    full["last_probe"] = date


def fiche(target: dict) -> dict:
    """La fiche d'hôte que `appliance_ssh` consomme, tirée de la cible.

    Les deux formats ne se confondent pas : la cible est ce qu'on écrit et
    relit, la fiche est ce qu'on donne au transport. Les champs qui ne
    servent qu'à l'écran — le nom, le domaine, la date — n'ont rien à faire
    dans une ligne ssh.
    """
    full = with_defaults(target)
    return {
        "name": full["name"],
        "target": full["target"],
        "jump": full["jump"],
        "port": full["port"],
        "identity": full["identity"],
        "sudo": full["sudo"],
        "version": full["version"],
    }


def make_vars(target: dict, resolve=None) -> dict:
    """Les variables SSH_* que le Makefile attend, tirées de la cible.

    LE COMPTE EST SÉPARÉ DE L'ADRESSE. Le Makefile recompose
    « $(SSH_USER)@$(SSH_HOST) » : lui passer « compte@machine » comme hôte
    produit « erplibre@compte@machine », que ssh refuse. Une cible qui porte
    son compte est donc COUPÉE ici, une fois, plutôt que de laisser onze
    verbes se tromper chacun de leur côté.

    `resolve` sert à retrouver le compte d'un alias de ~/.ssh/config, que le
    Makefile ne consulte pas. Absent, la variable est omise et le défaut du
    Makefile s'applique — ce qui est le comportement d'avant.
    """
    full = with_defaults(target)
    adresse = full["target"]
    compte = ""
    if "@" in adresse:
        compte, adresse = adresse.rsplit("@", 1)
    port = full["port"]
    identity = full["identity"]
    if not compte and resolve:
        vu = resolve(adresse) or {}
        compte = vu.get("user") or ""
        port = port or vu.get("port") or ""
        identity = identity or vu.get("identity") or ""
    variables = {
        "SSH_HOST": adresse,
        "SSH_USER": compte,
        "SSH_PORT": port,
        "SSH_KEY": identity,
        "SSH_PATH": full["path"],
        "SSH_JUMP": full["jump"],
    }
    return {k: v for k, v in variables.items() if v}
