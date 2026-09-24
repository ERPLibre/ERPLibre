#!/usr/bin/env python3
# © 2026 TechnoLibre (http://www.technolibre.ca)
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl)
"""Ce qu'un serveur ANNONCE savoir faire, et ce qu'un gpt exige de lui.

La lecture des capacités a trois degrés d'honnêteté, et les confondre est le
mode de défaillance qui compte. AUTOMATIQUE — Ollama, LocalAI par sa
compatibilité Ollama, llama.cpp — publie ses capacités, sa longueur de
contexte et son nombre de paramètres : la lecture est un fait. PARTIEL — LM
Studio donne le contexte et la vision mais aucun drapeau d'outils, KoboldCpp
des booléens à l'échelle du serveur mais aucun contexte. MUET — vLLM,
text-generation-webui, Jan, Open WebUI, TabbyAPI, GPT4All et l'API OpenAI
distante, dont le schéma de modèle ne porte aucun champ de capacité : TOUT
vaut alors `None`, et c'est le cas du point de terminaison le plus courant.

Un champ vaut `None` tant qu'il n'a pas été LU dans une réponse. Une valeur
tirée du NOM d'un modèle est un indice et non une lecture : elle est remplie,
et son nom entre dans `estimated`.

D'où la règle que `match` applique : **l'inconnu ne grise jamais**. Seule une
exigence contredite par une valeur réellement lue rend « no ». Un champ vide
rend « unknown » : l'entrée reste lançable, et l'exigence se répète par son
nom au moment de l'envoi. Une valeur estimée ne grise pas davantage —
refuser un montage qui fonctionne sur une devinette est un refus que
l'utilisateur ne peut pas discuter. Griser sur l'inconnu viderait le
catalogue devant un serveur générique compatible OpenAI, qui n'annonce rien.

`hosting` est la seule exigence qui ne peut jamais être inconnue : elle ne
demande aucune requête, donc elle peut griser dès le premier contact. Elle
porte deux pièges. `ipaddress` rapporte la boucle locale comme privée AUSSI,
d'où une échelle qui teste `is_loopback` d'abord, `is_private` ensuite. Et
`ip_address` lève sur un nom d'hôte : un nom se résout d'abord, et un nom qui
ne résout pas se lit comme `global`, la lecture pessimiste, jamais comme
satisfait.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
import urllib.request
from dataclasses import dataclass, replace

from script.todo.assistant.fingerprint import Fingerprint

# Les six clés d'exigence, dans l'ordre où une raison se rend. `hosting`
# d'abord parce que c'est la seule qui grise sans avoir parlé au serveur.
REQUIREMENT_KEYS = (
    "hosting",
    "context_window",
    "parameters",
    "tool_calling",
    "vision",
    "json_output",
)

# L'échelle d'hébergement est ORDONNÉE : loopback satisfait lan, qui satisfait
# any. Une seule clé exprime « doit être local » ET « pas de tiers », qui sont
# deux demandes différentes — une machine du réseau local n'est ni l'une ni
# l'autre.
HOSTING_ORDER = ("loopback", "lan", "global")
ANY_HOSTING = "any"
DEFAULT_HOSTING = "lan"

# Les raisons sont des CLÉS i18n, et `t()` rend une clé absente inchangée : une
# clé oubliée s'affiche en anglais correct. Les `%s` se remplissent par
# l'appelant, qui tient déjà `requires` et les capacités.
REASON_HOSTING = "asks for a local server, this one is %s"
REASON_CONTEXT = "asks for %s of context, this server announces %s"
REASON_PARAMETERS = "asks for %s B of parameters, this server announces %s B"
REASON_TOOLS = "asks for tool calling, this server does not announce it"
REASON_VISION = "asks for vision, this server does not announce it"
REASON_JSON = "asks for JSON output, this server does not announce it"

# La raison d'un « unknown » NOMME l'exigence qu'on n'a pas pu vérifier :
# l'envoi la répète, et « une exigence non vérifiée » sans son nom n'apprend
# rien. Les six chaînes sont écrites une par une pour qu'un balayage des clés
# i18n les trouve, là où une clé assemblée à l'exécution serait invisible.
REASON_UNCHECKED = {
    "hosting": "hosting could not be checked",
    "context_window": "context_window could not be checked on this server",
    "parameters": "parameters could not be checked on this server",
    "tool_calling": "tool_calling could not be checked on this server",
    "vision": "vision could not be checked on this server",
    "json_output": "json_output could not be checked on this server",
}
REASON_UNCHECKED_OTHER = "a requirement could not be checked"

# Le corps d'une réponse de capacités pèse quelques kilo-octets. Le plafond
# existe pour qu'un mauvais chemin — une page d'administration, un flux qui ne
# finit pas — ne puisse pas remplir la mémoire.
BODY_LIMIT = 1_000_000

# La lecture arrive après que l'utilisateur a désigné un serveur : elle peut
# attendre plus longtemps qu'un balayage, et charger un modèle prend du temps.
BUDGET = 3.0

# Un nombre suivi de « b » dans un texte : « 7.2B » d'un serveur, « 7b » d'un
# nom de modèle. La barrière devant le nombre écarte le numéro de version d'un
# nom comme « modele2.5:7b », où le chiffre voulu est le dernier.
PARAMETER_SIZE = re.compile(r"(?<![\d.])(\d+(?:[.,]\d+)?)\s*[bB](?!\w)")

# Deux noms coexistent selon la version de llama.cpp pour le même drapeau.
LLAMACPP_TOOL_FLAGS = ("supports_tools", "supports_tool_calls")

# L'énumération d'Ollama nomme un modèle qui lit une image de deux façons.
# N'en reconnaître qu'une rendrait « pas de vision » à un modèle qui en a, et
# griserait un gpt sur un détail de vocabulaire.
VISION_MARKS = ("vision", "image")


@dataclass(frozen=True)
class Capabilities:
    """Ce que le serveur a annoncé, champ par champ.

    Chaque champ vaut `None` quand il n'a pas été lu dans une réponse — jamais
    `False`, qui serait une négation lue. `estimated` porte le nom des champs
    remplis par déduction plutôt que par lecture ; `match` les traite comme
    inconnus, et l'affichage les marque.
    """

    context_window: int | None = None
    parameters: float | None = None
    tool_calling: bool | None = None
    vision: bool | None = None
    json_output: bool | None = None
    estimated: frozenset[str] = frozenset()


# Ce qu'un serveur muet rend, et ce que rend un logiciel non reconnu.
NOTHING_ANNOUNCED = Capabilities()


def classify_hosting(host: str, *, resolve=None) -> str:
    """La classe d'hébergement de `host` : loopback, lan ou global.

    Rend toujours l'une des trois, et la plus pessimiste quand un nom porte
    plusieurs adresses : une destination n'est locale que si toutes ses
    adresses le sont.

    `resolve(host)` rend les adresses en chaînes et vaut `None` par défaut,
    résolu au résolveur du système. Un résolveur qui échoue, un nom qui ne
    résout pas, un hôte vide comptent pour `global` — la lecture pessimiste
    est la seule qui ne présente jamais un tiers comme local.
    """
    addresses = _addresses(host, resolve)
    if not addresses:
        return HOSTING_ORDER[-1]
    return HOSTING_ORDER[max(_rank_of_address(a) for a in addresses)]


def match(requires: dict, caps: Capabilities, hosting: str) -> tuple[str, str]:
    """L'appariement d'un gpt à un serveur : (verdict, clé de raison).

    Le verdict est « ok », « unknown » ou « no », et la raison une clé i18n,
    vide sur « ok ». Un « no » l'emporte sur un « unknown », et à verdict égal
    c'est la première exigence de `REQUIREMENT_KEYS` qui donne la raison.

    `requires["hosting"]` vaut `lan` en son absence : un gpt qui ne dit rien
    n'autorise pas pour autant un tiers. Les autres clés absentes ne sont pas
    des exigences. Une clé hors de l'ensemble fermé rend « unknown » plutôt que
    d'être ignorée en silence.
    """
    requires = requires or {}
    verdicts = [
        _check(key, requires, caps, hosting)
        for key in _requirement_order(requires)
    ]
    for wanted in ("no", "unknown"):
        for verdict, reason in verdicts:
            if verdict == wanted:
                return verdict, reason
    return "ok", ""


def read(
    fingerprint: Fingerprint,
    host: str,
    port: int,
    *,
    http_post=None,
    http_get=None,
) -> Capabilities:
    """Les capacités du modèle reconnu par `fingerprint` sur `host:port`.

    Ne consulte de l'empreinte que `software`, qui choisit le lecteur, et
    `models`, dont le premier nom désigne le modèle interrogé. Ne lève jamais :
    un corps qui n'est pas du JSON, un statut autre que 200, un champ absent
    laissent le champ à `None`, parce qu'un menu qui plante sur une réponse
    inattendue est pire qu'un menu qui dit ne pas savoir.

    `http_get(host, port, path)` et `http_post(host, port, path, payload)`
    rendent `(statut, corps)` ou `None`, valent `None` par défaut et se
    résolvent au transport de ce module. Ce transport est le seul du paquet à
    émettre un POST : la découverte n'émet que des GET pour qu'un balayage ne
    puisse jamais déclencher une génération, alors que la lecture des capacités
    arrive après qu'un serveur a été désigné.
    """
    software = getattr(fingerprint, "software", "") or ""
    models = tuple(getattr(fingerprint, "models", ()) or ())
    # Muet et non reconnu se rendent pareil, et sans aucune requête : il n'y a
    # rien à demander à un serveur dont le schéma ne porte pas de capacité.
    if software in SILENT or software not in READERS:
        return NOTHING_ANNOUNCED
    caps = READERS[software](
        models,
        _getter(host, port, http_get),
        _poster(host, port, http_post),
    )
    return _estimate_parameters(caps, models[0] if models else "")


def _addresses(host, resolve):
    """Les adresses de `host`, en chaînes ; vide si rien ne se résout."""
    host = _bare_host(host)
    if not host:
        return []
    if _is_address(host):
        return [host]
    if resolve is None:
        resolve = _resolve_addresses
    try:
        return [str(a) for a in resolve(host) or ()]
    except Exception:
        # Un résolveur peut lever autre chose qu'une erreur système : celui du
        # système lève `OSError`, un résolveur injecté ce qu'il veut. Toutes
        # ces issues disent la même chose, que le nom n'est pas résolu.
        return []


def _bare_host(host):
    """L'hôte débarrassé de ce qui empêche `ip_address` de le lire.

    Les crochets d'une adresse IPv6 littérale et l'identifiant de zone qu'un
    résolveur accroche à une adresse de lien local font tous deux lever
    `ip_address`, alors que l'adresse elle-même est parfaitement classable.
    """
    host = (host or "").strip()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    return host.split("%", 1)[0].strip()


def _is_address(text):
    try:
        ipaddress.ip_address(text)
    except ValueError:
        return False
    return True


def _resolve_addresses(host):
    """Les adresses de `host` selon le résolveur du système."""
    return [info[4][0] for info in socket.getaddrinfo(host, None)]


def _rank_of_address(text):
    """Le rang de `text` dans `HOSTING_ORDER`.

    La boucle locale est testée AVANT le privé : `ipaddress` rapporte
    127.0.0.1 comme privé aussi, et l'ordre inverse classerait la machine même
    comme du réseau local. Ce qui n'est ni l'un ni l'autre — une plage de
    transition d'opérateur autant qu'une adresse publique — est global : le
    rang le plus haut est celui qui ne promet rien.
    """
    try:
        address = ipaddress.ip_address(_bare_host(text))
    except ValueError:
        return len(HOSTING_ORDER) - 1
    if address.is_loopback:
        return 0
    if address.is_private:
        return 1
    return len(HOSTING_ORDER) - 1


def _requirement_order(requires):
    """Les clés à vérifier : l'ensemble fermé, puis ce qu'il ne couvre pas."""
    extra = sorted(k for k in requires if k not in REQUIREMENT_KEYS)
    return REQUIREMENT_KEYS + tuple(extra)


def _check(key, requires, caps, hosting):
    """Le verdict d'UNE exigence : (verdict, clé de raison).

    Deux clés se comportent à part. `hosting` est vérifié même absent, sur son
    défaut. Toute autre clé absente n'est pas une exigence et rend « ok », ce
    qui distingue « ce gpt ne demande rien là-dessus » de « le serveur ne dit
    rien là-dessus », qui rend « unknown ».
    """
    if key == "hosting":
        return _check_hosting(requires.get(key, DEFAULT_HOSTING), hosting)
    if key not in requires:
        return "ok", ""
    if key == "context_window":
        return _check_number(key, requires[key], caps, REASON_CONTEXT)
    if key == "parameters":
        return _check_number(key, requires[key], caps, REASON_PARAMETERS)
    if key == "tool_calling":
        return _check_flag(key, requires[key], caps, REASON_TOOLS)
    if key == "vision":
        return _check_flag(key, requires[key], caps, REASON_VISION)
    if key == "json_output":
        return _check_flag(key, requires[key], caps, REASON_JSON)
    return "unknown", REASON_UNCHECKED_OTHER


def _check_hosting(required, actual):
    """L'échelle d'hébergement, la seule qui grise sans requête.

    Un barreau que l'échelle ne connaît pas rend « unknown » : ce n'est pas une
    contradiction, et griser un gpt sur une faute de frappe dans son en-tête
    serait un refus sans recours.
    """
    wanted = _hosting_rank(required)
    reached = _hosting_rank(actual)
    if wanted is None or reached is None:
        return "unknown", REASON_UNCHECKED["hosting"]
    if reached > wanted:
        return "no", REASON_HOSTING
    return "ok", ""


def _hosting_rank(value):
    """Le rang d'un barreau, `any` au plus permissif ; None si inconnu."""
    if value == ANY_HOSTING:
        return len(HOSTING_ORDER) - 1
    if value in HOSTING_ORDER:
        return HOSTING_ORDER.index(value)
    return None


