#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Les serveurs LLM retenus : une poignée opaque, une adresse qui ne sort pas.

Chaque serveur porte une POIGNÉE — « server-1 » — attribuée par son RANG au
chargement, et c'est la seule forme qui a le droit de circuler : `redacted`
est ce qui peut atteindre une invite, un argument de commande ou un fichier
que le dépôt suit. L'hôte, le port et le libellé servent à l'affichage du
menu et à la configuration privée, et s'arrêtent là.

La retenue est structurelle parce qu'elle ne peut pas être un filtre : le
détecteur du dépôt reconnaît les adresses, les courriels et les chemins de
compte, et rend une liste vide devant un nom d'hôte, un alias SSH ou un nom
de VM. Ce qu'aucun garde-fou ne voit passer ne doit pas être en position de
passer.

L'écriture passe par `set_config_value`, et par lui seul. Des trois fichiers
que la lecture fusionne, c'est le seul qui soit gitignored ; les deux autres
suivent le dépôt en amont, et ce qui vit sous `private/` devient public avec
lui sur un fork rendu public. Une seule section est écrite, sous le chemin de
clés « assistant › servers ».

N'est enregistré que ce que l'utilisateur a choisi de garder : ni date de
dernier contact, ni rapport de balayage, ni résultat négatif. La liste de qui
a répondu parmi les 254 adresses d'un /24 décrit des machines que personne
n'a désignées, là où un serveur retenu en désigne une seule, volontairement.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

# Le chemin de clés de la section, dans les fichiers de configuration.
CONFIG_KEYS = ("assistant", "servers")

HANDLE_PREFIX = "server-"

# La poignée d'un serveur qui n'a pas encore reçu de rang. Elle garde
# l'adresse dehors là où un repli sur le libellé l'y ferait entrer.
UNASSIGNED_HANDLE = f"{HANDLE_PREFIX}?"

# L'échelle d'hébergement, du plus contenu au plus exposé.
HOSTINGS = ("loopback", "lan", "global")

# La classe d'une valeur stockée qu'on ne reconnaît pas. Lire au plus
# prudent impose la confirmation la plus stricte au lieu de la lever.
UNKNOWN_HOSTING = "global"

# La famille sans racine `/v1`, réduite à ses lettres et ses chiffres.
OPEN_WEBUI = "openwebui"
OPEN_WEBUI_ROOT = "/api"
DEFAULT_ROOT = "/v1"

HTTPS_PORT = 443
MAX_PORT = 65535


@dataclass
class Server:
    """Un serveur retenu.

    `handle` vaut « server-N » et se rattribue à chaque chargement ;
    `label` est ce que l'utilisateur a tapé pour le nommer, et ne sert qu'à
    l'affichage. `secret_ref` est vide, ou « kdbx:<titre d'entrée> » : la
    clé elle-même reste dans le coffre, jamais ici.
    """

    handle: str
    label: str
    host: str
    port: int
    software: str
    model: str
    hosting: str
    secret_ref: str


def assign_handles(servers) -> list[Server]:
    """Les mêmes serveurs, chacun portant « server-N » selon son rang.

    Numérote à partir de 1, dans l'ordre de la liste reçue. Pure : rend de
    nouveaux objets et laisse intacts ceux qu'on lui donne.

    La poignée dérive de la seule position et jamais d'une valeur stockée :
    un fichier édité à la main ne peut donc produire ni deux « server-1 »,
    ni une poignée qui porterait un nom de machine.
    """
    return [
        replace(server, handle=f"{HANDLE_PREFIX}{rank}")
        for rank, server in enumerate(servers, 1)
    ]


def load(*, get_config=None) -> list[Server]:
    """Les serveurs enregistrés, poignées attribuées. Jamais None.

    `get_config` prend un chemin de clés et rend la valeur fusionnée des
    trois fichiers de configuration ; il vaut `ConfigFile().get_config_value`
    quand rien n'est injecté, résolu ici pour qu'un test n'ait aucun fichier
    réel à toucher.

    Rend une liste vide plutôt que de lever, dans les quatre cas où la
    configuration ne porte pas de section utilisable : l'accesseur lève
    `TypeError` quand la section est absente, `ValueError` sur un JSON
    abîmé, `OSError` sur un fichier illisible, et rend n'importe quel type
    sur un fichier édité à la main. Aucun n'est une raison d'empêcher le
    menu de s'ouvrir.

    Une entrée qui ne décrit pas un serveur est écartée seule : une ligne
    abîmée ne fait pas disparaître les suivantes.
    """
    if get_config is None:
        from script.config.config_file import ConfigFile

        get_config = ConfigFile().get_config_value
    try:
        raw = get_config(list(CONFIG_KEYS))
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        return []
    if not isinstance(raw, list):
        return []
    kept = [_from_dict(entry) for entry in raw]
    return assign_handles([server for server in kept if server is not None])