def _check_number(key, required, caps, reason):
    """Un seuil : satisfait quand la valeur LUE atteint ce qui est demandé."""
    try:
        wanted = float(required)
    except (TypeError, ValueError):
        return "unknown", REASON_UNCHECKED[key]
    announced = getattr(caps, key)
    if announced is None or key in caps.estimated:
        return "unknown", REASON_UNCHECKED[key]
    if float(announced) < wanted:
        return "no", reason
    return "ok", ""


def _check_flag(key, required, caps, reason):
    """Un booléen. Un gpt qui n'en a pas besoin est satisfait par tout."""
    if not required:
        return "ok", ""
    announced = getattr(caps, key)
    if announced is None or key in caps.estimated:
        return "unknown", REASON_UNCHECKED[key]
    if not announced:
        return "no", reason
    return "ok", ""


def _authority(host, port):
    """`hôte:port`, l'hôte entre crochets quand c'est une adresse IPv6."""
    host = _bare_host(host)
    if ":" in host:
        host = f"[{host}]"
    return f"{host}:{port}"


def _http(host, port, path, payload=None):
    """`(statut, corps)` d'une requête, ou `None` si elle n'aboutit pas.

    N'envoie AUCUN en-tête d'autorisation : un serveur qui exige une clé
    n'annonce rien plutôt que de s'en voir présenter une, une clé se
    configurant contre un serveur qu'on a nommé. Le corps est lu jusqu'au
    plafond, jamais jusqu'à la fin.
    """
    url = f"http://{_authority(host, port)}{path}"
    data = None
    headers = {}
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=BUDGET) as answer:
            return answer.status, answer.read(BODY_LIMIT)
    except Exception:
        # Une socket refusée, un délai dépassé, un statut d'erreur, un corps
        # coupé : la lecture n'a rien appris, et le champ reste vide.
        return None


def _getter(host, port, http_get):
    """Un lecteur de chemin, qui rend le corps JSON d'un GET ou `None`."""

    def fetch(path):
        call = http_get if http_get is not None else _http
        return _json(call(host, port, path))

    return fetch


def _poster(host, port, http_post):
    """Un lecteur de chemin, qui rend le corps JSON d'un POST ou `None`."""

    def fetch(path, payload):
        if http_post is not None:
            return _json(http_post(host, port, path, payload))
        return _json(_http(host, port, path, payload))

    return fetch


def _json(answer):
    """Le dictionnaire d'une réponse 200, `None` pour tout le reste.

    Un statut de démarrage ou un défi d'authentification est un serveur vivant,
    mais il n'annonce aucune capacité ; du HTML et un corps tronqué non plus.
    """
    if not answer:
        return None
    status, body = answer
    if status != 200:
        return None
    if isinstance(body, (bytes, bytearray)):
        body = bytes(body).decode("utf-8", "replace")
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _integer(value):
    """La valeur en entier positif, `None` si ce n'en est pas un.

    Un booléen est écarté avant tout : `isinstance(True, int)` est vrai, et un
    drapeau lu comme la longueur 1 serait une capacité inventée. Un zéro ou un
    négatif n'annonce rien non plus.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value) if value > 0 else None
    if isinstance(value, str):
        try:
            return _integer(int(value.strip()))
        except ValueError:
            return None
    return None


def _billions(count):
    """Un nombre de paramètres COMPTÉ, rendu en milliards."""
    value = _integer(count)
    return None if value is None else round(value / 1e9, 2)


def _billions_from_text(text):
    """Le nombre de milliards écrit dans un texte, `None` s'il n'y en a pas."""
    if not isinstance(text, str):
        return None
    found = PARAMETER_SIZE.search(text)
    if not found:
        return None
    try:
        return float(found.group(1).replace(",", "."))
    except ValueError:
        return None


def _parameter_size(details):
    """Le `parameter_size` d'un bloc de détails, en milliards."""
    if not isinstance(details, dict):
        return None
    return _billions_from_text(details.get("parameter_size"))