def save(servers, *, set_config=None) -> None:
    """Écrit la liste sous « assistant › servers », et rien d'autre.

    `set_config` prend un chemin de clés et une valeur ; il vaut
    `ConfigFile().set_config_value` quand rien n'est injecté. C'est le seul
    écrivain autorisé : il vise le seul des trois fichiers fusionnés qui
    soit gitignored, il fusionne au lieu d'écraser, et il écrit
    atomiquement par un temporaire en 0600 suivi d'un `os.replace`.

    La poignée n'est pas écrite : elle se rattribue au chargement, et un
    rang figé sur le disque survivrait à la suppression d'un voisin.
    """
    if set_config is None:
        from script.config.config_file import ConfigFile

        set_config = ConfigFile().set_config_value
    set_config(list(CONFIG_KEYS), [_as_dict(server) for server in servers])


def base_url(server) -> str:
    """La racine d'API à laquelle parler à ce serveur.

    Toutes les familles servent leur complétion sous `/v1`, sauf Open WebUI
    qui n'a PAS de racine `/v1` : la sienne vit sous `/api`, la complétion à
    `/api/chat/completions`, et elle exige un jeton Bearer. Une racine
    `/v1` pointée sur lui rend 404 à chaque envoi.

    Le schéma se déduit du port : 443 est du TLS, tout le reste du HTTP en
    clair, qui est ce qu'un serveur de modèle sert par défaut.
    """
    scheme = "https" if server.port == HTTPS_PORT else "http"
    root = (
        OPEN_WEBUI_ROOT
        if _family(server.software) == OPEN_WEBUI
        else DEFAULT_ROOT
    )
    return f"{scheme}://{server.host}:{server.port}{root}"


def redacted(server) -> str:
    """Ce que ce serveur a le droit de devenir dans une invite.

    Rend « server-1 (ollama) », ou la seule poignée quand le logiciel n'a
    pas été reconnu. La poignée et le nom du logiciel ne désignent personne.

    L'hôte, le port et le libellé n'en sortent jamais : le libellé est ce
    que l'opérateur a tapé, donc un alias ou un nom de machine aussi souvent
    qu'autre chose. Un serveur sans rang rend `UNASSIGNED_HANDLE` plutôt que
    de combler le trou avec son adresse.
    """
    handle = server.handle or UNASSIGNED_HANDLE
    software = _text(server.software)
    return f"{handle} ({software})" if software else handle


def _family(software) -> str:
    """Le nom d'un logiciel réduit à ses lettres et ses chiffres, en bas de
    casse.

    L'échelle de reconnaissance nomme « Open WebUI » ; l'espace, le tiret et
    la casse varient d'une source à l'autre sans changer la famille, et
    comparer les chaînes brutes ferait dépendre la racine d'API d'un tiret.
    """
    return "".join(c for c in (software or "").lower() if c.isalnum())


def _from_dict(entry):
    """Un serveur lu depuis la configuration, ou None si l'entrée n'en
    décrit pas un.

    Exige un hôte et un port utilisables — sans eux il n'y a rien à
    joindre — et se contente du reste tel qu'il vient. La poignée stockée
    est IGNORÉE : elle se rattribue par le rang.

    Un libellé absent retombe sur l'hôte, comme la saisie du menu le fait
    déjà : le libellé ne sert qu'à l'affichage, où l'adresse a le droit de
    paraître.
    """
    if not isinstance(entry, dict):
        return None
    host = _text(entry.get("host"))
    port = _port(entry.get("port"))
    if not host or port is None:
        return None
    return Server(
        handle="",
        label=_text(entry.get("label")) or host,
        host=host,
        port=port,
        software=_text(entry.get("software")),
        model=_text(entry.get("model")),
        hosting=_hosting(entry.get("hosting")),
        secret_ref=_text(entry.get("secret_ref")),
    )


def _as_dict(server) -> dict:
    """L'entrée écrite pour un serveur : ce qui a été choisi, rien de plus.

    Sept champs, tous fournis par l'utilisateur ou par la reconnaissance du
    serveur qu'il a désigné. Aucun horodatage, aucune trace de contact : ce
    fichier dit ce qu'on garde, pas ce qu'on a vu.
    """
    return {
        "label": server.label,
        "host": server.host,
        "port": server.port,
        "software": server.software,
        "model": server.model,
        "hosting": server.hosting,
        "secret_ref": server.secret_ref,
    }


def _text(value) -> str:
    """La valeur quand c'est une chaîne, sans ses espaces de bord ; sinon "".

    Une valeur d'un autre type est jetée plutôt que passée par `str()` :
    la représentation d'un dictionnaire ou d'une liste entrerait dans un
    libellé et de là dans l'affichage.
    """
    return value.strip() if isinstance(value, str) else ""


def _port(value):
    """Le numéro de port, ou None quand la valeur n'en est pas un.

    `bool` est un `int` pour Python : sans le refus explicite, `true`
    deviendrait le port 1. Une chaîne de chiffres est acceptée parce qu'un
    fichier de configuration édité à la main en porte volontiers une.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            return None
        value = int(value)
    if not isinstance(value, int):
        return None
    return value if 1 <= value <= MAX_PORT else None


def _hosting(value) -> str:
    """La classe d'hébergement stockée, « global » si elle n'est pas connue.

    La lecture est pessimiste : une valeur absente ou abîmée vaut tiers, ce
    qui impose au premier envoi la confirmation la plus stricte au lieu de
    la lever.
    """
    text = _text(value)
    return text if text in HOSTINGS else UNKNOWN_HOSTING