def _entries(body, field):
    """La liste de dictionnaires que `body[field]` porte, sinon vide."""
    if not isinstance(body, dict):
        return []
    return [e for e in body.get(field) or () if isinstance(e, dict)]


def _entry_named(entries, name, fields):
    """L'entrée que le serveur publie pour `name`, sinon la première.

    Un serveur qui tient plusieurs modèles chargés les publie dans l'ordre
    qu'il veut : chercher le nom d'abord évite de lire le contexte du voisin.
    """
    for entry in entries:
        if name and any(entry.get(field) == name for field in fields):
            return entry
    return entries[0] if entries else None


def _first_bool(mapping, fields):
    """Le premier de `fields` que `mapping` publie en booléen, sinon `None`."""
    if not isinstance(mapping, dict):
        return None
    for field in fields:
        if isinstance(mapping.get(field), bool):
            return mapping[field]
    return None


def _context_from_model_info(info):
    """La longueur de contexte de `model_info`, `None` si elle n'y est pas.

    La clé porte le nom de l'architecture, que `general.architecture` donne.
    Le repli sur n'importe quelle clé qui finit par « .context_length » couvre
    un serveur qui nomme l'architecture autrement dans les deux champs.
    """
    if not isinstance(info, dict):
        return None
    architecture = info.get("general.architecture")
    if isinstance(architecture, str):
        found = _integer(info.get(f"{architecture}.context_length"))
        if found is not None:
            return found
    for key, value in info.items():
        if isinstance(key, str) and key.endswith(".context_length"):
            found = _integer(value)
            if found is not None:
                return found
    return None


def _read_ollama(models, get, post):
    """Ollama, et LocalAI qui émule son API native.

    `POST /api/show` porte l'énumération de capacités et le bloc `model_info`
    d'où sortent le contexte et le compte de paramètres. `GET /api/tags` est le
    repli sur le `parameter_size` que le serveur publie déjà pour le modèle :
    c'est une lecture, pas une déduction, donc elle n'est pas estimée.
    """
    name = models[0] if models else ""
    context = parameters = tools = vision = None
    shown = post("/api/show", {"model": name}) if name else None
    if isinstance(shown, dict):
        announced = shown.get("capabilities")
        if isinstance(announced, list):
            tools = "tools" in announced
            vision = any(mark in announced for mark in VISION_MARKS)
        info = shown.get("model_info")
        context = _context_from_model_info(info)
        if isinstance(info, dict):
            parameters = _billions(info.get("general.parameter_count"))
        if parameters is None:
            parameters = _parameter_size(shown.get("details"))
    if parameters is None:
        entries = _entries(get("/api/tags"), "models")
        entry = _entry_named(entries, name, ("name", "model"))
        parameters = _parameter_size(entry.get("details")) if entry else None
    return Capabilities(
        context_window=context,
        parameters=parameters,
        tool_calling=tools,
        vision=vision,
    )


def _read_llamacpp(models, get, post):
    """llama.cpp : les drapeaux dans `/props`, les nombres dans `/v1/models`.

    `/props` porte les capacités du gabarit de conversation, `/v1/models` les
    nombres du modèle chargé : deux corps pour une seule lecture.
    """
    props = get("/props")
    tools = _first_bool(
        props.get("chat_template_caps") if isinstance(props, dict) else None,
        LLAMACPP_TOOL_FLAGS,
    )
    vision = _first_bool(
        props.get("modalities") if isinstance(props, dict) else None,
        ("vision",),
    )
    context = parameters = None
    entries = _entries(get("/v1/models"), "data")
    entry = _entry_named(entries, models[0] if models else "", ("id",))
    meta = entry.get("meta") if entry else None
    if isinstance(meta, dict):
        context = _integer(meta.get("n_ctx_train"))
        parameters = _billions(meta.get("n_params"))
    return Capabilities(
        context_window=context,
        parameters=parameters,
        tool_calling=tools,
        vision=vision,
    )


def _read_lmstudio(models, get, post):
    """LM Studio : le contexte et la vision, jamais les outils.

    Le serveur ne publie aucun drapeau d'outils. `tool_calling` reste donc
    vide, et non `False` : un `False` inventé griserait un serveur qui appelle
    des outils en vrai.
    """
    entries = _entries(get("/api/v0/models"), "data")
    entry = _entry_named(entries, models[0] if models else "", ("id",))
    if entry is None:
        return NOTHING_ANNOUNCED
    kind = entry.get("type")
    return Capabilities(
        context_window=_integer(entry.get("max_context_length")),
        vision=(kind == "vlm") if isinstance(kind, str) else None,
    )


def _read_koboldcpp(models, get, post):
    """KoboldCpp : des booléens à l'échelle du serveur, aucun contexte."""
    return Capabilities(
        vision=_first_bool(get("/api/extra/version"), ("vision",))
    )


def _estimate_parameters(caps, name):
    """Le nombre de paramètres deviné dans le NOM du modèle, marqué estimé.

    Ne remplit que ce qui n'a pas été lu, et n'existe que pour `parameters` :
    un nom de modèle porte souvent sa taille, jamais sa longueur de contexte,
    qui reste donc vide plutôt que devinée. Le nom entre dans `estimated`, ce
    qui empêche `match` d'en tirer un refus.
    """
    if caps.parameters is not None:
        return caps
    guessed = _billions_from_text(name)
    if guessed is None:
        return caps
    return replace(
        caps,
        parameters=guessed,
        estimated=caps.estimated | {"parameters"},
    )


# Un lecteur par famille, tous de la même forme `(models, get, post)`, ce qui
# rend la table lisible comme la liste des serveurs qui annoncent quelque
# chose. Ceux qui n'y sont pas n'annoncent rien.
READERS = {
    "ollama": _read_ollama,
    "localai": _read_ollama,
    "llamacpp": _read_llamacpp,
    "lmstudio": _read_lmstudio,
    "koboldcpp": _read_koboldcpp,
}

# Reconnus, et muets : leur schéma de modèle ne porte aucun champ de capacité.
# L'API OpenAI distante en fait partie, ce qui est la raison d'être de la règle
# « l'inconnu ne grise jamais » — sinon le catalogue serait vide sur le chemin
# de repli.
SILENT = frozenset(
    {
        "vllm",
        "textgen_webui",
        "jan",
        "open_webui",
        "tabbyapi",
        "gpt4all",
        "openai",
    }
)
